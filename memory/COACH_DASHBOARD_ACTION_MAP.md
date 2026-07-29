# Coach Dashboard — Action Map

Every coach-facing action / button and what it does. Read-only.

## Notation

- **Engine**: `V1` (legacy generator), `V2` (Engine V2), `SHARED` (no engine involvement), `ADMIN`.
- **Risk**: P0 (can trigger legacy generation on a V2 client), P1 (workflow duplication), P2 (UX clutter), P3 (cosmetic).

## Home (`v2-home.tsx`)

| Action | Where | Handler | Backend | Engine | Class | Risk |
|---|---|---|---|---|---|---|
| Enable | onboarding card | `enableV2` | `PATCH /v2/coach/me/dashboard-flag` | V2 | KEEP | — |
| View clients → | header chip | route `/clients` | — | SHARED | KEEP | — |
| Review (per attention card) | attention list | route `/coach/client/{id}/workspace` | — | V2 | KEEP | — |

Home no longer has: add client, delete client, filter chips, client table (all removed iter 128c).

## Clients (`clients.tsx`)

| Action | Handler | Backend | Engine | Class | Risk |
|---|---|---|---|---|---|
| Card click | route `/coach/client/{id}/workspace` | — | V2 | KEEP | — |
| Preview | opens preview sandbox | `/coach/preview/sandbox-info` | SHARED | KEEP | — |
| Review → | route `/coach/client/{id}/workspace` | — | V2 | KEEP | — |
| Add client | `AddClientSheet` | `POST /admin/clients` | SHARED | KEEP | — |
| Archive | `archiveClient` | `POST /admin/clients/{id}/archive` | SHARED | KEEP | — |
| Restore | `restoreClient` | `POST /admin/clients/{id}/restore` | SHARED | KEEP | — |
| Soft delete (trash) | `softDeleteClient` | `POST /admin/clients/{id}/soft-delete` | SHARED | KEEP | P2: trash beside everyday actions |
| Filter chips | client-side | — | — | KEEP | — |

## Canonical client workspace (`client/[id]/workspace.tsx`)

| Action | Handler | Backend | Engine | Class | Risk |
|---|---|---|---|---|---|
| Back | `router.back()` | — | — | KEEP | — |
| ADMIN | route `/coach/client/{id}` | — | — | KEEP | **P1** — this links to the legacy V1 page which contains DANGEROUS V1 buttons (see below) |
| Month prev/next | `stepMonth` | reload | V2 | KEEP | — |
| Build plan | `kickoffBuild` | `POST /v2/coach/clients/{id}/engine-v2/kickoff` | V2 | KEEP | — |
| Publish changes | opens `PublishPanel` | `POST /v2/coach/clients/{id}/engine-v2/publish` | V2 | KEEP | — |
| Approve N Ready | `approveReady` | `POST /v2/coach/clients/{id}/plan/approve-ready` | V2 | KEEP | — |
| Add directive | opens `DirectiveEditor` | `POST /v2/coach/clients/{id}/directives` | V2 | KEEP | — |
| Rebuild draft | in `EngineV2DraftPanel` | `POST /v2/coach/clients/{id}/engine-v2/kickoff` | V2 | KEEP | — |
| Compare Live | in `EngineV2DraftPanel` | `GET /v2/coach/clients/{id}/engine-v2/compare` | V2 | KEEP | — |
| Cannot publish (grey button) | disabled state | — | V2 | KEEP | — |
| Command Bar | inline | `POST /v2/coach/clients/{id}/command-bar/parse|apply` | V2 | KEEP | — |
| Roster upload button | `CoachRosterUploadButton` | `POST /coach/roster/upload` | SHARED | KEEP | — |
| Move assignment | drag/drop | `POST /v2/coach/clients/{id}/plan/assignments/{aid}/move` | V2 | KEEP | — |
| Flight Support override | drawer | `POST /v2/coach/clients/{id}/flight-support/override` | V2 | KEEP | — |
| Flight Support toggle | drawer | `POST /v2/coach/clients/{id}/flight-support/toggle` | V2 | KEEP | — |
| Resolve exception | `POST /v2/coach/clients/{id}/engine-v2/exceptions/{eid}/resolve` | V2 | KEEP | — |
| Tabs: Plan · Check-ins · Messages · Progress · History · Goals | in-page | V2 endpoints | V2 | KEEP | — |

## Legacy client profile (`client/[id].tsx`) — reached via ADMIN button

### KEEP (safe admin actions)

