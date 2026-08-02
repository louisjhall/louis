# CrewFit — Technical Handover (Delta)

**Date:** 2026-06 · **Scope:** Delta-only handover (Option A) covering the 9
undocumented areas of the CrewFit codebase. This document supplements the
existing Joel / Pietro V2 Engine deep-dive specs and the V2 Engine phase
guides.

Everything here is derived from a **read-only** inspection of the current repo.
No plans were regenerated, no LLMs were called, no tests were run.

## Contents

1. Roster ingestion path
2. Exercise library / Media queue
3. Today's Reality surface
4. Notifications wiring
5. App data retrieval (client-side loaders)
6. API routes map (V2 coach + client + support)
7. DB schema — key relationships
8. Preview vs Production separation
9. Coach approval / publish flow
10. Appendix A — file → responsibility index
11. Appendix B — conflicting sources of truth (call-outs)

---

## 1. Roster ingestion path

There are **two entry points** and **one shared downstream pipeline**.

### 1.1 Client-side upload (source of truth for parsing)

- **UI:** `/app/frontend/app/roster-upload.tsx`
- **API:** `POST /api/roster/upload-and-generate` (in `server.py`)
  - Also: `POST /api/roster/extract` (parse only), `POST /api/roster/{rid}/confirm`,
    `GET /api/roster/current`, `GET /api/roster/history`.
- **Job model:** `db.roster_jobs` (progress polled via
  `GET /api/roster/jobs/{job_id}` and `GET /api/roster/jobs/active`).
- **Parser fallthrough** (`feature_roster_confirmation.py`):
  1. Try airline-specific parser (deterministic):
     - `parsers/emirates_detailed.py` → `parsers/emirates.py` (Emirates PDFs)
     - `parsers/etihad.py` (Etihad PDFs / images)
  2. If no airline match → send file to **Gemini** via `call_gemini_file`
     (`ROSTER_SYSTEM` prompt lives in `server.py`) and parse the returned
     JSON with `parse_json_from_text`.
- **Post-parse enrichment:**
  - `_apply_day_defaults()` — normalises day_type, flights, load, home/away.
  - `_align_days_to_weekday_labels()` (server.py) — corrects off-by-one dates
    when the vision model shifts by ±1 day.
  - Airline **label enrichment**:
    - `parsers/etihad_labels.py::decide_day` — writes `label`, `client_label`,
      `training_colour`, `blocked[]`, `equipment_assumption`,
      `recovery_risk`, `chain_flag`.
    - `parsers/emirates_labels.py::enrich_emirates_days` — parity for Emirates.
- **Confidence gate:** `_needs_review(day)` marks any day with
  `confidence < LOW_CONFIDENCE_THRESHOLD` or day_type "Unknown/Needs
  Confirmation" as review-required. Client cannot activate until all
  low-confidence days are reviewed.

### 1.2 Coach-side upload (bypass for the coach)

- **API:** `POST /api/coach/clients/{cid}/roster/upload-parse` and
  `POST /api/coach/clients/{cid}/roster/pending/{rid}/confirm`
  (`feature_coach_roster_upload.py`).
- **Difference vs client path:** the coach *is* the reviewer, so the
  low-confidence gate is bypassed. Everything else — parsing pipeline,
  activation, month generation — is **reused directly** from
  `feature_roster_confirmation.py`.
- Uploaded rosters are stamped `uploaded_by="coach"` so the roster-history
  drawer can badge them.

### 1.3 Downstream fan-out (V1 + V2)

On confirmation:

1. **V1 side:** `_generate_month()` (server.py) creates `db.workouts` rows for
   each day and (optionally) a `db.programmes` row.
2. **V2 side:** `feature_v2_p4_roster.py::_build_roster_facets()` **must** be
   invoked. It reads `db.rosters.days[]` and writes:
   - `db.schedule_days` — one row per date with `derived.duty_burden_score`,
     `derived.training_opportunity`, `derived.available_time_min`,
     `derived.recommended_intensity_ceiling`.
   - `db.roster_duties` — one row per duty with `sectors[]`.
   - `db.flight_sectors` — one row per flight leg.
3. `emit_roster_change_exceptions()` compares prior vs new `derived` fields
   and emits `ROSTER_CHANGED` exceptions where material state changed
   (these are what the V2 kickoff surfaces to the coach).

### 1.4 Overlap semantics

Only overlapping date ranges get superseded. Non-overlapping months (July
uploaded, then August uploaded) both remain `is_active=True`. This is what
prevents the "July disappeared" regression class.

### 1.5 Zombie recovery

On startup (`server.py::_startup`), any `roster_jobs` still in `processing`
are swept to `status=failed, stage="interrupted"` with an actionable retry
message. Same treatment for `image_jobs` / `content_jobs`.

---

## 2. Exercise library / Media queue

Two **overlapping** systems exist. Understand this before touching either.

### 2.1 New unified library — `exercises_v2` (`feature_exercise_content.py`)

- **Purpose:** Single source of truth for **everything** an exercise needs —
  cues, video, generated Nano Banana images, coaching notes, per-slot flags
  (warm-up, mobility, cardio, cooldown, hotel_circuit, layover_workout, etc.).
- **Endpoints (all `/api` prefixed):**
  - `POST /exercise-content` (admin create)
  - `GET  /exercise-content` (list + filters + text search)
  - `GET  /exercise-content/{id}` / `PATCH` / `DELETE` (soft archive)
  - `POST /exercise-content/{id}/approve` — one-click coach approvals
  - `POST /exercise-content/{id}/generate-image` — kicks the Nano Banana
    image generation job (start / end / primary variants). Model:
    `gemini-3.1-flash-image-preview`. Uses `EMERGENT_LLM_KEY`.
  - `GET  /exercise-content/images/{img_id}/stream` — HMAC-signed streaming
    of stored blobs from `EXERCISE_IMAGE_ROOT` (default
    `/app/backend/uploads/exercise_images`) via `storage.py`.
  - `GET  /exercise-content/{id}/log` — change log.
  - `POST /exercise-content/scan-todos` — nightly coach-task generator that
    finds library gaps.
