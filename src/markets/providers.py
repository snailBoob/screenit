"""Public exchange data only. Conversion at the edge; no trading API keys."""

import json
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .metrics import number, pct

BINANCE = "https://fapi.binance.com"
HYPER = "https://api.hyperliquid.xyz/info"
MS = {
    '30m': 1800000,
    "1m": 60000,
    "5m": 300000,
    "15m": 900000,
    "1h": 3600000,
    "4h": 14400000,
    "1d": 86400000,
}


def now():
    return int(time.time() * 1000)


def request(url, body=None, headers=None):
    req = Request(
        url,
        data=json.dumps(body).encode() if body else None,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Screenit/1.0 (public market data)",
        },
    )
    for key, value in (headers or {}).items():
        req.add_unredirected_header(key, value)
    with urlopen(req, timeout=7) as res:
        raw = res.read(12_000_001)
    if len(raw) > 12_000_000:
        raise ValueError("Response too large")
    return json.loads(raw)


def bn(path, **args):
    return request(BINANCE + path + ("?" + urlencode(args) if args else ""))


def hl(kind, **args):
    return request(HYPER, {"type": kind, **args})


def row(symbol, at, metrics, base=None, qty=None):
    return {
        "symbol": symbol,
        "label": symbol,
        "at": at,
        "metrics": {k: v for k, v in metrics.items() if number(v) is not None},
        "metricAt": {},
        "trend": [],
        "_base": base,
        "_qty": qty,
    }


def binance_rows(symbols, tickers, premiums, periods):
    active = {
        s["symbol"]: s
        for s in symbols
        if s.get("contractType", "").endswith("PERPETUAL")
        and s.get("status") == "TRADING"
    }
    prem = {s["symbol"]: s for s in premiums}
    out = []
    for t in tickers:
        s = t["symbol"]
        price = number(t.get("lastPrice"))
        at = t.get("closeTime")
        if s not in active or not price or not at:
            continue
        p = prem.get(s, {})
        rate = number(p.get("lastFundingRate"))
        period = periods.get(s, 8) if periods is not None else None
        r = row(
            s,
            int(at),
            {
                "price": price,
                "change:1d": number(t.get("priceChangePercent")),
                "changeUsd:1d": number(t.get("priceChange")),
                "volume:1d": number(t.get("quoteVolume")),
                "trades:1d": number(t.get("count")),
                "funding": 100 * rate / period
                if rate is not None and period and p.get("time")
                else None,
            },
            active[s].get("baseAsset"),
        )
        if "funding" in r["metrics"]:
            r["metricAt"]["funding"] = int(p["time"])
        out.append(r)
    return out


def hyper_rows(payload, timestamp):
    out = []
    for meta, ctx in zip(payload[0]["universe"], payload[1], strict=True):
        p = number(ctx.get("markPx"))
        prev = number(ctx.get("prevDayPx"))
        qty = number(ctx.get("openInterest"))
        rate = number(ctx.get("funding"))
        s = meta["name"]
        if meta.get("isDelisted") or not p:
            continue
        out.append(
            row(
                s,
                timestamp,
                {
                    "price": p,
                    "oi": qty * p if qty is not None else None,
                    "funding": 100 * rate if rate is not None else None,
                    "volume:1d": number(ctx.get("dayNtlVlm")),
                    "change:1d": pct(p, prev),
                    "changeUsd:1d": p - prev if prev else None,
                },
                s,
                qty,
            )
        )
    return out


def hl_bar(x):
    close = float(x['c'])
    return dict(t=int(x['t']), o=float(x['o']), h=float(x['h']), l=float(x['l']),
                c=close, v=float(x['v'])*close, n=int(x['n']), d=None)


def fetch_bars(exchange, symbol, interval, count, before=None):
    """Fetch one page ending strictly before the supplied UTC millisecond cursor."""
    if exchange == "binance":
        cursor = {} if before is None else {"endTime": before - 1}
        data = bn("/fapi/v1/klines", symbol=symbol, interval=interval, limit=count, **cursor)
        bars = [
            dict(
                t=int(x[0]),
                o=float(x[1]),
                h=float(x[2]),
                l=float(x[3]),
                c=float(x[4]),
                v=float(x[7]),
                n=int(x[8]),
                d=2 * float(x[10]) - float(x[7]),
            )
            for x in data
        ]
    else:
        end = now() if before is None else before - 1
        step = MS[interval]
        data = hl(
            "candleSnapshot",
            req={
                "coin": symbol,
                "interval": interval,
                "startTime": max(0, (end // step - count + 1) * step),
                "endTime": end,
            },
        )
        bars = [hl_bar(x) for x in data]
    return sorted(
        (
            b
            for b in bars
            if all(number(b[k]) is not None for k in ["o", "h", "l", "c", "v"])
            and b["l"] > 0 and (before is None or b["t"] < before)
        ),
        key=lambda b: b["t"],
    )
