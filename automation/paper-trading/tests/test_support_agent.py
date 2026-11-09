import sqlite3, unittest, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support_agent as sa


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


class SupportAgentTests(unittest.TestCase):
    def setUp(self):
        self.db = MemDB()
        for sql in (Path(__file__).resolve().parents[1] / 'schema.sql').read_text().split(';'):
            if sql.strip():
                self.db.batch([(sql.strip(), ())])
        sa.init(self.db)

    def test_a1_schema_finding_id_and_append_only_status_transitions(self):
        fid1 = sa.finding_id('unexpected_skip', 'corr-1', '2026-11-09T10:00:00+05:30')
        fid2 = sa.finding_id('unexpected_skip', 'corr-1', '2026-11-09T10:00:00+05:30')
        self.assertEqual(fid1, fid2)
        self.assertEqual(len(fid1), 64)
        first = sa.append_finding(
            self.db, 'test_ns', 'unexpected_skip', 'corr-1',
            '2026-11-09T10:00:00+05:30', '2026-11-09',
            severity='WARN', status='OPEN', details={'cause': 'UNKNOWN'},
        )
        self.assertTrue(first['created'])
        self.assertEqual(first['finding_id'], fid1)
        self.assertEqual(first['status_seq'], 1)
        dup = sa.append_finding(
            self.db, 'test_ns', 'unexpected_skip', 'corr-1',
            '2026-11-09T10:00:00+05:30', '2026-11-09',
        )
        self.assertFalse(dup['created'])
        self.assertEqual(dup['status_seq'], 1)
        ack = sa.transition_finding(self.db, 'test_ns', fid1, 'ACKNOWLEDGED', note='investigating')
        self.assertEqual(ack['status_seq'], 2)
        res = sa.transition_finding(self.db, 'test_ns', fid1, 'RESOLVED', note='fixed')
        self.assertEqual(res['status_seq'], 3)
        wont = sa.transition_finding(self.db, 'test_ns', fid1, 'WONT_FIX', note='expected in test')
        self.assertEqual(wont['status_seq'], 4)
        all_rows = self.db.query('SELECT * FROM support_findings WHERE namespace=? ORDER BY status_seq', ('test_ns',))
        self.assertEqual(len(all_rows), 4)
        self.assertEqual([r['status'] for r in all_rows], ['OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'WONT_FIX'])
        cur = sa.current_findings(self.db, 'test_ns', '2026-11-09')
        self.assertEqual(len(cur), 1)
        self.assertEqual(cur[0]['status'], 'WONT_FIX')
        self.assertEqual(cur[0]['history_count'], 4)
        with self.assertRaises(ValueError):
            sa.transition_finding(self.db, 'test_ns', fid1, 'DELETED')

    def test_a2_checkpoint_consumer_resumes_without_reprocessing(self):
        self.db.batch([
            ('INSERT INTO paper_events(namespace,event_id,run_id,session_day,source_at,recorded_at,event_type,severity,outcome,signal_id,data_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
             ('test_ns', 'e1', 'r1', '2026-11-09', '2026-11-09T09:16:00+00:00', '2026-11-09T09:16:01+00:00', 'paper_order_attempt', 'INFO', 'ok', 'sig-1', '{"correlation_id":"sig-1"}')),
            ('INSERT INTO paper_events(namespace,event_id,run_id,session_day,source_at,recorded_at,event_type,severity,outcome,signal_id,data_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
             ('test_ns', 'e2', 'r1', '2026-11-09', '2026-11-09T09:16:02+00:00', '2026-11-09T09:16:03+00:00', 'paper_order_result', 'INFO', 'filled', 'sig-1', '{"correlation_id":"sig-1"}')),
            ('INSERT INTO paper_decisions(namespace,seq,correlation_id,decision_type,strategy,symbol,signal_id,cause,rule,execution_path,source_at,recorded_at,prev_hash,entry_hash,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
             ('test_ns', 1, 'sig-1', 'ENTRY', 1, 'RELIANCE-EQ', 'sig-1', 'filled', 'feed_official_open', 'FEED_OPEN', '2026-11-09T09:16:02+00:00', '2026-11-09T09:16:02+00:00', '0'*64, 'a'*64, '{"price":100}')),
        ])
        first = sa.consume_checkpoint(self.db, 'test_ns', batch_limit=1)
        self.assertEqual(first['events_consumed'], 1)
        self.assertEqual(first['decisions_consumed'], 1)
        self.assertIn('sig-1', first['by_correlation'])
        second = sa.consume_checkpoint(self.db, 'test_ns', batch_limit=10)
        self.assertEqual(second['events_consumed'], 1)
        self.assertEqual(second['decisions_consumed'], 0)
        third = sa.consume_checkpoint(self.db, 'test_ns', batch_limit=10)
        self.assertEqual(third['events_consumed'], 0)
        self.assertEqual(third['decisions_consumed'], 0)
        self.assertEqual(third['checkpoint']['last_event_id'], 'e2')
        self.assertEqual(third['checkpoint']['last_decision_seq'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