- **Style prompts** (`EXERCISE_STYLE_MALE`, `EXERCISE_STYLE_FEMALE`) are
  hard-coded inside `feature_exercise_content.py` and include the CrewFit
  logo brief, red trainers rule, dark studio, black brick wall.

### 2.2 Legacy library — `db.exercises` + `db.exercise_videos` + `db.exercise_video_blobs`

- **Purpose:** Preceded `exercises_v2`. Still driven by the endpoints in
  `server.py`:
  - `GET/POST/DELETE /exercises`
  - `GET /exercises/previous` (per-client PR/last-set lookup)
  - `GET /exercises/alternatives` (swap suggestions)
  - `GET /exercises/video`, `POST /exercises/videos-batch`
  - Coach video CRUD: `POST /coach/videos/upsert`, `slot`, `approve`,
    `preferred`, `variant`, `rescan`, `upload`, `DELETE /coach/videos/slot`.

### 2.3 Reconciliation — the "todo" surface

- `feature_media_reconciliation.py` scans upcoming workouts for
  `_classify_missing()` gaps and emits `coach_tasks` of kind
  `exercise_media_review`.
- Endpoints:
  - `POST /admin/media/reconcile` — trigger a full pass (admin/coach).
  - `GET  /admin/media/todos` — open review tasks.
- Also runs opportunistically inside `GET /workouts/week` (best-effort,
  swallowed on failure — never blocks a client read).
- **Priority buckets** are days-until-workout: `urgent ≤1d`, `high ≤7d`,
  `medium ≤30d`, `low` otherwise.

### 2.4 Media queue (Flight Support)

- Collection: `db.media_queue`.
- Populated by `feature_flight_support_media.py` (persona-aware:
  louis / female / pilot) and consumed by `feature_v2_coach_home.py` when
  building the coach Action Queue.

### 2.5 Resolver bridge — how the client-facing workout row gets its media

`feature_v2_resolver.py` joins:
- `plan_live_v2.session_specs[eid]` (exercise names + slot templates)
- `exercises_v2` (library entry)
- `exercise_content_images` (Nano Banana output)
- fallback to legacy `db.exercise_videos` / `db.exercise_video_blobs`

into a single legacy-shaped `workout.exercises[]` row for the client.

**⚠ Conflicting source of truth** — see Appendix B item B1.

---

## 3. Today's Reality surface

There are **three distinct concepts** which are often conflated in
conversation. Do not treat them as one.

### 3.1 "Today" composite endpoint

- `GET /api/client/today` in `feature_aviation_support_api.py`.
- Aggregates for `date.today()`:
  - **Training:** first tries `synth_workouts_for_user()`
    (`feature_v2_client_bridge.py`) which reads `plan_live_v2`; falls back
    to `db.workouts` (V1).
  - **Roster context:** `_roster_days_between()` — direct read from
    `db.rosters`.
  - **Flight Support:** `get_flight_support_by_date()` — deterministic
    selector layered with per-user overrides
    (`db.flight_support_overrides`) and completions
    (`db.flight_support_activity`).
- Returns `labels.training_state` (`rest_day` / `session_planned`) and
  `labels.flight_support_state` (`present` / `disabled` / `none`).
- **Zero mutations.** Pure read-time composition.

### 3.2 Reality chip resolver (P10)

- `feature_v2_p10_reality.py`:
  - `POST /api/v2/client/reality/apply` (self)
  - `POST /api/v2/coach/clients/{client_id}/reality/apply` (coach on behalf)
- Deterministic map (`CHIP_MAP`) — no LLM — from a **chip intent**
  (`im_tired`, `sore_knee`, `short_on_time`, `hotel_room`, `no_energy`,
  `low_motivation`, `life_change`) to `{reduce_pct, convert_to_mobility,
  cue}`.
- Routes through `feature_v2_p7_equipment._adapt()` to actually mutate the
  `workout_assignments` row. Emits a `write_decision` audit + a
  `reality_chip_applied` metric.
- The **"other" free-text branch** is the *only* one that escalates to LLM
  (design constraint — keep reality chips cheap).

### 3.3 Legacy `/reality/*` endpoints (V1 surface)

- `POST /api/reality/submit`, `POST /api/reality/apply`,
  `GET /api/reality/history`, `GET /api/reality/{event_id}`,
  `GET /api/reality/kinds`, plus coach review:
  `GET /api/coach/reality/pending`, `POST /api/coach/reality/decision`.
- Collection: `db.reality_events`. Still active for V1 clients.

### 3.4 Readiness state (P10)

- `POST /api/v2/client/readiness` (+ coach twin).
- Deterministic classifier `_classify_readiness()` maps
  `sleep_score_avg`, `energy_score_avg`, `soreness_score_avg`, `pain_flags`,
  `missed_sessions_count` → band ∈
  `{normal, slight_reduce, recover_priority, coach_review}`.
- Also derives `avoid_movement_patterns` from pain flags
  (`_movement_avoidance_from_pain`) — knee → skip `deep_squat`, `lunge`,
  `gait_run_tempo`; shoulder → skip `overhead_press`, `vertical_pull`; etc.
- Persisted in `db.readiness_states`, consumed by
  `feature_v2_p6_construction.py` during workout construction.

---

## 4. Notifications wiring

Two co-existing surfaces:

### 4.1 In-app bell (fallback when push is off)

- `feature_notifications.py`:
  - `GET  /api/notifications`
  - `GET  /api/notifications/unread-count`
  - `POST /api/notifications/{id}/read`
  - `POST /api/notifications/read-all`
  - `GET  /api/notifications/settings`
  - `PUT  /api/notifications/settings`
  - `POST /api/notifications/permission`
- Collection: `db.notifications`. **Every enqueue also writes an in-app
  notification row** so nothing gets lost when push is disabled.
- Dedupe key: `(user_id, notif_type, related_id, dedupe_key)`.
- Category routing: `NOTIF_CATEGORY` map (e.g.
  `flight_support_pre_flight → flight_support`).

### 4.2 Push (Firebase via Emergent Push proxy)

