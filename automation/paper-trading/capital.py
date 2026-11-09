"""Freeze-version capital policy. Share rounding, the 9-position sleeve, and the 3-strategy ISIN cap are enforced."""
import hashlib, json, math, re
from pathlib import Path

POLICY = json.loads((Path(__file__).resolve().parent / 'capital_policy.json').read_text())
_PRICE = re.compile(r'^\d+(\.\d{1,2})?$')

def assert_freeze(policy=None):
    p = POLICY if policy is None else policy
    if p.get('version') != 'freeze_capital_v1':
        raise SystemExit('FREEZE_CAPITAL_POLICY_REQUIRED')
    if p.get('master_capital_inr') != 3500000 or p.get('sleeve_capital_inr') != 500000:
        raise SystemExit('FREEZE_CAPITAL_POLICY_REQUIRED')
    if p.get('strategy_count') != 7 or p['sleeve_capital_inr'] * p['strategy_count'] != p['master_capital_inr']:
        raise SystemExit('FREEZE_CAPITAL_POLICY_REQUIRED')
    if p.get('target_notional_inr') != 50000 or p.get('max_positions_per_sleeve') != 9 or p.get('max_strategies_per_isin') != 3:
        raise SystemExit('FREEZE_CAPITAL_POLICY_REQUIRED')
    if p.get('zero_share_cause') != 'UNAFFORDABLE_ZERO_SHARES' or p.get('sleeve_slot_cause') != 'SLEEVE_SLOT_FULL' or p.get('isin_cap_cause') != 'ISIN_CAP' or p.get('sleeve_cash_cause') != 'INSUFFICIENT_CASH':
        raise SystemExit('FREEZE_CAPITAL_POLICY_REQUIRED')
    if p.get('slot_order_seed') != 'freeze_capital_v1':
        raise SystemExit('FREEZE_CAPITAL_POLICY_REQUIRED')
    # 9 x ₹50,000 = ₹4,50,000, which leaves ₹50,000 of the ₹5,00,000 sleeve for fees and slippage.
    if p['max_positions_per_sleeve'] * p['target_notional_inr'] >= p['sleeve_capital_inr']:
        raise SystemExit('FREEZE_CAPITAL_POLICY_REQUIRED')
    enforced = p.get('enforced', [])
    if any(item not in enforced for item in ('integer_share_rounding', 'sleeve_slot_limit', 'isin_cap', 'sleeve_cash', 'shadow_ledger', 'adv_filter_placeholder', 'adv_participation_cap')):
        raise SystemExit('FREEZE_CAPITAL_POLICY_REQUIRED')
    # ₹10 crore is the placeholder floor. It is not a reviewed freeze until the funnel report is reviewed.
    if p.get('adv_floor_inr') != 100_000_000 or p.get('adv_lookback_sessions') != 20 or p.get('adv_lag_sessions') != 1:
        raise SystemExit('FREEZE_CAPITAL_POLICY_REQUIRED')
    if p.get('adv_filter_cause') != 'ADV_FILTER_SKIP' or p.get('adv_floor_review') != 'pending_funnel_report':
        raise SystemExit('FREEZE_CAPITAL_POLICY_REQUIRED')
    if p.get('participation_rate') != 0.005 or p.get('participation_cause') != 'ADV_PARTICIPATION_CAP':
        raise SystemExit('FREEZE_CAPITAL_POLICY_REQUIRED')
    return p

def slot_rank(session_date, symbol):
    """Stable order for competing entries: sha256(session date, symbol, fixed seed)."""
    day = str(session_date)
    if not isinstance(symbol, str) or not symbol:
        raise ValueError('slot_symbol')
    digest = hashlib.sha256(f'{day}|{symbol}|{POLICY["slot_order_seed"]}'.encode()).hexdigest()
    return int(digest[:16], 16)

def price_paise(fill_price):
    """Paise exactly as fees.mjs accepts: a positive price with at most two decimal places."""
    if isinstance(fill_price, bool) or isinstance(fill_price, (bytes, bytearray)):
        raise ValueError('price_requires_positive_paise')
    if isinstance(fill_price, float):
        if not math.isfinite(fill_price):
            raise ValueError('price_requires_positive_paise')
        text = json.dumps(fill_price)
        if text.endswith('.0'):
            text = text[:-2]
    elif isinstance(fill_price, int):
        text = str(fill_price)
    else:
        text = str(fill_price).strip()
    if not _PRICE.fullmatch(text):
        raise ValueError('price_requires_positive_paise')
    whole, _, frac = text.partition('.')
    paise = int(whole) * 100 + int((frac + '00')[:2])
    if paise <= 0:
        raise ValueError('price_requires_positive_paise')
    return paise

def integer_shares(fill_price, target_notional_inr=None):
    """floor(target notional / fill price). Zero means the order cannot buy one share."""
    target = POLICY['target_notional_inr'] if target_notional_inr is None else target_notional_inr
    if isinstance(target, bool) or not isinstance(target, int) or target <= 0:
        raise ValueError('target_notional')
    return (target * 100) // price_paise(fill_price)

assert_freeze()
