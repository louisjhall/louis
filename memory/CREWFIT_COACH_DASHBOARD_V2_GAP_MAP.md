# CrewFit Coach Dashboard — V2 Gap Map

**Version:** Iter 111 · 2026-07-27
**Companion to:** `CREWFIT_COACH_DASHBOARD_CURRENT_STATE_AUDIT.md` · `CREWFIT_TRAINING_INTELLIGENCE_V2_COACH_UX.md` · `CREWFIT_TRAINING_INTELLIGENCE_V2_MIGRATION.md`
**Purpose:** For every V2 coach-facing capability, name what exists today, what the target looks like, and the delta that must be closed.

Delta scale: **S** (≤3 days) · **M** (4-10 days) · **L** (2-4 weeks) · **XL** (1-3 months)
Risk: **L** low · **M** medium · **H** high

---

## 0. Reading the map

Each row asks four questions:
1. **What does the coach need to do?**
2. **How is it possible today (V1)?**
3. **What does V2 require?**
4. **What must be built to close the gap?**

Rows are grouped by capability area. `Depends on` refers to the 12-phase migration in `CREWFIT_TRAINING_INTELLIGENCE_V2_MIGRATION.md`.

---

## 1. Attention management

| # | Capability | V1 today | V2 target | Delta | Depends on | Risk |
|---|---|---|---|---|---|---:|
| 1.1 | See at a glance what needs coach eyes across all clients | Manual scan of 3 tabs (approvals · check-ins · messages). No unified queue. | Single "Needs Review" queue with severity, age, one-line reason, one-click apply for common resolutions. | L | P1, P5 | M |
| 1.2 | See at a glance what needs coach eyes for one client | Overview tab is a superset feed; no ranking, no state. | Per-client Attention Panel: exceptions + directives + last-3-check-ins + recovery flag with SLA age. | L | P1, P5, P10 | M |
| 1.3 | Time-boxed backlog (e.g. "3 items are ≥24h old") | Not measured. | Backlog age tracked per queue item; visual escalation at coach's chosen SLA. | S | P1 (metrics_events) | L |
| 1.4 | Batch approve N items | Approve is per-workout only. `approvals` nav shows roster-generated coach_tasks, not workouts. | Multi-select in Attention Panel → single approval → single PlanVersion published. | M | P1 | L |
| 1.5 | Auto-approve for SUPPORTING/OPTIONAL items | Not available. Every workout requires manual click. | Coach flag on programme; DecisionRecord still written. | S | P1 | L |

---

## 2. Roster + Plan workspace

| # | Capability | V1 today | V2 target | Delta | Depends on | Risk |
|---|---|---|---|---|---|---:|
| 2.1 | One canonical view combining roster + plan for a client | Duplicated across overview, calendar, roster tab, programme tab, workouts tab, client-months. | ROSTER + PLAN workspace: two-column ~28-day view; roster left, plan right, day-clicked = detail drawer. | L | P4, P5, P6, P11 | M |
| 2.2 | See DRAFT vs LIVE side by side | No draft concept — every LLM output goes straight to the client. | LIVE column read-only; DRAFT column editable; diff highlighted per day. | L | P1, P5, P6 | H |
| 2.3 | Preview a plan before it's visible to the client | Not possible — publish is implicit. | DRAFT builds don't touch client's LIVE view until approval. | Already shipped in P1 backend | P1 | L |
| 2.4 | Move a session to another day within the plan | Coach edits the workout's date directly on the workout editor. | Drag-drop or "move to date" action → creates ChangeSet if it exceeds SAB. | M | P5 | M |
| 2.5 | Understand duty burden per day | Backend computes home/away, layover; no duty_burden score visualised. | Every day cell renders `duty_burden_band` (light/moderate/heavy/extreme) + `training_opportunity` (0-100). | S | P4 | L |
| 2.6 | See recovery gap between duties | Not surfaced. | Rendered inline (`14h since last duty`) with red/amber if under threshold. | S | P4 | L |
| 2.7 | Cache historical months quickly | Historical months load per-tap. | Pre-fetch adjacent months on open; cache in memory. | S | — | L |

---

## 3. Publishing & approvals

| # | Capability | V1 today | V2 target | Delta | Depends on | Risk |
|---|---|---|---|---|---|---:|
| 3.1 | Non-destructive revert to a previous plan | No version concept. | Any PlanVersion browsable + revertable; revert = new version, never destructive. | Already shipped in P1 backend | P1 | L |
| 3.2 | Approve per-scope (workout / day / week / phase / programme) | Approve per-workout only. | Explicit `scope` field on Approval. | Already shipped in P1 backend | P1 | L |
| 3.3 | See a plan's approval lineage ("who approved what and when") | Only individual `approved_by` on workout. | `approvals[]` per PlanVersion; DecisionRecord chain queryable. | S (UI) | P1 | L |
| 3.4 | Auto-publish safe changes | Nothing is auto-published. | Client-side reality changes within SAB auto-publish without coach; DecisionRecord written. | Backend shipped (P7); UI surfacing pending | P7, P11 | M |

