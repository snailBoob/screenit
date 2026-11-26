import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

from src.contracts import defaults
from . import validation as v


def now():
    return int(time.time() * 1000)


class Conflict(Exception):
    def __init__(self, current):
        self.current = current


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.tx() as db:
            if db.execute("pragma user_version").fetchone()[0] > 2:
                raise RuntimeError("This database was created by a newer version")
            db.executescript("""PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS workspace(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER, doc TEXT);
              CREATE TABLE IF NOT EXISTS rules(id TEXT PRIMARY KEY, revision INTEGER, doc TEXT);
              CREATE TABLE IF NOT EXISTS latch(rule TEXT REFERENCES rules ON DELETE CASCADE,symbol TEXT, active INTEGER, fired INTEGER,PRIMARY KEY(rule,symbol));
              CREATE TABLE IF NOT EXISTS watermarks(rule TEXT REFERENCES rules ON DELETE CASCADE,symbol TEXT, stamps TEXT, PRIMARY KEY(rule,symbol));
              CREATE TABLE IF NOT EXISTS cooldowns(rule TEXT REFERENCES rules ON DELETE CASCADE,symbol TEXT,at INTEGER,PRIMARY KEY(rule,symbol));
              CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,ruleName TEXT,exchange TEXT,symbol TEXT,at INTEGER,message TEXT,delivery TEXT,tries INTEGER DEFAULT 0,due INTEGER DEFAULT 0);
              CREATE INDEX IF NOT EXISTS outbox ON events(delivery,due,id);
              PRAGMA user_version=2;""")
            if 'sound' not in {r[1] for r in db.execute('PRAGMA table_info(events)')}:
                db.execute("ALTER TABLE events ADD COLUMN sound TEXT NOT NULL DEFAULT ''")
            if 'destination' not in {r[1] for r in db.execute('PRAGMA table_info(events)')}:
                db.execute('ALTER TABLE events ADD COLUMN destination TEXT')
            db.execute(
                "INSERT OR IGNORE INTO workspace VALUES(1,1,?)",
                (json.dumps(defaults()),),
            )

    @contextmanager
    def tx(self, write=False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def workspace(db):
        r = db.execute("SELECT revision,doc FROM workspace WHERE id=1").fetchone()
        return {"revision": r["revision"], "settings": defaults() | json.loads(r["doc"])}

    def get_settings(self):
        with self.tx() as db:
            return self.workspace(db)

    def patch(self, revision, changes):
        v.require(
            type(revision) is int
            and isinstance(changes, dict)
            and changes.keys() <= defaults().keys()
        )
        with self.tx(True) as db:
            old = self.workspace(db)
            if revision != old["revision"]:
                raise Conflict(old)
            new = old["settings"] | changes
            v.settings(new)
            db.execute(
                "UPDATE workspace SET revision=revision+1,doc=? WHERE id=1",
                (json.dumps(new),),
            )
            return self.workspace(db)

    @staticmethod
    def unpack(r):
        return dict(id=r["id"], revision=r["revision"], **json.loads(r["doc"]))

    def rules(self):
        with self.tx() as db:
            return [
                self.unpack(r) for r in db.execute("SELECT * FROM rules ORDER BY rowid")
            ]

    def change_rule(self, payload, rid=None, delete=False):
        v.require(isinstance(payload, dict))
        data = payload.copy()
        rev = data.pop("revision", None)
        i = data.pop("id", None)
        v.require(i is None or i == rid)
        if not rid and 'symbols' in data:
            symbols=data.pop('symbols');v.require(isinstance(symbols,list) and 1<=len(symbols)<=128 and all(v.short(x) and x.strip() for x in symbols) and len(set(symbols))==len(symbols),'Invalid symbol selection')
            batch=[{**data,'symbol':sym} for sym in symbols]
            for item in batch:v.rule(item)
            with self.tx(True) as db:
                v.require(db.execute('SELECT COUNT(*) FROM rules').fetchone()[0]+len(batch)<=128,'Maximum of 128 alerts')
                return {'rules':[self.insert_rule(db,item) for item in batch]}
        if not delete:
            v.rule(data)
        with self.tx(True) as db:
            if rid:
                existing = db.execute(
                    "SELECT * FROM rules WHERE id=?", (rid,)
                ).fetchone()
                if not existing:
                    raise KeyError("Alert not found")
                if type(rev) is not int or existing["revision"] != rev:
                    raise Conflict(
                        {
                            "rule": self.unpack(existing),
                            "error": "Alert changed elsewhere",
                        }
                    )
                if delete:
                    db.execute("DELETE FROM rules WHERE id=?", (rid,))
                    return {"ok": True}
                old = json.loads(existing["doc"])
                rev += 1
                if any(
                    old[k] != data[k]
                    for k in ("exchange", "symbol", "repeat", "groups")
                ):
                    db.execute("DELETE FROM latch WHERE rule=?", (rid,))
                    db.execute("DELETE FROM watermarks WHERE rule=?", (rid,))
                    db.execute("DELETE FROM cooldowns WHERE rule=?", (rid,))
                db.execute(
                    "UPDATE rules SET revision=?,doc=? WHERE id=?",
                    (rev, json.dumps(data), rid),
                )
            else:
                v.require(
                    db.execute("SELECT COUNT(*) FROM rules").fetchone()[0] < 128,
                    "Maximum of 128 alerts",
                )
                return {'rule':self.insert_rule(db,data)}
            return {"rule": dict(id=rid, revision=rev, **data)}

    @staticmethod
    def insert_rule(db,data):
        rid=uuid.uuid4().hex;db.execute('INSERT INTO rules VALUES(?,?,?)',(rid,1,json.dumps(data)))
        return dict(id=rid,revision=1,**data)

    def history(self):
        with self.tx() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,ruleName,exchange,symbol,at,message,delivery,sound FROM events ORDER BY id DESC LIMIT 500"
                )
            ]
