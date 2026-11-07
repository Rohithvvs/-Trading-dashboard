# Seven-strategy PAPER session engine — upgrade v2

**No broker orders. No funded account. One share, long-only, independent virtual position per strategy/stock.** Only Fyers `data/history` and `data/quotes` endpoints are allowlisted. Manual dashboard demonstrations live in a separate table/namespace; this engine never queries them.

## Installation and deployment boundary

Production installation is `/workspace/paper-trading` on the shared bot box. Versioned source is `automation/paper-trading` in the dashboard GitHub repo. **Vercel hosts only the read-only dashboard/API, NOT this persistent Python worker. A GitHub push does not install/start the box engine or save routines.** Do not copy `.env`, logs, output files, auth circuits, SQLite test databases or caches into Git.

Tested Python3.13.5 (`requirements.txt`) and @libsql/client0.18.0 (matching the existing installed runtime) (`package-lock.json`). `run.sh` uses the existing external Python venv; `PAPER_PYTHON` can select a different compatible interpreter. Node resolves installed dependencies normally; use `npm ci` in this package on a new installation. Market-data auth remains the existing local `fyers_auth` integration. The shared protected credentials remain `/workspace/sahil-fyers-turso/.env`; never use browser-prefixed env variables. This source package contains no credentials. Tests use disposable, path-restricted local libSQL files and do not read the production env.

Install updates under the existing exclusive `engine.lock`; migrate additive schema first, then atomically replace versioned source files before releasing the lock. Preserve the lock inode, local credentials, logs and out files. Schema setup is `./run.sh init` (idempotent), which registers an immutable policy snapshot and `automation_schema_version=2`. Never initialize test fills in production.

## Frozen rules, completed data and eligibility

`strategy_indicators.py` and `strategy_rules.json` preserve the original seven rules. Source-function comparisons are in the original28 regression tests. Donchian uses prior20 highs/prior10 lows; actual Supertrend/EMA/MACD crosses remain events, not relaxed bullish states. RSI/Bollinger/momentum retain their existing inequalities. Momentum alone has its prescribed10% completed-close high-water trail, plus completed-close SMA50 exit. No extra target, stop, stop-and-reverse, rebalancing or end-of-day liquidation is introduced.

The frozen paper universe is692 exact symbol+series/ISIN identities, with59 explicitly excluded identities from the original751 audit. No alias substitution or new-market expansion. Missing/stale/current-bar-invalid data cannot qualify. Only previous **completed exchange sessions** are scanned; the daily bar is conservatively considered completed from16:00 IST. History sync is incremental and rejects future, closed/unverified-session and invalid OHLC candles. Existing invalid data exclusion remains separate from the unchanged research backtests. EMA/ATR/RSI history initialization is not truncated or redefined.

Each scan transaction saves all seven strategy/current-stock filter checklists, observed indicator values, qualification flags and honest plans to Turso, including explicit unavailable states. `paper_scan_batches.report_json` contains sequential and individual filter pass counts. Every signal retains its strategy/symbol/completed-bar identity. Watermarks, pending-state checks, unique fill IDs and a transactional same-bar re-entry guard prevent duplicate/replayed orders. **Existing Friday6Nov watermarks are not reseeded or backfilled.** Entry requires a NEW completed bar after its watermark, no position, no pending entry, and first fresh eligible-session Fyers LTP; never a claimed exact opening fill. Unchanged bar replay creates no new order. A daily condition need not become false and then true again: its original rule is preserved.

The calendar retains the previously verified8Nov2026 Sunday special session as historical/completed-bar input, but new automatic scan/worker execution is **Mon–Fri only**. Thus a genuinely new verified Sunday daily bar could be processed Monday; previously processed Friday data alone does not generate retrospective orders. Holidays fail closed. Calendar validity remains1Nov–31Dec2026;2027 sessions are **not guessed**. Review/extend from official NSE notices before expiry. Health warns within14days; unsupported dates stop automation. Existing calendar URLs remain in config.

## Commands and persistence

```sh
./run.sh scan --sync       # scheduled08:45 IST weekdays; sync prior completed session, persist screen, queue NEW eligible signals
./run.sh screen-only       # explicit screen refresh, NO sync/queue/watermark/position changes (does write screen/audit/run records)
./run.sh ensure-monitor    # supervised singleton startup/healthcheck; closed/unverified/weekend -> no worker or Fyers call
./run.sh worker            # normally launched only by ensure-monitor; bounded to verified weekday session
./run.sh monitor-once      # backwards-compatible bounded iteration; closed -> no quote/fill/P&L snapshot
./run.sh health            # read-only DB/worker health; no P&L write
./run.sh positions         # read-only real strategy positions
./run.sh trades-today      # read-only paper fills
./run.sh finance           # read-only gross/net/estimated costs, reconciliation, freshness, strategy/cohort groups
./run.sh charges           # read-only immutable fill-charge components
./run.sh overlap           # read-only saved current qualifiers -> sorted strategy sets and exclusive buckets
./run.sh eod               # persist/upsert weekday EOD at/after16:00 IST; never force-close a position
./run.sh weekly            # read-only Mon-through-current-session change summary
./run.sh pnl               # legacy GROSS snapshot command: WRITES paper_pnl, adds estimated_finance
./run.sh status            # legacy compatibility: also WRITES paper_pnl; use health+finance for read-only checks
```

