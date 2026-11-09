import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import capital as cap

class CapitalTests(unittest.TestCase):
    def test_freeze_identity(self):
        cap.assert_freeze()
        self.assertEqual(cap.POLICY['master_capital_inr'], 7 * cap.POLICY['sleeve_capital_inr'])
        self.assertEqual(cap.POLICY['target_notional_inr'], 50000)
        self.assertIn('sleeve_slot_limit', cap.POLICY['enforced'])
        self.assertIn('isin_cap', cap.POLICY['enforced'])
        self.assertNotIn('isin_cap', cap.POLICY['recorded_not_yet_enforced'])
        self.assertEqual(cap.POLICY['max_positions_per_sleeve'] * cap.POLICY['target_notional_inr'], 450000)
        self.assertLess(450000, cap.POLICY['sleeve_capital_inr'])
        self.assertEqual(cap.slot_rank('2026-11-09', 'ABB-EQ'), cap.slot_rank('2026-11-09', 'ABB-EQ'))
        self.assertNotEqual(cap.slot_rank('2026-11-09', 'ABB-EQ'), cap.slot_rank('2026-11-10', 'ABB-EQ'))

    def test_floor_share_counts(self):
        self.assertEqual(cap.integer_shares(2500), 20)
        self.assertEqual(cap.integer_shares(100), 500)
        self.assertEqual(cap.integer_shares(90), 555)
        self.assertEqual(cap.integer_shares('100.50'), 497)
        self.assertEqual(cap.integer_shares(50000), 1)
        self.assertEqual(cap.integer_shares(50000.01), 0)
        self.assertEqual(cap.integer_shares(60000), 0)
        self.assertEqual(cap.price_paise(100.0), 10000)
        self.assertEqual(cap.price_paise(2500.10), 250010)

    def test_rejects_unpriced_or_sub_paise(self):
        for price in (0, -1, 0.001, '100.123', float('nan'), True):
            with self.assertRaises(ValueError):
                cap.integer_shares(price)
        with self.assertRaises(ValueError):
            cap.integer_shares(100, target_notional_inr=0)
