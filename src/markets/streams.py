"""Shared upstream connections. REST still supplies discovery, history and recovery."""
import json
import logging
import threading
import time

from .providers import hyper_rows, now, number

URLS = {
    'binance': 'wss://fstream.binance.com/market/ws/!ticker@arr',
    'hyperliquid': 'wss://api.hyperliquid.xyz/ws',
}


def quotes(venue, packet, universes, stamp):
    if venue == 'binance':
        result = {}
        if not isinstance(packet, list):return result
        for t in packet:
            if t.get('e')!='24hrTicker' or not number(t.get('c')):continue
            fields={k:number(t.get(w)) for k,w in [('price','c'),('change:1d','P'),('changeUsd:1d','p'),('volume:1d','q'),('trades:1d','n')]}
            result[t['s']] = (int(t['C']),{k:v for k,v in fields.items() if v is not None})
        return result
    if packet.get('channel')!='allDexsAssetCtxs':return {}
    result={}
    for dex,contexts in packet['data']['ctxs']:
        meta=universes.get(dex)
        # Context arrays use the immutable venue asset index, including delistings.
        if not meta or len(meta['universe'])!=len(contexts):continue
        for r in hyper_rows([meta,contexts],stamp):result[r['symbol']]=(stamp,r['metrics'])
    return result


def consume(venue, universes, stop, publish):
    from websocket import create_connection
    delay=1
    while not stop.is_set():
        sock=None
        try:
            sock=create_connection(URLS[venue],timeout=10,suppress_origin=True)
            if venue=='hyperliquid':
                sock.settimeout(70)
                sock.send(json.dumps({'method':'subscribe','subscription':{'type':'allDexsAssetCtxs'}}))
            pending={};last=0
            while not stop.is_set():
                raw=sock.recv()
                if not raw:raise OSError('Exchange stream closed')
                decoded=quotes(venue,json.loads(raw),universes,now())
                for key,item in decoded.items():
                    if key not in pending or item[0]>=pending[key][0]:pending[key]=item
                if pending and time.monotonic()-last>=0.8:
                    publish(venue,pending);pending={};last=time.monotonic();delay=1
        except Exception as exc:
            if not stop.is_set():logging.getLogger(__name__).warning('%s stream reconnecting (%s)',venue,type(exc).__name__)
        finally:
            if sock is not None:sock.close(timeout=1)
        stop.wait(delay);delay=min(delay*2,30)


def start(universes,stop,publish):
    for venue in URLS:
        threading.Thread(target=consume,args=(venue,universes,stop,publish),name='quotes-'+venue,daemon=True).start()
