# CrewFit — Project Handover Report

**Prepared:** June 2026
**Purpose:** Comprehensive snapshot of the CrewFit codebase, product, integrations, economics, risks and roadmap — designed to be pasted into ChatGPT (or any strategic advisor) for review, planning and decision support.
**Audience:** Founder (personal use). Direct, technical-but-plain tone.
**Sensitive data policy:** No API keys, secrets, private URLs, or user PII included.

---

## 1. Executive Summary

CrewFit is an aviation-professional-focused fitness + wellbeing platform (pilots, cabin crew). It combines:

- **Client mobile app** — workouts, habits, roster-aware planning, weekly check-ins, and now a full **Nutrition Centre** with barcode + AI photo meal logging + travel-aware guidance.
- **Coach dashboard** — client management, workout/exercise library, video content pipeline, coaching DNA, social studio, approvals, analytics, changelog.
- **AI layer** — Atlas (Claude Sonnet 4.5) for insights + travel guidance + photo meal analysis; Gemini Nano Banana for brand imagery; OpenAI Whisper for transcription.

**Current state:** MVP+ complete. Nutrition Centre (Phases 1–5) shipped. Exercise library unified. Media storage abstracted for S3/R2. Ready to move from **build phase** into **polish + launch phase**.

**Codebase size:** ~14,500 lines of Python backend, 2,700 lines of nutrition frontend alone, ~15+ feature modules.

---

## 2. Product Vision & Positioning

**One-liner:** "The only fitness + nutrition app built for the reality of aviation life — jet lag, hotel gyms, standby, layovers, and duty-timed eating."

**Differentiators vs. MyFitnessPal / Whoop / Freeletics:**
1. **Roster-aware** — knows your duty schedule, layovers, timezone shifts.
2. **Coach-in-the-loop** — real coach dashboard, not just an algorithm.
3. **Aviation-native flows** — standby days, holiday mode, sickness mode, airport eating decisions.
4. **Atlas AI persona** — one voice across insights, meal analysis, and travel guidance (Claude Sonnet 4.5).

**Target user:** ~200k–500k long-haul crew globally who currently hack together generic apps that don't understand their life.

---

## 3. Current Feature State

### ✅ Shipped (client-facing)
- **Auth** — JWT + bcrypt, signup / login / onboarding
- **Assessment engine** — initial fitness/lifestyle profile + reassessment prompts
- **Coaching DNA** — living profile, updated over time
- **Workouts** — sets/reps player, personal records, dedupe index
- **Schedule / Roster** — roster upload, day overrides, holidays, sickness, standby, calendar
- **Habits** — tracking, reviews, weekly log
- **Weekly check-in** — reality events, progress log
- **Nutrition Centre (5 Phases):**
  - P1: Dashboard + macro targets + manual food logging + coach visibility
  - P2: Barcode scanner (Open Food Facts, cached, Nutritionix-ready)
  - P3: AI Photo Meal Scanner (Claude Sonnet 4.5 Vision)
  - P4: Travel/airport/timezone guidance (Atlas)
  - P5: Weekly insights + Sunday check-in integration + coach to-do generation
- **Notifications** — in-app + push scaffold (Emergent push key)

### ✅ Shipped (coach-facing)
- Client list, individual client drill-down
- Approvals queue
- Message drafts / scheduled messages
- Analytics + overview
- Content library (unified `exercises_v2` — 248 legacy V1 exercises migrated)
- Video pipeline + subtitles + brand images
- Social Studio (recording, drafts, teleprompter)
- Changelog / day change log
- Nutrition coach view

### 🟡 Partially done / mocked
- **Buffer integration** — UI hooks present, OAuth wiring parked (needs user API keys)
- **S3/R2 storage** — abstraction complete (`storage.py`), currently falling back to local disk (no cloud env vars set)

### 🔴 Not yet started
- Community / social feed (deferred to V2)
- GPS-based cardio players — running, cycling, swimming (V2)
- Nutritionix / FatSecret provider layer (P2 backlog)

---

## 4. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│  Expo (React Native, SDK 54) — iOS / Android / Web  │
│  expo-router file-based routing, react-native-web   │
└──────────────────┬──────────────────────────────────┘
                   │ HTTPS (all routes prefixed /api)
                   │ Kubernetes ingress → port 8001
