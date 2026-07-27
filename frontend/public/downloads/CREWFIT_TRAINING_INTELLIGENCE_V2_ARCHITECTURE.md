# CrewFit Training Intelligence V2 — Architecture

**Companion documents**
- `CREWFIT_TRAINING_INTELLIGENCE_V2_SCHEMA.md` — canonical data model
- `CREWFIT_TRAINING_INTELLIGENCE_V2_RULE_ENGINE.md` — deterministic logic
- `CREWFIT_TRAINING_INTELLIGENCE_V2_COACH_UX.md` — coach workspace
- `CREWFIT_TRAINING_INTELLIGENCE_V2_CLIENT_UX.md` — client screens
- `CREWFIT_TRAINING_INTELLIGENCE_V2_MIGRATION.md` — V1→V2 sequencing

**Prerequisite:** `/app/memory/CREWFIT_TRAINING_INTELLIGENCE_CURRENT_ARCHITECTURE.md` (V1 audit).

---

## 1. Product principle (immutable)

> **AI plans. Rules protect quality. Coach reviews exceptions. Coach approves LIVE.**

No AI-authored change ever reaches the client's LIVE plan without a coach approval or a policy-defined safe-adaptation boundary (see §11 Publishing Contract).

---

## 2. Three architectural layers (WHAT / WHEN / HOW)

CrewFit V2 replaces the V1 "one big prompt per week" pattern with three independent layers:

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1 — TRAINING DEMAND ENGINE   ("WHAT does the client need?") │
│  Input:  goals, phases, event, timeline, history, progression      │
│  Output: TrainingObjective + ObjectiveExposure records            │
│  Nature: DETERMINISTIC, ROSTER-BLIND                              │
└────────────────────────────────┬────────────────────────────┘
                                 ↓
┌─────────────────────────────────────────────────────────────┐
│  LAYER 2 — SCHEDULING INTELLIGENCE  ("WHEN can they do it?")     │
│  Input:  roster, readiness, opportunity scores, precedence       │
│  Output: WorkoutAssignment (objective bound to date)             │
│  Nature: DETERMINISTIC RANKING + optional AI polish              │
└────────────────────────────────┬────────────────────────────┘
                                 ↓
