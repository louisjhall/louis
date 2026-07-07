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
