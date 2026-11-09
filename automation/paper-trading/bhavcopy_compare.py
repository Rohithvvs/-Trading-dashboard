"""Compare a feed session open with the NSE bhavcopy open.

The report is append-only and hash-chained. It does not place orders and it does not change fills.
A matching open is OPEN_MATCH. A different open is OFFICIAL_OPEN_DIFF. A missing side keeps its own cause.
"""
import csv, hashlib, json, sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

GENESIS = '0' * 64

def paise(value):
    if value is None or str(value).strip() == '':
        return None
    return int((Decimal(str(value).strip()) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

def symbol_key(row):
    """Classic bhavcopy uses SYMBOL and SERIES. UDiFF uses TckrSymb and SctySrs. Feed rows may already be RELIANCE-EQ."""
    raw = row.get('symbol') or row.get('TckrSymb') or row.get('SYMBOL')
    if raw is None or str(raw).strip() == '':
        return None
    sym = str(raw).strip().upper()
    if '-' in sym and not (row.get('SctySrs') or row.get('SERIES') or row.get('series')):
        return sym
    series = str(row.get('series') or row.get('SERIES') or row.get('SctySrs') or 'EQ').strip().upper()
    base = sym.split('-')[0]
    return f'{base}-{series}'

def open_of(row):
    for key in ('open', 'OPEN', 'OpnPric', 'feed_open', 'bhav_open'):
        if key in row and str(row[key]).strip() != '':
            return row[key]
    return None

def compare_rows(feed_rows, bhav_rows, trade_date):
    feed, bhav = {}, {}
    for row in feed_rows:
        key = symbol_key(row)
        if key:
            feed[key] = paise(open_of(row))
    for row in bhav_rows:
        key = symbol_key(row)
        if key:
            bhav[key] = paise(open_of(row))
    out = []
    for key in sorted(set(feed) | set(bhav)):
        left, right = feed.get(key), bhav.get(key)
        if left is None:
            cause = 'FEED_OPEN_MISSING'
        elif right is None:
            cause = 'BHAV_OPEN_MISSING'
        elif left == right:
            cause = 'OPEN_MATCH'
        else:
            cause = 'OFFICIAL_OPEN_DIFF'
        out.append({'trade_date': str(trade_date), 'symbol': key, 'feed_open_paise': left, 'bhav_open_paise': right, 'diff_paise': None if left is None or right is None else left - right, 'cause': cause})
    return out

def stable(row):
    return json.dumps(row, sort_keys=True, separators=(',', ':'))

def chain(rows, prev=GENESIS):
    chained = []
    for row in rows:
        entry = hashlib.sha256((prev + '\n' + stable(row)).encode()).hexdigest()
        chained.append({**row, 'prev_hash': prev, 'entry_hash': entry})
        prev = entry
    return chained

def read_jsonl(path):
    file = Path(path)
    if not file.exists():
        return []
    return [json.loads(line) for line in file.read_text().splitlines() if line.strip()]

def verify(rows):
    prev = GENESIS
    for row in rows:
        body = {k: v for k, v in row.items() if k not in ('prev_hash', 'entry_hash')}
        entry = hashlib.sha256((prev + '\n' + stable(body)).encode()).hexdigest()
        if row.get('prev_hash') != prev or row.get('entry_hash') != entry:
            return False
        prev = row['entry_hash']
    return True

def append_report(path, rows):
    existing = read_jsonl(path)
    prev = existing[-1]['entry_hash'] if existing else GENESIS
    chained = chain(rows, prev)
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open('a', encoding='utf-8') as out:
        for row in chained:
            out.write(stable(row) + '\n')
    return chained

def load_csv(path):
    with open(path, newline='', encoding='utf-8') as handle:
        return list(csv.DictReader(handle))

def main(argv):
    if len(argv) != 5:
        print('usage: bhavcopy_compare.py TRADE_DATE FEED.csv BHAV.csv REPORT.jsonl', file=sys.stderr)
        return 2
    trade_date, feed_path, bhav_path, report_path = argv[1:]
    rows = compare_rows(load_csv(feed_path), load_csv(bhav_path), trade_date)
    append_report(report_path, rows)
    counts = {}
    for row in rows:
        counts[row['cause']] = counts.get(row['cause'], 0) + 1
    print(json.dumps({'trade_date': trade_date, 'rows': len(rows), 'causes': counts, 'chain_ok': verify(read_jsonl(report_path))}))
    return 0

if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
