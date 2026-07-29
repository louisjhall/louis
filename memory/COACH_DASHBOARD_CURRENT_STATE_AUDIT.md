# Coach Dashboard — Current-State Audit

Read-only. Snapshot of the coach product as it stands at end of iter 128c.

## Executive facts

- **Coach screens/routes audited**: 33 (11 sidebar-visible + 22 URL-reachable)
- **Client-visible V1/V2 labels**: **0** as of iter 128c (was 6+ before)
- **Legacy pages still reachable via URL**: 7
- **Legacy backend endpoints still hit from the frontend**: 12
- **Silent-fallback risks** (V1 masquerading as V2): 3 endpoints

## §2 — Home audit

### V2 Home (`v2-home.tsx`) — the current default

Post iter 128c, contains:

| Widget | Data source | Retention |
|---|---|---|
| Header title "Coach Home" + subtitle | static | KEEP |
| "View clients →" chip | route action | KEEP |
| Summary strip: Active clients / Need attention / Programmes ready / Roster changes / Check-in concerns | `/v2/coach/dashboard/summary` | KEEP |
| Attention queue (grouped by client) with Review button | `/v2/coach/dashboard/attention` | KEEP |
| Onboarding card ("Enable") when `coach_dashboard_v2_enabled=false` | flag | KEEP (safety) |
| ~~Client table~~ | — | REMOVED iter 128c |
| ~~Add client button~~ | — | REMOVED iter 128c |
| ~~Filter chips~~ | — | REMOVED iter 128c |
| ~~Trash/delete inline~~ | — | REMOVED iter 128c |
| ~~"Switch to V1" chip~~ | — | REMOVED iter 128c |

### V1 Overview (`overview.tsx`) — hidden from sidebar

Still-present widgets:

| Widget | Data source | Retention |
|---|---|---|
| ToDo feed (`CoachToDoFeed`) | `/coach/tasks` | HIDE (superseded by attention queue) |
| Live feed (`CoachLiveFeed`) | V1 workout activity | HIDE (V1 only) |
| Pending approvals card (`CoachApprovalQueueCard`) | `/coach/pending-approvals` | MERGE into `/approvals` |
| Exercise media summary (`ExerciseMediaSummary`) | `/coach/exercise-media-summary` | MOVE to `/library` |
| Notification bell | notifications feed | MOVE to top-of-sidebar / header |
| Preview launcher | preview sandbox | MOVE to `/clients` (already exists there) |
| Client dashboard summary (`data.clients`, `.counts`) | `/coach/dashboard` (V1) | HIDE |
| Analytics summary (30-day) | `/coach/analytics` | REMAIN in `/analytics` only |
| Equipment mismatch banner | `/coach/equipment-mismatches` | KEEP but move to `/library` or `/analytics` |

**Recommendation**: `/(coach)/overview` should redirect to `/(coach)/v2-home` after two future iterations of monitoring — no reason to keep two Home concepts.

## §3 — Client-list audit

Only place with a canonical client list: **`/(coach)/clients`**.

Rich card fields verified from source:
- Avatar / initial + client name
- Role · Airline (e.g. "Pilot · Etihad")
- Base airport · Environment mix (e.g. "AUH · MIXED")
- Roster progress bar (30-day)
- Roster window date range
- Preview / archive / delete buttons + REVIEW → chevron
- Status chips: Expired / Expiring / Needs Confirm / Profile Gap / Red Days / Missed
- 4 KPI tiles at the top: Active / Expiring / Expired / No Roster
- 10 filter chips: ALL · NEEDS REVIEW · PROFILE GAP · EXPIRING · EXPIRED · NO ROSTER · NEEDS CONFIRM · PENDING · RED DAYS · MISSED

**Post iter 128c, no other coach screen shows a client list. Duplication removed.**

## §4 — Client workspace audit

Two workspaces exist. Both readable, only one canonical.

### CURRENT — `client/[id]/workspace.tsx` (`Roster + Plan`)

Tabs verified from source: `plan` (default), `checkins`, `messages`, `progress`, `history`, `goals`.

Header: back arrow, client name, programme meta (`v{N} live · draft available`), **ADMIN button (added iter 128c)**.

Ribbon: month selector, count pills (Ready / Review / Conflict / Approved / Live / Locked), Approve N Ready, Add directive, Build plan OR Publish changes, Roster upload.

