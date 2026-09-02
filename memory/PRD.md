# CrewFit V1.5 — PRD

## What it is
Airline-crew fitness coaching mobile app. Client uploads a full month of flight roster; AI extracts every duty and classifies each day into 17 aviation-specific types (Home Day, Turnaround Duty, Layover Arrival/Full/Departure Day, Long-Haul, Night Flight, Early Report, Late Finish, Rest, Recovery, Standby, Sim, Annual Leave, etc.) and colours it Green/Amber/Red (or Blue/Purple/Grey for Duty/Layover/Unknown). AI then generates a location-aware, equipment-aware monthly training plan a coach can lock/edit before the client trains.

## Core promise
**"Turn a full aviation roster into a smart monthly training plan that respects fatigue, location, and available equipment — and a coach controls."**

## V1.5 Phase A feature set (this iteration)
### Client
- Extended onboarding: home equipment picklist (20 items) + training location + max home minutes + preferred days + goal + injuries + cardio equipment + will_run_outside + level + body & targets.
- Roster upload (PDF/image/screenshot) → **full-month Gemini 2.5 Flash extraction** (17 day types, confidence scores, home/away, report/finish times, flights, layover_city/nights, hotel).
- **Roster confirm** — per-day editable card (day type / load / flights) + hotel section for every layover with community-DB lookup + equipment checklist.
- **Roster expiry tracking** — Home hero shows a Roster Remaining card and a warning banner at ≤7 / ≤3 / expired. Historical rosters are never overwritten.
- **Monthly Calendar** — month grid, week list, day drill-down. Colour tags: green/amber/red/blue/purple/grey. Click day → regenerate this day. Sticky "Regenerate Month" bar.
- **AI Monthly Plan** — via Claude Sonnet 4.5, chunked into concurrent 7-day windows and dispatched as a background job (`POST /workouts/generate-month` returns instantly with `job_id`; client polls). Each workout carries: location, duration, focus, warm-up steps, exercises (sets/reps/rest/RPE/notes), alternatives (home/hotel/no-equipment/easier/harder), and a plain-English rationale.
- Aviation coaching rules baked into the AI prompt: no heavy legs within 24h of long-haul arrival; layover arrival = mobility/walk only; layover full day = strongest training opportunity; 3+ consecutive duty days = reduce load; no exercise the client has no equipment for; if hotel gym unknown → bodyweight only.
- Workout detail: shows location & warm-up & AI rationale & alternatives; complete with RPE; coach lock protects a workout from AI regeneration.
- V1 features retained: nutrition tracker with meal-photo AI feedback, weekly check-ins, progress photos + weight, messaging.

### Coach
- Dashboard: 4 widgets (Active / Expiring / Expired / No Roster) + 8 filter chips (all, expiring_soon, expired, no_roster, needs_confirmation, pending_approval, red_days, missed).
- Client list — enriched with `latest_roster`, `roster_expiry`, `pending_approvals`, `red_days`, `missed_workouts` and a colour-coded 14-day roster strip.
- Client detail — roster (with expiry), full workout list, latest check-in, full roster history.
- Workout builder & edit — cycle day-load, edit title/exercises/warm-up, coach notes, approve / reject, lock/unlock.
- Exercise library — CRUD with full V1.5 metadata (movement pattern, muscle group, home_ok, hotel_ok, bodyweight_ok, level, joint scores, fatigue cost, pre/post-flight).

### Community Hotel DB
- `POST /hotels` upserts by (name, city); `submissions` count + `confidence` grow each time the same hotel is confirmed. Two hotels seeded (Marina Bay Sands, Sofitel LAX).
- `POST /roster/{id}/hotel` attaches a hotel to a specific layover date.

### Push notifications
- `POST /register-push` (non-blocking) + `send_push()` helper wired for Emergent-managed push. `EMERGENT_PUSH_KEY=placeholder` in `.env` — real key is injected by the Emergent Publish/deploy pipeline. Works on real device builds only.

## Test status
- 42/42 backend pytest tests green (iteration_4).
- All 3 previously-failing tests (`register-push`, exercises seed, generate-month timeout) fixed.

## Stack
- Frontend: Expo SDK 54, Expo Router, expo-image, expo-image-picker, expo-document-picker, expo-notifications.
- Backend: FastAPI + Motor (MongoDB), JWT auth, bcrypt, httpx.
- LLM: emergentintegrations — Claude Sonnet 4.5 (workouts) + Gemini 2.5 Flash (roster + meal photo).

## Iter190 — Coach Video MP4 Compatibility
- Added `imageio-ffmpeg` to backend dependencies (ships a static ffmpeg binary; no system packages required).
- `_save_coach_video` now transcodes WebM uploads to H.264/AAC MP4 (+faststart) before storage; QuickTime .mov is passed through unchanged; hard-fallback to raw WebM only if ffmpeg errors.
- `GET /coach/videos/{id}/file` now emits `Accept-Ranges: bytes` and honours `Range: bytes=start-end` (single-range, incl. suffix ranges) with proper 206/416 responses so native iOS/Android <video> players can seek/stream.
- Migration script `/app/backend/scripts/migrate_coach_videos_webm_to_mp4.py` retro-actively converts existing WebM videos in R2 to MP4, preserves the WebM originals under `legacy_webm_key`, and stamps `migrated_to_mp4_at` for idempotent re-runs. Supports `--dry-run` and `--limit N`.

