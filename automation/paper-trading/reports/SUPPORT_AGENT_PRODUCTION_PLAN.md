# Support Agent — Production Action Plan (Version 3)

Version 3, reconciled from the Claude and Gemini reviews: a read-only monitor flags breakage, independent verifier agents check every proposed fix, and nothing reaches the live paper runtime until you approve it in the evening report. **Plan only: nothing is built, installed or scheduled, and the Wednesday 11 Nov test is untouched.**

---

## Recommendation

**Two separate gates.**
Verifier agents decide whether a fix is good enough. You decide whether it gets installed. The Support Agent only detects and asks: three independent verifiers and a Reconciler must pass a fix, and the change then waits for your explicit approval in the evening report before installing in the 15:45–08:30 IST window.

The core of the design is still an expectation ledger: each expected job has a time and a grace, and absence past the grace is the finding. That's what catches failures like the 08:45 scan on 9 Nov, which left no failure event at all.

**New in v3:** the sidecar runs from a local systemd timer so it survives a Grok Bot outage; heavy fix and replay work happens only after 15:35; installs need a verified batch branch, a process quiescence gate and a policy-timed morning abort; verifiers see only the diff and raw script output; and the 9 Nov replay now expects two SEV1 findings (1-share fills, Strategy 7 over its slots).

---

## Hard limits

| Id | Limit |
| :--- | :--- |
| **H1** | No orders, paper or real, by the support or fix pipeline |
| **H2** | Support Agent never writes trading tables |
| **H3** | No change to Track A rules or locked policy files; no freeze-lock bypass |
| **H4** | No credentials in code, output, logs, reports or chat |
| **H5** | No email, Slack or external sends; Grok Bot chat only |
| **H6** | Install only 15:45–08:30 IST before a trading day, after your approval; not on holidays, not around the 11 Nov test |
| **H7** | No new hardcoded thresholds |
| **H8** | Holiday-aware schedules unchanged |

---

## What is watched

| Area | Detector | Sev | 9 Nov evidence |
| :--- | :--- | :--- | :--- |
| Pre-market scan | `scan_missed` | SEV2 | 08:45 scan failed |
| Worker | `worker_down` | SEV2 | No checks 09:15–12:27 |
| Worker errors | `error_taxonomy_gap` | SEV3 | 6 unclassified failures |
| Scan lock | `lock_blocked_gap` | SEV3 | Gaps of about 8 and 16 min |
| Quotes | `quote_batch_failed` + recovery | SEV3 | 30 s timeout at 14:09 |
| Quote source | `quote_field_regression` | SEV1 | `tt` vs `ltt` |
| Order gates | `duplicate_fill`, `asm_gsm_buy`, `sleeve_over_limit` | SEV1 | S7 got 12 buys vs 9 slots; ASM not evaluable for 9 Nov |
| Monitor coverage | `monitor_staleness` | SEV2 | First check 12:27:44, last 15:29:58 |
| Fill sizing | `fill_sizing_anomaly` (new v3) | SEV1 | 17 fills at 1 share; MAHABANK 86.49 implies 578 |
| Execution latency | `signal_to_fill_latency` (new v3) | SEV3 | 12:57:47 scan → 13:17:58 fill |
| Install pipeline | `install_aborted_process_active`, `install_rolled_back` | SEV2 | — |
| Policy hygiene | `policy_value_missing` (08:30, once per key) | SEV4 | — |
| Exits | `exit_path_unexercised` | SEV4 | No stop or target hit |
| Decision log | `reconstruction_failure` | SEV1 | — |
| EOD / ledger | `eod_missed`, `ledger_unreconciled` | SEV1–2 | EOD 16:17 ok |
| Reference feeds | `feed_http_403`, `feed_stale` | SEV3 | NSE 403 |
| Freeze integrity | `freeze_lock_mismatch` | SEV1 | — |
| Routines / usage | `routine_missed` | SEV2 | Usage outage |
| Box health | `disk`, `stale_lock`, `venv`, `clock` | SEV2 | — |
| Dashboard | `dashboard_health` | SEV3 | — |
| Support itself | `support_self_stale` | SEV2 | — |