┌─────────────────────────────────────────────────────────────┐
│  LAYER 3 — WORKOUT CONSTRUCTION  ("HOW do they execute today?")  │
│  Input:  assignment, equipment context, duration, readiness      │
│  Output: WorkoutImplementation (concrete exercises + prescriptions)│
│  Nature: STRUCTURED SLOTS + AI for personalisation/copy          │
└─────────────────────────────────────────────────────────────┘
```

**Consequence — the layer contract:**
- A **HOW change** (equipment swap) → new `WorkoutImplementation` only; same `ObjectiveExposure`, same progression counter.
- A **WHEN change** (duty added tomorrow) → move `WorkoutAssignment`; same `ObjectiveExposure`, same identity, same progression counter.
- A **WHAT change** (goal shift, injury cancels an objective) → new `TrainingObjective` graph, cascades downward.

This alone eliminates the V1 problem where "Lower Strength Exposure 4" becomes an unrelated random workout after any change.

---

## 3. Programming hierarchy (the object graph)

```
Client
  └─ Goal (ordered list, primary + secondaries with weights)
       └─ Timeline (developmental / standard / compressed / high-risk)
       └─ Event (0..n; A/B/C priority)
       └─ Programme (macrocycle spanning goal lifetime)
            └─ ProgrammePhase (Foundation / Build / … / Taper / Race Week …)
                 └─ PhaseObjectives (what this phase must accomplish)
                      └─ TrainingObjective (Upper Strength, Long Run, …)
                           └─ ObjectiveExposure (Exposure #4 of Upper Strength)
                                └─ WorkoutAssignment (bound to a ScheduleDay)
                                     └─ WorkoutImplementation (equipment-specific)
                                          └─ ExercisePrescription (per set/rep/rest)
                                               └─ PerformanceRecord (client-logged)
                                                    └─ ProgressionState (feeds forward)
```

Scheduling operates on **ObjectiveExposure ⇄ ScheduleDay** links.
Everything above `WorkoutAssignment` is roster-blind.

---

## 4. Planning windows (not Mon–Sun)

**Planning window** = the smallest unit that carries training objective targets.

Three window types, chosen per goal type:

| Window type | Length | Used for | Advance trigger |
|---|---|---|---|
| **Rolling 7-day** | 7 days floating anchor | Body-comp, general fitness, aviation consistency | Rolls one day forward daily; recomputes weekly targets vs completed |
| **ISO week** | Mon–Sun | Return-to-training, health markers | ISO Monday |
| **Race microcycle** | 7/10/14/21/7 days depending on phase | Event goals | Anchored to race date; phase boundaries trigger new cycles |

**Key rule:** targets are `{objective, count_required, priority, deadline}` per window — not "Tuesday = Upper".

Coach still sees calendar month/week visually; the underlying model tracks *targets vs completions* in the window regardless of which weekday things landed on.

---

## 5. Goal architecture (extensible taxonomy)

Every goal in the system carries a **GoalDefinition** (see Schema doc). New goals plug in by writing the definition, not by writing a new generator.

**Categories** (extensible root list):
- `body_composition` — {fat_loss, muscle_gain, recomposition, maintenance}
- `strength` — {general_strength, max_strength, strength_endurance}
- `general_fitness` — {general_fitness, aerobic_fitness, work_capacity, health_longevity}
- `hybrid` — {strength_endurance_hybrid, general_hybrid}
- `running` — {general_running, 5k, 10k, half_marathon, marathon, ultra, custom_distance}
- `cycling` — {general_cycling, endurance_event, custom}
- `swimming` — {general_swimming, distance_target, open_water}
- `triathlon` — {sprint, olympic, 70_3, ironman, custom}
- `movement_recovery` — {mobility, return_to_training, movement_capacity}

**Every goal_id defines** (schema in `RULE_ENGINE` doc):
```
priority_adaptations: [strength, hypertrophy, aerobic_base, threshold, mobility, …]
frequency_range: {min:2, max:6}
volume_curve: linear | undulating | block | race-anchored
intensity_curve: same enum
key_stimuli: [ordered TrainingObjective ids]
required_disciplines: [strength, run, bike, swim, mobility]
progression_model: linear_load | double_progression | polarised | race_km_curve | …
compatible_phase_sequence: [ordered phase_ids]
recovery_requirements: {min_hours_between_key: 48, min_easy_days_after_key: 1}
conflict_map: [{other_goal_id, conflict_severity, mitigation}]
```

This is deterministic scaffolding. AI **personalises implementation** (exercise selection, coaching cues) but **never invents the programming model**.

---

## 6. Primary + secondary goals

Each client has:
```
goals: [
  {goal_id: "marathon",        priority: "A", weight: 0.7, target_date: 2026-11-08},
  {goal_id: "general_strength", priority: "B", weight: 0.3, target_date: null}
]
```

**Weight semantics** — weight influences how the training-demand engine allocates weekly exposure counts. A 0.7/0.3 marathon/strength split with 4 sessions/wk → 3 running slots + 1 strength slot. A 0.5/0.5 muscle-gain + 10k split with 5 sessions/wk → 3 strength + 2 running with interference rules applied.

**Interference rules** live in `RULE_ENGINE`. Two primary conflict flavours:
- *Molecular* — heavy leg strength ≤ 24h before long run
- *Volume* — total weekly load exceeds phase-appropriate cap for goal

---

## 7. Goal conflict engine

For every ordered pair `(primary_goal, secondary_goal)` the `conflict_map` returns:

| Class | Meaning | Action |
|---|---|---|
| `compatible` | Complementary | No warning |
| `manageable` | Interference exists; rules mitigate | Apply mitigation rules; no coach flag |
| `competing` | Both viable but expected trade-offs | Show coach one-time explanation |
| `strongly_conflicting` | Meaningful compromise inevitable | Require coach acknowledgement |
| `unrealistic_within_timeline` | Cannot both be achieved | Block save until coach chooses which to demote |

Examples the engine ships with:
- `marathon + max_strength` → `strongly_conflicting`
- `fat_loss + performance_event` → `competing` with "prioritise fuelling in race week" mitigation
- `muscle_gain + marathon` → `competing`
- `muscle_gain + 10k` → `manageable`
- `return_to_training + aggressive_event` → `unrealistic_within_timeline`

---

## 8. Timeline engine

For any goal with a `target_date` the engine classifies:

```
if weeks_to_target >= ideal_prep_weeks(goal):        DEVELOPMENTAL
elif weeks_to_target >= ideal_prep_weeks * 0.7:      STANDARD
elif weeks_to_target >= ideal_prep_weeks * 0.4:      COMPRESSED
else:                                                HIGH_RISK / UNREALISTIC
```

`ideal_prep_weeks` per goal in `RULE_ENGINE`. Examples:
- marathon → 16 weeks ideal, 12 standard, 8 compressed floor
- half_marathon → 12 / 10 / 6
- 70.3 → 20 / 16 / 12
- Ironman → 32 / 24 / 16
- max_strength → 16 / 12 / 8
- muscle_gain → 12 (per phase block)
- fat_loss → open-ended (no timeline requirement)

`HIGH_RISK` → conflict engine surfaces coach warning. Programme still generates, but flagged.

---

## 9. Event engine

Events are structured, not free text. Every event carries:
```
event_id, client_id
event_type (from goal taxonomy — e.g. marathon, 70_3, custom)
category (race | medical | aviation_work | sport_hobby | personal)
priority (A | B | C)
date (YYYY-MM-DD), time (HH:MM optional)
distance / duration / target
current_performance
required_disciplines: [run, bike, swim, strength, mobility]
notes
```

Multiple events supported. **Only A events dominate periodisation.** B events adjust weekly targets. C events are training-day markers.

**Multi-event conflict** — if two A events within 8 weeks of each other, engine forces one to demote to B or reject one.

---

## 10. Event countdown (deterministic — never LLM)

At every plan pass:
```python
days_to_event = (event.date - today).days
weeks_to_event = days_to_event / 7

phase = _phase_from_weeks_to_event(event_type, weeks_to_event)
long_target = _long_target_for_week(event_type, weeks_to_event, is_cutback_week)
weekly_volume_target = _weekly_volume(event_type, weeks_to_event)
taper_active = (0 < days_to_event <= taper_days_for(event_type))
race_week = (0 < days_to_event <= 7)
post_race_recovery = (-14 <= days_to_event < 0)
```

Every downstream layer reads these — never re-derives them.

---

## 11. Publishing contract — DRAFT vs LIVE

The single most important architectural change.

```
┌─────────────┐   coach approve   ┌─────────────┐
│    DRAFT    │ ──────────────>   │    LIVE     │
│  (private)  │                    │  (client)   │
│             │ <──────────────    │             │
│             │   coach edits      │             │
└─────────────┘                    └─────────────┘
     ↑                                    ↑
     │                                    │
    AI writes here freely            Only via approval
     │                                    │
    Client change flow             Coach direct edit
    within Safe-Adaptation         (always LIVE, timestamped)
    Boundary → LIVE               
```

### 11.1 Safe-Adaptation Boundary (SAB)

A named policy attached to every `WorkoutAssignment` when it goes LIVE. It defines what the client's app can change *without* requiring coach approval. Coach sets this per client (defaults per goal).

Default SAB:
```
allow_equipment_swap: true            # HOW change
allow_duration_reduce_pct: 40         # up to −40%
allow_convert_to_recovery: true       # if readiness or reality dictates
allow_convert_to_mobility: true
allow_skip: false                     # requires coach directive
allow_move_within_planning_window: true  # WHEN change within window
allow_move_across_windows: false      # requires DRAFT change
allow_substitute_exercise_from_approved_pool: true
key_session_hardened: true            # key sessions can only be reduced by 20%
```

Anything **outside** the boundary automatically creates a DRAFT `ChangeSet` for coach review. The client still sees the adapted session in LIVE, but the coach gets a "Ready to Review" flag.

### 11.2 Approval scopes

Coach can approve:
- one workout · one day · a set of dates · a planning window · a phase · a whole programme
- "APPROVE ALL 27 READY ITEMS" batch
- "APPROVE — hold exceptions" (surfaces the 3 flagged items only)

### 11.3 Versioning

Every publish creates a `PlanVersion`. Previous LIVE versions kept intact forever. `plan_versions[]` on `Programme` doc; each carries `plan_snapshot_id → plan_snapshots` (immutable copy of the LIVE state at that moment).

---

## 12. Roster + duty (structured, not string-typed)

V1 uses free-text `day_type` (17 labels). V2 uses **structured facets** so the same day can be simultaneously a Layover Full Day AND host a training opportunity AND carry a duty-burden score.

```
ScheduleDay
├─ date
├─ duty[]:                     # 0..n RosterDuty records per day
│   ├─ duty_type: enum         # flight | standby | sim | training | positioning | leave | rest | off
│   ├─ report_time
│   ├─ duty_start_time
│   ├─ duty_finish_time_local
│   ├─ sectors[]: FlightSector[]
│   ├─ standby_type (if applicable)
│   ├─ standby_location, window_start, window_end
│   ├─ crossed_midnight (bool)
│   └─ overnight_at (city/IATA — if duty ends away from base)
├─ home_or_away
├─ tz_offset_from_base_hours
├─ recovery_window_hours (to next duty)
├─ derived.duty_burden_score      # 0..100 deterministic
├─ derived.training_opportunity   # 0..100 deterministic (see §14)
├─ derived.recommended_intensity_ceiling  # RPE ceiling
├─ derived.available_time_min
└─ derived.classification         # {rest, layover, turnaround, standby, home, other}
```

Legacy V1 labels are still emitted for coach display but are **derived**, not primary.

---

## 13. Duty-burden score (deterministic)

```
score = 0
if report_time < 05:00:      score += 20
if finish_time > 23:00:      score += 15
if crossed_midnight:         score += 20
if flight_duration >= 12h:   score += 25
elif flight_duration >= 8h:  score += 15
if sectors >= 4:             score += 15
elif sectors == 3:           score += 8
tz_shift = abs(dest_tz_hours - base_tz_hours)
score += min(20, tz_shift * 2)
if consecutive_duty_days >= 4: score += 15
elif consecutive_duty_days == 3: score += 8
if recovery_window_hours_to_prior_duty < 12: score += 15
score = min(100, score)
```

**Bands:**
- 0-25 → light
- 26-50 → moderate
- 51-75 → heavy
- 76-100 → extreme

Downstream engines read the band, not the raw score, so bands can be re-tuned without breaking rules.

---

## 14. Training-opportunity score

For each ScheduleDay:
```
opp = 100
opp -= 0.6 * duty_burden_score
opp -= 25 if recovery_window_hours < 18 else 0
opp += 20 if home_or_away == "home" else 0
opp += 15 if classification == "layover" and duty_burden_score < 50 else 0
opp += 10 if available_time_min >= 60 else 0
opp -= 30 if readiness_band == "recover_priority" else 0
opp -= 15 if next_day_high_burden else 0
opp = clamp(0, 100)
```

Scheduling engine ranks dates by `opp` when placing important sessions. Key sessions (long_run, heavy strength) go into top-quartile opportunity days.

---

## 15. Roster upload — one flow, two entry points

**Same underlying model, different actors.** Client upload flow ✅ existed in V1. Coach upload flow was added Iter 109.

V2 unifies them:
```
Actor uploads file
  ↓
STAGE 1 — Extract  (5-15s wall clock)
    airline_parser?   → yes: parsers/etihad|emirates|...
                      → no:  Gemini ROSTER_SYSTEM (unchanged)
  ↓
STAGE 2 — Normalise                          (< 1s, deterministic)
    Produces ScheduleDay[] with structured duties
  ↓
STAGE 3 — Preview                            (immediate)
    User confirms/edits low-confidence days
  ↓
STAGE 4 — Confirm                            (immediate DB write)
    ScheduleDay[] committed, existing overlapping days superseded
  ↓
STAGE 5 — Draft generation                   (background, event-driven)
    Fires the WHAT → WHEN → HOW pipeline (§16-18)
    Coach sees "Draft Ready" typically < 60s after confirm
```

Only Stage 5 is async. Client sees a live "planning" indicator; coach dashboard shows "Draft building".

Preview UI never blocks on Stage 5. Coach + client can already see the roster days while the plan is composing.

---

## 16. Fast generation pipeline (Stage 5 expanded)

Replaces V1's monolithic `_generate_month`. Uses **incremental composition** — never rebuild everything.

```
Trigger: RosterConfirmed | RosterChanged | GoalChanged | PhaseAdvanced | CoachDirective | ReadinessShift

Step A — DEMAND: TrainingObjective composer          (deterministic, <100ms)
    - Read Goal/Phase/Timeline/Event → compute PhaseObjectives
    - Emit/refresh ObjectiveExposure records for the affected windows
    - Uses adherence + progression state to advance sequences

Step B — SCHEDULE: Assignment planner                (deterministic, <500ms)
    - For each ObjectiveExposure in the target window, rank ScheduleDays by
      training_opportunity, subject to constraints (§20 precedence)
    - Emit WorkoutAssignment (objective_id + date + priority + boundaries)
    - Handles missed-session redistribution (§21)

Step C — IMPLEMENT: Workout constructor              (parallel, <20s each)
    For each Assignment:
      1. Determine EquipmentContext (default bodyweight if unknown)
      2. Structured slot template for objective × phase
      3. Filter exercises_v2 by eligibility (§18)
      4. Rank candidates (variety penalty, progression fit, coach exclusions)
      5. Select + build WorkoutImplementation
      6. AI polish pass (optional, cache-warm): coaching cues, rationale text
      7. Validate (§22)

Step D — VALIDATE + FLAG                              (deterministic)
    Emit Exceptions[] for coach review
    Everything else stamped READY

Step E — DIFF vs LIVE                                 (deterministic)
    ChangeSet built between current LIVE and new DRAFT
    Coach sees per-day badges: unchanged | new | modified | removed
```

**Key acceleration levers vs V1:**
- Step A is deterministic → 0 LLM calls for demand
- Step B is deterministic → 0 LLM calls for scheduling
- Step C fans out per-assignment with **workout templates keyed by (objective, phase, equipment)** — LLM only fills the polish layer, and results are **cached by template hash** so unchanged sessions never re-hit an LLM

**Target latency:** DRAFT visible to coach within 45 seconds of confirm for a 28-day roster. Individual workouts stream in as they complete.

---

## 17. Incremental replanning

Roster changes rarely need a full regenerate. V2 computes the **minimum affected window**:

```
On RosterChanged(dates_affected):
  1. Find ObjectiveExposures assigned to those dates → pool_A
  2. Find ObjectiveExposures whose current placement creates conflicts
     with new duty burden → pool_B
  3. Union pool_A + pool_B = pool_to_replan
  4. Determine impact window = [min_date-1, max_date+3] within active planning window
  5. Re-run Step B (schedule) for pool_to_replan
  6. Re-run Step C (implement) only for assignments whose date OR
     equipment_context changed
  7. Everything else remains unchanged and stays in LIVE (no diff)
```

**Concrete example:** Client's Tuesday flips from Home Day to unexpected duty. Only the Tue assignment + its rebound date (say, Thu) go through Step B/C. Mon/Wed/Fri/Sat/Sun are untouched.

---

## 18. Workout construction (structured, not prose)

V1 asks the LLM to invent a full workout. V2 gives the LLM a **filled slot template** and asks it only for polish.

### Slot templates per TrainingObjective × Phase

Example — `upper_strength × build`:
```
slots = [
  {role:"primary_horizontal_push", eq_pref:["barbell","dumbbells","bodyweight"], sets:4, reps:"6-8", rest_sec:120, rpe:7-8, key:true},
  {role:"primary_vertical_pull",   eq_pref:["pull_up_bar","cable","band"], sets:4, reps:"6-8", rest_sec:120, rpe:7-8, key:true},
  {role:"secondary_horizontal_pull", eq_pref:["dumbbells","cable","band"], sets:3, reps:"8-12", rest_sec:90, rpe:7},
  {role:"secondary_vertical_push", eq_pref:["dumbbells","barbell","bodyweight"], sets:3, reps:"8-12", rest_sec:90, rpe:7},
  {role:"accessory_isolation",     eq_pref:["dumbbells","cable","band","bodyweight"], sets:3, reps:"12-15", rest_sec:60, rpe:8},
  {role:"trunk",                    eq_pref:["bodyweight","medicine_ball","cable"], sets:3, reps:"30-45s or 10-15", rest_sec:45},
]
```

### Eligibility filter (deterministic pre-LLM)

For each slot, filter `exercises_v2` by:
```
1. exercise.status == "Live"
2. exercise.approval == "approved"
3. exercise.movement_pattern in slot.role_pattern_pool
4. exercise.equipment_type ⊆ available_equipment_context
5. exercise.movement_pattern not in client.avoid_movement_patterns
6. exercise.id not in coach.exclusions_for_client
7. exercise.difficulty_level compatible with client.experience_level
8. exercise not used in last N sessions (variety window per role — configurable)
```

### Selection ranking (deterministic)

Among eligible candidates, score by:
- progression fit (previous exposure of same exercise: +30)
- variety (last used >21 days: +10, never used: +5)
- key-session-hardened preference (compound > isolation for primary slots: +20)
- client dislikes (from coach_notes.preferences: −50)
- media completeness (has video: +5)

Top-N candidates handed to AI polish layer.

### AI polish layer

Given the pre-selected exercise list + slot metadata:
- Writes `client_facing_instructions` (short cue)
- Writes `rationale` for the workout ("Second upper exposure this window; using dumbbells because bench is set to zero at 22kg")
- Optionally proposes tempo/RPE notes
- **Never adds or removes exercises**

Cache key = hash(objective_id, phase, equipment_context, exercise_ids, client_id). Repeat hits skip the LLM.

---

## 19. Equipment context (no hotel database)

**We remove `hotels` collection dependency for scheduling.** The V1 shared-hotel model stays for coach-facing hotel notes only (see Migration doc), but the training engine no longer needs it.

`EquipmentContext` (schema in `SCHEMA.md`):
```
source:  profile | client_selected | coach_selected | reality_flow
scope:   permanent | date_range | today | this_session
equipment: [dumbbells, adjustable_bench, cable_stack, treadmill, floor_space, …]
detail:  {dumbbell_max_kg?: 22, notes?: "Smith machine present but not familiar"}
valid_from, valid_until
created_at, created_by
```

**Resolution order** when constructing a workout:
```
1. Session-scoped context (client just tapped I'M IN A GYM) — highest priority
2. Coach-scoped override for this date range
3. Reality-flow context (from Today's Reality)
4. Profile-permanent (home gym / regular commercial gym)
5. Default: BODYWEIGHT
```

Sessions never assume equipment from location. Nothing is inferred from "you're in Dubai".

---

## 20. Precedence engine (deterministic order)

Every conflicting decision resolves against this hierarchy — no LLM tiebreakers:

```
1. Safety hard constraints  (never violate)
     - Injury contraindications from coach_notes.cautions or persistent restrictions
     - Auto-populated pain_flags (< 14 days)
     - Parser-emitted training_colour == "black"

2. Coach locks
     - Locked exercise / workout / day / objective / period

3. Active coach directives
     - Structured directives with scope in effect for this date

4. Event-critical requirements
     - Key sessions in the race-week / taper window
     - Long run peak weeks

5. Programme objective requirements
     - Weekly exposure counts

6. Roster feasibility
     - duty_burden band caps
     - recovery_window minimums
     - parser action != "full_session"

7. Recovery / readiness state
     - auto_deload_trigger
     - motivation_flag == "low"
     - poor sleep trend

8. Primary goal preferences

9. Secondary goal preferences

10. Client preferences (favourite / disliked exercises)

11. AI optimisation (variety, elegance, cue quality)
```

Each rule declares its `precedence_tier` (1-11). When two rules touch the same decision, the lower-numbered tier wins. Rules at the same tier resolve deterministically by rule_id ordering.

**Nothing is decided by LLM tie-break.** LLM never sees rules with tier 1-7 as "suggestions" — it sees them as hard input parameters.

---

## 21. Missed-session engine

Every session has a `programme_importance`:
```
KEY         (race-critical, primary progression exposure)
IMPORTANT   (secondary progression, key movement exposure)
SUPPORTING  (auxiliary work)
OPTIONAL    (recovery walks, optional mobility)
```

On completion or window boundary:
```
For each missed session in the closing window:
  if importance == OPTIONAL:      drop, no cascade
  if importance == SUPPORTING:    attempt shift within window; drop if no slot
  if importance == IMPORTANT:     attempt shift within window; else compress with next same-objective session; else defer to next window with flag
  if importance == KEY:           MUST reschedule
       - if window still has capacity: place on best available opportunity day
       - if not: cascade — demote another IMPORTANT session
       - if still no fit: create Exception → coach review
```

Progression counter (`ObjectiveExposure.sequence`) never resets on miss — the sequence continues from wherever it got to.

---

## 22. Validation engine

Runs after Step C for every DRAFT workout. Every check is a rule with a `severity`:

```
Severity:
  auto_repair  — engine can fix in place
  flag_coach   — needs coach eye
  block        — cannot promote to READY

Checks (initial set):
  V1  Objective served                 severity: block
  V2  Sequence integrity               severity: auto_repair
  V3  Recovery gap ≥ min for objective severity: flag_coach
  V4  Duty fit                          severity: flag_coach
  V5  Equipment available               severity: auto_repair (fallback bodyweight)
  V6  All exercises approved            severity: auto_repair (swap to approved) or flag
  V7  Restriction respected             severity: block
  V8  Duration within tolerance         severity: auto_repair
  V9  Progression logical               severity: flag_coach
  V10 Event-critical session preserved  severity: flag_coach
  V11 Weekly volume ≤ cap for phase     severity: flag_coach
  V12 Key-session spacing (≥48h)        severity: flag_coach
  V13 No hard-lower within 24h post-ULR severity: block
```

Auto-repair actions are logged in `DecisionRecord` so coach can see what was auto-fixed and why.

Only `block` severity prevents READY status. `flag_coach` still READYs but appears in the Exception list.

---

## 23. Coach dashboard = the control centre

Design deeply covered in `V2_COACH_UX.md`. Summary:

Every client has one top-level page: **ROSTER + PLAN**.

```
┌─────────────────────────────────────────────────────────────┐
│ Client: Louis Hall · Marathon (A) in 12 weeks · Phase: Build │
│ ▸ 27 Ready · 2 Need Review · 1 Conflict · 3 Coach Edited      │
│                                                                │
│ Command bar: [Tell CrewFit what to change...              ]   │
│ [ APPROVE 27 READY ]  [ Review 3 ]                             │
├─────────────────────────────────────────────────────────────┤
│ ROSTER (real life)                CREWFIT PLAN (DRAFT)         │
│ Mon 3 Aug  Home Day               Upper Strength · 45m · Home  │
│                                    Exposure #4 · Build wk 3    │
│ Tue 4 Aug  LHR→JFK · 07:00–16:30   Post-Flight Mobility · 15m  │
│            Duty 9.5h · Heavy       ⚠ Recovery-first day        │
│ Wed 5 Aug  JFK Layover             Lower Strength · 40m · Hotel│
│            32h free                Exposure #4 · Build wk 3    │
│ Thu 6 Aug  JFK→LHR Overnight       ULR Recovery · 25m          │
│            Duty 14h · Extreme      ⚠ Deferred long run         │
│ Fri 7 Aug  Home Day                Long Run · 22km · Outdoor   │
│                                    KEY SESSION · Marathon wk 3 │
└─────────────────────────────────────────────────────────────┘
```

Every row is one-tap actionable:
- Tap workout → open editor
- Tap ⚠ badge → see exception + auto-repair suggestion
- Tap "Why?" → see structured rationale (from DecisionRecord)
- Long-press → contextual actions (Move / Regenerate / Lock / Add Directive / Set Equipment)

Advanced controls (phase transitions, goal edits) live behind an "•••" per-client menu, not on the primary view.

---

## 24. Client dashboard

Covered fully in `V2_CLIENT_UX.md`. Summary:

Client sees only **LIVE**. Three primary screens:

```
TODAY
  Workout card (title, duration, equipment, KEY badge if key session)
  [START]  [CHANGE EQUIPMENT]  [TODAY'S REALITY]

UPCOMING (7-day rolling)
  Cards for next 7 days from LIVE plan

MY PROGRAMME
  Goal, phase, event countdown, weekly window progress
```

Client never sees "DRAFT". Everything they see has been coach-approved OR was auto-adapted within the client's `SafeAdaptationBoundary`.

---

## 25. Change-equipment flow (the flagship interaction)

Trigger: client taps **CHANGE EQUIPMENT** on today's workout.

```
1. Modal opens:  "Where are you training?"
   [Bodyweight]  [Gym]  [Dumbbells only]  [Outdoors]  [Pool]  [Other]

2a. If Gym → "What's here?" quick multi-select:
    [Dumbbells] [Bench] [Cable] [Smith] [Barbell/Rack] [Treadmill] [Bike] [Rower]
    [Kettlebells] [Bands] [Pull-up bar] [Machines] [Floor space]
    Optional: "Dumbbells up to?" [15kg] [20kg] [25kg] [30kg+] [Not sure]
    [ADAPT WORKOUT]

3. Backend receives EquipmentContext(scope=this_session, equipment=[…])
4. Retrieves the current WorkoutAssignment (still Upper Strength · Exposure #4)
5. Re-runs Step C (implement) ONLY — new WorkoutImplementation
6. Same objective_id, same exposure_sequence, same key_session status,
   fresh implementation
7. Client sees new exercises inside the SAME session card
8. If within SafeAdaptationBoundary → immediate LIVE; no coach approval
9. If outside SAB → DRAFT ChangeSet created; client sees adapted session,
   coach sees "adaptation to review" badge
```

Target latency: < 5 seconds end-to-end. Cache warm for template hash of `(objective, phase, common_equipment_sets)`.

---

## 26. Today's Reality flow

Same principle. Reality flow is now a **structured intent classifier** first, LLM second:

```
Client taps TODAY'S REALITY:
  Quick chips:  "Tired"  "Only 20 min"  "No gym"  "Called to work"  "Feeling great"
                "Sore knee"  "Missed sleep"  "Bad weather"  "Other…"

Intent chip → intent_type
  ↓
  Deterministic rule engine tries to resolve within SafeAdaptationBoundary
  (reduce duration, swap to mobility, drop to bodyweight, etc.)
  ↓
  If resolvable within SAB → propose adapted session, one-tap accept
  If not → escalate to REALITY_SYSTEM LLM (V1 flow) with structured context
```

**Result:** for common cases (Tired, Only 20 min, No gym) — no LLM call needed, response is instant.

---

## 27. AI role (explicit)

**AI is used for:**
- Roster document extraction (ROSTER_SYSTEM — unchanged from V1)
- Coach command bar natural-language parsing → structured Change proposals
- Workout implementation polish (coaching cues, rationale copy) — bounded input
- Reality flow escalation only when structured rules can't resolve
- Coach message drafts (unchanged from V1)
- Weekly review / check-in question generation (unchanged from V1)
- Explanation generation ("Why this session?") — reads DecisionRecord, expresses it in Louis-voice

**AI is NEVER used for:**
- Dates, event countdowns, phase math
- Programme state transitions (phase advance, exposure sequencing)
- Approval decisions
- Locks
- Version bookkeeping
- Training history lookups
- Exercise eligibility
- Progression math
- Scheduling constraints
- Publishing to LIVE

---

## 28. Automation pipelines (event-driven)

Every state change fires a named event. Handlers subscribe.

Primary events:
- `RosterUploaded`, `RosterConfirmed`, `RosterChanged`, `RosterDeleted`
- `GoalCreated`, `GoalChanged`, `GoalCompleted`
- `EventCreated`, `EventChanged`, `EventCompleted`
- `PhaseAdvanced`, `PhaseTransitionProposed`
- `CoachDirectiveCreated`, `CoachDirectiveExpired`
- `WorkoutCompleted`, `WorkoutSkipped`, `WorkoutMissed`
- `CheckInSubmitted`, `PainReported`
- `EquipmentContextChanged`
- `PlanApproved`, `PlanReverted`
- `WorkoutLocked`, `WorkoutUnlocked`

Handlers are **idempotent**. Repeated firings collapse to the same state.

Job runner (replaces V1's asyncio.create_task pattern):
- Reliable queue with retries + dead-letter
- Idempotency key = (event_id, handler_name)
- Partial completion state stored per job
- Coach dashboard shows job status per client

---

## 29. Equipment-change policy — coach approval boundary

**Programme-level approval:** coach approves objectives + acceptable adaptation boundaries.
**Session-level auto-adaptation:** client's app can freely produce different `WorkoutImplementation` within SAB.

Rule of thumb:
- Change to `WorkoutImplementation` (exercises, cues) inside SAB → **no coach approval needed**
- Change to `WorkoutAssignment` (which date, which objective) → **DRAFT ChangeSet**, coach approval required unless SAB `allow_move_within_planning_window: true`
- Change to `ObjectiveExposure` (skip, drop, add) → **always DRAFT ChangeSet**

---

## 30. Same-day emergency policy

When the day breaks (called to work, flight delayed, sudden fatigue), client can:
- Convert to recovery/mobility (within SAB)
- Skip (only if SAB.allow_skip = true; otherwise DRAFT)
- Move to another day within window (within SAB.allow_move_within_planning_window)

The engine posts a DRAFT ChangeSet describing what happened for coach visibility, but the client's day is resolved instantly.

---

## 31. Decision audit trail

Every material decision writes a `DecisionRecord`:
```
{
  id, timestamp, actor: (system|coach|client|ai),
  event_that_triggered,
  layer: (WHAT|WHEN|HOW|VALIDATE|PUBLISH),
  input_summary,
  rule_or_prompt: {id, version, tier},
  confidence: 0.0-1.0,
  previous_state_ref,
  new_state_ref,
  outcome: (READY|FLAGGED|REPAIRED|BLOCKED),
  human_readable_reason,        # this is what "Why?" displays
}
```

Powers:
- Coach "Why?" tooltips
- Debugging when things go wrong
- Coach-facing changelog
- Automation metrics (§ Observability)

---

## 32. No-roster mode

When client has no active roster:
- Engine uses `profile.default_availability` (weekdays available, session cap, preferred times)
- Planning windows still function
- WorkoutAssignments are anchored to weekdays with `hypothetical: true`
- When roster later arrives: `RosterConfirmed` event fires incremental replan (§17) against the hypothetical assignments — never destroys history

Coach can still edit, approve, lock a no-roster plan normally.

---

## 33. Shadow mode + coach-only beta

Migration approach in `V2_MIGRATION.md`. Briefly:
- V2 engine runs in parallel to V1 for opted-in clients
- Every V2 output written to a `plan_shadows` collection
- Coach dashboard optionally shows "V1 said X · V2 proposed Y"
- Nothing V2 produces reaches the client until manually promoted

Then a coach-only beta where V2 produces DRAFTs but coach still approves everything explicitly.

Finally, V2 becomes the default, V1 kept as read-only fallback.

---

## 34. Observability + automation metrics

Emitted per plan pass:
- `roster_upload_to_draft_ready_seconds` (target: < 60s p95)
- `llm_calls_per_plan` (target: < 5 for a monthly draft; unchanged sessions hit cache)
- `validation_failures_per_plan`
- `exceptions_per_plan`
- `coach_edits_per_plan`
- `plan_approval_time_minutes` (target: < 5 min for a 28-day plan p95)
- `equipment_adaptations_within_sab_pct` (target: > 90%)
- `equipment_adaptations_escalated_to_coach_pct`
- `missed_session_reschedule_success_rate`
- `objective_completion_rate` (per planning window)
- `sab_expansion_events` (times coach loosened boundary)

Kept in a dedicated `metrics_events` collection; dashboards summarise weekly.

---

## 35. Core data model summary (details in SCHEMA)

Ten top-level entities:

1. **Client** (unchanged from V1 users doc; adds `default_availability`, `safe_adaptation_boundary_default`)
2. **Goal** (new — proper multi-goal)
3. **Event** (evolved from V1 events; adds priority, required_disciplines)
4. **Programme** (new top-level container; one per active Goal set)
5. **ProgrammePhase** (new; concrete phase records with start/end)
6. **TrainingObjective** (new; templated per phase)
7. **ObjectiveExposure** (new; the sequenced session identity)
8. **ScheduleDay + RosterDuty** (evolved from V1 rosters.days[])
9. **WorkoutAssignment** (new; joins ObjectiveExposure ↔ ScheduleDay)
10. **WorkoutImplementation** (evolved from V1 workouts; carries the exercises + prescription)

Support entities: `EquipmentContext`, `ReadinessState`, `ProgressionState`, `PerformanceRecord`, `CoachDirective`, `Restriction`, `PlanDraft`, `PlanVersion`, `Approval`, `Lock`, `Exception`, `ChangeSet`, `DecisionRecord`.

Detailed schemas + field-by-field rules in `V2_SCHEMA.md`.

---

## 36. Ten most important changes from V1

1. **Split WHAT / WHEN / HOW into separate engines** (§2, §16) — biggest single architectural gain
2. **DRAFT vs LIVE with explicit publishing contract** (§11) — coach retains control
3. **ObjectiveExposure preserves session identity across rescheduling** (§18) — no more "long run became random workout"
4. **Deterministic scheduling by training-opportunity score** (§14) — replaces LLM-guessed placement
5. **Structured slot templates instead of prose LLM generation** (§18) — reliable programming quality
6. **Multi-goal with weighted allocation + explicit conflict engine** (§6, §7)
7. **Kill the hotel database dependency** (§19) — replaced with session-scoped EquipmentContext
8. **Bodyweight is the default fallback; equipment adaptation preserves objectives** (§25)
9. **Explicit precedence hierarchy** (§20) — no more LLM tie-breaking on aviation rules
10. **Incremental replanning + template cache** (§17) — 10-20× faster than V1's full-month rebuild

---

## 37. Ten V1 systems worth preserving

1. Etihad + Emirates coordinate parsers (`parsers/etihad.py`, `parsers/emirates.py`)
2. `parser_constraints` deterministic safety net
3. `exercises_v2` library + approval status pipeline
4. `feature_v2_resolver` exercise-snapping logic (now feeds the eligibility filter)
5. `feature_layover_naming` post-processor
6. Emergent LLM integration layer (`call_claude`, `call_gemini_file`, `emergentintegrations`)
7. Structured `coach_notes` slots (preferences/cautions/goal_override/weekly_shape/notes)
8. `feature_live_state` pain-flag + focus-shift extraction (feeds V2's ReadinessState)
9. Traffic-light variants (green/amber/red) — become WorkoutImplementation variants
10. `PAIN_REGION_AVOID` mapping (moved into V2's deterministic post-filter)

---

## 38. Ten V1 systems that should be REPLACED

1. `_generate_month` monolithic prompt — replaced by three-layer pipeline
2. `_phase_for_week` modulo cycling — replaced by phase records with start/end dates
3. Single-goal `main_goal_key` — replaced by multi-goal weighted list
4. `hotels` collection dependency in the training path — replaced by `EquipmentContext`
5. Free-text `day_type` as primary key — replaced by structured `RosterDuty` + derived classification
6. LLM-picking-placement inside a chunk — replaced by scheduling engine
7. Silent chunk-drop on LLM failure — replaced by template-first + retry queue
8. `WORKOUT_SYSTEM` writing entire workouts — replaced by polish-only role
9. `feature_workout_fallback` V1 + V2 side-by-side — consolidated into one template library
10. Two exercise collections (`exercises` + `exercises_v2`) — consolidated to v2 only

---

## 39. Ten highest architectural risks in V2

1. **Objective identity drift** — if `ObjectiveExposure.sequence` counters get out of sync with actual completions, progression breaks silently
2. **Template cache staleness** — coach edits a template; caches must invalidate cleanly
3. **SAB abuse** — client repeatedly adapting sessions within SAB could drift the LIVE plan away from coach intent
4. **Precedence engine escape hatches** — every "if AI thinks otherwise" clause reintroduces V1's problems
5. **Migration data loss** — V1's messy goal fields must map cleanly to V2's Goal records
6. **Incremental replan bugs** — missing an affected assignment means stale data in LIVE
7. **DecisionRecord bloat** — writing per-decision audit records can balloon; needs retention policy
8. **Coach-only beta becoming permanent** — engine never trusted enough to reduce coach load
9. **Equipment adaptation quality** — bodyweight version of "primary_horizontal_push" must not become "push-ups × 3" for a strength client
10. **Race-week edge cases** — event date within a partially-generated planning window creates weird boundaries

---

## 40. Twenty biggest opportunities

1. First-class multi-goal + weighted allocation
2. Session identity + progression that survives rescheduling
3. Sub-minute draft generation via template cache
4. Deterministic scheduling that beats LLM placement
5. DRAFT/LIVE with proper versioning
6. Coach approval by exception (approve-27-ready-batch)
7. Coach command bar with structured intent parsing
8. Client equipment swap in < 5s
9. Bodyweight default that never blocks the client
10. Structured Reality flow (chip → rule → LLM only if needed)
11. Explicit SafeAdaptationBoundary reduces coach micromanagement
12. Missed-session engine with importance-tiered cascade
13. Load memory persisted per exercise per client
14. Injury post-filter deterministic (not LLM-only)
15. Weekly-objective tracking replaces Mon–Sun assumptions
16. Multi-event support with A/B/C priority
17. Timeline classification flags unrealistic goals up front
18. Duty-burden score powers consistent decisions across engines
19. Decision audit trail powers "Why?" tooltips + debugging
20. Automation metrics let us measure coach-workload reduction

---

## 41. Implementation roadmap (12 phases)

Details in `V2_MIGRATION.md`. Dependency-ordered summary:

| Phase | Scope | Complexity | Ships behind flag? | Depends on |
|---|---|---:|---|---|
| P1 | Draft/Live/Version/Approval/Lock/ChangeSet/DecisionRecord | L | yes | — |
| P2 | Goal + Timeline + Phase records (data-only) | M | yes | P1 |
| P3 | TrainingObjective + ObjectiveExposure engine (WHAT) | L | yes | P2 |
| P4 | Roster structured facets + duty-burden + opportunity scores | M | yes | P1 |
| P5 | Scheduling engine (WHEN) | L | yes | P3, P4 |
| P6 | Workout construction slot templates (HOW) | XL | yes | P3, P5 |
| P7 | EquipmentContext + client adaptation flow | M | yes | P6 |
| P8 | Progression state + PerformanceRecord + training history feed-forward | L | yes | P6 |
| P9 | Event countdown + phase transitions | M | yes | P2, P3 |
| P10 | Readiness state + Today's Reality structured layer | M | yes | P3 |
| P11 | Coach Dashboard V2 (ROSTER + PLAN workspace) | L | yes | P1..P8 |
| P12 | Automation pipelines + shadow mode + observability | M | yes | all |

**Coach-only beta** is enabled after P11 completes.
**Client-visible V2** is enabled after 4 weeks of coach-only beta with acceptance metrics green.

---

## 42. What CAN be built without affecting current clients

- All of P1-P4 (data models, no client-visible surface)
- Shadow-mode V2 running alongside V1 for opted-in clients
- Coach Dashboard V2 gated by feature flag per coach

## 43. What REQUIRES data migration

- Goals: V1 `profile.main_goal_key` + free text → V2 `Goal` records
- Rosters: V1 `rosters.days[].day_type` → derived facet on V2 `ScheduleDay`
- Workouts: V1 `workouts` docs → V2 `WorkoutImplementation` + reconstructed `WorkoutAssignment` + best-effort `ObjectiveExposure`
- Coach notes: V1 `users.coach_notes` slots → V2 `CoachDirective[]` (structured)
- Progression: V1 `progression_snapshots` → V2 `ProgressionState` per objective
- Hotels: V1 `hotels` docs → OPTIONAL migration to coach-facing notes only; NOT into training path

## 44. What must be complete before V2 draft generation is trusted

- P1 (Draft/Live) — non-negotiable safety net
- P2, P3 (Goal + Objective engines) — otherwise nothing to plan against
- P5 (Scheduling) — deterministic placement
- P6 (Construction) — the actual workouts
- P8 (Progression) — otherwise exposures don't sequence
- Structured validation (P6 embeds this)

## 45. What could create the largest reduction in coach workload

Ranked by expected impact:
1. Draft/Live with batch approve (`APPROVE 27 READY`) — coach touches 3 items instead of 30
2. Client equipment adaptation within SAB — coach never touches these
3. Incremental replan on roster change — no full-month regenerate for a Tuesday flip
4. Structured coach command bar — natural-language → proposed change set
5. Decision "Why?" tooltips — no context-hunting when reviewing
6. Missed-session automatic redistribution — coach doesn't manually reshuffle

---

## 46. Final design principle (verbatim reminder)

CrewFit must understand three different questions:
- **WHAT** does this client need? — goal + phase + timeline + event + history
- **WHEN** should they do it? — roster + recovery + readiness + sequencing + opportunity
- **HOW** can they do it right now? — time + environment + available equipment + restrictions

These are separate architectural layers.
A change in **HOW** should not unnecessarily change **WHAT**.
A change in **WHEN** should not destroy progression.
A change in **WHAT** should happen because the programme actually requires it.

---

**End of architecture document.** See companion files for schema (`SCHEMA.md`), rule engine (`RULE_ENGINE.md`), coach UX (`COACH_UX.md`), client UX (`CLIENT_UX.md`), and migration (`MIGRATION.md`).
