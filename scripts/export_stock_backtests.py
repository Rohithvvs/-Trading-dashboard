"""Read-only deterministic detail export. No indicators/strategies rerun, no database access."""
import pathlib,json,csv,math,collections,hashlib
ROOT=pathlib.Path('/workspace/strategies');BASE=pathlib.Path(__file__).resolve().parents[1];history=json.load(open(BASE/'public/data/historical.json'));companies={}
with open('/workspace/sahil-fyers-turso/universe.csv') as h:
 for r in csv.DictReader(h):companies[r['Symbol']+'-'+r['Series']]={'name':r['Company Name'],'industry':r['Industry']}
def num(v):
 try:
  n=float(v);return n if math.isfinite(n) else None
 except (ValueError,TypeError):return None
catalog={'asOf':history['asOf'],'coverage':history['coverage'],'caveats':history['caveats'],'strategies':[]};checks=[]
for s in history['strategies']:
 p=ROOT/s['source'];bysymbol=collections.defaultdict(list)
 with open(p/'closed_trades.csv') as h:
  for r in csv.DictReader(h):
   bysymbol[r['symbol']].append({k:(num(r[k]) if k in ['entry_price','exit_price','return_pct','bars_held'] else r[k]) for k in ['symbol','signal_date','entry_date','entry_price','exit_date','exit_price','return_pct','bars_held']})
 screens={r['symbol']:r for r in s['screens']};qual=[]
 for q in s['qualifiers']:
  sym=q['symbol'];screen=screens[sym];assert screen['qualifies'] and all(screen['flags'].values());info=companies[sym];trades=sorted(bysymbol[sym],key=lambda r:(r['exit_date'],r['entry_date']))
  issues=[];last=None
  for t in trades:
   t['calendar_days']=(__import__('datetime').date.fromisoformat(t['exit_date'])-__import__('datetime').date.fromisoformat(t['entry_date'])).days
   t['dataSensitive']=t['return_pct'] is None or abs(t['return_pct'])>=100 or (t['entry_price'] or 0)<=0 or (t['exit_price'] or 0)<=0
   if t['dataSensitive']:issues.append({'entry':t['entry_date'],'exit':t['exit_date'],'return':t['return_pct'],'reason':'unverified extreme or invalid-price historical trade'})
   if last and t['entry_date']<last:issues.append({'entry':t['entry_date'],'reason':'overlapping closed trades; normalized index must be unavailable'})
   last=t['exit_date']
  item={'symbol':sym,**info,'date':q['date'],'close':q['close'],'held':q['position_at_latest_close'],'fresh':q['fresh_entry_signal'],'values':q,'checks':screen['flags'],'bars':q['bars']};qual.append(item)
  payload={'asOf':history['asOf'],'strategyId':s['id'],'strategyName':s['name'],'stock':item,'rules':s['rules'],'closedTrades':trades,'issues':issues,'source':s['source']+'/closed_trades.csv','caveats':history['caveats']}
  dest=BASE/'public/data/stock-backtests'/str(s['id']);dest.mkdir(parents=True,exist_ok=True);(dest/(sym+'.json')).write_text(json.dumps(payload,separators=(',',':'),allow_nan=False))
  assert len(trades)==next((r['closed'] for r in s['perStock'] if r['symbol']==sym),0)
 catalog['strategies'].append({'id':s['id'],'name':s['name'],'qualifierCount':len(qual),'qualifiers':qual,'rules':s['rules'],'historicalMetrics':s['metrics']})
 checks.append({'strategy':s['id'],'qualifiers':len(qual),'detailFiles':len(qual),'tradeRows':sum(len(bysymbol[q['symbol']]) for q in s['qualifiers'])})
assert [c['qualifiers'] for c in checks]==[49,19,19,7,6,7,89]
(BASE/'public/data/strategy-catalog.json').write_text(json.dumps(catalog,separators=(',',':'),allow_nan=False))
(BASE/'stock-backtest-verification.json').write_text(json.dumps({'asOf':history['asOf'],'checks':checks,'totalFiles':sum(c['detailFiles'] for c in checks),'catalogSha256':hashlib.sha256((BASE/'public/data/strategy-catalog.json').read_bytes()).hexdigest()},indent=2))
print(json.dumps({'asOf':history['asOf'],'checks':checks,'catalogBytes':(BASE/'public/data/strategy-catalog.json').stat().st_size}))
