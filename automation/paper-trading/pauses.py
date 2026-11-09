"""Strategy and system pause rules.

Strategy pause uses the shadow book. System pause uses the capped book.
A strategy stays paused until a manual override. The freeze names hysteresis as
N new shadow trades and does not give N, so that path is not invented.
System reinstatement is recovery to within 3 percent of the pre-pause peak, or a manual override.
Peak resets on reinstatement.
"""
import math
import capital as cap

SLEEVE = cap.POLICY['sleeve_capital_inr'] * 100
MASTER = cap.POLICY['master_capital_inr'] * 100


def breaches(values, percent):
    """Return the peak that a later trough exceeds, or None. Exactly `percent` does not breach."""
    if not values:
        return None
    num, den = int(round(percent * 1000)), 1000
    peak, hit = values[0], None
    for value in values:
        if value > peak:
            peak = value
        elif peak > 0 and (peak - value) * den > peak * num:
            hit = peak
    return hit


def recovered(equity, peak, gap):
    if equity is None or peak is None or peak <= 0:
        return False
    keep = int(round((1 - gap) * 1000))
    return equity * 1000 >= peak * keep


def upper_bound(pnls, z):
    n = len(pnls)
    if n < 1:
        return None
    mean = sum(pnls) / n
    if n == 1:
        return mean
    var = sum((x - mean) ** 2 for x in pnls) / (n - 1)
    return mean + z * math.sqrt(var / n)


def _rows(rows, book, strategy, baseline):
    return [r for r in rows if r['book'] == book and int(r['strategy']) == strategy and str(r['day']) > baseline]


def _state_map(states):
    return {(s['scope'], int(s['strategy'])): s for s in states}


def _override(overrides, scope, strategy, paused_at):
    paused_at = paused_at or ''
    return any(o['scope'] == scope and int(o['strategy']) == strategy and o['action'] == 'reinstate' and str(o['recorded_at']) > paused_at for o in overrides)


def plan(closes, trades, states, overrides, day, now):
    """Return pause-row writes and decision notes. Does not touch the database."""
    policy = cap.POLICY
    z = policy['ucb_one_sided_z']
    window = policy['ucb_closed_trades']
    drawdown_only = set(policy['drawdown_only_strategies'])
    current = _state_map(states)
    writes, notes = [], []

    def emit(scope, strategy, paused, cause, peak, pre, baseline, paused_at, rule):
        writes.append({'scope': scope, 'strategy': strategy, 'paused': 1 if paused else 0, 'cause': cause, 'peak_paise': peak, 'pre_pause_peak_paise': pre, 'baseline_day': baseline or '', 'paused_at': paused_at, 'updated_at': now})
        notes.append({'scope': scope, 'strategy': strategy, 'cause': 'KILL_PAUSE' if paused else 'reinstated', 'rule': rule, 'paused': bool(paused)})

    for strategy in range(1, 8):
        state = current.get(('strategy', strategy), {})
        baseline = state.get('baseline_day') or ''
        values = [int(r['equity_paise']) for r in _rows(closes, 'shadow', strategy, baseline)]
        paused = bool(state.get('paused'))
        if paused and _override(overrides, 'strategy', strategy, state.get('paused_at')):
            peak = values[-1] if values else SLEEVE
            emit('strategy', strategy, False, None, peak, None, day, None, 'manual_override_reinstates_strategy')
            continue
        if paused:
            continue
        hit = breaches(values, policy['sleeve_pause_drawdown'])
        if hit is not None:
            emit('strategy', strategy, True, 'sleeve_drawdown_exceeds_10pct', hit, hit, baseline, now, 'sleeve_net_drawdown_exceeds_10pct')
            continue
        if strategy in drawdown_only:
            continue
        pnls = [int(t['net_pnl_paise']) for t in trades if t['book'] == 'shadow' and int(t['strategy']) == strategy and str(t['closed_at'])[:10] > baseline]
        last = pnls[-window:]
        if len(last) == window and upper_bound(last, z) < 0:
            peak = values[-1] if values else SLEEVE
            emit('strategy', strategy, True, 'ucb_net_average_trade_below_zero', peak, peak, baseline, now, 'ucb_of_30_net_trades_below_zero')

    state = current.get(('system', 0), {})
    baseline = state.get('baseline_day') or ''
    values = [int(r['equity_paise']) for r in _rows(closes, 'capped', 0, baseline)]
    paused = bool(state.get('paused'))
    latest = values[-1] if values else None
    back = recovered(latest, state.get('pre_pause_peak_paise'), policy['system_reinstatement_gap'])
    if paused and (_override(overrides, 'system', 0, state.get('paused_at')) or back):
        peak = latest if latest is not None else MASTER
        rule = 'system_recovered_within_3pct_of_pre_pause_peak' if back else 'manual_override_reinstates_system'
        emit('system', 0, False, None, peak, None, day, None, rule)
    elif not paused:
        hit = breaches(values, policy['system_pause_drawdown'])
        if hit is not None:
            emit('system', 0, True, 'system_drawdown_exceeds_8pct', hit, hit, baseline, now, 'master_net_drawdown_exceeds_8pct')
    return writes, notes


def _price_paise(symbol, marks, closes):
    if symbol in closes and closes[symbol]:
        return cap.price_paise(closes[symbol])
    if symbol in marks and marks[symbol]:
        return cap.price_paise(marks[symbol])
    return None


