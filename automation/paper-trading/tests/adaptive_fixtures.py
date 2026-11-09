"""Synthetic, isolated fixtures for adaptive simulator tests (in-memory SQLite only; no Turso, no broker)."""
import sqlite3, numpy as np, pandas as pd
from datetime import date, timedelta
from pathlib import Path
import adaptive_logging as alog, pit_archive as pit, prefilter as pf
class MemDB:
    def __init__(self):
        self.c=sqlite3.connect(':memory:'); self.c.row_factory=sqlite3.Row
    def batch(self,stm):
        with self.c:
            for sql,args in stm: self.c.execute(sql,args)
    def query(self,sql,args=()): return [dict(r) for r in self.c.execute(sql,args).fetchall()]
def fresh_db(root):
    db=MemDB()
    for sql in (Path(root)/'schema.sql').read_text().split(';'):
        if sql.strip(): db.batch([(sql.strip(),())])
    pit.init(db); alog.init(db); return db
def trading_days(n, start=date(2024,1,1)):
    out=[];cur=start
    while len(out)<n:
        if cur.weekday()<5: out.append(cur.isoformat())
        cur+=timedelta(days=1)
    return out
def make_market(n_days=330, symbols=('AAA-EQ','BBB-EQ','CCC-EQ','DDD-EQ'), seed=7, volume=300_000):
    rng=np.random.default_rng(seed); days=trading_days(n_days); rows=[]
    for k,sym in enumerate(symbols):
        px=1000.0+50*k
        for i,d in enumerate(days):
            r=0.0015+0.018*np.sin(i/3.0+k)+rng.normal(0,0.004)
            o=round(px,2); px=max(50.0,px*(1+r)); c=round(px,2)
            rows.append({'symbol':sym,'trade_date':d,'open':o,'high':round(max(o,c)*1.005,2),'low':round(min(o,c)*0.995,2),'close':c,'volume':volume})
    idx=pd.DataFrame([{'symbol':'NIFTY500','trade_date':d,'open':1000+i,'high':1001+i,'low':999+i,'close':1000+i,'volume':1} for i,d in enumerate(days)])
    return days, pd.DataFrame(rows), idx
def seed_pit(db, ns, days, symbols, series='EQ', eligible=True):
    ver=pf.POLICY['version']
    for d in days:
        pit.ingest_bhavcopy_series(db,[{'symbol':s,'series':series,'close':1000.0} for s in symbols],trade_date=d) if series else None
        db.batch([('INSERT INTO daily_prefilter_universe(namespace,trade_date,symbol,policy_version,status,eligible,pit_series,metrics_json,data_hash,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (ns,d,s,ver,'PASS' if eligible else 'FAIL',1 if eligible else 0,series,'{}','h','t')) for s in symbols])
