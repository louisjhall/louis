# CrewFit Coach Dashboard — V2 Operating Model

**Version:** Iter 111 · 2026-07-27
**Companion to:** `CREWFIT_COACH_DASHBOARD_CURRENT_STATE_AUDIT.md` · `CREWFIT_COACH_DASHBOARD_V2_GAP_MAP.md` · `CREWFIT_TRAINING_INTELLIGENCE_V2_COACH_UX.md`
**Purpose:** Describe how the V2 coach dashboard actually operates day-to-day. Not a wireframe spec — a behavioural contract: who does what, when, at what latency, with what safety.

---

## 0. First principles

1. **The coach's job is exceptions, not throughput.** Anything routine belongs to the system.
2. **The client sees only LIVE.** DRAFT is the coach's workspace and must never leak to the client.
3. **Every material decision leaves an audit trail** (`decision_records`).
4. **Reverts are cheap.** Any state change can be undone by revert-to-version.
5. **The dashboard is a queue, not a filesystem.** Priority > completeness.
6. **Never speak "AI" to the client.** All client-visible copy is Louis's voice.

---

## 1. The coach's day (target model)

A Louis-style day looks like:

```
Login  ──►  Attention Panel (cross-client)
              │
              ├── 3 KEY items today  ► batch review 3 items in 2 min
              ├── 1 Exception (roster changed for client X)  ► one-click apply proposed resolution
              └── 2 client-side adaptations (within SAB, informational)
              │
              ▼
        Enter Client X (Roster + Plan workspace)
              │
              ├── Sees DRAFT + LIVE side-by-side
              ├── Understands "Why this?" via DecisionRecord chain
              ├── Uses command bar: "Push this week's key run to Sunday"
              └── Approves the affected day (1 click) → new PlanVersion
```

