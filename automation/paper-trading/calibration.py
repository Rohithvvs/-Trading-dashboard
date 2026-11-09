"""Calibration Harness (MDE, Injected Edge, ~30% Go/No-Go Power Floor, Oldest-Partition Tuning,
One-Touch Holdout Vault, Meta-Kill Switch) and Automated Look-Ahead Truncation Test (Price + Corporate Actions).

Implements Section 5, Section 6, A6, A7, A8.7, B1, and B4 of the Definitive Coding-Ready Plan.
"""
import math, uuid
from datetime import datetime, timezone
from statistics import NormalDist
import numpy as np
import pandas as pd

import adaptive_engine as ae
import adaptive_logging as alog
import adaptive_policy as apol
import pit_archive as pit
import prefilter as pf
import residualized_check as rc
import trial_counting as tc

AP = apol.POLICY
POWER_FLOOR = AP['power_floor']
OLDEST_PARTITION_NAME = 'OLDEST_CALIBRATION_PARTITION'


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def compute_mde_from_real_d_t(real_d_t, window_days, k_eff=1.0, alpha=tc.DEFAULT_ALPHA, target_power=POWER_FLOOR):
    """Compute Minimum Detectable Effect (MDE) from measured sigma of real d_t."""
    d = np.asarray(real_d_t, dtype=float)
    if len(d) < 2:
        raise ValueError('real_d_t_requires_at_least_2_observations')
    sigma_d_t = float(np.std(d, ddof=1))
    n = max(1, int(window_days))
    crit = tc.compute_effective_critical_value(k_eff=k_eff, alpha=alpha)['effective_critical_value']
    nd = NormalDist(0.0, 1.0)
    z_power = float(nd.inv_cdf(float(target_power)))
    se_window = sigma_d_t / math.sqrt(n)
    mde = max(0.0, (crit + z_power) * se_window)
    return {
        'sigma_d_t': sigma_d_t,
        'sigma_d_t_bps': sigma_d_t * 10_000.0,
        'window_days': n,
        'k_eff': float(k_eff),
        'effective_critical_value': crit,
        'target_power': float(target_power),
        'mde_daily': mde,
        'mde_bps': mde * 10_000.0,
    }


def estimate_power_at_injected_edge(
    real_d_t,
    smallest_actionable_edge,
    window_days,
    k_eff=1.0,
    alpha=tc.DEFAULT_ALPHA,
    n_sims=AP['calibration_n_sims'],
    seed=AP['base_seed'],
):
    """Estimate statistical power when injecting smallest_actionable_edge into centered real d_t."""
    edge = float(smallest_actionable_edge)
    if edge <= 0.0:
        raise ValueError('smallest_actionable_edge_must_be_positive')
    mde_info = compute_mde_from_real_d_t(real_d_t, window_days=window_days, k_eff=k_eff, alpha=alpha)
    sigma = mde_info['sigma_d_t']
    crit = mde_info['effective_critical_value']
    n = mde_info['window_days']

    nd = NormalDist(0.0, 1.0)
    if sigma <= 1e-15:
        analytical_power = 1.0
    else:
        non_centrality = (edge * math.sqrt(n)) / sigma
        analytical_power = float(1.0 - nd.cdf(crit - non_centrality))

    d = np.asarray(real_d_t, dtype=float)
    centered = d - np.mean(d)
    rng = np.random.default_rng(int(seed))
    detections = 0
    sims = max(AP['calibration_min_sims'], int(n_sims))
    for _ in range(sims):
        idx = rng.integers(0, len(centered), size=n)
        synth_d = centered[idx] + edge
        se = float(np.std(synth_d, ddof=1)) / math.sqrt(n)
        t_stat = (float(np.mean(synth_d)) / se) if se > 1e-15 else 0.0
        if t_stat >= crit:
            detections += 1
    empirical_power = detections / float(sims)
    # Conservative measured power is the minimum of analytical and empirical power
    measured_power = min(analytical_power, empirical_power)
    return {
        **mde_info,
        'injected_edge': edge,
        'injected_edge_bps': edge * 10_000.0,
        'analytical_power': analytical_power,
        'empirical_power': empirical_power,
        'measured_power': measured_power,
    }


