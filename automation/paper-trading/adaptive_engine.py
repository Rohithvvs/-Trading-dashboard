"""3-Tier Self-Improvement (Adaptive) Paper-Trading Engine (Tracks A, B, and C).

Implements:
- Track A (frozen baseline), Track B (max 2-3 parameter-only challengers per strategy),
  Track C (max 1 champion per strategy), with independent paper capital per track
- Tier-specific warm-start: 60 trading days (Fast Swing: strategies 3, 5) and
  100-120 trading days (Trend/Momentum: strategies 1, 2, 4, 6, 7)
- Point-in-time daily_prefilter_universe and Bhavcopy SERIES enforcement
- Point-in-time corporate-action indicator back-adjustment on/after ex-date only
- Starting equity E_0 valued net of exit haircut (modeled sell fees + exit slippage + circuit haircut)
- Separate counting of discordant trades for inherited warm-start positions vs new evaluation-window positions
- Target windows (45d Fast / 75d Trend) with at most one +15d extension on trade count or
  pre-registered regime flag; otherwise status = INCONCLUSIVE
- Microstructure locks: signals at close of t -> fills at open of t+1, circuit carry-forward,
  gap-aware stops, EQ-only new entries, 1.5x exit slippage on BE/BZ
"""
import copy, hashlib, json, math
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

import adaptive_logging as alog
import capital as cap
import pit_archive as pit
import strategy_indicators as si_base

SLEEVE_CAPITAL_PAISE = cap.POLICY['sleeve_capital_inr'] * 100  # 50,000,000 paise (₹5,00,000)
TARGET_NOTIONAL_INR = cap.POLICY['target_notional_inr']        # ₹50,000
MAX_POSITIONS_PER_SLEEVE = cap.POLICY['max_positions_per_sleeve']  # 9

MAX_TRACK_B_CHALLENGERS = 3
MAX_TRACK_C_CHAMPIONS = 1

FAST_SWING_STRATEGIES = frozenset({3, 5})
TREND_STRATEGIES = frozenset({1, 2, 4, 6, 7})

FAST_SWING_WARM_START_DAYS = 60
TREND_WARM_START_MIN_DAYS = 100
TREND_WARM_START_MAX_DAYS = 120
TREND_WARM_START_DEFAULT_DAYS = 110

FAST_SWING_TARGET_WINDOW_DAYS = 45
TREND_TARGET_WINDOW_DAYS = 75
EXTENSION_DAYS = 15
ALLOWED_EXTENSION_REASONS = frozenset({'trade_count_under_floor', 'preregistered_regime_flag'})

MIN_DISCORDANT_TRADES = 10
MIN_DISTINCT_ENTRY_WEEKS = 3

BASELINE_PARAMS = {
    1: {'entry_lookback': 20, 'exit_lookback': 10},
    2: {'atr_period': 10, 'atr_multiplier': 3.0},
    3: {'rsi_period': 14, 'rsi_entry': 40.0, 'rsi_exit': 60.0, 'sma_trend': 200, 'sma_exit': 5},
    4: {'ema_fast': 20, 'ema_slow': 50, 'sma_trend': 200},
    5: {'bb_period': 20, 'bb_std': 2.0, 'sma_trend': 200},
    6: {'ema_fast': 12, 'ema_slow': 26, 'signal_period': 9, 'sma_trend': 50},
    7: {'high_lookback': 252, 'near_high_ratio': 0.90, 'sma_trend': 200, 'sma_exit': 50, 'trail_ratio': 0.90},
}

SCALED_CORP_ACTIONS = frozenset({'SPLIT', 'BONUS', 'EXTRAORDINARY_DIVIDEND'})


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def strategy_tier(strategy):
    s = int(strategy)
    if s in FAST_SWING_STRATEGIES:
        return 'FAST_SWING'
    if s in TREND_STRATEGIES:
        return 'TREND'
    raise ValueError(f'unknown_strategy:{strategy}')


def default_warm_start_days(strategy):
    return FAST_SWING_WARM_START_DAYS if strategy_tier(strategy) == 'FAST_SWING' else TREND_WARM_START_DEFAULT_DAYS


def validate_warm_start_days(strategy, warm_start_days):
    tier = strategy_tier(strategy)
    days = int(warm_start_days)
    if tier == 'FAST_SWING':
        if days != FAST_SWING_WARM_START_DAYS:
            raise ValueError(f'fast_swing_warm_start_must_be_60_got_{days}')
    else:
        if not (TREND_WARM_START_MIN_DAYS <= days <= TREND_WARM_START_MAX_DAYS):
            raise ValueError(f'trend_warm_start_must_be_100_to_120_got_{days}')
    return days


def default_target_window_days(strategy):
    return FAST_SWING_TARGET_WINDOW_DAYS if strategy_tier(strategy) == 'FAST_SWING' else TREND_TARGET_WINDOW_DAYS


def validate_parameter_only_mutation(strategy, params):
    """Ensure Track B challengers only mutate allowed numeric parameters of the given strategy."""
    s = int(strategy)
    if s not in BASELINE_PARAMS:
        raise ValueError(f'unknown_strategy:{strategy}')
    if not isinstance(params, dict):
        raise ValueError('params_must_be_dict')
    allowed = BASELINE_PARAMS[s]
    unknown = set(params.keys()) - set(allowed.keys())
    if unknown:
        raise ValueError(f'disallowed_non_parameter_mutation:{sorted(unknown)}')
    merged = dict(allowed)
    for k, v in params.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) or float(v) <= 0:
            raise ValueError(f'invalid_parameter_value:{k}={v}')
        merged[k] = type(allowed[k])(v) if isinstance(allowed[k], int) and float(v).is_integer() else float(v)
    return merged