---

## 4. Signals → Actions

| # | Capability | V1 today | V2 target | Delta | Depends on | Risk |
|---|---|---|---|---|---|---:|
| 4.1 | See adherence % + trend for a client | Number displayed on overview. | Number + 4-week sparkline + verbal explanation ("held steady", "dropped 15pp"). | M | P8 (data), P11 (UI) | L |
| 4.2 | See RPE 7d/14d trend | Small number on overview. | Number + trend arrow + rolling avg + threshold triggers. | M | P8, P11 | L |
| 4.3 | Alerted when auto-deload triggers | Not surfaced anywhere. | Coach receives Attention Panel item: "Auto-deload triggered — next 7 days set to recovery bias." | S | P8, P10 | L |
| 4.4 | See structured pain flags | Buried in check-in free-text. | `readiness_states.avoid_movement_patterns[]` displayed as chips in Attention Panel. | S | P10 | L |
| 4.5 | See a signal's explicit plan consequence | Signals are consumed by prompt; consequence invisible to coach. | Signal card + a one-liner "→ reduced upper_strength volume next 7d by 20%". | M | P10 | M |

---

## 5. Command surfaces

| # | Capability | V1 today | V2 target | Delta | Depends on | Risk |
|---|---|---|---|---|---|---:|
| 5.1 | Regenerate a workout | Button on programme tab, workouts tab, workout editor, client-months. Full-month regen only. | Regenerate any scope (workout / day / week / phase). Incremental replan. | L | P5, P6 | H |
| 5.2 | Command bar (natural-language coach commands) | Not implemented. | "Move Tuesday's key run to Wednesday and reduce Thursday to 30 min" → structured ChangeSet proposal → coach one-click accept. | M | P11 + LLM | M |
| 5.3 | Coach edit → workout | Full workout editor page (`/coach/workout/edit/[wid]`). Preserves lock. | Inline edit on the Roster + Plan workspace; drawer overlay. | M | P11 | L |
| 5.4 | Coach explicit "why this?" tooltip | Not available. | Every assignment shows a DecisionRecord chain: what rule fired, at what confidence, why this exercise was chosen. | M | P1 (data), P11 (UI) | L |
| 5.5 | Coach directive editor (structured) | Free-text `users.coach_notes` (5 buckets). | `coach_directives[]` with `kind`, `scope`, `parameters`, `free_text`. | S (backend already shipped P10); UI pending | P10, P11 | L |
| 5.6 | Coach → client message with "coach says…" | Messages tab, generic thread. | Push a directive AND a client-facing message in one action. | S | P10, P11 | L |

---

## 6. Data + navigation architecture

| # | Capability | V1 today | V2 target | Delta | Depends on | Risk |
|---|---|---|---|---|---|---:|
| 6.1 | Non-duplicated screens for the same data | Roster days appear in 5 screens; workouts in 6. | Roster + Plan is canonical; other screens link into it. | L | P11 | M |
| 6.2 | Consistent `/coach/*` vs `/(coach)/*` split | Inconsistent. Some deep-links belong in the group; some group routes should be deep-links. | Rule: `(coach)/*` = coach-shell tabs. `coach/*` = per-client deep-links. | S | — | L |
| 6.3 | Retire legacy screens | `library-legacy`, `hotels`, `ui-issues`, `draft/[id]` stubs exist. | Archived; explicit deprecation notice. | S | — | L |
| 6.4 | Reduce the mega client profile | 2 008 LOC, 11 tabs. | Split into: Roster+Plan workspace · Attention Panel · Profile · Directives · History. | XL | P11 | H |
| 6.5 | Cross-tab hop count | Coach must open 6-8 tabs to answer "what does this client need this week". | Roster+Plan workspace answers in one screen. | Metric follows 6.4. | P11 | — |

---

## 7. Client visibility model

| # | Capability | V1 today | V2 target | Delta | Depends on | Risk |
|---|---|---|---|---|---|---:|
| 7.1 | Client only sees approved plan | Client sees every workout regardless of `approved`. | Client's `/live/plan` served from `plan_versions.live_plan_version` only. | Backend shipped (P1); frontend swap pending | P1, P11 | H |
| 7.2 | Client cannot see DRAFT | Draft doesn't exist. | Client endpoints strictly refuse to serve draft data. | Enforced by design — backend already excludes drafts from `/v2/live/plan` | P1 | L |
| 7.3 | Client adaptation within SAB stays silent | Not implemented in V1. | P7 endpoint auto-applies; DecisionRecord written. | Backend shipped (P7); client UI pending | P7 | M |

