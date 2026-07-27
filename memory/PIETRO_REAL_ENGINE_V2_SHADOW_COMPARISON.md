# Pietro Real-Client Engine V2 Shadow Comparison

Generated 2026-07-27T20:29:41.150223Z

## Kickoff result

- ok: **False**  status: `needs_review`
- goal: `running.marathon` (Marathon)
- phase: **foundation**
- planning_window: {'start': '2026-07-27', 'end': '2026-08-23', 'weeks': 4}
- counts: `{'required_exposures': 20, 'placements': 19, 'unfilled': 1, 'validation_errors': 1, 'validation_warnings': 0}`
- took: 0.021s

## Required Objective Quotas (WHAT)

| Objective | Required | Priority |
|---|---:|---|
| `run_easy` | 8 | IMPORTANT |
| `run_long` | 4 | KEY |
| `strength_full_body` | 4 | IMPORTANT |
| `mobility` | 4 | SUPPORTING |

**Total required exposures**: 20

## Exposure Sequence (identity check)

| Objective | Kind | Exposures placed | # sequence |
|---|---|---:|---|
| `58b78c1a9db2` | `run_long` | 4 | [1, 2, 3, 4] |
| `7a224682104f` | `run_easy` | 7 | [1, 2, 3, 4, 5, 6, 7] |
| `0aaafcc083a4` | `strength_full_body` | 4 | [1, 2, 3, 4] |
| `d5aa35ba68e8` | `mobility` | 4 | [1, 2, 3, 4] |

## Placements (WHEN)

| Date | Weekday | Kind | # | Priority | Duration | Key |
|---|---|---|---:|---|---:|:-:|
| 2026-07-28 | Tue | `run_easy` | #1 | IMPORTANT | 35 min |  |
| 2026-07-31 | Fri | `strength_full_body` | #1 | IMPORTANT | 40 min |  |
| 2026-08-01 | Sat | `run_easy` | #2 | IMPORTANT | 35 min |  |
| 2026-08-01 | Sat | `mobility` | #1 | SUPPORTING | 20 min |  |
| 2026-08-02 | Sun | `run_long` | #1 | KEY | 60 min | ★ |
| 2026-08-04 | Tue | `run_easy` | #3 | IMPORTANT | 35 min |  |
| 2026-08-05 | Wed | `strength_full_body` | #2 | IMPORTANT | 40 min |  |
| 2026-08-05 | Wed | `mobility` | #2 | SUPPORTING | 20 min |  |
| 2026-08-08 | Sat | `run_easy` | #4 | IMPORTANT | 35 min |  |
| 2026-08-09 | Sun | `run_long` | #2 | KEY | 60 min | ★ |
| 2026-08-12 | Wed | `run_easy` | #5 | IMPORTANT | 35 min |  |
| 2026-08-12 | Wed | `mobility` | #3 | SUPPORTING | 20 min |  |
| 2026-08-14 | Fri | `strength_full_body` | #3 | IMPORTANT | 40 min |  |
| 2026-08-15 | Sat | `run_easy` | #6 | IMPORTANT | 35 min |  |
| 2026-08-16 | Sun | `run_long` | #3 | KEY | 60 min | ★ |
| 2026-08-18 | Tue | `run_easy` | #7 | IMPORTANT | 35 min |  |
| 2026-08-18 | Tue | `mobility` | #4 | SUPPORTING | 20 min |  |
| 2026-08-19 | Wed | `strength_full_body` | #4 | IMPORTANT | 40 min |  |
| 2026-08-23 | Sun | `run_long` | #4 | KEY | 60 min | ★ |

## Session Content Samples (HOW)

### `run_long`
- duration: **60 min**
- environment: `outdoor`
- equipment_used: `['running_shoes']`
- rationale: Run Long — foundation phase
  - warmup: `{'duration_min': 10, 'hr_zone': 'z1', 'cue': 'Walk 2 min. 8 min easy jog. Progressive.'}`
  - main: `{'type': 'long_steady', 'duration_min': 45, 'hr_zone': 'z2', 'pace_target': 'MP+90s', 'fuel_cue': 'Fuel every 30-40 min if >75 min.', 'cue': 'Aerobic base. Stay relaxed.'}`
  - cooldown: `{'duration_min': 5, 'hr_zone': 'z1', 'cue': '5 min walk. Stretch quads + calves.'}`
### `run_easy`
- duration: **35 min**
- environment: `outdoor`
- equipment_used: `['running_shoes']`
- rationale: Run Easy — foundation phase
  - warmup: `{'duration_min': 5, 'hr_zone': 'z1', 'cue': 'Walk into easy jog. Loose ankles, tall posture.'}`
  - main: `{'type': 'steady', 'duration_min': 25, 'hr_zone': 'z2', 'pace_target': 'conversational', 'cue': 'Nasal breathing, chat-pace. No pushing.'}`
  - cooldown: `{'duration_min': 5, 'hr_zone': 'z1', 'cue': 'Walk-out. Light stretch — hips + calves.'}`
