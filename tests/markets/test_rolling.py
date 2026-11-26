import unittest

from src.markets.rolling import MinuteSeries, MINUTE


class LiveWindowTests(unittest.TestCase):
    start = 10000 * MINUTE

    def bar(self, i, n, close):
        return dict(
            t=self.start + i * MINUTE, o=100 + i, c=close, v=n * 10, n=n, d=n * 2
        )

    def test_live_revisions_rollover_and_gap_repair(self):
        s = MinuteSeries("binance")
        for i in range(4):
            b = self.bar(i, 10, 101 + i)
            s.put(b, b["t"] + MINUTE, True)
        b = self.bar(4, 5, 106)
        at = b["t"] + 1000
        s.put(b, at, False)

        def snapshot(t):
            return s.metrics(t, s)[1]

        self.assertEqual(snapshot(at)["trades:5m"], 45)
        b = self.bar(4, 20, 110)
        s.put(b, at + 2000, False)
        s.put(self.bar(4, 5, 106), at, False)  # delayed update cannot rewind
        m = snapshot(at + 2000)
        self.assertEqual(
            (m["volume:5m"], m["trades:5m"], m["volumeDelta:5m"]), (600, 60, 120)
        )
        self.assertAlmostEqual(m["change:5m"], 10)
        self.assertAlmostEqual(m["correlation:5m"], 1)
        s.put(b, b["t"] + MINUTE, True)
        nextbar = self.bar(5, 0, 110)
        t = nextbar["t"] + 500
        s.put(nextbar, t, False)
        self.assertEqual(
            snapshot(t)["trades:5m"], 50
        )  # confirmed 0; oldest 10 rolled out
        later = self.bar(6, 2, 111)
        t = later["t"] + 500
        s.put(later, t, False)
        self.assertNotIn("trades:5m", snapshot(t))  # lost final, not a made-up zero
        s.put(nextbar, nextbar["t"] + MINUTE, True)
        self.assertEqual(snapshot(t)["trades:5m"], 42)

    def test_hyperliquid_uses_first_close_and_confirmed_turnover_only(self):
        s = MinuteSeries("hyperliquid")
        for i in range(5):
            b = self.bar(i, 10, 105 + i)
            b["d"] = None
            s.put(b, b["t"] + 1000, i < 4)
        m = s.metrics(b["t"] + 1500, s)[1]
        self.assertAlmostEqual(m["change:5m"], (109 / 105 - 1) * 100)
        self.assertNotIn("volumeDelta:5m", m)
        self.assertNotIn("volume:15m", m)

    def test_quiet_binance_contract_requires_a_matching_exchange_last_trade(self):
        s = MinuteSeries("binance")
        for i in range(5):
            b = self.bar(i, 2 if i == 0 else 0, 110)
            s.put(b, b["t"] + MINUTE, True)
        now = b["t"] + MINUTE + 3000
        self.assertEqual(s.metrics(now, s)[1], {})
        s.confirm_inactive(now - 1000, 110, now)
        self.assertEqual(s.metrics(now, s)[1], {})
        s.confirm_inactive(self.start + 50, 111, now)
        self.assertEqual(s.metrics(now, s)[1], {})
        s.confirm_inactive(self.start + 50, 110, now)
        self.assertEqual(s.metrics(now, s)[1]["trades:5m"], 0)
        s.put(self.bar(5, 3, 112), now + 900, False)
        self.assertEqual(s.metrics(now + 900, s)[1]["trades:5m"], 3)

    def test_hyperliquid_dollar_oi_includes_price_change_and_day_volume_comparison(
        self,
    ):
        import tempfile
        from src.markets import MarketFeed
        from src.markets.providers import hyper_rows

        with tempfile.TemporaryDirectory() as d:
            f = MarketFeed(d)

            def observe(t, price, day):
                rows = hyper_rows(
                    [
                        {"universe": [{"name": "BTC"}]},
                        [dict(markPx=price, openInterest="10", dayNtlVlm=day)],
                    ],
                    t,
                )
                f._samples("hyperliquid", rows, t)
                return rows[0]["metrics"]

            observe(self.start, "100", "2000")
            m = observe(self.start + 5 * MINUTE, "110", "2100")
            self.assertEqual(m["oiDelta:5m"], 100)
            self.assertEqual(m["oiChange:5m"], 0)
            self.assertEqual(m["volChangeUsd:5m"], 100)
            self.assertEqual(m["volChange:5m"], 5)
            f.close()

    def test_full_history_uses_same_window_for_counts_dispersion_and_correlation(self):
        import math
        import statistics
        from src.contracts import WINDOWS

        s = MinuteSeries("binance")
        btc = MinuteSeries("binance")
        closes = []
        refs = []
        volumes = []
        for i in range(2880):
            t = self.start + i * MINUTE
            close = 100 + math.sin(i * 0.27)
            ref = 45000 + 100 * math.cos(i * 0.31)
            vol = (i % 17) * 100
            closes.append(close)
            refs.append(ref)
            volumes.append(vol)
            for book, c in [(s, close), (btc, ref)]:
                book.put(
                    dict(t=t, o=c - 0.1, c=c, v=vol, n=i % 17, d=vol * 0.2),
                    t + 800,
                    i < 2879,
                )
        m = s.metrics(t + 1000, btc)[1]
        for w, n in WINDOWS.items():
            expected = sum(volumes[-n:])
            prior = sum(volumes[-2 * n : -n])
            actual = m.get("volume:" + w, expected if w == "1d" else None)
            self.assertEqual(actual, expected)
            self.assertEqual(m["volChangeUsd:" + w], expected - prior)
            self.assertEqual(m["trades:" + w], expected // 100)
            a = [y / x - 1 for x, y in zip(closes[-n:], closes[-n + 1 :])]
            b = [y / x - 1 for x, y in zip(refs[-n:], refs[-n + 1 :])]
            self.assertAlmostEqual(
                m["volatility:" + w],
                statistics.stdev(map(math.log1p, a)) * 100,
                places=9,
            )
            self.assertAlmostEqual(
                m["correlation:" + w], statistics.correlation(a, b), places=9
            )
        self.assertAlmostEqual(
            m["rvol"], sum(volumes[-5:]) * 288 / sum(volumes[-1440:])
        )
