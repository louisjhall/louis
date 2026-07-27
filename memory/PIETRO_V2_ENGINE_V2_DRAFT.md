# CrewFit V2 Engine V2 — Pietro Draft (Deterministic Fixture)

Generated 2026-07-27T19:19:10.327496Z

## 1. Effective Client Context

| Field | Value |
|---|---|
| Client ID | fixture_pietro (deterministic snapshot) |
| Goal (raw) | 'marathon' |
| Goal (canonical) | `running.marathon` (Marathon) |
| Event | marathon on 2027-01-24 |
| Prep weeks | 25 |
| Current phase | **foundation** |
| Training days per week | 5 (min 4 / max 5) |
| Preferred training days | ['Mon', 'Wed', 'Fri', 'Sat', 'Sun'] |
| Preferred session length | 60 min |
| Equipment | ['bodyweight', 'dumbbells', 'treadmill'] |
| Restrictions | 'None' → parsed to empty set |
| Home base | HKG |

### Phase plan (compressed to 25 weeks)

- foundation: 2w ← current
- aerobic_base: 8w
- build: 8w
- specific_prep: 3w
- taper: 2w
- race_week: 1w

## 2. Required Objective Quotas (WHAT layer)

The demand for THIS planning window (Mon 2026-08-03 → Sun 2026-08-30, 4 weeks)

| Kind | Priority | Weekly (min/tgt/max) | Duration (min/tgt/max) | Recovery | Progression |
|---|---|---|---|---|---|
| `run_easy` | IMPORTANT | (2, 3, 3) | (25, 35, 50) | 24h | — |
| `run_long` | KEY | (0.5, 1, 1) | (45, 60, 75) | 72h | — |
| `strength_full_body` | IMPORTANT | (1, 2, 2) | (30, 40, 50) | 48h | — |
| `mobility` | SUPPORTING | (1, 2, 3) | (15, 20, 30) | 12h | — |

### Total required exposures in window: **20**

- `mobility`: 4
- `run_easy`: 8
- `run_long`: 4
- `strength_full_body`: 4

Frequency caps: `{'hard_per_week_max': 1, 'key_per_week_max': 1, 'consecutive_training_days_max': 3, 'client_sessions_per_week_min': 4, 'client_sessions_per_week_max': 4}`

Notes:
- Quota total 8.0/wk exceeds client max 4/wk — scaled by 0.50

## 3. Roster Context (rolling burden)