Plan tab contains: Programme Draft panel (`EngineV2DraftPanel`), pipeline status, command bar, day-by-day roster + plan grid with inline Flight Support cards.

**All V2. All safe.**

### LEGACY — `client/[id].tsx` (V1 profile)

Owns:
- ADMIN block (Reset password / Archive / Delete / Permanent delete / Coach assignment / Coach controls)
- V1 programme card + regenerate/approve controls **← danger**
- Programme overview + timeline reads
- Live signals card
- Directives editor
- Client-months button
- Draft button
- Script button
- Nudge-for-setup
- Preview-as-client
- Change log

**Recommendation**: Split into:
1. **Client Admin drawer/modal** attached to the workspace ADMIN button — Reset password / Archive / Delete / Coach assignment / Coach controls / Preview / Change log. That's it.
2. Move Directives + Live signals into the workspace.
3. DELETE the V1 programme card / regenerate buttons entirely — leave the file in place but return an empty section for V2 clients.

## §5 — Plan/roster workflow audit

Canonical V2 actions (all safe, all V2):

- Upload Roster → `POST /coach/roster/upload`
- Build Plan → `POST /v2/coach/clients/{id}/engine-v2/kickoff`
- Compare Draft vs Live → `GET /v2/coach/clients/{id}/engine-v2/compare`
- Add Directive → `POST /v2/coach/clients/{id}/directives`
- Approve N Ready → `POST /v2/coach/clients/{id}/plan/approve-ready`
- Publish → `POST /v2/coach/clients/{id}/engine-v2/publish` (or `/plan/publish`)
- Resolve Exception → `POST /v2/coach/clients/{id}/engine-v2/exceptions/{eid}/resolve`
- Move workout → `POST /v2/coach/clients/{id}/plan/assignments/{aid}/move`
- Edit workout (V2) → `PATCH /v2/coach/clients/{id}/plan/implementations/{iid}`
- Change equipment / setup → Universal Travel → `PATCH plan_live_v2_implementations`
- Flight Support override → `POST /v2/coach/clients/{id}/flight-support/override`

Legacy actions still callable (all P0/P1 – see Action Map for handler locations):

- `POST /coach/clients/{id}/programme/regenerate`
- `POST /coach/clients/{id}/programme/approve`
- `POST /coach/clients/{id}/programme/regenerate-preview|-apply`
- `POST /coach/workouts/{wid}/regenerate|approve|lock|move`
- `PATCH /coach/workouts/{wid}` and its `/exercises/*` subroutes

## §6 — Programme data-source audit

Cross-reference: see `COACH_DASHBOARD_DATA_SOURCE_MAP.md`.

Summary:
- **V2 clients** (post-migration): every canonical read path uses `plan_live_v2_implementations` + `workout_implementations`.
- **V1 clients** (pre-migration): reads `workout_assignments` + `workouts`.
- **Mixed screens** (`calendar`, `analytics`, `approvals`, `overview`, `client-months`) fall back to V1 for any client with `kind: "v1"` and to V2 for `kind: "v2"`. The visual is identical → **P1 confusion**.

## §7 — Draft/Live audit

Only ONE canonical Draft/Live flow exists:

- Draft: `plan_drafts_v2` → shown in `EngineV2DraftPanel` (canonical workspace, Plan tab)
- Live: `plan_live_v2` + `plan_live_v2_implementations` → shown in the ribbon (`v{N} live`)
- Publish gate: `POST /v2/coach/clients/{id}/engine-v2/publish` (never bypassed by V2 UI)

Duplicate pathways still callable (but not linked from V2):
- `/coach/draft/[id]` — legacy draft editor
- `POST /coach/clients/{id}/programme/approve` — legacy approve, bypasses publish
- `POST /coach/clients/{id}/programme/regenerate-apply` — legacy apply

## §8 — Approvals audit

`/approvals` currently unions:
1. V1 workout approvals (`workout_assignments` needing coach sign-off)
2. V2 draft change-sets (`plan_drafts_v2` needing publish)

Recommendation:
- Split the endpoint (`/coach/pending-approvals` should route per-client-kind).
- Or filter client-side to `kind: v2` and rely on Home attention queue for V2 draft signalling (which already surfaces there).

## §9 — Status vocabulary audit

Currently in circulation:

