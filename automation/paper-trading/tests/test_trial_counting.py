import sqlite3, sys, unittest
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import adaptive_engine as ae
import adaptive_logging as alog
import pit_archive as pit
import trial_counting as tc


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


class TrialCountingTests(unittest.TestCase):
    def setUp(self):
        self.db = MemDB()
        for sql in (Path(__file__).resolve().parents[1] / 'schema.sql').read_text().split(';'):
            if sql.strip():
                self.db.batch([(sql.strip(), ())])
        pit.init(self.db)
        alog.init(self.db)

    def test_k_cand_excludes_placebos_plateau_neighbors_and_shadows(self):
        records = [
            {'spawn_id': 'c1', 'candidate_kind': 'CANDIDATE', 'eligible_for_selection': 1},
            {'spawn_id': 'c2', 'candidate_kind': 'CANDIDATE', 'eligible_for_selection': 1},
            {'spawn_id': 'c3', 'candidate_kind': 'TRACK_C_COMPARISON', 'eligible_for_selection': 1},
            {'spawn_id': 'p1', 'candidate_kind': 'PLACEBO', 'eligible_for_selection': 0},
            {'spawn_id': 'n1', 'candidate_kind': 'PLATEAU_NEIGHBOR', 'eligible_for_selection': 0},
            {'spawn_id': 's1', 'candidate_kind': 'SHADOW', 'eligible_for_selection': 0},
            {'spawn_id': 'b1', 'candidate_kind': 'BASELINE', 'eligible_for_selection': 0},
        ]
        res = tc.count_k_cand(records)
        self.assertEqual(res['k_cand'], 3)
        self.assertEqual(res['excluded_count'], 4)
        self.assertEqual(res['eligible_ids'], ['c1', 'c2', 'c3'])

    def test_linear_k_eff_formula_and_rho_bar_clamped_at_0_90(self):
        # K_eff = 1 + (K_cand - 1) * (1 - rho_bar)
        r1 = tc.compute_k_eff(k_cand=11, rho_bar=0.5)
        self.assertAlmostEqual(r1['k_eff'], 6.0)

        # Clamped at 0.90 when rho_bar = 0.98 -> K_eff = 1 + 10 * 0.10 = 2.0
        r2 = tc.compute_k_eff(k_cand=11, rho_bar=0.98)
        self.assertAlmostEqual(r2['rho_bar_clamped'], 0.90)
        self.assertAlmostEqual(r2['k_eff'], 2.0)

        # Correlation matrix estimation with identical series clamps to 0.90
        base = np.linspace(-0.01, 0.02, 50)
        mat = np.vstack([base, base * 1.0001, base * 0.9999])
        rho_est = tc.estimate_rho_bar(candidate_return_matrix=mat)
        self.assertAlmostEqual(rho_est, 0.90)

    def test_explicit_gate2_effective_critical_value_link(self):
        # When K_eff is large, adjusted threshold exceeds 1.40 and becomes the binding critical value
        link_high = tc.evaluate_gate2_critical_link(t_hac=1.85, k_cand=10, rho_bar=0.2, alpha=0.05)
        self.assertGreater(link_high['effective_critical_value'], 1.40)
        self.assertFalse(link_high['passes_effective_critical_value'])

        link_pass = tc.evaluate_gate2_critical_link(t_hac=2.85, k_cand=10, rho_bar=0.2, alpha=0.05)
        self.assertTrue(link_pass['passes_effective_critical_value'])

        # Even if alpha is relaxed so quantile < 1.40, floor 1.40 still holds
        link_floor = tc.evaluate_gate2_critical_link(t_hac=1.35, k_cand=1, rho_bar=0.0, alpha=0.25)
        self.assertAlmostEqual(link_floor['effective_critical_value'], 1.40)
        self.assertFalse(link_floor['passes_effective_critical_value'])

        # Persist trial count into adaptive_spawns and verify log
        sp = ae.spawn_candidate(self.db, 'test_tc', strategy=3, params={'rsi_entry': 35.0}, track='B')
        ae.spawn_candidate(self.db, 'test_tc', strategy=3, params={'rsi_entry': 36.0}, track='B', candidate_kind='PLACEBO')
        rec = tc.record_trial_count(
            self.db, 'test_tc', strategy=3, explicit_rho_bar=0.4, t_hac=2.20, spawn_id=sp['spawn_id'],
        )
        self.assertEqual(rec['k_cand'], 1)
        self.assertTrue(rec['passes_effective_critical_value'])


if __name__ == '__main__':
    unittest.main()
