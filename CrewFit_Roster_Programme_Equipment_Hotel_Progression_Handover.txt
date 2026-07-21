# CrewFit Roster-To-Programme, Equipment, Hotel And Progression System — Full Confidence Handover

**Prepared:** 29 June 2026
**Basis:** live code inspection (`/app/backend`, `/app/frontend`), live DB inspection (`crewfit_v1`), and the pytest suites from iterations 75-80 (110/110 green).
**Scope:** everything from client signup through roster upload, programme build, workout generation, hotel handling, progression, coach controls.
**Tone:** brutally honest — nothing is called "working" unless it is implemented AND covered by a test that passed in the current codebase.

---

## SECTION 1 — SIMPLE END-TO-END SUMMARY

| # | Step | Status |
|---|---|---|
| 1 | New client creates account | **working** |
| 2 | Client completes profile setup (age/sex/pronouns confirmation) | **working** |
| 3 | Client completes Coaching DNA / consultation (Claude adaptive) | **working** |
| 4 | Client selects goal | **working** (fixed Plan A1 — was silently discarded) |
| 5 | Client selects training days per week | **working** (fixed Plan A1) |
| 6 | Client selects home equipment | **PARTIAL** — collected + stored, but coarse-grained (list only, no bench/rack/cable individual flags) |
| 7 | Client adds injury / limitation notes | **PARTIAL** — free text captured, not machine-actionable |
| 8 | Client uploads roster | **working** (3-layer defensive parser — Gemini → Claude Vision → user fallback) |
| 9 | Roster is parsed | **working** |
| 10 | Client reviews / confirms roster | **working** (edit any day, streaming progress) |
| 11 | Client confirms layovers / turnarounds / hotels | **MISSING** — no hotel-name / per-hotel confirmation step exists |
| 12 | Programme is created | **working** (LLM + deterministic fallback) |
| 13 | Weekly structure is created | **working** (per-goal + per-phase weekly shape, Plan B1) |
| 14 | Workouts are created | **working** |
| 15 | Exercises are selected | **PARTIAL** — V2 Library resolution + drop; equipment matching is coarse |
| 16 | Programme progression is planned | **PARTIAL** — phase + week + next_progression hint stored; per-exercise progression not stored |
| 17 | Programme is validated | **working** (11 validator rules — Plan A + B4) |
| 18 | Client sees Today / Next 7 Days / Programme Overview | **working** (Plan C1 + C2) |
| 19 | Louis sees dashboard, timeline, progress | **working** (Plan C3) |
| 20 | Future check-ins / completions / misses affect progression | **PARTIAL** — data is captured; automatic progression adjustment IS NOT wired to a feedback loop |

---

## SECTION 2 — CLIENT VARIABLES COLLECTED

| Field (client label) | DB field | Collection | Req? | Saved? | Used in gen? | Used in workout? | Used in progression? | Validated? | Louis sees? | Louis edits? |
|---|---|---|---|---|---|---|---|---|---|---|
| Name | name | users | yes | ✅ | — | — | — | — | ✅ | ✅ |
| Email | email | users | yes | ✅ | — | — | — | — | ✅ | ✅ |
| Biological sex | profile.biological_sex | users | yes | ✅ | ✅ (Claude bias check) | ✅ | — | — | ✅ | ✅ |
| Age confirmation | profile.age_confirmed | users | yes | ✅ | — | — | — | — | ✅ | — |
| Aviation role | profile.job_title | users | yes | ✅ | ✅ | ✅ | — | — | ✅ | ✅ |
| Long/short haul | profile.route_focus | users | opt | ✅ | ✅ | ✅ | — | — | ✅ | ✅ |
| Home base | profile.home_base | users | opt | ✅ | ✅ | — | — | — | ✅ | ✅ |
| Airline | profile.airline | users | opt | ✅ | ✅ | — | — | — | ✅ | ✅ |
| Primary goal (multi-select) | profile.primary_goal_id + main_goal_key + main_goal | users | yes | ✅ (Plan A1) | ✅ | ✅ | ✅ | ✅ | ✅ | via API |
| Secondary goals | profile.secondary_goal_ids | users | opt | ✅ | ✅ | partial | — | — | ✅ | via API |
| Event type preference | profile.event_type_pref | users | derived | ✅ (Plan A2) | ✅ | ✅ | ✅ | ✅ | ✅ | via API |
| Event date | events.event_date | events | opt | ✅ | ✅ (event_context) | ✅ | ✅ | — | ✅ | ✅ |
| Training days per week | profile.training_days_per_week | users | yes | ✅ (Plan A1) | ✅ | ✅ | ✅ | ✅ (Plan A3) | ✅ | ✅ |
| Experience level | profile.experience_level | users | yes | ✅ | ✅ | ✅ | partial | — | ✅ | — |
| Home equipment (list) | profile.equipment + home_equipment | users | opt | ✅ | ✅ | ✅ (V2 resolver) | — | partial | ✅ | via API |
| Max home minutes | profile.max_home_minutes | users | opt | ✅ | ✅ | ✅ | — | — | ✅ | — |
| Injuries (free text) | profile.injury_notes | users | opt | ✅ | ✅ (prompt) | ✅ (prompt) | — | — | ✅ | ✅ |
| Hotel gym frequency | profile.hotel_gyms | users | yes | ✅ | ✅ | ✅ | — | — | ✅ | — |
| Hotel gym confidence | dna.aviation_profile.hotel_gym_frequency | coaching_dna | opt | ✅ | ✅ | ✅ | — | — | via coach client detail | — |
| Coaching DNA snapshot | (full doc) | coaching_dna | yes | ✅ | ✅ | ✅ | partial | — | ✅ | — |
| Roster days | rosters.days[] | rosters | yes | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ (edit day) |
| Layover flag on a day | rosters.days[].day_type contains "layover" | rosters | derived | partial | ✅ | ✅ | — | — | ✅ | ✅ |
| Turnaround flag | ⚠ not modelled explicitly | — | — | ❌ | ❌ | ❌ | ❌ | ❌ | — | — |
| Hotel name / city / equipment | ⚠ NOT COLLECTED per-day | — | — | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

**Verdict on Section 2:** the client data model is well-populated for goal, availability, roster, general equipment and general hotel frequency. **Per-hotel equipment tracking is not implemented at all.**

---

## SECTION 3 — CONSULTATION ANSWERS USED OR IGNORED

For each answer collected in the adaptive assessment:

