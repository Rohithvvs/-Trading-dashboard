import sys, unittest
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import residualized_check as rc


class ResidualizedCheckTests(unittest.TestCase):
    def test_genuine_skill_passes_gate2_and_residualized_check(self):
        rng = np.random.default_rng(42)
        n = 75
        r_idx = rng.normal(0.0005, 0.008, size=n)
        r_base = 0.8 * r_idx + rng.normal(0.0, 0.002, size=n)
        # Variant adds genuine positive orthogonal alpha (+12 bps/day) with low tracking noise
        r_var = r_base + 0.0012 + 0.05 * r_idx + rng.normal(0.0, 0.0015, size=n)

        res = rc.evaluate_gate2_and_gate4(
            r_var=r_var,
            r_base=r_base,
            index_returns=r_idx,
            k_cand=3,
            rho_bar=0.5,
            cost_slippage_hurdle=0.0001,
        )
        self.assertTrue(res['clears_cost_slippage_hurdle'])
        self.assertTrue(res['passes_effective_critical_value'])
        self.assertTrue(res['residualized_check']['residual_mean_positive'])
        self.assertTrue(res['gate2_passed'])
        self.assertTrue(res['gate4_passed'])
        self.assertGreater(res['capital_day_expectancy']['ci_lower'], 0.0)

    def test_pure_beta_exposure_rejected_by_residualized_check(self):
        rng = np.random.default_rng(99)
        n = 75
        # Strong bull index period (mean +25 bps/day)
        r_idx = rng.normal(0.0025, 0.006, size=n)
        r_base = 0.5 * r_idx
        # Variant has negative true alpha (-3 bps/day) but higher beta (+0.8 * r_idx -> +20 bps/day raw active return)
        r_var = r_base - 0.0003 + 0.8 * r_idx + rng.normal(0.0, 0.0002, size=n)

        res = rc.evaluate_gate2_and_gate4(
            r_var=r_var,
            r_base=r_base,
            index_returns=r_idx,
            k_cand=1,
            rho_bar=0.0,
        )
        # Raw d_t mean is positive (~ +17 bps/day) and raw t_HAC is high
        self.assertGreater(res['d_t_mean'], 0.0010)
        self.assertTrue(res['passes_effective_critical_value'])
        # But residualized mean (alpha) is negative (~ -3 bps/day), so residualized check and Gate 2 FAIL!
        self.assertLess(res['residualized_check']['residual_mean'], 0.0)
        self.assertFalse(res['residualized_check']['residual_mean_positive'])
        self.assertFalse(res['gate2_passed'])
        self.assertTrue(res['gate4_binding'])
        self.assertFalse(res['gate4_passed'])


if __name__ == '__main__':
    unittest.main()
