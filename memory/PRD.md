# CrewFit V1 — PRD

## What it is
Airline-crew fitness coaching mobile app. A client uploads their flight roster; AI extracts the week's duties and scores each day Green/Amber/Red; AI drafts a matching weekly workout plan; a coach approves/edits before the client trains.

## Core promise (V1)
**"Turn a roster into a smart weekly training plan that a coach can edit."**

## Users (roles)
- **Client** – airline crew (pilot / cabin crew) training around rotations.
- **Coach** – reviews/edits AI plans and messages clients.

## V1 feature set (built)
### Client
- Login / Signup / Onboarding form
- Upload roster (PDF or photo) → AI extraction (Gemini 2.5 Flash) → confirm & edit
- Weekly training calendar with Green/Amber/Red day loads
- Today's workout hero + full weekly plan
- Workout detail: swap exercises, edit sets/reps, complete workout with RPE
- Weekly check-in (energy, sleep, soreness, stress, weight, notes)
- Nutrition tracker (calorie + protein targets, meal log, photo → AI feedback via Gemini)
- Progress photos + weight
- Messaging with coach
- Profile / settings + integration placeholders (Apple Health, Garmin, Strava, Oura, Google Health Connect)

### Coach
- Coach login (role-based routing)
- All clients list with pending-approval badges + latest roster preview
- Client detail (profile, roster, all workouts, latest check-in)
- Approvals queue for AI-generated workouts
- Workout builder / editor (edit title, exercises, cycle Green/Amber/Red, add coach notes)
- Approve / reject AI plans
- Exercise library (CRUD, category filter)
- Messaging with clients

### AI
- Roster reader: extracts flights / layovers / duties / off days from PDF or image
- Green/Amber/Red day scorer (rule-based on top of extracted data)
- Weekly workout generator (Claude Sonnet 4.5) — respects load per day
- Meal photo AI feedback (calories, protein, quality, tip)

## Stack
- Frontend: Expo 54, Expo Router, React Native, expo-image, expo-image-picker, expo-document-picker
- Backend: FastAPI + Motor (MongoDB), JWT auth, bcrypt
- LLM: emergentintegrations (Claude Sonnet 4.5 text, Gemini 2.5 Flash file/image), EMERGENT_LLM_KEY

## Explicitly deferred (V2)
Payments, community, full food database, barcode scanner, live Apple Health / Garmin sync, MyFitnessPal, advanced analytics, referrals, multi-coach, corporate dashboard.

## Business enhancement idea
"Layover Coach" premium tier — auto-detect the destination airport of a red-eye layover and generate a hotel-room-only 20 min mobility+strength session, no equipment required. Adds subscription retention on the exact moment users need the app most (arriving jet-lagged in a hotel).
