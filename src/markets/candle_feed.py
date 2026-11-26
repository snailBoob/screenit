"""Bounded live minute history: prioritize a short market-wide seed, then fill depth.

The same cumulative OHLC observations feed the HTTP snapshot, SSE and alert engine.
No trading endpoints, per-browser subscriptions or guessed empty bars.
"""

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError

from . import providers as api
from .rolling import DAY, MINUTE, MinuteSeries

LOG = logging.getLogger(__name__)


class CandleFeed:
    def __init__(self, venue, stop, symbols):
        self.venue, self.stop, self.symbols = venue, stop, symbols
        self.bn = venue == "binance"
        self.reference = "BTCUSDT" if self.bn else "BTC"
        self.lock = threading.RLock()
        self.books = {}
        self.ready = set()
        self.throttle = threading.Lock()
        self.next_request = {}
        self.pause_until = 0.0
        self.threads = []

    def start(self):
        for work in (
            self.seed,
            self.deep,
            self.stream,
            *((self.inactive,) if self.bn else ()),
        ):
            t = threading.Thread(
                target=work, name=f"{self.venue}-minutes-{work.__name__}", daemon=True
            )
            self.threads.append(t)
            t.start()

    def metrics(self, symbol, now):
        with self.lock:
            series = self.books.get(symbol)
            btc = self.books.get(self.reference)
            if not series:
                return 0, {}, 0
            at, m = series.metrics(now, btc)
            if "trades:5m" in m:
                self.ready.add(symbol)
            return at, m, min(at, btc.at) if btc else 0

    def accept(self, s, rows, stamp):
        with self.lock:
            book = self.books.get(s)
            if book is None:
                book = self.books[s] = MinuteSeries(self.venue)
            for b, final in rows:
                book.put(b, stamp, final)

    def inactive(self):
        while not self.stop.is_set():
            if self.books and time.monotonic() >= self.pause_until:
                try:
                    start = api.now()
                    rows = api.bn("/fapi/v2/ticker/price")
                    end = api.now()
                    exchange = max(r["time"] for r in rows)
                    asof = min(start, exchange)
                    if end - asof < 3500 and exchange - end < 3000:
                        with self.lock:
                            for r in rows:
                                b = self.books.get(r["symbol"])
                                if b:
                                    b.confirm_inactive(
                                        r["time"], float(r["price"]), asof
                                    )
                except HTTPError as e:
                    if e.code in (418, 429):
                        delay = e.headers.get("Retry-After", "")
                        self.pause_until = time.monotonic() + (
                            int(delay) if delay.isdigit() else 60
                        )
                except (OSError, KeyError, TypeError, ValueError):
                    pass
            self.stop.wait(4)

    def wait_budget(self, cost, lane):
        # Leave headroom for ticker discovery, OI, chart requests and other clients.
        with self.throttle:
            # Reserve a short-seed/repair budget independent of deep history. A large
            # history page must not delay forming-window recovery for hundreds of rows.
            interval = (
                (0.065 if lane == "seed" else 0.095)
                if self.bn
                else (0.105 if lane == "seed" else 0.19)
            )
            due = max(
                self.next_request.get(lane, 0), self.pause_until, time.monotonic()
            )
            self.next_request[lane] = due + cost * interval
        return (
            not self.stop.wait(max(0, due - time.monotonic()))
            and time.monotonic() >= self.pause_until
        )

    def backfill(self, s, limit, before=None):
        cost = (
            (1 if limit < 100 else 2 if limit < 500 else 5 if limit <= 1000 else 10)
            if self.bn
            else 20 + limit // 60
        )
        if not self.wait_budget(cost, "seed" if before is None else "deep"):
            return False
        at = api.now()
        end = before if before is not None else at + 1
        try:
            bars = api.fetch_bars(self.venue, s, "1m", limit, before=end)
            self.accept(s, [(b, b["t"] + MINUTE <= at) for b in bars], at)
            return bool(bars)
        except HTTPError as exc:
            if exc.code in (418, 429):
                retry = exc.headers.get("Retry-After", "")
                self.pause_until = time.monotonic() + (
                    int(retry) if retry.isdigit() else 60
                )
        except (OSError, ValueError, KeyError):
            pass
        return False

    def seed(self):
        visited = {}
        pending = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            while not self.stop.is_set():
                for s, f in list(pending.items()):
                    if f.done():
                        f.result()
                        del pending[s]
                if len(pending) >= 4:
                    self.stop.wait(0.05)
                    continue
                symbols = tuple(self.symbols())
                live = set(symbols)
                at = api.now()
                m = at // MINUTE
                with self.lock:
                    for s in self.books.keys() - live:
                        self.books.pop(s)
                    self.ready.intersection_update(live)
                    missing = [
                        s
                        for s in symbols
                        if s not in pending
                        and (
                            not (b := self.books.get(s))
                            or not (
                                b.has(m)
                                and all(b.has(m - i, True) for i in range(1, 5))
                            )
                        )
                    ]
                if not missing:
                    self.stop.wait(0.5)
                    continue
                s = min(missing, key=lambda x: visited.get(x, 0))
                if at - visited.get(s, 0) < 10000:
                    self.stop.wait(0.5)
                    continue
                visited[s] = at
                with self.lock:
                    b=self.books.get(s)
                    limit=(1+max((i for i in range(5) if not b.has(m-i, i>0)),default=0)
                           if b and s in self.ready else 90)
                pending[s] = pool.submit(self.backfill, s, limit)

    def deep(self):
        # One pass per symbol (including the reference); do not let one newly listed
        # or illiquid market with short history monopolize the repair queue.
        visited = {}
        while not self.stop.is_set():
            at = api.now()
            symbols = list(self.symbols())
            m = at // MINUTE
            if not symbols:
                self.stop.wait(1)
                continue
            order = (
                list(dict.fromkeys([self.reference, *symbols]))
                if self.reference in symbols
                else symbols
            )
            s = min(order, key=lambda x: visited.get(x, 0))
            age = at - visited.get(s, 0)
            if age < 60000:
                self.stop.wait(2)
                continue
            visited[s] = at
            with self.lock:
                b = self.books.get(s)
                length = 2 * DAY if self.bn else DAY
                missing = next(
                    (
                        i
                        for i in range(m - 1, m - length, -1)
                        if not b or not b.has(i, True)
                    ),
                    None,
                )
            if missing is None:
                continue
            # Fill the newest missing minutes first; individual pages stay within exchange limits.
            while missing > m - length and not self.stop.is_set():
                n = min(1440, missing - (m - length))
                end = (missing + 1) * MINUTE
                if not self.backfill(s, n, end):
                    break
                missing -= n

    def stream(self):
        from websocket import create_connection

        delay = 1
        while not self.stop.is_set():
            symbols = sorted(self.symbols())
            if not symbols:
                self.stop.wait(1)
                continue
            sock = None
            previous = {}
            known = set(symbols)
            try:
                url = (
                    "wss://fstream.binance.com/market/ws"
                    if self.bn
                    else "wss://api.hyperliquid.xyz/ws"
                )
                sock = create_connection(url, timeout=30, suppress_origin=True)
                def subscribe(symbols, add):
                  if self.bn:
                    for i in range(0, len(symbols), 150):
                        sock.send(
                            json.dumps(
                                dict(
                                    method="SUBSCRIBE" if add else "UNSUBSCRIBE",
                                    id=i + 1,
                                    params=[
                                        s.lower() + "@kline_1m"
                                        for s in symbols[i : i + 150]
                                    ],
                                )
                            )
                        )
                        if self.stop.wait(0.2):
                            return
                  else:
                    for s in symbols:
                        sock.send(
                            json.dumps(
                                dict(
                                    method="subscribe" if add else "unsubscribe",
                                    subscription=dict(
                                        type="candle", coin=s, interval="1m"
                                    ),
                                )
                            )
                        )
                        if self.stop.wait(0.04):
                            return
                subscribe(symbols, True)
                check = time.monotonic() + 60
                while not self.stop.is_set():
                    if time.monotonic() >= check:
                        updated=set(self.symbols())
                        subscribe(sorted(known-updated),False)
                        subscribe(sorted(updated-known),True)
                        for removed in known-updated:previous.pop(removed,None)
                        known=updated
                        check = time.monotonic() + 60
                    msg = json.loads(sock.recv())
                    stamp = api.now()
                    if "code" in msg or msg.get("channel") == "error":
                        raise ValueError("Subscription rejected")
                    if self.bn:
                        k = msg.get("k")
                        if not k:
                            continue
                        s = msg["s"]
                        obs = int(msg["E"])
                        t = int(k["t"])
                        final = k["x"]
                        b = dict(
                            t=t,
                            o=float(k["o"]),
                            c=float(k["c"]),
                            n=int(k["n"]),
                            v=float(k["q"]),
                            d=2 * float(k["Q"]) - float(k["q"]),
                        )
                    else:
                        if msg.get("channel") != "candle":
                            continue
                        k = msg["data"]
                        s = k["s"]
                        obs = stamp
                        t = int(k["t"])
                        final = False
                        b = api.hl_bar(k)
                    if s not in known or t > stamp or stamp - t > 3 * MINUTE:
                        continue
                    with self.lock:
                        if (
                            not self.bn
                            and previous.get(s) == t // MINUTE - 1
                            and s in self.books
                        ):
                            self.books[s].seal(t // MINUTE - 1)
                        previous[s] = max(previous.get(s, -1), t // MINUTE)
                        self.accept(s, [(b, final)], obs)
                    delay = 1
            except Exception as exc:
                if not self.stop.is_set():
                    LOG.warning(
                        "%s candle stream reconnect: %s", self.venue, type(exc).__name__
                    )
            finally:
                if sock:
                    sock.close(timeout=1)
                # A lost partial may not seed a crossing or be sealed by a different socket.
                with self.lock:
                    for s in previous:
                        b = self.books.get(s)
                        if b and b.minute >= 0 and b.tags[b.minute % b.size] < 0:
                            b.tags[b.minute % b.size] = 0
                            b.version += 1
                            b.result_key = None
            self.stop.wait(delay)
            delay = min(30, delay * 2)
