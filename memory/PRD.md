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

## Explicitly deferred (Phase B & V2)
Drag-and-drop calendar, web-lookup hotel gym fallback, live Apple Health / Garmin / Strava / Oura sync, MyFitnessPal, barcode scanner, payments, community, coach desktop layout, advanced analytics, multi-coach, corporate dashboard, referrals, real push delivery testing (requires deploy).

## Business enhancement idea
**"Layover Coach"** premium — when arriving at a Layover Arrival Day, auto-generate a hotel-room 20-min mobility+strength session tailored to the destination hotel's actual equipment (pulled from the community DB) and surface it as a push notification the moment the client's flight lands. Adds subscription retention at the exact jet-lagged moment users need the app most.