### `strength_full_body`
- duration: **40 min**
- environment: `home`
- equipment_used: `['bodyweight', 'dumbbells']`
- rationale: Strength Full Body — foundation phase
  - Goblet Squat — 3×6-8 @ RPE8
  - Dumbbell RDL — 3×6-8 @ RPE8
  - Push-up — 3×8-10 @ RPE7
### `mobility`
- duration: **20 min**
- environment: `any`
- equipment_used: `['mat']`
- rationale: Mobility flow — restorative and joint prep
  - {'name': "Cat-Cow + World's Greatest Stretch", 'duration_sec': 400}
  - {'name': 'Hip Openers: 90-90s + Deep Squat Hold + Thoracic Rotations', 'duration_sec': 400}
  - {'name': 'Legs-up-Wall + Diaphragm Breathing', 'duration_sec': 400}

## Unfilled (1)

- **`run_easy`** (IMPORTANT) — Cannot place run_easy (priority=IMPORTANT) target week 2026-08-17..2026-08-23 allowed window 2026-08-10..2026-08-30 — 14 candidate day(s) tried, all rejected.
  - 2026-08-10 — opportunity_below_floor: Opportunity 15 < floor 35 for IMPORTANT
  - 2026-08-11 — opportunity_below_floor: Opportunity 8 < floor 35 for IMPORTANT
  - 2026-08-12 — same_day_family_conflict: run_easy already placed on 2026-08-12

## Programme Validation Result

- **ok**: False
- ❌ `important_unfilled` — IMPORTANT run_easy required but could not be placed — Cannot place run_easy (priority=IMPORTANT) target week 2026-08-17..2026-08-23 allowed window 2026-08-10..2026-08-30 — 14 candidate day(s) tried, all rejected. (coach review required)

Quota report:
- `required_by_kind` = `{'run_easy': 8, 'run_long': 4, 'strength_full_body': 4, 'mobility': 4}`
- `placed_by_kind` = `{'run_long': 4, 'run_easy': 7, 'strength_full_body': 4, 'mobility': 4}`
- `priority_by_kind` = `{'run_easy': 'IMPORTANT', 'run_long': 'KEY', 'strength_full_body': 'IMPORTANT', 'mobility': 'SUPPORTING'}`
- `unfilled_total` = `1`
- `unfilled_key` = `[]`
- `unfilled_important` = `['run_easy (no_valid_slot)']`
- `unfilled_supporting` = `[]`
- `unfilled_optional` = `[]`
- `weekly_hard` = `{'(2026, 31)': 1, '(2026, 32)': 1, '(2026, 33)': 1, '(2026, 34)': 1}`
- `weekly_key` = `{'(2026, 31)': 1, '(2026, 32)': 1, '(2026, 33)': 1, '(2026, 34)': 1}`
- `weekly_strength` = `{'(2026, 31)': 1, '(2026, 32)': 1, '(2026, 33)': 1, '(2026, 34)': 1}`
- `daily_totals_min` = `{'2026-08-02': 60, '2026-08-09': 60, '2026-08-16': 60, '2026-08-23': 60, '2026-08-01': 55, '2026-07-31': 40, '2026-07-28': 35, '2026-08-04': 35, '2026-08-05': 60, '2026-08-08': 35, '2026-08-12': 55, '2026-08-14': 40, '2026-08-15': 35, '2026-08-18': 55, '2026-08-19': 40}`

## Old-engine current calendar (workout_assignments)
| Kind | Count |
|---|---:|
| `long_run` | 10 |
| `intervals_run` | 3 |
| `tempo_run` | 3 |
| `easy_run` | 2 |

Old-engine Long Run dates: ['2026-07-31', '2026-08-02', '2026-08-05', '2026-08-08', '2026-08-12', '2026-08-14', '2026-08-19', '2026-08-23', '2026-08-30', '2026-08-31']


## Availability-as-Ceiling Proof

- 2026-08-02 — `run_long`: target=60min (availability on this day was NOT prescribed as duration).
- 2026-08-09 — `run_long`: target=60min (availability on this day was NOT prescribed as duration).
- 2026-08-16 — `run_long`: target=60min (availability on this day was NOT prescribed as duration).

## Old vs New

| Metric | Old Engine | Engine V2 |
|---|---:|---:|
| Long Runs | 10 | 4 |
| Total placements | 18 | 19 |
| Programme validation | (not gated) | **False** |
| Min LR gap | (varied — some 24h) | 7 days |