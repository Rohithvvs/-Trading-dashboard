"""Read-only public reference data that feeds the freeze guards (plan A6/A7).

* NSE corporate actions -> paper_corporate_actions (split, bonus, cash dividend, manual-review kinds).
* NSE ASM list           -> paper_price_bands.surveillance = 'ASM'.
* NSE GSM list           -> paper_price_bands.surveillance = 'GSM' (when NSE serves it).
* Fyers symbol master    -> paper_price_bands.series = 'BE' / 'BZ' when an ISIN no longer trades as EQ.

Every source is fail-soft: a failed fetch is reported (never invented) and the engine keeps running.
No classification threshold is invented: dividends described as special/extraordinary are routed to
manual review because the freeze plan never defines "extraordinary".
"""
import csv, io, re
from datetime import date, datetime, timedelta
from fractions import Fraction
import requests

SOURCE_CA = 'NSE_CORPORATE_ACTIONS_API'
SOURCE_ASM = 'NSE_ASM_REPORT'
SOURCE_GSM = 'NSE_GSM_REPORT'
SOURCE_MASTER = 'FYERS_SYMBOL_MASTER'
MANUAL_WORDS = (('RIGHTS', r'\brights?\b'), ('DEMERGER', r'\bde-?merger\b'), ('MERGER', r'\bmerger\b|\bamalgamation\b|scheme of arrangement'))
_RS = r'(?:rs\.?|re\.?|inr|₹)\s*([0-9]+(?:\.[0-9]+)?)'


def nse_day(text):
    try:
        return datetime.strptime(str(text).strip(), '%d-%b-%Y').date().isoformat()
    except (TypeError, ValueError):
        return None


def classify(subject):
    """Return [(kind, ratio_num, ratio_den, cash_paise)] for one NSE subject line. [] means not a position event."""
    s = str(subject or '').lower()
    out = []
    for kind, pattern in MANUAL_WORDS:
        if re.search(pattern, s):
            out.append((kind, None, None, None))
    if out:
        return out[:1]
    if 'split' in s or 'sub-division' in s or 'sub division' in s:
        m = re.search(r'from\s*' + _RS + r'.*?to\s*' + _RS, s)
        if m and Fraction(m.group(2)) > 0:
            r = Fraction(m.group(1)) / Fraction(m.group(2))
            return [('SPLIT', r.numerator, r.denominator, None)] if r > 1 else [('SPLIT', None, None, None)]
        return [('SPLIT', None, None, None)]
    if 'bonus' in s:
        m = re.search(r'bonus\D*?(\d+)\s*:\s*(\d+)', s)
        if m and int(m.group(1)) > 0 and int(m.group(2)) > 0:
            # a:b bonus = a new shares for every b held, so r = (a+b)/b shares after per share before.
            r = Fraction(int(m.group(1)) + int(m.group(2)), int(m.group(2)))
            return [('BONUS', r.numerator, r.denominator, None)]
        return [('BONUS', None, None, None)]
    if 'dividend' in s:
        if 'special' in s or 'extraordinary' in s:
            return [('EXTRAORDINARY_DIVIDEND_REVIEW', None, None, None)]
        amounts = [Fraction(a) for a in re.findall(r'dividend[^/]*?' + _RS + r'\s*per\s*share', s)]
        if not amounts:
            return [('DIVIDEND_UNPARSED_REVIEW', None, None, None)]
        return [('CASH_DIVIDEND', None, None, int(round(sum(amounts) * 100)))]
    return []


def corporate_action_rows(rows, symbols, isins, start, end, now_iso):
    """Map NSE rows to paper_corporate_actions inserts for universe symbols with ex_date in [start, end]."""
    by_nse = {s.rsplit('-', 1)[0]: s for s in symbols}
    merged, skipped = {}, {'not_in_universe': 0, 'not_equity_series': 0, 'isin_differs_symbol_matched': 0, 'outside_window': 0, 'not_a_position_event': 0}
    for r in rows or []:
        sym = by_nse.get(str(r.get('symbol') or '').strip().upper())
        if not sym:
            skipped['not_in_universe'] += 1; continue
        if r.get('series') not in (None, '', '-', 'EQ', 'BE', 'BZ'):
            skipped['not_equity_series'] += 1; continue
        if isins.get(sym) and r.get('isin') and isins[sym] != r['isin']:
            # NSE corporate-action rows can carry a pre-face-value-change ISIN (e.g. CONCOR INE111A01017 vs current
            # INE111A01025). The NSE symbol is the match key; the difference is counted, not used to drop the event.
            skipped['isin_differs_symbol_matched'] += 1
        day = nse_day(r.get('exDate'))
        if not day or not start <= day <= end:
            skipped['outside_window'] += 1; continue
        events = classify(r.get('subject'))
        if not events:
            skipped['not_a_position_event'] += 1; continue
        for kind, num, den, cash in events:
            key = (sym, day, kind)
            if key in merged and kind == 'CASH_DIVIDEND':
                merged[key][5] += cash
            else:
                merged[key] = [sym, day, kind, num, den, cash, SOURCE_CA + ':' + str(r.get('subject'))[:160], now_iso]
    return [tuple(v) for v in merged.values()], skipped


