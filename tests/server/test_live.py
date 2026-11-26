import unittest

from src.server.live import LiveMarket


class LiveTests(unittest.TestCase):
    def test_reconnect_resync_and_slow_metrics_keep_their_source_time(self):
        row=dict(symbol='BTC',at=100,metrics={'price':10,'oi':90})
        snap=dict(exchange='hyperliquid',asOf=100,status='live',rows=[row])
        book=LiveMarket(snap);book.replace(snap,100)
        seq,kind,_=book.read(-1);self.assertEqual(kind,'snapshot')
        updated=book.update({'BTC':(200,{'price':11})},200)
        self.assertEqual(updated['rows'][0]['metricAt'],{'price':200,'oi':100})
        self.assertEqual(book.read(seq)[1],'quotes')
        self.assertIsNone(book.update({'BTC':(150,{'price':1})},210))
        book.update({'BTC':(300,{'price':12})},300)
        self.assertEqual(book.read(seq)[1],'snapshot')
        self.assertEqual(book.replace(snap,310)['rows'][0]['metrics']['price'],12)

    def test_candle_revision_does_not_refresh_oi_or_price_and_gap_removes_value(self):
        row=dict(symbol='BTC',at=100,metrics={'price':10,'oi':90},metricAt={'oi':80})
        snap=dict(exchange='binance',asOf=100,status='live',rows=[row]);book=LiveMarket(snap);book.replace(snap,100)
        seq=book.seq;row=book.windows({'BTC':({'trades:5m':25},{'trades:5m':150})},1)['rows'][0]
        self.assertEqual((row['at'],row['metricAt']['oi']),(100,80));self.assertEqual(book.read(seq)[1],'windows')
        seq=book.seq;row=book.windows({'BTC':({'trades:5m':None},{})},1)['rows'][0]
        self.assertNotIn('trades:5m',row['metrics']);self.assertIsNone(book.read(seq)[2]['windows']['BTC'][0]['trades:5m'])
