"""Price feeds: AMFI mutual-fund NAVs, stock prices, NPS NAVs.

All fetchers fail soft (return {} / None) so the app keeps working offline
with last-known or manual prices.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote, urlparse

import requests

import config
import netlog

AMFI_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"


class Offline(Exception):
    """Raised instead of opening a connection while offline mode is on."""


def _get(url, timeout):
    """Fetch a URL, but only one the app is allowed to contact, and log it.

    Every outbound call goes through here so the log in the app is the whole
    truth rather than a sample, and so offline mode is a fact about the code
    rather than a promise in the UI.
    """
    host = urlparse(url).hostname or ""
    purpose = netlog.purpose_for(host)
    if not purpose:
        netlog.record(host, "not on the allowed list", "refused")
        raise Offline("This app does not contact %s." % host)
    if config.offline():
        netlog.record(host, purpose, "blocked", "offline mode is on")
        raise Offline("Offline mode is on, so nothing was fetched.")
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        netlog.record(host, purpose, "failed", str(exc))
        raise
    netlog.record(host, purpose, "ok", "%d bytes" % len(resp.content))
    return resp


def parse_amfi_dump(text):
    """Parse AMFI's NAVAll.txt.

    Layout is semicolon-separated:
      Scheme Code;ISIN Div Payout/Growth;ISIN Div Reinvestment;Scheme Name;NAV;Date

    Both ISIN columns are kept so a CAS -- which identifies funds by ISIN and
    never by AMFI code -- can be resolved to the code that NAV refresh needs.
    """
    navs, by_isin = {}, {}
    for line in text.splitlines():
        parts = line.split(";")
        if len(parts) < 6 or not parts[0].strip().isdigit():
            continue
        code, isin1, isin2, name, nav, nav_date = [p.strip() for p in parts[:6]]
        try:
            nav_f = float(nav)
            d = datetime.strptime(nav_date, "%d-%b-%Y").date()
        except ValueError:
            continue
        navs[code] = {"name": name, "nav": nav_f, "date": d}
        for isin in (isin1, isin2):
            if isin and isin.upper() not in ("N.A.", "NA", "-"):
                by_isin[isin.upper()] = code
    return navs, by_isin


def fetch_amfi(timeout=30):
    """Download today's dump once and return both views of it.

    ({scheme_code: {"name", "nav", "date"}}, {ISIN: scheme_code}). The file
    is several megabytes, so a caller that wants both -- a price refresh that
    also has to resolve ISINs -- should not fetch it twice.
    """
    try:
        resp = _get(AMFI_NAV_URL, timeout)
    except (requests.RequestException, Offline):
        return {}, {}
    return parse_amfi_dump(resp.text)


def fetch_amfi_navs(timeout=30):
    """{scheme_code: {"name": str, "nav": float, "date": date}}."""
    return fetch_amfi(timeout)[0]


def fetch_amfi_isin_index(timeout=30):
    """{ISIN: AMFI scheme code}, so CAS holdings can price themselves."""
    return fetch_amfi(timeout)[1]


def search_amfi(navs, query, limit=20):
    q = query.lower()
    hits = [(code, info) for code, info in navs.items()
            if q in info["name"].lower()]
    return hits[:limit]


CHART_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/"
             "{symbol}?range=5d&interval=1d")


def parse_chart(payload):
    """Latest close and its date from Yahoo's chart JSON.

    Returns (price, date) or (None, None). Yahoo pads the series with nulls
    for holidays, so the last non-null close is taken rather than the last
    element.
    """
    try:
        result = payload["chart"]["result"][0]
        stamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        return None, None
    for ts, close in zip(reversed(stamps), reversed(closes)):
        if close is not None:
            return float(close), datetime.fromtimestamp(ts).date()
    return None, None


def fetch_stock_price(symbol, timeout=15):
    """Latest close for an NSE/BSE ticker, straight from Yahoo's chart API.

    This used to go through yfinance, which opened its own connections to
    whatever hosts it liked -- so the allowlist was advisory for the one feed
    that was a third-party library, and the log named a host that may not
    have been the one contacted. One small JSON parse buys back an enforced
    allowlist, an honest log, and one less dependency that breaks on Yahoo's
    schedule rather than ours.

    Pass the plain symbol (e.g. RELIANCE); .NS is appended if no suffix.
    Returns (price, date) or (None, None).
    """
    ticker = symbol if "." in symbol else symbol + ".NS"
    try:
        resp = _get(CHART_URL.format(symbol=quote(ticker, safe="")), timeout)
    except (requests.RequestException, Offline):
        return None, None
    try:
        return parse_chart(resp.json())
    except ValueError:
        return None, None


def fetch_stock_prices(symbols, timeout=15, workers=5):
    """Prices for several tickers at once.

    One holding per round trip made a thirty-stock refresh a thirty-request
    wait; symbols are de-duplicated first, because the same stock held by two
    people is still one price.
    """
    unique = []
    for sym in symbols:
        sym = (sym or "").strip()
        if sym and sym not in unique:
            unique.append(sym)
    if not unique:
        return {}
    if config.offline():                 # no threads, no sockets, one log line
        return {sym: fetch_stock_price(sym, timeout) for sym in unique[:1]}
    with ThreadPoolExecutor(max_workers=min(workers, len(unique))) as pool:
        results = pool.map(lambda s: fetch_stock_price(s, timeout), unique)
        return dict(zip(unique, results))
