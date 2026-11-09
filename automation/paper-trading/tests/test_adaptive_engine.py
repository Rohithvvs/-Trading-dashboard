import sqlite3, sys, unittest
from datetime import date, timedelta
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import adaptive_engine as ae
import adaptive_logging as alog
import pit_archive as pit


class MemDB:
    def __init__(self):
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row

    def batch(self, stm):
        with self.c:
            for sql, args in stm:
                self.c.execute(sql, args)

    def query(self, sql, args=()):
        return [dict(r) for r in self.c.execute(sql, args).fetchall()]


class AdaptiveEngineTests(unittest.TestCase):
    def setUp(self):
        self.db = MemDB()
        for sql in (Path(__file__).resolve().parents[1] / 'schema.sql').read_text().split(';'):
            if sql.strip():
                self.db.batch([(sql.strip(), ())])
        pit.init(self.db)
        alog.init(self.db)

    def test_3_tier_limits_and_parameter_only_mutation_locks(self):
        ns = 'test_3tier'
        # Track A baseline cannot be mutated
        with self.assertRaises(ValueError):
            ae.spawn_candidate(self.db, ns, strategy=3, params={'rsi_entry': 35.0}, track='A')
        base = ae.spawn_candidate(self.db, ns, strategy=3, params={}, track='A', candidate_kind='BASELINE')
        self.assertEqual(base['warm_start_days'], 60)
        self.assertEqual(base['eval_window_target_days'], 45)

        # Disallowed non-parameter key rejected
        with self.assertRaises(ValueError):
            ae.spawn_candidate(self.db, ns, strategy=3, params={'custom_indicator': 10}, track='B')

        # Track B allows max 3 concurrent challengers per strategy
        for idx, rsi_val in enumerate([35.0, 36.0, 38.0], start=1):
            sp = ae.spawn_candidate(self.db, ns, strategy=3, params={'rsi_entry': rsi_val}, track='B')
            self.assertEqual(sp['tier'], 'FAST_SWING')
        with self.assertRaises(RuntimeError):
            ae.spawn_candidate(self.db, ns, strategy=3, params={'rsi_entry': 39.0}, track='B')

        # Track C allows max 1 champion per strategy
        champ = ae.spawn_candidate(self.db, ns, strategy=1, params={'entry_lookback': 22}, track='C')
        self.assertEqual(champ['warm_start_days'], 110)
        self.assertEqual(champ['eval_window_target_days'], 75)
        with self.assertRaises(RuntimeError):
            ae.spawn_candidate(self.db, ns, strategy=1, params={'entry_lookback': 25}, track='C')

    def test_warm_start_lengths_net_of_haircut_equity_and_discordant_split(self):
        # Fast swing must be 60 days; Trend must be 100..120 days
        self.assertEqual(ae.validate_warm_start_days(3, 60), 60)
        self.assertEqual(ae.validate_warm_start_days(5, 60), 60)
        with self.assertRaises(ValueError):
            ae.validate_warm_start_days(3, 100)
        self.assertEqual(ae.validate_warm_start_days(1, 100), 100)
        self.assertEqual(ae.validate_warm_start_days(7, 120), 120)
        with self.assertRaises(ValueError):
            ae.validate_warm_start_days(7, 60)

        # Starting equity E_0 valued net of exit haircut
        eq = ae.value_starting_equity_net_of_haircut(
            cash_paise=40_000_000,
            open_positions=[{'symbol': 'RELIANCE-EQ', 'qty': 100, 'entry_price': 950.0, 'mark_price': 1000.0, 'series': 'EQ'}],
        )
        self.assertEqual(eq['starting_equity_gross_paise'], 50_000_000)
        self.assertGreater(eq['exit_haircut_paise'], 0)
        self.assertEqual(
            eq['starting_equity_net_haircut_paise'],
            eq['starting_equity_gross_paise'] - eq['exit_haircut_paise'],
        )

        # BE/BZ and lower-circuit locked positions incur a strictly larger exit haircut
        eq_stress = ae.value_starting_equity_net_of_haircut(
            cash_paise=40_000_000,
            open_positions=[{'symbol': 'RELIANCE-EQ', 'qty': 100, 'entry_price': 950.0, 'mark_price': 1000.0, 'series': 'BE', 'locked_days': 3}],
        )
        self.assertGreater(eq_stress['exit_haircut_paise'], eq['exit_haircut_paise'])

        # Inherited warm-start discordant trades counted separately from evaluation-window discordant trades
        base_trades = [
            {'symbol': 'INFY-EQ', 'entry_date': '2025-05-10', 'exit_date': '2025-06-15', 'qty': 50},
            {'symbol': 'TCS-EQ', 'entry_date': '2025-06-10', 'exit_date': '2025-06-20', 'qty': 20},
        ]
        var_trades = [
            {'symbol': 'INFY-EQ', 'entry_date': '2025-05-10', 'exit_date': '2025-06-18', 'qty': 50},  # inherited discordant
            {'symbol': 'TCS-EQ', 'entry_date': '2025-06-10', 'exit_date': '2025-06-20', 'qty': 20},   # concordant
            {'symbol': 'SBIN-EQ', 'entry_date': '2025-06-12', 'exit_date': '2025-06-25', 'qty': 100}, # new discordant
        ]
        disc = ae.classify_discordant_trades(var_trades, base_trades, warm_start_end_date='2025-06-01')
        self.assertEqual(disc['inherited_discordant_count'], 2)  # base exit 06-15 vs var exit 06-18
        self.assertEqual(disc['new_discordant_count'], 1)        # SBIN-EQ entered after 2025-06-01
        self.assertEqual(disc['distinct_new_entry_weeks'], 1)

    def test_windows_single_extension_and_inconclusive_stopping(self):
        ns = 'test_stop'
        sp = ae.spawn_candidate(self.db, ns, strategy=3, params={'rsi_entry': 36.0}, track='B')
        sid = sp['spawn_id']

        # Before 45 days: not ready, no early peeking
        early = ae.evaluate_stopping_and_window(self.db, ns, sid, days_elapsed=30, new_discordant_trades=15, distinct_entry_weeks=5)
        self.assertFalse(early['ready_for_final_gate_evaluation'])

        # At day 45 with only 6 discordant trades (< 10): grants single +15d extension
        ext = ae.evaluate_stopping_and_window(self.db, ns, sid, days_elapsed=45, new_discordant_trades=6, distinct_entry_weeks=2)
        self.assertFalse(ext['ready_for_final_gate_evaluation'])
        self.assertEqual(ext['status'], 'EXTENDED')
        self.assertEqual(ext['extension_days'], 15)
        self.assertEqual(ext['required_days'], 60)

        # At day 60 (after +15d extension) still under floor -> status = INCONCLUSIVE
        inc = ae.evaluate_stopping_and_window(self.db, ns, sid, days_elapsed=60, new_discordant_trades=8, distinct_entry_weeks=2)
        self.assertFalse(inc['ready_for_final_gate_evaluation'])
        self.assertEqual(inc['status'], 'INCONCLUSIVE')

    def test_pit_corporate_action_indicator_back_adjustment(self):
        dates = ['2025-07-01', '2025-07-02', '2025-07-03', '2025-07-04']
        prices = [1000.0, 1020.0, 515.0, 525.0]  # 2:1 split on ex-date 2025-07-03
        df = pd.DataFrame([
            {'symbol': 'SPLITCO-EQ', 'trade_date': d, 'open': p, 'high': p * 1.01, 'low': p * 0.99, 'close': p, 'volume': 1000}
            for d, p in zip(dates, prices)
        ])
        corp = [{'symbol': 'SPLITCO-EQ', 'ex_date': '2025-07-03', 'kind': 'SPLIT', 'ratio_num': 2, 'ratio_den': 1}]

        # Before ex-date (as_of 2025-07-02): future split is NOT applied
        before = ae.back_adjust_ohlc_pit(df, corp, as_of_date='2025-07-02')
        self.assertAlmostEqual(float(before.iloc[-1]['close']), 1020.0)

        # On/after ex-date (as_of 2025-07-03): pre-split bars are divided by 2
        on_ex = ae.back_adjust_ohlc_pit(df, corp, as_of_date='2025-07-03')
        self.assertAlmostEqual(float(on_ex.iloc[0]['close']), 500.0)
        self.assertAlmostEqual(float(on_ex.iloc[1]['close']), 510.0)
        self.assertAlmostEqual(float(on_ex.iloc[2]['close']), 515.0)
        self.assertAlmostEqual(float(on_ex.iloc[1]['volume']), 2000.0)


if __name__ == '__main__':
    unittest.main()
