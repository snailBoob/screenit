"""Statistics of fully closed 5-minute candles; missing bars break a window."""

import math

from src.contracts import WINDOWS

STEP = 300_000


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError, OverflowError):
        return None


def pct(new, old):
    return (new - old) / old * 100 if old and new is not None else None


def derive(bars, end):
    slots = {b["t"]: b for b in bars if b["t"] < end}
    trend = [slots.get(t, {}).get("c") for t in range(end - STEP * 283, end, 6 * STEP)]
    out = {}
    for window, minutes in WINDOWS.items():
        n = minutes // 5
        a = [slots.get(t) for t in range(end - n * STEP, end, STEP)]
        if not all(a):
            continue

        def prefix(key):
            return f"{key}:{window}"

        out[prefix("change")] = pct(a[-1]["c"], a[0]["o"])
        out[prefix("changeUsd")] = a[-1]["c"] - a[0]["o"]
        for key, prop in [("volume", "v"), ("trades", "n"), ("volumeDelta", "d")]:
            if all(b.get(prop) is not None for b in a):
                out[prefix(key)] = sum(b[prop] for b in a)
        if prefix("volume") in out:
            prev = [
                slots.get(t, {}).get("v")
                for t in range(end - 2 * n * STEP, end - n * STEP, STEP)
            ]
            if None not in prev:
                total = out[prefix("volume")]
                out[prefix("volChange")] = pct(total, sum(prev))
                out[prefix("volChangeUsd")] = total - sum(prev)
    return {k: v for k, v in out.items() if number(v) is not None}, trend