## Iter200-b — Parser tightening + Review Roster card redesign
- **Backend / roster_normalizer.py**:
  • Second-pass `_dedupe` runs AFTER classification (not just before) — collapses same-date twins where the LLM emitted both a turnaround AND a layover_arrival row.
  • Dedupe now prefers rows that already resolved to a real duty type over bare `layover` rows.
  • Blank days with no destination city and no pairing evidence → `rest_day` (not `needs_review`, not fictional layover).
  • Early-morning-departure rule: any first sector departing 00:00–05:00 with <8h ground time at the outstation → both outbound AND return legs downgraded to `night_flight`.
  • Customer labels rewritten to user's spec: plain type names only (`Night flight`, `Layover — Karachi`, `Rest day`, `Standby 06:00–14:00`, `Flying day — AUH → DXB`). Never parser jargon. Never "Layover in None".
- **Frontend / roster/confirm/[id].tsx**:
  • Day card redesigned: 40px icon on the LEFT + label + report/off times to the right, single traffic-light dot on the far right.
  • `_dayTypeIcon()` maps every internal type to a single Ionicon: night_flight→moon, turnaround/flight→airplane, layover→bed, rest_day→sunny, standby→time, sim→school, annual_leave→briefcase, sickness→medkit.
  • Report time now shown PROMINENTLY on every card that has one.
  • Debug tokens expanded (added "blank column", "layover inference").
  • Equipment pill continues to gate on confirmed layover with resolved city only.
- **New tests**: `test_second_pass_dedupe_collapses_turnaround_plus_layover_arrival`, `test_early_morning_departure_below_8h_is_night_flight`, `test_customer_labels_are_plain_human`. All 17 normalizer tests + 32 legacy tests green.


  • Night flights crossing midnight → now `night_flight`, not layover.
  • OFF/rest days from source → preserved (no fictional layovers).
  • Home-based standby → equipment `any` (was leaking `hotel_or_bodyweight`).
  • "Layover in None" → downgraded to `needs_review`.
  • Month-boundary look-ahead → clipped.
  • Duplicate-date rows → collapsed (richest wins).
  • Multi-base airlines (BA LHR+LGW, EK DXB) via fresh-duty-start heuristic.
- Wired into `roster_upload_and_generate` + legacy `roster_extract` endpoints.
- Frontend Review Roster:
  • Customer labels: "Night flight — X → Y", "Layover in CMB", "Day off", "Standby 06:00–14:00" — never raw types.
  • Removed QUICK_CHIPS row from default day card (moved corrections into Edit modal).
  • Moved SWAP button from default card into Edit modal.
  • Equipment pill "Hotel / bodyweight" now only shows for confirmed layovers with a resolved city.
  • Simplified overlap panel copy: "REPLACE EXISTING ROSTER" / "UPDATE CHANGED DAYS" / "KEEP BOTH FOR COACH REVIEW".
  • Top summary copy: "🟢 X great · 🟠 Y lighter · 🔴 Z recovery-focused".
  • Debug notes hidden from customer view (whitelist filter in _isDebugNote).
- 14 new regression tests in `tests/test_roster_normalizer.py` covering all 12 acceptance cases (same-day / overnight turnaround / genuine layover / multi-day / OFF preservation / standby / month boundary / dedupe / cross-airline).
- Real acceptance run: `scripts/acceptance_september_etihad.py` produces side-by-side old-vs-new for the Sept PDF.
- Future uploads only — no DB reprocessing of historical rosters.

## Iter200 — Home pill takeover + notification deep-link fix (2026-06)
- **Weekly video notification deep-link**: `notify_weekly_video_ready` now sets
  `action_url = "/video/{video_id}"` when a video_id is supplied, and
  `"/(client)/home"` as fallback. Previously pointed to `/(client)/videos`
  which did not resolve to the correct in-app player route.
- **Home pill takeover**: `GET /api/videos/welcome-for-me` now returns
  whichever video belongs in the client home pill:
  1. Latest weekly / check-in video (`video_kind=weekly`, `status ∈ {sent, viewed}`)
     — no grace cutoff, persistent pill.
  2. Otherwise, the welcome video with the pre-existing 24 h grace rule.
  3. Otherwise `{"video": null}` and the banner hides.
  Once the coach sends the first check-in video the welcome video is no
  longer surfaced from this endpoint — it is permanently taken over by
  the latest check-in, and every subsequent check-in replaces the
  previous one in the same pill.
- Frontend `WelcomeVideoBanner` reworked to render check-in copy
  (`NEW · CHECK-IN VIDEO` / `LATEST CHECK-IN`) when `video_kind === "weekly"`
  and preserve welcome-video copy otherwise.
- 7 backend regression tests (`tests/test_iter200_welcome_pill_and_notification_url.py`) — all pass.

## Explicitly deferred (Phase B & V2)
Drag-and-drop calendar, web-lookup hotel gym fallback, live Apple Health / Garmin / Strava / Oura sync, MyFitnessPal, barcode scanner, payments, community, coach desktop layout, advanced analytics, multi-coach, corporate dashboard, referrals, real push delivery testing (requires deploy).

## Business enhancement idea
**"Layover Coach"** premium — when arriving at a Layover Arrival Day, auto-generate a hotel-room 20-min mobility+strength session tailored to the destination hotel's actual equipment (pulled from the community DB) and surface it as a push notification the moment the client's flight lands. Adds subscription retention at the exact jet-lagged moment users need the app most.
