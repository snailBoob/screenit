"""Read public feeds only. Never starts the alerting Service."""

import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.markets import MarketFeed


def main():
    with tempfile.TemporaryDirectory() as data:
        feed = MarketFeed(data)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                for s in pool.map(feed.refresh, ["binance", "hyperliquid"]):
                    venue = s["exchange"]
                    print(
                        f"{venue}: {s['status']}, {len(s['rows'])} contracts; {s['message']}"
                    )
                    assert (
                        s["status"] == "live"
                        and s["rows"]
                        and any(r["metrics"].get("price", 0) > 0 for r in s["rows"])
                    )
                    if venue == "hyperliquid":
                        assert any(":" in r["symbol"] for r in s["rows"]), (
                            "HIP-3 markets missing"
                        )
            for v, sym in [("binance", "BTCUSDT"), ("hyperliquid", "BTC")]:
                bars = feed.candles(v, sym, "15m")
                assert len(bars) >= 2 and bars[0]["t"] < bars[-1]["t"]
                print(f"{sym}: {len(bars)} live candles")
        finally:
            feed.close()


if __name__ == "__main__":
    main()