┌──────────────────▼──────────────────────────────────┐
│  FastAPI (0.110)  •  Uvicorn                        │
│  server.py (main) + 14 feature_*.py modules         │
│  Auth: JWT + bcrypt                                 │
└──────────────────┬──────────────────────────────────┘
                   │  motor async driver
┌──────────────────▼──────────────────────────────────┐
│  MongoDB (Atlas / local dev)                        │
│  ~50 collections, indexed on user_id + date_local   │
└─────────────────────────────────────────────────────┘

  ↔ Emergent LLM Key (Claude 4.5, GPT, Gemini, Whisper)
  ↔ Open Food Facts (free, no key)
  ↔ Emergent Push Key (FCM/APNs abstraction)
  ↔ S3/R2 (via boto3, currently local-disk fallback)
```

**Deployment:** Emergent platform (Publish button → generates iOS/Android/Web builds).

---

## 5. Tech Stack & Dependencies

### Backend (Python 3.11)
- `fastapi 0.110.1`, `uvicorn 0.25.0`
- `motor 3.3.1` (async MongoDB), `pymongo 4.6.3`
- `pydantic >=2.6.4`, `pyjwt`, `bcrypt 4.1.3`, `passlib`
- `boto3 >=1.34.129` — S3/R2 abstraction
- `emergentintegrations 0.2.0` — LLM + push key gateway
- `python-multipart`, `pandas`, `numpy`, `requests`
- `cryptography`, `requests-oauthlib` (for future Buffer OAuth)

### Frontend (Expo SDK 54, React 19.1)
- `expo-router 6.0.24` — file-based routing
- `react-native 0.81.5`, `react-native-web 0.21.0`
- `expo-camera 17` — barcode + photo capture
- `expo-image-picker 17`, `expo-image 3`
- `expo-notifications 0.32`, `expo-audio 1.1`
- `react-native-reanimated 4.1.1`, `react-native-gesture-handler 2.28`
- `expo-secure-store`, `@react-native-async-storage/async-storage`
- `date-fns`, `dayjs`

**No web-only libs. No deprecated expo-av / expo-barcode-scanner / expo-google-fonts.** Clean.

---

## 6. Database Schema (MongoDB)

**~50 collections.** Grouped by domain:

| Domain | Key Collections |
|---|---|
| **Users / Auth** | `users`, `assessments`, `coaching_dna`, `dna_history` |
| **Schedule** | `rosters`, `roster_jobs`, `schedule_events`, `day_overrides`, `day_change_log`, `events`, `hotels` |
| **Workouts** | `workouts`, `workout_sets`, `exercises_v2` (unified), `exercise_content_images`, `exercise_content_log`, `exercise_videos`, `exercise_video_blobs`, `personal_records`, `move_history` |
| **Habits** | `habits`, `habit_logs`, `habit_reviews`, `daily_pulse` |
| **Nutrition** | `nutrition_logs`, `nutrition_targets`, `nutrition_insights`, `nutrition_atlas_tips`, `nutrition_favourites`, `nutrition_hydration`, `nutrition_notes`, `nutrition_photo_scans`, `nutrition_travel_cache`, `barcode_cache`, `meals` |
| **Coach** | `coach_tasks`, `coach_alerts`, `coach_change_log`, `coach_scripts`, `messages`, `message_drafts`, `scheduled_messages` |
| **Content / Brand** | `crewfit_images`, `image_jobs`, `gen_jobs`, `content_jobs`, `weekly_videos` |
| **Check-ins / Reality** | `checkins`, `check_ins`, `reality_events`, `reassessment_prompts`, `progress` |
| **Notifications** | `notifications` |

⚠️ **Note:** `checkins` vs `check_ins` — two collections exist due to historical refactor. Should be consolidated (see §12 tech debt).

Indexes: `user_id`, `date_local`, `(user_id, date_local)` compound on nutrition + workout + habit collections.

---

## 7. Backend Modules & API Surface

**~1,300 route handlers** across the modules. Route count per module:

| Module | Routes | Purpose |
|---|---|---|
| `server.py` | **705** | ⚠️ Everything not extracted yet — auth, workouts, schedule, DNA, reassessment, coach tasks, cron jobs |
| `feature_habits.py` | 111 | Habit CRUD + reviews + daily pulse |
| `feature_social_studio.py` | 86 | Recording, subtitles, scripts, drafts |
| `feature_coach_v1.py` | 70 | Coach approvals, alerts, message drafts |
| `feature_nutrition.py` | 52 | Nutrition dashboard, logging, targets |
| `feature_standby.py` | 49 | Standby day mechanics |
| `feature_nutrition_barcode.py` | 47 | Open Food Facts + cache |
| `feature_nutrition_travel.py` | 44 | Airport, timing, decision, travel |
| `feature_nutrition_insights.py` | 40 | Weekly insights, check-in hooks |
| `feature_nutrition_photo.py` | 34 | Claude Vision photo scan |
| `feature_exercise_content.py` | 33 | Exercise content library |
| `feature_brand_images.py` | 29 | Nano Banana brand image gen |
| `feature_notifications.py` | 28 | Push + in-app |
| `feature_admin_migrations.py` | 21 | One-shot migrations (V1→V2 exercises) |
| `feature_profile.py` | 10 | Profile photo, location |
| `storage.py` | 8 | Presigned URLs, upload helpers |

**Total: ~1,367 endpoints.** Yes, large. Consolidation candidates flagged in §12/§18.

---

## 8. Frontend Structure

```
/app/frontend/app/
  (auth)/            login, signup, onboarding
  (client)/          home, calendar, messages, nutrition, profile
  (coach)/           overview, clients, analytics, approvals, calendar,
                     changelog, checkins, exercises, library, messages,
                     profile, videos
  coach/             brand-images, exercise-content, nutrition,
                     draft/, checkin/, habit-review/, teleprompter/,
                     client/, scripts/
  nutrition/         index, log, targets, barcode, photo-scan,
                     favourites, history, insights, travel, airport,
                     timing, decision
  workout/[id]       Workout player
  schedule/          holiday, sickness
  social-studio/     record, subtitles
  video/[id]         Video player
  assessment.tsx, atlas-intro.tsx, checkin.tsx, coaching-dna.tsx,
  event.tsx, guard-rails.tsx, progress.tsx, reality-history.tsx,
  roster-upload.tsx, welcome.tsx
