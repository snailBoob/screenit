import json
import logging
import mimetypes
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlsplit

from src.contracts import EXCHANGES, INTERVALS, catalog, defaults
from .store import Conflict
from .validation import require


def make_http(service, host, port, ui_dir):
    root = Path(ui_dir).resolve()
    # HTTP/1 browsers normally allow six connections per origin. Leave slots
    # for navigation, assets and API calls even with multiple open tabs.
    stream_counts = {}
    stream_lock = Lock()
    allowed = {"localhost", "127.0.0.1", "::1"} | {
        h.strip().lower()
        for h in os.getenv("SCREENIT_ALLOWED_HOSTS", "").split(",")
        if h.strip()
    }

    class Handler(BaseHTTPRequestHandler):
        server_version = "Screenit"
        sys_version = ""

        def setup(self):
            super().setup()
            self.connection.settimeout(12)

        def log_message(self, fmt, *args):
            pass

        def send(self, status, body, kind="application/json; charset=utf-8"):
            content = (
                body
                if isinstance(body, bytes)
                else json.dumps(
                    body, allow_nan=False, ensure_ascii=False, separators=(",", ":")
                ).encode()
            )
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-src https://www.tradingview-widget.com; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            )
            self.end_headers()
            self.wfile.write(content)

        def body(self):
            require(
                self.headers.get_content_type() == "application/json", "JSON required"
            )
            n = int(self.headers.get("Content-Length", "0"))
            require(0 < n <= 131072, "Invalid message size")
            obj = json.loads(self.rfile.read(n))
            require(isinstance(obj, dict))
            return obj

        def stream(self,venue):
            peer = self.client_address[0]
            with stream_lock:
                available = stream_counts.get(peer, 0) < 3
                if available:
                    stream_counts[peer] = stream_counts.get(peer, 0) + 1
            if not available:
                # EventSource treats 204 as terminal; the client uses snapshots.
                return self.send(204, b'')
            try:
                self.serve_stream(venue)
            finally:
                with stream_lock:
                    stream_counts[peer] -= 1
                    if not stream_counts[peer]:
                        del stream_counts[peer]

        def serve_stream(self,venue):
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Accel-Buffering','no')
            self.end_headers()
            last=-1
            try:
                self.wfile.write(b'retry: 1500\n\n')
                while not service.stop_event.is_set():
                    last,kind,data=service.markets[venue].read(last)
                    if data is None:frame=b': heartbeat\n\n'
                    else:frame=('event: '+kind+'\ndata: '+json.dumps(data,allow_nan=False,separators=(',',':'))+'\n\n').encode()
                    self.wfile.write(frame);self.wfile.flush()
            except (OSError,TimeoutError):pass

        def handle_request(self):
            verb = self.command
            rawhost = self.headers.get("Host", "")
            authority = urlsplit("//" + rawhost)
            if (
                authority.hostname not in allowed
                or authority.username
                or authority.password
                or authority.path
                or authority.query
                or authority.fragment
            ):
                return self.send(403, {"error": "Unknown host"})
            origin = self.headers.get("Origin")
            mutation = verb != "GET"
            if mutation and (
                (
                    origin is not None
                    and origin not in ("http://" + rawhost, "https://" + rawhost)
                )
                or self.headers.get("Sec-Fetch-Site") == "cross-site"
            ):
                return self.send(403, {"error": "Invalid request origin"})
            url = urlsplit(self.path)
            path = url.path
            query = parse_qs(url.query, max_num_fields=8)
            store = service.store
            if verb == "GET":
                if path == "/api/catalog":
                    return self.send(
                        200, {**catalog(), "defaultColumns": defaults()["columns"]}
                    )
                if path == "/api/health":
                    return self.send(
                        200,
                        {
                            "ok": True,
                            "exchanges": {
                                v: service.snapshot(v)["status"] for v in EXCHANGES
                            },
                        },
                    )
                if path == "/api/settings":
                    return self.send(200, store.get_settings())
                if path == "/api/alerts":
                    return self.send(200, {"rules": store.rules()})
                if path == "/api/history":
                    return self.send(200, {"events": store.history()})
                if path in ("/api/market", "/api/candles", "/api/market/stream", "/api/trend"):
                    venue = query.get("exchange", [""])[0]
                    require(venue in EXCHANGES, "Unknown exchange")
                    if path == '/api/trend':
                        return self.send(200, service.feed.trend(venue, query.get('symbol', [''])[0]))
                    if path=='/api/market/stream':return self.stream(venue)
                    snap = service.snapshot(venue)
                    if path == "/api/market":
                        return self.send(200, snap)
                    sym = query.get("symbol", [""])[0]
                    interval = query.get("interval", [""])[0]
                    require(
                        interval in INTERVALS
                        and any(r["symbol"] == sym for r in snap["rows"]),
                        "Unknown instrument or interval",
                    )
                    limit = int(query.get("limit", ["160"])[0]); require(1 <= limit <= (2881 if venue=='hyperliquid' else 499), "Invalid candle limit")
                    before = int(query["before"][0]) if "before" in query else None
                    require(before is None or before > 0, "Invalid candle cursor")
                    return self.send(200, {"candles": service.feed.candles(venue, sym, interval, limit, before)})
                name = "index.html" if path == "/" else path[1:]
                f = (root / name).resolve()
                if (
                    re.fullmatch(r"[a-zA-Z0-9_-]+\.(?:html|mjs|js|css|svg|ico|woff2|png|webmanifest)", name)
                    and root in f.parents
                    and f.is_file()
                ):
                    return self.send(
                        200,
                        f.read_bytes(),
                        (
                            "text/javascript"
                            if name.endswith(".mjs")
                            else mimetypes.guess_type(name)[0]
                        )
                        or "application/octet-stream",
                    )
            if verb == "PATCH" and path == "/api/settings":
                obj = self.body()
                return self.send(
                    200, store.patch(obj.get("revision"), obj.get("changes"))
                )
            if verb == "POST" and path == "/api/alerts":
                return self.send(201, store.change_rule(self.body()))
            match = re.fullmatch(r"/api/alerts/([0-9a-f]{32})", path)
            if match and verb in ("PUT", "DELETE"):
                obj = (
                    {"revision": int(query.get("revision", ["-1"])[0])}
                    if verb == "DELETE"
                    else self.body()
                )
                return self.send(
                    200, store.change_rule(obj, match[1], verb == "DELETE")
                )
            self.send(404, {"error": "Not found"})

        def dispatch(self):
            try:
                self.handle_request()
            except Conflict as e:
                self.send(409, e.current)
            except KeyError:
                self.send(404, {"error": "Not found"})
            except (TypeError, ValueError, OverflowError, RecursionError) as e:
                self.send(400, {"error": str(e)[:140] or "Invalid input"})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except OSError:
                self.send(503, {"error": "Data source temporarily unavailable"})
            except Exception:
                logging.getLogger(__name__).exception("HTTP request failed")
                self.send(500, {"error": "Internal server error"})

        do_GET = do_PATCH = do_POST = do_PUT = do_DELETE = dispatch

    return ThreadingHTTPServer((host, port), Handler)