def tune_thresholds_on_partition(partition_name, ordered_partitions, candidate_thresholds, real_d_t):
    """Enforce that calibration threshold tuning occurs ONLY on the oldest calibration partition."""
    if not ordered_partitions:
        raise ValueError('ordered_partitions_required')
    oldest = str(ordered_partitions[0])
    if str(partition_name) != oldest:
        raise PermissionError(f'threshold_tuning_restricted_to_oldest_partition:got_{partition_name}_expected_{oldest}')

    d = np.asarray(real_d_t, dtype=float)
    if len(d) < 2:
        raise ValueError('threshold_tuning_requires_at_least_2_d_t_observations')
    sigma = float(np.std(d, ddof=1))
    best = None
    for thresh in candidate_thresholds:
        val = float(thresh)
        if best is None or abs(val - 0.5 * sigma) < abs(best - 0.5 * sigma):
            best = val
    return {
        'partition_used': str(partition_name),
        'oldest_partition_verified': True,
        'tuned_threshold': best,
        'sigma_d_t': sigma,
    }


def run_calibration_go_no_go(
    db,
    namespace,
    strategy,
    real_d_t,
    smallest_actionable_edge,
    window_days=None,
    k_eff=1.0,
    partition_name=OLDEST_PARTITION_NAME,
    ordered_partitions=(OLDEST_PARTITION_NAME, 'VALIDATION_PARTITION', 'HOLDOUT_VAULT'),
    power_floor=POWER_FLOOR,
    lengthen_on_low_power=False,
    calibration_id=None,
    correlation_id=None,
    seed=AP['base_seed'],
):
    """Run the calibration protocol and enforce the ~30% power floor go/no-go rule."""
    s = int(strategy)
    if not ordered_partitions or str(partition_name) != str(ordered_partitions[0]):
        raise PermissionError(f'calibration_must_tune_on_oldest_partition:{partition_name}')

    w_days = int(window_days or ae.default_target_window_days(s))
    pwr = estimate_power_at_injected_edge(
        real_d_t=real_d_t,
        smallest_actionable_edge=smallest_actionable_edge,
        window_days=w_days,
        k_eff=k_eff,
        seed=seed,
    )
    floor = float(power_floor)
    passes_floor = pwr['measured_power'] >= floor - 1e-12

    if passes_floor:
        go_no_go = 'GO'
        pipeline_mode = 'OBSERVATION_ONLY_PENDING_COMPLETION'
        recommended_window_days = w_days
    elif lengthen_on_low_power:
        go_no_go = 'NO_GO_LENGTHEN_WINDOW'
        pipeline_mode = 'MONITOR_ONLY'
        # Compute window length required to reach power_floor
        nd = NormalDist(0.0, 1.0)
        z_req = pwr['effective_critical_value'] + float(nd.inv_cdf(floor))
        req_n = int(math.ceil(((z_req * pwr['sigma_d_t']) / float(smallest_actionable_edge)) ** 2))
        recommended_window_days = max(w_days + ae.EXTENSION_DAYS, req_n)
    else:
        go_no_go = 'NO_GO_MONITOR_ONLY'
        pipeline_mode = 'MONITOR_ONLY'
        recommended_window_days = w_days

    cid = str(calibration_id or f'cal_{s}_{uuid.uuid4().hex[:12]}')
    prior = db.query('SELECT holdout_touched,vault_spent FROM adaptive_calibration_runs WHERE namespace=? AND calibration_id=?', (namespace, cid))
    if prior and (int(prior[0]['holdout_touched']) or int(prior[0]['vault_spent'])):
        # Re-running a calibration id must never reset its holdout-vault flags.
        raise PermissionError(f'calibration_already_touched_holdout:{cid}')
    corr = str(correlation_id or cid)
    stamp = _utc_now()
    details = {
        **pwr,
        'power_floor': floor,
        'passes_power_floor': passes_floor,
        'go_no_go': go_no_go,
        'pipeline_mode': pipeline_mode,
        'automatic_promotion_enabled': False,
        'recommended_window_days': recommended_window_days,
        'partition_name': str(partition_name),
    }
    dhash = alog.compute_hash(details)

    db.batch([(
        'INSERT OR REPLACE INTO adaptive_calibration_runs('
        'namespace,calibration_id,correlation_id,strategy,partition_name,sigma_d_t,mde,injected_edge,'
        'measured_power,power_floor,go_no_go,pipeline_mode,holdout_touched,vault_spent,details_json,data_hash,recorded_at'
        ') VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (
            namespace, cid, corr, s, str(partition_name),
            pwr['sigma_d_t'], pwr['mde_daily'], pwr['injected_edge'],
            pwr['measured_power'], floor, go_no_go, pipeline_mode,
            0, 0, alog.stable_json(details), dhash, stamp,
        ),
    )])

    alog.append_log(
        db, namespace, correlation_id=corr, track='SYSTEM', strategy=s,
        category='CALIBRATION',
        decision_type='CALIBRATION_GO' if passes_floor else 'CALIBRATION_NO_GO',
        named_cause=go_no_go.lower(),
        rule_fired='calibration_power_floor_30pct_go_no_go',
        conditions={
            'sigma_d_t': pwr['sigma_d_t'],
            'mde_daily': pwr['mde_daily'],
            'injected_edge': pwr['injected_edge'],
            'measured_power': pwr['measured_power'],
            'power_floor': floor,
            'partition_name': str(partition_name),
        },
        execution_details=details,
        input_data=details,
        source_at=stamp,
    )
    return {
        'calibration_id': cid,
        'correlation_id': corr,
        'strategy': s,
        **details,
    }


