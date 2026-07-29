#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

# THIS SECTION CONTAINS CRITICAL TESTING INSTRUCTIONS FOR BOTH AGENTS
# BOTH MAIN_AGENT AND TESTING_AGENT MUST PRESERVE THIS ENTIRE BLOCK

# Communication Protocol:
# If the `testing_agent` is available, main agent should delegate all testing tasks to it.
#
# You have access to a file called `test_result.md`. This file contains the complete testing state
# and history, and is the primary means of communication between main and the testing agent.
#
# Main and testing agents must follow this exact format to maintain testing data. 
# The testing data must be entered in yaml format Below is the data structure:
# 
## user_problem_statement: {problem_statement}
## backend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.py"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## frontend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.js"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## metadata:
##   created_by: "main_agent"
##   version: "1.0"
##   test_sequence: 0
##   run_ui: false
##
## test_plan:
##   current_focus:
##     - "Task name 1"
##     - "Task name 2"
##   stuck_tasks:
##     - "Task name with persistent issues"
##   test_all: false
##   test_priority: "high_first"  # or "sequential" or "stuck_first"
##
## agent_communication:
##     -agent: "main"  # or "testing" or "user"
##     -message: "Communication message between agents"

# Protocol Guidelines for Main agent
#
# 1. Update Test Result File Before Testing:
#    - Main agent must always update the `test_result.md` file before calling the testing agent
#    - Add implementation details to the status_history
#    - Set `needs_retesting` to true for tasks that need testing
#    - Update the `test_plan` section to guide testing priorities
#    - Add a message to `agent_communication` explaining what you've done
#
# 2. Incorporate User Feedback:
#    - When a user provides feedback that something is or isn't working, add this information to the relevant task's status_history
#    - Update the working status based on user feedback
#    - If a user reports an issue with a task that was marked as working, increment the stuck_count
#    - Whenever user reports issue in the app, if we have testing agent and task_result.md file so find the appropriate task for that and append in status_history of that task to contain the user concern and problem as well 
#
# 3. Track Stuck Tasks:
#    - Monitor which tasks have high stuck_count values or where you are fixing same issue again and again, analyze that when you read task_result.md
#    - For persistent issues, use websearch tool to find solutions
#    - Pay special attention to tasks in the stuck_tasks list
#    - When you fix an issue with a stuck task, don't reset the stuck_count until the testing agent confirms it's working
#
# 4. Provide Context to Testing Agent:
#    - When calling the testing agent, provide clear instructions about:
#      - Which tasks need testing (reference the test_plan)
#      - Any authentication details or configuration needed
#      - Specific test scenarios to focus on
#      - Any known issues or edge cases to verify
#
# 5. Call the testing agent with specific instructions referring to test_result.md
#
# IMPORTANT: Main agent must ALWAYS update test_result.md BEFORE calling the testing agent, as it relies on this file to understand what to test next.

#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================



#====================================================================================================
# Testing Data - Main Agent and testing sub agent both should log testing data below this section
#====================================================================================================

user_problem_statement: "Build a dedicated Coach Web Dashboard (Option C) for CrewFit — desktop-native routes inside the current Expo app that render a sidebar layout on wide screens (>=1024px web) with Overview, Clients, Calendar, Approvals, Library, Messages, Analytics and Profile."