---

## 8. Observability, safety, audit

| # | Capability | V1 today | V2 target | Delta | Depends on | Risk |
|---|---|---|---|---|---|---:|
| 8.1 | Every material decision has an audit row | Partial (`coach_actions_log`, `workout_change_log`). | Every WHAT/WHEN/HOW/PUBLISH/ADAPT/COMPLETE decision → `decision_records`. | Backend shipped (P1); some paths still to instrument | P1, P12 | L |
| 8.2 | Coach can query decisions by scope | Not available. | `GET /v2/coach/clients/{cid}/decisions` (shipped). UI pending. | Backend shipped | P1, P11 | L |
| 8.3 | Metrics dashboard (approval time, backlog age, latency) | No dedicated view. | `/api/v2/admin/metrics` (shipped); UI pending. | Backend shipped | P12, P11 | L |
| 8.4 | Shadow-mode diff view | Not built. | Coach can compare V1's proposal vs V2's proposal per day. | UI pending | P12, P11 | M |
| 8.5 | Load test baseline | None. | p95 targets: dashboard ≤2 s · client profile ≤2 s · draft build ≤60 s. | Test scripts pending | P12 | M |

---

## 9. Retirement candidates

| # | Screen / concept | V1 status | V2 verdict | Migration action |
|---|---|---|---|---|
| 9.1 | `/coach/hotels` | Implemented | Deprecated (V2 §19 removes hotels from training path) | Keep as coach-only notes; remove from workout-build flow. |
| 9.2 | `(coach)/library-legacy` | Present | Retire | Delete route; ensure content library covers all needs. |
| 9.3 | `coach/ui-issues` | Placeholder | Retire or move to internal admin | Delete route or move behind admin-only flag. |
| 9.4 | `coach/draft/[id]` | Stub | Retire | Delete; replaced by the ROSTER + PLAN workspace's Draft column. |
| 9.5 | Client profile "overview" tab conditional-render trick | Overgrown | Replace | Split into distinct views; delete the `tab === "overview" || tab === "programme"` composite. |
| 9.6 | Backend labels bleeding into UI (`ULR`, `report_time_utc`, etc.) | Present | Retire | Terminology map at the UI layer. |

---

## 10. Zero-regression rules for the V2 rollout

These MUST hold at every phase of the coach-dashboard rebuild:

1. **V1 dashboard stays fully functional** until per-coach flag flip.
2. **Coach can always revert to V1** with one click (`v2_default = false`).
3. **No client sees V2 data** until per-client `v2_default = true` AND at least one PlanVersion exists.
4. **Every V2 dashboard route** logs a DecisionRecord for material actions (approve, revert, edit, apply, escalate).
5. **Coach roster upload (Iter 109)** and multi-active-roster preservation (Iter 109) must keep working — they feed P4.
6. **Auth remains unchanged** — no re-plumb of login/sessions during V2 dashboard work.
7. **App Store review credentials** (`reviewer@crewfit.net`) continue to work throughout.

---

## 11. Ordering summary (dashboard-side of the 12 phases)

- **P1** (State foundation) — backend ready; Approvals nav → refactor to Attention Panel comes with P11.
- **P4** (Roster facets) — schedule_days + duty_burden feed the day-cell rendering in P11.
- **P5** (Scheduling) — enables drag-drop / move-with-validation in P11.
- **P6** (Construction) — enables per-slot preview and "swap exercise" drawer.
- **P7** (Equipment/SAB) — enables client-side adapt UI + coach SAB editor.
- **P8** (Progression) — enables per-exercise history & feed-forward strip.
- **P9** (Events + phase transitions) — enables countdown card and transition proposals.
- **P10** (Reality) — enables Attention Panel signal-to-action narrative.
- **P11 (Coach Dashboard V2)** — the actual dashboard build; consumes everything above.
- **P12** (Automation + shadow + metrics) — instruments observability the moment P11 lands.

---

## 12. Highest-impact single-change candidates

If forced to pick ONE change to ship in the coach dashboard first, ordered by expected reduction in coach workload:

1. **Attention Panel with batch approve** — collapses approvals + roster changes + exceptions into one queue.
2. **ROSTER + PLAN workspace** — kills 4-5 duplicate screens and 6-8 tab-hops.
3. **Command bar** — 10× faster than manual edits for typical coach requests.
4. **Client change-equipment within SAB (no coach involvement)** — removes an entire category of coach interruptions.
5. **DecisionRecord chain rendered as "Why this?"** — the coach never has to hunt for context again.

Everything else compounds these five.

---

**End of gap map.**
