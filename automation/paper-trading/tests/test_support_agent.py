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

    def test_a3_all_seven_detectors_fire_without_invented_timeout_or_trading_writes(self):
        self.assertIsNone(sa.INCOMPLETE_LIFECYCLE_MINUTES)
        day = '2026-11-09'
        self.db.batch([
            # coverage_gap: completed scan with only 1 prefilter symbol (<751)
            ('INSERT INTO paper_events(namespace,event_id,run_id,session_day,source_at,recorded_at,event_type,severity,outcome,symbol,data_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
             ('test_ns', 'cg1', 'scan-run-1', day, '2026-11-09T09:15:00+00:00', '2026-11-09T09:15:01+00:00', 'prefilter_decision', 'INFO', 'PASS', 'RELIANCE-EQ', '{}')),
            ('INSERT INTO paper_events(namespace,event_id,run_id,session_day,source_at,recorded_at,event_type,severity,outcome,data_json) VALUES(?,?,?,?,?,?,?,?,?,?)',
             ('test_ns', 'cg2', 'scan-run-1', day, '2026-11-09T09:15:02+00:00', '2026-11-09T09:15:03+00:00', 'scan_completed', 'INFO', 'ok', '{}')),
            # incomplete_lifecycle: order attempt with no result or decision
            ('INSERT INTO paper_events(namespace,event_id,run_id,session_day,source_at,recorded_at,event_type,severity,outcome,signal_id,data_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
             ('test_ns', 'il1', 'mon-run-1', day, '2026-11-09T09:20:00+00:00', '2026-11-09T09:20:01+00:00', 'paper_order_attempt', 'INFO', 'ok', 'orphan-sig', '{"correlation_id":"orphan-sig"}')),
            # monitor_staleness: two monitor_completed events 300s apart (>120s)
            ('INSERT INTO paper_events(namespace,event_id,run_id,session_day,source_at,recorded_at,event_type,severity,outcome,data_json) VALUES(?,?,?,?,?,?,?,?,?,?)',
             ('test_ns', 'ms1', 'mon-1', day, '2026-11-09T09:30:00+00:00', '2026-11-09T09:30:01+00:00', 'monitor_completed', 'INFO', 'ok', '{"status":"ok"}')),
            ('INSERT INTO paper_events(namespace,event_id,run_id,session_day,source_at,recorded_at,event_type,severity,outcome,data_json) VALUES(?,?,?,?,?,?,?,?,?,?)',
             ('test_ns', 'ms2', 'mon-2', day, '2026-11-09T09:35:00+00:00', '2026-11-09T09:35:01+00:00', 'monitor_completed', 'INFO', 'ok', '{"status":"ok"}')),
            # unexpected_skip + placeholder_text + reconstruction_failure (broken hash)
            ('INSERT INTO paper_decisions(namespace,seq,correlation_id,decision_type,strategy,symbol,signal_id,cause,rule,execution_path,source_at,recorded_at,prev_hash,entry_hash,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
             ('test_ns', 1, 'bad-skip-1', 'SKIP', 1, 'RELIANCE-EQ', 'bad-skip-1', 'MYSTERY_SKIP_CAUSE', 'todo_rule', 'FEED_OPEN', '2026-11-09T09:40:00+00:00', '2026-11-09T09:40:00+00:00', '0'*64, 'wrong_hash', '{"note":"TODO fix placeholder"}')),
        ])
        res = sa.run_detectors(self.db, 'test_ns', day)
        self.assertGreaterEqual(res['findings_created'], 7)
        findings = sa.current_findings(self.db, 'test_ns', day)
        detectors = {f['detector'] for f in findings}
        self.assertEqual(detectors, {
            'coverage_gap',
            'incomplete_lifecycle',
            'unexpected_skip',
            'placeholder_text',
            'reconstruction_failure',
            'monitor_staleness',
            'named_cause_dump',
        })
        il = next(f for f in findings if f['detector'] == 'incomplete_lifecycle')
        self.assertIsNone(il['details']['incomplete_lifecycle_timeout_minutes'])
        # Idempotent on second run
        again = sa.run_detectors(self.db, 'test_ns', day)
        self.assertEqual(again['findings_created'], 0)

    def test_a4_session_reporter_summarizes_findings_and_writes_json(self):
        import tempfile
        day = '2026-11-09'
        sa.append_finding(self.db, 'test_ns', 'coverage_gap', 'run-1', '2026-11-09T09:15:00+00:00', day, severity='WARN')
        sa.append_finding(self.db, 'test_ns', 'named_cause_dump', f'named_cause_dump:{day}', '2026-11-09T09:15:00+00:00', day, severity='INFO', details={'cause_counts': {'ADV_FILTER_SKIP': 2}})
        with tempfile.TemporaryDirectory() as tmp:
            rep = sa.session_report(self.db, 'test_ns', day, out_dir=tmp)
            self.assertEqual(rep['total_findings'], 2)
            self.assertEqual(rep['open_findings'], 2)
            self.assertEqual(rep['by_detector']['coverage_gap'], 1)
            self.assertEqual(rep['named_causes'], {'ADV_FILTER_SKIP': 2})
            self.assertTrue(rep['decision_chain_intact'])
            self.assertTrue(Path(rep['report_path']).exists())

    def test_a5_schedule_runs_without_engine_lock_or_trading_mutation(self):
        from datetime import datetime, time as dt_time
        import tempfile
        day = '2026-11-09'
        bounds = (dt_time(9, 15), dt_time(15, 30))
        w_intra = sa.schedule_window(datetime(2026, 11, 9, 10, 0), bounds)
        self.assertTrue(w_intra['due'])
        self.assertEqual(w_intra['phase'], 'intraday')
        self.assertFalse(w_intra['schedule']['locks_engine'])
        w_eod = sa.schedule_window(datetime(2026, 11, 9, 15, 35), bounds)
        self.assertTrue(w_eod['due'])
        self.assertEqual(w_eod['phase'], 'post_eod')
        w_closed = sa.schedule_window(datetime(2026, 11, 9, 20, 0), None)
        self.assertFalse(w_closed['due'])
        with tempfile.TemporaryDirectory() as tmp:
            out = sa.run_scheduled_pass(self.db, 'test_ns', day, session_bounds=bounds, now_at=datetime(2026, 11, 9, 15, 35), out_dir=tmp)
            self.assertEqual(out['status'], 'ok')
            self.assertEqual(out['window']['phase'], 'post_eod')
            self.assertTrue(Path(out['report']['report_path']).exists())

    def test_a6_observation_only_writes_findings_and_never_notifies(self):
        day = '2026-11-09'
        self.db.batch([
            ('INSERT INTO paper_events(namespace,event_id,run_id,session_day,source_at,recorded_at,event_type,severity,outcome,data_json) VALUES(?,?,?,?,?,?,?,?,?,?)',
             ('test_ns', 'ev-obs-1', 'run-obs', day, '2026-11-09T09:16:00+00:00', '2026-11-09T09:16:01+00:00', 'scan_completed', 'INFO', 'ok', '{"symbols":1}')),
        ])
        calls = []
        out = sa.run_scheduled_pass(self.db, 'test_ns', day, observation_only=True, notify_fn=lambda r: calls.append(r))
        self.assertTrue(out['observation_only'])
        self.assertEqual(out['notifications_sent'], 0)
        self.assertEqual(calls, [])
        rows = self.db.query('SELECT observation_only,notified FROM support_findings WHERE namespace=?', ('test_ns',))
        self.assertTrue(len(rows) >= 1)
        for r in rows:
            self.assertEqual(r['observation_only'], 1)
            self.assertEqual(r['notified'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
