# Self-Improvement (Adaptive 3-Tier) Gap Analysis

Date: 2026-11-09  
Branch: `self-improvement-adaptive` (branched from `freeze-strategies-upgrade`)  
Sources of Truth:
- Self-Improvement Definitive Coding-Ready Plan (`15Sk6te6O6BAQtxa1zfSy4eeD_gbghdUqPMVr3UhrcIk`)
- Self-Improvement Plan – Implementation and Testing Checklists (`1_mLz_ACCcdIh4l1boTW9T9ARBHJ8N7Q0SzDJtfcL1g4`)
- Self-Improvement Plan – Comprehensive Logging Specification (`19m4K52UT5nM-_pTQTtpsAEyIqt12IqU9TUV1NuHrBOw`)

---

## 0.1 Review of Current Implementation (`freeze-strategies-upgrade`)

1. **Paper-Trading Engine (`automation/paper-trading/engine.py`, `db.mjs`, `automation.py`)**:
   - Implements single-track paper execution (`namespace = 'paper_v1'`) for Strategies 1–7.
   - Enforces next-session open fills (`FEED_OPEN`, `AUCTION_CAPTURE`, `FALLBACK_OPEN`, `LTP_LEGACY`), Strategy 07 completed-bar trailing stops (`trail_gap` -> queued SMA50 open exit -> `trail_touch`), and Muhurat (`2026-11-08`) indicator exclusion.
2. **Strategies & Prefilter (`strategy_rules.json`, `strategy_indicators.py`, `prefilter.py`, `prefilter_policy.json`)**:
   - Seven frozen baseline strategies and Stage-1 `beta_momentum_v1` prefilter exist.
   - `strategy_indicators.py` currently uses fixed baseline parameters only and does not accept parameter-only challenger overrides or perform point-in-time ex-date indicator back-adjustment on raw unadjusted history.
   - `prefilter.py` stores `paper_prefilter_states` per scan date, but there is no multi-year point-in-time `daily_prefilter_universe` + daily Bhavcopy `SERIES` archive table/module for historical warm-starts.
3. **Capital, Cost Model, Microstructure & Corporate Actions (`capital.py`, `fees.mjs`, `corporate_actions.py`, `pauses.py`)**:
   - Enforces ₹35,00,000 master / ₹5,00,000 sleeve / ₹50,000 target notional, 9 slots/sleeve, 3 strategies/ISIN, lagged 20-day median ADV floor, 0.5% ADV participation cap, tiered slippage with 1.5× stress, circuit locks (`UPPER`/`LOWER`, `pending_exit`, 1%/day haircut), `BE`/`BZ` entry blocks and 1.5× exit slippage, `ASM`/`GSM` blocks, and ex-date position/state scaling (`corporate_actions.py`).
4. **Turso Schema & Logging (`schema.sql`, `audit.py`, `support_agent.py`)**:
   - `paper_events` (allowlisted event stream) and `paper_decisions` (SHA-256 hash-chained `ENTRY`/`EXIT`/`SKIP`/`HOLD` log with `correlation_id`) exist for the single baseline track.
   - `support_agent.py` consumes `paper_events` and `paper_decisions` in read-only observation mode.
   - No schema tables or modules exist yet for Track A/B/C isolation, candidate spawns, warm-starts, $K_{\text{eff}}$, Atomic Gates 1–9, residualized $d_t$, calibration & holdout vault, probation, or meta-kill switch.

---

## 0.2 New vs. Updated Features

### Already Correct (No Change Needed to Frozen Baseline Logic)
- **Track A Frozen Baseline Rules**: The 7 frozen strategies in `strategy_rules.json`, Stage-1 prefilter rules in `prefilter_policy.json`, cost model in `charge_policy.json` / `fees.mjs`, and capital policy in `capital_policy.json` remain the permanent, unmutated Track A baseline.
- **Execution-Layer Microstructure Primitives**: Official open selection, circuit lock detection, 1%/day lower-circuit carry-forward haircut, `BE`/`BZ` entry blocking and 1.5× exit stress slippage, `ASM`/`GSM` restrictions, and Strategy 07 `trail_gap`/`trail_touch` priority.
- **Support Agent**: Read-only `support_agent.py` detectors and append-only `support_findings`.

### Existing Features That Must Be Updated
1. **Schema (`automation/paper-trading/schema.sql`, `engine.py`, `db.mjs`)**:
   - Add multi-year point-in-time archive tables (`daily_prefilter_universe`, `bhavcopy_series_archive`).
   - Add adaptive tables (`adaptive_tracks`, `adaptive_spawns`, `adaptive_warm_starts`, `adaptive_daily_returns`, `adaptive_gate_evaluations`, `adaptive_calibration_runs`, `adaptive_holdout_vault`, `adaptive_probation`, `adaptive_meta_kill`, `adaptive_audit_logs`) with $K_{\text{eff}}$, hashes (`harness_hash`, `data_snapshot_hash`), RNG seeds, net-of-haircut starting equity $E_0$, and SHA-256 hash-chained decision/lifecycle logging across Tracks A, B, and C.
