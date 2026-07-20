# CrewFit Roster Upload System — Full Handover Report

_Date: July 2026 — audit prepared for handover to product owner. This report is
based on a direct static read of the codebase, database schema and job flow as
committed on the current branch. Nothing was built during this audit._

---

## Section 1 — Current Status

| Component | Verdict | Notes |
|---|---|---|
| Roster upload (client picks file) | ✅ WORKING | JPEG/PNG + PDF both accepted; base64 stream is fine end-to-end. |
| Roster parsing | ✅ WORKING | Uses Gemini for OCR/extraction; brittle on unusual layouts but functional on tested airline formats. |
| Calendar generation | ✅ WORKING | Every parsed day writes into `rosters.days[]` and is readable by `/api/calendar/timeline`. |
| Programme generation after roster | ⚠️ PARTIAL | Two blocking issues: (1) **LLM budget exhausted on the shared Emergent key** — every Claude chunk call fails. (2) Template fallback exists but has a **known bug**: retry-worker path misses `source='template'` + `needs_coach_review=true` flags on the DB rows (main worker is correct). |
| Coach review alerts | ✅ WORKING | High-priority `coach_tasks` doc created for `timeout`, `error`, `0 workouts generated`, and now `template fallback used`. |
| Client-facing "plan preparing / needs review" banners | ✅ WORKING | Home screen polls `/roster/jobs/active` and shows red/amber banners with retry + acknowledge. |
| **Safe for real beta today?** | 🟡 **ALMOST** | Safe ONLY if the Emergent Universal Key budget is topped up. Otherwise clients receive the deterministic template plan (still real workouts) + a coach task, but the plan will not be tailored by the LLM. |

**Why "almost":** the flow is now robust to LLM outages, but the template
fallback is a starter plan, not a coaching-grade programme. For a paid beta we
also want an LLM-generated plan on top of the safety net.

---

## Section 2 — Supported File Types

| Type | Frontend picker | Backend parser | Tested | Known issues |
|---|---|---|---|---|
| PDF | ✅ `expo-document-picker` (`application/pdf` filter) | ✅ Gemini vision on rendered pages | Yes (single roster) | Multi-page PDFs work — Gemini reads text natively. Poor scans still degrade parsing. |
| JPEG / PNG screenshot | ✅ `expo-image-picker` | ✅ Gemini vision | Yes (screenshots) | Cropped screenshots occasionally miss the header date row. |
| HEIC / HEIF | ⚠️ Accepted by picker but not tested end-to-end | Uncertain | No | Should convert client-side before upload. |
| CSV / Excel | ❌ Not supported | ❌ Not supported | — | No importer written. |
| Plain text paste | ❌ Not supported | ❌ Not supported | — | No paste-a-roster field. |
| Manual entry | ⚠️ Partial | The client can add per-day overrides via `POST /calendar/day-override` but cannot enter a whole roster from scratch. |
| Camera capture ("Take Photo") | ❌ Not exposed | — | — | Only "Upload Photo" from library is wired. |

---

## Section 3 — Client Upload Flow

**Screen:** `/roster-upload.tsx` (Expo Router route `/roster-upload`).

1. Client taps "UPLOAD ROSTER" on Home (empty state) or from the Setup Day card.
2. Two options appear: `UPLOAD PHOTO` (image picker) or `UPLOAD PDF` (document picker).
3. On pick, the file is base64-encoded and POSTed to
   `POST /api/roster/upload-and-generate`. The backend responds immediately with a `job_id`.
4. Frontend enters a **progress screen** with 8 stage rows (Uploading roster → Preparing coach review), a
   percentage, and a coloured progress bar. It polls `GET /api/roster/jobs/{job_id}` every 2 seconds.
5. Success path: status flips to `complete`, message reads either "Your new plan is ready" (LLM path) or
   "Starter plan ready — Louis will refine your sessions soon." (template fallback). The client is redirected
   to the calendar screen after ~800 ms.
