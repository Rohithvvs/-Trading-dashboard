// @vitest-environment node
// Isolated in-memory fixture database only. No environment credentials or production writes.
import {readFileSync} from 'node:fs';import {createClient} from '@libsql/client';import {afterEach,it,expect} from 'vitest';import {readDashboard,parseOptions} from '../server/data.mjs';
const clients=[];afterEach(()=>clients.splice(0).forEach(c=>c.close()));
async function fixture(){const db=createClient({url:'file::memory:'});clients.push(db);await db.executeMultiple(readFileSync(process.cwd()+'/tests/paper-schema.sql','utf8'));return db;}
const now=new Date('2026-11-07T04:30:00Z');const run=db=>async(sql,args)=>(await db.execute({sql,args})).rows;
it('calculates real SQL closed win rate, matched average holding days and total P&L without summing daily snapshots',async()=>{
 const db=await fixture();
 for(const [signal,side,day,price,pnl]of [['a','BUY','01',100,0],['b','SELL','03',120,20],['c','BUY','04',100,0],['d','SELL','05',90,-10]])await db.execute({sql:'INSERT INTO paper_fills(namespace,signal_id,strategy,symbol,side,qty,price,quote_at,filled_at,reason,realized_pnl,cashflow) VALUES(?,?,1,?,?,1,?,?,?,?,?,?)',args:['paper_v1',signal,'FIXTURE-EQ',side,price,`2026-11-${day}T10:00:00+05:30`,`2026-11-${day}T10:00:00+05:30`,'daily_entry',pnl,side==='BUY'?-price:price]});
 await db.execute("INSERT INTO paper_positions VALUES('paper_v1',2,'FIXTURE-EQ',2,50,'2026-11-06T10:00:00+05:30',60,60,'2026-11-07T10:00:00+05:30','2026-11-07T10:00:00+05:30')");
 for(const[day,total,daily]of [['2026-11-06',25,25],['2026-11-07',30,5]])await db.execute({sql:'INSERT INTO paper_pnl VALUES(?,?,?,?)',args:['paper_v1',day,day+'T10:00:00+05:30',JSON.stringify({latest_known_total_pnl_INR:total,daily_mark_to_market_pnl_INR:daily})]});
 const d=await readDashboard(parseOptions(),run(db),now);expect(d.closedStats).toEqual({count:2,winRate:50,averageHoldDays:1.5,matchedClosures:2});expect(d.totals).toMatchObject({realized:10,unrealized:20,total:30,daily:5,closedTrades:2});expect(d.dailyHistory.map(r=>r.total)).toEqual([25,30]);
});
it('history reads only accepted positive quotes, binds symbol/namespace and deduplicates timestamps',async()=>{
 const db=await fixture();for(const[p,at,accepted,ns]of [[55,'09:59:00',1,'paper_v1'],[59,'10:00:00',1,'paper_v1'],[60,'10:00:00',1,'paper_v1'],[9999,'10:01:00',0,'paper_v1'],[8888,'10:02:00',1,'other']])await db.execute({sql:'INSERT INTO paper_quote_audit(namespace,symbol,observed_at,quote_at,price,accepted,reason) VALUES(?,?,?,?,?,?,?)',args:[ns,'FIXTURE-EQ','2026-11-07T'+at+'+05:30','2026-11-07T'+at+'+05:30',p,accepted,'fresh']});const d=await readDashboard(parseOptions({view:'history',symbol:'FIXTURE-EQ'}),run(db),now);expect(d.rows.map(r=>r.price)).toEqual([55,60]);expect(d.namespace).toBe('paper_v1');
});
it('omits unmatched exits from holding average rather than inventing an entry timestamp',async()=>{const db=await fixture();await db.execute("INSERT INTO paper_fills(namespace,signal_id,strategy,symbol,side,qty,price,quote_at,filled_at,reason,realized_pnl,cashflow) VALUES('paper_v1','unmatched',1,'FIXTURE-EQ','SELL',1,100,'2026-11-07T10:00:00+05:30','2026-11-07T10:00:00+05:30','recorded_event',5,100)");const d=await readDashboard(parseOptions(),run(db),now);expect(d.closedStats).toEqual({count:1,winRate:100,averageHoldDays:null,matchedClosures:0});});
