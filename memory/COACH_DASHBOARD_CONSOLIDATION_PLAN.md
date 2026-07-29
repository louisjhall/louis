# Coach Dashboard — Consolidation Plan

Read-only recommendations. **Do not execute until user confirms.**

## §32 — Recommended final information architecture

```
SIDEBAR
├─ Home                         (attention queue + summary — /(coach)/v2-home renamed)
├─ Clients                      (canonical directory — /(coach)/clients)
├─ Calendar                     (cross-client schedule — /(coach)/calendar, V2-only reads)
├─ Approvals                    (V2-only pending items — /(coach)/approvals rewired)
├─ Library                      (Exercise Library — /(coach)/library)
├─ Videos                       (/(coach)/videos)
├─ Messages                     (/(coach)/messages)
├─ Analytics                    (/(coach)/analytics, unified adherence)
├─ Change Log                   (/(coach)/changelog)
└─ Admin                        (coach list + system controls)
     ├─ Coaches                 (/(coach)/admin/coaches)
     └─ System                  (/(coach)/admin/live-controls)

CLIENT WORKSPACE  (single canonical URL: /coach/client/{id}/workspace)
├─ Plan                         (default — Roster + Draft + Live + Flight Support + Directives + Exceptions)
├─ Check-ins
├─ Messages
├─ Progress
├─ History
├─ Goals / Profile              (consolidated from V1 controls + V2 goals)
└─ ADMIN button                 (opens drawer: Reset password / Archive / Delete / Coach assignment / Preview)
```

No more separate "V1 client profile" URL surfacing. The `client/[id].tsx` file remains as the admin drawer target, with V1 programme controls stripped/hidden.

## §33 — Every feature classified

| Feature | Class |
|---|---|
| V2 Home operations dashboard | **KEEP** |
| V1 Overview page | **HIDE LEGACY** (already hidden iter 128c; retire after 2 iters) |
| `/clients` rich directory | **KEEP** |
| Home client table | (removed iter 128c) |
| Workspace canonical (`workspace.tsx`) | **KEEP** |
| Legacy client profile (`client/[id].tsx`) — admin block | **MIGRATE** — split off admin drawer, keep as backing store |
| Legacy client profile — V1 programme card | **HIDE LEGACY** (return empty for V2 clients) |
| Legacy client profile — regenerate/approve buttons | **REMOVE LATER** (P0 blockers) |
| `WorkoutQuickActions.regenerate|approve|lock` | **REMOVE LATER** (P0 blockers) |
| Calendar | **MIGRATE** (V2-only endpoint) |
| Approvals | **MIGRATE** (V2-only endpoint or per-kind dispatch) |
| Analytics | **MIGRATE** (unified adherence) |
| `/client-months/[id]` | **HIDE LEGACY** |
| `/coach/draft/[id]` | **HIDE LEGACY** |
| `/coach/workout/edit/[wid]` | **HIDE LEGACY** for V2 clients — dispatch on client-kind |
| `/library-legacy` | **HIDE LEGACY** (already hidden) |
| `/coach/hotels` (training use) | **HIDE LEGACY** for training |
| `/coach/hotels` (nutrition/layover use) | **KEEP** underneath |
| `PreviewLauncher` on Overview | **REMOVE LATER** (when Overview retired) |
| `CoachToDoFeed` / `CoachLiveFeed` / `CoachApprovalQueueCard` / `ExerciseMediaSummary` | **HIDE** on Overview; keep as components used inside workspace where appropriate |
| Flight Support (protocol modal + carousel + notifier + variety engine) | **KEEP** |
| Universal Travel / Change Setup | **KEEP** |
| Exercise Content editor (with PILOT persona) | **KEEP** |
| Media Queue (via `/library` MISSING filter) | **KEEP** |
| Feature flags (`coach_dashboard_v2_enabled`, `engine_v2_enabled`, `default_engine_v2`) | **KEEP** underneath |
| V1 collections (`workout_assignments`, `workouts`, `workouts_archive`, `programmes`) | **KEEP** underneath (until final removal) |
| Global check-ins page | **KEEP** |
| Global messages page | **KEEP** |
| Change log page | **KEEP** |
| Admin: Coaches | **KEEP** |
| Admin: live-controls | **KEEP** under Admin submenu |
| Client Preview button on `/clients` | **KEEP** |
| Preview Sandbox on `/clients` | **KEEP** |
| `client-months/[id]` | **HIDE LEGACY** (link removed) |
| Nutrition coach queue | **KEEP** |
| Brand images / social studio / demand queue | **KEEP** as admin-only |
| UI issues page | **ADMIN ONLY** |

**Nothing left "NEEDS DECISION"** — every visible feature has a class above. If any listed as HIDE/MIGRATE/REMOVE needs sign-off, that's covered in §34 priorities.