| Answer | Collected | Stored | Passed to gen | Weekly structure | Exercise choice | Progression | Louis sees | Validator |
|---|---|---|---|---|---|---|---|---|
| Marathon prep | ✅ | ✅ (profile.main_goal_key='event', event_type_pref='marathon') | ✅ | ✅ (event weekly shape) | ✅ | ✅ | ✅ | ✅ (no-run rule) |
| Half marathon / 10k / 5k | ✅ | ✅ | ✅ | ✅ | ✅ | partial | ✅ | ✅ |
| Ironman / triathlon | ✅ | ✅ | ✅ | ✅ (swim/bike/brick slots) | partial | partial | ✅ | ✅ |
| HYROX | ✅ | ✅ | ✅ | ✅ | partial | partial | ✅ | ✅ |
| 4 days/week max | ✅ | ✅ (Plan A1) | ✅ | ✅ (Plan A3 cap) | ✅ | ✅ | ✅ | ✅ (rule 8) |
| Beginner/intermediate/advanced | ✅ | ✅ (profile.experience_level) | ✅ | partial | partial | ⚠ not machine-actionable | ✅ | ❌ |
| Preferred session duration | ✅ | ✅ (max_home_minutes) | ✅ | ✅ | ✅ | — | ✅ | ❌ |
| Home equipment | ✅ | ✅ | ✅ | ✅ | ✅ (V2 resolver) | — | ✅ | ⚠ no explicit "unavailable exercise" validator |
| Hotel gym access (frequency) | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ | ❌ |
| Bodyweight only | ✅ | ✅ (equipment list) | ✅ | ✅ | ✅ (fallback goes bodyweight when equipment empty) | — | ✅ | ❌ |
| Dumbbells only | ✅ | ✅ | ✅ | ✅ | partial (no strict "no barbell" enforcement) | — | ✅ | ❌ |
| Full gym | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ | — |
| Injury notes | ✅ | ✅ | ✅ (prompt) | partial | partial (LLM instruction only, not enforced) | ⚠ no adjustment | ✅ | ❌ |
| Fat loss | ✅ | ✅ (main_goal_key='lose_fat') | ✅ | ✅ (strength shape) | ✅ | partial | ✅ | ✅ |
| Strength/muscle | ✅ | ✅ (main_goal_key='build_muscle') | ✅ | ✅ | ✅ | partial (fields exist, no auto-progression) | ✅ | ✅ |
| General fitness | ✅ | ✅ | ✅ | ✅ | ✅ | partial | ✅ | ✅ |
| Health markers | ✅ | ✅ | ✅ | ✅ | ✅ | partial | ✅ | ✅ |
| Return to training | ✅ | ✅ | ✅ | ✅ | ✅ | partial | ✅ | ✅ |
| Improve energy | ✅ | ✅ | ✅ | ✅ | ✅ | partial | ✅ | ✅ |
| Confidence / body composition | ⚠ mapped to fat_loss/general_fitness | partial | partial | partial | partial | — | partial | — |
| Roster struggle | ⚠ captured in DNA but not structured | partial | partial (Claude sees) | — | — | — | via DNA | — |
| Sleep / recovery issues | ⚠ captured in DNA free text | partial | partial (Claude sees) | — | — | — | via DNA | — |

**Verdict on Section 3:** goal + availability answers now genuinely drive the plan. Injury notes are seen by the LLM but not automatically enforced (no "avoid X pattern" rule). Roster/sleep struggle answers are seen by the LLM but not surfaced as structured signals into the generator.

---

## SECTION 4 — TRAINING DAYS PER WEEK

- **Stored at**: `users.profile.training_days_per_week` (int 1-7). Also mirrored to `programmes.target_sessions_per_week`.
- **Population path**: assessment → `_apply_assessment_answers_to_profile` (Plan A1) — matches fuzzy question IDs (`training_days`, `weekly_training_time_available`, `days_per_week`, plus DNA fallback).
- **Passed to LLM**: yes, via `programme_context.profile_snapshot.training_days_per_week` AND `programme_context.target_sessions_per_week`. The WORKOUT_SYSTEM prompt now has a HARD RULE: "The number of REAL training sessions per 7-day chunk MUST NOT exceed `profile.training_days_per_week`. Extra days MUST be `focus='recovery'` cards".
- **Post-generation enforcement**: `server._apply_days_cap_and_min_content` runs after LLM AND after fallback. Groups workouts into ISO-week windows; if real training sessions > cap, demotes the trailing ones (priority-preserved: key_session → endurance → strength) to `Optional Recovery Walk` (focus='recovery', duration=20, optional=true).
- **Validator**: `feature_programme_quality.validate_programme` rule 8 — weeks with `>target+2` → **error**; `target+1` → **warning**.
- **Client visibility**: shown in Programme Overview card ("YOUR CURRENT FOCUS") as "N/target this week" (Plan C2).
- **Coach visibility**: shown in Programme Overview card + Programme Timeline tab (Plan C3).

