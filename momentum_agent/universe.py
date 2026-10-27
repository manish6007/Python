"""Default trading universe: liquid NSE large & mid caps (roughly today's Nifty 200).

WARNING - survivorship bias: this is TODAY's list. Stocks that were large 10 years ago
but have since collapsed (e.g. Yes Bank-style blowups, delisted names) are under-
represented, which flatters any backtest. For honest results supply point-in-time index
constituents via --universe-file.
"""
from pathlib import Path

DEFAULT_UNIVERSE = [
    # Nifty 50 (approx.)
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO",
    "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL", "CIPLA", "COALINDIA", "DRREDDY",
    "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY", "ITC", "JIOFIN",
    "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM",
    "TATASTEEL", "TCS", "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
    # Next 50 / large-mid caps
    "ABB", "ADANIGREEN", "ADANIPOWER", "AMBUJACEM", "BAJAJHLDNG", "BANKBARODA",
    "BOSCHLTD", "BPCL", "BRITANNIA", "CANBK", "CHOLAFIN", "COLPAL", "DABUR", "DIVISLAB",
    "DLF", "DMART", "GAIL", "GODREJCP", "HAVELLS", "HAL", "HINDZINC", "ICICIGI",
    "ICICIPRULI", "INDHOTEL", "IOC", "IRFC", "JINDALSTEL", "LICI", "LODHA", "LTIM",
    "MOTHERSON", "NAUKRI", "PIDILITIND", "PFC", "PNB", "RECLTD", "SHREECEM", "SIEMENS",
    "TATAPOWER", "TORNTPHARM", "TVSMOTOR", "UNITDSPR", "VBL", "VEDL", "ZYDUSLIFE",
    # Midcaps
    "CUMMINSIND", "POLYCAB", "PERSISTENT", "MUTHOOTFIN", "LUPIN", "AUROPHARMA",
    "TATAELXSI", "MARICO", "BERGEPAINT", "SRF", "PIIND", "MPHASIS", "COFORGE",
    "ASHOKLEY", "INDIGO", "BHEL", "NHPC", "IDFCFIRSTB", "FEDERALBNK", "AUBANK",
    "PAGEIND", "PETRONET", "ALKEM", "ABCAPITAL", "BALKRISIND", "VOLTAS", "MRF",
    "APOLLOTYRE", "DIXON", "ASTRAL", "OBEROIRLTY", "GODREJPROP", "PRESTIGE",
    "SUPREMEIND", "DEEPAKNTR", "TATACOMM", "CONCOR", "SAIL", "NMDC", "BANDHANBNK",
    "LICHSGFIN", "M&MFIN", "BIOCON", "GLENMARK", "IPCALAB", "LALPATHLAB", "MAXHEALTH",
    "KPITTECH", "OFSS", "TIINDIA", "SUZLON", "YESBANK", "INDUSTOWER", "IDEA",
    "ESCORTS", "EXIDEIND", "BHARATFORG", "JUBLFOOD", "MFSL", "TORNTPOWER", "UPL",
    "COROMANDEL", "GMRAIRPORT", "CGPOWER", "SOLARINDS", "BSE", "MAZDOCK", "POLICYBZR",
    "PATANJALI", "HINDPETRO", "OIL", "UNIONBANK", "INDIANB", "IRCTC", "LAURUSLABS",
    "MANKIND", "PHOENIXLTD", "KEI", "SBICARD", "HDFCAMC", "TATACHEM", "ACC",
    "ABFRL", "NAM-INDIA", "SUNTV", "ZEEL", "RBLBANK", "CROMPTON", "AARTIIND",
]


def load_universe(path: str | None = None) -> list[str]:
    """Symbols from a file (one per line, '#' comments allowed) or the default list."""
    if not path:
        return list(DEFAULT_UNIVERSE)
    symbols = []
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            symbols.append(line.upper())
    return symbols
