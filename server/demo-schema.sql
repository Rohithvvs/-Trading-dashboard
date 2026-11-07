CREATE TABLE IF NOT EXISTS paper_demo_trades (
 id TEXT PRIMARY KEY,
 namespace TEXT NOT NULL CHECK(namespace='paper_demo_v1'),
 is_test INTEGER NOT NULL CHECK(is_test=1),
 strategy_label TEXT NOT NULL CHECK(strategy_label='Dummy Test'),
 symbol TEXT NOT NULL,
 side TEXT NOT NULL CHECK(side='BUY'),
 qty INTEGER NOT NULL CHECK(qty>0),
 entry_price REAL NOT NULL CHECK(entry_price>0),
 status TEXT NOT NULL CHECK(status='OPEN'),
 entry_at TEXT NOT NULL,
 price_source TEXT NOT NULL CHECK(price_source='MANUAL_TEST_NOT_LIVE'),
 note TEXT NOT NULL
);
