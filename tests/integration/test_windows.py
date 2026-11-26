import tempfile
import unittest
from pathlib import Path

from src.markets import MarketFeed
from src.markets.rolling import MINUTE
from src.server import Service, Store


class MarketWindowIntegration(unittest.TestCase):
    def test_binance_daily_percentage_stays_with_ticker(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as d:
            feed = MarketFeed(d)
            at = 10000 * MINUTE
            row = dict(symbol="BTCUSDT", at=at, metrics={"price": 100, "change:1d": 3.5})
            for candles in ({}, {"change:1d": 4.2}):
                with patch.object(feed.activity["binance"], "metrics", return_value=(at, candles, at)):
                    changes, _ = feed.window_patch("binance", [row], at)
                    self.assertNotIn("change:1d", changes.get("BTCUSDT", ({}, {}))[0])
            feed.close()

    def test_rest_sse_and_background_rule_observe_one_cumulative_revision(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as d:
            feed = MarketFeed(d)
            store = Store(Path(d) / "workspace.db")
            svc = Service(store, feed, None)
            store.change_rule(
                dict(
                    exchange="binance",
                    symbol="BTCUSDT",
                    enabled=True,
                    name="Five-minute trades",
                    repeat="once",
                    groups=[[dict(metric="trades:5m", op="cross_up", value=25)]],
                )
            )
            book = svc.markets["binance"]
            clock = 10000 * MINUTE

            def candle(i, n, stamp, final):
                feed.activity["binance"].accept(
                    "BTCUSDT",
                    [
                        (
                            dict(
                                t=clock + i * MINUTE,
                                o=100.0,
                                c=110.0,
                                v=10.0 * n,
                                n=n,
                                d=0.0,
                            ),
                            final,
                        )
                    ],
                    stamp,
                )

            for i in range(4):
                candle(i, 4, clock + (i + 1) * MINUTE, True)
            at = clock + 4 * MINUTE + 1000
            candle(4, 6, at, False)
            # Price intentionally differs from candle.close; CHG $ must use ticker price.
            row = dict(
                symbol="BTCUSDT",
                at=at,
                metrics={"price": 120.0},
                metricAt={"price": at},
            )
            view = book.replace(
                dict(exchange="binance", rows=[row], status="live", asOf=at),
                at,
                feed.window_patch,
            )
            svc.cache["binance"] = view
            svc.engine.tick(view, at)
            self.assertAlmostEqual(view["rows"][0]["metrics"]["changeUsd:5m"], 12.0)
            self.assertEqual(view["rows"][0]["metrics"]["trades:5m"], 22)
            seq = book.seq
            at += 1500
            candle(4, 10, at, False)
            with patch("src.server.now", return_value=at):
                svc.window_cycle("binance")
                doc = svc.snapshot("binance")
            value = doc["rows"][0]["metrics"]["trades:5m"]
            self.assertEqual(value, 26)
            _, kind, msg = book.read(seq)
            self.assertEqual(kind, "windows")
            self.assertEqual(msg["windows"]["BTCUSDT"][0]["trades:5m"], value)
            self.assertEqual(
                [e["message"] for e in store.history()],
                ["BTCUSDT — TRD 5M crossed above 25"],
            )
            feed.close()
