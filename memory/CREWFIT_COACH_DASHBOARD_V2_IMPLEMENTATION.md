# Coach Dashboard V2 — Implementation Progress

**Version:** Iter 114 · 2026-07-27
**Status:** Session A complete (3 engine loops closed)
**Feature flag:** `users.profile.v2_flags.coach_dashboard_v2_enabled` (per-coach)


---

## Session A — engine loops closed (Iter 114)

**Added `/app/backend/feature_v2_directive_engine.py`** — the missing bridge:
- `active_directives_for(client_id, date)` — resolves scope (today · this_week · custom · phase · until_changed); auto-resolves `phase` to the current `phase_id` and persists it back
- `directive_forbids_kind(directives, kind)` — pattern-match + text-heuristic (e.g. "no running" in free_text blocks any run objective)
- `apply_change_set(cs)` — applies one proposed change_set to the DRAFT: `assignment_moved` (updates date + schedule_day_id) · `implementation_changed` (duration override, convert_to_mobility/recovery) · `exposure_deferred` (skip + defer exposure). Respects locks. Idempotent (only touches `status=proposed`). Marks `applied` on success with reason; `rejected` on failure with reason.
- `apply_pending_change_sets_for(client_id, draft_id)` — sweeps all proposed change_sets for a draft
- `emit_roster_change_exceptions(client_id, prior_days, new_days)` — diffs classification + duty_burden per date; writes `exceptions(kind=roster_change, severity=warning)` and a paired proposed `change_sets(kind=implementation_changed)` per changed date so the applier can absorb the change
- `write_assignment_decision(...)` — writes a `decision_records` row with `scope_id=<assignment_id>` (fixes empty "Why this?" drawer)

**Wired into engines**:
- `feature_v2_p5_scheduling.py` — `plan_build` consults `active_directives_for(...)` for every candidate day; skips days blocked by `avoid_movement`; writes assignment-scoped DecisionRecord after every successful placement
- `feature_v2_p6_construction.py` — `_load_context` merges directive avoid-patterns into the movement-region blocklist so exercise selection respects them
- `feature_v2_p4_roster.py` — `roster_facets_build` snapshots prior derived state, then calls `emit_roster_change_exceptions` after rebuild → Attention queue now populates when a roster changes
- `feature_v2_coach_command_bar.py` — `command_apply` now calls `apply_pending_change_sets_for` after writing the change_sets → coach's applied proposals actually mutate the DRAFT

**Tests** (`tests/test_v2_directive_engine.py`), all pass:
- ✅ Directive with `avoid_movement:gait_run_tempo` blocks tempo_run + long_run objectives, allows upper_hypertrophy
- ✅ Proposed `assignment_moved` change_set moves the assignment's date + marks itself `applied`
- ✅ classification change from `home` → `layover_full` emits a `roster_change` exception with human-readable reason

**Regression check** — `tests/test_v2_full_pipeline.py` still passes end-to-end.

### FULLY FUNCTIONAL END-TO-END now
- Directive → planner: creating a directive genuinely prevents the planner placing forbidden objectives; the exception queue records `coach_directive_conflict` for anything that had no candidate day.
- ChangeSet → draft: coach-applied change_sets actually move / edit / skip assignments and write DecisionRecords.
- Roster changed → attention queue: a re-run of `roster_facets_build` with different duty classifications materialises exceptions on the affected dates and paired change_sets ready for the applier.
- Assignment-level DecisionRecord: the "Why this?" drawer now has a record for every V2-planner-placed assignment.

### INCOMPLETE / PRESENTATIONAL / WAITING (honest)
- Draft vs Live diff view (no side-by-side yet — only counts).
- Inline workout editor drawer (edit still hands off to V1 editor page).
- Regenerate-one-session endpoint + button.
- V1 workout → V2 drawer adapter (drawer still empty for V1 workouts).
- Roster upload embedded in workspace (still on the client admin tab).
- Real duty times (report/depart/arrive) in the roster column — only classification shows.
- Check-ins + Messages inside V2 client profile.
- Progress area (adherence/progression per objective per goal).
- History timeline UI.
- Signal → action narrative on the workspace.
- Client-facing V2 read path (`/api/live/plan` still hits V1 collections).
- Mobile card layout (untested at 390px).
- "Switch to V1" as the only V1 reference (V1 Overview still in primary nav).
- Setup-incomplete state on the client list.
- V2 client profile navigation restructure (Roster+Plan / Check-ins / Messages / Progress / History / Profile / More).