```

**~90 route files.** All using expo-router file-based routing. Cross-platform (iOS + Android + Web via react-native-web).

`/app/frontend/src/` — components, hooks, lib (theme, api, ux modal), utils, desktop overrides.

---

## 9. Third-Party Integrations

| Integration | Purpose | Key Source | Status |
|---|---|---|---|
| **Claude Sonnet 4.5** | Atlas AI persona — insights, travel guidance, meal photo analysis | Emergent LLM Key | ✅ Live |
| **Gemini Nano Banana** | Brand imagery generation | Emergent LLM Key | ✅ Live |
| **OpenAI Whisper-1** | Speech-to-text (social studio subtitles) | Emergent LLM Key | ✅ Live |
| **OpenAI GPT (fallback)** | Text generation fallback | Emergent LLM Key | ✅ Available |
| **Open Food Facts** | Barcode → nutrition data | Free, no key | ✅ Live |
| **Nutritionix** | Richer barcode data (fallback) | User keys (not set) | 🟡 Ready, dormant |
| **Emergent Push** | iOS/Android push abstraction | Emergent Push Key | 🟡 Scaffold; works only after native build |
| **S3 / Cloudflare R2** | Media storage (photos, videos) | Not set | 🟡 Falls back to local disk |
| **Buffer** | Social scheduling | User OAuth (parked) | 🔴 Blocked on user creds |
| **JWT + bcrypt** | Auth | Self-hosted | ✅ Live |

**Zero direct third-party keys in code.** All LLM traffic routes through Emergent LLM Key. All push traffic routes through Emergent Push Key.

---

## 10. Storage Strategy

`storage.py` implements a **provider-agnostic upload layer**:

- **DISK mode (current default):** Files written to `/app/backend/uploads/` — fine for dev but fills container disk over time.
- **S3/R2 mode (auto-activates):** When env vars `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_ENDPOINT_URL` (R2) are present, `boto3` takes over.
- **Presigned URL support** for direct client → cloud uploads (bypasses backend disk entirely).

**Current risk:** Every AI photo scan + brand image + video is stored locally. On production traffic this will exhaust the pod disk within weeks. **Priority action: point at Cloudflare R2 (cheapest egress) before launch.**

---

## 11. Unit Economics (rough estimates)

### Assumptions
- Target ARPU: **£9.99/month** (aviation crew tier)
- Average client behavior per month:
  - 2 AI photo scans (Claude Vision)
  - 15 barcode lookups (Open Food Facts, free)
  - 4 travel guidance calls (Claude text)
  - 4 weekly insights (Claude text)
  - 1 brand image gen (Nano Banana) — coach only
  - 5 minutes Whisper transcription (coach studio only)

### Per-client monthly variable cost (very rough)

| Line item | Volume | Est. unit cost | Monthly cost |
|---|---|---|---|
| Claude Sonnet 4.5 vision (photo scan) | 2 calls × ~1200 tokens + image | ~$0.012 / call | **~$0.024** |
| Claude 4.5 text (travel + insights) | 8 calls × ~800 tokens | ~$0.004 / call | **~$0.032** |
| Open Food Facts | 15 lookups | Free | **$0.00** |
| Nano Banana image (coach-side) | 1/mo per coach (not per client) | ~$0.03 / image | ~$0.03 / coach |
| Whisper-1 | 5 min/mo (coach-side) | ~$0.006 / min | ~$0.03 / coach |
| MongoDB Atlas | shared M10-ish | ~$60/mo fixed | negligible / client at scale |
| S3/R2 storage | ~10 MB/client/mo (photos) | ~$0.015/GB (R2) | **~$0.0002** |
| R2 egress | ~50 MB/client/mo | free (R2!) | **$0.00** |
| Compute (Emergent pod) | shared | ~$40/mo per pod | negligible / client at scale |
| Push (Emergent) | included | 0 | **$0.00** |

**Per-client variable cost: ~£0.06–0.10 / month**
**Gross margin at £9.99 ARPU: ~99%** (before fixed infra)

### Break-even math
- Fixed infra (Mongo + compute): ~£80–100/mo
- Break-even: **~10–12 paying clients**
- At 100 clients: ~£1,000 MRR, ~£995 gross profit
- At 1,000 clients: ~£10,000 MRR, ~£9,900 gross profit

### Cost hot-spots to watch
1. **Photo scans** — if crew log every meal, cost jumps 5–10×. Cap free-tier scans at 30/mo.
2. **Weekly insights** — currently cheap but scales linearly.
3. **Storage** — R2 is the right call (no egress). If you accidentally use S3, egress will bite.
4. **Coach-side** — Nano Banana + Whisper are the big-ticket coach costs. Consider a per-coach add-on tier.

---

## 12. Known Issues & Technical Debt

### 🔴 Critical
1. **`server.py` is ~7,000 lines.** Cron jobs, coach task creation, workout scanning, DNA logic, reassessment engine — all in one file. Any change risks regressions across unrelated features.
2. **Local disk storage in production would fill the pod within weeks.** S3/R2 env vars need to be set before any real traffic.
3. **Two check-in collections (`checkins` + `check_ins`).** Historical refactor artifact. Reads may miss data written under the other name.

### 🟠 High
4. **No rate limiting on AI endpoints.** A malicious user could burn Emergent LLM credit in minutes.
5. **No cost telemetry per user.** We can't currently see who's driving LLM spend.
6. **`exercises_v2` migration complete but old `exercises` collection still present.** Should be archived + dropped.
7. **Buffer OAuth scaffolded but not implemented.** UI implies it works — needs either wiring or a "Coming soon" gate.

### 🟡 Medium
8. **No E2E test for the full nutrition flow.** Unit tests exist per module but no end-to-end journey test.
9. **Test credentials hardcoded in memory file.** Fine for dev, but rotate before public launch.
10. **`react-native-dotenv` used alongside `expo-constants`.** Pick one — creates confusion.
11. **No dark mode toggle** — theme is fixed. Aviation crew often work in dim cabins.

### 🟢 Low
12. **Some route handlers return raw dicts** — should use Pydantic response models for type safety.
13. **Bare `except:` in a few older handlers.** Should be `except Exception as e:` with logging.

---

## 13. Testing Status

- **34 pytest files** in `/app/backend/tests/` covering nutrition (barcode/photo/travel/insights/v1), workouts, habits, roster, standby, coach dashboard, brand images, exercise content, social studio, subtitles, notifications, assessment engine, reality engine, override rules, schedule player, and more.
- **Test iterations logged:** through iteration 41 in `/app/test_result.md`.
- **Testing agent** used extensively. Frontend tested via playwright/browser automation. Backend tested via HTTP integration tests.
- **Known regressions:** none open.
- **Coverage gaps:** end-to-end user journeys, load testing, security fuzzing.

---

## 14. Deployment / Publishing Status

- **Preview environment:** live on Emergent pod (web preview + Expo Go QR).
- **Production deployment:** not yet triggered. User needs to click **"Publish"** in Emergent (top right) to generate iOS + Android + Web builds.
- **App Store readiness:** iOS `NSCameraUsageDescription`, `NSPhotoLibraryUsageDescription`, `NSMicrophoneUsageDescription` all set in `app.json`.
- **Play Store readiness:** Android permissions declared. **Privacy policy URL not yet provided** — blocker.
- **Bundle identifiers, icons, splash screen:** set.
- **OTA update strategy:** Expo EAS Update (available once first build is published).

---

## 15. Security & Privacy

### ✅ Done
- Passwords hashed with `bcrypt` (cost factor 12).
- JWT with reasonable expiry.
- All API routes require auth except `/api/auth/*`.
- No API keys in code — all secrets in `.env` (git-ignored).
- HTTPS enforced by Emergent ingress.
- User photos stored per-user, not publicly listed.

### 🟡 Gaps
- No 2FA.
- No password reset flow (email delivery not integrated).
- No account deletion flow (**GDPR requirement**).
- No data export flow (**GDPR requirement**).
- Privacy policy + terms of service — not written.
- Cookie/tracking policy — not applicable yet (no analytics).

---

## 16. Risk Register (with mitigation priorities)

| # | Risk | Likelihood | Impact | Priority | Mitigation |
|---|---|---|---|---|---|
| R1 | Emergent LLM credit exhausted by abuse | Medium | High (service down) | **P0** | Add per-user daily quota + monitoring dashboard |
| R2 | Pod disk fills from photo uploads | High (at scale) | High (crashes) | **P0** | Set S3/R2 env vars, migrate uploads/ folder |
| R3 | `server.py` bloat causes regression during change | High | Medium | **P1** | Extract cron, coach task, workout scan into services/ |
| R4 | GDPR non-compliance (no deletion / export) | High (once EU users onboard) | High (fines) | **P1** | Build account deletion + data export before EU launch |
| R5 | App Store rejection on first submission | Medium | Medium (delay) | **P1** | Test-flight rehearsal; verify all permission descriptions |
| R6 | Buffer never delivered — coach expectation gap | Medium | Low | **P2** | Either wire OAuth or hide UI behind feature flag |
| R7 | Two check-in collections cause data loss | Low | Medium | **P2** | Migration script to unify, then drop old collection |
| R8 | Coach-side LLM costs exceed pricing | Low | Medium | **P2** | Per-coach add-on tier or usage caps |
| R9 | Emergent platform lock-in | Low | Medium | **P3** | Document escape hatch (backend is standard FastAPI + Mongo — portable) |
| R10 | Model deprecation (Claude 4.5 → 5.x) breaks flows | Medium | Low | **P3** | Version-pin model IDs, add integration test on model calls |

---

## 17. Roadmap

### 🔴 Immediate (this week / next week)
- **Configure S3/R2 credentials** — activate cloud storage (fixes R2)
- **Refactor `server.py`** — extract cron + coach tasks + workout scanning (fixes R3)
- **Add per-user LLM rate limit** — dead-simple in-memory counter to start (fixes R1)
- **Unify `checkins` / `check_ins` collections** (fixes R7)
- **Draft privacy policy + terms** — even a template is enough to unblock stores

### 🟡 Upcoming (2–4 weeks)
- **Buffer OAuth wiring** — when user provides Client ID/Secret
- **Google Play production readiness** — permissions audit, screenshots, feature graphic
- **App Store production readiness** — same, plus review notes explaining aviation context
- **Account deletion + data export** — GDPR must-have
- **Nutritionix / FatSecret provider layer** — richer barcode data

### 🟢 Backlog (post-launch)
- **Community / social feed** (V2)
- **GPS players** — running / cycling / swimming with route recording (V2)
- **Wearable integrations** — Whoop, Garmin, Apple Watch HealthKit (V2)
- **Coach marketplace** — multi-coach onboarding, revenue share
- **Dark mode**
- **Localization** — Spanish, French, German (aviation is global)
- **Sleep + jet-lag prediction module**

---

## 18. Suggested Refactors

**Priority order — start top-down:**

1. **Break up `server.py`** into:
   - `services/auth.py`
   - `services/cron.py` — all scheduled jobs
   - `services/coach_tasks.py` — task creation logic
   - `services/workout_scanner.py`
   - `services/reassessment.py`
   - `services/dna.py`
   - Keep `server.py` as a thin app assembler + router registration.

2. **Introduce `routers/` properly.** Already scaffolded (`routers/reassessment.py`, `routers/shared.py`) — extend the pattern.

3. **Pydantic response models everywhere.** Currently many endpoints return raw dicts.

4. **Consolidate check-in collections.** One-shot migration script → drop old.

5. **Add a `constants.py`** — collection names, model IDs, quotas. Currently scattered.

6. **Standardize error responses.** Some endpoints return `{"error": "..."}`, others raise `HTTPException`. Pick one.

7. **Frontend `/src/lib/api.ts`** — centralize base URL + auth header injection. Some screens duplicate this.

---

## 19. Go-to-Market Readiness Checklist

- [ ] S3/R2 credentials configured
- [ ] Privacy policy + Terms of Service published
- [ ] Account deletion + data export flows
- [ ] Per-user LLM rate limits + admin dashboard for cost visibility
- [ ] App Store connect account + first TestFlight build
- [ ] Play Store internal test track + first AAB
- [ ] Pricing page in-app (Stripe integration — separate task, not yet started)
- [ ] Landing page (crewfit.com — separate task)
- [ ] Onboarding email sequence (Resend / SendGrid — separate task)
- [ ] Analytics (PostHog / Mixpanel — separate task)
- [ ] Support inbox (email or Intercom)
- [ ] First 20 beta users lined up

---

## 20. Key Decisions Needed From You

1. **Storage:** Cloudflare R2 vs AWS S3 vs Backblaze B2? *Recommendation: R2 (zero egress).*
2. **Pricing model:** flat £9.99/mo? Or £7.99 client / £19.99 coach add-on tier?
3. **Payment provider:** Stripe (recommended) vs Paddle (better for EU VAT).
4. **Launch geography:** UK-first, EU-second, global-third? Affects GDPR urgency + language priorities.
5. **Coach acquisition:** invite-only closed beta or open marketplace?
6. **Buffer:** actually wire it up, or drop it and use a simpler in-app scheduler?
7. **Nutritionix:** worth £$X/mo for richer barcode data, or stay free-tier on Open Food Facts?
8. **Push notifications timing:** ship at launch, or wait for post-launch iteration?

---

## Appendix A — File-by-File Backend Map

| File | Lines | Role |
|---|---|---|
| `server.py` | 6,971 | Main app + auth + workouts + schedule + DNA + cron (needs refactor) |
| `server.py.pre_refactor` | — | Legacy backup, delete once refactor is stable |
| `feature_social_studio.py` | 1,216 | Recording / scripts / subtitles / drafts |
| `feature_habits.py` | 789 | Habits domain |
| `feature_nutrition.py` | 632 | Nutrition dashboard + logging |
| `feature_brand_images.py` | 540 | Nano Banana pipeline |
| `feature_nutrition_insights.py` | 540 | Weekly insights + coach hooks |
| `feature_exercise_content.py` | 514 | Exercise content library |
| `feature_coach_v1.py` | 487 | Coach approvals + alerts + drafts |
| `feature_standby.py` | 466 | Standby mechanics |
| `feature_nutrition_photo.py` | 440 | Claude Vision photo scan |
| `feature_notifications.py` | 425 | Push + in-app |
| `feature_nutrition_travel.py` | 397 | Travel / airport / timing / decision |
| `feature_nutrition_barcode.py` | 391 | Open Food Facts + cache |
| `storage.py` | 287 | S3/R2 abstraction (boto3) |
| `feature_admin_migrations.py` | 208 | One-shot migrations |
| `feature_profile.py` | 204 | Profile photo + location |

## Appendix B — Test Credentials (dev only)

- **Client:** `client@crewfit.com` / `Client123!`
- **Coach/Admin:** `coach@crewfit.com` / `Coach123!`

*Rotate before public launch. Do not commit to public repos.*

---

## Appendix C — What ChatGPT Should Focus On

If you're pasting this into ChatGPT for review, the highest-leverage questions to ask are:

1. "Given the roadmap and risk register, what should I do this week vs. this month?"
2. "How should I price CrewFit given the unit economics above?"
3. "Draft the shortest defensible privacy policy for a UK-launched fitness app."
4. "What's the smallest possible refactor of `server.py` that reduces risk without a rewrite?"
5. "Given a £0.10/client variable cost and £9.99 ARPU, what's the case for adding a free tier?"
6. "What are the top 3 things aviation crew will complain about in my beta, and how do I pre-empt them?"

---

*End of report.*
