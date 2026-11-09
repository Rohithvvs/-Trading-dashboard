CREATE TABLE IF NOT EXISTS paper_signals(namespace TEXT NOT NULL,id TEXT NOT NULL,strategy INTEGER NOT NULL,symbol TEXT NOT NULL,bar_date TEXT NOT NULL,side TEXT NOT NULL CHECK(side IN('BUY','SELL')),status TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL,eligible_date TEXT NOT NULL,PRIMARY KEY(namespace,id));
CREATE TABLE IF NOT EXISTS paper_positions(namespace TEXT NOT NULL,strategy INTEGER NOT NULL,symbol TEXT NOT NULL,qty INTEGER NOT NULL CHECK(qty>=0),entry_price REAL NOT NULL CHECK(entry_price>0),entry_at TEXT NOT NULL,high_water REAL NOT NULL CHECK(high_water>0),mark_price REAL,mark_at TEXT,updated_at TEXT NOT NULL,PRIMARY KEY(namespace,strategy,symbol));
CREATE TABLE IF NOT EXISTS paper_fills(id INTEGER PRIMARY KEY AUTOINCREMENT,namespace TEXT NOT NULL,signal_id TEXT NOT NULL,strategy INTEGER NOT NULL,symbol TEXT NOT NULL,side TEXT NOT NULL,qty INTEGER NOT NULL CHECK(qty>0),price REAL NOT NULL CHECK(price>0),quote_at TEXT NOT NULL,filled_at TEXT NOT NULL,reason TEXT NOT NULL,realized_pnl REAL NOT NULL,cashflow REAL NOT NULL,execution_path TEXT NOT NULL DEFAULT 'LTP_LEGACY' CHECK(execution_path IN('LTP_LEGACY','FEED_OPEN','AUCTION_CAPTURE','FALLBACK_OPEN')),UNIQUE(namespace,signal_id));
CREATE TABLE IF NOT EXISTS paper_watermarks(namespace TEXT NOT NULL,strategy INTEGER NOT NULL,symbol TEXT NOT NULL,bar_date TEXT NOT NULL,PRIMARY KEY(namespace,strategy,symbol));
CREATE TABLE IF NOT EXISTS paper_pnl(namespace TEXT NOT NULL,day TEXT NOT NULL,as_of TEXT NOT NULL,report_json TEXT NOT NULL,PRIMARY KEY(namespace,day));
CREATE TABLE IF NOT EXISTS paper_runs(id INTEGER PRIMARY KEY AUTOINCREMENT,namespace TEXT NOT NULL,kind TEXT NOT NULL,at TEXT NOT NULL,status TEXT NOT NULL,details_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS paper_quote_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,namespace TEXT NOT NULL,symbol TEXT NOT NULL,observed_at TEXT NOT NULL,quote_at TEXT,price REAL,accepted INTEGER NOT NULL,reason TEXT NOT NULL,source TEXT NOT NULL DEFAULT 'FYERS_QUOTES');
CREATE TABLE IF NOT EXISTS paper_data_audit(namespace TEXT NOT NULL,symbol TEXT NOT NULL,bar_date TEXT NOT NULL,reason TEXT NOT NULL,observed_at TEXT NOT NULL,PRIMARY KEY(namespace,symbol,bar_date,reason));
CREATE TABLE IF NOT EXISTS paper_meta(namespace TEXT NOT NULL,key TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(namespace,key));

