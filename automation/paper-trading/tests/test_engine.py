import json,sys,unittest,uuid,threading
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
  out=e.fill(self.db,self.signal('SELL'),self.quote(110),T);self.assertEqual(out['realized_pnl'],5000)
  p=e.pnl(self.db);self.assertEqual(p['daily_mark_to_market_pnl_INR'],5000);self.assertEqual(p['latest_known_total_pnl_INR'],5000);self.assertEqual(len(self.db.positions()),0)
 def test_multistock_and_strategy_separation(self):
  for sym,strategy in [('RELIANCE-EQ',1),('RELIANCE-EQ',2),('TCS-EQ',1)]:self.assertTrue(e.fill(self.db,self.signal(symbol=sym,strategy=strategy),self.quote(),T)['filled'])
  self.assertEqual(len(self.db.positions()),3)
 def test_no_oversell(self):self.assertFalse(e.fill(self.db,self.signal('SELL'),self.quote(),T)['filled'])
 def test_cannot_duplicate_position(self):
  e.fill(self.db,self.signal(),self.quote(),T);self.assertFalse(e.fill(self.db,self.signal(),self.quote(),T)['filled'])
 def test_reject_stale(self):self.assertFalse(e.fill(self.db,self.signal(),self.quote(age=61),T)['filled'])
 def test_reject_future(self):self.assertFalse(e.fill(self.db,self.signal(),self.quote(age=-10),T)['filled'])
 def test_reject_zero(self):self.assertFalse(e.fill(self.db,self.signal(),self.quote(0),T)['filled'])
 def test_target_notional_share_count_and_unaffordable_skip(self):
  priced=e.fill(self.db,self.signal(),self.quote(2500),T);self.assertTrue(priced['filled']);self.assertEqual(priced['qty'],20)
  s=self.signal(strategy=2);r=e.fill(self.db,s,self.quote(60000),T);self.assertFalse(r['filled']);self.assertEqual(r['reason'],'UNAFFORDABLE_ZERO_SHARES');self.assertEqual(r['quantity'],0)
  self.assertEqual(self.db.query('SELECT status FROM paper_signals WHERE namespace=? AND id=?',(e.NS,s['id']))[0]['status'],'pending')
  self.assertFalse(self.db.query('SELECT * FROM paper_fills WHERE namespace=? AND strategy=2',(e.NS,)))
  rows=self.db.query("SELECT data_json FROM paper_events WHERE namespace=? AND event_type='paper_order_result'",(e.NS,));self.assertTrue(any(json.loads(x['data_json']).get('reason')=='UNAFFORDABLE_ZERO_SHARES' for x in rows))
  exact=e.fill(self.db,self.signal(strategy=3),self.quote(50000),T);self.assertTrue(exact['filled']);self.assertEqual(exact['qty'],1)
 def test_sleeve_holds_nine_positions_and_keeps_the_next_entry_pending(self):
  symbols=['360ONE-EQ','3MINDIA-EQ','ABB-EQ','ACC-EQ','AGI-EQ','AIAENG-EQ','APLAPOLLO-EQ','ASKAUTOLTD-EQ','AUBANK-EQ','AARTIDRUGS-EQ']
  for sym in symbols[:9]:self.assertTrue(e.fill(self.db,self.signal(symbol=sym,strategy=1),self.quote(),T)['filled'])
  skipped=self.signal(symbol=symbols[9],strategy=1);r=e.fill(self.db,skipped,self.quote(),T)
  self.assertFalse(r['filled']);self.assertEqual(r['reason'],'SLEEVE_SLOT_FULL');self.assertEqual(r['quantity'],0);self.assertEqual(r['open_positions'],9)
  self.assertEqual(self.db.query('SELECT status FROM paper_signals WHERE namespace=? AND id=?',(e.NS,skipped['id']))[0]['status'],'pending')
  self.assertFalse(self.db.query('SELECT * FROM paper_fills WHERE namespace=? AND strategy=1 AND symbol=?',(e.NS,symbols[9])))
  blocked=self.db.query("SELECT outcome,data_json FROM paper_events WHERE namespace=? AND event_type='paper_order_blocked'",(e.NS,))
  self.assertTrue(any(x['outcome']=='SLEEVE_SLOT_FULL' and json.loads(x['data_json']).get('open_positions')==9 for x in blocked))
  self.assertTrue(e.fill(self.db,self.signal(symbol=symbols[9],strategy=2),self.quote(),T)['filled'])
  self.assertTrue(e.fill(self.db,self.signal('SELL',symbol=symbols[0],strategy=1),self.quote(110),T)['filled'])
  self.assertTrue(e.fill(self.db,skipped,self.quote(),T)['filled'])
  self.assertEqual(len([p for p in self.db.positions() if p['strategy']==1]),9)
 def test_monitor_frees_a_slot_before_entries_and_hashes_the_last_slot(self):
  symbols=['360ONE-EQ','3MINDIA-EQ','ABB-EQ','ACC-EQ','AGI-EQ','AIAENG-EQ','APLAPOLLO-EQ','ASKAUTOLTD-EQ','AUBANK-EQ']
  for sym in symbols:self.assertTrue(e.fill(self.db,self.signal(symbol=sym,strategy=1),self.quote(),T)['filled'])
  contenders=['AARTIDRUGS-EQ','AARTIIND-EQ'];day=T.date().isoformat()
  winner=min(contenders,key=lambda sym:(e.cap.slot_rank(day,sym),sym));loser=[sym for sym in contenders if sym!=winner][0]
  sell=self.signal('SELL',symbol=symbols[0],strategy=1);buy=self.signal(symbol=winner,strategy=1);other=self.signal(symbol=loser,strategy=1)
  class Feed:
   def quotes(_,requested):return {sym:{'symbol':sym,'price':100,'quote_at':T.isoformat(),'provider_status':'ok'} for sym in requested}
  report=e.monitor(self.db,Feed());self.assertEqual(report['fills'],2)
  self.assertFalse(self.db.query('SELECT * FROM paper_positions WHERE namespace=? AND strategy=1 AND symbol=? AND qty>0',(e.NS,symbols[0])))
  self.assertTrue(self.db.query('SELECT * FROM paper_positions WHERE namespace=? AND strategy=1 AND symbol=? AND qty>0',(e.NS,winner)))
  self.assertEqual(self.db.query('SELECT status FROM paper_signals WHERE namespace=? AND id=?',(e.NS,other['id']))[0]['status'],'pending')
  self.assertEqual(len([p for p in self.db.positions() if p['strategy']==1]),9)
 def test_fill_is_ltp_legacy_and_decision_chain_detects_tamper(self):
  s=self.signal();r=e.fill(self.db,s,self.quote(),T);self.assertTrue(r['filled']);self.assertEqual(r['execution_path'],'LTP_LEGACY');self.assertEqual(r['correlation_id'],s['id'])
  self.assertEqual(self.db.query('SELECT execution_path FROM paper_fills WHERE namespace=?',(e.NS,))[0]['execution_path'],'LTP_LEGACY')
  decision=self.db.query('SELECT * FROM paper_decisions WHERE namespace=? AND correlation_id=?',(e.NS,s['id']))[0]
  self.assertEqual(decision['decision_type'],'ENTRY');self.assertEqual(decision['cause'],'filled');self.assertEqual(decision['execution_path'],'LTP_LEGACY')
  payload=json.loads(decision['payload_json']);self.assertEqual(payload['quantity'],500);self.assertEqual(payload['price'],100);self.assertEqual(payload['open_positions_before'],0);self.assertIn('strategy_version',payload)
  self.assertTrue(self.db.call({'action':'verify_decisions','namespace':e.NS})['ok'])
  self.db.batch([('UPDATE paper_decisions SET cause=? WHERE namespace=? AND seq=?',('tampered',e.NS,decision['seq']))])
  self.assertFalse(self.db.call({'action':'verify_decisions','namespace':e.NS})['ok'])
 def test_unaffordable_skip_is_on_the_decision_chain(self):
  s=self.signal(strategy=2);r=e.fill(self.db,s,self.quote(60000),T);self.assertEqual(r['reason'],'UNAFFORDABLE_ZERO_SHARES')
  decision=self.db.query('SELECT decision_type,cause,execution_path FROM paper_decisions WHERE namespace=? AND correlation_id=?',(e.NS,s['id']))[0]
  self.assertEqual(decision['decision_type'],'SKIP');self.assertEqual(decision['cause'],'UNAFFORDABLE_ZERO_SHARES');self.assertEqual(decision['execution_path'],'LTP_LEGACY')
  self.assertTrue(self.db.call({'action':'verify_decisions','namespace':e.NS})['ok'])
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
  r=e.monitor(self.db,Feed());self.assertEqual(r['fills'],1);fills=self.db.query('SELECT * FROM paper_fills WHERE namespace=? ORDER BY id',(e.NS,));self.assertEqual(fills[-1]['price'],85);self.assertEqual(fills[-1]['realized_pnl'],-7500)
 def test_closed_monitor_no_quotes(self):
  e.now=lambda:datetime(2026,11,7,10,tzinfo=e.IST)
  class Feed:
   def quotes(_,s):raise AssertionError('should not fetch')
  self.assertEqual(e.monitor(self.db,Feed())['fills'],0)
 def test_daily_start_mark_not_entry_basis(self):
  # Position opened during prior special session, cost90; previous completed close100; current mark105.
  yesterday=datetime(2026,11,8,14,30,tzinfo=e.IST);s=self.signal(eligible='2026-11-08');q={'price':90,'quote_at':yesterday.isoformat()};self.assertTrue(e.fill(self.db,s,q,yesterday)['filled'])
  self.db.batch([('INSERT INTO daily_ohlcv(symbol,trade_date,close) VALUES(?,?,?)',('RELIANCE-EQ','2026-11-08',100)),('UPDATE paper_positions SET mark_price=?,mark_at=? WHERE namespace=?',(105,T.isoformat(),e.NS))]);p=e.pnl(self.db);self.assertEqual(p['daily_mark_to_market_pnl_INR'],2775);self.assertEqual(p['latest_known_total_pnl_INR'],8325)
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
  def get(route,params):calls.append(params['symbols'].split(','));return {'d':[]}
  api.get=get;api.quotes(['X'+str(i)+'-EQ' for i in range(101)]);self.assertEqual([len(x) for x in calls],[50,50,1])
 def test_real_order_routes_absent(self):
  self.assertEqual(set(e.AUTH_ROUTES),{'quotes','history'});self.assertTrue(e.CFG['paper_only']);self.assertEqual(e.cap.POLICY['target_notional_inr'],50000)
if __name__=='__main__':unittest.main(verbosity=2)
