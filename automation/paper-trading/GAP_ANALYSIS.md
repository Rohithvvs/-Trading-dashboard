# Gap analysis — freeze upgrade and support agent

Date: 2026-11-09. Repo: `vvsrohith9490870277-stack/-Trading-dashboard`. Core: `automation/paper-trading/`.

> Update 2026-11-09 16:15 IST: funnel/ADV impact, overlap, Stage A replay (6 Nov 100%; 8 Nov all 17 divergences = SPECIAL_SESSION_EXCLUDED) and the live-month blockers are in `reports/FREEZE_FUNNEL_AND_RECONCILIATION_2026-11-09.md`. ADV now uses `COALESCE(turnover, close*volume)` and skips the Muhurat session; the ₹10 crore floor is still `pending_funnel_report`. Dashboard headline P&L now reads the capped master ledger and historical figures carry gross / survivorship-biased / not-jointly-tested labels. Live engine testing: Wednesday 11 Nov 2026 (Tuesday 10 Nov is an NSE holiday).

Sources: Implementation Action Plan `1D9BKMAUvEskfOUNzAav42AcKlzmuVIneNQ1C7QTP7BY`, Freeze Version `1wYCbiCCSCedPEhj_6lMV-gwr0CFG6SARyOX1yY20-oY`, freeze checklists `1TNprAJLI97dwMJkSFFUvrDumspayTA3_OVjyqO2SN_4`, freeze logging spec `1Zo9n9yfpUmtXAV6DNw1iIVtRGkRRcPzjKu5m3ojufqI`, Support Agent plan `1wxsNpjuDTratWW4bbua0YifSj_GK8FYYp9LgZnG_2U0`, support checklists `1mAT2hES_vNwJHXXjZuoXa5wqBYTNRYS0DBfLmoH-GtQ`, support logging spec `1juueVBRskwxHxXcFkZkK9L9yGB_6WP7g_XMvARPKouo`.

Locked numbers are not open for change: master ₹35,00,000, sleeve ₹5,00,000 × 7, target notional ₹50,000, 9 positions per sleeve, 3 strategies per ISIN, entry order exits then `sha256(session date, symbol, freeze_capital_v1)` then strategies 01–07.

Status: Task Groups A–I, the Stage A / Stage B reconciliation harness, and the Support Agent (A1–A6 + B tests) are implemented on `freeze-strategies-upgrade` (live month replay remains blocked on external Turso credentials and NSE bhavcopy archives, so live acceptance is not claimed). The ₹10 crore ADV floor is still `pending_funnel_report`. Nothing is installed on the bot box. BE/BZ exit slippage uses the locked 1.5 stress multiplier because the freeze requires higher exit slippage and does not give a separate rate. Split and bonus prices use half-up paise. A fractional share waits for the post-adjustment open. Strategy-pause hysteresis N is not numeric in the freeze, so automatic reinstatement from N shadow trades is not implemented. The 30-trade upper bound uses a one-sided 95% normal critical value because the freeze names the bound and the window but not the critical value. Strategy 07 trailing stops follow `trail_gap` → queued SMA50 open exit → `trail_touch` with `0.90 * H` unchanged and the evidence clock reset to `2026-11-09`. Muhurat (`2026-11-08`) is excluded from indicators, the funnel report and 7×7 overlap matrix are exposed, headline P&L comes from the capped master ledger, and the Support Agent writes append-only findings (`INCOMPLETE_LIFECYCLE_MINUTES = None`, observation-only by default) without mutating trading state.

## Strategy 07 trailing stop

This is a signal-layer change. Do it only in Task Group H, with a version bump and an evidence-clock reset.

`strategy_rules.json` strategy 7 sets `H = max(H, completed close)` and evaluates the stop on the next session: open at or through the prior stop (`trail_gap`), then a queued SMA50 exit at the open, then `low <= stop` (`trail_touch`). High-water uses closes, not highs. The formula is `0.90 * H`.

`engine.py` `_monitor` fills that stop during the session when the polled LTP is at or below `0.90 * high_water`, reason `observed_LTP_below_close_highwater_stop`. The scan updates `high_water` from completed closes only. Intraday polling is not display-only.

The trail formula already matches the frozen JSON. The timing does not.

## Already matches the freeze

Leave these alone except where a later task says to extend them.

- Paper only, long only, no broker order routes. One open position per strategy and symbol.
- Seven frozen rules in `strategy_rules.json` and `strategy_indicators.py`. Stage-1 prefilter `beta_momentum_v1`. Next-session eligibility. Completed-bar signals.
- Cost model in `charge_policy.json` / `fees.mjs`: brokerage `min(₹20, 0.3%)`, STT 0.1% both legs, stamp 0.015% on buys, GST 18% on brokerage + exchange + SEBI + IPFT, integer paise. DP is once per ISIN per sell day, currently charged to the first overnight sell rather than pro-rata.
- Holiday calendar through 2026-12-31, including the 8 Nov 2026 Muhurat window 14:20–15:15. That window is a tradable special session. It is not yet excluded from indicators.
- Allowlisted `paper_events` audit, spool, export, and the session guardian heartbeat.
- Working tree, tested on Linux: `floor(₹50,000 / fill price)` and `UNAFFORDABLE_ZERO_SHARES` (signal stays pending). Sleeve cap of 9 inside the fill write transaction, cause `SLEEVE_SLOT_FULL` (signal stays pending). Sells are not blocked by the cap. Monitor runs exits before entries, then hash order, then strategy number.

