import fs from 'fs';import {createRequire} from 'module';const require=createRequire(import.meta.url);const{createClient}=require('@libsql/client');
import path from 'node:path';import {fileURLToPath} from 'node:url';import {policy,paise,estimate} from './fees.mjs';
const a=JSON.parse(fs.readFileSync(0,'utf8'));const root=path.dirname(fileURLToPath(import.meta.url));
if(a.test_database&&(!path.resolve(a.test_database).startsWith(root+'/tests/test_')||!a.test_database.endsWith('.sqlite')))throw Error('invalid_test_path');
const env={};if(!a.test_database){for(const l of fs.readFileSync(process.env.PAPER_ENV_FILE||'/workspace/sahil-fyers-turso/.env','utf8').split('\n')){const p=l.indexOf('=');if(p>0&&!l.startsWith('#'))env[l.slice(0,p).trim()]=l.slice(p+1).trim().replace(/^(['"])(.*)\1$/,'$2')}}
const db=createClient(a.test_database?{url:'file:'+a.test_database}:{url:env.TURSO_DATABASE_URL,authToken:env.TURSO_AUTH_TOKEN});let tx;
const rows=r=>r.rows.map(x=>Object.fromEntries(Object.entries(x).map(([k,v])=>[k,typeof v==='bigint'?Number(v):v])));
try{
if(a.action==='register_policy'){const val=JSON.stringify(policy);await db.execute({sql:'INSERT OR IGNORE INTO paper_charge_policies(version,policy_json) VALUES(?,?)',args:[policy.version,val]});const r=rows(await db.execute({sql:'SELECT policy_json FROM paper_charge_policies WHERE version=?',args:[policy.version]}))[0];if(r.policy_json!==val)throw Error('immutable_policy_changed');console.log(JSON.stringify({policy_version:policy.version}));}
else if(a.action==='query'){const r=await db.execute({sql:a.sql,args:a.args||[]});console.log(JSON.stringify(rows(r)))}
else if(a.action==='batch'){await db.batch(a.statements,'write');console.log('{}')}
else if(a.action==='fill'){
 tx=await db.transaction('write');const n=a.namespace,s=a.signal;
 let r=await tx.execute({sql:'SELECT * FROM paper_signals WHERE namespace=? AND id=?',args:[n,s.id]});let signal=rows(r)[0];
 if(!signal&&s.stop){await tx.execute({sql:'INSERT INTO paper_signals(namespace,id,strategy,symbol,bar_date,side,status,reason,created_at,eligible_date) VALUES(?,?,?,?,?,?,?,?,?,?)',args:[n,s.id,s.strategy,s.symbol,s.bar_date,'SELL','pending',s.reason,a.at,s.eligible_date]});signal=s}
 if(!signal||signal.status&&signal.status!=='pending'){await tx.rollback();console.log(JSON.stringify({filled:false,reason:'not_pending'}));process.exit(0)}
 r=await tx.execute({sql:'SELECT * FROM paper_positions WHERE namespace=? AND strategy=? AND symbol=?',args:[n,s.strategy,s.symbol]});const p=rows(r)[0],qty=p?.qty||0;const side=s.side;
 if((side==='BUY'&&qty>0)||(side==='SELL'&&qty<=0)){await tx.execute({sql:"UPDATE paper_signals SET status='ignored_state' WHERE namespace=? AND id=?",args:[n,s.id]});await tx.commit();console.log(JSON.stringify({filled:false,reason:'position_guard'}));process.exit(0)}
 if(signal.strategy!==s.strategy||signal.symbol!==s.symbol||signal.side!==side)throw Error('signal_mismatch');
 const expected=s.expected_entry_at||(signal.reason?.startsWith('daily_exit:')?signal.reason.slice('daily_exit:'.length):null);
 if(side==='SELL'&&expected&&p.entry_at!==expected){await tx.execute({sql:"UPDATE paper_signals SET status='ignored_stale_position' WHERE namespace=? AND id=?",args:[n,s.id]});await tx.commit();console.log(JSON.stringify({filled:false,reason:'position_identity_guard'}));process.exit(0)}
 if(side==='BUY'&&rows(await tx.execute({sql:"SELECT 1 FROM paper_fills f JOIN paper_signals g ON g.namespace=f.namespace AND g.id=f.signal_id WHERE f.namespace=? AND f.strategy=? AND f.symbol=? AND f.side='BUY' AND g.bar_date=? LIMIT 1",args:[n,s.strategy,s.symbol,signal.bar_date]})).length){await tx.execute({sql:"UPDATE paper_signals SET status='ignored_same_bar' WHERE namespace=? AND id=?",args:[n,s.id]});await tx.commit();console.log(JSON.stringify({filled:false,reason:'same_bar_reentry_guard'}));process.exit(0)}
 if(!Number.isInteger(s.strategy)||s.strategy<1||s.strategy>7||!Number.isInteger(a.quantity)||a.quantity<1||!Number.isFinite(a.price)||a.price<=0)throw Error('fill_input_guard');
 const day=a.at.slice(0,10);if(day<policy.effective_from||day>policy.valid_through)throw Error('charge_policy_expired');
 if(!a.isin||!/^IN[A-Z0-9]{10}$/.test(a.isin))throw Error('verified_isin_required');
 if(side==='BUY'&&rows(await tx.execute({sql:'SELECT COUNT(*) AS n FROM paper_fills f LEFT JOIN paper_fill_costs c ON c.namespace=f.namespace AND c.fill_id=f.id WHERE f.namespace=? AND c.fill_id IS NULL',args:[n]}))[0].n)throw Error('unpriced_legacy_fills_entry_paused');
 const q=side==='BUY'?a.quantity:qty;const turnover=paise(a.price)*BigInt(q);if(turnover>BigInt(Number.MAX_SAFE_INTEGER))throw Error('turnover_bounds');
 const prior=rows(await tx.execute({sql:'SELECT side,turnover_paise,policy_version FROM paper_fill_costs WHERE namespace=? AND day=?',args:[n,day]}));
 if(prior.some(x=>x.policy_version!==policy.version))throw Error('mixed_daily_policy');
 const dp=side==='SELL'&&p.entry_at.slice(0,10)<day&&!rows(await tx.execute({sql:'SELECT 1 FROM paper_dp_debits WHERE namespace=? AND day=? AND isin=?',args:[n,day,a.isin]})).length;
 const fees=estimate({turnover,side,prior:prior.reduce((v,x)=>v+BigInt(x.turnover_paise),0n),priorBuy:prior.filter(x=>x.side==='BUY').reduce((v,x)=>v+BigInt(x.turnover_paise),0n),dp});
 const pol=JSON.stringify(policy);await tx.execute({sql:'INSERT OR IGNORE INTO paper_charge_policies(version,policy_json) VALUES(?,?)',args:[policy.version,pol]});
 if(rows(await tx.execute({sql:'SELECT policy_json FROM paper_charge_policies WHERE version=?',args:[policy.version]}))[0].policy_json!==pol)throw Error('immutable_policy_changed');
 const realized=side==='SELL'?(a.price-p.entry_price)*q:0;
 await tx.execute({sql:'INSERT INTO paper_fills(namespace,signal_id,strategy,symbol,side,qty,price,quote_at,filled_at,reason,realized_pnl,cashflow) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',args:[n,s.id,s.strategy,s.symbol,side,q,a.price,a.quote_at,a.at,s.reason,realized,(side==='BUY'?-1:1)*q*a.price]});
 const fillId=Number(rows(await tx.execute('SELECT last_insert_rowid() AS id'))[0].id);
 await tx.execute({sql:'INSERT INTO paper_fill_costs(namespace,fill_id,day,strategy,symbol,isin,side,turnover_paise,policy_version,components_json,total_paise,entry_at,gross_cashflow_paise,net_cashflow_paise) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',args:[n,fillId,day,s.strategy,s.symbol,a.isin,side,Number(turnover),policy.version,JSON.stringify(fees),fees.total,side==='BUY'?a.at:p.entry_at,Number(turnover)*(side==='BUY'?-1:1),Number(turnover)*(side==='BUY'?-1:1)-fees.total]});
 if(dp)await tx.execute({sql:'INSERT INTO paper_dp_debits(namespace,day,isin,fill_id,amount_paise) VALUES(?,?,?,?,?)',args:[n,day,a.isin,fillId,fees.dp+fees.dp_gst]});
 if(side==='BUY'){
  const qq=rows(await tx.execute({sql:'SELECT strategy FROM paper_qualifier_states WHERE namespace=? AND bar_date=? AND symbol=? AND qualified=1 ORDER BY strategy',args:[n,signal.bar_date,s.symbol]})).map(x=>x.strategy);
  const cohort=qq.includes(s.strategy)?(qq.length===1?'single':qq.length===2?'exactly_2':qq.length===3?'exactly_3':'4_plus'):'unavailable';
  await tx.execute({sql:'INSERT INTO paper_entry_cohorts(namespace,strategy,symbol,entry_at,signal_bar,strategies_json,cohort) VALUES(?,?,?,?,?,?,?)',args:[n,s.strategy,s.symbol,a.at,signal.bar_date,JSON.stringify(qq),cohort]});
 }
 if(side==='BUY')await tx.execute({sql:'INSERT INTO paper_positions(namespace,strategy,symbol,qty,entry_price,entry_at,high_water,mark_price,mark_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(namespace,strategy,symbol) DO UPDATE SET qty=excluded.qty,entry_price=excluded.entry_price,entry_at=excluded.entry_at,high_water=excluded.high_water,mark_price=excluded.mark_price,mark_at=excluded.mark_at,updated_at=excluded.updated_at',args:[n,s.strategy,s.symbol,q,a.price,a.at,a.price,a.price,a.quote_at,a.at]});
 else await tx.execute({sql:'UPDATE paper_positions SET qty=0,mark_price=?,mark_at=?,updated_at=? WHERE namespace=? AND strategy=? AND symbol=?',args:[a.price,a.quote_at,a.at,n,s.strategy,s.symbol]});
 await tx.execute({sql:"UPDATE paper_signals SET status='filled' WHERE namespace=? AND id=?",args:[n,s.id]});await tx.commit();console.log(JSON.stringify({filled:true,side,qty:q,price:a.price,realized_pnl:realized,estimated_cost_paise:fees.total,policy_version:policy.version}));
}else if(a.action==='estimate'){console.log(JSON.stringify(estimate({turnover:paise(a.price)*BigInt(a.quantity),side:a.side,prior:BigInt(a.prior||0),priorBuy:BigInt(a.priorBuy||0),dp:!!a.dp})))}else throw Error('invalid_action');
}catch(e){if(tx)try{await tx.rollback()}catch{/* Preserve the original sanitized failure. */}const local=new Set(['price_requires_positive_paise','price_bounds','fee_inputs','fee_bounds','turnover_bounds','charge_policy_expired','mixed_daily_policy','verified_isin_required','immutable_policy_changed','fill_input_guard','signal_mismatch','unpriced_legacy_fills_entry_paused']);const code=local.has(e.message)?e.message:(/^[A-Z0-9_]{1,60}$/.test(e.code||'')?e.code:'TURSO_OPERATION_FAILED');console.error(JSON.stringify({error:'database_operation_failed',code,type:e.name}));process.exitCode=1}finally{db.close()}
