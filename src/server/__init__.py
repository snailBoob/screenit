import logging
import os
import threading
from urllib.request import build_opener, HTTPRedirectHandler, Request

from src.contracts import EXCHANGES
from .alerts import Engine
from .http import make_http
from .live import LiveMarket
from .store import Store, now

__all__ = ["Service", "Store", "make_http"]

LOG = logging.getLogger(__name__)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Service:
    def __init__(self, store, feed, notify_url, poll_seconds=30):
        self.store = store
        self.feed = feed
        self.notify_url = notify_url
        self.poll_seconds = poll_seconds
        self.stop_event = threading.Event()
        self.work = []
        self.cache = {
            v: dict(
                exchange=v,
                asOf=None,
                status="warming",
                rows=[],
                message="Waiting for the first market update…",
            )
            for v in EXCHANGES
        }
        self.engine = Engine(store)
        self.markets = {v:LiveMarket(self.cache[v]) for v in EXCHANGES}
        self.tick_lock = {v:threading.Lock() for v in EXCHANGES}

    def cycle(self, venue):
        try:
            if hasattr(self.feed, "set_focus"):
                ids = [
                    r["symbol"]
                    for r in self.store.rules()
                    if r["enabled"] and r["exchange"] == venue and r["symbol"]
                ]
                ids.extend(
                    f.split(":", 1)[1]
                    for f in self.store.get_settings()["settings"]["favorites"]
                    if f.startswith(venue + ":")
                )
                self.feed.set_focus(venue, ids)
            snap = self.feed.refresh(venue)
        except Exception as e:
            LOG.warning("Market refresh %s: %s", venue, type(e).__name__)
            previous = self.cache[venue]
            snap = {
                **previous,
                "status": "stale" if previous["rows"] else "error",
                "message": "Exchange unavailable. Retrying automatically.",
            }
        with self.tick_lock[venue]:
            self.cache[venue] = self.markets[venue].replace(snap,now(),getattr(self.feed,'window_patch',None))
            self.engine.tick(self.cache[venue],now())

    def on_quotes(self,venue,quotes):
        with self.tick_lock[venue]:
            snap=self.markets[venue].update(quotes,now())
            if snap is not None:
                self.cache[venue]=snap
                self.engine.tick(snap,now())

    def snapshot(self, venue):
        snap = self.cache[venue]
        if snap["status"] == "live" and now() - snap["asOf"] > 120000:
            return {
                **snap,
                "status": "stale",
                "message": "The latest price update is stale.",
            }
        return snap

    def window_cycle(self, venue):
        with self.tick_lock[venue]:
            market=self.markets[venue];at=now()
            if not market.snapshot['rows']:return
            patch,ready=self.feed.window_patch(venue,market.snapshot['rows'],at)
            snap=market.windows(patch,ready)
            if snap is not None:
                self.cache[venue]=snap
                self.engine.tick(snap,at)

    def deliver(self, stamp=None):
        stamp = now() if stamp is None else stamp
        with self.store.tx() as db:
            ev = db.execute(
                "SELECT * FROM events WHERE delivery='pending' AND due<=? ORDER BY id LIMIT 1",
                (stamp,),
            ).fetchone()
        if not ev:
            return False
        try:
            destination = ev['destination'] or self.notify_url  # pre-0.1.1 pending events
            if not destination:
                raise ValueError('No notification destination configured')
            title = ev['ruleName'] or 'Screenit Alert'
            headers = {"Title": title.encode('utf-8'), "Content-Type": "text/plain; charset=utf-8"}
            token = os.environ.get("SCREENIT_NTFY_TOKEN")
            if token and destination == self.notify_url:
                headers["Authorization"] = "Bearer " + token
            req = Request(
                destination,
                data=ev["message"].encode(),
                headers=headers,
                method="POST",
            )
            with build_opener(NoRedirect()).open(req, timeout=6) as res:
                if not 200 <= res.status < 300:
                    raise OSError("ntfy")
            state = "sent"
        except (OSError, ValueError):
            state = "failed" if ev["tries"] >= 4 else "pending"
        with self.store.tx(True) as db:
            db.execute(
                "UPDATE events SET delivery=?,tries=tries+1,due=? WHERE id=?",
                (state, stamp + min(300000, 5000 * 2 ** ev["tries"]), ev["id"]),
            )
        return True

    def start(self):
        if hasattr(self.feed,'start_quotes'):
            self.feed.start_quotes(self.on_quotes)
        def loop(fn, delay):
            while not self.stop_event.is_set():
                try:
                    busy = fn()
                except Exception:
                    LOG.exception("Background task interrupted")
                    busy = False
                self.stop_event.wait(0.08 if busy else delay)

        for target, delay in [
            *((lambda v=v: self.cycle(v), self.poll_seconds) for v in EXCHANGES),
            *((lambda v=v: self.window_cycle(v), 2.5) for v in EXCHANGES if hasattr(self.feed,'window_patch')),
            (self.deliver, 0.6),
        ]:
            t = threading.Thread(target=loop, args=(target, delay), daemon=True)
            self.work.append(t)
            t.start()

    def stop(self):
        self.stop_event.set()
        if hasattr(self.feed, "close"):
            self.feed.close()
        for t in self.work:
            t.join(timeout=9)