- `send_push(recipients, data, idempotency_key)` in `server.py` (line 4472).
- Posts to `EMERGENT_PUSH_KEY`-authenticated proxy at `PUSH_BASE_URL` +
  `/api/v1/push/trigger`. Non-blocking — failures are logged, not raised.
- `EMERGENT_PUSH_KEY` is `placeholder` in dev; **replaced at deploy time**
  by the Emergent build pipeline. Never edit that env var by hand.
- Token registration endpoints:
  - `POST /api/register-push` (line 4427)
  - `POST /api/unregister-push` (line 4444)

### 4.3 Quiet hours + settings

- `_get_notif_settings(user)` merges stored settings over
  `DEFAULT_NOTIFICATION_SETTINGS` (categories: `check_ins`, `habits`,
  `workouts`, `coach_messages`, `weekly_videos`, `roster`,
  `programme_updates`, `flight_support`, `crew_base`).
- Quiet hours: `quiet_hours_start` / `quiet_hours_end` — respected by
  `_in_quiet_hours()` before enqueue.
- Aviation-duty guard also drops pushes during active flight duty windows.

### 4.4 Reminder tick

- `_tick_reminders()` (server.py line 12395) — invoked by a background
  scheduler in `server.py`.
- Iterates users, enqueues `weekly_check_in_available`, `reminder_1/2/last`,
  `missed_check_in`, `habit_daily`, `workout_today`, etc. based on schedule.
- `_tick_reminders_all()` is the batch entrypoint the scheduler calls.

### 4.5 Emergent push key contract

`google-services.json` and APNs config are handled by the Emergent build
pipeline, **not** by this repo. The user's checked-in `.env` value
(`EMERGENT_PUSH_KEY=placeholder`) is intentional and MUST NOT be edited.
Push only works from a published build, never from Expo Go / web preview.

---

## 5. App data retrieval (client-side loaders)

### 5.1 The single API entrypoint

- `/app/frontend/src/lib/api.ts` — one `api()` helper wraps `fetch`, prepends
  `EXPO_PUBLIC_BACKEND_URL + "/api"`, injects the Bearer token from
  `AsyncStorage["cf_token"]`, and surfaces structured `detail` objects so
  callers can branch on `err.detail.code` (e.g. `profile_incomplete`,
  `preview_readonly`).
- `uploadFile()` handles React-Native FormData (`{uri, name, type}`) and
  browser Blob/File uniformly.

### 5.2 Auth context

- `/app/frontend/src/lib/auth.tsx` — React Context that holds
  `{user, loading, ...}` and `refresh()`s from `GET /api/auth/me` on mount.
- Token is stored in `AsyncStorage` under key `cf_token`.
  During preview, coach token is stashed at `cf_token_backup`.

### 5.3 Client home loaders (`app/(client)/home.tsx`)

Calls in parallel on focus:
- `GET /api/client/today` — composite Today snapshot (see §3.1)
- `GET /api/workouts/week` — legacy V1 workout row (V2 clients pass through
  the bridge, see below)
- `GET /api/programme/current`, `GET /api/programme/focus`
- `GET /api/roster/current`, `GET /api/roster/jobs/active`
- `GET /api/setup-day/status`, `GET /api/standby/today`
- `GET /api/profile/live-state` — cached `db.live_state` (sleep/energy)
- `GET /api/personal-activities`, `GET /api/events/active`,
  `GET /api/events/current`
- `GET /api/reassessment/prompts`

### 5.4 V2 client bridge (crucial)

`feature_v2_client_bridge.py::synth_workouts_for_user()` is what makes V2
clients invisible to the legacy client UI:

1. Check `users.profile.v2_flags.{engine_v2| v2_default}`.
2. Read `plan_live_v2` (`active=True`).
3. For each `placement`, look for an override in
   `plan_live_v2_implementations` (Change Setup), then per-exercise swaps
   in `plan_live_v2_exercise_swaps`, then compose a **legacy-shaped
   workout row** via `synth_workout_from_placement()`.
4. Return that array. Legacy endpoints (`/workouts/week`,
   `/workouts/{wid}`) transparently splice these in.

The synthetic workout id format is `v2p:{live_id}:{exposure_id}` —
`synth_workout_by_wid()` reverses it.

### 5.5 Coach shell loaders

- `/app/frontend/app/(coach)/v2-home.tsx` — hits
  `GET /api/v2/coach/home/action-queue`, `/dashboard/attention`,
  `/dashboard/summary`, `/dashboard/clients`, `/calendar`,
  and the client-directory endpoint.
- `EngineV2DraftPanel.tsx` calls `/v2/coach/clients/{id}/engine-v2/draft` +
  `state` + `exceptions` + `compare` + `publish`.

### 5.6 Config-driven feature gates

`useFlag()` from `src/lib/appConfig.tsx` reads `db.app_config` via
`GET /api/app-config/effective`. That's how the frontend toggles
Engine V2, Crew Base, Nutrition, Flight Support cards without needing a
new build.

---

## 6. API routes map

Route decorators live either on `api = APIRouter(prefix="/api")` in
`server.py` (~182 routes) or on the imported `api` in every `feature_*.py`
(~129 additional V2 routes). All are mounted under `/api/*`.

### 6.1 V1 core (server.py)

Auth, roster, workouts, hotels, nutrition, coaching-DNA, events, personal
records, workouts, exercises, videos, checkins, messages, coach dashboard,
progress, calendar, notifications, timezone. See grep output at
`/app/backend/server.py` for the full list — approximately:

- **Auth:** `/auth/signup`, `/auth/login`, `/auth/me`, `/auth/change-password`,
  `/auth/onboarding`, `/auth/player-pref`.
- **Roster:** `/roster/extract`, `/roster/upload-and-generate`,
  `/roster/{rid}/confirm`, `/roster/current`, `/roster/history`,
  `/roster/jobs/*`, `/roster/{rid}/day`.
- **Workouts:** `/workouts/week`, `/workouts/{wid}`, `/workouts/{wid}/swap-exercise`,
  `/workouts/{wid}/move`, `/workouts/{wid}/complete`, `/workouts/generate-month`,
  `/workouts/regenerate`, `/workouts/{wid}/sets`.