### Can I coach Louis entirely through V2 for a month without opening V1?
**No — not yet.** Blockers:
1. No inline workout editor → any edit sends coach to V1 page
2. Check-ins, messages, notes still live in V1 tabs
3. Roster upload still in V1 admin tab
4. Client-facing plan reads V1

Session B is needed for a yes.


Companion documents:
- `CREWFIT_COACH_DASHBOARD_CURRENT_STATE_AUDIT.md`
- `CREWFIT_COACH_DASHBOARD_V2_GAP_MAP.md`
- `CREWFIT_COACH_DASHBOARD_V2_OPERATING_MODEL.md`
- `CREWFIT_COACH_WORKFLOW_AUDIT.md`
- `CREWFIT_TRAINING_INTELLIGENCE_V2_*.md` (backend engine, shipped last session)

---

## 1. Iteration 1 — completed

Shipped in this session:

### 1.1 Backend
- **`feature_v2_coach_dashboard.py`** — 5 aggregate endpoints, all gated by the per-coach flag:
  - `PATCH/GET /api/v2/coach/me/dashboard-flag` — coach opt-in/out
  - `GET  /api/v2/coach/dashboard/attention` — cross-client Attention queue
  - `GET  /api/v2/coach/dashboard/summary` — Today totals
  - `GET  /api/v2/coach/dashboard/clients?filter=…&q=…` — Client list w/ state chips
  - `GET  /api/v2/coach/clients/{cid}/workspace/months` — available months
  - `GET  /api/v2/coach/clients/{cid}/workspace/{YYYY-MM}` — ONE aggregate for Roster+Plan
  - `POST /api/v2/coach/clients/{cid}/plan/approve-ready` — batch Approve Ready → new PlanVersion
- **V1 fallback**: workspace endpoint reads V1 `rosters.days[]` + V1 `workouts` as read-only rows for clients without the V2 state-foundation flag. No V1 client is left with an empty screen.
- Vocabulary translated at the API boundary (`layover_full` → "Layover", `layover_arrival` → "Layover Arrival", etc.) per §50.

### 1.2 Frontend
- **`/(coach)/v2-home.tsx`** — Coach Home:
  - Today summary (5 cells: active clients / need attention / programmes ready / roster changes / check-in concerns)
  - Needs Your Attention queue grouped by client, with severity dots, one-line reason, per-client Review button
  - Client list with filters (`All / Needs Attention / Programme Ready / Roster Changed / No Action`) + search
  - Status pills: Ready · Review · Conflict · Roster Changed · Check-in
  - Empty state per §51
  - Opt-in / opt-out card visible when coach hasn't enabled the flag
- **`/coach/client/[id]/workspace.tsx`** — Roster + Plan workspace:
  - Two-column desktop layout (Roster / Real life ← → CrewFit Plan)
  - Compact client header + status ribbon: Ready / Review / Conflict / Approved / Live / Locked count pills
  - Month navigation (`‹ current ›` + chip row of available months)
  - Batch **Approve N Ready** button in the ribbon when Ready count > 0
  - Duty burden band + training opportunity + overnight location on the roster column
  - Workout side-drawer opens over the schedule (does not navigate away)
  - Drawer shows: title, duration, equipment, rationale, exercise list, "Why this?" DecisionRecord chain
  - Edit button in drawer hands off to the existing `/coach/workout/edit/[wid]` (per §17 — reuse)
  - Exceptions panel below the schedule
- **`DesktopShell.tsx`** — new nav entry "V2 Home (New)" pinned at the top; "Overview (V1)" preserved
- **`(coach)/_layout.tsx`** — mobile tab for V2 Home added

