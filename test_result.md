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
