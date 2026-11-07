import {it,expect,vi,afterEach} from 'vitest';import {render,screen,cleanup,fireEvent} from '@testing-library/react';import {GateSummary,GateMetrics} from '../src/Prefilter';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('two-stage funnel explains exact defaults and optional volume without claiming proprietary or backtested results',()=>{
 render(<GateSummary scan={{bar_date:'2026-11-06',prefilter:{ready:true,data_usable:600,beta_pass:150,passed:30,policy:{version:'beta_momentum_v1'}}}}/>);expect(screen.getByText('30')).toBeVisible();expect(screen.getByText(/not a proprietary Swing Trade Analyzer replica/)).toBeInTheDocument();expect(screen.getByText(/No claim of improved returns or combined-system backtest validation/)).toBeInTheDocument();
});
it('missing stage-one evidence is unavailable, not a satisfied legacy entry',()=>{render(<GateMetrics/>);expect(screen.getByText(/No entry can rely on an ungated legacy signal/)).toBeVisible();});
it('advanced audit is fetched only after expansion with bounded read-only parameters',async()=>{
 const fetch=vi.fn(async()=>({ok:true,json:async()=>({total:1,rows:[{symbol:'TCS-EQ',name:'TCS',status:'UNAVAILABLE',metrics:{reasons:['stale_stock_or_benchmark']}}]})}));vi.stubGlobal('fetch',fetch);render(<GateSummary scan={{bar_date:'2026-11-06'}}/>);expect(fetch).not.toHaveBeenCalled();fireEvent.click(screen.getByText('Advanced · original universe pass/fail/unavailable audit'));expect(await screen.findByText('Stock or benchmark does not match the completed target session')).toBeVisible();expect(String(fetch.mock.calls[0][0])).toContain('view=prefilter');expect(String(fetch.mock.calls[0][0])).toContain('limit=12');
});
it('input audit preserves raw/history provenance and links mock-only dates to official evidence',()=>{
 render(<GateSummary scan={{bar_date:'2026-11-06',inputValidation:{excluded_rows:7789,legacy_before_coverage_rows_retained:2200235,policy:{version:'verified_live_inputs_v1'},excluded_by_date:{'2026-07-04':557}},inputEvidence:{sources:{'2026-07-04':'https://nsearchives.nseindia.com/content/circulars/CMTR74982.pdf'},classification:{'2026-07-04':'Mock-only session'}}}}/>);
 expect(screen.getByText('Verified live-input session audit')).toBeInTheDocument();expect(screen.getByText(/all raw rows remain stored/)).toBeInTheDocument();expect(screen.getByText(/pre-coverage rows not claimed calendar-clean/)).toBeInTheDocument();expect(screen.getByRole('link',{name:'2026-07-04',hidden:true})).toHaveAttribute('href','https://nsearchives.nseindia.com/content/circulars/CMTR74982.pdf');
});
it('beta just below 1.2 keeps decimal labels, six-digit display and exact unrounded threshold evidence',()=>{
 render(<GateMetrics metrics={{status:'FAIL',beta:1.1951234,checks:{beta_at_least_1_2:false},reasons:['beta_at_least_1_2'],return63:.099999,relative63:.049999,return20:-.000001}}/>);
 expect(screen.getByText('1.195123')).toBeVisible();expect(screen.getByText('Beta ≥ 1.2',{selector:'strong'})).toBeVisible();expect(screen.queryByText('beta at least 1 2')).not.toBeInTheDocument();expect(screen.getByTitle(/Actual beta 1\.195123/)).toHaveAttribute('aria-label',expect.stringContaining('required beta ≥ 1.2'));expect(screen.getByText(/Volume expansion is diagnostic only/)).toHaveTextContent('Beta ≥ 1.2');
});
it('unknown reason punctuation is preserved rather than silently rewriting a numerical condition',()=>{
 render(<GateMetrics metrics={{status:'UNAVAILABLE',reasons:['provider.reason: threshold 1.2 unavailable']}}/>);expect(screen.getByText(/provider.reason: threshold 1.2 unavailable/)).toBeInTheDocument();
});
it('actual stored SSWL beta displays below threshold rather than a misleading 1.20',()=>{
 render(<GateMetrics metrics={{status:'FAIL',beta:1.1995215626470972,checks:{beta_at_least_1_2:false},reasons:['beta_at_least_1_2']}}/>);expect(screen.getByText('1.199522')).toBeVisible();expect(screen.queryByText('1.20')).not.toBeInTheDocument();expect(screen.getByTitle('Unrounded beta: 1.1995215626470972; threshold ≥ 1.2')).toBeVisible();
});