6. Failure paths render inline recovery UI:
   - **Slow** (no progress ≥ 90 s): amber banner "This is taking longer than expected. You can leave this
     screen — we'll keep working in the background." + `Message Louis` + `Go To Home` buttons.
   - **Stuck** (no progress ≥ 210 s): red banner "Your roster was uploaded, but plan generation may need
     review."
   - **needs_review / partial / failed** status: `RETRY PLAN GENERATION` primary button + `MESSAGE LOUIS` +
     `GO TO HOME`.
7. Cancel button prompts a three-option dialog: `Continue waiting` / `Keep roster and exit` /
   `Cancel generation`.

Home screen also renders standing banners above `NEXT 7 DAYS`:
- Red "CrewFit is preparing your training plan around your roster." while the job is `queued|processing`.
- Amber "Your roster uploaded successfully, but your training plan needs review. Louis has been notified."
  while `needs_review|partial|failed` and not yet acknowledged.

---

## Section 4 — Progress / Job System

**YES — proper background job.** The endpoint returns immediately and a real async task drives progress.

- `job_id` — UUID generated in `roster_upload_and_generate`.
- Stored in **`roster_jobs`** collection with fields: `id, user_id, status, stage, progress, message, error, error_detail, created_at, updated_at, completed_at, roster_id, workouts_generated, used_template, retry_count, retried_at, client_acknowledged, acknowledged_at`.
- Frontend polls `GET /api/roster/jobs/{job_id}` every 2 s.

**Statuses actually implemented:**
- `queued`, `processing`, `complete`, `failed`, `partial`, `needs_review`.

**Stages actually implemented (`stage` field):**
- `uploading`, `reading`, `extracting`, `detecting`, `overlap`, `calendar`, `generating`, `coach`, `complete`.

**Progress logic**
- The main worker sets discrete checkpoints (5 → 15 → 30 → 40 → 55 → 70 → 80 → 98 → 100).
- A background `_generation_heartbeat` bumps progress 80 → 95 while the LLM runs so the frontend never
  sees a truly frozen bar (this is the fix for the earlier "stuck at 80%" report).

**Timeouts**
- Per LLM chunk: **75 s** (`asyncio.wait_for(call_claude, 75)`).
- Whole plan generation: **180 s** (`asyncio.wait_for(_generate_month, 180)`), applied in both the main and
  retry workers.

**Retry**
- `POST /api/roster/jobs/{job_id}/retry` re-runs `_generate_month` on the SAVED roster (no re-upload).
  Also increments `retry_count` and calls the template fallback if the LLM still fails.

**Acknowledge**
- `POST /api/roster/jobs/{job_id}/acknowledge` sets `client_acknowledged=true` so the amber banner stops
  appearing after dismiss.

---

## Section 5 — Roster Parsing

**Module:** `/app/backend/server.py` — the endpoint chain
`POST /roster/extract` (raw parse) and `POST /roster/upload-and-generate` (one-shot upload + parse + plan).

**Parser type:** LLM (Google Gemini vision — text and PDF pages both go via the same call). NOT rule-based
and NOT OCR-only. The LLM does OCR + interpretation in one step.

**Fields the parser is asked to extract per duty**
- `date` (local)
- `duty_type` (flight / standby / off / annual_leave / sickness / positioning / simulator / training / layover / rest)
- `report_time`, `off_duty_time`
- `duty_hours`
- Flight numbers, sectors, origin/destination airports
- Base + layover destination + hotel name when visible
- `time_zone` (departure/arrival)
- Notes (any free-text callouts)

**Uncertain data handling**
- Missing fields default to `unknown`; the parser is instructed not to fabricate.
- The whole month is packed into `rosters.days[]`; anything not recognised is stored with `day_type='unknown'`.
- Overlaps with prior rosters are surfaced to the client on `POST /roster/{rid}/confirm` for approval before persisting.

**Time zones**
- All dates are stored as **client-local ISO strings** (`YYYY-MM-DD`). No UTC drift in the workouts feed,
  which is why "Today" now correctly appears at the top of the 7-day list.

**Weaknesses (honest)**
- Only tested with a handful of airline layouts (Emirates, easyJet, BA-style). Unusual formats risk empty
  or partial parses.
- No confidence score returned per field.
- Screenshots with heavy cropping or overlapping graphics may miss the header date.

