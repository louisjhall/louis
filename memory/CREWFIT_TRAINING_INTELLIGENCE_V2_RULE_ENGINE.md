# CrewFit V2 — Rule Engine

Companion to `V2_ARCHITECTURE.md` and `V2_SCHEMA.md`.
Every rule declared here is **deterministic**. LLM callouts are labelled explicitly. Every rule declares its `precedence_tier` (1-11 from Architecture §20).

---

## 1. Goal definitions (extensible)

Every goal ships as a `GoalDefinition` record. Fields:

```
GoalDefinition {
  goal_id_taxonomy: string
  discipline_bias: {strength: 0..1, run: 0..1, bike: 0..1, swim: 0..1, mobility: 0..1}
  priority_adaptations: [enum: "strength","hypertrophy","aerobic_base","threshold","VO2","mobility","recovery"]
  frequency_range: { min: int, max: int }
  volume_curve: "linear"|"undulating"|"block"|"race_anchored"|"maintenance"
  intensity_curve: same enum
  key_stimuli: [objective_kind, …]         // ordered — most important first
  progression_model: "linear_load"|"double_progression"|"polarised"|"race_km_curve"|"none"
  recovery_requirements: {
    min_hours_between_key: int,
    min_easy_days_after_key: int,
    weekly_deload_frequency: int|null
  }
  compatible_phase_sequence: [phase_kind, …]
  ideal_prep_weeks: int|null                // for timeline classification
  standard_prep_weeks: int|null
  compressed_prep_weeks: int|null
  conflict_map: [
    { other_goal_id, class: "compatible"|"manageable"|"competing"|"strongly_conflicting"|"unrealistic_within_timeline",
      mitigation_rule_ids: [string, …] }
  ]
  event_types_that_qualify: [event_type, …]  // if goal is event-anchored
}
```

### Initial catalog (representative examples — full set implemented per taxonomy in §5 of architecture)

**`body_composition.fat_loss`**
```
discipline_bias: {strength:0.4, run:0.3, mobility:0.2, recovery:0.1}
priority_adaptations: [strength, aerobic_base, mobility]
frequency_range: {min:3, max:5}
volume_curve: linear
intensity_curve: linear
key_stimuli: [full_body_strength, z2_run, z2_bike, mobility]
progression_model: linear_load
recovery_requirements: {min_hours_between_key:48, min_easy_days_after_key:1, weekly_deload_frequency:null}
compatible_phase_sequence: [foundation, build, maintenance]
ideal_prep_weeks: null   // open-ended
```

**`body_composition.muscle_gain`**
```
discipline_bias: {strength:0.75, mobility:0.15, recovery:0.1}
priority_adaptations: [hypertrophy, strength]
frequency_range: {min:3, max:5}
volume_curve: undulating
intensity_curve: undulating
key_stimuli: [push_strength, pull_strength, lower_strength, upper_hypertrophy, lower_hypertrophy]
progression_model: double_progression
recovery_requirements: {min_hours_between_key:48, min_easy_days_after_key:0, weekly_deload_frequency:4}
compatible_phase_sequence: [foundation, hypertrophy, strength, peak, deload]
ideal_prep_weeks: null
```

**`running.marathon`**
```
discipline_bias: {run:0.75, strength:0.15, mobility:0.1}
priority_adaptations: [aerobic_base, threshold, VO2, race_specific]
frequency_range: {min:4, max:6}
volume_curve: race_anchored
intensity_curve: race_anchored
key_stimuli: [long_run, tempo_run, intervals_run, easy_run, strength_support]
progression_model: race_km_curve
recovery_requirements: {min_hours_between_key:48, min_easy_days_after_key:1, weekly_deload_frequency:4}
compatible_phase_sequence: [aerobic_base, build, specific_prep, peak, taper, race_week, recovery]
ideal_prep_weeks: 16
standard_prep_weeks: 12
compressed_prep_weeks: 8
event_types_that_qualify: [marathon]
```