def compute_harness_hash():
    """Compute a deterministic SHA-256 hash of the adaptive engine and indicator rules."""
    here = Path(__file__).resolve()
    ind = here.parent / 'strategy_indicators.py'
    rules = here.parent / 'strategy_rules.json'
    h = hashlib.sha256()
    for p in (here, ind, rules):
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()


def back_adjust_ohlc_pit(df, corp_actions, as_of_date):
    """Back-adjust pre-ex-date OHLC prices for splits/bonuses strictly with ex_date <= as_of_date.

    Corporate actions with ex_date > as_of_date are never applied (zero look-ahead).
    For an action on ex_date <= as_of_date with ratio r = ratio_num / ratio_den,
    bars with trade_date < ex_date have open/high/low/close divided by r and volume multiplied by r.
    """
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()
    as_of = str(as_of_date)
    out = df[df['trade_date'].astype(str) <= as_of].copy().sort_values('trade_date').reset_index(drop=True)
    if out.empty or not corp_actions:
        return out
    for col in ('open', 'high', 'low', 'close'):
        if col in out.columns:
            out[col] = out[col].astype(float)
    if 'volume' in out.columns:
        out['volume'] = out['volume'].astype(float)

    sym_col = out['symbol'].iloc[0] if 'symbol' in out.columns and len(out) else None
    applicable = []
    for act in corp_actions:
        if act.get('kind') not in SCALED_CORP_ACTIONS:
            continue
        ex_date = str(act.get('ex_date') or '')
        if not ex_date or ex_date > as_of:
            continue
        if sym_col and act.get('symbol') and str(act['symbol']) != str(sym_col):
            continue
        num = act.get('ratio_num')
        den = act.get('ratio_den')
        if isinstance(num, int) and isinstance(den, int) and num > 0 and den > 0:
            applicable.append((ex_date, float(num) / float(den)))

    applicable.sort(key=lambda x: x[0])
    for ex_date, ratio in applicable:
        mask = out['trade_date'].astype(str) < ex_date
        if mask.any():
            for col in ('open', 'high', 'low', 'close'):
                if col in out.columns:
                    out.loc[mask, col] = out.loc[mask, col] / ratio
            if 'volume' in out.columns:
                out.loc[mask, 'volume'] = out.loc[mask, 'volume'] * ratio
    return out


