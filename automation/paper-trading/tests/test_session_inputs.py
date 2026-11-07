import unittest,json
from unittest.mock import patch
import pandas as pd
import engine as e
import session_inputs as si
class SessionInputs(unittest.TestCase):
 def frame(self,dates):return pd.DataFrame([{'symbol':'TEST-EQ','trade_date':d,'open':100.,'high':102.,'low':99.,'close':101.,'volume':1000.} for d in dates])
 def test_holidays_removed_not_raw(self):
  raw=self.frame(['2026-01-14','2026-01-15','2026-01-26','2026-02-01']);before=raw.copy(deep=True);clean,details,a=si.filter_history(raw,self.frame(['2026-01-14','2026-02-01']));pd.testing.assert_frame_equal(raw,before);self.assertEqual(clean.trade_date.tolist(),['2026-01-14','2026-02-01']);self.assertEqual(a['excluded_rows'],2);self.assertFalse(a['raw_rows_mutated']);self.assertTrue(details['TEST-EQ']['full_warmup_retained'])
 def test_real_day_missing_benchmark_not_dropped(self):
  clean,d,a=si.filter_history(self.frame(['2026-09-16','2026-09-17','2026-09-18']),self.frame(['2026-09-16','2026-09-18']));self.assertEqual(len(clean),3);self.assertEqual(d['TEST-EQ']['unverified_recent_dates'],['2026-09-17']);self.assertEqual(a['unverified_recent_symbols'],1)
 def test_unknown_saturday_retained_and_flagged(self):
  clean,d,_=si.filter_history(self.frame(['2026-07-03','2026-07-18','2026-07-20']),self.frame(['2026-07-03','2026-07-20']));self.assertIn('2026-07-18',list(clean.trade_date));self.assertEqual(d['TEST-EQ']['unverified_recent_dates'],['2026-07-18'])
 def test_special_sunday_and_full_warmup_preserved(self):
  dates=pd.date_range('2003-01-01','2026-02-01',freq='B').strftime('%Y-%m-%d').tolist()+['2026-02-01'];clean,details,a=si.filter_history(self.frame(dates),self.frame(['2026-01-30','2026-02-01']));self.assertGreater(len(clean),5000);self.assertIn('2026-02-01',list(clean.trade_date));self.assertGreater(details['TEST-EQ']['legacy_before_coverage_rows_retained'],5000);self.assertEqual(a['excluded_by_date']['2026-01-15'],1)
 def test_clean_inputs_all_seven_formula_equivalence(self):
  raw=self.frame(pd.date_range('2024-01-01',periods=330,freq='B').strftime('%Y-%m-%d').tolist());clean,_,_=si.filter_history(raw,raw)
  for strategy in range(1,8):pd.testing.assert_frame_equal(e.indicator(strategy,raw),e.indicator(strategy,clean))
 def test_explicit_evidence_no_generic_weekday_rule(self):
  self.assertEqual(len(si.POLICY['closed_dates']),21);self.assertNotIn('2026-02-01',si.POLICY['closed_dates']);self.assertIn('2026-02-01',si.POLICY['special_sessions_preserved']);self.assertNotIn('2026-09-17',si.POLICY['closed_dates']);self.assertTrue(all(url.startswith('https://') for url in si.POLICY['closed_dates'].values()))
 def test_policy_immutability(self):
  class DB:
   def query(self,sql,args=()):return [{'policy_json':'different'}] if sql.startswith('SELECT') else []
  with self.assertRaisesRegex(RuntimeError,'immutable_input_policy_changed'):si.init(DB())
