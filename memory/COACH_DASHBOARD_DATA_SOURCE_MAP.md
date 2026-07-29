# Coach Dashboard — Data-Source Map

Read-only. Traces every coach screen to the backend collections/endpoints it reads/writes.

## Legend

- **V1 collection**: `workout_assignments`, `workouts`, `workouts_archive`
- **V2 collection**: `plan_drafts_v2`, `plan_live_v2`, `plan_live_v2_implementations`, `workout_implementations`, `schedule_days`, `objective_exposures`, `programme_versions`
- **SHARED**: `users`, `rosters`, `rosters_versions`, `flight_support_activity`, `flight_support_overrides`, `directives`, `check_ins`, `coach_notes`, `decision_records`, `personal_activities`

## Screen → data source(s)

| Screen / component | Endpoint(s) | Collections read | Collections written | Class |
|---|---|---|---|---|
| `v2-home` (Home) | `/v2/coach/dashboard/summary`, `/v2/coach/dashboard/attention`, `/v2/coach/me/dashboard-flag` | V2 (attention_items, users, drafts) | V2 flags | CURRENT |
| `overview` (V1 Home – hidden) | `/coach/dashboard`, `/coach/pending-approvals`, `/coach/analytics`, `/coach/equipment-mismatches` | V1 (`workout_assignments`, `workouts`) + `users` | — | **LEGACY** |
| `clients` (list) | `/coach/clients`, `/coach/preview/sandbox-info`, `/admin/clients/{id}/archive|restore|soft-delete` | `users`, `rosters`, `programmes_v2` | admin flags | CURRENT |
| `calendar` | `/coach/calendar?days=N` | Mixed: reads `workout_assignments` OR `workout_implementations` depending on client `kind` | — | **MIXED** |
| `approvals` | `/coach/pending-approvals` | Union: V1 workouts pending + V2 draft change-sets | — | **MIXED** |
| `library` | `/coach/exercises` + `/coach/exercises/{name}` | `exercises_v2` | `exercises_v2` | CURRENT |
| `library-legacy` (hidden) | Same collection but read via legacy filters | `exercises_v2` | — | LEGACY UX layer only |
| `videos` | `/coach/videos*` | `videos` | `videos` | CURRENT |
| `messages` | `/coach/messages/drafts*`, `/messages/*` | `messages`, `message_drafts` | same | CURRENT |
| `analytics` | `/coach/analytics?days=N` | V1 `workout_assignments` for adherence + `check_ins` | — | **MIXED** — V2 clients read no adherence |
| `changelog` | `/coach/change-log` | `decision_records` + admin audit | — | CURRENT |
| `checkins` (global) | `/coach/checkins` | `check_ins` | `check_ins` | CURRENT |
| `client/[id]` (LEGACY workspace) | 12+ endpoints incl. `/coach/clients/{id}/programme{,-overview,-timeline,/history,/regenerate,/approve,/regenerate-preview,/regenerate-apply}`, `/admin/*`, `/coach/clients/{id}/controls`, `/coach/clients/{id}/reset-password` | **V1** `workout_assignments`, `workouts`, `programmes` **+** V2 controls (flags, `live_state`) | V1 programmes, V1 workouts, users | **MIXED** — safe admin actions here (reset password, archive) BUT dangerous V1 generators also here |
| `client/[id]/workspace` (canonical) | `/v2/coach/clients/{id}/workspace/{month}`, `/v2/coach/clients/{id}/workspace/months`, `/v2/coach/clients/{id}/engine-v2/*`, `/v2/coach/clients/{id}/plan/*`, `/v2/coach/clients/{id}/directives`, `/v2/coach/clients/{id}/decisions`, `/v2/coach/clients/{id}/flight-support` | **V2 only** — `plan_drafts_v2`, `plan_live_v2`, `plan_live_v2_implementations`, `workout_implementations`, `schedule_days`, `flight_support_activity`, `objective_exposures` | V2 only | CURRENT |
| `client-months/[id]` | `/coach/clients/{id}/roster/months*` + `WorkoutQuickActions` | Roster reads + **V1 `/coach/workouts/{wid}/regenerate|approve|lock`** | V1 workouts | **MIXED — P0** |
| `draft/[id]` (legacy) | `/coach/drafts/{id}` | V1 draft schema | — | LEGACY |
| `workout/edit/[wid]` | `/coach/workouts/{wid}` (PATCH), `/coach/workouts/{wid}/exercises/*` | V1 `workouts` | V1 `workouts` | **MIXED** — called by `InlineWorkoutEditor` for V1 clients only |
| `exercise-content.tsx` | `/exercise-content/*`, `/exercise-content/{id}/generate-image`, `/exercise-content/{id}/image-prompt` | `exercises_v2`, `exercise_content_images`, `media_queue` | same | CURRENT |
| `brand-images` | `/brand-images/*` | `brand_images` (own domain) | same | ADMIN |
| `hotels` | `/coach/hotels/review-queue`, `/hotels/{id}`, `/coach/hotels/{id}/verify` | `hotels`, `hotel_verifications` | same | **LEGACY for training** — kept for nutrition-travel / layover-naming consumers |
| `nutrition` | `/coach/nutrition/*` | `nutrition_*` | same | CURRENT |

## Silent-fallback risks (V1 masquerading as V2)

1. **`/(coach)/calendar`** — the endpoint `/coach/calendar` reads different collections per client-`kind`. A V2 client with an incomplete V2 plan may fall through to `workout_assignments`, producing stale data that looks canonical.
2. **`/(coach)/analytics`** — same `/coach/analytics` endpoint. V2 clients whose `workout_implementations` completion isn't wired into the adherence calculation will show `0%` or `—`.
3. **`/(coach)/approvals`** — `/coach/pending-approvals` returns both V1 workout approvals and V2 draft change-sets in a single list; visually indistinguishable.
4. **`/coach/client/[id]` ADMIN entry** — clicking ADMIN from the V2 workspace opens the LEGACY page which shows a V1 "Regenerate Programme" button next to the "Reset Password" button (see Legacy Inventory, item L1).

## V2-only collections (safe touch)

- `plan_drafts_v2` · `plan_live_v2` · `plan_live_v2_implementations` · `workout_implementations` · `schedule_days` · `objective_exposures` · `programme_versions` · `roster_facets` · `programme_phases` · `progression_states` · `performance_records`

## V1-only collections (do not touch; used by hidden pages)

- `workout_assignments` · `workouts` · `workouts_archive` · `programmes` (V1 programme container)

## Shared collections (both eras use)

- `users` · `rosters` · `roster_versions` · `flight_support_activity` · `flight_support_overrides` · `directives` · `check_ins` · `coach_notes` · `decision_records` · `personal_activities` · `messages` · `notifications` · `exercises_v2` · `exercise_content_images` · `media_queue` · `videos`