def evaluate_parameterized_strategy(strategy, df, params=None):
    """Evaluate strategy indicators and entry/exit conditions using baseline or challenger parameters."""
    s = int(strategy)
    merged = validate_parameter_only_mutation(s, params or {})
    if merged == BASELINE_PARAMS[s]:
        if s == 1:
            f = df.copy()
            f['entry_condition'] = f.close > f.high.shift().rolling(20).max()
            f['exit_condition'] = f.close < f.low.shift().rolling(10).min()
            return f
        return getattr(si_base, f'strategy_{s}')(df)

    g = df.copy()
    c = g['close'].astype(float)
    h = g['high'].astype(float)
    l = g['low'].astype(float)

    if s == 1:
        en_lb = int(merged['entry_lookback'])
        ex_lb = int(merged['exit_lookback'])
        g['entry_condition'] = c > h.shift().rolling(en_lb).max()
        g['exit_condition'] = c < l.shift().rolling(ex_lb).min()
        return g

    if s == 2:
        period = int(merged['atr_period'])
        mult = float(merged['atr_multiplier'])
        ha, la, ca = h.to_numpy(float), l.to_numpy(float), c.to_numpy(float)
        n = len(g)
        tr = np.maximum(ha - la, np.maximum(np.abs(ha - np.r_[np.nan, ca[:-1]]), np.abs(la - np.r_[np.nan, ca[:-1]])))
        if n > 0:
            tr[0] = ha[0] - la[0]
        atr = np.full(n, np.nan)
        upper = atr.copy()
        lower = atr.copy()
        line = atr.copy()
        direction = atr.copy()
        init_idx = period - 1
        for i in range(n):
            if i < init_idx:
                continue
            atr[i] = np.mean(tr[:period]) if i == init_idx else (atr[i - 1] * (period - 1) + tr[i]) / period
            bu = (ha[i] + la[i]) / 2.0 + mult * atr[i]
            bl = (ha[i] + la[i]) / 2.0 - mult * atr[i]
            if i == init_idx:
                upper[i], lower[i], direction[i], line[i] = bu, bl, 1.0, bu
                continue
            upper[i] = bu if bu < upper[i - 1] or ca[i - 1] > upper[i - 1] else upper[i - 1]
            lower[i] = bl if bl > lower[i - 1] or ca[i - 1] < lower[i - 1] else lower[i - 1]
            if line[i - 1] == upper[i - 1]:
                direction[i] = -1.0 if ca[i] > upper[i] else 1.0
            else:
                direction[i] = 1.0 if ca[i] < lower[i] else -1.0
            line[i] = lower[i] if direction[i] == -1.0 else upper[i]
        g['atr'] = atr
        g['supertrend'] = line
        g['direction'] = direction
        g['prior_direction'] = g['direction'].shift()
        g['entry_condition'] = (g['prior_direction'] == 1) & (g['direction'] == -1) & (c > g['supertrend'])
        g['exit_condition'] = (g['prior_direction'] == -1) & (g['direction'] == 1)
        return g

    if s == 3:
        rp = int(merged['rsi_period'])
        d = c.diff().to_numpy()
        up = np.maximum(d, 0.0)
        down = np.maximum(-d, 0.0)
        n = len(c)
        ag = np.full(n, np.nan)
        al = ag.copy()
        if n > rp:
            ag[rp] = up[1 : rp + 1].mean()
            al[rp] = down[1 : rp + 1].mean()
            for i in range(rp + 1, n):
                ag[i] = ((rp - 1) * ag[i - 1] + up[i]) / rp
                al[i] = ((rp - 1) * al[i - 1] + down[i]) / rp
        with np.errstate(divide='ignore', invalid='ignore'):
            rsi = 100.0 - 100.0 / (1.0 + ag / al)
        rsi = np.where(al == 0, 100.0, rsi)
        rsi = np.where((ag == 0) & (al > 0), 0.0, rsi)
        g['rsi14'] = rsi
        g['sma200'] = c.rolling(int(merged['sma_trend'])).mean()
        g['sma5'] = c.rolling(int(merged['sma_exit'])).mean()
        g['entry_condition'] = (c > g['sma200']) & (g['rsi14'] < float(merged['rsi_entry']))
        g['exit_condition'] = (g['rsi14'] > float(merged['rsi_exit'])) | (c > g['sma5'])
        return g

    if s == 4:
        g['ema20'] = c.ewm(span=int(merged['ema_fast']), adjust=False).mean()
        g['ema50'] = c.ewm(span=int(merged['ema_slow']), adjust=False).mean()
        g['prior_ema20'] = g['ema20'].shift()
        g['prior_ema50'] = g['ema50'].shift()
        g['sma200'] = c.rolling(int(merged['sma_trend'])).mean()
        g['entry_condition'] = (g['ema20'] > g['ema50']) & (g['prior_ema20'] <= g['prior_ema50']) & (c > g['sma200'])
        g['exit_condition'] = (g['ema20'] < g['ema50']) & (g['prior_ema20'] >= g['prior_ema50'])
        return g

    if s == 5:
        bp = int(merged['bb_period'])
        bstd = float(merged['bb_std'])
        g['bb_middle'] = c.rolling(bp).mean()
        g['std20'] = c.rolling(bp).std(ddof=0)
        g['bb_lower'] = g['bb_middle'] - bstd * g['std20']
        g['sma200'] = c.rolling(int(merged['sma_trend'])).mean()
        g['entry_condition'] = (c > g['sma200']) & (c <= g['bb_lower'])
        g['exit_condition'] = c >= g['bb_middle']
        return g

    if s == 6:
        g['ema12'] = c.ewm(span=int(merged['ema_fast']), adjust=False).mean()
        g['ema26'] = c.ewm(span=int(merged['ema_slow']), adjust=False).mean()
        g['macd'] = g['ema12'] - g['ema26']
        g['signal'] = g['macd'].ewm(span=int(merged['signal_period']), adjust=False).mean()
        g['prior_macd'] = g['macd'].shift()
        g['prior_signal'] = g['signal'].shift()
        g['sma50'] = c.rolling(int(merged['sma_trend'])).mean()
        g['entry_condition'] = (g['macd'] > g['signal']) & (g['prior_macd'] <= g['prior_signal']) & (c > g['sma50'])
        g['exit_condition'] = (g['macd'] < g['signal']) & (g['prior_macd'] >= g['prior_signal'])
        return g

    if s == 7:
        hlb = int(merged['high_lookback'])
        ratio = float(merged['near_high_ratio'])
        g['high252'] = h.rolling(hlb).max()
        g['sma200'] = c.rolling(int(merged['sma_trend'])).mean()
        g['sma50'] = c.rolling(int(merged['sma_exit'])).mean()
        g['entry_condition'] = (c > g['sma200']) & (c >= ratio * g['high252'])
        g['exit_condition'] = c < g['sma50']
        return g

    raise ValueError(f'unsupported_strategy:{s}')


def estimate_exit_haircut_paise(qty, mark_price, series='EQ', locked_lower_days=0, adv_inr=200_000_000, stress=False):
    """Compute exit haircut in paise for an open position (sell charges + tiered slippage + circuit lock haircut)."""
    qty = int(qty)
    if qty <= 0:
        return 0
    mark_paise = cap.price_paise(mark_price)
    gross_paise = qty * mark_paise

    # 1. Lower-circuit carry-forward haircut: 1% per locked day after the first
    extra_locked = max(0, int(locked_lower_days) - 1)
    circuit_loss_paise = (gross_paise * min(100, extra_locked)) // 100

    # 2. Tiered exit slippage (1.5x stress on BE/BZ or explicit stress mode)
    base_bps = 5 if float(adv_inr) > 200_000_000 else 8
    part_bps = 10.0 * (gross_paise / 100.0) / max(1.0, 0.005 * float(adv_inr))
    total_bps = base_bps + part_bps
    if stress or str(series).upper() in ('BE', 'BZ'):
        total_bps *= 1.5
    slippage_paise = int(math.ceil(gross_paise * (total_bps / 10_000.0)))

    # 3. Modeled sell charges (brokerage min(20 INR, 0.3%), STT 0.1%, exchange/SEBI/IPFT + 18% GST + overnight DP 14.75 INR)
    brokerage_paise = min(2000, int(round(gross_paise * 0.003)))
    stt_paise = int(round(gross_paise * 0.001))
    exch_sebi_paise = int(round(gross_paise * 0.0000345))
    gst_paise = int(round((brokerage_paise + exch_sebi_paise) * 0.18))
    dp_paise = 1475 + 266  # 14.75 INR + 18% GST
    fees_paise = brokerage_paise + stt_paise + exch_sebi_paise + gst_paise + dp_paise

    return circuit_loss_paise + slippage_paise + fees_paise