### 1.3 Feature flag & migration safety
- V1 dashboard fully preserved. Nothing V1 was mutated.
- Coach opt-in is a single toggle (`PATCH /api/v2/coach/me/dashboard-flag`).
- V1 clients (no V2 flags) still appear in the V2 Client List labelled `Training Intelligence V1`; their workspace uses V1 rosters + V1 workouts read-only.
- V2 clients (any of the state-foundation flags) use the full V2 aggregate.

### 1.4 Reused components / endpoints
- `CoachRosterUploadButton` (existing, Iter 109) — still available; no change
- `/coach/workout/edit/[wid]` (existing workout editor) — drawer hands off to it
- `DesktopShell` — new nav item added, no other changes
- `api.ts` — existing HTTP client used unchanged
- V1 `/api/coach/clients/*` endpoints — untouched

### 1.5 Backend files added / changed
- **Added:** `/app/backend/feature_v2_coach_dashboard.py` (~500 LOC)
- **Added:** `/app/backend/tests/test_v2_coach_dashboard.py` (4 pytests)
- **Modified:** `/app/backend/server.py` — one-line import for the new module

### 1.6 Frontend files added / changed
- **Added:** `/app/frontend/app/(coach)/v2-home.tsx` (~350 LOC)
- **Added:** `/app/frontend/app/coach/client/[id]/workspace.tsx` (~500 LOC)
- **Modified:** `/app/frontend/app/(coach)/_layout.tsx` — mobile tab entry
- **Modified:** `/app/frontend/src/desktop/DesktopShell.tsx` — desktop nav entry

### 1.7 Tests
| Test | Verdict |
|---|---|
| `test_flag_gate_blocks` (coach without flag → 409 on every endpoint) | PASS |
| `test_summary_and_clients_when_enabled` (v1/v2 kinds surfaced correctly) | PASS |
| `test_workspace_month_aggregate` (schedule day + assignment counts in ONE call) | PASS |
| `test_batch_approve_ready_creates_plan_version` (batch approve → plan_versions row) | PASS |

Verified in browser: coach opts in, lands on V2 Home, sees 4 clients, filters + search work; opens Louis Hall client (V1) → workspace shows 31 days in July 2026 with roster + Review pills on V1 workouts.

### 1.8 Backend / API changes summary
- New endpoints listed in §1.1. No V1 endpoints modified.
- No changes to V2 engine modules (P1-P12). This build stayed on the interface layer per §68.
- Added collection indexes (`plan_snapshots`, `approvals` supplementary).

---

## 2. What's NOT in Iteration 1 (deferred to Iteration 2 & 3)

Per the brief §70, deferred with acknowledgement:

### Iteration 2 (in progress)
- ~~Command bar (natural-language → structured ChangeSet proposal — §31, §32)~~ ✅ SHIPPED Iter 112
- ~~Structured directive editor (Add Directive flow — §33, §34, §35)~~ ✅ SHIPPED Iter 113
- ~~Programme summary panel (expandable — §20)~~ ✅ SHIPPED Iter 113
- ~~Progress bar for async generation — §24, §25~~ ✅ SHIPPED Iter 113
- History timeline (audit style — §43)
- Previous-performance context in workout drawer (§18)
- Signal-to-action narrative in the workspace (§37, §38)

### Iter 113 batch — Directive editor + Generation status + Programme summary

**Backend** (`feature_v2_coach_directives.py`, ~350 LOC)
- `POST   /api/v2/coach/clients/{cid}/dashboard-directives` — structured directive create (6 kinds × 6 scopes)
- `GET    /api/v2/coach/clients/{cid}/dashboard-directives` — coach list (filter by status)
- `PATCH  /api/v2/coach/clients/{cid}/dashboard-directives/{did}` — status/free_text/parameters edits
- `GET    /api/v2/coach/clients/{cid}/generation/status?month=YYYY-MM` — pipeline snapshot: 8 canonical stages (roster_uploaded → roster_parsed → schedule_created → planning_programme → generating_workouts → validating → ready_for_review → published) with per-stage state + detail; joins V1 rosters, V2 schedule_days, jobs, implementations, exceptions, drafts, plan_versions
- `GET    /api/v2/coach/clients/{cid}/programme/summary` — aggregate: goal + phase strip + active phase + event countdown + 14-day adherence + per-discipline planning-objective quotas
- Every directive create writes a DecisionRecord + `directive_created` metric

