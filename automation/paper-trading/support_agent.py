"""Read-only Support Agent for paper trading.

The Support Agent is strictly read-only on trading state (paper_signals, paper_positions,
paper_fills, paper_fill_costs, paper_decisions, etc.) and only writes to support_findings
and support_checkpoints.
Findings are append-only; status transitions (OPEN, ACKNOWLEDGED, RESOLVED, WONT_FIX)
insert new rows with incrementing status_seq and never update or delete prior rows.
"""
import hashlib, json, re
from datetime import datetime, timezone
import reconciliation as rec

VALID_STATUSES = ('OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'WONT_FIX')
VALID_SEVERITIES = ('INFO', 'WARN', 'ERROR', 'CRITICAL')
INCOMPLETE_LIFECYCLE_MINUTES = None

EXPECTED_SKIP_CAUSES = rec.NAMED_CAUSES | frozenset({
    'not_pending',
    'position_guard',
    'missing_or_failed_current_prefilter_proof',
    'position_identity_guard',
    'same_bar_reentry_guard',
    'not_yet_eligible',
    'expired_entry_signal',
    'nonpositive_price',
    'stale_or_future_quote',
    'market_closed_or_unverified',
    'provider_quote_error',
    'nonpositive_or_missing_price',
    'missing_exchange_timestamp',
    'quote_outside_verified_session',
})

PLACEHOLDER_PATTERN = re.compile(r'(\bTODO\b|\bFIXME\b|\bTBD\b|\bPLACEHOLDER_TEXT\b|\[redacted\]|\bunclassified_condition\b)', re.IGNORECASE)
GENESIS = '0' * 64


def _stable_json(v):
    if isinstance(v, list):
        return '[' + ','.join(_stable_json(x) for x in v) + ']'
    if isinstance(v, dict):
        return '{' + ','.join(json.dumps(k) + ':' + _stable_json(v[k]) for k in sorted(v.keys())) + '}'
    return json.dumps(None if v is None else v)

SCHEMA = """CREATE TABLE IF NOT EXISTS support_findings(namespace TEXT NOT NULL,finding_id TEXT NOT NULL,status_seq INTEGER NOT NULL,detector TEXT NOT NULL,correlation_id TEXT NOT NULL,first_event_at TEXT NOT NULL,session_day TEXT NOT NULL,severity TEXT NOT NULL CHECK(severity IN('INFO','WARN','ERROR','CRITICAL')),status TEXT NOT NULL CHECK(status IN('OPEN','ACKNOWLEDGED','RESOLVED','WONT_FIX')),observation_only INTEGER NOT NULL DEFAULT 1,notified INTEGER NOT NULL DEFAULT 0,details_json TEXT NOT NULL,recorded_at TEXT NOT NULL,PRIMARY KEY(namespace,finding_id,status_seq));
CREATE INDEX IF NOT EXISTS support_findings_session_idx ON support_findings(namespace,session_day,finding_id,status_seq);
CREATE TABLE IF NOT EXISTS support_checkpoints(namespace TEXT PRIMARY KEY,last_recorded_at TEXT NOT NULL,last_event_id TEXT NOT NULL,last_decision_seq INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL);"""


def init(db):
    db.batch([(s.strip(), ()) for s in SCHEMA.split(';') if s.strip()])


def finding_id(detector, correlation_id, first_event_at):
    """Stable SHA-256 hash of detector + correlation_id + first_event_at."""
    if not detector or not correlation_id or not first_event_at:
        raise ValueError('finding_identity_required')
    raw = f'{detector}|{correlation_id}|{first_event_at}'
    return hashlib.sha256(raw.encode('utf8')).hexdigest()


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def append_finding(db, namespace, detector, correlation_id, first_event_at, session_day, severity='WARN', status='OPEN', details=None, observation_only=True, notified=False, recorded_at=None):
    """Append an initial OPEN finding idempotently without mutating existing rows."""
    if status not in VALID_STATUSES:
        raise ValueError('invalid_finding_status')
    if severity not in VALID_SEVERITIES:
        raise ValueError('invalid_finding_severity')
    fid = finding_id(detector, correlation_id, first_event_at)
    existing = db.query(
        'SELECT status_seq,status FROM support_findings WHERE namespace=? AND finding_id=? ORDER BY status_seq DESC LIMIT 1',
        (namespace, fid),
    )
    if existing and status == 'OPEN':
        return {'created': False, 'finding_id': fid, 'status_seq': int(existing[0]['status_seq']), 'status': existing[0]['status']}
    seq = (int(existing[0]['status_seq']) + 1) if existing else 1
    stamp = recorded_at or _utc_now()
    obs_flag = 1 if observation_only else 0
    notif_flag = 0 if observation_only else (1 if notified else 0)
    payload = json.dumps(details or {}, sort_keys=True, separators=(',', ':'), default=str)
    db.batch([(
        'INSERT INTO support_findings(namespace,finding_id,status_seq,detector,correlation_id,first_event_at,session_day,severity,status,observation_only,notified,details_json,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (namespace, fid, seq, str(detector), str(correlation_id), str(first_event_at), str(session_day), severity, status, obs_flag, notif_flag, payload, stamp),
    )])
    return {'created': True, 'finding_id': fid, 'status_seq': seq, 'status': status}


def transition_finding(db, namespace, fid, new_status, note=None, recorded_at=None):
    """Record an immutable status transition as a new append-only row."""
    if new_status not in VALID_STATUSES:
        raise ValueError('invalid_finding_status')
    rows = db.query(
        'SELECT * FROM support_findings WHERE namespace=? AND finding_id=? ORDER BY status_seq DESC LIMIT 1',
        (namespace, fid),
    )
    if not rows:
        raise KeyError('finding_not_found')
    latest = rows[0]
    seq = int(latest['status_seq']) + 1
    details = json.loads(latest['details_json'])
    if note is not None:
        details = {**details, 'status_note': str(note), 'previous_status': latest['status']}
    else:
        details = {**details, 'previous_status': latest['status']}
    stamp = recorded_at or _utc_now()
    db.batch([(
        'INSERT INTO support_findings(namespace,finding_id,status_seq,detector,correlation_id,first_event_at,session_day,severity,status,observation_only,notified,details_json,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (
            namespace,
            fid,
            seq,
            latest['detector'],
            latest['correlation_id'],
            latest['first_event_at'],
            latest['session_day'],
            latest['severity'],
            new_status,
            int(latest['observation_only']),
            0,
            json.dumps(details, sort_keys=True, separators=(',', ':'), default=str),
            stamp,
        ),
    )])
    return {'finding_id': fid, 'status_seq': seq, 'status': new_status}


