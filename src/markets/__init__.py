import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from src.contracts import EXCHANGES, INTERVALS, WINDOWS, metric_ttl
from . import providers as api
from .metrics import STEP, pct
from .rolling import MINUTE, KEY, owned
from .candle_feed import CandleFeed
from .capitalization import MarketCaps, HOUR
from .interest import OpenInterest

WINDOW_KEYS = {v: owned(v) for v in EXCHANGES}
CONTEXT_KEYS = {stem+':'+w for stem in ('oiChange','oiDelta','volChange','volChangeUsd') for w in WINDOWS}


class MarketFeed:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "market.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.done = threading.Event()
        self.threads = {}
        self.known = {v: [] for v in EXCHANGES}
        self.activity = {v: CandleFeed(v,self.done,lambda v=v:self.history_symbols(v)) for v in EXCHANGES}
        self.prices = {}
        self.context_anchors = {}
        self.hl_universes = {}
        self.index = {v: set() for v in EXCHANGES}
        self.catalog = {}
        self.charts = {}
        self.focus = {v: [] for v in EXCHANGES}
        self.priority = {v: [] for v in EXCHANGES}
        self.chart_slots = threading.BoundedSemaphore(3)
        self.trend_cache = {}
        self.trend_slots = threading.BoundedSemaphore(4)
        with closing(self.db()) as db:
            db.executescript("""PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS observed(venue TEXT,bucket INTEGER,symbol TEXT,price REAL,qty REAL,PRIMARY KEY(venue,bucket,symbol)) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS day_samples(bucket INTEGER,symbol TEXT,volume REAL,PRIMARY KEY(bucket,symbol)) WITHOUT ROWID;""")
        self.caps = MarketCaps(self.db,self.done)
        self.interest = OpenInterest(self.db,self.done)

    def db(self):
        return sqlite3.connect(self.path, timeout=12)

    def cached(self, key, ttl, get):
        current = api.now()
        t, val = self.catalog.get(key, (0, None))
        if current - t > ttl:
            val = get()
            self.catalog[key] = current, val
        return val

    def refresh(self, exchange):
        if exchange not in EXCHANGES:
            raise ValueError("Unknown exchange")
        message = ""
        if exchange == "binance":
            meta = self.cached(
                "binance", 3600000, lambda: api.bn("/fapi/v1/exchangeInfo")["symbols"]
            )
            try:
                periods = self.cached(
                    "periods",
                    1800000,
                    lambda: {
                        x["symbol"]: int(x["fundingIntervalHours"])
                        for x in api.bn("/fapi/v1/fundingInfo")
                    },
                )
            except (OSError, ValueError, KeyError):
                periods = None
                message = "Funding intervals are temporarily unavailable."
            tick = api.bn("/fapi/v1/ticker/24hr")
            try:
                prem = api.bn("/fapi/v1/premiumIndex")
            except (OSError, ValueError):
                prem = []
                message = "Funding data is temporarily unavailable."
            rows = api.binance_rows(meta, tick, prem, periods)
        else:
            try:
                dexes = self.cached(
                    "dexes",
                    900000,
                    lambda: [
                        v["name"] for v in api.hl("perpDexs") if v and v.get("name")
                    ],
                )
            except (OSError, ValueError):
                dexes = self.catalog.get('dexes', (0, []))[1]
                message = "HIP-3 market list is temporarily unavailable."

            def fetch(dex):
                try:
                    start = api.now()
                    packet = api.hl("metaAndAssetCtxs", **({"dex": dex} if dex else {}))
                    rows = api.hyper_rows(packet, start)
                    self.hl_universes[dex] = packet[0]
                    return rows, None
                except (ValueError, OSError, KeyError, TypeError):
                    return [], dex or "main market"

            with ThreadPoolExecutor(max_workers=4) as pool:
                parts = list(pool.map(fetch, ["", *dexes]))
            rows = [r for part, _ in parts for r in part]
            failures = [name for _, name in parts if name]
            if failures:
                message = "Market unavailable: " + ", ".join(failures)
            retained = [m['name'] for dex, (_, failure) in zip(['', *dexes], parts)
                        if failure for m in self.hl_universes.get(dex, {}).get('universe', [])
                        if not m.get('isDelisted')]
        if not rows:
            raise OSError("No market data received")
        now = api.now()
        ids = [
            r["symbol"]
            for r in sorted(rows, key=lambda r: -(r["metrics"].get("volume:1d") or 0))
        ]
        with self.lock:
            self.known[exchange] = ids + (retained if exchange=='hyperliquid' else [])
            self.index[exchange] = set(ids)
            if exchange=='binance':self.prices={r['symbol']:(r['metrics']['price'],r['at']) for r in rows}
        self._samples(exchange, rows, now)
        for r in rows:
            m = r['metrics']
            r.pop('_base');r.pop('_qty')
            for k in WINDOW_KEYS[exchange]&m.keys():del m[k]
            if exchange=='binance':
                oi=self.interest.values.get(r['symbol'])
                if oi:m.update(oi[0]);r['metricAt'].update(oi[1])
            mc=self.caps.values.get((exchange,r['symbol'].upper()))
            if mc and 0<=now-mc[1]<=2*HOUR:
                m['mcap'],r['metricAt']['mcap'],r['capSource']=mc
            for key in list(m):
                ts = r["metricAt"].get(key, r["at"])
                max_age=metric_ttl(key,key in r['metricAt'])
                if not -30000 <= now - ts <= max_age:
                    del m[key]
            values,times=self.window_values(exchange,r,now)
            m.update(values);r["metricAt"].update(times)
        stamp = max(r["at"] for r in rows)
        return dict(
            exchange=exchange,
            asOf=stamp,
            status="live" if -60000 <= now - stamp < 120000 else "stale",
            rows=rows,
            fiveReady=self.initial_count(exchange),
            message=message,
        )

    def _samples(self, venue, rows, now):
        # Store one sample per minute: avoid comparing the live price near
        # the end of a five-minute bucket with a nearly ten-minute-old quote.
        bucket = now // 60000 * 60000
        fresh = [r for r in rows if -60000 <= now - r["at"] <= 90000]
        grids = {}
        want = set()
        origins={r['at']//MINUTE*MINUTE for r in fresh}
        if venue=='hyperliquid':origins|={t+MINUTE for t in origins}
        for origin in origins:
            keys = [origin - n * 60000 for n in WINDOWS.values()]
            trendkeys = list(range(origin - 282 * STEP, origin + 1, 6 * STEP))
            grids[origin] = keys, trendkeys
            want.update(keys + trendkeys)
        with closing(self.db()) as db, db:
            db.executemany(
                "INSERT OR IGNORE INTO observed VALUES(?,?,?,?,?)",
                (
                    (
                        venue,
                        r["at"] // 60000 * 60000,
                        r["symbol"],
                        r["metrics"]["price"],
                        r["_qty"],
                    )
                    for r in fresh
                ),
            )
            db.execute(
                "DELETE FROM observed WHERE venue=? AND bucket<?",
                (venue, bucket - 290 * STEP),
            )
            days={}
            if venue=='hyperliquid' and want:
                db.executemany('INSERT OR IGNORE INTO day_samples VALUES(?,?,?)',[(r['at']//MINUTE*MINUTE,r['symbol'],r['metrics']['volume:1d']) for r in fresh if 'volume:1d' in r['metrics']]);db.execute('DELETE FROM day_samples WHERE bucket<?',(bucket-290*STEP,))
                days={(s,t):d for s,t,d in db.execute('SELECT symbol,bucket,volume FROM day_samples WHERE bucket IN ('+','.join('?' for _ in want)+')',list(want))}
            values = {
                (s, t): (p, q)
                for t, s, p, q in db.execute(
                    "SELECT bucket,symbol,price,qty FROM observed WHERE venue=? AND bucket IN ("
                    + ",".join("?" * len(want))
                    + ")",
                    [venue, *want],
                )
            }
        anchors={}
        for r in fresh:
            keys, trendkeys = grids[r["at"] // 60000 * 60000]
            s = r["symbol"]
            m = r["metrics"]
            price = m["price"]
            qty = r["_qty"]
            if venue=='hyperliquid':
                minute=r['at']//MINUTE
                for origin in (minute,minute+1):
                    baseline={w:(old[0],old[1],days.get((s,t))) for w,t in zip(WINDOWS,grids[origin*MINUTE][0]) if (old:=values.get((s,t)))}
                    anchors[s,origin]=baseline
                    if origin==minute:m.update(self._context_changes(baseline,price,qty,m.get('volume:1d')))
            sampled = [values.get((s, t), (None, None))[0] for t in trendkeys]
            r["trend"] = sampled if sum(v is not None for v in sampled) >= 2 else []
        if venue=='hyperliquid':self.context_anchors=anchors

    @staticmethod
    def _context_changes(baseline,price,qty,day):
        m={}
        for w,(p,q,before) in baseline.items():
            if before is not None and day is not None:
                m['volChangeUsd:'+w]=day-before
                if before>0:m['volChange:'+w]=pct(day,before)
            if qty is not None and q:
                m['oiChange:'+w]=pct(qty,q)
                m['oiDelta:'+w]=qty*price-q*p
        return m

    def window_values(self, venue, row, now):
        at, source, paired_at=self.activity[venue].metrics(row['symbol'],now)
        values={k:v for k,v in source.items() if k in WINDOW_KEYS[venue]}
        times=dict.fromkeys(values,at)
        price=row['metrics'].get('price');pt=row.get('metricAt',{}).get('price',row['at'])
        for k in KEY.values():
            if k['correlation'] in values:times[k['correlation']]=paired_at
            if price and -30000<=now-pt<=120000 and k['change'] in source:
                values[k['changeUsd']]=price*source[k['change']]/100;times[k['changeUsd']]=min(at,pt)
        if venue=='hyperliquid':
            anchor=self.context_anchors.get((row['symbol'],pt//MINUTE));obs=row.get('metricAt',{});oi=row['metrics'].get('oi');dt=obs.get('volume:1d',row['at'])
            if anchor and -30000<=now-pt<120000:
                qty=oi/price if price and oi is not None and pt==obs.get('oi',row['at']) else None
                day=row['metrics'].get('volume:1d') if dt//MINUTE==pt//MINUTE else None
                changes=self._context_changes(anchor,price,qty,day);values.update(changes)
                times.update({k:pt if k.startswith('oi') else dt for k in changes})
        return values,times

    def initial_count(self,venue):
        with self.activity[venue].lock:return len(self.activity[venue].ready & self.index[venue])

    def window_patch(self,venue,rows,now):
        patch={};keys=WINDOW_KEYS[venue]
        if venue=='hyperliquid':keys=keys|CONTEXT_KEYS
        for row in rows:
            values,times=self.window_values(venue,row,now);old=row['metrics'];oldtimes=row.get('metricAt',{})
            updated={k:x for k,x in values.items() if x!=old.get(k) or times[k]!=oldtimes.get(k)}
            updated.update(dict.fromkeys((keys & old.keys())-values.keys()))
            if updated:patch[row['symbol']]=(updated,{k:times[k] for k in updated if k in times})
        return patch,self.initial_count(venue)

    def _enrich(self):
        self.interest.run(lambda:self.history_symbols('binance'),lambda s:self.prices.get(s,(None,0)))

    def set_focus(self,venue,symbols):
        with self.lock:self.priority[venue]=list(dict.fromkeys(symbols))[:40]

    def history_symbols(self,venue):
        with self.lock:
            first=[s for s in [self.activity[venue].reference,*self.priority[venue],*self.focus[venue]] if s in self.index[venue]]
            return list(dict.fromkeys(first+self.known[venue]))

    def trend(self, exchange, symbol):
        step = api.MS['30m']
        end = api.now() // step * step
        key = (exchange, symbol)
        with self.lock:
            if symbol not in self.index.get(exchange, set()):
                raise ValueError('Unknown instrument')
            cached = self.trend_cache.get(key)
            if cached and cached['end'] == end:
                return cached
        if not self.trend_slots.acquire(timeout=1):
            raise OSError('Trend history busy')
        try:
            bars = api.fetch_bars(exchange, symbol, '30m', 48, before=end)
            closes = {b['t']: b['c'] for b in bars}
            result = {'end': end, 'points': [closes.get(t) for t in range(end-48*step, end, step)]}
            with self.lock:
                self.trend_cache[key] = result
            return result
        finally:
            self.trend_slots.release()

    def candles(self, exchange, symbol, interval, limit=160, before=None):
        with self.lock:
            if (
                exchange not in EXCHANGES
                or symbol not in self.index[exchange]
                or interval not in INTERVALS
            ):
                raise ValueError("Unknown instrument or interval")
            if type(limit) is not int or not 1 <= limit <= (2881 if exchange=='hyperliquid' else 499) or (before is not None and (type(before) is not int or not 0 < before <= api.now())):
                raise ValueError("Invalid candle history range")
            key = (exchange, symbol, interval, limit, before)
            previous = self.charts.get(key)
            if previous and api.now() - previous[0] < (600000 if before is not None else 5000):
                return previous[1]
            self.focus[exchange] = [
                symbol,
                *[s for s in self.focus[exchange] if s != symbol],
            ][:5]
        if not self.chart_slots.acquire(timeout=0.3):
            raise OSError("Charts are busy; try again")
        try:
            rows = api.fetch_bars(exchange, symbol, interval, limit, before)
        finally:
            self.chart_slots.release()
        with self.lock:
            if len(self.charts) >= 160:
                self.charts.pop(min(self.charts, key=lambda k: self.charts[k][0]))
            self.charts[key] = (api.now(), rows)
        return rows

    def start_quotes(self, publish):
        from .streams import start
        for activity in self.activity.values():activity.start()
        for fn in (self._enrich,self.caps.run):
            t=threading.Thread(target=fn,daemon=True);self.threads[fn]=t;t.start()
        def forward(v, quotes):
            clean={}
            for s,(stamp,metrics) in quotes.items():
                if v=='binance' and 'price' in metrics:self.prices[s]=(metrics['price'],stamp)
                clean[s]=(stamp,{k:x for k,x in metrics.items() if k not in WINDOW_KEYS[v]})
            publish(v,clean)
        start(self.hl_universes,self.done,forward)

    def close(self):
        self.done.set()
        for thread in list(self.threads.values()):
            thread.join(timeout=9)