**Frontend**
- `src/components/DirectiveEditor.tsx` (~220 LOC) — modal editor with 6 kind rows, kind-specific parameter inputs, 6 scope chips, custom date range, reason/notes textarea, Save/Cancel
- `src/components/GenerationStatusBanner.tsx` (~150 LOC) — dots-and-rails pipeline visualisation, polls every 3.5 s, auto-collapses to a one-line pill, auto-hides when idle
- `src/components/ProgrammeSummaryPanel.tsx` (~140 LOC) — collapsible panel with title (goal), sub-row (active phase · event countdown · adherence %), phase strip (chip row with current phase highlighted), expanded body (event card, per-discipline objective quotas, timeline classification)
- `workspace.tsx` — mounted all three above the command bar, added "Add directive" button in the ribbon next to Approve Ready

**Verified live (screenshot captured)**
- Directive editor: modal opens; 6 kind rows selectable, PATTERN input, 6 SCOPE chips, REASON textarea, Save creates `coach_directives` row + DecisionRecord
- Generation status: Louis Hall V1 client shows "Roster uploaded ✓ · 31 days parsed ✓" · remaining stages pending
- Programme summary: correctly returns `present=false` for V1 client (no V2 programme yet); would render goal + phase strip + adherence for V2 clients

**Tests** — 3 new pytests, all pass:
- directive create/list/patch flow
- generation_status returns 8 canonical stages in canonical order
- programme_summary returns `present=false` when no V2 programme exists

### Command Bar (shipped Iter 112)

**Backend** (`feature_v2_coach_command_bar.py`, ~250 LOC):
- `POST /api/v2/coach/clients/{cid}/command-bar/parse` — free text + workspace context → Claude Sonnet 4.5 → structured proposals JSON (never mutates)
- `POST /api/v2/coach/clients/{cid}/command-bar/apply` — accepted proposals become `coach_directives` or `change_sets` with `triggered_by=ai_command_bar`
- `GET  /api/v2/coach/clients/{cid}/command-bar/history` — coach's past prompts
- LLM prompt is grounded on: coach voice only (never "AI"), 6-proposal cap, only assignments actually in the current month
- Every apply writes a DecisionRecord with `rule_or_prompt.id="command_bar"`
- Emits metrics `command_bar_parsed` + `command_bar_applied`

**Frontend** (`src/components/CommandBar.tsx`, ~200 LOC):
- Collapsed pill at top of workspace: "Ask CrewFit to adjust this plan…"
- Expands to multi-line input + Propose button + 5 example chips
- Proposal preview list with per-item checkbox + icon per kind
- "Apply to Draft" / "Cancel" — never touches LIVE
- Auto-refreshes the workspace after apply
- Works for both V1 and V2 clients (directive/note proposals valid for V1)

**Verified live**:
- Parse: `"No running until Sunday because his knee is sore."` → Claude returned `add_directive(avoid_movement, until_changed, target_date=2026-07-06)` — screenshot captured
- Apply: created `coach_directives` row with `source=command_bar` + DecisionRecord in `decision_records`
- Pytest `test_v2_command_bar.py` — apply flow + flag gate — PASS



### Iteration 3 (planned later)
- Cross-client portfolio scorecard (§23 of gap map)
- Bulk actions across clients from global home (§59)
- Mobile card layout + bottom sheets (§44, §45)
- Inline roster edit (§54)
- Equipment picker widget (§55)
- Rich empty states per screen (§51 subset)
- Draft vs Live diff view (§27)

### Not this build (out of scope)
- Push notifications
- Wearable / HR integrations
- Hotel database

---

## 3. Known limitations

