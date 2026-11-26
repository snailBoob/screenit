import tempfile
import unittest
from pathlib import Path

from src.server.alerts import Engine
from src.server.store import Store, Conflict


def config(op="gt", repeat="rearm"):
    return dict(
        name="Price watcher",
        exchange="binance",
        symbol="BTCUSDT",
        enabled=True,
        repeat=repeat,
        groups=[[dict(metric="price", op=op, value=100)]],
    )


class AlertTests(unittest.TestCase):
    def test_sustained_level_repeats_at_cooldown_with_fresh_evidence_after_restart(self):
        self.store.change_rule({**config(), 'cooldownMs': 60000})
        self.tick(110); first = self.t
        self.t = first + 54000; self.tick(110)
        self.engine = Engine(Store(self.store.path))
        self.t = first + 55000; self.tick(110, metric_at=first + 54000)
        self.assertEqual(len(self.store.history()), 1)  # older than last seen
        self.tick(110); second = self.t
        self.t = second + 55000; self.tick(110)
        self.assertEqual([e['at'] for e in self.store.history()], [self.t, second, first])

    def test_other_metric_updates_cannot_repeat_an_unchanged_observation(self):
        self.store.change_rule({**config(), 'cooldownMs': 60000,
            'groups': [[{'metric':'oi', 'op':'gt', 'value':10}], [{'metric':'price','op':'lt','value':1}]]})
        at = self.t
        for dt, oi_at, expected in [(0,0,1),(61000,0,1),(62000,62000,2)]:
            t = at+dt
            row = dict(symbol='BTCUSDT',at=t,metrics={'oi': 20,'price': 100}, metricAt={'oi':at+oi_at})
            self.engine.tick(dict(exchange='binance',status='live',asOf=t,rows=[row]), t)
            self.assertEqual(len(self.store.history()),expected)

    def test_optional_name_and_atomic_multi_symbol_creation(self):
        data={**config(), 'symbol':None, 'name':'', 'symbols':['BTCUSDT','ETHUSDT'], 'sound':'bell'}
        rules=self.store.change_rule(data)['rules'];self.assertEqual([r['symbol'] for r in rules],data['symbols'])
        self.tick(110);event,=self.store.history();self.assertEqual((event['ruleName'],event['sound'],event['delivery'],event['message']),('Screenit Alert','bell','off','BTCUSDT — PRICE is above 100'))
        with self.assertRaises(ValueError):self.store.change_rule({**data,'symbols':['OTHER','']})
        self.assertEqual(len(self.store.rules()),2)

    def test_repeating_cooldown_persists_across_restart(self):
        self.store.change_rule({**config('cross_up'),'cooldownMs':60000,'sound':'ding'});self.tick(90);self.tick(110)
        self.engine=Engine(Store(self.store.path));self.tick(90);self.tick(110);self.assertEqual(len(self.store.history()),1)
        self.t+=60000;self.tick(90);self.tick(110);self.assertEqual(len(self.store.history()),2)

    def test_late_baseline_before_known_missing_point_cannot_bridge_gap(self):
        self.store.change_rule(config("cross_up"))
        self.tick(110)
        t = self.t
        self.tick(None, stamp=t + 5000)
        self.tick(90, stamp=t + 1000)
        self.tick(110, stamp=t + 15000)
        self.assertFalse(self.store.history())
        self.tick(90)
        self.tick(110)
        self.assertEqual(len(self.store.history()), 1)

    def test_cross_rearms_on_first_below_after_restart(self):
        self.store.change_rule(config("cross_up"))
        self.tick(90)
        self.tick(110)
        self.engine = Engine(self.store)
        self.t += 300000
        self.tick(90)
        self.tick(110)
        self.assertEqual(len(self.store.history()), 2)

    def test_replay_after_stale_or_restart_is_not_a_new_cross(self):
        self.store.change_rule(config("cross_up"))
        self.tick(110)
        t = self.t
        self.tick(0, status="stale")
        self.engine = Engine(self.store)
        self.tick(90, stamp=t - 1000)
        self.tick(110, stamp=t)
        self.assertFalse(self.store.history())
        self.tick(90)
        self.tick(110)
        self.assertEqual(len(self.store.history()), 1)

    def test_reordered_price_cannot_manufacture_a_later_crossing(self):
        self.store.change_rule(config("cross_up"))
        first = self.t
        self.tick(102, stamp=first)
        self.tick(99, stamp=first - 1000)
        self.tick(103)
        self.assertFalse(self.store.history())

    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.store = Store(Path(t.name) / "alerts")
        self.engine = Engine(self.store)
        self.t = 500000000

    def tick(self, price, *, status="live", metric_at=None, extras=None, stamp=None):
        self.t += 5000
        at = stamp or self.t
        r = dict(at=at, symbol="BTCUSDT", metrics={"price": price, **(extras or {})})
        if metric_at is not None:
            r["metricAt"] = {"price": metric_at}
        self.engine.tick(
            dict(exchange="binance", asOf=self.t, status=status, rows=[r]), self.t
        )

    def test_level_latch_once_and_rearm_survive_restart(self):
        self.store.change_rule(config())
        self.store.change_rule(config(repeat="once"))
        self.tick(101)
        self.tick(999)
        self.engine = Engine(Store(self.store.path))
        self.tick(None)
        self.tick(102)
        self.assertEqual(len(self.store.history()), 2)
        self.t += 300000
        self.tick(99)
        self.tick(101)
        self.assertEqual(len(self.store.history()), 3)

    def test_cross_needs_fresh_observations_and_real_crossing(self):
        self.store.change_rule(config("cross_up"))
        self.tick(125)
        self.tick(90)
        self.tick(None)
        self.tick(101)
        self.assertFalse(self.store.history())
        self.tick(90)
        self.tick(90, status="stale")
        self.tick(101)
        self.tick(90)
        self.engine = Engine(self.store)
        self.tick(101)
        self.assertFalse(self.store.history())
        self.tick(99)
        self.tick(100)
        self.tick(101)
        self.assertEqual(len(self.store.history()), 1)

    def test_stale_metric_and_repeated_timestamp_do_not_trigger(self):
        self.store.change_rule(config("cross_up"))
        ts = self.t
        self.tick(90, stamp=ts)
        self.tick(110, stamp=ts)
        self.tick(115, metric_at=ts - 990000)
        self.tick(116)
        self.assertFalse(self.store.history())

    def test_boolean_groups_scope_and_validation(self):
        rule = config()
        rule["groups"] = [
            [
                {"metric": "oi", "op": "between", "value": 10, "upper": 12},
                {"metric": "funding", "op": "lt", "value": 0},
            ],
            [{"metric": "price", "op": "outside", "value": 50, "upper": 150}],
        ]
        r = self.store.change_rule(rule)["rule"]
        self.tick(70, extras={"oi": 11, "funding": 1})
        self.assertFalse(self.store.history())
        self.tick(70, extras={"oi": 11, "funding": -1})
        self.assertEqual(len(self.store.history()), 1)
        self.tick(50, extras={"oi": 7})
        self.t += 300000
        self.tick(170)
        self.assertEqual(len(self.store.history()), 2)
        self.store.change_rule({**r, "enabled": False}, r["id"])
        with self.assertRaises(Conflict):
            self.store.change_rule(r, r["id"])
        with self.assertRaises(ValueError):
            self.store.change_rule({**config(), "symbol": None})