**`triathlon.70_3`**
```
discipline_bias: {run:0.35, bike:0.4, swim:0.15, strength:0.1}
priority_adaptations: [aerobic_base, threshold, brick_capacity, race_specific]
frequency_range: {min:5, max:7}
key_stimuli: [long_run, long_bike, brick, swim_aerobic, tempo_run, bike_intervals]
progression_model: race_km_curve
compatible_phase_sequence: [aerobic_base, build, specific_prep, peak, taper, race_week, recovery]
ideal_prep_weeks: 20
standard_prep_weeks: 16
compressed_prep_weeks: 12
```

Same shape for every goal in the taxonomy. Ship 30+ initial `GoalDefinition` records; add more without code changes.

---

## 2. Timeline classification

```
def classify_timeline(goal, event_date):
    if goal.ideal_prep_weeks is None or event_date is None:
        return "developmental"                  // open-ended
    weeks = (event_date - today) / 7
    if weeks >= goal.ideal_prep_weeks:      return "developmental"
    if weeks >= goal.standard_prep_weeks:   return "standard"
    if weeks >= goal.compressed_prep_weeks: return "compressed"
    return "high_risk"
```

`high_risk` → conflict engine (§4) raises `unrealistic_timeline` exception. Programme still generates; coach reviews before promote.

---

## 3. Phase machine

Each `programme_phase` uses:
```
PhaseDefinition {
  phase_kind: string
  duration_weeks_range: { min: int, max: int }
  entry_criteria: [PhaseGate, …]
  exit_criteria: [PhaseGate, …]
  training_priorities: [obj_kind, …]
  volume_bias, intensity_bias
  fatigue_tolerance: "low"|"moderate"|"high"
  exercise_selection_bias: {
    prefer_compound: boolean,
    prefer_unilateral: boolean,
    prefer_ballistic: boolean
  }
}

PhaseGate {
  kind: "timeline"|"performance"|"adherence"|"readiness"|"coach_approval"
  parameters: {…}
  required: boolean
}
```

**Standard non-endurance sequence:**
`foundation(3-4wk) → hypertrophy(4-6wk) → strength(3-4wk) → peak(2-3wk) → deload(1wk) → repeat_or_transition`

**Endurance sequence (race-anchored):**
`aerobic_base(4-8wk) → build(4-6wk) → specific_prep(3-4wk) → peak(2-3wk) → taper(2-3wk) → race_week(1wk) → recovery(2wk)`

**Return-to-training override:** always `return_to_training(4-6wk)` first before anything else.

### Phase transition rules

```
def can_advance(current_phase, client_state):
    for gate in current_phase.exit_criteria:
        if gate.required and not evaluate_gate(gate, client_state):
            return False, gate.kind
    return True, None

Exit criteria examples:
  foundation:
    - timeline: >= 3 weeks in phase
    - adherence: >= 65% completed key sessions
  hypertrophy:
    - timeline: >= 4 weeks
    - performance: at least one +5% load increase logged
  strength:
    - timeline: >= 3 weeks
    - performance: primary-lift RPE trending stable or down
  taper (endurance):
    - timeline: race is now within 7 days (auto)
  race_week:
    - timeline: race day arrived (auto)
```

**Coach controls (precedence tier 2):**
- `advance_now` — bypass gates, coach approval logged in DecisionRecord
- `extend_phase(weeks)` — delay transition
- `move_to_phase(phase_kind)` — jump forward/back

Every transition generates a `PhaseTransitionProposed` event; coach approves before it becomes LIVE (unless `auto_advance_enabled` on programme).

---

## 4. Goal conflict engine

For every ordered pair of active goals `(A, B)`:
```
if A.goal_id == B.goal_id: skip
class = A.conflict_map.find(B.goal_id).class
if class == "compatible": no action
if class == "manageable":
    apply mitigation rules from conflict_map
if class == "competing":
    log Exception(severity=info) once per programme
if class == "strongly_conflicting":
    log Exception(severity=warning) — coach must acknowledge
if class == "unrealistic_within_timeline":
    log Exception(severity=blocker) — programme blocked until coach demotes one goal
```

### Mitigation rules (initial set)