CREATE INDEX IF NOT EXISTS paper_signals_pending_idx ON paper_signals(namespace,status);
CREATE INDEX IF NOT EXISTS paper_fills_day_idx ON paper_fills(namespace,filled_at);
CREATE INDEX IF NOT EXISTS paper_positions_open_idx ON paper_positions(namespace,qty);
CREATE TABLE IF NOT EXISTS paper_charge_policies(version TEXT PRIMARY KEY,policy_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS paper_fill_costs(namespace TEXT NOT NULL,fill_id INTEGER NOT NULL,day TEXT NOT NULL,strategy INTEGER NOT NULL,symbol TEXT NOT NULL,isin TEXT NOT NULL,side TEXT NOT NULL,turnover_paise INTEGER NOT NULL,policy_version TEXT NOT NULL,components_json TEXT NOT NULL,total_paise INTEGER NOT NULL,entry_at TEXT NOT NULL,gross_cashflow_paise INTEGER NOT NULL,net_cashflow_paise INTEGER NOT NULL,PRIMARY KEY(namespace,fill_id));
CREATE TABLE IF NOT EXISTS paper_dp_debits(namespace TEXT NOT NULL,day TEXT NOT NULL,isin TEXT NOT NULL,fill_id INTEGER NOT NULL,amount_paise INTEGER NOT NULL,PRIMARY KEY(namespace,day,isin));
CREATE TABLE IF NOT EXISTS paper_entry_cohorts(namespace TEXT NOT NULL,strategy INTEGER NOT NULL,symbol TEXT NOT NULL,entry_at TEXT NOT NULL,signal_bar TEXT NOT NULL,strategies_json TEXT NOT NULL,cohort TEXT NOT NULL,PRIMARY KEY(namespace,strategy,symbol,entry_at));
CREATE TABLE IF NOT EXISTS paper_scan_batches(namespace TEXT NOT NULL,bar_date TEXT NOT NULL,scanned_at TEXT NOT NULL,status TEXT NOT NULL,report_json TEXT NOT NULL,PRIMARY KEY(namespace,bar_date));
CREATE TABLE IF NOT EXISTS paper_qualifier_states(namespace TEXT NOT NULL,bar_date TEXT NOT NULL,strategy INTEGER NOT NULL,symbol TEXT NOT NULL,qualified INTEGER NOT NULL,checklist_json TEXT NOT NULL,plan_json TEXT NOT NULL,scanned_at TEXT NOT NULL,PRIMARY KEY(namespace,bar_date,strategy,symbol));
CREATE TABLE IF NOT EXISTS paper_monitor_health(namespace TEXT PRIMARY KEY,pid INTEGER NOT NULL,heartbeat_at TEXT NOT NULL,status TEXT NOT NULL,detail_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS paper_eod(namespace TEXT NOT NULL,day TEXT NOT NULL,as_of TEXT NOT NULL,report_json TEXT NOT NULL,PRIMARY KEY(namespace,day));
CREATE INDEX IF NOT EXISTS paper_cost_day_idx ON paper_fill_costs(namespace,day);
CREATE INDEX IF NOT EXISTS paper_qualified_bar_idx ON paper_qualifier_states(namespace,bar_date,qualified,symbol);

-- Versioned two-layer entry gate (additive, separate from demo tables).
CREATE TABLE IF NOT EXISTS paper_prefilter_policies(version TEXT PRIMARY KEY,policy_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS paper_prefilter_states(namespace TEXT NOT NULL,bar_date TEXT NOT NULL,symbol TEXT NOT NULL,policy_version TEXT NOT NULL,status TEXT NOT NULL,metrics_json TEXT NOT NULL,observed_at TEXT NOT NULL,PRIMARY KEY(namespace,bar_date,symbol,policy_version));
CREATE TABLE IF NOT EXISTS paper_entry_gate_proofs(namespace TEXT NOT NULL,signal_id TEXT NOT NULL,bar_date TEXT NOT NULL,symbol TEXT NOT NULL,policy_version TEXT NOT NULL,PRIMARY KEY(namespace,signal_id));


CREATE TABLE IF NOT EXISTS paper_history_gap_checks(namespace TEXT NOT NULL,symbol TEXT NOT NULL,trade_date TEXT NOT NULL,checked_at TEXT NOT NULL,outcome TEXT NOT NULL,retry_after TEXT NOT NULL,details_json TEXT NOT NULL,PRIMARY KEY(namespace,symbol,trade_date));

-- Additive immutable live-input provenance. Raw OHLCV is never deleted.
CREATE TABLE IF NOT EXISTS paper_input_policies(version TEXT PRIMARY KEY,policy_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS paper_input_evidence(version TEXT PRIMARY KEY,policy_version TEXT NOT NULL,evidence_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS paper_entry_input_proofs(namespace TEXT NOT NULL,signal_id TEXT NOT NULL,policy_version TEXT NOT NULL,bar_date TEXT NOT NULL,observed_at TEXT NOT NULL,PRIMARY KEY(namespace,signal_id));

-- Durable allowlisted paper-event audit and local session guardian.
CREATE TABLE IF NOT EXISTS paper_events(namespace TEXT NOT NULL,event_id TEXT NOT NULL,run_id TEXT NOT NULL,session_day TEXT NOT NULL,source_at TEXT NOT NULL,recorded_at TEXT NOT NULL,event_type TEXT NOT NULL,severity TEXT NOT NULL,outcome TEXT NOT NULL,strategy INTEGER,symbol TEXT,bar_date TEXT,signal_id TEXT,policy_version TEXT,input_policy_version TEXT,data_json TEXT NOT NULL,persisted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),PRIMARY KEY(namespace,event_id));CREATE INDEX IF NOT EXISTS paper_events_session ON paper_events(namespace,session_day,recorded_at,event_id);CREATE INDEX IF NOT EXISTS paper_events_run ON paper_events(namespace,run_id);
CREATE TABLE IF NOT EXISTS paper_guardian_health(namespace TEXT PRIMARY KEY,pid INTEGER NOT NULL,process_start TEXT NOT NULL,session_day TEXT NOT NULL,heartbeat_at TEXT NOT NULL,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS paper_decisions(namespace TEXT NOT NULL,seq INTEGER NOT NULL,correlation_id TEXT NOT NULL,decision_type TEXT NOT NULL CHECK(decision_type IN('ENTRY','EXIT','SKIP','HOLD')),strategy INTEGER,symbol TEXT,signal_id TEXT,cause TEXT,rule TEXT,execution_path TEXT,source_at TEXT NOT NULL,recorded_at TEXT NOT NULL,prev_hash TEXT NOT NULL,entry_hash TEXT NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(namespace,seq));
CREATE INDEX IF NOT EXISTS paper_decisions_correlation ON paper_decisions(namespace,correlation_id,seq);
CREATE TABLE IF NOT EXISTS paper_shadow_positions(namespace TEXT NOT NULL,strategy INTEGER NOT NULL,symbol TEXT NOT NULL,qty INTEGER NOT NULL CHECK(qty>=0),entry_price REAL NOT NULL,entry_at TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(namespace,strategy,symbol));
CREATE TABLE IF NOT EXISTS paper_shadow_costs(namespace TEXT NOT NULL,signal_id TEXT NOT NULL,strategy INTEGER NOT NULL,symbol TEXT NOT NULL,side TEXT NOT NULL,qty INTEGER NOT NULL,price REAL NOT NULL,total_paise INTEGER NOT NULL,net_cashflow_paise INTEGER NOT NULL,filled_at TEXT NOT NULL,PRIMARY KEY(namespace,signal_id));
