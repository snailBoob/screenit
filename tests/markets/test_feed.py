import unittest
import tempfile
from unittest.mock import patch

from src.markets.providers import binance_rows, hyper_rows
from src.markets import MarketFeed


class ProviderTests(unittest.TestCase):
    def test_sampled_ticker_prices_do_not_override_minute_candle_correlation(self):
        from src.markets.providers import row

        with tempfile.TemporaryDirectory() as d:
            f = MarketFeed(d)
            base = 300000000

            def prices(stamp, p):
                return [
                    row("BTCUSDT", base + stamp * 1000, {"price": p}),
                    row("ETHUSDT", base + stamp * 1000, {"price": p / 2}),
                ]

            for received, at, price in [
                (0, 0, 100),
                (45, 0, 100),
                (90, 0, 100),
                (180, 180, 110),
                (270, 180, 110),
            ]:
                rs = prices(at, price)
                f._samples("binance", rs, base + received * 1000)
            self.assertNotIn("correlation:5m", rs[1]["metrics"])
            for i, p in enumerate([100, 101, 99, 104, 103, 105]):
                at = 600 + i * 60
                rs = prices(at, p)
                f._samples("binance", rs, base + at * 1000)
            self.assertNotIn('correlation:5m', rs[1]['metrics'])
            f.close()

    def test_delayed_receipt_does_not_shorten_the_metric_window(self):
        with tempfile.TemporaryDirectory() as d:
            f = MarketFeed(d)
            base = 300000000

            def obs(at, px):
                return hyper_rows(
                    [{"universe": [{"name": "BTC"}]}, [dict(markPx=str(px))]], at
                )

            f._samples("hyperliquid", obs(base + 60000, 100), base + 60000)
            rows = obs(base + 300000, 110)
            f._samples("hyperliquid", rows, base + 360000)
            self.assertNotIn("change:5m", rows[0]["metrics"])
            f.close()

    def test_partial_dex_failure_preserves_main_and_native_chart_validation(self):
        def source(kind, **kw):
            if kind == "perpDexs":
                return [None, {"name": "gone"}, {"name": "xyz"}]
            if kw.get("dex") == "gone":
                raise OSError("offline")
            name = "xyz:NVDA" if kw.get("dex") else "BTC"
            return [
                {"universe": [{"name": name}]},
                [dict(markPx="55", openInterest="2", prevDayPx="50")],
            ]

        with (
            tempfile.TemporaryDirectory() as d,
            patch("src.markets.providers.hl", side_effect=source),
            patch.object(MarketFeed, "_enrich", return_value=None),
        ):
            feed = MarketFeed(d)
            try:
                snap = feed.refresh("hyperliquid")
                self.assertEqual(snap["status"], "live")
                self.assertIn("gone", snap["message"])
                self.assertEqual(
                    {r["symbol"] for r in snap["rows"]}, {"BTC", "xyz:NVDA"}
                )
                with self.assertRaises(ValueError):
                    feed.candles("hyperliquid", "unknown", "5m")
                with patch(
                    "src.markets.providers.fetch_bars", return_value=[{"t": 100}]
                ) as read:
                    self.assertEqual(
                        feed.candles("hyperliquid", "xyz:NVDA", "5m"),
                        feed.candles("hyperliquid", "xyz:NVDA", "5m"),
                    )
                    self.assertEqual(read.call_count, 1)
            finally:
                feed.close()

    def test_observed_oi_survives_restart_but_unsupported_window_is_absent(self):
        with tempfile.TemporaryDirectory() as d:
            base = 300000000
            feed = MarketFeed(d)

            def r(t, q):
                return hyper_rows(
                    [
                        {"universe": [{"name": "BTC"}]},
                        [dict(markPx="50", openInterest=str(q))],
                    ],
                    t,
                )

            feed._samples("hyperliquid", r(base, 20), base)
            feed.close()
            other = MarketFeed(d)
            rows = r(base + 300000, 25)
            other._samples("hyperliquid", rows, base + 300000)
            self.assertEqual(rows[0]["metrics"]["oiChange:5m"], 25)
            self.assertEqual(rows[0]["metrics"]["oiDelta:5m"], 250)
            self.assertNotIn("oiChange:1h", rows[0]["metrics"])
            other.close()

    def test_binance_contract_selection_and_actual_funding_period(self):
        def instrument(symbol, kind, status="TRADING"):
            return dict(
                symbol=symbol, contractType=kind, status=status, baseAsset="BTC"
            )

        symbols = [
            instrument("BTCUSDT", "PERPETUAL"),
            instrument("NUSDT", "TRADIFI_PERPETUAL"),
            instrument("Q", "CURRENT_QUARTER"),
            instrument("OLD", "PERPETUAL", "SETTLING"),
        ]
        tick = [
            dict(
                symbol=x["symbol"],
                lastPrice="100",
                closeTime=100000,
                quoteVolume="300",
                count=5,
            )
            for x in symbols
        ]
        rows = binance_rows(
            symbols,
            tick,
            [dict(symbol="BTCUSDT", lastFundingRate=".001", time=100000)],
            {"BTCUSDT": 4},
        )
        self.assertEqual({r["symbol"] for r in rows}, {"BTCUSDT", "NUSDT"})
        self.assertAlmostEqual(rows[0]["metrics"]["funding"], 0.025)
        self.assertNotIn("funding", rows[1]["metrics"])

    def test_hip3_identity_and_oi_quantity_to_notional(self):
        p = [
            {"universe": [{"name": "xyz:NVDA"}, {"name": "OLD", "isDelisted": True}]},
            [
                dict(
                    markPx="50",
                    openInterest="3",
                    funding="-.0001",
                    dayNtlVlm="2400",
                    prevDayPx="40",
                ),
                {},
            ],
        ]
        (asset,) = hyper_rows(p, 100000)
        self.assertEqual(asset["symbol"], "xyz:NVDA")
        self.assertEqual(asset["metrics"]["oi"], 150)
        self.assertEqual(asset["metrics"]["change:1d"], 25)
        self.assertEqual(asset["metrics"]["funding"], -0.01)
