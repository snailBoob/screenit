import concurrent.futures
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.server.store import Conflict, Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.path = Path(t.name) / "state"
        self.store = Store(self.path)

    def test_restart_and_compare_and_swap(self):
        s = self.store
        rev = s.get_settings()["revision"]

        def save(i):
            try:
                return s.patch(rev, {"search": str(i)})["settings"]["search"]
            except Conflict:
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            winners = [x for x in pool.map(save, range(4)) if x is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(
            Store(self.path).get_settings()["settings"]["search"], winners[0]
        )
        self.assertEqual(s.get_settings()["revision"], rev + 1)

    def test_invalid_mixed_patch_is_atomic(self):
        initial = self.store.get_settings()
        with self.assertRaises(ValueError):
            self.store.patch(
                initial["revision"],
                {"exchange": "hyperliquid", "columns": ["__proto__"]},
            )
        self.assertEqual(self.store.get_settings(), initial)

    def test_newer_schema_is_not_reinitialized(self):
        db = sqlite3.connect(self.path)
        db.execute("PRAGMA user_version=99")
        db.close()
        with self.assertRaises(RuntimeError):
            Store(self.path)