| Status | Screen(s) | Source | Meaning |
|---|---|---|---|
| Ready | Home summary, count-pill, client card | V2 draft `ready` count | V2 assignment prepared, unapproved |
| Review | Count-pill | V2 draft `review` count | Needs coach review |
| Conflict | Count-pill | V2 exceptions | Blocking exception |
| Approved | Count-pill | V2 assignments approved | Ready to publish |
| Live | Count-pill, workspace ribbon | `plan_live_v2` | Published |
| Locked | Count-pill | V2 assignments locked | Prevents auto-recompute |
| Roster changed | V1 client-list chip | `rosters_versions` diff | New roster uploaded |
| Needs Review | V1 chip | mixed | Legacy programme needs approval |
| Programme Ready | V1 chip | V1 programme | V1 generator finished |
| No Roster | Clients KPI | `rosters` collection empty | No roster uploaded |
| Profile Gap | Client card banner | user.profile completeness | Missing required fields |
| Expired | Clients KPI + card | roster window past | Roster ended |
| Expiring | Clients KPI + card | roster window ending in ≤7d | — |
| Pending | Clients filter | mixed | Unclear origin |
| Red Days | Clients filter | flight_support/attention feed | Multiple attention items on same day |
| Missed | Clients filter | V1 completions | Legacy metric |
| Needs Attention | attention queue | V2 attention items | Aggregate |

**Proposed canonical set (do not implement yet)**:

- **Needs Attention** (aggregate)
- **Draft Ready** (V2 ready to review)
- **Live** (V2 published)
- **Roster Required** (no roster)
- **Profile Incomplete** (profile gap)
- **Missed** (deprecated — only for V1 clients until migration complete)
- **No Action** (quiet)

Retire from coach UI: "Ready", "Review", "Conflict", "Approved", "Locked" (keep them as *internal* counts inside the workspace count pills, but never surface them on the client list where a single word conveys client health).

## §10 — Pipeline status audit

Pipeline shown in workspace (per screenshot):
`Roster uploaded → Roster parsed → Schedule created → Planning programme → Generating workouts → Validating → Ready for review → Published`

Wiring:
- Stages 1–3 update reliably from Roster upload + parser.
- Stages 4–7 update from Engine V2 kickoff (`/engine-v2/kickoff`).
- Stage 8 updates from publish.

Recommendation:
- **Keep** during Draft phase.
- **Collapse to a single "Live vN" badge** once Published, so it doesn't dominate the workspace.

## §11 — Legacy generation entry points

See `COACH_DASHBOARD_LEGACY_INVENTORY.md` §A + §B. Four P0 buttons still callable.

## §12 — Legacy client reads

Screens still reading V1 (mixed with V2 for same client if both exist):
- `overview.tsx` (hidden but URL-reachable)
- `calendar.tsx` (endpoint mixed)
- `analytics.tsx` (endpoint mixed)
- `client-months/[id].tsx`
- `[id].tsx` programme card + timeline + regenerate/approve

## §13 — Client preview audit

