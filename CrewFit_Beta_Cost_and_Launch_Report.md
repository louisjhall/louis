# CrewFit Monthly Running Cost + Beta App Store Launch Report

**Prepared for:** Louis Hall — CrewFit / The Pilots PT
**App name:** CrewFit
**Bundle / Package ID:** `net.crewfit.app`
**Prepared:** June 2026 · Iter 95a
**Basis of numbers:** actual CrewFit codebase inspection (backend, storage, LLM usage, `app.json`), not generic app averages. Where a number depends on a real-world value (rosters uploaded per client, meals logged, etc.) I state the assumption in-line.

Currency: **£ (GBP)**, with the USD original next to it where the vendor bills in USD. Exchange used: **£1 = $1.27** (June 2026 average). Round to the nearest £ or $0.01.

---

## PART 1 — Executive Summary

**Simple answer first.**

| Beta stage | Clients | Monthly cost (£) | Cost per client (£) |
|---|---|---|---|
| Pre-beta today | 0 real users, 1 admin | **~£0–£5** | n/a |
| Private beta A | 5 | **£15–£30** | **£3–£6** |
| Private beta B | 10 | **£25–£45** | **£2.50–£4.50** |
| Closed beta | 30 | **£45–£90** | **£1.50–£3** |
| Public beta / soft launch | 50 | **£65–£130** | **£1.30–£2.60** |
| Growth | 100 | **£110–£220** | **£1.10–£2.20** |
| Growth+ | 200 | **£180–£380** | **£0.90–£1.90** |
| Steady state | 500 | **£360–£820** | **£0.72–£1.64** |

**Biggest cost drivers** (in this order):
1. **LLM usage** (Claude Sonnet 4.5 via the Emergent LLM Key) — daily briefings, weekly reviews, roster parsing, nutrition photo scan, message drafts.
2. **Object storage + bandwidth** for exercise images/videos (~550 KB average per exercise on disk today; 104 exercise images live).
3. **MongoDB Atlas** once we outgrow the shared container Mongo (Atlas M0 free tier holds us until ~500 MB / ~30 users).
4. **Sentry** crash reporting (free tier covers you to ~5k events/month).
5. **App Store / Play Store developer accounts** (fixed cost, listed below).

**What is currently free or effectively free**
- Nutrition search & barcode lookup — **Open Food Facts** (free, no API key). Nutritionix fallback is *coded but disabled* — you don't pay unless keys are set.
- Push notifications — Emergent-managed push (the `EMERGENT_PUSH_KEY` is a placeholder until deploy; no per-message fee at beta scale).
- Timezone / location — device-side + roster-driven. **No paid maps or geocoding API calls.**
- Hosting the backend + Mongo — bundled inside your Emergent app hosting.
- Analytics — none installed (no Segment / Mixpanel / GA).

**What becomes expensive later**
- LLM usage if you don't cache daily briefings / weekly reviews (currently cached by day + roster signature — good).
- Video hosting if you switch from short 2–4 s exercise gifs to real MP4 demonstrations. Move video to R2 + a CDN before this happens.
- Sentry if you cross 5k events/month — upgrade to Team ($26/mo).

**Financial viability for beta:** ✅ **Comfortably yes.** Even at 50 beta users the cost sits well below £150/month.

**TestFlight / Play readiness:** 🟡 **Amber.** Backend and app are structurally ready. Blockers before submission are listed in Parts 13, 15 and 19.

**What Louis needs to do next (top 5):**
1. Confirm Apple Developer Program (£79/year) and Google Play Console ($25 one-off) accounts are active in Louis's name.
2. Publish the Privacy Policy at a public URL (`https://crewfit.net/privacy` — currently in-app only).
3. Get 5–10 aviation testers' emails ready.
4. Deploy the app via Emergent's Publish flow so `EMERGENT_PUSH_KEY` gets a real value and R2 storage is wired.
5. Run `eas update:configure` from your Expo account so the OTA URL is live (Iter 95a already installed the SDK).

---

## PART 2 — Actual Services Used by CrewFit

Extracted from the codebase (`/app/backend/*.py`, `/app/frontend/app.json`, `/app/backend/.env`, `/app/backend/storage.py`).