backend:
  - task: "Media storage abstraction (S3/R2) + ops endpoints"
    implemented: true
    working: true
    file: "backend/storage.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "New /app/backend/storage.py exposes a single `storage` singleton with two drivers: DiskDriver (default, matches today's on-disk behaviour) and R2Driver (Cloudflare R2 via boto3 s3v4). Driver is auto-selected at import time based on R2_ACCOUNT_ID + R2_ACCESS_KEY_ID + R2_SECRET_ACCESS_KEY + R2_BUCKET env vars. Optional R2_PUBLIC_HOSTNAME uses your CNAME for direct public URLs (else presigned). New feature_admin_migrations.py exposes admin-only ops routes: GET /admin/storage/status, POST /admin/storage/backfill?dry_run=true (walks /app/backend/uploads, idempotent, skips files already in R2). feature_nutrition_photo.py refactored to write through storage.storage.write_bytes(); its GET /photo/{id}/image endpoint now issues a 302 to a 10-min signed URL when R2 is live and continues serving FileResponse locally otherwise — zero client changes required. Verified live: storage/status → {'driver':'disk','is_cloud':false}. Backfill correctly reports 'no cloud driver configured' when idle. Ready to activate: paste R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_BUCKET in backend/.env, restart, then POST /admin/storage/backfill?dry_run=false to move existing media."

  - task: "Exercise Library data migration (v1 → exercise_content)"
    implemented: true
    working: true
    file: "backend/feature_admin_migrations.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "One-shot idempotent migrator: POST /admin/exercises/migrate?dry_run=[true|false]. Reads legacy `exercises` collection (v1) plus any linked rows from `videos` and upserts into `exercise_content` (v2) with training_type/body_area/category coerced, equipment_type + alternatives normalised to string lists, coaching_points parsed from cues/notes/tips (best-effort), image_url → primary_image_url, video url → primary_video_url. All migrated rows are tagged migrated_from_v1: true and start at status='draft' with approved_*_status='pending' (or 'missing') so the coach can review via the existing Exercise Content UI (Phase 35). Live result: 248 v1 exercises → 248 upserts on first run, 0 inserts + 248 updates on 2nd run (idempotency verified). Sample verified: Goblet Squat/Push-Up/Dumbbell Row all present in exercise_content with migrated_from_v1=true. Companion status endpoint: GET /admin/exercises/migrate/status → {exercises_v1, exercise_content_v2, videos}."

  - task: "Nutrition Centre backend (Phase 5 · Adaptive insights + Coach To-Do)"
    implemented: true
    working: true
    file: "backend/feature_nutrition_insights.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Phase 5 shipped: closes the Nutrition Centre spec. 9 endpoints. (a) Adaptive Weekly Atlas Insights — analyses 14-day rolling window (logs, hydration, protein trend, layover count, photo/barcode usage) and picks ONE of 6 actions (keep / simplify / protein_focus / adjust_calories / add_travel_strategy / flag_coach_review) using Claude Sonnet 4.5 with a deterministic rule-based fallback. Stored in nutrition_insights with dedupe per (user, week_start). (b) Sunday check-in enrichment — GET /nutrition/checkin/questions returns 5-7 goal-personalised nutrition questions the frontend appends to /checkins/questions. (c) Coach To-Do integration — POST /coach/nutrition/scan-todos sweeps all clients, generates insights, and creates dedupe'd coach_tasks with task_type='nutrition_review' whenever coach_review_required=true. Coach approve/dismiss endpoints; approve+applyTargetChange automatically writes a new nutrition_targets row with target_type='coach_from_atlas' and safety floors applied. Verified end-to-end: scan-todos across 23 clients created 22 nutrition_review tasks (client with 0 logs → flag_coach_review action). Endpoints tested manually via curl: /insights/generate, /insights/latest, /insights/mine, /checkin/questions, /coach/insights/pending, /coach/scan-todos, /coach/insights/{id}/approve, /coach/insights/{id}/dismiss."

  - task: "Nutrition Centre backend (Phase 4 · Roster/Airport/Timing/Guide)"
    implemented: true
    working: true
    file: "backend/feature_nutrition_travel.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Phase 4 shipped: travel-guidance Atlas engine. 5 endpoints — POST /nutrition/travel/decision (Atlas Meal Decision from 11 situation types), POST /nutrition/travel/airport (Airport Survival Mode with best/ok/avoid/snack lists), POST /nutrition/travel/timing (time-zone meal timing with meal_plan array + caffeine/hydration/post-flight blocks), POST /nutrition/travel/guide (11 topic library from airport_strategy to hydration_caffeine, goal-personalised via if_goal_is_* fields), GET /nutrition/travel/context (client-side prefill: goal + remaining kcal/protein/hydration). All calls go through Claude Sonnet 4.5 via emergentintegrations with a shared strict-JSON prompt + banned-word sanitizer ('cheat'→'flexible choice', 'diet'→'nutrition', 'failed'→'adjusted'). Per-day cache keyed by (user, intent, params-hash) in nutrition_travel_cache collection prevents repeat API calls. Verified end-to-end: decision(night_flight, sleep_soon) → 'Skip the meal, prioritize rest', do_this + avoid + protein_led_options populated. Airport(DXB) → contextual best/ok/avoid + hydration reminder."

  - task: "Nutrition Centre backend (Phase 3 · AI Photo Meal Scanner)"
    implemented: true
    working: true
    file: "backend/feature_nutrition_photo.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Phase 3 shipped: AI photo meal scanner via Claude Sonnet 4.5 vision through emergentintegrations. Endpoints: POST /nutrition/photo/analyse (base64 JPEG/PNG/WEBP, ≤8MB, mode: meal|hotel_buffet), GET /nutrition/photo/{id}, GET /nutrition/photo/{id}/image (supports Bearer + ?token= for <Image> tags on web), POST /nutrition/photo/{id}/patch (edit macros/items/tip), POST /nutrition/photo/{id}/save-log (writes nutrition_logs w/ source='photo' + photo_scan_id + photo_url, optional save_as_favourite). Strict JSON prompt returns items+macros+confidence+atlas_tip+warnings; response normalised w/ safety clamps (calories ≤3000, protein ≤200g, carbs ≤300g, fats ≤200g). Photos stored on disk under /app/backend/uploads/nutrition/{user_id}/{date}/{scan_id}.{ext}. Fallback estimate returned if vision fails so client always sees a review card. Verified end-to-end w/ a real salmon-poke bowl photo → 9 items detected, 485 kcal / 42g P / 28g C / 22g F, medium confidence, coaching-tone Atlas tip."

  - task: "Nutrition Centre backend (Phase 2 · Barcode)"
    implemented: true
    working: true
    file: "backend/feature_nutrition_barcode.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Phase 2 shipped: barcode + food-DB provider abstraction. Endpoints: GET /nutrition/barcode/lookup?code=..., POST /nutrition/logs/from-barcode (adjusts by servings, optionally saves favourite), GET /nutrition/food/search?q= (OFF free-text). Providers list is ordered Nutritionix (no-op until keys) → Open Food Facts (free, no key). Barcode results cached 30 days in barcode_cache collection (negative results cached 1 day). Manual verification: EAN 5449000000996 → Coca-Cola 139 kcal, 35g carbs, 0g protein/fat, image + brand pulled. New env vars supported: NUTRITIONIX_APP_ID, NUTRITIONIX_APP_KEY, OFF_TIMEOUT_S, OFF_USER_AGENT."

  - task: "Nutrition Centre backend (Phase 1)"
    implemented: true
    working: true
    file: "backend/feature_nutrition.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "New feature_nutrition module with 14 endpoints. Collections: nutrition_logs, nutrition_targets, nutrition_hydration, nutrition_favourites, nutrition_notes, nutrition_atlas_tips. Safety guardrails (min 1500 kcal, min 60g protein, min 1500ml hydration) enforced in _sanitize_target. Atlas defaults auto-computed from user weight when target row missing. Atlas tip cached per (user, date) — Claude Sonnet 4.5 via emergentintegrations. Coach endpoints (require_admin): list clients w/ 7-day averages + flags, per-client deep dive, PATCH targets, POST notes. Note: legacy /nutrition/summary and /nutrition/meals in server.py are UNTOUCHED; new weekly summary lives at /nutrition/week-summary to avoid path collision."

  - task: "GET /api/coach/calendar — per-client roster+workout grid for next N days"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "New endpoint returning {dates, clients:[{client_id, client_name, days:[{date, load, duty_type, workout_id, title, completed, key_session, approved, duration_min, location}]}]} for N days from today. Verified manually via curl - returns 15 clients with populated days array. Requires role=coach."
  - task: "GET /api/coach/analytics — fleet-wide compliance and RPE aggregation"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "New endpoint returning per-client compliance %, avg RPE, key_sessions completed vs scheduled, load distribution, and global aggregates for last N days (default 30). Verified manually via curl - returns 15 clients + load_distribution. Requires role=coach."

frontend:
  - task: "Guided Flow — Autopilot / Flow Mode (hands-free class experience)"
    implemented: true
    working: "NA"
    file: "frontend/app/workout/[id]/guided.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "New Iter 95i. At the top of Guided Flow, a StartModeSheet asks the client 'How do you want to run today's session?' with two options: (a) Track my lifts (existing tap-COMPLETE-SET flow) or (b) Just flow (autopilot). In autopilot: each work set becomes a timer (~3s/rep, clamped 20-90s for strength; explicit duration_sec/work_sec honoured for cardio/timed), 3-2-1 beeps at the tail, then auto-log with target reps and auto-slide into RestTimer with autoContinueOverride forced true. The work UI hides the log inputs & COMPLETE SET button and shows a big MM:SS numeral + progress bar. Warm-up flow untouched. autoRest and autoCont are both forced true in autopilot. Set logs still POST to /workouts/{id}/sets so history stays intact (autopilot flag + actual_reps=target). Voice narration + beeps carry through every phase; mic toggle in top bar still works to mute mid-workout. Manual pause via top-bar pause button remains available. If the autopilot log POST fails, the flow still advances so the client isn't stranded mid-workout. Legacy 'log' mode is unchanged."

  - task: "Guided Flow audio: countdown beeps + Louis coach voice narration"
    implemented: true
    working: "NA"
    file: "frontend/app/workout/[id]/guided.tsx, frontend/src/lib/sounds.ts, frontend/src/lib/narration.ts, frontend/src/components/RestTimer.tsx, frontend/src/lib/workoutMode.ts, frontend/src/components/WorkoutSettingsPanel.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "New: (1) sounds.ts now plays native beeps via expo-audio + bundled WAV assets (tick / chime / rest_start / success) in assets/audio/, with the existing Web Audio synth kept as web fallback. Players are created lazily, reused, and audio-mode is configured once (playsInSilentMode=false, mixWithOthers). warmupSoundEngine() pre-warms players on guided-flow mount. (2) narration.ts wraps expo-speech with a Louis coach voice — en-GB on iOS, en-US on Android/web — cancels the previous utterance before speaking a new one, de-dupes any cue that repeats within 800ms, and never throws. Helpers: narrateWorkStart, narrateWarmup, narrateRestStart, narrateRestReady, narrateWorkoutComplete. (3) workoutMode.ts adds `voice` pref (default ON) — surfaced in WorkoutSettingsPanel as 'Coach Voice'. (4) Guided flow now (a) pre-warms audio, (b) speaks 'Set X of Y — Exercise — reps' when a new work set begins, (c) speaks the warm-up move name and plays 3-2-1 beeps in the tail of each warm-up move, (d) speaks 'Rest N seconds, next up …' at rest start and 'Ready, let's go' at rest end (via RestTimer), (e) speaks 'Workout complete, great work' on finish. Voice toggle button (mic / mic-off) added to guided-flow top bar for one-tap mute. stopNarration() runs on unmount. All copy respects the NO-AI rule (no bot/generated/AI wording). Foreground-only for v1 — no background audio session, no lock-screen playback. Untouched: Manual mode. Expo dev-preview: beeps + TTS both work; on real device they will also work in Expo Go (no dev-build required) since we did not enable background playback."

  - task: "Coach Desktop Shell (sidebar + slot) on wide web viewports (>=1024px)"
    implemented: true
    working: "NA"
    file: "frontend/src/desktop/DesktopShell.tsx, frontend/app/(coach)/_layout.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Layout swaps Tabs -> Slot inside DesktopShell when useIsDesktop() returns true. Sidebar has 8 nav items with active-highlight, coach avatar, and sign-out. Screenshots on 1440x900 verified visually working."
  - task: "Coach Overview page — KPIs, alerts, top clients, pending approvals, top performers"
    implemented: true
    working: "NA"
    file: "frontend/app/(coach)/overview.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "6 KPIs (active/expiring/expired/red-days/pending/compliance), attention alerts, clients preview with 14-day mini load bars, pending approvals sidebar (deep-links to /workout/[id]), top-5 compliance leaderboard. Coach lands here on desktop after login; mobile lands on Clients tab (unchanged). Header buttons hidden on narrow screens; twoCol layout stacks below 768px."
  - task: "Coach Calendar page — client × 14 day workout grid"
    implemented: true
    working: "NA"
    file: "frontend/app/(coach)/calendar.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Horizontally scrollable grid: rows = clients, cols = days (7/14/28 selectable). Each cell shows title (or duty_type when no workout), key-session star, completed check, unapproved dot, duration. Today column highlighted. Clicking a workout cell deep-links to /workout/[id]. Verified visually."
  - task: "Coach Analytics page — compliance % + load distribution"
    implemented: true
    working: "NA"
    file: "frontend/app/(coach)/analytics.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "5 KPIs (clients, scheduled, completed, compliance %, avg RPE), per-client compliance bar chart (color-coded by threshold), key-session ratio, and stacked load distribution bar with legend. Range selector for 7/30/90 days. Verified visually."
  - task: "Login redirect: coaches on desktop web -> /overview, on mobile -> /clients"
    implemented: true
    working: "NA"
    file: "frontend/app/(auth)/login.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "useWindowDimensions + Platform.OS==='web' && width>=1024 detects desktop web. Coach lands on overview when desktop, clients tab otherwise. Client behavior unchanged."
  - task: "YouTube 'Watch demo' link on exercises (previous session fix verification)"
    implemented: true
    working: true
    file: "frontend/app/workout/[id]/index.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "VERIFIED via screenshot: 6/6 exercises show 'Watch demo · [channel]' with YouTube icon; opens correct channel-scoped search URL. Channels routed by name (Squat U for squats, Jeff Nippard for pull, etc)."

metadata:
  created_by: "main_agent"

##====================================================================
## §26 — Embedded Exercise Video System (PHASE A: in-app YouTube playback)
##====================================================================

backend:
  - task: "GET /api/exercises/video — single exercise YouTube lookup with in-DB cache"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Scrapes YouTube search HTML (no API key) with channel-hint per exercise category. Picks the highest-ranked candidate that is NOT from embed-blocked channels (e.g. Squat University). Persists to exercise_videos collection keyed by normalized name. Returns {exercise, video:{source, video_id, title, channel, channel_hint, thumbnail_url, approval_status, added_at, search_query}, key, id}. Rejected videos are hidden from clients."
  - task: "POST /api/exercises/videos-batch — bulk lookup + concurrent fetch"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Accepts {exercises:[names]}, returns cached results immediately and concurrently scrapes up to 8 uncached in parallel with a semaphore of 4. Used by the frontend to preload the whole workout's demos on entry."

frontend:
  - task: "ExerciseVideoPlayer component — thumbnail + in-app modal with YouTube iframe"
    implemented: true
    working: true
    file: "frontend/src/components/ExerciseVideoPlayer.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Verified visually: thumbnail from YouTube CDN loads; tap opens modal; iframe on web uses https://www.youtube.com/embed/{id}?rel=0&modestbranding=1&playsinline=1 and PLAYS in-app (Athlean-X goblet squat rendered with real player, not 'Video unavailable'). Native: uses react-native-webview 13.15.0 with same URL. Modal has 'Open on YouTube' secondary button. Empty state shows required message: 'Demo coming soon. Follow the written coaching cues.' Includes preloadExerciseVideos() helper to warm the memory cache."
      - working: "NA"
        agent: "main"
        comment: "Requires final regression test after wiring in workout/[id], workout timer, and coach library."
  - task: "Wire video player into workout details, guided timer, and coach library"
    implemented: true
    working: "NA"
    file: "frontend/app/workout/[id]/index.tsx, frontend/app/workout/[id]/timer.tsx, frontend/app/(coach)/library.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Replaced external Linking.openURL YouTube search links with in-app <ExerciseVideoPlayer /> across all three screens. preloadExerciseVideos() called on mount to warm cache. Test IDs: ex-video-{idx} on workout detail; gt-video on timer (work phase); lib-video-{id} on library. Screenshot verified thumbnails render correctly and modal plays actual video."

test_plan:
  current_focus:
    - "GET /api/exercises/video"
    - "POST /api/exercises/videos-batch"
    - "ExerciseVideoPlayer component (thumbnail + modal + fallback)"
    - "Wired video player in workout detail, timer, coach library"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: "§26 Phase A complete. Backend scrapes YouTube search HTML (no API key required) and picks embed-friendly channels (Athlean-X, Jeff Nippard, etc.) — skips known blocked channels like Squat University. Frontend has a reusable <ExerciseVideoPlayer /> component that renders a thumbnail, opens a modal, embeds via https://www.youtube.com/embed/{id} (NOT the nocookie domain; and WITHOUT autoplay=1 which caused 'Video unavailable' errors). Wired into workout detail, guided timer (compact), and coach library. Please test backend endpoints (client + coach roles) and verify (a) thumbnails load, (b) modal opens on tap, (c) iframe actually plays a video (not 'Video unavailable' message), (d) empty-state fallback message appears when no video is found, (e) 'Open on YouTube' still works as a secondary link."

  version: "1.4"
  test_sequence: 8
  run_ui: true

test_plan:
  current_focus:
    - "GET /api/coach/calendar"
    - "GET /api/coach/analytics"
    - "Coach Desktop Shell (sidebar + slot)"
    - "Coach Overview page"
    - "Coach Calendar page"
    - "Coach Analytics page"
    - "Login redirect (coach desktop vs mobile)"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: "Added Coach Web Dashboard (Option C). Two new backend endpoints (/api/coach/calendar and /api/coach/analytics) + three new desktop screens (overview, calendar, analytics) + DesktopShell wrapper. Please test both backend endpoints (auth required: coach@crewfit.com / Coach123!) and the frontend desktop shell at viewport >=1024px on web. Verify sidebar navigation, KPI accuracy on overview, calendar grid clickthrough to /workout/[id], and analytics compliance bars. Mobile experience for coach (viewport 390x844) should still show existing Tabs layout with 5 tabs — please confirm nothing broke on mobile."

##====================================================================
## §26 Phase B — Coach Video CRUD Dashboard
##====================================================================

backend:
  - task: "GET /api/coach/videos — list with search + smart sort"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Returns {items:[{id,key,display_name,category,primary_video_id,primary_channel,primary_thumbnail,has_custom_url,has_custom_upload,variants_configured,preferred_slot,approval_state,last_reviewed_at}], total}. Optional ?search= param. Includes library exercises without records (materialised on demand). Sort: needs-attention first (missing > rejected > un-reviewed), then alphabetical."
  - task: "GET /api/coach/videos/detail?key=... — full record (query-param keyed to handle '/' in keys)"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Uses ?key= query param (not path) because some exercise keys contain '/' (e.g. '90/90 hip rotation'). If no record exists for a library exercise, materialises a stub. 200 returns full doc with all slots + variants."
  - task: "POST /api/coach/videos/upsert — create new exercise video record"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Creates an empty record for arbitrary exercise names."
  - task: "POST /api/coach/videos/slot?key=... — set slot with YouTube URL parsing"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Body: {slot, video_id?, video_url?, title?, channel?, notes?, source?}. Slots: primary|alternative|custom_url|custom_upload|youtube_backup|ai_image. Auto-parses YouTube URLs (youtube.com/watch, youtu.be, shorts, embed, /v/) to extract 11-char video ID. Sets approval_status='approved' by default (coach action). Updates last_reviewed_at."
  - task: "POST /api/coach/videos/approve?key=... — approve/reject a slot"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Body: {slot, status: approved|rejected|auto|pending}. Rejected slots are excluded by _resolve_display_video."
  - task: "POST /api/coach/videos/preferred?key=... — set preferred slot"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Client display resolution honors this preferred slot when the target slot is not rejected."
  - task: "POST /api/coach/videos/variant?key=... — per-location override (home/hotel/gym)"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Body: {variant: home|hotel|gym, video_id?, video_url?, delete?}. Overrides default video when a client resolution passes matching variant."
  - task: "DELETE /api/coach/videos/slot?key=...&slot=... — delete a slot"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Removes slot. If preferred slot was deleted, resets preferred to null."
  - task: "POST /api/coach/videos/rescan?key=... — force re-scrape primary from YouTube"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Re-picks a fresh video ignoring cache. Useful when the current primary is broken or embed-blocked."
  - task: "_resolve_display_video — priority resolver honoring variants + preferred + approval"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Priority: variant override > preferred slot > (custom_upload>custom_url>youtube_backup>primary>alternative>ai_image). Excludes rejected slots. Used by GET /exercises/video and POST /exercises/videos-batch (both accept ?variant=home|hotel|gym|default)."

frontend:
  - task: "Coach Videos screen — master/detail layout with 6 slots + 3 variants"
    implemented: true
    working: true
    file: "frontend/app/(coach)/videos.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Verified visually with screenshots. Master panel: search bar, add-exercise button, list of exercises with thumbnails and status dots (MISSING / AUTO / APPROVED / REJECTED), badges for URL/UP/V<n>. Detail panel: header with preferred slot + last-reviewed date + RE-SCAN YOUTUBE button, live preview using <ExerciseVideoPlayer>, 6 slot cards (PRIMARY / CUSTOM URL / CREWFIT UPLOAD (Phase C stub) / ALTERNATIVE / YOUTUBE BACKUP / AI IMAGE (Phase C stub)) with APPROVE / REJECT / MARK PREFERRED / DELETE buttons + PREFERRED badge on the chosen slot. Add-or-replace section: slot chip selector + YouTube URL input + SAVE. Per-location variants section: HOME / HOTEL / GYM with dedicated URL inputs. Add-exercise modal for arbitrary names. Successfully tested: (1) auto-select first item on load, (2) click item with '/' in key ('90/90 hip rotation') loads detail (uses ?key= query param to bypass FastAPI path-slash issue), (3) MARK PREFERRED flips header state from PRIMARY to CUSTOM_URL, (4) status dots + badges render correctly."
  - task: "Sidebar 'Videos' nav item on desktop"
    implemented: true
    working: true
    file: "frontend/src/desktop/DesktopShell.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "Added 'Videos' with videocam-outline icon after 'Library' in sidebar."
  - task: "Route hidden from mobile Tabs (href: null)"
    implemented: true
    working: true
    file: "frontend/app/(coach)/_layout.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "videos route registered with href:null to keep mobile tab bar at 5 items."

guided_flow_v1:
  - task: "Guided Flow Mode (step-by-step player)"
    implemented: true
    working: true
    file: "frontend/app/workout/[id]/guided.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "Built full Guided Flow experience: ModePickerModal (Manual vs Guided with Remember toggle), guided.tsx state machine (warmup → work → rest → complete). Reuses same workout data, same /workouts/{id}/sets logging endpoint, same /exercises/content and /exercises/previous. WarmupPanel with per-move image + timer + cue. WorkPanel with media (Nano Banana image priority), primary cue, LAST TIME + TODAY'S TARGET (from progression_hint), weight/reps/RPE/note inputs, COMPLETE SET button. RestPanel with big countdown, +15s, SKIP, 3-2-1 countdown before advance, auto-continue toggle persisted to AsyncStorage. HowToSheet bottom modal (instructions/cues/mistakes/video). SwapSheet uses existing /exercises/alternatives. WorkoutComplete screen with 4 summary stats + Atlas summary + auto-marks workout complete. Fixed cardio detection regex (was matching 'row' in 'Bent-Over Row'). All 5 test-IDs verified via screenshot flow: mode-picker, warmup, work, rest, next-up card."
  - task: "Batch Atlas image generation (background job)"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "Added POST /api/coach/exercises/batch-generate-images (filter=warmup|missing_image|all|category, force=bool, limit=int) which fires an asyncio.create_task worker that iterates matching exercises, calls Gemini Nano Banana per item with a 1.2s throttle, updates DB, and reports progress. GET /status returns the active or last-finished job doc. POST /cancel marks the job cancelled. Smoke-tested with limit=2 → 2/2 succeeded in ~20s. Kicked off the real warmup batch (217 items) and verified progress at 4/217 with 0 failures after 30s."

test_plan:
  current_focus:
    - "Coach BATCH modal opens, filter selection works, START triggers the job"
    - "Progress polling shows real-time status/succeeded/failed/current_name"
    - "Warmup batch job completes without failures on the majority of items"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

backend_phase3:
  - task: "Cardio interval logging via /workouts/{wid}/sets"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Extended WorkoutSetBody with logging_type, duration_sec, distance_m, pace_sec_per_km, heart_rate_avg, heart_rate_max, calories, warmup. Server auto-computes pace_sec_per_km when duration_sec + distance_m provided but pace is missing. Verified locally: POST with duration_sec=1800, distance_m=5000 → pace=360 sec/km (6:00/km)."
  - task: "Smart progression_hint on /exercises/previous"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Response now includes progression_hint {action: 'increase'|'hold', delta_kg, reason}. Rule: if all last-session sets hit target reps AND RPE<=8 → increase +max(2.5, wt*0.025). If RPE>=9 → hold. Otherwise hold with 'log RPE next time'. Verified with 80kg @ RPE 7 × 2 sets → +2.5kg to 82.5kg with reason 'Hit target reps last time at RPE 7.0 — Atlas is adding +2.5kg.'"

backend_new:
  - task: "Atlas Nano Banana exercise image generation (Louis reference)"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Added POST /api/coach/exercises/{name}/generate-image. Loads /app/backend/assets/louis_ref.png, base64 encodes it, sends to Gemini model gemini-3.1-flash-image-preview with modalities=[image,text] via emergentintegrations LlmChat. Prompt built from exercise name/equipment/pattern/cues with clean-studio style. Saves data-URL to exercise.custom_image_b64, image_source=atlas_nano_banana, image_prompt_summary. Requires coach role. Verified locally with 'Assault Bike Zone 2' → 603KB JPEG returned successfully. Frontend button in /(coach)/exercises editor: 'GENERATE ATLAS IMAGE' (or 'REGENERATE ATLAS IMAGE' when image exists, with confirm alert)."

agent_communication:
  - agent: "main"
    message: "Client Calendar Override Rules Engine implemented. When a client saves a day override via POST /api/calendar/day-override, backend deterministically mutates today's workout: (1) sick/injured or day_type in {sick,injury,rest} or training_preference=rest → REST workout (0 exercises, day_load=green, title='Rest & Recovery'); (2) annual_leave/holiday or day_type in {annual_leave,holiday,family} → OFF workout (grey); (3) poor_sleep/need_rest/high_stress/family_commitment/childcare or training_preference=mobility → 15-min mobility session with 5 stretches; (4) training_preference=reduce or limited_time or availability_min 1-20 → intensity reduction (sets -1, duration ×0.65, load steps down one level); (5) hotel_gym/no_gym/outdoor_run_possible tags → location update only. Response now includes {adjustment: {action, reason, changed, new_title, new_duration, new_day_load, coach_locked}}. Respects coach_locked and completed workouts (no changes). Coach visibility: /api/coach/calendar cells include override_tags/override_notes/override_applied. /api/coach/clients/{id} response now includes overrides[] and change_log[] arrays. Frontend: DayEditModal shows adjustment alert; workout screen shows amber 'PLAN ADJUSTED' banner with reason; coach calendar cells show amber left border + tag badge; coach client detail shows CLIENT DAY EDITS card. Please test rules engine matrix + coach visibility endpoints."
  - agent: "main"
    message: "§26 Phase B complete. Coach video CRUD dashboard delivered as /(coach)/videos screen with sidebar nav. 8 new backend endpoints (list, detail, upsert, slot, approve, preferred, variant, delete, rescan). Detail + mutation endpoints use ?key= query param (not path) because some exercise keys contain '/'. Client-facing GET /exercises/video and POST /exercises/videos-batch now accept ?variant=home|hotel|gym|default and use _resolve_display_video for priority (variant > preferred slot > custom_upload > custom_url > youtube_backup > primary > alternative > ai_image), excluding rejected slots. Please test all 8 backend endpoints (coach role required; client role must get 403 on all coach endpoints) AND the frontend flow (open Videos in sidebar, click item with '/' in key, paste a YouTube URL, mark preferred, set a hotel variant, verify the client's workout screen picks up the change). Phase C (custom uploads via base64) and Phase D (YouTube search via general web search) still pending."

  - agent: "main"
    message: "Lean V1 Coach To-Do Feed + AI Message Drafting + Per-Client Coach Controls + Change Log delivered.\n\nBACKEND additions (server.py):\n1. New collections: message_drafts, coach_change_log.\n2. _create_coach_task extended: new fields message_draft_id, risk_level, category, payload.\n3. POST /messages now background-triggers Atlas draft when a client messages a coach (asyncio.create_task(_bg_generate_message_draft)). Never auto-sends.\n4. Atlas draft prompt (MSG_DRAFT_SYSTEM) uses Claude Sonnet 4.5 via emergentintegrations. Returns STRICT JSON: atlas_draft, risk_level (low/medium/high), risk_reason, action_hint, tone_used, summary. Fallback text used if Atlas fails.\n5. Risk drives task priority: high→urgent, medium→high, low→normal.\n6. New endpoints:\n   - POST /coach/messages/generate         { client_id, source_message_id?, tone_hint?, custom_instruction? } → creates draft + coach_task\n   - POST /coach/messages/{draft_id}/regenerate  { tone, custom_instruction? } (tone: shorter|warmer|clearer|custom) → in-place update, preserves last 5 versions\n   - PATCH /coach/messages/{draft_id}       { coach_edited_text } → save edit\n   - POST /coach/messages/{draft_id}/approve  { coach_edited_text? } → inserts real coach→client message, marks draft sent, resolves coach_task, sends push, logs to coach_change_log\n   - POST /coach/messages/{draft_id}/dismiss → marks dismissed, closes coach_task, logs\n   - GET  /coach/messages/drafts            ?status=&client_id=&limit=\n   - GET  /coach/messages/drafts/{id}       returns draft + full thread\n7. Per-client Coach Controls (persisted on user.coach_controls):\n   - GET  /coach/clients/{id}/controls\n   - PUT  /coach/clients/{id}/controls      { programme_flexibility, progression_speed, injury_caution, video_frequency, auto_approval_risk_threshold }\n   - Defaults: flexible / standard / medium / weekly / none (coach reviews all).\n   - Diff is logged to coach_change_log.\n8. Change log endpoints:\n   - GET /coach/change-log?client_id=&category=&limit=\n   - GET /coach/clients/{id}/change-log\n\nFRONTEND additions:\n1. NEW /app/frontend/app/coach/draft/[id].tsx — full-screen draft review with Editable atlas_draft, SHORTER/WARMER/CLEARER regenerate buttons (Claude round-trip each), DISMISS + APPROVE&SEND actions, risk pill, thread history.\n2. REWROTE /app/frontend/src/components/CoachToDoFeed.tsx — grouped by category (URGENT SAFETY / MESSAGES / REVIEWS / VIDEOS / PROGRAMME / ROSTER / OTHER), risk_level pills (HIGH RISK / REVIEW), message_draft_ready cards route to /coach/draft/[id].\n3. EXTENDED /app/frontend/app/coach/client/[id].tsx — new COACH CONTROLS section (5 controls: programme_flexibility, progression_speed, injury_caution, video_frequency, auto_approval_risk_threshold) with tap-to-save chips + saving indicator; new CHANGE LOG section (client-scoped); added DRAFT REPLY button next to WEEKLY SCRIPT.\n4. NEW /app/frontend/app/(coach)/changelog.tsx — coach-wide Change Log tab with category filters (ALL / MESSAGES / CONTROLS / SCRIPTS / PROGRAMME), grouped by day. Registered in DesktopShell sidebar; hidden from mobile tab bar.\n\nRules:\n- Atlas NEVER auto-sends. Every draft lands as status='waiting_approval' + creates a message_draft_ready coach_task.\n- Auto-approval threshold defaults to 'none' — coach reviews EVERY message (per user's requirement).\n\nPlease test backend endpoints first (draft creation on client-send, regenerate/edit/approve/dismiss, coach controls save+read, change-log listing), then frontend flow: sign in as client@crewfit.com/Client123!, send a message; sign in as coach@crewfit.com/Coach123! → Overview → COACH TO-DO → open MESSAGE DRAFT card → verify edit / warmer / send. Also test client detail → COACH CONTROLS chip toggles + CHANGE LOG entries appearing. Note server.py is now ~7000 lines; refactor still deferred."

  - agent: "main"
    message: "Social Studio V1 shipped (admin-only). 31/31 backend tests pass (iteration_29).\n\nBACKEND — NEW /app/backend/feature_social_studio.py (~500 lines):\n- Added require_admin() dep in server.py: coach acts as admin in dev; role='admin' also accepted.\n- 14 endpoints: /social/generate, /social/posts (CRUD+list), /social/posts/{id}/regenerate (10 tone actions), /approve, /schedule, /mark-posted, /dismiss, /social/analytics, /social/settings GET/PUT, /social/daily/generate, /social/daily/regenerate.\n- Atlas generation via Claude Sonnet 4.5 with SOCIAL_SYSTEM prompt (Louis voice: direct, aviation-specific, no cheesy hype). Deterministic fallback with anchor lines like 'Most pilots don't need a perfect plan. They need one that survives the roster.'\n- 15 CrewFit content pillars, 6 platforms, 10 post types.\n- Status machine: Idea → Draft → Approved → Scheduled → Posted (+ Dismissed / Archived / Failed / Sent to Buffer / Recording Needed / Recorded / Subtitle Review / etc).\n- revision_history[] preserves last 10 versions on regenerate — 'do not delete regenerated versions' rule honoured.\n- Daily task: task_type='daily_social_media_post' created idempotently per date (task per (task_type, payload.for_date)); pillar rotation avoids repeating last 5. Ticker hooked into _tick_reminders_all → _tick_daily_social. Days filter (every/weekdays/custom) respected.\n- On approve/schedule/mark-posted/dismiss, the linked coach_task is auto-resolved (done or dismissed).\n\nFRONTEND — NEW /app/frontend/app/social-studio.tsx (admin-only route):\n- Guard: if user.role not in (admin, coach) → 'Admin only' screen.\n- Header with sparkle icon (generate today's post) + back nav.\n- List of posts with platform tag, status pill, hook + pillar.\n- Detail view with hook / script / caption / hashtags / CTA.\n- 10 tone regenerate buttons (SHORTER / PUNCHIER / PROFESSIONAL / DIRECT / MORE LINKEDIN / MORE TIKTOK / AVIATION EXAMPLES / ADD CTA / REGEN HOOK / REGEN CAPTION).\n- APPROVE / COPY CAPTION / COPY HASHTAGS / DISMISS / SCHEDULE (manual date-time input) — no auto-post per V1 rules.\n- Coach overview gets a new 'SOCIAL' quick-access button.\n- CoachToDoFeed routes daily_social_media_post tasks to /social-studio and labels them 'SOCIAL POST'.\n\nStubs for next session (clean, non-blocking):\n- Recording Studio + Teleprompter — /teleprompter/[id].tsx exists; wire 'Record Video' button and camera capture next.\n- Subtitle generation — endpoint stub; UI can show 'Coming next session' pill.\n- Buffer OAuth — settings screen shows 'Not connected · manual fallback active'. Manual copy/download flow works today.\n- Media upload / storage abstraction — next session (S3/R2/Cloudinary swap-ready).\n\nManual smoke: Atlas produced 'Your training plan isn't bad. Your roster just doesn't care about it.' as today's Louis-voice hook. Screenshot confirms the admin-only card renders with platform tag, DRAFT pill, hook and pillar."\n\nBACKEND — NEW /app/backend/feature_standby.py (~410 lines):\n1. Extended ROSTER_SYSTEM prompt to detect STBY/SBY/RES/RSV/RESERVE/STDBY/HSBY/ASBY/SC/LC/on-call/reserve tokens and emit normalised standby_type (home_standby|airport_standby|reserve|short_call|long_call|night_standby|early_standby|unknown_standby) plus standby_start_time/standby_end_time/standby_location/standby_needs_confirmation.\n2. Endpoints:\n   - GET  /standby/today                          returns { is_standby, standby: {type,start,end,location,status,called_out,needs_confirmation}, workout, recommendations, reason }\n   - POST /standby/status  { status, date?, confirm_type?, note? }  status ∈ waiting|called_out|not_called_out|cancelled|too_tired|have_time\n   - POST /standby/called-out { report_time, expected_duty_length_hours, destination, can_train }  auto-swaps to standby workout unless coach_locked/key_session (then creates coach task)\n   - POST /standby/apply-workout { recommendation_id }  explicit swap; 409 if coach-locked (also creates coach task)\n   - POST /standby/restore-original                 restores original workout from workouts_archive\n   - GET  /coach/clients/{id}/standby ?weeks=4     coach view of standby days + workouts\n3. Deterministic Atlas selector `atlas_standby_recommendations` — 4 curated options per standby_type (mobility / strength / bodyweight / Z2 / walk / recovery / no_training). Home standby → 4 options; short-call → 2 (5min mobility, activation); night → recovery-first; called-out with can_train=no → NO_TRAINING_REC first + only mobility/recovery follow-ups.\n4. Workout swap = OPTION i (replace in place):\n   - Snapshot copied to db.workouts_archive with archive_of=<id>\n   - In-place update sets: title, exercises, duration_min, focus='standby', standby_adjusted=True, original_workout_id=<id>, standby_recommendation=<rec_id>, standby_reason=<explainer text>\n   - Restore endpoint reads back from archive.\n5. Coach task rules honoured: task 'standby_key_affected' (category='programme', priority='high', risk_level='medium') ONLY created when coach_locked OR key_session is true. Never for routine standby.\n6. Change log entries + in-app 'Standby session applied' notification on every swap (dedupe key = standby::<date>).\n\nFRONTEND — NEW /app/frontend/src/components/StandbyStatusCard.tsx (mounted on /(client)/home between HabitTodayCard and WeeklyCheckinCard):\n1. Only renders when GET /standby/today returns is_standby=true.\n2. Shows standby type + window + location, status pill (waiting/called_out/not_called_out/cancelled/too_tired/have_time — colour-coded), and Atlas's warm reason line.\n3. 6 action buttons for status updates.\n4. 'CALLED OUT' opens a bottom-sheet with report_time / duty_length / destination / can_train (yes/no/unsure).\n5. 'PICK A STANDBY-FRIENDLY SESSION' opens a picker showing Atlas's ranked recommendations; tapping applies the swap and shows the applied session banner with a RESTORE button.\n6. If coach-locked (409), friendly message: 'Coach review needed · Louis has been notified.'\n\nCoach client detail: new STANDBY section with per-day badges (type + start/end + status colour). CoachToDoFeed handles new task_type='standby_key_affected' (label 'STANDBY · KEY SESSION', category 'programme').\n\nManual verification: seeded a home_standby day for Alex, hit /standby/today → 4 recs returned; POST /standby/called-out with can_train=no on a key_session workout → coach task 'standby_key_affected' created correctly, no swap; flipped key_session=false, POST /standby/apply-workout {recommendation_id:'hs_bw'} → workout swapped to 'Standby Bodyweight' with standby_adjusted=true; POST /standby/restore-original → restored to 'Lower Body + Pull Strength'; screenshot confirms Standby Mode card renders with all 6 status buttons + CTA.\n\nPlease TEST: /standby/today returns correct shape for both standby and non-standby days; all 4 mutation endpoints (status, called-out, apply-workout, restore-original) with valid + invalid inputs; coach-lock/key-session BLOCKS auto-swap and creates 'standby_key_affected' task; recommendations sort correctly for night_standby / short_call / can_train=no cases; restore fails cleanly when nothing to restore; role guard on /coach/clients/{id}/standby. Regression check on habits + drafts + notifications + change log unchanged." (76/76 backend tests pass, iteration_27).\n\nExtracted three logical blocks into feature modules:\n  - /app/backend/feature_coach_v1.py      (487 lines) — Coach Message Drafts + Coach Controls + Change Log endpoints\n  - /app/backend/feature_habits.py         (789 lines) — Goal-Based Habit Tracking endpoints (client + coach)\n  - /app/backend/feature_notifications.py  (429 lines) — Notifications V1 endpoints + enqueue helper + notify_* hooks\n\nserver.py is now 6,909 lines (down from 8,462 — 20% reduction, 1,553 lines relocated).\n\nMechanism (pattern to reuse when adding new features):\n1. Each feature module does `from server import ...` for shared symbols (api router, db, current_user, require_role, models, helpers, LLM callers).\n2. server.py imports the feature modules at the VERY BOTTOM (just before app.include_router(api)) so all shared symbols are already defined.\n3. After the imports, server.py rebinds feature-module functions into its own namespace so pre-existing call sites in server.py (like /assessment/finalize → _seed_habits_for_user_by_id or /checkins/submit → _run_habit_review_after_checkin) continue to work unchanged. Same trick used for notify_coach_message/notify_coach_draft_ready/notify_weekly_video_ready/notify_programme_updated/enqueue_notification/_bg_generate_message_draft.\n4. Reminder tick chain is composed in server.py post-import: `_tick_reminders_all` calls base tick, then feature_habits._tick_habit_reminders, then feature_notifications._tick_roster_and_workout_reminders. This replaces the previous in-module rebind pattern.\n5. _log_change (shared change-log helper) moved back to server.py as a shared utility since it's called by both coach_v1 and habits features.\n6. feature_notifications._is_on_duty_now uses a deferred `from feature_habits import _is_flight_day` inside the function to break the circular import.\n\nPre-refactor snapshot saved at /app/backend/server.py.pre_refactor for diffing if needed.\n\nZero endpoint URLs or payload contracts changed. All existing frontend calls unchanged. No frontend restart required.\n\nMinor code-quality touches applied per testing-agent notes:\n- Lazy notify_* shims in feature_coach_v1.py made `async def` for type clarity.\n- Dead _tick_reminders_full alias removed from feature_notifications.py.\n\nReady to build Standby Mode on this cleaner surface in the next session."\n\nBACKEND (server.py, ~430 new lines):\n1. New collection `notifications` (in-app notification centre).\n2. Extended `scheduled_messages` scheduler via `_tick_roster_and_workout_reminders` (roster expiry at 7/3/1/expired, workout reminder at preferred_reminder_time default 07:30 local, missed-check-in coach task on TUESDAY 09:00 local for the previous week's uncompleted check-in).\n3. `enqueue_notification()` — creates in-app + best-effort push; deduplicates on (user_id, notif_type, related_id, dedupe_key); rewords body with 'when you're off duty and settled' when the client is on flight duty.\n4. Endpoints:\n   - GET  /notifications ?unread_only=&limit=\n   - GET  /notifications/unread-count\n   - POST /notifications/{id}/read\n   - POST /notifications/read-all\n   - GET  /notifications/settings\n   - PUT  /notifications/settings  { 7 category toggles + quiet_hours_start/end + preferred_reminder_time + travel_use_current_tz }\n   - POST /notifications/permission { status: granted|denied|not_requested, platform?, device_info? }\n5. Hook helpers wired into: /coach/messages/{id}/approve → notify_coach_message; weekly_video/send → notify_weekly_video_ready; reality/coach-approve → notify_programme_updated; _bg_generate_message_draft → notify_coach_draft_ready (coach in-app).\n6. Uses IANA time zones from user.current_time_zone/home_time_zone. Quiet hours enforced via existing _in_quiet_hours. `_get_notif_settings` merges DEFAULT_NOTIFICATION_SETTINGS with per-user overrides and mirrors legacy top-level quiet_hours fields.\n\nFRONTEND additions:\n1. NEW /app/frontend/src/components/NotificationBell.tsx — unread-count badge + slide-up drawer with unread pill, category dots, DUTY-SAFE tag, mark-all-read, tap to navigate via action_url. Mounted on client home and coach overview.\n2. NEW /app/frontend/src/components/NotificationPreferencesCard.tsx — mounted in /(client)/profile between Habits and Workout Settings. 7 category switches, HH:MM inputs for preferred + quiet hours, travel-tz switch, Allow-push CTA banner (only if permission != granted).\n3. NEW /app/frontend/src/components/PushPermissionPrompt.tsx — one-time, non-blocking modal fired 2.5s after client home renders IF permission_status='not_requested'. ALLOW invokes promptAndRegisterPush(); NOT NOW records status='denied'. Copy: 'Stay in touch with Louis · Allow CrewFit to send reminders for check-ins, workouts, habits and coach updates. Quiet by default — nothing during quiet hours or flight duty.'\n4. Updated /app/frontend/src/lib/push.ts — `registerForPush` now ONLY runs if permission is already granted (no first-launch nag). New `promptAndRegisterPush(userId)` handles explicit prompt + token save + /notifications/permission persist.\n\nRules honoured:\n- Permission not asked immediately on first login (per brief).\n- In-app notifications always created as a fallback even if push fails or is disabled.\n- Dedupe prevents duplicates across (user, notif_type, related_id, dedupe_key).\n- Flight-duty rewording ('… when you're off duty and settled') applied to workout/habit/check-in reminders when today's roster shows flight/duty.\n- Missed-check-in coach task on TUESDAY morning (weekday=1, 09:00 local).\n\nManual verification: GET /notifications/settings returns defaults correctly; POST /notifications/permission { status: 'granted' } persisted; POST /notifications creates in-app doc when hook helpers fire; bell renders on home with unread badge; permission prompt renders when permission_status='not_requested'; ALLOW / NOT NOW actions call the correct endpoints.\n\nPlease TEST: all notification endpoints incl. dedupe (post two coach msg approve calls with same draft_id → single notification updated), permission save transitions, settings merge on partial PUT, unread-count math after read/read-all, and hook wiring: send a coach message via /coach/messages/{id}/approve → client should get a notification with category='coach_messages' and action_url='/(client)/messages'; send a weekly video → client should get category='weekly_videos'. Regression check on habits + drafts + change log endpoints.\n\nServer.py is now ~8500 lines — refactor into /routers/* strongly recommended before next feature."\n\nBACKEND additions (server.py, ~600 new lines):\n1. New collections: `habits`, `habit_logs`, `habit_reviews`.\n2. Auto-seeding: /assessment/finalize now spawns asyncio background task _seed_habits_for_user_by_id(user_id). Uses HABIT_SEED_SYSTEM (Claude Sonnet 4.5) with the client's Coaching DNA. Falls back to a deterministic starter pack if the LLM fails. Idempotent — never duplicates.\n3. Weekly Atlas review: /checkins/submit now spawns _run_habit_review_after_checkin(user, checkin_id, week_start, week_end). Aggregates habit_logs + check-in answers + coach_controls, calls HABIT_REVIEW_SYSTEM (Claude), produces recommendations {action, change, reason, risk_level, new_target, ...} + new_habits.\n4. Auto-apply vs coach review — respects user.coach_controls.auto_approval_risk_threshold. If any recommendation is medium/high OR touches injury OR if threshold is 'none' → coach_review_required=True + coach_task of type 'habit_review' (category 'programme') is created. Otherwise auto-applied by Atlas.\n5. _apply_habit_review honours actions: keep / scale_down / scale_up / pause / resume / replace / simplify / make_specific / remove and inserts new_habits (max 5 active total enforced).\n6. Endpoints:\n   Client:\n   - POST /habits/seed (idempotent)\n   - GET  /habits/today (day-type-aware — filters by roster/workout)\n   - GET  /habits/mine (active + paused)\n   - POST /habits/{id}/log { status, reason?, note?, date_local?, time_zone? }\n   - GET  /habits/{id}/logs\n   - POST /habits/reminders/toggle { enabled }\n   - GET  /habits/reviews/latest\n   Coach:\n   - GET  /coach/clients/{id}/habits (active + paused + archived + completion + streaks + latest + pending review)\n   - POST /coach/clients/{id}/habits (manual create)\n   - PATCH /coach/habits/{id} (edit title/target/reason/status pause|active|archived)\n   - POST /coach/habits/reviews/{id}/approve { coach_note?, modified_recommendations? }\n   - POST /coach/habits/reviews/{id}/reject { coach_note? }\n7. Habit types supported: daily, weekly, training-day-only, rest-day-only, flight-day, layover-day, home-day, post-flight, pre-flight, recovery-day, after-workout, event-specific, custom. _habit_relevant_today() decides visibility from roster day_type + workout presence.\n8. Streaks: KIND design — skipped and not_possible preserve the streak per user's explicit requirement (option b). Only a fully unlogged expected day breaks it.\n9. Reminders: extended _tick_reminders via _tick_reminders_with_habits — enqueues at most one habit_daily scheduled_messages row at 10:00 local, respects quiet-hours + user.habit_reminders_enabled toggle + relevance to today's day-type. IANA time zones.\n\nFRONTEND additions:\n1. NEW /app/frontend/src/components/HabitTodayCard.tsx — 'TODAY'S HABITS · N' card on client home. Each habit shows title, reason, linked-goal chip, streak, Done / Skipped / Not Possible buttons. Skipped/Not-Possible open a reason modal with 11 supportive chips (Roster, Fatigue, Time, Family, Illness, Forgot, No kit, Poor sleep, Stress, Not relevant, Other) and a 'skip · just log it' bypass. Warm kind copy after logging.\n2. Home hook — HabitTodayCard rendered between the quick-row and WeeklyCheckinCard.\n3. NEW HabitsProfileSection appended to /(client)/profile.tsx — 'HABITS' section under Coaching Headquarters with active/paused lists, streaks, and a REMINDERS ON/OFF toggle (posts to /habits/reminders/toggle). Fallback 'Atlas · seed my starter habits' CTA for cases where the DNA hook didn't fire.\n4. Check-in extended — /app/frontend/app/checkin.tsx now appends 4 OPTIONAL habit questions (Easy/Manageable/Mixed/Too much/Not realistic; hardest, most helpful, needs changing). Never gates submit. After submit, the SubmittedView polls /habits/reviews/latest and shows 'HABIT UPDATE' with 'Atlas has prepared a habit update for Louis to review' when coach approval pending.\n5. NEW /app/frontend/app/coach/habit-review/[id].tsx — Louis approves/rejects each recommendation via a per-item checkbox toggle, adds a coach note, sees risk badges + what worked / what didn't. Approve applies filtered set; Reject marks dismissed. Coach task auto-resolves.\n6. Coach client detail /app/frontend/app/coach/client/[id].tsx — new HABITS card with completion %, streak, paused list, latest Atlas review, and REVIEW READY pill that opens the approval screen when a pending review exists.\n7. CoachToDoFeed now routes habit_review tasks to the new approval screen and shows HABIT REVIEW label.\n\nVerification so far: manual curl seeded 4 personalised habits for the demo client ('Log 3 runs per week', 'Walk for 10 minutes after each run', 'Eat within 30 minutes of finishing each run', 'Get 7+ hours sleep on training nights' — running-focused via DNA). POST /habits/{id}/log returned OK with streak=1. GET /coach/clients/{id}/habits returns 4 active with completion rates. Screenshot of client home confirmed TODAY'S HABITS card rendering with Done buttons and streak indicators.\n\nPlease test backend end-to-end (seed idempotency, day-type filtering on /habits/today with a home-day habit + a post-flight habit, log upsert + streak preservation on skipped, reminders toggle persistence, coach GET /clients/{id}/habits shape, PATCH /coach/habits/{id}/pause, and a full habit review approve flow: manually insert a habit_review doc, GET pending, POST approve with a filtered recommendation list, verify habit updates + coach_change_log entries). Then frontend smoke: client login → habits card → Done + Skipped-with-reason; coach login → client detail → HABITS block; approve a review from the coach screen."



##====================================================================
## §32 — Social Studio · Recording Studio + Teleprompter integration
##====================================================================

backend:
  - task: "POST /api/social/posts/{post_id}/assets — multipart video upload"
    implemented: true
    working: true
    file: "backend/feature_social_studio.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Accepts multipart/form-data with file + kind/duration_seconds/width/height/label. Streams to disk under /app/backend/uploads/social_assets/<post_id>/<asset_id>.<ext>. Enforces 120MB cap and ALLOWED_MIMES (mp4/mov/webm/mkv/mpeg/3gp/mp3/wav). Persists metadata to social_media_assets. Transitions post.status to 'Recorded' if currently Idea/Draft/Script Ready/Recording Needed, and links post.media_id. Admin-only via require_admin() (coach role is admin in dev)."
      - working: true
        agent: "testing"
        comment: "27/27 pytest passed (iteration_30). Multipart upload, status transition Draft→Recorded, media_id set, size/mime/kind/storage correct. Image mime → 400. 130MB stream → 413."
  - task: "GET /api/social/posts/{post_id}/assets — list drafts"
    implemented: true
    working: true
    file: "backend/feature_social_studio.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "Verified: sorted created_at desc, no file_path leak."
  - task: "GET /api/social/assets/{asset_id} — detail"
    implemented: true
    working: true
    file: "backend/feature_social_studio.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "Verified: 404 on miss, correct payload on hit."
  - task: "DELETE /api/social/assets/{asset_id} — retake / archive"
    implemented: true
    working: true
    file: "backend/feature_social_studio.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "Verified: soft-archive + disk unlink + post.media_id cleared + subsequent stream 404."
  - task: "GET /api/social/assets/{asset_id}/stream — auth-signed file streaming"
    implemented: true
    working: true
    file: "backend/feature_social_studio.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "Both Authorization header AND ?token= query verified. 401 on missing/bad. Follow-up non-blocking: FileResponse lacks Range/206 support — HTML5 video scrubbing will re-download. Consider StreamingResponse with Range parsing later."
  - task: "POST /api/social/assets/{asset_id}/subtitles/generate — subtitle stub"
    implemented: true
    working: true
    file: "backend/feature_social_studio.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "testing"
        comment: "Confirmed: doc created with status=pending, provider=whisper-1-stub, asset.subtitle_id set, note field present. Real Whisper-1 lands next release."

frontend:
  - task: "Recording Studio screen with teleprompter overlay (9:16)"
    implemented: true
    working: "NA"
    file: "frontend/app/social-studio/record/[postId].tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "New route /social-studio/record/[postId]. Uses expo-camera CameraView (mode=video, facing=front, videoQuality=1080p) on native and browser getUserMedia + MediaRecorder on web. Contextual camera + mic permission prompt with pre-explainer, canAskAgain-aware Open Settings fallback via Linking.openSettings. 3-2-1 countdown, auto-scrolling teleprompter (SLOW/NORMAL/FAST + A/A+/A++ font size), REC pill with elapsed time, 60s hard auto-stop, retake/save-draft/send-to-subtitles action row on preview. Multipart upload via uploadFile() helper with XHR upload progress %. Cleans up temp cache file via FileSystem.deleteAsync after upload on native. Camera behaviour only fully works on a device build post-Publish."
  - task: "Subtitle Editor stub screen"
    implemented: true
    working: "NA"
    file: "frontend/app/social-studio/subtitles/[assetId].tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "New route /social-studio/subtitles/[assetId]. Streams the video via buildStreamUrl() (token in querystring), shows asset metadata, GENERATE SUBTITLES button that hits the stub endpoint. Copy explicitly labels this as a placeholder ahead of Whisper-1 landing next session."
  - task: "Social Studio · RECORD VIDEO CTA + recorded drafts list"
    implemented: true
    working: "NA"
    file: "frontend/app/social-studio.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Added a crimson RECORD VIDEO button on each post's detail view that pushes to /social-studio/record/<postId>. Detail view also lists recorded drafts (kind/duration/size/created_at) with tap-to-open subtitle editor route."
  - task: "api client — uploadFile() + buildStreamUrl() helpers"
    implemented: true
    working: "NA"
    file: "frontend/src/lib/api.ts"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "uploadFile(path, file, extraFields, {onProgress}) uses XHR when progress is requested (browsers + RN both support XHR). Accepts either browser Blob/File OR RN-style {uri,name,type}. buildStreamUrl(path) appends the current auth token as ?token=… so <video> can stream authorised media."

test_plan:
  current_focus:
    - "POST /api/social/posts/{post_id}/assets (multipart upload + status transition + 120MB cap + mime validation)"
    - "GET /api/social/posts/{post_id}/assets"
    - "GET /api/social/assets/{asset_id}"
    - "DELETE /api/social/assets/{asset_id} (file removal + media_id unlink + archive)"
    - "GET /api/social/assets/{asset_id}/stream (both header + query token auth)"
    - "POST /api/social/assets/{asset_id}/subtitles/generate (stub creates social_subtitles doc)"
    - "Auth gating: client role → 403 on ALL new endpoints"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: "Recording Studio + Teleprompter integration shipped. NEW backend endpoints in feature_social_studio.py: POST /social/posts/{post_id}/assets (multipart upload — writes to /app/backend/uploads/social_assets/<post_id>/<asset_id><ext>, enforces 120MB cap + mime allow-list, transitions post.status to 'Recorded' + sets media_id when post was upstream, persists to social_media_assets), GET /social/posts/{post_id}/assets (list, hides file_path), GET /social/assets/{asset_id} (detail), DELETE /social/assets/{asset_id} (soft-archive + delete file + unlink post.media_id), GET /social/assets/{asset_id}/stream (accepts Authorization header OR ?token= query — needed for <video> tag which can't set headers), POST /social/assets/{asset_id}/subtitles/generate (placeholder — real Whisper-1 lands next). NEW frontend routes: /social-studio/record/[postId] (full-screen vertical camera + auto-scroll teleprompter, contextual perms with Open Settings fallback, 3-2-1 countdown, 60s auto-stop, retake/save-draft/send-to-subtitles) and /social-studio/subtitles/[assetId] (stub editor with token-signed video preview). Social Studio detail view now has a crimson RECORD VIDEO CTA and lists recorded drafts. New api helpers uploadFile() (XHR-based, supports progress + RN {uri,name,type}) + buildStreamUrl() in /src/lib/api.ts. Camera recording only works fully on a device build (Expo Go + web preview can start recording via MediaRecorder for QA, but final testing needs Publish). Please test all 6 new endpoints (with coach@crewfit.com/Coach123!) — role gating (client → 403), a real multipart upload (any small video works), status transition, list, stream via query token, delete then verify file gone from disk + media_id unlinked, subtitle stub creation. Skip actual native camera in testing — the recorder falls back to MediaRecorder on the web preview."

##====================================================================
## §33 — Whisper-1 subtitle pipeline + SRT editor
##====================================================================

backend:
  - task: "POST /api/social/assets/{asset_id}/subtitles/generate — real Whisper-1"
    implemented: true
    working: true
    file: "backend/feature_social_studio.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "REPLACED the stub with a real background pipeline: ffmpeg extracts a 16kHz mono 64kbps mp3 (stays under 25MB whisper cap) → OpenAISpeechToText (emergentintegrations, model=whisper-1, response_format=verbose_json, timestamp_granularities=[segment]) → SRT + VTT rebuilt from segments and written to disk alongside the source + persisted in the social_subtitles doc. status machine: pending → generating → ready | failed. Manual smoke test: 5-second silent test.mp4 → status=ready in ~4s with 1 segment ('you' — accurate for near-silent audio) + language=english + duration=5.05."
  - task: "PATCH /api/social/subtitles/{subtitle_id} — segment edit + SRT/VTT rebuild"
    implemented: true
    working: "NA"
    file: "backend/feature_social_studio.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Accepts {segments:[{index,start,end,text}]}. Rebuilds SRT + VTT from edited segments, writes to side files, transitions status to 'edited', invalidates any prior burn_video_path so a re-burn is required."
  - task: "GET /api/social/subtitles/{subtitle_id}/download — .srt / .vtt file download"
    implemented: true
    working: "NA"
    file: "backend/feature_social_studio.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Accepts fmt=srt|vtt and BOTH Authorization header OR ?token= query. Returns file with correct Content-Disposition."
  - task: "POST /api/social/subtitles/{subtitle_id}/burn — ffmpeg subtitle burn-in"
    implemented: true
    working: true
    file: "backend/feature_social_studio.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Async ffmpeg render with libx264 veryfast/CRF22 + AAC 128k + faststart. Uses force_style ASS overrides (default: white bold text, black outline, MarginV=90). Writes <name>_subtitled.mp4 alongside the source and updates subtitle doc with burned_video_path + burned_at + burn_style. status machine adds: burning → ready | burn_failed. Manual smoke test: 5-second video → burned file 12.7KB written to disk in ~1s."
  - task: "GET /api/social/subtitles/{subtitle_id}/burned/stream — auth-signed burned mp4"
    implemented: true
    working: "NA"
    file: "backend/feature_social_studio.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "FileResponse of the burned mp4. Accepts Authorization header OR ?token= query (needed by <video> tag)."
  - task: "GET /api/social/subtitles/{subtitle_id} — poll status"
    implemented: true
    working: "NA"
    file: "backend/feature_social_studio.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Returns full subtitle doc (segments, srt, vtt, status, burned_video_path, error). Used by frontend polling loop."
  - task: "GET /api/social/assets/{asset_id}/subtitles — latest by asset"
    implemented: true
    working: "NA"
    file: "backend/feature_social_studio.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Restored on the new pipeline; returns the newest subtitle doc for a given asset (or null)."

frontend:
  - task: "Subtitle Editor screen (segment editing + burn-in + downloads)"
    implemented: true
    working: "NA"
    file: "frontend/app/social-studio/subtitles/[assetId].tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Full rewrite. Preview toggles between original and burned MP4 when burn is ready. Per-segment TextInput lets the coach edit text (V1 keeps timing untouched). SAVE EDITS uses the PATCH endpoint. BURN CAPTIONS INTO VIDEO kicks off ffmpeg render with a status banner (QUEUED / TRANSCRIBING / READY / BURNING / FAILED). Auto-polls every 2s while a job is in-flight; stops when terminal. Download buttons open .SRT / .VTT / burned .MP4 via token-signed URLs. Dirty state disables burn until saved."

test_plan:
  current_focus:
    - "POST /api/social/assets/{asset_id}/subtitles/generate — real Whisper-1 round-trip"
    - "PATCH /api/social/subtitles/{subtitle_id} — segment edit + SRT rebuild"
    - "POST /api/social/subtitles/{subtitle_id}/burn — burned file lands on disk"
    - "GET /api/social/subtitles/{subtitle_id}/download?fmt=srt|vtt"
    - "GET /api/social/subtitles/{subtitle_id}/burned/stream (header + query token)"
    - "GET /api/social/subtitles/{subtitle_id} (poll status transitions)"
    - "Role gating: client role → 403 on ALL new subtitle endpoints"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: "§33 shipped — real Whisper-1 subtitle pipeline replaces the stub, plus ffmpeg burn-in and a fully functional SRT editor UI. Key implementation notes: audio extraction is a compact 16kHz mono 64kbps mp3 to stay under the 25MB Whisper limit; transcription is done as a background asyncio task (POST returns queued immediately, frontend polls GET /social/subtitles/{id}); OpenAISpeechToText from emergentintegrations was passed a file-like object (open(...,'rb')) — passing a path string breaks with 'Expected entry at file to be bytes...'; SRT/VTT are rebuilt from segments on save so edits stick to both formats; burn-in writes a new <name>_subtitled.mp4 alongside the source with libx264+AAC+faststart for Buffer/TikTok/LinkedIn compatibility; edits invalidate any prior burn (burned_video_path cleared) so the coach must re-burn after editing. ffmpeg (5.1.9) installed via apt. Manual round-trip verified: generate → 5-second silent test.mp4 → status=ready in ~4s → 1 segment → burn → 12.7KB burned file on disk. Please regression-test the previous asset endpoints (§32) too — they share the same file. Test credentials in /app/memory/test_credentials.md. Note that Whisper on a truly silent audio track may hallucinate short 'you' tokens — this is expected and the coach's edit workflow handles it."


##====================================================================
## §34 — Premium Brand Refresh · Client Home Header + Profile Photo + Location + Fonts + Logo
##====================================================================

backend:
  - task: "POST /api/user/profile/photo — multipart profile photo upload"
    implemented: true
    working: "NA"
    file: "backend/feature_profile.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Multipart upload → /app/backend/uploads/profile_photos/<user_id>/<photo_id>.<ext>. 5MB cap. Allowed: jpeg/png/webp/heic/heif. Sets user.profile_photo_url = '/api/user/profile/photo/<user_id>' and stores file_path/mime/size/updated_at on user doc. Deletes any previous file on replace."
  - task: "DELETE /api/user/profile/photo — remove photo"
    implemented: true
    working: "NA"
    file: "backend/feature_profile.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Unlinks file from disk + unsets profile_photo_url/path/mime/size on user."
  - task: "GET /api/user/profile/photo/{user_id} — token-signed streaming"
    implemented: true
    working: "NA"
    file: "backend/feature_profile.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Accepts Authorization header OR ?token= query. ANY authenticated user can view another user's photo (coach ↔ client dashboards). 404 when no photo."
  - task: "POST /api/user/location — upsert location + tz"
    implemented: true
    working: true
    file: "backend/feature_profile.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Sets current_location_city/country/time_zone + location_source + location_permission_status + location_last_updated_at."
      - working: true
        agent: "main"
        comment: "Empty-body 400 fixed: LocationBody.source default was 'manual' which pre-seeded updates. Set source default to None and moved timestamps assignment AFTER the emptiness check. Verified: {}→400, {city:'Paris'}→200."
  - task: "POST /api/user/location/permission — record permission state"
    implemented: true
    working: "NA"
    file: "backend/feature_profile.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Persists location_permission_status ∈ {granted, denied, not_requested}."
  - task: "PATCH /api/user/profile — extended fields (job_title, airline, home_base, aircraft_type, route_focus)"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "UserProfilePatch extended with the aviation-branding fields. Values are stored under user.profile.<field>."

frontend:
  - task: "ClientProfileHeader — premium aviation identity hero"
    implemented: true
    working: "NA"
    file: "frontend/src/components/ClientProfileHeader.tsx, frontend/app/(client)/home.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "New premium header on client home: ProfileAvatar (photo or monogrammed circle with wings) + HELLO eyebrow + first name in Creo Bold display font + role · airline + home base chip + LocationBadge (city + local time) + load pill + STANDBY pill + day-type + day-title. Screenshot verified rendering with HELLO / ALEX / CREW · Skyline Air / GREEN DAY / STANDBY / Standby Mobility."
  - task: "ProfileAvatar + LocationBadge + CrewFitLogo variants"
    implemented: true
    working: "NA"
    file: "frontend/src/components/ProfileAvatar.tsx, frontend/src/components/LocationBadge.tsx, frontend/src/components/Logo.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "ProfileAvatar shows token-signed photo OR wings-in-navy-circle monogram with initials. LocationBadge shows a location pill with brand-tinted background + optional local time computed via Intl.DateTimeFormat. Logo module split into CrewFitLogo (full), CrewFitWings (wings-only), and legacy CrewFitWordmark shim."
  - task: "ProfilePhotoRow — inline profile photo picker"
    implemented: true
    working: "NA"
    file: "frontend/src/components/ProfilePhotoRow.tsx, frontend/app/(client)/profile.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Take Photo / Upload / Remove buttons using expo-image-picker; multipart upload via uploadFile(). Contextual permissions with Open-Settings fallback via canAskAgain. Screenshot verified — Profile section now shows avatar, PROFILE PHOTO card, and new JOB TITLE / AIRLINE / HOME BASE / AIRCRAFT / ROUTE FOCUS rows."
  - task: "Brand fonts (Source Sans 3 + Creo ExtraBold) + logo assets"
    implemented: true
    working: "NA"
    file: "frontend/src/hooks/use-brand-fonts.ts, frontend/assets/fonts/*, frontend/assets/images/crewfit-*"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Wired expo-font to load Source Sans 3 (Regular/SemiBold/Bold) + Creo ExtraBold/ExtraLight (user-provided licensed files). theme.font.display/text/textSemi/textBold constants added; ClientProfileHeader + Profile page consume them. Logo saved with transparent bg + a wings-only crop. Fonts confirmed rendering in web preview."
  - task: "app.json — new permissions descriptions"
    implemented: true
    working: "NA"
    file: "frontend/app.json"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Added iOS: NSPhotoLibraryAddUsageDescription + NSLocationWhenInUseUsageDescription. Refined existing camera/mic/library strings. Android: ACCESS_COARSE_LOCATION + ACCESS_FINE_LOCATION."

test_plan:
  current_focus:
    - "POST /api/user/profile/photo (upload + status transition + 5MB cap + mime whitelist)"
    - "DELETE /api/user/profile/photo (file + fields removed)"
    - "GET /api/user/profile/photo/{user_id} (header + query token auth)"
    - "POST /api/user/location (upsert)"
    - "POST /api/user/location/permission (status transitions)"
    - "PATCH /api/user/profile (job_title / airline / home_base / aircraft_type / route_focus persist)"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: "§34 Phase 1 shipped (foundation for premium brand refresh). New feature_profile.py module (5 endpoints) + UserProfilePatch extended in server.py. Client home has a brand-new hero: ProfileAvatar + HELLO eyebrow + first name in Creo ExtraBold + role · airline + home-base chip + city + local time + load pill + STANDBY pill + day-title. Profile page has a new ProfilePhotoRow (Take/Upload/Remove) plus editable job_title/airline/home_base/aircraft_type/route_focus fields. CrewFit wings logo transparent-bg version saved. Source Sans 3 + Creo ExtraBold fonts loaded via expo-font (user's licensed Creo file). app.json updated with photo/library/location permissions. Please test the 6 new/extended endpoints (upload, delete, GET-photo dual-auth, location upsert, permission, profile PATCH). Test credentials in /app/memory/test_credentials.md. Phase 2 (AI imagery + storage abstraction) + Phase 3 (icon sweep) still pending."


##====================================================================
## §34 · Phase 3 — Emoji sweep + Icon system + Coach client cards
##====================================================================

frontend:
  - task: "Client home — emoji-free hero + card icons"
    implemented: true
    working: "NA"
    file: "frontend/app/(client)/home.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Removed 🏁 ⏰ 🧠 🔀 🏖️ 🤕 📅 emojis from `iconFor(kind)`. Reassessment prompt cards now render an Ionicons in a brand-tinted circle (calendar/medkit/sunny/alarm/flag/swap-horizontal/pulse). Reality bubble renders a compass icon in a brand circle. 'Did today go to plan?' modal replaces ✅ 💪 ✈️ 😴 🤒 👨‍👩‍👧 🏨 ❌ ⏳ ✍️ with proper Ionicons (checkmark-circle / barbell / airplane / radio / moon / medkit / people / business / close-circle / hourglass / create). Also fixes unescaped apostrophe in 'We'll adjust...'."
  - task: "Reality modal — icon-first"
    implemented: true
    working: "NA"
    file: "frontend/src/components/RealityModal.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Kind grid now uses each REALITY_KINDS entry's `icon` prop (already existed alongside `emoji`) in a brand-tinted round wrapper. Selected-kind chip in loading state also uses icon."
  - task: "Client profile — icon-only section headers + stats"
    implemented: true
    working: "NA"
    file: "frontend/app/(client)/profile.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Section renderer no longer branches on emoji — always uses Ionicons. Check-in stats (💤/⚡/😣) replaced with icon chips (moon/flash/pulse). Event 🎯 replaced with flag icon. `emoji` prop retained on Section signature for backwards-compat but ignored."
  - task: "Workout screen — chip icons + reality bubble"
    implemented: true
    working: "NA"
    file: "frontend/app/workout/[id]/index.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: "NA"
        agent: "main"
        comment: "📍 location chip → Ionicons location; ⏱ time chip → time icon; ⭐ KEY SESSION → star icon on brand background; 🧠 reality bubble → compass icon in tinted circle."
  - task: "Habit + coach habit — flame streak icon"
    implemented: true
    working: "NA"
    file: "frontend/src/components/HabitTodayCard.tsx, frontend/app/coach/client/[id].tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: "NA"
        agent: "main"
        comment: "🔥 streak → Ionicons flame in brand-outlined chip in both places."
  - task: "Coach dashboard clients — colored dots + ProfileAvatar cards"
    implemented: true
    working: "NA"
    file: "frontend/app/(coach)/clients.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: "NA"
        agent: "main"
        comment: "🟢🟠🔴⚪ widget prefixes replaced with 10px colored dots (green/amber/red/textDim). Each client card now shows a ProfileAvatar (44px, ringless — softer look), name, role · airline (First Officer · Emirates), and home base + current location line (DUBAI (DXB) · in London). Backend already returns these fields via _client_summary spreading the user doc."
  - task: "Small emoji sweep — coach scripts, coaching-dna, nutrition, social-studio, reality-history"
    implemented: true
    working: "NA"
    file: "frontend/app/coach/scripts/[id].tsx, frontend/app/coaching-dna.tsx, frontend/app/(client)/nutrition.tsx, frontend/app/social-studio.tsx, frontend/app/reality-history.tsx, frontend/app/assessment.tsx"
    stuck_count: 0
    priority: "low"
    needs_retesting: false
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Individual sweeps: coach scripts 'SENT ✓' → 'SENT'. coaching-dna 🎯 → flag icon. nutrition 💡 → bulb icon in row. social-studio ✨ empty-state copy softened. reality-history 📝 → document icon in tinted circle. assessment.tsx event pill 🎯 → flag icon. NOTE: assessment.tsx equipment picker (18 emoji strings) intentionally deferred to a future turn — it's a lower-visibility onboarding screen and each emoji needs a considered icon mapping."

agent_communication:
  - agent: "main"
    message: "§34 Phase 3 shipped — massive emoji cleanup + coach dashboard client card upgrade. Screenshot A (client home) shows the previous 🏁 ⏰ 🧠 emojis replaced by crimson-tinted circular icons (flag, alarm, ribbon-ish, compass). Screenshot B (coach dashboard) shows the client status widgets with clean colored dots + Alex Rivera's client card showing photo initials + 'First Officer · Emirates' + 'DUBAI (DXB) · in London' — exactly as briefed. NO backend changes in this phase — coach client summary was already returning the fields we needed via _client_summary(u). One known deferred: assessment.tsx equipment picker still has emojis (18 items — separate turn). Fonts (Creo Bold headers, Source Sans body) are visibly rendering. Everything else in the emoji audit is done."


##====================================================================
## §34 · Phase 2 — AI Imagery Library + Admin + Equipment Icons
##====================================================================

backend:
  - task: "feature_brand_images.py — Nano Banana library generation + admin"
    implemented: true
    working: true
    file: "backend/feature_brand_images.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "New module. 8 endpoints — POST /brand-images/seed (kicks off 9 pending jobs, one per LIBRARY entry), GET /brand-images (list, filter by category, hide/show hidden), GET /brand-images/pick (best-fit context matcher — role/gender/goal/workout_type/phase/context/day_type — falls back to hero_default), GET /brand-images/{id}/stream (auth-signed via header OR ?token= query), POST /brand-images/{id}/regenerate, PATCH /brand-images/{id} (is_default / status / label), DELETE /brand-images/{id} (soft-hide + file unlink). Uses emergentintegrations LlmChat with model 'gemini-3.1-flash-image-preview' and modalities=['image','text']. LIBRARY constant defines 9 categories with BASE_STYLE + role/gender/context-specific prompt suffixes. Manual smoke test: seeded and all 9 images generated to /app/backend/uploads/brand_images in ~25s. Pick with workout_type=endurance+goal=marathon returned workout_endurance_marathon with score=6. Two generated images inspected — both premium cinematic aviation shots exactly matching the brief."

frontend:
  - task: "AIHeroImage component — contextual best-fit renderer"
    implemented: true
    working: true
    file: "frontend/src/components/AIHeroImage.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "New component. Takes an ImageContext prop, calls /brand-images/pick, builds token-signed stream URL, renders <Image> with LinearGradient overlay for text legibility. In-memory pickCache keyed by sorted context so many cards on one screen don't hammer the endpoint. Graceful fallback (solid navy) when no library image is ready."
  - task: "Client home — hero background switched to AIHeroImage"
    implemented: true
    working: true
    file: "frontend/app/(client)/home.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "Removed Unsplash HERO import + LinearGradient wrapper. Passes user.profile.job_title-derived role (crew vs pilot), preferred_visual_gender, todaysWorkout.focus, standby state, and today's day_type. Screenshot verified — hero now shows the AI-generated male-pilot hotel-hallway image; text and STANDBY badges remain legible on top."
  - task: "Workout screen — AI banner above title"
    implemented: true
    working: true
    file: "frontend/app/workout/[id]/index.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "Added a 180px AIHeroImage banner card just below the top bar. Picks workout_type ∈ {endurance, strength} based on focus text and passes event_phase. Renders the focus eyebrow + workout title on the gradient overlay."
  - task: "Coach · Brand Images admin screen"
    implemented: true
    working: true
    file: "frontend/app/coach/brand-images.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "New /coach/brand-images route. Grid of every library image with status pill, DEFAULT pill, context chips, size + timestamp, REGEN / MAKE DEFAULT / HIDE / RESTORE actions. Auto-polls every 3s while any job is generating. SEED / TOP UP LIBRARY CTA for cold-start. Coach overview header now has a new IMAGES button (ov-goto-brand) alongside SOCIAL."
  - task: "Assessment equipment picker — 18 emoji → 18 Ionicons"
    implemented: true
    working: true
    file: "frontend/app/assessment.tsx"
    stuck_count: 0
    priority: "low"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "Option type extended with optional `icon` field. HOME_EQ list rebuilt using Ionicons (barbell, fitness, boat, bicycle, walk, bed-outline, construct, link, ellipse, hand-left, swap-horizontal, remove-circle-outline, grid-outline, infinite, flash, trending-up, reorder-two). Renderers in SingleSelect / MultiSelect / EquipmentPicker prefer icon over emoji so legacy backend options with `emoji` still render but new local list uses icons."

test_plan:
  current_focus:
    - "POST /api/brand-images/seed — 200 with created list; kicks off background jobs; second call is idempotent"
    - "GET  /api/brand-images (client + coach can list ready images; hidden filtered out unless include_hidden=true)"
    - "GET  /api/brand-images/pick with various context params (role/gender/workout_type/goal/phase/day_type/context) — deterministic best-match + hero_default fallback"
    - "GET  /api/brand-images/{id}/stream — Authorization header AND ?token= query both work"
    - "POST /api/brand-images/{id}/regenerate — admin only; resets status=pending; new file replaces old on disk"
    - "PATCH /api/brand-images/{id} — is_default/status/label; invalid status → 400"
    - "DELETE /api/brand-images/{id} — soft-hide, file unlinked, subsequent stream 404"
    - "Role gating: client hitting admin endpoints (seed, regenerate, patch, delete) → 403"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: "§34 Phase 2 shipped — CrewFit is now a properly branded premium aviation product. 9 Nano-Banana-generated images seed the library at /app/backend/uploads/brand_images/, admin can regen/hide/set-default from /coach/brand-images. AIHeroImage picks the best-fit image based on {role, gender, workout_type, goal, phase, context, day_type} via /brand-images/pick. Client home hero now shows a real cinematic aviation image (verified: pilot in hotel hallway). Workout screen has a 180px branded banner above the title. Coach overview has a new IMAGES nav button. All 9 seed images generated cleanly on first try (~25s for the batch). Also completed the equipment picker emoji sweep (18 items — dumbbell/barbell/bicycle/boat/bed/etc). No backend regressions expected — this is purely additive (new module + new collection). Please run backend tests on all 8 brand-images endpoints (auth gating, seed idempotency, pick with all context perms, stream with dual auth, patch/delete). Test credentials in /app/memory/test_credentials.md. Note: seed makes 9 real Nano Banana calls (~25s + LLM key cost). To avoid re-hitting the model in tests, mock or re-use existing entries where possible."


##====================================================================
## §34 · Phase 2.5 — Personal Imagery + wider card wiring + startup fix
##====================================================================

backend:
  - task: "POST /api/brand-images/personalise — client-driven personalised image request"
    implemented: true
    working: true
    file: "backend/feature_brand_images.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Authenticated client can request a personalised image. Server composes a Nano Banana prompt from their profile (job_title → role, preferred_visual_gender, goal, workout_type override, phase, and an optional freeform prompt_hint). Rate limit: 409 if any prior image for this user is pending/generating/pending_approval. Image lands as `pending_approval` (NOT ready) so a coach must approve via PATCH status=approved before /pick will serve it. Verified end-to-end: personalise → status transitions pending → generating → pending_approval; coach approve → status ready; client /pick returns the personal image with personalised=true."
  - task: "GET /api/brand-images/personal/mine — my images"
    implemented: true
    working: true
    file: "backend/feature_brand_images.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Returns the current user's personalised images (any status) sorted newest first."
  - task: "GET /api/brand-images/pending-approval — coach queue"
    implemented: true
    working: true
    file: "backend/feature_brand_images.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Coach-only. Returns all images awaiting approval."
  - task: "GET /api/brand-images — filters + user-scoped personal visibility"
    implemented: true
    working: true
    file: "backend/feature_brand_images.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Added include_pending and include_personal query params. By default users only see the shared library + their own personalised entries; coaches can pass include_personal=true to see everyone's."
  - task: "PATCH /api/brand-images/{id} — approve/reject support"
    implemented: true
    working: true
    file: "backend/feature_brand_images.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "PatchBody status now accepts 'rejected' which soft-hides + deletes the file. 'approved' still maps to 'ready'."
  - task: "GET /api/brand-images/pick — personal-first ordering"
    implemented: true
    working: true
    file: "backend/feature_brand_images.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Priority: (1) this user's own approved personalised images (best context match wins, then most recent), (2) library images (personalised_for is null). Returns `personalised: bool` on the response."
  - task: "Startup reconciliation of stale generating rows"
    implemented: true
    working: true
    file: "backend/feature_brand_images.py, backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "Added _reconcile_stale_jobs() that flips any 'generating'/'pending' rows to 'failed' with error='server restart'. Invoked from server.py @app.on_event('startup'). Fixes the 409 lockout observed by testing agent when the server restarts mid-generation."

frontend:
  - task: "AIHeroImage wired into event countdown card"
    implemented: true
    working: true
    file: "frontend/app/(client)/home.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "Event countdown card (Abu Dhabi Marathon · 104 DAYS TO RACE) now renders a branded runner-on-runway image as backdrop. Passes context={event, goal:event_type, phase:phase_info.phase}. Screenshot verified."
  - task: "AIHeroImage wired into StandbyStatusCard"
    implemented: true
    working: true
    file: "frontend/src/components/StandbyStatusCard.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "Standby card gained a 110px banner-image header with the standby_readiness image (radar icon + STANDBY MODE overlay). Body wrapped in a padded View so existing sections still work."
  - task: "PersonalImageryCard on client profile"
    implemented: true
    working: true
    file: "frontend/src/components/PersonalImageryCard.tsx, frontend/app/(client)/profile.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "New card at the bottom of the client's PROFILE section. Freeform prompt_hint input, GENERATE MY PERSONAL IMAGE button, live list of my personalised images with status labels (QUEUED / GENERATING / AWAITING COACH APPROVAL / READY · ON YOUR HOME SCREEN / FAILED). Auto-polls every 3s while a job is running. Backend rate-limit (409) reflected in disabled state."
  - task: "Coach brand-images admin — AWAITING APPROVAL section"
    implemented: true
    working: true
    file: "frontend/app/coach/brand-images.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "Coach screen now loads /brand-images/pending-approval alongside the library and renders a separate 'AWAITING APPROVAL' block per card with APPROVE (green) / REJECT (muted) / REGEN buttons. Cards are ringed in amber to make the queue obvious. Backend PATCH approved→ready, rejected→hidden."

test_plan:
  current_focus:
    - "POST /api/brand-images/personalise (round-trip + 409 rate-limit + prompt composition from profile)"
    - "GET  /api/brand-images/personal/mine"
    - "GET  /api/brand-images/pending-approval (coach only)"
    - "PATCH /api/brand-images/{id} status=approved and status=rejected (approved→ready, rejected→hidden + file unlinked)"
    - "GET  /api/brand-images/pick prefers user's approved personal over library entries"
    - "Startup reconciliation flips lingering 'generating' rows to 'failed'"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: "§34 Phase 2.5 shipped. Backend: personalise + personal/mine + pending-approval endpoints, pick now prefers user's approved personalised images, PATCH accepts approved/rejected, and startup reconciliation clears stuck 'generating' rows. Frontend: AIHeroImage wired into the event countdown card and the StandbyStatusCard, PersonalImageryCard added to client profile, coach brand-images admin now has an APPROVE/REJECT queue for pending_approval images. Full round-trip verified manually — client generated 'marathon build after long-haul' → pilot doing hamstring recovery in an airport-view gym with a CrewFit water bottle (681KB PNG) → coach approved → /pick returned personalised=true for that client. Please regression test the 6 new/extended endpoints plus role gating: client can call personalise/mine and their own generate; coach only can access pending-approval + PATCH status. LLM cost: each real personalise call = 1 Nano Banana generation (~$0.03), so use the shared existing image for most tests and only trigger 1 fresh personalise if needed."


##====================================================================
## §35 — Unified Exercise Content Library
##====================================================================

backend:
  - task: "feature_exercise_content.py — unified exercise CRUD + approvals"
    implemented: true
    working: "NA"
    file: "backend/feature_exercise_content.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "New module + `exercises_v2` collection (old exercises/videos untouched — Phase 3 migration). 11 endpoints: POST/GET/PATCH/DELETE /exercise-content (list has q + category + training_type + body_area + status + missing_content + used_tomorrow + approved_only filters), POST /{id}/approve with scope ∈ {all, images, coaching, video, mark_live, needs_update}, POST /{id}/generate-image (slot ∈ primary|start|end — kicks off Nano Banana job with new exercise style: solid black bg, athletic person in dark kit, softly shaded face, equipment visible, portrait 3:4), GET /images/{id}/stream (dual auth), GET /images/{id}, GET /{id}/log (change history), POST /scan-todos (bumps used_in_tomorrow_workouts_count then creates coach tasks via _create_coach_task for missing artwork/coaching/video/approval — dedupe by task_type + payload.exercise_id + open/snoozed status). Status enum: Draft/Needs Review/Artwork Needed/Coaching Points Needed/Video Needed/Ready for Approval/Approved/Live/Needs Update/Rejected/Archived. Startup reconciliation _reconcile_ex_stale wired via server.py on_event('startup'). Manual smoke test: 3 exercises created (Band Lateral Raise, Deep Bodyweight Squat, World's Greatest Stretch)."
  - task: "New exercise-image style prompt template"
    implemented: true
    working: true
    file: "backend/feature_exercise_content.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "EXERCISE_STYLE constant + _build_ex_prompt compose slot-specific prompts (START POSITION / END POSITION / primary demonstration) with body area emphasis, equipment inline, and softly-shaded face instruction. Female/male toggle via body.female."

frontend:
  - task: "Client · Adaptive Atlas Insights + Sunday check-in enrichment (Phase 5)"
    implemented: true
    working: true
    file: "frontend/app/nutrition/insights.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "New /nutrition/insights route (big card for the latest insight + history list). Nutrition home now shows a WEEKLY ATLAS INSIGHT preview card between the daily Atlas tip and the quick-actions grid — clicking navigates to the full screen. Screenshot verified: card renders 'Only one day logged in fourteen days...' with 'REVIEW' badge + 'AWAITING LOUIS' + 'VIEW ALL' link. The full /insights screen shows big action-tag badge (KEEP/SIMPLIFY/PROTEIN FOCUS/ADJUST CALORIES/TRAVEL STRATEGY/FLAGGED FOR REVIEW), atlas_summary, MAIN ISSUE + SUGGESTED ACTION + optional ATLAS TARGET SUGGESTION card, and 4-stat mini row (logged/avg kcal/avg P/low-P days). Refresh button in header force-generates a new insight. Empty state includes a GENERATE ANYWAY button. Sunday check-in (/app/checkin.tsx) now also fetches /nutrition/checkin/questions and appends the goal-personalised nutrition question block."

  - task: "Coach · Nutrition dashboard — pending Atlas insights (Phase 5)"
    implemented: true
    working: true
    file: "frontend/app/coach/nutrition.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Coach nutrition dashboard extended with (a) a pending-reviews bar at the top ('23 pending Atlas reviews · OPEN'), (b) a scan-icon in the header (testID `coach-nutr-scan`) that triggers /coach/nutrition/scan-todos with a toast, (c) a page-sheet modal listing every pending insight per-client with action badge, atlas_summary, main_issue, suggested_action, optional target-change card, and DISMISS / APPROVE + APPLY (or MARK REVIEWED) buttons. Approve+apply writes a new nutrition_targets row with target_type='coach_from_atlas'; dismiss just marks the insight status. Screenshot verified end-to-end w/ 23 pending reviews visible."

  - task: "Client · Travel Food Guidance suite (Phase 4)"
    implemented: true
    working: true
    file: "frontend/app/nutrition/travel.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "All 4 SOON placeholders replaced with real Atlas-powered screens plus a shared travel-shared.tsx component library. (a) /nutrition/decision — situation chip picker (11 options), hunger/next-context chips, notes, primary CTA calls /travel/decision, renders ResultCard + DO THIS / PROTEIN-LED / AVOID / hydration blocks. (b) /nutrition/airport — airport-code text input + time-available chips + hunger + next-context, renders BEST/OK/AVOID/SNACK BACKUP + hydration + short-time card. (c) /nutrition/timing — home-tz + current-tz chips (auto-detects current via Intl.DateTimeFormat), flight-context chips, sleep HH:MM input, next-workout chips, renders headline + MEAL PLAN timeline + caffeine/hydration/post-flight tiny cards. (d) /nutrition/travel — 11-topic grid (airport_strategy, hotel_breakfast, hotel_buffet, crew_meal, long_haul, night_flight, early_start, fat_loss_layover, muscle_gain_travel, endurance_fuelling, hydration_caffeine); tap → modal with one_liner + steps + watchouts + goal-tailored 'FOR YOUR GOAL: FAT LOSS' card. Every screen has a ContextRibbon showing goal + kcal/protein remaining. SOON pills removed from all 4 home ActionBtn. Screenshot verified: NIGHT FLIGHT decision returned 'Skip the meal, prioritize rest' with populated DO/AVOID lists."

  - task: "Client · AI Photo Meal Scan (Phase 3)"
    implemented: true
    working: true
    file: "frontend/app/nutrition/photo-scan.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Placeholder replaced with the real AI photo meal scan flow. Pick phase: MEAL vs HOTEL BUFFET mode cards, MEAL TYPE chip row, TAKE PHOTO (camera) + PICK FROM LIBRARY buttons (upload only on web). Uses expo-image-picker w/ base64:true, request permission on demand, Open-Settings fallback when canAskAgain=false. Analysing phase: shows the picked image + spinner + Atlas coaching copy ('5–15 sec'). Review phase: photo hero w/ HIGH/MEDIUM/LOW confidence pill, Atlas estimate tip card, 4 macro cards with +/- steppers AND direct-edit numeric inputs, editable items list (add/remove/edit name+portion), meal-type chip re-pick, Save-as-Favourite. Warnings surfaced in amber card when present. LOG MEAL button calls PATCH /photo/{id}/patch (persist edits) → POST /photo/{id}/save-log (write nutrition_logs). SOON pill removed from home ActionBtn."

  - task: "Client · Barcode Scanner (Phase 2)"
    implemented: true
    working: true
    file: "frontend/app/nutrition/barcode.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Placeholder replaced with the real Barcode scanner. Native: full-screen CameraView (expo-camera v17) with onBarcodeScanned covering EAN-13/8, UPC-A/E, Code-128/39, QR. Custom-drawn scan-frame + corner brackets + auto duplicate debounce. Contextual pre-permission screen w/ Open-Settings fallback if canAskAgain=false. Product review card: image, brand, source badge, live-calculated macros × servings, 44px +/- serving buttons + [0.5, 1, 1.5, 2]x quick chips, meal-type chip row, Save-as-Favourite toggle, LOG MEAL primary button. Not-found fallback: routes to /nutrition/log?barcode=... with barcode pre-filled in notes and Save-as-Favourite pre-ticked. Web: manual barcode-entry field (Playwright test verified: EAN 5449000000996 → Coca-Cola review card renders w/ 139 kcal, 35g carbs). SOON pill removed from home ActionBtn."

  - task: "Client · Nutrition Centre (Phase 1)"
    implemented: true
    working: true
    file: "frontend/app/nutrition/index.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Phase 1 of the travel-aware Nutrition Centre. New /nutrition/index (mounted on the existing NUTRITION tab). Shows today's calorie + protein rings, carbs/fats/hydration micro-cards, 3-tap hydration ticker (+250/+500/+750/-250ml), Atlas insight card (Claude Sonnet 4.5), quick-actions grid (Manual Log LIVE + Barcode/Photo/Favourites/Travel/Decide/Airport/Timing SOON pills), weekly summary bar-chart, and a safety disclaimer. Additional routes: /nutrition/log (full form with meal-type + roster-context chips + Save-as-Favourite + all macros), /nutrition/history (7-day grouped), /nutrition/targets (read-only view with Atlas-default vs Coach-set badge + safety copy), /nutrition/favourites (tap-to-log). Placeholders: /nutrition/barcode, /photo-scan, /travel, /decision, /airport, /timing. Cross-platform confirm+toast helper new: /src/lib/ux.tsx (fixes RN-Web Alert.alert bug across the whole app; ToastHost mounted in root _layout.tsx). Legacy (client) nutrition tab now re-exports the new home."

  - task: "Coach · Nutrition Dashboard (Phase 1)"
    implemented: true
    working: true
    file: "frontend/app/coach/nutrition.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "New /coach/nutrition route. One-row-per-client cards showing goal, targets, today's kcal+protein, 7-day averages, days-logged, and low-protein/no-logs/coach-set/Atlas-default badges. Tap → deep-dive modal with recent 7-day logs list, coach notes (create + list), and an Edit Targets modal (goal chips + calories/protein/carbs/fats/hydration numeric inputs). All values pass through backend safety floors (1500 kcal / 60g protein / 1500ml). Coach overview screen now has a new NUTRITION button (Ionicons nutrition-outline) between EXERCISES and the notification bell."

  - task: "Alert.alert web bug fix (Exercise Content Archive + Scan-todos)"
    implemented: true
    working: true
    file: "frontend/app/coach/exercise-content.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Replaced Alert.alert-based Archive confirm and Scan-todos success alerts with new cross-platform confirm() and toast() from @/src/lib/ux. Native (iOS/Android) still uses Alert.alert internally; web now uses a real Modal-based confirm and animated toast (mounted in root _layout.tsx via <ToastHost/>)."

  - task: "Coach · Exercise Content Library screen"
    implemented: true
    working: true
    file: "frontend/app/coach/exercise-content.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "New /coach/exercise-content route. Two-pane layout: left = filter tabs (ALL/WARM-UP/MOBILITY/STRENGTH/CARDIO/REHAB/COOLDOWN/TOMORROW/MISSING/APPROVED) + search + list with status dots + MISSING badges + TMW badges; right = detail with START/END/PRIMARY image slots (each with GENERATE/REGEN button), coaching points, common mistakes, video card with status badge, and 6 approval buttons (APPROVE ALL, IMAGES, COACHING, VIDEO, MARK LIVE, NEEDS UPDATE). Bell icon in top-right triggers POST /exercise-content/scan-todos which reports how many coach tasks were created. Coach overview now has a new EXERCISES nav button next to IMAGES."
      - working: true
        agent: "main"
        comment: "Phase-2 UI wiring complete. Added: (a) '+' header button that opens CreateExerciseModal (name/category/training_type/body_area/equipment chips → POST /api/exercise-content), (b) SectionHeader with EDIT button for COACHING POINTS, COMMON MISTAKES, ALTERNATIVES, CLIENT INSTRUCTIONS, VIDEO URL — each opens the appropriate modal and PATCHes the exercise, (c) reusable EditListModal (add/remove/reorder items) + EditTextModal (single/multiline field), (d) image polling: on generate-image success, poll /images/{id} every 3s until ready/failed and refresh detail, (e) CHANGE LOG button opens ChangeLogModal fetching /exercise-content/{id}/log, (f) ARCHIVE button with confirm → DELETE /exercise-content/{id}. New reusable modal component at frontend/src/components/coach/ExerciseEditModals.tsx. Also fixed filter tabs stretching bug (added flexGrow:0 maxHeight:46 and alignItems:center)."

test_plan:
  current_focus:
    - "POST /api/exercise-content (create) — admin only; default flags applied"

  - agent: "main"
    message: "§41 shipped — Backlog Sweep #1: Media Storage Abstraction (S3/R2) + Exercise Library data migration. Backend: new storage.py with StorageDriver interface, DiskDriver (default) + R2Driver (auto-activates when R2_* env vars present). feature_nutrition_photo.py refactored to write via storage.write_bytes() and serve via 302→presigned when R2 is live. New feature_admin_migrations.py exposes admin-only ops routes for both features: GET/POST /admin/storage/{status,backfill}, GET/POST /admin/exercises/migrate{/status}. Exercise migration ran live: 248 v1 exercises → 248 upserted into exercise_content with migrated_from_v1=true, status=draft, approved_*=pending; 2nd run confirmed 0 inserts / 248 updates (idempotent). All in-flight features (nutrition today, exercise-content list, photo scan 404 path) still return healthy status codes and no new errors in backend logs. TO ACTIVATE R2: paste R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET into backend/.env (optionally R2_PUBLIC_HOSTNAME + R2_ENDPOINT_URL), restart backend, then POST /admin/storage/backfill?dry_run=false to move existing media. TESTING: this is an infra/ops delivery — no user-facing screens changed. Backend sanity was covered by curl. No frontend flows changed. Do NOT re-test Phase 1-5 (all green)."
    - "GET /api/exercise-content with each filter combination — search + used_tomorrow + missing_content + approved_only"
    - "PATCH /api/exercise-content/{id} — status enum guard; content_status.coaching_points auto-updates when coaching_points array set"
    - "POST /api/exercise-content/{id}/approve — each scope transitions the right fields"
    - "POST /api/exercise-content/{id}/generate-image slot=start|end|primary — kicks off Nano Banana and updates the correct slot key on the parent doc"
    - "GET /api/exercise-content/images/{id}/stream — dual auth"
    - "POST /api/exercise-content/scan-todos — creates dedup'd tasks for exercises used tomorrow with missing content"
    - "Role gating: client hitting admin endpoints (create/patch/delete/approve/generate/scan) → 403"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"

  - agent: "main"
    message: "§41 hotfix — Coach Library screen was showing 0 exercises after the migration. Two root causes: (1) my initial migration wrote to `exercise_content` collection but the Exercise Content Library reads from `exercises_v2` (naming mismatch inside feature_exercise_content.py); (2) the legacy /coach/library screen still hit v1 /api/exercises which returned 401 when token expired. Fix: pointed migration at db.exercises_v2 (correct target), added a `legacy_category` field so PUSH/PULL/LEGS/CORE filter chips continue to work post-migration, and refactored /coach/library UI to read from /api/exercise-content (with legacy /exercises as fallback). Also fixed the horizontal filter tabs stretching vertically on web (same bug I fixed on /coach/exercise-content earlier). Cleaned up the 248 misplaced rows in exercise_content and re-ran migration → 248 inserted into exercises_v2. Live verified: /library now shows 256 exercises (248 migrated + 8 hand-created) with categories (LEGS/PUSH/PULL/CORE/…) preserved, YouTube video previews, delete + V2-upgrade + migration-banner all present. No frontend breakage elsewhere."
    message: "§35 Phase 1 shipped. Unified Exercise Content Library backend (feature_exercise_content.py) + coach admin console (/coach/exercise-content). 11 endpoints, new exercise-specific Nano Banana prompt (solid black bg, softly-shaded face, portrait 3:4), start/end/primary image slots per exercise, one-click approval scopes, change-log, and a scan-todos endpoint that plugs into the existing Coach To-Do Feed for demand-driven approval requests. Old exercises + videos collections deliberately left alone (Phase 3 migration). Screenshot verified: 3 seed exercises visible, DRAFT+MISSING status badges, right pane detail with START/END/PRIMARY slots + APPROVE controls, filter tabs and search wired. Please test all 11 endpoints — auth gating, filters, approval scope transitions, and one image generation round-trip (each call ~$0.03). scan-todos will only create tasks when there are actual workouts scheduled tomorrow referencing exercises_v2 — right now the seeded exercises are not yet referenced so scan-todos returns created=0, which is correct."
  - agent: "main"
    message: "§35 Phase 2 shipped — Coach Exercise Content full UI wiring. New file frontend/src/components/coach/ExerciseEditModals.tsx (EditListModal, EditTextModal, CreateExerciseModal, ChangeLogModal). exercise-content.tsx now has (1) '+' header button → CreateExerciseModal → POST /api/exercise-content, (2) EDIT buttons next to Coaching Points/Common Mistakes/Alternatives/Client Instructions/Video URL sections → PATCH the exercise, (3) generate-image now polls /images/{id} every 3s until ready and auto-refreshes the detail, (4) CHANGE LOG button → GET /exercise-content/{id}/log rendered in modal, (5) ARCHIVE button with confirmation → DELETE /exercise-content/{id}. Also fixed a filter-tab vertical-stretch bug on web. Please run FRONTEND tests on this screen: login as coach (coach@crewfit.com / Coach123!), navigate to Coach Overview → EXERCISES button → verify: create flow, edit each list/text field, approve controls, image generation polling (Nano Banana ~15s), change log, and archive. Do not need to re-test the backend endpoints — they were tested in iteration 35 and passed."

  - agent: "main"
    message: "§36 shipped — CrewFit Nutrition Centre (Phase 1) + Alert.alert web bug fix. Backend: new feature_nutrition.py w/ 14 endpoints (targets, logs CRUD, hydration, favourites, today totals, week summary, Atlas tip via Claude Sonnet 4.5, coach dashboard endpoints w/ safety guardrails). Frontend: /nutrition tab now shows premium home screen w/ dual-metric rings, hydration ticker, Atlas insight (verified: Sonnet 4.5 returned a real coaching sentence), quick actions, weekly bar chart. Supporting routes: /nutrition/log (manual form), /nutrition/history (7-day grouped), /nutrition/targets (client read), /nutrition/favourites, plus 6 Phase-2/3/4 placeholder screens marked SOON. New coach screen /coach/nutrition (row-per-client + deep-dive modal + EDIT TARGETS modal + add-note). Coach overview gained NUTRITION nav button. New cross-platform ux helper (confirm() + toast() + <ToastHost/>) fixes RN-Web Alert.alert silent-failure — applied to Exercise Content Archive + Scan-todos."

  - agent: "main"
    message: "§39 shipped — Nutrition Phase 4 (Travel Guidance). Backend: new feature_nutrition_travel.py with 5 endpoints (decision / airport / timing / guide / context) all routed through Claude Sonnet 4.5 with a shared strict-JSON prompt, banned-word sanitizer, and per-day cache in nutrition_travel_cache. Frontend: 4 new premium screens replacing the SOON placeholders + one shared travel-shared.tsx component (Screen / TravelHeader / LoadingBlock / ContextRibbon / ResultCard / ListBlock / Chips / travelStyles). All screens auto-fetch /travel/context on mount so kcal/protein remaining is always visible. Screenshot-verified end-to-end for Atlas Decide (night_flight → 'Skip the meal, prioritize rest'). TEST: (a) 5 endpoints incl 400 on invalid situation/topic and 401 without auth, (b) cache hit returns same payload with cached:true on 2nd call, (c) banned-word sanitizer clamps 'cheat' etc., (d) all 4 frontend screens (decision / airport / timing / travel guides) — pick chips, submit, verify Atlas response renders (blocks are non-empty, confidence pill shows). Do NOT re-test Phases 1/2/3. Fresh caches so first call is real LLM. Roughly 15s per Atlas call; give timeouts of 30s."

  - agent: "main"
    message: "§40 shipped — Nutrition Phase 5 (Adaptive insights + Sunday check-in enrichment + Coach To-Do integration). Closes out the full Nutrition Centre spec. Backend: feature_nutrition_insights.py with 9 endpoints (client insights CRUD + coach approve/dismiss/scan-todos). Adaptive analyser looks at 14-day rolling window (logs, hydration, protein trend, layover count, tool usage) and picks ONE of 6 actions via Claude Sonnet 4.5 with a deterministic rule-based fallback. Dedupes per (user, week_start). Sanitises banned words. Coach scan-todos creates nutrition_review coach_tasks with dedupe (verified: 23 clients scanned → 22 tasks created; 2nd run creates 0). Frontend: (a) new /nutrition/insights screen with big action-badge card + previous-insights list + Refresh button, (b) Weekly Atlas Insight preview card on /nutrition home (screenshot-verified: renders correctly with REVIEW badge + AWAITING LOUIS + VIEW ALL link), (c) Sunday check-in fetches /nutrition/checkin/questions and appends 5-7 goal-personalised nutrition questions to the form, (d) coach nutrition dashboard has a '23 pending Atlas reviews · OPEN' bar + scan-icon in header + page-sheet modal with DISMISS / APPROVE + APPLY buttons (approve+apply writes new nutrition_targets row with target_type='coach_from_atlas'). TEST: backend all 9 endpoints, verify scan-todos dedupe, verify approve+applyTargetChange writes a target row. Frontend: (i) client home Weekly Insight card, (ii) coach dashboard pending bar + approve/dismiss modal. TESTING_TYPE: both. Do NOT re-test Phase 1-4."


# ═════════════════════════════════════════════════════════════════════
# ITER 81 — MASTER FIX PROMPT · PHASE 1 · HOTEL SYSTEM
# ═════════════════════════════════════════════════════════════════════

backend:
  - task: "Hotel System · Layover vs Turnaround classifier + hotel_profiles endpoints"
    implemented: true
    working: true
    file: "backend/feature_hotel_system.py, backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Phase 1 of Master Fix Prompt shipped. New feature_hotel_system.py module with (a) compute_layover_hours(day, next_day) computing hours between duty_end_time and next report_time, (b) classify_stay() returning layover/turnaround/home/off/flight/unknown with 18h threshold, (c) resolve_gym_equipment() mapping gym_type → equipment presets (full_gym / cardio_only / basic / bodyweight_only / none / unknown), (d) is_bodyweight_only() gating for safe fallback, (e) confidence_score() / is_low_confidence() for coach review queue, (f) reason_for() returning client-facing 'why this changed' strings. Extended HotelBody model (server.py) with gym_type, safe_outdoor_run, verified_by_coach (coach-only). New endpoints: GET /api/hotels/lookup?query= (unified fuzzy search), POST /api/hotels/{hid}/confirm (client-side confirmation bumps confidence), PATCH /api/hotels/{hid}, GET /api/hotels/pending-for-today (upcoming layovers needing hotel), GET /api/coach/hotels/review-queue (coach-only), POST /api/coach/hotels/{hid}/verify (coach-only). Wired hotel context into feature_workout_fallback.build_template_plan(hotel_lookup=...) — Turnaround (<18h) → forced mobility session; Layover with unknown/bodyweight hotel → bodyweight-safe stub; Layover with known gym → hotel gym stub. All 5 callsites (server.py x2, feature_programme_quality, feature_roster_confirmation, feature_coach_workout_editor) now preload hotels via load_hotel_lookup_for_roster(). Added bodyweight-safe strength_support template variant. 27/27 phase 1 unit + integration tests pass (backend/tests/test_iter81_phase1_hotel_system.py). No lint errors. No regressions vs pre-existing failures in iter58/64/68/79."

frontend:
  - task: "Hotel Setup Card (client home) + /hotel-setup screen"
    implemented: true
    working: true
    file: "frontend/src/components/HotelSetupCard.tsx, frontend/app/hotel-setup.tsx, frontend/app/(client)/home.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "New HotelSetupCard component on client /home — polls /api/hotels/pending-for-today and appears when upcoming (next 7 days) layovers either have no hotel attached OR low-confidence (<0.6) hotel that needs re-confirmation. Card shows layover city + count of pending, taps into /hotel-setup?date=YYYY-MM-DD. New /hotel-setup screen with 3-step flow: (1) hotel name (fuzzy search via /hotels/lookup showing coach-verified badge) + city + country, (2) gym type picker (5 cards: full_gym / cardio_only / basic / bodyweight_only / none) applying sensible equipment presets, (3) equipment chip toggles for 13 items (dumbbells / barbell / bench / cable_stack / etc), outdoor-run safety toggle, notes textarea. Save flow: upsert /hotels → attach to roster day via /roster/{rid}/hotel → confirm via /hotels/{id}/confirm to bump confidence. Uses theme.color.brand (crimson) and testIDs on all interactive elements. Lint clean, expo restarted OK, /home renders."

test_plan:
  current_focus:
    - "Backend: compute_layover_hours math (20h, 8h, missing data)"
    - "Backend: classify_stay 18h threshold — layover ≥18h, turnaround <18h, flight with short/long gap"
    - "Backend: is_bodyweight_only for None hotel, gym_available=False, gym_type=unknown+empty equipment, full_gym"
    - "Backend: resolve_gym_equipment presets vs explicit equipment"
    - "Backend: reason_for returns correct REASON_STRINGS for turnaround / unknown-hotel / bodyweight-only / confirmed"
    - "Backend: POST /api/hotels creates with gym_type + safe_outdoor_run; equipment persisted; confidence=0.5 initial"
    - "Backend: POST /api/hotels/{id}/confirm bumps confidence, merges equipment (does not clobber), sets gym_type"
    - "Backend: PATCH /api/hotels/{id} patches without bumping submissions"
    - "Backend: GET /api/hotels/lookup?query= returns rows sorted by confidence desc, max 15"
    - "Backend: GET /api/hotels/pending-for-today returns [] when no roster, layover days with missing/needs_confirm status"
    - "Backend: GET /api/coach/hotels/review-queue coach-only (403 for client), returns low-confidence rows"
    - "Backend: POST /api/coach/hotels/{hid}/verify coach-only, sets verified_by_coach + verified_at + verified_by + bumps confidence"
    - "Backend: feature_workout_fallback.build_template_plan(hotel_lookup=...) — Turnaround = mobility, Unknown-hotel-layover = bodyweight strength_support, Known gym layover = Hotel Gym Workout"
    - "Frontend: /home shows HotelSetupCard when /hotels/pending-for-today returns rows; hidden when empty"
    - "Frontend: tapping card navigates to /hotel-setup?date=..."
    - "Frontend: /hotel-setup 3-step form — name search (verified-badge for coach-verified rows), gym type picker applies preset, chip toggles work, save flow upserts hotel + attaches to roster + confirms"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: "Iter 81 shipped Phase 1 of the MASTER FIX PROMPT (Hotel System). New feature_hotel_system.py module (~230 LOC) with pure helpers for layover/turnaround detection (18h threshold), gym-type presets, bodyweight-only routing, confidence scoring, and client-facing 'why this changed' reason strings. Extended HotelBody + wired 6 new endpoints (lookup / confirm / patch / pending-for-today / coach review queue / coach verify). Wired hotel context into all 5 build_template_plan callsites so template fallbacks now respect layover vs turnaround AND known vs unknown hotel gyms — turnaround yields mobility only, unknown hotel yields bodyweight-safe strength support, known gym yields Hotel Gym Workout with equipment matching. Frontend: HotelSetupCard on /home (auto-hides when no pending layovers) + full /hotel-setup screen (name fuzzy search / gym type presets / equipment chips / outdoor-run toggle / notes) that saves via upsert→attach→confirm. 27/27 phase 1 backend tests pass. No regressions vs pre-existing test failures (iter58/64/68/79 — same 10 tests failing before + after). Ready for backend + frontend testing. TESTING_TYPE: both. Credentials: client@crewfit.com / Client123! and coach@crewfit.com / Coach123!. NEXT PHASES (waiting on user confirmation): Phase 2 — Strict Equipment Matching (hard validation gates in feature_v2_resolver); Phase 3 — Reactive progression + Your Progress card; Phase 4-6 — coach dashboard hotel review queue UI, Marathon adjustments, final 15 test cases."

# ═════════════════════════════════════════════════════════════════════
# ITER 81 — MASTER FIX PROMPT · PHASE 2 · STRICT EQUIPMENT MATCHING
# ═════════════════════════════════════════════════════════════════════

backend:
  - task: "Strict Equipment Matching — hard validation gates in resolver"
    implemented: true
    working: true
    file: "backend/feature_equipment_matcher.py, backend/feature_v2_resolver.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Phase 2 of Master Fix Prompt shipped. New feature_equipment_matcher.py module with: (a) CANONICAL_EQUIPMENT + EQUIPMENT_ALIASES lookup, (b) FULL_GYM_EXPANSION preset (dumbbells/barbell/bench/cable_stack/…), (c) EQUIPMENT_REGEXES list with ~35 patterns covering bench-press family, cable, machine, dumbbell/kettlebell, pull-up, cardio, bands, TRX, box, med ball, (d) required_equipment(exercise) — reads library equipment_type first then regex-matches on name, (e) validate_exercise_equipment(exercise, available) returns {passes, required, missing, reason} with friendly human strings ('Requires a bench — not available at your current setup.'), (f) normalise_available(items) accepts list OR dict form (hotel_profiles map) and expands 'hotel_gym' marker to FULL_GYM_EXPANSION, (g) enforce_equipment_gate(workout, available, hotel_context, hotel_name) mutates exercises in place with equipment_check='fail' + equipment_reason + equipment_required, and sets workout.needs_coach_review=true + workout.change_reason='Hotel gym is limited at Marina Bay Sands — 2 exercise(s) need coach review: X, Y. Louis will review before you train.'. Wired into feature_v2_resolver.apply_resolver_to_workouts: after resolving each workout, computes available equipment based on classify_stay(day, next_day) — layover with known hotel → resolve_gym_equipment(hotel_doc); layover with unknown hotel → {bodyweight}; home day → client profile equipment. New stats: equipment_failures, workouts_needs_review. 25/25 phase 2 unit tests pass. No regressions."

frontend:
  - task: "'Why this changed' UI — reason pill on home + banner + eq-warn per exercise"
    implemented: true
    working: true
    file: "frontend/app/(client)/home.tsx, frontend/app/workout/[id]/index.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Client-facing 'Why this changed' visibility: (a) on client /home each workout row now shows a compact reason pill under the meta line when workout.change_reason is set (testID: workout-reason-<id>), (b) on the workout detail screen /workout/[id]/ a full 'WHY THIS CHANGED' brand-tinted banner sits above the WHY THIS SESSION rationale block (testID: workout-change-reason), (c) each individual exercise card in the workout preview shows an amber warning below the meta line when ex.equipment_check==='fail' with the specific equipment_reason (testID: ex-eq-warn-<idx>). Uses theme.color.brand for change-reason and theme.color.amber for equipment warnings. Lint clean."

test_plan:
  current_focus:
    - "Backend: required_equipment name-based regex hits (barbell bench press, dumbbell bench press, cable row, pull-up with hyphen, dumbbell curl, kettlebell swing, RDL multi-option)"
    - "Backend: required_equipment reads library equipment_type FIRST (skips regex when explicit)"
    - "Backend: validate_exercise_equipment — bodyweight pass, missing bench fail with reason, any-of match passes, cable fail with reason"
    - "Backend: normalise_available — list with aliases (DB, Barbell, no equipment), dict from hotel (False values excluded), 'hotel_gym' marker expands, None input → {bodyweight} only"
    - "Backend: enforce_equipment_gate — all bodyweight passes no flag; mixed workout flags needs_coach_review with change_reason listing failed names; hotel_context uses 'Hotel gym is limited at <name>' prefix; full gym at layover all pass"
    - "Backend integration: feature_v2_resolver.apply_resolver_to_workouts now sets stats.equipment_failures + stats.workouts_needs_review, and workouts on layover days with unknown hotels default to bodyweight-only equipment"
    - "Frontend: /home workout row shows reason pill when change_reason is set"
    - "Frontend: /workout/[id]/ shows WHY THIS CHANGED banner and per-exercise equipment warnings"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: "Iter 81 Phase 2 shipped — Strict Equipment Matching. New feature_equipment_matcher.py (~275 LOC) with equipment taxonomy, ~35 regex patterns, and pure helpers required_equipment / validate_exercise_equipment / normalise_available / enforce_equipment_gate. Wired into feature_v2_resolver.apply_resolver_to_workouts — after LLM matching, each workout is validated against the correct equipment set (home vs hotel vs bodyweight), and any exercise that requires kit the client doesn't have gets equipment_check='fail' + reason string, and the whole workout gets needs_coach_review=true with a client-facing change_reason. Client-facing UI: reason pill on /home + full banner on /workout/[id] + per-exercise amber warning. 25/25 phase 2 tests pass. Combined phases: 63/63 tests pass. TESTING_TYPE: both. Ready for testing_agent verification. NEXT PHASE (Phase 3): Reactive progression + Your Progress card."

# ═════════════════════════════════════════════════════════════════════
# ITER 81 — MASTER FIX PROMPT · PHASE 3 · REACTIVE PROGRESSION + YOUR PROGRESS
# ═════════════════════════════════════════════════════════════════════

backend:
  - task: "Reactive weekly progression + snapshot storage"
    implemented: true
    working: true
    file: "backend/feature_progression.py, backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Phase 3 of Master Fix Prompt shipped. New feature_progression.py module with: (a) iso_week_bounds() and week_key() helpers, (b) compute_status(workouts, week_start, week_end) — pure rule engine returning progression_status: progressing_well | maintain | reduce_load | deload, with STATUS_LABELS (PROGRESSING / STEADY / PULL BACK / DELOAD), STATUS_COPY (client-facing reason), STATUS_COACH_NOTE. Rule order: 2+ very-high RPE (≥9.5) + n_completed≥3 → deload; adherence<60% → reduce_load; avg_rpe≥9 → reduce_load; key_missed≥1 & adherence<80% → reduce_load; adherence≥80% & 6≤rpe≤8.5 → progressing_well; else → maintain. (c) compute_and_store_week(db, user_id, week_date, force) — persists to progression_snapshots collection with {user_id, week_key, status, reason, metrics, week_start, week_end, computed_at}. (d) on_workout_completed(db, user, workout) trigger — called from POST /api/workouts/{wid}/complete; ONLY snapshots when this workout was the LAST planned session of the ISO week (no remaining incomplete planned workouts). (e) latest_snapshot() + snapshot_history() readers. New endpoints: GET /api/progress/current (returns latest or {}), GET /api/progress/history?weeks=8 (last N weeks), POST /api/progress/recompute (manual refresh), GET /api/coach/clients/{cid}/progress/current + /history (coach-only). 19/19 phase 3 unit + endpoint tests pass. No regressions."

frontend:
  - task: "ProgressCard on /home + /your-progress screen"
    implemented: true
    working: true
    file: "frontend/src/components/ProgressCard.tsx, frontend/app/your-progress.tsx, frontend/app/(client)/home.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "New ProgressCard component on client /home — auto-hides when GET /progress/current returns {} (no snapshot yet). Shows status pill (PROGRESSING green / STEADY brand / PULL BACK amber / DELOAD blue) with trending icon, client-facing reason string (max 2 lines), and 3-column metrics strip (SESSIONS x/y, ADHERENCE %, AVG RPE). Border-left color matches status. Tapping opens /your-progress. testID: progress-card. New /your-progress full-screen: header with back button + 'Recompute' button (testID progress-recompute-btn, calls POST /progress/recompute), scrollable list of last 8 weekly snapshots as cards (testID snap-{week_key}) each showing dates, status pill, reason, and 3-4 column metrics (adds KEY MISSED column in red when >0). Empty state (testID your-progress-empty) with 'Complete a full training week...' copy. Uses theme.color.brand + cross-platform toast helper for notifications. Lint clean."

test_plan:
  current_focus:
    - "Backend: iso_week_bounds + week_key produce Mon-Sun and 'YYYY-Www' key"
    - "Backend: compute_status rule engine — progressing_well (4/4 adherence, RPE 7-8), maintain (2/3 adherence RPE 7-8), reduce_load (1/4 adherence), reduce_load (avg RPE ≥9), reduce_load (missed key session + <80% adherence), deload (4 sessions RPE ≥9.5), deload (2 sessions ≥9.5 + n_completed≥3)"
    - "Backend: compute_status ignores placeholder workouts (no exercises)"
    - "Backend: compute_status empty week produces well-formed snapshot"
    - "Backend: HTTP GET /progress/current returns {} or dict"
    - "Backend: HTTP GET /progress/history?weeks=8 returns list, clamps to [1..52]"
    - "Backend: HTTP POST /progress/recompute returns snapshot with status + metrics"
    - "Backend: HTTP GET /coach/clients/{cid}/progress/current denied for client (403), OK for coach"
    - "Backend: HTTP GET /coach/clients/{cid}/progress/history denied for client (403), OK for coach"
    - "Backend integration: POST /workouts/{wid}/complete triggers on_workout_completed — only creates snapshot when this is the last planned session of the ISO week"
    - "Frontend: ProgressCard auto-hides on /home when no snapshot; shows correctly when snapshot exists (verify with recompute button on /your-progress)"
    - "Frontend: /your-progress renders empty state when no snapshots, list of snapshots when present"
    - "Frontend: Recompute button triggers POST /progress/recompute, refreshes list, shows toast"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: "Iter 81 Phase 3 shipped — Reactive Progression + Your Progress. New feature_progression.py (~230 LOC) implements the weekly rule engine (progressing_well / maintain / reduce_load / deload) + on_workout_completed trigger + 5 new endpoints. Frontend: ProgressCard on /home + full /your-progress screen with recompute button and empty state. 19/19 phase 3 tests pass. Combined phases: 86/86 tests pass (Phase 1 = 38, Phase 2 = 29, Phase 3 = 19). TESTING_TYPE: both. Do NOT re-test Phase 1 or Phase 2 endpoints. NEXT PHASE (Phase 4-6): Coach hotel review queue UI, Marathon adjustments, final 15 test cases."

# ═════════════════════════════════════════════════════════════════════
# ITER 81 — MASTER FIX PROMPT · PHASE 4 · COACH DASHBOARD (HOTELS + PROGRESSION)
# ═════════════════════════════════════════════════════════════════════

backend:
  - task: "Coach dashboard: hotels_pending_review count + progression_pill on client summaries"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Phase 4 backend augmentation. (1) Extended _client_summary() to attach progression_pill (latest weekly snapshot from progression_snapshots) with status/status_label/reason/coach_note/week_key/week_start/week_end/metrics — appears on every client returned by /api/coach/dashboard and /api/coach/clients. (2) Extended coach_client_detail /api/coach/clients/{cid} to attach progression_pill on client doc. (3) Added counts.hotels_pending_review to /api/coach/dashboard payload (queries db.hotels where verified_by_coach !== true AND confidence < 0.7). 5/5 Phase 4 tests pass. Combined phases: 94/94 tests pass. No regressions."

frontend:
  - task: "Coach overview alerts + KPIs + client-row progression pill + /coach/hotels review screen + client detail progression"
    implemented: true
    working: true
    file: "frontend/app/(coach)/overview.tsx, frontend/app/coach/hotels.tsx, frontend/app/coach/client/[id].tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Phase 4 frontend. (1) Coach /overview now shows: (a) new KPI 'HOTELS TO REVIEW' (amber, tappable, routes to /coach/hotels), (b) new ATTENTION REQUIRED alert row with chevron and route action when hotels_pending_review > 0, (c) new HOTELS header button (testID ov-goto-hotels), (d) small ProgressionPill on each client row (colour-coded: PROGRESSING green / STEADY brand / PULL BACK amber / DELOAD blue) sourced from progression_pill.status. (2) New /coach/hotels screen (testID coach-hotels-back / coach-hotels-empty / coach-hotel-<id> / coach-hotel-<id>-eq-<key> / coach-hotel-<id>-verify) — lists all low-confidence unverified hotels sorted by last_confirmed_at desc, each card shows confidence %, gym_type label, submissions count, outdoor safety chip, equipment chips (12 items — tap to PATCH /api/hotels/{id}), client notes if any, and a VERIFY HOTEL button that POSTs /api/coach/hotels/{id}/verify (removes from queue on success). (3) Coach client detail /coach/client/[id] now shows progression pill under the client name with the coach_note as sub-text (testID cd-progression-pill). Lint clean."

test_plan:
  current_focus:
    - "Backend: /api/coach/dashboard response includes counts.hotels_pending_review (int, ≥0)"
    - "Backend: /api/coach/dashboard response includes progression_pill key on every client (may be null)"
    - "Backend: /api/coach/clients/{cid} client doc includes progression_pill"
    - "Backend: hotels_pending_review increments after a fresh client hotel submission"
    - "Backend: /api/coach/hotels/review-queue + /api/coach/hotels/{id}/verify still work; verified hotel removed from queue after verify"
    - "Frontend: coach /overview shows HOTELS TO REVIEW KPI + tappable alert row when count > 0"
    - "Frontend: HOTELS header button routes to /coach/hotels"
    - "Frontend: /coach/hotels renders list, chip toggle sends PATCH, verify button POSTs verify + removes card"
    - "Frontend: /coach/client/[id] shows progression pill + coach_note when progression_pill exists on client"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: "Iter 81 Phase 4 shipped — Coach Dashboard (Hotels + Progression). Backend: _client_summary now attaches progression_pill; coach_client_detail attaches progression_pill; coach_dashboard exposes counts.hotels_pending_review. Frontend: new /coach/hotels review-queue screen with chip toggles and per-hotel Verify button; coach overview alerts + KPIs + HOTELS header + per-client ProgressionPill; coach client detail pill+coach_note. 5/5 Phase 4 tests pass. Combined: 94/94 across all four phases. TESTING_TYPE: both. Do NOT re-test Phase 1/2/3 endpoints. NEXT PHASES (5-6): Marathon adjustments (progression-aware long-run scaling) + final 15 test cases + audit closeout."

# ═════════════════════════════════════════════════════════════════════
# ITER 81 — MASTER FIX PROMPT · PHASE 5 · PROGRESSION-AWARE MARATHON
# ═════════════════════════════════════════════════════════════════════

backend:
  - task: "Progression-aware endurance scaling (long_run / tempo / intervals / easy_run)"
    implemented: true
    working: true
    file: "backend/feature_progression.py, backend/feature_workout_fallback.py, backend/server.py, backend/feature_programme_quality.py, backend/feature_roster_confirmation.py, backend/feature_coach_workout_editor.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: "Phase 5 of Master Fix Prompt shipped. New in feature_progression.py: (a) PROGRESSION_SCALARS = {progressing_well: 1.07, maintain: 1.00, reduce_load: 0.88, deload: 0.55} — multipliers applied to endurance session duration and reps. (b) PROGRESSION_REASONS — 4 client-facing strings ('You had a strong week — the long session is nudged up +7% this week.' etc.). (c) scale_endurance_session(session, status) — mutates duration_min (rounded to nearest 5 min, floored at 15 min) and any 'X-Y min' or 'X min' reps ranges via regex; stamps progression_status; appends to existing change_reason (does not clobber hotel/equipment reasons) or sets it. (d) get_current_status(db, user_id) helper reading latest snapshot. Wired build_template_plan(user, roster, hotel_lookup, progression_status) — new kwarg loaded from feature_progression.get_current_status at ALL 5 callsites (server.py x2, feature_programme_quality, feature_roster_confirmation, feature_coach_workout_editor). Inside the loop, only long_run/tempo/intervals/easy_run slots get scaled. 14/14 Phase 5 tests pass. Combined phases 1-5: 108/108. No regressions."

test_plan:
  current_focus:
    - "Backend: PROGRESSION_SCALARS values direction — progressing_well > 1.0 > maintain, reduce < 1, deload < reduce"
    - "Backend: scale_endurance_session no-op when status is None; stamps status even for MAINTAIN"
    - "Backend: scale_endurance_session at PROGRESSING (~+7%) increases 75→80 min, reps '60-90 min' → '64-96 min'"
    - "Backend: scale_endurance_session at REDUCE_LOAD (-12%) decreases 75→65 min, reps '60-90 min' → '53-79 min'"
    - "Backend: scale_endurance_session at DELOAD (~-45%) decreases 75→40 min"
    - "Backend: scale_endurance_session appends to existing change_reason (preserves hotel/eq reasons)"
    - "Backend: 20 min floored to 15 min minimum on deload"
    - "Backend: Non-endurance sessions ignored (strength_support reps '10' unchanged)"
    - "Backend integration: build_template_plan(status=REDUCE) produces a Long Run with LESS duration than status=None"
    - "Backend integration: build_template_plan(status=PROGRESSING) produces a Long Run with MORE duration than status=None"
    - "Backend HTTP: POST /progress/recompute + downstream regeneration reflects the status in generated workouts"

  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: "Iter 81 Phase 5 shipped — Progression-Aware Marathon adjustments. When a client is progressing_well, their long run bumps +7%; when reduce_load, it pulls back -12%; when deload, it drops -45%. All endurance sessions (long_run/tempo/intervals/easy_run) get duration + reps ranges scaled with regex, and a 'Why this changed' reason string is stamped/appended (works alongside Phase 1 hotel reasons and Phase 2 equipment reasons — no clobbering). Wired into all 5 callsites of build_template_plan. 14/14 Phase 5 tests pass. Combined: 108/108 across Phase 1-5. TESTING_TYPE: backend only (frontend already renders change_reason via Phase 2 UI — no new components needed for Phase 5). Do NOT re-test earlier phase endpoints. NEXT PHASE (6): final 15-case audit report closeout."

# ═════════════════════════════════════════════════════════════════════
# ITER 81 — MASTER FIX PROMPT · PHASE 6 · FINAL AUDIT CLOSEOUT
# ═════════════════════════════════════════════════════════════════════

agent_communication:
  - agent: "main"
    message: "Iter 81 Phase 6 (FINAL) shipped. Ran full Master Fix Prompt suite: 110/110 tests pass across all 5 phases + 1 designed skip. Zero regressions. Wrote /app/CrewFit_MASTER_FIX_PROMPT_FINAL_REPORT.md documenting all closed gaps, endpoints, files, decisions, and beta-readiness. Master Fix Prompt is COMPLETE. All four handover gaps (hotel system, strict equipment matching, reactive progression, why-this-changed UI) are closed. System is now roster-aware, hotel-aware, equipment-strict, and progression-reactive. Ready for beta with 20-50 cabin-crew users. NEXT: user acceptance test, deploy, and generate iOS/Android builds via Emergent Publish."


# ═════════════════════════════════════════════════════════════════════
# ITER 83 — CLIENT-SIDE ROSTER DAY CORRECTION UI (long-press picker)
# ═════════════════════════════════════════════════════════════════════

frontend:
  - task: "Long-press roster day picker on client home"
    implemented: true
    working: true
    file: "frontend/src/components/RosterDayPickerSheet.tsx, frontend/app/(client)/home.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: |
            User complaint: 'The etihad roster still isn't accurate and currently
            its hard for the client to move the days if they aren't correct.'
            Backend PATCH /api/roster/{rid}/day already existed (iter 82). We now
            surfaced it with a long-press interaction on each 'Next 7 Days' row
            on the client home screen.
        -working: true
        -agent: "testing"
        -comment: |
            Iter 89 initial pass: 8/9 scenarios PASS. One HIGH bug found on the
            Layover chip (auto-saved with null city). Iter 90 retest: layover
            defer-save fix VERIFIED — all 9/9 scenarios now PASS. No regressions.
            testID surface: week-longpress-hint, roster-day-picker-{DutyType},
            roster-day-picker-city, roster-day-picker-save-layover,
            roster-day-picker-close.

agent_communication:
  - agent: "main"
    message: "Iter 83 shipped: client-side roster day correction UI (long-press picker sheet). Verified locally via playwright: long-press opens the sheet correctly and the PATCH fires with the right payload (returns 404 on out-of-range test date, which is expected — added client-side guard + friendly toast). Please test: (1) log in as client, scroll to NEXT 7 DAYS, verify hint text visible only when a roster exists; (2) long-press any day within the roster window and confirm the sheet opens with the current day_type highlighted; (3) tap a chip and confirm the sheet closes with a success toast, home reloads, and the workout on that date is flagged needs_coach_review; (4) select 'Layover' and confirm a city input + SAVE LAYOVER button appear; (5) attempt long-press on a date NOT covered by the roster and confirm we see the 'not on your current roster' toast instead of an API error. Also confirm no regressions to the existing 'onPress' (single-tap = open workout detail) behaviour on workout rows."


# ─────────────────────────────────────────────────────────────────────────
# Iter 91 — Phase 1 remaining tasks (1.7 verify, 1.8, 1.9, 1.10)
# ─────────────────────────────────────────────────────────────────────────

backend:
  - task: "Task 1.7 — Multi-event dashboard endpoints"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: |
            Endpoints: GET /api/events/active (returns all future events with
            priority A/B/C) and PATCH /api/events/{eid}/priority. Home dashboard
            renders the event stack via EventPrioritySheet. Please verify:
            (a) GET returns the list ordered by date; (b) PATCH persists priority
            and reflects on next GET; (c) 403 for another user's event.

  - task: "Task 1.9 — Structured strength overload directive"
    implemented: true
    working: "NA"
    file: "backend/feature_programme_quality.py, backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: |
            New helper strength_overload_for(goal_key, phase_key, prev_completed,
            prev_planned) returns concrete deltas per phase. Wired into
            programme_context_for_llm ONLY for non-event goals. Attached to
            programmes.strength_overload and included in LLM prompt (bumped
            programme_ctx cap from 2500 → 3200 chars). Adherence multiplier:
            <50% completed last week = hold (mult 0.0); 50-75% = half; ≥75% =
            full. Deload phase is never dampened. Please verify:
            (i) build_muscle/build phase after full adherence => sets_delta=+1;
            (ii) same phase with 0/3 adherence => sets_delta=0 and note
            'hold — <50% completed last week';
            (iii) event-goal users should NOT get strength_overload field (only
            endurance periodisation applies).

  - task: "Task 1.10 — Profile-completeness pill on coach dashboard"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: |
            _client_summary now emits profile_incomplete_pill (missing_fields,
            friendly_labels, missing_count) when _user_essentials_present is
            False. New dashboard bucket 'profile_incomplete'. Please verify:
            (a) freshly-seeded client with no training_setup has
            profile_incomplete_pill populated; (b) after finishing
            training-setup the field is null on next fetch; (c) filter
            /coach/dashboard?filter=profile_incomplete returns only those.

frontend:
  - task: "Task 1.7 — Client home event stack UI"
    implemented: true
    working: "NA"
    file: "frontend/app/(client)/home.tsx, frontend/src/components/EventPrioritySheet.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: |
            Home renders active events with priority chips. Long-press event
            card opens EventPrioritySheet which PATCHes priority. Verify: (a)
            events show in chronological order; (b) A/B/C chip highlights
            current priority; (c) tap chip → sheet closes + card reflects new
            priority; (d) if no events, no card is rendered (silent).

  - task: "Task 1.8 — Coach DEEP EDIT button"
    implemented: true
    working: "NA"
    file: "frontend/app/coach/client/[id].tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: |
            New button 'DEEP EDIT (SETS / EXERCISES)' in the workout action
            sheet. Routes to /coach/workout/edit/{wid}. Disabled when workout
            is coach_locked. Verify: (a) button visible on unlocked workouts;
            (b) tap → editor loads for that wid; (c) locked workout dims the
            button and prevents navigation.

  - task: "Task 1.10 — PROFILE INCOMPLETE amber pill"
    implemented: true
    working: "NA"
    file: "frontend/app/(coach)/clients.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: |
            Client cards now render an amber row with 'PROFILE INCOMPLETE · N
            MISSING · label1, label2…' when the backend sets
            profile_incomplete_pill. New filter chip 'PROFILE GAP' at position
            3 of the filter row. Verify: (a) freshly-seeded client card shows
            the amber pill; (b) filter narrows list correctly; (c) after
            client completes training-setup pull-to-refresh removes the pill.

agent_communication:
  - agent: "main"
    message: "Iter 91: shipped remaining Phase 1 tasks. TEST BOTH backend and frontend. Focus on (1) Task 1.7 endpoints + UI, (2) Task 1.9 strength_overload matrix in programmes doc (endpoint /api/coach/clients/{id}/programme should include strength_overload for non-endurance clients), (3) Task 1.10 profile_incomplete_pill + amber UI pill, (4) Task 1.8 DEEP EDIT button navigates to /coach/workout/edit/{wid}. Credentials in /app/memory/test_credentials.md. Any test failures should be reported with testIDs / API responses so I can fix quickly."

# ─────────────────────────────────────────────────────────────────────────
# Iter 92 — Phase 2 · Living Profile Wire-Back (Tasks 2.1 → 2.6)
# ─────────────────────────────────────────────────────────────────────────

backend:
  - task: "Task 2.1 — Signal extractor from check-ins"
    implemented: true
    working: true
    file: "backend/feature_live_state.py, backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            extract_signals_from_checkin() parses energy/sleep/soreness/stress,
            plus regex-driven pain regions (shoulder/knee/hip/lower_back/etc.),
            focus-shift ("more strength" | "less running" | "too hard"), life
            change ("new roster/pregnant/surgery"), motivation flag. Signals
            stored on checkins.signals AND rolled into users.profile.live_state
            after every /checkins and /checkins/adaptive submission. Verified
            via 4-variant pain regex test.

  - task: "Task 2.2 — Live-state read-model endpoints"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            GET /api/profile/live-state — client rolling snapshot + receipt.
            POST /api/profile/live-state/refresh — force recompute.
            GET /api/coach/clients/{id}/live-state — coach read-model.
            Payload: 14-day energy_avg/trend, sleep, soreness, stress,
            adherence_pct, avg_rpe_last_7d, missed_sessions, pain_flags,
            avoid_movement_patterns, focus_shift_request, life_change,
            auto_deload_trigger + reason, motivation_flag.

  - task: "Task 2.3 — Auto-deload override + energy dampening in plan build"
    implemented: true
    working: true
    file: "backend/feature_programme_quality.py, backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            programme_context_for_llm() now attaches live_state and:
              (a) If auto_deload_trigger=True → override phase to
                  {'key':'deload','label':'Deload (auto)'} and re-derive
                  strength_overload with deload matrix.
              (b) If energy_trend=='down' and phase != 'deload' →
                  strength_overload.sets_delta forced to 0, load_delta_pct 0.
            LLM prompt extended with 5-part live_state block instructing:
            avoid pain-flagged patterns, honour focus_shift, treat
            coach_directives as binding, favour shorter sessions when
            motivation_flag=='low'. programme_ctx prompt cap 3200→4200.
            Rule: adherence<50% AND avg RPE≥8 last 7d → auto-deload
            (user-approved threshold).

  - task: "Task 2.4 — Coach message → coach_directive wire-back"
    implemented: true
    working: true
    file: "backend/server.py, backend/feature_live_state.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            MessageBody now accepts include_in_next_plan boolean.
            POST /api/messages with include_in_next_plan=true (coach only)
            auto-pins the message onto profile.live_state.coach_directives
            with 21-day TTL. New coach endpoints:
              POST /api/coach/clients/{id}/directives {text, ttl_days}
              DELETE /api/coach/clients/{id}/directives/{directive_id}
            Kept last 7 non-expired directives. Directives included in
            programme_context_for_llm output so LLM honours them.

frontend:
  - task: "Task 2.5 — Client 'YOUR INPUT · NEXT WEEK' receipt card"
    implemented: true
    working: true
    file: "frontend/app/(client)/home.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            After each check-in the home fetch to /api/profile/live-state
            returns a receipt {headline, bullets, computed_at}. Home
            renders a brand-tinted card above NEXT 7 DAYS with each bullet.
            When auto_deload_trigger=true an amber DELOAD · AUTO chip is
            appended. testID live-state-receipt.
            VERIFIED LIVE (screenshot) — after seeding a check-in with
            "left shoulder sore, please add more strength", the card
            rendered exactly the two expected bullets.

  - task: "Task 2.6 — Coach LIVE SIGNALS card + directive management"
    implemented: true
    working: true
    file: "frontend/app/coach/client/[id].tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            Coach client detail now shows LIVE SIGNALS · LAST 14D card:
              - 4-cell metric grid (ENERGY+trend, RPE 7D, ADHERENCE %, MISSED)
              - Red chips per pain flag region (testID cd-pain-flag-{key})
              - Hint lines: "Avoiding next week: …" and "Focus shift: …"
              - Amber AUTO-DELOAD pill when trigger active
              - COACH DIRECTIVES · PINNED list with delete X per item
              - Inline TextInput + PIN button to add a new directive
                (testID cd-directive-input, cd-directive-add)
            VERIFIED LIVE (screenshot) — pinned a directive
            ("Focus on posterior chain — deadlifts & Romanians.") and
            observed it render below the pain / focus-shift hints.

agent_communication:
  - agent: "main"
    message: "Iter 92 shipped: Phase 2 Living Profile Wire-Back. Backend 10/10 pytest scenarios PASSED (test_iter92_live_state.py) covering signal extractor, live-state endpoints, auto-deload flip, coach-message directive pin, coach POST/DELETE directive endpoints, and energy-trend dampening. Frontend: manually verified receipt card on client home and LIVE SIGNALS card on coach detail via screenshots (both render correctly with pain flag from seeded shoulder check-in, and coach directive PIN flow works end-to-end). Regression: Phase 1 tests still 13/13 passing."


# ─────────────────────────────────────────────────────────────────────────
# Iter 93 — Phase 3 · Strict post-LLM guardrails
# ─────────────────────────────────────────────────────────────────────────

backend:
  - task: "Phase 3 — Post-LLM guardrail validator + auto-heal"
    implemented: true
    working: true
    file: "backend/feature_workout_guardrails.py, backend/server.py, backend/feature_programme_quality.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            NEW module feature_workout_guardrails.validate_batch runs after
            every generation path (main worker line 4234, retry worker line
            4544, generate-month line 6567) and BEFORE persistence. Enforces:
              H_AVOID: exercises matching avoid_movement_patterns are
                       substituted with safe alternatives (overhead_press →
                       Landmine Press, deep_squat → Box Squat, etc.). 19
                       patterns wired.
              H_OVERLOAD: primary-lift sets clamped to phase-aware band
                          (2-5 build; 2-4 deload). Reps rewritten to
                          strength_overload.reps_target when >4 outside band.
              H_DURATION: workout duration clamped to phase band (recovery
                          8-25, deload 18-45, endurance 25-120, else 20-75).
              H_SHAPE: batch-level check that weekly_shape_ideal is met;
                       first real workout flagged for coach if missing.
              H_MISSING_EX: delegates to _ensure_workout_content (iter 83).
            Persisted workout gets `guardrail_violations` array. Persisted
            programme record gets `guardrail_report {total, ok, healed,
            flagged, violations}`.
            Coach dashboard programme_pill exposes guardrail_healed +
            guardrail_flagged counts. Client cards show new GUARDRAILS ·
            N HEALED · N FLAGGED chip (testID guardrail-row-<clientId>).
            Tests: 15/15 pytest scenarios pass (test_iter93_guardrails.py).

frontend:
  - task: "Phase 3 — Coach dashboard guardrail chip"
    implemented: true
    working: true
    file: "frontend/app/(coach)/clients.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            Client cards now render GUARDRAILS · N HEALED · N FLAGGED chip
            beneath the programme pill whenever guardrail_healed +
            guardrail_flagged > 0. testID guardrail-row-<clientId>.

agent_communication:
  - agent: "main"
    message: "Iter 93 (Phase 3) shipped. 15/15 new pytest scenarios green (test_iter93_guardrails.py). No regressions: Phase 1 13/13 and Phase 2 10/10 still pass individually. Feature summary: every workout now flows through validate_batch() before persistence to enforce (a) no exercises matching pain-avoid patterns, (b) sets/reps inside strength_overload deltas, (c) duration inside phase band, (d) weekly session mix matches weekly_shape_ideal. Auto-heal fixes what it can (substitutes banned exercises, clamps sets/reps/duration); unhealable violations (missing week-shape slots) flag the workout for coach review + surface a GUARDRAILS chip on the coach dashboard."


# ─────────────────────────────────────────────────────────────────────────
# Iter 94c — Flying-day Gap 1 fix: recovery-first long-haul into layover
# ─────────────────────────────────────────────────────────────────────────

backend:
  - task: "Gap 1 — long-haul into 18h+ layover no longer forced to 15-min mobility"
    implemented: true
    working: true
    file: "backend/feature_workout_fallback.py, backend/feature_programme_quality.py, backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            When _classify_day() == flight_heavy AND (classify_stay==layover
            OR the next roster day is a layover / rest-at-hotel) AND we know
            the hotel — we now bypass the safety override and emit a normal
            layover session flagged `recovery_first=True`.
            Emission changes:
              * day_load downgraded to 'amber' (was 'red')
              * FLIGHT_RECOVERY_MOBILITY prepended to warmup (5-item mobility
                + breathing block)
              * RPE clamped ≤7 on main exercises
              * long_run / tempo / intervals slots downshifted to easy_run
              * hard strength slots downshifted to strength_support
              * change_reason: "Long-haul into layover — recovery mobility
                first, then a moderated session."
            LLM prompt also updated: programme_context.roster_summary now
            exposes `recovery_first_days: [ISO_DATE, ...]` and rule (6) tells
            the LLM to open with 10 min mobility, cap the session at RPE 7,
            ≤45 min total, and mention the layover-window rationale.
            Safety-preserving fallback: if there is NO known hotel_id, the
            legacy 15-min mobility (RED) still fires.
            Tests: 7/7 pytest scenarios PASSED (test_iter94c_gap1_recovery_first.py).
            Regressions clean: iter91 13/13, iter93 15/15, iter92 10/10 with
            iter94c on top.

agent_communication:
  - agent: "main"
    message: "Iter 94c shipped: closed Gap 1 from the flying-day audit. Long-haul crew who land in DXB/BKK/SYD with 22h in a known hotel now get a real training session (recovery-first: mobility + moderated strength or easy run) instead of the wasted 15-min safety override. Behaviour is provable via test_iter94c_gap1_recovery_first.py::test_recovery_first_session_replaces_15min_mobility. When there's no hotel_id on the roster row (unknown hotel), we still fall back to the 15-min RED safety override — that path is covered by test_no_hotel_still_forces_safety_override."


# ─────────────────────────────────────────────────────────────────────────
# Iter 94d — Flying-day Gap 3: TIERED post-flight recovery templates
# ─────────────────────────────────────────────────────────────────────────

backend:
  - task: "Gap 3 — tiered flight recovery (short / medium / ULR)"
    implemented: true
    working: true
    file: "backend/feature_workout_fallback.py, backend/feature_programme_quality.py, backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            NEW helper flight_recovery_template_for(duty_hours) returns one of:
              short  (<6h)  → 8-min Airport Mobility (4 standing moves, no floor)
              medium (6-11h)→ 15-min classic FLIGHT_RECOVERY_MOBILITY (unchanged)
              ulr    (≥12h) → 25-min ULR Recovery + Sleep Prep, 7 moves incl.
                             wall thoracic decompression, deep hip flexor,
                             glute bridge (paused), band pull-apart, and
                             4-7-8 + box breathing for parasympathetic
                             downshift. Rationale includes 'Hydrate before
                             starting.'
            NEW arrays:
              SHORT_HAUL_AIRPORT_MOBILITY (4 items)
              ULR_RECOVERY_PROTOCOL       (7 items)
            _override_for_duty(kind, date, duty_hours=None) now picks the
            correct tier and stamps `recovery_tier` + `duty_hours` on the
            emitted workout. Load rules:
              short → amber, optional=True
              medium→ amber (or red at 10-11h duty), optional=True
              ulr   → red, optional=False (sleep prep is mandatory)
            LLM path also updated: _roster_summary now emits
            `recovery_tiered_days: [{date, tier, duty_hours}, ...]` and new
            prompt rule (7) instructs the LLM to tailor session length /
            breathing / hydration prompts per tier.
            Tests: 10/10 pytest scenarios PASSED
            (test_iter94d_gap3_tiered_recovery.py).
            Regressions clean: 45/45 across Phase 1, Phase 3, Gap 1, Gap 3.

agent_communication:
  - agent: "main"
    message: "Iter 94d shipped: closed Gap 3 from the flying-day audit. Flight recovery is now aviation-appropriate — a 3h EDI turnaround gets 8 min of concourse mobility, a 14h SYD ULR gets 25 min with thoracic decompression + 4-7-8 breathing + hydration cues. ULR sessions are marked mandatory (optional=False) because sleep prep is critical. Backend 45/45 pytest across all iterations. Iter 94b flying-type training-setup UI was ALSO built earlier this session — awaiting a fresh test-user smoke check on device (the seeded client is already through setup so training-setup redirects to home, expected)."



# ─────────────────────────────────────────────────────────────────────────
# Iter 95a — Weekly Review dedupe + Dual-Session + OTA + App Store metadata
# ─────────────────────────────────────────────────────────────────────────

backend:
  - task: "Weekly Review — real coach-task id on dedupe (was 'existing')"
    implemented: true
    working: true
    file: "backend/feature_weekly_review.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            `_maybe_create_video_task` now returns Optional[str] and stores the
            REAL MongoDB coach-task id on `weekly_reviews.video_task_id` so the
            coach dashboard can deep-link straight into the video review task.
            Three code paths:
              1) stored task id still exists → reuse it.
              2) live task exists for same user+week → adopt + persist its id.
              3) no live task → create a new one and persist its id.
            Idempotent under repeated /weekly-review/checkin-complete +
            /progress-complete calls (verified: back-to-back calls return the
            SAME UUID, no duplicates in coach_tasks).
        -working: true
        -agent: "testing"
        -comment: "11/11 pytest PASS (tests/test_iter95a_endpoints.py) — video_task_id is a real UUID, no duplicate weekly_video_review docs for same week_start."

  - task: "Dual-Session — short-haul airport activation eligibility + endpoints"
    implemented: true
    working: true
    file: "backend/feature_dual_session.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            New feature module. Pure eligibility evaluator:
              evaluate_day(day, next_day, profile) → {eligible, reason, gap_hours,
                                                       duty_hours, flight_count, pattern}
            Rules:
              • flying_type must be short_haul/mixed/charter (long_haul → not eligible)
              • off/home/annual/sick day types → not eligible
              • duty_hours > 11.5 → not eligible (safety cap)
              • Path A: airport gap ≥ 3h between consecutive legs AND day ends
                        at a hotel (or next day rest/off)
              • Path B: 3+ legs AND day ends at a hotel → eligible
            Endpoints (all gated by dual_session_enabled flag):
              GET  /api/dual-session/today
              GET  /api/dual-session/upcoming?days=N (max 21)
              GET  /api/dual-session/debug/{user_id}   (coach-only)
            Session template = 8-min "Airport Activation" — mobility + calf
            raises + bodyweight hinge + brisk walk + breathing. All copy is
            Louis-voiced. Feature flag `dual_session_enabled` seeded ENABLED.
            Unit tests: 9/9 PASS (test_iter95a.py). Endpoint tests: 11/11 PASS.

  - task: "OTA (expo-updates) config + hook — silent JS-only updates"
    implemented: true
    working: true
    file: "frontend/app.json, frontend/src/hooks/use-ota-updates.ts, frontend/app/_layout.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            Installed expo-updates@29.0.19 (SDK 54 compatible). Added to app.json:
              runtimeVersion: { policy: "appVersion" }
              updates: { enabled: true, checkAutomatically: ON_LOAD, fallbackToCacheTimeout: 0 }
            New hook useOtaUpdates() wired into RootLayout — silently no-ops
            on web / Expo Go / dev. Reloads only after a fetched update, and
            waits 2.5s so the initial paint isn't hijacked.
            Wire-up for the URL is via `eas update:configure` (owner action).

  - task: "App Store / Beta readiness reference doc"
    implemented: true
    working: true
    file: "APP_STORE_METADATA.md"
    stuck_count: 0
    priority: "low"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            New /app/APP_STORE_METADATA.md — living checklist: metadata (name,
            keywords, categories), screenshots plan, in-app quality gates,
            compliance disclaimers, TestFlight setup, OTA workflow, review
            pre-flight checks, and known-parked items. Ready for Louis to
            paste directly into App Store Connect.

agent_communication:
  - agent: "main"
    message: "Iter 95a shipped four items in one pass: (1) Weekly Review dedupe returns the real coach-task id so the coach app can deep-link. (2) Dual-Session (short-haul airport activation) — feature-flagged endpoints + Home card that renders only on eligible days, never touches the planned session doc. (3) expo-updates wired for OTA (silent, safe fallback). (4) App Store metadata doc committed to /app. 20/20 backend tests green (11 endpoint + 9 unit). Frontend restarted. Ready for user verification of the Home-screen card on a device with an eligible short-haul roster day."


# ─────────────────────────────────────────────────────────────────────────
# Iter 95b — Phase 1 Beta Blockers: Privacy URL + Support URL + Health Disclaimer
# ─────────────────────────────────────────────────────────────────────────

backend:
  - task: "Public URLs seeded into app_config (privacy, support, terms, website, whatsapp)"
    implemented: true
    working: true
    file: "backend/feature_app_config.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            Seeded 5 new keys: public_privacy_url (https://crewfit.net/privacy),
            public_support_url (https://crewfit.net/support), public_terms_url,
            public_website_url, whatsapp_support_url. All added to
            SAFE_CONTENT_KEYS so they can be edited live without an app update.
            Verified via GET /api/app-config → all 5 present under `flags`.

frontend:
  - task: "Public URLs single source of truth (publicUrls.ts)"
    implemented: true
    working: true
    file: "frontend/src/lib/publicUrls.ts"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: "New PUBLIC_URLS constants file. No hard-coded URLs remain anywhere else."

  - task: "Health disclaimer above signup CTA"
    implemented: true
    working: true
    file: "frontend/app/(auth)/signup.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            Added highlighted disclaimer box with medkit-outline icon,
            "Before you continue" heading, and the exact required copy.
            Placed directly above the CREATE ACCOUNT button so a reviewer
            or beta tester cannot miss it. Not blocking — signup still
            proceeds on age-check + submit. Verified via screenshot.

  - task: "Public Privacy + Support links on signup and login"
    implemented: true
    working: true
    file: "frontend/app/(auth)/signup.tsx, frontend/app/(auth)/login.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            Signup: `crewfit.net/privacy · crewfit.net/support` links below
            the CTA (testIDs signup-privacy-public-link, signup-support-public-link).
            Login: `Privacy Policy · Support` links below the beta line
            (testIDs login-privacy-public-link, login-support-public-link).
            Both use Linking.openURL() so they open the mobile browser.
            Screenshots captured.

  - task: "In-app Privacy screen shows public mirror URL"
    implemented: true
    working: true
    file: "frontend/app/legal/privacy.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            Added a highlighted "PUBLIC MIRROR — crewfit.net/privacy" card
            at the top of the in-app policy so reviewers can confirm the
            offline mirror matches the URL declared in App Store Connect.

  - task: "Contact screen shows public Support URL and WhatsApp"
    implemented: true
    working: true
    file: "frontend/app/legal/contact.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            Rebuilt the contact screen with a top-of-screen "ONLINE SUPPORT —
            crewfit.net/support" card, plus a WhatsApp card (uses
            PUBLIC_URLS.whatsapp = https://wa.link/k9x12s), plus existing
            email cards.

  - task: "Profile — new SUPPORT button"
    implemented: true
    working: true
    file: "frontend/app/(client)/profile.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            Added `SUPPORT` button below `LEGAL & PRIVACY` (testID hq-support)
            → routes to /legal/contact which contains the public URL card.

  - task: "Store review risk audit — beta clean"
    implemented: true
    working: true
    file: "audit"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        -working: true
        -agent: "main"
        -comment: |
            Audit results:
              - No Coach Kai references in /app/frontend
              - No fake/demo client data
              - Demo login gated by EXPO_PUBLIC_SHOW_DEMO_LOGIN_SHORTCUTS
                (not set in .env; also requires __DEV__) → hidden in TestFlight/Play
              - No client-facing AI/generated/bot wording (privacy policy
                disclosure of inference providers is REQUIRED for GDPR,
                not client UI copy)
              - No location permission requested (no expo-location, no
                NSLocationUsageDescription, no ACCESS_FINE_LOCATION)
              - Push opt-in only: push.ts calls getPermissionsAsync then
                only registers if already granted. First launch stays quiet.
              - Delete account route /legal/delete-account exists
              - Health disclaimer visible on signup screen
              - Public Privacy + Support URLs open the mobile browser

agent_communication:
  - agent: "main"
    message: "Phase 1 beta blockers cleared. All required public URLs (privacy, support) wired via a single-source-of-truth constants file plus backend app_config. Health disclaimer added to signup with exact required copy. Store-review risk audit: clean. Login demo shortcut confirmed gated (hidden in beta builds). Both public URLs verified opening on mobile."


# Iter 95e — REGRESSION-FIX PASS (correction only, no rebuild)
# Fixed 5 items that were previously reported as complete but failed in real Expo/mobile testing.

backend: []

frontend:
  - task: "Calendar — page-by-7 instead of append (PREV 7 / TODAY / NEXT 7)"
    working: true
    file: "frontend/src/components/ClientCalendarPanel.tsx"
    verified_on: "Expo web mobile preview 390×844 — screenshots /tmp/i1_calendar_initial.png + /tmp/i1_calendar_next7.png"
    change: "Replaced load-more append flow with strict 7-day paging. Initial view = today + 6 days. Prev7 / Today / Next7 buttons jump the window by 7."

  - task: "Roster upload — native-safe base64 (was crashing on file:// / content:// URIs)"
    working: true
    file: "frontend/app/roster-upload.tsx"
    verified_on: "Expo web preview loads all 3 pick buttons and no crash. Native path uses `expo-file-system/legacy` readAsStringAsync + cache fallback for Android content:// URIs. Also added WhatsApp escape hatch on upload failure."
    change: "Rewrote uriToBase64 to branch web vs native. Added error card with Try Again / Choose Different File / Message Louis on WhatsApp buttons."

  - task: "Log First Meal — full modality picker instead of manual-only"
    working: true
    file: "frontend/app/nutrition/pick.tsx (new), frontend/src/components/NutritionTodayCard.tsx"
    verified_on: "Expo /nutrition/pick shows all 4 options (Photo / Barcode / Search / Manual)."
    change: "New picker route. LOG FIRST MEAL and LOG FOOD buttons now route to /nutrition/pick, which offers all four modalities with feature-flag gating for photo/barcode."

  - task: "Progress — adaptive with goal-class aliases + universal fallback"
    working: true
    file: "frontend/src/components/ProgressDashboard.tsx"
    verified_on: "Expo /progress renders YOUR GOAL FAT LOSS + Adherence + Body Weight chart (-1.7kg) + Body Waist chart."
    change: "Mapped body_composition → fat_loss panel, marathon → running, muscle → strength, others → health panel fallback. No goal_class now falls through empty."

  - task: "Habits — auto-seed on first-run empty state"
    working: true
    file: "frontend/src/components/HabitTodayCard.tsx"
    verified_on: "Expo home screen shows 'Drink 2L water minimum' habit with DONE/SKIPPED/NOT POSSIBLE controls."
    change: "If /habits/today returns empty on first load, silently POST /habits/seed and refetch. One-shot per component mount."

agent_communication:
  - agent: "main"
    message: "Iter 95e regression-fix pass. No rebuilds, no new features, no LLM/image spend. 5 issues fixed and verified live in the Expo web mobile preview at 390×844. All lint clean. Habits and Progress now populate immediately for a first-run user (auto-seed + goal-class fallback). Roster upload native path fixed by switching to expo-file-system/legacy — was failing silently because the code was using fetch+FileReader which does not support file:// / content:// URIs on native RN."


# Iter 109 — Phase A · Coach Dashboard Rebuild (A1 + A2)
# Fixes the "July disappeared after August upload" client-side visibility bug
# AND adds coach-side "Upload roster on behalf of client" capability.

backend:
  - task: "A1 — /roster/current merges days from ALL active rosters (not just newest)"
    working: true
    file: "backend/server.py"
    verified_on: "Direct DB probe on Louis Hall client (louis@hotmail.co.uk): 62 merged days now returned across July + August; each day carries _source_roster_id so day-picker routes correctly."
    change: "Rewrote /roster/current to gather every is_active=True roster, merge days by date (newest wins), preserve source roster id, and recompute start_date/end_date/day_count across the union."

  - task: "A1 — feature_calendar_recovery._roster_days_between merges across active rosters"
    working: true
    file: "backend/feature_calendar_recovery.py"
    verified_on: "pytest tests/test_roster_month_preservation.py -v → 3/3 PASSED (merge, inactive-ignored, newest-wins)."
    change: "Was filtering on `status='active'` (a value never actually written) via find_one — returned nothing. Now finds all is_active=True rosters and merges days by date; stamps _source_roster_id on each day."

  - task: "A2 — POST /api/coach/clients/{cid}/roster/upload-parse (coach uploads on behalf of client)"
    working: true
    file: "backend/feature_coach_roster_upload.py"
    verified_on: "pytest tests/test_coach_roster_upload.py -v → 3/3 PASSED (endpoints registered, role-gated, 404 on missing pending)."
    change: "New endpoint. Requires role=coach. Enqueues background parse worker that writes the pending roster with user_id=client_id + uploaded_by='coach' + uploaded_by_coach_id."

  - task: "A2 — POST /api/coach/clients/{cid}/roster/pending/{rid}/confirm (coach-side confirm + generate)"
    working: true
    file: "backend/feature_coach_roster_upload.py"
    verified_on: "Endpoint registered + role-gated. Reuses same overlap-aware deactivation + generation pipeline as client flow, but bypasses the client-side 'all low-confidence days must be reviewed' gate — the coach IS the reviewer."
    change: "New endpoint. Marks the pending roster is_active=True, status=confirmed, confirmed_by='coach', supersedes only overlapping rosters, and kicks off the same _generate_month worker."

frontend:
  - task: "A1 — client dashboard shows July + August together"
    working: true
    file: "frontend/app/(client)/home.tsx"
    verified_on: "Backend /roster/current now returns 62 merged days across two months for the test user; openDayPicker prefers per-day _source_roster_id so PATCH routes to the correct roster."
    change: "openDayPicker now uses rd._source_roster_id (falls back to roster.id) so day-type edits work even when the day lives on an older active roster."

  - task: "A2 — CoachRosterUploadButton on coach dashboard + client-months screen"
    working: true
    file: "frontend/src/components/CoachRosterUploadButton.tsx"
    verified_on: "Expo web preview 390×844 loads cleanly, no lint errors. Button placed on /coach/client/[id] action row AND /coach/client-months/[id] header + empty state."
    change: "New reusable component. Picks pdf/image, uploads to /coach/clients/{cid}/roster/upload-parse, polls the job, auto-confirms the pending roster on behalf of client, then polls the generation job to completion."

agent_communication:
  - agent: "main"
    message: "Phase A (Coach Dashboard Rebuild) complete. A1 fixes the 'July disappeared' visibility bug via multi-roster merge in /roster/current and _roster_days_between. A2 gives Louis a one-tap 'Upload roster for client' path from both the client detail screen and the month-navigator, with auto-confirm on the coach's behalf. 6/6 pytest cases green. Ready for user validation before proceeding to Phase B."


# V2 Phase 1 — DRAFT/LIVE state foundation (Iter 112)

backend:
  - task: "V2 Phase 1: DRAFT / LIVE / VERSION state layer"
    working: true
    file: "backend/feature_v2_state_foundation.py"
    verified_on: "pytest tests/test_v2_state_foundation.py → 8/8 PASSED"
    change: |
      New module registering 13 endpoints under /api/v2/*:
        - PATCH /v2/coach/clients/{cid}/flags           (enable V2 per client)
        - GET   /v2/coach/clients/{cid}/flags
        - POST/GET/PATCH /v2/coach/clients/{cid}/drafts
        - GET   /v2/coach/clients/{cid}/drafts/{did}
        - POST  /v2/coach/clients/{cid}/drafts/{did}/change-sets
        - GET   /v2/coach/clients/{cid}/drafts/{did}/change-sets
        - PATCH /v2/coach/clients/{cid}/change-sets/{csid}/resolve
        - POST  /v2/coach/clients/{cid}/drafts/{did}/approvals
        - GET   /v2/coach/clients/{cid}/versions
        - GET   /v2/coach/clients/{cid}/versions/{vid}
        - POST  /v2/coach/clients/{cid}/versions/revert
        - POST/GET/DELETE /v2/coach/clients/{cid}/locks
        - GET   /v2/coach/clients/{cid}/decisions
        - GET   /v2/live/plan            (client stub; empty until later phases)
      New collections used (write-only from V2 code, unread by V1):
        plan_drafts, plan_versions, plan_snapshots, change_sets,
        approvals, locks, decision_records.
      Feature flag: profile.v2_flags.state_foundation_enabled — off by default.
    invariants_verified:
      - Flag gate: 409 without state_foundation_enabled=True
      - Role gate: every /v2/coach/* endpoint requires role=coach
      - Version immutability: immutable=True flag on every plan_versions row
      - Non-destructive revert: revert(v1) creates v3, leaving v1 and v2 intact
      - Draft supersession: second draft_create discards the prior building draft
      - DecisionRecord fires on every state transition
      - /v2/live/plan returns has_v2_plan=False by default — no V1 client sees V2 output

agent_communication:
  - agent: "main"
    message: |
      V2 Phase 1 shipped behind per-client feature flag. Zero V1 impact
      (verified: no V1 files reference the new collections). 8/8 backend
      tests green. This is the foundation every subsequent V2 phase
      (goals → objectives → scheduling → construction) will build on.
      To try it end-to-end: PATCH /v2/coach/clients/{cid}/flags with
      {"state_foundation_enabled": true} then create a draft, approve,
      revert. Client's actual LIVE plan remains served by V1.


##====================================================================
## Coach Dashboard V2 Iteration 3 · Priority 4 & 5 — DRAFT vs LIVE + INLINE EDITING
##====================================================================

backend:
  - task: "V2 Draft vs Live diff endpoint"
    implemented: true
    working: "NA"
    file: "backend/feature_v2_coach_publish.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          New endpoint GET /api/v2/coach/clients/{cid}/plan/diff?month=YYYY-MM.
          Returns per-assignment delta (LIVE vs DRAFT implementation
          signatures + concrete field bullets) plus all proposed
          change_sets attached to the active draft. Supports 4 delta
          kinds: unchanged / modified / added / live_only. Handles the
          "no programme yet" case gracefully by returning empty arrays.
          Coach role + V2 dashboard flag required. Manual smoke test:
          returns valid empty envelope for a v2-flagged client with no
          programme. Sample response shape verified via curl.

  - task: "V2 selective plan publish endpoint"
    implemented: true
    working: "NA"
    file: "backend/feature_v2_coach_publish.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          New endpoint POST /api/v2/coach/clients/{cid}/plan/publish.
          Body: { draft_id, assignment_ids?, accept_change_set_ids?,
          reject_change_set_ids?, notes?, scope: 'selected'|'all' }.
          For each selected assignment promotes draft_implementation_id
          → live_implementation_id and flips status to 'live'. Accepts
          named change_sets, rejects others (never promoted). Creates
          ONE new plan_version + snapshot + approval row and marks
          accepted change_sets promoted_in_version_id. Draft status
          transitions to promoted (all consumed) or partially_approved.
          Programme.live_plan_version bumped. DecisionRecord written.
          Guards: 404 draft not found, 409 draft promoted/discarded,
          coach role + V2 dashboard flag.

  - task: "V2 Inline Workout Implementation editor endpoints"
    implemented: true
    working: "NA"
    file: "backend/feature_v2_coach_inline_editor.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          5 new mutation endpoints on the DRAFT implementation:
            PATCH  /v2/coach/clients/{cid}/plan/implementations/{iid}
                   (title/duration/focus/rationale/key_session/coach_notes/needs_coach_review)
            PATCH  /v2/coach/clients/{cid}/plan/implementations/{iid}/exercises/{idx}
                   (name/sets/reps/rpe/rest_sec/hr_zone/duration_sec/coaching_cue/slot_role)
            DELETE /v2/coach/clients/{cid}/plan/implementations/{iid}/exercises/{idx}
            POST   /v2/coach/clients/{cid}/plan/implementations/{iid}/exercises
            POST   /v2/coach/clients/{cid}/plan/implementations/{iid}/exercises/reorder
          Guards: refuses edit if impl is LIVE (draft_impl != live_impl
          contract); marks parent workout_assignment coach_edited=True
          and downgrades status from 'live' to 'coach_edited'; writes a
          DecisionRecord layer=HOW every mutation. Manual smoke: PATCH
          on nonexistent impl returns 404.

frontend:
  - task: "PublishPanel — Draft vs Live diff modal + selective publish UI"
    implemented: true
    working: "NA"
    file: "frontend/src/components/PublishPanel.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Full-height right-side panel opened from Publish button in
          workspace ribbon. Loads /plan/diff for current month, shows
          summary chips (Changed/New/Unchanged/Changes to review), a
          Proposed Changes list (each with Accept/Reject/Skip radio) and
          per-day session cards with LIVE vs DRAFT columns + delta
          bullets. Publishable items are checkable; locked ones are
          disabled. Publish button posts to /plan/publish with
          selection. Success shows a "Published · N sessions live · vX"
          banner and refreshes the diff. Coach note (optional) attached
          as `notes`. No AI wording.
  - task: "InlineWorkoutEditor — inline exercise + meta editor inside V2 drawer"
    implemented: true
    working: "NA"
    file: "frontend/src/components/InlineWorkoutEditor.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Replaces the redirect to the V1 full-page editor (was pushing
          /coach/workout/edit/[wid]) with an inline form INSIDE the
          workspace drawer. Two-mode drawer: VIEW / EDIT. EDIT lets the
          coach change title, duration, focus, location, coach note,
          key-session toggle, and clear the "needs coach review" flag;
          for each exercise: name, sets, reps, rest, RPE, cue, plus
          add/delete/reorder. Every field commits on blur, calls the
          V2 inline-editor endpoints, refreshes the impl, and marks the
          assignment coach-edited. Errors surface inline. Live impls
          return 409 → shown as inline error banner.
  - task: "V2 Workspace ribbon Publish button + WorkoutDrawer rewrite"
    implemented: true
    working: "NA"
    file: "frontend/app/coach/client/[id]/workspace.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Added "Publish changes" button in the workspace ribbon (only
          when data.programme.draft_id exists) that opens PublishPanel.
          Rewired WorkoutDrawer.onEditRequested → drawer-local
          setMode("edit") which renders InlineWorkoutEditor instead of
          pushing to the V1 route. Drawer now displays coach_notes when
          present, retains "Why this?" DecisionRecord list, and offers
          "Edit inline" as the primary button.

test_plan:
  current_focus:
    - "GET /v2/coach/clients/{cid}/plan/diff"
    - "POST /v2/coach/clients/{cid}/plan/publish"
    - "PATCH /v2/coach/clients/{cid}/plan/implementations/{iid}"
    - "PATCH /v2/coach/clients/{cid}/plan/implementations/{iid}/exercises/{idx}"
    - "DELETE /v2/coach/clients/{cid}/plan/implementations/{iid}/exercises/{idx}"
    - "POST /v2/coach/clients/{cid}/plan/implementations/{iid}/exercises"
    - "POST /v2/coach/clients/{cid}/plan/implementations/{iid}/exercises/reorder"
    - "PublishPanel modal open + publish button + change-set decisions"
    - "InlineWorkoutEditor inside V2 drawer (view→edit toggle)"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      Coach Dashboard V2 Iteration 3 shipped. Priority 4 (Draft vs Live UI
      + Publishing Flow) and Priority 5 (Inline Workout Editing) are both
      implemented behind the existing per-coach v2 dashboard flag.
      Coach credentials: louis@crewfit.net / Louis123!. V2 client with
      flags enabled: client@crewfit.com (id d6e0be44-d3a5-407f-bc04-7cc7ef96179a),
      but NB the client currently has no programmes_v2 row yet — the
      empty-state paths must be exercised. Please test:
      (1) All 7 new backend endpoints (auth+flag guards, happy path if
          seeded, edge cases like 404 impl / rejects with no promotions).
      (2) PublishPanel opens from workspace ribbon and renders empty
          state when no draft exists.
      (3) InlineWorkoutEditor renders in EDIT mode inside the drawer,
          field edits patch through to the backend on blur, and the
          drawer shows the fresh impl after mutation.
      No AI/bot wording anywhere in the new UI.

##====================================================================
## Coach Dashboard V2 Iteration 4 · P1 — Roster Upload + Client Profile Tabs
##====================================================================

frontend:
  - task: "V2 workspace ribbon — inline Roster Upload button"
    implemented: true
    working: "NA"
    file: "frontend/app/coach/client/[id]/workspace.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Embedded the existing `CoachRosterUploadButton` (compact mode)
          in the workspace ribbon so the coach can upload the next roster
          without leaving the V2 workspace. Passes clientId + clientName,
          onComplete triggers loadMonth() to refresh the whole month.
  - task: "V2 client profile tabs — Plan / Check-ins / Messages / Progress / History / Goals"
    implemented: true
    working: "NA"
    file: "frontend/src/components/V2ClientTabs.tsx + frontend/app/coach/client/[id]/workspace.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          The workspace now has a 6-tab bar directly under the ribbon:
            plan / checkins / messages / progress / history / goals
          Plan (default) renders the existing Roster+Plan calendar with
          ProgrammeSummaryPanel + GenerationStatusBanner + CommandBar +
          day rows + exceptions + workout drawer.
          All 5 non-Plan tabs live in `V2ClientTabs.tsx`:
            - CheckinsPanel: `GET /coach/clients/{id}` → checkins list with
              energy/recovery/mood/sleep/injury flags, review badge.
            - MessagesPanel: `GET /messages/{cid}` list + `POST /messages`
              compose bar. Coach messages align right (brand color).
            - ProgressPanel: progression pill from client detail +
              adherence bar from workouts + milestones from
              /programme-overview.
            - HistoryPanel: `GET /coach/clients/{id}/programme/history`
              with status badge and completion bar.
            - GoalsPanel: primary goal + target event (with phase &
              weeks-out) + Training DNA rows (progression, days/week,
              equipment, injuries, constraints).
          All tabs are Coach-only surfaces; no AI/bot/generated wording.
          Testable via testIDs `v2-tabbar`, `v2-tab-{plan|checkins|
          messages|progress|history|goals}`, `v2-checkins-panel`,
          `v2-messages-panel`, `v2-progress-panel`, `v2-history-panel`,
          `v2-goals-panel`, `v2-message-input`, `v2-message-send`.

test_plan:
  current_focus:
    - "V2 workspace ribbon includes CoachRosterUploadButton (compact)"
    - "V2 tab bar with 6 tabs; Plan renders unchanged; each non-Plan tab loads without error"
    - "MessagesPanel send + refresh round-trip"
    - "GoalsPanel and HistoryPanel handle empty state gracefully"
    - "No AI/bot/generated wording in any tab"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      Coach Dashboard V2 Iteration 4 shipped. Both P1 items done in one
      pass: (1) Roster Upload is now embedded inline in the workspace
      ribbon; (2) A 6-tab bar switches between Plan (unchanged) and 5
      new panels — Check-ins / Messages / Progress / History / Goals —
      all reading from existing V1 coach endpoints (no new backend
      required). Coach can now maintain full context in one screen with
      no bounces to V1. No AI/bot wording. Please test the tab
      switcher, empty states for a client without much data, and one
      message round-trip.


##====================================================================
## V1 → V2 MIGRATION · Phase A (default flip) + Phase C (data wipe)
##====================================================================

backend:
  - task: "V2 flags default-on for new signups + coach-created clients"
    implemented: true
    working: "NA"
    file: "backend/feature_v2_defaults.py + backend/server.py (signup + coach_create_client)"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Added feature_v2_defaults.py with default_client_v2_flags() and
          default_coach_v2_flags() helpers. Both signup and
          coach_create_client now inject the full V2 flag bundle
          (state_foundation, goals_phases, roster_facets, scheduling_v2,
          construction_v2, equipment_adaptation_v2, progression_v2,
          reality_v2, events_v2, automation_v2, demand_engine +
          v2_default). Coaches created via signup ROUTE cannot exist
          (role forced to client), so no coach-creation change needed.
  - task: "One-shot V2 flip + client-data wipe migration"
    implemented: true
    working: true
    file: "backend/migrations/v2_flip_default.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Migration script (dry-run supported) executed twice against the
          live crewfit_v1 DB. Final state:
            - 2 coaches: louis@crewfit.net (13 flags), coach@crewfit.com (13 flags)
            - 1 client: reviewer@crewfit.net (12 flags — App Store account, preserved)
            - All test clients + orphan V1/V2 data wiped (30 collections
              across programmes, workouts, plans, drafts, versions,
              messages, audit_logs, etc.).
          Preserved emails hardcoded: louis@crewfit.net,
          reviewer@crewfit.net.

frontend:
  - task: "Coach lands on V2 Home by default (retiring /coach/clients as landing)"
    implemented: true
    working: true
    file: "frontend/app/index.tsx + (auth)/login.tsx + (auth)/signup.tsx + (coach)/_layout.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          All 4 coach-redirect points changed from /coach/clients (or
          /coach/overview on desktop) to /(coach)/v2-home:
            - /app/index.tsx      Redirect on session
            - login.tsx            first-login redirect
            - login.tsx            demo-login redirect
            - signup.tsx           post-signup redirect (defensive; role is
                                   forced to client on this route)
          Coach tab bar reordered: v2-home is now first tab, labeled
          "HOME" (no longer "V2 HOME" — V2 IS home now). Verified on
          desktop via screenshot at /app/scripts/coach_home_v2.png —
          Louis lands on V2 Home instantly with sidebar "V2 Home (New)"
          active.

test_plan:
  current_focus:
    - "signup persists v2_flags on new clients"
    - "coach_create_client persists v2_flags on manually-created clients"
    - "coach login → V2 Home (not V1 clients/overview)"
    - "V2 endpoints work for the reviewer account (only surviving client)"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      Phase A of V1→V2 migration shipped:
        1. New signups/coach-created clients get the full V2 flag bundle
        2. Existing users migrated (3 test clients deleted; louis coach +
           reviewer client + coach@ coach retained with V2 flags on)
        3. Coach lands on V2 Home by default; tab bar reordered
      Phase B (client-facing V2 UI — reading LIVE plan from
      workout_implementations) starts next. Phase D (V1 UI retirement)
      after B is stable.


##====================================================================
## V2 Migration · Hotfixes + Kickoff (unblocks the "Planning programme" stall)
##====================================================================

backend:
  - task: "Roster upload — coach polling permission fix"
    implemented: true
    working: true
    file: "backend/server.py (GET+POST /roster/jobs/{jid} + /retry)"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Coach polling of roster jobs was returning 404 because the
          endpoint filtered strictly on user_id == caller.id, but the
          job's user_id is the CLIENT id (coach uploads on behalf of).
          Fix: when caller is coach, match on user_id OR coach_id. Same
          fix applied to /roster/jobs/{jid}/retry. Verified via curl —
          coach now polls jobs successfully.
  - task: "V1 roster → V2 schedule_days bridge on confirmation"
    implemented: true
    working: true
    file: "backend/feature_v2_p4_roster.py (_build_roster_facets helper) + feature_coach_roster_upload.py + feature_roster_confirmation.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Refactored the P4 build endpoint into a reusable
          `_build_roster_facets(client_id, roster_id?, actor_id)` helper.
          Hooked into BOTH the coach-side and client-side roster confirm
          endpoints so that whenever a roster is confirmed for a V2
          client, V2 `schedule_days` + `roster_duties` + `flight_sectors`
          are materialised immediately. Also added a duplicate-date
          delete_many to avoid Mongo unique-index conflicts when a new
          roster supersedes an old one. Verified live: Pietro's July
          roster now shows classified days ("Light burden ·
          opportunity 100") instead of "V1 roster · read-only".
  - task: "V2 plan kickoff — one-click programme + phases + P3 + P5 + P6"
    implemented: true
    working: true
    file: "backend/feature_v2_coach_kickoff.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          New endpoint POST /api/v2/coach/clients/{cid}/plan/kickoff.
          Scaffolds the full V2 pipeline for a client that only has a
          roster: (1) seed goals_v2 (general.longevity default),
          (2) create programmes_v2, (3) build 2 phases (foundation +
          maintenance) directly, (4) run P3 objectives_build, (5) run
          P5 plan_build, (6) run P6 implementations_build. Also creates
          a plan_drafts row so the workspace publish flow lights up.
          Verified with Pietro Sangermano: single call created 2 phases,
          6 objectives, 28 assignments, 18 implementations. Pipeline now
          shows every stage lit except Validating/Published.
  - task: "Pipeline status widget — data-driven fallback"
    implemented: true
    working: true
    file: "backend/feature_v2_coach_directives.py (generation_status)"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          The generation_status widget only lit "Planning programme" and
          "Generating workouts" when it found a `jobs.kind=draft_build`
          row, which the one-click kickoff endpoint doesn't create.
          Added a data-driven fallback: infer Planning programme = done
          when training_objectives exist for the client; infer
          Generating workouts state from assignments vs implementations
          counts. Verified visually on Pietro's workspace — all stages
          now show green/amber correctly after kickoff.

frontend:
  - task: "AddClientSheet — double-JSON-stringify fix"
    implemented: true
    working: true
    file: "frontend/src/components/AddClientSheet.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          The CREATE ACCOUNT button silently failed because the payload
          was JSON.stringify'd twice (once by the sheet, once by the
          api() helper). Removed the local JSON.stringify. Verified live:
          TestLouis Hall created successfully from V2 Home → Add client.
  - task: "V2 workspace — Kickoff 'Build plan' button + Add client on V2 Home"
    implemented: true
    working: true
    file: "frontend/app/coach/client/[id]/workspace.tsx + (coach)/v2-home.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Added "Build plan" button in workspace ribbon (testID
          `kickoff-build-btn`) that shows ONLY when there's no
          programme yet. Calls /plan/kickoff and refreshes the month.
          Also added "Add client" button on V2 Home (testID
          `add-client-btn`) that opens AddClientSheet inline.

test_plan:
  current_focus:
    - "POST /v2/coach/clients/{cid}/plan/kickoff — happy path with roster present"
    - "POST /v2/coach/clients/{cid}/plan/kickoff — 409 when client is not V2-flagged"
    - "coach role can poll /roster/jobs/{jid} for uploads they created"
    - "V1 roster confirm bridges to V2 schedule_days for V2-flagged clients"
    - "AddClientSheet submits successfully (no double JSON stringify)"
    - "generation_status lights Planning programme + Generating workouts stages after kickoff"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      Batch of hotfixes shipped to unstick the V2 pipeline from
      "Planning programme". After a roster is uploaded:
        1. Coach can now poll the job (fixed 404)
        2. V1 roster → V2 schedule_days auto-bridged on confirm
        3. Coach clicks "Build plan" (new ribbon button) → single
           /plan/kickoff call scaffolds programme + phases + objectives
           and runs P5+P6 → assignments + implementations exist
        4. Pipeline widget now lights every stage green/amber based
           on actual DB state (no reliance on `jobs.kind=draft_build`).
      Also fixed AddClient double-stringify bug from earlier session.


##====================================================================
## V2 Kickoff — Goal-aware rewrite (marathon detection + rationale)
##====================================================================

backend:
  - task: "V2 kickoff rewritten to detect real goal + event from client DNA"
    implemented: true
    working: true
    file: "backend/feature_v2_coach_kickoff.py (rewritten)"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Original kickoff hardcoded 'general.longevity' regardless of
          what the client had actually told us. Rewrite:
            1. Resolves goal from client.profile.primary_goal_id /
               profile.main_goal_key / profile.event_type_pref (with
               GOAL_ALIASES to map "marathon" → "running.marathon" etc.)
            2. Reads the next active target event from db.events
            3. Sets programme end_date to event_date when present
            4. Chooses phase blueprint by taxonomy family:
                 running    → foundation → aerobic_base → build →
                              specific_prep → taper → race_week
                 triathlon  → similar with brick blocks
                 strength   → foundation → hypertrophy → strength → peak
                 body_comp  → foundation → hypertrophy → strength →
                              recovery
                 general    → foundation → maintenance
            5. Distributes phase weeks proportionally to the actual
               prep window (no more hardcoded 8w)
            6. Writes a FULL rationale decision_record so the coach can
               read exactly why the plan is built the way it is
            7. Returns rich response: goal source, event details,
               weeks_out, phase_plan with per-phase rationale, and the
               human-readable rationale string
          Verified live on Pietro Sangermano (client with marathon
          on 2027-01-17): kickoff now produces running.marathon /
          25-week prep / 6 phases (2+8+8+4+2+1) / 15 objectives /
          8 assignments in first 8w. Full rationale written to
          decision_records:
          "Goal=running.marathon (source=profile.primary_goal_id);
           target event: marathon on 2027-01-17; window=25w;
           phases: foundation (2w) → aerobic_base (8w) → build (8w) →
           specific_prep (4w) → taper (2w) → race_week (1w);
           client cap: 5 sessions/wk, equipment=['dumbbells', 'treadmill'];
           P3→15 objectives, P5→8 sessions, P6→8 implementations."

test_plan:
  current_focus:
    - "kickoff resolves marathon from profile.primary_goal_id"
    - "kickoff picks event_date as programme end when future event exists"
    - "phase blueprint matches taxonomy family (running/triathlon/strength/body_comp/general)"
    - "phase weeks sum exactly to total prep window"
    - "rationale is persisted as a decision_record on scope_kind=programme"
    - "kickoff returns rich audit payload (goal source, event, phase_plan, rationale)"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      Honest correction. Prior kickoff was too generic — it defaulted
      to general.longevity even though Pietro's DNA clearly stated
      Marathon on 2027-01-17. Rewrite now reads goal from profile
      *and* the active event, chooses the correct phase blueprint,
      sizes phases to the actual event window, and writes a full
      rationale decision_record so the coach can see WHY the plan
      looks the way it does. Also fixes silent objectives-count
      undercount from previous run (15 objectives now vs 6 before).
      Still open: (1) 2 out of 36 objective exposures failed to build
      an implementation — P6 slot template coverage gap. (2) "Why this?"
      drawer scope-query still needs to include programme_id +
      objective_id, not just assignment_id.


##############################################################################
# ITERATION 107 — V2 GENERATION ENGINE P0 FIXES
##############################################################################

backend:
  - task: "P0-3 burden/opportunity redesign (feature_v2_p4_roster.py)"
    implemented: true
    working: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          Rewrote _duty_burden + _training_opportunity around
          CATEGORICAL day_type baselines. Layover_arrival = HIGH (75+
          burden, opp ≤ 30). Turnaround, layover_departure = HIGH.
          Standby = MEDIUM. Home_day = LOW. TZ crossings, prior-24h
          recovery window, and duty duration additively increase burden.
          Validated on Pietro's 62 real schedule_days: layover_arrival
          n=7 avg_burden=75 avg_opp=0; home_day n=26 avg_burden=10
          avg_opp=89; standby n=8 avg_burden=45 avg_opp=23.
          BEFORE: every day had opp=100 (including turnarounds).

  - task: "P0-4 client-frequency cap in P5 scheduler"
    implemented: true
    working: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          feature_v2_p5_scheduling now reads profile.sessions_per_week_max
          / training_days_per_week and enforces a weekly cap.
          Days below opportunity floor (30 non-key / 50 key) are rejected
          with "low_opportunity_window" exception. Preferred_training_days
          list is honoured via +10 rank bump.

  - task: "P0-5 event-anchored programme end date"
    implemented: true
    working: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          _ensure_programme now ALWAYS recomputes start_date/end_date/
          event_ids from the current active event on every kickoff
          (previously stale on non-force runs). Emits a decision_record
          whenever the window changes. Pietro's programme end now
          correctly = 2027-01-17 (was 2026-09-20).

  - task: "P0-6 DNA sync to restrictions + equipment_contexts"
    implemented: true
    working: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          Added sync_dna_to_v2_collections() in feature_v2_common.py.
          Parses profile.injuries free-text into structured
          restriction rows (knee, back, shoulder etc. keywords).
          Upserts a permanent-scope equipment_context from
          profile.equipment. Called at start of kickoff. Pietro now has
          an equipment_context row (['bodyweight','dumbbells','treadmill'])
          and 0 restrictions (correctly parsed 'None').

  - task: "P0-1 / P1-3 blocks[] schema + running/mobility/cardio builders"
    implemented: true
    working: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          Added _build_running_blocks(), _build_mobility_blocks(),
          _build_cardio_generic_blocks() in feature_v2_p6_construction.py.
          Endurance sessions now populate blocks[] with warmup / steady /
          tempo / interval / cooldown segments including pace_target,
          hr_zone, effort_rpe, sets/reps for intervals, coaching cues.
          Also added 20+ new slot_templates for missing phase_kind × 
          objective_kind combinations.

  - task: "P0-2 READY gating (no impl without content)"
    implemented: true
    working: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          P6 now requires len(exercises) > 0 OR len(blocks) > 0 before
          transitioning assignment status to "ready". Otherwise leaves it
          at "building" with needs_coach_review=True AND opens a
          "impl_build_failed" exception in coach's tray.
          Response includes implementations_needing_review count.

  - task: "P1-2 drawer 'Why this?' scope expansion"
    implemented: true
    working: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          /api/v2/coach/clients/{cid}/decisions now accepts
          ?assignment_id= param that auto-expands scope to include
          objective_id + programme_id + phase_id + exposure_id.
          Frontend workspace.tsx drawer updated to call with
          assignment_id. Also renders blocks[] for endurance sessions.

frontend:
  - task: "V2 workout drawer renders blocks[] for endurance"
    implemented: true
    working: "NA"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          workspace.tsx drawer now renders detail.blocks[] with
          type / duration / hr_zone / pace / rpe / cue. Falls back to
          "Needs coach review" pill if both exercises AND blocks are empty.

metadata:
  created_by: "main_agent"
  version: "iter107"
  test_sequence: 107
  run_ui: false

test_plan:
  current_focus:
    - "kickoff produces properly categorised burden/opportunity per day_type"
    - "weekly cap enforced (no more than training_days_per_week sessions per ISO week)"
    - "programme end anchored to event_date on every kickoff run"
    - "restrictions collection populated from profile.injuries free-text"
    - "equipment_contexts (scope=permanent) upserted from profile.equipment"
    - "running assignments produce non-empty blocks[]"
    - "assignments without content stay at status=building"
    - "impl_build_failed exception opens for uncoverable slots"
    - "/decisions?assignment_id=xxx returns programme + objective + assignment scoped records"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      Executed authorised P0 fix plan for V2 generation engine:
      (1) rewrote burden+opportunity around categorical day_type
      baselines (P0-3); (2) added weekly cap in P5 (P0-4);
      (3) event-anchored programme end recomputed on every kickoff
      (P0-5); (4) DNA→restrictions/equipment_contexts sync at start
      of kickoff (P0-6); (5) blocks[] schema + running / mobility /
      cardio builders (P1-3, P0-1); (6) READY gating requires content
      (P0-2); (7) decisions endpoint scope expansion (P1-2). Also
      added new slot_templates for missing phase_kind × objective_kind
      combos, and legacy empty-impl purge on kickoff.
      Verified end-to-end on Pietro: 17 assignments across 5 weeks
      (well under 5/wk cap), 17 impls all with blocks=3 or exercises.
      Programme end correctly 2027-01-17. No more opp=100-everywhere.


##############################################################################
# ITERATION 108 — V2 ENGINE V2 (FULL WHAT→WHEN→HOW→VALIDATE REBUILD)
##############################################################################

backend:
  - task: "Sport taxonomy registry (10 goals, 42 session kinds)"
    implemented: true
    working: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          feature_v2_sport_configs.py — declarative source of truth for
          marathon / half / 10K / 5K / cycling.endurance / triathlon.olympic
          / muscle_gain / fat_loss / strength.general / general.fitness. Each
          goal has phase_sequence + phase_specs with QuotaRule (kind,
          exposures_per_week, priority, min_recovery_hours, duration_min,
          intensity_target, progression, can_skip_if_missed). Forbidden
          sequences catalogued per goal. Invariant checks run on import.

  - task: "Rolling roster context (feature_v2_roster_context.py)"
    implemented: true
    working: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          Replaced isolated day scoring with 72h look-back + 48h look-ahead.
          DayContext exposes burden, opportunity, available_time_min (CAP),
          recovery_state, recent_hard_days_48h, upcoming_hard_days_48h,
          consecutive_duty_days, sleep_opportunity, tz_shift_last_48h.
          Rolling penalties: recent hard streak, tz jetlag carryover,
          consecutive duty streak. Categorical baseline is a HINT, never a
          verdict.

  - task: "Sequencing engine (feature_v2_sequencing.py)"
    implemented: true
    working: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          PlacementPlan + validate_placement is the ONLY gatekeeper for
          schedule decisions. Enforces: hard-day cap per week, key-day cap
          per week, min recovery hours (family-specific), forbidden sequences
          (prev-day AND next-day), 48h key spacing, consecutive training
          days cap, same-day family collision, opportunity floors by priority.

  - task: "Demand engine v2 (feature_v2_demand_v2.py)"
    implemented: true
    working: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          build_demand() derives REQUIRED exposures from goal + phase +
          progression. Never invents demand from opportunity. Stable
          exposure_id per (client, goal, phase, kind, week, ordinal) —
          monotonic and persistent across reschedules. schedule_demand()
          iterates required exposures in priority order, validates every
          candidate via sequencing engine, surfaces Unfilled with
          candidate_hint_dates when placement fails.

  - task: "Construction v2 (feature_v2_construction_v2.py) — sport-typed session specs"
    implemented: true
    working: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          Discriminated union SessionSpec: running / cycling / swimming /
          strength / mobility / recovery / travel_recovery / activation /
          brick / rest. Each has its own payload shape. Running:
          warmup/main/cooldown with pace/HR/RPE/intervals. Strength:
          exercises[] with subs_allowed. Equipment labels are modality-
          appropriate (running=outdoor/treadmill + running_shoes; strength=
          gym/home/hotel_room/bodyweight_only). Running NEVER shows
          "bodyweight, dumbbells" — that was the observed bug.

  - task: "Validators v2 (feature_v2_validators_v2.py)"
    implemented: true
    working: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          validate_session: rejects zero-duration, empty payload, restriction
          conflicts. validate_programme: KEY unfilled (error), forbidden
          sequences in placements (error), weekly cap exceeded, exposure
          numbering not monotonic, same-day family duplicate. Returns
          ProgrammeValidation.ok=True only when ALL invariants pass.

  - task: "Engine v2 orchestrator + feature flag (feature_v2_engine_v2_kickoff.py)"
    implemented: true
    working: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          POST /api/v2/coach/clients/{cid}/engine-v2/kickoff
          GET  /api/v2/coach/clients/{cid}/engine-v2/draft
          GET  /api/v2/coach/clients/{cid}/engine-v2/status
          PATCH /api/v2/coach/clients/{cid}/engine-v2/enable
          PATCH /api/v2/coach/clients/{cid}/engine-v2/disable
          Draft/shadow output only in plan_drafts_v2. Existing Live plans
          untouched. HTTP smoke: 409 pre-enable, 200 with graceful
          no_schedule_days branch, enable/disable idempotent.

  - task: "Regression test suite (37 tests, all green)"
    implemented: true
    working: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          /app/backend/tests/test_engine_v2_invariants.py
          Groups: TestGoalConfigInvariants (6), TestRosterContextRolling (6),
          TestDemandDoesNotInventSessions (3), TestSchedulerRespectsInvariants
          (8), TestConstructionSportTyped (6), TestValidatorGate (2),
          TestPietroAugustRegression (6). Verifies every one of the 13+
          named failure modes from the user directive.

  - task: "Pietro deterministic fixture + shadow report"
    implemented: true
    working: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          /app/backend/scripts/run_pietro_shadow.py builds a marathon draft
          from Pietro's real DNA + Cathay-shape roster and writes the
          comparison to /app/memory/PIETRO_V2_ENGINE_V2_DRAFT.md. All 11
          named failure modes verified fixed. 4 unfilled strength sessions
          surfaced with candidate_hint_dates — coach gets an actionable
          exception instead of a silent decision.

  - task: "Coach workspace renders V2 Live/Draft placements on the calendar"
    implemented: true
    working: "NA"
    file: "/app/backend/feature_v2_coach_dashboard.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: |
          Coach dashboard Publish silently produced an empty calendar because
          workspace_month only pulled from the legacy `workout_assignments`
          collection while Engine V2 stores its result in `plan_live_v2`
          (placements + session_specs). Bridged the two:
          - workspace_month now loads active plan_live_v2, else falls back
            to the active plan_drafts_v2 (needs_review / ready_for_review).
          - Each placement is emitted as a synthetic assignment card with
            id="v2p:<source_id>:<exposure_id>", status_kind=live|review,
            equipment/environment surfaced, key session flag preserved.
          - Rest placements are skipped (day cell already reads "Rest").
          - Added new endpoint
            GET /api/v2/coach/clients/{cid}/engine-v2/placement-detail
            that returns placement + session_spec + required_exposure so the
            frontend drawer can hydrate without touching workout_implementations.
          - Frontend workspace drawer now detects v2p: IDs and calls the new
            endpoint, adapting running/cycling/swim/brick/strength/mobility
            payloads into blocks[] + exercises[] the existing drawer renders.
          - "Edit inline" is hidden for V2 placements (no inline editor yet
            for immutable Live plans; will be a separate feature).
          Backend verified with Pietro's account: /workspace/2026-07 now
          returns counts.live=3, three v2p: assignments hydrated with
          duration/equipment/status. Needs full E2E retest through the
          publish flow + drawer.

  - task: "V2 client-side bridge — legacy /workouts/* → plan_live_v2"
    implemented: true
    working: "NA"
    file: "/app/backend/feature_v2_client_bridge.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: |
          Coach dashboard was rendering the Live V2 plan correctly but the
          CLIENT's Expo app still read from legacy /workouts/week,
          /calendar/timeline, and /workouts/{id} — which all hit the empty
          `workouts` collection for V2 clients. Client saw "REST & RECOVER"
          on days that had published workouts.

          Added `feature_v2_client_bridge` with:
          - synth_workouts_for_user(db, user_id, start_iso?, end_iso?)
            reads plan_live_v2 active doc and maps each non-rest placement
            + session_spec → legacy workout row shape (id="v2p:{live_id}:
            {exposure_id}", title, focus, duration_min, blocks[], exercises[],
            warmup, day_load, key_session, location, needs_coach_review,
            approved=True, coach_locked=True, source="engine_v2").
          - synth_workout_by_wid(db, wid, user_id) resolves a v2p: id back
            to the workout row, only if the plan_live_v2 doc still matches
            (active + owned by user).

          Wired into server.py:
          - GET /workouts/week — appends V2 rows (dedup by date).
          - GET /calendar/timeline — splices V2 rows into wk_map for the
            timeline day cells (workout_id, workout_title, completed,
            key_session, location surfaced automatically).
          - GET /workouts/{wid} — recognises "v2p:" prefix, resolves via
            bridge, 404 if the source doc is gone.

          Backend verified with Pietro:
          - workouts/week → 3 rows (Run Easy 07-28, Mobility 07-28,
            Run Long 07-31), all source=engine_v2.
          - calendar/timeline → workout dots on 07-28 + 07-31.
          - workouts/{v2p_id} → full workout with warmup + blocks[]
            (warmup Z1 / long_steady Z2 MP+90s / cooldown Z1).

          Zero frontend changes — the existing client home / calendar /
          workout screens now render V2 plans automatically.

metadata:
  version: "iter109b"
  test_sequence: 109
  run_ui: false

agent_communication:
  - agent: "main"
    message: |
      Full V2 engine rebuild landed as parallel modules behind a per-client
      `engine_v2` feature flag. Old engine untouched. 37/37 regression tests
      pass. Pietro deterministic report proves all 11 named August-plan
      failures are gone.
  - agent: "main"
    message: |
      Fixed the "Publish did nothing" bug. Root cause: workspace_month
      rendered from workout_assignments only, while Engine V2 stores its
      results in plan_live_v2. Bridged the two + added placement-detail
      endpoint + drawer adapter. Please backend-verify (workspace_month
      returns V2 placements + placement-detail resolves) and then frontend-
      verify the coach can click "Publish" on Pietro's July plan and see
      the workouts land on the Roster+Plan calendar cells with a working
      workout drawer.


##====================================================================
## Iter 128b — Flight Support Variety Engine + Coach Media Queue Matrix
##====================================================================

backend:
  - task: "Flight Support Variety / Rotation Engine (P0)"
    implemented: true
    working: "NA"
    file: "backend/feature_aviation_support.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Replaced the hardcoded single-protocol-per-trigger with a deterministic
          Variety Engine. Added `POOLS` mapping every trigger context to a list
          of safety-equivalent alternates (pre_flight_light has 5 options,
          post_flight_reset 4, layover_full 3, movement_break 3, arrival_mobility 2,
          turnaround_reset 2). Added 11 NEW ProtocolSpecs (breathing, neck/shoulder,
          hip opener, gentle stretch, legs-up-wall, longer explore/park walks,
          micro-stretch, walking break, arrival breathing, turnaround breathing) so
          there is genuine variety. Added `restricted_regions` + `required_equipment`
          + `environment` fields on ProtocolSpec.

          `pick_from_pool()` implements the priority order requested by the user:
          Safety → Suitability (equipment/env) → Context/Time → Objective (family match)
          → Environment preference → Media availability (deferred) → Recent repetition
          penalty → Deterministic hash tiebreak. Recent-repetition penalty scales
          with recency (newest use = -10, oldest in window = -2). Lookback = 5
          (matches "recommended" per user).

          `select_interventions_for_day` now accepts `user_id`, `history_keys`,
          `restrictions`, `equipment_available` (all optional, backward-compatible).
          `get_flight_support_by_date` loads history from `flight_support_activity`
          (newest 5 protocol_keys) + injury regions from profile.injuries /
          persistent_restrictions + equipment from profile.equipment BEFORE
          calling the selector.

          Unit-checked locally:
            - Deterministic (same inputs → same key).
            - Different dates → different picks (per-date tiebreak).
            - Knee restriction → hip_opener excluded.
            - History of [breathing, neck_shoulder, mobility] → picks activation next.

          Endpoint contract unchanged. Interventions now include `pool_key` for
          future coach overrides.

  - task: "GET /api/coach/flight-support/media-queue (P1)"
    implemented: true
    working: "NA"
    file: "backend/feature_flight_support_media.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          New coach-only endpoint that returns the Media Queue matrix. Reads
          from `db.media_queue` (rows created by resolve_flight_support_frames
          when a Flight Support exercise is missing preferred-persona media).

          Query params:
            status=all|needs_media|complete
            persona_missing=any|pilot|louis|female  (filter rows lacking that persona)
            search=<substring>
            limit=<int, default 200>

          Response shape:
            { items: [{ exercise_id, exercise_name, status, preferred_persona,
                        matrix: { pilot|louis|female : { start|mid|end : bool } },
                        missing: { persona: [missing slots] },
                        covered, total_cells, flight_support_contexts, updated_at }],
              stats: { total, needs_media, complete, pilot_missing_count,
                       louis_missing_count, female_missing_count } }

          Sort key: PILOT-missing first, then LOUIS, then FEMALE, then complete.
          Coach role guard: 403 for anyone not in ('coach','admin').

          Manually verified: created 3 test rows (Dumbbell Row, Goblet Squat,
          Push-Up), endpoint returns them ordered by PILOT-missing count with
          correct matrix cells and stats.

frontend:
  - task: "Coach Media Queue Matrix UI (P1)"
    implemented: true
    working: true
    file: "frontend/app/(coach)/media-queue.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          New desktop-only coach screen at /(coach)/media-queue. Registered in
          the DesktopShell sidebar with `images-outline` icon between Videos
          and Messages, and hidden from mobile tabs via href:null.

          Screen layout:
            - Header with "PERSONA COVERAGE" title.
            - Stats strip: 6 pills (TOTAL, NEEDS MEDIA, COMPLETE, PILOT ✕,
              LOUIS ✕, FEMALE ✕).
            - Filter row: search input + status chips (ALL/NEEDS/COMPLETE) +
              persona-missing chips (ANY/PILOT/LOUIS/FEMALE).
            - Card list: one per exercise with 3×3 matrix cells showing ✓/✗ per
              (persona × slot). Preferred persona label highlighted in brand red.
              Complete rows show green pill; needs-media rows show amber pill.
            - Tap → deep-links to /(coach)/exercises with the exercise name so
              the coach can upload/generate the missing frames using the
              existing editor + Nano Banana button.

          Screenshot verified end-to-end on 1440×900: Louis coach signed in,
          sidebar "Media Queue" active, 3 exercises rendered with correct
          matrix cells, PILOT column all-red (missing), LOUIS partial, filters
          responsive. Pull-to-refresh + focus-effect re-load working.

test_plan:
  current_focus:
    - "Flight Support Variety Engine — deterministic rotation, safety filter, history penalty"
    - "GET /api/coach/flight-support/media-queue — coach guard, matrix + stats shape"
    - "Coach Media Queue Matrix UI — filters + tap-through to exercise editor"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      Iter 128b delivered two P0/P1 items from the Flight Support Beta upgrade:

      (1) Variety / Rotation Engine (backend, feature_aviation_support.py):
      Replaced fixed protocol-per-trigger with deterministic pool selection.
      11 new alternate protocols added (breathing, neck/shoulder, hip opener,
      gentle stretch, legs-up-wall, park walk, longer explore walk, micro-
      stretch, walking break, arrival breathing, turnaround breathing).
      Priority order enforced: Safety → Equipment → Time → Objective →
      Environment → Recency → Deterministic tiebreak. 5-session lookback
      from flight_support_activity. Backward-compatible signature — existing
      callers still work. Coach interventions now carry `pool_key`.

      (2) Coach Media Queue Matrix (backend + frontend):
      - GET /api/coach/flight-support/media-queue returns the persona × slot
        matrix + stats, sorted PILOT-missing first.
      - Desktop-only coach screen at /(coach)/media-queue with filter chips,
        search, and tap-to-editor deep link.

      Please TEST:
      Backend:
        (a) /client/today & /client/flight-support show variety-picked keys
            for the reviewer / pietro accounts, with pool_key populated.
        (b) /coach/flight-support/media-queue with different filters returns
            the correct sort + stats + matrix cells + coach guard.
        (c) Variety engine determinism: same user + roster → same picks
            across restarts; different dates rotate; history reshuffles.
        (d) Restrictions: user with `injuries: 'knee pain'` never gets
            hip_opener or activation.
      Frontend:
        (e) Sidebar nav Media Queue renders on wide viewport, is hidden from
            mobile tabs.
        (f) Matrix cells accurate, sort order correct (PILOT-missing first),
            chip filters re-query correctly, tap navigates to exercise editor.

