"""Price data: download daily OHLCV from Yahoo Finance (cached to CSV) or load your own CSVs.

Each source ends up as a dict of wide DataFrames (index = date, columns = symbol):
    {"open": ..., "low": ..., "close": ..., "volume": ...}
Prices are split/dividend adjusted.
"""
from pathlib import Path

import pandas as pd

FIELDS = ("Open", "Low", "Close", "Volume")


def _yahoo_symbol(symbol: str) -> str:
    return symbol if symbol.startswith("^") or "." in symbol else f"{symbol}.NS"


def _drop_glitches(df: pd.DataFrame) -> pd.DataFrame:
    """Blank out bad prints: bars whose close is <0.5x or >2x the 11-day centred median.

    Yahoo has a few of these (e.g. GOLDBEES on 19-20 Dec 2019 at 1/100th of the real price for
    two days). A real move of that size does not reverse within days, so a centred median is a
    safe data-cleaning test; it is not used for any trading signal.
    """
    if "Close" not in df.columns or len(df) < 11:
        return df
    med = df["Close"].rolling(11, center=True, min_periods=5).median()
    ratio = df["Close"] / med
    bad = (ratio < 0.5) | (ratio > 2.0)
    if bad.any():
        df = df.copy()
        df.loc[bad, [c for c in ("Open", "Low", "Close") if c in df.columns]] = float("nan")
        df[[c for c in ("Open", "Low", "Close") if c in df.columns]] = df[
            [c for c in ("Open", "Low", "Close") if c in df.columns]].ffill()
    return df


def _read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["Date"], index_col="Date")
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return _drop_glitches(df.sort_index())


def download_yahoo(symbols, start: str, end: str | None, cache_dir: str = "data_cache",
                   refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Download (or read cached) daily bars for each symbol. Returns {symbol: OHLCV frame}."""
    import yfinance as yf  # imported lazily so tests and CSV mode don't need it

    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    frames = {}
    for symbol in symbols:
        path = cache / f"{symbol.replace('^', 'IDX_')}.csv"
        if path.exists() and not refresh:
            frames[symbol] = _read_csv(path)
            continue
        raw = yf.download(_yahoo_symbol(symbol), start=start, end=end, auto_adjust=True,
                          progress=False, multi_level_index=False)
        if raw is None or raw.empty:
            print(f"  ! no data for {symbol}, skipping")
            continue
        raw = raw[[c for c in FIELDS if c in raw.columns]].dropna(how="all")
        raw.index.name = "Date"
        raw.to_csv(path)
        frames[symbol] = _read_csv(path)
    return frames


def load_csv_dir(directory: str, symbols=None) -> dict[str, pd.DataFrame]:
    """Load `<SYMBOL>.csv` files with Date, Open, Close, Volume columns (e.g. exported from Kite)."""
    frames = {}
    for path in sorted(Path(directory).glob("*.csv")):
        symbol = path.stem.replace("IDX_", "^")
        if symbols is None or symbol in symbols:
            frames[symbol] = _read_csv(path)
    return frames


def to_panel(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Turn {symbol: OHLCV} into {"open"|"close"|"volume": wide frame} on a common calendar."""
    panel = {}
    for field in FIELDS:
        cols = {s: f[field] for s, f in frames.items() if field in f.columns}
        panel[field.lower()] = pd.DataFrame(cols).sort_index()
    return panel