## Exists but must change

- `paper_fills` has no `execution_path`. Every fill is an implicit LTP. Group A adds the column and writes `LTP_LEGACY` until Group D selects the open.
- Decision logs cannot be reconstructed. `paper_events` is an allowlisted stream. `logs/engine.jsonl` is a side file. There is no `correlation_id` and no SHA-256 hash chain. Group A adds `paper_decisions`.
- DP attribution is first-sell, not pro-rata across the strategies that sell that ISIN that day (`charge_policy.json` assumptions). Update when sleeve cash exists.
- `engine.py` `_monitor` Strategy 07 stop, in Group H only.
- `src/App.jsx` still says one share per strategy-symbol. Leave that sentence until the bot box runs this engine.
- `paper_scan_batches.report_json` stores the live symbol funnel. It is not the ADV-impact funnel or the signal-overlap matrix (Group I).

## Missing (freeze action plan)

- Group A: `execution_path`; append-only decision log; correlation id; hash chain.
- Group B remainder: ISIN cap `ISIN_CAP`; sleeve cash and `INSUFFICIENT_CASH`; shadow ledger that does not consume the ISIN cap; pro-rata DP.
- Group C: lagged 20-day median ADV floor (do not freeze the ₹10 crore cutoff until the funnel report is reviewed); participation cap `ADV_PARTICIPATION_CAP` on entries only; tiered slippage and 1.5× stress.
- Group D: official open or tagged `FALLBACK_OPEN`; bhavcopy comparison; path selected per fill.
- Group E: directional circuits, `pending_exit`, upper-circuit buy expiry at t+1, EQ→BE/BZ, ASM/GSM, gap-aware stops.
- Group H: bar-only Strategy 07 stop, version, evidence-clock reset.
- Group I: ADV funnel and overlap matrix, Muhurat excluded from indicators, public gross/survivorship labels, headline P&L from the capped ledger.
- Section B reconciliation (last complete month, 260-bar warmup, Stage A and Stage B) runs after A–I. It needs Turso history and NSE bhavcopy. It is not the unit suite.

## Missing (support agent)

The agent is read-only on trading state. It does not exist yet.

- `guardian.py` already heartbeats and bounds sessions. `audit.py` already stores `paper_events` and can replay a spool.
- No `support_findings` table, no consumer checkpoint, no detectors (coverage gap, incomplete lifecycle, unexpected skip, placeholder text, reconstruction failure, monitor staleness, named-cause dump), no immutable status events, no session report, no observation-only flag.
- Implement A1–A6 only after the freeze decision log exists, so detectors can group on `correlation_id`.

## Task order

1. Group A — schema and decision log.
2. Group B remainder — ISIN cap, sleeve cash, shadow ledger, pro-rata DP.
3. Groups C through I in that order.
4. Reconciliation harness to the extent the local fixtures allow. A live Turso month replay waits on the bot database.
5. Support agent A1–A6, then its tests.

Do not deploy to the bot box from this repo. A GitHub push does not install `/workspace/paper-trading`.

## Hardcoded-value audit and checklist status (9 Nov 2026, after hours)

### Where every number now lives
| Kind | File | Notes |
|---|---|---|
| Capital, sizing, caps, ADV, participation, slippage, pause thresholds, circuit haircut | `capital_policy.json` | `value_provenance` lists which are locked freeze placeholders, which the engine chose where the plan is silent (`ucb_one_sided_z`, `circuit_lock_haircut_pct_per_extra_day`, `slot_order_seed`), and which wait on the user (`adv_floor_inr` review, `hysteresis_shadow_trades`). |
| Charge rates (brokerage, exchange, SEBI, IPFT, STT, stamp, GST, DP) | `charge_rates.json` (numeric) + `charge_policy.json` (dated text) | `fees.mjs` reads exact fractions; fails closed if `charge_rates.json` names a different charge-policy version. Verified identical fees/slippage on 160,000 random cases vs the previous code. |
| Session times, completed-bar cutoff, Muhurat indicator exclusion, Strategy 07 trail fraction, Fyers routes/pacing, guardian timings, reconciliation warmup, reference-feed URLs | `config.json` | Strategy 07 trail fraction must equal the frozen rule text (`.9*H`) or the engine refuses to start. |
| Lock | `freeze_lock.json` | SHA-256 of the three policy files. `engine.py` (via `capital.assert_freeze`) and `db.mjs` both refuse to run on a mismatch. Change = edit JSON + `python3 capital.py --print-lock` + commit; no code edit. |

