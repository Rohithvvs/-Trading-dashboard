import sqlite3, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import adaptive_logging as alog


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


class AdaptiveSchemaAndLoggingTests(unittest.TestCase):
    def setUp(self):
        self.db = MemDB()
        for sql in (Path(__file__).resolve().parents[1] / 'schema.sql').read_text().split(';'):
            if sql.strip():
                self.db.batch([(sql.strip(), ())])
        alog.init(self.db)

    def test_schema_tables_hold_keff_hashes_and_net_of_haircut_equity(self):
        self.db.batch([(
            'INSERT INTO adaptive_spawns('
            'namespace,spawn_id,correlation_id,strategy,track,tier,parent_version,params_json,candidate_kind,'
            'eligible_for_selection,k_cand,rho_bar,k_eff,effective_critical_value,warm_start_days,'
            'eval_window_target_days,starting_equity_gross_paise,exit_haircut_paise,starting_equity_net_haircut_paise,'
            'harness_hash,data_snapshot_hash,rng_seeds_json,decision_inputs_json,status,spawned_at'
            ') VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (
                'test_ns', 'spawn-001', 'corr-001', 3, 'B', 'FAST_SWING', 'v1_hash',
                '{"rsi_entry":35}', 'CANDIDATE', 1, 5, 0.5, 3.0, 2.12, 60, 45,
                50_000_000, 125_000, 49_875_000,
                'harness_sha256', 'snapshot_sha256', '[101,102]', '{"universe":"pit"}',
                'WARM_START', '2026-11-09T09:15:00+05:30',
            ),
        )])
        rows = self.db.query('SELECT * FROM adaptive_spawns WHERE namespace=? AND spawn_id=?', ('test_ns', 'spawn-001'))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertAlmostEqual(row['k_eff'], 3.0)
        self.assertAlmostEqual(row['effective_critical_value'], 2.12)
        self.assertEqual(row['starting_equity_net_haircut_paise'], 49_875_000)
        self.assertEqual(row['harness_hash'], 'harness_sha256')
        self.assertEqual(row['data_snapshot_hash'], 'snapshot_sha256')

    def test_hash_chained_full_lifecycle_query_and_reconstruction(self):
        ns = 'test_ns'
        cid = 'corr-lifecycle-1'
        sid = 'spawn-b-01'
        oid = 'ord-b-01'

        # 1. Spawn
        alog.append_log(
            self.db, ns, correlation_id=cid, spawn_id=sid, track='B', strategy=3,
            category='SPAWN', decision_type='SPAWN', named_cause='challenger_spawned',
            rule_fired='parameter_mutation_only', strategy_version='v1_mut_1',
            conditions={'warm_start_days': 60, 'eval_window_target_days': 45},
            execution_details={'harness_hash': 'h1', 'data_snapshot_hash': 'd1', 'rng_seeds': [1, 2, 3]},
            source_at='2026-11-09T09:15:00+05:30',
        )
        # 2. Signal & Order submission
        alog.append_log(
            self.db, ns, correlation_id=cid, spawn_id=sid, order_id=oid, track='B', strategy=3, symbol='RELIANCE-EQ',
            category='DECISION_CONTEXT', decision_type='ENTRY', named_cause='qualified',
            rule_fired='rsi14_below_38_and_close_above_sma200', strategy_version='v1_mut_1',
            conditions={'rsi14_lt_38': True, 'close_gt_sma200': True},
            filters={'prefilter': 'PASS', 'series': 'EQ', 'adv_floor': 'PASS'},
            indicator_snapshot={'close': 1250.0, 'rsi14': 34.2, 'sma200': 1180.0},
            risk_state={'sleeve_open_positions': 2, 'cash_paise': 40_000_000},
            source_at='2026-11-09T15:30:00+05:30',
        )
        # 3. Fill
        f_log = alog.append_log(
            self.db, ns, correlation_id=cid, spawn_id=sid, order_id=oid, track='B', strategy=3, symbol='RELIANCE-EQ',
            category='ORDER_LIFECYCLE', decision_type='FILL', named_cause='filled',
            rule_fired='feed_official_open', execution_path='FEED_OPEN', strategy_version='v1_mut_1',
            execution_details={'price': 1252.10, 'shares': 39, 'costs_paise': 8450},
            source_at='2026-11-10T09:15:05+05:30',
        )
        # 4. Shadow skip on another symbol
        alog.append_log(
            self.db, ns, correlation_id='corr-skip-1', spawn_id=sid, order_id='ord-b-02', track='B', strategy=3, symbol='TCS-EQ',
            category='ORDER_LIFECYCLE', decision_type='SKIP', named_cause='SLEEVE_SLOT_FULL',
            rule_fired='max_9_open_positions_per_sleeve', execution_path='FEED_OPEN', strategy_version='v1_mut_1',
            filters={'sleeve_slot': 'FAIL'},
            risk_state={'sleeve_open_positions': 9},
            execution_details={'shadow_logged': True},
            source_at='2026-11-10T09:15:06+05:30',
        )
        # 5. Gate evaluation
        alog.append_log(
            self.db, ns, correlation_id=cid, spawn_id=sid, track='B', strategy=3,
            category='GATE_EVALUATION', decision_type='GATE_PASS', named_cause='all_atomic_gates_passed',
            rule_fired='gate_2_hac_and_residualized_check', strategy_version='v1_mut_1',
            conditions={'gates': {'gate_1': True, 'gate_2': True, 'gate_8': True}, 'k_eff': 2.4, 'effective_critical_value': 1.98, 't_hac': 2.35},
            execution_details={'residual_alpha_bps': 1.25},
            source_at='2026-12-24T16:00:00+05:30',
        )
        # 6. Immutable correction referencing f_log
        alog.log_correction(
            self.db, ns, original_log_id=f_log['log_id'], correlation_id=cid, track='B',
            reason='overnight_dp_pro_rata_adjustment',
            corrected_details={'costs_paise': 8100},
            source_at='2026-11-10T16:05:00+05:30',
        )

        # Verify hash chain
        ver = alog.verify_hash_chain(self.db, ns)
        self.assertTrue(ver['ok'])
        self.assertEqual(ver['count'], 6)

        # Query by named_cause, gate, date, track
        skips = alog.query_logs(self.db, ns, track='B', named_cause='SLEEVE_SLOT_FULL')
        self.assertEqual(len(skips), 1)
        self.assertEqual(skips[0]['symbol'], 'TCS-EQ')

        gate2 = alog.query_logs(self.db, ns, spawn_id=sid, gate='gate_2')
        self.assertEqual(len(gate2), 1)
        self.assertEqual(gate2[0]['decision_type'], 'GATE_PASS')

        # Reconstruct full record from logs alone
        rec = alog.export_reconstructed_record(self.db, ns, spawn_id=sid)
        self.assertTrue(rec['reconstructable'])
        self.assertTrue(rec['chain_verified'])
        self.assertIsNotNone(rec['spawn_record'])
        self.assertEqual(len(rec['order_transitions']), 3)
        self.assertEqual(len(rec['gate_evaluations']), 1)
        self.assertEqual(len(rec['corrections']), 1)

        # Tamper detection test
        self.db.batch([("UPDATE adaptive_decision_logs SET named_cause='tampered' WHERE namespace=? AND seq=2", (ns,))])
        tampered = alog.verify_hash_chain(self.db, ns)
        self.assertFalse(tampered['ok'])
        self.assertIn(2, tampered['breaks'])


if __name__ == '__main__':
    unittest.main()
