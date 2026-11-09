import React from 'react';import {it,expect,vi,afterEach} from 'vitest';import {render,screen,fireEvent,cleanup,waitFor} from '@testing-library/react';import LiveResults,{LiveStrategies,PnlLines,AdaptiveTracksView} from '../src/LiveResults';import {readAdaptiveSummary} from '../server/automation-read.mjs';
afterEach(()=>{cleanup();vi.unstubAllGlobals();window.history.replaceState(null,'','#results');});
const empty={gross_total_paise:0,net_total_accrued_paise:0,accrued_cost_paise:0,open_positions:0,closed_trades:0,fills:0,win_rate:null};
const fixture={available:true,readAt:'2026-11-07T07:30:00Z',totals:empty,ledger_reconciled:true,eods:[],strategies:Array.from({length:7},(_,i)=>({strategy:i+1,...empty})),cohorts:['single','exactly_2','exactly_3','4_plus','unavailable'].map(cohort=>({cohort,...empty})),charge_breakdown_paise:{brokerage:0,stt:0,dp:0,gst:0},policy:{version:'test policy',effective_from:'2026-11-07',valid_through:'2026-12-31',rates:{brokerage:'Estimated Standard delivery'},assumptions:['Test-only policy fixture']},weekly:{gross_paise:null,net_paise:null,week_start:'2026-11-02',through:null,reason:'Awaiting complete verified daily baselines.'}};
const scan={available:true,readAt:fixture.readAt,bar_date:'2026-11-06',counts:Array.from({length:7},(_,i)=>({strategy:i+1,qualified:i+1})),stocks:[{symbol:'RELIANCE-EQ',name:'Reliance',strategies:[1,2,3]}]};
it('tabs retain zero ledger honestly, no fabricated curve and explicit modeled charges',async()=>{vi.stubGlobal('fetch',vi.fn(async u=>({ok:true,json:async()=>String(u).includes('view=scan')?scan:fixture})));window.history.replaceState(null,'','#results');render(<LiveResults refreshKey={0}/>);await screen.findByText('No verified end-of-day snapshots yet');expect(document.querySelector('svg[aria-label="Actual gross and net paper P&L by EOD session"]')).toBeNull();fireEvent.click(screen.getByRole('tab',{name:'Strategies'}));expect(await screen.findByText('Donchian / Turtle')).toBeInTheDocument();fireEvent.click(screen.getByRole('tab',{name:'Charges'}));expect(await screen.findByText(/No executed real paper orders yet/)).toBeInTheDocument();fireEvent.click(screen.getByRole('tab',{name:'Daily & weekly'}));expect(await screen.findByText('Latest daily net change')).toBeInTheDocument();expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(1);});
it('real snapshot line points expose keyboard/touch values without seeded baseline',()=>{render(<PnlLines rows={[{day:'2026-11-09',closing_valuation_complete:true,gross_total_paise:1000,net_total_accrued_paise:800}]}/>);const point=screen.getAllByRole('button')[0];fireEvent.keyDown(point,{key:'Enter'});expect(screen.getByText(/2026-11-09 · Gross/)).toBeInTheDocument();expect(document.querySelectorAll('circle')).toHaveLength(2);});
it('new live qualifier without frozen research gets real checklist and honest historical empty state',async()=>{const row={symbol:'NEWSTOCK-EQ',name:'New Stock',checklist:{checks:{actual_cross:true},rule:'Actual frozen cross condition'},plan:{reference_close:100,entry:'First fresh in-session quote',stop:'No fixed stop',exit_rule:'Completed-candle exit'}};vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({available:true,rows:[row],total:1,bar_date:'2026-11-06'})})));const catalog={strategies:[{id:1,name:'Donchian',qualifiers:[]}]};render(<LiveStrategies catalog={catalog} scan={scan} route={{id:1,symbol:'NEWSTOCK-EQ'}} refreshKey={0} onResearch={vi.fn()}/>);await screen.findByText('New Stock');expect(screen.getByText(/No saved historical backtest exists/)).toBeInTheDocument();expect(screen.getByText('actual cross')).toBeInTheDocument();expect(screen.queryByText('Open frozen historical backtest')).toBeNull();});
it('latest selector renders all seven real counts',()=>{vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({rows:[],available:true,total:0})})));const {container}=render(<LiveStrategies catalog={{strategies:scan.counts.map(c=>({id:c.strategy,name:'Strategy '+c.strategy}))}} scan={scan} route={{id:null,symbol:null}} refreshKey={0}/>);expect(container.querySelectorAll('.strategy-choice')).toHaveLength(7);expect(screen.getByText('7 qualified')).toBeInTheDocument();});

