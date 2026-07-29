# Coach Dashboard — Route Map

Read-only audit. `AUDIT — do not delete / do not migrate yet`.

## Sidebar-visible routes (as of iter 128c)

| # | Route | Screen file | Purpose | Data source(s) | Class | Final destination |
|---|---|---|---|---|---|---|
| 1 | `/(coach)/v2-home` | `v2-home.tsx` | Operations dashboard (attention queue + summary) | `/v2/coach/dashboard/summary`, `/v2/coach/dashboard/attention`, `/v2/coach/me/dashboard-flag` | **CURRENT** | HOME (canonical) |
| 2 | `/(coach)/clients` | `clients.tsx` | Client directory (rich cards, filters, Preview/Review, Add client, Archive/Delete) | `/coach/clients`, `/admin/clients/{id}/archive|restore|soft-delete`, `/coach/preview/sandbox-info` | **CURRENT** | CLIENTS (canonical) |
| 3 | `/(coach)/calendar` | `calendar.tsx` | Cross-client 7/14-day schedule view | `/coach/calendar?days=N` | **MIXED** (still reads V1 workout view for some clients) | CALENDAR (keep, need V2 source) |
| 4 | `/(coach)/approvals` | `approvals.tsx` | Pending review items | `/coach/pending-approvals` | **MIXED** | APPROVALS (needs V2 rewiring) |
| 5 | `/(coach)/library` | `library.tsx` | Unified Exercise Library (V2) | `/coach/exercises` | CURRENT | LIBRARY |
| 6 | `/(coach)/videos` | `videos.tsx` | Coach-facing video assets | `/coach/videos*` | CURRENT | VIDEOS |
| 7 | `/(coach)/messages` | `messages.tsx` | Global inbox | `/coach/messages/drafts*` | CURRENT | MESSAGES |
| 8 | `/(coach)/analytics` | `analytics.tsx` | 30-day adherence + trends | `/coach/analytics` | MIXED (reads legacy `workout_assignments`-based metrics) | ANALYTICS (needs V2 metrics fallback) |
| 9 | `/(coach)/changelog` | `changelog.tsx` | Global change log | `/coach/change-log` | CURRENT | CHANGE LOG |
| 10 | `/coach/admin/coaches` | `coaches.tsx` | Admin: coaches list | `/admin/coaches*` | CURRENT | ADMIN |
| 11 | `/(coach)/profile` | `profile.tsx` | Louis's own profile | `/coach-profile` | CURRENT | ADMIN (or user menu) |

## Sidebar-hidden but reachable via URL