def current_findings(db, namespace, session_day=None):
    """Return latest status per finding_id and full append-only history count."""
    if session_day:
        rows = db.query(
            'SELECT * FROM support_findings WHERE namespace=? AND session_day=? ORDER BY finding_id,status_seq',
            (namespace, str(session_day)),
        )
    else:
        rows = db.query(
            'SELECT * FROM support_findings WHERE namespace=? ORDER BY finding_id,status_seq',
            (namespace,),
        )
    grouped = {}
    for r in rows:
        grouped.setdefault(r['finding_id'], []).append(r)
    out = []
    for fid, hist in grouped.items():
        latest = dict(hist[-1])
        latest['history_count'] = len(hist)
        latest['statuses'] = [h['status'] for h in hist]
        latest['details'] = json.loads(latest['details_json'])
        out.append(latest)
    return out


def get_checkpoint(db, namespace):
    rows = db.query('SELECT * FROM support_checkpoints WHERE namespace=?', (namespace,))
    if not rows:
        return {'namespace': namespace, 'last_recorded_at': '', 'last_event_id': '', 'last_decision_seq': 0}
    r = rows[0]
    return {
        'namespace': namespace,
        'last_recorded_at': str(r['last_recorded_at']),
        'last_event_id': str(r['last_event_id']),
        'last_decision_seq': int(r['last_decision_seq']),
    }


def event_correlation_id(event_row):
    try:
        payload = json.loads(event_row.get('data_json') or '{}')
    except Exception:
        payload = {}
    return str(payload.get('correlation_id') or event_row.get('signal_id') or event_row.get('run_id') or event_row.get('event_id'))


