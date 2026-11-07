import {createClient} from '@libsql/client/web';
export const NAMESPACE='paper_v1';
export const IST='Asia/Kolkata';
export function istDay(value=new Date()){return new Intl.DateTimeFormat('en-CA',{timeZone:IST,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));}
export function numeric(value){if(value===null||value===undefined||value==='')return null;const n=Number(value);return Number.isFinite(n)?n:null;}
export function ageSeconds(value,now=Date.now()){const d=Date.parse(value);return Number.isFinite(d)?(now-d)/1000:null;}
export function marketState(now=new Date()){
 const day=istDay(now),time=new Intl.DateTimeFormat('en-GB',{timeZone:IST,hour:'2-digit',minute:'2-digit',hour12:false}).format(now),week=new Intl.DateTimeFormat('en-US',{timeZone:IST,weekday:'short'}).format(now);
 if(day<'2026-11-01'||day>'2026-12-31')return {open:false,label:'Calendar review required',calendarValidThrough:'2026-12-31'};
 const session=day==='2026-11-08'?['14:20','15:15']:['09:15','15:30'];const trading=day==='2026-11-08'||(!['Sat','Sun'].includes(week)&&!['2026-11-10','2026-11-24','2026-12-25'].includes(day));
 return {open:trading&&time>=session[0]&&time<session[1],label:trading&&time>=session[0]&&time<session[1]?'NSE session open':'NSE session closed',calendarValidThrough:'2026-12-31'};
}
export function positionView(row,now=Date.now()){
 const qty=numeric(row.qty),entry=numeric(row.entry_price),mark=numeric(row.mark_price),age=ageSeconds(row.mark_at,now);
 const valid=mark!==null&&mark>0;
 return {...row,qty,entry_price:entry,mark_price:valid?mark:null,mark_age_seconds:age,mark_stale:!valid||age===null||age>60||age< -5,unrealized_pnl:valid&&qty!==null&&entry!==null?(mark-entry)*qty:null};
}
export function publicRows(rows){return rows.map(row=>{const r={...row};if('reason' in r){const known=['daily_entry','observed_LTP_below_close_highwater_stop','market_closed_or_unverified','provider_quote_error','nonpositive_or_missing_price','missing_exchange_timestamp','stale_or_future_quote','quote_outside_verified_session','fresh'];r.reason=known.includes(r.reason)?r.reason:/^daily_exit:\d{4}-\d{2}-\d{2}T[0-9:.+Z-]{8,40}$/.test(r.reason)?r.reason:'recorded_event';}if('status' in r&&!['pending','filled','ignored_state','ignored_stale_position','expired','closed','ok','failed','success','noop'].includes(r.status))r.status='recorded';if('kind' in r&&!['monitor','scan','bootstrap','probe','init','pnl','status'].includes(r.kind))r.kind='engine_run';if('source' in r)r.source=r.source==='FYERS_QUOTES'?'FYERS_QUOTES':'market_data';return r;});}
export function parseOptions(query={}){
 const view=query.view??'overview';if(!['overview','fills','positions','signals','runs','quotes'].includes(view))throw new Error('BAD_REQUEST');
 const integer=(v,def,max)=>{const n=v===undefined?def:Number(v);if(!Number.isInteger(n)||n<1||n>max)throw new Error('BAD_REQUEST');return n;};
 const page=integer(query.page,1,10000),limit=integer(query.limit,25,100);
 const strategy=query.strategy===undefined||query.strategy===''?null:integer(query.strategy,1,7);
 const scope=query.scope??'all';if(!['all','today'].includes(scope))throw new Error('BAD_REQUEST');
 const allowed=new Set(['view','page','limit','strategy','scope']);if(Object.keys(query).some(k=>!allowed.has(k)))throw new Error('BAD_REQUEST');
 return {view,page,limit,strategy,scope};
}
let client;
function getClient(){
 if(process.env.PAPER_NAMESPACE&&process.env.PAPER_NAMESPACE!==NAMESPACE)throw new Error('CONFIGURATION');
 const url=process.env.TURSO_DATABASE_URL,authToken=process.env.TURSO_AUTH_TOKEN;
 if(!url||!authToken)throw new Error('CONFIGURATION');
 if(!/^libsql:\/\/|^https:\/\//.test(url))throw new Error('CONFIGURATION');
 return client??=createClient({url,authToken});
}
// Only fixed SELECT statements below. No client SQL, namespaces, writes or broker access.
export async function readDashboard(options,execute,now=new Date()){
 const run=execute??(async(sql,args)=>(await getClient().execute({sql,args})).rows);
 const select=(sql,args=[])=>{if(!/^SELECT\s/i.test(sql))throw new Error('READ_ONLY_GUARD');return run(sql,args);};
 const day=istDay(now),ns=[NAMESPACE];
 if(options.view!=='overview'){
  const definitions={
   fills:{table:'paper_fills',fields:'id,strategy,symbol,side,qty,price,quote_at,filled_at,reason,realized_pnl',order:'filled_at DESC,id DESC',date:'filled_at'},
   positions:{table:'paper_positions',fields:'strategy,symbol,qty,entry_price,entry_at,high_water,mark_price,mark_at,updated_at',order:'strategy,symbol',date:'entry_at'},
   signals:{table:'paper_signals',fields:'id,strategy,symbol,bar_date,side,status,reason,created_at,eligible_date',order:'created_at DESC,id DESC',date:'created_at'},
   runs:{table:'paper_runs',fields:'kind,at,status',order:'at DESC,id DESC',date:'at'},
   quotes:{table:'paper_quote_audit',fields:'symbol,observed_at,quote_at,price,accepted,reason,source',order:'observed_at DESC,id DESC',date:'observed_at'}
  };
  const d=definitions[options.view],args=[...ns];let where='namespace=?'+(options.view==='positions'?' AND qty>0':'');
  if(options.strategy!==null){if(!['fills','positions','signals'].includes(options.view))throw new Error('BAD_REQUEST');where+=' AND strategy=?';args.push(options.strategy);}
  if(options.scope==='today'){where+=` AND date(${d.date},'+5 hours','+30 minutes')=?`;args.push(day);}
  const [counts,rows]=await Promise.all([select(`SELECT COUNT(*) AS total FROM ${d.table} WHERE ${where}`,args),select(`SELECT ${d.fields} FROM ${d.table} WHERE ${where} ORDER BY ${d.order} LIMIT ? OFFSET ?`,[...args,options.limit,(options.page-1)*options.limit])]);
  return {readAt:now.toISOString(),namespace:NAMESPACE,page:options.page,limit:options.limit,total:Number(counts[0].total),rows:options.view==='positions'?rows.map(r=>positionView(r,now.getTime())):publicRows(rows)};
 }
 const [totals,positions,pnl,performance,recentFills,recentSignals,lastRuns,audit,coverage]=await Promise.all([
  select("SELECT COUNT(*) AS filled_orders,COALESCE(SUM(realized_pnl),0) AS realized,COALESCE(SUM(CASE WHEN side='SELL' THEN 1 ELSE 0 END),0) AS closed_trades,COALESCE(SUM(CASE WHEN date(filled_at,'+5 hours','+30 minutes')=? THEN 1 ELSE 0 END),0) AS today_fills FROM paper_fills WHERE namespace=?",[day,NAMESPACE]),
  select('SELECT strategy,symbol,qty,entry_price,entry_at,high_water,mark_price,mark_at,updated_at FROM paper_positions WHERE namespace=? AND qty>0 ORDER BY strategy,symbol LIMIT 5000',ns),
  select('SELECT day,as_of,report_json FROM paper_pnl WHERE namespace=? ORDER BY day DESC LIMIT 366',ns),
  select("SELECT strategy,SUM(CASE WHEN side='SELL' THEN 1 ELSE 0 END) AS closed_trades,SUM(CASE WHEN side='SELL' AND realized_pnl>0 THEN 1 ELSE 0 END) AS wins,COALESCE(SUM(realized_pnl),0) AS realized FROM paper_fills WHERE namespace=? GROUP BY strategy ORDER BY strategy",ns),
  select('SELECT id,strategy,symbol,side,qty,price,quote_at,filled_at,reason,realized_pnl FROM paper_fills WHERE namespace=? ORDER BY filled_at DESC,id DESC LIMIT 12',ns),
  select('SELECT strategy,symbol,bar_date,side,status,reason,created_at,eligible_date FROM paper_signals WHERE namespace=? ORDER BY created_at DESC LIMIT 12',ns),
  select('SELECT kind,at,status FROM paper_runs WHERE namespace=? ORDER BY at DESC,id DESC LIMIT 10',ns),
  select('SELECT symbol,observed_at,quote_at,price,accepted,reason,source FROM paper_quote_audit WHERE namespace=? ORDER BY observed_at DESC,id DESC LIMIT 8',ns),
  select("SELECT (SELECT COUNT(*) FROM paper_watermarks WHERE namespace=?) AS watermarks,(SELECT COUNT(*) FROM paper_data_audit WHERE namespace=?) AS excluded_bars,(SELECT COUNT(*) FROM paper_signals WHERE namespace=? AND status='pending') AS pending_signals",[NAMESPACE,NAMESPACE,NAMESPACE])
 ]);
 const pos=positions.map(r=>positionView(r,now.getTime()));const unrealized=pos.some(r=>r.unrealized_pnl===null)?null:pos.reduce((a,r)=>a+r.unrealized_pnl,0);
 const reports=pnl.map(r=>{let d={};try{d=JSON.parse(r.report_json);}catch{/* Corrupt snapshots stay unavailable. */}return {day:r.day,asOf:r.as_of,daily:numeric(d.daily_mark_to_market_pnl_INR),total:numeric(d.latest_known_total_pnl_INR),realizedClosuresToday:numeric(d.realized_on_closures_today_INR),valuationIsLive:d.valuation_is_live===true,missingDailyBasis:d.missing_daily_basis_symbols??[]};});
 const latest=reports[0]??null,today=latest?.day===day?latest:null,realized=numeric(totals[0].realized);
 return {readAt:now.toISOString(),namespace:NAMESPACE,day,market:marketState(now),totals:{filledOrders:Number(totals[0].filled_orders),closedTrades:Number(totals[0].closed_trades),todayFills:Number(totals[0].today_fills),openPositions:pos.length,realized,unrealized,total:unrealized===null?null:realized+unrealized,daily:today?.daily??null,staleMarks:pos.filter(r=>r.mark_stale).length,missingMarks:pos.filter(r=>r.unrealized_pnl===null).length,pendingSignals:Number(coverage[0].pending_signals)},positions:pos.slice(0,20),performance:Array.from({length:7},(_,i)=>{const row=performance.find(r=>Number(r.strategy)===i+1);const closed=Number(row?.closed_trades??0);return {strategy:i+1,closedTrades:closed,winRate:closed?Number(row.wins)/closed*100:null,realized:numeric(row?.realized??0),openPositions:pos.filter(r=>Number(r.strategy)===i+1).length};}),dailyHistory:reports.reverse(),latestSnapshot:latest,recentFills:publicRows(recentFills),recentSignals:publicRows(recentSignals),lastRuns:publicRows(lastRuns),quoteAudit:publicRows(audit),coverage:coverage[0]};
}
