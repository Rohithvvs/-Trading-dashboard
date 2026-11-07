import React from 'react';import {it,expect,vi,afterEach} from 'vitest';import {render,screen,fireEvent,act,cleanup} from '@testing-library/react';import App from '../src/App';
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals();});
it('page-load, manual, five-minute refresh and auto-off use actual API fetch flow',async()=>{
 vi.useFakeTimers();
 const live={readAt:new Date().toISOString(),totals:{filledOrders:0,closedTrades:0,todayFills:0,openPositions:0,realized:0,unrealized:0,total:0,daily:null,staleMarks:0,missingMarks:0,pendingSignals:0},market:{label:'NSE session closed'},coverage:{watermarks:4844,excluded_bars:2},lastRuns:[],positions:[],performance:[],recentSignals:[],recentFills:[],dailyHistory:[],latestSnapshot:null};
 const fetcher=vi.fn(async url=>({ok:true,json:async()=>url==='/api/dashboard'?live:{strategies:[],caveats:[],verification:[]}}));vi.stubGlobal('fetch',fetcher);
 await act(async()=>{render(<App/>);});const calls=()=>fetcher.mock.calls.filter(c=>c[0]==='/api/dashboard').length;
 expect(calls()).toBe(1);expect(screen.getByText('Clarity, before capital.')).toBeInTheDocument();
 await act(async()=>{fireEvent.click(screen.getByRole('button',{name:'Refresh'}));});expect(calls()).toBe(2);
 await act(async()=>{await vi.advanceTimersByTimeAsync(300000);});expect(calls()).toBe(3);
 fireEvent.click(screen.getByRole('checkbox'));await act(async()=>{await vi.advanceTimersByTimeAsync(300000);});expect(calls()).toBe(3);
});
