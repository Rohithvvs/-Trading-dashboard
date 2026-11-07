import {it,expect} from 'vitest';
import {readFileSync,globSync} from 'node:fs';
// Official https://openapi.vercel.sh/vercel.json verified 7 Nov 2026:
// functions.*.includeFiles is one glob STRING, not an array.
it('Vercel function includeFiles uses its schema-supported string glob and includes only the three public data files',()=>{
 const config=JSON.parse(readFileSync('vercel.json','utf8'));const pattern=config.functions['api/dashboard.js'].includeFiles;
 expect(typeof pattern).toBe('string');expect(pattern.length).toBeLessThanOrEqual(256);
 expect(globSync(pattern).sort()).toEqual(['automation/paper-trading/charge_policy.json','automation/paper-trading/config.json','server/instruments.json']);
});
