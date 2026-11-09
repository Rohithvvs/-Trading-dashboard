"""Loader for adaptive_policy.json: the single home of every adaptive (Track B/C) number.

Track A frozen policy files (capital_policy.json, charge_rates.json, config.json, strategy_rules.json)
are only read here, never written. A missing or malformed key fails closed at import time.
"""
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POLICY_PATH = ROOT / 'adaptive_policy.json'

_INTS = (
    'max_track_b_challengers', 'max_track_c_champions', 'fast_swing_warm_start_days', 'trend_warm_start_min_days',
    'trend_warm_start_max_days', 'trend_warm_start_default_days', 'fast_swing_target_window_days', 'trend_target_window_days',
    'extension_days', 'min_new_discordant_trades', 'min_distinct_entry_weeks', 'gate1_min_total_trades', 'gate5_min_observations',
    'placebo_runs', 'probation_days_trend', 'probation_days_fast_swing', 'bootstrap_block_size', 'bootstrap_n_boot',
    'calibration_n_sims', 'calibration_min_sims', 'meta_kill_min_days', 'observation_min_sessions', 'base_seed', 'placebo_seed_stride',
)
_FLOATS = (
    'max_rho_bar', 'critical_value_floor', 'alpha', 'gate2_cost_slippage_hurdle_daily', 'gate3_min_dd_baseline_floor',
    'max_dd_multiplier', 'max_single_trade_share', 'gate4_beta_se_stability_threshold', 'gate4_max_subsample_beta_diff',
    'gate5_max_abs_lag1_autocorr', 'gate5_min_half_mean_vs_overall', 'plateau_retention_min', 'placebo_percentile',
    'gate9_min_effect_size_daily', 'track_c_superiority_bps_per_day', 'probation_sigma_multiplier', 'bootstrap_ci_level',
    'power_floor', 'meta_kill_max_t',
)


def _fail(reason):
    raise RuntimeError(f'adaptive_policy_invalid:{reason}')


def load(path=POLICY_PATH):
    p = json.loads(Path(path).read_text(encoding='utf8'))
    for k in _INTS:
        v = p.get(k)
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            _fail(k)
    for k in _FLOATS:
        v = p.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            _fail(k)
    for k in ('fast_swing_strategies', 'trend_strategies'):
        if not isinstance(p.get(k), list) or not p[k] or not all(isinstance(x, int) and not isinstance(x, bool) for x in p[k]):
            _fail(k)
    if set(p['fast_swing_strategies']) & set(p['trend_strategies']) or set(p['fast_swing_strategies']) | set(p['trend_strategies']) != set(range(1, 8)):
        _fail('strategy_tiers_must_partition_1_to_7')
    if not p['trend_warm_start_min_days'] <= p['trend_warm_start_default_days'] <= p['trend_warm_start_max_days']:
        _fail('trend_warm_start_default_out_of_range')
    if not 0 < p['alpha'] < 0.5 or not 0 <= p['max_rho_bar'] < 1 or not 0 < p['power_floor'] < 1 or not 0 < p['bootstrap_ci_level'] < 1:
        _fail('probability_out_of_range')
    if not 0 < p['placebo_percentile'] < 100:
        _fail('placebo_percentile')
    labelled = set()
    for keys in (p.get('provenance') or {}).values():
        labelled |= set(keys)
    missing = (set(_INTS) | set(_FLOATS) | {'fast_swing_strategies', 'trend_strategies'}) - labelled
    if missing:
        _fail('unlabelled_provenance:' + ','.join(sorted(missing)))
    return p


POLICY = load()


def policy_hash():
    return hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest()


def read_json(name):
    """Read a Track A policy file (read-only)."""
    return json.loads((ROOT / name).read_text(encoding='utf8'))