it('manual refresh and global five-minute refresh key force actual GET rereads',async()=>{const fetch=vi.fn(async u=>({ok:true,json:async()=>String(u).includes('view=scan')?scan:fixture}));vi.stubGlobal('fetch',fetch);window.history.replaceState(null,'','#results');const {rerender}=render(<LiveResults refreshKey={0}/>);await screen.findByText('No verified end-of-day snapshots yet');fireEvent.click(screen.getByRole('button',{name:'Refresh results'}));await waitFor(()=>expect(fetch.mock.calls.filter(([u])=>String(u).includes('view=analytics'))).toHaveLength(2));rerender(<LiveResults refreshKey={1}/>);await waitFor(()=>expect(fetch.mock.calls.filter(([u])=>String(u).includes('view=analytics'))).toHaveLength(3));expect(fetch.mock.calls.every(([u,o])=>String(u).includes('refresh=1')&&o.cache==='no-store')).toBe(true);});
it('overview leads with the capped master ledger headline and labels historical figures',async()=>{const capped={headline:true,book:'capped',headline_net_pnl_paise:123400,equity_paise:350123400,capital_return_pct:0.0353,master_capital_paise:350000000};vi.stubGlobal('fetch',vi.fn(async u=>({ok:true,json:async()=>String(u).includes('view=scan')?scan:{...fixture,capped_master_ledger:capped}})));render(<LiveResults refreshKey={0}/>);expect(await screen.findByText('Headline P&L · capped master ledger')).toBeInTheDocument();expect(screen.getByText('Headline net P&L')).toBeInTheDocument();expect(screen.getByText('0.0353%')).toBeInTheDocument();expect(screen.getByText(/legacy 1-share LTP fills/)).toBeInTheDocument();});
it('adaptive Tracks A/B/C tab renders status, gate evaluations, hash-chained logs, and tier controls',async()=>{
 const adaptive={
  observation_only:true,
  ci_lookahead_passed:true,
  calibration_go:true,
  power_floor_target:0.30,
  max_concurrent_challengers_track_b:3,
  max_champions_per_strategy_track_c:1,
  tracks:[
   {track_id:'track_a_s1',tier:'A',strategy:1,status:'active',warm_start_days:120,target_window_days:75,extension_days:0,starting_equity_paise:50000000,exit_haircut_paise:0},
   {track_id:'track_b_s3_01',tier:'B',strategy:3,status:'active',warm_start_days:60,target_window_days:45,extension_days:0,starting_equity_paise:49850000,exit_haircut_paise:150000},
   {track_id:'track_c_s1_champ',tier:'C',strategy:1,status:'active',warm_start_days:120,target_window_days:75,extension_days:0,starting_equity_paise:50000000,exit_haircut_paise:0}
  ],
  spawns:[],
  gate_evaluations:[{spawn_id:'spawn_s3_01',strategy:3,track_id:'track_b_s3_01',k_cand:3,rho_bar:0.5,k_eff:2.0,effective_critical_t:1.96,t_hac:2.35,residualized_mean_bps:38.4,all_gates_passed:1,terminal_status:'promoted'}],
  calibration_runs:[],
  probation:[],
  logs:[
   {seq_id:1,tier:'B',track_id:'track_b_s3_01',event_type:'SPAWN_CREATED',named_cause:'CHALLENGER_SPAWNED_PURE_PAPER',entry_hash:'abcdef1234567890'},
   {seq_id:2,tier:'C',track_id:'track_c_s1_champ',event_type:'PROMOTION_COMPLETED',named_cause:'CHALLENGER_PROMOTED_TO_TRACK_C',entry_hash:'9876543210fedcba'}
  ]
 };
 vi.stubGlobal('fetch',vi.fn(async u=>({ok:true,json:async()=>String(u).includes('view=scan')?scan:{...fixture,adaptive}})));
 window.history.replaceState(null,'','#results');
 render(<LiveResults refreshKey={0}/>);
 await screen.findByText('No verified end-of-day snapshots yet');
 fireEvent.click(screen.getByRole('tab',{name:'Tracks A/B/C'}));
 expect(await screen.findByText('3-Tier Adaptive Architecture · Tracks A, B & C')).toBeInTheDocument();
 expect(screen.getByText('Observation-only lock active')).toBeInTheDocument();
 expect(screen.getByText('Calibration Go (≥30% power)')).toBeInTheDocument();
 expect(screen.getByText('CI Look-ahead Truncation Verified')).toBeInTheDocument();
 expect(screen.getByText('track_b_s3_01')).toBeInTheDocument();
 expect(screen.getByText('spawn_s3_01')).toBeInTheDocument();
 expect(screen.getByText('CHALLENGER_SPAWNED_PURE_PAPER')).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Track C'}));
 expect(screen.getByText('track_c_s1_champ')).toBeInTheDocument();
 expect(screen.queryByText('track_b_s3_01')).toBeNull();
 const summary=await readAdaptiveSummary(async()=>[]);
 expect(summary.observation_only).toBe(true);
 expect(summary.max_concurrent_challengers_track_b).toBe(3);
});
