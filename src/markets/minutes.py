"""Rolling minute-candle statistics. NaN inside the window denotes a missing slot."""

from array import array
from dataclasses import dataclass
import math
from statistics import correlation, stdev

from src.contracts import WINDOWS

MINUTE = 60_000
DAY = WINDOWS['1d']


@dataclass
class MinuteWindow:
    at: int
    closes: array
    volumes: array

    def request_size(self, at):
        # Always fetch the old forming candle again: its close and volume can change.
        delta = at // MINUTE - self.at // MINUTE
        return min(DAY, delta + 1) if delta >= 0 else DAY

    @classmethod
    def updated(cls, old, at, bars):
        size = old.request_size(at) if old else DAY
        # Only two doubles per minute per contract, including explicit gaps.
        empty = array('d', [math.nan]) * size
        prices = old.closes[size - 1:-1] + empty if size < DAY else empty[:]
        volumes = old.volumes[size - 1:-1] + empty if size < DAY else empty[:]
        start = at // MINUTE - DAY + 1
        for bar in bars:
            minute, remainder = divmod(bar['t'], MINUTE)
            i = minute - start
            if remainder or not DAY-size <= i < DAY:
                continue
            c, v = bar['c'], bar['v']
            if math.isfinite(c) and c > 0:
                prices[i] = c
            if math.isfinite(v) and v >= 0:
                volumes[i] = v
        return cls(at, prices, volumes)

    def metrics(self, btc):
        out = {}
        total = math.fsum(self.volumes)
        if total > 0:
            out['rvol'] = math.fsum(self.volumes[-5:]) / (total / (DAY / 5))
        aligned = btc is not None and btc.at // MINUTE == self.at // MINUTE
        for label, length in WINDOWS.items():
            closes = self.closes[-length:]
            if not all(map(math.isfinite, closes)):
                continue
            ratios = [b / a for a, b in zip(closes, closes[1:])]
            out['volatility:'+label] = 100 * stdev(map(math.log, ratios))
            if not aligned:
                continue
            ref = btc.closes[-length:]
            if not all(map(math.isfinite, ref)):
                continue
            left = [v - 1 for v in ratios]
            right = left if self is btc else [b/a - 1 for a, b in zip(ref, ref[1:])]
            if min(left) != max(left) and min(right) != max(right):
                out['correlation:'+label] = correlation(left, right)
        return out
