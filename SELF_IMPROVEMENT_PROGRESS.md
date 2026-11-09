# Self-Improvement (Adaptive 3-Tier) Progress

Branch: `self-improvement-adaptive` (from `freeze-strategies-upgrade`)  
Updated: 2026-11-09

## Section 0: Pre-Implementation Review and Task Planning
- [x] 0.1 Review Current Implementation (`engine.py`, `strategy_rules.json`, `strategy_indicators.py`, `prefilter.py`, cost model, `schema.sql`, `corporate_actions.py`, `pauses.py`, `support_agent.py`)
- [x] 0.2 Decide New vs. Updated Features (`SELF_IMPROVEMENT_GAP.md`)
- [x] 0.3 Create Small Tasks with clear definitions of done (`SELF_IMPROVEMENT_GAP.md`)
- [x] 0.4 Build One Task at a Time (in progress)

## Implementation Sequence (Section A8 & Section B)
- [x] Task 1 (A8.1 / A2 / B1): Point-in-time prefilter (`daily_prefilter_universe`) + Bhavcopy `SERIES` archive (multi-year) (`pit_archive.py`, `schema.sql`, `tests/test_pit_archive.py`)
- [x] Task 2 (A8.2 / A7 / Logging): Schema with `K_eff`, hashes, net-of-haircut starting equity, and SHA-256 hash-chained skill-enhanced adaptive logging (`schema.sql`, `adaptive_logging.py`, `tests/test_adaptive_schema_logging.py`)
- [x] Task 3 (A8.3 / A1 / A2 / A3 / B2): 3-tier engine, independent track capital, tier-specific warm-start lengths (60d / 100–120d), PIT data, net-of-haircut re-baseline, inherited discordant trade split, indicator back-adjustment, and target windows (45d/75d + single +15d extension -> `inconclusive`) (`adaptive_engine.py`, `tests/test_adaptive_engine.py`)
- [x] Task 4 (A8.4 / A4 / B3): Trial counting (`K_cand`, `K_eff` linear formula with $\bar{\rho} \le 0.9$) and explicit link to effective critical value in Gate 2 (`trial_counting.py`, `tests/test_trial_counting.py`)
- [ ] Task 5 (A8.5 / A5 / B3): Paired daily active return $d_t$, HAC $t$-stat, residualized $d_t$ check, Gate 4 binding $\alpha$, and block-bootstrap capital-day expectancy
- [ ] Task 6 (A8.6 / A5 / B3 / B5): Atomic Gates 1, 3, 5, 6, 7, 8 (250 seeded placebos including selection process, jittering only discordant trades), 9, incremental superiority vs Track C, and Track C probation
- [ ] Task 7 (A8.7 / A6 / A7 / B1 / B4): Calibration harness with go/no-go ~30% power floor, oldest-partition tuning, single-touch holdout vault, meta-kill switch, and CI look-ahead truncation test (price + corporate actions)
- [ ] Task 8 (A8.8 / A6 / B4): Observation-only mode and promotion lock (requires calibration pass + CI look-ahead pass + observation period)
- [ ] Task 9 (A8.9 / B6): UI and read API for Tracks A, B, and C status, logs, and controls
- [ ] Task 10 (A8.10 / B1–B6): Full checklist verification and acceptance criteria