def consume_checkpoint(db, namespace, batch_limit=500, recorded_at=None):
    """Consume new paper_events and paper_decisions after the stored checkpoint (read-only on trading tables)."""
    cp = get_checkpoint(db, namespace)
    events = db.query(
        'SELECT * FROM paper_events WHERE namespace=? AND (recorded_at>? OR (recorded_at=? AND event_id>?)) ORDER BY recorded_at,event_id LIMIT ?',
        (namespace, cp['last_recorded_at'], cp['last_recorded_at'], cp['last_event_id'], int(batch_limit)),
    )
    try:
        decisions = db.query(
            'SELECT * FROM paper_decisions WHERE namespace=? AND seq>? ORDER BY seq LIMIT ?',
            (namespace, cp['last_decision_seq'], int(batch_limit)),
        )
    except Exception:
        decisions = []
    next_rec = cp['last_recorded_at']
    next_eid = cp['last_event_id']
    if events:
        next_rec = str(events[-1]['recorded_at'])
        next_eid = str(events[-1]['event_id'])
    next_seq = int(decisions[-1]['seq']) if decisions else cp['last_decision_seq']
    stamp = recorded_at or _utc_now()
    if events or decisions:
        db.batch([(
            'INSERT INTO support_checkpoints(namespace,last_recorded_at,last_event_id,last_decision_seq,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(namespace) DO UPDATE SET last_recorded_at=excluded.last_recorded_at,last_event_id=excluded.last_event_id,last_decision_seq=excluded.last_decision_seq,updated_at=excluded.updated_at',
            (namespace, next_rec, next_eid, next_seq, stamp),
        )])
    by_correlation = {}
    for ev in events:
        cid = event_correlation_id(ev)
        slot = by_correlation.setdefault(cid, {'events': [], 'decisions': []})
        slot['events'].append(ev)
    for dec in decisions:
        cid = str(dec['correlation_id'])
        slot = by_correlation.setdefault(cid, {'events': [], 'decisions': []})
        slot['decisions'].append(dec)
    return {
        'namespace': namespace,
        'events_consumed': len(events),
        'decisions_consumed': len(decisions),
        'events': events,
        'decisions': decisions,
        'by_correlation': by_correlation,
        'checkpoint': {
            'last_recorded_at': next_rec,
            'last_event_id': next_eid,
            'last_decision_seq': next_seq,
        },
    }


def verify_decision_reconstruction(decisions):
    """Verify hash-chain integrity and reconstructability of paper_decisions rows."""
    prev = GENESIS
    failures = []
    for row in sorted(decisions, key=lambda r: int(r['seq'])):
        seq = int(row['seq'])
        try:
            payload = json.loads(row['payload_json'])
        except Exception:
            failures.append({'seq': seq, 'correlation_id': row.get('correlation_id'), 'source_at': row.get('source_at'), 'reason': 'invalid_payload_json'})
            prev = str(row.get('entry_hash') or '')
            continue
        body = {
            'namespace': row['namespace'],
            'seq': seq,
            'correlation_id': row['correlation_id'],
            'decision_type': row['decision_type'],
            'strategy': row.get('strategy'),
            'symbol': row.get('symbol'),
            'signal_id': row.get('signal_id'),
            'cause': row.get('cause'),
            'rule': row.get('rule'),
            'execution_path': row.get('execution_path'),
            'source_at': row['source_at'],
            'recorded_at': row['recorded_at'],
            'payload': payload,
        }
        expected = hashlib.sha256((prev + '\n' + _stable_json(body)).encode('utf8')).hexdigest()
        if row.get('prev_hash') != prev or row.get('entry_hash') != expected:
            failures.append({'seq': seq, 'correlation_id': row.get('correlation_id'), 'source_at': row.get('source_at'), 'reason': 'hash_chain_mismatch'})
        missing = [k for k in ('correlation_id', 'decision_type', 'cause', 'rule', 'execution_path', 'source_at') if not row.get(k)]
        if row.get('decision_type') in ('ENTRY', 'EXIT') and ('price' not in payload or 'quantity' not in payload):
            missing.append('entry_exit_price_or_quantity')
        if missing:
            failures.append({'seq': seq, 'correlation_id': row.get('correlation_id'), 'source_at': row.get('source_at'), 'reason': 'missing_reconstruction_fields', 'fields': missing})
        prev = str(row.get('entry_hash') or '')
    return failures


