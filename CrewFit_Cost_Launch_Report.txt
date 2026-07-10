# CrewFit — Cost, Launch & Running-Cost Report

**Prepared:** June 2026
**Purpose:** Copy-paste into ChatGPT for pricing/strategic advice.
**Sensitive data:** NONE. No API keys, passwords, tokens, URLs, or client data.
**Basis:** Actual codebase state as of the launch-hardening pass (iteration 42).
**Currencies:** USD and GBP. Assumed rate: £1 = $1.27.

---

## 1. CURRENT BUILD STATUS

### What is currently built (verified in the codebase)

- **Backend:** ~15,565 lines of Python across 16 feature modules + main app
- **Frontend:** 74 screens (Expo Router file-based)
- **Database:** ~50 MongoDB collections, indexed on user_id + date_local
- **Seeded users:** 24 (mix of client + coach test accounts)
- **Exercise library:** 256 unified V2 exercises
- **Real workouts logged:** 179
- **Real rosters uploaded:** 34
- **Real check-ins:** 13
- **Real messages:** 32
- **Real AI photo scans:** 8

### What is actually working (production-quality)

- Auth (JWT + bcrypt)
- Onboarding + assessment engine
- Coaching DNA (living profile, updates over time)
- Workouts (player, sets/reps, PRs, dedupe)
- Schedule / Roster (upload, day overrides, holiday, sickness, standby)
- Habits (tracking, weekly review)
- Weekly check-in (reality events + progress log)
- **Nutrition Centre — all 5 phases:**
  - P1: Dashboard + targets + manual logging + coach visibility
  - P2: Barcode scanner (Open Food Facts, cached)
  - P3: AI photo meal scanner (Claude Sonnet 4.5 Vision)
  - P4: Travel/airport/timezone AI guidance (Atlas)
  - P5: Weekly insights + Sunday check-in integration + coach to-do
- Coach dashboard (clients, approvals, messages, analytics, changelog)
- Content library (unified exercises_v2)
- Video pipeline + subtitles
- Social Studio (recording, drafts, teleprompter, subtitles)
- Brand image generation (Gemini Nano Banana)
- **AI usage quotas + cost telemetry (just shipped)** — 13 features tracked
- **GDPR delete + data export (just shipped)** — 30-day soft-delete
- **Legal pages (just shipped)** — privacy, terms, data-safety, contact, delete-account
- Push notification scaffold (Emergent Push Key, works after native build)

### What is only scaffolded or mocked

| Item | Status |
|---|---|
| **Buffer OAuth** | Backend statuses exist; frontend now honestly labels "SET REMINDER (MANUAL POST) — Buffer coming soon" |
| **Cloud storage (R2/S3)** | Code is 100% wired via `storage.py`; falls back to local disk until env vars are set |
| **Nutritionix / FatSecret** | Backend gated on env vars — dormant, uses Open Food Facts for free |
| **Admin telemetry UI** | Backend endpoints live; no frontend dashboard yet (curl-testable) |
| **Payment integration** | Not started (Stripe/Play Billing) |
| **Analytics** | Zero third-party analytics — deliberate |
| **Crash reporting** | Not integrated (Sentry recommended) |

### What is broken

**Nothing.** Test iteration 42: 18/18 backend + full frontend green. Zero known regressions.

### What still needs testing

- End-to-end journey test (create account → onboard → workout → nutrition → check-in) — currently tested in isolation
- Real-device iOS + Android testing (only web preview + Expo Go tested)
- Load testing (never done)
- Security fuzzing (never done)

### Readiness snapshot

| Question | Answer |
|---|---|
| Ready for internal beta? | **YES** — 10–50 real crew testers today |
| Ready for paid users? | **NO** — no payment integration, no crash reporting, no professionally reviewed legal pages |
| Ready for Google Play? | **NO** — 4 external items pending (public privacy URL, feature graphic, screenshots, first AAB) |
| Ready for App Store? | **NO** — same 4 items + Apple Developer enrolment |

### Percentage complete

| Milestone | % Complete |
|---|---|
| **Lean MVP** (works end-to-end for one aviation user with no coach) | **98%** |
| **Proper V1** (client + coach with all shipped features stable) | **92%** |
| **App Store Ready V1** (stores approved, public web presence, crash reporting) | **75%** |
| **Paid User Ready V1** (payment integration, refunds, receipts, VAT handling) | **60%** |

---

## 2. CURRENT EMERGENT CREDIT POSITION

**Honest limitation:** I do not have live visibility into your Emergent account balance or plan. Below are best-effort estimates based on the volume of work done.

**All numbers below are ESTIMATES — check your actual balance in Profile → Credits.**

### Credits used so far — rough estimate

Based on the scope shipped (14 major feature modules, ~15,500 backend lines, 74 frontend screens, 5 Nutrition phases, storage abstraction, exercise migration, GDPR module, AI limits module, legal pages, 42 test iterations, extensive integrations):

