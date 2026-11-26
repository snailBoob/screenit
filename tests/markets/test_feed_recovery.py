import tempfile
import threading
import unittest
from unittest.mock import patch

from src.markets import MarketFeed, providers as api
from src.markets.candle_feed import CandleFeed
from src.markets.rolling import MINUTE


def bar(i):
    return dict(t=i*MINUTE, o=10, c=10, n=3, v=30, d=6)


class RecoveryTests(unittest.TestCase):
    def test_binance_repair_and_replayed_final_do_not_double_count(self):
        feed=CandleFeed('binance',threading.Event(),lambda:['BTCUSDT'])
        at=105*MINUTE+500
        feed.accept('BTCUSDT',[(bar(i),True) for i in range(100,104)],at-MINUTE)
        feed.accept('BTCUSDT',[(bar(105),False)],at)
        self.assertNotIn('trades:5m',feed.metrics('BTCUSDT',at)[1])
        with patch.object(api,'fetch_bars',return_value=[bar(104),bar(105)]),patch.object(api,'now',return_value=at):
            self.assertTrue(feed.backfill('BTCUSDT',2))
        feed.accept('BTCUSDT',[(bar(104),True)],at)
        self.assertEqual(feed.metrics('BTCUSDT',at)[1]['trades:5m'],15)

    def test_partial_dex_failure_preserves_subscriptions_through_rollover(self):
        failed=False
        def hl(kind,**opts):
            if kind=='perpDexs':return [None,{'name':'xyz'}]
            if failed and opts.get('dex'):raise OSError('offline')
            name='xyz:NVDA' if opts.get('dex') else 'DOGE'
            return [{'universe':[{'name':name}]},[{'markPx':'10'}]]
        with tempfile.TemporaryDirectory() as d,patch.object(api,'hl',side_effect=hl):
            f=MarketFeed(d);at=api.now()//MINUTE*MINUTE+1;m=at//MINUTE
            with patch.object(api,'now',return_value=at):f.refresh('hyperliquid')
            feed=f.activity['hyperliquid'];before=set(feed.symbols());self.assertIn('xyz:NVDA',before)
            feed.accept('DOGE',[(bar(i),True) for i in range(m-4,m+1)],at)
            failed=True;at+=MINUTE;feed.accept('DOGE',[(bar(m+1),False)],at)
            with patch.object(api,'now',return_value=at):snap=f.refresh('hyperliquid')
            self.assertEqual(before,set(feed.symbols()));self.assertIn('xyz',snap['message'])
            self.assertEqual(snap['rows'][0]['metrics']['trades:5m'],15)
            f.close()
