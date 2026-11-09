import sys,unittest
from pathlib import Path
from datetime import datetime,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));import engine as e
T=datetime(2026,11,9,12,32,tzinfo=e.IST)
MIDNIGHT_TT=1794182400  # 2026-11-09 00:00 UTC == 05:30 IST: what /data/quotes returns as `tt`
class DepthQuoteFreshness(unittest.TestCase):
 def api(self,payloads):
  api=e.MarketData.__new__(e.MarketData);calls=[]
  def get(route,params):
   calls.append((route,params));item=payloads[params['symbol']]
   if isinstance(item,Exception):raise item
   return {'s':'ok','d':{params['symbol']:item}}
  api.get=get;api.calls=calls;return api
 def q(self,ltt,price=1307.7,sym='RELIANCE-EQ'):
  return self.api({'NSE:'+sym:{'ltp':price,'ltt':ltt,'v':100}}).quotes([sym])[sym]
 def test_midnight_tt_style_stamp_rejected(self):
  q=self.q(MIDNIGHT_TT);self.assertEqual(q['quote_at'],'2026-11-09T05:30:00+05:30');self.assertEqual(e.valid_quote(q,T),(False,'stale_or_future_quote'))
 def test_fresh_ltt_accepted(self):
  q=self.q(int((T-timedelta(seconds=5)).timestamp()));self.assertEqual(q['price'],1307.7);self.assertEqual(q['source'],'FYERS_DEPTH_LTT');self.assertTrue(e.valid_quote(q,T)[0])
 def test_stale_ltt_rejected_60s_rule_unchanged(self):
  self.assertEqual(e.CFG['quote_max_age_seconds'],60)
  self.assertTrue(e.valid_quote(self.q(int((T-timedelta(seconds=60)).timestamp())),T)[0])
  self.assertEqual(e.valid_quote(self.q(int((T-timedelta(seconds=61)).timestamp())),T),(False,'stale_or_future_quote'))
 def test_missing_or_invalid_ltt_fails_closed(self):
  for bad in [None,'',0,-5,'abc',float('nan'),True,'1794207721x']:
   q=self.q(bad);self.assertIsNone(q['quote_at']);self.assertEqual(e.valid_quote(q,T),(False,'missing_exchange_timestamp'))
  q=self.api({'NSE:RELIANCE-EQ':{'ltp':1307.7}}).quotes(['RELIANCE-EQ'])['RELIANCE-EQ'];self.assertEqual(e.valid_quote(q,T),(False,'missing_exchange_timestamp'))
 def test_future_ltt_rejected(self):
  self.assertEqual(e.valid_quote(self.q(int((T+timedelta(seconds=30)).timestamp())),T),(False,'stale_or_future_quote'))
 def test_missing_symbol_and_provider_error_fail_closed(self):
  api=self.api({'NSE:A-EQ':RuntimeError('market_data_error_-50')});q=api.quotes(['A-EQ'])['A-EQ'];self.assertEqual(q['provider_status'],'error');self.assertFalse(e.valid_quote(q,T)[0])
  api=e.MarketData.__new__(e.MarketData);api.get=lambda r,p:{'s':'ok','d':{}};q=api.quotes(['B-EQ'])['B-EQ'];self.assertEqual(q['provider_status'],'missing');self.assertFalse(e.valid_quote(q,T)[0])
 def test_transport_and_auth_errors_still_raise(self):
  for err in ['market_data_transport_failed','auth_circuit_open_30min','market_data_rate_limit']:
   with self.assertRaisesRegex(RuntimeError,err):self.api({'NSE:A-EQ':RuntimeError(err)}).quotes(['A-EQ'])
 def test_one_symbol_per_depth_request(self):
  api=self.api({'NSE:A-EQ':{'ltp':1,'ltt':1},'NSE:B-EQ':{'ltp':2,'ltt':2}});api.quotes(['A-EQ','B-EQ'])
  self.assertEqual([(r,p['symbol']) for r,p in api.calls],[('depth','NSE:A-EQ'),('depth','NSE:B-EQ')])
 def test_exit_path_uses_same_gate(self):
  # Strategy-7 stop and all SELL fills call valid_quote on the same quote dict, so stale exits are blocked too.
  stale=self.q(MIDNIGHT_TT);self.assertFalse(e.valid_quote(stale,T)[0])
if __name__=='__main__':unittest.main(verbosity=2)