| Route | Screen file | Purpose | Class | Notes |
|---|---|---|---|---|
| `/(coach)/overview` | `overview.tsx` | **V1 Overview** (old Home) | LEGACY | Fallback after iter 128b nav consolidation. Contains CoachToDoFeed + CoachLiveFeed + CoachApprovalQueueCard + ExerciseMediaSummary; reads `/coach/dashboard`, `/coach/pending-approvals`, `/coach/analytics`, `/coach/equipment-mismatches`. **Hidden from sidebar; still reachable at `/(coach)/overview`.** |
| `/(coach)/library-legacy` | `library-legacy.tsx` | V1 exercise library | LEGACY | Displays "LEGACY · V1" banner. Hidden from sidebar. |
| `/(coach)/checkins` | `checkins.tsx` | Global check-in inbox | CURRENT | Reads `/coach/checkins`. Not in sidebar but linked from workspace. |
| `/(coach)/exercises` | `exercises.tsx` | Exercise editor (v2) | CURRENT | Deep-linked from library. |
| `/(coach)/engine-v2-draft/[cid]` | `engine-v2-draft/[cid].tsx` | Draft detail view | CURRENT | Deep-link from workspace. |
| `/coach/client/[id]` | `client/[id].tsx` | **Legacy client profile** (V1) | LEGACY | 2,084 lines. Owns Admin actions (Archive/Delete/**Reset Password**/Coach-assignment). Also owns V1 programme controls (regenerate, approve, regenerate-preview, regenerate-apply). Reachable via new ADMIN button in workspace header. |
| `/coach/client/[id]/workspace` | `client/[id]/workspace.tsx` | **Canonical client workspace** (V2) | CURRENT | Tabs: Plan · Check-ins · Messages · Progress · History · Goals. Reads `/v2/coach/clients/{id}/workspace/{month}`. |
| `/coach/client-months/[id]` | `client-months/[id].tsx` | Roster months view | MIXED | Uses `WorkoutQuickActions` which still calls `/coach/workouts/{wid}/regenerate` (V1). |
| `/coach/draft/[id]` | `draft/[id].tsx` | Old draft editor | LEGACY | Not linked from any current V2 flow. Confirmed by grep. |
| `/coach/workout/edit/[wid]` | `workout/edit/[wid].tsx` | Workout deep-edit | MIXED | Called by V2 `InlineWorkoutEditor` but writes to `db.workouts`. |
| `/coach/scripts/[id]` | `scripts/[id].tsx` | Coach script/teleprompter | CURRENT | Deep-link from workspace. |
| `/coach/teleprompter/[id]` | `teleprompter/[id].tsx` | Reader UI for scripts | CURRENT | |
| `/coach/exercise-content.tsx` | | Exercise media editor (PILOT persona lives here) | CURRENT | |
| `/coach/brand-images` | `brand-images.tsx` | Brand asset editor | ADMIN | Uses `/brand-images/{id}/regenerate` (own generator, not programme). |
| `/coach/checkin/[id]` | `checkin/[id].tsx` | Single check-in reviewer | CURRENT | |
| `/coach/habit-review/[id]` | `habit-review/[id].tsx` | Habit review | CURRENT | |
| `/coach/demand-queue` | `demand-queue.tsx` | Batch content generation queue | ADMIN | |
| `/coach/hotels` | `hotels.tsx` | **Hotel review queue** | LEGACY | Uses `/coach/hotels/review-queue`, `/hotels/{id}` PATCH, `/coach/hotels/{id}/verify`. See §22 – no longer required for training (roster → environment). Kept for hotel database consumers (nutrition-travel, layover naming). |
| `/coach/nutrition` | `nutrition.tsx` | Coach nutrition review | CURRENT | Reads `/coach/nutrition/*`. |
| `/coach/ui-issues` | `ui-issues.tsx` | UI bug reports | ADMIN | |
| `/coach/admin/live-controls` | `admin/live-controls.tsx` | Live-state flag controls | ADMIN | |

## Route summary counts

- **Sidebar-visible:** 11 (1 renamed, 1 hidden vs previous iter → clean)
- **URL-only reachable:** 22
- **CURRENT:** 20
- **LEGACY:** 5 (overview, library-legacy, draft/[id], hotels, client/[id]'s programme controls)
- **MIXED:** 6 (calendar, approvals, analytics, workout/edit, client-months, client/[id] admin block)
- **ADMIN-only:** 6

## Duplicate/overlapping routes (must eventually collapse)

| # | Route A | Route B | Overlap |
|---|---|---|---|
| 1 | `/(coach)/v2-home` | `/(coach)/overview` | Both are "Home" — V1 hidden but reachable |
| 2 | `/(coach)/library` | `/(coach)/library-legacy` | Same domain, V1 legacy |
| 3 | `/coach/client/[id]` | `/coach/client/[id]/workspace` | Two client workspaces; V1 (admin+programme+profile) vs V2 (Roster+Plan) |
| 4 | `/coach/draft/[id]` | `/coach/client/[id]/workspace` (Plan tab) | V1 draft editor vs V2 EngineV2DraftPanel |
| 5 | `/coach/client-months/[id]` | `/coach/client/[id]/workspace` (roster grid) | V1 roster month view vs V2 workspace grid |
