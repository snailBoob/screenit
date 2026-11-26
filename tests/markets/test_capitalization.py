import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.markets.capitalization import MarketCaps, HOUR
from src.markets import providers


class Immediate:
    def wait(self, _):
        return False

    def is_set(self):
        return False


class MarketCapTests(unittest.TestCase):
    def test_exchange_identity_batches_currency_and_restart(self):
        ts = 1795554000000

        def provider(url, headers):
            if "/derivatives/" in url:
                bn = "binance_futures" in url

                def token(s, coin, rwa=None):
                    return dict(
                        contract_type="perpetual",
                        symbol=s + "USDT",
                        base=s,
                        coin_id=coin,
                        rwa_id=rwa,
                    )

                return dict(
                    tickers=[
                        token("BTW", "bitway" if bn else "banana-tape-wall"),
                        token("NVDA", None, "nvidia"),
                        token("SOXL", None, "leveraged-etf"),
                        token("X", "a"),
                        token("X", "b"),
                    ]
                )
            if "/coins/markets?" in url:
                from datetime import datetime, timezone

                return [
                    dict(
                        id=c,
                        market_cap=v,
                        last_updated=datetime.fromtimestamp(
                            ts / 1000, timezone.utc
                        ).isoformat(),
                    )
                    for c, v in [("bitway", 1e7), ("banana-tape-wall", 2e6)]
                ]
            self.assertEqual(headers, {"X-Finnhub-Token": "test-only"})
            return dict(ticker="NVDA", currency="USD", marketCapitalization=100)

        with (
            tempfile.TemporaryDirectory() as d,
            patch.dict(
                os.environ,
                {"SCREENIT_FINNHUB_KEY": "test-only", "SCREENIT_MARKET_CAP": "1"},
            ),
            patch.object(providers, "now", return_value=ts),
            patch.object(providers, "request", side_effect=provider),
        ):
            def db():
                return sqlite3.connect(Path(d) / "cap.db")
            c = MarketCaps(db, Immediate())
            c.update()
            self.assertEqual(c.values["binance", "BTWUSDT"], (1e7, ts, "CoinGecko"))
            self.assertEqual(c.values["hyperliquid", "BTW"], (2e6, ts, "CoinGecko"))
            self.assertEqual(c.values["binance", "NVDAUSDT"], (100e6, ts, "Finnhub"))
            self.assertNotIn(("binance", "XUSDT"), c.values)
            self.assertNotIn(("binance", "SOXLUSDT"), c.values)
            self.assertEqual(c.values, MarketCaps(db, Immediate()).values)
            with patch.object(providers, "now", return_value=ts + 3 * HOUR):
                self.assertFalse(MarketCaps(db, Immediate()).values)