| Line | Action | testID | Backend | Class |
|---|---|---|---|---|
| 322 | Reset password | `admin-reset-password` | `POST /coach/clients/{id}/reset-password` | KEEP |
| 245–268 | Archive (with pause option) | `admin-archive-btn` | `POST /admin/clients/{id}/archive` | KEEP |
| 270 | Restore | `admin-restore-btn` | `POST /admin/clients/{id}/restore` | KEEP |
| 272–282 | Soft delete | `admin-soft-delete-btn` | `POST /admin/clients/{id}/soft-delete` | KEEP |
| 289–309 | Permanent delete (type DELETE) | `admin-perm-delete-btn` | `POST /admin/clients/{id}/permanent-delete` | KEEP |
| — | Coach picker / assign | `admin-change-coach-btn` | `POST /admin/clients/{id}/assign-coach` | KEEP |
| — | Coach controls (flexibility / progression / injury caution / video touchpoint) | `POST /coach/clients/{id}/controls` | KEEP |
| — | Add directive | `POST /coach/clients/{id}/directives` | KEEP |
| — | Nudge for setup | `POST /coach/clients/{id}/nudge-setup` | KEEP |
| — | Programme overview card (read-only) | `GET /coach/clients/{id}/programme-overview` | **MIGRATE** — should show V2 summary instead |

### P0 — MUST HIDE for V2 clients

| Line | Action | testID | Backend | Reason |
|---|---|---|---|---|
| 1074 | Regenerate programme | `programme-regenerate` | `POST /coach/clients/{id}/programme/regenerate` | Runs V1 generator |
| 1060 | Approve programme | `programme-approve` | `POST /coach/clients/{id}/programme/approve` | Bypasses V2 publish gates |
| — | Regenerate preview / apply | — | `POST /coach/clients/{id}/programme/regenerate-preview\|-apply` | Same generator |
| — | Programme card (V1 daily view) | `programme-card` | `GET /coach/clients/{id}/programme` | V1 workout list |
| — | Programme history | — | `GET /coach/clients/{id}/programme/history` | V1 programme container |

### P1 — Should route to V2 equivalent

| Action | Currently | Should |
|---|---|---|
| Client-months button | `router.push('/coach/client-months/{id}')` (V1) | Should link to workspace roster grid |
| Draft button | `router.push('/coach/draft/{id}')` (legacy) | Should open Engine V2 draft panel |
| Script button | `router.push('/coach/scripts/{id}')` | Keep (independent domain) |

## Calendar (`/calendar`)

| Action | Handler | Backend | Engine | Risk |
|---|---|---|---|---|
| Days selector (7/14/30) | `setDays` | `GET /coach/calendar?days=N` | MIXED | **P1** — endpoint returns V1 workouts for V1 clients + V2 assignments for V2 clients but they share the same visual pill; a mixed roster looks inconsistent |
| Client name click | route `/coach/client/{id}/workspace` | — | V2 | KEEP |
| Workout pill click | opens `/coach/workout/edit/{wid}` | V1 | **P1** — for V2 clients this opens a V1 editor |

## Approvals (`/approvals`)

| Action | Handler | Backend | Engine | Risk |
|---|---|---|---|---|
| List load | `setItems` | `GET /coach/pending-approvals` | MIXED | **P1** — V1 workout-approvals and V2 draft change-sets share this list |
| Item click | (varies) | possibly `POST /coach/workouts/{wid}/approve` | V1 | **P0 for V2 clients** — approving a V1 workout on a V2 client mutates V1 collections that V2 doesn't read |

## Analytics (`/analytics`)

| Action | Backend | Engine | Risk |
|---|---|---|---|
| Days selector | `GET /coach/analytics?days=N` | MIXED | **P1** — V2 completion tracked in `workout_implementations`, not `workout_assignments`. V2 clients often show 0% adherence. |

## Change Log

| Action | Backend | Engine | Risk |
|---|---|---|---|
| List | `GET /coach/change-log` | SHARED (`decision_records`) | KEEP |

## Global check-ins (`/checkins`)

| Action | Backend | Engine | Risk |
|---|---|---|---|
| List load | `GET /coach/checkins` | SHARED | KEEP |
| Click | `/coach/checkin/{id}` | SHARED | KEEP |

## Messages

| Action | Backend | Engine | Risk |
|---|---|---|---|
| Load drafts | `GET /coach/messages/drafts` | SHARED | KEEP |
| Send | `POST /coach/messages/drafts/{did}/send` | SHARED | KEEP |
| AI redraft | `POST /coach/messages/{did}/regenerate` | SHARED (LLM) | KEEP |

## Library / Videos / Exercises

- All CURRENT. Actions write to `exercises_v2`, `videos`, `exercise_content_images`, `media_queue`.
- **`library-legacy` page** is hidden from nav but self-labelled and reachable via URL. Recommend HIDE completely.

## Global P0 action inventory

1. `WorkoutQuickActions.regenerate` (line 101) — visible on `CoachLiveFeed` (hidden) and `client-months/[id]` (still linked from ADMIN button).
2. `[id].tsx` "programme-regenerate" (line 1074) — visible on the ADMIN page one click from workspace.
3. `[id].tsx` "programme-approve" (line 1060) — same page.
4. `/coach/pending-approvals` items — approving a V1 workout on a V2 client.
