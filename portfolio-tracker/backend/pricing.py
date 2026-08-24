"""Price feeds: AMFI mutual-fund NAVs, stock prices, NPS NAVs.

All fetchers fail soft (return {} / None) so the app keeps working offline
with last-known or manual prices.
"""
from datetime import datetime

import requests

AMFI_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"


def fetch_amfi_navs(timeout=30):
    """Download today's AMFI NAV dump.

    Returns {scheme_code: {"name": str, "nav": float, "date": date}}.
    """
    try:
        resp = requests.get(AMFI_NAV_URL, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException:
        return {}
    navs = {}
    for line in resp.text.splitlines():
        parts = line.split(";")
        if len(parts) < 6 or not parts[0].strip().isdigit():
            continue
        code, _, _, name, nav, nav_date = [p.strip() for p in parts[:6]]
        try:
            nav_f = float(nav)
            d = datetime.strptime(nav_date, "%d-%b-%Y").date()
        except ValueError:
            continue
        navs[code] = {"name": name, "nav": nav_f, "date": d}
    return navs


def search_amfi(navs, query, limit=20):
    q = query.lower()
    hits = [(code, info) for code, info in navs.items()
            if q in info["name"].lower()]
    return hits[:limit]


def fetch_stock_price(symbol):
    """Latest close for an NSE/BSE ticker via yfinance.

    Pass the plain symbol (e.g. RELIANCE); .NS is appended if no suffix.
    Returns (price, date) or (None, None).
    """
    try:
        import yfinance as yf
    except ImportError:
        return None, None
    ticker = symbol if "." in symbol else symbol + ".NS"
    try:
        hist = yf.Ticker(ticker).history(period="5d")
        if hist is None or hist.empty:
            return None, None
        last = hist["Close"].dropna()
        if last.empty:
            return None, None
        return float(last.iloc[-1]), last.index[-1].date()
    except Exception:
        return None, None
