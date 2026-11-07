import React from 'react';import {afterEach,describe,it,expect,vi} from 'vitest';import {render,screen,cleanup} from '@testing-library/react';import {todayStatus,Sparkline,PortfolioLine,PositionCard} from '../src/Beginner';import {readConfig,publicError,parseOptions} from '../server/data.mjs';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const live={signalsToday:0,totals:{pendingSignals:0},market:{open:false}};
describe('calm and truthful status',()=>{
 it('closed empty is neutral, not a red failure',()=>{expect(todayStatus(live,'').tone).toBe('muted');expect(todayStatus(live,'').title).toContain('market is closed');});
 it('successful empty open session is green',()=>expect(todayStatus({...live,market:{open:true}},'').tone).toBe('green'));
 it('pending has no false filled claim',()=>{expect(todayStatus({...live,totals:{pendingSignals:1}},'').title).toContain('waiting');});
 it('new signals are green and a failed connection is amber',()=>{expect(todayStatus({...live,signalsToday:2},'').tone).toBe('green');expect(todayStatus(live,'offline').tone).toBe('amber');expect(todayStatus(null,'offline').text).toContain('cannot confirm');});
});
describe('no fabricated price or funded equity',()=>{
 it('has no sparkline with zero or one observation',()=>{const{rerender}=render(<Sparkline rows={[]}/>);expect(screen.queryByRole('img')).not.toBeInTheDocument();rerender(<Sparkline rows={[{price:100}]}/>);expect(screen.queryByRole('img')).not.toBeInTheDocument();});
 it('draws only actual accepted source rows supplied by history API',()=>{render(<Sparkline rows={[{price:100,quote_at:'2026-11-07T09:59:00+05:30'},{price:101,quote_at:'2026-11-07T10:00:00+05:30'}]}/>);expect(screen.getByRole('img')).toHaveAttribute('aria-label',expect.stringContaining('2 recorded accepted quote prices'));expect(document.querySelector('polyline').getAttribute('points')).toBe('0,44 220,8');});
 it('empty curve has no invented example trend',()=>{render(<PortfolioLine rows={[]}/>);expect(screen.getByText(/will not draw an example trend/)).toBeInTheDocument();});
 it('why-trade text is the actual strategy rule, not fabricated entry indicators',async()=>{vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({rows:[]})})));render(<PositionCard position={{symbol:'FIXTURE-EQ',strategy:6,entry_price:100,mark_price:102,qty:1,mark_stale:true,mark_at:null,unrealized_pnl:2,entry_at:'2026-11-06T10:00:00+05:30'}}/>);expect(screen.getByText(/MACD crossed above its signal/)).toBeInTheDocument();expect(screen.getByText(/indicator values for this entry are not stored/)).toBeInTheDocument();await screen.findByText(/two accepted quote observations/);});
});
describe('server-only configuration diagnostics',()=>{
 it('normalizes whitespace, newline and surrounding quotes',()=>expect(readConfig({TURSO_DATABASE_URL:'  "libsql://fixture.turso.io"\n',TURSO_AUTH_TOKEN:' dummy-fixture \n'})).toEqual({url:'libsql://fixture.turso.io',authToken:'dummy-fixture'}));
 it.each([[{},'CONFIG_MISSING_URL'],[{TURSO_DATABASE_URL:'libsql://fixture'},'CONFIG_MISSING_TOKEN'],[{PAPER_NAMESPACE:'other'},'CONFIG_NAMESPACE']])('reports missing/invalid setup without values', (env,code)=>{expect(()=>readConfig(env)).toThrow(code);expect(publicError(new Error(code)).code).toBe(code);});
 it('classifies rejected auth/schema with no raw token or DB host',()=>{const a=publicError(Object.assign(new Error('401 secret-fixture-token'),{code:'UNAUTHORIZED'}));expect(a.code).toBe('DB_AUTH_REJECTED');expect(JSON.stringify(a)).not.toContain('secret-fixture-token');expect(publicError(new Error('no such table: paper_fills')).code).toBe('DB_SCHEMA_MISSING');});
 it.each([{view:'history'},{view:'history',symbol:"x';DROP TABLE x"},{view:'history',symbol:'A-EQ',namespace:'other'},{view:'fills',symbol:'A-EQ'}])('rejects invalid quote history request %j',q=>expect(()=>parseOptions(q)).toThrow('BAD_REQUEST'));
});
