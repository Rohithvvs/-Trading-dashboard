import json, tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bhavcopy_compare as b

class BhavcopyTests(unittest.TestCase):
    def test_paise_diff_and_hash_chain(self):
        feed = [{'symbol': 'RELIANCE-EQ', 'open': '100'}, {'symbol': 'TCS-EQ', 'open': '100.05'}, {'symbol': 'INFY-EQ', 'open': '20'}]
        classic = [{'SYMBOL': 'RELIANCE', 'SERIES': 'EQ', 'OPEN': '100.00'}, {'SYMBOL': 'TCS', 'SERIES': 'EQ', 'OPEN': '100'}, {'SYMBOL': 'HDFCBANK', 'SERIES': 'EQ', 'OPEN': '1500'}]
        udiff = [{'TckrSymb': 'TCS', 'SctySrs': 'EQ', 'OpnPric': '100'}]
        rows = b.compare_rows(feed, classic, '2026-11-09')
        by = {r['symbol']: r for r in rows}
        self.assertEqual(by['RELIANCE-EQ']['cause'], 'OPEN_MATCH')
        self.assertEqual(by['RELIANCE-EQ']['diff_paise'], 0)
        self.assertEqual(by['TCS-EQ']['cause'], 'OFFICIAL_OPEN_DIFF')
        self.assertEqual(by['TCS-EQ']['diff_paise'], 5)
        self.assertEqual(by['INFY-EQ']['cause'], 'BHAV_OPEN_MISSING')
        self.assertEqual(by['HDFCBANK-EQ']['cause'], 'FEED_OPEN_MISSING')
        self.assertEqual(b.compare_rows([{'symbol': 'TCS-EQ', 'open': '100'}], udiff, '2026-11-09')[0]['cause'], 'OPEN_MATCH')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'opens.jsonl'
            b.append_report(path, rows)
            stored = b.read_jsonl(path)
            self.assertTrue(b.verify(stored))
            self.assertEqual(stored[0]['prev_hash'], b.GENESIS)
            tampered = json.loads(json.dumps(stored))
            tampered[1]['cause'] = 'OPEN_MATCH'
            self.assertFalse(b.verify(tampered))
            b.append_report(path, [{'trade_date': '2026-11-09', 'symbol': 'ADDED-EQ', 'feed_open_paise': 1, 'bhav_open_paise': 1, 'diff_paise': 0, 'cause': 'OPEN_MATCH'}])
            self.assertTrue(b.verify(b.read_jsonl(path)))

if __name__ == '__main__':
    unittest.main()
