"""Read-only Support Agent for paper trading.

The Support Agent is strictly read-only on trading state (paper_signals, paper_positions,
paper_fills, paper_fill_costs, paper_decisions, etc.) and only writes to support_findings
and support_checkpoints.
Findings are append-only; status transitions (OPEN, ACKNOWLEDGED, RESOLVED, WONT_FIX)
insert new rows with incrementing status_seq and never update or delete prior rows.
"""
import hashlib, json
from datetime import datetime, timezone

VALID_STATUSES = ('OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'WONT_FIX')
VALID_SEVERITIES = ('INFO', 'WARN', 'ERROR', 'CRITICAL')

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

