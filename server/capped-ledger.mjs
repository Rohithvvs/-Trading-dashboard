// Server-only SELECT mirror of automation.py capped_ledger(): the public headline P&L book.
import capital from '../automation/paper-trading/capital_policy.json' with {type:'json'};
import {paise} from '../automation/paper-trading/fees.mjs';

export const PUBLIC_LABELS=Object.freeze({
 historical_figures_gross:true,
 survivorship_biased:true,
 not_jointly_tested:true,
 historical_disclaimer:'Historical backtest figures are gross of transaction costs, survivorship-biased on the present-day universe, and not jointly tested across strategies.',
 headline_pnl_source:'capped_master_ledger',
 shadow_book_diagnostic_only:true,
 adv_floor_review:capital.adv_floor_review
});

const int=v=>{const x=Number(v??0);if(!Number.isSafeInteger(x))throw Error('PRECISION_UNAVAILABLE');return x;};

export async function cappedLedger(select,namespace,positions){
 const master=int(capital.master_capital_inr*100),sleeveCap=int(capital.sleeve_capital_inr*100);
 let flows;
 try{flows=new Map((await select('SELECT strategy,COALESCE(SUM(net_cashflow_paise),0) AS n FROM paper_fill_costs WHERE namespace=? GROUP BY strategy',[namespace])).map(r=>[Number(r.strategy),int(r.n)]));}
 catch(e){if(/no such (table|column)/i.test(String(e?.message??'')))return {headline:true,book:'capped',available:false,reason:'fee_ledger_unavailable',headline_net_pnl_paise:null,equity_paise:null,master_capital_paise:master,public_labels:PUBLIC_LABELS};throw e;}
 // Legacy fills without a fee/cashflow row cannot be valued; never treat them as zero-cost.
 let uncovered=0;
 try{uncovered=int((await select('SELECT COUNT(*) AS n FROM paper_fills f WHERE f.namespace=? AND f.strategy BETWEEN 1 AND 7 AND NOT EXISTS(SELECT 1 FROM paper_fill_costs c WHERE c.namespace=f.namespace AND c.fill_id=f.id)',[namespace]))[0]?.n);}
 catch(e){if(!/no such (table|column)/i.test(String(e?.message??'')))throw e;}
 let credits=new Map(),creditsAvailable=true;
 try{credits=new Map((await select('SELECT strategy,COALESCE(SUM(amount_paise),0) AS n FROM paper_cash_credits WHERE namespace=? GROUP BY strategy',[namespace])).map(r=>[Number(r.strategy),int(r.n)]));}
 catch(e){if(!/no such table/i.test(String(e?.message??'')))throw e;creditsAvailable=false;}
 const sleeves={};let cash=0,marked=0,missing=false;
 for(let s=1;s<=capital.strategy_count;s++){
  const held=positions.filter(p=>Number(p.strategy)===s&&Number(p.qty)>0);const c=sleeveCap+(flows.get(s)??0)+(credits.get(s)??0);cash+=c;
  if(held.some(p=>!(Number(p.mark_price)>0))){missing=true;sleeves[s]={cash_paise:c,market_value_paise:null,equity_paise:null,net_pnl_paise:null,open_positions:held.length,slots_max:capital.max_positions_per_sleeve};continue;}
  const mv=held.reduce((a,p)=>a+int(paise(Number(p.mark_price).toFixed(2))*BigInt(p.qty)),0);marked+=mv;
  sleeves[s]={cash_paise:c,market_value_paise:mv,equity_paise:c+mv,net_pnl_paise:c+mv-sleeveCap,open_positions:held.length,slots_max:capital.max_positions_per_sleeve};
 }
 if(uncovered)missing=true;
 const equity=missing?null:cash+marked,net=equity===null?null:equity-master;
 return {headline:true,book:'capped',available:true,uncovered_fills:uncovered,marks_missing:missing,policy_version:capital.version,master_capital_paise:master,sleeve_capital_paise:sleeveCap,sleeve_count:capital.strategy_count,target_notional_paise:int(capital.target_notional_inr*100),max_positions_per_sleeve:capital.max_positions_per_sleeve,max_strategies_per_isin:capital.max_strategies_per_isin,adv_floor_inr:capital.adv_floor_inr,adv_floor_review:capital.adv_floor_review,cash_paise:cash,market_value_paise:missing?null:marked,equity_paise:equity,headline_net_pnl_paise:net,capital_return_pct:net===null?null:Math.round(net/master*1e6)/1e4,cash_credits_available:creditsAvailable,sleeves,public_labels:PUBLIC_LABELS};
}
