"""Exchange-minute windows, including the forming bar. Fixed memory per instrument.

Closed minutes are immutable inputs to a cached set of sums. Revising the forming
minute only costs O(number of windows), independent of their length.
"""

from array import array
from math import isfinite, log1p, sqrt

from src.contracts import WINDOWS
from .metrics import pct

MINUTE = 60000
DAY = WINDOWS["1d"]
WINDOW_ENDS = {n - 1: (w, n) for w, n in WINDOWS.items()}
PREV_ENDS = {2 * n - 1: (w, n) for w, n in WINDOWS.items()}
STEMS = (
    "change",
    "changeUsd",
    "volume",
    "trades",
    "volumeDelta",
    "volatility",
    "correlation",
    "volChange",
    "volChangeUsd",
)
KEY = {w: {k: k + ":" + w for k in STEMS} for w in WINDOWS}


def owned(venue):
    return {
        key
        for cols in KEY.values()
        for k, key in cols.items()
        if key != "volume:1d"
        and not (venue == "binance" and key == "change:1d")
        and (
            venue == "binance" or k not in ("volChange", "volChangeUsd", "volumeDelta")
        )
    } | {"rvol"}


class MinuteSeries:
    def __init__(self, venue):
        self.binance = venue == "binance"
        self.size = DAY * (2 if self.binance else 1)
        self.tags = array("q", [0]) * self.size  # epoch minute + 1; negative while open
        self.o, self.c, self.v, self.n, self.d = [
            array("d", [0]) * self.size for _ in range(5)
        ]
        self.minute = -1
        self.at = self.version = 0
        self.base_key = self.result_key = None

    def put(self, bar, stamp, final):
        minute, rem = divmod(bar["t"], MINUTE)
        if rem or minute <= self.minute - self.size:
            return
        idx = minute % self.size
        old = self.tags[idx]
        new = minute + 1
        o, c, v, n = (bar[k] for k in ("o", "c", "v", "n"))
        d = bar.get("d") if self.binance else 0.0
        if (
            not all(
                isinstance(x, (int, float)) and isfinite(x) for x in (o, c, v, n, d)
            )
            or min(o, c) <= 0
            or min(n, v) < 0
        ):
            return
        if not final and (
            old == new
            or minute < self.minute
            or (old == -new and (stamp < self.at or n < self.n[idx]))
        ):
            return
        if (
            final
            and old == new
            and (o, c, v, n, d)
            == (self.o[idx], self.c[idx], self.v[idx], self.n[idx], self.d[idx])
        ):
            return
        self.tags[idx] = new if final else -new
        self.o[idx], self.c[idx], self.v[idx], self.n[idx], self.d[idx] = o, c, v, n, d
        if final:
            self.version += 1
        if minute >= self.minute:
            self.minute = minute
            self.at = stamp
        self.result_key = None

    def seal(self, minute):
        # Caller must have a venue observation confirming completion.
        i = minute % self.size
        if self.tags[i] == -(minute + 1):
            self.tags[i] = minute + 1
            self.version += 1
            self.result_key = None

    def confirm_inactive(self, trade_at, price, asof):
        """A *fresh exchange response* confirms the last trade, including its time.

        Extend only from a locally known close at the same price. Never count a
        silent transport, an absent symbol or a stale batch as proof of no trades.
        """
        m = asof // MINUTE
        if (
            not self.binance
            or self.minute < 0
            or trade_at >= m * MINUTE
            or self.minute < m - 6
        ):
            return
        j = self.minute % self.size
        if self.c[j] != price or not self.has(self.minute):
            return
        if not self.has(self.minute, True) and self.minute < m:
            if trade_at >= self.minute * MINUTE or self.n[j] != 0:
                return
            self.seal(self.minute)
        first = max(self.minute, trade_at // MINUTE + 1)
        for minute in range(first, m + 1):
            idx = minute % self.size
            if self.has(minute, True):
                continue
            if self.has(minute) and self.n[idx] > 0:
                return
            self.put(
                {"t": minute * MINUTE, "o": price, "c": price, "v": 0, "d": 0, "n": 0},
                asof,
                minute < m,
            )

    def has(self, minute, closed=False):
        t = self.tags[minute % self.size]
        return (t if closed else abs(t)) == minute + 1

    def _closed(self, m, btc):
        key = (m, self.version, id(btc), btc.version if btc else 0)
        if key == self.base_key:
            return
        self.base_key = key
        self.base = {}
        self.prior = {}
        vol = num = delta = lg = lg2 = sx = sx2 = sy = sy2 = sxy = 0.0
        last = ref = 0.0
        paired = btc is not None
        for i in range(1, self.size):
            t = m - i
            j = t % self.size
            if self.tags[j] != t + 1:
                break
            vol += self.v[j]
            num += self.n[j]
            delta += self.d[j]
            if i < DAY:
                c = self.c[j]
                if paired:
                    k = t % btc.size
                    paired = btc.tags[k] == t + 1
                    if paired:
                        bc = btc.c[k]
                if last:
                    x = last / c - 1
                    lr = log1p(x)
                    lg += lr
                    lg2 += lr * lr
                    sx += x
                    sx2 += x * x
                    if paired:
                        y = ref / bc - 1
                        sy += y
                        sy2 += y * y
                        sxy += x * y
                last = c
                if paired:
                    ref = bc
            if i in WINDOW_ENDS:
                w, n = WINDOW_ENDS[i]
                self.base[w] = (
                    n,
                    self.o[j] if self.binance else self.c[j],
                    vol,
                    num,
                    delta,
                    lg,
                    lg2,
                    sx,
                    sx2,
                    sy,
                    sy2,
                    sxy,
                    paired,
                )
            if self.binance and i in PREV_ENDS:
                w, _ = PREV_ENDS[i]
                self.prior[w] = max(0.0, vol - self.base[w][2])

    def metrics(self, now, btc):
        m = now // MINUTE
        j = m % self.size
        if self.minute != m or not self.has(m) or not -30000 <= now - self.at < MINUTE:
            return 0, {}
        if btc and (
            btc.minute != m or not btc.has(m) or not -30000 <= now - btc.at < MINUTE
        ):
            btc = None
        key = (
            m,
            self.at,
            self.version,
            id(btc),
            btc.at if btc else 0,
            btc.version if btc else 0,
        )
        if key == self.result_key:
            return self.at, self.result
        self._closed(m, btc)
        out = {}
        c = self.c[j]
        p = (m - 1) % self.size
        if self.base:
            x = c / self.c[p] - 1
            lr = log1p(x)
        for w, (
            n,
            first,
            vol,
            num,
            delta,
            lg,
            lg2,
            sx,
            sx2,
            sy,
            sy2,
            sxy,
            paired,
        ) in self.base.items():
            k = KEY[w]
            total = vol + self.v[j]
            out[k["change"]] = pct(c, first)
            out[k["trades"]] = int(num + self.n[j])
            out[k["volume"]] = total
            if self.binance:
                out[k["volumeDelta"]] = delta + self.d[j]
                prev = self.prior.get(w)
                if prev is not None:
                    out[k["volChangeUsd"]] = total - prev
                    if prev > 0:
                        out[k["volChange"]] = pct(total, prev)
            N = n - 1
            var = max(0.0, lg2 + lr * lr - (lg + lr) ** 2 / N)
            out[k["volatility"]] = 100 * sqrt(var / (N - 1))
            if paired:
                y = btc.c[m % btc.size] / btc.c[(m - 1) % btc.size] - 1
                vx = sx2 + x * x - (sx + x) ** 2 / N
                vy = sy2 + y * y - (sy + y) ** 2 / N
                if vx > 0 and vy > 0:
                    cor = (sxy + x * y - (sx + x) * (sy + y) / N) / sqrt(vx * vy)
                    out[k["correlation"]] = max(-1.0, min(1.0, cor))
        daily = out.pop("volume:1d", 0)  # table uses the separate rolling venue ticker
        if daily > 0:
            out["rvol"] = out["volume:5m"] * (DAY / 5) / daily
        self.result_key = key
        self.result = out
        return self.at, out