| Rule ID | When applied | Effect |
|---|---|---|
| `M1_hard_leg_vs_long_run` | any pair with heavy_strength × long_run | Min 24h between; long_run always gets the higher-opportunity day |
| `M2_hypertrophy_vs_endurance_volume` | muscle_gain × any endurance goal | Cap endurance weekly km at 40 for base, 55 for build |
| `M3_fat_loss_vs_event` | fat_loss + any event | In race week + 2wk pre-race, disable calorie deficit prompts |
| `M4_strength_vs_max_endurance` | max_strength × marathon/70.3/IM | Strength drops to 1× per week during peak/taper |
| `M5_return_vs_aggressive_event` | return_to_training × A-priority event | Block promote until timeline reclassified or event demoted |
| `M6_two_A_events_within_8_weeks` | 2 events priority=A, dates ≤ 56 days apart | Block; require one to demote to B |

---

## 5. Training-demand engine (WHAT)

Runs when: `RosterConfirmed`, `GoalChanged`, `EventChanged`, `PhaseAdvanced`, `CoachDirectiveCreated`.

```
def compute_demand(programme):
    active_phase = programme.active_phase
    windows = active_planning_windows(programme)   // typically current + next
    demand = []
    for window in windows:
        # Aggregate weekly targets from all active goals (weighted)
        target_frequency = weighted_frequency(programme.goals)
        target_frequency = clamp(target_frequency,
                                 programme.client.training_days_per_week_target,
                                 min_of_all_active_goal_frequency_maxes)
        # Compose stimuli
        stimuli = compose_stimuli(programme.goals, active_phase, target_frequency)
        for obj_kind, req_count, importance in stimuli:
            demand.append({
                planning_window_id: window.id,
                objective_kind: obj_kind,
                target_count: req_count,
                importance: importance,
                slot_template: pick_template(obj_kind, active_phase.phase_kind)
            })
    return demand
```

### Weighted frequency

```
def weighted_frequency(goals):
    total = 0
    for g in goals:
        base = midpoint(GoalDefinition[g.goal_id].frequency_range)
        total += base * g.weight
    return round(total)
```

Example: marathon(A, 0.7) + general_strength(B, 0.3) → `4.5*0.7 + 4*0.3 = 4.35` → 4 sessions/wk.

### Stimulus composition

For each active goal, weighted contribution of its `key_stimuli` to the weekly slot count. Marathon(0.7) contributes 3 slots (long_run, tempo, easy_run); Strength(0.3) contributes 1 slot (upper_or_lower alternating). Total = 4.

Multi-goal interaction:
- If two goals both want the same objective_kind, target_count sums (capped by phase-appropriate max)
- If two goals want conflicting stimuli in same slot, precedence: primary goal wins slot, secondary demoted to next window

### Exposure emission

For each `{objective_kind, target_count}`:
- Find or create `training_objectives` record for `(programme, phase, kind)`
- Emit `objective_exposures` records with `sequence` continuing from the objective's current sequence counter
- Only emit as many as `target_count` per window; if more phase-total needed, they wait for next window

**Invariant:** the sequence counter is per-`training_objectives.id`, monotonic, never resets except when the training_objective itself is retired (phase transition ends it).

---

## 6. Scheduling engine (WHEN) — the ranking algorithm

Runs after demand for each window:
```
def schedule_window(window, exposures, schedule_days):
    # Rank exposures by importance
    exposures_sorted = sorted(exposures, key=lambda e: (
        -importance_rank(e.importance),
        -objective_priority_rank(e.objective_kind)
    ))
    assignments = []
    for exp in exposures_sorted:
        candidate_days = filter_feasible(schedule_days, exp)
        candidate_days.sort(key=lambda d: -d.training_opportunity)
        chosen = pick_first_respecting_spacing(candidate_days, assignments, exp)
        if chosen is None:
            raise Exception("session_cannot_fit", exp)
        assignments.append(make_assignment(exp, chosen))
    return assignments
```

### filter_feasible checks (all deterministic)

1. Day not already carrying a KEY session (unless spacing rules permit)
2. Day's `duty_burden_band ≤ allowed_burden_for(exp.importance)`
   - KEY → light only
   - IMPORTANT → light or moderate
   - SUPPORTING → any except extreme
   - OPTIONAL → any