def touch_holdout_vault_once(db, namespace, vault_id, calibration_id, holdout_passed):
    """Enforce single-touch holdout vault: if touched before or spent, reject; if calibration fails, vault is spent."""
    vid = str(vault_id)
    existing = db.query('SELECT * FROM adaptive_holdout_vault WHERE namespace=? AND vault_id=?', (namespace, vid))
    if existing and (int(existing[0]['touched_count']) >= 1 or int(existing[0]['vault_spent']) == 1):
        raise PermissionError(f'holdout_vault_already_touched_or_spent:{vid}')

    passed = bool(holdout_passed)
    vault_spent = 0 if passed else 1
    status = 'PASSED_SINGLE_TOUCH' if passed else 'SPENT_USE_OBSERVATION_ONLY_AS_OOS'
    stamp = _utc_now()
    details = {
        'vault_id': vid,
        'calibration_id': str(calibration_id),
        'holdout_passed': passed,
        'vault_spent': bool(vault_spent),
        'true_oos_fallback': 'observation_only_period' if vault_spent else None,
    }
    db.batch([
        (
            'INSERT INTO adaptive_holdout_vault(namespace,vault_id,touched_count,vault_spent,first_touched_at,calibration_id,status,details_json,updated_at) '
            'VALUES(?,?,?,?,?,?,?,?,?)',
            (namespace, vid, 1, vault_spent, stamp, str(calibration_id), status, alog.stable_json(details), stamp),
        ),
        (
            'UPDATE adaptive_calibration_runs SET holdout_touched=1,vault_spent=? WHERE namespace=? AND calibration_id=?',
            (vault_spent, namespace, str(calibration_id)),
        ),
    ])
    alog.append_log(
        db, namespace, correlation_id=str(calibration_id), track='SYSTEM',
        category='CALIBRATION',
        decision_type='CALIBRATION_GO' if passed else 'CALIBRATION_NO_GO',
        named_cause='holdout_vault_passed' if passed else 'holdout_vault_spent_on_failure',
        rule_fired='holdout_vault_single_touch_lock',
        conditions={'vault_id': vid, 'touched_count': 1, 'holdout_passed': passed},
        execution_details=details,
        source_at=stamp,
    )
    return {
        'vault_id': vid,
        'touched_count': 1,
        'vault_spent': bool(vault_spent),
        'status': status,
        'details': details,
    }


def evaluate_meta_kill_switch(db, namespace, strategy, champion_r_series, track_a_r_series, min_days=AP['meta_kill_min_days'], max_negative_t=AP['meta_kill_max_t'], spawn_id=None):
    """Trigger the meta-kill switch if Track C champions fail to beat Track A baseline over time."""
    s = int(strategy)
    d_t = rc.compute_paired_active_returns(champion_r_series, track_a_r_series)
    n = len(d_t)
    hac = rc.newey_west_t_hac(d_t)
    cum_active = float(np.sum(d_t))
    triggered = bool(n >= int(min_days) and cum_active < 0.0 and hac['t_hac'] <= float(max_negative_t))
    stamp = _utc_now()

    if triggered:
        db.batch([
            (
                "UPDATE adaptive_tracks SET status='killed',updated_at=? WHERE namespace=? AND track='C' AND strategy=?",
                (stamp, namespace, s),
            ),
            (
                "UPDATE adaptive_probation SET meta_kill_triggered=1,status='META_KILLED',updated_at=? WHERE namespace=? AND strategy=?",
                (stamp, namespace, s),
            ),
            (
                "INSERT INTO paper_meta(namespace,key,value) VALUES(?,?,?) ON CONFLICT(namespace,key) DO UPDATE SET value=excluded.value",
                (namespace, f'adaptive_meta_kill_strategy_{s}', '1'),
            ),
        ])
        alog.append_log(
            db, namespace, correlation_id=str(spawn_id or f'meta_kill_s{s}'),
            spawn_id=spawn_id, track='C', strategy=s,
            category='KILL_SWITCH', decision_type='META_KILL',
            named_cause='champion_failed_to_beat_track_a_over_time',
            rule_fired='meta_kill_switch_on_negative_champion_vs_track_a',
            conditions={'days': n, 'min_days': int(min_days), 'cumulative_active_return': cum_active, 't_hac': hac['t_hac']},
            execution_details={'meta_kill_triggered': True, 'track_c_demoted_to_track_a': True},
            source_at=stamp,
        )

    return {
        'strategy': s,
        'days_evaluated': n,
        'cumulative_active_return': cum_active,
        'mean_active_return': hac['mean'],
        't_hac': hac['t_hac'],
        'meta_kill_triggered': triggered,
    }