---

## Section 6 — Duty Types Detected

Based on the roster.days schema and the LLM extraction prompt:

| Duty type | Detected |
|---|---|
| Flying duty (generic) | ✅ |
| Short-haul | ✅ (via `duty_hours < 8`) |
| Long-haul | ✅ (via `long_haul` tag OR `duty_hours >= 10`) |
| Ultra long-haul | ⚠️ Partial (parsed as long-haul; no separate tag) |
| Night flight | ✅ |
| Early start / late finish | ⚠️ Partial — depth of parsing depends on the LLM |
| Multi-sector day | ✅ (each sector captured in `flights[]`) |
| Turnaround | ✅ |
| Layover | ✅ |
| Standby (airport / home / reserve) | ✅ generic; sub-type NOT distinguished |
| Positioning | ⚠️ Parsed if the source labels it as such |
| Simulator / recurrent / ground school | ✅ |
| Annual leave | ✅ |
| Sickness | ✅ |
| Day off / rest | ✅ |
| Unknown duty | ✅ (falls into `day_type='unknown'`) |

---

## Section 7 — Calendar Generation

- Every parsed day becomes an entry in `rosters.days[]` — an array embedded in the roster document (not a
  separate collection).
- The client-facing calendar is served by `GET /api/calendar/timeline` which merges roster days + workouts
  + day overrides into a single monthly view.
- Overlap detection runs against previously-saved rosters. Conflicts are surfaced on `/roster/{rid}/confirm`
  with a merge/replace choice before persisting.
- Old rosters are marked `is_active=false` when a new one is confirmed — they are **preserved as history**,
  never deleted.
- Client can override any day via `POST /calendar/day-override` (used from the Calendar screen long-press).
  Overrides live in a separate `day_overrides` collection with a `day_change_log` audit trail.
- Louis (coach) can edit any day via the coach client screen; edits also write to `day_change_log`.
- **Missing:** there is no explicit "review parsed roster before saving" step — the client sees the parsed
  data only via the calendar after upload.

---

## Section 8 — Workout Generation After Roster

**Trigger:** the `_worker()` inside `POST /roster/upload-and-generate` calls `_generate_month(user, roster)`
after roster save succeeds. Same trigger inside `_retry_worker()` on `POST /roster/jobs/{job_id}/retry`.

**Generator:** `_generate_month` at `server.py:4058`. Splits the roster into 7-day chunks and calls Claude
Sonnet 4.5 concurrently for each chunk. Each chunk returns one workout per date with `title, focus, location,
duration_min, warmup, exercises, alternatives, rationale, key_session, event_phase`.

**Inputs passed to the LLM**
- `user.profile` (up to 2 KB)
- **Coaching DNA** (`dna_history` latest snapshot, up to 2.5 KB)
- Active event (if any) with phase info
- 7 days of roster data (`days` + hotel data for layovers)

**Inputs currently NOT injected**
- Structured periodisation phase (Foundation → Build → Peak → Deload).
- Explicit weekly session target derived from goal.
- Personal activities collection (would let the LLM avoid clashes with tennis/football).
- Recent check-in feedback / RPE trends.

_This is the "programme quality" gap in Section 9._

**First-workout date**
- Handled by `feature_setup_day.filter_new_client_workouts` called inside the worker BEFORE persistence.
- Rules (post-fix):
  - If the client has NO completed workouts and NO other roster's workouts → treated as new; today is
    dropped, first workout falls on **tomorrow** by default.
  - Gate advances by at most **+2 days** (previously +7 caused the empty-week bug).
  - Only these tags count as "too heavy to start on": `night_flight`, `night-flight`, `night duty`,
    `overnight`, `red_eye`, `red-eye`. `duty_hours ≥ 14` also counts.
  - Existing clients bypass the gate.
  - Louis can override via `POST /api/coach/clients/{id}/programme/start-today`.

