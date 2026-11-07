import {parseOptions,readDashboard,publicError} from '../server/data.mjs';
const cache=new Map(),clients=new Map();
export function createHandler(reader=readDashboard){return async function handler(req,res){
 res.setHeader('Content-Type','application/json; charset=utf-8');res.setHeader('Cache-Control','no-store');res.setHeader('X-Content-Type-Options','nosniff');
 if(req.method!=='GET'){res.setHeader('Allow','GET');return res.status(405).json({error:{code:'METHOD_NOT_ALLOWED',message:'Read-only endpoint. Use GET.'}});}
 const now=Date.now();const ip=String(req.headers['x-forwarded-for']??req.socket?.remoteAddress??'unknown').split(',')[0].trim().slice(0,100);
 const bucket=clients.get(ip);if(bucket&&now-bucket.at<60000){bucket.count++;if(bucket.count>90){res.setHeader('Retry-After','60');return res.status(429).json({error:{code:'RATE_LIMITED',message:'Please wait a minute before refreshing.'}});}}else clients.set(ip,{at:now,count:1});
 if(clients.size>2000)for(const[k,v]of clients)if(now-v.at>60000||clients.size>2000)clients.delete(k);
 try{const options=parseOptions(req.query??{});const {forceRefresh,...readOptions}=options;const key=JSON.stringify(readOptions);let value=cache.get(key);
  if(forceRefresh||!value||now-value.at>20000){const data=await reader(readOptions);value={at:now,data};if(cache.size>=200)cache.delete(cache.keys().next().value);cache.set(key,value);}
  return res.status(200).json({...value.data,cacheAgeSeconds:Math.floor((now-value.at)/1000)});
 }catch(error){const bad=error.message==='BAD_REQUEST',safe=bad?{code:'BAD_REQUEST',message:'Invalid view or pagination parameters.'}:publicError(error);if(!bad)console.error(JSON.stringify({event:'dashboard_read_failed',code:safe.code,at:new Date().toISOString()}));return res.status(bad?400:503).json({error:safe});}
};}
export default createHandler();
