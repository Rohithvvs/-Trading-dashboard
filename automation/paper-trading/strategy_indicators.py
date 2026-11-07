# Frozen exact indicator functions from verified strategy scripts; execution is paper engine, not backtest.
import numpy as np
import pandas as pd

def strategy_2(g):
    h, l, c = [g[k].to_numpy(float) for k in ['high', 'low', 'close']]
    n = len(g)
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.r_[np.nan, c[:-1]]), np.abs(l - np.r_[np.nan, c[:-1]])))
    tr[0] = h[0] - l[0]
    atr = np.full(n, np.nan)
    upper = atr.copy()
    lower = atr.copy()
    line = atr.copy()
    direction = atr.copy()
    for i in range(n):
        if i < 9:
            continue
        atr[i] = np.mean(tr[:10]) if i == 9 else (atr[i - 1] * 9 + tr[i]) / 10
        bu = (h[i] + l[i]) / 2 + 3 * atr[i]
        bl = (h[i] + l[i]) / 2 - 3 * atr[i]
        if i == 9:
            upper[i] = bu
            lower[i] = bl
            direction[i] = 1
            line[i] = bu
            continue
        upper[i] = bu if bu < upper[i - 1] or c[i - 1] > upper[i - 1] else upper[i - 1]
        lower[i] = bl if bl > lower[i - 1] or c[i - 1] < lower[i - 1] else lower[i - 1]
        if line[i - 1] == upper[i - 1]:
            direction[i] = -1 if c[i] > upper[i] else 1
        else:
            direction[i] = 1 if c[i] < lower[i] else -1
        line[i] = lower[i] if direction[i] == -1 else upper[i]
    f = g.copy()
    f['atr10'] = atr
    f['final_upper'] = upper
    f['final_lower'] = lower
    f['supertrend'] = line
    f['direction'] = direction
    f['prior_direction'] = f.direction.shift()
    f['entry_condition'] = (f.prior_direction == 1) & (f.direction == -1) & (f.close > f.supertrend)
    f['exit_condition'] = (f.prior_direction == -1) & (f.direction == 1)
    return f

def strategy_3(g):
    f = g.copy()
    c = f.close.astype(float)
    d = c.diff().to_numpy()
    up = np.maximum(d, 0)
    down = np.maximum(-d, 0)
    n = len(c)
    ag = np.full(n, np.nan)
    al = ag.copy()
    if n > 14:
        ag[14] = up[1:15].mean()
        al[14] = down[1:15].mean()
        for i in range(15, n):
            ag[i] = (13 * ag[i - 1] + up[i]) / 14
            al[i] = (13 * al[i - 1] + down[i]) / 14
    with np.errstate(divide='ignore', invalid='ignore'):
        rsi = 100 - 100 / (1 + ag / al)
    rsi = np.where(al == 0, 100, rsi)
    rsi = np.where((ag == 0) & (al > 0), 0, rsi)
    f['rsi14'] = rsi
    f['sma200'] = c.rolling(200).mean()
    f['sma5'] = c.rolling(5).mean()
    f['entry_condition'] = (c > f.sma200) & (f.rsi14 < 40)
    f['exit_condition'] = (f.rsi14 > 60) | (c > f.sma5)
    return f

def strategy_4(g):
    f = g.copy()
    c = f.close.astype(float)
    f['ema20'] = c.ewm(span=20, adjust=False).mean()
    f['ema50'] = c.ewm(span=50, adjust=False).mean()
    f['prior_ema20'] = f.ema20.shift()
    f['prior_ema50'] = f.ema50.shift()
    f['sma200'] = c.rolling(200).mean()
    f['cross_up'] = (f.ema20 > f.ema50) & (f.prior_ema20 <= f.prior_ema50)
    f['cross_down'] = (f.ema20 < f.ema50) & (f.prior_ema20 >= f.prior_ema50)
    f['entry_condition'] = f.cross_up & (c > f.sma200)
    f['exit_condition'] = f.cross_down
    return f

def strategy_5(g):
    f = g.copy()
    c = f.close.astype(float)
    f['bb_middle'] = c.rolling(20).mean()
    f['std20'] = c.rolling(20).std(ddof=0)
    f['bb_lower'] = f.bb_middle - 2 * f.std20
    f['bb_upper'] = f.bb_middle + 2 * f.std20
    f['sma200'] = c.rolling(200).mean()
    f['warmup_complete'] = f.sma200.notna() & f.bb_lower.notna()
    f['passes_trend'] = c > f.sma200
    f['touches_lower_band'] = c <= f.bb_lower
    f['entry_condition'] = f.passes_trend & f.touches_lower_band
    f['exit_condition'] = c >= f.bb_middle
    return f

def strategy_6(g):
    f = g.copy()
    c = f.close.astype(float)
    f['ema12'] = c.ewm(span=12, adjust=False).mean()
    f['ema26'] = c.ewm(span=26, adjust=False).mean()
    f['macd'] = f.ema12 - f.ema26
    f['signal'] = f.macd.ewm(span=9, adjust=False).mean()
    f['histogram'] = f.macd - f.signal
    f['prior_macd'] = f.macd.shift()
    f['prior_signal'] = f.signal.shift()
    f['sma50'] = c.rolling(50).mean()
    f['warmup_complete'] = f.sma50.notna()
    f['passes_trend'] = c > f.sma50
    f['cross_up'] = (f.macd > f.signal) & (f.prior_macd <= f.prior_signal)
    f['cross_down'] = (f.macd < f.signal) & (f.prior_macd >= f.prior_signal)
    f['entry_condition'] = f.cross_up & f.passes_trend
    f['exit_condition'] = f.cross_down
    return f

def strategy_7(g):
    f = g.copy()
    f['high252'] = f.high.rolling(252).max()
    f['sma200'] = f.close.rolling(200).mean()
    f['sma50'] = f.close.rolling(50).mean()
    f['warmup_complete'] = f.high252.notna() & f.sma200.notna()
    f['passes_trend'] = f.close > f.sma200
    f['within10pct'] = f.close >= 0.9 * f.high252
    f['within5pct'] = f.close >= 0.95 * f.high252
    f['distance_below_high_pct'] = 100 * (1 - f.close / f.high252)
    f['entry_condition'] = f.passes_trend & f.within10pct
    f['exit_condition'] = f.close < f.sma50
    return f