- **Calendar/Schedule:** `/calendar/timeline`, `/calendar/day-override`,
  `/schedule/daily-happened`, `/schedule/standby`, `/schedule/sickness`,
  `/schedule/holiday`, `/schedule/smart-replan`, `/schedule/events`.
- **Reality:** `/reality/kinds`, `/reality/submit`, `/reality/apply`,
  `/reality/history`, `/reality/{event_id}`, `/coach/reality/pending`,
  `/coach/reality/decision`.
- **Coach:** `/coach/clients`, `/coach/dashboard`, `/coach/clients/{id}`,
  `/coach/pending-approvals`, `/coach/calendar`, `/coach/analytics`,
  `/coach/tasks`, `/coach/exercise-swaps`, `/coach/roster-alerts`,
  `/coach/clients/{id}/reset-password`, `/coach/clients/{id}/directives`,
  `/coach/clients/{id}/duplicates`.
- **Exercises / videos:** `/exercises*`, `/coach/videos*`, `/coach/exercises`,
  `/videos/blob/{blob_id}`.
- **Nutrition:** `/nutrition/meals`, `/nutrition/summary`, plus barcode /
  photo / travel endpoints in dedicated `feature_nutrition_*` modules.
- **Notifications:** `/notifications*`, `/register-push`, `/unregister-push`.

### 6.2 V2 engine (`feature_v2_*.py`)

All under `/api/v2/*`. Key groups:

| Prefix | File | Purpose |
|---|---|---|
| `/v2/coach/clients/{id}/goals*` | `feature_v2_p2_goals.py` | Goal + programme + phase CRUD |
| `/v2/coach/clients/{id}/objectives*`, `planning-windows*` | `feature_v2_p3_demand.py` | Objective build + planning window |
| `/v2/coach/clients/{id}/roster-facets/build`, `schedule-days*` | `feature_v2_p4_roster.py` | Roster → schedule_days facets |
| `/v2/coach/clients/{id}/plan/build`, `assignments*`, `exceptions*` | `feature_v2_p5_scheduling.py` | WHEN — placement scheduler |
| `/v2/coach/clients/{id}/plan/build-implementations`, `implementations/{aid}` | `feature_v2_p6_construction.py` | HOW — workout construction |
| `/v2/client/equipment-contexts`, `/v2/coach/.../adapt` | `feature_v2_p7_equipment.py` | Equipment + adapt |
| — | `feature_v2_p8_progression.py` | Progression coefficients |
| `/v2/coach/clients/{id}/events`, `/v2/coach/clients/{id}/phase-transitions` | `feature_v2_p9_events.py` | Events + phase transitions |
| `/v2/client/readiness`, `/v2/client/reality/apply`, `/v2/coach/.../directives` | `feature_v2_p10_reality.py` | Reality + readiness + directives |
| `/v2/coach/clients/{id}/jobs*`, `/shadow/build`, `/v2/admin/metrics` | `feature_v2_p12_automation.py` | Automation + metrics |
| `/v2/coach/clients/{id}/engine-v2/kickoff`, `/draft`, `/status`, `/enable`, `/disable` | `feature_v2_engine_v2_kickoff.py` | The single "Build Plan" endpoint |
| `/v2/coach/goal-config/status/{key}`, `.../exceptions/*/resolve`, `/compare`, `/publish`, `/state`, `/placement-detail`, `/v2/client/plan/live*` | `feature_v2_engine_v2_publish.py` | Publish gates + Live-read |
| `/v2/coach/clients/{id}/plan/publish` (deprecated) | `feature_v2_coach_publish.py` | Legacy publish — do not use |
| `/v2/coach/clients/{id}/plan/kickoff` | `feature_v2_coach_kickoff.py` | Legacy kickoff — superseded by engine-v2/kickoff |
| `/v2/coach/clients/{id}/training-availability` | `feature_v2_coach_training_availability.py` | **NEW** — coach-editable duty caps |
| `/v2/coach/clients/{id}/command-bar/*` | `feature_v2_coach_command_bar.py` | LLM command bar |
| `/v2/coach/clients/{id}/plan/implementations/{iid}` (PATCH/DELETE), `.../plan/swap-exercise`, `.../plan/regenerate-day` | `feature_v2_coach_inline_editor.py` | Inline coach editor |
| `/v2/coach/dashboard/*`, `/v2/coach/me/dashboard-flag`, `.../workspace/*` | `feature_v2_coach_dashboard.py` | Coach dashboard summary |
| `/v2/coach/home/action-queue`, `/v2/coach/clients/directory`, `/v2/coach/calendar` | `feature_v2_coach_home.py` | Coach v2 home |
| `/v2/coach/clients/{id}/dashboard-directives*`, `/generation/status`, `/programme/summary` | `feature_v2_coach_directives.py` | Coach directives + generation status |
| DELETE `/v2/coach/clients/{id}` | `feature_v2_coach_client_admin.py` | Confirmed client delete (requires `confirm_email`) |

### 6.3 Aviation, preview, exercise-content, media, admin

| Prefix | File |
|---|---|
| `/client/today`, `/coach/clients/{id}/today`, `/flight-support/*` | `feature_aviation_support_api.py` |
| `/coach/preview/impersonate`, `/exit`, `/demo-seed`, `/new-client` | `feature_preview.py` |
| `/coach/preview/persistent`, `/coach/preview/reset` | `feature_preview_sandbox.py` |
| `/exercise-content*` | `feature_exercise_content.py` |
| `/admin/media/reconcile`, `/admin/media/todos` | `feature_media_reconciliation.py` |
| `/admin/telemetry*` | `feature_admin_telemetry.py` |
| `/admin/lifecycle/*` (soft-delete, restore, archive, permanent-delete) | `feature_admin_lifecycle.py` |
| `/app-config/effective`, `/app-config/audit` | `feature_app_config.py` |

**Router registration:** every feature module imports `api` from `server.py`
and attaches its routes at import time. `server.py` imports the feature
modules at the **very bottom** of the file (line ~12680+), after all shared
helpers are defined.

