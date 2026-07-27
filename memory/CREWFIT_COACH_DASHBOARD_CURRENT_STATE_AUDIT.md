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