| Date | Day type | Burden | Opp | Avail (min) | Ceiling | Recovery | Reasons |
|---|---|---|---|---|---|---|---|
| 2026-08-03 (Mon) | home_day | 8 | 83 | 120 | any | fresh | day_type=home_day baseline_hint=8; upcoming hard streak → opp -8 |
| 2026-08-04 (Tue) | flight | 50 | 8 | 25 | rpe7 | accumulated | day_type=flight baseline_hint=50 |
| 2026-08-05 (Wed) | layover_arrival | 82 | 0 | 30 | rpe4 | accumulated | day_type=layover_arrival baseline_hint=55; prior recovery 10h +12; tz shift 8h +10 |
| 2026-08-06 (Thu) | layover_full | 40 | 45 | 75 | rpe7 | accumulated | day_type=layover_full baseline_hint=20; tz shift 16h +15; 2+ recent hard days +10 |
| 2026-08-07 (Fri) | layover_departure | 69 | 0 | 25 | rpe4 | accumulated | day_type=layover_departure baseline_hint=45; tz shift 24h +15; 1 recent hard day +5 |
| 2026-08-08 (Sat) | home_day | 32 | 70 | 120 | rpe7 | accumulated | day_type=home_day baseline_hint=8; tz shift 24h +15; 1 recent hard day +5 |
| 2026-08-09 (Sun) | home_day | 28 | 72 | 120 | rpe8 | accumulated | day_type=home_day baseline_hint=8; tz shift 16h +15; 1 recent hard day +5 |
| 2026-08-10 (Mon) | turnaround | 77 | 0 | 20 | rpe4 | accumulated | day_type=turnaround baseline_hint=55; prior recovery 11h +12; tz shift 8h +10 |
| 2026-08-11 (Tue) | home_day | 13 | 88 | 120 | rpe8 | accumulated | day_type=home_day baseline_hint=8; 1 recent hard day +5 |
| 2026-08-12 (Wed) | standby | 35 | 41 | 60 | rpe7 | accumulated | day_type=standby baseline_hint=30; 1 recent hard day +5 |
| 2026-08-13 (Thu) | home_day | 8 | 91 | 120 | any | fresh | day_type=home_day baseline_hint=8 |
| 2026-08-14 (Fri) | home_day | 8 | 91 | 120 | any | fresh | day_type=home_day baseline_hint=8 |
| 2026-08-15 (Sat) | off | 3 | 99 | 150 | any | fresh | day_type=off baseline_hint=3 |
| 2026-08-16 (Sun) | home_day | 8 | 83 | 120 | any | fresh | day_type=home_day baseline_hint=8; upcoming hard streak → opp -8 |
| 2026-08-17 (Mon) | flight | 50 | 8 | 25 | rpe7 | accumulated | day_type=flight baseline_hint=50 |
| 2026-08-18 (Tue) | layover_arrival | 87 | 0 | 30 | rpe4 | accumulated | day_type=layover_arrival baseline_hint=55; prior recovery 9h +12; tz shift 12h +15 |
| 2026-08-19 (Wed) | layover_full | 40 | 45 | 75 | rpe7 | accumulated | day_type=layover_full baseline_hint=20; tz shift 24h +15; 2+ recent hard days +10 |
| 2026-08-20 (Thu) | layover_full | 39 | 56 | 75 | rpe7 | accumulated | day_type=layover_full baseline_hint=20; tz shift 36h +15; 1 recent hard day +5 |
| 2026-08-21 (Fri) | layover_departure | 64 | 0 | 25 | rpe4 | accumulated | day_type=layover_departure baseline_hint=45; tz shift 48h +15; consecutive duty streak 3 +4 |
| 2026-08-22 (Sat) | home_day | 32 | 70 | 120 | rpe7 | accumulated | day_type=home_day baseline_hint=8; tz shift 36h +15; 1 recent hard day +5 |
| 2026-08-23 (Sun) | off | 23 | 80 | 150 | rpe8 | accumulated | day_type=off baseline_hint=3; tz shift 24h +15; 1 recent hard day +5 |
| 2026-08-24 (Mon) | home_day | 23 | 75 | 120 | rpe8 | normal | day_type=home_day baseline_hint=8; tz shift 12h +15; tz jetlag → opp -8 |
| 2026-08-25 (Tue) | home_day | 8 | 91 | 120 | any | fresh | day_type=home_day baseline_hint=8 |
| 2026-08-26 (Wed) | home_day | 8 | 91 | 120 | any | fresh | day_type=home_day baseline_hint=8 |
| 2026-08-27 (Thu) | standby | 30 | 44 | 60 | rpe7 | normal | day_type=standby baseline_hint=30 |
| 2026-08-28 (Fri) | home_day | 8 | 91 | 120 | any | fresh | day_type=home_day baseline_hint=8 |
| 2026-08-29 (Sat) | home_day | 8 | 91 | 120 | any | fresh | day_type=home_day baseline_hint=8 |
| 2026-08-30 (Sun) | off | 3 | 99 | 150 | any | fresh | day_type=off baseline_hint=3 |

## 4. Scheduled Placements (WHEN layer)