def value_starting_equity_net_of_haircut(cash_paise, open_positions, marks_by_symbol=None, series_by_symbol=None, locked_days_by_symbol=None, stress=False):
    """Value starting equity E_0 net of exit haircut for all inherited open positions."""
    marks_by_symbol = marks_by_symbol or {}
    series_by_symbol = series_by_symbol or {}
    locked_days_by_symbol = locked_days_by_symbol or {}

    gross_positions_paise = 0
    total_haircut_paise = 0
    for pos in open_positions:
        qty = int(pos.get('qty') or 0)
        if qty <= 0:
            continue
        sym = pos['symbol']
        px = marks_by_symbol.get(sym, pos.get('mark_price') or pos.get('entry_price'))
        px_paise = cap.price_paise(px)
        gross_positions_paise += qty * px_paise
        total_haircut_paise += estimate_exit_haircut_paise(
            qty=qty,
            mark_price=px,
            series=series_by_symbol.get(sym, pos.get('series', 'EQ')),
            locked_lower_days=locked_days_by_symbol.get(sym, pos.get('locked_days', 0)),
            stress=stress,
        )
    gross_equity_paise = int(cash_paise) + gross_positions_paise
    net_equity_paise = gross_equity_paise - total_haircut_paise
    return {
        'cash_paise': int(cash_paise),
        'gross_positions_paise': gross_positions_paise,
        'starting_equity_gross_paise': gross_equity_paise,
        'exit_haircut_paise': total_haircut_paise,
        'starting_equity_net_haircut_paise': net_equity_paise,
        'inherited_positions_count': sum(1 for p in open_positions if int(p.get('qty') or 0) > 0),
    }


def classify_discordant_trades(var_trades, base_trades, warm_start_end_date):
    """Separate discordant trades into inherited (entered during warm-start) vs new (entered in evaluation window).

    A trade is discordant if its (symbol, entry_date, exit_date, qty) or presence differs between
    the candidate variant and the baseline.
    """
    ws_end = str(warm_start_end_date)

    def _key(t):
        return (str(t['symbol']), str(t['entry_date']), str(t.get('exit_date') or 'OPEN'))

    base_keys = {_key(t): t for t in base_trades}
    var_keys = {_key(t): t for t in var_trades}

    all_keys = sorted(set(base_keys.keys()) | set(var_keys.keys()))
    inherited_discordant = []
    new_discordant = []
    entry_weeks = set()

    for k in all_keys:
        bt = base_keys.get(k)
        vt = var_keys.get(k)
        if bt is not None and vt is not None and int(bt.get('qty', 0)) == int(vt.get('qty', 0)):
            continue
        ref = vt if vt is not None else bt
        entry_date = str(ref['entry_date'])
        item = {
            'symbol': ref['symbol'],
            'entry_date': entry_date,
            'exit_date': ref.get('exit_date'),
            'in_variant': vt is not None,
            'in_baseline': bt is not None,
            'inherited_from_warm_start': entry_date <= ws_end,
            'net_pnl_paise': int(ref.get('net_pnl_paise', 0)),
        }
        if entry_date <= ws_end:
            inherited_discordant.append(item)
        else:
            new_discordant.append(item)
            d_obj = datetime.strptime(entry_date[:10], '%Y-%m-%d').date()
            iso_yr, iso_wk, _ = d_obj.isocalendar()
            entry_weeks.add(f'{iso_yr}-W{iso_wk:02d}')

    return {
        'inherited_discordant_count': len(inherited_discordant),
        'new_discordant_count': len(new_discordant),
        'distinct_new_entry_weeks': len(entry_weeks),
        'inherited_discordant_trades': inherited_discordant,
        'new_discordant_trades': new_discordant,
    }