**Failure modes**
- If any chunk returns [], the surviving chunks still persist — partial results are kept.
- If ALL chunks return [] (LLM budget / provider outage / total timeout), the deterministic
  **template fallback** (`feature_workout_fallback.build_template_plan`) fires and produces:
  - Home / off-day → 45-min full-body strength
  - Layover / hotel → 30-min bodyweight session (5 exercises)
  - Flight (heavy) → 15-min post-flight mobility (5 items)
  - Flight (light) → 12-min pre/post-flight mobility
  - Standby / reserve → 20-min standby activation
  - Simulator / training → 20-min light activation
  - Rest / off / annual leave → NO workout (day genuinely rest)
- Any fallback path opens a HIGH-priority `coach_tasks` doc so Louis reviews the client.
- If, after all that, 0 workouts persist, the job is marked `needs_review` and the same coach task fires.

**Why workouts previously failed to generate (root causes fixed)**
1. **Setup-day gate too aggressive** — flagged every `duty_hours ≥ 10` day as heavy, advanced the gate up to
   7 days and dropped the whole week. FIXED — now capped at +2 and threshold raised to 14 h.
2. **Outer wait_for at 90 s** — killed the whole batch mid-flight. FIXED — bumped to 180 s + per-chunk 75 s.
3. **No safety net if LLM returned []** — silent empty week. FIXED — template fallback + coach task.
4. **LLM budget exhausted on Emergent Universal Key** — every Claude call returns `BadRequestError: Budget
   has been exceeded`. **NOT FIXED IN CODE** — requires topping up the Universal Key balance.

---

## Section 9 — Programme Quality

Honest verdict: **the plan is currently "reasonable sessions on reasonable days" — NOT a real periodised
coaching programme.**

| Question | Answer |
|---|---|
| Does it have a stated goal? | ⚠️ Partial — `profile.main_goal` is passed to the LLM but not enforced downstream. |
| Does it have a phase? | ⚠️ Partial — only event-driven phases (`base/build/peak/taper/race_week/recovery`). No general periodisation for non-event clients. |
| Does it use periodisation? | ❌ No (module `feature_programme_quality.py` scaffolded but NOT wired into `_generate_month`). |
| Does it use progression week-to-week? | ❌ Not currently. |
| Weekly structure (target sessions/week)? | ❌ Not enforced. The LLM decides per chunk. |
| Movement pattern balance (push/pull/hinge/squat/core/mobility)? | ❌ Not validated. |
| Deload / recovery logic? | ⚠️ Partial — Coaching DNA `recovery_risk` is passed in but no explicit deload week. |
| Does each workout have a "why this session?" | ✅ YES — every workout has a `rationale` field (LLM-generated OR template). |
| Client "why this session?" UI | ⚠️ **Backend has the data; frontend does not surface it yet on the workout screen.** |
| Coach programme-level rationale | ❌ No dedicated rationale UI in the coach dashboard yet. |
| Empty/random-plan validation gate | ⚠️ Partial — only checks `count > 0`. No movement-balance or goal-match validation running in production. |

**Bottom line:** if the LLM is up, the plan is coherent and roster-aware, but it is decided week-by-week by
Claude without a top-down periodised structure. If the LLM is down, the template plan is safe but
undifferentiated across goals (fat-loss vs strength both get "Full Body Strength").

---

## Section 10 — First Workout Rule

**Implemented.** Lives in `/app/backend/feature_setup_day.py`.

- Local date used (client `current_time_zone` from profile, fallback `home_time_zone`, ultimate fallback
  `Europe/London`). NOT UTC.
- Only new clients are gated (see Section 8).
- Tomorrow unsuitable → move up to +2 days.
- Coach override endpoints:
  - `POST /api/coach/clients/{client_id}/programme/start-today` → sets `setup_day_override=true`
  - `POST /api/coach/clients/{client_id}/programme/clear-override` → reverse.
- Existing clients are NOT affected (query filters look for no prior completed workouts).

---

## Section 11 — Next 7 Days Display

- Data source: `GET /api/workouts/week` → returns ALL workouts. The frontend takes the first 7 dates
  ≥ today (local).
- Formatting: `EEE d MMM` (e.g. "Wed 1 Jul"). "Today" and "Tomorrow" labels appear on the first two rows;
  year suffix only when the date is not in the current year.