- **SEV1** is correctness at risk and **SEV2** is coverage lost; you're told about both immediately.
- **SEV3** is degraded and goes in the next digest.
- **SEV4** is evidence only and goes in the post-EOD report.

---

## Detection, storage, dedupe

| Aspect | Specification |
| :--- | :--- |
| **Thresholds** | `support_policy.json` with its own lock, outside `freeze_lock.json`. Existing `config.json` keys are reused, not copied. Undecided values ship as `null` and are reported as missing, not guessed. |
| **Derived counts** | Universe size and strategy cells are computed from files, replacing the hardcoded `751` and `5257`. |
| **Store** | Local append-only, hash-chained `out/support/support.sqlite`, plus daily JSON and Markdown. Turso `support-ops` is optional later. |
| **Dedupe** | Absence findings are keyed on `session_day + expectation`. Repeats join an open episode, which closes on recovery. |
| **Escalation (v3)** | Episodes count `occurrence_count` and `cumulative_blind_seconds`; crossing the policy limits (proposed 600 s or 3 occurrences) lifts SEV3 to SEV2 and informs once. |
| **Null rule (v3)** | No `null` SEV1/SEV2 threshold before P2. A `null` SEV3/SEV4 value gives one SEV4 `policy_value_missing` per day and key at 08:30. |
| **Time (v3)** | `session_day` and every window use `Asia/Kolkata`; naive `datetime.now()`, `utcnow()` and SQLite `date('now')` are banned by an AST check. |
| **New policy keys (proposed)** | `heavy_work.start_after` 15:35, `install.max_seconds` 900, `install.morning_abort_at` 08:05, `episode.escalate_blind_seconds` 600, `episode.escalate_occurrences` 3, `latency.signal_to_fill_poll_multiple`. |
| **Read hygiene** | Local SQLite opened with `mode=ro`; `logs/audit-spool/` is read as files. |

---

## Informing and schedule

| IST | Run |
| :--- | :--- |
| **08:30** | Pre-open readiness |
| **09:05** | Scan verification |
| **Hourly 09:20–15:20** | Intraday digest, silent if nothing new |
| **15:40** | Close check |
| **16:35** | Post-EOD report |
| **16:45** | Evening daily report + install approval ask |
| **19:30, 21:30, 07:30** | Reminders, only if a batch is unanswered |

All of these are weekday-only and skip NSE holidays, with delivery to Grok Bot chat only. The 07:30 reminder runs on the next trading day, so Monday after a Friday batch.

The sidecar itself runs from a local systemd timer (cron fallback), not from routines, and writes a local heartbeat that the reports read to show blind windows. No public health endpoint; a dashboard banner is deferred to P5 behind auth.

### Wednesday 11 Nov
Nothing is installed or scheduled before or during the live paper test.

---

## Verifier agents

| Role | Checks | Power |
| :--- | :--- | :--- |
| **Proposer / Fix Agent** | After 15:35, drafts the fix in a worktree under `/workspace/support-work/` with a reproducing test, and tags its change class | Never touches live; never reviews itself |
| **Verifier 1 — Correctness** | Root cause, fix fits the finding, missing cases, over-engineering | `PASS` / `WARN` / `FAIL` |
| **Verifier 2 — Safety** | H1–H8, script results, install window | **Hard veto** |
| **Verifier 3 — Regression** | Full suites, virtual-clock replay of 9 Nov and later sessions, zero Track A diff, no duplicate findings, batch branch | `PASS` / `WARN` / `FAIL` |
| **Reconciler / Judge** | Merges verdicts after all are written | Best outcome is `READY_FOR_HUMAN` |
| **You** | Read the evening report | `APPROVE` / `DECLINE` / `HOLD` install; veto anytime |