`capital.assert_freeze` and `db.mjs` no longer repeat policy numbers (the old `!==9`, `!==3`, `!==100000000`, `!==0.005`, `500000`, `1475`, `LIMIT 20`, `.9*` literals are gone). Remaining guards are structural (sleeves sum to master, fee headroom, cause names) or capability guards (`adv_lag_sessions` must be 1; `hysteresis_shadow_trades` must stay null until the user specifies the reinstatement rule). `tests/test_hardcode_audit.py` scans the engine sources and fails if any of those literals return.

### Genuine bugs fixed
- Exit orders passed a fixed `quantity=1` to `db.mjs`; the fill used the stored position size but the order audit logged 1 share. Exits now pass the real open quantity.
- `UNAFFORDABLE_ZERO_SHARES` decision payload used the variable `quantity` (0) as a key instead of `'quantity'`.
- Muhurat date `2026-11-08` was a literal in `engine.py` and `prefilter.py`; ADV window excluded every `special_sessions` date. All three now read `config.json` `indicator_excluded_sessions`.
- Scan report hard-coded `excluded_audit_symbols: 59` / `original_audit_universe: 751`; now counted from the files.
- Qualifier plan text still said entries fill at "First fresh ... LTP"; now describes the official-open path.
- `reconciliation.run_harness` defaulted `trade_date` to `2026-11-09` (test value in production code); now required for a bhavcopy compare.
- Guardian timings were literals despite `guardian_seconds` in config.
- Dashboard copy repeated ₹35,00,000 / ₹5,00,000 / ₹50,000 / 9 / 3 / ₹10 crore / 0.90; now rendered from `capital_policy.json` and `config.json` (`src/policyText.js`).
- Corporate-action, ASM/GSM and BE/BZ guards had code but nothing ever loaded data into `paper_corporate_actions` / `paper_price_bands`. `reference_feeds.py` now loads NSE corporate actions, NSE ASM/GSM and the Fyers symbol master during `scan --sync` (and `run.sh reference-feeds`). Fail-soft; special/unparsed dividends go to manual review because the plan never defines "extraordinary".

### Checklist A (features)
| Item | Status | Evidence |
|---|---|---|
| A1 capital, sleeves, 9 slots, ISIN cap 3, shadow ledger, kills by book, capped headline | Done | `capital.py`, `db.mjs` fill path, `pauses.py`, `automation.finance`; tests `test_capital`, `test_engine`, `test_pauses` |
| A2 ADV floor, participation, ordering, integer shares, skip logging | Done in code; ADV ₹10 cr floor is a **placeholder pending user review** of the funnel report | `capital_policy.json adv_floor_review=pending_funnel_report` |
| A3 tiered slippage, stress, STT/stamp/GST, DP pro-rata, STT rounding, dated config rates | Done | `charge_rates.json`, `fees.mjs`. DP uses the dated Fyers ₹12.50+GST, not the plan's approximate "₹13.5–18.5". |
| A4 official open, fallback tag, execution_path, bhavcopy compare | Code done; **bhavcopy archive download blocked (HTTP 403 from this machine)** | `execution_reference`, `bhavcopy_compare.py` |
| A5 Strategy 07 completed-bar stop | Done as implemented: stop level from completed closes only; open gap fills at open, intraday touch fills at the fixed stop level (frozen research rule). **User should confirm** this reading of "intraday polling is display-only". | `strategy_rules.json 7`, `_monitor` |
| A6 circuits, pending_exit, t+1 expiry, BE/BZ, ASM/GSM, gap stops, haircut | Code done; data now loaded by `reference_feeds.py`. NSE ASM/GSM endpoints are intermittent (403) from this machine; the "fallback scaled to band width" heuristic is a flat-bar flag only. | `market_guard`, `reference_feeds.py` |
| A7 corporate actions | Done; rights/merger/demerger/special dividends to manual review | `corporate_actions.py`, `reference_feeds.py` |
| A8 kill/pause | Done except **hysteresis N (plan never sets it)**: strategy reinstatement is manual-only | `pauses.py` |
| A9 Muhurat calendar entry, holiday scheduler | Done; config-driven | `config.json` |
| A10 funnel/overlap, version hash, labels, skip causes | Done; funnel report exists, **review by user pending** | `automation.funnel/overlap`, dashboard labels |

### Checklist B (tests)
| Item | Status |
|---|---|
| B1 reconciliation month | **Blocked**: no complete live month (live logs start 7 Nov, first fills 9 Nov) and NSE bhavcopy archives return 403. Harness exists and refuses to claim acceptance. Two-day Stage A check: 6 Nov exact match; 8 Nov differences are all the Muhurat exclusion. |
| B2 capital/sizing | Unit-tested |
| B3 execution/microstructure | Unit-tested; live official-open fills start 11 Nov |
| B4 kill/pause | Unit-tested except hysteresis N (undefined) |
| B5 reporting | Funnel + overlap generated; dashboard labels tested; funnel review pending |
| B6 acceptance | Not claimable until B1 and the two user decisions are closed |
