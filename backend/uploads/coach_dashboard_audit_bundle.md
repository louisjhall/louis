# CrewFit Coach Dashboard — Full Audit Bundle

**Generated:** 2026-07-27


This bundle collates 5 companion documents into a single file for coach + engineering review.


## Table of contents

1. [Part 1 · Current State — Forensic Audit](#part-1-current-state-forensic-audit)
2. [Part 2 · Screen Inventory (JSON)](#part-2-screen-inventory-json)
3. [Part 3 · V2 Gap Map](#part-3-v2-gap-map)
4. [Part 4 · V2 Operating Model](#part-4-v2-operating-model)
5. [Part 5 · Coach Workflow Audit (V1→V2 traces)](#part-5-coach-workflow-audit-v1v2-traces)


---




<a id="part-1--current-state--forensic-audit"></a>

# Part 1 · Current State — Forensic Audit


_Source file: `CREWFIT_COACH_DASHBOARD_CURRENT_STATE_AUDIT.md`_


# CrewFit Coach Dashboard — Current State Forensic Audit

**Version:** Iter 111 · session 2026-07-27
**Scope:** Read-only. No code, prompt, or schema changes.
**Prerequisite reading:** V1 audit + V2 architecture files under `/app/memory/`.

**Honesty labels:** ✅ IMPLEMENTED · ⚠️ PARTIAL · ❓ AMBIGUOUS/DUPLICATED · ❌ NOT IMPLEMENTED · 🧪 PLACEHOLDER.

Companion outputs:
- `CREWFIT_COACH_DASHBOARD_V2_GAP_MAP.md`
- `CREWFIT_COACH_DASHBOARD_V2_OPERATING_MODEL.md`
- `CREWFIT_COACH_DASHBOARD_SCREEN_INVENTORY.json`
- `CREWFIT_COACH_WORKFLOW_AUDIT.md`

---

## 0. Snapshot

| Metric | Value |
|---|---:|
| Coach top-level routes | 30 (16 under `/coach/*`, 14 under `/(coach)/*`) |
| Coach-specific backend endpoints | 88 |
| Client profile page LOC | **2 008** (single file: `/coach/client/[id].tsx`) |
| Client-months navigator LOC | 866 |
| Exercise content page LOC | 949 (own tool) |
| Client-profile tabs | **11** (overview, notes, calendar, roster, programme, timeline, workouts, checkins, messages, profile, admin) |
| Reusable coach components | 5 |
| Duplicate schedule representations per client | **4** (Overview + Calendar + Roster + Programme + Workouts all overlap) |
| Ambiguous status vocabulary | 8+ terms (`needs_review`, `approved`, `coach_locked`, `completed`, `is_active`, `status="pending_confirmation"`, `source="template"`, `variants`) |

**Headline finding:** the coach client profile is a **kitchen-sink page**. 11 tabs, several of which show the same underlying data through different lenses. There is no single canonical "Roster + Plan" workspace. Attention management is manual — the coach must know what to open.

---

## 1. Top-level coach navigation

### 1.1 Group route `/(coach)/*` — coach's home shell (bottom tabs / left rail)
Route | Purpose | Status
---|---|---
`(coach)/overview.tsx` | Landing / dashboard | ⚠️ PARTIAL — mostly feed of activity, not an attention queue
`(coach)/clients.tsx` | Client list | ✅ IMPLEMENTED
`(coach)/approvals.tsx` | Approvals list | ⚠️ PARTIAL — see §23
`(coach)/checkins.tsx` | Cross-client check-in inbox | ✅ IMPLEMENTED
`(coach)/messages.tsx` | Cross-client messages | ✅ IMPLEMENTED
`(coach)/calendar.tsx` | Cross-client calendar | ⚠️ AMBIGUOUS — overlaps per-client calendar
`(coach)/exercises.tsx` | Exercise browser | ✅ IMPLEMENTED
`(coach)/library.tsx` | Content library | ✅ IMPLEMENTED
`(coach)/library-legacy.tsx` | LEGACY | ❓ DUPLICATED (see §54 of V1 audit)
`(coach)/videos.tsx` | Video library | ✅ IMPLEMENTED
`(coach)/analytics.tsx` | Coach analytics | ⚠️ PARTIAL
`(coach)/changelog.tsx` | Change log | ⚠️ PARTIAL
`(coach)/profile.tsx` | Coach's own profile | ✅ IMPLEMENTED

### 1.2 Non-grouped routes `/coach/*` — deep-links
Route | Purpose | Status
---|---|---
`/coach/client/[id]` | **The mega client profile** — 11 tabs, 2 008 LOC | ⚠️ OVERGROWN
`/coach/client-months/[id]` | Programme by Month workspace | ⚠️ PARTIAL — added Iter 100 → 109
`/coach/workout/edit/[wid]` | Workout editor | ✅ IMPLEMENTED
`/coach/checkin/[id]` | Individual check-in review | ✅ IMPLEMENTED
`/coach/scripts/[id]` | Weekly script editor | ⚠️ PARTIAL — role unclear (§14)
`/coach/teleprompter/[id]` | Teleprompter for coach video | ✅ IMPLEMENTED
`/coach/habit-review/[id]` | Habit review | ✅ IMPLEMENTED
`/coach/exercise-content.tsx` | Exercise content admin tool | ✅ IMPLEMENTED
`/coach/hotels.tsx` | Hotel gym editor | ⚠️ DEPRECATED in V2 (see V2 §19)
`/coach/nutrition.tsx` | Nutrition tool | ✅ IMPLEMENTED
`/coach/brand-images.tsx` | Brand images | ✅ IMPLEMENTED
`/coach/demand-queue.tsx` | Coach demand queue | ⚠️ PARTIAL — potentially useful for V2 exception queue
`/coach/draft/[id]` | Draft item viewer | ⚠️ PARTIAL — role unclear
`/coach/ui-issues.tsx` | UI issues admin | 🧪 debug
`/coach/admin/coaches.tsx` | Coach admin | ✅ IMPLEMENTED
`/coach/admin/live-controls.tsx` | Live controls | 🧪 admin

**Observation:** the **`/coach/*`** vs **`/(coach)/*`** split is inconsistent. Some deep-links belong in the group; some group routes should be deep-links. There is no obvious rule.

---

## 2. The client profile (`/coach/client/[id].tsx`) — deep dive

**2 008 lines, 11 tabs in a single file.** Tab enum:
```
type Tab = "overview" | "notes" | "calendar" | "roster" | "programme"
         | "timeline" | "workouts" | "checkins" | "messages" | "profile" | "admin";
```

Rendering pattern: multiple `{tab === "X" && …}` blocks. Overview is **conditionally rendering many other tabs' content** (`tab === "overview" || tab === "programme"` gates), which means:
- ❓ **Overview is not a distinct view** — it's a superset of programme + roster + workouts + checkins + habits + profile.
- ⚠️ Data is fetched for every tab even if unused → performance cost.
- ⚠️ Cognitive load: everything is available, nothing is prioritised.

### 2.1 What each tab actually shows

Tab | Unique job | Overlap with other tabs
---|---|---
**overview** | Superset landing | Overlaps EVERY tab below
**notes** | Coach-facing structured coach_notes + free text | Notes surface again in overview
**calendar** | 7-day calendar with roster/workout markers | Same data as roster + workouts + programme
**roster** | Day-by-day roster list with day_type + hotel | Same data used in calendar + programme
**programme** | Programme summary (goal, phase, next 7 days) | Overlaps overview + calendar + workouts
**timeline** | Historical activity feed (workouts, check-ins, roster events) | Similar to `/(coach)/changelog`
**workouts** | Workout list for this client + edit link | Same underlying data as calendar + programme
**checkins** | Check-in history + habits | Also visible in overview + `(coach)/checkins`
**messages** | Message history | Also in `(coach)/messages`
**profile** | Client profile fields | Static, unique
**admin** | Debug / raw controls | Unique, but hosts several coaching functions

### 2.2 Duplication matrix (per-client)

Data | Screens it appears on
---|---
Roster days | `overview`, `calendar`, `roster`, `programme` (as day list), `client-months` page
Workouts | `overview`, `calendar`, `programme`, `workouts`, `client-months` page, `workout/edit/[wid]`
Check-ins | `overview`, `checkins` tab, `(coach)/checkins`, `checkin/[id]`
Messages | `overview` (recent), `messages` tab, `(coach)/messages`
Coach notes | `notes` tab, `admin` tab, sometimes overview
Habits | `overview`, `checkins` tab (as habits section)
Programme summary (goal, phase) | `overview`, `programme` tab, `client-months` header

Coach's day is spent hopping between 4-5 places for the same underlying schedule.

### 2.3 What's missing from the client profile
- ❌ Attention-queue view scoped to this client
- ❌ DRAFT vs LIVE comparison (V1 has no draft concept)
- ❌ Programme version history browsable
- ❌ Batch approval UI (approve N READY workouts in one action)
- ❌ Command bar (natural language coach commands)
- ❌ "Why this?" tooltip on any assignment
- ❌ Structured coach directive editor (only free-text notes)
- ❌ Progression memory view (last exposure of exercise X vs prescribed next)

---

## 3. Information hierarchy on opening a client (§5 of brief)

Question | Currently answerable from | Tabs needed
---|---|---:
Main goal | Overview OR Profile | 1
Programme name / kind | Programme tab | 1
Current phase | Programme tab | 1
Event exists / countdown | Programme tab or Timeline | 1
Roster this week | Roster tab OR Calendar OR Overview | 1
This week's workouts | Programme/Calendar/Workouts | 1
Adherence % / completions | Overview OR check-ins tab | 1
Recovery issue? | Check-ins tab (manual read) | 1
Roster changed recently? | Timeline tab (must scroll) | 1
Waiting for approval? | Approvals nav OR overview badge | 1-2
Anything wrong? | ❌ No single answer | many
What needs attention today? | ❌ No unified queue | many

**Score:** to answer "everything I need to know about this client this week" the coach must consult **6-8 tabs**. In V2 target this should be **one screen**.

---

## 4. Attention model + status vocabulary (§6)

### 4.1 Statuses that exist
Concept | Where it lives | Consistent name?
---|---|---
Needs Review | `workouts.needs_coach_review` bool | ⚠️ Also implied by `source="template"`
Approved | `workouts.approved` bool | ✅ single field
Locked | `workouts.coach_locked` bool | ✅ single field
Draft | `rosters.status="pending_confirmation"` | ⚠️ Roster only, not workouts
Live | Implicit — every non-draft workout is live | ❌ No LIVE flag
Missing data | Not a stored state | ❌
Client changed | Would be captured by `reality_events`, `move_history`, `workout_exercise_swaps` — not surfaced | ❌ UI-side
Roster changed | Would fire from `RosterChanged` event — no such event | ❌
Event risk | ❌ NOT IMPLEMENTED
Progression issue | `progression_snapshots.status_label` | ⚠️ present but hidden from primary UI
Conflict | ❌ NOT IMPLEMENTED
AI Ready | ⚠️ ambiguous — either `source="coaching_system"` or absence of `needs_coach_review`

### 4.2 Assessment
- ⚠️ Status vocabulary is **fragmented across 4-5 collections and 3-4 field names**.
- ❌ No unified "attention required" state model.
- ❌ No cross-client "queue" of events that need coach eyes.
- ⚠️ Approvals nav exists but is roster-centric, not workout/exception-centric.

---

## 5. Live signals (§7-8)

### 5.1 Signals actually surfaced on coach dashboard
Signal | Source | Displayed where | Programme consequence?
---|---|---|---
Adherence % (14d) | derived from `workouts.completed` | Overview + checkins | ✅ Feeds `_adherence_multiplier` in progression
Missed sessions count | derived | Overview + checkins | ✅ Feeds progression
Avg RPE (7d, 14d) | `workouts.completion.rpe` | Overview (small) | ✅ Feeds `compute_status`
Sleep score trend | check_ins.scores.sleep | Overview / checkins | ⚠️ Feeds `readiness.band`; no direct plan consequence
Energy score | check_ins.scores.energy | Overview / checkins | ⚠️ Same
Soreness / stress | check_ins.scores | Overview / checkins | ⚠️ Same
Motivation flag | derived (feature_live_state) | ❌ Not displayed | ✅ Feeds `programme_ctx.live_state`
Pain flags | derived from check-in text | Notes tab (implicit) | ✅ Feeds Rule 5(b) LLM prompt
Focus-shift request | derived from check-in text | ❌ Not displayed | ✅ Feeds `programme_ctx.live_state`
Life-change flag | derived | ❌ Not displayed | ✅ Feeds live_state
Auto-deload trigger | `adherence<0.5 AND avg_rpe_7d>=8` | ❌ Not displayed | ✅ Forces deload week

### 5.2 Signal-to-action verdict
- ✅ Signals ARE consumed by the plan generator (V1 §37 audit).
- ⚠️ **Signals are NOT actionable in the coach UI.** The dashboard shows raw numbers ("Adherence 65%") without saying:
  > "Adherence fell to 65%. 2 strength sessions missed. Next week's draft volume has been reduced automatically. Review recommended."
- ❌ **No coach-side alert** when auto-deload triggers.
- ❌ **No trend visualisation** — coach sees today's numbers only, must manually compare with last week.

**Distance to V2 target:** wide. The pipeline exists (signals → plan) but the coach-facing explanation layer is entirely absent.

---

## 6. Roster experience end-to-end (§10-13)

### 6.1 Roster viewing
- ✅ Client-months page (`/coach/client-months/[id]`) with month tabs
- ✅ Multi-active-roster merge (Iter 109 fix) — both July + August months now show
- ✅ Coach roster upload (Iter 109)
- ⚠️ Duty details displayed but use backend labels in places (see §58 terminology)
- ⚠️ Historical months load per-tap — no eager cache

### 6.2 "July disappeared" root cause (Iter 109)
Traced fully. Was `_roster_days_between()` in `feature_calendar_recovery.py` filtering on `status="active"` (never set on any roster) via `find_one` (single record only). **Both bugs fixed Iter 109.**

Remaining risks:
- ⚠️ V1 has no `RosterChanged` domain event — the UI has no way to be pushed a change; it polls.
- ⚠️ Historical months rely on `is_active=True` filter — a coach who accidentally deactivates an old roster loses visibility (fix: filter should be date-based, not is_active-based, for read paths).

### 6.3 Roster upload flow
Path | Status
---|---
Client roster upload | ✅ IMPLEMENTED (existed pre-V1 audit)
Coach roster upload on behalf of client | ✅ IMPLEMENTED (Iter 109 — `feature_coach_roster_upload.py`)
Preview + edit before confirm | ⚠️ PARTIAL — parser produces days with confidence but coach cannot edit inline before confirming
Overlap detection | ✅ IMPLEMENTED
Overlap-aware supersession | ✅ IMPLEMENTED

### 6.4 Roster → programme latency
Trace:
```
Upload (~2-5s network) → Parse (5-15s Etihad/Emirates, 30-60s LLM fallback)
  → Confirm (<1s DB) → _generate_month worker (parallel Claude calls, 75s per chunk × N chunks)
  → Persist (DB) → Coach polls /roster/jobs/{job_id}
  → Coach UI refreshes
```

Observed p50: 60-90s. p95: 3-5 minutes for a 28-day roster.

**Contributing causes:**
1. ⚠️ `_generate_month` runs the FULL month in one worker — 4 concurrent Claude calls, each 30-70s.
2. ⚠️ No incremental replan — every fresh roster confirm rebuilds every day, even unchanged ones.
3. ⚠️ Coach UI polls at 2s intervals; frontend can't stream partial results.
4. ⚠️ No template cache — every workout rebuilds from LLM even if identical to last week.
5. ⚠️ Sequential heavy steps: `programme_context_for_llm` runs once but the LLM call is the bottleneck.

**Separation:** backend generation latency is 90-95% of total. Frontend visibility delay is minor (2s poll cadence).

---

## 7. Programme-by-Month flow (§13)

Coach clicks "PROGRAMME BY MONTH":
```
→ router.push(/coach/client-months/{id})
→ /api/coach/clients/{cid}/roster/months → month list
→ user selects month
→ /api/coach/clients/{cid}/roster/months/{key} → month detail
   returns: roster days + assigned workouts + confidence + coach_notes
→ per-day <ScheduleRow /> renders
```

- ✅ Regeneration doesn't happen from this page — pure view
- ⚠️ "Programme quality" is not summarised (no "8 of 8 sessions ready, weekly volume OK")
- ⚠️ Approve is per-workout, not per-month
- ❌ No preview of the plan **before** confirmation

---

## 8. Programme approval system (§23)

### 8.1 What "approval" means today
- `workouts.approved` — boolean per workout
- `workouts.coach_locked` — boolean per workout (stronger form)
- No cross-workout aggregated approval state
- ⚠️ **Client sees workouts regardless of `approved` value.** Approval affects UI badges only, not visibility.

### 8.2 Consequence
There is **NO DRAFT vs LIVE distinction** in V1. Every LLM-generated workout goes straight to the client's calendar. This is the single biggest deviation from V2's Publishing Contract.

Regeneration bypasses `approved=True` (only `coach_locked=True` and `completed=True` are protected — see V1 §42).

### 8.3 Approvals nav (`/(coach)/approvals`)
- ⚠️ Currently shows pending coach_tasks (roster-generated) primarily.
- ❌ Does not surface individual workouts needing review.
- ❌ Does not batch-approve a month.

---

## 9. Regeneration UX (§26)

Coach can trigger regeneration from:
1. `/coach/client/[id]` — buttons on the programme tab and workouts tab
2. `/coach/client-months/[id]` — per-day options
3. `/coach/workout/edit/[wid]` — regenerate this workout
4. Coach notes save automatically triggers a full-month regenerate on next roster confirmation (Iter 108)

- ⚠️ **No preview of proposed changes before regeneration** — coach commits then sees result
- ⚠️ No coach-provided context field on regeneration button — must use coach_notes to inject intent
- ❌ No "restore previous version" — regeneration overwrites in place
- ⚠️ Regeneration ambiguity: "regenerate week" vs "regenerate month" vs "regenerate one workout" use different buttons in different tabs

---

## 10. Coach-to-AI command surfaces (§27-28)

Places the coach can currently tell CrewFit what they want:
Surface | Status | Consumed by generator?
---|---|---
`users.coach_notes.cautions` free text | ✅ | ✅ Rule 9
`users.coach_notes.goal_override` | ✅ | ✅ Iter 108 profile.goal_type override
`users.coach_notes.preferences` | ✅ | ✅ Rule 9
`users.coach_notes.weekly_shape` | ✅ | ⚠️ Passes as free-text to LLM
`users.coach_notes.notes` | ✅ | ⚠️ Passes as free-text to LLM
`workouts.coach_notes` (per-workout) | ✅ | ✅ read on next generation for that date
Regenerate button (no context) | ✅ | — same input, different pass
Draft message / weekly script | ✅ | ❌ NOT consumed by plan generator
Coach direct exercise edit | ✅ | ⚠️ locks workout; not fed back as "future rule"

**Verdict:** ⚠️ **5 different mechanisms**, no unified "coach directive" system. All feed the same `WORKOUT_SYSTEM` prompt as different string slots. In V2 → single `coach_directives` structured entity.

---

## 11. Coach ↔ AI ↔ Client control matrix (§28)

Action | Coach | AI | Client | Current precedence winner
---|---|---|---|---
Create programme | Trigger (roster upload) | Generate | — | AI generates; coach approves post-hoc
Schedule session | Edit day | Places | — | AI wins unless coach relocates
Edit exercise (specific) | ✅ direct | Generates | Swap via workout log | Coach `coach_locked=True` overrides
Move workout | Coach can | AI can (on regen) | Reality flow can | Coach if locked, else last write
Change equipment | Coach can set for context | Adapts on regen | Reality flow | Ambiguous
Change goal | Coach via profile | — | Client via signup | Coach wins
Change phase | Coach via coach_notes | Auto every 4wk | — | Ambiguous — coach cannot override modulo cleanly
Regenerate | Trigger | Execute | — | Coach
Change roster | ✅ upload (Iter 109) | — | ✅ upload | Whoever confirms last
Apply recovery | Coach via directive | Auto via live_state | Reality flow | AI (silent auto-deload) → creates coach surprise
Restrict exercise | ✅ coach_notes.cautions | — | — | Coach
Approve | ✅ (per-workout, per-day, roster) | — | — | Coach
Publish (client visibility) | ❌ Not a concept | — | — | Everything is live |
Lock | ✅ `coach_locked` | — | — | Coach

**Ambiguous ownership:** phase transitions (modulo vs coach), auto-deload triggers (silent), post-hoc equipment changes.

---

## 12. Roster + Plan future workspace (§29-31)

### 12.1 Existing building blocks
- ✅ `<ScheduleRow />` component (Iter 100) — coach dashboard row for combined roster + plan
- ✅ `/coach/client-months/[id]` uses ScheduleRow for a month view
- ✅ Coach roster upload button (Iter 109)
- ✅ Multi-active-roster merged view (Iter 109)

### 12.2 What's already close to the target
| Target (V2 Coach UX §3) | V1 state |
|---|---|
| Side-by-side ROSTER / PLAN rows | ✅ ScheduleRow exists |
| Per-row status badges | ⚠️ PARTIAL — coloured but no unified badge system |
| Long-press contextual menu | ⚠️ PARTIAL — some actions exist via floating menu |
| Command bar | ❌ NOT IMPLEMENTED |
| Batch APPROVE READY | ❌ NOT IMPLEMENTED |
| "Why this?" tooltip | ❌ NOT IMPLEMENTED |
| Exception review sheet | ❌ NOT IMPLEMENTED |

### 12.3 Backend data readiness for one-shot API
To serve one date row (roster duty + programme objective + assigned workout + status + approval + lock + exceptions + coach directive + completion + readiness), the coach client-months endpoint **already** joins:
- `rosters.days[]`
- `workouts` filtered by date
- `coach_notes`
- ⚠️ Missing: exceptions, DRAFT/LIVE, decision_records, progression state

The API can be extended incrementally.

---

## 13. Duplicated schedule representations (§17, §31, §83)

Same "what's happening on 5 August?" data appears via:
1. `/coach/client/[id]?tab=calendar` → 7-day grid
2. `/coach/client/[id]?tab=roster` → day list with roster fields
3. `/coach/client/[id]?tab=programme` → day list with workout focus
4. `/coach/client/[id]?tab=workouts` → workout-first view
5. `/coach/client-months/[id]` → month-level side-by-side
6. `/(coach)/calendar` → cross-client calendar
7. `/(coach)/approvals` → items awaiting review

**No canonical schedule model shared across these views.** Each reconstructs from raw entities. Consistent state depends on all fetches being fresh — they aren't always.

---

## 14. Notes systems (§19)

Note surface | Consumed by AI? | Structured?
---|---|---
`users.coach_notes.cautions` | ✅ Rule 9 | ⚠️ semi (free text within named slots)
`users.coach_notes.preferences` | ✅ | same
`users.coach_notes.goal_override` | ✅ | same
`users.coach_notes.weekly_shape` | ⚠️ LLM sees as string | same
`users.coach_notes.notes` | ⚠️ passed as string | same
`workouts.coach_notes` (per-workout) | ✅ | ❌ free text only
`coach_scripts.*` (weekly script) | ❌ | Free text
`messages` (coach draft messages) | ❌ | Free text

- ✅ Notes ARE fed into the generator.
- ❌ NO distinction between "NOTE" (advisory / context) and "ACTIVE DIRECTIVE" (must alter plan).
- ❌ No scope on notes (persistent forever unless coach edits).

Coach can't tell CrewFit "no running until next Monday" as a scoped directive — they can only edit `coach_notes.cautions` free text, hope the LLM picks it up, and manually revert next week.

---

## 15. Check-ins, messages, admin (§20-22)

### 15.1 Check-ins
- ✅ Data captured (weekly + daily_pulse)
- ✅ Extracted signals feed live_state → generator
- ⚠️ Coach sees latest submission but not trend
- ❌ No "3 weeks of fatigue trending down" auto-summary

### 15.2 Messages
- ✅ Message history visible
- ❌ "My knee is sore" → no structured extraction into a coach directive or pain flag
- Coach must read → remember → open programme → change (5-6 steps)

### 15.3 Admin tab
Currently hosts:
- Client onboarding overrides
- Programme force-regenerate
- Live control toggles
- Delete client
- Data export
- Debug info

⚠️ **Everyday coaching operations mixed with debug/admin.** E.g. "restart client's programme" lives here even though it's a coaching action.

---

## 16. Timeline tab (§18)

- Shows chronological activity: workout completions, check-ins, roster confirmations, coach edits
- ⚠️ Overlaps with `/(coach)/changelog` — very similar data, different lens
- ⚠️ Currently a raw feed; not filterable
- Not a "programme version history" — cannot see "what did LIVE look like 3 weeks ago?"

---

## 17. Workouts tab (§16)

- List of all this client's workouts (past + future)
- Each row links to `/coach/workout/edit/[wid]`
- ⚠️ Duplicates data available in calendar + programme + client-months
- ⚠️ No sort by importance / status
- ✅ Direct edit path is functional and complete

---

## 18. Live signals card (§7 continued)

Where surfaced: `overview` tab has a "Live Signals" region with:
- Adherence %
- Missed sessions count
- Avg RPE
- Latest check-in scores

⚠️ Colour-coded but no interpretation text. No auto-deload alert. No trend chart. No "insufficient data" handling for new clients — sometimes shows 0/0 without explanation.

---

## 19. Global coach dashboard (§34-35)

`/(coach)/overview` is the coach's daily landing. Currently:
- ✅ CoachLiveFeed component (roster confirmations, workouts completed, check-ins submitted)
- ✅ CoachToDoFeed (open coach_tasks)
- ✅ CoachApprovalQueueCard (Phase 7B addition)
- ⚠️ Feeds are chronological, not prioritised
- ❌ **No unified inbox** with categories (Review Required · Programme Ready · Client Change · Roster Change · Check-in Concern · Message · System Failure)
- ❌ No SLA / freshness indicator
- ❌ Roster uploads don't create a distinct "new roster ready" alert — coach must notice the feed entry

---

## 20. Real-time / async UI (§62)

- ✅ Polling via `/api/roster/jobs/{job_id}` during generation
- ✅ Live progress via `_set_job` heartbeat
- ⚠️ Progress states: `uploading → reading → extracting → detecting → generating → coach → complete`
- ❌ No websocket / SSE — polling only
- ❌ Coach cannot see incremental workout generation ("Mon+Tue ready · Wed+Thu building")

---

## 21. Error states (§63)

Failure scenario | Coach experience
---|---
Roster parse fails | Toast + job.status=failed; must retry
Whole plan generation fails | Template fallback runs silently; source="template" on every workout; needs_coach_review flags fire; coach_task opens ("stuck_generation")
One chunk fails | Missing days silently absent from calendar
LLM times out | Same as chunk fail — SILENT
Programme partly generates | Silent gap; coach must notice
Duplicate roster days | Deduplicated silently
Exercise unavailable | `feature_v2_resolver` drops silently → workout under-filled
Client data missing (no goal) | Falls back to `general_fitness`, silent

⚠️ **Silent failures are the biggest coach-facing risk.** V2 target: explicit exceptions surface every failure.

---

## 22. Bulk actions (§64)

Bulk action | Status
---|---
Approve multiple days | ❌
Lock multiple days | ❌
Regenerate selected range | ⚠️ Whole-month only
Add directive across dates | ❌
Change phase | ⚠️ Only via coach_notes free text
Apply programme change set | ❌ (no changeset concept)

---

## 23. Client comparison / portfolio (§65)

`/(coach)/clients` list shows: name, avatar, latest activity summary.
- ✅ Basic filtering (search)
- ❌ No per-client "state at a glance" (goal · phase · today's day-type · attention flag)
- ❌ No sort by "needs attention first"

Coach scanning 30-50 clients cannot triage without opening each profile.

---

## 24. Coach workload — how it scales (§66)

Task | 10 clients | 30 clients | 50 clients | 100 clients
---|---|---|---|---
Roster upload monitoring | Fine | Manageable | Painful | Impossible
Individual workout approval | Fine (~5min/client/wk) | 30min/wk manageable | 50min/wk hard | 90-100min impractical
Check-in review | Fine | Fine (auto-scan) | Requires triage tool | Blocks
Reality-flow escalations | Rare | Manageable | Frequent | Overwhelming
Roster-change notifications | Absent → coach spot-checks | Missed | Chronic gaps | Chronic gaps
Message reading | Manual | Manual | Auto-triage needed | Auto-triage needed

**Bottleneck:** individual per-workout approval scales linearly. Everything else scales sub-linearly with better tooling.

---

## 25. Duplicated components (§59)

Duplicate | Where |
---|---
Client header | `client/[id]`, `client-months/[id]`, `workout/edit/[wid]` (three implementations)
Workout card | Overview + Calendar + Workouts + Programme tabs
Roster row | Roster tab + calendar + client-months (three variants)
Status badge | 4+ inline implementations
Date formatting | Inline everywhere
Action menu | 3+ variations (long-press, floating, header)
Month navigation | Client-months + coach calendar

---

## 26. Duplicated data fetching (§60)

Client profile page mounts fetches for:
- Client basic (`/coach/clients/{id}`)
- Roster (`/coach/clients/{id}/roster/current` implicitly via overview)
- Workouts (`/coach/clients/{id}/workouts` for calendar + workouts tab)
- Check-ins (per checkins tab)
- Messages (per messages tab)
- Habits (per checkins tab)
- Coach notes (per notes tab)
- Live signals (bundled in overview)

⚠️ Some fire regardless of active tab (data preloaded for overview's superset behaviour). Others fire per-tab on demand.

**Result:** initial client profile load fires **7-9 requests** on mount. Some duplicate (e.g. workouts fetched multiple times).

---

## 27. Terminology bleeding through (§58)

Backend labels visible to coach:
- `Layover Full Day`, `Layover Arrival Day`, `Layover Departure Day` (roster tab)
- `Turnaround Duty`, `Simulator/Training Day` (roster tab)
- `needs_coach_review` (badge text)
- `pending_confirmation` (roster status)
- `insufficient_data` (readiness signal)
- `superseded` (roster history)
- `home_standby`, `airport_standby` (standby type)

⚠️ All should be human copy. "Layover", "Overnight", "Turnaround" — no `_` characters visible.

---

## 28. Status colour system (§57)

Inconsistent:
- Green for `approved`, also for `completed`, also for `is_active`
- Amber for `needs_coach_review`, also for standby, also for warnings
- Red for `not approved`, also for `failed`, also for `missed`

No shared semantic palette. Same colour means different things across screens.

---

## 29. Mobile responsiveness (§54)

- `/coach/client/[id]` uses horizontal scrolling for tabs and some tables — usable but cramped
- `/coach/client-months/[id]` uses stacked cards on mobile — reasonable
- `/coach/workout/edit/[wid]` — usable
- Coach dashboard could not currently deliver the V2 "phone stack" layout easily without work

---

## 30. Client visibility model (§24)

**Client sees workouts immediately after generation.** No approval gate. `approved` bool exists but does not affect client rendering.

- ✅ `coach_locked=True` protects during regeneration
- ⚠️ `approved=True` is decorative
- ❌ No LIVE version
- ❌ No history of what the client USED to see

If coach edits or regenerates, client's calendar changes silently. This is the single biggest V2 blocker.

---

## 31. Permissions / safety (§85)

- ✅ Role-gated endpoints (`require_role("coach")`)
- ✅ Client-scoped queries (coach can't accidentally patch another coach's client)
- ⚠️ Destructive actions (delete client, restart programme) have no confirmation modal in some paths
- ✅ Locks respected in known regeneration paths (Iter 109 tested)
- ⚠️ Cross-coach isolation: multi-coach scenario not thoroughly tested
- ⚠️ Approval authority not modelled (any coach can approve any client's plan)

---

## 32. Audit logging (§86)

Present:
- ✅ `coach_change_log` (workout edits)
- ✅ `coach_notes_history` (structured note versions)
- ✅ `roster_audit_log` (roster edits)
- ✅ `change_log`, `day_change_log` collections
- ✅ `audit_logs` (general)
- ⚠️ No unified per-client audit view surface
- ❌ No "who last touched this workout" surfaced inline

---

## 33. Coach dashboard performance (§61)

- Initial client profile: 7-9 requests, ~1-3s to interactive on production
- Roster + workouts merged from multiple sources
- No aggregate `/coach/clients/{id}/workspace` endpoint — must query 4-5 endpoints and merge client-side
- Polling during generation adds 2s granularity

Fine for 20-40 clients. Bottleneck at 50+ if coach opens many profiles per hour.

---

## 34. Backend gaps for V2 coach dashboard (§82)

Missing:
- ❌ Aggregate client workspace endpoint (roster + programme + assignments + exceptions + progression in one call)
- ❌ Exception list per client
- ❌ Attention queue endpoint (cross-client)
- ❌ Draft/live comparison endpoint
- ❌ Change sets endpoint
- ❌ Programme summary endpoint (goal · phase · countdown · adherence · exceptions)
- ❌ Progression summary per objective
- ❌ Notification stream (roster changed, pain reported, plan ready, generation failed)

---

## 35. Single source of truth (§83)

Current entities all sharing "5 August" data:
- `rosters.days[]` (roster fact)
- `workouts` (workout fact)
- `reality_events` (adaptation history)
- `schedule_events` (client-driven changes: holiday, sickness, standby)
- `day_overrides` (coach-driven adjustments)
- `move_history` (moved workouts)

⚠️ **No canonical ScheduleDay entity.** V2 fixes this (V2 SCHEMA §8).

---

## 36. Programme approval UX (§38-40)

To be comfortable approving a plan today the coach must open individual workouts. No summary showing:
- Goal · Phase · Event countdown
- N training sessions · M recovery days
- Adherence
- Weekly objectives satisfied
- Roster coverage complete
- Exceptions / conflicts

**None of this exists as a single glanceable summary.** All information is available across 4-5 tabs but nowhere aggregated.

---

## 37. Version history (§41)

- Individual workouts have `updated_at` timestamps
- `coach_change_log` records edits
- ❌ NO programme-level version snapshots
- ❌ NO "revert to last week's plan" capability
- ❌ NO diff view

**V2 introduces plan_versions + plan_snapshots to solve this.**

---

## 38. Event management (§42)

- ✅ Event upsert endpoints exist
- ⚠️ Only ONE active event visible per client
- ❌ No priority (A/B/C)
- ❌ No connection to phase display beyond generator's internal use
- ✅ Race countdown computed in generator; not always surfaced in UI
- ❌ No post-race recovery block visible

---

## 39. Goal management (§43)

- ⚠️ Multiple goal fields (main_goal, main_goal_key, primary_goal, goal, goal_type) — see V1 audit §5
- ✅ Coach can edit via admin tab OR profile tab
- ❌ Goal change does NOT trigger regeneration automatically — coach must remember
- ⚠️ Coach sees ONE goal — no primary/secondary UI

---

## 40. Phase management (§44)

- ⚠️ Phase displayed on programme tab only if generator has computed it into a workout's `event_phase` field
- ❌ Cannot see "next phase transition date"
- ❌ Cannot manually override phase (only indirect via coach_notes)
- ⚠️ Modulo-4 cycling opaque to coach

---

## 41. Exercise + equipment editing (§45-48)

- ✅ Coach can swap exercises via `/coach/workout/edit/[wid]`
- ⚠️ Filtered to approved exercises_v2 — good
- ❌ Coach cannot pre-set equipment context for a specific date
- ❌ No "bodyweight variant vs gym variant" toggle per workout
- ⚠️ Client's post-hoc equipment adaptation appears in workout_exercise_swaps but not framed as "adapted implementation of same objective"

---

## 42. Completion + progression visibility (§49-50)

- ✅ Completion RPE, notes, sets_done visible on workout detail
- ✅ workout_sets logs per-set reps/weight/rpe
- ⚠️ Coach does NOT see "last exposure of DB Bench: 24kg × 10 RPE 8" when opening next week's Bench workout
- ❌ No progression chart per exercise
- ❌ Progression status ("progressing_well", "reduce_load") stored in progression_snapshots but not featured on the coach dashboard prominently

---

## 43. Missed sessions & readiness workflow (§51-52)

- ⚠️ Missed sessions surface only as "not completed" in adherence stats
- ❌ No importance distinction (KEY vs OPTIONAL) in the coach UI
- ⚠️ No trend visualisation for readiness — coach sees today's numbers, not "3 weeks trending down"

---

## 44. Pain / safety signal convergence (§53)

Sources that could report "knee hurts":
- Weekly check-in free text → extracted to pain_flags
- Reality flow ("sore knee" chip could exist — currently free-form)
- Coach edit → coach_notes.cautions
- Client message (unstructured)

⚠️ **They converge in the LLM prompt (via live_state) but NOT in the coach UI.** The coach must read messages, then check-ins, then know that live_state exists. No single "pain" surface.

---

## 45. Global inbox / notifications (§76)

- ⚠️ `coach_tasks` collection acts as a lightweight to-do queue
- ✅ CoachToDoFeed surfaces open tasks
- ❌ Types of triggers implemented: roster generated, plan needs review, script needs review — but NOT: pain reported, check-in concern, generation partial, roster changed after approval, event approaching

---

## 46. Scenario evaluation (§78) — real dashboard against real workflows

Scenario | Coach experience today
---|---
A. Client uploads August roster, coach immediately sees plan alongside | ⚠️ Delayed 60-180s; visible via client-months but not on landing
B. 3 of 31 days need review | ⚠️ Needs badges scattered; no filter to jump to just those 3
C. Coach disagrees with one workout | ✅ Direct edit works; but regeneration button on the whole day/week may overwrite other days too
D. Roster changes after approval | ⚠️ Coach must notice via feed; no diff or "what changed"
E. Client walks into gym and adapts | ⚠️ Change surfaces as `workout_exercise_swaps` — not framed as adapted implementation
F. Client misses key session | ⚠️ Appears in adherence; no importance flag; no "consequence shown"
G. Pain reported | ⚠️ Extracted to live_state; coach must find in check-ins or messages
H. Race 2 weeks away | ⚠️ Coach sees phase text but no "taper starting" callout
I. AI fails one workout | ⚠️ Silent gap on that date OR template fallback used silently
J. Coach wants to change next 7 days with one instruction | ❌ Not possible — must edit each

---

## 47. Code quality (§81)

Concerns in `/coach/client/[id].tsx`:
- ⚠️ 2 008 LOC single file
- ⚠️ 11-tab switch inline in JSX
- ⚠️ State fetched for tabs not visible (overview reads other tabs' data)
- ⚠️ Duplicated data fetching (workouts, roster fetched by multiple sub-blocks)
- ⚠️ Hardcoded tab configuration
- ⚠️ Business logic mixed with presentation (some data derivation inline)
- ⚠️ Prop drilling into sub-cards
- ✅ `<ScheduleRow />` extracted separately (Iter 100) — the one clean win

---

## 48. Scorecard (out of 10) — critical

Area | Score | Notes
---|---:|---
Overall coach usability | 5 | Functional but demands too much tab-hopping
Client profile usability | 4 | 11 tabs, superset overview, no attention model
Programme visibility | 5 | Data exists but spread across screens
Roster visibility | 7 | Iter 109 improvements + client-months navigator solid
Roster/programme connection | 6 | ScheduleRow is the right primitive but underused
Approval workflow | 3 | Per-workout only, no batch, no DRAFT/LIVE
AI supervision | 4 | Silent failures + no draft state
Exception handling | 2 | Coach_tasks exist but no coherent queue with categories
Programme editing | 6 | Direct workout edit is fine; whole-plan editing weak
Workout editing | 7 | Good individual-workout UX
Coach directives | 4 | Free-text slots only, no scoped structured directives
Progression visibility | 3 | Data exists, coach can't see it easily
Event visibility | 4 | Race countdown internal; not surfaced strongly
Recovery visibility | 4 | Live signals raw; no trends, no interpretation
Client monitoring | 4 | No trend view; no cross-client attention view
Multi-client scalability | 3 | Linear per-workout approval; no batch actions
Navigation | 4 | Two conflicting route groups; 11 tabs; inconsistent
Mobile usability | 5 | Client-months mobile-ready; profile page cramped
Performance | 6 | Adequate for small caseloads; not aggregated
Architectural consistency | 4 | Multiple schedule reps; multiple status vocabularies

**Weighted average: ~4.7 / 10.** Solid components exist. The framework that connects them into a coach control centre does not.

---

## 49. Ten strongest things to preserve

1. **`<ScheduleRow />` component** (Iter 100) — the germ of Roster + Plan
2. **`/coach/client-months/[id]`** — month navigator with side-by-side layout close to V2 target
3. **Coach roster upload endpoint + UI** (Iter 109)
4. **Multi-active roster merge** (Iter 109) — history preserved
5. **`/coach/workout/edit/[wid]`** — clean, focused edit surface
6. **Structured `users.coach_notes` slots** — foundation for coach_directives
7. **`CoachApprovalQueueCard`** and `CoachToDoFeed` — proto attention queue
8. **Etihad/Emirates parsers + parser_constraints** — reliable roster input
9. **`exercises_v2` + resolver** — approved-exercise pipeline
10. **`coach_change_log` + `coach_notes_history`** — audit infrastructure

## 50. Ten biggest UX problems

1. 11-tab client profile with superset overview — no clear job per tab
2. No unified attention queue — coach must scan feeds
3. No DRAFT vs LIVE — every AI-generated workout goes live silently
4. Per-workout approval doesn't scale beyond ~20 clients
5. Backend labels leak into coach UI ("Layover Full Day", "needs_coach_review")
6. No trend visualisation for signals — only today's numbers
7. Regeneration overwrites without preview
8. Silent LLM failures / partial calendars
9. No "why?" tooltip anywhere — coach cannot see reasoning
10. Pain signals converge in generator, not in coach UI

## 51. Ten biggest architecture problems

1. No canonical ScheduleDay — 4+ representations of a client's day
2. No LIVE version pointer — workouts always visible to client
3. No `RosterChanged`, `PlanReady`, `PainReported` domain events
4. Coach directives are free-text slots, not structured entities
5. Approvals nav is roster-centric; not workout/exception-centric
6. Backend has no aggregate workspace endpoint — client-side stitches many calls
7. Duplicate collections: `check_ins` + `checkins`; `exercises` + `exercises_v2`; hotel equipment vocabularies
8. Silent template fallback masks LLM failures
9. Client-side state is fetched per-tab AND partially fetched by overview superset — inconsistency
10. `_generate_month` is a monolith — no incremental replan

## 52. Ten sources of unnecessary coach workload

1. Individual workout approval (should be batch)
2. Reading messages to find "knee hurts" (should be structured)
3. Tab-hopping to answer basic client questions
4. Monitoring roster changes manually (no push alerts)
5. Regenerating whole plan to fix one workout
6. Reading check-in trends manually (no auto-summary)
7. Setting equipment context per session (no persistence pattern)
8. Copy-pasting "avoid running" into free-text notes (no scoped directive)
9. Watching progress bars during 60-90s plan generation (no incremental UI)
10. Reconciling client's post-hoc adaptations vs approved plan (no framing)

## 53. Ten areas of duplicated functionality

1. Schedule representation × 4 (calendar/roster/programme/workouts)
2. Client header × 3 (client/client-months/workout-edit)
3. Coach notes × 2 (notes tab + admin)
4. Check-ins × 3 (client tab + global inbox + individual review)
5. Messages × 2 (client tab + global inbox)
6. Approval queue split (per-workout + coach_tasks + approvals nav)
7. Timeline vs changelog vs audit_logs
8. Programme-by-month page vs programme tab
9. Legacy library + library
10. Backend regeneration triggers × 4 code paths

## 54. Ten highest-value V2 Coach Dashboard changes

1. Introduce DRAFT / LIVE — everything else stems from this
2. Batch approval UI (APPROVE 27 READY)
3. Attention queue with categorised inbox
4. Roster + Plan workspace as the client's landing tab
5. Command bar (natural-language coach instructions)
6. Structured `coach_directives` replacing free-text slots
7. "Why this?" tooltip powered by DecisionRecords
8. Progression view (last exposure + suggested next) per exercise
9. Exception surfacing with one-click resolutions
10. Aggregate client-workspace API endpoint (kills client-side stitching)

## 55. Five things to automate immediately

1. Roster change → incremental replan (not full-month)
2. Auto-approve OPTIONAL/SUPPORTING sessions if within validation
3. Bodyweight fallback for unknown equipment (already partial)
4. Missed OPTIONAL session → drop silently
5. Detect roster upload during active phase → propose phase-appropriate placements

## 56. Five things to keep coach-controlled

1. Promotion of DRAFT → LIVE
2. Goal changes
3. Injury/restriction overrides
4. Cancellation of KEY event-critical sessions
5. Multi-A event demotion

## 57. Five things clients should be allowed to adapt themselves

1. Equipment context (change to available)
2. Session duration within SAB (up to −40%)
3. Convert-to-recovery when tired
4. Move a session within the current planning window (SAB permitting)
5. Exercise swaps within same slot from approved library

---

## 58. Minimum-viable V2 Coach Dashboard

Ordered by dependency (smallest set for the biggest win):
1. **Attention queue** (global inbox + per-client exception queue)
2. **Roster + Plan workspace** (promote ScheduleRow to primary landing)
3. **DRAFT / LIVE state model + batch approve**
4. **Programme summary strip** on the workspace (goal · phase · event · counts)
5. **Structured coach directives** (replace free-text notes)
6. **Inline workout edit + regenerate with preview**
7. **Command bar** (natural language → change proposal)

Everything else can be preserved / left for later.

---

## 59. THE most important question (§106)

> If CrewFit V2 were completed tomorrow, what would stop the CURRENT Coach Dashboard from allowing one coach to effectively supervise a large caseload?

Ranked blockers:

**CRITICAL**
- No DRAFT / LIVE → any AI-authored change is instant-live → coach cannot supervise
- Per-workout approval doesn't batch → workload scales linearly with caseload
- No aggregate attention queue → coach doesn't know who needs attention first

**HIGH**
- No structured coach directives → coach cannot scope "no running this trip" cleanly
- No canonical Roster + Plan primary view → tab-hopping erodes speed
- No incremental replan → every change waits 60-90s
- Signals surfaced but not interpreted → coach must translate raw numbers

**MEDIUM**
- No "Why this?" reasoning → coach cannot audit AI decisions
- Silent failures / template fallback → coach must spot-check
- No programme version history → cannot compare or revert
- Client's post-hoc adaptations not framed as same objective → creates false alarms

**LOW**
- Backend labels bleeding into UI (cosmetic)
- Mobile density on profile page (usable, not ideal)
- Duplicate `library` + `library-legacy` routes (cleanup)

---

**End of current-state audit.**




---




<a id="part-2--screen-inventory-json"></a>

# Part 2 · Screen Inventory (JSON)


_Source file: `CREWFIT_COACH_DASHBOARD_SCREEN_INVENTORY.json`_


```json
{
  "$schema_version": "1.0",
  "generated_at": "2026-07-27",
  "source_of_truth": "CREWFIT_COACH_DASHBOARD_CURRENT_STATE_AUDIT.md",
  "convention": {
    "status_values": ["implemented", "partial", "ambiguous", "duplicated", "not_implemented", "placeholder", "deprecated_v2"],
    "route_prefix_group": "/(coach)/*",
    "route_prefix_deep": "/coach/*",
    "backend_api_prefix": "/api",
    "notes": "This inventory is descriptive only — it does not prescribe V2. Cross-reference with the audit sections for context."
  },

  "top_level_routes": {
    "group_shell": [
      { "route": "(coach)/overview",       "purpose": "Landing / activity feed",              "status": "partial",       "audit_ref": "1.1",  "loc_estimate": 620,  "notes": "Not an attention queue; scroll-based activity list." },
      { "route": "(coach)/clients",        "purpose": "Client list",                          "status": "implemented",   "audit_ref": "1.1",  "loc_estimate": 240 },
      { "route": "(coach)/approvals",      "purpose": "Approvals list",                       "status": "partial",       "audit_ref": "23",   "loc_estimate": 210,  "notes": "Roster-centric, not workout/exception centric." },
      { "route": "(coach)/checkins",       "purpose": "Cross-client check-in inbox",          "status": "implemented",   "audit_ref": "15",   "loc_estimate": 195 },
      { "route": "(coach)/messages",       "purpose": "Cross-client messages",                "status": "implemented",   "audit_ref": "15",   "loc_estimate": 180 },
      { "route": "(coach)/calendar",       "purpose": "Cross-client calendar",                "status": "ambiguous",     "audit_ref": "13",   "loc_estimate": 220,  "notes": "Overlaps per-client calendar." },
      { "route": "(coach)/exercises",      "purpose": "Exercise browser",                     "status": "implemented",   "audit_ref": "41" },
      { "route": "(coach)/library",        "purpose": "Content library",                      "status": "implemented" },
      { "route": "(coach)/library-legacy", "purpose": "Legacy library",                       "status": "duplicated",    "audit_ref": "53",   "notes": "Duplicate of /library." },
      { "route": "(coach)/videos",         "purpose": "Video library",                        "status": "implemented" },
      { "route": "(coach)/analytics",      "purpose": "Coach-side analytics",                 "status": "partial",       "audit_ref": "19" },
      { "route": "(coach)/changelog",      "purpose": "Global change log",                    "status": "partial",       "audit_ref": "16",   "notes": "Overlaps client timeline tab." },
      { "route": "(coach)/profile",        "purpose": "Coach's own profile",                  "status": "implemented" }
    ],
    "deep_links": [
      { "route": "coach/client/[id]",             "purpose": "Mega client profile — 11 tabs", "status": "partial", "audit_ref": "2", "loc_estimate": 2008, "notes": "Kitchen-sink page. Overview conditionally renders every tab's data." },
      { "route": "coach/client-months/[id]",      "purpose": "Programme by Month workspace",  "status": "partial", "audit_ref": "7", "loc_estimate": 866 },
      { "route": "coach/workout/edit/[wid]",      "purpose": "Workout editor",                "status": "implemented", "audit_ref": "17" },
      { "route": "coach/checkin/[id]",            "purpose": "Individual check-in review",    "status": "implemented" },
      { "route": "coach/scripts/[id]",            "purpose": "Weekly script editor",          "status": "partial", "audit_ref": "14", "notes": "Role unclear — not obviously wired to a coach workflow." },
      { "route": "coach/teleprompter/[id]",       "purpose": "Teleprompter for coach video",  "status": "implemented" },
      { "route": "coach/habit-review/[id]",       "purpose": "Habit review",                  "status": "implemented" },
      { "route": "coach/exercise-content",        "purpose": "Exercise content admin tool",   "status": "implemented", "loc_estimate": 949 },
      { "route": "coach/hotels",                  "purpose": "Hotel gym editor",              "status": "deprecated_v2", "audit_ref": "V2 §19", "notes": "V2 architecture removes hotels from the training path." },
      { "route": "coach/nutrition",               "purpose": "Nutrition tool",                "status": "implemented" },
      { "route": "coach/brand-images",            "purpose": "Brand images admin",            "status": "implemented" },
      { "route": "coach/demand-queue",            "purpose": "Coach demand queue",            "status": "partial", "audit_ref": "45", "notes": "Useful base for V2 exception queue." },
      { "route": "coach/draft/[id]",              "purpose": "Draft item viewer",             "status": "partial", "notes": "Role unclear — appears to be a stub." },
      { "route": "coach/ui-issues",               "purpose": "UI issues admin",               "status": "placeholder" },
      { "route": "coach/admin/coaches",           "purpose": "Coach admin",                   "status": "implemented" },
      { "route": "coach/admin/live-controls",     "purpose": "Live admin controls",           "status": "placeholder" }
    ]
  },

  "client_profile_tabs": {
    "route": "coach/client/[id]",
    "loc": 2008,
    "tabs": [
      { "id": "overview",  "unique_job": "Superset landing",       "overlap_with": ["notes","calendar","roster","programme","timeline","workouts","checkins","messages","profile"], "verdict": "overgrown" },
      { "id": "notes",     "unique_job": "Coach-facing structured coach_notes + free text", "overlap_with": ["overview","admin"], "verdict": "keep (structured directives target for V2)" },
      { "id": "calendar",  "unique_job": "7-day calendar with roster/workout markers", "overlap_with": ["roster","workouts","programme"], "verdict": "duplicated" },
      { "id": "roster",    "unique_job": "Day-by-day roster list with day_type + hotel", "overlap_with": ["calendar","programme","client-months"], "verdict": "keep primary; retire from other tabs" },
      { "id": "programme", "unique_job": "Programme summary (goal, phase, next 7d)", "overlap_with": ["overview","calendar","workouts"], "verdict": "keep primary; retire from overview" },
      { "id": "timeline",  "unique_job": "Historical activity feed", "overlap_with": ["(coach)/changelog"], "verdict": "consolidate" },
      { "id": "workouts",  "unique_job": "Workout list for this client + edit links", "overlap_with": ["calendar","programme","client-months"], "verdict": "duplicated" },
      { "id": "checkins",  "unique_job": "Check-in history + habits", "overlap_with": ["overview","(coach)/checkins"], "verdict": "keep primary" },
      { "id": "messages",  "unique_job": "Message history", "overlap_with": ["overview","(coach)/messages"], "verdict": "consolidate under global inbox" },
      { "id": "profile",   "unique_job": "Client profile fields", "overlap_with": [], "verdict": "keep primary" },
      { "id": "admin",     "unique_job": "Debug / raw controls (hosts coaching functions)", "overlap_with": ["notes","admin/live-controls"], "verdict": "split — coaching-adjacent controls should escape 'admin'" }
    ]
  },

  "duplicated_screens_data_matrix": [
    { "data": "roster_days",       "surfaces": ["overview","calendar","roster","programme","client-months"] },
    { "data": "workouts",          "surfaces": ["overview","calendar","programme","workouts","client-months","workout/edit/[wid]"] },
    { "data": "check_ins",         "surfaces": ["overview","checkins","(coach)/checkins","checkin/[id]"] },
    { "data": "messages",          "surfaces": ["overview","messages","(coach)/messages"] },
    { "data": "coach_notes",       "surfaces": ["notes","admin","overview (implicit)"] },
    { "data": "habits",            "surfaces": ["overview","checkins"] },
    { "data": "programme_summary", "surfaces": ["overview","programme","client-months (header)"] }
  ],

  "reusable_components": [
    { "name": "ScheduleRow",             "path": "src/components/coach/ScheduleRow.tsx",             "used_in": ["client-months","client/[id]/roster","client/[id]/programme"], "status": "keep" },
    { "name": "DayCard",                 "path": "src/components/coach/DayCard.tsx",                 "used_in": ["calendar","client/[id]/calendar"],                            "status": "duplicated_of ScheduleRow" },
    { "name": "WorkoutSummaryPill",      "path": "src/components/coach/WorkoutSummaryPill.tsx",      "used_in": ["overview","programme","workouts","client-months"],             "status": "keep" },
    { "name": "CheckInBadge",            "path": "src/components/coach/CheckInBadge.tsx",            "used_in": ["overview","checkins"],                                          "status": "keep" },
    { "name": "CoachRosterUploadButton", "path": "src/components/CoachRosterUploadButton.tsx",       "used_in": ["client/[id]/admin"],                                            "status": "keep (Iter 109)" }
  ],

  "backend_endpoints_by_domain": {
    "roster": [
      "GET  /api/coach/clients/{cid}/roster/months",
      "GET  /api/coach/clients/{cid}/roster/months/{key}",
      "POST /api/coach/clients/{cid}/roster/upload",
      "POST /api/roster/confirm",
      "GET  /api/roster/jobs/{job_id}",
      "GET  /api/roster/status",
      "POST /api/roster/regenerate/{month_key}",
      "POST /api/roster/versions/supersede"
    ],
    "workouts": [
      "GET   /api/coach/clients/{cid}/workouts",
      "GET   /api/coach/workouts/{wid}",
      "PATCH /api/coach/workouts/{wid}",
      "POST  /api/coach/workouts/{wid}/regenerate",
      "POST  /api/coach/workouts/{wid}/approve",
      "POST  /api/coach/workouts/{wid}/lock",
      "POST  /api/coach/workouts/{wid}/swap"
    ],
    "check_ins": [
      "GET  /api/coach/checkins",
      "GET  /api/coach/checkins/{id}",
      "POST /api/coach/checkins/{id}/reply"
    ],
    "programme": [
      "GET  /api/coach/clients/{cid}/programme",
      "POST /api/coach/clients/{cid}/programme/regenerate",
      "POST /api/coach/clients/{cid}/programme/approve",
      "GET  /api/coach/clients/{cid}/programme/timeline"
    ],
    "notes_directives": [
      "GET  /api/coach/clients/{cid}/notes",
      "PATCH /api/coach/clients/{cid}/notes",
      "POST /api/coach/clients/{cid}/reset"
    ],
    "approvals_queue": [
      "GET  /api/coach/tasks",
      "POST /api/coach/tasks/{id}/resolve"
    ],
    "v2_ready_to_wire": [
      "PATCH /api/v2/coach/clients/{cid}/flags",
      "POST  /api/v2/coach/clients/{cid}/drafts",
      "POST  /api/v2/coach/clients/{cid}/drafts/{did}/approvals",
      "POST  /api/v2/coach/clients/{cid}/plan/build",
      "POST  /api/v2/coach/clients/{cid}/plan/build-implementations",
      "GET   /api/v2/coach/clients/{cid}/exceptions",
      "POST  /api/v2/coach/clients/{cid}/jobs (kind=draft_build)"
    ]
  },

  "status_vocabulary_current": [
    { "term": "needs_coach_review", "collection": "workouts",  "type": "bool",   "meaning": "Coach hasn't reviewed this LLM output",              "consistency": "partial" },
    { "term": "approved",           "collection": "workouts",  "type": "bool",   "meaning": "Coach approved — does NOT gate client visibility",   "consistency": "partial" },
    { "term": "coach_locked",       "collection": "workouts",  "type": "bool",   "meaning": "Regeneration must skip this workout",                "consistency": "consistent" },
    { "term": "completed",          "collection": "workouts",  "type": "bool",   "meaning": "Client marked done",                                 "consistency": "consistent" },
    { "term": "is_active",          "collection": "rosters",   "type": "bool",   "meaning": "This roster feeds the plan",                         "consistency": "consistent" },
    { "term": "status",             "collection": "rosters",   "type": "enum",   "meaning": "pending_confirmation | confirmed | superseded",      "consistency": "ambiguous with is_active" },
    { "term": "source",             "collection": "workouts",  "type": "enum",   "meaning": "coaching_system | template | manual",                "consistency": "used inconsistently as review-state proxy" },
    { "term": "variants",           "collection": "workouts",  "type": "array",  "meaning": "green/amber/red duration variants",                  "consistency": "clean" }
  ],

  "notification_surfaces": [
    { "surface": "(coach)/approvals",   "shows": ["pending coach_tasks (roster-generated)"], "audit_ref": "8.3" },
    { "surface": "(coach)/checkins",    "shows": ["new client check-ins"], "audit_ref": "15" },
    { "surface": "(coach)/messages",    "shows": ["new client messages"],  "audit_ref": "15" },
    { "surface": "coach/demand-queue",  "shows": ["exercise-content request tasks"], "audit_ref": "45" },
    { "surface": "coach/client/[id] overview tab", "shows": ["mixed activity (roster changes, workouts, check-ins)"], "audit_ref": "2" }
  ],

  "missing_capabilities_relative_to_v2": [
    "attention_queue_across_clients",
    "attention_queue_within_client",
    "batch_approval_ui",
    "draft_vs_live_split",
    "programme_version_history_browsable",
    "why_this_tooltip_on_assignments",
    "structured_coach_directive_editor",
    "progression_memory_view_per_exercise",
    "command_bar_natural_language",
    "roster_change_domain_event_push",
    "signal_to_action_narrative",
    "coach_alert_on_auto_deload",
    "trend_visualisation_per_signal",
    "cross_client_portfolio_snapshot",
    "sla_and_response_time_dashboard",
    "load_test_baseline_p95"
  ],

  "metrics_needed_but_not_captured": [
    "time_to_first_action_after_client_open",
    "clicks_per_approval",
    "clicks_per_regenerate",
    "cross_tab_hop_count_per_session",
    "approval_backlog_size",
    "median_backlog_age_hours",
    "p95_dashboard_load_ms",
    "p95_client_profile_load_ms",
    "client_count_per_coach_hour",
    "reality_change_frequency_per_client_week"
  ],

  "safety_and_permissions": {
    "role_gates": [
      { "gate": "require_role('coach')", "coverage": "consistent on all /api/coach/* endpoints" }
    ],
    "audit_logging_present": ["coach_actions_log", "workout_change_log (partial)"],
    "audit_logging_missing": ["per-tab open events","per-field-edit trail","assignment move audit","draft build lineage"]
  },

  "known_dead_or_stub_screens": [
    "coach/ui-issues", "coach/draft/[id]", "coach/admin/live-controls",
    "(coach)/library-legacy"
  ]
}

```



---




<a id="part-3--v2-gap-map"></a>

# Part 3 · V2 Gap Map


_Source file: `CREWFIT_COACH_DASHBOARD_V2_GAP_MAP.md`_


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




---




<a id="part-4--v2-operating-model"></a>

# Part 4 · V2 Operating Model


_Source file: `CREWFIT_COACH_DASHBOARD_V2_OPERATING_MODEL.md`_


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




---




<a id="part-5--coach-workflow-audit-v1v2-traces"></a>

# Part 5 · Coach Workflow Audit (V1→V2 traces)


_Source file: `CREWFIT_COACH_WORKFLOW_AUDIT.md`_


# CrewFit Coach — Workflow Audit

**Version:** Iter 111 · 2026-07-27
**Companion to:** `CREWFIT_COACH_DASHBOARD_CURRENT_STATE_AUDIT.md` · `CREWFIT_COACH_DASHBOARD_V2_GAP_MAP.md` · `CREWFIT_COACH_DASHBOARD_V2_OPERATING_MODEL.md`

**Purpose:** For each real workflow the coach actually performs, trace it end-to-end on today's V1 UI. Count clicks, tabs, latency and friction. Show where V2 collapses the flow.

---

## 0. Reading this document

Every workflow section has four fields:

- **Trigger** — what starts it
- **V1 path (today)** — literal click-by-click trace
- **Friction** — the specific cognitive or UX cost
- **V2 target path** — what the flow becomes after `P11 Coach Dashboard V2`

Click counts are conservative estimates from the current codebase (`/app/frontend/app/(coach)/*.tsx` and `/app/frontend/app/coach/**/*.tsx`).

---

## 1. Morning triage — "what needs me today?"

**Trigger:** Louis opens the app.

**V1 path (today):**
1. Land on `(coach)/overview` — activity feed
2. Open `(coach)/approvals` — read pending roster-generated tasks
3. Open `(coach)/checkins` — scan new check-ins
4. Open `(coach)/messages` — scan new messages
5. For each flagged client: open `/coach/client/[id]` → decide what to do
6. If a client changed something: open their `overview` tab → scroll → hop into `programme` or `roster` tab

**Click / tab count:** ~12-25 depending on flagged-client count. **Time:** 8-15 min.

**Friction:**
- No single queue — coach has to visit 3 tabs to see the full picture
- Age of the oldest un-handled item is not visible anywhere
- Approvals nav is roster-centric, not workout-centric — coach misses individual workouts needing eyes
- Overview scrolls chronologically; latest changes bury older un-handled items

**V2 target path:**
1. Land on Attention Panel — one queue
2. Filter or scroll — every row has kind, severity, age, one-line reason
3. Batch-approve or one-click resolve inline

**Target clicks:** 3-8. **Target time:** 2-4 min.

---

## 2. A client uploads a new roster

**Trigger:** Push/badge indicates a new roster arrived (or coach uploads on their behalf via Iter 109 button).

**V1 path (today):**
1. Coach opens `/coach/client/[id]`
2. Overview → sees "roster uploaded"
3. Opens `roster` tab → scrolls new days
4. Opens `programme` tab OR `client-months` page → waits for `_generate_month` job to finish (p50 60-90s, p95 3-5 min)
5. When ready → opens each affected workout → reviews → approves
6. If a chunk fails → coach must know to re-trigger regeneration manually
7. Coach may need to re-open notes tab to nudge context and regenerate again

**Click / tab count:** ~15-40 per roster confirm. **Time:** 5-15 min of coach attention (spread over minutes of wait).

**Friction:**
- No preview of the plan **before** confirmation
- No incremental replan — every full-month rebuild
- No template cache — identical weeks rebuild from LLM every time
- Coach polls at 2s intervals; frontend can't stream partial results
- Coach must re-read the roster to guess what changed relative to previous version

**V2 target path:**
1. New roster arrives → P4 builds ScheduleDays automatically
2. P5+P6 build an incremental DRAFT (only affected days) in ≤60 s
3. Attention Panel shows: "Roster changed · 3 days affected · DRAFT ready"
4. Coach opens Roster+Plan workspace → sees DRAFT delta highlighted → command bar available for tweaks → batch approves

**Target clicks:** 4-8. **Target time:** 2-5 min.

---

## 3. Reviewing an LLM-produced workout for the first time

**Trigger:** Coach opens the client's programme.

**V1 path (today):**
1. `/coach/client/[id]` → `programme` tab OR `workouts` tab
2. Sees list of workouts — no filter by "needs review"
3. Clicks a workout → `/coach/workout/edit/[wid]` opens full editor
4. Reads the exercise list — no rationale visible
5. Coach opens `notes` tab in a separate hop if they need to check goal/preferences
6. Decides: edit / regenerate / approve / lock
7. Clicks Approve → `needs_coach_review=false`
8. Clicks Lock (optional) → `coach_locked=true`

**Click / tab count:** ~8-15 per workout. **Time:** 2-5 min per workout.

**Friction:**
- No "Why this?" — coach has to infer the rationale from goal + phase + exercise list
- Editor is a full-page nav away; loses roster context
- No batch approve
- No filter by "needs review" on the workouts tab

**V2 target path:**
1. Attention Panel row: "3 KEY workouts need review"
2. Multi-select → batch approve
3. For any workout, click "Why this?" → DecisionRecord chain drawer (rule id, confidence, previous state)
4. Edit inline in a drawer on the same page

**Target clicks:** 2-3 per approved workout · 4-6 per edited workout.

---

## 4. Client reports pain in a check-in

**Trigger:** Client submits a check-in mentioning knee pain.

**V1 path (today):**
1. `(coach)/checkins` list → click the check-in
2. `/coach/checkin/[id]` opens with free-text and scores
3. Coach reads → identifies pain region
4. Nav to `/coach/client/[id]` → `notes` tab → adds pain to `cautions` free-text
5. Nav to `programme` tab → triggers full-month regeneration (so LLM Rule 5b avoids knee patterns)
6. Waits for regeneration
7. Reviews affected workouts

**Click / tab count:** ~10-15. **Time:** 5-10 min plus regen wait.

**Friction:**
- Pain is captured as free-text in one place, but the deterministic plan gate is spread across a separate rule engine.
- Coach must remember to trigger regeneration explicitly.
- No structured directive — future coach's-eyes-view can't easily list active cautions.

**V2 target path:**
1. Attention Panel row (auto-generated): "Client X · pain flag: knee (from check-in)"
2. Coach clicks "Add directive" → structured `coach_directives(kind=avoid_movement, parameters={pattern:'deep_squat'})`
3. P5 auto-recomputes ONLY affected assignments within the SAB rules
4. DRAFT delta ready → batch approve

**Target clicks:** 3-5. Regeneration is incremental and background.

---

## 5. Client wants to swap an exercise

**Trigger:** Client messages "can I swap barbell squat for goblet squat this week?"

**V1 path (today):**
1. `(coach)/messages` → read the request
2. Nav to `/coach/client/[id]` → programme tab → find the workout
3. `/coach/workout/edit/[wid]` → find the exercise in the list → replace it
4. Save → reply to the client in messages

**Click / tab count:** ~8-12. **Time:** 3-8 min.

**Friction:**
- Two round-trips through separate screens
- Every swap loses history (no audit of "coach honoured this request")
- Client can't do this themselves

**V2 target path:**
- If SAB permits → **client does it themselves** (P7 adapt endpoint). Coach never sees it.
- If SAB blocked → Attention Panel row: "Client X requested exercise swap on {date}"; coach clicks "Approve" → applied automatically.

**Target clicks:** 0 (SAB-permitted) or 1-2 (escalated).

---

## 6. Adding a new client's programme from scratch

**Trigger:** A new client finishes DNA / onboarding.

**V1 path (today):**
1. `(coach)/clients` → find the new client → open profile
2. `notes` tab → set goal_override, cautions, weekly_shape, preferences (5 free-text fields)
3. `programme` tab → verify goal detected
4. If a race event is entered → coach adds an event via `/coach/client/[id]` (implementation varies by event category feature)
5. Confirm the roster (if uploaded)
6. Wait for `_generate_month` → review each workout → approve

**Click / tab count:** ~15-30. **Time:** 15-25 min.

**Friction:**
- Goal is a free-text `main_goal_key` field, not a first-class object
- Coach notes are 5 buckets of unstructured text
- No timeline classification is shown ("this goal is compressed / high_risk")
- Events → discipline mapping is inferred, not explicit

**V2 target path:**
1. Coach opens client → sees onboarding intake pre-mapped to a `goals[]` primary goal + timeline_class banner ("compressed — 8 weeks to a marathon")
2. Coach adjusts weight / priority if needed → programme built automatically (phase machine picks the sequence)
3. Coach reviews the auto-built Attention Panel items and approves

**Target clicks:** 4-8 for a straightforward client.

---

## 7. Adjusting a phase transition

**Trigger:** Coach knows client's foundation phase should extend by 1 week (their week has been hard).

**V1 path (today):**
1. `/coach/client/[id]` → programme tab
2. Read what "phase" the plan is in (modulo 4-week bucket + heuristics)
3. Add a note in `weekly_shape` → save
4. Trigger a regenerate → wait
5. Re-check that next 7 days shifted

**Click / tab count:** ~6-10. **Time:** 3-5 min + regen wait.

**Friction:**
- Phase is not an editable entity — coach can only nudge via free-text notes
- No visibility of when the phase is scheduled to change
- No structured "extend phase by 1 week" control

**V2 target path:**
1. Client workspace → phase strip at top (per `programme_phases`)
2. Coach clicks current phase → "Extend by 1 week" → DecisionRecord written, DRAFT delta produced
3. Coach approves

**Target clicks:** 3.

---

## 8. Missing a KEY session

**Trigger:** Client didn't complete Tuesday's key strength session (marked missed).

**V1 path (today):**
1. `/coach/client/[id]` → overview shows adherence dropped
2. Coach must open workouts tab → find the missed session → decide whether to re-schedule this week or absorb into next
3. If reschedule → coach edits the date directly → saves
4. Adherence updates on next check-in aggregation cycle

**Click / tab count:** ~7-12. **Time:** 4-8 min.

**Friction:**
- No automatic cascade proposal — coach must invent the fix
- Progression memory not visible (would the next KEY session be too heavy given the missed exposure? unclear)

**V2 target path:**
1. Attention Panel row (auto): "Client X · missed KEY upper_strength (Tuesday). Proposed: re-place Thursday, shift Thursday's easy_run to Friday."
2. Coach clicks "Apply proposal" → DRAFT delta ready → approve

**Target clicks:** 2.

---

## 9. Regenerating a whole month because coach notes changed

**Trigger:** Coach updates `weekly_shape` note in `/coach/client/[id]` → notes tab.

**V1 path (today):**
1. Save note (implicit trigger)
2. Next roster confirmation triggers full-month regeneration (Iter 108 behaviour)
3. All non-locked workouts rebuild
4. Coach must re-review each workout

**Click / tab count:** ~10-30 (per re-review workout). **Time:** 10-25 min.

**Friction:**
- Full-month regen instead of impact-limited replan
- Coach must re-review every workout to trust it

**V2 target path:**
1. Note becomes a `coach_directive` on save
2. P3 (demand engine) evaluates whether the directive touches active phase priorities
3. If yes → incremental replan of affected windows only
4. Attention Panel: "Directive applied · N assignments touched · DRAFT delta ready"
5. Coach reviews delta only

**Target clicks:** 2-5.

---

## 10. Reviewing decision provenance ("Why is this workout on Tuesday?")

**Trigger:** Coach questions why a specific day has a specific session.

**V1 path (today):**
1. Coach must reconstruct the reasoning from:
   - `main_goal_key` on user profile
   - Latest active event + priority
   - Current phase (bucketed by modulo 4)
   - Coach notes free-text
   - The workout's `focus` and `source` fields
2. No single place shows the causal chain

**Click / tab count:** ~10-15 across 4-5 tabs.

**Friction:**
- Coach doesn't trust the plan when they can't explain it
- Time spent on this is pure overhead

**V2 target path:**
1. Coach clicks any assignment → "Why this?" drawer
2. Chain of DecisionRecords rendered oldest→newest: goal → phase → objective → assignment → implementation
3. Every entry has a human_readable_reason field
4. Coach reads and moves on in seconds

**Target clicks:** 2.

---

## 11. Cross-client portfolio management

**Trigger:** Louis wants to know: which of my 30 clients are at risk this week?

**V1 path (today):**
1. `(coach)/clients` → scroll list → open each in turn
2. Adherence + RPE badges vary by tab
3. No sort by "risk"
4. No "quiet" state visible

**Click / tab count:** ~30-60 (linear scan). **Time:** 15-30 min.

**Friction:**
- Everything is per-client
- No portfolio scorecard

**V2 target path:**
1. `(coach)/clients` shows a scorecard: name · timeline_class · adherence trend · attention items · next KEY date
2. Sort by any column
3. Filter: "unread ≥24h", "adherence <70%", "event within 4 weeks"

**Target clicks:** 1-3 to identify at-risk clients.

---

## 12. Publishing preview before it goes live

**Trigger:** Coach wants to see the next 4 weeks before the client does.

**V1 path (today):** **Not possible.** Every LLM output is client-visible immediately. Coach's only knob is `coach_locked`, which is per-workout.

**V2 target path:**
1. Coach opens Roster+Plan workspace → DRAFT column always shows the next-scope plan
2. Client sees LIVE (`plan_versions.live_plan_version`)
3. Coach reviews DRAFT → approves scopes → new PlanVersion published → client sees it

Publication is deliberate, not incidental.

---

## 13. Reverting a bad plan

**Trigger:** Coach discovers Monday's plan is wrong (e.g. included a KEY session on a duty day due to a stale roster).

**V1 path (today):**
1. Coach opens each affected workout → edits back
2. Or coach regenerates the month → hopes the roster is right this time
3. History of what changed is not queryable — no version snapshots

**Click / tab count:** ~15-30. **Time:** 10-20 min.

**Friction:**
- No revert — only forward edits
- No ability to see prior state cleanly

**V2 target path:**
1. Coach opens client workspace → History tab → last 5 PlanVersions listed with published_at + approval scope
2. Click prior version → "Revert to this" → new PlanVersion created from old snapshot; previous versions retained
3. Client's LIVE updates within 15 s

**Target clicks:** 2.

---

## 14. Handling a client's equipment change

**Trigger:** Client messages "I'm in a hotel this week — only bodyweight."

**V1 path (today):**
1. `(coach)/messages` → read
2. Coach nav to `/coach/client/[id]` → find each affected day
3. Manually edit each workout to bodyweight versions
4. Reply to client

**Click / tab count:** ~10-20. **Time:** 5-12 min.

**Friction:**
- Client can't declare this themselves
- Coach has to think through movement pattern substitutions per exercise

**V2 target path:**
- Client uses "Change equipment" chip in their app → within SAB → auto-adapted with green-variant workout; coach never notified except in the "informational" tab of Attention Panel.
- If SAB exceeded → escalated → coach one-click accept.

**Target clicks (coach):** 0-1.

---

## 15. Cohort of coach workflows summarised

| Workflow | V1 clicks | V1 time | V2 clicks | V2 time |
|---|---:|---:|---:|---:|
| Morning triage | 12-25 | 8-15 min | 3-8 | 2-4 min |
| Roster upload → published | 15-40 | 5-15 min | 4-8 | 2-5 min |
| Review one workout | 8-15 | 2-5 min | 2-3 | <1 min |
| Handle pain from check-in | 10-15 | 5-10 min | 3-5 | 2-3 min |
| Client requests exercise swap | 8-12 | 3-8 min | 0-2 | 0-1 min |
| Onboard new client | 15-30 | 15-25 min | 4-8 | 6-10 min |
| Extend a phase | 6-10 | 3-5 min | 3 | 1 min |
| Missed KEY session | 7-12 | 4-8 min | 2 | 30 s |
| Regen after notes change | 10-30 | 10-25 min | 2-5 | 2-4 min |
| "Why this?" investigation | 10-15 | 3-8 min | 2 | 30 s |
| Portfolio scan (30 clients) | 30-60 | 15-30 min | 1-3 | 3-5 min |
| Publish preview | not possible | — | native | — |
| Revert bad plan | 15-30 | 10-20 min | 2 | <1 min |
| Client hotel-only week | 10-20 | 5-12 min | 0-1 | 0-1 min |

**Total per-client per-week estimate:** V1 ~50 min → V2 ~20 min (per V2 architecture success metric).

---

## 16. Highest-friction pinch points to eliminate first

Ranked by expected coach-time savings:

1. **No cross-client attention queue** → Attention Panel · P1+P11
2. **Full-month regen bottleneck** → Incremental replan · P5+P6
3. **No DRAFT** — nothing to review before it hits client · P1 (backend done) + P11 UI
4. **11-tab client profile forcing tab-hopping** · P11
5. **No "Why this?" chain** — coach can't trust the plan · P1 (backend done) + P11 UI
6. **Client can't adapt within SAB** → shifts coach load · P7 (backend done) + client UI
7. **Free-text coach notes** — no structured directives · P10 (backend done) + P11 UI
8. **Roster upload → published latency (90+ s)** · P4-P6 incremental + template cache
9. **No revert** — coach lives in fear of pressing regenerate · P1 (backend done) + P11 UI
10. **No portfolio scorecard** — coach scans 30 clients linearly · P11

Backend for items 1, 3, 5, 6, 7, 9 is already shipped through P1–P10 + P12. The remaining lift is P11 (Coach Dashboard V2) + a modest amount of client-side adaptation UI.

---

**End of workflow audit.**




---

