# CrewFit — App Store & Beta Readiness (Iter 95a)

> Living checklist for TestFlight private beta and the follow-on
> App Store / Play Store submission. Update as items are completed.

## 1. App metadata (App Store Connect / Play Console)

**Name:** CrewFit — Coaching for Aviation Crew  
**Subtitle (iOS, 30 char max):** Coaching for aviation crew  
**Short description (Play, 80 char max):** Personal coaching for pilots and cabin crew — training that works around your roster.  
**Full description:**

CrewFit is a personal coaching platform built for aviation professionals — pilots, cabin crew and dispatch. Every training plan, meal target and recovery decision is written around your actual roster, hotels and timezone.

What you get
- Coaching from Louis Hall, an ex-crew personal trainer, delivered inside the app.
- Weekly programmes that adapt to your flying pattern: long-haul, short-haul, standby and mixed.
- A safe missed-session recovery flow (never stacks two hard sessions).
- Nutrition targets that follow you across timezones and layovers.
- Habit tracking, weekly check-ins and a Sunday review from Louis.
- Guided workouts with mobility warm-ups, cool-downs and video demonstrations.

CrewFit is a personal wellbeing tool — not a medical device. Speak to your AME before starting a new training programme.

**Keywords (iOS, 100 char max):**  
`pilot,cabin crew,aviation,flying,jet lag,fitness,training,coaching,roster,nutrition`

**Primary category:** Health & Fitness  
**Secondary category (iOS):** Lifestyle  
**Content rating:** 12+ (fitness content, occasional mention of alcohol / caffeine in context)

**Support URL:** https://crewfit.net/support  
**Marketing URL:** https://crewfit.net  
**Privacy Policy URL:** https://crewfit.net/privacy (mirrored in-app at `/legal/privacy`, banner on that screen tapping through to the public URL)
**Terms URL:** https://crewfit.net/terms (mirrored in-app at `/legal/terms`)

> Single source of truth for these URLs is `/app/frontend/src/lib/publicUrls.ts` (frontend) and `app_config` keys `public_privacy_url`, `public_support_url`, `public_terms_url`, `public_website_url`, `whatsapp_support_url` (backend).

**Copyright:** © 2026 CrewFit Ltd.

## 2. Screenshots to produce (6.7" iPhone + 6.9" iPhone required)

**Done (Iter 95c).** Six store-ready screenshots at 1290×2796 (iOS) and 1080×1920 (Play) live at:
- `/app/store_assets/final/`      — iOS 6.7" iPhone (satisfies 6.9" too)
- `/app/store_assets/final_play/` — Google Play phone (9:16)

Full set + regeneration instructions in `/app/store_assets/README.md`.

The set (in order):
1. **`01_home_briefing.png`** — *Coaching that flies with you.* Hero: pilot warming up in hangar. Screen: home dashboard.
2. **`02_guided_workout.png`** — *Never train alone in a hotel again.* Hero: pilot in hotel gym. Screen: guided timer.
3. **`03_calendar.png`** — *Never train on the wrong day.* Hero: crew at airport concourse. Screen: multi-month calendar.
4. **`04_nutrition.png`** — *Fuel across every timezone.* Hero: crew preparing high-protein meal. Screen: nutrition dashboard.
5. **`05_weekly_review.png`** — *A weekly review from Louis.* Hero: pilot + crew reviewing plan. Screen: home w/ weekly review card.
6. **`06_crew_hotel.png`** — *Hotel room. 20 minutes. Done.* Hero: crew doing hotel squats. Screen: workout detail.

## 3. In-app content quality gates

- [x] Privacy Policy live at `/legal/privacy` (verified June 2026).
- [x] Terms of Service live at `/legal/terms`.
- [x] Data Safety summary at `/legal/data-safety`.
- [x] Delete account flow live at `/legal/delete-account` (soft-delete with 30-day purge).
- [x] Data export flow live in Settings.
- [x] Beta disclaimer gate on first launch (`feature_beta_readiness`).
- [x] `NSCameraUsageDescription`, `NSPhotoLibraryUsageDescription`, `NSMicrophoneUsageDescription` present in `app.json`.
- [x] Android `POST_NOTIFICATIONS`, `CAMERA`, `RECORD_AUDIO`, `READ_MEDIA_IMAGES` in `app.json`.
- [x] `ITSAppUsesNonExemptEncryption: false` for smooth review.
- [x] `newArchEnabled: true`.
- [x] `runtimeVersion.policy: appVersion` + `updates` block wired for expo-updates OTA (Iter 95a).

## 4. Compliance

- **Health/medical disclaimer** must appear at signup and inside any workout-generation screen. Copy: "CrewFit is a personal wellbeing tool, not a medical device. Speak to your AME before starting a new programme."
- **Age-gate:** users must confirm they are 16+ (already implemented in signup — `age_confirmed`).
- **AI disclosure (App Store guideline 5.5):** app doesn't advertise AI features to end users — inference is used behind the scenes to draft coaching content that Louis reviews. Privacy Policy already discloses trusted inference processors.
- **No client-facing "AI/generated/bot" copy.** Enforced in Iter 94 review — checked before every release.

## 5. TestFlight private beta

- Distribution: TestFlight external group `CrewFit Private Beta`.
- Max testers this cycle: 50 (crew from LHR + DXB base).
- Feedback channel: `beta@crewfit.net` and in-app "Report an issue" (already wired to `/coach/ui-issues`).
- Kill-switch: `beta_banner_enabled` and every risky feature flag is remotely toggleable via `/coach/admin/live-controls`.

## 6. OTA update workflow (Iter 95a)

- Package: `expo-updates@29.x` installed.
- `app.json` → `runtimeVersion: { policy: "appVersion" }` and `updates.enabled: true`, `checkAutomatically: ON_LOAD`.
- To wire the update URL: run `eas update:configure` once from the CrewFit Expo account, then push OTA fixes with `eas update --branch production`.
- Client behaviour: silent check on cold start in `useOtaUpdates()`. Never interrupts the user; reloads only when an update is fully downloaded.

## 7. Store review pre-flight tests (manual)

Before every submission:

- [ ] `sudo supervisorctl restart backend` — clean logs.
- [ ] Login as `testcal2@crewfit.com` (client) — walk full onboarding.
- [ ] Login as `louis@crewfit.net` (coach) — verify live-controls, tasks, weekly reviews.
- [ ] Delete-account flow (staging user) — grace period, hard purge.
- [ ] Attempt to sign up under 16 — must be blocked.
- [ ] Deny every permission in turn — no dead-ends.
- [ ] Airplane mode — safe empty states, no crashes.
- [ ] Force-quit mid-workout — session state recovers on relaunch.

## 8. Known parked items

Not shipping in this beta:
- Apple Health / Google Fit step sync (parked by user).
- Stripe payments (parked).
- Firebase push notifications (parked; using Emergent-managed push once we're ready).

## 9. Version tracking

| App version | Runtime version | Build | Notes |
|-------------|----------------|-------|-------|
| 1.0.0 | 1.0.0 | 1 (TBD) | Private beta — first submission after Iter 95a. |

