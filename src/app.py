"""Entrypoint for the local process and single-container deployment."""

import logging
import os
from pathlib import Path
import signal
import threading

from .markets import MarketFeed
from .server import Service, Store, make_http


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    data = Path(os.getenv("SCREENIT_DATA", "data"))
    data.mkdir(parents=True, exist_ok=True)
    service = Service(
        Store(data / "screenit.sqlite3"),
        MarketFeed(data),
        os.getenv("SCREENIT_NTFY_TRUSTED_URL"),
        max(10, float(os.getenv("SCREENIT_POLL_SECONDS", "30"))),
    )
    http = make_http(
        service,
        os.getenv("SCREENIT_BIND", "127.0.0.1"),
        int(os.getenv("SCREENIT_PORT", "8080")),
        Path(__file__).with_name("ui"),
    )

    def shutdown(*_):
        threading.Thread(target=http.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    logging.info("Screenit is listening on %s:%d", *http.server_address)
    service.start()
    try:
        http.serve_forever()
    finally:
        http.server_close()
        service.stop()


if __name__ == "__main__":
    main()