def spawn_candidate(
    db,
    namespace,
    strategy,
    params,
    track='B',
    candidate_kind='CANDIDATE',
    warm_start_days=None,
    eval_window_target_days=None,
    data_snapshot_hash=None,
    rng_seeds=None,
    decision_inputs=None,
    starting_cash_paise=SLEEVE_CAPITAL_PAISE,
    inherited_positions=None,
    marks_by_symbol=None,
    series_by_symbol=None,
    spawn_id=None,
    correlation_id=None,
    spawned_at=None,
):
    """Spawn a Track B challenger or Track C champion with full engineering locks and capital isolation."""
    s = int(strategy)
    tier = strategy_tier(s)
    if track not in ('A', 'B', 'C'):
        raise ValueError(f'invalid_track:{track}')
    validated_params = validate_parameter_only_mutation(s, params)
    if track == 'A' and validated_params != BASELINE_PARAMS[s]:
        raise ValueError('track_a_baseline_cannot_be_mutated')

    active_in_track = db.query(
        "SELECT COUNT(*) AS n FROM adaptive_tracks WHERE namespace=? AND track=? AND strategy=? AND status IN ('active','challenger','champion','probation')",
        (namespace, track, s),
    )[0]['n']
    if track == 'B' and int(active_in_track) >= MAX_TRACK_B_CHALLENGERS and candidate_kind == 'CANDIDATE':
        raise RuntimeError(f'track_b_max_{MAX_TRACK_B_CHALLENGERS}_concurrent_challengers_exceeded')
    if track == 'C' and int(active_in_track) >= MAX_TRACK_C_CHAMPIONS:
        raise RuntimeError(f'track_c_max_{MAX_TRACK_C_CHAMPIONS}_champion_exceeded')

    ws_days = validate_warm_start_days(s, warm_start_days or default_warm_start_days(s))
    target_days = int(eval_window_target_days or default_target_window_days(s))
    eligible_for_selection = 1 if candidate_kind in ('CANDIDATE', 'TRACK_C_COMPARISON') else 0

    eq_info = value_starting_equity_net_of_haircut(
        cash_paise=starting_cash_paise,
        open_positions=inherited_positions or [],
        marks_by_symbol=marks_by_symbol,
        series_by_symbol=series_by_symbol,
    )

    stamp = spawned_at or _utc_now()
    h_hash = compute_harness_hash()
    d_hash = str(data_snapshot_hash or alog.compute_hash({'strategy': s, 'params': validated_params, 'at': stamp}))
    seeds = list(rng_seeds or [20261109])
    inputs = decision_inputs or {'strategy': s, 'params': validated_params, 'tier': tier}
    sid = str(spawn_id or alog.compute_hash(f'{namespace}|{track}|{s}|{alog.stable_json(validated_params)}|{stamp}')[:32])
    cid = str(correlation_id or sid)
    parent_ver = alog.compute_hash(BASELINE_PARAMS[s])

    db.batch([(
        'INSERT INTO adaptive_spawns('
        'namespace,spawn_id,correlation_id,strategy,track,tier,parent_version,params_json,candidate_kind,'
        'eligible_for_selection,k_cand,rho_bar,k_eff,effective_critical_value,warm_start_days,'
        'eval_window_target_days,starting_equity_gross_paise,exit_haircut_paise,starting_equity_net_haircut_paise,'
        'inherited_positions_count,harness_hash,data_snapshot_hash,rng_seeds_json,decision_inputs_json,status,spawned_at'
        ') VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (
            namespace, sid, cid, s, track, tier, parent_ver,
            alog.stable_json(validated_params), candidate_kind, eligible_for_selection,
            1, 0.0, 1.0, 1.40, ws_days, target_days,
            eq_info['starting_equity_gross_paise'],
            eq_info['exit_haircut_paise'],
            eq_info['starting_equity_net_haircut_paise'],
            eq_info['inherited_positions_count'],
            h_hash, d_hash, alog.stable_json(seeds), alog.stable_json(inputs),
            'SPAWNED', stamp,
        ),
    )])

    if candidate_kind in ('BASELINE', 'CANDIDATE', 'TRACK_C_COMPARISON') and track in ('A', 'B', 'C'):
        slot_idx = int(active_in_track) + 1
        role_status = 'active' if track == 'A' else ('challenger' if track == 'B' else 'champion')
        db.batch([(
            'INSERT OR REPLACE INTO adaptive_tracks('
            'namespace,track,strategy,slot_index,spawn_id,status,params_json,allocated_capital_paise,cash_paise,'
            'starting_equity_net_haircut_paise,created_at,updated_at'
            ') VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (
                namespace, track, s, slot_idx, sid, role_status,
                alog.stable_json(validated_params), SLEEVE_CAPITAL_PAISE,
                eq_info['cash_paise'], eq_info['starting_equity_net_haircut_paise'],
                stamp, stamp,
            ),
        )])

    alog.append_log(
        db, namespace, correlation_id=cid, spawn_id=sid, track=track, strategy=s,
        category='SPAWN', decision_type='SPAWN', named_cause='candidate_spawned',
        rule_fired='tier_warm_start_and_net_haircut_lock', strategy_version=parent_ver,
        conditions={
            'tier': tier,
            'warm_start_days': ws_days,
            'eval_window_target_days': target_days,
            'candidate_kind': candidate_kind,
            'eligible_for_selection': bool(eligible_for_selection),
        },
        execution_details={
            'params': validated_params,
            'starting_equity_gross_paise': eq_info['starting_equity_gross_paise'],
            'exit_haircut_paise': eq_info['exit_haircut_paise'],
            'starting_equity_net_haircut_paise': eq_info['starting_equity_net_haircut_paise'],
            'harness_hash': h_hash,
            'data_snapshot_hash': d_hash,
            'rng_seeds': seeds,
            'decision_inputs': inputs,
        },
        input_data=inputs,
        source_at=stamp,
    )
    return {
        'spawn_id': sid,
        'correlation_id': cid,
        'strategy': s,
        'track': track,
        'tier': tier,
        'params': validated_params,
        'warm_start_days': ws_days,
        'eval_window_target_days': target_days,
        'starting_equity_gross_paise': eq_info['starting_equity_gross_paise'],
        'exit_haircut_paise': eq_info['exit_haircut_paise'],
        'starting_equity_net_haircut_paise': eq_info['starting_equity_net_haircut_paise'],
        'harness_hash': h_hash,
        'data_snapshot_hash': d_hash,
        'rng_seeds': seeds,
    }