Two mechanisms:
1. **`PreviewLauncher`** on `/overview` — launches a browser "preview as client" flow (opens client's home in the current session).
2. **Preview button on `/clients` card** — same mechanism, canonical.
3. **Preview Sandbox** on `/clients` — separate sandbox client (`sandbox_client_id`) for coach testing, isolated from real clients.

Recommendation: keep sandbox and per-client Preview on `/clients` only. Kill `PreviewLauncher` on `/overview` when that page is fully retired.

## §14 — Review button audit

Trace:
- `/(coach)/clients` card `REVIEW →` → `router.push('/coach/client/{id}/workspace')` (iter 128c change)
- `/(coach)/v2-home` attention card `Review` → same target

Both open the canonical workspace on the Plan tab. Correct.

## §15 — Destructive actions

| Action | Location | Confirmation? | Recommendation |
|---|---|---|---|
| Trash on `/clients` row | inline icon | requires typing email | KEEP but move to card menu (currently beside PREVIEW which is safe) |
| Archive | `/clients` menu or `[id].tsx` | 2-step (Archive vs Archive+Pause) | KEEP |
| Soft delete | `[id].tsx` | 1-step | ADD 2-step confirmation |
| Permanent delete | `[id].tsx` | Requires typing DELETE | KEEP |
| Reset password | `[id].tsx` (via ADMIN) | typed prompt + confirm | KEEP |
| ~~Delete client on Home~~ | — | — | REMOVED iter 128c |

## §16 — Calendar audit

Genuine cross-client value:
- Weekly view of who has what tomorrow (roster + planned session)
- Spotting equipment mismatches by day
- Quickly moving assignments between days across clients

Duplicates workspace month grid only for **single-client** view. Recommendation: keep, but move to V2 data source only.

## §17 — Check-ins audit

Two locations:
- Global `/(coach)/checkins` — reads all check-ins across clients
- Workspace `checkins` tab — reads that client's check-ins

Different scopes, no duplication. Both current. **KEEP BOTH.**

## §18 — Messages audit

Two locations:
- Global `/(coach)/messages` — coach inbox / drafts / send
- Workspace `messages` tab — that client's thread

Different scopes, no duplication. Both current. **KEEP BOTH.**

## §19 — Progress / Analytics audit

- Global `/analytics` — 30-day summary across all clients (**MIXED** — see §12)
- Workspace `progress` tab — that client's progress
- Workspace `history` tab — decision + change history

Programme adherence in `/analytics` is currently V1-based for legacy clients and empty for pure V2 clients. Needs a unified adherence calculator. Flight Support adherence is separate and not yet in either surface (backlog item from earlier iters).

## §20 — Goals / Profile audit

Currently two editors:
- Workspace `goals` tab — V2 goals (`/v2/coach/clients/{id}/goals`)
- `[id].tsx` client controls — V1 flexibility / injury caution / video touchpoint / progression speed

Recommendation: **CONSOLIDATE INTO ONE goals+controls editor** on the workspace `goals` tab. Move the V1 client controls block from `[id].tsx` into it.

## §21 — Equipment / Change setup audit

Current V2 flow is Universal Travel via `plan_live_v2_implementations`. Old buttons still visible on:
- `[id].tsx` "Change equipment" (partial; may not be wired)
- `client-months/[id]` (if inline)

Recommendation: audit these two spots specifically before removing; per-client-kind dispatch is required.

## §22 — Hotel legacy audit

- `/coach/hotels` — hotel review queue (verify equipment)
- `hotel-lookup` — used by nutrition travel + layover naming (still active)

Product principle: **NO hotel DB required for training**. Recommendation:
- Do NOT delete hotels collection or verify UI (still used by nutrition-travel + layover-naming).
- HIDE the `/coach/hotels` link from any coach sidebar it might still appear in (verify — not in current sidebar).
- Explicitly NOT part of Home/Clients/Workspace training flow.

## §23 — Aviation Support audit

Authoritative screen: workspace Plan tab → inline Flight Support rows per day → drawer via day tap.

No duplication found. **KEEP.**

## §24 — Library audit

- `/(coach)/library` — unified V2 library, reads `exercises_v2`.
- `/(coach)/library-legacy` — hidden from nav, self-labelled "LEGACY · V1", reads same collection with legacy filter.
- Engine V2 draft construction reads from `exercises_v2` via the same library.

**Recommendation**: `library-legacy` can be marked hidden immediately (already hidden). Retire in a later iteration.

## §25 — Videos audit

Single canonical `/(coach)/videos`. Backed by `videos` collection. Used by workout implementations + Flight Support cues. **KEEP.**

## §26 — Change Log / History audit

Global `/changelog` — reads `decision_records` + admin audit. Client-scoped history lives in the workspace `history` tab, reads `/v2/coach/clients/{id}/decisions`. Different scopes, no duplication. **KEEP BOTH.**

## §27 — Admin audit

- `/coach/admin/coaches` — coaches directory (sidebar item "Coaches (Admin)")
- `/coach/admin/live-controls` — feature flag controls (not in sidebar)
- Client admin actions live in `[id].tsx` reached via workspace ADMIN button

Recommendation: keep sidebar item; put a small "System" tab inside for `live-controls`.

## §28 — Dead-button audit

Sweep found:
- `WorkoutQuickActions.regenerate` — still bound, still callable — P0
- `[id].tsx` `programme-regenerate` / `programme-approve` — still bound — P0
- `PreviewLauncher` on `/overview` — bound but page is hidden
- "Back to V1 Overview" — removed iter 128c
- "Switch to V1" chip — removed iter 128c

## §29 — Feature-flag audit

See Legacy Inventory §D. Three flags in circulation, all currently required.

## §30 — Route map

See `COACH_DASHBOARD_ROUTE_MAP.md`.

## §31 — API map

See `COACH_DASHBOARD_DATA_SOURCE_MAP.md`.
