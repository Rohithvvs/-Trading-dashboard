import {readFileSync,readdirSync,existsSync} from 'node:fs';import {join} from 'node:path';import {parse} from 'dotenv';
const base=process.cwd(),files=[];function walk(dir){for(const d of readdirSync(dir,{withFileTypes:true})){if(['.git','node_modules','.vercel'].includes(d.name)||d.name.startsWith('.env'))continue;const p=join(dir,d.name);if(d.isDirectory())walk(p);else files.push(p);}}walk(base);
// Optional exact secret-value check, handled silently; no values are printed or persisted.
let secrets=[];const external=process.env.LOCAL_TURSO_ENV_FILE;if(external){const parsed=parse(readFileSync(external));secrets=Object.values(parsed).filter(v=>typeof v==='string'&&v.length>=18);}
let failures=0;for(const file of files){const text=readFileSync(file,'utf8');if(secrets.some(v=>text.includes(v))){console.error('FAIL: secret value detected in',file.slice(base.length+1));failures++;}if(file.includes('/dist/assets/')&&/TURSO_AUTH_TOKEN|TURSO_DATABASE_URL|LOCAL_TURSO_ENV_FILE|@libsql/.test(text)){console.error('FAIL: server configuration found in client bundle',file.slice(base.length+1));failures++;}}
if(!existsSync(join(base,'dist/index.html'))){console.error('Build first; dist is missing');failures++;}
console.log(JSON.stringify({filesScanned:files.length,exactSecretsChecked:secrets.length,failures,clientServerSeparation:failures===0}));process.exitCode=failures?1:0;