2. **Corporate-Action Indicator Back-Adjustment (`corporate_actions.py` / adaptive engine)**:
   - Ensure point-in-time indicator back-adjustment on corporate-action ex-dates (scaling pre-ex-date OHLC history for indicator continuity only on or after `ex_date`, never before `ex_date`).
   - Distinguish signal-layer parameterization (Track B parameter-only variations) from execution-layer locks (next-open fills, costs, slippage, microstructure).
3. **Dashboard API & UI (`server/automation-read.mjs`, `src/LiveResults.jsx`)**:
   - Surface Track A (frozen baseline), Track B (challengers, warm-start, window progress, $K_{\text{eff}}$, gate evaluations), Track C (active champion, incremental superiority, probation, meta-kill switch), calibration status, and observation-only controls.
4. **CI / Test Suite (`package.json`, `automation/paper-trading/tests/`)**:
   - Wire automated look-ahead truncation tests (cutting both price and corporate-action data at $t$) into the test suite.

### Entirely New Features to Implement
1. **Point-in-Time Prefilter + Bhavcopy SERIES Archive (`pit_archive.py`)**:
   - Multi-year point-in-time `daily_prefilter_universe` and daily Bhavcopy `SERIES` storage and lookup with strict `trade_date <= as_of_date` enforcement.
2. **3-Tier Architecture & Track Isolation (`adaptive.py`)**:
   - Track A (permanent frozen baseline), Track B (max 2–3 concurrent parameter-only challengers per strategy, pure paper), Track C (max 1 champion per strategy, pure paper), with independent paper capital per track.
   - Spawn-time capture of `harness_hash`, `data_snapshot_hash`, `rng_seeds`, and full decision inputs.
3. **Tier-Specific Warm-Start & Net-of-Haircut Re-Baseline**:
   - Fast Swing tier (Strategies 3, 5): 60 trading days warm-start.
   - Trend / Momentum tier (Strategies 1, 2, 4, 6, 7): 100–120 trading days warm-start.
   - Uses PIT `daily_prefilter_universe` and PIT Bhavcopy `SERIES` on every historical date.
   - Values starting equity $E_0$ at evaluation window start **net of exit haircut** (modeled sell charges + exit slippage + any circuit haircut).
   - Counts discordant trades for inherited warm-start positions separately from newly entered evaluation-window discordant trades.
4. **Target Windows & Non-Informative Stopping**:
   - Target windows: 45 trading days (Fast Swing) / 75 trading days (Trend / Momentum).
   - At most one +15-day extension allowed, triggered only by trade-count floor or pre-registered regime flag.
   - If sample remains under floor after one extension -> `status = 'inconclusive'`.
   - Atomic gates evaluated once on the final decision day.
5. **Trial Counting ($K_{\text{cand}}$, $K_{\text{eff}}$) & Explicit Link to Gate 2**:
   - $K_{\text{cand}}$ counts only candidate evaluations eligible for selection (including Track C incremental superiority comparisons); excludes placebos, plateau neighbors, and shadow runs.
   - Linear formula: $K_{\text{eff}} = 1 + (K_{\text{cand}} - 1)(1 - \bar{\rho})$ with $\bar{\rho}$ clamped $\le 0.9$.
   - Effective critical value: $t_{\text{crit}} = \max\left(1.40, \Phi^{-1}\left(1 - \frac{\alpha}{K_{\text{eff}}}\right)\right)$ (and expected max $t$ under $K_{\text{eff}}$ null draws).
   - Gate 2 requires observed $t_{\text{HAC}} \ge t_{\text{crit}}$.
6. **Residualized $d_t$ Check & Atomic Gates 1–9**:
   - Paired daily active return $d_t = R_{\text{var},t} - R_{\text{base},t}$ (unlevered total portfolio MTM including cash).
   - Required residualized check: OLS regression of $d_t$ on benchmark index returns $R_{\text{idx},t}$; residual mean $\hat{\alpha}$ must be positive (or Gate 4 becomes binding when beta is stable).
   - Secondary metric: capital-day expectancy with block-bootstrap CI.
   - All 9 Atomic Gates: Gate 1 (sample size + $\ge 10$ new discordant trades + distinct entry weeks), Gate 2 ($d_t$ net of cost/slippage hurdle + $t_{\text{HAC}} \ge t_{\text{crit}}$ + residualized check), Gate 3 (guardrails: $\text{DD} \le 1.10\times$, single-trade $\le 35\%$), Gate 4 (benchmark $\alpha$), Gate 5 (stationarity), Gate 6 (parameter plateau $\ge 75\%$ retention), Gate 7 (microstructure stress: $1.5\times$/liquidity-scaled slippage, circuit carry-forward, gap-aware stops, ex-date indicator back-adjustment, EQ-only entries, higher BE/BZ exit slippage), Gate 8 ($M = 250$ seeded placebo runs repeating exact spawn-time screening and jittering only discordant trades, beating 90th percentile), Gate 9 (minimum effect size).
   - Incremental superiority vs Track C: paired $d_t$ test against current Track C with stated threshold (e.g. mean active return $\ge +0.35\text{ bps/day}$), counted as a trial in $K_{\text{cand}}$.
   - Track C probation (longer for trend; tolerance band calibrated to $\sim 2\sigma$ of historical tracking error).
