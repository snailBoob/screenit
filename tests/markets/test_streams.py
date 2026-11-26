import unittest

from src.markets.streams import quotes


class QuoteTests(unittest.TestCase):
    def test_binance_ticker_units_and_hyperliquid_native_asset_index(self):
        self.assertEqual(quotes('binance',[{'e':'24hrTicker','s':'BTCUSDT','c':'91','P':'1.2','C':900}],{},1000),{'BTCUSDT':(900,{'price':91,'change:1d':1.2})})
        packet={'channel':'allDexsAssetCtxs','data':{'ctxs':[['xyz',[{}, {'markPx':'20','openInterest':'3'}]],['other',[{}]]]}}
        meta={'xyz':{'universe':[{'name':'OLD','isDelisted':True},{'name':'xyz:NVDA'}]}}
        result=quotes('hyperliquid',packet,meta,1000)
        self.assertEqual(set(result),{'xyz:NVDA'});self.assertEqual(result['xyz:NVDA'][1]['oi'],60)