**Target totals per client per week:** ~20 minutes (down from V1's ~50 min).

---

## 2. Two top-level shells

### 2.1 Coach shell — `/(coach)/*`
Global, cross-client. Six primary destinations, ordered by priority:

1. **Attention Panel** (was `overview`; renamed to reflect purpose).
2. **Clients** (portfolio grid; sortable by attention age, adherence, next event).
3. **Approvals** (backwards-compat entry point — routes into Attention Panel filtered on "approval needed").
4. **Check-ins** (inbox).
5. **Messages** (inbox).
6. **Library** (exercises · content · videos · brand images).

Everything else moves behind an "Admin" drawer (analytics, changelog, coach admin, nutrition tool, hotels notes).

### 2.2 Client workspace — `/coach/client/[id]`
One page, one purpose: **Roster + Plan**. Everything else is a drawer or a peer route:

- Drawers (in-page): day detail · assignment detail · directive editor · attention panel (this client) · signal card
- Peer routes: profile · history (versions) · directives (structured) · check-ins detail · messages

The 11-tab kitchen-sink page is retired.

---

## 3. State machine (per client)

```
                     ┌──────────────┐
   coach creates DRAFT────►│ building     │
                     └──────┬───────┘
                            │ system finishes → ready_for_review
                            ▼
                     ┌──────────────┐
                     │ ready_review │◄──────────── coach edits (no state change)
                     └──────┬───────┘
                            │ coach approves (any scope)
                            ▼
                     ┌──────────────┐
                     │ published    │──► new plan_versions row (immutable)
                     └──────┬───────┘
                            │ client's live_plan_version pointer updated
                            ▼
                     ┌──────────────┐
                     │ live (client)│
                     └──────┬───────┘
                            │ client completes / adapts within SAB → performance_records
                            │ coach can revert → NEW version (never destructive)
                            ▼
                     ┌──────────────┐
                     │ archived hist│
                     └──────────────┘
```

Rules:
- `plan_versions` rows are immutable after publish. Revert creates a new version.
- Client's LIVE view queries `plan_versions.live_plan_version` only.
- DRAFT changes never affect LIVE until an Approval is written.

---

## 4. The Attention Panel (cross-client)

Single queue. Every row = one actionable item.

Row fields:
- **client** (avatar + name)
- **kind** (approval · exception · check-in flag · adaptation escalation · directive followup)
- **severity** (info · warning · blocker)
- **age** (hours since triggered)
- **SLA** (per coach-configured target; red if ≥ SLA)
- **one-line reason** (from `decision_records` or `exceptions`)
- **primary action button** (varies by kind — see 4.1)
- **secondary actions** (link into client workspace at the right spot)

### 4.1 Primary actions per kind
- **approval** → "Approve batch" (multi-select) or "Open plan"
- **exception** → "Apply proposed resolution" (one-click) or "Open exception"
- **check-in flag** → "Open check-in"
- **adaptation escalation** (SAB exceeded) → "Approve adaptation" or "Reject & revert"
- **directive followup** → "Mark handled" or "Reissue directive"

### 4.2 Batch approve
- Coach selects N rows of `kind=approval`.
- Single "Approve N items" button.
- System writes ONE `plan_versions` row spanning all selected assignments.
- One DecisionRecord chain: outcome=APPLIED, scope=batch_ready, count=N.

---

## 5. The Roster + Plan workspace (per client)

### 5.1 Layout contract
Two synchronised columns spanning ~28 days:
- **Left:** ROSTER (schedule_days + duties)
- **Right:** PLAN (DRAFT column + LIVE column, toggleable)

Every day row shows:
- Date · day-of-week · duty_burden band · training_opportunity score · recovery hours
- LIVE assignment (green background) · DRAFT delta (amber if changed)
- Icons: KEY (star) · locked · approved · has-exception · client-adapted

### 5.2 Day drawer (click a day)
- Duty detail (report time, sectors, layover context)
- LIVE workout (read-only) — expandable exercise list
- DRAFT workout (editable) — swap exercise · edit sets/reps · duration slider
- DecisionRecord chain — "Why this?"
- Coach directive that touched this day (if any)

### 5.3 Command bar (top of workspace)
Free-text input. Parses to structured ChangeSet proposals:
- "Move Tuesday's long run to Sunday" → `assignment_moved` change_set
- "Reduce Thursday to 30 min" → `implementation_changed`
- "Add mobility on Wednesday" → `objective_added`
- "Louis' note: he flies to LHR next week — bump strength earlier" → `coach_directive_applied` + narrative

Coach reviews the proposal card and clicks Apply → change_set persisted → coach approves → PlanVersion published.

---

## 6. Latency SLOs

| Path | p50 target | p95 target |
|---|---:|---:|
| Attention Panel initial load | 500 ms | 1500 ms |
| Client workspace initial load | 800 ms | 2000 ms |
| Day drawer open | 200 ms | 500 ms |
| Approve batch (up to 30 items) | 800 ms | 2000 ms |
| Command bar parse → proposal | 1000 ms | 3000 ms |
| DRAFT rebuild (P4→P3→P5→P6) after roster confirm | 20 s | 60 s |
| Client-side adaptation within SAB | 500 ms | 1500 ms |

All measured against `metrics_events`. p95 breach → alert on `(coach)/analytics`.

---

## 7. Signal → Action narrative contract

For every material signal the coach needs a **verbal explanation of the plan consequence**. UI copy is coach-voice, not "AI".

Examples:
- Adherence 65% (was 84%) → *"Two strength sessions missed. Next week's DRAFT reduced upper volume by 20%. Review recommended."*
- Pain flag (knee) → *"Deep_squat & lunge patterns removed from the next 14 days. No client-visible change until you approve."*
- Auto-deload trigger → *"Adherence < 50% AND RPE ≥ 8 (7d) → forced deload week starting Monday."*
- Roster change (Tuesday moved from OFF to duty) → *"Tuesday long_run reassigned to Wednesday. Wednesday's easy_run reassigned to Thursday."*

The narrative is generated by the same rule that fired the change and stored in the `decision_records.human_readable_reason` field. UI reads it verbatim.

---

## 8. Two-way controls (who can do what)

| Action | Client | Coach (SAB allow) | Coach (SAB exceed) | System |
|---|:-:|:-:|:-:|:-:|
| Change equipment for tomorrow | ✅ | ✅ | — | — |
| Reduce today's session ≤SAB% | ✅ | ✅ | — | — |
| Convert today to mobility | ✅ (if SAB.allow_convert_to_mobility) | ✅ | — | — |
| Move a session inside window | ❌ | ✅ (if SAB.allow_move_within_window) | ✅ (creates change_set) | — |
| Swap exercise (approved pool) | ✅ | ✅ | — | ✅ (auto) |
| Skip a session | ❌ | ✅ (if SAB.allow_skip) | ✅ | — |
| Add / remove objective | ❌ | ✅ | — | ✅ (rule fires) |
| Change goal | ❌ | ✅ | — | — |
| Trigger phase transition | ❌ | ✅ | — | ✅ (auto on end-date) |
| Approve a PlanVersion | ❌ | ✅ | — | — |
| Revert to previous version | ❌ | ✅ | — | — |

Any row where "Coach (SAB exceed)" is ticked → the action requires an explicit ChangeSet + Approval before it becomes LIVE.

---

## 9. Failure & fallback behaviour

- **A V2 code path throws** → the request falls back to V1, and a DecisionRecord with `outcome=BLOCKED` is written.
- **Job runner times out** → job moves to `dead_letter`; visible in `(coach)/analytics`.
- **LLM polish call fails** → the workout is still built (template rationale); `needs_coach_review=true` set.
- **Coach hits "revert"** → NEW PlanVersion created reading from the target snapshot. Original untouched.
- **Feature flag disabled mid-session** → coach sees V1 view; V2 background writes continue safely (no client-visible change).

---

## 10. Metrics tracked by default

Written to `metrics_events` and surfaced in `(coach)/analytics`:

```
attention_panel_load_ms
client_workspace_load_ms
plan_approval_time_seconds
plan_approval_scope_count
batch_approve_size
command_bar_parse_ms
llm_calls_per_plan
draft_build_seconds
sab_exceeded_count
adaptations_within_sab_count
decision_records_written
exceptions_open_count
exceptions_median_age_hours
coach_edits_per_client_per_week
p95_dashboard_load_ms
```

Green criteria for going from coach-only beta → default V2:
- `coach_edits_per_client_per_week` ≤ 3
- `plan_approval_time_seconds` p95 ≤ 480
- Zero data-integrity incidents
- Coach subjective sign-off

---

## 11. Coach vocabulary — canonical terms

The V2 dashboard uses one vocabulary end-to-end:

| Term | Meaning |
|---|---|
| DRAFT | Coach-editable working copy. Never visible to client. |
| LIVE | The published, client-visible plan (latest `plan_versions`). |
| PlanVersion | Immutable snapshot of a LIVE plan. |
| ChangeSet | A proposed diff against DRAFT. |
| Approval | Coach action promoting a ChangeSet (or scope) → new PlanVersion. |
| Attention | Anything in the coach's queue needing eyes (approvals, exceptions, escalations). |
| Exception | A rule-detected condition needing coach input (severity: info/warning/blocker). |
| SAB | Safe Adaptation Boundary. What the client can change without coach approval. |
| Directive | Structured coach instruction (avoid/require/limit/note). |
| Objective | Training stimulus (kind × phase). E.g. upper_hypertrophy · long_run. |
| Exposure | One instance the client actually performs of an Objective. Monotonic sequence. |
| Assignment | An Exposure placed on a specific ScheduleDay. |
| Implementation | The concrete workout (exercises, sets, reps) attached to an Assignment. |

**Never surfaced client-facing:** AI · bot · generated · algorithm. All client copy is coach voice.

---

## 12. Coach-onboarding to V2 (per client)

Zero big-bang. Per-client opt-in:

1. Louis opens `/coach/client/[id]/admin` → toggles the twelve `v2_flags`.
2. First DRAFT build triggered (shadow mode by default).
3. Coach compares V1 vs V2 output in the "Shadow" tab.
4. If satisfied → promote DRAFT to LIVE via approval → client is now on V2.
5. Any time → coach can flip `v2_default=false` → V1 view resumes.

No client sees V2 output until step 4 is explicit.

---

## 13. Non-goals of the V2 coach dashboard

Explicit list of what the V2 dashboard does **not** attempt:

- Real-time video calls or teleprompter (kept as a separate route).
- Nutrition planning (kept as a separate module).
- Full CRM / lead-gen (out of scope).
- Multi-coach collaboration (single-coach model preserved).
- Wearable / HR live streams (post-V2 optional).
- Push notifications (opt-in only; not core).

---

## 14. Definition of done for the V2 dashboard

The V2 coach dashboard is "done" when all of the following hold on production traffic for 4 consecutive weeks:

- ✅ Coach opens exactly one panel per morning and completes all overnight decisions from it.
- ✅ Coach never needs more than 2 clicks to see "Why this?" for any assignment.
- ✅ Every client the coach touches has ≤ 3 coach edits per 28-day plan.
- ✅ Client-visible copy contains zero forbidden words ("AI", "bot", "generated", "algorithm").
- ✅ Zero data-integrity incidents.
- ✅ V1 dashboard still available via feature flag with zero regressions.
- ✅ Louis signs off explicitly.

---

**End of operating model.**
