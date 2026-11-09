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
- [x] Participation cap 0.005 × ADV, entries only, skip not scale, `ADV_PARTICIPATION_CAP`. Exits are not skipped.
- [x] Tiered slippage. 8 bps through ₹20 crore, 5 bps above, plus 10 × notional / (0.005 × ADV). Stress 1.5× is implemented and off. Share count stays on the reference price.

## Task Group D — open price

- [x] Official open or `FALLBACK_OPEN`. Fyers `open_price` is `FEED_OPEN`. Auction equilibrium is used only when that open is missing. A first trade with no open is `FALLBACK_OPEN`. No open stays `LTP_LEGACY`.
- [x] `execution_path` selected per fill. Share count and slippage use that reference. Polled stops still use the last trade.
- [x] Bhavcopy comparison script (`bhavcopy_compare.py`). Differences are `OFFICIAL_OPEN_DIFF`. The report is append-only and hash-chained. It does not change fills.

## Task Group E — microstructure

- [x] Directional circuits, `pending_exit`, series, ASM/GSM, gap-aware stops. Upper blocks buys through the session close. Lower locks the exit until a clear session. Haircut is 1% per locked session after the first. BE/BZ blocks entries and sells use the locked 1.5× stress multiplier. A missing band is not a lock.

## Task Group F — corporate actions

- [x] Split/bonus scaling, fractional cash credit, dividends, manual review. Quantity is floored. The fractional share is credited once the post-adjustment open exists. Cash dividends do not scale prices. Rights, demergers, and mergers stay `CORP_ACTION_MANUAL_REVIEW`. Credits are visible to `INSUFFICIENT_CASH`.

## Task Group G — kill and pause

- [x] 10% sleeve drawdown on the shadow book, 30-trade one-sided 95% UCB (the freeze does not name the critical value), strategies 03 and 05 are drawdown-only. Pause blocks new entries and still allows exits. Shadow entries continue and do not consume the ISIN cap. Strategy reinstatement is manual only: hysteresis N is not in the freeze, so it is not invented. System pause is 8% of the capped book and reinstates within 3% of the pre-pause peak, or by manual override. Peak resets on reinstatement.

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
