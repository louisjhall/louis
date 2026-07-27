# PIETRO V2 GENERATION TRACE — human-readable

**Client**: Pietro Sangermano · `pietrosangermano1992@hotmail.com` · id `cbca8b09-1734-4442-9a55-1bb2f78f35c3`
**Generated**: 27 Jul 2026 (kickoff run)  ·  Machine-readable trace: `/app/memory/PIETRO_V2_GENERATION_TRACE.json`

## Headline numbers
| | |
|---|---|
| Goal in DNA | `main_goal="Marathon"` + `primary_goal_id="marathon"` |
| Event in DNA | Marathon on **2027-01-17**, priority A |
| Programme end V2 chose | **2026-09-20** ← WRONG (12 weeks, should be 25 weeks) |
| Objectives created | 15 |
| Assignments created | 21 |
| Implementations created | 18 (17 of them have **0 exercises**) |
| Assignments with NO impl | 3 |
| Schedule days with opportunity=100 | **62 of 62** — including 20 layover/turnaround days |
| Restrictions rows | 0 (never populated) |
| Equipment contexts rows | 0 (never populated) |
| Progression signals rows | 0 |
| Coach directives | 0 |

## DNA → V2 field audit
See `dna_field_audit` in the JSON trace. Summary:
* **USED**: goal (main_goal / primary_goal_id / event_type_pref), events row (event_date drives programme end)
* **LOADED BUT IGNORED**: training_days_per_week, max_home_minutes, equipment (printed in rationale but never gates P5/P6), injuries, home_base, airline
* **NEVER LOADED**: age, sex, height_cm, weight_kg, flying_type, assessments answers
* **MISSING FROM DNA SCHEMA**: preferred_training_days, sessions_per_week_min/max — no field exists to store client's desired frequency, so V2 can only guess from `training_days_per_week`
* **COLLECTIONS EMPTY (dead pipelines)**: restrictions, equipment_contexts, progression_signals, coach_directives

## Goal & phase resolution
* Kickoff correctly resolved `running.marathon` from `profile.primary_goal_id`.
* Programme created with `timeline_class="developmental"` (correct).
* **Programme end incorrectly clamped to 2026-09-20** despite event on 2027-01-17. Root cause suspected: an earlier kickoff run used the fallback `standard_prep_weeks=12` because a prior seeded event was in the past OR because `_ensure_programme` returned the existing programme without recomputing end_date. Force-re-run needed to verify.
* Phases created: foundation 1w · aerobic_base 2w · build 2w · specific_prep 1w · taper 1w · race_week 1w — total 8w. **Too compressed for a marathon 25w out.**

## Duty burden / training opportunity — the biggest defect
Every one of Pietro's 62 schedule days scored **opportunity = 100**, including:
* 20 layover_arrival / layover_departure / turnaround days
* All standby days
* All home days

The `_training_opportunity(day, burden_score)` helper in `feature_v2_p4_roster.py` returns a flat 100 whenever `roster_duties` is empty for that day. Because the parser stores duties into the roster's `days[].duties` sub-array (not the separate `roster_duties` collection), the V2 bridge inserts **0 duty rows** for Pietro. Result: burden score is always low → opportunity always 100 → scheduler treats every day as equally trainable.

This is the "why does the planner think a layover arrival is high-opportunity" question. Answer: the burden engine never sees the actual duty; it only sees the categorical `day_type`. Time zones, sector length, prior duty, next duty, and layover destination are **not connected**.

## Workout construction — where "Exercises (0)" comes from
* **CASE B** confirmed. Implementations exist (18) with `title`, `focus`, `duration_min` populated — but the `exercises` array is empty for 17 of 18 (only strength_support impl has any exercises).
* Running assignments don't produce a `blocks` array either (warm-up / interval / tempo / cool-down structure) — the impl doc simply has no sport-specific content.
* This means P6's slot templates only cover generic strength workouts. Running / cycling / swim / mobility have no template registered, so P6 silently returns an empty implementation.
* Drawer showing "EXERCISES (0)" is a faithful render of the DB. Not a UI bug.

**Additional defect**: 3 assignments have no implementation at all — P6 skipped them completely. Yet the workspace shows those rows as green/ready. No `status="building"` intermediate state is emitted.

## READY status integrity
An assignment becomes "ready" the moment P5 writes it, regardless of whether:
* P6 has built an implementation
* The implementation has any exercises/blocks
* Validation has run

The user's observation is correct: **the pipeline can show rows as READY before Validating completes**. Coach can hit "Approve 5 Ready" and publish an empty workout to a client.

## Fallbacks in effect for Pietro
| Fallback | Silent? | Impact |
|---|---|---|
| No `roster_duties` rows → burden score defaults to 0 | YES | opportunity=100 across the board |
| No `equipment_contexts` → P6 uses slot-template default | YES | Impl says "band, mat, bodyweight" even though Pietro has dumbbells + treadmill |
| No `restrictions` → injury data ignored | YES | Pietro's `injuries="None"` is irrelevant, but architecture wouldn't gate anyway |
| No running slot template → empty exercises | YES | 17 empty impls |
| No progression signal → assume exposure #1 | YES | All sessions look like "first exposure" — no volume ramp |
| `training_days_per_week` unused → P5 schedules on every high-opportunity day | YES | Pietro said 5/wk; system will schedule more if roster is light |
| Programme end derived from `standard_prep_weeks` when event query races → 12w window | YES | Marathon plan compressed to 8w visible in DB |

## Decision records
45 records exist. Layer breakdown: WHY (5), WHAT (16), WHEN (17), HOW (7), ORCHESTRATION (0). Reasons ARE populated ("Key long_run placed on 2026-07-30 (light burden · opportunity 100). Exposure #1 of objective.") but the drawer queries by `assignment_id` only — it will not find WHAT records (scope_kind=objective) or ORCHESTRATION records (scope_kind=programme). So the coach sees an empty "Why this?" panel.

## Answer to "is V2 currently capable of generating a programme we can safely approve?"
**NO.**

Concrete blockers (all P0):
1. Every day scores opportunity=100 — scheduler has no signal to protect layover/turnaround/standby recovery
2. 81 % of implementations have zero exercises — approving them ships empty workouts to the client
3. READY does not require an implementation, let alone valid content
4. Programme end anchored to an incorrect date so phases are compressed
5. Equipment/injury/frequency preferences never gate output
