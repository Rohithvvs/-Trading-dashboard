"""Repair official completed daily bars; never orders, valid-bar overwrites or fills."""
import json,math,time
from pathlib import Path
SCHEMA="CREATE TABLE IF NOT EXISTS paper_history_gap_checks(namespace TEXT NOT NULL,symbol TEXT NOT NULL,trade_date TEXT NOT NULL,checked_at TEXT NOT NULL,outcome TEXT NOT NULL,retry_after TEXT NOT NULL,details_json TEXT NOT NULL,PRIMARY KEY(namespace,symbol,trade_date))"
def ranges(days,e):
 days=sorted(days);out=[]
 while days:
  start=e.date.fromisoformat(days[0]);end=min(e.date.fromisoformat(days[-1]),start+e.timedelta(days=364));out.append((start,end));days=[d for d in days if d>str(end)]
 return out

def repair(e,db,api,target,budget=20,deadline_seconds=240,progress=None):
 db.batch([(SCHEMA,())]);t=e.now();start=time.monotonic();bench=e.pf.benchmark(e,db,target);dates=sorted(bench.trade_date.tolist())[-253:] if not bench.empty else []
 if not dates or dates[-1]!=str(target):return {'status':'benchmark_unavailable','requests':0}
 syms=e.universe();presence={s:set() for s in syms};earliest={r['symbol']:r['first'] for r in db.query('SELECT symbol,MIN(trade_date) first FROM daily_ohlcv GROUP BY symbol')}
 for i in range(0,len(syms),50):
  part=syms[i:i+50]
  for r in db.query('SELECT symbol,trade_date FROM daily_ohlcv WHERE symbol IN ('+','.join('?'*len(part))+') AND trade_date>=? AND trade_date<=?',part+[dates[0],str(target)]):presence[r['symbol']].add(r['trade_date'])
 invalid={(r['symbol'],r['trade_date']):r for r in db.query('SELECT symbol,trade_date,open,high,low,close,volume,source,loaded_at FROM daily_ohlcv WHERE trade_date>=? AND trade_date<=? AND (open<=0 OR high<=0 OR low<=0 OR close<=0 OR high<MAX(open,close,low) OR low>MIN(open,close,high))',(dates[0],str(target))) if r['symbol'] in presence}
 for (sym,day) in invalid:presence[sym].discard(day)
 checks={(r['symbol'],r['trade_date']):r for r in db.query('SELECT symbol,trade_date,outcome,retry_after FROM paper_history_gap_checks WHERE namespace=? AND trade_date>=? AND trade_date<=?',(e.NS,dates[0],str(target)))}
 missing={s:sorted(set(dates)-presence[s]) for s in syms};todo={s:[d for d in days if (s,d) not in checks or checks[s,d]['retry_after']<=t.isoformat()] for s,days in missing.items()}
 # Repair established-stock internal gaps first, then possible short-history names.
 order=sorted(syms,key=lambda s:(earliest.get(s,'9999')>dates[0],-sum(d>=dates[-200] for d in todo[s]),s))
 report={'status':'running','target':str(target),'benchmark':e.pf.POLICY['benchmark'],'eligible_symbols':len(syms),'symbols_with_missing':sum(bool(x) for x in missing.values()),'missing_required_bars_before':sum(map(len,missing.values())),'requests':0,'symbols_requested':0,'provider_rows':0,'accepted_missing_rows':0,'corrected_invalid_rows':0,'rejected_rows':0,'no_provider_bar':0,'errors':[],'short_history_evidence':[],'budget':budget,'execution_calendar_unchanged':True,'writes':'Missing OHLC inserts / audited invalid-only corrections and repair checkpoints; never valid-bar overwrite'}
 statements=[];consecutive_errors=0
 def flush():
  nonlocal statements
  if statements:db.batch(statements);statements=[]
  if progress:
   p=Path(progress);tmp=p.with_suffix('.tmp');tmp.write_text(e.js(report));tmp.replace(p)
 for sym in order:
  if not todo[sym]:continue
  requested_symbol=False;returned_dates=set()
  for begin,end in ranges(todo[sym],e):
   if report['requests']>=budget or time.monotonic()-start>deadline_seconds:report['status']='bounded_budget_exhausted';flush();return report
   wanted={d for d in todo[sym] if str(begin)<=d<=str(end)};report['requests']+=1;requested_symbol=True
   try:candles=api.history(sym,begin,end)
   except RuntimeError as error:
    reason=str(error);safe=reason if reason.startswith(('market_data_','auth_','token_refresh')) and len(reason)<90 else 'history_request_failed';report['errors'].append({'symbol':sym,'reason':safe})
    if reason in ['market_data_error_-300','market_data_error_300']:
     for d in wanted:statements.append(('INSERT OR REPLACE INTO paper_history_gap_checks VALUES(?,?,?,?,?,?,?)',(e.NS,sym,d,e.now().isoformat(),'PROVIDER_REJECTED_RANGE',(e.now()+e.timedelta(days=7)).isoformat(),e.js({'reason':safe,'range_from':str(begin),'range_to':str(end),'not_assumed_IPO':True}))))
     flush();continue
    consecutive_errors+=1
    for d in wanted:statements.append(('INSERT OR REPLACE INTO paper_history_gap_checks VALUES(?,?,?,?,?,?,?)',(e.NS,sym,d,e.now().isoformat(),'TRANSIENT_ERROR',(e.now()+e.timedelta(hours=1)).isoformat(),e.js({'reason':safe}))))
    if reason.startswith(('auth_','token_refresh')) or consecutive_errors>=3:report['status']='paused_provider_failure';flush();return report
    continue
   consecutive_errors=0;accepted=set();report['provider_rows']+=len(candles)
   for c in candles:
    try:
     stamp,o,h,l,cl,v=c[:6];day=e.datetime.fromtimestamp(float(stamp),e.IST).date().isoformat()
     valid=day in wanted and day<=str(target) and all(math.isfinite(float(x)) and float(x)>0 for x in [o,h,l,cl]) and h>=max(o,l,cl) and l<=min(o,h,cl) and math.isfinite(float(v)) and v>=0
    except (ValueError,TypeError,OverflowError):valid=False;day=None
    if day in set(dates) and str(begin)<=day<=str(end):returned_dates.add(day)
    if not valid:
     # Existing candles returned inside the requested range are neither overwritten nor rejected as bad data.
     if day not in presence[sym]:report['rejected_rows']+=1
     continue
    if day in accepted:continue
    accepted.add(day);presence[sym].add(day);report['accepted_missing_rows']+=1;report['corrected_invalid_rows']+=int((sym,day) in invalid)
    statements.append(('INSERT OR IGNORE INTO daily_ohlcv(trade_date,symbol,open,high,low,close,volume,turnover,source,loaded_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(trade_date,symbol) DO UPDATE SET open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,volume=excluded.volume,turnover=excluded.turnover,source=excluded.source,loaded_at=excluded.loaded_at WHERE daily_ohlcv.open<=0 OR daily_ohlcv.high<=0 OR daily_ohlcv.low<=0 OR daily_ohlcv.close<=0 OR daily_ohlcv.high<MAX(daily_ohlcv.open,daily_ohlcv.close,daily_ohlcv.low) OR daily_ohlcv.low>MIN(daily_ohlcv.open,daily_ohlcv.close,daily_ohlcv.high)',(day,sym,o,h,l,cl,v,float(cl)*float(v),'FYERS_VERIFIED_GAP_REPAIR',e.now().isoformat())))
   for d in wanted:
    outcome='FILLED' if d in accepted else 'NO_PROVIDER_BAR';report['no_provider_bar']+=int(outcome!='FILLED');delay=7 if e.date.fromisoformat(d)<target-e.timedelta(days=30) else 1
    statements.append(('INSERT OR REPLACE INTO paper_history_gap_checks VALUES(?,?,?,?,?,?,?)',(e.NS,sym,d,e.now().isoformat(),outcome,(e.now()+e.timedelta(days=delay)).isoformat(),e.js({'range_from':str(begin),'range_to':str(end),'source':'FYERS_HISTORY','symbol':'NSE:'+sym,'existing_earliest':earliest.get(sym),'no_forward_fill':True,'invalid_original_before_image':invalid.get((sym,d))}))))
  if requested_symbol:
   report['symbols_requested']+=1
   if earliest.get(sym,'9999')>dates[0]:report['short_history_evidence'].append({'symbol':sym,'existing_earliest':earliest.get(sym),'provider_earliest_in_requested_window':min(returned_dates) if returned_dates else None,'classification':'insufficient_available_history_not_verified_IPO' if not returned_dates or min(returned_dates)>dates[0] else 'recoverable_older_history'})
   if report['symbols_requested']%5==0:flush()
 report['status']='complete';report['missing_required_bars_after']=sum(len(set(dates)-x) for x in presence.values());flush();return report
