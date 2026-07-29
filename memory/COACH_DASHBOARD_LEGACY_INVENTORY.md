# Coach Dashboard — Legacy Inventory

Read-only. Every V1 concept currently reachable by a coach in the deployed UI.

## L. Legacy pages (still reachable via URL but hidden from sidebar)

| ID | Route | Component | Risk |
|---|---|---|---|
| L1 | `/(coach)/overview` | `overview.tsx` — V1 Home | Uses V1 `workout_assignments`; still functional; no direct destructive action |
| L2 | `/(coach)/library-legacy` | `library-legacy.tsx` — self-labelled "LEGACY · V1" | Read-only; low risk |
| L3 | `/coach/client/[id]` | 2,084-line V1 client profile | Owns admin AND V1 programme controls — **mixed danger** |
| L4 | `/coach/draft/[id]` | Legacy draft editor | Orphaned (no current V2 flow links here) |
| L5 | `/coach/client-months/[id]` | Legacy monthly view | Uses V1 `WorkoutQuickActions` |
| L6 | `/coach/workout/edit/[wid]` | V1 workout deep-edit | Still reachable from V1 daily-view links |
| L7 | `/coach/hotels` | Hotel review queue | Not needed for training; still used by nutrition-travel |

## A. Legacy Actions (buttons/controls) — P0 CANDIDATES

Any of these can *silently* invoke old programme generation on a V2 client.

### A1 · `[id].tsx` (V1 client profile) — reachable via ADMIN button in workspace header

| Line | Button testID | Backend call | Risk |
|---|---|---|---|
| 1074 | `programme-regenerate` | `POST /coach/clients/{id}/programme/regenerate` | **P0** — legacy generator, overwrites live plan |
| 1060 | `programme-approve` | `POST /coach/clients/{id}/programme/approve` | **P0** — bypasses V2 publish gate |
| — | (calls `regenerate-preview`) | `POST /coach/clients/{id}/programme/regenerate-preview` | **P1** — read-only preview but confusing beside V2 |
| — | (calls `regenerate-apply`) | `POST /coach/clients/{id}/programme/regenerate-apply` | **P0** — applies preview to live |

### A2 · `WorkoutQuickActions` component (used on `client-months/[id]` and `CoachLiveFeed`)

| Line | Button | Backend call | Risk |
|---|---|---|---|
| 101 | Regenerate | `POST /coach/workouts/{id}/regenerate` | **P0** for V2 clients — writes to V1 `workouts` |
| 115 | Approve | `POST /coach/workouts/{id}/approve` | **P0** for V2 clients |
| 123 | Lock | `POST /coach/workouts/{id}/lock` | **P0** for V2 clients |

### A3 · `InlineWorkoutEditor` (deep-edit)

- Reads/writes `db.workouts` for V1 clients. For V2 clients it should route to `/v2/coach/clients/{id}/plan/implementations/{impl_id}` — verify per-client-kind dispatch. **P0** if dispatch is missing.

### A4 · `CoachApprovalQueueCard` on `/overview` — shows V1 pending approvals

- Reads `/coach/pending-approvals` which mixes V1 + V2 items. Approving a V1 item on a V2 client is a live-data mismatch. **P1**

### A5 · `CoachLiveFeed` on `/overview`

- Shows V1 workout activity for all clients. For V2 clients, completion data lives in `workout_implementations` — feed under-reports. **P1**

## B. Legacy backend endpoints still reachable from coach frontend

| Endpoint | Location | Callers |
|---|---|---|
| `POST /coach/clients/{id}/programme/regenerate` | `feature_programme_quality.py:1367` | `client/[id].tsx` |
| `POST /coach/clients/{id}/programme/approve` | `feature_programme_quality.py:1523` | `client/[id].tsx` |
| `POST /coach/clients/{id}/programme/regenerate-preview` | `feature_coach_workout_editor.py:487` | `client/[id].tsx` |
| `POST /coach/clients/{id}/programme/regenerate-apply` | `feature_coach_workout_editor.py:588` | `client/[id].tsx` |
| `POST /coach/clients/{id}/reset-programme` | `feature_coach_reset.py:34` | Not currently linked from UI |
| `POST /coach/clients/{id}/approve-programme` | `feature_programme_status.py:306` | Not currently linked from UI |
| `POST /coach/workouts/{wid}/regenerate` | `feature_coach_deep_edit.py:273` | `WorkoutQuickActions` |
| `POST /coach/workouts/{wid}/approve` | `feature_coach_deep_edit.py:100` | `WorkoutQuickActions` |
| `POST /coach/workouts/{wid}/lock` | `feature_coach_deep_edit.py:149` | `WorkoutQuickActions` |
| `POST /coach/workouts/{wid}/move` | `feature_coach_deep_edit.py:202` | `InlineWorkoutEditor` for V1 |
| `PATCH /coach/workouts/{wid}` | `feature_coach_workout_editor.py:98` | V1 workout editor |
| `GET /coach/pending-approvals` | `feature_coach_v1.py` | `overview.tsx`, `approvals.tsx` |
| `GET /coach/dashboard` | `feature_coach_v1.py` | `overview.tsx` |
| `GET /coach/equipment-mismatches` | `feature_coach_v1.py` | `overview.tsx`, badge in `/clients` |
| `POST /brand-images/{id}/regenerate` | `feature_brand_images.py:508` | own-domain, safe |
| `POST /coach/messages/{draft_id}/regenerate` | `feature_coach_v1.py:278` | Messages AI redraft — not programme |

## C. Legacy visible labels

- `Training Intelligence V1` / `Training Intelligence V2` pills — **removed iter 128c** ✓
- "Engine V2 · Roster required" / "Engine V2 · No Draft" / "Engine V2 Draft" — **renamed iter 128c** to "Programme · …" ✓
- "V2 Home (New)" / "Overview (V1)" — **removed iter 128c** ✓
- "Switch to V1" chip on Home — **removed iter 128c** ✓
- "Back to V1 Overview" link on onboarding card — **removed iter 128c** ✓
- `library-legacy.tsx` — still shows "LEGACY · V1" and "OPEN V2" (page hidden from nav but self-labelled)
- `[id].tsx` — no user-visible V1/V2 label but structurally the "V1 workspace"

## D. Feature flags currently in circulation

| Flag | Location | Purpose | Default | Still needed? |
|---|---|---|---|---|
| `coach_dashboard_v2_enabled` (on user doc) | `feature_v2_coach_dashboard.py` | Gate for V2 home vs V1 | `true` for coaches created post-flip | YES (safety net — do not remove yet) |
| `engine_v2_enabled` (on user doc) | `feature_v2_state_foundation.py` | Route client through V2 planner vs V1 | `true` for post-migration clients | YES (used by dispatch logic) |
| Global `default_engine_v2` (migration) | `migrations/v2_flip_default.py` | Flip default to V2 | Applied | Retire once all clients migrated |

**Recommendation**: keep all three during clean-up; retire after "final removal" phase.

## E. Legacy scripts (not user-visible but capable of running)

- `scripts/pietro_shadow_run.py` — writes to V1 `workout_assignments` (guarded by env; not scheduled)
- `scripts/pietro_safe_reset.py` — V1 reset (guarded)
- `migrations/v2_flip_default.py` — idempotent, already applied

## F. Collections we must NOT delete (yet)

`workout_assignments`, `workouts`, `workouts_archive`, `programmes` — these still back legacy read paths (calendar fallback, analytics fallback, `client-months`, `[id].tsx`). Deletion would produce silent 500s in mixed pages.
