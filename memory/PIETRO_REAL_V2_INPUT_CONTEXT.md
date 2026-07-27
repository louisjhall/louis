# Pietro — Real V2 Input Context

Generated 2026-07-27T19:57:05.512318Z

## CLIENT
- id: `c4c7c7dd-4303-4645-af2c-b70212495360`
- name: Pietro Sangermano

## PRIMARY GOAL
- profile.main_goal = `'Marathon'`
- profile.event_type_pref = `'marathon'`
- profile.primary_goal_id = `'marathon'`

## SECONDARY GOALS
- profile.secondary_goal_ids = []

## EVENT
- marathon on 2027-01-17
- event id: `077cc47e-652f-4552-9298-9e1c87b72777`

## AVAILABILITY
- training_days_per_week: 5
- training_days: 5
- max_home_minutes: 60
- time_home_min: 60
- time_layover_min: 60
- preferred_training_days: None
- sessions_per_week_min: None
- sessions_per_week_max: None
- preferred_session_length: None

## RESTRICTIONS
- profile.injuries: `'None'`
- profile.no_go_movements: ['none']
- restrictions collection rows: 0

## EQUIPMENT
- profile.equipment: ['dumbbells', 'treadmill']
- profile.home_equipment: ['dumbbells', 'treadmill']
- equipment_contexts (permanent): ['bodyweight', 'dumbbells', 'treadmill']
- hotel_gym_reliability: always

## ROSTER SUMMARY
- 62 schedule_days
  - home_day: 25
  - standby: 8
  - layover_arrival: 7
  - layover_departure: 7
  - turnaround: 4
  - home: 3
  - direct flight: 2
  - layover: 2
  - rest: 1
  - layover_full: 1
  - flight: 1
  - off: 1

## ACTIVE COACH DIRECTIVES
- 0 active

## PROFILE PHYSICAL
- height_cm: 181.0
- weight_kg: 83.0
- sex: male
- experience_level: 10_to_15k

## FIELD FIDELITY CHECK
| Field | Stored | Engine V2 Received | Used By | Status |
|---|---|---|---|---|
| main_goal | `Marathon` | `marathon` → canonical `running.marathon` | canonicalise_goal_key | USED |
| event_date | `2027-01-17` | passed to _load_effective_context | end_date calc | USED |
| training_days_per_week | `5` | `5` | _client_frequency_bounds | USED |
| preferred_training_days | `None` | empty set | scheduler rank bias | MISSING — not captured in DNA |
| sessions_per_week_max | `None` | falls back to training_days_per_week | frequency cap | MISSING (falls back — OK) |
| preferred_session_length | `None` | none | (not read by v2) | MISSING — v2 uses quota target |
| max_home_minutes | `60` | clipped Home Day cap to 60 | roster context clip | USED (fix applied this iteration) |
| time_layover_min | `60` | clipped Layover cap to 60 | roster context clip | USED (fix applied this iteration) |
| injuries | `None` | 0 restrictions | avoid_patterns | USED (None → empty) |
| equipment | `['dumbbells', 'treadmill']` | `['bodyweight', 'dumbbells', 'treadmill']` | _pick_running_environment / _pick_strength | USED |
| home_base | `AUH` | passed | equipment_context.detail | USED |
| schedule_days | 62 rows Jul-Aug | build_day_contexts | rolling burden | USED |
| coach_directives | 0 active | active_directives_for | avoid_patterns | USED (empty) |
| secondary_goal_ids | `[]` | none | (not read) | MISSING — single-goal engine v1 |