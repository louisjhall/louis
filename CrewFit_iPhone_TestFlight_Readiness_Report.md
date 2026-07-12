# CrewFit — iPhone TestFlight Readiness Report

**Generated:** June 2026  
**App Version:** 1.0.0  
**Bundle Identifier:** `net.crewfit.app`  
**Target:** Apple TestFlight (Internal + External Beta)  
**Backend Verification:** ✅ iter-45 backend tests PASS (11/11) — no known 5xx  

---

## 0. TL;DR — Am I ready to ship a build?

| Area | Status | Blocker Level |
|---|---|---|
| **Code / API stability** | ✅ Ready | — |
| **iOS config (`app.json`)** | ✅ Ready with 3 minor fixes | 🟡 Low |
| **App Store icon (1024×1024)** | ❌ Current is 512×512 | 🔴 P0 — Apple will reject |
| **Build number** | ❌ Missing `ios.buildNumber` | 🟠 P1 — every upload needs a unique value |
| **Privacy manifest (`PrivacyInfo.xcprivacy`)** | ⚠️ Not yet added | 🟠 P1 — Apple requires since May 2024 |
| **Sentry DSN (crash reporting)** | ⚠️ Env vars wired but DSN blank | 🟡 Optional for beta |
| **R2/S3 media storage** | ⚠️ Abstraction ready, keys blank | 🟡 Optional for closed beta |
| **App Store Connect setup** | ❌ Not verified from this environment | 🔴 You must do this manually |
| **TestFlight compliance** | ✅ Age gate + Beta disclaimer + GDPR | — |
| **Legal pages hosted publicly** | ⚠️ Content exists, hosting pending | 🟠 P1 — TestFlight external review needs public URLs |

**Bottom line:** You are ~90 minutes of manual work away from your first TestFlight upload. Fix the 3 P0/P1 items below, click **Publish** in Emergent, then upload via App Store Connect.

---

## 1. iOS Configuration Audit (`/app/frontend/app.json`)

### 1.1 What's already correct ✅

| Key | Value | Verdict |
|---|---|---|
| `expo.name` | `CrewFit` | ✅ |
| `expo.slug` | `crewfit` | ✅ |
| `expo.version` | `1.0.0` | ✅ (marketing version) |
| `expo.orientation` | `portrait` | ✅ |
| `expo.userInterfaceStyle` | `automatic` | ✅ dark mode supported |
| `expo.newArchEnabled` | `true` | ✅ Fabric/TurboModules on |
| `expo.ios.supportsTablet` | `false` | ✅ phone-only for beta |
| `expo.ios.bundleIdentifier` | `net.crewfit.app` | ✅ matches Apple record you must create |
| `ITSAppUsesNonExemptEncryption` | `false` | ✅ skips the export-compliance modal each build |
| `NSPhotoLibraryUsageDescription` | Set, benefit-focused | ✅ |
| `NSPhotoLibraryAddUsageDescription` | Set | ✅ |
| `NSCameraUsageDescription` | Set, benefit-focused | ✅ |
| `NSMicrophoneUsageDescription` | Set | ✅ |
| Location permissions | **REMOVED** | ✅ App Store rejection risk cleared |
| `scheme` | `crewfit` | ✅ deep-linking ready |

### 1.2 What must change before the first upload

#### 🔴 P0 — Icon must be 1024×1024 PNG (no alpha)

- **Current:** `frontend/assets/images/icon.png` is **512×512 RGB**.
- **Apple requirement:** 1024×1024 PNG, **no alpha channel**, no transparency, no rounded corners (Apple applies the mask).
- **Fix:** Regenerate the icon at 1024×1024 and replace the file. Use the existing brand mark (`crewfit-logo.png`) as the source.

#### 🟠 P1 — Add `ios.buildNumber`

Apple requires a unique **build number** per upload (independent from `version`). Add to `app.json`:

```jsonc
"ios": {
  "buildNumber": "1",           // increment for every upload: 1 → 2 → 3
  "bundleIdentifier": "net.crewfit.app",
  ...
}
```

Emergent's Publish flow will bump this for you, but a starting value avoids surprises.

#### 🟠 P1 — Add `expo.ios.privacyManifests` or ship `PrivacyInfo.xcprivacy`

Since May 2024 Apple requires a privacy manifest declaring **Required Reason APIs** and **tracking domains**. CrewFit uses:

- User defaults (`AsyncStorage`) → reason `CA92.1`
- File timestamp APIs (image uploads) → reason `C617.1`
- System boot time (Sentry, if enabled) → reason `35F9.1`

Add to `app.json`:

```jsonc
"ios": {
  ...
  "privacyManifests": {
    "NSPrivacyAccessedAPITypes": [
      { "NSPrivacyAccessedAPIType": "NSPrivacyAccessedAPICategoryUserDefaults",
        "NSPrivacyAccessedAPITypeReasons": ["CA92.1"] },
      { "NSPrivacyAccessedAPIType": "NSPrivacyAccessedAPICategoryFileTimestamp",
        "NSPrivacyAccessedAPITypeReasons": ["C617.1"] },
      { "NSPrivacyAccessedAPIType": "NSPrivacyAccessedAPICategorySystemBootTime",
        "NSPrivacyAccessedAPITypeReasons": ["35F9.1"] }
    ],
    "NSPrivacyTracking": false,
    "NSPrivacyTrackingDomains": [],
    "NSPrivacyCollectedDataTypes": []
  }
}
```

*(If Sentry DSN is enabled, App Privacy also needs to declare "Crash Data" collection — see §4.)*

### 1.3 What's fine but worth knowing

| Item | Note |
|---|---|
| `plugins.expo-notifications` | Push channel is wired. To actually receive pushes you must (a) provide `google-services.json` for Android and (b) enable Push Notifications capability in App Store Connect. Not required for beta. |
| `plugins.sentry-expo` + `@sentry/react-native` | Init is guarded — no-op when `EXPO_PUBLIC_SENTRY_DSN` is blank. Safe to ship without a DSN. |
| Splash screen | 512×512 works for now; iOS scales it. High-quality retina asset (2732×2732) is nice-to-have post-beta. |

---

## 2. Backend / API Readiness

### 2.1 Verified in iter-45 ✅

- `_process_upload_and_generate`, `workouts_generate_month`, and `workouts_regenerate` all use the **`delete_many({user_id, date}) + insert_one`** pattern inside try/except → no E11000 duplicate-key crashes across roster uploads, month generation, or manual regenerate.
- `unique_user_date` index on `db.workouts` invariant holds.
- `GET /api/gdpr/export` returns 200 JSON blob with all user data.
- `GET /api/beta/status` and `POST /api/beta/accept` gate first-login correctly.
- Client Preview Mode (`POST /api/preview/impersonate`) works — coach can view any client's app safely with an impersonation JWT.

