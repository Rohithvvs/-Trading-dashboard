# Freeze upgrade and support agent — progress

Branch: `freeze-strategies-upgrade`. Updated 2026-11-09.

Source of truth: Implementation Action Plan `1D9BKMAUvEskfOUNzAav42AcKlzmuVIneNQ1C7QTP7BY`, then Support Agent plan `1wxsNpjuDTratWW4bbua0YifSj_GK8FYYp9LgZnG_2U0`.

The engine is not installed on the bot box.

## Section 0

- [x] Gap analysis written (`GAP_ANALYSIS.md`)
- [x] Strategy 07 timing checked: live monitor fills on polled LTP; frozen rule is completed-bar / next-open. Group H only.

## Task Group A — schema and logging

- [x] `execution_path` on every fill (`LTP_LEGACY` until Group D)
- [x] `paper_decisions` append-only hash chain and `correlation_id`
- [x] One sample decision reconstructs from the table alone

## Task Group B — capital and sizing

- [x] Master ₹35,00,000, sleeve ₹5,00,000, target ₹50,000, `floor(notional / price)`, `UNAFFORDABLE_ZERO_SHARES`
- [x] Max 9 open positions per sleeve, `SLEEVE_SLOT_FULL`, count inside the fill transaction
- [x] Exits first, then `sha256(session|symbol|freeze_capital_v1)`, then strategy 01–07
- [x] ISIN cap 3, `ISIN_CAP`
- [x] Sleeve cash, `INSUFFICIENT_CASH`
- [x] Shadow ledger does not consume the ISIN cap. ISIN-blocked buys are recorded there. Shadow-only exits are still open.
- [x] Pro-rata DP. One ₹14.75 charge per ISIN per sell day, turnover-weighted. Remainder paise go to the latest sell.

## Task Group C — ADV, participation, slippage

- [x] ADV floor placeholder ₹10 crore, lagged 20-session median, `ADV_FILTER_SKIP`. Review status remains `pending_funnel_report`. Exits are not filtered.
- [ ] Participation cap, entries only, exits never skipped
- [ ] Tiered slippage and 1.5× stress

## Task Group D — open price

- [ ] Official open or `FALLBACK_OPEN`
- [ ] `execution_path` selected per fill
- [ ] Bhavcopy comparison script

## Task Group E — microstructure

- [ ] Directional circuits, `pending_exit`, series, ASM/GSM, gap-aware stops

## Task Group F — corporate actions

- [ ] Split/bonus scaling, fractional cash credit, dividends, manual review

## Task Group G — kill and pause

- [ ] 10% sleeve, 30-trade UCB, shadow hysteresis, 8% system, 3% reinstatement

## Task Group H — Strategy 07

- [ ] Completed-bar stop only, formula unchanged, version and evidence clock reset

## Task Group I — reporting and sessions

- [ ] Funnel report and overlap matrix
- [ ] Muhurat excluded from indicators
- [ ] Public labels and capped headline P&L

## Acceptance

- [ ] Stage A / Stage B reconciliation (needs Turso logs and bhavcopy; not claimed from unit tests)

## Support agent

- [ ] A1 schema
- [ ] A2 consumer
- [ ] A3 detectors
- [ ] A4 reporter
- [ ] A5 schedule
- [ ] A6 observation mode
- [ ] B tests