---

## 7. DB schema — key relationships

MongoDB. Database name is env-driven (`DB_NAME`, default `crewfit_v1` on
Preview). The Preview and Production instances are **separate physical
databases** (see §8).

### 7.1 Identity + auth

- **`users`** — one document per person. Role ∈ `{client, coach, admin}`.
  Notable fields:
  - `id`, `email`, `password_hash` (bcrypt), `name`, `role`,
    `created_at`, `onboarded`.
  - `coach_id` / `assigned_coach_id` — who owns this client.
  - `profile.v2_flags.{engine_v2, v2_default, roster_facets_enabled,
    reality_v2_enabled, …}` — feature flags per client.
  - `profile.primary_goal_type` / `primary_goal` / `main_goal_key` /
    `event_type_pref` — DNA goal candidates read by Engine V2 kickoff.
  - `profile.availability` — duty caps and off-day preferences (edited via
    `/v2/coach/clients/{id}/training-availability`).
  - `profile.flight_support.disabled` — global FS toggle.
- **`system_bootstrap`** — one-shot marker for the Louis emergency password
  reset (see §8.3).

### 7.2 Restrictions (injury / avoid patterns)

- **`restrictions`** — `{client_id, region, severity, avoid_patterns[],
  raw_text, source, status, created_at, updated_at}`.
  - Written by `POST /api/coach/clients/{cid}/restrictions`.
  - Consumed by `feature_v2_p6_construction.py` (skips slots that match
    `avoid_patterns`) and by `feature_v2_p10_reality.py::_write_readiness`.

### 7.3 Roster tree

```
rosters (V1 source of truth for the raw parsed calendar)
  └── days[]  (embedded)   ← parser output, includes label/blocked/equipment_assumption
        │
        │  _build_roster_facets() fans out to →
        ▼
schedule_days   ─── (unique on client_id+date)
   │  derived.{duty_burden_score, training_opportunity,
   │           available_time_min, recommended_intensity_ceiling,
   │           classification}
   │
   ├──▶ roster_duties     (one row per duty period, links back via schedule_day_id)
   │       └──▶ flight_sectors  (one row per flight leg, links via duty_id)
```

- Rosters are versioned via `is_active` and `superseded_by`. Rebuild is
  idempotent — facet rebuild deletes old rows for the same
  `source_roster_id` and reinserts.

### 7.4 Programme + plan (V1)

- **`programmes`** — legacy V1 programme doc per user.
- **`workouts`** — legacy V1 workout doc per (user, date). This is what the
  client UI reads. Post-V2, entries are **synthesised in-memory** via
  `synth_workouts_for_user()` unless the client is legacy V1.
- **`programme_timeline`, `progression_snapshots`, `progress`, `checkins`,
  `check_ins`, `daily_pulse`, `weekly_reviews`** — V1 telemetry.

### 7.5 V2 engine

```
goals_v2 ─┐
programmes_v2 (long-horizon programme spec) ─┐
  └── programme_phases_v2 (phase blocks)     │
training_objectives (WHAT — what to expose) ─┤
  └── objective_exposures (WHEN — placements)│
                                             ▼
plan_drafts_v2  ← Engine V2 kickoff output (draft)
                  fields: placements[], session_specs{},
                          programme_validation, exceptions[],
                          effective_context, planning_window, status
                          ("draft" | "published" | "superseded")
                          exception_resolutions[] (coach ACKs)
                          receipt (Iter 130 deterministic hash)
        │
        │  publish
        ▼
plan_live_v2  ← Immutable snapshot activated for the client
                one row with active=True per client
                previous_live_id points to the previously-active row
        │
        ├── plan_live_v2_implementations   (Change Setup overrides for a
        │    specific placement / date range — spec_snapshot wins)
        ├── plan_live_v2_exercise_swaps    (per-exercise swaps for a date)
        └── decision_records               (audit trail)

workout_assignments        ← concrete "one workout row" the coach edits
workout_implementations    ← the built-out per-slot content for an assignment
```

Also:

- **`readiness_states`** — deterministic band per client per date.
- **`coach_directives`** — structured directives
  (`avoid_movement | require_movement | limit_frequency | limit_volume |
  limit_intensity | note_only`).
- **`exceptions`** — validator + roster-change flags surfaced to the coach
  UI; resolved via `POST /v2/coach/clients/{id}/engine-v2/exceptions/{eid}/resolve`.
- **`exposures / objective_exposures`** — the WHEN-layer output.
- **`equipment_contexts`** — captured client equipment for a date/window.
- **`change_sets, plan_versions, plan_snapshots, approvals`** — foundation
  audit tables (`feature_v2_state_foundation.py`).

### 7.6 Aviation / flight support

- `flight_support_activity` (completions), `flight_support_overrides`
  (per-user overrides), `media_queue` (persona-aware media backlog).

### 7.7 Nutrition + habits + crew base

- `nutrition_logs`, `nutrition_targets`, `nutrition_favourites`,
  `nutrition_hydration`, `nutrition_insights`, `nutrition_notes`,
  `nutrition_photo_scans`, `barcode_cache`.
- `habits`, `habit_logs`, `habit_events`, `habits_daily`, `habit_reviews`.
- `crew_base_posts`, `crew_base_comments`, `crew_base_reactions`,
  `crew_base_seen`.

### 7.8 Ops + auditing

- `audit_logs`, `auth_events`, `coach_change_log`, `coach_reset_audit`,
  `decision_records`, `metrics_events`, `preview_audit`, `roster_audit_log`,
  `system_bootstrap`.

---

## 8. Preview vs Production separation

### 8.1 Databases

Both stacks are the same **codebase**, deployed twice, pointing at
**different MongoDB instances**:

| Stack | `MONGO_URL` | `DB_NAME` | Notes |
|---|---|---|---|
| Preview (local pod) | `mongodb://localhost:27017` | `crewfit_v1` | What you see when you open the Emergent preview URL |
| Production (Cloudflare Pages + hosted backend) | different Mongo cluster (managed) | (managed) | What Louis's real clients hit |