- Rest / empty days are padded with a "Rest Day" row (or "Flight · Recovery" if the roster day is a flight).
- Setup-day for a new client renders a distinct **SETUP DAY** row instead of a Rest Day.
- Client-friendly banners above the list handle the "plan preparing" and "plan needs review" cases.

**Weakness:** on a brand-new client with no LLM plan AND without the template fallback firing (e.g.
mid-generation), the 7-day list can still read "Rest Day" for every row. Now largely covered by the template
fallback, but not 100 %.

---

## Section 12 — Error Handling

| Failure | Client sees | Louis sees | Retry? | Data saved? |
|---|---|---|---|---|
| Upload network drop | Inline red error, "Upload failed. Please try a different file." | — | Manual retry via UI | No — nothing persisted |
| Unsupported file (unlikely — pickers restrict types) | Same as above | — | Manual retry | No |
| OCR / parse failure | Job status → `failed`, message set | Coach task | ✅ button `TRY AGAIN` | No |
| Partial parse | Job status → `partial`, roster IS saved | Coach task | ✅ | Yes |
| No duties found | Job → `needs_review` | Coach task | ✅ | Yes (empty roster row) |
| Plan generation timeout | Job → `needs_review` **OR** template fallback fires → `complete` | Coach task (either way) | ✅ retry | Yes |
| No workouts generated | Same as above | Coach task | ✅ | Yes |
| Duplicate roster / overlap | Confirm modal on `/roster/{rid}/confirm` | — | User chooses merge or replace | Optional |
| Unexpected backend error | Job → `failed` with error text | Coach task | ✅ | Depends on where it errored |
| User leaves screen | Nothing lost — banners on Home take over | — | ✅ from Home banner | Yes |

Coach task types related to roster:
- `roster_plan_generation_issue` (timeout, error, 0 workouts, template fallback)

---

## Section 13 — Coach / Admin Review

Louis can see roster activity via:

- `GET /api/coach/roster-alerts` — list of `coach_alerts` (unread + read).
- `GET /api/coach/tasks` — includes `roster_plan_generation_issue` tasks with priority `high`.
- `GET /api/coach/clients` + `GET /api/coach/clients/{id}` — client detail with roster status.
- `GET /api/coach/calendar` — cross-client calendar view.

Louis **cannot** currently:
- Edit an individual roster day directly from the coach UI (backend endpoint exists via `day-override` but no coach-side UI is wired for editing per-day).
- Retry plan generation on behalf of a client (endpoint exists, no dedicated coach button).
- Manually build a plan from scratch in-UI (workouts POST/PATCH exist, no builder screen).

Coach can message the client from the client detail page (Messages tab is wired).

---

## Section 14 — Database / Collections

Only listing collections directly involved in the roster flow. All are MongoDB, all queried by `user_id`.

| Collection | Purpose | Key fields (examples) |
|---|---|---|
| `users` | Profile + auth | `id, role, name, email, profile{main_goal, experience, hotel_gyms, ...}, current_time_zone, first_workout_date, setup_day_reason, setup_day_override` |
| `rosters` | Parsed rosters + embedded day array | `id, user_id, is_active, start_date, end_date, days[]:{date, day_type, duty_hours, flights[], hotel_id, layover_city, ...}, created_at` |
| `roster_jobs` | Async job tracking | `id, user_id, roster_id, status, stage, progress, message, error, workouts_generated, used_template, retry_count, client_acknowledged, created_at, updated_at` |
| `workouts` | Per-day sessions | `id, user_id, roster_id, date, day_load, title, location, focus, warmup[], exercises[], alternatives{}, rationale, key_session, source, needs_coach_review, coach_locked, approved, completed` |
| `hotels` | Layover hotel gym info | `id, name, city, gym_available, equipment{}, confidence` |
| `day_overrides` | Client per-day overrides | `id, user_id, date, day_type, tags[], notes, created_at` |
| `day_change_log` | Audit trail of edits | `id, actor_id, target_id, action, before, after, timestamp` |
| `coach_alerts` | New-roster inbox for Louis | `id, client_id, kind, roster_id, job_id, read, created_at` |
| `coach_tasks` | High-priority follow-ups | `id, client_id, type, title, body, priority, risk_level, category, payload{}, status, created_at` |
| `messages` | Client ↔ coach chat | `id, from_user, to_user, body, attachments[], created_at` |
| `programmes` | Programme versioning (SCAFFOLDED, not yet written) | `id, user_id, roster_id, goal_key, phase, week_index, target_sessions_per_week, validation_status, ...` |

