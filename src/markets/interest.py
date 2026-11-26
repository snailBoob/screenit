"""Timestamped Binance quantities. REST history seeds anchors, never a live reading."""

from contextlib import closing
from bisect import bisect_left
import time
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError

from src.contracts import WINDOWS
from . import providers as api
from .metrics import number, pct
from .rolling import MINUTE


class OpenInterest:
    def __init__(self, db, stop):
        self.db, self.stop = db, stop
        self.values = {}
        with closing(db()) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS oi_points(symbol TEXT,at INTEGER,qty REAL,PRIMARY KEY(symbol,at)) WITHOUT ROWID"
            )

    def run(self, symbols, price_for):
        visited = {}
        seeded = {}
        maintenance = 0
        paused = [0.0]

        def sample(s):
            at = api.now()
            try:
                seed = []
                if at - seeded.get(s, 0) > 24 * 3600000:
                    rows = api.bn(
                        "/futures/data/openInterestHist",
                        symbol=s,
                        period="5m",
                        limit=290,
                    )
                    seed = [
                        (s, int(r["timestamp"]), v)
                        for r in rows
                        if (v := number(r.get("sumOpenInterest"))) is not None
                        and v >= 0
                    ]
                    seeded[s] = at
                data = api.bn("/fapi/v1/openInterest", symbol=s)
                stamp = int(data["time"])
                q = number(data["openInterest"])
                price, pt = price_for(s)
                with closing(self.db()) as c, c:
                    if seed:
                        c.executemany(
                            "INSERT OR IGNORE INTO oi_points VALUES(?,?,?)", seed
                        )
                    if (
                        q is not None
                        and q >= 0
                        and -30000 <= api.now() - stamp <= 450000
                    ):
                        c.execute(
                            "INSERT OR REPLACE INTO oi_points VALUES(?,?,?)",
                            (s, stamp, q),
                        )
                        if price and abs(stamp - pt) <= 120000:
                            pts = list(
                                c.execute(
                                    "SELECT at,qty FROM oi_points WHERE symbol=? AND at>=? AND at<? ORDER BY at",
                                    (s, stamp - 1443 * MINUTE, stamp),
                                )
                            )
                            metrics = {"oi": q * price}
                            times = {"oi": min(pt, stamp)}
                            for w, n in WINDOWS.items():
                                target = stamp - n * MINUTE
                                i = bisect_left(pts, (target,))
                                candidates = pts[max(0, i - 1) : i + 1]
                                if not candidates:
                                    continue
                                when, old = min(
                                    candidates, key=lambda p: abs(p[0] - target)
                                )
                                if old > 0 and abs(when - target) <= 150000:
                                    metrics["oiChange:" + w] = pct(q, old)
                                    metrics["oiDelta:" + w] = (q - old) * price
                                    times["oiChange:" + w] = stamp
                                    times["oiDelta:" + w] = min(pt, stamp)
                            self.values[s] = (metrics, times)
            except HTTPError as e:
                if e.code in (418, 429):
                    retry = e.headers.get("Retry-After", "")
                    paused[0] = time.monotonic() + (
                        int(retry) if retry.isdigit() else 60
                    )
            except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
                pass

        with ThreadPoolExecutor(max_workers=4) as pool:
            pending = {}
            while not self.stop.is_set():
                at = api.now()
                ids = symbols()
                for s, f in list(pending.items()):
                    if f.done():
                        f.result()
                        del pending[s]
                if self.stop.wait(max(0, paused[0] - time.monotonic())):
                    break
                if at - maintenance > 600000:
                    with closing(self.db()) as c, c:
                        c.execute(
                            "DELETE FROM oi_points WHERE at<?", (at - 1450 * MINUTE,)
                        )
                    maintenance = at
                options = [
                    s
                    for s in ids
                    if s not in pending and at - visited.get(s, 0) >= MINUTE
                ]
                if len(pending) < 4 and options:
                    s = min(options, key=lambda x: visited.get(x, 0))
                    visited[s] = at
                    pending[s] = pool.submit(sample, s)
                self.stop.wait(0.34)  # under 1000 statistics requests per five minutes
