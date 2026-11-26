import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.server import Service, Store, make_http
from tests.e2e.fixture import Feed


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = TemporaryDirectory()
        base = Path(cls.tmp.name)
        (base / "price").write_text("90")
        cls.svc = Service(Store(base / "db"), Feed(base), "http://127.0.0.1:1/Screenit")
        cls.svc.cycle("binance")
        cls.http = make_http(cls.svc, "127.0.0.1", 0, "src/ui")
        cls.url = "http://127.0.0.1:" + str(cls.http.server_port)
        cls.thread = threading.Thread(target=cls.http.serve_forever)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.thread.join()
        cls.http.server_close()
        cls.tmp.cleanup()

    def req(self, path, method="GET", headers=None, body=None):
        req = Request(
            self.url + path,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
            data=json.dumps(body).encode() if body is not None else None,
        )
        try:
            with urlopen(req) as response:
                return response.status, response.read(), response.headers
        except HTTPError as e:
            return e.code, e.read(), e.headers

    def test_actual_http_and_static_boundaries(self):
        code, body, headers = self.req("/")
        self.assertEqual(code, 200)
        self.assertIn(b"Perpetual futures screener", body)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(self.req("/app.mjs")[2].get_content_type(), "text/javascript")
        self.assertEqual(self.req("/../server/store.py")[0], 404)
        self.assertEqual(
            self.req("/api/settings", headers={"Host": "foreign.invalid"})[0], 403
        )
        self.assertEqual(
            self.req(
                "/api/settings",
                "PATCH",
                {"Origin": "https://other.invalid"},
                {"revision": 1, "changes": {}},
            )[0],
            403,
        )
        self.assertEqual(
            self.req(
                "/api/settings",
                "PATCH",
                {"Content-Type": "text/plain"},
                {"revision": 1, "changes": {}},
            )[0],
            400,
        )
        self.assertEqual(
            self.req("/api/candles?exchange=binance&symbol=UNKNOWN&interval=5m")[0], 400
        )
        r = json.loads(
            self.req("/api/candles?exchange=binance&symbol=BTCUSDT&interval=5m")[1]
        )
        self.assertEqual(len(r["candles"]), 160)
        start = r['candles'][0]['t'];base='/api/candles?exchange=binance&symbol=BTCUSDT&interval=5m'
        code,body,_=self.req(base+f'&before={start}&limit=20');self.assertEqual(code,200)
        page=json.loads(body)['candles'];self.assertEqual(len(page),20);self.assertEqual(page[-1]['t'],start-300000)
        self.assertEqual(self.req(base+'&limit=100000')[0],400)

    def test_failure_isolated_and_last_fresh_data_identified(self):
        from unittest.mock import patch

        self.svc.cycle("hyperliquid")
        with patch.object(self.svc.feed, "refresh", side_effect=OSError("upstream")):
            self.svc.cycle("hyperliquid")
        self.assertEqual(self.svc.snapshot("binance")["status"], "live")
        other = self.svc.snapshot("hyperliquid")
        self.assertEqual(other["status"], "stale")
        self.assertTrue(other["rows"])
