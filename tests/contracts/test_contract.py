import unittest

from src.contracts import catalog, defaults


class CatalogTests(unittest.TestCase):
    def test_each_selectable_metric_has_a_unique_numeric_identity_and_unit(self):
        fields = catalog()['metrics']
        keys = {f['id'] for f in fields}
        self.assertEqual(len(keys), 82)
        self.assertEqual(len(keys), len(fields))
        self.assertTrue(all(f['unit'] and f['label'] for f in fields))
        self.assertTrue(set(defaults()['columns']) <= keys | {'trend', 'symbol'})
        self.assertIn(defaults()['sort']['key'], keys)

    def test_independent_initial_workspaces_and_native_symbols(self):
        first = defaults()
        first['favorites'].append('hyperliquid:xyz:NVDA')
        self.assertEqual(defaults()['favorites'], [])
        self.assertEqual(first['favorites'][0].split(':', 1), ['hyperliquid', 'xyz:NVDA'])
        self.assertIn(first['exchange'], catalog()['exchanges'])
        self.assertIn(first['chartInterval'], catalog()['intervals'])
