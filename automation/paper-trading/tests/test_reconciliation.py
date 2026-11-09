import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reconciliation as rec


class ReconciliationTests(unittest.TestCase):
    def test_stage_a_and_b_harness_maps_named_causes_and_never_fakes_live_acceptance(self):
        signals = [
            {'bar_date': '2026-11-06', 'strategy': 1, 'symbol': 'RELIANCE-EQ', 'side': 'BUY'},
            {'bar_date': '2026-11-06', 'strategy': 7, 'symbol': 'TCS-EQ', 'side': 'SELL'},
        ]
        warmup = {'RELIANCE-EQ': 260, 'TCS-EQ': 260}
        baseline_fills = [
            {'correlation_id': 'sig-1', 'strategy': 1, 'symbol': 'RELIANCE-EQ', 'quantity': 500, 'price': 100.09},
            {'correlation_id': 'sig-2', 'strategy': 2, 'symbol': 'INFY-EQ', 'quantity': 500, 'price': 100.09},
            {'correlation_id': 'sig-3', 'strategy': 3, 'symbol': 'HDFCBANK-EQ', 'quantity': 500, 'price': 100.09},
            {'correlation_id': 'sig-4', 'strategy': 4, 'symbol': 'SBIN-EQ', 'quantity': 500, 'price': 100.09},
            {'correlation_id': 'sig-5', 'strategy': 5, 'symbol': 'ICICIBANK-EQ', 'quantity': 500, 'price': 100.09},
            {'correlation_id': 'sig-6', 'strategy': 6, 'symbol': 'AXISBANK-EQ', 'quantity': 500, 'price': 100.09},
            {'correlation_id': 'sig-7', 'strategy': 7, 'symbol': 'TCS-EQ', 'quantity': 500, 'price': 85.0},
            {'correlation_id': 'sig-8', 'strategy': 7, 'symbol': 'WIPRO-EQ', 'quantity': 500, 'price': 85.0},
            {'correlation_id': 'sig-9', 'strategy': 1, 'symbol': 'LT-EQ', 'quantity': 500, 'price': 100.09},
            {'correlation_id': 'sig-10', 'strategy': 1, 'symbol': 'ITC-EQ', 'quantity': 500, 'price': 100.09},
        ]
        candidate_decisions = [
            {'correlation_id': 'sig-1', 'strategy': 1, 'symbol': 'RELIANCE-EQ', 'cause': 'filled', 'rule': 'feed_official_open', 'execution_path': 'FEED_OPEN', 'payload': {'quantity': 500, 'price': 100.09}},
            {'correlation_id': 'sig-2', 'strategy': 2, 'symbol': 'INFY-EQ', 'cause': 'ADV_FILTER_SKIP', 'rule': 'median_20d_traded_value_vs_placeholder_floor', 'execution_path': 'FEED_OPEN', 'payload': {'quantity': 0}},
            {'correlation_id': 'sig-3', 'strategy': 3, 'symbol': 'HDFCBANK-EQ', 'cause': 'ISIN_CAP', 'rule': 'max_3_strategies_per_symbol', 'execution_path': 'FEED_OPEN', 'payload': {'quantity': 0}},
            {'correlation_id': 'sig-4', 'strategy': 4, 'symbol': 'SBIN-EQ', 'cause': 'SLEEVE_SLOT_FULL', 'rule': 'max_9_open_positions_per_sleeve', 'execution_path': 'FEED_OPEN', 'payload': {'quantity': 0}},
            {'correlation_id': 'sig-5', 'strategy': 5, 'symbol': 'ICICIBANK-EQ', 'cause': 'KILL_PAUSE', 'rule': 'pause_blocks_new_entries_exits_still_run', 'execution_path': 'FEED_OPEN', 'payload': {'quantity': 0}},
            {'correlation_id': 'sig-6', 'strategy': 6, 'symbol': 'AXISBANK-EQ', 'cause': 'CIRCUIT_LOCKED', 'rule': 'upper_circuit_blocks_buys_until_close', 'execution_path': 'FEED_OPEN', 'payload': {'quantity': 0}},
            {'correlation_id': 'sig-7', 'strategy': 7, 'symbol': 'TCS-EQ', 'cause': 'filled', 'rule': 'trail_gap', 'execution_path': 'FEED_OPEN', 'payload': {'quantity': 500, 'price': 79.92}},
            {'correlation_id': 'sig-8', 'strategy': 7, 'symbol': 'WIPRO-EQ', 'cause': 'filled', 'rule': 'trail_touch', 'execution_path': 'LTP_LEGACY', 'payload': {'quantity': 500, 'price': 90.0}},
            {'correlation_id': 'sig-9', 'strategy': 1, 'symbol': 'LT-EQ', 'cause': 'filled', 'rule': 'first_trade_fallback', 'execution_path': 'FALLBACK_OPEN', 'payload': {'quantity': 500, 'price': 100.09}},
            {'correlation_id': 'sig-10', 'strategy': 1, 'symbol': 'ITC-EQ', 'cause': 'filled', 'rule': 'ltp_legacy_fill', 'execution_path': 'LTP_LEGACY', 'payload': {'quantity': 500, 'price': 100.09, 'lock_unknown': True}},
            {'correlation_id': 'ca-1', 'strategy': 1, 'symbol': 'RELIANCE-EQ', 'cause': 'STATE_SCALING', 'rule': 'split_bonus_state_scaled', 'execution_path': 'LTP_LEGACY', 'payload': {}},
            {'correlation_id': 'ca-2', 'strategy': 1, 'symbol': 'RELIANCE-EQ', 'cause': 'CASH_CREDITED', 'rule': 'fractional_share_credited_at_open', 'execution_path': 'FEED_OPEN', 'payload': {}},
            {'correlation_id': 'ca-3', 'strategy': 1, 'symbol': 'ICICIBANK-EQ', 'cause': 'CORP_ACTION_MANUAL_REVIEW', 'rule': 'manual_review_required', 'execution_path': 'LTP_LEGACY', 'payload': {}},
        ]
        feed_opens = [{'symbol': 'RELIANCE-EQ', 'open': '100.05'}]
        bhav_rows = [{'SYMBOL': 'RELIANCE', 'SERIES': 'EQ', 'OPEN': '100.00'}]
        report = rec.run_harness(
            signals,
            signals,
            baseline_fills,
            candidate_decisions,
            warmup_bars_by_symbol=warmup,
            feed_opens=feed_opens,
            bhav_rows=bhav_rows,
            trade_date='2026-11-09',
            env_path='/nonexistent/.env',
            bhavcopy_dir='/nonexistent/bhavcopy',
        )
        self.assertEqual(report['status'], 'EXTERNAL_BLOCKER_LIVE_DATA_AND_BHAVCOPY_REQUIRED')
        self.assertFalse(report['acceptance_claimed'])
        self.assertTrue(report['stage_a']['local_fixture_signal_match'])
        self.assertFalse(report['stage_a']['live_month_acceptance_claimed'])
        self.assertTrue(report['stage_b']['all_divergences_named'])
        self.assertFalse(report['stage_b']['live_month_acceptance_claimed'])
        causes = report['stage_b']['divergences_by_cause']
        for expected in ('OFFICIAL_OPEN_DIFF', 'ADV_FILTER_SKIP', 'ISIN_CAP', 'SLEEVE_SLOT_FULL', 'KILL_PAUSE', 'CIRCUIT_LOCKED', 'trail_gap', 'trail_touch', 'FALLBACK_OPEN', 'LOCK_UNKNOWN', 'STATE_SCALING', 'CASH_CREDITED', 'CORP_ACTION_MANUAL_REVIEW'):
            self.assertIn(expected, causes)
        for not_invented in ('DATA_REVISION', 'SPECIAL_SESSION_EXCLUDED', 'STRATEGY_VERSION_DIFF', 'PARTIAL_FILL'):
            self.assertNotIn(not_invented, rec.NAMED_CAUSES)
        short = rec.reconcile_stage_a(signals, signals, warmup_bars_by_symbol={'RELIANCE-EQ': 259})
        self.assertFalse(short['local_fixture_signal_match'])
        self.assertEqual(short['short_warmup_symbols'], ['RELIANCE-EQ'])
        unknown = rec.reconcile_stage_b(
            [{'correlation_id': 'u-1', 'strategy': 1, 'symbol': 'RELIANCE-EQ', 'quantity': 500, 'price': 100}],
            [{'correlation_id': 'u-1', 'strategy': 1, 'symbol': 'RELIANCE-EQ', 'cause': 'UNEXPLAINED_DIFF', 'rule': 'unknown', 'execution_path': 'LTP_LEGACY', 'payload': {}}],
        )
        self.assertFalse(unknown['all_divergences_named'])
        self.assertEqual(len(unknown['unmapped_divergences']), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