def record_equity(e, db, day):
    """Insert today's shadow and capped equity if that day is not already stored."""
    costs = {int(r['strategy']): int(r['n']) for r in db.query('SELECT strategy, COALESCE(SUM(net_cashflow_paise),0) AS n FROM paper_fill_costs WHERE namespace=? GROUP BY strategy', (e.NS,))}
    credits = {int(r['strategy']): int(r['n']) for r in db.query('SELECT strategy, COALESCE(SUM(amount_paise),0) AS n FROM paper_cash_credits WHERE namespace=? GROUP BY strategy', (e.NS,))}
    positions = db.query('SELECT strategy,symbol,qty,entry_price,mark_price FROM paper_positions WHERE namespace=? AND qty>0', (e.NS,))
    shadow_costs = {int(r['strategy']): int(r['n']) for r in db.query('SELECT strategy, COALESCE(SUM(net_cashflow_paise),0) AS n FROM paper_shadow_costs WHERE namespace=? GROUP BY strategy', (e.NS,))}
    shadows = db.query('SELECT strategy,symbol,qty,entry_price FROM paper_shadow_positions WHERE namespace=? AND qty>0', (e.NS,))
    symbols = {p['symbol'] for p in positions} | {p['symbol'] for p in shadows}
    close_rows = db.query(f"SELECT symbol,close FROM daily_ohlcv WHERE trade_date=? AND symbol IN ({','.join('?' for _ in symbols)})", (day, *symbols)) if symbols else []
    closes = {r['symbol']: r['close'] for r in close_rows}
    marks = {p['symbol']: p['mark_price'] or p['entry_price'] for p in positions}

    def value(rows, price_of):
        total = 0
        for row in rows:
            px = _price_paise(row['symbol'], {row['symbol']: price_of(row)}, closes)
            if px is None:
                px = cap.price_paise(row['entry_price'])
            total += int(row['qty']) * px
        return total

    capped, shadow = {}, {}
    for strategy in range(1, 8):
        held = [p for p in positions if int(p['strategy']) == strategy]
        capped[strategy] = SLEEVE + costs.get(strategy, 0) + credits.get(strategy, 0) + value(held, lambda p: p['mark_price'] or p['entry_price'])
        sh = [p for p in shadows if int(p['strategy']) == strategy]
        shadow[strategy] = SLEEVE + shadow_costs.get(strategy, 0) + value(sh, lambda p: p['entry_price'])
    master = sum(capped.values())
    statements = [('INSERT OR IGNORE INTO paper_equity_closes(namespace,book,strategy,day,equity_paise) VALUES(?,?,?,?,?)', (e.NS, 'capped', strategy, day, equity)) for strategy, equity in capped.items()]
    statements += [('INSERT OR IGNORE INTO paper_equity_closes(namespace,book,strategy,day,equity_paise) VALUES(?,?,?,?,?)', (e.NS, 'shadow', strategy, day, equity)) for strategy, equity in shadow.items()]
    statements.append(('INSERT OR IGNORE INTO paper_equity_closes(namespace,book,strategy,day,equity_paise) VALUES(?,?,?,?,?)', (e.NS, 'capped', 0, day, master)))
    db.batch(statements)
    return {'capped': capped, 'shadow': shadow, 'master': master}


def evaluate(e, db, day, force=False):
    day = str(day)
    if not force:
        seen = db.query("SELECT value FROM paper_meta WHERE namespace=? AND key='pause_day'", (e.NS,))
        if seen and seen[0]['value'] == day:
            return {'status': 'already'}
    record_equity(e, db, day)
    closes = db.query('SELECT book,strategy,day,equity_paise FROM paper_equity_closes WHERE namespace=? ORDER BY day', (e.NS,))
    trades = db.query('SELECT book,strategy,net_pnl_paise,closed_at FROM paper_closed_trades WHERE namespace=? ORDER BY closed_at', (e.NS,))
    states = db.query('SELECT * FROM paper_pause_state WHERE namespace=?', (e.NS,))
    overrides = db.query('SELECT scope,strategy,action,recorded_at FROM paper_pause_overrides WHERE namespace=?', (e.NS,))
    now = e.now().isoformat()
    writes, notes = plan(closes, trades, states, overrides, day, now)
    if writes:
        db.batch([('INSERT INTO paper_pause_state(namespace,scope,strategy,paused,cause,peak_paise,pre_pause_peak_paise,baseline_day,paused_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(namespace,scope,strategy) DO UPDATE SET paused=excluded.paused,cause=excluded.cause,peak_paise=excluded.peak_paise,pre_pause_peak_paise=excluded.pre_pause_peak_paise,baseline_day=excluded.baseline_day,paused_at=excluded.paused_at,updated_at=excluded.updated_at', (e.NS, w['scope'], w['strategy'], w['paused'], w['cause'], w['peak_paise'], w['pre_pause_peak_paise'], w['baseline_day'], w['paused_at'], w['updated_at'])) for w in writes])
    for note in notes:
        e.decide(db, {'id': e.stable_id('pause', e.NS, note['scope'], note['strategy'], day, note['rule']), 'strategy': note['strategy'] or None, 'symbol': None}, e.now(), 'HOLD', note['cause'], note['rule'], {'ex_date': day, 'scope': note['scope'], 'strategy': note['strategy'], 'paused': note['paused'], 'hysteresis_shadow_trades': None})
    db.batch([('INSERT INTO paper_meta(namespace,key,value) VALUES(?,?,?) ON CONFLICT(namespace,key) DO UPDATE SET value=excluded.value', (e.NS, 'pause_day', day))])
    return {'status': 'evaluated', 'changes': len(writes)}