3. `available_time_min ≥ exp.slot_template.target_duration_min * 0.9`
4. `recovery_window_hours_from_prior_duty ≥ min_for_objective_kind`
5. No coach lock on this day
6. No coach directive excludes this objective_kind for this date
7. Restriction/pain flags don't block this objective_kind

### pick_first_respecting_spacing

- Ensures `min_hours_between_key` respected between KEY sessions of the same objective family
- Ensures `M1..M6` mitigation rules applied
- Ensures event-critical sessions land in the right relative position (long_run ordinal fits `_long_run_km_for_week` curve)

### Cascade on failure

If no feasible day exists for a KEY session:
1. Attempt to displace another exposure (importance = IMPORTANT or lower)
2. If still no room → next window with `carry_over: true` flag on the exposure
3. If displacement broke event-critical sequencing → raise `Exception("event_session_unscheduled")`

---

## 7. Duty-burden score (precise formula)

```
score = 0
if report_time < 05:00:      score += 20
if finish_local > 23:00:     score += 15
if crossed_midnight:         score += 20
flight_dur_hours = sum(sector.duration_min for sector in duty.sectors) / 60
if flight_dur_hours >= 12:   score += 25
elif flight_dur_hours >= 8:  score += 15
elif flight_dur_hours >= 4:  score += 8
n_sectors = len(duty.sectors)
if n_sectors >= 4:           score += 15
elif n_sectors == 3:         score += 8
tz_shift = abs(destination_tz_offset - base_tz_offset)
score += min(20, tz_shift * 2)
consecutive_duty = count_consecutive_duty_days_prior_to(day)
if consecutive_duty >= 4:    score += 15
elif consecutive_duty == 3:  score += 8
if recovery_window_hours_from_prior_duty < 12: score += 15
score = min(100, score)

bands:
  0-25   → light
  26-50  → moderate
  51-75  → heavy
  76-100 → extreme
```

Recomputed on every roster change (§17 architecture).

---

## 8. Training-opportunity score (precise formula)

```
opp = 100
opp -= 0.6 * duty_burden_score
if recovery_window_hours_from_prior_duty < 18:
    opp -= 25
elif recovery_window_hours_from_prior_duty < 12:
    opp -= 40
if home_or_away == "home":
    opp += 20
if classification == "layover_full" and duty_burden_band in ["light","moderate"]:
    opp += 15
if available_time_min >= 60:
    opp += 10
elif available_time_min < 30:
    opp -= 20
if readiness.band == "recover_priority":
    opp -= 30
elif readiness.band == "slight_reduce":
    opp -= 10
if next_day_burden_band in ["heavy","extreme"]:
    opp -= 15
if prior_day_had_key_session:
    opp -= 20
opp = clamp(0, 100)
```

Bands:
- 75-100 → excellent (host KEY sessions here)
- 50-74 → good (IMPORTANT sessions)
- 25-49 → limited (SUPPORTING sessions or mobility)
- 0-24 → poor (mobility/recovery only)

---

## 9. Workout construction (HOW) — deterministic slot fill + LLM polish

Given a WorkoutAssignment + EquipmentContext + planned duration + readiness state:

```
def construct(assignment, equipment_ctx, duration_min, readiness):
    template = fetch_slot_template(assignment.objective_kind, assignment.phase_kind)

    # Duration variant selection
    if duration_min < template.target_duration_min * 0.6:
        variant = pick_short_variant(template, duration_min)
        active_slots = variant.slots
    else:
        active_slots = template.slots

    # Adjust for readiness
    if readiness.band == "slight_reduce":
        active_slots = drop_optional(active_slots)
        rpe_ceiling = min(rpe_ceiling, readiness.recommended_intensity_ceiling)
    elif readiness.band == "recover_priority":
        return build_mobility_only(assignment, duration_min)

    exercises_selected = []
    for slot in active_slots:
        candidates = eligible_exercises(slot, assignment, equipment_ctx, readiness)
        if not candidates:
            if slot.required:
                candidates = eligible_bodyweight_fallback(slot)
            else:
                continue
        picked = rank_and_pick(candidates, slot, assignment)
        prescription = build_prescription(slot, picked, assignment, readiness)
        exercises_selected.append({slot, picked, prescription})

    warmup = compose_warmup(active_slots, readiness)
    cooldown = compose_cooldown(active_slots, readiness)

    # AI polish pass (optional, cached)
    coaching_cues, rationale = ai_polish(exercises_selected, assignment, readiness)

    return WorkoutImplementation(...)
```

