import React from 'react';import {readFileSync} from 'node:fs';import {it,expect,vi,afterEach} from 'vitest';import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react';import App from '../src/App';
const history=JSON.parse(readFileSync(process.cwd()+'/public/data/historical.json','utf8'));
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('renders every real saved strategy, filter explorer, overlaps and methodology without mock production fills',async()=>{
 const live={readAt:new Date().toISOString(),totals:{filledOrders:0,closedTrades:0,todayFills:0,openPositions:0,realized:0,unrealized:0,total:0,daily:null,staleMarks:0,missingMarks:0,pendingSignals:0},market:{label:'NSE session closed'},coverage:{watermarks:4844,excluded_bars:2},lastRuns:[],positions:[],performance:[],recentSignals:[],recentFills:[],dailyHistory:[],latestSnapshot:null};
 vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url==='/data/historical.json'?history:url==='/api/dashboard?refresh=1'?live:{readAt:new Date().toISOString(),rows:[],total:0}})));vi.stubGlobal('scrollTo',vi.fn());
 render(<App/>);await screen.findByText('Your swing-trading journal.');
 fireEvent.click(screen.getByRole('checkbox',{name:/Advanced tools/}));fireEvent.click(screen.getByRole('button',{name:/Strategy research/}));await screen.findByText('The seven-strategy atlas');
 for(let i=1;i<=7;i++){fireEvent.change(screen.getByRole('combobox',{name:'Choose strategy'}),{target:{value:String(i)}});expect(screen.getByRole('heading',{name:history.strategies[i-1].name,exact:true})).toBeInTheDocument();}
 fireEvent.click(screen.getByRole('button',{name:'Filter explorer'}));expect(screen.getByText('Why did a stock pass — or fail?')).toBeInTheDocument();
 for(let i=1;i<=7;i++){fireEvent.change(screen.getByRole('combobox',{name:'Choose strategy'}),{target:{value:String(i)}});expect(screen.getByRole('heading',{name:`${history.strategies[i-1].name} · ordered filter funnel`})).toBeInTheDocument();}
 fireEvent.click(screen.getByRole('button',{name:'Overlap atlas'}));expect(screen.getByText('Where strategies intersect')).toBeInTheDocument();expect(screen.getByRole('heading',{name:'Exactly 7 strategies'})).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Methodology'}));expect(screen.getByText('Know what the numbers mean.')).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Paper ledger'}));await waitFor(()=>expect(screen.getByText('The execution ledger')).toBeInTheDocument());
});