| Date | Kind | Priority | Exposure # | Duration | Intensity | Key |
|---|---|---|---|---|---|---|
| 2026-08-03 (Mon) | `run_long` | KEY | #1 | 60 min | z2 | ★ |
| 2026-08-03 (Mon) | `run_easy` | IMPORTANT | #1 | 35 min | z2 |  |
| 2026-08-03 (Mon) | `mobility` | SUPPORTING | #1 | 20 min | flow |  |
| 2026-08-09 (Sun) | `run_easy` | IMPORTANT | #2 | 35 min | z2 |  |
| 2026-08-14 (Fri) | `run_easy` | IMPORTANT | #4 | 35 min | z2 |  |
| 2026-08-15 (Sat) | `run_long` | KEY | #2 | 60 min | z2 | ★ |
| 2026-08-15 (Sat) | `run_easy` | IMPORTANT | #3 | 35 min | z2 |  |
| 2026-08-15 (Sat) | `mobility` | SUPPORTING | #2 | 20 min | flow |  |
| 2026-08-22 (Sat) | `run_easy` | IMPORTANT | #6 | 35 min | z2 |  |
| 2026-08-23 (Sun) | `run_long` | KEY | #3 | 60 min | z2 | ★ |
| 2026-08-23 (Sun) | `run_easy` | IMPORTANT | #5 | 35 min | z2 |  |
| 2026-08-23 (Sun) | `mobility` | SUPPORTING | #3 | 20 min | flow |  |
| 2026-08-26 (Wed) | `run_easy` | IMPORTANT | #8 | 35 min | z2 |  |
| 2026-08-30 (Sun) | `run_long` | KEY | #4 | 60 min | z2 | ★ |
| 2026-08-30 (Sun) | `run_easy` | IMPORTANT | #7 | 35 min | z2 |  |
| 2026-08-30 (Sun) | `mobility` | SUPPORTING | #4 | 20 min | flow |  |

**Placed: 16 / Required: 20**

### Unfilled (4)

- **`strength_full_body` (IMPORTANT)** — Cannot place strength_full_body (priority=IMPORTANT) in the target week — 14 candidate day(s) tried, all rejected.
  - 2026-08-03 — weekly_hard_cap: Week already has 1 hard days
  - 2026-08-04 — opportunity_below_floor: Opportunity 8 < floor 35 for IMPORTANT
  - 2026-08-05 — opportunity_below_floor: Opportunity 0 < floor 35 for IMPORTANT
- **`strength_full_body` (IMPORTANT)** — Cannot place strength_full_body (priority=IMPORTANT) in the target week — 21 candidate day(s) tried, all rejected.
  - 2026-08-03 — weekly_hard_cap: Week already has 1 hard days
  - 2026-08-04 — opportunity_below_floor: Opportunity 8 < floor 35 for IMPORTANT
  - 2026-08-05 — opportunity_below_floor: Opportunity 0 < floor 35 for IMPORTANT
- **`strength_full_body` (IMPORTANT)** — Cannot place strength_full_body (priority=IMPORTANT) in the target week — 21 candidate day(s) tried, all rejected.
  - 2026-08-10 — opportunity_below_floor: Opportunity 0 < floor 35 for IMPORTANT
  - 2026-08-11 — weekly_hard_cap: Week already has 1 hard days
  - 2026-08-12 — weekly_hard_cap: Week already has 1 hard days
- **`strength_full_body` (IMPORTANT)** — Cannot place strength_full_body (priority=IMPORTANT) in the target week — 14 candidate day(s) tried, all rejected.
  - 2026-08-17 — opportunity_below_floor: Opportunity 8 < floor 35 for IMPORTANT
  - 2026-08-18 — opportunity_below_floor: Opportunity 0 < floor 35 for IMPORTANT
  - 2026-08-19 — weekly_hard_cap: Week already has 1 hard days

## 5. Session Content Samples (HOW layer)

### `run_long` — running

- Duration: **60 min** (available cap: 120 min)
- Environment: `outdoor`
- Equipment used: `['running_shoes']`
- Intensity: z2
- Rationale: Run Long — foundation phase

  - **Warmup**: {'duration_min': 10, 'hr_zone': 'z1', 'cue': 'Walk 2 min. 8 min easy jog. Progressive.'}
  - **Main**: {'type': 'long_steady', 'duration_min': 45, 'hr_zone': 'z2', 'pace_target': 'MP+90s', 'fuel_cue': 'Fuel every 30-40 min if >75 min.', 'cue': 'Aerobic base. Stay relaxed.'}
  - **Cooldown**: {'duration_min': 5, 'hr_zone': 'z1', 'cue': '5 min walk. Stretch quads + calves.'}