### Eligibility filter

```
def eligible_exercises(slot, assignment, eq_ctx, readiness):
    all_ex = load_approved_exercises()  # exercises_v2 where approval=approved, status=live
    return [e for e in all_ex if
        e.workout_role_suitability includes slot.role
        and e.equipment_type ⊆ eq_ctx.equipment
        and e.movement_pattern not in readiness.avoid_movement_patterns
        and e.movement_pattern not in assignment.client.restrictions.affects_movement_patterns
        and e.id not in coach_exclusions_for(assignment.client, assignment.date)
        and e.difficulty_level ≤ client.experience_level + 1
    ]
```

### Ranking

```
def rank_and_pick(candidates, slot, assignment):
    prior_exposure_map = load_progression_state(assignment.client, assignment.objective_id)
    for c in candidates:
        c.score = 0
        # progression fit — use same exercise as last exposure if beneficial
        if c.id in prior_exposure_map:
            c.score += 30
        # variety — penalise repeats within recent window
        c.score -= 20 * days_since_last_use_lt(c.id, 7)
        c.score += 10 if days_since_last_use_gt(c.id, 21) else 0
        # key session prefers compound
        if slot.key and c.compound:
            c.score += 20
        # client dislikes
        if c.id in client.coach_notes.disliked_ids:
            c.score -= 50
        # media completeness
        if c.media.primary_video: c.score += 5
    return max(candidates, key=lambda c: c.score)
```

### Prescription building

```
def build_prescription(slot, exercise, assignment, readiness):
    prior = load_last_exposure(assignment.client, assignment.objective_id, exercise.id)
    base = { sets: slot.sets, reps: slot.reps, rest_sec: slot.rest_sec, rpe: slot.rpe_target }
    deltas = progression_deltas_for(prior, assignment.programme.phase, assignment.programme.goals[0])
    if prior:
        base.reps = apply_reps_delta(prior.reps_actual, deltas)
        base.load_prescribed_kg = apply_load_delta(prior.load_kg, deltas)
    else:
        base.load_prescribed_kg = None    // first exposure — client sets to feel
    if readiness.band == "slight_reduce":
        base.load_prescribed_kg *= 0.9 if base.load_prescribed_kg else None
        base.sets = max(2, base.sets - 1)
    return base
```

### AI polish call (bounded input)

**Model:** Claude Sonnet 4.5 (via emergentintegrations)
**Input (structured):**
```
{
  objective_kind, phase_kind, duration_min,
  exercises: [{slot_role, exercise_name, sets, reps, load, rest, rpe}],
  client_summary: {experience, primary_goal, recent_rpe_avg, top_pain_flags},
  coach_directives: [free_text of active directives]
}
```
**Output required (JSON):**
```
{
  workout_title, workout_focus_label,
  rationale: "80 words, references specific data points, no AI language",
  coaching_cues: [{slot_role, one_line_cue}]
}
```
**Cap:** 12s timeout, retry once with reduced context, then fallback to template rationale.

**NEVER lets LLM alter exercises, prescriptions, or slots.** Only the copy.

---

## 10. Progression engine (per-exercise memory)

Each `progression_states` record tracks one `(client, objective)`. Fed forward every construction.

### Strength progression rules

```
double_progression:
    if last_actual_reps >= slot.reps_upper and last_rpe <= 8:
        next.load_delta_pct = +2.5
        next.reps_target = slot.reps_lower
    elif last_actual_reps >= slot.reps_lower and last_rpe <= 8.5:
        next.reps_delta = +1                   // add a rep, hold load
    elif last_rpe >= 9 or session_missed:
        next.load_delta_pct = -5.0             // regress
        next.reps_target = slot.reps_lower
    else:
        next.load_delta_pct = 0
        next.reps_target = same
```