- **Estimated total credits used:** **1,500–2,500** _(guess only — verify in-app)_
- **Credits used in last 7 days:** **~150–300** _(guess based on this session's scope)_
- **Recent major features consuming credits:**
  - Nutrition Phases 1–5: ~400–600
  - Storage abstraction + exercise migration: ~80–120
  - This launch hardening pass (AI limits, telemetry, GDPR, legal): ~200–350
  - Testing agent iterations (42 total): ~100–200
  - Everything else (initial build, workouts, coach dashboard, DNA, etc.): balance

### Emergent plan / subscription

**I cannot see:**
- Your current Emergent subscription tier
- Your monthly Emergent bill
- Your remaining credit balance
- Deployment cost per month

**To find this:** Profile icon (top right) → **Credits** and **Universal Key**.

### What is included in your Emergent bill (general model)

| Line item | Typical model |
|---|---|
| **Platform hosting** | Included in your plan |
| **Deployment** | Publish button generates builds — some plans include, others may charge per build |
| **Mobile builds (iOS/Android AAB/IPA)** | Some plans include, verify in your billing |
| **AI usage via Universal Key (Claude, Gemini, Whisper)** | **Separately metered** on the Universal Key balance — not the main Credits balance |
| **AI credits vs Platform credits** | These are **two separate balances** — check both |

**Verify all of the above by going to Profile → Credits and Profile → Universal Key.**

---

## 3. CREDITS NEEDED TO GET TO V1

Below are per-task credit estimates for the remaining work to go from *today* to live on both stores.

**Assumption:** 1 credit ≈ $0.01 rough equivalent for scale. Your mileage will vary — use ranges.

### A. Critical launch hardening

Most of this is **already done in the last session**. Remaining items:

| Item | Low | Likely | High | Complexity | Risk | Essential? |
|---|---|---|---|---|---|---|
| Storage: paste R2 creds + smoke test | 0 | 5 | 15 | Trivial | Low | ✅ Yes |
| Backfill uploads/ folder to R2 (one-off script) | 20 | 40 | 80 | Medium | Low | ⚠️ Recommended |
| Profile photos → storage abstraction | 15 | 30 | 60 | Medium | Low | ⚠️ Recommended |
| Social studio blobs → storage abstraction | 30 | 60 | 100 | Medium | Low | ❌ Post-launch |
| ~~AI rate limits~~ | ✅ Done | – | – | – | – | – |
| ~~Cost telemetry~~ | ✅ Done | – | – | – | – | – |
| ~~Privacy pages~~ | ✅ Done | – | – | – | – | – |
| ~~Account deletion~~ | ✅ Done | – | – | – | – | – |
| ~~Data export~~ | ✅ Done | – | – | – | – | – |
| ~~Check-in consolidation~~ | ✅ Done | – | – | – | – | – |
| Bug fixing from beta testers | 50 | 150 | 400 | Variable | Medium | ✅ Yes |
| **Section A subtotal** | **85** | **235** | **555** | | | |

### B. App Store readiness

| Item | Low | Likely | High | Complexity | Risk | Essential? |
|---|---|---|---|---|---|---|
| Google Play console setup (guidance + review) | 10 | 20 | 40 | Trivial | Low | ✅ Yes |
| App Store Connect setup (guidance) | 10 | 20 | 40 | Trivial | Low | ✅ Yes |
| Screenshots: capture + resize (5 shots) | 20 | 50 | 100 | Low | Low | ✅ Yes |
| Feature graphic 1024×500 | 10 | 30 | 80 | Low | Low | ✅ Yes |
| Permission descriptions review | 5 | 10 | 20 | Trivial | Low | ✅ Yes |
| Data safety form answers (draft provided) | 5 | 15 | 30 | Low | Low | ✅ Yes |
| Content rating questionnaire | 5 | 10 | 20 | Trivial | Low | ✅ Yes |
| App icon polish / adaptive icon | 10 | 20 | 60 | Low | Low | ⚠️ Recommended |
| Review notes for both stores | 5 | 15 | 30 | Trivial | Low | ✅ Yes |
| Test account setup (already done) | 0 | 5 | 10 | Trivial | Low | ✅ Yes |
| **Section B subtotal** | **80** | **195** | **430** | | | |

### C. Testing & fixes

| Item | Low | Likely | High | Complexity | Risk | Essential? |
|---|---|---|---|---|---|---|
| Internal beta setup + monitoring | 20 | 40 | 80 | Low | Medium | ✅ Yes |
| Android device testing + fixes | 30 | 80 | 200 | Medium | Medium | ✅ Yes |
| iOS device testing + fixes | 30 | 80 | 200 | Medium | Medium | ✅ Yes |
| Coach dashboard regression pass | 15 | 30 | 60 | Low | Low | ✅ Yes |
| Client app regression pass | 15 | 30 | 60 | Low | Low | ✅ Yes |
| Nutrition end-to-end journey test | 15 | 30 | 60 | Low | Low | ✅ Yes |
| Roster edge-case testing | 10 | 25 | 50 | Low | Medium | ⚠️ Recommended |
| Workout player edge-case testing | 10 | 25 | 50 | Low | Low | ⚠️ Recommended |
| **Section C subtotal** | **145** | **340** | **760** | | | |

### D. Optional polish

| Item | Low | Likely | High | Essential? |
|---|---|---|---|---|
| Visual polish (spacing/copy pass) | 30 | 80 | 200 | ❌ No |
| Exercise image regen for missing exercises | 40 | 100 | 250 | ❌ No |
| Brand image quality improvements | 20 | 60 | 150 | ❌ No |
| Message tone/polish pass | 20 | 50 | 120 | ❌ No |
| Notification copy polish | 10 | 25 | 60 | ❌ No |
| Onboarding animations | 30 | 80 | 200 | ❌ No |
| **Section D subtotal** | **150** | **395** | **980** | – |

### Total credits to V1 live

| Path | Low | Likely | High |
|---|---|---|---|
| **Absolute minimum (A+B+C only)** | **310** | **770** | **1,745** |
| **With recommended polish (+D)** | **460** | **1,165** | **2,725** |

**My honest recommendation:** Buy **1,000–1,500 credits** to be safe. If you rush, 500 might just about do it, but you'll run out during beta bug-fixing.

---

## 4. CASH COST TO GET LIVE

### Mandatory cash items

| Item | USD | GBP |
|---|---|---|
| **Apple Developer Program** (annual) | $99 | ~£78 |
| **Google Play Developer** (one-off) | $25 | ~£20 |
| **UK ICO registration** (annual, GDPR mandatory) | – | £40 |
| **crewfit.com domain** (annual) | $13 | ~£10 |
| **Emergent credits top-up** (to cover credits section 3) | $100–$300 | £80–£240 |
| **Total mandatory upfront** | **$237–$437** | **£228–£388** |

### Recommended cash items

| Item | USD | GBP |
|---|---|---|
| Design assets (feature graphic + 5 screenshots) — DIY Canva vs Fiverr | $0–$300 | £0–£240 |
| Legal review of privacy + terms | $0–$500 | £0–£400 |
| App icon polish (if outsourced) | $0–$150 | £0–£120 |
| Landing page hosting (Vercel free tier is fine) | $0 | £0 |
| Email service (Resend free tier is fine) | $0 | £0 |
| **Total recommended upfront** | **$0–$950** | **£0–£760** |

### Optional cash items

| Item | USD | GBP |
|---|---|---|
| Nutritionix API (richer barcode data) | $69/mo starter | £55/mo |
| Sentry (crash reporting) | $0–$26/mo | £0–£21/mo |
| Buffer API (if you wire it up) | Free tier possible | Free–£12/mo |

### Total cash to launch

| Scenario | USD upfront | GBP upfront | USD monthly |
|---|---|---|---|
| **Cheapest** (DIY everything) | **$237** | **£228** | ~$5/mo |
| **Realistic** (some outsourcing) | **$500–$700** | **£400–£560** | ~$15/mo |
| **Cautious** (legal review + pro design) | **$1,000–$1,400** | **£800–£1,150** | ~$25/mo |

---

## 5. MONTHLY RUNNING COSTS

### Assumptions

- **AI cost per active user:** ~$0.06–$0.10 (from unit economics — 2 photo scans + 8 text calls + free barcode lookups)
- **Storage per user:** ~10 MB/month (photos), R2 storage is $0.015/GB
- **Notifications:** Emergent Push Key — included
- **Email:** Not sending transactional email yet — $0

### Per-tier line items

| Line item | 10 users | 25 | 50 | 100 | 250 | 500 | 1,000 |
|---|---|---|---|---|---|---|---|
| **Emergent subscription** | Fixed (your plan) | | | | | | |
| **Emergent hosting/deployment** | Included in plan | | | | | | |
| **MongoDB** (M0 free → M10 at ~500 users) | $0 | $0 | $0 | $0 | $0 | $45 | $57 |
| **R2 storage** | ~$0 | ~$0 | ~$0 | $1 | $2 | $4 | $8 |
| **AI text (Atlas messages, insights, travel, workout gen)** | $1 | $3 | $5 | $10 | $25 | $50 | $100 |
| **AI photo meal scanning** | $0.50 | $1 | $2 | $5 | $12 | $25 | $50 |
| **AI roster parsing** | $0.50 | $1 | $2 | $5 | $10 | $20 | $40 |
| **AI workout generation** | $0.50 | $1 | $2 | $5 | $10 | $20 | $40 |
| **AI check-in summaries** | $0.20 | $0.50 | $1 | $2 | $5 | $10 | $20 |
| **AI message drafting (coach)** | $1 | $2 | $4 | $8 | $20 | $40 | $80 |
| **AI nutrition insights** | $0.30 | $0.80 | $1.50 | $3 | $8 | $15 | $30 |
| **AI exercise/brand images (coach only)** | $1 | $2 | $3 | $5 | $10 | $15 | $25 |
| **Transcription (Whisper, coach only)** | $0.50 | $1 | $2 | $4 | $8 | $15 | $25 |
| **Push notifications** | $0 | $0 | $0 | $0 | $0 | $0 | $0 |
| **Email service** (not yet active) | $0 | $0 | $0 | $0 | $0 | $0–$20 | $20 |
| **Barcode DB (Open Food Facts, free)** | $0 | $0 | $0 | $0 | $0 | $0 | $0 |
| **Buffer** (not wired) | $0 | $0 | $0 | $0 | $0 | $0 | $0 |
| **Analytics (none used)** | $0 | $0 | $0 | $0 | $0 | $0 | $0 |
| **Crash reporting (Sentry free tier)** | $0 | $0 | $0 | $0 | $0 | $0 | $26 |
| **App store fees ($99/yr Apple + $25 one-time Google)** amortised | $8 | $8 | $8 | $8 | $8 | $8 | $8 |
| **Domain (£10/yr)** amortised | $1 | $1 | $1 | $1 | $1 | $1 | $1 |
| | | | | | | | |
| **TOTAL (realistic)** | **~$14** | **~$21** | **~$32** | **~$57** | **~$119** | **~$268** | **~$530** |
| **TOTAL (low)** | ~$8 | ~$14 | ~$22 | ~$38 | ~$80 | ~$180 | ~$360 |
| **TOTAL (high spike)** | ~$25 | ~$40 | ~$60 | ~$110 | ~$225 | ~$500 | ~$1,000 |

### What could make costs spike

1. **Users spamming photo meal scans** (top risk) — now mitigated by AI quotas ✅
2. **Users repeatedly regenerating workouts** — mitigated by AI quotas ✅
3. **Roster upload abuse** — mitigated by AI quotas ✅
4. **Coach going wild on brand image generation** — coach quotas exist but you may want to lower
5. **Video uploads growing past R2 free tier** — monitor; R2 is cheap but not free forever
6. **MongoDB scaling** — M10 at ~500 users; beyond 5,000 users you'll need M20 (~$150/mo)
7. **Model upgrades** — if Claude 5 launches at 2× the price
8. **Emergent LLM Key auto-recharge misconfigured** — set a monthly ceiling

---

## 6. COST PER CLIENT

### A. Light user (workouts only, few AI calls, no photo scanning)

| Line | Cost |
|---|---|
| AI text (maybe 2 Atlas messages/month) | $0.01 |
| Storage | $0.001 |
| DB/hosting share | $0.03 |
| Notification | $0 |
| **Total per month** | **~$0.05** |

### B. Normal user (workouts + habits + check-ins + some messages + occasional nutrition)

| Line | Cost |
|---|---|
| AI text (~10 calls/month) | $0.04 |
| AI photo scans (~1/month) | $0.01 |
| Storage | $0.002 |
| DB/hosting share | $0.05 |
| Notification | $0 |
| **Total per month** | **~$0.10** |

### C. Heavy user (frequent AI messages, meal photos, roster uploads, nutrition, video watching)

| Line | Cost |
|---|---|
| AI text (~30 calls/month) | $0.12 |
| AI photo scans (~15/month, at quota cap of 30) | $0.18 |
| AI roster parsing (~2/month) | $0.02 |
| Video streaming (~200 MB/month via R2, no egress) | $0 |
| Storage | $0.005 |
| DB/hosting share | $0.05 |
| **Total per month** | **~$0.38** |

### D. High-touch coaching user (weekly coach video, frequent messages, programme adjustments, nutrition review, check-in review)

| Line | Cost |
|---|---|
| AI text (client side, ~40 calls/month) | $0.16 |
| AI photo scans (~20/month) | $0.24 |
| Coach-side message drafts (~30/month per client — shared cost with Louis's other clients) | $0.12 |
| Coach-side weekly video (Whisper transcription) | $0.04 |
| Storage (larger video usage) | $0.02 |
| DB/hosting share | $0.05 |
| **Total per month** | **~$0.63** |

### Blended average (30% light, 50% normal, 15% heavy, 5% high-touch)

**Blended cost per client ≈ $0.13–$0.15/month** at scale.

At £49/month subscription (£38.60 after Apple/Google 20% fee, or full £49 direct):
- **Gross margin per client: ~99.7%** on infra alone
- The real cost is **Louis's time** (see Section 11)

---

## 7. AI USAGE AND LIMITS

### Currently shipped ✅ (verified working, iteration 42)

| Feature | Status |
|---|---|
| Per-user AI rate limits | ✅ Yes (`ai_limits.py`) |
| Daily AI limits | ✅ Yes (13 features) |
| Monthly AI limits | ✅ Yes (13 features) |
| Admin cost dashboard (endpoints) | ✅ Yes (7 endpoints) |
| Admin cost dashboard (UI) | ❌ No — needs building (~1 hour) |
| AI usage logging | ✅ Yes (`db.ai_usage`) |
| Feature-level AI cost tracking | ✅ Yes (est_cost_usd per row) |
| Abuse prevention (429 responses) | ✅ Yes |
| Failed AI call tracking | ✅ Yes (`success: false` rows) |
| Outlier detection | ✅ Yes (P90-based) |

**Credits to add remaining piece (admin UI):** 40–80

### Current default limits (already in `ai_limits.py`)

| Feature | Free tier day | Free tier month | Paid tier day |
|---|---|---|---|
| Photo meal scans | 10 | 30 | 100 |
| Atlas messages | 5 | 60 | 50 |
| Roster parsing | 3 | 20 | 10 |
| Workout generation | 5 | 40 | 20 |
| Check-in summaries | 2 | 10 | 5 |
| Nutrition insights | 1 | 6 | 2 |
| Travel guidance | 5 | 30 | 30 |
| Habit reviews | 2 | 10 | 5 |
| Chat with Atlas | 10 | 100 | 100 |
| Image generation (coach only) | 0 | 0 | 20/day |
| Social generation (coach only) | 0 | 0 | 20/day |
| Transcription (coach only) | 0 | 0 | 30/day |

### Recommended limits at each price tier (my honest opinion)

**£49/month "Standard" tier:**
- Roster uploads: **5/month** (aviation rosters change ~monthly)
- Meal photo scans: **30/month** (~1/day)
- AI Atlas messages: **60/month** (~2/day)
- Workout regenerations: **20/month**
- Image gen: **0** (coach-only feature)
- Social gen: **0** (coach-only feature)

**£99/month "Premium" tier:**
- Roster uploads: **10/month**
- Meal photo scans: **90/month** (~3/day)
- AI Atlas messages: **200/month**
- Workout regenerations: **60/month**

**£249/month "High-Touch" tier:**
- Everything unlimited within reason
- Priority coach access
- Weekly personalised video from Louis

---

## 8. STORAGE STATUS AND COST

### Current state (verified)

- Total disk used: **7.4 MB** (yes, only 7 MB across 24 users)
- Container disk available: **7.9 GB free**
- Storage driver: **disk** (S3/R2 not configured)
- Brand images: **stored via storage abstraction** ✅ (writes to disk, ready for R2)
- Exercise images: **stored via storage abstraction** ✅
- Meal photos: **stored via storage abstraction** ✅
- Profile photos: **direct disk write** (not yet via abstraction — minor risk)
- Coach videos: **direct disk write** (not yet via abstraction — 4 KB only so far)
- Social studio blobs: **direct disk write** (172 KB so far)
- Base64 in Mongo: **No** (verified — only `feature_nutrition_photo.py` accepts base64 input; it's decoded and written to storage)

### What happens if many users upload

At current growth rate: nothing. But at 500 users doing 2 photo scans/month × 300 KB each = **300 MB/month growth**. Container disk fills in ~2 years at this rate. **Fine for beta, must fix before 1,000 users.**

### Storage costs

| Users | Total storage | Cloudflare R2 monthly | AWS S3 monthly |
|---|---|---|---|
| 50 | ~500 MB | ~$0.01 | ~$0.02 + egress |
| 100 | ~1 GB | ~$0.02 | ~$0.02 + egress |
| 500 | ~5 GB | ~$0.08 | ~$0.12 + egress |
| 1,000 | ~10 GB | ~$0.15 | ~$0.23 + egress |
| 10,000 | ~100 GB | ~$1.50 | ~$2.30 + egress (up to $50 depending on egress) |

**R2 wins big at scale because there is zero egress fee.**

### Cost to configure R2

- **Signup:** Free
- **Test bucket creation:** Free
- **Access keys:** Free
- **Emergent credits to paste keys and verify:** ~5 credits
- **Backfill script (move existing uploads to R2):** ~40–80 credits
- **Total:** ~45–85 credits, £0 cash

---

## 9. APP STORE READINESS COST

### Google Play — Status

| Item | Status |
|---|---|
| Developer account | ❌ Missing ($25 one-off) |
| Package name (`net.crewfit.app`) | ✅ Set |
| AAB build | ❌ Not generated yet (Emergent Publish button) |
| Internal testing track | ❌ Not created |
| Closed testing (14-day requirement for new personal-account devs) | ❌ Not started |
| Data safety form | ⚠️ Draft answers ready (in google_play_readiness.md) |
| Privacy policy URL | ❌ In-app text ready, needs to be public at crewfit.com |
| Account deletion URL | ❌ Same (needs public landing page) |
| Screenshots | ❌ Not captured |
| Content rating | ⚠️ Draft answers ready (expected PEGI 3) |
| Production application | ❌ Not submitted |

### App Store — Status

| Item | Status |
|---|---|
| Apple Developer account | ❌ Missing ($99/year) |
| Bundle ID (`net.crewfit.app`) | ✅ Set |
| iOS build | ❌ Not generated yet |
| TestFlight beta | ❌ Not set up |
| Privacy nutrition labels | ⚠️ Same info as Play data safety |
| Screenshots (6.7" and 6.5" required) | ❌ Not captured |
| App review notes | ❌ Draft in google_play_readiness.md |
| Permissions wording | ✅ Set (5 iOS descriptions) |
| Production submission | ❌ Not submitted |

### Cost estimates

| Item | Credits | Cash | Time | Rejection risk |
|---|---|---|---|---|
| Google Play submission | 30–60 | $25 | 3–5 days | Low (data safety mismatch is #1 rejection) |
| App Store submission | 30–60 | $99/year | 5–14 days | Medium (Apple is stricter; may bounce for permission wording) |
| Landing page + public policy URL | 30–60 | $0 (Vercel free) | 4 hours | N/A |
| Screenshots + feature graphic | 40–100 | $0 (DIY) to $250 (Fiverr) | 4–8 hours | N/A |
| **Total** | **130–280** | **$124–$374** | **~2 weeks elapsed** | Medium overall |

**Most common rejection reasons for CrewFit specifically:**
1. Health claims not backed up → mitigated by "not medical advice" clause ✅
2. AI content warnings → mitigated by "AI can be wrong" clause ✅
3. Permission descriptions that don't match usage → all 5 iOS descriptions are aviation-specific ✅
4. Privacy policy URL not accessible → **this is your main risk** — must be publicly hosted

---

## 10. LEGAL / PRIVACY / GDPR READINESS

### What exists ✅ (just shipped)

| Item | Status |
|---|---|
| Privacy policy | ✅ In-app at `/legal/privacy` (10 sections, UK/EU GDPR-styled) |
| Terms of service | ✅ In-app at `/legal/terms` (11 sections) |
| Account deletion | ✅ In-app at `/legal/delete-account` (30-day soft-delete + 30-day grace) |
| Data export | ✅ In-app at `/legal/delete-account` (JSON download) |
| Data retention policy | ✅ Documented (30-day grace, then hard-delete) |
| Location data handling | ✅ Opt-in only, coarse city/country |
| Health/fitness data handling | ✅ Covered in privacy policy |
| Nutrition data handling | ✅ Covered |
| Profile photos/media | ✅ Covered |
| Roster files | ✅ Covered (fitness data) |
| AI data processing disclosure | ✅ Covered (Anthropic/Google/OpenAI sub-processors named) |
| Push token handling | ✅ Covered (device tokens for notifications) |
| User consent (opt-in for location) | ✅ Handled in permission flow |
| Data safety summary table | ✅ At `/legal/data-safety` |
| Contact emails | ✅ support@ / privacy@ / security@crewfit.com |
| Admin audit trail for deletions | ✅ `db.gdpr_audit` |

### What is missing

| Item | Blocker? |
|---|---|
| **Public web-hosted privacy policy** (crewfit.com/legal/privacy) | ✅ App Store requires |
| **Public web-hosted account deletion instructions** | ✅ Google Play requires |
| **UK ICO registration** (£40/year) | ⚠️ Legally required for processing UK personal data |
| **Legal review by a UK solicitor** | ❌ Not blocking, but recommended for paid tier |
| **Age verification** (16+ per privacy policy) | ⚠️ Currently none — recommend adding at signup |
| **Cookie/tracker policy** | N/A — you have no cookies or trackers |
| **Right of access response process** (not just download button) | ⚠️ You need to be reachable at privacy@ within 30 days |

### Cost to make launch-safe

| Item | Credits | Cash |
|---|---|---|
| Public policy landing page | 40–80 | $0 |
| Age gate at signup | 20–40 | $0 |
| UK ICO registration | 0 | £40 |
| Legal review (optional) | 0 | £150–£500 |
| **Total** | **60–120** | **£40–£540** |

---

## 11. COACH TIME COST (Louis)

This is the **real cost** you should be worried about, not infrastructure.

### Weekly time per client-count band

| Clients | Check-ins | Messages | AI approvals | Workout approvals | Roster issues | Nutrition | Videos | Admin | **Total /week** |
|---|---|---|---|---|---|---|---|---|---|
| **10** | 1.5h | 1h | 0.5h | 1h | 0.5h | 0.5h | 1h | 0.5h | **6h** |
| **25** | 3h | 2.5h | 1h | 2h | 1h | 1h | 2h | 1h | **13.5h** |
| **50** | 5h | 5h | 2h | 3h | 2h | 2h | 3h | 2h | **24h** |
| **100** | 8h | 10h | 4h | 5h | 4h | 4h | 4h | 3h | **42h** (⚠️ full-time) |
| **250** | Impossible without automation | | | | | | | | **80h+** ❌ |

### What must be automated / capped to keep Louis sane past 50 clients

1. **AI-drafted messages** — coach approves in bulk, never types from scratch
2. **AI-drafted check-in responses** — coach reviews, edits, sends
3. **Weekly video: pre-recorded once, personalised in intro only**
4. **Workout approval → auto-approve after 24h if coach is silent** (already in the codebase)
5. **Roster issues → mostly self-service via AI parsing** (already automated)
6. **Nutrition review → automated weekly insight goes to client; coach only intervenes for red flags** (already in P5)
7. **Bulk operations**: approve all pending messages, send weekly video to all clients at once
8. **Tiered clients**: Standard tier (self-serve) vs High-Touch tier (coach involvement) — pricing must reflect this

### Rough sustainable model

- **50 Standard clients** = ~15h/week of coach time = manageable
- **20 High-Touch clients** = ~15h/week of coach time = manageable
- **Blended (30 Standard + 15 High-Touch)** = ~20h/week = a well-run business

**Anything beyond 50 total clients without hiring a second coach = Louis burns out.**

---

## 12. PRICING AND PROFITABILITY MODEL

### Assumptions
- Blended infra cost per client: **$0.15/month** (~£0.12)
- App Store/Play Store fees: **20% off subscription revenue** (Apple's small business tier) or **0%** if you use Stripe direct via web signup
- Louis's time: **not costed here** (up to you what you value it at)
- Model: **Stripe direct via web signup, iOS/Android just for login** (avoids the 20%)

### Revenue table (monthly gross profit before Louis's time)

| Price | 25 users | 50 users | 100 users | 250 users |
|---|---|---|---|---|
| **£49** rev | £1,225 | £2,450 | £4,900 | £12,250 |
| **£49** infra | £3 | £6 | £12 | £30 |
| **£49** profit | **£1,222** | **£2,444** | **£4,888** | **£12,220** |
| **£49** margin | 99.8% | 99.8% | 99.8% | 99.8% |
| **£49** break-even | ~1 client | | | |
| | | | | |
| **£79** rev | £1,975 | £3,950 | £7,900 | £19,750 |
| **£79** profit | **£1,972** | **£3,944** | **£7,888** | **£19,720** |
| | | | | |
| **£99** rev | £2,475 | £4,950 | £9,900 | £24,750 |
| **£99** profit | **£2,472** | **£4,944** | **£9,888** | **£24,720** |
| | | | | |
| **£149** rev | £3,725 | £7,450 | £14,900 | £37,250 |
| **£149** profit | **£3,722** | **£7,444** | **£14,888** | **£37,220** |
| | | | | |
| **£199** rev | £4,975 | £9,950 | £19,900 | £49,750 |
| **£199** profit | **£4,972** | **£9,944** | **£19,888** | **£49,720** |
| | | | | |
| **£249** rev | £6,225 | £12,450 | £24,900 | £62,250 |
| **£249** profit | **£6,222** | **£12,444** | **£24,888** | **£62,220** |

**Break-even is trivial at every price point.** The real constraint is Louis's time, not infra.

### Recommended tier structure

**Standard — £49/month**
- Self-serve workouts, nutrition, habits
- 30 photo scans/month, 5 roster uploads/month
- Weekly automated Atlas insights
- Community-style automated coaching (no direct Louis time)
- Target: **50–100 users, ~0.15h/user/week from Louis** (bug reports only)

**Premium — £99/month**
- Everything in Standard
- Direct message access to Louis (async, 48h response)
- Monthly 15-min video review
- 90 photo scans/month
- Target: **25–40 users, ~0.5h/user/week from Louis**

**High-Touch — £249/month**
- Everything in Premium
- Weekly 1:1 async video from Louis
- Custom nutrition review
- Roster-specific workout adjustment
- Personal programme design
- Target: **10–20 users, ~1.5h/user/week from Louis**

**Realistic revenue mix (Year 1 target):**
- 40 Standard × £49 = £1,960
- 20 Premium × £99 = £1,980
- 8 High-Touch × £249 = £1,992
- **Total: £5,932 MRR / £71,184 ARR** with ~35h/week Louis time — sustainable one-person business

---

## 13. WHAT SHOULD NOT BE BUILT BEFORE V1

Delay these — they will cost credits, add support burden, and delay launch:

| Feature | Why delay |
|---|---|
| **Full community / social feed** | Moderation is a nightmare. Massive support burden. Adds nothing to core value prop. Wait for 200+ users to see if there's demand. |
| **Wearable integrations (Whoop, Garmin, Apple Watch)** | Each is 2–4 weeks of work. Users can enter data manually. Zero users have asked for this yet. |
| **GPS players (running, cycling, swimming)** | Aviation crew mostly train in hotel gyms, not outdoors. Wrong target for aviation. |
| **Advanced social studio (auto-post to Instagram/TikTok)** | Buffer wiring alone is 40–80 credits. Every social platform changes their API. Endless maintenance. |
| **Advanced nutrition (recipes, meal planning, grocery lists)** | Massive scope. MyFitnessPal already does this. Your USP is aviation-native, not comprehensive. |
| **Corporate/airline B2B dashboard** | Sales cycle is 12+ months. Different product. Ship consumer first. |
| **Advanced analytics dashboards (client-facing)** | Coach dashboard has enough. Client-facing analytics rarely drive retention. |
| **Multi-coach marketplace** | Legal/tax complexity (revenue share, contracts, quality control). Do it after £10k MRR. |
| **Localization (Spanish, French, German)** | 4× the QA cost. Do it after £5k MRR from English speakers. |
| **Dark mode toggle** | Nice-to-have. Zero users have requested. |
| **Coach mobile app (separate)** | Coach dashboard works on mobile web. Don't split apps until Louis begs. |

**Rule of thumb:** if a feature was not in the original 10-task launch brief, don't build it before V1.

---

## 14. BEST NEXT BUILD ORDER (10 tasks)

| # | Task | Why | Credits | Cash | Risk | Launch req? | Affects run cost? | Affects store approval? |
|---|---|---|---|---|---|---|---|---|
| **1** | Paste R2/S3 credentials + smoke test | Activates cloud storage; single biggest infra risk closed | 5–15 | $0 | Low | ✅ Yes | ✅ Yes | ⚠️ Indirect (avoids disk-full crashes during review) |
| **2** | Register domain + host public privacy URL on Vercel | Google Play + App Store require public policy URL | 40–80 | $10/yr | Low | ✅ Yes | ❌ No | ✅ Yes |
| **3** | Enrol Apple Developer + Google Play accounts | Cannot ship without them | 10–20 | $99+$25 | Low | ✅ Yes | ❌ No | ✅ Yes |
| **4** | Capture screenshots (5) + design feature graphic in Canva | Cannot submit without them | 40–100 | $0 DIY | Low | ✅ Yes | ❌ No | ✅ Yes |
| **5** | UK ICO registration | Legally required to process UK personal data | 0 | £40 | Low | ⚠️ Legal | ❌ No | ❌ No |
| **6** | Emergent Publish → first internal-test AAB + IPA | Cannot beta without a build | 30–60 | $0 | Medium | ✅ Yes | ❌ No | ✅ Yes |
| **7** | 5-user internal beta (invite crew friends via TestFlight/Play internal) | Real-device bug-catching before submitting | 100–300 | $0 | Medium | ✅ Yes | ❌ No | ✅ Yes |
| **8** | Fix any beta bugs + polish | Whatever comes back from #7 | 100–300 | $0 | Variable | ✅ Yes | ❌ No | ✅ Yes |
| **9** | Submit to Google Play internal test track | First store submission (easier than Apple) | 20–40 | $0 | Low | ✅ Yes | ❌ No | ✅ Yes |
| **10** | Submit to App Store TestFlight external testing | First iOS submission | 20–40 | $0 | Medium | ✅ Yes | ❌ No | ✅ Yes |

**Order matters:** #1–#3 can run in parallel while you work on #4. #6 gates everything after.

**After #10, before public launch:**
- Add Stripe integration for paid tier (~200–400 credits)
- Add Sentry crash reporting (~30–60 credits)
- Build admin dashboard UI for AI telemetry (~40–80 credits)
- Add age gate at signup (~20–40 credits)

---

## 15. FINAL DIRECT ANSWERS

### 1. How much more should I realistically spend to get V1 live?

- **Cheapest path (DIY):** ~$237 USD / £228 GBP cash + 500 credits ($5–$10 top-up)
- **Realistic:** ~$500–$700 USD / £400–£560 GBP cash + 1,000–1,500 credits
- **My honest number: budget £600 cash + 1,200 credits.**

### 2. How many Emergent credits should I buy next?

**Buy 1,000–1,500 credits.** If you have 500 already, top up to 1,500 total. This covers:
- ~200 for R2 wiring + backfill + polish
- ~200 for store submission cycles (screenshots, metadata, review notes)
- ~400 for beta bug-fixing (unpredictable)
- ~200 buffer for one Apple rejection cycle
- ~200 for Stripe integration when you're ready
- ~200 padding

**Do not buy 500 credits and rush** — you will run out mid-beta and be stuck with a broken app in real users' hands.

### 3. How long will it realistically take?

- **Fastest possible:** 10 days elapsed (if you drop everything else)
- **Realistic:** **14–21 days elapsed, ~3–4 days of your actual work**
- **Cautious with polish:** 30 days elapsed

Bottleneck is **Apple review + store metadata prep**, not code.

### 4. What will monthly running cost likely be at 50 users?

- **Low:** $22/month (£17)
- **Realistic:** **$32/month (£25)**
- **High spike:** $60/month (£47)

Your Emergent subscription is separate and already covered.

### 5. What will monthly running cost likely be at 100 users?

- **Low:** $38/month (£30)
- **Realistic:** **$57/month (£45)**
- **High spike:** $110/month (£87)

### 6. What is likely cost per client at 50 users?

**Blended average: ~$0.15/client/month (~£0.12).** At a £49 subscription, that's a **99.8% infra gross margin.** The cost that matters is Louis's time.

### 7. What should I charge per month?

**Recommended tier structure** (see Section 12 detail):
- **Standard: £49/month** — self-serve, most users
- **Premium: £99/month** — some coach access
- **High-Touch: £249/month** — real 1:1 coaching

**Do not launch at a single flat price.** You will either over-serve high-touch users at £49 (Louis burns out) or under-serve standard users at £99 (churn goes to 20%).

### 8. What should I build next?

**In order:**
1. Paste R2 credentials
2. Public privacy URL on crewfit.com
3. Apple + Google Developer accounts
4. Screenshots + feature graphic
5. First AAB/IPA build
6. 5-user internal beta

Nothing else. See Section 14.

### 9. What should I stop building?

**Do not build any of these before V1:**
- Community / social feed
- Wearable integrations
- GPS players
- Advanced nutrition (meal planning, recipes, grocery lists)
- Corporate B2B dashboard
- Multi-coach marketplace
- Localization
- Dark mode
- Any feature that "just adds a small thing"

See Section 13.

### 10. Is CrewFit ready for beta, paid users, Google Play and App Store?

Honest answer:

| Question | Answer | Blockers |
|---|---|---|
| Ready for internal beta (10–50 crew friends)? | **✅ YES today** | None |
| Ready for paid users? | **❌ NO** | No payment integration, no crash reporting, legal review recommended |
| Ready for Google Play? | **❌ NO** | Public privacy URL, screenshots, developer account, first AAB — all external, no code needed |
| Ready for App Store? | **❌ NO** | Same as Google Play + Apple Dev enrolment + TestFlight beta cycle |

**Honest risks:**
1. **App Store rejection on first submission** is likely (Apple always finds something). Budget 1–2 rejection cycles.
2. **First 10 beta users will find bugs** you never imagined. Budget 300 credits for fixes.
3. **Louis time is the constraint, not infra.** At 50 clients he's already at 24h/week. Price accordingly.
4. **Payment integration is a separate 2–4 day project** before you can charge real users.

**Do not sugar-coat:** you are 2 weeks and £600 away from an internal beta launching, and 4 weeks and £800 away from paid users on both stores. That's fast and cheap for an app this size, but only if you avoid scope creep.

---

*End of report.*

**Files updated in this pass:**
- `/app/CrewFit_Cost_Launch_Report.md` (this file)
- `/app/CrewFit_Cost_Launch_Report.txt` (identical text mirror)
