export const DEMO_NAMESPACE='paper_demo_v1';
export const DEMO_ID='dummy_reliance_manual_v1';
export const DEMO_FIELDS='id,is_test,strategy_label,symbol,side,qty,entry_price,status,entry_at,price_source,note';
export const DEMO_SELECT=`SELECT ${DEMO_FIELDS} FROM paper_demo_trades WHERE namespace=? AND is_test=1 ORDER BY entry_at DESC LIMIT 25`;