### Endurance progression rules

```
race_km_curve:
    for long_run objective, next.km = _long_km_for_week(weeks_to_race, event_type)
    for easy_run, next.km = 0.6 * long_run_km
    for tempo, next.duration_min derived from phase target
    for intervals, workload_curve keyed on phase
```

### Cutback + deload triggers

```
every_4th_week_in_build_or_peak_phase: long_run *= 0.7  (endurance cutback)

if very_high_rpe_count(last_week) >= 2 and n_completed(last_week) >= 3:
    next_week_status = "deload"; volume *= 0.6

if adherence_last_14d < 0.5 and avg_rpe_last_7d >= 8:
    auto_deload_trigger = true
```

Deload behaviour:
- Volume × 0.6 for KEY sessions, × 0.5 for IMPORTANT, drop SUPPORTING and OPTIONAL
- Intensity unchanged (deload = volume reduction not effort reduction)

---

## 11. Readiness engine

```
def compute_readiness(client, as_of_date):
    checkins = load_checkins(client, since=as_of_date - 14d)
    workouts = load_workouts_completed(client, since=as_of_date - 14d)

    signals = extract_signals(checkins, workouts)  // as V1 feature_live_state

    band = "normal"
    if signals.motivation_flag == "low" and signals.sleep_score_avg < 5:
        band = "slight_reduce"
    if signals.auto_deload_trigger:
        band = "recover_priority"
    if any_pain_flag_new_within_7d():
        band = max(band, "slight_reduce")     // upgrade if not already higher
    if severe_pain_flag or coach_directive_urgent:
        band = "coach_review"
    return {signals, band, avoid_movement_patterns}
```

**Band → downstream effect:**
- `normal` → no adjustment
- `slight_reduce` → RPE ceiling = 7, drop OPTIONAL slots, load ×0.9
- `recover_priority` → convert scheduled sessions to mobility/recovery for 1-3 days
- `coach_review` → block promotion of new LIVE workouts until coach acknowledges

---

## 12. Injury post-filter (deterministic, tier 1)

Applies AFTER exercise selection, BEFORE workout goes to READY.

```
def injury_filter(workout, client):
    persistent = client.restrictions
    temporary = client.readiness.pain_flags (< 14d old)

    for ex in workout.exercises:
        blocked_patterns = union(
            [r.affects_movement_patterns for r in persistent],
            [PAIN_REGION_AVOID[p.region] for p in temporary]
        )
        blocked_ids = union([r.affects_exercise_ids for r in persistent])
        if ex.exercise_ref.movement_pattern in blocked_patterns:
            substitute_or_flag(ex)
        if ex.exercise_ref.id in blocked_ids:
            substitute_or_flag(ex)
```

**substitute_or_flag:** try exercise's `substitute_ids` chain, filtered by same eligibility; if no safe substitute, drop slot if not required, else raise `Exception(pain_reported, severity=warning)`.

---

## 13. Coach directive interpretation

Coach types free text in command bar OR uses the structured form. AI intent parser (structured output) converts to a `coach_directives` record.

**Command bar prompt input:**
```
{coach_free_text, client_summary, current_programme_state, recent_directives}
```
**Structured output required:**
```
{
  proposed_directives: [
    { kind, scope, parameters, free_text_original, confidence }
  ],
  human_summary: "You asked for X. I propose to Y from Z."
}
```

Coach previews the parsed directive before it's applied. Never auto-applied.

Precedence: tier 3 (below safety + locks).

---

## 14. Precedence engine (canonical ordered check)

Every decision runs through:
```
def apply_precedence(candidate_decision, context):
    for tier in [1,2,3,4,5,6,7,8,9,10,11]:
        rules = rules_by_tier[tier]
        for rule in rules:
            if rule.applies_to(candidate_decision, context):
                verdict = rule.evaluate(candidate_decision, context)
                if verdict == "block":
                    return {blocked_by: rule.id, reason: rule.reason}
                if verdict == "modify":
                    candidate_decision = rule.transform(candidate_decision, context)
                if verdict == "allow": pass
    return {approved: candidate_decision}
```

