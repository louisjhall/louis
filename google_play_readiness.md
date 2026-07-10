# Google Play Readiness Checklist — CrewFit

_Last audited: June 2026 (launch hardening pass)_

This is a live checklist. Tick items as they are completed.

## Store Listing Basics

- [ ] **App name:** CrewFit
- [ ] **Short description** (80 chars): _e.g._ "Aviation-native fitness. Workouts, nutrition and coaching for pilots and crew."
- [ ] **Full description** (up to 4,000 chars) — highlight aviation focus, roster awareness, coach + AI
- [ ] **Category:** Health & Fitness (primary), Lifestyle (secondary)
- [ ] **Content rating:** IARC — answers below (§Content Rating)
- [ ] **Contact email:** support@crewfit.com ✅ (already displayed in Legal > Contact)
- [ ] **Contact phone:** optional
- [ ] **Website URL:** https://crewfit.com (needs to exist)
- [ ] **Privacy policy URL:** https://crewfit.com/legal/privacy (needs to be public and match in-app page)
- [ ] **Account deletion URL:** https://crewfit.com/legal/delete-account (public web landing that explains the in-app flow)

## Package + Signing

- [ ] **Package name:** `com.crewfit.app` (verify in `app.json` under `expo.android.package`)
- [ ] **Application ID matches package name**
- [ ] **Version code + version name** bumped for each release
- [ ] **Signing key:** upload key generated (Emergent Publish handles this)
- [ ] **Bundle format:** Android App Bundle (AAB), not APK
- [ ] **Target SDK:** at least Android 14 (API 34) — required as of Aug 2024

## Permissions

Declared in `/app/frontend/app.json` under `expo.android.permissions`.

- [ ] `CAMERA` — for barcode + meal photo (**provide justification in Play Console**)
- [ ] `READ_MEDIA_IMAGES` — photo picker
- [ ] `RECORD_AUDIO` — social studio recording (coach feature)
- [ ] `POST_NOTIFICATIONS` — push (Android 13+)
- [ ] `INTERNET`, `ACCESS_NETWORK_STATE` — default
- [ ] Optional: `ACCESS_COARSE_LOCATION` — only if in-app permission flow is live

**Rule:** any permission not actively used must be removed — Play rejects apps that request more than they need.

## Screenshots + Graphics

Required sizes:

- [ ] **App icon:** 512×512 PNG (already in `assets/`, verify not clipped)
- [ ] **Feature graphic:** 1024×500 PNG — the big banner at the top of the store listing
- [ ] **Phone screenshots:** min 2, max 8 (1080×1920 recommended). Suggested set:
  1. Home / dashboard with roster awareness visible
  2. Workout player mid-session
  3. Nutrition dashboard with photo scan result
  4. Weekly check-in / progress
  5. Coach dashboard (if pitching to coaches)
- [ ] **7-inch tablet screenshots:** min 2 (1024×600) — optional but recommended
- [ ] **10-inch tablet screenshots:** min 2 (1920×1200) — optional
- [ ] **Promo video:** YouTube URL — optional

## Data Safety Form (Play Console)

Answers to give in the Data Safety form:

| Question | Answer |
|---|---|
| Does your app collect/share user data? | **Yes, collect. No sharing with third parties for their own use.** |
| Is data encrypted in transit? | **Yes** |
| Can users request deletion? | **Yes** — in-app + web |
| Does data collection follow Play Families policy? | N/A (not targeted at kids) |
| **Personal info** (name, email) | Collected, required, optional=no |
| **Health & Fitness** (workouts, weight, nutrition) | Collected, required, optional=no |
| **Photos** (meal photos) | Collected, required=no (opt-in via camera) |
| **Location** (approximate only) | Collected, required=no |
| **App activity** | Not collected as advertising-linked data |
| **Device or other IDs** | Not collected for advertising |

Purposes to declare per data type:
- App functionality ✅
- Account management ✅
- Personalisation ✅ (for AI features)
- Analytics ❌ (not currently used)
- Developer communications ✅ (support emails)
- Advertising or marketing ❌
- Fraud prevention ✅ (security only)

## Content Rating (IARC questionnaire)

Expected outcome: **PEGI 3 / ESRB Everyone**

- Violence: **No**
- Sexuality: **No**
- Language: **No**
- Controlled substances: **No**
- Gambling: **No**
- User-generated content shared publicly: **No** (messages are 1:1 with coach)
- Location sharing: **Approximate only, user-controlled**
- Personal info sharing: **No**
- Digital purchases: **Yes** (subscription, once payment is live)
- Web browsing: **No**
- Unrestricted internet access: **No**

## Test Account

Provide these in Play Console for reviewer:

- **Login:** client@crewfit.com
- **Password:** Client123!
- **Notes for reviewer:**
  > CrewFit is a fitness and wellbeing app for aviation crew (pilots, cabin crew). To evaluate the full experience, sign in with the credentials above. The core features are Home, Workouts, Nutrition (barcode + AI photo scan), and Weekly Check-in. Meal photo scanning uses AI — photos are sent to Anthropic Claude for that single request and not stored on their servers.

## Pre-Launch Report Fixes

Run the Pre-Launch Report in Play Console after your first internal-test upload. Common fixes:

- [ ] No crashes across supported Android versions
- [ ] No ANRs (Application Not Responding)
- [ ] Deep links resolve correctly
- [ ] Accessibility warnings addressed
- [ ] No insecure network usage flags

## Publishing Track

Recommended progression:
1. **Internal test** — up to 100 testers, immediate publish, no review
2. **Closed test** — 100+ testers, 14-day required duration for new personal-account developers
3. **Open test** — optional beta
4. **Production** — full release

## Post-Launch

- [ ] Set up **crash reporting** (Firebase Crashlytics or similar) — not currently wired
- [ ] Monitor **Vitals** in Play Console weekly
- [ ] Respond to reviews within 48h during first month
- [ ] Version bump for every hotfix; use Play Console **staged rollout** (10% → 50% → 100%)

## Blockers Right Now

- 🔴 `com.crewfit.app` package needs to be verified in `app.json` (check current value)
- 🔴 Public `https://crewfit.com/legal/privacy` page must exist and match in-app text
- 🔴 Feature graphic (1024×500) not yet designed
- 🔴 Screenshots not yet captured
- 🔴 First internal-test AAB not yet uploaded
- 🟡 Notification permission flow: confirm Android 13+ POST_NOTIFICATIONS is requested contextually
- 🟡 Payment integration (Stripe/Play Billing) — required only if launching paid tier
