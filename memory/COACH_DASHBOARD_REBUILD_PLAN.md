# CrewFit — Roster + Plan Workspace · Phase A / B Execution Plan

Handoff document for next session. Tonight (Iter 100 → 108) is ready to publish. Next session picks up Phase A of the coach dashboard rebuild.

## Ship queue tonight (nothing new to build, just verify + publish)
- Iter 100 — Roster chips (client home hero + calendar)
- Iter 101 — Post-workout rating sheet (Smooth/Light/Heavy/Diverted)
- Iter 102 — Layover destination naming (`ICN Layover Hotel Gym Strength`)
- Iter 103 — CrewFit logo on female images + Louis face no longer darkened + British male voice for guided flow
- Iter 104 — Louis welcome video (bundled 4 MB, autoplay muted on web + unmuted on native)
- Iter 105 — CrewFit intro animation on cold launch + post-onboarding (12h cooldown, autoplay, tap-to-skip)
- Iter 106 — Single timeline (removed duplicate NEXT 5 DAYS), full logo top-left, prominent standalone UPLOAD ROSTER button, airline-agnostic copy
- Iter 107 — Coach dashboard SCHEDULE tab with `Date | Roster | Assigned Plan` rows (`ScheduleRow` component)
- Iter 108 — Coach note text parser: extracts goal/frequency/equipment and overrides profile before LLM. Marathon clients now get 5 sessions/week with proper strength + runs instead of mobility filler.

**eas.json fix already applied** — no `_comment` field. Publish should now clear the pipeline.

---

## Phase A — Foundation (next session, ~2-3 hrs) — ✅ COMPLETE (Iter 109)

### A1 — Diagnose + repair "July disappeared" for Louis Hall (`5a019f2a-d001-42c8-b875-eba4d3d3ccf1`) — ✅ FIXED
- Root cause: `_roster_days_between()` in `feature_calendar_recovery.py` filtered on `status="active"` (never actually set on any roster in DB) via `find_one` — so it returned nothing. Meanwhile `/roster/current` returned just the newest active roster via `find_one`.
- Fix: both now query ALL `is_active=True` rosters and merge days by date (newest wins on conflict). Each day carries `_source_roster_id` so the day-picker routes edits back to the correct roster.
- Verified: 17/17 backend tests green (6 unit + 11 HTTP integration in `tests/test_iter109_coach_roster_http.py`). Louis Hall's account now returns 62 merged days across July + August.

### A2 — Coach uploads roster on behalf of client — ✅ SHIPPED
- New file `feature_coach_roster_upload.py` with two endpoints:
  - `POST /api/coach/clients/{cid}/roster/upload-parse` — coach-role gated, parses to a pending roster owned by the client, stamps `uploaded_by='coach'` + `uploaded_by_coach_id`.
  - `POST /api/coach/clients/{cid}/roster/pending/{rid}/confirm` — coach-side confirm that bypasses the client-side low-confidence review gate (coach IS the reviewer), reuses the overlap-aware deactivation + generation pipeline.
- Frontend: `<CoachRosterUploadButton />` on `/coach/client/[id]` action row and `/coach/client-months/[id]` header + empty state. Auto-confirms on the coach's behalf and polls the generation job to completion.
- Uses SAME roster collection. Same downstream generation.

### A3 — Preview + confirm before save — ⏳ DEFERRED to Phase B (owned by workspace redesign)
- Current implementation auto-confirms on coach's behalf. Inline preview + edit lands with `<ScheduleRow>` enrichment in Phase B.
- Big red "Save Roster & Generate Plan" button UX will follow in Phase B.

---

## Phase B — Roster + Plan workspace (next-next session)

### B1 — New primary tab in coach client profile
- Component: `<RosterPlanWorkspace clientId={cid} />`
- Route: replace or supplement `/coach/client-months/[id]` as the primary view.
- Reuses `<ScheduleRow>` built in Iter 107 as the row component.

### B2 — Enrich `ScheduleRow`
Currently shows: DOW/date · Roster label · Assigned plan title.
Need to add:
- **Roster block:** flight sectors with report/depart/arrive/off times; layover hotel + departure; standby window; time zones on flying days.
- **Plan block:** status pill (AI Ready / Approved / Needs Review / Conflict / Coach Edited / Locked), rationale ("Why?") on tap.
- **••• menu:** Open workout / Change plan / Regenerate / Add coach directive / Edit roster day / Move workout / Copy / Rest day / Lock / Approve.
- **Colour tone:** already implemented (Home blue, Standby amber, Flight red, Layover purple, Turnaround orange, Rest neutral).

### B3 — Top-of-month approval bar
- Counts: `X Ready · Y Need Review · Z Coach Edited · W Conflict`
- Buttons: `REVIEW Y` (filters to needs-review rows) + `APPROVE READY DAYS` (bulk approve) + `APPROVE AUGUST PLAN` (once resolved).
- Uses existing `POST /coach/clients/{cid}/approve-programme` — extend to accept a filter `{ ready_only: true }` for bulk approve.