New additive tables: `paper_charge_policies`, `paper_fill_costs`, `paper_dp_debits`, `paper_entry_cohorts`, `paper_scan_batches`, `paper_qualifier_states`, `paper_monitor_health`, `paper_eod`. All namespace-scoped rows use existing `paper_v1`; policy versions are shared immutable public configuration, not credentials. Legacy tables/column meanings are preserved. No historical fee backfill: existing unpriced fills make net metrics unavailable and pause new entries until an explicit migration decision.

## Worker safety and supervision — routines MUST be saved separately

30-second target polling,50symbols/request batches, existing1.3-second minimum between requests. Actual cadence can be longer for large batches/network/DB latency. This is **polling, not every tick**; a gap can fill a stop at the observed price, never at an invented threshold. Quote source status, same verified session, positive finite price, exchange timestamp and60-second age are checked **again for each individual fill** and mark update. Stale/unavailable quotes never create fills. Entries expire after their eligible session; exits are processed first. Auth refresh remains single-attempt with a30-minute circuit; the circuit is checked BEFORE another HTTP call. Transport failures use bounded backoff up to300seconds; auth failure pauses/exits the worker.

An inherited OS file-lock lease prevents launch races/duplicate workers. Each iteration takes existing `engine.lock`, so scan/old routine commands cannot overlap a worker fill. Health and supervision deliberately bypass that command mutex, so a hung iteration cannot block its own recovery. The worker releases that lock between iterations. Heartbeats record actual PID/process-start identity and status. A stale lease-free PID is harmless: OS locks release on crash. A heartbeat over600seconds old permits supervisor to TERM **only a verified same-start, exact-path owned worker**, never arbitrary/reused PIDs; next supervision starts a replacement. Otherwise report attention needed. Worker exits when session ends. No system cron, systemd or routines are installed by this package. Host restart needs the durable supervisor to run again.

Parent should replace old16:00 daily scan and bounded5-minute monitor schedules, not create duplicates. All trigger times **Asia/Calcutta (IST)**:
- Scan: `45 8 * * 1-5` → `run.sh scan --sync`.
- Worker bootstrap/supervisor trigger group: `15,20,25,30,35,40,45,50,55 9 * * 1-5`; `*/5 10-14 * * 1-5`; `0,5,10,15,20,25,30 15 * * 1-5` → `run.sh ensure-monitor`, then `run.sh health`.
- EOD: `10 16 * * 1-5` → `run.sh eod`, then `run.sh weekly`.
- Report failures, paused_auth, stale heartbeat, missing cost/basis/marks or calendar/policy warning; remain quiet on normal verified closures. The verified full692-symbol screen from existing completed history took about6minutes; fresh history sync adds API-dependent time. The08:45 trigger is a start time, not a guarantee that all scanning finishes before09:15. A routine may start late (scheduler jitter), so09:15 exact execution is not guaranteed. Between-supervisor downtime can be5minutes plus jitter. The15:30 tick correctly refuses new worker startup.

## Estimated delivery charges: sources, assumptions and rounding

Rates retrieved/opened7Nov2026 IST, recorded in `charge_policy.json`. **These are modeled paper costs, never actual debits or a contract-note guarantee.** Standard plan assumed; Prime/promotion not verified.

| Component | Policy |
|---|---|
|Brokerage|min(₹20,0.3% turnover), per executed virtual order, both sides; effective1Oct2024|
|STT|0.1% delivery buy/sell; namespace/day cumulative nearest-rupee liability, incremental allocation|
|NSE transaction|0.0030699% both sides; revised split effective1Mar2026|
|NSE IPFT|₹0.01/crore (0.0000001%) both sides, NOT obsolete₹10/crore|
|SEBI|₹10/crore (0.0001%) both sides|
|Stamp|0.015% buy; cumulative day rounded to paise|
|GST|18% brokerage+exchange+SEBI+IPFT; DP GST separate|
|DP|₹12.50+₹2.25 GST once/ISIN/day on overnight sell, across strategies; first eligible sell bears allocation|
|Cash clearing|₹0 assumed; cash row not separately specified. Do not apply derivatives clearing rates to cash.|

