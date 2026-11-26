import unittest

from src.markets.metrics import STEP, derive


class WindowTests(unittest.TestCase):
    def test_closed_windows_units_baseline_and_gap(self):
        end = 600 * STEP
        bars = [
            dict(
                t=i * STEP,
                o=100 + i,
                h=102 + i,
                l=99 + i,
                c=101 + i,
                v=10 if i < 588 else 20,
                n=3,
                d=-5,
            )
            for i in range(24, 600)
        ]
        metrics, trend = derive(bars, end)
        self.assertEqual(metrics["volume:1h"], 240)
        self.assertEqual(metrics["volChange:1h"], 100)
        self.assertEqual(metrics["volumeDelta:5m"], -5)
        self.assertEqual(metrics["trades:1h"], 36)
        self.assertNotIn('correlation:1h', metrics)
        self.assertNotIn('rvol', metrics)
        self.assertNotIn('volatility:1h', metrics)
        self.assertEqual(trend[-1], 700)
        broken = [b for b in bars if b["t"] != end - 2 * STEP]
        metrics, _ = derive(broken, end)
        self.assertNotIn("volume:1h", metrics)
        self.assertIn("volume:5m", metrics)

    def test_no_history_invents_no_numbers(self):
        metrics, trend = derive([], 500 * STEP)
        self.assertEqual(metrics, {})
        self.assertFalse(any(trend))