def evaluate_stopping_and_window(
    db,
    namespace,
    spawn_id,
    days_elapsed,
    new_discordant_trades,
    distinct_entry_weeks,
    preregistered_regime_flag=False,
    min_discordant_trades=MIN_DISCORDANT_TRADES,
    min_entry_weeks=MIN_DISTINCT_ENTRY_WEEKS,
    decided_at=None,
):
    """Enforce non-informative stopping: 45d (Fast) / 75d (Trend), at most one +15d extension, else INCONCLUSIVE."""
    rows = db.query('SELECT * FROM adaptive_spawns WHERE namespace=? AND spawn_id=?', (namespace, spawn_id))
    if not rows:
        raise KeyError(f'spawn_not_found:{spawn_id}')
    sp = rows[0]
    target_days = int(sp['eval_window_target_days'])
    ext_days = int(sp['extension_days'] or 0)
    total_required_days = target_days + ext_days
    days_elapsed = int(days_elapsed)
    new_disc = int(new_discordant_trades)
    weeks = int(distinct_entry_weeks)
    stamp = decided_at or _utc_now()

    if days_elapsed < total_required_days:
        return {
            'spawn_id': spawn_id,
            'ready_for_final_gate_evaluation': False,
            'status': sp['status'],
            'days_elapsed': days_elapsed,
            'required_days': total_required_days,
            'reason': 'window_in_progress_no_early_peeking',
        }

    sample_sufficient = (new_disc >= int(min_discordant_trades)) and (weeks >= int(min_entry_weeks))
    if not sample_sufficient and ext_days == 0:
        ext_reason = 'trade_count_under_floor' if new_disc < int(min_discordant_trades) or weeks < int(min_entry_weeks) else None
        if preregistered_regime_flag and ext_reason is None:
            ext_reason = 'preregistered_regime_flag'
        if ext_reason in ALLOWED_EXTENSION_REASONS:
            db.batch([(
                'UPDATE adaptive_spawns SET extension_days=?,extension_reason=?,new_discordant_trades=?,distinct_entry_weeks=?,status=? WHERE namespace=? AND spawn_id=?',
                (EXTENSION_DAYS, ext_reason, new_disc, weeks, 'EXTENDED', namespace, spawn_id),
            )])
            alog.append_log(
                db, namespace, correlation_id=sp['correlation_id'], spawn_id=spawn_id,
                track=sp['track'], strategy=sp['strategy'],
                category='WARM_START', decision_type='WINDOW_EXTEND', named_cause=ext_reason,
                rule_fired='single_15_day_extension_on_sample_or_regime',
                conditions={'days_elapsed': days_elapsed, 'new_discordant_trades': new_disc, 'distinct_entry_weeks': weeks},
                execution_details={'extension_days': EXTENSION_DAYS, 'new_total_window_days': target_days + EXTENSION_DAYS},
                source_at=stamp,
            )
            return {
                'spawn_id': spawn_id,
                'ready_for_final_gate_evaluation': False,
                'status': 'EXTENDED',
                'extension_days': EXTENSION_DAYS,
                'extension_reason': ext_reason,
                'required_days': target_days + EXTENSION_DAYS,
            }

    if not sample_sufficient and ext_days > 0:
        db.batch([(
            'UPDATE adaptive_spawns SET new_discordant_trades=?,distinct_entry_weeks=?,status=?,decided_at=? WHERE namespace=? AND spawn_id=?',
            (new_disc, weeks, 'INCONCLUSIVE', stamp, namespace, spawn_id),
        )])
        alog.append_log(
            db, namespace, correlation_id=sp['correlation_id'], spawn_id=spawn_id,
            track=sp['track'], strategy=sp['strategy'],
            category='GATE_EVALUATION', decision_type='INCONCLUSIVE', named_cause='insufficient_sample_after_single_extension',
            rule_fired='non_informative_stopping_inconclusive',
            conditions={
                'days_elapsed': days_elapsed,
                'extension_days': ext_days,
                'new_discordant_trades': new_disc,
                'min_discordant_trades': min_discordant_trades,
                'distinct_entry_weeks': weeks,
                'min_entry_weeks': min_entry_weeks,
            },
            source_at=stamp,
        )
        return {
            'spawn_id': spawn_id,
            'ready_for_final_gate_evaluation': False,
            'status': 'INCONCLUSIVE',
            'extension_days': ext_days,
            'reason': 'insufficient_sample_after_single_extension',
        }

    if preregistered_regime_flag and ext_days == 0:
        db.batch([(
            'UPDATE adaptive_spawns SET extension_days=?,extension_reason=?,new_discordant_trades=?,distinct_entry_weeks=?,status=? WHERE namespace=? AND spawn_id=?',
            (EXTENSION_DAYS, 'preregistered_regime_flag', new_disc, weeks, 'EXTENDED', namespace, spawn_id),
        )])
        return {
            'spawn_id': spawn_id,
            'ready_for_final_gate_evaluation': False,
            'status': 'EXTENDED',
            'extension_days': EXTENSION_DAYS,
            'extension_reason': 'preregistered_regime_flag',
            'required_days': target_days + EXTENSION_DAYS,
        }

    db.batch([(
        'UPDATE adaptive_spawns SET new_discordant_trades=?,distinct_entry_weeks=?,status=? WHERE namespace=? AND spawn_id=?',
        (new_disc, weeks, 'EVALUATING', namespace, spawn_id),
    )])
    return {
        'spawn_id': spawn_id,
        'ready_for_final_gate_evaluation': True,
        'status': 'EVALUATING',
        'days_elapsed': days_elapsed,
        'new_discordant_trades': new_disc,
        'distinct_entry_weeks': weeks,
    }