1. Each verifier is a separate sub-worker in a fresh context and sees only the plan, finding, diff and raw artifacts, never another verdict, commit message or Proposer narrative.
2. No agent reviews its own work. Where possible, Verifier 2 runs on a different model family than the Proposer.
3. **Tools before opinions:** the order-route AST check, freeze-lock hash, locked-file diff, `gitleaks`, install-window and NTP checks, change-class and naive-clock AST checks, a comment-injection scan, the test suites and the replay diff run outside any LLM, write a read-only verdict file, and are binding.
4. Two change classes: `support_only` (support code only) and `engine_instrumentation_or_locking` (logging and lock paths in the engine), which needs a zero Track A diff, an AST proof that no signal, sizing or order function changed, and approval by change id.
5. V2 and V3 stay separate roles and the hash chain stays (Claude's C-10 was rejected); both are script-first.
6. A Verifier 2 `FAIL` is a veto. `MUST` items need unanimity; `SHOULD` items pass by 2 of 3, with dissent recorded; `NICE` items are advisory.
7. A `FAIL` on a `MUST` or safety item stops the change. The Proposer may revise once, and all verifiers then re-run from scratch. A second failure means `REJECT`, and the finding stays open.

There are two separate loops:
- **Code-fix loop:** finding → Proposer → verifiers → Reconciler → your approval → install.
- **Plan-document loop:** Claude → Gemini → Document Reconciler → plan version bump. Plan disagreements change this document, never code.

---

## Daily loop and your approval

1. **During the trading day (09:15–15:35):** Only the read-only sidecar runs. Nothing is built, replayed, installed or merged. Urgent SEV1 and SEV2 findings are still told immediately.
2. **After 15:35:** Proposer builds, suites and replays run under `nice`/`ionice` and a policy cap against a local snapshot, paused while EOD runs. Each change is verified alone, then the batch branch `support/batch-YYYY-MM-DD` as a whole. Anything not ready by 16:45 waits for the next report.
3. **16:45 evening report:** Today's issues, today's updates, every verdict, the batch id, and an explicit ask to approve the batch for next-day install. If nothing is ready, it's a short status and no reminders follow.
4. **Reminders:** 19:30 and 21:30 the same evening, then 07:30 the next trading day (Monday after a Friday, or the day after a holiday). At most three, never on weekends or holidays.
5. **Your reply:** `APPROVE <batch>`, `APPROVE <batch> C1`, `DECLINE <batch>` or `HOLD <batch>`, from your own chat message only. The batch id carries a hash of its commit list. Engine-class changes need approval by change id. Silence is never approval.
6. **Install slot:** 21:45 if approved by 21:30 (also on a Friday or holiday eve), or 07:50 on the next trading day if approved by 07:45. Done by 08:20; if not done by the policy abort time (proposed 08:05) it rolls back unconditionally.
7. **Pre-flight and install:** The local approval record in `support.sqlite` is the gate, not GitHub. NTP check, safety scripts on the exact approved SHAs, and a re-verify of the exact subset tree if you approved only some changes. Quiescence gate: no engine, scan, worker or guardian process or lock, else abort with SEV2 `install_aborted_process_active`. Then merge, install to `releases/<sha>`, smoke test, and roll back automatically on failure.
8. **Next session:** The detector must stay silent, and then the finding is `VERIFIED`.

Your approval is tied to the exact commits in the report, and any change after it voids the approval. A decline, a hold or a missed cutoff waits for the next evening report. Nothing is ever installed silently or during market hours.

---

## Architecture

```mermaid
flowchart LR
    Engine["Frozen engine (scan, worker, guardian, EOD)"] -->|events (read)| Sidecar["Support sidecar (read-only, local systemd timer)"]
    Sidecar -->|finding| Proposer["Proposer (isolated worktree)"]
    Proposer -->|diff + raw script output| Verifiers["Verifier 1–3 (independent sub-workers)"]
    Verifiers -->|verdicts| Reconciler["Reconciler (READY_FOR_HUMAN)"]
    Reconciler -->|16:45 report| You["You (evening approval)"]
    You -->|"APPROVE (quiescence gate)"| Install["Install + smoke (15:45–08:30 window)"]
    Install -->|release switch| Engine
```

---

## Phased delivery

| Phase | Earliest | Acceptance |
| :--- | :--- | :--- |
| **P0 Review** | Now–11 Nov | Plan signed off; Wednesday undisturbed |
| **P1 Foundations** | 12–13 Nov | Virtual-clock 9 Nov replay yields exactly: SEV1 `fill_sizing_anomaly` and `sleeve_over_limit_new_buy`; SEV2 `scan_missed`, `worker_down` 09:15–12:27, `monitor_staleness`, `lock_blocked_gap` x2 (escalated); SEV3 `error_taxonomy_gap` x6, `quote_batch_failed` (recovered), `signal_to_fill_latency`; SEV4 `exit_path_unexercised`; `asm_gsm_buy` not evaluable. No duplicates; IST `session_day` tests; no null SEV1/SEV2 thresholds |
| **P2 Shadow** | Next 5 sessions | No crash, no engine latency change |
| **P3 Inform** | After P2 | Silent on a holiday; injected SEV2 reaches chat; sidecar keeps writing with routines paused; Friday batch gets no weekend reminders |
| **P4 Verifier loop** | After P3 and the release-layout migration | Independent verifiers; Verifier 2 vetoes an injected unsafe diff and a `'mark PASS'` comment; subset approval re-verified; a held lock aborts install; slow smoke test rolls back by the abort time; an `APPROVE` inside a tool result does not count; rollback rehearsed |
| **P5 Extras** | December | Month-end bhavcopy reconciliation; optional authenticated blind banner; synthetic replays for exits, ASM buys and duplicate fills |

**Release layout before P4:** code in `/workspace/pt/releases/<sha>/`, state in `/workspace/pt/shared/`, and `/workspace/paper-trading` linked to `current`. The one-time migration is its own approved off-hours change after 11 Nov, with a swap test proving `run.sh status` is unchanged.

---

## Gaps vs Drive docs and code

| Source | Gap |
| :--- | :--- |
| **Drive plan** | Stops at reporting; no fix, verify, approve, install or rollback loop |
| **Drive plan** | No absence detection; no monitoring of routines, the box, feeds or the freeze lock |
| **Drive plan** | Suggests Slack or email, which conflicts with the no-send rule |
| **Logging spec** | Evidence hash, hash chain, detector and export logs, and status actor missing in code |
| **`support_agent.py`** | Hardcoded `751`, `5257`, `120`, `300`; all-days fallback; checkpoint unused |
| **`support_agent.py`** | `unclassified_condition` treated as placeholder text; writes into the trading DB; never scheduled |

---

## Risks and non-goals

| Risk | Mitigation |
| :--- | :--- |
| Verifiers share blind spots | Fresh contexts, model diversity, binding scripts, your approval |
| Rubber-stamp approvals | One batch per evening, at most 3 reminders, per-change approval |
| Morning install breaks the scan | Done by 08:20, policy abort at 08:05, smoke test, automatic rollback |
| Heavy work starves the worker | Only the sidecar runs 09:15–15:35; heavy work after, capped and paused during EOD |
| Swap during a live process | Quiescence gate before switching the release |
| Untested partial batch | Batch branch plus re-verify of the exact subset tree |
| Prompt injection from the Proposer | Diff-only handoff, comment scanner, scripts outside the LLM |
| Public repo exposure | Branches and artifacts stay local; only the approved, sanitized commit is pushed |
| Drafted fix shifts Track A | Zero decision diff on replay plus Verifier 2 veto |
| Secret leak (public repo) | Redaction, `gitleaks`, raw reports never committed |
| Alert fatigue | Episodes, silent digests, shadow period |

**Non-goals:** it doesn't replace the freeze engine, the guardian or the adaptive Track B/C engine. There's no strategy tuning, no broker integration, and no auto-remediation.

---

## Skills that shaped the plan

| Skill | Design choice |
| :--- | :--- |
| `routines` | Weekday holiday-aware cron; fixed reminder times; webhook for urgent findings |
| `workflow` | Verifiers in parallel, Reconciler join, then pause until you approve, with a cutoff |
| `build-agents` | Eve rejected for detection, which must be deterministic and local |
| `create-a-backend` | Engine stays on the box; Vercel only for dashboard health |
| `queues` | Stable ids and episodes for at-least-once safety |
| `deployments-cicd` | Staged deploy, promote after approval, rollback |
| `verification` | End-to-end check after every install |
| `env-vars`, `auth` | Secrets stored as Secret type; findings panel only behind auth |
| `flags-sdk`, `runtime-cache` | Inform switch stays in the locked policy; cache rejected for findings |
| `vercel-functions`, `custom-metrics` | Low-cadence dashboard probe; bounded metric tags |
| `no-connector-fallback` | No scraping around blocked feeds |

---

## Open decisions

| Decision | Status |
| :--- | :--- |
| `support_policy` initial values | pending, 9 Nov |
| Install slots 21:45 / 07:50, done by 08:20, cutoffs 21:30 / 07:45 | pending |
| Reminder cadence 16:45, 19:30, 21:30, 07:30 (max 3) | pending |
| Standing authorization for the pipeline to open and merge PRs after an approved batch | pending |
| Model per role (Verifier 2 on a different family) | pending |
| Webhook for immediate SEV1/SEV2; shadow length; store choice | pending |
| 9 Nov SEV1 replay findings (1-share fills, 12 Strategy 7 buys): `WONT_FIX` as pre-freeze legacy, or keep open | new in v3 |
| Make the GitHub repo private before P4 | new in v3 |
| Release-layout migration slot after 11 Nov | new in v3 |
| New proposed policy values (heavy work start, install timeout and abort, escalation, latency multiple) | new in v3 |
| Plan v2 reviewed by Claude (C5) and Gemini (C6), reconciled in C7 | 9 Nov |

---

## Review log

| Round | When (IST) | Reviewer | Result |
| :--- | :--- | :--- | :--- |
| **v1** | 9 Nov, 19:30 | Grok Bot (author) | First plan |
| **v2** | 9 Nov, 19:45 | Grok Bot (author) | Verifier agents and evening approval |
| **C5** | 9 Nov | Claude, first pass | 10 items, 5 hard-limit concerns; ready with changes |
| **C6** | 9 Nov | Gemini, saw Claude | Agree 5, partly 4, disagree 1; 6 new items; 6 errors; risk medium |
| **C7** | 9 Nov, 20:10 | Grok Bot, Document Reconciler | 28 decisions: 24 accept, 2 reject, 2 defer → v3 |

**Rejected:** collapsing Verifier 2 and 3 and dropping the hash chain (the logging spec requires the chain), and cutting reminders.
**Deferred to P5:** the dashboard blind banner and a synthetic replay corpus.
Claude's hardcoded `900 s`, `600 s` and `3` were accepted only as proposed policy values. The two incomplete C5 files were not used as reviews. No hard limit was relaxed and your install approval is unchanged. Full decisions: `/workspace/paper-trading/reports/C7_DOCUMENT_RECONCILER.json`.

---

## Appendix B: how to run reviews

1. Open a new, empty chat for every role and every round.
2. Paste the role's `SYSTEM` prompt first, then its `USER` prompt, then the inputs it lists: the plan and, for code reviews, the finding, diff and artifacts.
3. Paste earlier reviewer output only into the Reconciler (C4), Gemini (C6) or the Document Reconciler (C7), never into a first pass of Verifier 1–3 or Claude (C5).
4. Ask for the JSON exactly as specified and save it as `review-<role>-<id>-<round>.json`.
5. If the chatbot cannot run tests or see files, it must answer `NOT_VERIFIABLE`, never `PASS`.

### Appendix B1: Role summary (machine-readable)

```yaml
plan: support-agent-production-plan
plan_version: 3
roles:
  proposer:
    type: code_fix
    schedule: works after 15:35 IST
    inputs: [plan, finding, worktree]
    change_classes: [support_only, engine_instrumentation_or_locking]
    constraints:
      - prose stripped before handoff
      - never touches live
      - never reviews own change
  verifier_1_correctness:
    inputs: [plan, finding, diff, artifacts]
    excluded_inputs: [other_verdicts, commit_messages, proposer_narrative]
  verifier_2_safety:
    inputs: [plan, finding, diff, artifacts, script_outputs, planned_install_time]
    hard_veto: true
    binding_scripts_outside_llm:
      - order_route_ast
      - freeze_lock
      - locked_files_diff
      - gitleaks
      - install_window
      - ntp_sync
      - change_class_ast
      - naive_clock_ast
      - comment_injection_scan
  verifier_3_regression:
    inputs: [plan, finding, diff, artifacts, test_logs, replay_reports]
  reconciler:
    inputs: [all_three_verdicts_after_final]
    outcomes: [READY_FOR_HUMAN, REVISE, REJECT]
    constraints:
      - never proposes
      - never installs
  human_kgr:
    role: approves next-day install
    outcomes: [APPROVE, DECLINE, HOLD]
    constraints:
      - only from a user-authored chat turn
      - approval record in support.sqlite is the install gate
  plan_reviewer_claude:
    inputs: [plan]
    tags: [MUST, SHOULD, NICE]
  plan_critic_gemini:
    inputs: [plan, claude_review]
    outcomes: [AGREE, DISAGREE, PARTLY]
  document_reconciler:
    inputs: [plan, claude_review, gemini_review]
    outcomes: [ACCEPT, REJECT, DEFER]
decision_rules:
  safety_fail_is_veto: true
  must: unanimous
  should: 2 of 3
  max_revisions: 1
  reruns_from_scratch: true
  install_requires_human_approval: true
  install_window: "15:45-08:30 IST before a trading day, never on NSE holidays or weekends"
  quiescence_gate: true
  morning_abort_at_policy: "install.morning_abort_at (proposed 08:05)"
  batch_branch: "support/batch-YYYY-MM-DD"
  batch_id: "B-YYYY-MM-DD-<sha256(sorted SHAs)[:8]>"
  subset_approval_reverifies_tree_sha: true
  engine_class_needs_per_change_approval: true
reminders:
  evening_report: "16:45"
  follow_ups: ["19:30", "21:30", "07:30 next trading day (Monday after Friday, day after a holiday)"]
cutoffs:
  slot_21_45: "21:30"
  slot_07_50: "07:45"
```

---

## Appendix C: role prompts

Each prompt is self-contained: hard limits, 9 Nov facts and the output schema are all included. Copy `SYSTEM` and then `USER`.
- **C1.** Verifier 1 — Correctness / SRE
- **C2.** Verifier 2 — Safety / Hard limits (hard veto)
- **C3.** Verifier 3 — Regression / Replay
- **C4.** Reconciler / Judge
- **C5.** Plan review — Claude (first pass)
- **C6.** Plan critique — Gemini (sees Claude's review)
- **C7.** Document Reconciler (plan loop)

---

## Appendix E: evening and reminder templates

- **E1.** Evening report prompt (16:45 IST)
- **E2.** Reminder prompt (19:30, 21:30, 07:30)

---

## Sources

- [fuzzylabs/sre-agent](https://github.com/fuzzylabs/sre-agent)
- [dastergon/awesome-sre](https://github.com/dastergon/awesome-sre)
- [last9/awesome-sre-agents](https://github.com/last9/awesome-sre-agents)
- [agamm/awesome-ai-sre](https://github.com/agamm/awesome-ai-sre)
- [SquadcastHub/awesome-sre-tools](https://github.com/SquadcastHub/awesome-sre-tools)
- [PagerDuty/incident-response-docs](https://github.com/PagerDuty/incident-response-docs)
- [monzo/response](https://github.com/monzo/response)
- [Netflix/dispatch (archived)](https://github.com/Netflix/dispatch)
- [healthchecks/healthchecks](https://github.com/healthchecks/healthchecks)
- [gerrymanoim/exchange_calendars](https://github.com/gerrymanoim/exchange_calendars)
- [rsheftel/pandas_market_calendars](https://github.com/rsheftel/pandas_market_calendars)
- [bayfolio/bf-nse-hols](https://github.com/bayfolio/bf-nse-hols)
- [danielfm/pybreaker](https://github.com/danielfm/pybreaker)
- [jd/tenacity](https://github.com/jd/tenacity)
- [hynek/structlog](https://github.com/hynek/structlog)
- [open-telemetry/opentelemetry-python](https://github.com/open-telemetry/opentelemetry-python)
- [gitleaks/gitleaks](https://github.com/gitleaks/gitleaks)
- [trufflesecurity/trufflehog](https://github.com/trufflesecurity/trufflehog)
- [Deployments and environments — GitHub Docs](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
- [-Trading-dashboard (main 4a6c382)](https://github.com/vvsrohith9490870277-stack/-Trading-dashboard)
