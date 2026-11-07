import fs from 'node:fs';
export const policy=JSON.parse(fs.readFileSync(new URL('./charge_policy.json',import.meta.url),'utf8'));
const div=(n,d)=>(n+d/2n)/d;
export function paise(price){const s=String(price);if(!/^\d+(\.\d{1,2})?$/.test(s))throw Error('price_requires_positive_paise');const [a,b='']=s.split('.');const n=BigInt(a)*100n+BigInt(b.padEnd(2,'0'));if(n<=0n||n>9007199254740991n)throw Error('price_bounds');return n;}
export function estimate({turnover,side,prior=0n,priorBuy=0n,dp=false}){
 const v=BigInt(turnover),old=BigInt(prior),oldBuy=BigInt(priorBuy);if(v<=0n||!['BUY','SELL'].includes(side))throw Error('fee_inputs');
 const f={brokerage:div(v*3n,1000n),exchange:div(v*30699n,1000000000n),sebi:div(v,1000000n),ipft:div(v,1000000000n),clearing:0n};if(f.brokerage>2000n)f.brokerage=2000n;
 f.stt=(div(old+v,100000n)-div(old,100000n))*100n;
 f.stamp=side==='BUY'?div((oldBuy+v)*3n,20000n)-div(oldBuy*3n,20000n):0n;
 f.gst=div((f.brokerage+f.exchange+f.sebi+f.ipft)*18n,100n);f.dp=dp?1250n:0n;f.dp_gst=dp?225n:0n;
 const total=Object.values(f).reduce((a,b)=>a+b,0n);if(total>BigInt(Number.MAX_SAFE_INTEGER))throw Error('fee_bounds');return {...Object.fromEntries(Object.entries(f).map(([k,v])=>[k,Number(v)])),total:Number(total)};
}
