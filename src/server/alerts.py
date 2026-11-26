"""A level may be known, false, or unknown. Unknown never rearms a latch."""

import json
from src.contracts import metric_ttl
from .validation import numeric

LABELS = dict(price='PRICE', funding='FUNDING/H', oi='OI $', mcap='MCAP', rvol='RVOL', change='CHG %', changeUsd='CHG $', volume='VOL', trades='TRD', volatility='VLT', oiChange='OI CHG %', oiDelta='OI QTY Δ$', volumeDelta='VOL Δ', volChange='VOL CHG %', volChangeUsd='VOL CHG $', correlation='COR')
PHRASES = dict(gt='is above', lt='is below', cross_up='crossed above', cross_down='crossed below', between='is between', outside='is outside')

def condition_message(c, venue=None):
    key, _, window = c['metric'].partition(':')
    name='OI VALUE Δ$' if key=='oiDelta' and venue=='hyperliquid' else LABELS[key]
    label = ' '.join(filter(None, [name, window.upper()]))
    value = str(c['value']).removesuffix('.0')
    if c['op'] in ('between','outside'):
        value += (' and ' if c['op']=='between' else ' - ') + str(c['upper']).removesuffix('.0')
    return f"{label} {PHRASES[c['op']]} {value}"


def fresh_metric(row, key, now):
    val = row["metrics"].get(key)
    explicit = row.get("metricAt", {})
    at = explicit.get(key, row["at"])
    age = metric_ttl(key,key in explicit)
    if not numeric(val) or not numeric(at) or not -30000 <= now - at <= age:
        return None
    return val, at, age


def evaluate(rule, row, previous, now, watermarks):
    sample = {
        c["metric"]: fresh_metric(row, c["metric"], now)
        for g in rule["groups"]
        for c in g
    }
    # A repeated or reordered quote is not a new price observation. Do not
    # let it change the baseline for a subsequent threshold crossing either.
    for metric, point in sample.items():
        old = previous.get(metric)
        if old and point and point[1] <= old[1]:
            sample[metric] = old
        elif point and point[1] <= max(
            watermarks.get(metric, -1), watermarks.get("*", -1)
        ):
            # No contiguous in-memory sample: this old observation may not
            # reconstruct an edge across a gap, outage or process restart.
            sample[metric] = None
    evidence = []
    groups = []
    for g in rule["groups"]:
        results = []
        for c in g:
            k = c["metric"]
            point = sample[k]
            result = None
            if point:
                value, ts, ttl = point
                op = c["op"]
                cut = c["value"]
                old = previous.get(k)
                if op.startswith("cross"):
                    if (op == "cross_up" and value <= cut) or (
                        op == "cross_down" and value >= cut
                    ):
                        result = False
                    elif old and 0 < ts - old[1] <= ttl:
                        result = (
                            old[0] <= cut < value
                            if op == "cross_up"
                            else old[0] >= cut > value
                        )
                elif op == "gt":
                    result = value > cut
                elif op == "lt":
                    result = value < cut
                else:
                    inside = cut <= value <= c["upper"]
                    result = inside if op == "between" else not inside
            results.append(result)
        truth = False if False in results else (None if None in results else True)
        groups.append(truth)
        if truth and any(
            sample[c['metric']][1] > max(watermarks.get(c['metric'], -1), watermarks.get('*', -1))
            for c in g
        ):
            # Only a fresh observation in a satisfied group is trigger evidence.
            # Updating another instrument / an unrelated OR group cannot retrigger it.
            evidence = [condition_message(c,rule.get('exchange')) for c in g]
            break
    return (
        (True if True in groups else None if None in groups else False),
        sample,
        " AND ".join(evidence),
    )


