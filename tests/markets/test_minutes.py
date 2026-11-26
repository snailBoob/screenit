import math
import unittest

from src.markets.minutes import MINUTE, DAY, MinuteWindow


class MinuteMetricTests(unittest.TestCase):
    # The newest minute is still forming, as it was in the paired Orion feed.
    at = 2 * DAY * MINUTE + 25000

    def bars(self, tail, volumes=None):
        start = (self.at // MINUTE - DAY + 1) * MINUTE
        prices = [100.0] * (DAY - len(tail)) + tail
        return [dict(t=start+i*MINUTE, c=p, v=volumes[i] if volumes else 10.0)
                for i, p in enumerate(prices)]

    def test_rolling_volume_log_dispersion_and_aligned_btc_returns(self):
        vol = [10] * (DAY - 5) + [20] * 5
        s = MinuteWindow.updated(None, self.at, self.bars([100, 110, 99, 108.9, 98.01], vol))
        btc = MinuteWindow.updated(None, self.at, self.bars([100, 95, 99.75, 94.7625, 99.500625]))
        m = s.metrics(btc)
        self.assertAlmostEqual(m['rvol'], 100 / (14450 / 288))
        # Four close-to-close returns from five closes, sample standard deviation.
        self.assertAlmostEqual(m['volatility:5m'], 100*math.log(1.1/0.9)/math.sqrt(3))
        self.assertAlmostEqual(m['correlation:5m'], -1.0)

    def test_missing_minutes_missing_reference_and_zero_denominators(self):
        bars = self.bars([100, 102, 101, 104, 103]); del bars[-7]
        s = MinuteWindow.updated(None, self.at, bars)
        flat = MinuteWindow.updated(None, self.at, self.bars([100], [0]*DAY))
        m = s.metrics(flat)
        self.assertNotIn('rvol', m); self.assertNotIn('volatility:15m', m)
        self.assertIn('volatility:5m', m); self.assertNotIn('correlation:5m', m)
        self.assertNotIn('rvol', flat.metrics(None)); self.assertEqual(flat.metrics(None)['volatility:5m'], 0)
        late = MinuteWindow.updated(None, self.at+MINUTE, bars)
        self.assertNotIn('correlation:5m', s.metrics(late))

    def test_refetch_and_replace_the_forming_minute_no_forward_filling(self):
        bars = self.bars([90, 95, 100, 105, 112]); s = MinuteWindow.updated(None,self.at,bars)
        now = self.at + MINUTE
        self.assertEqual(s.request_size(now), 2)
        # Revision of the formerly open minute and a partial new minute.
        delta = [{**bars[-1], 'v': 40, 'c': 106}, {**bars[-1], 't': bars[-1]['t']+MINUTE, 'v': 30}]
        incremental = MinuteWindow.updated(s, now, delta)
        full = MinuteWindow.updated(None, now, bars[1:-1] + delta)
        self.assertEqual(incremental.metrics(full), full.metrics(full))
        self.assertNotIn('rvol', MinuteWindow.updated(s, now, delta[-1:]).metrics(None))
        self.assertEqual(s.request_size(now+DAY*MINUTE), DAY)
