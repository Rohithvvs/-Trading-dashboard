import {readFileSync} from 'node:fs';
import {DEMO_NAMESPACE,DEMO_ID} from './demo-read.mjs';
export {DEMO_NAMESPACE,DEMO_ID,DEMO_SELECT} from './demo-read.mjs';
export function validateDemo(row){if(row.id!==DEMO_ID||row.namespace!==DEMO_NAMESPACE||row.is_test!==1||row.strategy_label!=='Dummy Test'||row.symbol!=='RELIANCE-EQ'||row.side!=='BUY'||row.qty!==1||row.entry_price!==2500||row.status!=='OPEN'||row.price_source!=='MANUAL_TEST_NOT_LIVE'||!Number.isFinite(Date.parse(row.entry_at)))throw new Error('INVALID_MANUAL_DEMO');return row;}
export async function insertManualDemo(client,at=new Date().toISOString()){
 const schema=readFileSync(new URL('./demo-schema.sql',import.meta.url),'utf8');
 const expected=validateDemo({id:DEMO_ID,namespace:DEMO_NAMESPACE,is_test:1,strategy_label:'Dummy Test',symbol:'RELIANCE-EQ',side:'BUY',qty:1,entry_price:2500,status:'OPEN',entry_at:at,price_source:'MANUAL_TEST_NOT_LIVE',note:'User-requested manual visibility test. Price ₹2500 is supplied, not a Fyers quote. Excluded from automation, signals, holdings and all paper performance.'});
 const tx=await client.transaction('write');
 try{
  await tx.execute(schema);
  const result=await tx.execute({sql:'SELECT id FROM paper_demo_trades WHERE namespace=? AND id=?',args:[DEMO_NAMESPACE,DEMO_ID]});
  let created=false;
  if(!result.rows.length){const keys=Object.keys(expected);await tx.execute({sql:`INSERT INTO paper_demo_trades(${keys.join(',')}) VALUES(${keys.map(()=>'?').join(',')})`,args:Object.values(expected)});created=true;}
  const stored=(await tx.execute({sql:'SELECT * FROM paper_demo_trades WHERE namespace=? AND id=?',args:[DEMO_NAMESPACE,DEMO_ID]})).rows[0];validateDemo(stored);
  await tx.commit();return {created,row:stored};
 }catch(error){await tx.rollback();throw error;}finally{tx.close();}
}
