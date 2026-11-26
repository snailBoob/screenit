"""Test-only exchange input and loopback notification sink. No external requests."""

import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import signal
import sys

from src.server import Service, Store, make_http
from src.server.store import now
from src.markets.providers import MS


class Feed:
    def __init__(self, path):
        self.price = path / "price"

    def refresh(self, exchange):
        stamp = now()
        price = float(self.price.read_text())
        native = (
            ["BTCUSDT", "ETHUSDT"] if exchange == "binance" else ["BTC", "xyz:NVDA"]
        )
        rows = [
            dict(
                symbol=s,
                label=s,
                at=stamp,
                metrics={
                    "price": price + i * 10,
                    "funding": 0.003,
                    "volume:1d": 10000000 / (i + 1),
                    "oi": 3000000,
                    "change:1d": 2 - i * 3,
                    "change:1h": 5 - i * 10,
                    "volume:1h": 26000,
                    "oiChange:1h": 5,
                },
                trend=[80, 90, None, 93, 88, 96],
            )
            for i, s in enumerate(native)
        ]
        return dict(exchange=exchange, asOf=stamp, status="live", message="", rows=rows,
                    fiveReady=1 if price == 90 else len(rows))

    def trend(self, exchange, symbol):
        end = now() // 1800000 * 1800000
        return {'end': end, 'points': [b['c'] for b in self.candles(exchange,symbol,'30m',48,end)]}

    def candles(self, exchange, symbol, interval, limit=160, before=None):
        step=MS[interval]; clock=self.price.parent/'clock'
        end=int(clock.read_text()) if clock.exists() else now()
        last=((end if before is None else min(end,before-1))//step)*step
        return [
            dict(t=t, o=90+t//step%30, h=95+t//step%30, l=89+t//step%30, c=92+t//step%30, v=340+t//step%30)
            for t in range(last-(limit-1)*step,last+step,step) if t>0
        ]


def main():
    data = Path(sys.argv[1])
    os.environ.pop("SCREENIT_NTFY_TOKEN", None)

    class Sink(BaseHTTPRequestHandler):
        def do_POST(self):
            with (data / "delivered").open("a") as f:
                f.write(
                    self.path
                    + " "
                    + self.rfile.read(int(self.headers["Content-Length"])).decode()
                    + "\n"
                )
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    receiver = HTTPServer(("127.0.0.1", 0), Sink)
    (data / 'ntfy-url').write_text(f'http://127.0.0.1:{receiver.server_port}')
    threading.Thread(target=receiver.serve_forever, daemon=True).start()
    svc = Service(
        Store(data / "test.db"),
        Feed(data),
        f"http://127.0.0.1:{receiver.server_port}/Screenit",
        0.20,
    )
    http = make_http(svc, "127.0.0.1", 0, "src/ui")
    svc.start()
    print(http.server_port, flush=True)
    signal.signal(
        signal.SIGTERM,
        lambda *_: threading.Thread(target=http.shutdown, daemon=True).start(),
    )
    try:
        http.serve_forever()
    finally:
        http.server_close()
        svc.stop()
        receiver.shutdown()
        receiver.server_close()


if __name__ == "__main__":
    main()
