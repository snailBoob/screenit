import os
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from src.server import Service, Store


@contextmanager
def receiver(code, received):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(
                (
                    self.path,
                    self.rfile.read(int(self.headers["Content-Length"])).decode(),
                    self.headers.get("Title"),
                )
            )
            self.send_response(code)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}/Screenit"
    finally:
        srv.shutdown()
        srv.server_close()
        t.join()


class DeliveryTests(unittest.TestCase):
    def test_real_post_and_no_resend_after_restart(self):
        received = []
        with (
            TemporaryDirectory() as d,
            receiver(200, received) as url,
            patch.dict(os.environ, SCREENIT_NTFY_TOKEN=""),
        ):
            s = Store(Path(d) / "state")
            msg = "Rule α · BTCUSDT · binance · price = 101"
            with s.tx(True) as db:
                db.execute(
                    "INSERT INTO events(ruleName,exchange,symbol,at,message,delivery) VALUES('Rule','binance','BTCUSDT',1,?,'pending')",
                    (msg,),
                )
            self.assertTrue(Service(s, None, url).deliver())
            self.assertEqual(received, [("/Screenit", msg, "Rule")])
            self.assertEqual(s.history()[0]["delivery"], "sent")
            self.assertFalse(Service(Store(s.path), None, url).deliver())
            self.assertEqual(len(received), 1)

    def test_failures_back_off_and_end_in_visible_failed_state(self):
        received = []
        with TemporaryDirectory() as d, receiver(503, received) as url:
            s = Store(Path(d) / "state")
            service = Service(s, None, url)
            with s.tx(True) as db:
                db.execute(
                    "INSERT INTO events(message,delivery) VALUES('test','pending')"
                )
            for t in (0, 5000, 15000, 35000, 75000):
                self.assertTrue(service.deliver(t))
                self.assertFalse(service.deliver(t))
            self.assertEqual(len(received), 5)
            self.assertEqual(s.history()[0]["delivery"], "failed")
