// Public copy derived from the engine's locked policy files, so the dashboard never repeats policy numbers by hand.
import capital from '../automation/paper-trading/capital_policy.json' with {type:'json'};
import engine from '../automation/paper-trading/config.json' with {type:'json'};

const inr=n=>'₹'+new Intl.NumberFormat('en-IN',{maximumFractionDigits:0}).format(n);
const words=['zero','one','two','three','four','five','six','seven','eight','nine','ten'];
const crore=n=>{const c=n/1e7;return `₹${Number.isInteger(c)?c:c.toFixed(2)} crore`;};

export const POLICY=Object.freeze({
 version:capital.version,
 master:inr(capital.master_capital_inr),
 masterInr:capital.master_capital_inr,
 sleeve:inr(capital.sleeve_capital_inr),
 sleeves:capital.strategy_count,
 sleevesWord:words[capital.strategy_count]??String(capital.strategy_count),
 target:inr(capital.target_notional_inr),
 slots:capital.max_positions_per_sleeve,
 isinCap:capital.max_strategies_per_isin,
 advFloor:crore(capital.adv_floor_inr),
 advFloorStatus:capital.adv_floor_review==='reviewed'?'reviewed':'placeholder, pending funnel review',
 trail:Number(engine.strategy_07_trail_fraction).toFixed(2),
 inr
});