def run_detectors(db, namespace, session_day, observation_only=True, stale_threshold_seconds=120, recorded_at=None):
    """Run the 7 deterministic support detectors (read-only on trading tables)."""
    if INCOMPLETE_LIFECYCLE_MINUTES is not None:
        raise RuntimeError('incomplete_lifecycle_minutes_must_not_be_invented')
    session_day = str(session_day)
    events = db.query('SELECT * FROM paper_events WHERE namespace=? AND session_day=? ORDER BY recorded_at,event_id', (namespace, session_day))
    all_decisions = db.query('SELECT * FROM paper_decisions WHERE namespace=? ORDER BY seq', (namespace,))
    day_decisions = [d for d in all_decisions if str(d.get('source_at') or '')[:10] == session_day or str(d.get('recorded_at') or '')[:10] == session_day]
    if not day_decisions and all_decisions:
        day_decisions = all_decisions
    created = []

    def record(detector, cid, first_at, severity, details):
        res = append_finding(
            db, namespace, detector, cid, first_at, session_day,
            severity=severity, status='OPEN', details=details,
            observation_only=observation_only, notified=False, recorded_at=recorded_at,
        )
        created.append({**res, 'detector': detector, 'correlation_id': cid})

    # 1. coverage_gap
    scan_runs = {}
    for ev in events:
        rid = ev['run_id']
        sr = scan_runs.setdefault(rid, {'first_at': ev['source_at'], 'prefilter': set(), 'strategy_cells': 0, 'completed': False})
        if ev['event_type'] == 'prefilter_decision' and ev.get('symbol'):
            sr['prefilter'].add(ev['symbol'])
        elif ev['event_type'] == 'strategy_decisions':
            try:
                sr['strategy_cells'] += len(json.loads(ev.get('data_json') or '{}').get('decisions', []))
            except Exception:
                pass
        elif ev['event_type'] == 'scan_completed':
            sr['completed'] = True
    for rid, sr in scan_runs.items():
        if sr['completed'] and (len(sr['prefilter']) < 751 or sr['strategy_cells'] < 5257):
            record('coverage_gap', rid, sr['first_at'], 'WARN', {
                'run_id': rid,
                'prefilter_symbols': len(sr['prefilter']),
                'expected_symbols': 751,
                'strategy_cells': sr['strategy_cells'],
                'expected_strategy_cells': 5257,
            })

    # 2. incomplete_lifecycle (no numeric minute timeout invented)
    attempts = {}
    resolved_orders = set()
    runs_started = {}
    runs_finished = set()
    for ev in events:
        cid = event_correlation_id(ev)
        et = ev['event_type']
        if et == 'paper_order_attempt':
            attempts.setdefault(cid, ev['source_at'])
        elif et in ('paper_order_result', 'paper_order_executed', 'paper_order_blocked'):
            resolved_orders.add(cid)
        elif et == 'run_started':
            runs_started.setdefault(ev['run_id'], ev['source_at'])
        elif et in ('run_completed', 'run_failed'):
            runs_finished.add(ev['run_id'])
    for dec in day_decisions:
        resolved_orders.add(str(dec['correlation_id']))
    for cid, first_at in attempts.items():
        if cid not in resolved_orders:
            record('incomplete_lifecycle', cid, first_at, 'ERROR', {
                'kind': 'order_attempt_without_decision_or_result',
                'incomplete_lifecycle_timeout_minutes': INCOMPLETE_LIFECYCLE_MINUTES,
                'timeout_source': 'not_numeric_in_plan_not_invented',
            })
    for rid, first_at in runs_started.items():
        if rid not in runs_finished:
            record('incomplete_lifecycle', rid, first_at, 'WARN', {
                'kind': 'run_started_without_completion',
                'incomplete_lifecycle_timeout_minutes': INCOMPLETE_LIFECYCLE_MINUTES,
                'timeout_source': 'not_numeric_in_plan_not_invented',
            })

    # 3. unexpected_skip
    for dec in day_decisions:
        if dec.get('decision_type') == 'SKIP' and dec.get('cause') not in EXPECTED_SKIP_CAUSES:
            record('unexpected_skip', str(dec['correlation_id']), str(dec['source_at']), 'WARN', {
                'cause': dec.get('cause'),
                'rule': dec.get('rule'),
                'symbol': dec.get('symbol'),
                'strategy': dec.get('strategy'),
            })
    for ev in events:
        if ev['event_type'] == 'paper_order_blocked' and ev.get('outcome') not in EXPECTED_SKIP_CAUSES:
            record('unexpected_skip', event_correlation_id(ev), str(ev['source_at']), 'WARN', {
                'outcome': ev.get('outcome'),
                'event_id': ev['event_id'],
            })

    # 4. placeholder_text
    for dec in day_decisions:
        raw = str(dec.get('payload_json') or '')
        m = PLACEHOLDER_PATTERN.search(raw)
        if m:
            record('placeholder_text', str(dec['correlation_id']), str(dec['source_at']), 'WARN', {
                'source': 'paper_decisions',
                'matched': m.group(0),
                'seq': int(dec['seq']),
            })
    for ev in events:
        raw = str(ev.get('data_json') or '')
        m = PLACEHOLDER_PATTERN.search(raw)
        if m:
            record('placeholder_text', event_correlation_id(ev), str(ev['source_at']), 'WARN', {
                'source': 'paper_events',
                'matched': m.group(0),
                'event_id': ev['event_id'],
            })

    # 5. reconstruction_failure
    for fail in verify_decision_reconstruction(all_decisions):
        cid = str(fail.get('correlation_id') or f"seq:{fail['seq']}")
        first_at = str(fail.get('source_at') or f'{session_day}T00:00:00+00:00')
        record('reconstruction_failure', cid, first_at, 'CRITICAL', fail)

    # 6. monitor_staleness
    check_times = []
    for ev in events:
        if ev['event_type'] == 'monitor_completed':
            try:
                check_times.append((datetime.fromisoformat(str(ev['source_at']).replace('Z', '+00:00')), ev))
            except Exception:
                pass
        elif ev['event_type'] == 'guardian_check':
            try:
                lag = json.loads(ev.get('data_json') or '{}').get('heartbeat_lag_seconds')
                if isinstance(lag, (int, float)) and lag > stale_threshold_seconds:
                    record('monitor_staleness', ev['run_id'], str(ev['source_at']), 'WARN', {
                        'heartbeat_lag_seconds': lag,
                        'threshold_seconds': stale_threshold_seconds,
                    })
            except Exception:
                pass
    check_times.sort(key=lambda x: x[0])
    for (t1, _), (t2, ev2) in zip(check_times, check_times[1:]):
        gap = (t2 - t1).total_seconds()
        if gap > stale_threshold_seconds:
            record('monitor_staleness', ev2['run_id'], str(ev2['source_at']), 'WARN', {
                'gap_seconds': gap,
                'threshold_seconds': stale_threshold_seconds,
            })

    # 7. named_cause_dump
    cause_counts = {}
    unmapped_causes = []
    for dec in day_decisions:
        c = str(dec.get('cause') or 'NONE')
        cause_counts[c] = cause_counts.get(c, 0) + 1
        if c != 'filled' and c != 'reinstated' and c not in EXPECTED_SKIP_CAUSES:
            unmapped_causes.append(c)
    if day_decisions or events:
        first_at = (day_decisions[0]['source_at'] if day_decisions else events[0]['source_at'])
        record('named_cause_dump', f'named_cause_dump:{session_day}', str(first_at), 'INFO', {
            'session_day': session_day,
            'cause_counts': cause_counts,
            'unmapped_causes': sorted(set(unmapped_causes)),
            'total_decisions': len(day_decisions),
        })

    return {
        'namespace': namespace,
        'session_day': session_day,
        'findings_evaluated': len(created),
        'findings_created': sum(1 for x in created if x['created']),
        'results': created,
    }