**Guarantee:** no code path in this repo hard-codes a database name or a
Mongo URL. Everything reads `os.environ["MONGO_URL"]` and
`os.environ["DB_NAME"]` at boot. Preview cannot see Production data and
vice-versa.

### 8.2 Frontend URL config (protected)

`/app/frontend/.env` MUST NOT be edited:

- `EXPO_PACKAGER_PROXY_URL` — Emergent-managed ingress
- `EXPO_PACKAGER_HOSTNAME` — ditto
- `EXPO_PUBLIC_BACKEND_URL` — same host; `api.ts` appends `/api`.

Any `/api/*` request from the client is routed to backend on
`0.0.0.0:8001` by the Kubernetes ingress. Everything else is served by
Metro (Expo dev bundler) on port 3000.

### 8.3 The `RESET_ADMIN_ON_STARTUP` unlock

`/app/backend/server.py::seed()` (~line 11329) has an emergency reset:

- If `RESET_ADMIN_ON_STARTUP=1` **or** `system_bootstrap["admin_password_unlock_iter130a"]`
  doc is missing → force Louis's password to `ADMIN_STARTUP_PASSWORD`
  (default `"Louis123!"`) and write the marker.
- Currently `RESET_ADMIN_ON_STARTUP=1` is set on Preview so restarts always
  reset. **On Production this is what re-resets Louis's password on every
  restart** — remove or set to `0` after verifying Louis's new password
  sticks. (This is a known follow-up.)

### 8.4 Coach "Preview as Client" mode (Coach → Client role toggle)

Not the same as "Preview stack vs Production stack". This is an
**in-app impersonation** feature so Louis can walk through the client
experience without leaving his coach account:

- `feature_preview.py`:
  - `POST /coach/preview/impersonate` — issues a JWT with
    `{preview: true, preview_by: coach_id, preview_by_email}`.
  - `POST /coach/preview/exit` — audit-only; frontend discards token.
  - `POST /coach/preview/demo-seed` + `POST /coach/preview/new-client` —
    scaffold throwaway target clients.
- `feature_preview_sandbox.py`:
  - `POST /coach/preview/persistent` — persistent sandbox client (Louis's
    own play area, survives across sessions).
  - `POST /coach/preview/reset` — wipe the sandbox.

### 8.5 Preview read-only guard

Middleware in `server.py` (`preview_readonly_guard`, line 12687):

- Any non-GET request signed by a `preview=True` JWT is **rejected 403**
  with `detail.error = "preview_readonly"` unless the path is in
  `_PREVIEW_WRITE_ALLOWLIST` or `preview_kind == "sandbox"`.
- The frontend `api()` helper (see §5.1) catches this and surfaces a
  friendly toast — no console spam.

### 8.6 Coach "settings mode"

`PATCH /api/coach/settings/mode` (server.py line 6966) toggles the coach's
own default mode (`live` vs `preview`) — persists on the user doc so
subsequent logins land in the correct workspace.

---

## 9. Coach approval / publish flow

### 9.1 The two-step contract

1. **Kickoff (draft)** — `POST /api/v2/coach/clients/{id}/engine-v2/kickoff`
   (`feature_v2_engine_v2_kickoff.py`). Runs
   WHAT → WHEN → HOW → VALIDATE. Writes results to `plan_drafts_v2`.
   **Never touches Live.**
2. **Publish (live)** — `POST /api/v2/coach/clients/{id}/engine-v2/publish`
   (`feature_v2_engine_v2_publish.py`). Promotes the current draft into
   `plan_live_v2` with `active=True`.

### 9.2 Publish gates (in order)

`endpoint_engine_v2_publish` enforces these deterministically:

1. **Stale draft** — the passed `draft_id` must equal the latest active
   draft; otherwise `422 stale_draft` with the current id.
2. **Goal-config status** — `get_goal_config_status(goal_key)`:
   - `MISSING` → hard block `422 config_missing`.
   - `PARTIAL` → require `ack_partial_config=true` on the request, else
     `422 partial_config_ack_required` (this is why
     `strength.fat_loss` and `running.marathon` need P8 progression
     tables — they currently return PARTIAL).