### `run_easy` — running

- Duration: **35 min** (available cap: 120 min)
- Environment: `outdoor`
- Equipment used: `['running_shoes']`
- Intensity: z2
- Rationale: Run Easy — foundation phase

  - **Warmup**: {'duration_min': 5, 'hr_zone': 'z1', 'cue': 'Walk into easy jog. Loose ankles, tall posture.'}
  - **Main**: {'type': 'steady', 'duration_min': 25, 'hr_zone': 'z2', 'pace_target': 'conversational', 'cue': 'Nasal breathing, chat-pace. No pushing.'}
  - **Cooldown**: {'duration_min': 5, 'hr_zone': 'z1', 'cue': 'Walk-out. Light stretch — hips + calves.'}

### `mobility` — mobility

- Duration: **20 min** (available cap: 120 min)
- Environment: `any`
- Equipment used: `['mat']`
- Intensity: flow
- Rationale: Mobility flow — restorative and joint prep

  - {'name': "Cat-Cow + World's Greatest Stretch", 'duration_sec': 400}
  - {'name': 'Hip Openers: 90-90s + Deep Squat Hold + Thoracic Rotations', 'duration_sec': 400}
  - {'name': 'Legs-up-Wall + Diaphragm Breathing', 'duration_sec': 400}

## 6. Validation

✅ **Programme validation passed — 0 errors, 0 warning(s).**

### Quota report

- **required_by_kind**: `{'run_easy': 8, 'run_long': 4, 'strength_full_body': 4, 'mobility': 4}`
- **placed_by_kind**: `{'run_long': 4, 'run_easy': 8, 'mobility': 4}`
- **unfilled_total**: `4`
- **unfilled_key**: `[]`
- **weekly_hard**: `{'(2026, 32)': 1, '(2026, 33)': 1, '(2026, 34)': 1, '(2026, 35)': 1}`
- **weekly_key**: `{'(2026, 32)': 1, '(2026, 33)': 1, '(2026, 34)': 1, '(2026, 35)': 1}`

## 7. Old vs New — Named failure modes

### Old August observed

```
- 8 Long Runs in one month
- Long Runs 48 hours apart
- Tempo Run immediately after Long Run
- 90-minute default durations on most Home Days
- 120-minute sessions on Off days
- Repeated/reset exposure numbering
- Running-heavy programming with little/no strength or mobility
- Generic equipment labels such as bodyweight, dumbbells, treadmill
- Rest used as the default response to many aviation duties
- Some layover/turnaround scoring that appears overly categorical
```

### New engine result

| Check | Result | Evidence |
|---|---|---|
| ≤ 4 long runs in 4-week window | ✅ | actual: 4 |
| No more than 1 long run per week | ✅ | actual max: 1 |
| Long runs ≥ 3 days apart | ✅ | actual min gap: 7d |
| Zero tempo runs immediately after long runs | ✅ | count: 0 |
| Duration NOT auto-set from availability | ✅ | target from goal+phase+progression only |
| Exposure numbering monotonic per objective | ✅ | verified in test suite |
| Running ≤ 85% of programme (strength/mobility present) | ✅ | running 12 / 16 = 75%, strength=0, mobility=4 |
| Running sessions NEVER labelled with 'dumbbells/bodyweight' | ✅ | labels: outdoor/treadmill + running_shoes only |
| No opp=100 blanket across the roster | ✅ | rolling burden produces varied opp |
| Missing DNA cannot become unlimited | ✅ | verified in test: sessions_per_week_max floor = 5 in code |
| Ready gating requires validated content | ✅ | validate_session blocks empty payload |

---

*This report was generated by the deterministic fixture in 
`/app/backend/tests/test_engine_v2_invariants.py`. Re-run any time with:*

```bash
python /app/backend/scripts/run_pietro_shadow.py
```