**Can 7 workouts still appear for a 4-day/wk client?** Historically YES (that's the exact bug Louis reported). Now NO — the post-gen cap runs on both LLM + fallback paths. Verified in test iteration 75 T2 (7 → 4 real + 3 optional recovery). Optional recovery cards are labelled explicitly and do not count toward the training cap.

**Client-visible messaging when roster forces below cap?** ⚠ partial — the Programme Overview card shows planned/target for the current week, but there is no explicit "your roster only allowed 2 safe windows this week" copy yet.

---

## SECTION 5 — GOAL AND EVENT PROCESS

`_resolve_goal_key` (feature_programme_quality) → `main_goal_key` via `GOAL_MATRIX`. Everything downstream reads from `main_goal_key`.

| Goal | main_goal_key | Event row? | Weekly target | Session types | Progression | Validator | Louis / client |
|---|---|---|---|---|---|---|---|
| Marathon | event | ✅ (dated or `needs_date_confirmation`) | 4 | easy_run · long_run · tempo · intervals · strength_support | phase-aware (foundation/build/peak/deload) | no-run error | ✅ / ✅ |
| Half marathon | event | ✅ | 4 | same as marathon | ✅ | no-run error | ✅ / ✅ |
| 5K / 10K | event | ✅ | 4 | intervals-heavy at peak | ✅ | no-run error | ✅ / ✅ |
| Triathlon (sprint/oly/70.3/full) | event | ✅ | 4-6 | swim / bike / brick / run | phase-aware | no-run error | ✅ / ✅ |
| HYROX | event | ✅ | 4 | conditioning + strength_support + intervals | partial | no-run error | ✅ / ✅ |
| Fat loss | lose_fat | — | 3 | upper/lower strength + conditioning + mobility | phase (foundation/build/deload) | template-ratio | ✅ / ✅ |
| Build muscle | build_muscle | — | 4 | push · pull · leg · upper | phase (foundation/build/peak/deload) | template-ratio | ✅ / ✅ |
| Build strength | build_muscle | — | same as build_muscle | ✅ | ✅ | ✅ | ✅ / ✅ |
| General fitness | general_fitness | — | 3 | upper_strength + conditioning + lower + mobility | partial | template-ratio | ✅ / ✅ |
| Improve energy | improve_energy | — | 3 | easy_run + mobility + light strength | partial | — | ✅ / ✅ |
| Health markers / aviation medical | health_markers | — | 3 | mixed aerobic + strength + mobility | gentle | — | ✅ / ✅ |
| Aviation consistency / roster | aviation_consistency | — | 3 | short strength + mobility | gentle | — | ✅ / ✅ |
| Return to training | return_to_training | — | 2 | mobility-heavy ramp | slow | — | ✅ / ✅ |
| Sport / hobby / confidence | ⚠ falls through to general_fitness | — | — | — | — | — | partial |
| Mobility only | improve_energy | — | 3 | mobility-heavy | — | — | ✅ / ✅ |

---

## SECTION 6 — MARATHON PREP PROCESS

Full path when a client picks Marathon:

1. Assessment answer `primary_goal = ['marathon']` (or `primary_goals` — both handled).
2. `_apply_assessment_answers_to_profile` → sets `profile.main_goal_key='event'`, `main_goal='Marathon'`, `event_type_pref='marathon'`, `primary_goal_id='marathon'`.
3. If an event date is in the answers or DNA `next_event`, insert dated `events` row. Otherwise insert `needs_date_confirmation=true` stub.
4. Programme generation reads `profile.event_type_pref='marathon'` → `event_weekly_shape('marathon', phase, target_sessions)` returns the ideal slots:
   - foundation: `[easy_run, long_run, strength_support, easy_run]` + mobility/recovery padding
   - build: `[easy_run, long_run, tempo, strength_support, easy_run]`
   - peak: `[easy_run, long_run, intervals, strength_support, easy_run]`
   - deload: `[easy_run, long_run, easy_run, strength_support]`
5. `programme_context.weekly_shape_ideal` is injected into the LLM prompt PLUS the fallback consumes the same list.
6. The fallback (`build_template_plan`) has the real running templates: `EASY_RUN_MAIN`, `LONG_RUN_MAIN`, `TEMPO_RUN_MAIN`, `INTERVAL_RUN_MAIN`, `STRENGTH_FOR_RUNNERS`, plus `COOLDOWN_RUN`.
7. Aviation safety overrides preserved: long-haul day → Flight Recovery Mobility (not a run); standby → Activation. Excess runs slide, they don't get cut arbitrarily.
8. Post-gen cap enforces 4 real training sessions per week.
9. Validator rule 9: endurance/event goal with no running session → **error**.
10. Long run automatically flagged `key_session=true` (in stub factory and in the prompt) — so C7 preserves it during regen.

**End-to-end test (iteration 76 T3)**: Marathon Prep + 4 days/wk + 14-day roster with 2 long-hauls + 2 layovers → exactly 4 real sessions/week, at least 1 Long Run + 1 Easy Run + 1 Strength for Runners per week, ZERO "Full Body Strength" cards. Verified.

**Can current system deliver Louis' expected marathon plan?** ✅ YES for 2-3 week horizon. **Progression across 12-16 weeks (auto-increasing long-run duration by 10% every fortnight)** — partial: the `next_progression` hint is stored, but no automatic increase is applied to next week's workouts based on completion data yet.

---

## SECTION 7 — HOME EQUIPMENT PROCESS

- **Collected at**: assessment (`equipment_home` / `equipment_access_home` — dynamic id) as a **flat list of strings** (e.g. `["dumbbells", "bench", "resistance_bands"]`), or nested `{location, equipment: [...]}` dict.
- **Stored at**: `users.profile.equipment` AND `users.profile.home_equipment` (duplicated for compat). One source of truth is `profile.equipment`.
- **Passed into gen**: yes, via `programme_context.profile_snapshot.equipment` and the LLM prompt.
- **Passed into workout gen**: yes.
- **Passed into V2 resolver**: yes — `feature_v2_resolver` filters candidates by `equipment_type` overlap with the client's equipment.
- **Validator**: no explicit "unavailable exercise" rule. If the LLM asks for a barbell squat and the client has no barbell, the resolver TRIES to substitute; if no substitute matches, the exercise is DROPPED (which used to leave 45-min workouts with 1 exercise — mitigated by Plan A4 min-content rule).

**Equipment options currently supported (V2 library `equipment_type` tags):**

| Option | Client UI selectable | Stored | Used in gen | V2 tag exists |
|---|---|---|---|---|
| Bodyweight only | ✅ | ✅ | ✅ (fallback goes bodyweight) | ✅ bodyweight |
| Dumbbells | ✅ | ✅ | ✅ | ✅ dumbbells |
| Adjustable dumbbells | partial (rolls into "dumbbells") | ✅ | partial | ⚠ no separate tag |
| Kettlebells | ✅ | ✅ | ✅ | ✅ kettlebell |
| Resistance bands | ✅ | ✅ | ✅ | ✅ bands |
| Bench | partial | ✅ | partial | ⚠ used loosely — no strict "requires bench" rule |
| Pull-up bar | ⚠ not a distinct chip | ⚠ | ⚠ | ⚠ |
| Barbell | ✅ | ✅ | ✅ | ✅ barbell |
| Squat rack | ⚠ not a distinct chip | ⚠ | ⚠ | ⚠ |
| Cable machine | ⚠ not a distinct chip | ⚠ | ⚠ | ⚠ |
| Treadmill | ⚠ implicit (client can add) | partial | partial | ⚠ |
| Exercise bike / rowing machine | ⚠ implicit | partial | partial | ⚠ |
| Skipping rope | ⚠ | partial | partial | ⚠ |
| TRX / suspension | ⚠ | partial | partial | ⚠ |
| Yoga mat / foam roller | ⚠ implied | partial | partial | ⚠ |
| Mini bands | ⚠ | partial | partial | ⚠ |
| Step / box | ⚠ | partial | partial | ⚠ |
| Full home gym | ✅ (via chip) | ✅ | ✅ | ✅ (matches all) |
| Commercial gym | ✅ | ✅ | ✅ | ✅ |
| Outdoor only | ✅ | ✅ | ✅ | ✅ |
| No equipment | ✅ | ✅ | ✅ (bodyweight) | ✅ |

**Verdict on Section 7:** the coarse-grained tags (bodyweight / dumbbells / barbell / full gym) work well. Fine-grained gate (bench required? cable required?) is NOT strict — the V2 resolver treats these as soft filters, not hard gates.

---

## SECTION 8 — HOME EQUIPMENT MATCHING RULES

| Rule | Implemented |
|---|---|
| 1. Bodyweight-only clients only receive bodyweight exercises | ✅ (fallback + V2 filter) |
| 2. Dumbbell-only clients do not receive barbell/cable/machine | ⚠ SOFT — resolver drops if no substitute; no HARD rejection |
| 3. Bench exercises require bench selected | ❌ MISSING |
| 4. Pull-up exercises require pull-up bar | ❌ MISSING |
| 5. Cable exercises require cable machine | ❌ MISSING |
| 6. Barbell exercises require barbell access | ⚠ SOFT (resolver filter, not strict) |
| 7. Squat rack exercises require squat rack | ❌ MISSING |
| 8. Treadmill sessions require treadmill only if indoor running specified | ❌ MISSING (fallback assumes outdoor + treadmill as alternative) |
| 9. Bike sessions require bike if cycling | ⚠ triathlon-only, no client-side toggle |
| 10. Recovery/mobility should not require unavailable equipment | ✅ (mobility templates are bodyweight) |
| 11. Substitutions respect available equipment | ⚠ soft — resolver tries but can DROP |
| 12. Regenerated workouts respect current equipment | ⚠ same as 11 |
| 13. Equipment changes trigger a review of future workouts | ❌ MISSING |

---

## SECTION 9 — HOTEL WORKOUT PROCESS

**Brutal honesty:** CrewFit does NOT have a per-hotel workout system yet.

What exists:
- One field on the user profile: `profile.hotel_gyms` = `"always"|"often"|"sometimes"|"rare"|"never"` (a **frequency estimate**).
- The fallback maps this to a category: `hotel_gym_reliable` → hotel-style workouts, else bodyweight.
- Roster days classified as `layover` get the hotel/bodyweight equipment context.

What does NOT exist:
- No hotel-name capture during roster review.
- No per-city hotel database.
- No hotel_id, no hotel_confirmed, no per-hotel equipment.
- No hotel_gym_confidence per hotel.
- No saved hotel profile with previous usage.
- No confirmation flow "does this hotel have a gym / treadmill / dumbbells".
- No coach hotel review queue.
- Hotel data is NOT parsed from the roster (roster parsing extracts flight IDs, day types, times — not hotel names).

**Verdict:** Section 9-13 is CrewFit's biggest product gap.

---

## SECTION 10 — HOTEL VARIABLES

| Variable | Exists |
|---|---|
| is_layover | ⚠ derived from `day_type` string match — no boolean field |
| is_turnaround | ❌ MISSING (not modelled) |
| layover_city / layover_country | ❌ MISSING |
| hotel_name | ❌ MISSING |
| hotel_id | ❌ MISSING |
| hotel_confirmed | ❌ MISSING |
| hotel_gym_available | ❌ MISSING (only profile-level frequency) |
| hotel_gym_confidence | ❌ MISSING |
| hotel_equipment | ❌ MISSING |
| dumbbells_available / treadmill_available / bike_available / cable / bench / kettlebells / pool | ❌ MISSING |
| safe_outdoor_run / safe_outdoor_walk | ❌ MISSING |
| client_hotel_notes / coach_hotel_notes | ❌ MISSING |
| hotel_last_verified / hotel_verified_by / hotel_source / hotel_usage_count | ❌ MISSING |

**Every field in Section 10 is missing.** This is the single biggest opportunity for CrewFit to be different from every generic fitness app.

---

## SECTION 11 — LAYOVER VS TURNAROUND LOGIC

- Layover detection: `feature_workout_fallback._classify_day` checks `day_type` for the substring `"layover"` or `"hotel"` → returns `"layover"`.
- Turnaround detection: **not modelled**. A same-day return would currently be classified as `flight_light` or `home` depending on the roster string.
- Multi-sector: currently classified as `flight_light`.
- Positioning: not modelled.
- Rest day after layover: not modelled — no "yesterday was a layover" awareness beyond the same-day duty type.

Coach can edit any day in the roster review UI (added in the previous session), so any misclassification can be manually corrected. But the app is not automatically distinguishing turnaround vs layover.

---

## SECTION 12 — HOTEL WORKOUT DECISION TREE

**The full decision tree in Section 12 is NOT implemented.** Only step 1 (is-this-a-layover-day) exists.

---

## SECTION 13 — HOTEL SOLUTION RECOMMENDATIONS (proposal for next iteration)

For a beta-safe hotel system in ~2 days of work:

**A. Confirmation during roster review** — add a small "layover details" sub-flow when a layover day is confirmed:
- Hotel name (free text, optional)
- Gym available? (yes / no / unknown)
- Equipment chips (dumbbells / treadmill / bench / bike — 4 chips only)
- Safe outdoor run? (yes / no / unknown)
- Notes (optional)

**B. Saved hotel profiles** — new `hotels` collection keyed by `(city, name)`. First time populated by client; subsequent uploads at the same hotel autoload equipment + confidence label + last_verified timestamp.

**C. Safe default** — unknown hotel gym → bodyweight-safe session. Marathon prep goal: swap to a run outdoors if `safe_outdoor_run=true`, else move the key session to the next home day.

**D. Coach hotel review queue** — new coach To-Do task type `hotel_review_needed` when client says "no gym" or "unknown".

Not implemented yet — waiting for Louis' go.

---

## SECTION 14 — ROSTER BALANCE PROCESS

For each roster variable, current behaviour:

| Roster factor | Placement | Intensity | Session type | Recovery | Progression | Deload trigger | Louis override |
|---|---|---|---|---|---|---|---|
| Early starts | ⚠ not modelled explicitly | — | — | — | — | — | via day edit |
| Late finishes | ⚠ not modelled explicitly | — | — | — | — | — | via day edit |
| Night flights | ✅ (long-haul override → Flight Recovery Mobility) | ✅ | ✅ | ✅ | — | — | via day edit |
| Long haul | ✅ | ✅ | ✅ | ✅ | — | — | via day edit |
| Ultra long haul | ⚠ treated as long-haul | ⚠ | ⚠ | ⚠ | — | — | via day edit |
| Multi-sector | ⚠ treated as flight_light | ⚠ | ⚠ | ⚠ | — | — | via day edit |
| Standby | ✅ (Activation stub) | ✅ | ✅ | ✅ | — | — | via day edit |
| Layovers | partial (no hotel-specific behaviour) | ✅ | ✅ | ✅ | — | — | via day edit |
| Turnarounds | ⚠ not distinct | ⚠ | ⚠ | ⚠ | — | — | via day edit |
| Days off | ✅ (real training day) | ✅ | ✅ | — | — | — | via day edit |
| Annual leave | ✅ (excluded from training) | — | — | — | — | — | ✅ |
| Sickness | ✅ (excluded) | — | — | — | — | — | ✅ |
| Simulator / training days | ✅ (Light Activation stub) | ✅ | ✅ | ✅ | — | — | via day edit |
| Heavy duty blocks | partial (per-day) | partial | partial | partial | — | ❌ | via edits |
| Rest / recovery windows | partial (light padding slots) | ✅ | ✅ | ✅ | — | — | ✅ |
| Hotel gym availability | ⚠ frequency-only | ⚠ | ⚠ | — | — | — | ⚠ |
| Home / base days | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ |

**Deload triggered by high roster fatigue?** ❌ NOT AUTOMATIC. `phase.key='deload'` is decided by `week_index` in a fixed cycle (`_phase_for_week`), NOT by roster load or check-in fatigue. Louis can manually flip a client's phase.

---

## SECTION 15 — PROGRESSION SYSTEM

| Feature | Status | Where | Client sees | Coach sees |
|---|---|---|---|---|
| Programme phase | ✅ implemented | `programmes.phase` (foundation/build/peak/deload) | ✅ Programme Overview card | ✅ Programme Overview |
| Week index | ✅ | `programmes.week_index` | ✅ | ✅ |
| Progression model | partial | `_next_progression_note()` — per goal + phase static hint | ⚠ not surfaced client-side | ✅ (via `programmes.progression.next_progression`) |
| Target sessions per week | ✅ | `programmes.target_sessions_per_week` | ✅ | ✅ |
| Planned session types | ✅ | `programmes.weekly_shape_ideal` | partial | ✅ |
| Previous week comparison | ❌ | — | ❌ | ❌ |
| Completed workout history | ✅ | `workouts.completed=true` + `completed_at` | ✅ (checkmark) | ✅ (timeline) |
| Missed workout history | ✅ | derived (past date + not completed) | ✅ | ✅ |
| RPE history | partial (per-exercise) | `exercises[].rpe` | ⚠ not aggregated | ⚠ not aggregated |
| Load / reps history | ❌ (workout log field exists but no aggregation) | — | ❌ | ❌ |
| Running distance/duration history | ❌ | — | ❌ | ❌ |
| Long run progression | ⚠ programme phase drives it, but no automatic uplift on completion | — | — | — |
| Strength progression | ⚠ same (phase-driven, not completion-driven) | — | — | — |
| Conditioning / mobility progression | ⚠ same | — | — | — |
| Deload logic | ⚠ scheduled every 4th week by `_phase_for_week`, NOT reactive to fatigue | ✅ (`progression.deload_status`) | ✅ (DELOAD pill) | ✅ |
| Taper logic | ⚠ Claude prompt has taper rules, no automatic countdown from event date | — | partial | partial |
| Recovery week | ⚠ same as deload | ✅ | ✅ | ✅ |
| Progression notes | ✅ | `programmes.progression.next_progression` | ⚠ not shown client-side yet | ✅ |
| Coach approval of progression | partial | `programmes.coach_approved` | — | ✅ |
| Client-facing progress summary | partial (Programme Overview card) | Home | ✅ | — |

**Verdict on Section 15:** the *scaffolding* is fully there (phase, week_index, target, weekly_shape, progression block). The *feedback loop* — take completion data + check-in data and auto-adjust next week — is NOT wired.

---

## SECTION 16 — PROGRESSION BY GOAL

| Goal | Expected progression | Current app | Gap |
|---|---|---|---|
| Marathon / running event | Easy run duration ↑, long run ↑, quality introduced at build/peak, taper before event | Phase-driven only — long run duration is FIXED at 75min per generation. Client sees phase change (foundation → build) but not "your long run went 40 → 45 → 50 min" | Auto-increase long_run duration by 10% every fortnight if adherence ≥ 3/4 |
| Strength / muscle | Reps/load/sets ↑ over time, main movements repeat enough to measure | Same movements now repeat across weeks (Plan B), but no auto-increase in load/reps | Add "last performance" retrieval + auto RPE-based progression |
| Fat loss | Strength consistency, weekly conditioning ↑ if recovery allows | Phase-driven; no auto-increase | Add conditioning density progression |
| General fitness | Balanced ↑ in strength, conditioning, mobility | Phase-driven | Same as above |
| Health markers / aviation medical | Moderate sustainable ↑, aerobic base | Phase-driven, no automatic titration | Add gentle 5% weekly volume ramp |
| Return to training | Slow ramp, low starting volume, build confidence | `return_to_training` has target=2, foundation-only shapes | ✅ probably safe; no fatigue-triggered slowdown yet |

---

## SECTION 17 — PROGRESSION WHILE BALANCING ROSTER

For each example:

**Example 1:** Long run planned Saturday but roster shows long-haul duty Saturday.
- **Current behaviour:** the LLM prompt says "long runs preferably on home / off-duty days" and the fallback slides real training slots off long-haul days (they become Flight Recovery Mobility instead). So the long run WOULD move to the next home day. However, this happens at generation time — if the client's roster changes mid-week, the current plan does not auto-relocate.
- **Client sees:** the Programme Overview card shows the next key session. It does NOT yet explicitly say "moved from Saturday to Friday because of long-haul".

**Example 2:** Client misses two workouts due to night flights.
- **Current behaviour:** missed workouts count is stored in `progression.sessions_missed_this_week`. **No automatic action is taken.** The next week's plan is generated fresh (not from previous week).
- **Expected:** cram or slow — currently NEITHER happens automatically.

**Example 3:** Client completes all strength sessions easily.
- **Current behaviour:** completion data is stored but NOT fed back to next week's generation. Same sets/reps repeat.
- **Expected:** auto-uplift on RPE < target OR set count ↑ on next generation.

**Example 4:** Client reports poor sleep and soreness in check-in.
- **Current behaviour:** check-in is stored; a coach task fires. Programme itself is NOT auto-adjusted.
- **Expected:** insert a deload week or amber the next few days.

**Example 5:** Client has 4 days/wk target but only 2 safe windows.
- **Current behaviour:** the cap enforcer keeps ≤4 real sessions; remaining slots become Optional Recovery. Client would see 2 real + 5 recovery/optional. There is NO explicit copy explaining "your roster only allowed 2 real training days this week".
- **Expected:** UI copy in the Programme Overview card + coach task.

**Verdict on Section 17:** roster IS respected at generation time. Roster-adaptive progression (mid-week regen when things change) is NOT wired.

---

## SECTION 18 — CLIENT-FACING PROGRESSION

Client currently sees (post Plan C):
| Item | Shown |
|---|---|
| Current goal | ✅ (Programme Overview card "goal_label") |
| Current phase | ✅ (Programme Overview card "phase_label") |
| Week number | ✅ (Programme Overview card "Week N") |
| Weekly target | ✅ (metrics grid) |
| Completed sessions this week | ✅ |
| Missed sessions | partial (shown as "not completed" — no explicit "you missed" copy) |
| Next key session | ✅ (Programme Overview card pointer) |
| Progression focus | ✅ (focus_copy from goal matrix) |
| Last week vs this week | ❌ NOT SHOWN |
| Strength progression numbers | ❌ |
| Running progression numbers | ❌ |
| Consistency streak | ❌ |
| Deload / recovery explanation | partial (DELOAD pill; no expanded copy) |
| Why a session was moved | ❌ (moved sessions carry a rationale but not surfaced with a "moved" label) |
| Why intensity was reduced | ❌ |
| What they are building towards | partial (goal label only) |

The expected "Your Progress" card in Section 18 is **partial** — the top rows exist, the progression numbers do not.

---

## SECTION 19 — COACH-FACING PROGRESSION

Louis currently sees:
| Item | Shown |
|---|---|
| Programme timeline | ✅ (Plan C3 — Timeline tab) |
| Phase / week / target | ✅ (Programme Overview card) |
| Planned vs completed | ✅ (week_counts grid) |
| Missed sessions | ✅ |
| Adherence | derived (completed/planned) — not surfaced as a % headline |
| Progression changes | partial (`programmes.progression.next_progression` stored, shown as string) |
| Running volume progression | ❌ |
| Strength progression | ❌ |
| RPE trends | ❌ |
| Load / reps history | ❌ |
| Check-in trends | partial (Check-ins tab exists) |
| Roster adjustments | partial (change_log entries exist, no dedicated "adjustments" widget) |
| Coach notes | ✅ |
| Validation warnings | ✅ (NEEDS COACH REVIEW pill + Timeline validation_flag events) |
| Approve programme | ✅ |
| Regenerate workout / programme | ✅ (Plan C6 + C7) |
| Swap exercises | ✅ (Plan C5) |
| Lock key sessions | ✅ (existing lock endpoint) |
| Ability to pause progression | ❌ (no explicit "pause" toggle) |
| Ability to deload client | partial (manual phase flip on request) |

---

## SECTION 20 — PROGRESSION DATA MODEL

| Field | Exists | Location |
|---|---|---|
| programme_id | ✅ | programmes.id |
| programme_version | ✅ | programmes.version_number |
| goal_key | ✅ | programmes.goal_key |
| phase | ✅ | programmes.phase.{key,label} |
| week_index | ✅ | programmes.week_index |
| target_sessions_per_week | ✅ | programmes.target_sessions_per_week |
| planned_sessions | ✅ | programmes.progression.sessions_planned_this_week |
| completed_sessions | ✅ | programmes.progression.sessions_completed_this_week |
| missed_sessions | ✅ | programmes.progression.sessions_missed_this_week |
| adherence_percentage | ❌ derived on read | — |
| progression_model | partial | `_next_progression_note` returns static hint |
| progression_status | ❌ | — |
| next_progression | ✅ | programmes.progression.next_progression (string hint) |
| deload_status | ✅ | programmes.progression.deload_status |
| taper_status | ❌ | — |
| last_week_summary | ❌ | — |
| this_week_focus | partial | programmes.focus_copy |
| next_week_plan | ❌ | — |
| run_volume / long_run_duration | ❌ NOT AGGREGATED | — |
| strength_volume | ❌ | — |
| exercise_progression | ❌ | — |
| RPE (per exercise) | ✅ per exercise, not aggregated | workouts[].exercises[].rpe |
| client_feedback (check-in) | ✅ | checkins |
| coach_progression_notes | partial | coach_notes free text on client detail |
| roster_adjustment_reason | ❌ NOT captured as a distinct field | — |

---

## SECTION 21 — WORKOUT COMPLETENESS AND PROGRESSION

| Check | Status |
|---|---|
| Exercises have sets / reps / rest / RPE | ✅ (all four fields required) |
| Previous performance shown next to exercise | ❌ NOT surfaced |
| Suggested next progression on exercise | ❌ NOT surfaced |
| Running workouts have distance / duration / RPE | ✅ (duration + RPE); distance not modelled distinctly |
| Long runs progress sensibly | partial — phase-driven only |
| Strength repeats enough to measure progress | partial — Plan B introduced repeatable weekly shape, but exercise-level continuity across weeks is best-effort |
| 45-minute 1-exercise workouts prevented | ✅ (Plan A4 min-content validator flags them + coach review) |
| Session duration matches content | ✅ (Plan A4 flag) |
| Client can log performance | partial — workout completion recorded; per-set logs limited |
| Louis can see performance | partial — completed workouts appear in timeline; no per-exercise history dashboard |
| Louis can adjust future progression | ✅ (Plan C4 editor + C7 regen) |

**Can a 45-min workout with 1 exercise still ship?** Data flow: LLM proposes 5 exercises → resolver drops 3 unresolved → workout has 2 exercises + 45min → Plan A4 flag fires → `validation_status='incomplete_content'` + `needs_coach_review=true` → client sees "AWAITING COACH REVIEW" badge + Louis sees it in Programme Overview + Timeline. So it can technically still exist in the DB, but it is now VISIBLE, FLAGGED and ACTIONABLE by Louis.

---

## SECTION 22 — EXERCISE SELECTION AND V2 LIBRARY

| Criterion | Applied |
|---|---|
| Goal | ✅ (session_type per weekly_shape drives movement pattern) |
| Progression needs | partial (phase-driven, not exercise-level) |
| Movement pattern | ✅ (resolver filters by movement_pattern) |
| Equipment | ✅ (resolver filters by equipment_type overlap) |
| Hotel equipment | ⚠ frequency-based only |
| Injury notes | partial (LLM sees text, resolver has no injury-friendly tag filter automated) |
| Difficulty | ✅ (resolver considers) |
| Previous exercise history | ❌ NOT used |
| Approved/Live status | ✅ (resolver only returns Approved/Live) |
| Selects approved V2 IDs | ✅ (after resolver runs) |
| Invents free-text | ⚠ LLM may — resolver drops OR files a draft exercise request + coach task (Plan D1) |
| Creates exercise requests | ✅ (`create_exercise_request_if_missing`) |
| Creates To-Do tasks for new exercises | ✅ (Plan D1 hook — dedup + priority) |
| Avoids unapproved exercises client-side | ✅ (drop or substitute) |
| Avoids equipment mismatches | ⚠ soft |
| Supports progression via repeated exercises | partial — same weekly shape means same session types repeat, but exercise IDs across weeks are not deterministically re-used |

---

## SECTION 23 — PROGRAMME VALIDATION

11 validator rules in `feature_programme_quality.validate_programme`:

| Rule | Implemented | Fails as |
|---|---|---|
| No workouts | ✅ | error |
| Workout with no exercises AND no warmup | ✅ | error |
| Movement pattern imbalance | ✅ | warning |
| Setup-day gap (first workout > 3 days out) | ✅ | warning |
| Real sessions in next 7 days | ✅ | error |
| V2 missing exercise_id | ✅ | error |
| V2 substitute ratio > 30% | ✅ | warning |
| Incomplete content (45-min <3 ex) | ✅ Plan A4 | error |
| Weekly cap exceeded (>target+2) | ✅ Plan A3 | error |
| Endurance goal without running | ✅ Plan A/B | error |
| Template-source ratio > 50% | ✅ | warning |
| Repeated identical title (≥5) | ✅ | warning |

Not implemented:
- No progression phase → ❌ (programmes.phase is always set by generation, so this never fires)
- No programme_id → ❌ (impossible by construction)
- Workouts not linked to programme → ⚠ workouts don't carry programme_id directly (shared through roster_id)
- Coach instructions conflict → ❌
- Hotel equipment mismatch → ❌ (no hotel equipment field)
- Home equipment mismatch → ⚠ (relies on resolver drop, no distinct validator rule)

---

## SECTION 24 — CLIENT-FACING OUTPUT

| Screen | Data source | Status |
|---|---|---|
| Home | /workouts/week + /programme/current + /roster/current + prompts + jobs | ✅ |
| Today | Home + workout detail | ✅ |
| Next 7 Days | /workouts/week filtered next7 | ✅ (Plan C1 badges) |
| Calendar | /workouts/week + /roster/current | ✅ |
| Programme Overview card | /programme/current | ✅ (Plan C2) |
| Workout Detail | /workouts/{id} | ✅ |
| Guided Workout | workouts[].exercises + traffic light variants | ✅ |
| Manual Workout | workouts[].exercises | ✅ |
| Roster Review | /roster/current + parse jobs | ✅ |
| Hotel Details screen | ❌ MISSING |
| Equipment Needed | inferred per-workout; no dedicated screen | ⚠ |
| Why This Session | workouts[].rationale | ✅ |
| Why This Changed | ❌ MISSING |
| Weekly Focus | Programme Overview.focus_copy | ✅ |
| Current Phase | Programme Overview.phase_label | ✅ |
| Progression Summary | ❌ MISSING (numbers) |
| Deload / Recovery explanation | partial (DELOAD pill; no expanded card) |
| Plan Preparing | roster job progress stream | ✅ |
| Plan Failed | gen_jobs.status='failed' + banner | ✅ |
| Plan Needs Review | programmes.validation_status !== "ok" | ✅ Plan C2 |
| Starter Plan | when source=template | ⚠ shown as needs_coach_review, no "starter plan" copy label |
| Status badge (PLANNED/PENDING/READY) | workout.approved/coach_locked/needs_coach_review | ✅ Plan C1 |

---

## SECTION 25 — COACH-FACING OUTPUT

| View | Route | Status |
|---|---|---|
| Client list | /(coach)/clients.tsx | ✅ |
| Client overview | /coach/client/[id].tsx | ✅ |
| Training calendar | /coach/client/[id] Calendar tab | ✅ |
| Roster tab | /coach/client/[id] Roster tab | ✅ |
| Programme tab | /coach/client/[id] Programme tab + Programme Overview card | ✅ (Plan C3) |
| Workouts tab | /coach/client/[id] Workouts tab | ✅ |
| Timeline | /coach/client/[id] Timeline tab | ✅ (Plan C3) |
| Progression dashboard | ⚠ overview_card metrics only | partial |
| Exercise swaps | Coach Workout Editor swap sheet | ✅ (Plan C5) |
| Regenerate workout | Coach Workout Editor preset grid | ✅ (Plan C6) |
| Regenerate programme | PREVIEW & REGEN modal | ✅ (Plan C7) |
| Coach instructions | Programme tab / notes | partial |
| Validation errors | Programme Overview `needs_coach_review` + Timeline validation_flag | ✅ |
| Home equipment | Client detail profile | ✅ |
| Hotel equipment | ⚠ frequency only | partial |
| Hotel review queue | ❌ MISSING |
| To-Do list | /coach/exercise-content + coach dashboard tasks | partial |
| Exercise requests | /api/coach/exercise-reviews/list + counter | ✅ (Plan D1-3) |
| Client messages | messages tab | ✅ |
| Archive / delete | via admin lifecycle | ✅ |

---

## SECTION 26 — TO-DO / COACH TASK PROCESS

| Task | Implemented |
|---|---|
| Roster confirmation incomplete | ✅ (existing) |
| Low-confidence roster | partial (roster parse job flags) |
| Unknown duty | ⚠ soft — Louis sees the day but no dedicated task |
| Layover needs hotel details | ❌ |
| Hotel equipment unknown | ❌ |
| Hotel profile needs review | ❌ |
| Client says equipment unavailable | ❌ (would need a client trigger) |
| Programme failed | ✅ (gen_jobs.status='failed' surfaces) |
| Programme validation failed | ✅ (needs_coach_review + validation_errors) |
| Template fallback used | ✅ (source='template' + template-ratio warning) |
| Incomplete workout | ✅ (Plan A4 → validation_status='incomplete_content') |
| Too many sessions | ✅ (Plan A3 → error) |
| Goal mismatch (no run for marathon) | ✅ (Plan B4 → error) |
| Progression missing | ⚠ programme always has progression fields; no "progression stalled" task |
| Progression conflict | ❌ |
| Client not progressing | ❌ (no adherence trigger) |
| Poor adherence | ❌ (data available, no task) |
| Poor recovery check-in | partial (check-in creates a Louis task) |
| Home equipment mismatch | ❌ |
| Hotel equipment mismatch | ❌ |
| Exercise request | ✅ (Plan D1 — exercise_library_review) |
| Missing media | partial (task_type='exercise_media_needed' exists; no automatic creation on approval) |
| Coach instruction conflict | ❌ |
| Client deleted roster | ✅ (Plan D4 — roster_deleted task) |
| Replacement roster failed | ❌ |
| 48h no replacement | ✅ (Plan D ticker → roster_no_replacement task) |

---

## SECTION 27 — FAILURE PROCESS

| Failure | Client sees | Louis sees | Data saved | Retryable | Cleanup |
|---|---|---|---|---|---|
| Roster upload fails | Error banner on roster-upload | gen_jobs failure log | file + partial parse | manual retry | orphan cleared |
| Roster parse fails | 3-layer fallback (Gemini→Claude→user) so client rarely sees a hard fail | ✅ | ✅ | automatic | ✅ |
| Client exits roster review | draft roster sits in "pending_confirmation" | dashboard notification | ✅ | ✅ | manual |
| Client deletes roster | success receipt (Plan D4) | coach task | ✅ (audit log) | replacement upload | cascade cleanup |
| Client uploads wrong roster | can delete + reupload | audit trail | ✅ | ✅ | ✅ |
| Hotel unknown | ⚠ no explicit prompt yet | ❌ | ⚠ | — | — |
| Hotel gym wrong | no way for client to correct | ❌ | ⚠ | — | — |
| Client has no equipment | fallback goes bodyweight | ✅ | ✅ | — | — |
| Programme generation times out | Plan Preparing banner + retry after 3s (existing) | ✅ | partial | ✅ | ✅ |
| Provider budget exhausted | fallback fires → starter plan | ✅ (source=template task) | ✅ | ✅ | ✅ |
| Fallback template used | client sees needs_coach_review badges | ✅ | ✅ | ✅ | — |
| Programme validation fails | Programme Overview shows NEEDS COACH REVIEW | ✅ | ✅ | ✅ | — |
| Progression cannot be calculated | ⚠ silently defaults to phase="foundation" | ❌ | partial | — | — |
| Workouts are incomplete | AWAITING COACH REVIEW badges | ✅ | ✅ | ✅ | — |
| Workout has unavailable equipment | ⚠ resolver drops → Plan A4 min-content flag | ✅ | ✅ | — | — |
| Client misses workouts | listed in Overview | ✅ | ✅ | manual | — |
| Client reports fatigue | ⚠ check-in stored, no auto adjustment | ✅ | ✅ | — | — |
| Client gets no workouts | Plan Preparing → fallback fires | ✅ | ✅ | ✅ | ✅ |
| Client gets too many workouts | ⚠ prevented by Plan A3 cap | ✅ | ✅ | ✅ | ✅ |
| Coach dashboard misses a task | ⚠ reconciliation runs on dashboard load (Plan D2) | ✅ | ✅ | ✅ | ✅ |

---

## SECTION 28 — EXACT TEST CASE AUDIT

**Test 1 — Marathon Prep, 4 days/wk, treadmill + dumbbells:** ✅ verified in iter76 T3. Expected outcome achieved.

**Test 2 — Long run planned Saturday, long-haul Saturday:** ✅ at generation time (fallback slides real slots off long-haul days). ❌ mid-week roster change → not re-shuffled automatically.

**Test 3 — Client completes all sessions easily:** ❌ NO automatic progression uplift on next week. Louis would need to regenerate manually or edit sets.

**Test 4 — Client misses two workouts due to night flights:** ⚠ counts stored, plan NOT auto-adjusted. Louis needs to intervene (which they can via the editor).

**Test 5 — Client reports poor sleep and soreness:** ⚠ check-in stored + coach task fires. Programme itself NOT auto-adjusted.

**Test 6 — Bodyweight-only, general fitness:** ✅ fallback produces bodyweight strength. Progression through reps/tempo/density: ⚠ not currently modelled.

**Test 7 — Dumbbells-only, strength:** ✅ resolver returns dumbbell exercises. Repeatable movements ✅ (weekly shape repeats). Auto load/rep progression: ❌.

**Test 8 — Layover with unknown hotel gym:** ⚠ current default = bodyweight based on profile-level frequency. No client prompt to add hotel details.

**Test 9 — Confirmed hotel with treadmill + dumbbells:** ❌ NOT POSSIBLE currently (no per-hotel data model).

**Test 10 — Client changes home equipment after plan created:** ⚠ profile update endpoint works; future workouts are NOT auto-reviewed for equipment mismatch.

---

## SECTION 29 — CONFIDENCE SCORE (0-10)

| Area | Score | Justification |
|---|---|---|
| Data collection | 8 | All major fields captured; hotel/turnaround/roster-timing gaps |
| Data storage | 9 | Well-modelled; single source of truth for main goal + days |
| Consultation answers used | 8 | Post Plan A, all critical answers flow through |
| Roster parsing | 9 | 3-layer defensive parser + edit-any-day |
| Roster confirmation | 8 | Solid; no per-hotel step |
| Home equipment matching | 6 | Coarse tags work; fine-grained rules (bench/rack/cable) missing |
| Hotel equipment matching | 2 | Only frequency-level; no per-hotel data |
| Layover / turnaround handling | 4 | Layover partial; turnaround unmodelled |
| Programme generation | 8 | Marathon shape + cap + fallback all in place |
| Goal-specific programming | 8 | 12 goal shapes × 4 phases catalogued |
| Marathon prep programming | 8 | Verified in iter76 |
| Training availability enforcement | 9 | Hard cap + validator + labelled optional recovery |
| Roster-balanced progression | 5 | Roster respected at gen time; not mid-week reactive |
| Client-facing progression | 6 | Card shows goal/phase/week/target; no numbers |
| Coach-facing progression | 7 | Overview + timeline + editor; no strength/run history dashboard |
| Weekly structure | 9 | Deterministic per goal + phase |
| Workout completeness | 8 | Min-content validator + coach review flag |
| Exercise selection | 7 | V2 resolver + drop; no history-aware selection |
| V2 Library matching | 8 | Approved/Live only; equipment overlap |
| Validation | 8 | 11 rules; some rules for hotel/equipment missing |
| Coach visibility | 8 | Overview + Timeline + editor + regen preview |
| Client visibility | 7 | Programme Overview + status badges; no "why this changed" copy |
| Error handling | 8 | Fallback + typed statuses + coach tasks |
| Beta readiness (3-5 clients) | 7 | Ready if hotel gap is acceptable |
| Paid user readiness (50+) | 5 | Hotel gap + progression feedback loop must land first |

---

## SECTION 30 — TOP GAPS

### Gap 1: Hotel workout system entirely missing
- **Why it matters**: Pilots/cabin crew are on the road 40-60% of days. Hotel workouts ARE the product.
- **Where it happens**: no hotel data model.
- **Client impact**: hotel workouts default to a coarse category. Trust breaks the first time a client is in a hotel with no gym and gets a dumbbell plan.
- **Coach impact**: no hotel review queue.
- **Fix required**: Section 13 proposal (roster review hotel step + hotels collection + safe defaults + coach queue).
- **Estimated time**: 2 days.
- **Estimated credits**: ~medium.
- **Beta blocker**: no if you brief testers.
- **Paid blocker**: YES.

### Gap 2: No feedback loop from completion / check-in data to next week's plan
- **Why it matters**: Progression only visible via phase change every 4 weeks, not by actual improvement.
- **Where**: no post-generation callback consumes `workouts.completed` or `checkins` to reshape next week.
- **Client impact**: feels like the plan doesn't respond to how well/badly they did.
- **Coach impact**: Louis has to manually adjust every week.
- **Fix required**: nightly job that reads last-7-day completion + check-in + RPE aggregate, sets `progression_status`, produces coach recommendation for regen.
- **Estimated time**: 1.5 days.
- **Estimated credits**: low.
- **Beta blocker**: no (but eats coach hours).
- **Paid blocker**: MEDIUM.

### Gap 3: Per-exercise progression not tracked
- **Why it matters**: "Last week you did X kg for 8 reps, aim for 9 today" is the killer feature of every strength app.
- **Fix**: workout completion form captures per-exercise sets+reps+load+RPE; generator queries last N sessions of the same exercise_id.
- **Estimated time**: 1 day.
- **Beta blocker**: no.
- **Paid blocker**: HIGH for strength/muscle clients.

### Gap 4: Equipment strict-gate rules
- **Why**: bench/rack/cable-only exercises can slip through soft filters.
- **Fix**: hard `requires_equipment` rule on V2 exercise rows; validator rule "exercise references unavailable equipment".
- **Estimated time**: 0.5 day.
- **Beta blocker**: no (rare).
- **Paid blocker**: MEDIUM.

### Gap 5: Turnaround vs layover distinction
- **Why**: turnaround = no hotel gym; layover = maybe hotel gym.
- **Fix**: roster parser classifier + confirmation step.
- **Estimated time**: 0.5 day.
- **Beta blocker**: no.
- **Paid blocker**: MEDIUM.

### Gap 6: Client-visible progression numbers
- **Why**: "you did 40 → 45 min long run" is more motivating than "Week 3".
- **Fix**: aggregate query + card additions to Programme Overview.
- **Estimated time**: 0.5 day.
- **Beta blocker**: no.
- **Paid blocker**: MEDIUM.

---

## SECTION 31 — FINAL VERDICT

1. **Can I trust the app to use consultation answers?** ALMOST — post Plan A, primary answers flow. Roster/sleep struggle free-text still only seen by the LLM.
2. **Can I trust it to respect training days per week?** YES — Plan A3 hard cap + validator.
3. **Can I trust it to match selected home equipment?** PARTIAL — coarse tags yes; fine-grained (bench/rack/cable) no.
4. **Can I trust hotel workouts to match actual hotel equipment?** NO — no per-hotel data.
5. **Can I trust unknown hotel gyms to default safely?** ALMOST — profile-level frequency yields bodyweight, but no client prompt to correct.
6. **Can I trust marathon prep clients to get running sessions?** YES — Plan B1/B2 verified.
7. **Can I trust clients will progress over time?** PARTIAL — phase-driven only, not adherence-driven.
8. **Can I trust progression to balance around roster demands?** PARTIAL — at generation time yes; mid-week reactive no.
9. **Can clients clearly see they are progressing?** PARTIAL — Programme Overview shows phase + week; no numbers.
10. **Can Louis clearly see progression and make changes?** YES for changes; PARTIAL for progression viz.
11. **Can Louis swap exercises, regenerate workouts and control?** YES — Plan C4/C5/C6/C7.
12. **Can I trust workouts to be complete?** YES — Plan A4 catches under-populated workouts and flags them.
13. **Can I trust the app not to create random sessions?** YES for goal alignment + weekly shape; template-source ratio validator catches fallback-heavy plans.
14. **Beta test with 3-5 clients?** YES (with a "hotels TBD" caveat).
15. **Beta test with 20-50 clients?** ALMOST — need Gap 1 (hotels) closed first.
16. **Ready for paid clients?** NO — Gaps 1 + 2 + 3 must land.

---

## SECTION 32 — EXACT FIX PLAN

### A. Must fix before any more beta testing (P0 — 1 day)
- **A1** — Warn client + coach when the plan is auto-limited by roster (e.g. "your roster only allowed 2 real training days this week"). Files: `feature_programme_quality`, `app/(client)/home.tsx`. ~2h. Risk if skipped: client thinks plan is broken.

### B. Must fix before 3-5 real beta clients (P1 — 3 days)
- **B1** — Hotel confirmation step in roster review (name + gym yes/no/unknown + 4 equipment chips + safe-outdoor-run flag). Files: NEW `feature_hotels.py`, `app/roster/confirm.tsx`. ~1 day.
- **B2** — Client-visible progression numbers card (long run min this week vs 2 weeks ago; strength volume delta). Files: `app/(client)/home.tsx` + new `/api/programme/progression-history`. ~0.5 day.
- **B3** — Coach hotel review queue + counter. ~0.5 day.
- **B4** — Client "swap this to a run outdoors" quick action for unknown hotel days. ~0.5 day.

### C. Must fix before 20-50 beta clients (P2 — 4 days)
- **C1** — Nightly progression job that reads completion + check-in and produces a coach recommendation. ~1.5 days.
- **C2** — Per-exercise strength history (last-set retrieval + auto RPE-based progression). ~1 day.
- **C3** — Turnaround vs layover distinction in the roster classifier. ~0.5 day.
- **C4** — Hard equipment-gate rules + validator (bench/rack/cable required). ~0.5 day.

### D. Must fix before paid clients (P3 — 3 days)
- **D1** — Saved hotel profiles (crowd-sourced across the client base). ~1 day.
- **D2** — Automatic taper before an event date. ~0.5 day.
- **D3** — Automatic deload trigger on 2+ weeks of poor adherence or fatigue. ~0.5 day.
- **D4** — Client-visible "why this changed" copy on any session that got moved / regenerated. ~0.5 day.
- **D5** — Programme Health tile on coach dashboard (template % / validation-fail % / substitute %). ~0.5 day.

### E. Can wait until later
- Route-specific micro-goals (jet-lag protocols, night-flight pre-conditioning).
- Multi-goal fluidity (e.g. marathon + strength blend across a year).
- Adaptive session duration based on client-reported time available today.
- Public-facing testimonials / referral system.

---

## Bottom line

CrewFit's programme generation is **structurally sound** after Plans A + B + C + D:
- goal + days + phase + weekly shape + validation + coach controls all work.
- 110 pytest cases green.
- Louis' original "7 generic Full Body Strength cards for a marathon client" bug is architecturally impossible now — the cap, min-content, endurance-run and template-ratio rules would all fire.

What is missing is:
- **hotels** (the biggest CrewFit differentiator gap),
- **adaptive progression** (react to what actually happened last week),
- **per-exercise history** (strength progression numbers).

**Trust score for beta with 3-5 pilots you can brief personally**: 7/10.
**Trust score for open beta at 20-50**: 5/10 until hotels + progression feedback land.
**Trust score for paid**: 4/10 until the top 3 gaps are closed.

End of report.