def run_lookahead_truncation_test(stock_df, index_df, corp_actions, cut_dates, strategies=range(1, 8), params_by_strategy=None):
    """Automated CI look-ahead truncation test: cuts BOTH price data AND corporate-action data at t.

    Verifies that for every cut_date t and every strategy:
    1. Point-in-time prefilter status & metrics at t are identical whether computed on full data or data truncated at t.
    2. Corporate-action back-adjusted prices at t are identical whether future corporate actions (ex_date > t) exist or are cut at t.
    3. Entry and exit signals at t are 100% identical between the full dataset and the truncated dataset.
    """
    params_by_strategy = params_by_strategy or {}
    mismatches = []
    checks_run = 0
    symbols = sorted(stock_df['symbol'].astype(str).unique().tolist()) if not stock_df.empty else []

    for cut_t in [str(d) for d in cut_dates]:
        # Truncated datasets cut strictly at cut_t
        trunc_stock = stock_df[stock_df['trade_date'].astype(str) <= cut_t].copy()
        trunc_index = index_df[index_df['trade_date'].astype(str) <= cut_t].copy()
        trunc_corps = [c for c in (corp_actions or []) if str(c.get('ex_date') or '') <= cut_t]

        for sym in symbols:
            full_sym = stock_df[stock_df['symbol'] == sym]
            trunc_sym = trunc_stock[trunc_stock['symbol'] == sym]
            if trunc_sym.empty or str(trunc_sym.iloc[-1]['trade_date']) != cut_t:
                continue

            # 1. Prefilter invariance at cut_t
            pf_full = pf.evaluate(full_sym, index_df, cut_t)
            pf_trunc = pf.evaluate(trunc_sym, trunc_index, cut_t)
            checks_run += 1
            if pf_full['status'] != pf_trunc['status'] or pf_full['checks'] != pf_trunc['checks']:
                mismatches.append({'cut_date': cut_t, 'symbol': sym, 'stage': 'prefilter', 'full': pf_full['status'], 'trunc': pf_trunc['status']})

            # 2. Corporate-action back-adjusted indicator & signal invariance at cut_t
            adj_from_full = ae.back_adjust_ohlc_pit(full_sym, corp_actions, as_of_date=cut_t)
            adj_from_trunc = ae.back_adjust_ohlc_pit(trunc_sym, trunc_corps, as_of_date=cut_t)

            for s in strategies:
                p = params_by_strategy.get(int(s), {})
                ind_full = ae.evaluate_parameterized_strategy(int(s), adj_from_full, p)
                ind_trunc = ae.evaluate_parameterized_strategy(int(s), adj_from_trunc, p)
                row_full = ind_full.iloc[-1]
                row_trunc = ind_trunc.iloc[-1]
                checks_run += 1
                en_f, en_t = bool(row_full['entry_condition']), bool(row_trunc['entry_condition'])
                ex_f, ex_t = bool(row_full['exit_condition']), bool(row_trunc['exit_condition'])
                cl_f, cl_t = float(row_full['close']), float(row_trunc['close'])
                if en_f != en_t or ex_f != ex_t or abs(cl_f - cl_t) > 1e-9:
                    mismatches.append({
                        'cut_date': cut_t,
                        'symbol': sym,
                        'strategy': int(s),
                        'stage': 'signal_or_back_adjust',
                        'full': {'entry': en_f, 'exit': ex_f, 'close': cl_f},
                        'trunc': {'entry': en_t, 'exit': ex_t, 'close': cl_t},
                    })

    return {
        'passed': len(mismatches) == 0,
        'checks_run': checks_run,
        'cut_dates_tested': [str(d) for d in cut_dates],
        'mismatches': mismatches,
    }
