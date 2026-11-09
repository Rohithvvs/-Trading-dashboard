# Gap analysis — freeze upgrade and support agent

Date: 2026-11-09. Repo: `vvsrohith9490870277-stack/-Trading-dashboard`. Core: `automation/paper-trading/`.

Sources: Implementation Action Plan `1D9BKMAUvEskfOUNzAav42AcKlzmuVIneNQ1C7QTP7BY`, Freeze Version `1wYCbiCCSCedPEhj_6lMV-gwr0CFG6SARyOX1yY20-oY`, freeze checklists `1TNprAJLI97dwMJkSFFUvrDumspayTA3_OVjyqO2SN_4`, freeze logging spec `1Zo9n9yfpUmtXAV6DNw1iIVtRGkRRcPzjKu5m3ojufqI`, Support Agent plan `1wxsNpjuDTratWW4bbua0YifSj_GK8FYYp9LgZnG_2U0`, support checklists `1mAT2hES_vNwJHXXjZuoXa5wqBYTNRYS0DBfLmoH-GtQ`, support logging spec `1juueVBRskwxHxXcFkZkK9L9yGB_6WP7g_XMvARPKouo`.

Locked numbers are not open for change: master ₹35,00,000, sleeve ₹5,00,000 × 7, target notional ₹50,000, 9 positions per sleeve, 3 strategies per ISIN, entry order exits then `sha256(session date, symbol, freeze_capital_v1)` then strategies 01–07.

Status: Task Groups A–G are implemented on `freeze-strategies-upgrade`. The ₹10 crore ADV floor is still `pending_funnel_report`. Nothing is installed on the bot box. Groups H–I, acceptance, and the support agent remain. BE/BZ exit slippage uses the locked 1.5 stress multiplier because the freeze requires higher exit slippage and does not give a separate rate. Split and bonus prices use half-up paise. A fractional share waits for the post-adjustment open. Strategy-pause hysteresis N is not numeric in the freeze, so automatic reinstatement from N shadow trades is not implemented. The 30-trade upper bound uses a one-sided 95% normal critical value because the freeze names the bound and the window but not the critical value.

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
