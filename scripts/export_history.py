"""Deterministic, read-only export of saved research. Never runs a strategy or touches credentials."""
import csv,json,pathlib,statistics,collections,math,hashlib
ROOT=pathlib.Path('/workspace/strategies'); OUT=pathlib.Path(__file__).resolve().parents[1]/'public/data/historical.json'
NAMES=['Donchian / Turtle','Supertrend','RSI Pullback','Dual MA','Bollinger Reversion','MACD Trend','52W Momentum']
def csvrows(p):
 with open(p,newline='') as h:return [{k:cast(v) for k,v in r.items()} for r in csv.DictReader(h)]
def cast(v):
 if v in ('True','true'):return True
 if v in ('False','false'):return False
 if v in ('','nan','NaN','None'):return None
 try:
  n=float(v);return int(n) if n.is_integer() else n if math.isfinite(n) else None
 except (ValueError,TypeError):return v
def stats(rs):
 vals=[r['return_pct'] for r in rs];return {'closed':len(vals),'winRate':sum(v>0 for v in vals)/len(vals)*100 if vals else None,'mean':statistics.mean(vals) if vals else None,'median':statistics.median(vals) if vals else None}
def v(r,k):return r.get(k) if isinstance(r.get(k),(int,float)) else None
def cmp(r,a,b,op):
 x=v(r,a);y=v(r,b);return x is not None and y is not None and op(x,y)
def conditions(i,r):
 warm=(r.get('bars') or 0)>=[21,11,200,200,200,50,252][i-1]
 gt=lambda a,b:a>b
 if i==1:rest=[('Close > prior 20-bar high',cmp(r,'close','breakout20',gt))]
 elif i==2:rest=[('Actual red → green flip',r.get('prior_direction')==1 and r.get('direction')==-1),('Close > Supertrend',cmp(r,'close','supertrend',gt))]
 elif i==3:rest=[('Close > SMA200',cmp(r,'close','sma200',gt)),('Wilder RSI14 < 40',v(r,'rsi14') is not None and r['rsi14']<40)]
 elif i==4:rest=[('Close > SMA200',cmp(r,'close','sma200',gt)),('Actual EMA20 / EMA50 cross up',cmp(r,'ema20','ema50',gt) and cmp(r,'prior_ema20','prior_ema50',lambda a,b:a<=b))]
 elif i==5:rest=[('Close > SMA200',cmp(r,'close','sma200',gt)),('Close ≤ lower Bollinger band',cmp(r,'close','bb_lower',lambda a,b:a<=b))]
 elif i==6:rest=[('Close > SMA50',cmp(r,'close','sma50',gt)),('Actual MACD / signal cross up',cmp(r,'macd','signal',gt) and cmp(r,'prior_macd','prior_signal',lambda a,b:a<=b))]
 else:rest=[('Close > SMA200',cmp(r,'close','sma200',gt)),('Close ≥ 90% of 252-bar high',v(r,'close') is not None and v(r,'high252') is not None and r['close']>=.9*r['high252'])]
 return [('Full indicator warmup',warm)]+rest
