import {parseOptions,readDashboard} from '../server/data.mjs';
const cache=new Map(),clients=new Map();
export function createHandler(reader=readDashboard){return async function handler(req,res){
 res.setHeader('Content-Type','application/json; charset=utf-8');res.setHeader('Cache-Control','no-store');res.setHeader('X-Content-Type-Options','nosniff');
 if(req.method!=='GET'){res.setHeader('Allow','GET');return res.status(405).json({error:{code:'METHOD_NOT_ALLOWED',message:'Read-only endpoint. Use GET.'}});}
 const now=Date.now();const ip=String(req.headers['x-forwarded-for']??req.socket?.remoteAddress??'unknown').split(',')[0].trim().slice(0,100);
 const bucket=clients.get(ip);if(bucket&&now-bucket.at<60000){bucket.count++;if(bucket.count>90){res.setHeader('Retry-After','60');return res.status(429).json({error:{code:'RATE_LIMITED',message:'Please wait a minute before refreshing.'}});}}else clients.set(ip,{at:now,count:1});
 if(clients.size>2000)for(const[k,v]of clients)if(now-v.at>60000||clients.size>2000)clients.delete(k);
 try{const options=parseOptions(req.query??{});const key=JSON.stringify(options);let value=cache.get(key);
  if(!value||now-value.at>20000){const data=await reader(options);value={at:now,data};if(cache.size>=200)cache.delete(cache.keys().next().value);cache.set(key,value);}
  return res.status(200).json({...value.data,cacheAgeSeconds:Math.floor((now-value.at)/1000)});
 }catch(error){const bad=error.message==='BAD_REQUEST';if(!bad)console.error(JSON.stringify({event:'dashboard_read_failed',code:'DATA_UNAVAILABLE',at:new Date().toISOString()}));return res.status(bad?400:503).json({error:{code:bad?'BAD_REQUEST':'DATA_UNAVAILABLE',message:bad?'Invalid view or pagination parameters.':'Paper data is unavailable. Verify server-only Turso configuration.'}});}
};}
export default createHandler();