def simulate_track_window(
    db,
    namespace,
    strategy,
    params,
    stock_df,
    index_df,
    warm_start_dates,
    eval_dates,
    corp_actions=None,
    bands_by_date_symbol=None,
    stress_slippage=False,
):
    """Run point-in-time warm-start + evaluation window simulation for a single track with all microstructure locks.

    Enforces:
    - Signals at close of day t -> fills at open of day t+1
    - PIT daily_prefilter_universe and PIT Bhavcopy SERIES on every historical date
    - PIT corporate-action indicator back-adjustment on/after ex-date
    - Upper-circuit buy block, lower-circuit carry-forward exit with 1%/day haircut, gap-aware Strategy 07 stops
    - EQ-only new entries, 1.5x exit slippage on BE/BZ
    - Starting equity E_0 at eval_dates[0] valued net of exit haircut
    """
    s = int(strategy)
    validated_params = validate_parameter_only_mutation(s, params)
    ws_dates = [str(d) for d in warm_start_dates]
    ev_dates = [str(d) for d in eval_dates]
    validate_warm_start_days(s, len(ws_dates))
    all_dates = ws_dates + ev_dates
    ws_end = ws_dates[-1]
    corp_actions = corp_actions or []
    bands_by_date_symbol = bands_by_date_symbol or {}

    cash_paise = SLEEVE_CAPITAL_PAISE
    positions = {}  # symbol -> {qty, entry_price, entry_date, high_water, pending_exit, locked_days}
    pending_signals = []  # list of {symbol, side, signal_date, stop, stop_level}
    closed_trades = []
    daily_records = []
    starting_equity_summary = None

    symbols = sorted(stock_df['symbol'].astype(str).unique().tolist()) if not stock_df.empty else []

    for idx_d, day in enumerate(all_dates):
        in_eval = day > ws_end
        day_bars = stock_df[stock_df['trade_date'].astype(str) == day]
        bar_map = {str(r['symbol']): r for _, r in day_bars.iterrows()}

        # 1. Apply point-in-time corporate action scaling on held positions on ex_date == day
        for act in corp_actions:
            if str(act.get('ex_date')) == day and act.get('symbol') in positions and act.get('kind') in SCALED_CORP_ACTIONS:
                pos = positions[act['symbol']]
                num, den = int(act['ratio_num']), int(act['ratio_den'])
                new_qty = (pos['qty'] * num) // den
                if new_qty >= 1:
                    pos['qty'] = new_qty
                    pos['entry_price'] = round(pos['entry_price'] * den / num, 2)
                    pos['high_water'] = round(pos['high_water'] * den / num, 2)

        # 2. Fill pending signals from day t-1 at open of day t (exits first, then entries)
        exits = [sig for sig in pending_signals if sig['side'] == 'SELL']
        entries = [sig for sig in pending_signals if sig['side'] == 'BUY']

        # Also check carried-forward lower-circuit pending_exit or Strategy 07 gap/touch stops on held positions
        for sym, pos in list(positions.items()):
            bar = bar_map.get(sym)
            if bar is None:
                continue
            open_px = float(bar['open'])
            low_px = float(bar['low'])
            if pos.get('pending_exit'):
                exits.append({'symbol': sym, 'side': 'SELL', 'signal_date': day, 'reason': 'circuit_carry_forward'})
            elif s == 7:
                trail_ratio = float(validated_params.get('trail_ratio', 0.90))
                stop_lvl = round(trail_ratio * pos['high_water'], 2)
                if open_px <= stop_lvl:
                    exits.append({'symbol': sym, 'side': 'SELL', 'signal_date': day, 'stop': True, 'fill_override': open_px, 'reason': 'trail_gap'})
                elif low_px <= stop_lvl and not any(x['symbol'] == sym for x in exits):
                    exits.append({'symbol': sym, 'side': 'SELL', 'signal_date': day, 'stop': True, 'fill_override': stop_lvl, 'reason': 'trail_touch'})

        seen_exit = set()
        for sig in exits:
            sym = sig['symbol']
            if sym in seen_exit or sym not in positions:
                continue
            bar = bar_map.get(sym)
            if bar is None:
                continue
            band = bands_by_date_symbol.get((day, sym), {})
            circuit = str(band.get('circuit') or 'NONE').upper()
            pit_ser = pit.get_pit_series(db, sym, day, as_of_date=day) or str(band.get('series') or 'EQ').upper()
            pos = positions[sym]
            if circuit == 'LOWER':
                pos['pending_exit'] = True
                pos['locked_days'] = int(pos.get('locked_days', 0)) + 1
                continue
            raw_fill = float(sig.get('fill_override') or bar['open'])
            haircut = estimate_exit_haircut_paise(
                qty=pos['qty'],
                mark_price=raw_fill,
                series=pit_ser,
                locked_lower_days=0,
                stress=stress_slippage,
            )
            gross_proceeds = pos['qty'] * cap.price_paise(raw_fill)
            net_proceeds = gross_proceeds - haircut
            cash_paise += net_proceeds
            entry_cost = pos['qty'] * cap.price_paise(pos['entry_price'])
            closed_trades.append({
                'symbol': sym,
                'entry_date': pos['entry_date'],
                'exit_date': day,
                'qty': pos['qty'],
                'entry_price': pos['entry_price'],
                'exit_price': raw_fill,
                'net_pnl_paise': net_proceeds - entry_cost,
                'reason': sig.get('reason', 'daily_exit'),
            })
            del positions[sym]
            seen_exit.add(sym)

        entries.sort(key=lambda sig: (cap.slot_rank(day, sig['symbol']), sig['symbol']))
        for sig in entries:
            sym = sig['symbol']
            if sym in positions or len(positions) >= MAX_POSITIONS_PER_SLEEVE:
                continue
            bar = bar_map.get(sym)
            if bar is None:
                continue
            band = bands_by_date_symbol.get((day, sym), {})
            circuit = str(band.get('circuit') or 'NONE').upper()
            pit_ser = pit.get_pit_series(db, sym, day, as_of_date=day) or str(band.get('series') or 'EQ').upper()
            if circuit == 'UPPER' or pit_ser != 'EQ':
                continue
            open_px = float(bar['open'])
            qty = cap.integer_shares(open_px, TARGET_NOTIONAL_INR)
            if qty < 1:
                continue
            buy_haircut = estimate_exit_haircut_paise(qty=qty, mark_price=open_px, series='EQ', stress=stress_slippage)
            need_paise = qty * cap.price_paise(open_px) + buy_haircut
            if cash_paise < need_paise:
                continue
            cash_paise -= need_paise
            positions[sym] = {
                'symbol': sym,
                'qty': qty,
                'entry_price': open_px,
                'entry_date': day,
                'high_water': max(open_px, float(bar['close'])),
                'mark_price': float(bar['close']),
                'series': pit_ser,
                'pending_exit': False,
                'locked_days': 0,
            }

        # Update marks and high-water at close of day t
        marks = {}
        series_map = {}
        locked_map = {}
        for sym, pos in positions.items():
            bar = bar_map.get(sym)
            if bar is not None:
                cl = float(bar['close'])
                pos['mark_price'] = cl
                pos['high_water'] = max(pos['high_water'], cl)
            marks[sym] = pos['mark_price']
            series_map[sym] = pit.get_pit_series(db, sym, day, as_of_date=day) or pos.get('series', 'EQ')
            locked_map[sym] = pos.get('locked_days', 0)

        # At the end of the warm-start window, record starting equity E_0 net of exit haircut
        if day == ws_end:
            starting_equity_summary = value_starting_equity_net_of_haircut(
                cash_paise=cash_paise,
                open_positions=list(positions.values()),
                marks_by_symbol=marks,
                series_by_symbol=series_map,
                locked_days_by_symbol=locked_map,
                stress=stress_slippage,
            )

        # Value end-of-day total portfolio equity (unlevered total MTM including cash)
        marked_val = 0
        for sym, pos in positions.items():
            px = pos['mark_price']
            if pos.get('pending_exit') and pos.get('locked_days', 0) > 1:
                extra = min(99, pos['locked_days'] - 1)
                px = round(px * (100 - extra) / 100.0, 2)
            marked_val += pos['qty'] * cap.price_paise(px)
        eod_equity_paise = cash_paise + marked_val

        if in_eval:
            prev_eq = (
                starting_equity_summary['starting_equity_net_haircut_paise']
                if len(daily_records) == 0 and starting_equity_summary
                else (daily_records[-1]['equity_paise'] if daily_records else SLEEVE_CAPITAL_PAISE)
            )
            r_t = (eod_equity_paise - prev_eq) / float(prev_eq) if prev_eq > 0 else 0.0
            daily_records.append({
                'trade_date': day,
                'equity_paise': eod_equity_paise,
                'cash_paise': cash_paise,
                'open_positions': len(positions),
                'return': r_t,
            })

        # 3. Generate close-of-day t signals for next session open t+1 using strictly PIT data <= day
        pending_signals = []
        pit_u = pit.get_pit_prefilter_universe(db, namespace, day, as_of_date=day, require_eq_series=True)
        eligible_set = set(pit_u['eligible_symbols'])
        if not eligible_set and not pit_u['by_symbol']:
            # Archive PIT prefilter on the fly if not yet cached for this date
            pit.archive_daily_prefilter(db, namespace, day, stock_df, index_df, symbols=symbols, as_of_date=day)
            pit_u = pit.get_pit_prefilter_universe(db, namespace, day, as_of_date=day, require_eq_series=True)
            eligible_set = set(pit_u['eligible_symbols'])

        for sym in symbols:
            if sym not in eligible_set and sym not in positions:
                continue
            sym_hist = stock_df[(stock_df['symbol'] == sym) & (stock_df['trade_date'].astype(str) <= day)]
            if sym_hist.empty or str(sym_hist.iloc[-1]['trade_date']) != day:
                continue
            adj_hist = back_adjust_ohlc_pit(sym_hist, corp_actions, as_of_date=day)
            ind_df = evaluate_parameterized_strategy(s, adj_hist, validated_params)
            last_row = ind_df.iloc[-1]
            if sym in positions and bool(last_row.get('exit_condition', False)):
                pending_signals.append({'symbol': sym, 'side': 'SELL', 'signal_date': day, 'reason': 'daily_exit'})
            elif sym not in positions and sym in eligible_set and bool(last_row.get('entry_condition', False)):
                pending_signals.append({'symbol': sym, 'side': 'BUY', 'signal_date': day, 'reason': 'daily_entry'})

    return {
        'strategy': s,
        'params': validated_params,
        'warm_start_days': len(ws_dates),
        'eval_days': len(ev_dates),
        'starting_equity': starting_equity_summary,
        'daily_records': daily_records,
        'closed_trades': closed_trades,
        'open_positions': list(positions.values()),
    }
