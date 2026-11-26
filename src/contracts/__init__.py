"""Wire definitions shared by data acquisition, HTTP service and browser."""

WINDOWS = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "8h": 480, "12h": 720, "1d": 1440}
INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"]
EXCHANGES = ["binance", "hyperliquid"]
CORE = {"price": ("Price", "usd"), "oi": ("Open interest", "usd"), "funding": ("Funding / hour", "pct"), "rvol": ("Relative volume", "ratio"), "mcap": ("Market cap", "usd")}
SERIES = {"change": ("Price change", "pct"), "changeUsd": ("Price change $", "usd"), "volume": ("Volume", "usd"), "trades": ("Trades", "count"), "volatility": ("Volatility", "pct"), "oiChange": ("OI change", "pct"), "oiDelta": ("Open interest Δ$", "usd"), "volumeDelta": ("Buy/sell delta", "usd"), "volChange": ("Volume change", "pct"), "volChangeUsd": ("Volume change $", "usd"), "correlation": ("BTC correlation", "corr")}
def metric_ttl(key, explicit=True):
    if key=='mcap':return 2*3600000
    if key=='oi' or key.startswith(('oiChange:','oiDelta:')):return 450000 if explicit else 120000
    return 120000

DEFAULT_COLUMNS = ["trend", "symbol", "price", "change:5m", "change:1h", "change:1d", "volume:1h", "volume:1d", "oi", "oiChange:1h", "funding", "volatility:15m", "trades:15m"]
FILTER_OPS = ["gt", "gte", "lt", "lte", "eq", "between", "abs_gt"]
MAX_FILTERS = 9
ALERT_OPS = ["gt", "lt", "cross_up", "cross_down", "between", "outside"]


def catalog():
    fields = [{"id": k, "label": label, "unit": unit, "group": "Core"} for k, (label, unit) in CORE.items()]
    for key, (label, unit) in SERIES.items():
        fields.extend({"id": f"{key}:{w}", "label": f"{label} ({w})", "unit": unit, "group": label} for w in WINDOWS)
    return {"metrics": fields, "exchanges": EXCHANGES, "intervals": INTERVALS, "windows": list(WINDOWS), "filterOps": FILTER_OPS, "alertOps": ALERT_OPS, "maxFilters": MAX_FILTERS}


def defaults():
    return {"exchange": "binance", "columns": DEFAULT_COLUMNS.copy(), "sort": {"key": "volume:1d", "dir": "desc"}, "favorites": [], "favoritesOnly": False, "filters": [], "hyperliquidFilters": [], "filtersEnabled": True, "hyperliquidFiltersEnabled": True, "theme": "dark", "chartInterval": "15m", "search": "", "browserNotifications": False}
