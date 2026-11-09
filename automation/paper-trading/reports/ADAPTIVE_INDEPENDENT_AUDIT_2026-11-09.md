# Adaptive (Track B/C) engine: independent audit, 9 Nov 2026

Tested: `main` at 4a6c382 (adaptive code from 82dfdd4 plus the freeze commits). Isolated clone at `/workspace/adaptive-test`.
The live runtime `/workspace/paper-trading` was not touched, and no engine lock was taken.

## Verdict
**Not complete, and not trustworthy for promotion yet.** All 21 original adaptive tests passed, but they never ran the
simulator (`simulate_track_window` had no test), and they called the gates directly on freshly spawned candidates.
This audit found and fixed 12 reproducible defects. Several plan items are still library stubs (see Open items).
Adaptive code is **not wired** into `run.sh`, `engine.py`, `db.mjs` or any routine, and has no order or broker path.
Observation-only remains the default.

## Defects found and fixed (each pinned by `tests/test_adaptive_independent_audit.py` or `tests/adaptive-read.test.js`)
1. **Cost model copied wrong literals.** DP was ₹14.75+GST against the frozen ₹12.50+GST, exchange/SEBI were 0.00345% against 0.0031709%, there was no stamp duty on buys, and buys were charged sell-side STT+DP. Slippage tiers and the ₹20 cr ADV default were hardcoded. Charges and slippage now come from `charge_rates.json` and `capital_policy.json` and match `fees.mjs` exactly (checked against node).
2. **ADV floor and participation cap were ignored** in the simulator. They now use the same lagged-median ADV as `db.mjs laggedAdv()`, and skip causes are recorded.
3. **Gates could run before the window ended and more than once** (peeking). They now require status `EVALUATING` from the stopping rule, and a second evaluation is refused.
4. **`INCONCLUSIVE` could be reopened** to `EVALUATING` by calling the stopping rule again. Terminal statuses are now final.
5. **Gate 7 rubber-stamped every microstructure lock** (all defaulted to True). The simulator now reports the locks it enforced, and a missing lock fails Gate 7.
6. **A live Track C champion could be bypassed.** The superiority test was optional, and its trial was not counted in Gate 2's K_cand. It is now mandatory when a champion exists and is counted (K_cand+1).
7. **Promotion ignored a champion promoted after the challenger's gate run.** Promotion now blocks with `incremental_superiority_vs_current_track_c_not_tested`, and also requires a gate-passed Track B candidate.
8. **Track B slot reuse overwrote a live challenger row** (`INSERT OR REPLACE` on `active_count+1`). New spawns now take the lowest free slot.
9. **Fractional values for integer parameters** were silently truncated later (for example `entry_lookback=20.5`). They are now rejected.
10. **A missing PIT Bhavcopy SERIES silently became `EQ`.** It is now `UNKNOWN`, and new entries are blocked (`PIT_SERIES_UNKNOWN`).
11. **Silent sigma defaults:** probation used 0.002 and tuning used 0.001 when history was short. Both now raise. A calibration re-run could also reset a spent holdout vault's flags. That is now refused.
12. **The dashboard read API queried columns that do not exist** (`track_id`, `seq_id`, `k`/`v`, ...). It was caught by `catch{return def}`, so the Tracks A/B/C tab always showed empty defaults. The SQL now uses the real schema columns, and errors surface as `read_error`. UI copy that described rules the code doesn't implement was corrected.

Hardcoded values: every adaptive number now lives in `adaptive_policy.json`, labelled `plan`, `plan_example` or
`placeholder_pending_review`, and validated by `adaptive_policy.py`, which fails closed. The Strategy 07 trail ratio is read
from `config.json`. The harness hash now covers all adaptive modules and the policy. Track A locked files were only read.

## Placeholders the plan does not specify (need your decision before any promotion)
Gate 9 minimum effect is 2 bps/day. The Gate 2 cost hurdle is 1 bp/day. Gate 1 requires at least 10 total trades and at
least 3 distinct entry weeks. Gate 3 has a 0.5% DD floor. The Gate 4 beta-stability limits are SE≤0.5 and Δβ≤0.75. The
Gate 5 limits are n≥6, |ρ1|<0.95 and half-mean ≥ −25%. Probation is 60 days (trend) and 30 days (fast). The meta-kill
switch needs at least 20 days and t≤−1.0. The observation period is 15 sessions. The trend warm-start default is 110 days.
The bootstrap uses 5-day blocks, 500 draws and a 90% CI. Calibration uses 400 simulations.

## Open items (not fixed; these are plan gaps, not bugs I could safely patch)
- **No orchestration.** Nothing spawns challengers, runs daily shadow simulations, writes `adaptive_daily_returns` (no code writes it), or schedules final-day evaluation. Adaptive is a tested library, not a running engine.
- **Gate 8 placebo** repeats "spawn-time screening" only over a caller-supplied pool. By default it uses only the observed candidate, and it permutes or sign-flips daily d_t instead of jittering discordant trades.
- **Gate 6 plateau:** no code generates neighbour parameter runs. The caller passes numbers in.
- **The Track A replica differs from live Track A.** The simulator re-implements execution and has no cross-strategy ISIN cap, kill-pause, shadow ledger or aggregate participation. d_t is measured against this replica, not the live ledger.
- **E0 is net of haircut, but daily equity is gross.** The first evaluation-day return includes the haircut as a gain, in both arms. This needs a decision.
- **"CI" look-ahead pass** is a DB flag that any caller can set. The repo has no CI workflow. The truncation test is weak because `back_adjust_ohlc_pit` itself truncates at as_of.
- **Calibration** power uses iid sigma, not HAC. Oldest-partition enforcement is a name check only. Promotion does not require the holdout vault result.
- **The observation period** is a caller-supplied session count, not derived from logged sessions.
- **Acceptance tests** use synthetic return arrays. No end-to-end test goes from simulation through gates to promotion on simulated trades.
- **No populated multi-year PIT Bhavcopy or prefilter archive exists yet** (the tables exist).