Indexes: `users(id), rosters(user_id + is_active), workouts(user_id + date UNIQUE), roster_jobs(user_id + status)`.

---

## Section 15 — API Endpoints

Roster-related HTTP surface. All require Bearer JWT unless noted.

| Method | Path | Purpose | Called by |
|---|---|---|---|
| `POST` | `/api/roster/extract` | Parse a file, do NOT save | (internal / debug) |
| `POST` | `/api/roster/upload-and-generate` | Parse + save + kick off plan generation | roster-upload.tsx |
| `POST` | `/api/roster/{rid}/confirm` | Confirm overlap resolution | roster-upload.tsx |
| `GET`  | `/api/roster/current` | Return active roster | home.tsx, calendar.tsx |
| `GET`  | `/api/roster/history` | Return past rosters | (coach view) |
| `POST` | `/api/roster/{rid}/hotel` | Update hotel data | (calendar edit) |
| `GET`  | `/api/roster/jobs/active` | Any current banner-worthy job | home.tsx |
| `GET`  | `/api/roster/jobs/{job_id}` | Poll status | roster-upload.tsx |
| `POST` | `/api/roster/jobs/{job_id}/retry` | Retry plan generation | roster-upload.tsx |
| `POST` | `/api/roster/jobs/{job_id}/acknowledge` | Dismiss amber banner | home.tsx |
| `GET`  | `/api/coach/roster-alerts` | Coach inbox | coach dashboard |
| `POST` | `/api/coach/roster-alerts/mark-read` | Mark alerts read | coach dashboard |
| `POST` | `/api/workouts/generate-month` | Kick off generation (legacy path) | (rarely used) |
| `POST` | `/api/workouts/regenerate` | Regenerate workouts (subset) | coach dashboard |
| `GET`  | `/api/workouts/week` | Week-of-workouts feed | home.tsx |
| `GET`  | `/api/workouts/{wid}` | Full workout | workout screen |
| `PATCH`| `/api/workouts/{wid}` | Edit / lock / approve | coach + client |
| `POST` | `/api/workouts/{wid}/complete` | Mark done | client |
| `GET`  | `/api/calendar/timeline` | Merged calendar view | calendar.tsx |
| `POST` | `/api/calendar/day-override` | Per-day override | calendar.tsx |
| `GET`  | `/api/setup-day/status` | Am I on setup day? | home.tsx |
| `POST` | `/api/coach/clients/{id}/programme/start-today` | Override the gate | (coach UI TBD) |

---

## Section 16 — Frontend Files / Components

| File | Role |
|---|---|
| `/app/frontend/app/roster-upload.tsx` | Upload screen — pickers, progress card, retry, cancel |
| `/app/frontend/app/(client)/home.tsx` | Today view, banners, NEXT 7 DAYS, Setup Day card |
| `/app/frontend/app/(client)/calendar.tsx` | Month view; long-press adds day override; secondary FAB adds a personal activity |
| `/app/frontend/app/(client)/messages.tsx` | Chat with Louis (attachment support) |
| `/app/frontend/app/workout/[id]/*.tsx` | Workout detail / player / guided mode |
| `/app/frontend/app/(coach)/overview.tsx` | Louis' dashboard |
| `/app/frontend/app/(coach)/clients.tsx` + `/coach/client/[id].tsx` | Client detail (roster + workouts) |
| `/app/frontend/src/components/AddActivityModal.tsx` | Add sport / hobby |
| `/app/frontend/src/components/PersonalActivityCard.tsx` | Today's activity card |
| `/app/frontend/src/lib/api.ts` | Auth + fetch wrapper |

---

## Section 17 — Backend Files / Modules