Tiers 1-7 are hard; tiers 8-11 are preferences that can be overridden by higher tiers.

---

## 15. Validation checks (V1..V13 from architecture, expanded)

Each check exposes:
```
Check {
  id, name, severity: "auto_repair"|"flag_coach"|"block",
  applies_to: "assignment"|"implementation"|"draft",
  evaluate(target) → { pass: bool, reason?: str, auto_repair_action?: ChangeSet }
}
```

Full initial catalog:

| ID | Check | Severity |
|---|---|---|
| V1 | Every workout_assignment references an objective_exposure | block |
| V2 | Exposure sequence numbers are gapless per objective | auto_repair |
| V3 | Min recovery hours honoured between KEY sessions | flag_coach |
| V4 | Duty burden band compatible with assignment.importance | flag_coach |
| V5 | Equipment context satisfies all exercises | auto_repair |
| V6 | All exercises approval=approved AND status=live | auto_repair |
| V7 | No restriction/pain conflict | block |
| V8 | Duration within ±20% of slot_template.target_duration_min | auto_repair |
| V9 | Progression deltas within reasonable band (±10% load) | flag_coach |
| V10 | Event-critical KEY sessions preserved in expected window | flag_coach |
| V11 | Weekly volume ≤ phase cap | flag_coach |
| V12 | ≥48h between KEY sessions of same discipline | flag_coach |
| V13 | No hard-lower within 24h post-ULR duty | block |
| V14 | If SAB.key_session_hardened, KEY session not reduced >20% | block |
| V15 | No duplicate ObjectiveExposure on same date | block |
| V16 | Every coach_locked assignment untouched by regeneration | block |
| V17 | Warmup + cooldown present if slot_template requires | auto_repair |
| V18 | AI-generated rationale contains no forbidden vocabulary (AI, bot, generated, algorithm) | auto_repair (regenerate rationale) |

---

## 16. Reality flow — structured resolver first, LLM fallback

Client submits intent chip (see architecture §26). Engine tries deterministic resolution:

```
def resolve_reality(intent, workout, client):
    if intent == "tired":
        if workout.importance == "KEY" and readiness.band != "recover_priority":
            return { proposal: "reduce", target_min: workout.duration_min * 0.7,
                     rpe_ceiling: 7 }
        else:
            return { proposal: "convert_to_mobility", target_min: 20 }
    if intent == "only_20_min":
        return { proposal: "reduce", target_min: 20,
                 use_short_variant: True }
    if intent == "no_gym":
        return { proposal: "swap_to_bodyweight",
                 new_equipment_context: {equipment: [bodyweight, mat]} }
    if intent == "called_to_work":
        return { proposal: "move_within_window" or "convert_to_mobility",
                 create_change_set: True }
    if intent == "sore_knee":
        return { proposal: "swap_lower_pattern",
                 avoid_patterns: PAIN_REGION_AVOID["knee"] }
    if intent == "feeling_great":
        if workout.importance != "KEY":
            return { proposal: "add_optional_intensity_bonus" }
    return None    // escalate to LLM
```

If deterministic returns a proposal:
1. Check SAB — auto-apply within boundary, no coach approval
2. If outside SAB, propose to client + queue as DRAFT ChangeSet

If deterministic returns None:
1. Call REALITY_SYSTEM LLM (V1 flow) with fuller context
2. Handle response as A/B/C (V1 unchanged)

---

## 17. Equipment adaptation flow

```
def adapt_workout_to_equipment(assignment, new_equipment_ctx):
    old_impl = assignment.live_implementation
    exposure = assignment.objective_exposure
    # Same objective, new implementation
    new_impl = construct(assignment, new_equipment_ctx, assignment.planned_duration, readiness)
    # Validate
    for check in [V5, V6, V7, V14, V15, V17]:
        if not check.pass(new_impl):
            return { fail: check.reason }
    # SAB check
    if within_sab(new_impl, old_impl, assignment.safe_adaptation_boundary):
        commit_live(new_impl)
        return { ok: true, adapted: true }
    else:
        commit_draft(new_impl)
        create_change_set(kind="implementation_changed", proposed_by="client")
        return { ok: true, adapted: true, requires_coach_review: true }
```

