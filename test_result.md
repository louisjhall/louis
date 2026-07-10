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