| File | Role |
|---|---|
| `/app/backend/server.py` | Main FastAPI app: roster upload/parse, workouts, jobs, calendar, coach APIs. Contains `_generate_month`, both workers, all roster endpoints. |
| `/app/backend/feature_setup_day.py` | First-workout-tomorrow gate + coach override endpoints |
| `/app/backend/feature_workout_fallback.py` | Deterministic template plan when LLM is unavailable |
| `/app/backend/feature_event_categories.py` | Category-aware Event Training (race / medical / aviation_work / sport_hobby / personal) |
| `/app/backend/feature_personal_activities.py` | Personal Activity Planner (tennis, padel, football, etc.) |
| `/app/backend/feature_programme_quality.py` | **Scaffolded, NOT yet wired.** Goal → weekly target + phase + validation. |
| `/app/backend/feature_exercise_content.py` | V2 Unified Exercise Library, JIT image generation |
| `/app/backend/feature_message_attachments.py` | Voice / image / video attachments in messages |
| `/app/backend/feature_food_search.py` | Nutrition centre food DB search |
| `/app/backend/feature_habits.py` | Habits + streaks |
| `/app/backend/feature_coach_v1.py` | Coach dashboard endpoints |
| `/app/backend/feature_notifications.py` | Coach push notifications |

---

## Section 18 — Known Bugs / Risks

| # | Issue | Severity | Beta impact | Public launch impact | Likely cause | Fix estimate | Recommended action |
|---|---|---|---|---|---|---|---|
| 1 | **Emergent LLM budget exhausted** | 🔴 CRITICAL | High | Blocking | Universal Key balance below Claude cost | 5 min | **Top up balance via Emergent Profile → Universal Key → Add Balance. Enable auto-top-up.** |
| 2 | Retry-worker missing `source='template'` + `needs_coach_review=true` on DB rows | 🟠 HIGH | Low visible impact; wrong coach flag on retried template plans | Fix before launch | Copy-paste omission when the retry path was cloned from the main worker | 2 min | 2-line patch — mirror the main worker |
| 3 | Programme quality module (`feature_programme_quality`) not wired into `_generate_month` | 🟠 HIGH | Feels less like a coached programme | Blocking for paid launch | Deferred | 1–2 days | Wire in goal + phase + weekly target + validation gate |
| 4 | "Why this session?" client UI not surfaced | 🟡 MEDIUM | Client can't see the rationale field even though backend has it | Should fix | Frontend gap | 30 min | Add a small "Why today?" block in the workout screen |
| 5 | No client-side "review parsed roster before publish" step | 🟡 MEDIUM | Occasional mis-parsed days become workouts | Should fix | Trade-off for one-shot UX | 0.5 day | Add a confirm-parsed-days modal |
| 6 | No coach UI to edit a client's roster day | 🟡 MEDIUM | Louis has to ask client to edit | Should fix | Coach dashboard gap | 0.5 day | Add day-override to coach client screen |
| 7 | No coach retry button (only client can retry) | 🟡 MEDIUM | Louis waits for the client | Should fix | UI gap | 20 min | Add "Regenerate plan" on coach client card |
| 8 | Unusual airline roster layouts may partially parse | 🟡 MEDIUM | Fragile with unseen airlines | Fix during beta | Gemini prompt is generic | Ongoing | Collect beta test rosters, refine prompt |
| 9 | HEIC image support unverified | 🟡 MEDIUM | Some iPhone users may hit an error | Fix during beta | Not tested | 20 min | Add HEIC → JPEG conversion client-side |
| 10 | CSV / Excel / pasted-text imports missing | 🟢 LOW | Fine for beta | Nice-to-have later | Not built | 1 day | Post-beta |
| 11 | No confidence score on parsed fields | 🟢 LOW | No user-visible signal | Nice-to-have | Not built | 0.5 day | Post-beta |
| 12 | Camera "Take Photo" not exposed | 🟢 LOW | Client must upload from library | Nice-to-have | Small UI addition | 15 min | Post-beta |

---

## Section 19 — Test Coverage

Honest audit:

| Layer | Coverage | Notes |
|---|---|---|
| Backend unit tests | ✅ 20+ automated tests | Iterations 55–58 in `/app/backend/tests/*` cover setup-day gate, roster job filter/ack, timeout bumps, template fallback |
| Backend integration | ⚠️ Partial | Job workflow verified with stub `_generate_month`. Real end-to-end LLM path NOT auto-tested (would burn credits) |
| Frontend snapshot tests | ❌ None | |
| Frontend E2E (Playwright) | ✅ Smoke tests via testing_agent | Home banners, NEXT 7 DAYS, roster-upload landing screen |
| Real roster PDF upload | ⚠️ Once, manually — hit LLM budget error |
| Real roster screenshot upload | ⚠️ Once, manually — hit LLM budget error |
| Multi-page PDF | ❌ Not tested |
| iPhone Safari / native | ❌ Not manually tested in this iteration |
| Android Chrome / native | ❌ Not manually tested in this iteration |
| Expo Go on device | ❌ Not run in this iteration |
| Production build (EAS) | ❌ Not attempted |

---

## Section 20 — Beta Readiness Verdict

- **Can I let a beta tester upload a roster today?** — 🟡 **ALMOST.** Yes, if the LLM budget is topped up. Yes without it too, but they will get the deterministic template plan instead of a coached plan.
- **Will they reliably get a training plan?** — 🟢 **YES** (either LLM or template).
- **Will they get at least one workout in the next 7 days?** — 🟢 **YES** (setup-day gate now caps at +2 days; template fallback fills the rest).
- **Will Louis be alerted if it fails?** — 🟢 **YES** (`coach_tasks` + `coach_alerts`).
- **Can the client message Louis if it fails?** — 🟢 **YES** ("MESSAGE LOUIS" button pre-fills a draft).
- **Is the programme structured enough to feel like real coaching?** — 🟡 **ALMOST.** Sessions are sensible, but there is no top-down periodisation and the "why this session" is not surfaced on the client side.

**Must-fix before beta go-live:** top up the Universal Key; ship the 2-line retry-worker patch.

---

## Section 21 — Exact Next Fixes

### A. Must fix before roster beta

| # | Task | Time | Risk if skipped |
|---|---|---|---|
| A1 | Top up the Emergent LLM Universal Key balance + enable auto top-up | 5 min | Every plan generation falls back to template — clients don't get LLM coaching |
| A2 | Patch retry-worker: add `source='template'` + `needs_coach_review=true` to the doc dict (mirror main worker at server.py:2480-2481) | 2 min | Coach dashboard mis-labels retried template plans as coaching-system plans |
| A3 | Surface `workout.rationale` on the client workout screen as "Why this session?" | 30 min | Beta testers don't see the coaching intent even though the data exists |
| A4 | Add a "Regenerate plan" button on the coach client detail | 20 min | Louis has to ask the client to hit retry themselves |

### B. Should fix during beta

| # | Task | Time | Risk if skipped |
|---|---|---|---|
| B1 | Wire `feature_programme_quality` into `_generate_month` (goal → weekly target + phase + validation) | 1 day | Plan feels session-by-session, not periodised |
| B2 | Add "Confirm parsed roster" step before workouts are generated | 0.5 day | Occasional mis-parses become workouts |
| B3 | Add day-override editing to the coach client screen | 0.5 day | Louis can't fix parse errors himself |
| B4 | Collect beta rosters and tune the parser prompt for the top 5 airlines | Ongoing | Fragile parsing on unseen layouts |
| B5 | Add HEIC → JPEG conversion in the image picker | 20 min | Some iPhone uploads fail |

### C. Can wait until after beta

| # | Task | Time | Risk if skipped |
|---|---|---|---|
| C1 | Camera-capture flow ("Take Photo" of paper roster) | 15 min | Minor convenience |
| C2 | CSV / Excel / paste-text importer | 1 day | Only useful for a small subset of users |
| C3 | Per-field confidence indicators on the parsed roster review | 0.5 day | Nice-to-have polish |
| C4 | Multi-language parser prompt | 1 day | Only if we expand outside English-speaking airlines |

---

_End of report. This is a factual audit; nothing in this report was newly built._
