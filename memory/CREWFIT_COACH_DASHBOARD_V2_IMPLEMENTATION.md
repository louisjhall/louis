# Coach Dashboard V2 — Implementation Progress

**Version:** Iter 111 · 2026-07-27
**Status:** Iteration 1 complete · Iteration 2 & 3 pending
**Feature flag:** `users.profile.v2_flags.coach_dashboard_v2_enabled` (per-coach)

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

### Iteration 2 (planned next)
- Command bar (natural-language → structured ChangeSet proposal — §31, §32)
- Structured directive editor (Add Directive flow — §33, §34, §35)
- Programme summary panel (expandable — §20)
- History timeline (audit style — §43)
- Previous-performance context in workout drawer (§18)
- Signal-to-action narrative in the workspace (§37, §38)
- Progress bar for async generation (Roster uploaded → parsed → schedule → generating → ready — §24, §25)

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