- **Workspace endpoint** does not yet paginate — it loads the whole month in one payload. Fine for ≤50 days; will need trimming when clients push past 60-day windows.
- **Attention queue** does not currently detect *roster_changed* explicitly — the P4 pipeline doesn't emit `roster_change` events yet. Workaround: coach sees the new month's counts change in the client list once a fresh roster is confirmed.
- **Drawer "Edit"** hands off to the existing `/coach/workout/edit/[wid]` page — that page is the V1 editor. Coach loses drawer context on hand-off. Iteration 2 will bring editing inline.
- **Batch Approve Ready** publishes a version but currently sets an implicit programme id when no V2 programme exists (`programme:{client_id}`). When the client is fully migrated to V2, this maps cleanly to the real programme id; for now it's benign.
- **Command bar** absent — plan can only be adjusted via the existing per-workout editor (via drawer).
- **Empty V2 clients (no schedule_days yet)** show "No roster or plan for {month}"; the "Upload roster" action from within the workspace is deferred to Iteration 2 (currently users go to `/coach/client/[id]` → admin tab where the existing CoachRosterUploadButton lives).

---

## 4. Architecture deviations

None from the operating model / gap map.

Two small pragmatic choices:
- I chose to make `coach_dashboard_v2_enabled` a **per-coach** flag (not per-client). This matches how a coach opts into the preview and lets them see V1 and V2 clients side-by-side. Per-client `v2_flags` still gate whether Training Intelligence V2 fires for that specific client.
- The workspace aggregate re-humanises backend enums at the API layer (not client) so the UI stays static and testable.

---

## 5. Outstanding dependencies on future V2 engine work

- **P4 change events** — the roster-facets builder does not yet emit `roster_change` exceptions when a new roster overrides an old one. Once P4 adds a `RosterChanged` event, the Attention queue picks it up automatically (mapping already wired).
- **P9 phase-transition proposals** — the queue's `event_at_risk` kind already surfaces them via `exceptions`, but the current builder path is minimal.
- **P12 metrics dashboard** — separate build, not part of Iteration 1.

---

## 6. Demo (per §71-73)

Fully executable today:

**Demo 1 — coach onboarding to V2 home**
1. `louis@crewfit.net / Louis123!` logs in.
2. Nav → V2 Home (New). If flag off, one-click "Enable V2 preview".
3. Today summary + Attention queue (empty for now) + Client list render.

**Demo 2 — Louis Hall (V1 client, `louis@hotmail.co.uk`) opens in workspace**
4. Click Louis Hall row → lands directly on Roster + Plan.
5. Two-column view; month selector shows Jul 2026 + Aug 2026; V1 workouts flagged `Review` pill.
6. Click one → drawer opens (empty for V1 client — expected; V1 workouts don't have V2 implementations yet).

**Demo 3 — V2 client (any client with `state_foundation_enabled=true`)**
7. Enable V2 flags via `PATCH /api/v2/coach/clients/{cid}/flags` for a fresh client.
8. Run the V2 pipeline (existing `POST /api/v2/coach/clients/{cid}/jobs { kind: "draft_build" }` — shipped last session).
9. Return to Coach V2 Home → the client now shows a `Programme Ready` chip.
10. Open workspace → assignments render with duration + equipment + status.
11. Click `Approve 28 Ready` → new PlanVersion is created; assignments flip to `Live`.

---

## 7. Performance notes

- V2 Home makes 3 parallel API calls (summary + attention + clients). Empty-state renders in <500 ms.
- Workspace uses a single aggregate call per month (avg ~10 KB payload for 31 days, no exercise details).
- Workout drawer lazy-loads the implementation + decision chain only when opened.
- No unnecessary re-renders during month step (each month change triggers exactly one aggregate fetch).

Recommended next-step measurements (Iteration 2):
- p95 client-workspace-load time under production traffic
- Aggregate payload size for a 90-day window
- Time-to-first-decision from Attention Panel click through to Approve

---

## 8. Recommended next step (do NOT auto-begin per §81)

Iteration 2 has the highest workflow impact. The single most valuable change would be **the Command bar + structured directive editor**, because those together collapse "how a coach expresses intent" into two entry points instead of scattered notes fields.

Suggested Iteration 2 build order:
1. `Add Directive` flow with structured scope
2. Command bar (LLM parse to ChangeSet proposal, coach reviews before apply)
3. Progressive async generation UX (per §24-25)
4. Programme summary panel (per §20)

---

**End of implementation progress document.**