## §34 — Priority ordering

### P0 — Ship next (safety critical)

1. **Neutralise V1 generation surfaces for V2 clients**:
   - In `[id].tsx`: hide/return-empty the `programme-regenerate`, `programme-approve`, `programme-regenerate-preview`, `programme-regenerate-apply` buttons when the client's `kind === "v2"` (or `engine_v2_enabled`).
   - In `WorkoutQuickActions.tsx`: hide Regenerate/Approve/Lock for V2 workouts (dispatch on the workout being a V1 `workouts` doc vs V2 `plan_live_v2_implementations`).
   - Split `/coach/pending-approvals` per-kind server-side or filter client-side.

2. **Dispatch `InlineWorkoutEditor` per client-kind**: V1 → `PATCH /coach/workouts/{wid}`, V2 → `PATCH /v2/coach/clients/{id}/plan/implementations/{iid}`.

### P1 — Ship soon (confusion killers)

3. Move V1 client controls (flexibility / injury caution / progression speed / video touchpoint) from `[id].tsx` INTO the workspace `goals` tab. Then convert the ADMIN button to open a **narrow drawer** with only: Reset password, Archive, Delete, Coach assignment, Preview.
4. `Calendar` endpoint: return only V2 data for V2 clients; per-day pill click routes to `/v2/coach/clients/{id}/plan/implementations/{iid}` (not `/coach/workout/edit/{wid}`).
5. `Analytics` endpoint: unify adherence calculation across V1 `workout_assignments` and V2 `workout_implementations`. Show combined completion.
6. Shrink Client status vocabulary to canonical set (Needs Attention · Draft Ready · Live · Roster Required · Profile Incomplete · No Action). Retain V1-only chips for V1 clients until migration complete.

### P2 — Cleanup

7. Retire `/(coach)/overview` (redirect → `/(coach)/v2-home`).
8. Retire `/(coach)/library-legacy` (redirect → `/(coach)/library`).
9. Retire `/coach/client-months/{id}` (redirect → workspace roster grid).
10. Retire `/coach/draft/{id}` (redirect → workspace Plan tab).
11. Collapse pipeline status card to a single `Live vN` badge once Published.
12. Remove `PreviewLauncher` component when Overview is retired.

### P3 — Cosmetic

13. Remove `library-legacy.tsx` self-label "LEGACY · V1".
14. Remove remaining code comments referencing V1/V2 where they describe user-facing behavior (do not touch code identifiers).
15. Sweep for any remaining "V2" or "New" text.

## Recommended cleanup order (single-batch)

1. **P0 shipset** — bulletproof V2 clients against legacy generation
   - Hide `programme-regenerate` + `programme-approve` for V2 clients
   - Dispatch `WorkoutQuickActions` on workout kind
   - Filter `/coach/pending-approvals` per-kind
   - Effort: **SMALL** (~2h)
2. **P1 shipset** — one canonical experience
   - Move V1 controls into workspace goals tab
   - Convert ADMIN button to drawer (Reset PW · Archive · Delete · Coach assignment · Preview)
   - Rewire Calendar + Analytics per-kind
   - Shrink status vocabulary
   - Effort: **MEDIUM** (~4-6h)
3. **P2 shipset** — retire legacy pages
   - Redirect Overview / library-legacy / client-months / draft
   - Effort: **SMALL** (~1h)
4. **P3 shipset** — polish
   - Effort: **SMALL** (~30m)

**Total complexity: MEDIUM.** No engine changes, no data migrations, no destructive DB ops. All work is UI dispatch + one-time page redirects.

## Estimated total effort

| Phase | Complexity | ~Hours |
|---|---|---|
| P0 | SMALL | 2 |
| P1 | MEDIUM | 5 |
| P2 | SMALL | 1 |
| P3 | SMALL | 0.5 |
| **TOTAL** | **MEDIUM** | **~8-9 hours of focused work** |

## What must remain underneath for now

- `client/[id].tsx` — as admin-drawer backing (with V1 programme controls hidden)
- `overview.tsx` — as URL-only fallback
- All V1 collections (`workout_assignments`, `workouts`, `workouts_archive`, `programmes`)
- Legacy backend endpoints (still hit for V1 clients / nutrition-travel / layover-naming)
- All three feature flags

## What can eventually be removed (post final V1 client migration)

- V1 endpoints: `/coach/clients/{id}/programme/regenerate|-approve|-preview|-apply`, `/coach/workouts/{wid}/regenerate|approve|lock|move`
- V1 collections
- Legacy pages: `overview.tsx`, `library-legacy.tsx`, `client-months/[id].tsx`, `draft/[id].tsx`, `workout/edit/[wid].tsx`
- Feature flags after >30 days of clean telemetry