7. **Calibration Harness, Holdout Vault, Observation-Only Mode & Meta-Kill Switch**:
   - Compute MDE from measured $\sigma$ of real $d_t$; inject smallest actionable edge; enforce go/no-go power floor ($\sim 30\%$) so power $< 30\%$ keeps pipeline `monitor_only` or lengthens windows.
   - Threshold tuning restricted to oldest calibration partition; holdout vault touched once (spent if calibration fails).
   - Observation-only mode enforced before enabling automatic promotion.
   - Meta-kill switch triggers if Track C champions fail to beat Track A over time.
8. **Skill-Enhanced Comprehensive Logging**:
   - SHA-256 hash-chained decision context, order lifecycle, spawn, gate evaluation, calibration, promotion, and probation logs with `correlation_id` and `spawn_id`, supporting full reconstruction and tamper verification.

---

## 0.3 Ordered Implementation Tasks (One Feature at a Time)

1. **Task 1 (A8.1 / A2 / A7)**: Implement point-in-time `daily_prefilter_universe` + Bhavcopy `SERIES` multi-year archive (`pit_archive.py`) and unit tests.
2. **Task 2 (A8.2 / A1 / A7 / Logging)**: Add Turso/SQLite adaptive schema (`schema.sql`) and SHA-256 hash-chained adaptive decision/lifecycle logger (`adaptive_logging.py`) with `K_eff`, spawn hashes/seeds, net-of-haircut starting equity $E_0$, and reconstruction verifier.
3. **Task 3 (A8.3 / A1 / A2 / A3 / A7)**: Implement 3-tier Track A/B/C engine, independent track paper capital, tier-specific warm-start (60d Fast Swing / 100–120d Trend), PIT data & ex-date indicator back-adjustment, net-of-haircut $E_0$ valuation, separate inherited discordant trade counting, and target windows (45d/75d + single +15d extension -> `inconclusive`).
4. **Task 4 (A8.4 / A4)**: Implement trial counting ($K_{\text{cand}}$ eligibility rules, linear $K_{\text{eff}} = 1 + (K_{\text{cand}} - 1)(1 - \bar{\rho})$ with $\bar{\rho} \le 0.9$, effective critical value $\max(1.40, t^*(K_{\text{eff}}))$, and explicit Gate 2 link).
5. **Task 5 (A8.5 / A5 Gate 2 & Gate 4)**: Implement paired daily active return $d_t = R_{\text{var},t} - R_{\text{base},t}$ (including cash), HAC $t$-statistic, block-bootstrap capital-day expectancy CI, required residualized $d_t$ check against index returns, and Gate 4 benchmark $\alpha$ binding logic.
6. **Task 6 (A8.6 / A5 Gates 1, 3, 5, 6, 7, 8, 9 + Track C Superiority & Probation)**: Implement remaining Atomic Gates (1, 3, 5, 6, 7, 8 with $M = 250$ seeded selection-aware placebos jittering only discordant trades, 9), incremental superiority vs Track C ($\ge +0.35\text{ bps/day}$, counted in $K_{\text{cand}}$), and Track C probation ($\sim 2\sigma$ tracking error band).
7. **Task 7 (A8.7 / A6 / A7 / B1 / B4)**: Implement calibration harness (MDE from real $d_t$, injected edge, $\sim 30\%$ power floor go/no-go rule, oldest partition tuning, one-touch holdout vault, meta-kill switch) and automated look-ahead truncation test (price + corporate actions cut at $t$) wired into CI.
8. **Task 8 (A8.8 / A6)**: Enforce observation-only mode (`adaptive_observation_only`) and promotion gate lock requiring calibration pass + CI look-ahead truncation pass + completed observation-only period before automatic promotion.
9. **Task 9 (A8.9 / B6)**: Update dashboard read API (`server/automation-read.mjs`) and UI (`src/LiveResults.jsx`) to display Track A/B/C status, logs, $K_{\text{eff}}$/gate diagnostics, calibration/vault state, and observation-only / meta-kill controls.
10. **Task 10 (A8.10 / B1–B6)**: Execute full verification suite across all Section B checklists (B1–B6) and finalize `SELF_IMPROVEMENT_PROGRESS.md`.