**within_sab evaluation:**
```
def within_sab(new, old, sab):
    if not sab.allow_equipment_swap: return False
    if abs(new.duration_min - old.duration_min) / old.duration_min > sab.allow_duration_reduce_pct / 100: return False
    # objective preserved
    if new.assignment.objective_exposure_id != old.assignment.objective_exposure_id: return False
    # key session hardening
    if old.assignment.importance == "KEY" and sab.key_session_hardened:
        if new.duration_min < old.duration_min * 0.8: return False
    # exercise pool constraint
    for e in new.exercises:
        if e.exercise_id not in approved_pool: return False
    return True
```

---

## 18. Missed-session cascade

Runs at window boundary + after any completion/skip:
```
def handle_missed(exposure, window):
    imp = exposure.importance
    if imp == "OPTIONAL":  drop(exposure); return
    if imp == "SUPPORTING":
        try_shift_in_window(exposure) or drop(exposure)
        return
    if imp == "IMPORTANT":
        if shifted := try_shift_in_window(exposure): return
        if compressed := try_compress_with_same_objective_next_session(exposure): return
        defer_to_next_window(exposure, flag=True)
        return
    if imp == "KEY":
        if shifted := try_shift_in_window(exposure): return
        if displaced := try_displace_lower_importance(exposure): return
        raise Exception("event_session_unscheduled", severity="warning")
```

Sequence counter never regresses on miss; the missed exposure remains #N and any rescheduled placement retains its number.

---

## 19. Publishing rules — DRAFT → LIVE promotion

Coach action `Approve <scope>`:
```
def promote(scope, coach):
    draft = current_draft(scope.programme)
    affected = collect_scope_assignments(scope, draft)
    # Blockers
    blocked = [a for a in affected if any(exception.severity == "blocker" for exception in a.exceptions)]
    if blocked and not scope.force_coach_override:
        return { fail: "blocked_exceptions", ids: blocked.ids }
    # Snapshot + version
    version = new_version(scope.programme, published_by=coach.id)
    snapshot(version, affected)
    # Update pointers
    for a in affected:
        a.status = "live"
        a.live_implementation_id = a.draft_implementation_id
    # Emit event
    fire(PlanApproved, version.id, scope)
    return { ok: true, version_id: version.id }
```

Client immediately sees the newly LIVE workouts on next fetch.

---

## 20. Concrete precedence example (worked)

Situation: KEY long_run scheduled Saturday. Client reports low sleep + moderate soreness (readiness band = `slight_reduce`). Coach directive active: `avoid_movement: high_impact_run` until Monday.

```
Tier 1 (safety): pain flags none; no hard block
Tier 2 (coach locks): none on this workout
Tier 3 (coach directive): "avoid high_impact_run until Monday" — APPLIES → cannot proceed with long_run today
Tier 4 (event-critical): long_run is race-critical, but directive tier 3 > 4 → directive wins
Tier 5 (programme objective): objective is preserved; exposure #6 remains pending
Tier 6 (roster feasibility): Sunday has training_opportunity 78, no directive conflict
Tier 7 (readiness): slight_reduce — Sunday can host long_run but with RPE ceiling 6

Verdict: MOVE long_run from Saturday → Sunday. Saturday becomes mobility.
```

DecisionRecord captures each tier's evaluation. Coach sees "Why moved?" showing tier 3 rule.

---

## 21. Rule versioning

Every rule declared here has:
- `rule_id`
- `version` (semver)
- `changelog`
- `precedence_tier`
- `applies_to` (entity type)
- `evaluate` implementation reference

Rule changes never break older `DecisionRecord`s — the record captures `rule_or_prompt.version` at time of decision. This lets us evolve rules safely without corrupting audit history.

---

**End of rule engine document.**
