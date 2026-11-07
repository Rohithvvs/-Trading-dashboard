import unittest,sqlite3,json
from unittest.mock import patch
from datetime import datetime,timedelta,date
import pandas as pd
import engine as e
import history_repair as h
class DB:
 def __init__(self):
  self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.c.execute('CREATE TABLE daily_ohlcv(trade_date TEXT,symbol TEXT,open REAL,high REAL,low REAL,close REAL,volume REAL,turnover REAL,source TEXT,loaded_at TEXT,PRIMARY KEY(trade_date,symbol))')
 def query(self,s,args=()):return [dict(r) for r in self.c.execute(s,args).fetchall()]
 def batch(self,stm):
  with self.c:
   for s,args in stm:self.c.execute(s,args)
class RepairTests(unittest.TestCase):
 def setUp(self):
  self.db=DB();self.target=date(2026,11,6);self.dates=list(pd.bdate_range(end=str(self.target),periods=253).strftime('%Y-%m-%d'));self.time=datetime(2026,11,7,12,tzinfo=e.IST);self.patches=[patch.object(e,'now',side_effect=lambda:self.time),patch.object(e,'universe',return_value=['RELIANCE-EQ']),patch.object(e.pf,'benchmark',return_value=pd.DataFrame({'trade_date':self.dates}))]
  for p in self.patches:p.start()
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
 def seed(self,symbol='RELIANCE-EQ',missing=('2026-09-17',)):
  self.db.batch([('INSERT INTO daily_ohlcv VALUES(?,?,?,?,?,?,?,?,?,?)',(d,symbol,100,101,99,100,10,1000,'fixture','original')) for d in self.dates if d not in missing])
 def candle(self,d,price=110):return [int(datetime.fromisoformat(d+'T00:00:00+05:30').timestamp()),price,price+1,price-1,price,100]
 def feed(self,rows=None,error=None):
  class Feed:
   calls=[]
   def history(_,symbol,start,end):
    _.calls.append((symbol,str(start),str(end)))
    if error:raise RuntimeError(error)
    return rows or []
  return Feed()
 def test_genuine_old_missing_bars_repaired_without_execution_calendar_relaxation_or_overwrite(self):
  self.seed(missing=('2026-09-17','2026-10-21'));api=self.feed([self.candle('2026-09-17'),self.candle('2026-10-21'),self.candle('2026-09-18',999)])
  self.assertIsNone(e.session(date(2026,9,17)));r=h.repair(e,self.db,api,self.target);self.assertEqual(r['accepted_missing_rows'],2);self.assertEqual(r['missing_required_bars_after'],0);self.assertEqual(self.db.query("SELECT close FROM daily_ohlcv WHERE trade_date='2026-09-18'")[0]['close'],100);self.assertEqual(len(api.calls),1)
 def test_invalid_and_future_candles_never_inserted(self):
  self.seed();bad=self.candle('2026-09-17',0);r=h.repair(e,self.db,self.feed([bad,self.candle('2026-11-09')]),self.target);self.assertEqual(r['accepted_missing_rows'],0);self.assertEqual(r['rejected_rows'],2);self.assertEqual(r['no_provider_bar'],1)
 def test_no_provider_history_checkpoint_retries_bounded_not_every_scan(self):
  self.seed();api=self.feed();h.repair(e,self.db,api,self.target);h.repair(e,self.db,api,self.target);self.assertEqual(len(api.calls),1);self.time+=timedelta(days=8);h.repair(e,self.db,api,self.target);self.assertEqual(len(api.calls),2)
 def test_short_available_history_is_not_mislabeled_verified_IPO(self):
  self.seed(missing=self.dates[:-60]);r=h.repair(e,self.db,self.feed(),self.target);self.assertEqual(r['short_history_evidence'][0]['classification'],'insufficient_available_history_not_verified_IPO');self.assertGreater(r['no_provider_bar'],190)
 def test_budget_checkpoint_resumes_and_does_not_refetch_repaired_symbol(self):
  self.seed();self.seed('TCS-EQ');api=self.feed([self.candle('2026-09-17')])
  with patch.object(e,'universe',return_value=['RELIANCE-EQ','TCS-EQ']):
   r=h.repair(e,self.db,api,self.target,budget=1);self.assertEqual(r['status'],'bounded_budget_exhausted');self.assertEqual(r['requests'],1);r=h.repair(e,self.db,api,self.target,budget=1);self.assertEqual(r['accepted_missing_rows'],1);self.assertEqual(r['missing_required_bars_after'],0)
  self.assertEqual(len(api.calls),2)
 def test_auth_circuit_stops_immediately_without_hot_loop(self):
  self.seed();api=self.feed(error='auth_circuit_open_30min');r=h.repair(e,self.db,api,self.target);self.assertEqual(r['status'],'paused_provider_failure');self.assertEqual(len(api.calls),1);self.assertEqual(self.db.query('SELECT outcome FROM paper_history_gap_checks')[0]['outcome'],'TRANSIENT_ERROR')
 def test_rejected_range_checkpoint_is_not_assumed_IPO_or_repeated(self):
  self.seed();api=self.feed(error='market_data_error_-300');r=h.repair(e,self.db,api,self.target);h.repair(e,self.db,api,self.target);self.assertEqual(len(api.calls),1);self.assertEqual(self.db.query('SELECT outcome FROM paper_history_gap_checks')[0]['outcome'],'PROVIDER_REJECTED_RANGE')

 def test_invalid_existing_bar_corrected_only_with_verified_positive_provider_and_audited_before_image(self):
  self.seed(missing=());self.db.batch([("UPDATE daily_ohlcv SET open=0,high=0,low=0,close=0 WHERE trade_date='2026-09-17'",())]);r=h.repair(e,self.db,self.feed([self.candle('2026-09-17')]),self.target);self.assertEqual(r['corrected_invalid_rows'],1);self.assertEqual(self.db.query("SELECT close FROM daily_ohlcv WHERE trade_date='2026-09-17'")[0]['close'],110);before=json.loads(self.db.query('SELECT details_json FROM paper_history_gap_checks')[0]['details_json'])['invalid_original_before_image'];self.assertEqual(before['close'],0)

 def test_verified_historical_special_sunday_is_accepted_without_extending_execution_calendar(self):
  self.seed(missing=());dates=sorted(self.dates+['2026-02-01']);self.assertIsNone(e.session(date(2026,2,1)))
  with patch.object(e.pf,'benchmark',return_value=pd.DataFrame({'trade_date':dates})):
   r=h.repair(e,self.db,self.feed([self.candle('2026-02-01')]),self.target)
  self.assertEqual(r['accepted_missing_rows'],1);self.assertEqual(self.db.query("SELECT close FROM daily_ohlcv WHERE trade_date='2026-02-01'")[0]['close'],110)
