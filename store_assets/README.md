# CrewFit — App Store & Play Store Screenshots

**Generated:** Iter 95c · June 2026
**Cast:** male pilot (Louis-like) + female cabin crew (South Asian / Filipino heritage). Both in black CrewFit tees with the small white CREWFIT wordmark on chest + red trainers.
**Style:** cinematic aviation-adjacent premium fitness editorial. Warm morning light. No client-facing "AI" wording anywhere.

## What's here

```
/app/store_assets/
├── heroes/            ← generated background images (Gemini Nano Banana)
├── screens/           ← raw in-app screenshots (Expo web preview, 430×932)
├── final/             ← 1290×2796 App Store screenshots (6.7"/6.9" iPhone)
├── final_play/        ← 1080×1920 Google Play phone screenshots (9:16)
└── README.md
```

## The 6 screenshots

| # | Key                | Headline                                | Hero image                | Real screen           |
|---|--------------------|-----------------------------------------|---------------------------|-----------------------|
| 1 | `home_briefing`    | Coaching that flies with you.           | Pilot warming up · hangar | Home dashboard        |
| 2 | `guided_workout`   | Never train alone in a hotel again.     | Pilot · hotel gym         | Guided workout timer  |
| 3 | `roster_upload`    | Upload roster. We do the rest.          | Crew · airport concourse  | Roster upload screen  |
| 4 | `nutrition`        | Fuel across every timezone.             | Crew · kitchen with meal  | Nutrition dashboard   |
| 5 | `real_coach`       | Built by crew. For crew.                | Pilot + Crew · studio     | Messages / Louis chat |
| 6 | `crew_hotel`       | Hotel room. 20 minutes. Done.           | Crew · hotel squats       | Workout detail        |

## Branding (Iter 95d)

Each hero image has the **actual CrewFit winged logo** (red wings + white
CREWFIT wordmark) printed on the chest of the t-shirt — placed by Nano
Banana's image-edit mode using `/app/store_assets/brand/crewfit_logo_transparent.png`
as the reference. Nano Banana renders the logo with correct fabric curvature,
lighting and perspective per shot.

- Branded heroes:    `/app/store_assets/heroes_v2/`
- Original heroes:   `/app/store_assets/heroes/`  (kept for reference)
- Transparent logo:  `/app/store_assets/brand/crewfit_logo_transparent.png`

## How to upload

### Apple App Store Connect

1. Open your CrewFit app record → *App Store* tab → *iOS App*.
2. Under **App Previews and Screenshots** → **6.7" Display**, drag files 01–06 from `/app/store_assets/final/`.
3. Apple will automatically reuse the 6.7" set for 6.9" iPhone unless you upload separate ones (no need — 1290×2796 satisfies both).
4. Save. Then submit for TestFlight External Beta Review.

### Google Play Console

1. Open your CrewFit app → *Store presence* → *Main store listing* → *Screenshots (phone)*.
2. Drag files 01–06 from `/app/store_assets/final_play/`.
3. Save.

## Regenerate

If you change the copy, cast or app UI, regenerate with:

```bash
# 1) Hero images (~90 s each — costs Nano Banana image credits)
python3 /app/scripts/generate_store_heroes.py

# 2) Composite the final screenshots (fast, local, free)
python3 /app/scripts/build_store_screens.py
```

To regenerate only ONE hero, pass its key:

```bash
python3 /app/scripts/generate_store_heroes.py hero_crew_hotel
```

If you want to update ONLY the app-screen inside a screenshot (because a UI
change happened) — take a fresh in-app screenshot at 430×932, drop it in
`/app/store_assets/screens/` with the same name, and re-run the composer.

## Copyright / usage

- The cast are AI-generated fictional models. They are not real people. Safe to publish.
- The CrewFit wordmark on their shirts is legible — this reinforces brand, matches the app's real "CREWFIT" logo, and does not depict any airline.
- No airline branding, no real flight numbers, no visible passenger data — safe for App Store review.