Official opened sources: [FYERS detailed charges](https://fyers.in/charges-list), [FYERS plan pricing](https://fyers.in/pricing), [brokerage revision/effective date](https://support.fyers.in/portal/en/kb/articles/what-are-the-brokerage-charges-for-equity-intraday-and-delivery-trades-at-fyers), [DP per-ISIN/day](https://support.fyers.in/portal/en/kb/articles/how-are-dp-charges-levied-in-fyers), [NSE statutory rates](https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies), [NSE Clearing EOD STT](https://www.nseclearing.in/equities). The NSE27Feb2026 [FA73061 circular](https://nsearchives.nseindia.com/content/circulars/FA73061.pdf) was indexed with the March1 split but direct PDF retrieval returned403; the live FYERS charges list independently shows the same current split. Older FYERS support statutory text conflicts on IPFT/GST: use the current detailed charges list/NSE dated revision, not obsolete figures. Sources are not a claim that the user's actual account plan was checked.

BigInt integer-paise cashflows and charge components; half-up paise rounding per order, except cumulative STT whole rupees and cumulative stamp paise. GST is computed from the rounded taxable components. STT/stamp incremental allocation reconciles day totals; attribution between strategies is fill-order-dependent. Example on separate days: buy1@₹2500 estimated₹12.32, overnight sell1@₹2600 estimated₹27.05, gross₹100/net₹60.63. DP is capped once, not repeated for every strategy. Same-day exits have NO DP; delivery STT/stamp remain conservative assumptions, not an emulation of actual client security-wise netted intraday settlement. Subscription/interest/income tax/corporate actions are not modeled. Policy v1 is effective from7Nov2026 through31Dec2026; expiry fails closed and requires a new version, never mutation of an already-recorded policy.

Fill, position, gross cashflow, fee components/net cashflow, DP debit, entry cohort and signal status commit in ONE transaction. A rollback cannot leave an uncharged fill, double DP or orphan cohort. Replays cannot charge again. Existing `paper_fills.realized_pnl/cashflow` retain legacy GROSS meanings; exact new cashflows are integer paise in `paper_fill_costs`.

## Analytics definitions / next-dashboard contract

`finance` reports integer INR paise:
- gross total = closed realized + latest accepted marked unrealized;
- accrued model costs = executed BUY/SELL fees only;
- net realized = closed gross less its associated entry+exit costs;
- net unrealized accrued = open gross less its entry costs;
- net total accrued = gross total minus ALL accrued model fees;
- net after estimated exit = net total accrued minus a separate projected close-all sell-cost scenario, DP capped once. Projection is NOT booked, and stale mark provenance is explicit.
- net cashflow + current marked holdings reconciles to net total; missing cost/mark coverage is explicit. No funded capital/account equity/percentage return is invented.

Entry overlap freezes **the signal bar's** complete sorted strategy set. Exclusive buckets: single, exactly_2, exactly_3,4_plus, unavailable. Current-screen overlap also exposes at-least2/3 counts, which must NOT be summed as disjoint buckets. Strategy and entry-cohort gross/net totals reconcile without counting a trade in multiple exclusive buckets. The same stock can be separate virtual holdings in several strategies; these are not a deployable combined funded portfolio.

EOD preserves last accepted in-session mark timestamps, never claims official close/live quotes or closes swing positions. Daily changes require current marks within the last5minutes of the session (still NOT official close) and a preceding verified-session near-close EOD cumulative baseline; older marks preserve only clearly labeled latest-known cumulative values, not a falsely precise daily return; missing prior baseline yields unavailable daily P&L (except proven zero pre-inception ledger). No fabricated historical snapshots. Weekly sums verified DAILY CHANGES, not cumulative totals; missing session coverage yields unavailable totals. These are gross/net P&L curves unless funded capital is explicitly introduced in a later authorized change.

Logs: `logs/engine.jsonl`, `logs/monitor-worker.log`; tests use `logs/tests.jsonl`. Logs redact remote error contents and expose vetted codes only. Persisted `paper_runs`, worker health, scan batches and EOD reports provide auditability. Do not publish logs or credentials.

## Verification

```sh
PAPER_PYTHON=/workspace/sahil-fyers-turso/.venv/bin/python
"$PAPER_PYTHON" -m unittest discover -s tests -v
```

All execution examples in tests use local libSQL, fixtures and test namespaces, NOT production fills. Includes frozen indicator identity, fresh/session boundaries, bootstrap/no backlog/replay/oversell guards, atomic rollback/concurrency, independent Decimal fee arithmetic, DP cap, integer cashflows, immutable cohorts/policies, supervisor singleton/inherited lease/auth pause/backoff, completed-only sync, per-fill time revalidation, missing marks/baselines, EOD idempotence and weekly change arithmetic. Saturday verification cannot prove future in-session market availability or stop execution; report that limitation instead of claiming uninterrupted tick monitoring.
