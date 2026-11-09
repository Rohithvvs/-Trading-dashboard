# Funnel, ADV impact and paper-parity check — 9 Nov 2026

Paper only. Read-only SELECTs against Turso `paper_v1`; no fills, signals or prices were written or changed. Today's 17 `LTP_LEGACY` 1-share fills are untouched.

## 1. ADV floor impact (₹10 crore placeholder, still `pending_funnel_report`)

Rule: median of the last 20 regular sessions of traded value, lagged one day, for the next session (11 Nov 2026). Universe 692 symbols.

| Floor | Symbols removed (data as installed at `3f7a7c7`) | Symbols removed (after the turnover-gap fix) |
|---|---|---|
| ₹5 cr | 85 below + 495 history-short = 580 | 120 (17%) |
| **₹10 cr** | **125 below + 495 history-short = 620 (90%)** | **221 (32%)** |
| ₹20 cr | 146 below + 495 history-short = 641 | 334 (48%) |

Universe ADV distribution (close × volume, ₹ crore): p5 2.15, p10 3.34, p25 7.17, median 21.58, p75 89.75, p90 208.76.

Signals and Stage-1 passers (₹10 cr, after the fix):

| Completed bar | Prefilter PASS | Removed by ADV | Qualified signals | Removed by ADV |
|---|---|---|---|---|
| 6 Nov 2026 | 11 | 2 | 15 | 2 |
| 8 Nov 2026 (Muhurat) | 12 | 2 | 17 | 2 |

Removed at ₹10 cr: PDSL (₹2.53 cr) and PRINCEPIPE (₹5.72 cr). At ₹5 cr only PDSL is removed; at ₹20 cr three signals are removed.

### Data gap found and fixed
`daily_ohlcv.turnover` is NULL on many recent rows (e.g. only 186 of 877 rows on 19 Oct). The installed ADV gate required 20 non-NULL turnover rows, so **495 of 692 symbols would have been skipped as `lagged_adv_history_short`** — 8 of today's 17 signals for missing data alone. Where turnover is present it equals `close × volume` exactly (ratio 1.000 on every source), so the gate and the funnel now use `COALESCE(turnover, close × volume)` when volume > 0, record `derived_close_x_volume_sessions`, and leave zero-volume/NULL rows as missing (still history-short, never invented). The 8 Nov Muhurat session is excluded from the ADV window, matching the indicator exclusion. The ₹10 crore number itself is unchanged and still pending review.

Caveat: close × volume approximates NSE's official traded value (bhavcopy total traded value); it could not be cross-checked because NSE archives return HTTP 403 to this machine.

## 2. Signal-overlap (8 Nov bar)
12 stocks, 17 strategy-signals: 7 stocks single-strategy, 5 stocks exactly two (ADANIPORTS, ANGELONE, GRWRHITECH, MOTILALOFS: S1+S7; MAHABANK: S4+S7). None exceed the 3-strategy ISIN cap.

## 3. Stage A — signal replay (guards off)
Installed freeze code replayed from Turso history (from 2024-01-01) against the stored live screens.

| Bar | Prefilter match | Strategy-symbol match | Divergences |
|---|---|---|---|
| 6 Nov 2026 | 692/692 | 4,844/4,844 (100%) | 0 |
| 8 Nov 2026 | 692/692 | 4,827/4,844 | 17 — all 17 stored qualifiers; every one maps to `SPECIAL_SESSION_EXCLUDED` (Muhurat bar no longer produces entries) |

Consequence: under the freeze rules today's 17 entries would not have been generated, because their signal bar was the Muhurat session. They stay recorded as legacy `LTP_LEGACY` fills and are not rewritten.

## 4. Stage B — counterfactual for today's 17 entries (guards on)
If the bar had been eligible: 14 would fill at floor(₹50,000 / price) (e.g. ADANIPORTS 25, DLF 66, GRWRHITECH 6, MAHABANK 578/576 shares), PDSL and PRINCEPIPE → `ADV_FILTER_SKIP`, ANGELONE S7 → `SLEEVE_SLOT_FULL` (10th S7 entry in hash order). No `ISIN_CAP`, `UNAFFORDABLE_ZERO_SHARES` or `ADV_PARTICIPATION_CAP`. Open-price parity (`OFFICIAL_OPEN_DIFF`) is not testable for these fills: they were LTP fills and no bhavcopy is available.

## 5. Live-month reconciliation — blocked
- No complete live month exists: the `paper_v1` live logs start 7 Nov 2026 (first scan/monitor runs) and the first fills are 9 Nov 2026. October 2026 has no live signal or fill logs to reconcile against.
- NSE bhavcopy archives (`nsearchives.nseindia.com`, both the CM UDiFF zip and `sec_bhavdata_full`) return HTTP 403 Access Denied to this machine, so vendor-open vs bhavcopy-open and official traded value cannot be checked.
- Earliest possible: a complete live month after 30 Nov 2026 (December), plus a bhavcopy source that this machine can reach or files uploaded to it.

## 6. Still pending (not invented)
- ADV floor number: ₹10 cr stays a placeholder (`pending_funnel_report`) for the owner's review.
- Pause hysteresis N: unset (`hysteresis_shadow_trades: null`); reinstatement is manual.
- Prefilter still reads the Muhurat row (beta/SMA/returns); only strategy indicators and now ADV exclude it. Owner decision whether Stage-1 should exclude it too.