class Engine:
    def __init__(self, store):
        self.store = store
        self.prior = {}

    def tick(self, snapshot, now):
        venue = snapshot["exchange"]
        prev = self.prior.pop(venue, {})
        new = {}
        gap = (
            snapshot["status"] != "live"
            or not snapshot.get("asOf")
            or not -30000 <= now - snapshot["asOf"] <= 120000
        )
        rows = (
            {}
            if gap
            else {
                r["symbol"]: r
                for r in snapshot["rows"]
                if (r['at'] and -30000<=now-r['at']<=120000) or any(
                    k.startswith('trades:') and -30000<=now-ts<60000
                    for k,ts in r.get('metricAt',{}).items() if k in r['metrics']
                )
            }
        )
        with self.store.tx(True) as db:
            for rr in db.execute("SELECT * FROM rules"):
                rule = self.store.unpack(rr)
                rid = rule["id"]
                if not rule["enabled"] or rule["exchange"] != venue:
                    continue
                by_symbol = {
                    r["symbol"]: r
                    for r in db.execute("SELECT * FROM latch WHERE rule=?", (rid,))
                }
                repeating = rule['repeat'] == 'rearm'
                cooldown = rule.get('cooldownMs', 300000)
                last_trigger = dict(db.execute('SELECT symbol,at FROM cooldowns WHERE rule=?', (rid,))) if repeating else {}
                stamps = {
                    r["symbol"]: json.loads(r["stamps"])
                    for r in db.execute(
                        "SELECT symbol,stamps FROM watermarks WHERE rule=?", (rid,)
                    )
                }
                # Persist the time when an instrument disappeared, including a
                # venue-wide outage. Delayed old quotes are not post-gap data.
                for symbol in stamps.keys() - rows.keys():
                    if now > stamps[symbol].get("*", -1):
                        db.execute(
                            "UPDATE watermarks SET stamps=? WHERE rule=? AND symbol=?",
                            (json.dumps(stamps[symbol] | {"*": now}), rid, symbol),
                        )
                for symbol in [rule["symbol"]] if rule["symbol"] else rows:
                    row = rows.get(symbol)
                    if not row:
                        continue
                    key = (rid, rule["revision"], symbol)
                    p = prev.get(key, {})
                    watermark = stamps.get(symbol, {})
                    truth, new[key], notes = evaluate(rule, row, p, now, watermark)
                    advanced = {
                        k: v[1]
                        for k, v in new[key].items()
                        if v and v[1] > watermark.get(k, -1)
                    }
                    for k in new[key]:
                        # An explicit missing observation marks a discontinuity
                        # in *source* time, not just a break in arrival order.
                        if not fresh_metric(row, k, now) and row["at"] > watermark.get(
                            k, -1
                        ):
                            advanced[k] = row["at"]
                    if advanced:
                        db.execute(
                            "INSERT OR REPLACE INTO watermarks VALUES(?,?,?)",
                            (rid, symbol, json.dumps(watermark | advanced)),
                        )
                    if truth is None:
                        continue
                    old = by_symbol.get(symbol)
                    active, fired = (
                        (old["active"], old["fired"]) if old else (False, False)
                    )
                    due = symbol not in last_trigger or now - last_trigger[symbol] >= cooldown
                    trigger = bool(truth and notes and (due if repeating else not fired))
                    if trigger:
                        name=rule['name'].strip() or 'Screenit Alert'
                        msg = f"{symbol} — {notes}"
                        n = rule.get('ntfy')
                        destination = n['server'].rstrip('/') + '/' + n['topic'] if n else None
                        db.execute(
                            "INSERT INTO events(ruleName,exchange,symbol,at,message,delivery,sound,destination) VALUES(?,?,?,?,?,?,?,?)",
                            (name, venue, symbol, now, msg, 'pending' if n else 'off',rule.get('sound',''), destination),
                        )
                        if repeating:
                            db.execute('INSERT OR REPLACE INTO cooldowns VALUES(?,?,?)', (rid, symbol, now))
                    if truth != active or trigger:
                        db.execute(
                            "INSERT OR REPLACE INTO latch VALUES(?,?,?,?)",
                            (rid, symbol, int(truth), int(fired or trigger)),
                        )
            db.execute(
                "DELETE FROM events WHERE id < (SELECT MAX(id)-10000 FROM events) AND delivery!='pending'"
            )
        self.prior[venue] = new