### B4 — Month navigation
- Tabs: `‹ July 2026 | August 2026 | September 2026 ›` at top of workspace.
- Dropdown alternative on small screens.
- All months where roster data exists remain available.

### B5 — Roster History drawer
- Small link in workspace corner: "Roster History".
- Opens drawer listing every roster upload with timestamp + uploaded_by.

---

## Phase C — Intelligence & directives (session 3)

### C1 — Coach CrewFit command box
- Free-text input at top of workspace.
- Backend: new endpoint `POST /coach/clients/{cid}/plan-command` accepts a natural-language string.
- Uses Claude (Emergent LLM key) to interpret the instruction into structured edits (dates + planned changes).
- Returns diff — coach clicks Apply Changes to commit.
- Cost per command: ~$0.005 (small Claude call).

### C2 — Scoped coach directives
- New collection: `coach_directives` with `{ client_id, scope, applies_from, applies_until, text, active }`.
- Scope options: `this_day` / `this_trip` / `this_week` / `until_changed`.
- Injected into `_generate_month` LLM prompt like existing `coach_notes` — but with scope-aware filtering.
- Iter 108's text-parser extends to read these too.

### C3 — Per-day + period regeneration
- `POST /coach/workouts/{wid}/regenerate` — single day.
- `POST /coach/clients/{cid}/regenerate?from=YYYY-MM-DD&to=YYYY-MM-DD` — period. Skips locked + approved days.
- Optional `context_note` param appended to LLM prompt just for this regen.

### C4 — Smart replan on roster change
- On roster upload: compute date-set delta against existing programme.
- For overlapping dates only, regenerate. Non-overlapping approved days untouched.
- Return diff for coach to Accept All / Review.

### C5 — Lock day / period
- Field on workout: `locked: bool`.
- Generator + regen respect the flag.
- 🔒 icon on locked rows.

---

## Phase D — Uniformity & polish (session 4)

### D1 — Same workspace in Overview + Programme + Timeline
- Refactor those tabs to embed `<RosterPlanWorkspace mode="compact">` or link out to it.
- Single source of truth for schedule display.

### D2 — Mobile stacked cards
- Below breakpoint 600px, `ScheduleRow` transforms to stacked layout:
  ```
  WED 05 AUG
  ROSTER    → DXB Layover · Arrived 06:25
  CREWFIT   → Hotel Full Body · 30 min · Dumbbells
  Status: AI Ready ✓
  •••
  ```

### D3 — Persistent "Today" mini-header
- Small persistent bar in every coach client profile tab:
  `TODAY · LHR → JFK · Travel / Recovery`
- Click → back to Roster + Plan on today's row.

### D4 — Live Signals feed the LLM
- Extend `_generate_month` prompt to include `live_state` from last 14d check-ins.
- If energy_avg < 5, reduce volume 20%. Notes surface as "Programme adjusted due to low energy last 3 check-ins."

---

## Phase E — Data architecture (parallel design pass before code)

### E1 — Design new `client_schedule` collection
- Key: `{ client_id, date }` unique compound index
- Fields: `roster_data`, `workout_id`, `status`, `coach_directives`, `ai_rationale`, `approved_at`, `approved_by`, `locked`, `change_history[]`
- Migration script: for each existing user, walk rosters + workouts, produce one row per date.
- Rosters, workouts, coach_directives all become references, not owners of dates.

### E2 — Migration + backfill
- Non-destructive migration: build the new collection alongside existing. Verify parity. Cut over reads first, then writes.
- Verify: no `client_schedule` row is missing where a `rosters.days[].date` exists.

### E3 — Rewire endpoints
- All schedule reads go through `client_schedule` lookup by `client_id + date range`.
- Solves the "July disappeared" class of bug at the architecture level.

---

## Important architectural rule (from user's spec)
> Do not create different versions of roster dates, calendar dates, programme dates, workout assignments that can become unsynchronised. There should be one canonical client schedule keyed primarily by client_id + date.

This is Phase E. Every other phase is UI over the existing dual-collection model. Phase E is what makes the whole thing bulletproof long-term.

---

## Test coverage plan
- `test_coach_roster_upload.py` — coach uploads on behalf of client, user_id lands on target client.
- `test_roster_month_preservation.py` — uploading Aug does not remove July.
- `test_coach_note_overrides.py` — Iter 108 marathon fix cases + edge cases (existing goal wins).
- `test_client_schedule_migration.py` — new collection matches legacy for random samples.
- `test_regenerate_scoped.py` — per-day / week / month respect locked + approved.

## Handoff notes
- All new coach-facing copy: Louis-branded, aviation-professional, NO "AI" or "generated" wording.
- New API endpoints: coach-role gated, tests must include unauthorised coach → 403.
- Emergent LLM key already wired (Claude sonnet 4.5). New Claude calls should reuse the existing `call_claude` helper in server.py.
- Deploy: bump `app.json` versionCode for each real ship. Never touch `eas.json` custom fields (crashes EAS validation — see EAS_README.md).