def session_report(db, namespace, session_day, out_dir=None):
    """Build a deterministic support session report from append-only findings."""
    session_day = str(session_day)
    findings = current_findings(db, namespace, session_day)
    by_detector = {}
    by_status = {s: 0 for s in VALID_STATUSES}
    by_severity = {s: 0 for s in VALID_SEVERITIES}
    named_causes = {}
    for f in findings:
        det = f['detector']
        by_detector[det] = by_detector.get(det, 0) + 1
        by_status[f['status']] = by_status.get(f['status'], 0) + 1
        by_severity[f['severity']] = by_severity.get(f['severity'], 0) + 1
        if det == 'named_cause_dump':
            named_causes = f.get('details', {}).get('cause_counts', {})
    report = {
        'namespace': namespace,
        'session_day': session_day,
        'total_findings': len(findings),
        'open_findings': by_status['OPEN'],
        'by_detector': by_detector,
        'by_status': by_status,
        'by_severity': by_severity,
        'named_causes': named_causes,
        'decision_chain_intact': by_detector.get('reconstruction_failure', 0) == 0,
        'incomplete_lifecycle_timeout_minutes': INCOMPLETE_LIFECYCLE_MINUTES,
        'checkpoint': get_checkpoint(db, namespace),
        'findings': findings,
    }
    if out_dir is not None:
        from pathlib import Path
        target = Path(out_dir) / f'support-{session_day}.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding='utf8')
        report['report_path'] = str(target)
    return report



