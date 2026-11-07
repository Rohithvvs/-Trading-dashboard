// Administrative local CLI. Never imported by the public API; no web write endpoint.
import {readFileSync} from 'node:fs';import {parse} from 'dotenv';import {createClient} from '@libsql/client/web';import {readConfig} from '../server/data.mjs';import {DEMO_NAMESPACE,DEMO_ID,DEMO_SELECT,insertManualDemo} from '../server/demo.mjs';
const command=process.argv[2]??'list';const allowed=['list','insert-reliance','delete-reliance'];if(!allowed.includes(command))throw new Error('Use list | insert-reliance --confirm-manual-test | delete-reliance --confirm-delete');
const local=parse(readFileSync(process.env.LOCAL_TURSO_ENV_FILE??'.env.local'));const client=createClient(readConfig({...local,...process.env}));
try{
 if(command==='insert-reliance'){if(!process.argv.includes('--confirm-manual-test'))throw new Error('EXPLICIT_CONFIRMATION_REQUIRED');const result=await insertManualDemo(client,new Date().toISOString());console.log(JSON.stringify({status:'VERIFIED',created:result.created,demo:result.row}));}
 else if(command==='delete-reliance'){if(!process.argv.includes('--confirm-delete'))throw new Error('EXPLICIT_CONFIRMATION_REQUIRED');const result=await client.execute({sql:'DELETE FROM paper_demo_trades WHERE namespace=? AND id=? AND is_test=1',args:[DEMO_NAMESPACE,DEMO_ID]});console.log(JSON.stringify({deleted:Number(result.rowsAffected),id:DEMO_ID}));}
 else console.log(JSON.stringify({demo:(await client.execute({sql:DEMO_SELECT,args:[DEMO_NAMESPACE]})).rows}));
}catch(error){console.error(JSON.stringify({status:'FAILED',code:error.message==='EXPLICIT_CONFIRMATION_REQUIRED'?error.message:String(error.code??'DEMO_OPERATION_FAILED').replace(/[^A-Z0-9_]/g,'')}));process.exitCode=1;}finally{client.close();}
