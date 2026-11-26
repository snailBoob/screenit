import math
import re
from urllib.parse import urlsplit

from src.contracts import ALERT_OPS, EXCHANGES, FILTER_OPS, INTERVALS, MAX_FILTERS, catalog, defaults

METRICS = {m["id"] for m in catalog()["metrics"]}


def require(ok, message="Invalid input"):
    if not ok:
        raise ValueError(message)


def short(v, limit=128):
    return isinstance(v, str) and len(v) <= limit and all(ord(c) >= 32 for c in v)


def numeric(v):
    return type(v) in (int, float) and -1e100 <= v <= 1e100 and math.isfinite(v)


def condition(c, ops):
    require(
        isinstance(c, dict)
        and set(c) <= {"metric", "op", "value", "upper"}
        and c.get("metric") in METRICS,
        "Unknown metric",
    )
    op = c.get("op")
    require(
        op in ops and numeric(c.get("value")),
        "Check the comparison and threshold",
    )
    if op in ("between", "outside"):
        require(
            numeric(c.get("upper")) and c["upper"] >= c["value"],
            "Upper bound must be at least the lower bound",
        )


def settings(s):
    require(s.keys() == defaults().keys())
    require(s["theme"] in ("dark", "light", "system"))
    require(s["exchange"] in EXCHANGES and s["chartInterval"] in INTERVALS)
    require(short(s["search"]) and type(s["favoritesOnly"]) is bool)
    require(type(s['browserNotifications']) is bool)
    require(all(type(s[key]) is bool for key in ('filtersEnabled', 'hyperliquidFiltersEnabled')))
    cols = s["columns"]
    allowed = METRICS | {"trend", "symbol"}
    require(
        isinstance(cols, list)
        and 1 <= len(cols) <= len(allowed)
        and all(isinstance(c, str) and c in allowed for c in cols)
        and len(set(cols)) == len(cols)
        and "symbol" in cols,
        "Symbol must remain visible",
    )
    sort = s["sort"]
    require(
        isinstance(sort, dict)
        and sort.get("key") in METRICS | {"symbol"}
        and sort.get("dir") in ("asc", "desc")
    )
    fav = s["favorites"]
    require(
        isinstance(fav, list)
        and len(fav) <= 4000
        and all(
            short(x)
            and ":" in x
            and x.split(":", 1)[0] in EXCHANGES
            and x.split(":", 1)[1]
            for x in fav
        )
        and len(set(fav)) == len(fav)
    )
    for key in ('filters','hyperliquidFilters'):
        require(isinstance(s[key], list))
        require(len(s[key]) <= MAX_FILTERS, f"Maximum {MAX_FILTERS} filters per exchange.")
        for c in s[key]:
            condition(c, FILTER_OPS)


def rule(r):
    require(
        isinstance(r, dict)
        and {"name", "exchange", "symbol", "enabled", "repeat", "groups"} <= set(r)
        and not set(r)-{'name','exchange','symbol','enabled','repeat','groups','cooldownMs','sound','ntfy'}
    )
    n = r.get('ntfy')
    if n is not None:
        require(isinstance(n, dict) and set(n) == {'server','topic'}, 'Invalid ntfy settings')
        require(short(n['server'], 500) and re.fullmatch(r'https?://[^\s\\?#]+', n['server']), 'Enter a valid Server URL')
        url = urlsplit(n['server'])
        require(url.hostname and url.username is None and url.password is None and url.port != 0, 'Invalid ntfy server')
        require(short(n['topic'],64) and re.fullmatch(r'[A-Za-z0-9_-]+', n['topic']), 'Enter a valid Topic')
    require(short(r["name"], 90), "Alert name is too long or invalid")
    require(r.get('sound','') in ('','boop','bell','ding','alert','chime'),'Unknown alert sound')
    if 'cooldownMs' in r:
        require(type(r['cooldownMs']) is int and r['cooldownMs'] in (60000,300000,900000,1800000,3600000,14400000),'Invalid cooldown')
    require(
        r["exchange"] in EXCHANGES
        and type(r["enabled"]) is bool
        and r["repeat"] in ("once", "rearm")
    )
    require(r["symbol"] is None or (short(r["symbol"]) and r["symbol"].strip()))
    groups = r["groups"]
    require(isinstance(groups, list) and 0 < len(groups) <= 8)
    for g in groups:
        require(isinstance(g, list) and 0 < len(g) <= 8)
        for c in g:
            condition(c, ALERT_OPS)
            if c["metric"] == "price" or c["metric"].startswith("changeUsd:"):
                require(r["symbol"], "Select one instrument for this metric")
