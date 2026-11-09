"""Observation-Only Mode and Promotion Gate Lock for the Self-Improvement (Adaptive) System.

Implements Section 5, Section 7 (items 8 & 10), A6, A8.8, A8.10, and B4:
- Enforces observation-only mode by default (`adaptive_observation_only: true` in config.json).
- Blocks automatic promotion of Track B challengers to Track C unless:
  1. Observation-only period is completed AND observation_only is False
  2. Calibration harness passed (`go_no_go == 'GO'`, measured_power >= 30%)
  3. Automated CI look-ahead truncation test (price + corporate actions) passed
  4. Meta-kill switch is not active for the strategy
  5. Candidate passed all 9 Atomic Gates vs Track A and incremental superiority vs Track C
- When promoted, retires any prior Track C champion so Track C holds at most 1 champion per strategy.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import adaptive_engine as ae
import adaptive_logging as alog
import adaptive_policy as apol

CFG_PATH = Path(__file__).resolve().parent / 'config.json'


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def default_observation_only():
    try:
        cfg = json.loads(CFG_PATH.read_text(encoding='utf8'))
        return bool(cfg.get('adaptive_observation_only', True))
    except Exception:
        return True


def record_observation_period_completed(db, namespace, strategy, sessions_observed, min_sessions=apol.POLICY['observation_min_sessions'], recorded_at=None):
    """Record completion of the observation-only period for a strategy once min_sessions have been observed."""
    s = int(strategy)
    n = int(sessions_observed)
    req = int(min_sessions)
    completed = n >= req
    stamp = recorded_at or _utc_now()
    val = '1' if completed else '0'
    db.batch([(
        'INSERT INTO paper_meta(namespace,key,value) VALUES(?,?,?) ON CONFLICT(namespace,key) DO UPDATE SET value=excluded.value',
        (namespace, f'adaptive_observation_completed_s{s}', val),
    )])
    alog.append_log(
        db, namespace, correlation_id=f'obs_period_s{s}', track='SYSTEM', strategy=s,
        category='PROMOTION',
        decision_type='SYSTEM_OP',
        named_cause='observation_period_completed' if completed else 'observation_period_incomplete',
        rule_fired='observation_only_period_requirement',
        conditions={'sessions_observed': n, 'min_sessions': req, 'completed': completed},
        source_at=stamp,
    )
    return {'strategy': s, 'sessions_observed': n, 'min_sessions': req, 'completed': completed}


def record_ci_lookahead_pass(db, namespace, truncation_report, recorded_at=None):
    """Record the result of the automated CI look-ahead truncation test (price + corporate actions)."""
    passed = bool(truncation_report and truncation_report.get('passed') and int(truncation_report.get('checks_run', 0)) > 0)
    stamp = recorded_at or _utc_now()
    db.batch([(
        'INSERT INTO paper_meta(namespace,key,value) VALUES(?,?,?) ON CONFLICT(namespace,key) DO UPDATE SET value=excluded.value',
        (namespace, 'adaptive_ci_lookahead_passed', '1' if passed else '0'),
    )])
    alog.append_log(
        db, namespace, correlation_id='ci_lookahead_truncation', track='SYSTEM',
        category='SYSTEM',
        decision_type='SYSTEM_OP',
        named_cause='ci_lookahead_truncation_passed' if passed else 'ci_lookahead_truncation_failed',
        rule_fired='ci_price_and_corporate_action_truncation_lock',
        conditions={
            'passed': passed,
            'checks_run': truncation_report.get('checks_run', 0) if truncation_report else 0,
            'mismatches_count': len(truncation_report.get('mismatches', [])) if truncation_report else None,
        },
        execution_details=truncation_report or {},
        source_at=stamp,
    )
    return {'passed': passed, 'checks_run': truncation_report.get('checks_run', 0) if truncation_report else 0}


def check_promotion_prerequisites(db, namespace, strategy, spawn_id, observation_only=None):
    """Verify all mandatory prerequisites before allowing a Track B challenger to promote to Track C."""
    s = int(strategy)
    obs_flag = default_observation_only() if observation_only is None else bool(observation_only)

    obs_rows = db.query('SELECT value FROM paper_meta WHERE namespace=? AND key=?', (namespace, f'adaptive_observation_completed_s{s}'))
    obs_completed = bool(obs_rows and obs_rows[0]['value'] == '1')

    ci_rows = db.query('SELECT value FROM paper_meta WHERE namespace=? AND key=?', (namespace, 'adaptive_ci_lookahead_passed'))
    ci_lookahead_passed = bool(ci_rows and ci_rows[0]['value'] == '1')

    mk_rows = db.query('SELECT value FROM paper_meta WHERE namespace=? AND key=?', (namespace, f'adaptive_meta_kill_strategy_{s}'))
    meta_kill_active = bool(mk_rows and mk_rows[0]['value'] == '1')

    cal_rows = db.query(
        'SELECT go_no_go,measured_power,power_floor,vault_spent FROM adaptive_calibration_runs WHERE namespace=? AND strategy=? ORDER BY recorded_at DESC LIMIT 1',
        (namespace, s),
    )
    calibration_passed = bool(
        cal_rows
        and cal_rows[0]['go_no_go'] == 'GO'
        and float(cal_rows[0]['measured_power']) >= float(cal_rows[0]['power_floor']) - 1e-12
    )

    gate_rows = db.query(
        'SELECT overall_passed,gates_json FROM adaptive_gate_evaluations WHERE namespace=? AND spawn_id=? ORDER BY recorded_at DESC LIMIT 1',
        (namespace, str(spawn_id)),
    )
    gates_passed = bool(gate_rows and int(gate_rows[0]['overall_passed']) == 1)

    sp_rows = db.query('SELECT track,candidate_kind,status FROM adaptive_spawns WHERE namespace=? AND spawn_id=?', (namespace, str(spawn_id)))
    is_track_b_candidate = bool(sp_rows and sp_rows[0]['track'] == 'B' and sp_rows[0]['candidate_kind'] == 'CANDIDATE'
                                and sp_rows[0]['status'] in ('OBSERVATION_ONLY', 'PASSED'))

    # Incremental superiority must have been tested against the champion that is live NOW (a champion promoted
    # after this challenger's gate run was never compared against it).
    live_champion = db.query(
        "SELECT spawn_id FROM adaptive_tracks WHERE namespace=? AND track='C' AND strategy=? AND status IN ('champion','probation') AND spawn_id<>?",
        (namespace, s, str(spawn_id)),
    )
    track_c_superiority_ok = True
    if live_champion:
        details = json.loads(gate_rows[0]['gates_json']) if gate_rows else {}
        cmp_ = details.get('track_c_comparison') or {}
        track_c_superiority_ok = bool(cmp_.get('passed')) and bool(details.get('track_c_champion_present'))

    blockers = []
    if obs_flag:
        blockers.append('observation_only_mode_enabled')
    if not obs_completed:
        blockers.append('observation_only_period_not_completed')
    if not calibration_passed:
        blockers.append('calibration_go_power_floor_not_passed')
    if not ci_lookahead_passed:
        blockers.append('ci_lookahead_truncation_test_not_passed')
    if meta_kill_active:
        blockers.append('meta_kill_switch_active')
    if not gates_passed:
        blockers.append('atomic_gates_not_passed')
    if not is_track_b_candidate:
        blockers.append('not_a_gate_passed_track_b_candidate')
    if not track_c_superiority_ok:
        blockers.append('incremental_superiority_vs_current_track_c_not_tested')

    return {
        'can_promote': len(blockers) == 0,
        'observation_only': obs_flag,
        'observation_period_completed': obs_completed,
        'calibration_passed': calibration_passed,
        'ci_lookahead_passed': ci_lookahead_passed,
        'meta_kill_active': meta_kill_active,
        'gates_passed': gates_passed,
        'track_c_superiority_ok': track_c_superiority_ok,
        'blockers': blockers,
    }


def attempt_promotion(db, namespace, spawn_id, observation_only=None, promoted_at=None):
    """Attempt to promote a Track B challenger (`spawn_id`) to Track C champion."""
    sp_rows = db.query('SELECT * FROM adaptive_spawns WHERE namespace=? AND spawn_id=?', (namespace, str(spawn_id)))
    if not sp_rows:
        raise KeyError(f'spawn_not_found:{spawn_id}')
    sp = sp_rows[0]
    s = int(sp['strategy'])
    prereq = check_promotion_prerequisites(db, namespace, s, spawn_id, observation_only=observation_only)
    stamp = promoted_at or _utc_now()

    if not prereq['can_promote']:
        cause = prereq['blockers'][0]
        dtype = 'PROMOTE_BLOCKED_OBSERVATION' if 'observation_only' in cause else 'HOLD'
        new_status = 'OBSERVATION_ONLY' if prereq['gates_passed'] and ('observation_only' in cause) else sp['status']
        db.batch([(
            'UPDATE adaptive_spawns SET status=? WHERE namespace=? AND spawn_id=?',
            (new_status, namespace, str(spawn_id)),
        )])
        alog.append_log(
            db, namespace, correlation_id=sp['correlation_id'], spawn_id=str(spawn_id),
            track='B', strategy=s,
            category='PROMOTION',
            decision_type=dtype,
            named_cause=cause,
            rule_fired='promotion_lock_requires_calibration_lookahead_and_observation_completion',
            conditions=prereq,
            execution_details={'promoted': False, 'status': new_status},
            source_at=stamp,
        )
        return {
            'promoted': False,
            'spawn_id': str(spawn_id),
            'strategy': s,
            'status': new_status,
            'prerequisites': prereq,
        }

    # Retire any prior Track C champion for this strategy (max 1 champion per strategy)
    db.batch([
        (
            "UPDATE adaptive_tracks SET status='retired',updated_at=? WHERE namespace=? AND track='C' AND strategy=?",
            (stamp, namespace, s),
        ),
        (
            "UPDATE adaptive_tracks SET status='retired',updated_at=? WHERE namespace=? AND track='B' AND spawn_id=?",
            (stamp, namespace, str(spawn_id)),
        ),
        (
            "INSERT OR REPLACE INTO adaptive_tracks("
            "namespace,track,strategy,slot_index,spawn_id,status,params_json,allocated_capital_paise,cash_paise,"
            "starting_equity_net_haircut_paise,created_at,updated_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                namespace, 'C', s, 1, str(spawn_id), 'champion',
                sp['params_json'], ae.SLEEVE_CAPITAL_PAISE,
                ae.SLEEVE_CAPITAL_PAISE, sp['starting_equity_net_haircut_paise'],
                stamp, stamp,
            ),
        ),
        (
            "UPDATE adaptive_spawns SET track='C',status='PROMOTED',decided_at=? WHERE namespace=? AND spawn_id=?",
            (stamp, namespace, str(spawn_id)),
        ),
    ])

    alog.append_log(
        db, namespace, correlation_id=sp['correlation_id'], spawn_id=str(spawn_id),
        track='C', strategy=s,
        category='PROMOTION',
        decision_type='PROMOTE',
        named_cause='challenger_promoted_to_track_c_champion',
        rule_fired='all_gates_calibration_ci_lookahead_and_observation_passed',
        conditions=prereq,
        execution_details={
            'promoted': True,
            'track': 'C',
            'strategy': s,
            'params': json.loads(sp['params_json']),
        },
        source_at=stamp,
    )
    return {
        'promoted': True,
        'spawn_id': str(spawn_id),
        'strategy': s,
        'track': 'C',
        'status': 'PROMOTED',
        'prerequisites': prereq,
    }