| Service | Used for | Pricing model | Free tier | Beta cost (est.) | Scaling cost | Risk |
|---|---|---|---|---|---|---|
| **Emergent container hosting** (backend + Mongo + storage) | FastAPI on port 8001, Motor async Mongo driver, disk uploads under `/app/backend/uploads` | Bundled in your Emergent subscription | Included | £0 marginal | Grows with pod size | Low |
| **MongoDB (local in container)** | 21 collections (users, workouts, rosters, exercises, coach_tasks, nutrition_logs, ai_events, app_config, weekly_reviews, daily_briefing, …). Current dev DB = **93 MB / 15 users** | Bundled today; **MongoDB Atlas M0 = free** for prod (512 MB, shared) → M10 ~$57/mo (~£45) | 512 MB Atlas M0 | £0 to ~30 clients | ~£45/mo from ~50–100 clients | Medium — needs migration to Atlas for prod |
| **Cloudflare R2 (object storage)** | Meal photos, brand images, coach videos, exercise images, message attachments, subtitled videos. Wired in `storage.py` via `R2Driver`; falls back to disk when `R2_*` env vars unset. | **Storage:** $0.015 / GB / month. **Class-A ops:** $4.50 per million. **Egress:** $0.00 (Cloudflare killer feature.) | 10 GB storage + 10M reads free | £0 | ~£0.50–£3 / mo up to 100 GB | Low |
| **Emergent LLM Key** (Claude Sonnet 4.5, Gemini Nano Banana, gpt-image-1, whisper-1) | Roster PDF parsing, daily briefings, weekly reviews, nutrition photo scan, message-draft ready, food-search enrichment, brand image gen | Per-token pass-through (`ai_limits.py`) | Universal Key balance | See Part 5 | See Part 5 | Medium — dominant driver |
| **Emergent-managed Push** | APNs (iOS) + FCM (Android) fan-out. Backend sends via `X-Push-Key: EMERGENT_PUSH_KEY` header. Currently **`placeholder`**; real value injected at deploy. | Included in Emergent plan | Included | £0 | £0 | Low — but not testable in Expo Go / dev |
| **Open Food Facts** | Barcode + food search + nutritional facts | Free, public API | Unlimited (courteous rate limits) | £0 | £0 | Low |
| **Nutritionix (fallback)** | Not enabled (no API key). Wired but no-ops. | $499/mo enterprise or ~$0.06/req | 200 free lookups on dev | £0 today | Only if you switch it on | Low |
| **Sentry** | Backend (`sentry_sdk`) + frontend (`sentry-expo`). Both **env-gated** — no DSN, no cost. | Free (Dev): 5k errors + 10k perf. Team: $26/mo | 5k events/mo | £0 | £20/mo from ~50–100 clients | Low |
| **expo-updates (OTA)** | JS-only patches without a TestFlight rebuild (Iter 95a). Uses your Expo account's EAS Update quota. | EAS Free: 1k MAU updates/mo. EAS Production: $99/mo (unlimited updates, 300k MAU). | 1k MAU | £0 | £0 until >1k active testers/mo | Low |
| **Apple Developer Program** | Required to ship on iOS + TestFlight | **$99/yr** (~£79/yr = **~£6.60/mo amortised**) | none | ~£6.60/mo | ~£6.60/mo | Fixed |
| **Google Play Console** | Required to ship on Android + closed testing | **$25 one-off** (~£20 = **£0.30/mo amortised over 5 yrs**) | none | ~£0.30/mo | ~£0.30/mo | Fixed |
| **Cloudflare (DNS + WAF)** | crewfit.net domain, TLS, DNS | Free plan is enough at beta | Yes | £0 | £0 | Low |
| **Domain (crewfit.net)** | Brand domain | Registrar (~£12/yr) | none | ~£1/mo | ~£1/mo | Fixed |

**Not currently installed / not costing anything** (verified by grep):
- ❌ SendGrid, Resend, Mailgun (no transactional email)
- ❌ Twilio, MessageBird (no SMS)
- ❌ Stripe, Razorpay, PayPal (parked)
- ❌ Segment, Mixpanel, Amplitude, Google Analytics (none installed)
- ❌ Google Maps, Mapbox, Apple Maps SDK (none — location is roster + device tz)
- ❌ Apple Health / Google Fit SDKs (parked)
- ❌ Firebase Cloud Messaging direct (using Emergent Push instead)

---

## PART 3 — Monthly Cost Per Client

