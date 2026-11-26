"""A latest-value mailbox per exchange. Slow or reconnecting readers resync in full."""
from threading import Condition


class LiveMarket:
    def __init__(self, initial):
        self.changed=Condition()
        self.snapshot=initial
        self.index={}
        self.quotes={}
        self.seq=0
        self.delta=None
        self.kind='quotes'

    @staticmethod
    def merge(row, quote):
        stamp,values=quote
        if stamp<=row['at']: return row
        # A fast price tick must not renew the age of a slower OI or volume metric.
        metrics=row['metrics'].copy()
        times={k:row.get('metricAt',{}).get(k,row['at']) for k in metrics}
        for k,v in values.items():
            if stamp>=times.get(k,0):metrics[k]=v;times[k]=stamp
        return {**row,'at':stamp,'metrics':metrics,'metricAt':times}

    def replace(self,snapshot,now,project=None):
        with self.changed:
            self.index={r['symbol']:i for i,r in enumerate(snapshot['rows'])}
            self.quotes={s:q for s,q in self.quotes.items() if s in self.index and now-q[0]<10000}
            rows=[self.merge(r,self.quotes[r['symbol']]) if r['symbol'] in self.quotes else r for r in snapshot['rows']]
            if project is not None and rows:
                patch,ready=project(snapshot['exchange'],rows,now)
                rows=self.apply_windows(rows,patch);snapshot={**snapshot,'fiveReady':ready}
            self.snapshot={**snapshot,'rows':rows,'asOf':max([snapshot.get('asOf') or 0,*[r['at'] for r in rows]]) or None,'transport':'stream' if self.quotes else 'snapshot'}
            self.seq+=1;self.delta=None;self.changed.notify_all()
            return self.snapshot

    def update(self,quotes,now):
        with self.changed:
            rows=self.snapshot['rows'].copy();patch={}
            for s,(stamp,values) in quotes.items():
                i=self.index.get(s)
                if i is None or not -30000<=now-stamp<=30000 or stamp<=rows[i]['at']:continue
                self.quotes[s]=(stamp,values)
                rows[i]=self.merge(rows[i],(stamp,values));patch[s]=[stamp,values]
            if not patch:return None
            self.snapshot={**self.snapshot,'rows':rows,'asOf':max(self.snapshot.get('asOf') or 0,max(q[0] for q in patch.values())),'status':'live','transport':'stream'}
            self.delta={'asOf':self.snapshot['asOf'],'status':'live','transport':'stream','quotes':patch}
            self.kind='quotes'
            self.seq+=1;self.changed.notify_all()
            return self.snapshot

    def apply_windows(self,rows,patch):
        rows=rows.copy()
        for s,(values,times) in patch.items():
            i=self.index[s];row=rows[i];m=row['metrics'].copy();ts=row.get('metricAt',{}).copy()
            for k,v in values.items():
                if v is None:m.pop(k,None);ts.pop(k,None)
                else:m[k]=v;ts[k]=times[k]
            rows[i]={**row,'metrics':m,'metricAt':ts}
        return rows

    def windows(self, patch, ready):
        with self.changed:
            if not patch and ready==self.snapshot.get('fiveReady'):return None
            rows=self.apply_windows(self.snapshot['rows'],patch)
            self.snapshot={**self.snapshot,'rows':rows,'fiveReady':ready}
            self.delta={'windows':patch,'fiveReady':ready};self.kind='windows'
            self.seq+=1;self.changed.notify_all()
            return self.snapshot

    def read(self,last,timeout=8):
        with self.changed:
            if self.seq==last:self.changed.wait_for(lambda:self.seq!=last,timeout)
            if self.seq==last:return last,'heartbeat',None
            if self.delta is not None and self.seq==last+1 and last>=0:return self.seq,self.kind,self.delta
            return self.seq,'snapshot',self.snapshot