comparison=csvrows(ROOT/'overlap_analysis/2026-11-07/seven_strategy_comparison.csv')
matrix=csvrows(ROOT/'overlap_analysis/2026-11-07/membership_matrix_all751.csv');assert len(matrix)==751
strategies=[];verification=[]
for i,p in enumerate(sorted(ROOT.glob('0*/2026-11-07_run')),1):
 summary=json.load(open(p/'summary.json'));config=json.load(open(p/'config_rules.json'));screens=csvrows(p/'screen_all.csv');qual=csvrows(p/'today_qualifiers.csv');closed=csvrows(p/'closed_trades.csv');opened=csvrows(p/'open_positions.csv');m=comparison[i-1]
 m['pending_exit_orders']=sum(bool(r.get('position_at_latest_close')) and bool(r.get('exit_condition')) for r in screens)
 metrics=stats(closed);assert metrics['closed']==m['closed_trades'];assert math.isclose(metrics['mean'],m['mean_gross_return_pct'],abs_tol=1e-10);assert math.isclose(metrics['median'],m['median_gross_return_pct'],abs_tol=1e-10);assert len(qual)==m['latest_condition_qualifiers'];assert len(opened)==m['open_positions'];assert m['filled_entries']==len(closed)+len(opened)
 bysymbol=collections.defaultdict(list);years=collections.defaultdict(list);months=collections.defaultdict(list)
 for r in closed:bysymbol[r['symbol']].append(r);years[str(r['exit_date'])[:4]].append(r);months[str(r['exit_date'])[:7]].append(r)
 perstock=[{'symbol':symbol,**stats(bysymbol[symbol]),'best':max((r['return_pct'] for r in bysymbol[symbol]),default=None),'worst':min((r['return_pct'] for r in bysymbol[symbol]),default=None),'open':sum(r['symbol']==symbol for r in opened),'qualifies':any(r['symbol']==symbol for r in qual)} for symbol in sorted({r['symbol'] for r in screens})]
 screenmap={r['symbol']:r for r in screens};full=[]
 for univ in matrix:
  r=screenmap.get(univ['symbol']);coverage=univ['coverage'];item={'symbol':univ['symbol'],'coverage':coverage,'date':r.get('date') if r else None,'values':r or {},'qualifies':bool(r and r.get('entry_condition')),'fresh':bool(r and r.get('fresh_entry_signal')),'held':bool(r and r.get('position_at_latest_close'))}
  if coverage!='current':item.update(status=coverage,failed=[coverage.capitalize()+' coverage'],flags={})
  else:
   tests=conditions(i,r);flags={key:(ok if tests[0][1] or j==0 else None) for j,(key,ok) in enumerate(tests)};passed=all(flags.values());assert passed==item['qualifies'],(i,item['symbol'],tests)
   item.update(status='qualifies' if passed else 'insufficient history' if not tests[0][1] else 'condition failed',failed=[label for label,ok in tests if not ok] if tests[0][1] else ['Full indicator warmup'],flags=flags)
  full.append(item)
 funnel=[{'stage':'Exact universe','entering':751,'passed':751,'failed':0},{'stage':'Has history','entering':751,'passed':699,'failed':52},{'stage':'Current through 6 Nov','entering':699,'passed':692,'failed':7}];cohort=[r for r in full if r['coverage']=='current']
 for label in conditions(i,screens[0]):
  stage=label[0];nextcohort=[r for r in cohort if r['flags'][stage]];funnel.append({'stage':stage,'entering':len(cohort),'passed':len(nextcohort),'failed':len(cohort)-len(nextcohort)});cohort=nextcohort
 assert len(cohort)==len(qual)
 ordered=sorted(closed,key=lambda r:r['return_pct']);top=ordered[-5:][::-1];bottom=ordered[:5]
 for r in top+bottom:r['dataSensitive']=abs(r['return_pct'])>=100 or r['entry_price']<=0 or r['exit_price']<=0
 strategies.append({'id':i,'name':NAMES[i-1],'source':p.parent.name+'/2026-11-07_run','metrics':m,'rules':config,'qualifiers':qual,'screens':full,'funnel':funnel,'top':top,'bottom':bottom,'perStock':perstock,'yearly':[{'period':k,**stats(rs)} for k,rs in sorted(years.items())],'monthly':[{'period':k,**stats(rs)} for k,rs in sorted(months.items())]})
 verification.append({'strategy':i,'closed':len(closed),'qualifiers':len(qual),'screenRows':len(full),'checks':'counts, arithmetic, filled=closed+open, all latest flags and ordered funnel reconciled'})
result={'asOf':'2026-11-06','generatedOn':'2026-11-07','coverage':{'universe':751,'current':692,'missing':52,'stale':7},'strategies':strategies,'overlap':{'rows':csvrows(ROOT/'overlap_analysis/2026-11-07/aggregate_per_stock.csv'),'matrix':matrix,'performance':csvrows(ROOT/'overlap_analysis/2026-11-07/matched_stock_strategy_performance.csv'),'exactCounts':{str(n):sum(r['membership_count']==n for r in matrix) for n in range(1,8)}},'verification':verification,'caveats':['Historical closed-trade arithmetic statistics, not portfolio returns. Open trades excluded. No equal-capital sizing, compounding, equity curve, CAGR, or portfolio drawdown.','Gross zero costs; present-day universe survivorship bias; mixed-source corporate-action adjustments and missing sessions remain unverified. Extreme returns are data-sensitive, not recommendations.','Two zero-OHLC bars on 18 Jun 2026 (BAJAJ-AUTO and NAM-INDIA) were excluded only in Strategy 7. Earlier six reports remain unchanged. Strategy 3 includes an invalid BAJAJ-AUTO zero-price exit (−100%). Historical comparison is provisional.','Overlap membership uses all entry-condition qualifiers, including already-held stocks; not all fresh orders. No stock qualifies in 4, 5, 6 or 7 strategies.','Year/month statistics group closed trades by exit date; no closed observations means unavailable, not zero. Overlapping trades are not independent.']}
OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(result,separators=(',',':'),allow_nan=False));pathlib.Path('historical-verification.json').write_text(json.dumps({'sourceDate':result['asOf'],'checks':verification,'sha256':hashlib.sha256(OUT.read_bytes()).hexdigest()},indent=2));print('Verified seven preserved reports; historical JSON bytes:',OUT.stat().st_size)