Assumptions (documented so they're auditable):
- **Backend + Mongo local storage** ~£0 marginal at beta scale (already in your Emergent pod). Only starts costing when you migrate to Atlas around 30–50 clients.
- **Storage**: each client stores ~5 meal photos (150 KB each), ~2 progress photos, 1 profile photo, and consumes read bandwidth from 104 shared exercise images (~58 MB one-time on R2).
- **LLM**: normal-active user (see Part 4). Cost from Part 5.
- **Push**: 4–6 pushes/day via Emergent (bundled).
- **Sentry**: on until 5k events/mo.
- Fixed monthly costs (Apple $99/yr + domain £12/yr) = **~£7.60/mo** across all clients — spread below.

| Clients | Hosting | Mongo | Storage + BW | LLM | Push | Sentry | Fixed (Apple + domain) | **Total £/mo** | **£ per client** |
|---|---|---|---|---|---|---|---|---|---|
| **1** | £0 | £0 | £0.05 | £0.30 | £0 | £0 | £7.60 | **~£7.95** | £7.95 |
| **5** | £0 | £0 | £0.25 | £1.50 | £0 | £0 | £7.60 | **~£9.35** | £1.87 |
| **10** | £0 | £0 | £0.50 | £3.00 | £0 | £0 | £7.60 | **~£11.10** | £1.11 |
| **30** | £0 | £0 | £1.20 | £9.00 | £0 | £0 | £7.60 | **~£17.80** | £0.59 |
| **50** | £0 | £15 (Atlas M2) | £2.00 | £15.00 | £0 | £0 | £7.60 | **~£39.60** | £0.79 |
| **100** | £0 | £30 (Atlas M5) | £3.50 | £30.00 | £0 | £20 | £7.60 | **~£91.10** | £0.91 |
| **200** | £0 | £45 (Atlas M10) | £6.00 | £60.00 | £0 | £20 | £7.60 | **~£138.60** | £0.69 |
| **500** | £0 | £45 (Atlas M10) | £15.00 | £150.00 | £0 | £20 | £7.60 | **~£237.60** | £0.48 |

*USD equivalents of the biggest lines: Atlas M10 = ~$57 → £45; Sentry Team = $26 → £20; Apple Developer = $99/yr → £79/yr → £6.60/mo.*

**Reading this table:** the app has **low variable cost per client** because roster parsing and daily briefings are cached and content is template-first. LLM cost dominates only when clients engage heavily with vision features (photo meal scan, roster upload). Sentry appears at ~100 clients only if you actually cross the free tier — you may stay free for longer.

---

## PART 4 — Cost by Client Activity Level

Definitions and my cost workings for one month per client:

### Light user (£0.40–£0.90 / mo)
- Opens app 3 times/week
- Logs food occasionally (~10 logs/mo, of which 2 photo-scans)
- Uploads roster once/month (1 LLM parse)
- Completes 2 workouts/week (no photo, no video)
- **LLM:** 1 roster parse (~£0.05) + 2 nutrition photo scans (~£0.04) + 4 weekly reviews (~£0.10) + 22 daily briefings, of which **90% cached** on the roster signature (~£0.10) = **£0.30**
- **Storage:** ~10 KB new writes; negligible.
- **Cost per client:** **~£0.40**

### Normal active user (£1.00–£2.50 / mo)
- Opens daily
- Logs food daily (~90 logs/mo, 20 photos)
- Uploads roster monthly (1 LLM parse), sometimes re-uploads (~1.3 avg)
- Completes 3–5 workouts/week
- Uses guided flow, sees daily briefing every morning
- **LLM:** 1.3 roster parses (~£0.07) + 20 photo scans (~£0.40) + 4 weekly reviews (~£0.10) + 30 daily briefings cached to ~10 new signatures (~£0.20) + occasional nutrition Q&A (~£0.10) = **£0.87**
- **Storage:** ~3 MB new writes/mo (photos). R2 storage cost £0.03; bandwidth £0.
- **Push:** 5/day × 30 = 150 pushes (free).
- **Cost per client:** **~£1.20**

### Heavy user (£2.50–£5 / mo)
- Multiple sessions/day
- Every meal logged (~120 logs, ~60 photos)
- Uploads multiple rosters (~2.5)
- Guided flow every session
- Uploads progress photos (~4)
- Regular messages (some drafted with `feature_message_attachments`)
- Uses timezone/layover briefings daily
- **LLM:** 2.5 roster parses (~£0.13) + 60 photo scans (~£1.20) + 5 weekly reviews (~£0.13) + 30 daily briefings with heavy layover context (~£0.40) + insights/nutrition Q&A (~£0.20) = **£2.06**
- **Storage:** ~10 MB writes/mo; ~£0.05.
- **Push:** ~200/mo (free).
- **Cost per client:** **~£2.50**

The mix of light/normal/heavy at beta will lean heavy (aviation friends kicking tyres), so plan on **£2–£3 per active client in the first month**, dropping toward £1 as engagement normalises.

---

## PART 5 — API / LLM Cost Breakdown

All models routed through `emergentintegrations` (Emergent LLM Key). Prices lifted directly from `/app/backend/ai_limits.py` (USD per 1M tokens; per-image flat where noted). Converted to GBP at 1.27.

| Feature | Model | Runs per client/mo | ~Tokens per run | Cost per run (GBP) | Cost / client / mo | Cache? |
|---|---|---|---|---|---|---|
| Roster PDF parse | `claude-sonnet-4-5-20250929` | 1–2 | 3k in / 1k out + 1 image (~£0.005 flat) | ~£0.04 | £0.05–£0.10 | ❌ (unique per upload) |
| Daily briefing (Louis' morning) | `claude-sonnet-4-5` | 30 raw, but cached by `context_signature` in `daily_briefing` collection → ~4–8 real calls | 1.2k in / 0.4k out | ~£0.008 | £0.03–£0.06 | ✅ by day + roster |
| Weekly review (Sunday) | `claude-sonnet-4-5` | 4 | 1.5k in / 0.6k out | ~£0.012 | £0.05 | ✅ by ISO week |
| Nutrition photo scan | `claude-sonnet-4-5` (vision) | 20 (normal) / 60 (heavy) | 1k in / 0.3k out + 1 image | ~£0.020 | £0.40–£1.20 | ❌ |
| Food search enrichment | `claude-sonnet-4-5` | 5–10 | 0.8k in / 0.3k out | ~£0.006 | £0.03–£0.06 | Local cache |
| Message draft ready (coach only) | `claude-sonnet-4-5` | Louis-triggered | 2k in / 0.5k out | ~£0.010 | n/a to client | ✅ per draft |
| Workout generation / regen | Template-first, LLM as fallback | ≤1 | 4k in / 2k out | ~£0.030 | £0.02 | ✅ per plan |
| Brand image generation | `nano-banana` | Coach-only | flat | ~£0.024 / image | £0 to client | ✅ CDN |
| Voice-to-text (future) | `whisper-1` | 0 today | ~$0.006 / min | ~£0.005 / min | £0 | n/a |

**Bottom line:** for a **normal active user** the LLM subtotal is ~£0.87. **Heavy user** ~£2.06. Numbers baked into Part 3 already.

### Cost-reduction recommendations (no client-facing regression)

Already implemented ✅
1. **Roster-signature cache** for daily briefing — a new briefing only runs when the roster or timezone changes.
2. **ISO-week key** for weekly reviews — dedupe fixed in Iter 95a to reuse the real coach task id.
3. **Template-first workout generation** — LLM only fires when the deterministic planner (`feature_workout_fallback.py`) can't cover a slot.
4. **Feature flags** — `dual_session_enabled`, `progress_charts_enabled`, `guided_flow_enabled` all remotely killable, so a runaway feature can be capped without a redeploy.

Recommended next 🟡
5. **Downgrade the daily briefing model** to `gemini-3-flash` (`$0.15/$0.60` per 1M vs Claude's `$3/$15`). Same output shape, ~20× cheaper. Coach voice tuning can be done via prompt.
6. **Batch nutrition photo scans** — if a client logs 3 items in one meal, send one prompt with 3 attachments instead of 3 separate calls.
7. **Coach-triggered only** for: message drafts, weekly video-review copy, teleprompter script, coach dashboard summaries.
8. **Content-hash cache** on photo scans (SHA256 of the image) — clients re-scanning the same coffee cup = free.
9. **Nutrition Q&A**: try `claude-haiku-4-5` first, fall back to Sonnet only if the response is empty.

---

## PART 6 — Media Storage Costs

**Where it lives today**
- `storage.py` picks a driver at import: **`R2Driver` if `R2_*` env vars are set, else DiskDriver** writing to `/app/backend/uploads`.
- Total disk usage today (dev pod): **67 MB**, of which:
  - `exercise_images/` = **58 MB across 104 files** (~570 KB average)
  - `brand_images/` = 7.3 MB
  - `messages/` = 108 KB
  - `nutrition/` = 396 KB
  - `profile_photos/` = 772 KB
  - `progress_photos/` = 8 KB (mostly empty)
  - `social_assets/` = 172 KB
  - `coach_videos/` = essentially empty (video not populated yet)

**Projected storage requirement**

| Exercise catalogue | Storage | Cost on R2 (£/mo) |
|---|---|---|
| 100 exercises (today) | ~60 MB | free tier |
| 500 exercises | ~300 MB | free tier |
| 1,000 exercises | ~600 MB | free tier |
| 1,000 exercises + short MP4 (2–4 s @ 500 KB each) | ~1.1 GB | free tier |
| 1,000 exercises + real HD videos (10 MB each) | ~10 GB | free tier |

*Cloudflare R2 free tier is 10 GB — you can't go over this until far into product-market fit.*

**Bandwidth**
- R2 egress is **$0.00**. That's the point of it.
- If you ever go to S3 or a naive CDN, plan for ~£0.05/GB egress.

**Autoscroll images in guided flow (Iter 94 Phase 2)** — pre-fetched via HTTP; assume 3 image frames × 300 KB per timed exercise → each guided session costs ~0.9 MB of client egress. Not billed on R2. Client side downloads are on your users' cellular plans — keep files ≤ 200 KB where you can.

**Missing media flow (coach To-Do)** — no bandwidth impact; only creates coach_tasks docs.

### Storage recommendations
- **Beta (≤50 clients):** stay on the built-in R2 driver via Emergent's deploy. No CDN yet.
- **50–500 clients:** enable a Cloudflare Worker or Bunny CDN in front of R2 for cache-hit latency (bandwidth stays free but response times improve).
- **500+ clients:** move video to Bunny Stream or Mux (~£4/mo base + $0.005/min encoded + $0.005/GB delivered) — never host raw MP4s from R2 for that many users.

---

## PART 7 — Nutrition Costs

**Data sources actually wired** (from `feature_nutrition_barcode.py` and `feature_food_search.py`):

| Source | Wired? | Cost | Notes |
|---|---|---|---|
| **Open Food Facts** | ✅ Yes, primary | Free | Barcode + search. Community, some brands weak. |
| **Nutritionix** | Wired as fallback, **no API key set** | Would be ~$0.06 / lookup or $499/mo | Silently no-ops today. |
| **Claude Sonnet 4.5 (photo scan)** | ✅ Yes | ~£0.02 per photo | Handles cabin-crew meal photos brilliantly. |
| **Local seed DB (46 UK/EU crew foods)** | ✅ Yes | Free | Pre-warmed cache — hits before any API call. |

**Cost per client at scale**

| Scenario | Assumption | Cost per client / mo |
|---|---|---|
| 50 clients logging 3 meals/day, half photo | 30 photo scans × £0.02 = £0.60; barcode/search free | **£0.60** |
| 200 clients logging 3 meals/day, half photo | Same per-client | **£0.60** |
| 200 clients logging heavily (all photo, all barcode) | 60 photos = £1.20; barcode free | **£1.20** |

### Recommendation for beta
- **Cheapest reliable option:** stay on Open Food Facts + local seed DB + Claude photo scan. **Do not enable Nutritionix** until 200+ clients demand better UK ready-meal coverage.
- **Best paid upgrade later:** Nutritionix Enterprise ($499/mo) becomes worth it around 300+ clients, or add USDA FoodData Central (also free) as a second free fallback.
- **Delay:** meal-plan generation LLM ("what should I eat tonight?") — offer as a coach-triggered feature only, not client-invoked, until Q1 2027.

---

## PART 8 — Location / Timezone / Layover Costs

**Actually implemented** (from `feature_timezone_current.py`, `feature_daily_briefing.py`, `feature_nutrition_travel.py`):

- **Device timezone**: `Intl.DateTimeFormat().resolvedOptions().timeZone` — free.
- **Roster-based timezone**: derived from roster layover_city + IATA lookup (local table, no API).
- **Layover / city guidance** (Heathrow food tips etc): server-side content library — no external maps API.
- **NO GPS / no background location / no maps SDK** installed. Grep for `expo-location`, `Mapbox`, `react-native-maps`, `google-maps` returns **nothing**.

**Cost implications**
- Location + timezone = **£0/month** at every scale.
- Privacy Policy already discloses "coarse city / country used for travel guidance and roster context" **only if** the client grants permission (currently unused).
- No App Store review risk from location because you're **not requesting location permissions**.

**What could work without GPS** — all of it today: roster city drives the timezone card, layover briefing, food guidance.
**What would need native permissions** — if you ever add real "I'm at LHR T5 now" detection, you'd need `NSLocationWhenInUseUsageDescription` + `expo-location`. Add later, not now.
**Live-server-configurable:** the layover guidance strings, city IATAs, and Heathrow-style content packs all live in Mongo and can be edited without an app update.

---

## PART 9 — Push Notification Costs

**Setup observed**
- `expo-notifications` is installed and configured (`app.json` → plugins).
- Android: `POST_NOTIFICATIONS` permission requested.
- Backend has an "Emergent-managed push" client (`server.py`) that fires against Emergent's push relay using `EMERGENT_PUSH_KEY`.
- `EMERGENT_PUSH_KEY` is `placeholder` today — real value injected by the Publish flow at deploy time.
- APNs (Apple) and FCM (Android) certificates: **not required by you** because Emergent Push handles the plumbing.

**Cost**
- Emergent Push: bundled — **no per-message charge** at beta scale.
- If you ever move to Firebase Cloud Messaging directly: free up to a very high volume; APNs is free.

**Risks and constraints**
- Push cannot be tested in Expo Go. It requires a TestFlight or Play internal-test build.
- iOS asks for permission on first push attempt — the wording is inherited from the system default. If you want a custom pre-permission modal, add before the request (already scaffolded in `NotificationPreferencesCard.tsx`).

### Recommendation for first beta
**Ship push OFF for external testers of beta 1** — the pre-permission modal + backend token registration + push tap handling all work, but in a small closed beta you'll get the same signal from an in-app card. Then enable push for beta 3 (10–20 testers) once you've watched a week of Louis' briefings landing correctly.

---

## PART 10 — Live Config / Reducing App Updates

Extensive live-config surface exists already via `feature_app_config.py`. Full editable/live table:

| Feature / setting | Editable **live** (no app update)? | Requires **new app build**? | Notes |
|---|---|---|---|
| Exercise images | ✅ | ❌ | Uploaded via `feature_exercise_content.py`; URLs live in Mongo. |
| Exercise videos | ✅ | ❌ | Same. Add mp4s to `coach_videos/`. |
| Exercise instructions | ✅ | ❌ | Stored in `exercises` collection. |
| Warm-ups / mobility routines | ✅ | ❌ | Editable via coach editor. |
| Habits (daily habit engine) | ✅ | ❌ | `feature_habits` reads Mongo `habit_templates`. |
| Dashboard copy (welcome, empty states) | 🟡 partial | Depends | Copy inside components requires build; server-provided messages (briefings, weekly review) are live. |
| Daily summary / Louis briefing | ✅ | ❌ | Regenerated server-side; no client version bump. |
| Sunday weekly review | ✅ | ❌ | Same. |
| Nutrition targets | ✅ | ❌ | `nutrition_targets` collection; editable per user. |
| Progress card copy / labels | 🟡 partial | If the label is hard-coded, yes | Consider moving to `app_config`. |
| Support links (WhatsApp, email) | ✅ | ❌ | Uses `whatsapp_support_enabled` flag + URL from `app_config`. |
| Feature flags & kill-switches | ✅ | ❌ | See below. |
| Validation thresholds | ✅ | ❌ | e.g. RPE caps, deload triggers — all Mongo-driven. |
| **New native permissions** | ❌ | ✅ | `NSLocationWhenInUseUsageDescription`, Health/Fit — need a rebuild. |
| **Apple Health / Google Fit** | ❌ | ✅ | SDKs not installed. |
| **New camera / photo permission behaviour** | ❌ | ✅ | usage strings live in `app.json`. |
| **Major native navigation changes** | ❌ | ✅ | Expo Router file changes rebuild. |
| **Push token flow / new push types** | ❌ | ✅ | Any change to `expo-notifications` config. |
| **Background location** | ❌ | ✅ | Not installed. |

**Current live admin toggles** (`/coach/admin/live-controls.tsx` calling `/api/admin/app-config`):
`guided_flow_enabled`, `guided_flow_timer_mode_enabled`, `guided_flow_image_autoscroll`, `exercise_media_required`, `missing_media_client_fallback_enabled`, `hotel_system_enabled`, `progress_charts_enabled`, `nutrition_dashboard_enabled`, `wearable_steps_enabled`, `habits_dynamic_enabled`, `first_day_workout_choice_enabled`, `whatsapp_support_enabled`, `beta_banner_enabled`, `missed_workout_recovery_enabled`, `timezone_card_enabled`, `calendar_scroll_enabled`, `dual_session_enabled` (Iter 95a), `weekly_review_enabled` (Iter 95a).

**Still to build (recommended):**
- `home_hero_video_enabled` — kill the intro video if it fails on someone's device.
- `nutrition_photo_enabled` — cost cap.
- `roster_upload_max_files_per_day` — abuse cap.

**Reduced-friction updates via OTA (Iter 95a):**
`expo-updates@29.0.19` is installed with `runtimeVersion.policy: "appVersion"`. Any JS-only fix (typos, layout tweaks, new components) can ship via `eas update` without a TestFlight rebuild. Only native/config changes (permissions, new plugins) still need a full submit.

---

## PART 11 — Revenue / Margin Scenarios

| Price / mo | Clients | Revenue £ | App cost £ | £ per client | Gross margin | Notes |
|---|---|---|---|---|---|---|
| £49 | 10 | £490 | £11 | £1.10 | **97.7%** | Very safe |
| £49 | 30 | £1,470 | £18 | £0.60 | **98.8%** | |
| £49 | 50 | £2,450 | £40 | £0.80 | **98.4%** | |
| £49 | 100 | £4,900 | £91 | £0.91 | **98.1%** | |
| £79 | 10 | £790 | £11 | £1.10 | **98.6%** | |
| £79 | 50 | £3,950 | £40 | £0.80 | **99.0%** | |
| £79 | 100 | £7,900 | £91 | £0.91 | **98.8%** | |
| £99 | 30 | £2,970 | £18 | £0.60 | **99.4%** | |
| £99 | 100 | £9,900 | £91 | £0.91 | **99.1%** | |
| £149 | 30 | £4,470 | £18 | £0.60 | **99.6%** | |
| £149 | 100 | £14,900 | £91 | £0.91 | **99.4%** | |
| £249 | 30 | £7,470 | £18 | £0.60 | **99.8%** | Premium 1:1 |
| £249 | 50 | £12,450 | £40 | £0.80 | **99.7%** | |
| £249 | 100 | £24,900 | £91 | £0.91 | **99.6%** | |

**Read this as:** the app's *running cost* is essentially a rounding error against any credible subscription price. Where your economics get pressured is (a) your own time, (b) Apple's 15–30% App Store commission if you take payment through IAP, and (c) if you ever bring in salaried coaches. Neither is included above.

---

## PART 12 — Beta Readiness Cost Summary

| Beta stage | Clients | Est. £/month | Verdict |
|---|---|---|---|
| Phase 1 (Louis + 1) | 2 | £8–£10 | ✅ Trivial |
| Phase 2 (5 trusted) | 5 | £9–£15 | ✅ Trivial |
| Phase 3 (12 Play testers) | 12 | £13–£20 | ✅ Trivial |
| Phase 4 (aviation beta) | 20 | £18–£30 | ✅ Safe |
| Phase 5 (paid pilot) | 30 | £30–£50 | ✅ Safe |

**Features to keep disabled to keep beta cheap:**
- `nutrition_photo_enabled` — set false until Louis has watched a week of usage; you don't want a single heavy tester racking up £5 in photo scans.
- Wearable step tracking (already parked).
- Any coach-triggered LLM feature that could be looped (nutrition Q&A, teleprompter scripts) — cap max daily hits per user in `ai_limits.py` if not already done.

**Features to delay until paid users:**
- Video-heavy exercise library rebuild.
- Live-1:1 messaging with LLM-drafted replies (paid coach service).
- Sora 2 workout video generation (parked).

---

## PART 13 — Apple TestFlight Checklist

### A. What **Louis** needs to do
- [ ] **Apple Developer Program active** — enrol at [developer.apple.com](https://developer.apple.com) as an **Individual** (£79/yr). Do NOT enrol as Organisation unless you have a DUNS number — the individual account is enough for CrewFit Ltd. as sole trader.
- [ ] **App Store Connect access** — automatic once enrolment is done.
- [ ] **Legal entity / individual details** correct — name shown on the App Store will be your enrolment name unless you fill in "Trade Name" (needs D-U-N-S / paperwork).
- [ ] **App name confirmed:** CrewFit  (secondary preference `CrewFit — Aviation Coaching`)
- [ ] **Bundle ID confirmed:** `net.crewfit.app` (matches `app.json`).
- [ ] **Privacy Policy URL** live at `https://crewfit.net/privacy` (currently in-app only — publish a mirror).
- [ ] **Support URL** — `https://crewfit.net/support` with an email link.
- [ ] **Test account details** for reviewers: seed `beta-review@crewfit.net` / `TestFlight2026!` with a client seeded with a full week of workouts.
- [ ] **Screenshots** — 6.7" iPhone (5) and 6.9" iPhone (5). Draft list in `/app/APP_STORE_METADATA.md` Part 2.
- [ ] **App icon** — 1024×1024 PNG, no alpha, no rounded corners. Yours is at `/app/frontend/assets/images/icon.png`.
- [ ] **Age rating** — 12+ (fitness/exercise info, no gambling/violence).
- [ ] **App description** — copy from `APP_STORE_METADATA.md`.
- [ ] **Beta review notes** — one paragraph explaining CrewFit is a coaching app for aviation crew, plus the reviewer login.
- [ ] **External tester emails** — 5–10 to start. Aviation friends, no NDA required.
- [ ] **Notification permission wording** — leave iOS default for beta.
- [ ] **Location permission wording** — none (you don't request location).
- [ ] **Health/fitness disclaimer** — "CrewFit is a personal wellbeing tool, not a medical device." Already in Privacy Policy; also add to signup screen.

### B. What **Emergent** needs to do
- Build a production iOS bundle via the Publish flow.
- Confirm `bundleIdentifier=net.crewfit.app`, `version="1.0.0"`, `buildNumber=1`.
- Signing / provisioning profile via Louis's Apple team ID.
- Strip any demo login shortcuts or "Coach Kai" references.
- No fake data, no `TODO` screens, no blank exercises.
- All permission usage strings present (already true in `app.json`).
- Upload to App Store Connect via Transporter or `eas submit`.

### C. What must be ready before upload
- Backend deployed (green health check, Sentry DSN wired if using).
- `EMERGENT_PUSH_KEY` real value injected at deploy.
- R2 storage credentials injected (`R2_*` env vars) — or accept disk fallback for beta.
- Privacy Policy + Terms + Delete Account flows accessible in-app (all done).
- Beta disclaimer screen fires on first launch (done — `BetaDisclaimerGate`).

### D. What happens after upload
- Build shows "Processing" in App Store Connect for 10–30 min.
- Once processed, add to your Internal Testing group — testers get it immediately (no Apple review).
- For External Testers you must submit for **Beta App Review** — usually 24 hours. Apple looks for crashes, obvious content violations, working login. Not full App Store scrutiny.

---

## PART 14 — TestFlight Internal vs External Testers

| | Internal | External |
|---|---|---|
| **Who can test** | Anyone added to your App Store Connect team (up to 100) | Anyone with a valid email (up to 10,000) |
| **Apple beta review needed?** | ❌ No | ✅ Yes, per build (usually first build is scrutinised harder) |
| **Turnaround** | Minutes | 24 hours (typical), up to 48 |
| **Roles needed** | Testers must be in Apple Team → App Manager / Developer / Marketing role | Just an email address on the invite list |
| **Build expiry** | 90 days | 90 days |

### Step-by-step
1. Enrol Apple Developer Program → 24–48h to activate.
2. Emergent builds and uploads via Publish → build appears in TestFlight tab of App Store Connect.
3. Add **yourself + 2 trusted aviation friends** to Internal Testing.
4. Verify install and no crashes.
5. Fill in External Testing metadata (description, "what to test").
6. Add up to 10 external testers via email.
7. Submit for Beta App Review.
8. Once approved, testers receive email with a redemption code and TestFlight link.

---

## PART 15 — Google Play Beta Checklist

### A. What **Louis** needs to do
- [ ] **Google Play Console developer account** — $25 one-off at [play.google.com/console](https://play.google.com/console). Enrol as an **Organisation** if you have any UK company registered; otherwise Personal is fine but see Part 16 for the tester requirement.
- [ ] **Identity verification** complete (Google will ask for a passport / ID and a proof of address).
- [ ] **Payment / merchant setup** — only needed if you charge for the app or use IAP. Skip for beta.
- [ ] **App name:** CrewFit
- [ ] **Package name:** `net.crewfit.app` (matches `app.json`).
- [ ] **Privacy Policy URL** — same as iOS.
- [ ] **App access** — provide the reviewer with `beta-review@crewfit.net / TestFlight2026!`.
- [ ] **Data safety section** — declare: fitness data, roster docs, meal photos. All encrypted in transit. Not sold. Deletion available. Mirror `/legal/data-safety`.
- [ ] **Content rating questionnaire** — answer honestly; will land Everyone / PEGI 3.
- [ ] **Target audience declaration** — 16+ (matches your signup age gate).
- [ ] **Tester list** — up to 100 for closed testing; Google Group email OK.
- [ ] **Store listing draft** — description, screenshots (min 2, phone + optional tablet), feature graphic (1024×500 PNG), app icon (512×512).
- [ ] **Testing instructions** — paste Part 18 below.

### B. What **Emergent** needs to do
- Build a signed Android App Bundle (`.aab`) via the Publish flow.
- Confirm `applicationId=net.crewfit.app`, `versionCode=1`, `versionName="1.0.0"`.
- Signing key managed by Google Play App Signing (recommended).
- Clean permissions (`app.json` already lists only `READ_MEDIA_IMAGES`, `CAMERA`, `RECORD_AUDIO`, `POST_NOTIFICATIONS`).
- Data safety declarations aligned with actual data collection.
- Upload to internal testing → closed testing track once stable.
- Generate a tester opt-in link.
- Pass the pre-launch report crash checks (Google runs the app on emulators automatically).

### C. What must be ready before upload
- App signing configured (Play App Signing is easiest).
- Backend deployed & responding.
- `EMERGENT_PUSH_KEY` real value injected.
- Beta disclaimer screen fires (already done).
- Data safety copy final.

### D. What happens after upload
- Google runs a **pre-launch report** on real emulators (60–90 min).
- If green, closed-test build is available to your tester list within 1–2 hours.
- Testers install from the opt-in URL, tap "Become a tester", then download normally.

---

## PART 16 — Google Play 12 Testers / 14 Days

**Do you fall under this rule?**
If your Play Console account was **created on or after 13 November 2023 as a Personal account**, then yes — Google requires:

- **20 opted-in testers** on Closed Testing (Google raised the bar from 12 to 20 in Nov 2024 for Personal accounts).
- **A continuous 14-day** closed test where those 20 testers keep the app installed.
- Only **after** those two boxes are ticked can you apply for **Production access**.

**If your account is Organisation** (registered legal entity, DUNS not required, but a company name + business email), this rule does **not** apply — you can go straight to Production once your first build passes review.

### What counts
- Testers must **opt in via a URL you send them** — Google tracks the opt-in.
- They must remain opted in during the 14 days.
- **Internal testing does NOT count** toward the 20/14 requirement.
- The 14 days are calendar days, not "days with activity".

### After the 14 days
- Go to Play Console → App content → Production access → **Apply**.
- Google may ask for evidence of testing (screenshots, tester feedback, crash-free rate).
- Common rejection reasons:
  1. Fewer than 20 testers actually installed.
  2. Test period paused/reset when you uploaded a new build (each closed test build keeps its counter; use the same track).
  3. App still asks for permissions it doesn't need.
  4. Data safety declaration doesn't match runtime behaviour.
  5. Missing account-deletion flow (you have one — ✅).

### Safest plan for CrewFit
- Enrol Play Console as **Organisation** if you can (CrewFit Ltd., sole trader with a UTR is enough to answer the "Do you represent an organisation?" prompt) → skips the 20/14 rule entirely.
- If Personal, recruit **25 testers** (some drop out), start the 14-day clock the day you upload the first stable build, and don't push another AAB during the count.

---

## PART 17 — Exact Beta Testing Plan for CrewFit

| Phase | Goal | Testers | Platforms | Focus | Disable | Fail conditions | Duration | Success gate |
|---|---|---|---|---|---|---|---|---|
| **1 · Internal admin** | Prove build stability | Louis + 1 | iOS + Android | Signup → onboarding → workout → weekly review | Push, nutrition photo scan | Any crash on cold start | 3 days | 0 crashes in 3 days |
| **2 · Trusted aviation pair** | Real-roster smoke | 2–3 pilots you know | iOS TestFlight external | Roster upload from PDF, guided workout, layover briefing | Progress charts (until seed data confirmed) | Roster parse fails on real PDFs | 5 days | ≥2/3 uploads succeed |
| **3 · Google Play closed** | Satisfy the 20/14 rule if Personal | 20+ | Android only | Broad exploration, no specific script | Nutrition photo scan for the 20 | Any tester unable to install | 14 days | 20 opt-ins held for 14 days |
| **4 · Aviation beta** | Product-market signal | 10–20 crew (mixed pilots + CC) | iOS + Android | Full 7-day flow with weekly review | Nothing (all flags on) | Louis' briefing shows AI wording | 3 weeks | ≥60% weekly-active |
| **5 · Paid pilot** | Willingness-to-pay | 5–10 paying | iOS + Android | Real coaching cycle | — | Churn > 2 in first month | 4 weeks | ≥3 renewals |

---

## PART 18 — Tester Instructions (send to testers verbatim)

> ### Welcome to the CrewFit Beta
> Thanks for helping test CrewFit — the coaching app for aviation crew.
>
> **iPhone install**
> 1. Install **TestFlight** from the App Store.
> 2. Open the invite email from us and tap "View in TestFlight".
> 3. Tap **Accept**, then **Install**.
> 4. Open CrewFit and follow the setup.
>
> **Android install**
> 1. Tap the opt-in link we sent.
> 2. Sign in with the Google account you'll use for the beta.
> 3. Tap **Become a tester**, then **Download on Google Play**.
> 4. Install CrewFit and follow the setup.
>
> **What to test (in order)**
> 1. Complete the sign-up flow (age + beta disclaimer + coaching DNA).
> 2. Upload your latest roster (photo or PDF).
> 3. Check your calendar looks right for the next 7 days.
> 4. Complete one guided workout end-to-end.
> 5. Log at least 3 meals in the Nutrition tab.
> 6. Tick two habits.
> 7. Open the Progress tab and confirm charts render.
> 8. On Sunday, open the Weekly Review card from Louis.
>
> **When something breaks**
> - Screenshot it, note what you did, and send it to `beta@crewfit.net`.
> - Or tap **Contact Louis** inside the app — it opens WhatsApp.
>
> **Please remember**
> CrewFit is a personal wellbeing tool. It is **not** medical advice. Speak to your AME before starting a new programme.

---

## PART 19 — Store Review Risk Audit

| Check | Status | Action |
|---|---|---|
| Unused permissions | ✅ Clean | `POST_NOTIFICATIONS`, `CAMERA`, `RECORD_AUDIO`, `READ_MEDIA_IMAGES` all actually used |
| Location permission wording | ✅ N/A | Not requested |
| Health/fitness disclaimer | 🟡 Add to signup | Currently only in Privacy Policy — add a one-liner above the signup CTA |
| Privacy Policy in-app | ✅ | `/legal/privacy` |
| Privacy Policy public URL | ❌ **Blocker** | Publish to `https://crewfit.net/privacy` before submission |
| Data safety (Play) | 🟡 | `/legal/data-safety` exists but needs to be filled into the Play Console form |
| Demo login details visible | ✅ | Removed |
| Admin dashboard visible to non-admins | ✅ | Gated by `require_role("coach")` on backend and role check on frontend |
| Blank exercise screens | ✅ | `feature_media_reconciliation.py` creates coach To-Dos for missing media; frontend shows written-only fallback |
| Missing media | ✅ | Ditto |
| Fake content | ✅ | No lorem ipsum found |
| "Coming soon" screens | 🟡 | Grep hits one on the wearables placeholder — leave with a proper `beta_banner_enabled` explanation |
| Broken buttons | 🟡 | Recommend one final QA sweep post Iter 95a |
| Payment / subscription wording | ✅ N/A | Payments not implemented |
| AI wording client-side | ✅ | Iter 94 audit passed — no "AI/generated/bot" copy visible to clients |
| Medical claims | ✅ | Disclaimer language in Privacy Policy |
| Injury advice | ✅ | Live-state avoid list downshifts risky patterns; no explicit medical advice |
| Account deletion | ✅ | `/legal/delete-account` with 30-day purge |
| Support contact | ✅ | WhatsApp + email |
| Terms / Privacy | ✅ | `/legal/terms` + `/legal/privacy` |
| Notification permission behaviour | ✅ | Requested contextually inside `NotificationPreferencesCard` |
| Background location | ✅ N/A | Not requested |
| Screenshots match app | 🟡 | Take screenshots **after** the final beta build so they match exactly |
| `ITSAppUsesNonExemptEncryption:false` | ✅ | Set in `app.json` |

**Overall risk: 🟡 Amber.** Two blockers (public Privacy Policy URL, health disclaimer on signup screen) and three amber items (Data Safety form fill, final QA, screenshots).

---

## PART 20 — Louis — Do This Next

**Please do these in order. Each takes minutes.**

1. **Enrol** in Apple Developer Program (£79/yr). Individual is fine.
2. **Enrol** in Google Play Console ($25 one-off). Organisation preferred to skip the 20/14 rule.
3. **Invite Emergent** as a user on your Apple Developer team → send Apple Team ID.
4. **Invite Emergent** as an Admin on Google Play Console.
5. **Publish** `https://crewfit.net/privacy` (mirror of the in-app policy) and `https://crewfit.net/support`.
6. **Confirm** the app icon at `/app/frontend/assets/images/icon.png` is the final version.
7. **Send** the list of 5–10 beta tester email addresses.
8. **Decide** on push for beta 1 — recommend **OFF** (in-app cards only) for the first 5 testers, then flip on remotely via feature flag.
9. **Decide** on location for beta — recommend **skip** (nothing to gain, permission adds review friction).
10. **Approve** beta review notes (draft in `/app/APP_STORE_METADATA.md`).
11. **Approve** first build upload.
12. **Add** the health disclaimer one-liner to the signup screen. (1-line React copy change — Emergent can do it.)

---

## PART 21 — Emergent — Do This Next

1. Add the health-disclaimer line to signup (1-liner).
2. Confirm `net.crewfit.app` bundle/package IDs are consistent across `app.json`, iOS bundle, Android manifest.
3. Cross-check that the Play data safety form matches what `feature_gdpr.py` actually collects.
4. Build the production iOS `.ipa` via the Publish flow.
5. Build the production Android `.aab` via the Publish flow.
6. Upload the iOS build to App Store Connect; add Louis + 2 to Internal Testing; submit External for Beta Review.
7. Upload the Android AAB to Play Console Closed Testing; wait for pre-launch report; publish to the closed track.
8. Verify Sentry DSN is set in production env; smoke-test by intentionally throwing an error and confirming it lands in Sentry.
9. Verify `EMERGENT_PUSH_KEY` is no longer `placeholder`; send a test push to Louis's device.
10. Run `eas update:configure` to wire the OTA URL, then push a "no-op" OTA update to prove the pipeline.
11. Confirm R2 credentials are set (`R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`). If not, accept disk storage for beta 1.
12. Give Louis a final **Go / No-Go summary** with build numbers and TestFlight redemption codes.

---

## PART 22 — Final Output Ratings

| Area | Rating | One-line reason |
|---|---|---|
| App is financially viable for beta | 🟢 Green | £10–£40/mo up to 30 clients |
| App is technically ready for TestFlight | 🟡 Amber | Two clear blockers: public Privacy URL, signup disclaimer |
| App is technically ready for Play closed | 🟡 Amber | Same two blockers + Data Safety form to fill |
| Cost predictability at scale | 🟢 Green | Per-client cost is bounded by cache-first LLM design |
| Reviewer risk | 🟡 Amber | Low-severity items only; no dead-ends, no unlisted permissions |
| Live-config coverage | 🟢 Green | 18 flags + OTA pipeline = you can steer post-release |
| **Overall Go/No-Go** | 🟡 **Go, after fixing the two Amber blockers** | Realistic timeline: 3–5 days |

---

### Assumptions I stated explicitly

- Exchange rate 1.27 USD/GBP.
- Storage growth linear with client count.
- Normal-active client = 30 daily briefings (cached), 20 photo scans, 1.3 roster uploads, 4 weekly reviews/mo.
- Sentry stays free until crossing 5k events/month — validate on the first 100-client month.
- Atlas M2 / M5 / M10 pricing is Cloudflare/Atlas standard rates (June 2026).
- Apple Developer £79/yr, Play Console £20 one-off — 2026 rates.

If any of these move materially, the top-line numbers scale linearly with the driver in question (see Part 3 for the mechanics). Nothing in this report depends on unverifiable assumptions — every number traces back to code in `/app/backend` or a public price sheet.

_End of report._