def surveillance_rows(report, symbols, isins, label):
    by_nse = {s.rsplit('-', 1)[0]: s for s in symbols}
    found = {}
    if isinstance(report, dict):
        groups = [g.get('data', []) for g in report.values() if isinstance(g, dict)]
    elif isinstance(report, list):
        groups = [report]
    else:
        groups = []
    for group in groups:
        for r in group or []:
            sym = by_nse.get(str(r.get('symbol') or '').strip().upper())
            if sym:
                found[sym] = label
    return found


def series_from_master(text, symbols, isins):
    """ISIN -> series present in the Fyers NSE_CM master. A universe ISIN with BE/BZ and no EQ row is a transition."""
    series = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 10 or not row[9].startswith('NSE:'):
            continue
        isin, ticker = row[5].strip(), row[9]
        suffix = ticker.rsplit('-', 1)[-1] if '-' in ticker else ''
        series.setdefault(isin, set()).add(suffix)
    out = {}
    for sym in symbols:
        have = series.get(isins.get(sym) or '', set())
        if 'EQ' not in have and have & {'BE', 'BZ'}:
            out[sym] = 'BZ' if 'BZ' in have else 'BE'
    return out


def _get(url, timeout, agent, as_json=True):
    r = requests.get(url, timeout=timeout, headers={'User-Agent': agent, 'Accept': 'application/json,text/csv,*/*'})
    if r.status_code != 200:
        raise RuntimeError('http_' + str(r.status_code))
    return r.json() if as_json else r.text


def refresh(e, db, trade_day, fetch=None):
    """Fetch every source, write what parsed, and report errors per source. Paper data only."""
    cfg = e.CFG['reference_feeds']
    fetch = fetch or (lambda url, as_json=True: _get(url, cfg['timeout_seconds'], cfg['user_agent'], as_json))
    symbols = e.universe(); isins = e.ISINS; now_iso = e.now().isoformat(); day = str(trade_day)
    end = (date.fromisoformat(day) + timedelta(days=cfg['corporate_action_lookahead_days'])).isoformat()
    report = {'trade_day': day, 'sources': {}}
    try:
        rows, skipped = corporate_action_rows(fetch(cfg['nse_corporate_actions_url']), symbols, isins, day, end, now_iso)
        db.batch([('INSERT INTO paper_corporate_actions(symbol,ex_date,kind,ratio_num,ratio_den,cash_paise,source,recorded_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(symbol,ex_date,kind) DO UPDATE SET ratio_num=excluded.ratio_num,ratio_den=excluded.ratio_den,cash_paise=excluded.cash_paise,source=excluded.source,recorded_at=excluded.recorded_at', r) for r in rows])
        report['sources']['corporate_actions'] = {'status': 'ok', 'rows_written': len(rows), 'window': [day, end], 'skipped': skipped, 'kinds': sorted({r[2] for r in rows})}
    except Exception as ex:
        report['sources']['corporate_actions'] = {'status': 'unavailable', 'error': e.au.safe_error(ex)}
    flags = {}
    for name, url, label in (('asm', cfg['nse_asm_url'], 'ASM'), ('gsm', cfg['nse_gsm_url'], 'GSM')):
        try:
            found = surveillance_rows(fetch(url), symbols, isins, label)
            for sym, lab in found.items():
                flags.setdefault(sym, {})['surveillance'] = 'GSM' if 'GSM' in (lab, flags.get(sym, {}).get('surveillance')) else lab
            report['sources'][name] = {'status': 'ok', 'universe_symbols_flagged': len(found)}
        except Exception as ex:
            report['sources'][name] = {'status': 'unavailable', 'error': e.au.safe_error(ex)}
    try:
        moved = series_from_master(fetch(cfg['fyers_symbol_master_url'], as_json=False), symbols, isins)
        for sym, series in moved.items():
            flags.setdefault(sym, {})['series'] = series
        report['sources']['series'] = {'status': 'ok', 'universe_symbols_not_eq': len(moved)}
    except Exception as ex:
        report['sources']['series'] = {'status': 'unavailable', 'error': e.au.safe_error(ex)}
    statements = []
    for sym, f in sorted(flags.items()):
        source = '+'.join(k for k, ok in (('NSE_ASM_GSM', 'surveillance' in f), (SOURCE_MASTER, 'series' in f)) if ok)
        statements.append(('INSERT INTO paper_price_bands(symbol,trade_date,upper_price,lower_price,series,surveillance,fo_eligible,source) VALUES(?,?,NULL,NULL,?,?,0,?) ON CONFLICT(symbol,trade_date) DO UPDATE SET series=COALESCE(excluded.series,paper_price_bands.series),surveillance=COALESCE(excluded.surveillance,paper_price_bands.surveillance),source=excluded.source', (sym, day, f.get('series'), f.get('surveillance'), source)))
    db.batch(statements)
    report['guard_rows_written'] = len(statements)
    report['entry_blocked_symbols'] = sorted(flags)
    e.log('reference_feeds', **report)
    return report
