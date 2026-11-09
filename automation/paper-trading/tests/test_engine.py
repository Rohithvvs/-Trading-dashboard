import sys,unittest,uuid,threading
from pathlib import Path
from datetime import datetime,timedelta
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));import engine as e
T=datetime(2026,11,9,10,tzinfo=e.IST)
class PaperTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.db=e.DB(str(e.ROOT/'tests'/'test_')+uuid.uuid4().hex+'.sqlite');e.NS='test_fixture';e.init(cls.db)
  cls.db.batch([('CREATE TABLE daily_ohlcv(symbol TEXT,trade_date TEXT,close REAL)',())]);e.now=lambda:T
 def setUp(self):e.NS='test_'+uuid.uuid4().hex;e.now=lambda:T
 def signal(self,side='BUY',symbol='RELIANCE-EQ',strategy=1,eligible='2026-11-09'):
  s={'id':uuid.uuid4().hex,'strategy':strategy,'symbol':symbol,'side':side,'bar_date':'2026-11-08','eligible_date':eligible,'reason':'fixture'}
  self.db.batch([('INSERT INTO paper_signals(namespace,id,strategy,symbol,bar_date,side,status,reason,created_at,eligible_date) VALUES(?,?,?,?,?,?,?,?,?,?)',(e.NS,s['id'],strategy,symbol,s['bar_date'],side,'pending','fixture',T.isoformat(),eligible))])
  if side=='BUY':self.db.batch([('INSERT OR REPLACE INTO paper_entry_input_proofs VALUES(?,?,?,?,?)',(e.NS,s['id'],e.si.POLICY['version'],s['bar_date'],T.isoformat())),('INSERT OR REPLACE INTO paper_prefilter_states VALUES(?,?,?,?,?,?,?)',(e.NS,s['bar_date'],symbol,e.pf.POLICY['version'],'PASS','{}',T.isoformat())),('INSERT OR REPLACE INTO paper_entry_gate_proofs VALUES(?,?,?,?,?)',(e.NS,s['id'],s['bar_date'],symbol,e.pf.POLICY['version'])),('INSERT OR IGNORE INTO paper_qualifier_states VALUES(?,?,?,?,?,?,?,?)',(e.NS,s['bar_date'],strategy,symbol,1,e.js({'input_policy':{'version':e.si.POLICY['version']}}),'{}',T.isoformat()))])
  return s
 def quote(self,p=100,age=0):return {'symbol':'RELIANCE-EQ','price':p,'quote_at':(T-timedelta(seconds=age)).isoformat()}
 def test_buy_duplicate_exit_and_pnl(self):
  s=self.signal();self.assertTrue(e.fill(self.db,s,self.quote(),T)['filled']);self.assertFalse(e.fill(self.db,s,self.quote(),T)['filled'])
  out=e.fill(self.db,self.signal('SELL'),self.quote(110),T);self.assertEqual(out['realized_pnl'],10)
  p=e.pnl(self.db);self.assertEqual(p['daily_mark_to_market_pnl_INR'],10);self.assertEqual(p['latest_known_total_pnl_INR'],10);self.assertEqual(len(self.db.positions()),0)
 def test_multistock_and_strategy_separation(self):
  for sym,strategy in [('RELIANCE-EQ',1),('RELIANCE-EQ',2),('TCS-EQ',1)]:self.assertTrue(e.fill(self.db,self.signal(symbol=sym,strategy=strategy),self.quote(),T)['filled'])
  self.assertEqual(len(self.db.positions()),3)
 def test_no_oversell(self):self.assertFalse(e.fill(self.db,self.signal('SELL'),self.quote(),T)['filled'])
 def test_cannot_duplicate_position(self):
  e.fill(self.db,self.signal(),self.quote(),T);self.assertFalse(e.fill(self.db,self.signal(),self.quote(),T)['filled'])
 def test_reject_stale(self):self.assertFalse(e.fill(self.db,self.signal(),self.quote(age=61),T)['filled'])
 def test_reject_future(self):self.assertFalse(e.fill(self.db,self.signal(),self.quote(age=-10),T)['filled'])
 def test_reject_zero(self):self.assertFalse(e.fill(self.db,self.signal(),self.quote(0),T)['filled'])
 def test_reject_missing_timestamp(self):self.assertFalse(e.fill(self.db,self.signal(),{'price':100},T)['filled'])
 def test_closed_market(self):
  saturday=datetime(2026,11,7,10,tzinfo=e.IST);self.assertFalse(e.fill(self.db,self.signal(),self.quote(),saturday)['filled'])
 def test_expire_old_entry(self):
  s=self.signal(eligible='2026-11-06');self.assertFalse(e.fill(self.db,s,self.quote(),T)['filled']);r=self.db.query('SELECT status FROM paper_signals WHERE namespace=?',(e.NS,));self.assertEqual(r[0]['status'],'expired')
 def test_session_dates(self):
  self.assertFalse(e.is_open(datetime(2026,11,10,10,tzinfo=e.IST)));self.assertTrue(e.is_open(datetime(2026,11,8,14,30,tzinfo=e.IST)));self.assertFalse(e.is_open(datetime(2026,11,8,15,20,tzinfo=e.IST)));self.assertFalse(e.is_open(datetime(2027,1,4,10,tzinfo=e.IST)))
 def test_completed_candle_guard(self):
  self.assertEqual(str(e.completed_day(T)),'2026-11-08');self.assertEqual(str(e.completed_day(T.replace(hour=16))),'2026-11-09')
 def test_atomic_batch_failure(self):
  with self.assertRaises(RuntimeError):self.db.batch([('INSERT INTO paper_meta(namespace,key,value) VALUES(?,?,?)',(e.NS,'rollback','bad')),('INSERT INTO nonexistent VALUES(1)',())])
  self.assertFalse(self.db.query('SELECT * FROM paper_meta WHERE namespace=?',(e.NS,)))
 def test_concurrent_duplicate_fill(self):
  s=self.signal()
  def f(_):
   try:return e.fill(self.db,s,self.quote(),T)['filled']
   except RuntimeError:return False
  with ThreadPoolExecutor(max_workers=2) as pool:r=list(pool.map(f,[1,2]))
  self.assertEqual(sum(r),1);self.assertEqual(len(self.db.query('SELECT * FROM paper_fills WHERE namespace=?',(e.NS,))),1)
 def test_stop_fills_observed_quote_not_threshold(self):
  e.fill(self.db,self.signal(strategy=7),self.quote(),T)
  class Feed:
   def quotes(_,symbols):return {'RELIANCE-EQ':self.quote(85)}
  r=e.monitor(self.db,Feed());self.assertEqual(r['fills'],1);fills=self.db.query('SELECT * FROM paper_fills WHERE namespace=? ORDER BY id',(e.NS,));self.assertEqual(fills[-1]['price'],85);self.assertEqual(fills[-1]['realized_pnl'],-15)
 def test_closed_monitor_no_quotes(self):
  e.now=lambda:datetime(2026,11,7,10,tzinfo=e.IST)
  class Feed:
   def quotes(_,s):raise AssertionError('should not fetch')
  self.assertEqual(e.monitor(self.db,Feed())['fills'],0)
 def test_daily_start_mark_not_entry_basis(self):
  # Position opened during prior special session, cost90; previous completed close100; current mark105.
  yesterday=datetime(2026,11,8,14,30,tzinfo=e.IST);s=self.signal(eligible='2026-11-08');q={'price':90,'quote_at':yesterday.isoformat()};self.assertTrue(e.fill(self.db,s,q,yesterday)['filled'])
  self.db.batch([('INSERT INTO daily_ohlcv(symbol,trade_date,close) VALUES(?,?,?)',('RELIANCE-EQ','2026-11-08',100)),('UPDATE paper_positions SET mark_price=?,mark_at=? WHERE namespace=?',(105,T.isoformat(),e.NS))]);p=e.pnl(self.db);self.assertEqual(p['daily_mark_to_market_pnl_INR'],5);self.assertEqual(p['latest_known_total_pnl_INR'],15)
 def test_pnl_snapshot_idempotent(self):
  e.pnl(self.db);e.pnl(self.db);self.assertEqual(len(self.db.query('SELECT * FROM paper_pnl WHERE namespace=?',(e.NS,))),1)
 def test_stale_marks_labeled(self):
  e.fill(self.db,self.signal(),self.quote(),T);self.db.batch([('UPDATE paper_positions SET mark_at=? WHERE namespace=?',((T-timedelta(hours=1)).isoformat(),e.NS))]);self.assertFalse(e.pnl(self.db)['valuation_is_live'])
 def test_daily_scanner_bootstrap_queue_duplicate_and_fill(self):
  old_u=e.universe;old_read=e.read_history;old_indicator=e.indicator;old_eval=e.pf.evaluate;old_benchmark=e.pf.benchmark
  e.pf.evaluate=lambda *args:{"status":"PASS"};e.pf.benchmark=lambda *args:None
  def history(day):
   import pandas as pd
   dates=pd.bdate_range(end=day,periods=260).strftime('%Y-%m-%d');f=pd.DataFrame({'symbol':'RELIANCE-EQ','trade_date':dates,'open':100.,'high':101.,'low':99.,'close':100.,'volume':1})
   return f
  current=[history('2026-11-06')]
  e.universe=lambda:['RELIANCE-EQ'];e.read_history=lambda *args:current[0]
  def fake(i,g):
   f=g.copy();f['entry_condition']=True;f['exit_condition']=False;return f
  e.indicator=fake
  try:
   e.now=lambda:datetime(2026,11,7,10,tzinfo=e.IST);r=e.scan(self.db,None,bootstrap=True);self.assertEqual(r['signals_queued'],0)
   current[0]=history('2026-11-06');last=current[0].iloc[-1].copy();last['trade_date']='2026-11-08';import pandas as pd;current[0]=pd.concat([current[0],pd.DataFrame([last])],ignore_index=True)
   e.now=lambda:T;r=e.scan(self.db,None);self.assertEqual(r['signals_queued'],7);self.assertEqual(e.scan(self.db,None)['signals_queued'],0)
   class Feed:
    def quotes(_,symbols):return {'RELIANCE-EQ':self.quote()}
   r=e.monitor(self.db,Feed());self.assertEqual(r['fills'],7);self.assertEqual(e.monitor(self.db,Feed())['fills'],0);self.assertEqual(len(self.db.positions()),7)
  finally:e.universe=old_u;e.read_history=old_read;e.indicator=old_indicator;e.pf.evaluate=old_eval;e.pf.benchmark=old_benchmark;e.now=lambda:T
 def test_provider_error_rejected(self):
  q=self.quote();q['provider_status']='error';self.assertFalse(e.fill(self.db,self.signal(),q,T)['filled'])
 def test_quote_must_not_predate_signal_bar(self):
  s=self.signal(eligible='2026-11-11');self.assertFalse(e.fill(self.db,s,self.quote(),T)['filled'])
 def test_signal_tamper_rolls_back(self):
  s=self.signal();s['strategy']=2
  with self.assertRaises(RuntimeError):e.fill(self.db,s,self.quote(),T)
  self.assertEqual(len(self.db.positions()),0);self.assertEqual(len(self.db.query('SELECT * FROM paper_fills WHERE namespace=?',(e.NS,))),0)
 def test_old_position_exit_guard(self):
  e.fill(self.db,self.signal(),self.quote(),T);s=self.signal('SELL');self.db.batch([('UPDATE paper_signals SET reason=? WHERE namespace=? AND id=?',('daily_exit:2026-11-01T10:00:00+05:30',e.NS,s['id']))]);self.assertFalse(e.fill(self.db,s,self.quote(),T)['filled']);self.assertEqual(len(self.db.positions()),1)
 def test_frozen_indicators_match_originals(self):
  import ast,numpy as np,pandas as pd
  n=400;c=100+np.sin(np.arange(n)/9)*15+np.arange(n)*.02;g=pd.DataFrame({'open':c-.3,'high':c+1,'low':c-1,'close':c,'volume':100,'trade_date':pd.date_range('2025-01-01',periods=n).strftime('%Y-%m-%d')})
  for strategy,path in e.STRATEGY_SOURCES.items():
   source=Path('/workspace/strategies')/path;name='supertrend' if strategy==2 else 'indicators';fn=next(x for x in ast.parse(source.read_text()).body if isinstance(x,ast.FunctionDef) and x.name==name);ns={'np':np,'pd':pd};exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),ns);pd.testing.assert_frame_equal(e.indicator(strategy,g),ns[name](g))
  f=e.indicator(1,g);self.assertEqual(bool(f.entry_condition.iloc[-1]),g.close.iloc[-1]>g.high.iloc[-21:-1].max())
 def test_auth_retry_bounded_once(self):
  from unittest.mock import patch
  api=e.MarketData.__new__(e.MarketData);api.env={'FYERS_APP_ID':'fixture','FYERS_ACCESS_TOKEN':'fixture'};api.last=0;api.refreshed=False;count=[0]
  def refresh():
   if api.refreshed:raise RuntimeError('auth_failed_after_single_refresh')
   api.refreshed=True;count[0]+=1
  api.refresh=refresh
  class Response:
   status_code=401
   def json(self):return {'s':'error','code':-16}
  with patch.object(e.requests,'get',return_value=Response()) as req,patch.object(e.time,'sleep'):
   with self.assertRaises(RuntimeError):api.get('quotes',{'symbols':'NSE:RELIANCE-EQ'})
   self.assertEqual(count[0],1);self.assertEqual(req.call_count,2)
 def test_quote_batch_size(self):
  api=e.MarketData.__new__(e.MarketData);calls=[]
  def get(route,params):calls.append((route,params['symbol'].split(',')));return {'s':'ok','d':{}}
  api.get=get;q=api.quotes(['X'+str(i)+'-EQ' for i in range(101)]);self.assertEqual(len(calls),101);self.assertTrue(all(r=='depth' and len(x)==1 for r,x in calls));self.assertTrue(all(v['quote_at'] is None for v in q.values()))
 def test_real_order_routes_absent(self):
  self.assertEqual(set(e.AUTH_ROUTES),{'quotes','history','depth'});self.assertTrue(all('/data/' in u for u in e.AUTH_ROUTES.values()));self.assertTrue(e.CFG['paper_only']);self.assertGreater(e.CFG['quantity'],0)
if __name__=='__main__':unittest.main(verbosity=2)