3. **Programme validation** — if `programme_validation.ok == false`:
   - No exceptions at all → `422 validation_failed_no_exceptions`
     ("validator gap — the specific blocking finding has not been surfaced
     for coach resolution"). This is the **Iter 128e safety net**.
   - Otherwise all `KEY`/`IMPORTANT` exceptions must be resolved (row in
     `exception_resolutions[]`) or reported as `422
     unresolved_blocking_exceptions` with a list of blockers.
4. **Every non-rest placement must have a `session_spec`** — else `422
   incomplete_workout_construction`.

### 9.3 On success

1. Previous `plan_live_v2` row is set to `active=false` with
   `deactivated_at`, `deactivated_by`, `superseded_by_draft`.
2. New immutable `plan_live_v2` row is inserted with:
   `source_draft_id`, `goal_key`, `goal_config_status_at_publish`,
   `planning_window`, `effective_context`, `demand`, `placements`,
   `session_specs`, `programme_validation`, `unfilled`,
   `exception_resolutions`, `ack_partial_config`, `override_reason`,
   `coach_note`, `activated_at`, `activated_by`, `previous_live_id`.
3. `plan_drafts_v2` row is stamped `status="published"` with `live_id`.
4. `decision_records` audit entry written (actor=`coach`, layer=
   `ORCHESTRATION`, outcome=`PUBLISHED`).
5. `engine_v2_publish` metric emitted.

### 9.4 Client visibility

The instant `plan_live_v2` flips, the V2 bridge (`synth_workouts_for_user`)
starts serving the new placements. No client-side refresh needed beyond a
normal focus-refetch of `/workouts/week` or `/client/today`.

### 9.5 Legacy publish endpoint

`POST /api/v2/coach/clients/{id}/plan/publish` (`feature_v2_coach_publish.py`)
is marked `deprecated=True` in FastAPI but still mounted. It writes to the
older `plan_versions` / `plan_snapshots` foundation tables — the newer
`plan_live_v2` pathway supersedes it. Do not add new callers.

### 9.6 Exception resolution before publish

- Coach views exceptions via `GET /v2/coach/clients/{id}/engine-v2/exceptions`.
- Resolves each via `POST /v2/coach/clients/{id}/engine-v2/exceptions/{eid}/resolve`
  with `{action: "acknowledge" | "override" | "ignore", note}`. This adds
  a row to `plan_drafts_v2.exception_resolutions[]` and unblocks the
  publish gate if the exception was KEY/IMPORTANT.

### 9.7 Diff + compare (pre-publish review)

- `GET /v2/coach/clients/{id}/engine-v2/compare` returns a
  side-by-side diff between the current draft and the currently-live plan.
  Rendered in `EngineV2DraftPanel.tsx` before the coach hits publish.

### 9.8 Publish audit trail — where to look

| Question | Where |
|---|---|
| "When was this client's plan last published?" | `plan_live_v2.activated_at` where `active=true` |
| "Who published it?" | `plan_live_v2.activated_by`, `decision_records` filter by scope |
| "What draft was it built from?" | `plan_live_v2.source_draft_id` → `plan_drafts_v2.id` |
| "What did the previous plan look like?" | `plan_live_v2.previous_live_id` → prior row (kept forever) |
| "Was this a partial-config publish?" | `plan_live_v2.ack_partial_config` + `goal_config_status_at_publish` |
| "What exceptions were acknowledged?" | `plan_live_v2.exception_resolutions[]` |
| "Why did the coach override the gate?" | `plan_live_v2.override_reason` + `coach_note` |

---

## 10. Appendix A — file → responsibility index

Only the modules a maintainer will actually touch. Small helpers omitted.

### Backend — V1 core

| File | Responsibility |
|---|---|
| `server.py` (~12,720 lines) | HTTP app, auth, seed, most V1 endpoints, push proxy, preview R/O middleware |
| `feature_roster_confirmation.py` | Client-side roster parsing pipeline + activation |
| `feature_coach_roster_upload.py` | Coach-side "upload on behalf of client" |
| `feature_coach_roster_months.py` | Multi-month roster utilities |
| `parsers/emirates.py`, `emirates_detailed.py`, `emirates_labels.py` | Emirates PDF parser + labeller |
| `parsers/etihad.py`, `etihad_labels.py` | Etihad parser + labeller |
| `feature_exercise_content.py` | `exercises_v2` unified library + Nano Banana images |
| `feature_exercise_request_tasks.py` | Coach-task backlog for missing exercises |
| `feature_media_reconciliation.py` | Nightly gap-finder → `coach_tasks` |
| `feature_flight_support_media.py` | Persona-aware Flight Support media |
| `feature_notifications.py` | In-app bell + push settings |
| `feature_preview.py` | Coach "Preview as Client" (real/demo/new) |
| `feature_preview_sandbox.py` | Persistent sandbox client |
| `feature_aviation_support.py`, `feature_aviation_support_api.py` | Flight Support engine + `/client/today` |
| `feature_daily_briefing.py` | Daily briefing composer |
| `feature_nutrition*.py` | Nutrition (photo, barcode, travel, insights) |
| `feature_habits.py`, `feature_weekly_review.py` | Habits + weekly review |
| `feature_crew_base.py` | Community |

### Backend — V2 engine

| File | Responsibility |
|---|---|
| `feature_v2_common.py` | Flags, decision records, metrics, index bootstrap |
| `feature_v2_state_foundation.py` | Foundation audit tables |
| `feature_v2_p2_goals.py` | Goals + programmes + phases (WHAT) |
| `feature_v2_p3_demand.py` | Objectives + planning windows |
| `feature_v2_p4_roster.py` | Roster facets (schedule_days / duties / sectors) |
| `feature_v2_p5_scheduling.py` | WHEN — placement scheduler |
| `feature_v2_p6_construction.py` | HOW — workout construction |
| `feature_v2_p7_equipment.py` | Equipment context + `_adapt()` |
| `feature_v2_p8_progression.py` | Progression coefficients (**PARTIAL for strength.fat_loss + running.marathon**) |
| `feature_v2_p9_events.py` | Events + phase transitions |
| `feature_v2_p10_reality.py` | Readiness + reality chips + directives |
| `feature_v2_p12_automation.py` | Jobs + shadow build + admin metrics |
| `feature_v2_sport_configs.py` | `SPORT_CONFIGS` + `_GOAL_ALIASES` (frontend↔backend goal parity) |
| `feature_v2_demand_v2.py` | Sport-aware demand synthesis |
| `feature_v2_construction_v2.py` | New construction path (used by V2 kickoff) |
| `feature_v2_sequencing.py` | Session-day sequencer (48h recovery, target duration) |
| `feature_v2_validators_v2.py` | Programme validators |
| `feature_v2_variety.py` | Full-body A/B/C variety rotation |
| `feature_v2_defaults.py` | Default V2 flags for new clients |
| `feature_v2_engine_v2_kickoff.py` | THE Build-Plan endpoint |
| `feature_v2_engine_v2_publish.py` | THE Publish endpoint + Live-read |
| `feature_v2_client_bridge.py` | V2 → legacy workout row synthesis |
| `feature_v2_resolver.py` | Session-spec → exercise + media resolution |
| `feature_v2_coach_kickoff.py` | (legacy) coach kickoff |
| `feature_v2_coach_publish.py` | (legacy) publish — deprecated |
| `feature_v2_coach_dashboard.py` | Coach dashboard summary/attention/clients |
| `feature_v2_coach_home.py` | v2 home action queue + calendar |
| `feature_v2_coach_directives.py` | Structured directives UI |
| `feature_v2_coach_inline_editor.py` | Coach inline plan editing |
| `feature_v2_coach_command_bar.py` | LLM command bar |
| `feature_v2_coach_client_admin.py` | Confirmed client delete |
| `feature_v2_coach_training_availability.py` | NEW duty-cap editor |
| `feature_v2_directive_engine.py` | Roster-change exception emitter |
| `feature_v2_plan_live_adapt.py` | Reality-based live adapts |

### Frontend

| File | Responsibility |
|---|---|
| `app/index.tsx` | Root redirect (auth / onboarding / role) |
| `app/(auth)/*` | Login / signup / onboarding |
| `app/(client)/home.tsx` | Client home shell |
| `app/(client)/calendar.tsx`, `nutrition.tsx`, `profile.tsx`, `messages.tsx`, `base.tsx`, `crew-base-settings.tsx` | Client tab pages |
| `app/(coach)/v2-home.tsx`, `clients.tsx`, `calendar.tsx`, `overview.tsx`, `approvals.tsx`, `messages.tsx`, `analytics.tsx`, `checkins.tsx`, `exercises.tsx`, `library.tsx`, `videos.tsx`, `changelog.tsx`, `crew-base.tsx`, `profile.tsx` | Coach shell |
| `app/(coach)/engine-v2-draft/[cid].tsx` | Draft review + publish |
| `app/roster-upload.tsx` | Client roster upload |
| `app/reality-history.tsx`, `checkin.tsx`, `assessment.tsx`, `reassessment/*` | Reality + check-in surfaces |
| `src/lib/api.ts` | Single fetch helper |
| `src/lib/auth.tsx` | Auth context |
| `src/lib/preview.tsx` | Coach "Preview as Client" state |
| `src/lib/appConfig.tsx` | Feature flags (`useFlag()`) |
| `src/lib/push.ts` | Push token registration |
| `src/lib/sentry.ts` | Sentry init |
| `src/components/EngineV2DraftPanel.tsx` | Draft summary + publish |
| `src/components/ClientAdminDrawer.tsx` | Client admin (incl. duty-cap form) |
| `src/components/RealityModal.tsx` | Reality chip picker |

### Ops

| File | Responsibility |
|---|---|
| `backend/scripts/pietro_shadow_run.py`, `pietro_dna_check.py`, `pietro_safe_reset.py`, `wipe_users.py` | Read-only ops helpers (no writes on prod without `--confirm`) |
| `backend/migrations/*` | Migrations (idempotent, applied in `_startup` on demand) |
| `backend/tests/test_iter130g_programme_structure.py`, `test_iter130h_strength_cardio_protection.py` | Latest structural tests |
| `frontend/.env` | Preview URL config — **do not edit** |
| `backend/.env` | Mongo, JWT, LLM key, admin unlock (see §8.3) |

---

## 11. Appendix B — Conflicting sources of truth (call-outs)

### B1. Exercise library — two collections, one resolver

- `db.exercises` (V1) and `db.exercises_v2` (new) both exist and both hold
  data. The V2 resolver (`feature_v2_resolver.py`) reads V2 first, then
  V1. Legacy V1 endpoints (`GET /exercises`) only see V1.
- Practical rule: **all new content authoring happens in `exercises_v2`**
  via `POST /exercise-content`; V1 collection is only migrated on demand.

### B2. Scheduler vs Validator duration floor

- `feature_v2_sequencing.py` rejects placement on a day if
  `target_duration_min (40) + already_scheduled > cap`.
- `feature_v2_validators_v2.py` feasibility heuristic rejects when
  `cap < 30` (the quota MIN).
- These disagree on 30–39-min roster days: the validator says "day is
  feasible", the scheduler still rejects. This is the root cause behind
  Joel's 3rd strength session failing to place. **Known issue, not fixed
  in this handover.** See conversation history.

### B3. Publish endpoints — two of them

- `POST /api/v2/coach/clients/{id}/plan/publish` (deprecated,
  `feature_v2_coach_publish.py`) — writes to `plan_versions` /
  `plan_snapshots`.
- `POST /api/v2/coach/clients/{id}/engine-v2/publish` (current,
  `feature_v2_engine_v2_publish.py`) — writes to `plan_live_v2`.
- The client bridge reads `plan_live_v2` **only**. If any UI still calls
  the deprecated endpoint, the client will not see the change.

### B4. "Today" — three concepts

- `GET /api/client/today` — **composite** aggregator (recommended surface).
- `GET /api/reality/*` — V1 reality events store.
- `POST /api/v2/client/reality/apply` — V2 chip resolver.
- The client home consumes `/client/today`; reality submissions go through
  the V2 chip resolver. `/reality/*` is legacy telemetry.

### B5. Kickoff endpoints — two of them

- `POST /v2/coach/clients/{id}/plan/kickoff` (legacy,
  `feature_v2_coach_kickoff.py`).
- `POST /v2/coach/clients/{id}/engine-v2/kickoff` (current — the one
  the frontend's "Build Plan" button uses).

### B6. Goal-config parity between frontend and backend

- Frontend goal keys must map to entries in `feature_v2_sport_configs.py`
  (`SPORT_CONFIGS` or `_GOAL_ALIASES`).
- A startup lint (`server.py::_startup`, ~line 11478) logs a loud WARN
  when a frontend key has no backend alias. If Louis sees
  `critical_dna_missing` on Build Plan, this is the first log to check.

### B7. `RESET_ADMIN_ON_STARTUP` on Production

- Currently set to `1` in `backend/.env`. On Production this force-resets
  Louis's password to `Louis123!` on every restart.
- **Follow-up:** once Louis's new password is verified to persist,
  set this to `0` (or delete the env var) so `password_changed_at`
  writes survive.

### B8. `EMERGENT_PUSH_KEY=placeholder`

- Intentional. The Emergent deploy pipeline replaces the value during
  build. Do not manually change it. Push notifications only work on
  Published builds, never on Expo Go / web preview.

### B9. Wix DNS + Cloudflare Pages

- Web dashboard is deployed on Cloudflare Pages (not Cloudflare Workers)
  because the domain's nameservers stay on Wix. Pages accepts a
  CNAME/A-record mapping without transferring the domain.
- Backend continues to be served by the Emergent-managed API host — the
  Pages site only serves the compiled Expo web bundle.

---

**End of Delta Handover.**

For deeper dives into the V2 Engine's programmatic logic (variety
rotation, marathon guard, fat-loss cardio protection, deterministic
receipts, unfilled/exception surfacing) see the existing V2 Engine
iteration docs and the Joel/Pietro deep-dive specs previously shared
in this session.