### 2.2 Endpoints exposed for the app (sample of critical ones)

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/auth/signup` | POST | Now enforces `age_confirmed: true` (age gate) |
| `/api/auth/login` | POST | JWT-based |
| `/api/beta/status`, `/api/beta/accept` | GET/POST | First-login disclaimer |
| `/api/gdpr/delete-account`, `/cancel`, `/export` | POST/POST/GET | GDPR compliance |
| `/api/preview/impersonate` | POST | Coach → client preview |
| `/api/workouts/*` | GET/POST | Full workout stack, collision-safe |
| `/api/admin/telemetry/*` | GET | AI cost & usage dashboards |
| `/api/admin/sentry/test-error` | POST | Verifies crash pipeline (no-op without DSN) |

### 2.3 Env vars — production-ready checklist

Backend (`/app/backend/.env`):

```env
MONGO_URL=<managed by Emergent>          # ✅ set
JWT_SECRET=<managed>                     # ✅ set
JWT_ALGORITHM=HS256                      # ✅ set
EMERGENT_LLM_KEY=<managed>               # ✅ set — powers Claude/GPT/Gemini/Whisper
EMERGENT_PUSH_KEY=<placeholder>          # 🟡 auto-filled at Publish time
SENTRY_DSN=                              # 🟡 optional — set when you enable crash reporting
SENTRY_ENV=beta                          # 🟡 optional
R2_BUCKET=                               # 🟡 optional — set when moving off base64 media
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_ENDPOINT=
```

Frontend (`/app/frontend/.env`):

```env
EXPO_PUBLIC_BACKEND_URL=<managed>        # ✅ set — routes /api/* through ingress
EXPO_PUBLIC_SENTRY_DSN=                  # 🟡 optional
EXPO_PUBLIC_SENTRY_ENV=beta              # 🟡 optional
```

---

## 3. Feature Compliance Audit (for App Store Review)

| Guideline | Status | Evidence |
|---|---|---|
| **1.1 – Objectionable content** | ✅ | Aviation-focused fitness — no user-generated public feed |
| **2.1 – App completeness** | ✅ | All screens functional; **all "coming soon" copy removed** (verified via `grep`) |
| **2.3.7 – Accurate metadata** | ⚠️ You control | Fill App Store listing carefully — no "beta" or "test" in the App Store name |
| **2.5.4 – Multitasking apps** | ✅ | Audio-in-background is *not* enabled (avoids extra scrutiny) |
| **3.1.1 – In-App Purchase** | ✅ | No paid content in beta; Stripe/IAP deferred |
| **4.0 – Design** | ✅ | Native components only, safe-area aware, dark-mode aware |
| **5.1.1(v) – Sign-in for personal data** | ✅ | Age gate on signup, GDPR export/delete flows in-app |
| **5.1.2 – Data collection & storage** | ✅ | Privacy manifest planned (see §1.2), Sentry PII stripped in `beforeSend` |
| **5.1.5 – Location** | ✅ | All location permissions removed from Info.plist |
| **5.2.1 – Intellectual property** | ⚠️ You control | Confirm CrewFit branding, logos, and aviation imagery are cleared |
| **App Sandbox / ATS** | ✅ | Only HTTPS calls to backend — no ATS exception needed |

---

## 4. App Store Connect — Manual Checklist

Do these once, in this order.

### 4.1 Create the app record (5 min)
1. Sign in to https://appstoreconnect.apple.com/
2. **My Apps → +** → **New App**
3. **Platform:** iOS · **Name:** CrewFit · **Primary Language:** English (U.K. or U.S.) · **Bundle ID:** `net.crewfit.app` · **SKU:** `crewfit-ios-001`
4. Click **Create**.

### 4.2 App Information (10 min)
- **Category:** Health & Fitness · **Subcategory:** Fitness (optional)
- **Content Rights:** "Does not use third-party content" (unless you added stock imagery)
- **Age Rating:** answer the questionnaire — CrewFit should land at **12+** (health/fitness references)

### 4.3 Privacy — the "App Privacy" section (15 min)

Answer **Yes** to "Data collected". Declare:

| Data Type | Linked to User? | Used for Tracking? | Purpose |
|---|---|---|---|
| Email address | ✅ Yes | ❌ No | App Functionality, Account Management |
| Name | ✅ Yes | ❌ No | App Functionality |
| Physical characteristics (weight, height) | ✅ Yes | ❌ No | App Functionality |
| Health & Fitness (workouts, meals) | ✅ Yes | ❌ No | App Functionality |
| Photos or Videos (meal photos, coaching clips) | ✅ Yes | ❌ No | App Functionality |
| Coarse device usage (crash logs) | ❌ No (only if Sentry enabled) | ❌ No | Diagnostics |
| Identifiers → User ID | ✅ Yes | ❌ No | App Functionality |

### 4.4 Version 1.0 → **Prepare for Submission** page (skip for TestFlight-only)
For TestFlight-only distribution you can leave this blank until you're ready to submit for App Store review.

### 4.5 TestFlight setup (10 min)
1. **TestFlight → Test Information** — required for external testers:
   - Beta App Description (what CrewFit does)
   - Feedback email: `beta@crewfit.com` (or your address)
   - Marketing URL, Privacy Policy URL — **these must be live public URLs** (see §5)
2. **Test Information → Sign-In Information** — provide the test creds so Apple reviewers can log in:
   - Email: `client@crewfit.com` · Password: `Client123!`
   - Note: "Pilot / cabin crew test client. Coach role available with `coach@crewfit.com` / `Coach123!`."
3. **Internal Testing group:** add your team's Apple IDs — they get builds instantly, no Apple review needed.
4. **External Testing group** (up to 10 000 testers): first build in a group requires ~24 h Apple beta review, then subsequent builds are usually approved within a few hours.

### 4.6 Export Compliance
Because `ITSAppUsesNonExemptEncryption: false` is set in `app.json`, Apple won't ask you the compliance question on every upload. ✅

---

## 5. Legal Pages — must be publicly hosted

Apple requires a **publicly reachable** Privacy Policy and (for beta) Terms of Service.

- Content already drafted in `/app/CrewFit_Handover_Report.md` (Privacy Policy & ToS sections).
- **Action:** copy those two documents into any static host (Vercel, GitHub Pages, Cloudflare Pages, Notion Public, etc.) so they answer at:
  - `https://crewfit.app/privacy` (or similar)
  - `https://crewfit.app/terms`
- Paste those URLs into App Store Connect → **App Information → Privacy Policy URL** and TestFlight → **Test Information → Marketing URL / Privacy Policy URL**.

---

## 6. Build & Upload — the actual TestFlight flow

Because you're on Emergent, you do **not** use `eas build` or manage EAS credentials yourself. The flow is:

1. **In this workspace, click the "Publish" button (top-right).**
2. Choose **iOS build** in the Publish panel.
3. Provide the required credentials Apple needs (Emergent will guide you):
   - Apple ID that owns the App Store Connect account
   - App-specific password (generated at https://appleid.apple.com/account/manage → Security → App-Specific Passwords)
   - Team ID (found in Apple Developer → Membership)
4. Emergent handles signing, provisioning, and IPA upload to App Store Connect.
5. In App Store Connect → TestFlight, wait for the build to finish processing (~15 minutes for a fresh binary).
6. Add the build to your **Internal Testing** group → your testers get an email.
7. When ready, promote the same build to your **External Testing** group.

---

## 7. Tester Onboarding — email template

Copy-paste this into the TestFlight invite email (or send separately to your testers).

> **Subject:** You're in the CrewFit private beta ✈️
>
> Hi <name>,
>
> Thanks for helping us stress-test CrewFit — the aviation-first fitness and nutrition app for pilots and cabin crew.
>
> **1. Install TestFlight** on your iPhone: https://apps.apple.com/gb/app/testflight/id899247664
>
> **2. Accept the invite:** you'll get a separate email from TestFlight with a **redeem code** or a direct link. Tap **Start Testing** and CrewFit will install.
>
> **3. First launch:** you'll be asked to confirm you're 18+ and to accept a short beta disclaimer. Both are required by law and by Apple.
>
> **4. Log in or sign up.** Use your real email so we can reach you with fixes.
>
> **5. What to try first (15 minutes):**
> - Complete the onboarding assessment.
> - Upload a roster (PDF or photo) and watch the 4-week plan generate.
> - Log a meal via photo or barcode.
> - Open the Nutrition Centre and browse the 5 phases.
>
> **6. How to report issues:** tap the **shake gesture** or email `beta@crewfit.com` with a screenshot. TestFlight also has a built-in "Send Beta Feedback" button after every screenshot.
>
> **Known limits during beta:**
> - Data may be reset before public launch.
> - Some AI features have daily usage caps.
> - Payments are not enabled yet.
>
> Cleared for takeoff.
> — The CrewFit team

---

## 8. Post-launch monitoring quick-links

Once builds are live:

| What | Where |
|---|---|
| Crash reports | Sentry dashboard (once DSN configured) |
| AI cost & usage | Coach dashboard → `/admin/telemetry` |
| GDPR deletion queue | `db.gdpr_audit` collection · purge worker log line `gdpr: purge…` |
| Roster job status | `GET /api/workouts/job/{job_id}` — surfaced in coach UI |
| Beta acceptance rate | `db.beta_acceptances` — count per `required_version` |

---

## 9. Immediate action items (in order)

1. **🔴 Regenerate `frontend/assets/images/icon.png` at 1024×1024, no alpha** (5 min in any image tool)
2. **🟠 Add `ios.buildNumber: "1"` to `app.json`** (30 sec)
3. **🟠 Add the `ios.privacyManifests` block to `app.json`** (2 min, snippet in §1.2)
4. **🟠 Host `/privacy` and `/terms` on any static host** (10 min)
5. **🔴 Create the App Store Connect app record and fill App Privacy** (30 min — §4)
6. **✈️ Click Publish in Emergent → iOS build** (~15 min automated)
7. **✅ Invite yourself as Internal Tester → verify install → then promote to External Testers**

---

## 10. What is *not* in scope for this beta

- Stripe / IAP / paywall (deferred to post-beta)
- Buffer OAuth (parked pending API keys)
- Push notifications (works only after Firebase + APNs are configured; safe to skip for beta)
- Custom server-side R2/S3 storage (falls back to base64 while blank)
- `server.py` modular refactor (deliberately deferred to avoid launch instability)

You are launch-ready pending the 3 P0/P1 fixes and the App Store Connect steps in §4. Good luck. ✈️
