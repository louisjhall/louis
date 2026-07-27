# CrewFit V2 — Schema

Companion to `V2_ARCHITECTURE.md`. Defines every core entity, its fields, invariants, indexes, and its relationships to other entities.

Types shown as pseudo-TS. Collections use MongoDB names.

---

## 1. Naming conventions

- Collections: snake_case plural (`programmes`, `training_objectives`)
- IDs: string UUIDv4 (`id` field, unique)
- Timestamps: ISO-8601 with timezone (`created_at`, `updated_at`, `valid_from`, `valid_until`)
- References: `<entity>_id` (e.g. `client_id`, `objective_id`)
- Enum values: lowercase snake_case string literals
- Every entity carries `created_at`, `updated_at`, `created_by`, `version` (integer)

---

## 2. Client (evolved from V1 `users`)

```
users {
  id: string
  email, name, role: "client"|"coach"|"admin"
  profile: {
    // V1 fields retained
    first_name, last_name, age, sex, height_cm, weight_kg,
    airline, job_title, home_base, route_focus,

    // V2 additions
    default_availability: {
      preferred_days: ["mon","tue","wed","thu","fri","sat","sun"],
      session_max_min: 60,
      preferred_time_of_day: "morning"|"afternoon"|"evening"|"any",
      training_days_per_week_target: 4
    },
    experience_level: "beginner"|"intermediate"|"advanced",
    persistent_restrictions: [
      { id, region, notes, since_date, review_date?, source: "client"|"coach" }
    ],
    equipment_permanent: EquipmentContext[]     // profile-scoped contexts only
    safe_adaptation_boundary_default: SAB      // see §17
  }
  auth: { … }
}
```

Invariants:
- One user, many `Goal`s, one active `Programme` at a time.

---

## 3. Goal (new)

```
goals {
  id
  client_id
  goal_id_taxonomy: string    // e.g. "running.marathon", "body_composition.muscle_gain"
  priority: "A"|"B"|"C"
  weight: number  0..1        // allocation weight relative to other goals
  target_date?: ISO date
  target_metric?: {           // discipline-specific
    kind: "time"|"distance"|"weight_kg"|"body_fat_pct"|"custom",
    value: number|string,
    unit: string
  }
  current_baseline?: same shape as target_metric
  notes: string
  status: "active"|"paused"|"completed"|"abandoned"
  timeline_class: "developmental"|"standard"|"compressed"|"high_risk"  // computed
  created_at, updated_at, created_by
}
```

Constraints:
- Sum of `weight` across active goals ≈ 1.0 (normalised on write)
- Only ONE goal can hold `priority = "A"` unless conflict engine explicitly permits
- `target_date` in the past → `status="completed"` auto-set on next tick

Indexes: `{client_id, status}`, `{client_id, priority}`

---

## 4. Event (evolved from V1 `events`)

```
events {
  id
  client_id
  goal_id?                    // if linked to a specific Goal
  event_type: string          // maps to goal taxonomy (marathon, 70_3, sim_check, …)
  category: "race"|"medical"|"aviation_work"|"sport_hobby"|"personal"
  priority: "A"|"B"|"C"
  date: ISO date
  time?: HH:MM
  timezone?: IANA
  location?: { city, country, iata? }
  distance?: number  // km or m depending on discipline
  target_time?: seconds
  current_ability?: {
    metric_kind: string,
    value: any,
    measured_on: date
  }
  required_disciplines: string[]  // ["run","strength","mobility"]
  access: {                       // client-declared during setup
    gym: boolean, pool: boolean, bike: boolean, treadmill: boolean, outdoor_run: boolean
  }
  notes: string
  status: "active"|"completed"|"cancelled"
  is_active: boolean              // legacy alias — retained for coach-side filtering
  created_at, updated_at, created_by
}
```

Constraints:
- Two `priority=A` events within 8 weeks → engine raises `MultiAConflict` exception; requires coach demotion
- Post-event recovery window auto-created in the Programme timeline

Indexes: `{client_id, status, priority, date}`

---

## 5. Programme + ProgrammePhase (new)

```
programmes {
  id
  client_id
  primary_goal_id
  secondary_goal_ids: [goal_id, …]
  event_ids: [event_id, …]     // events tied to this programme
  timeline_class: enum          // copied from primary Goal at creation
  start_date, end_date?
  status: "draft"|"active"|"paused"|"completed"|"superseded"
  phase_sequence: [phase_id, …]  // ordered
  live_plan_version: int         // pointer to latest published version
  draft_plan_version: int        // pointer to currently editable draft
  created_at, updated_at, created_by
}

programme_phases {
  id
  programme_id
  phase_kind: "foundation"|"general_prep"|"hypertrophy"|"strength"|"aerobic_base"|"build"|"specific_prep"|"peak"|"taper"|"race_week"|"recovery"|"maintenance"|"return_to_training"
  ordinal: int
  planned_start_date, planned_end_date
  actual_start_date?, actual_end_date?
  entry_criteria: { … see RULE_ENGINE }
  exit_criteria: { … see RULE_ENGINE }
  status: "upcoming"|"active"|"completed"|"skipped"|"extended"
  purpose_summary: string      // coach-facing text
  training_priorities: [obj_kind, …]
  volume_bias: "low"|"moderate"|"high"|"tapering"
  intensity_bias: "low"|"moderate"|"high"|"race_specific"
  created_at, updated_at
}
```

Constraints:
- `programme_phases.ordinal` gapless within a programme
- Only one `programme_phases.status = "active"` per programme at a time

---

## 6. TrainingObjective + ObjectiveExposure (new — the CORE additions)

`TrainingObjective` is a **template + phase target** for a specific stimulus. `ObjectiveExposure` is a **sequenced instance** the client actually performs.

```
training_objectives {
  id
  programme_id
  phase_id                        // phase this objective belongs to
  kind: string                    // "upper_strength" | "long_run" | "z2_bike" | "swim_technique" | "mobility" | ...
  discipline: "strength"|"run"|"bike"|"swim"|"mobility"|"recovery"|"conditioning"|"brick"
  target_exposures_in_phase: int  // e.g. 12 upper_strength across 4 weeks = 12
  target_exposures_per_window: int// per planning window
  importance: "key"|"important"|"supporting"|"optional"
  slot_template_id: ref            // → workout_slot_templates
  progression_model: "linear_load"|"double_progression"|"polarised"|"km_curve"|"none"
  min_recovery_hours_after: int
  paired_with_other_objectives: [obj_id, …]   // e.g. long_run pairs with short_shakeout
  active_start_date, active_end_date
  status: "planned"|"active"|"completed"|"deferred"|"skipped"
  created_at, updated_at
}

objective_exposures {
  id
  objective_id
  programme_id
  client_id
  sequence: int                   // #1, #2, #3 within the objective
  status: "pending"|"assigned"|"in_progress"|"completed"|"missed"|"skipped"|"deferred"
  planning_window_id?             // reference (nullable if not yet placed)
  assignment_id?                  // reference to WorkoutAssignment (when placed)
  implementation_id?              // reference to WorkoutImplementation (when built)
  performance_record_id?          // populated on completion
  progression_state_snapshot: {   // snapshot at time of exposure, for feed-forward
    prior_loads?: [ … ],
    prior_reps?: [ … ],
    prior_rpe_avg?: number,
    prior_km?: number,
    prior_pace_sec_per_km?: number,
    prior_intervals?: any
  }
  created_at, updated_at
}
```

**Invariants (critical):**
- `objective_exposures.sequence` is monotonic per `objective_id`; NEVER resets on reschedule
- `objective_exposures.status` transitions: `pending → assigned → in_progress → completed | missed | deferred`
- Deleting a WorkoutAssignment does NOT delete its ObjectiveExposure — the exposure returns to `status="pending"`

Indexes: `{objective_id, sequence}`, `{client_id, status}`, `{assignment_id}`

---

## 7. Planning Window (new)

```
planning_windows {
  id
  programme_id
  kind: "rolling_7d"|"iso_week"|"race_microcycle"
  start_date, end_date
  anchor: "today"|"iso_monday"|"race_countdown"
  target_exposures: [               // computed by demand engine
    { objective_id, kind, required, importance }, …
  ]
  actual_exposures: [               // updated as workouts complete
    { objective_id, exposure_id, status, completed_on? }, …
  ]
  status: "upcoming"|"active"|"closing"|"closed"
  created_at, updated_at
}
```

---

## 8. ScheduleDay + RosterDuty + FlightSector (evolved)

```
schedule_days {
  id
  client_id
  date: ISO date
  home_or_away: "home"|"away"|"unknown"
  tz_offset_from_base_hours: number
  recovery_window_hours_to_next_duty: number|null
  recovery_window_hours_from_prior_duty: number|null
  duties: [duty_id, …]          // references roster_duties
  overnight_location?: { city, country, iata? }
  derived: {
    duty_burden_score: 0..100,
    duty_burden_band: "light"|"moderate"|"heavy"|"extreme",
    training_opportunity: 0..100,
    recommended_intensity_ceiling: "rpe4"|"rpe6"|"rpe7"|"rpe8"|"any",
    available_time_min: number,
    classification: "rest"|"layover_arrival"|"layover_full"|"layover_departure"|"turnaround"|"standby"|"home"|"leave"|"other"
  }
  source_roster_id: ref
  parser_confidence: 0..1
  version: int                   // rev counter for incremental replans
  updated_at, updated_by
}

roster_duties {
  id
  schedule_day_id
  duty_type: "flight"|"standby"|"sim"|"training"|"positioning"|"leave"|"rest"|"off"|"medical"
  report_time?: ISO datetime
  duty_start_time?: ISO datetime
  duty_finish_time?: ISO datetime
  crossed_midnight?: boolean
  standby: {                          // present only if duty_type=standby
    kind: "home"|"airport"|"reserve"|"short_call"|"long_call"|"night"|"early"|"unknown",
    window_start?: ISO datetime,
    window_end?: ISO datetime,
    location?: string
  }
  sectors: [sector_id, …]
  notes: string
  created_at, updated_at, created_by
}

flight_sectors {
  id
  duty_id
  ordinal: int                        // 1..N
  departure_iata: string
  arrival_iata: string
  departure_time: ISO datetime
  arrival_time: ISO datetime
  aircraft?: string
  duration_min: number                // derived
}
```

Indexes: `{client_id, date}`, `{source_roster_id}`

Legacy V1 `rosters.days[]` is retained read-only for migration; V2 writes go to the new tables.

---

## 9. WorkoutAssignment (new)

Joins an ObjectiveExposure to a ScheduleDay.

```
workout_assignments {
  id
  client_id
  programme_id
  planning_window_id
  objective_exposure_id           // 1:1 relationship
  schedule_day_id
  date: ISO date                  // denormalised for indexing
  status: "proposed"|"ready"|"live"|"in_progress"|"completed"|"missed"|"skipped"|"reverted"
  importance: "key"|"important"|"supporting"|"optional"  // inherited
  planned_duration_min: number
  safe_adaptation_boundary: SAB   // see §17
  live_implementation_id?         // pointer to LIVE WorkoutImplementation
  draft_implementation_id?        // pointer to DRAFT WorkoutImplementation
  locked: boolean
  locked_by?: user_id
  locked_at?: timestamp
  coach_notes: string             // per-assignment coach notes
  decision_record_ids: [id, …]
  created_at, updated_at
}
```

Indexes: `{client_id, date}`, `{objective_exposure_id}` unique, `{status}`, `{planning_window_id}`

---

## 10. WorkoutImplementation (evolved from V1 `workouts`)

```
workout_implementations {
  id
  assignment_id
  client_id
  date: ISO date                  // denormalised
  variant_of_id?                  // links green/amber/red variants
  variant_type: "green"|"amber"|"red"|null
  equipment_context: EquipmentContext  // snapshot at build time
  duration_min: number
  title: string
  location_label: string          // free text for client display
  focus: string                   // discipline/pattern
  warmup: [ { name, duration_sec, notes? }, … ]
  exercises: [                    // ORDERED
    {
      slot_role: string,          // "primary_horizontal_push", "trunk", …
      exercise_id: ref            // → exercises_v2
      exercise_name_display: string  // resolved at build; not authoritative
      sets: int,
      reps: string|int,           // "8-10" or int
      rest_sec: int,
      rpe?: string,               // "7" or "7-8"
      rir?: string,
      tempo?: string,
      load_prescribed_kg?: number,
      duration_sec?: number,
      distance_m?: number,
      pace_sec_per_km?: number,
      hr_zone?: "z1"|"z2"|"z3"|"z4"|"z5",
      substitution_hint?: string,
      coaching_cue: string        // AI polish output
    }, …
  ]
  cooldown: [ { name, duration_sec, notes? }, … ]
  rationale: string               // "Why this?"
  key_session: boolean
  source: "template_v2"|"template_v1_legacy"|"llm_polish"|"coach_authored"
  needs_coach_review: boolean
  built_at: timestamp
  cache_key: string               // for template cache invalidation
}
```

Indexes: `{assignment_id, variant_type}`, `{client_id, date}`

---

## 11. Workout Slot Templates (new, seeded)

```
workout_slot_templates {
  id
  objective_kind: string          // "upper_strength"
  phase_kind: string              // "build"
  intent: "primary"|"variant"     // primary = full session; variants are duration variants
  target_duration_min: number
  slots: [
    {
      role: string,               // "primary_horizontal_push"
      role_pattern_pool: [movement_pattern, …],  // {"horizontal_push"} etc.
      equipment_preference: [equipment_type ranked],
      sets: int|range,
      reps: string|range,
      rest_sec: int,
      rpe_target: string,
      key: boolean,
      required: boolean           // false = drop this slot if duration compressed
    }, …
  ]
  short_variants: [
    { target_duration_min: 30, keep_slots: [role_ids], compress_rules: {…} },
    { target_duration_min: 20, keep_slots: [role_ids], compress_rules: {…} },
    { target_duration_min: 10, keep_slots: [role_ids], compress_rules: {…} },
  ]
  bodyweight_fallback_slots: [ … ]  // fallback when no equipment
  metadata: { created_by, version, notes }
}
```

Seeded set (initial catalogue, expand over time):
- Strength: `upper_strength × {foundation, hypertrophy, strength, peak}`,
  `lower_strength × {…}`, `full_body × {…}`, `push × {…}`, `pull × {…}`,
  `legs × {…}`, `strength_endurance × {…}`
- Cardio: `easy_run × {base, build, peak}`, `long_run × {base, build, peak, taper}`,
  `tempo`, `intervals`, `easy_bike`, `long_bike`, `bike_intervals`,
  `swim_technique`, `swim_aerobic`, `swim_threshold`, `brick`
- Support: `mobility`, `flight_recovery_short`, `flight_recovery_medium`,
  `ulr_recovery`, `activation_short_haul_gap`, `bodyweight_layover_default`

---

## 12. Exercise (retained — exercises_v2 already close)

Fields extended slightly:
```
exercises_v2 {
  id
  exercise_name
  movement_family: "push"|"pull"|"squat"|"hinge"|"lunge"|"carry"|"rotate"|"anti_rotate"|"gait"|…
  movement_pattern: string        // "horizontal_push", "vertical_pull", …
  primary_muscles: [muscle_id, …]
  secondary_muscles: [muscle_id, …]
  equipment_type: [enum, …]       // {barbell, dumbbells, kettlebell, cable, machine, bench, bands, bodyweight, pull_up_bar, trx, …}
  difficulty_level: 1..5
  unilateral: boolean
  compound: boolean
  stability_requirement: "low"|"moderate"|"high"
  progression_ids: [exercise_id]  // easier→harder chain
  regression_ids: [exercise_id]
  substitute_ids: [exercise_id]   // similar stimulus
  contraindications: [region, …]  // do not use if pain in region
  workout_role_suitability: [role, …]  // e.g. "primary_horizontal_push"
  goal_suitability: [goal_id_taxonomy, …]
  coaching_points: [str, …]
  common_mistakes: [str, …]
  media: { primary_video, backup_video, images[] }
  approval_status: "draft"|"needs_review"|"artwork_needed"|"coaching_points_needed"|"video_needed"|"ready_for_approval"|"approved"|"live"|"needs_update"|"rejected"|"archived"
  approval: "pending"|"approved"|"rejected"
  created_at, updated_at
}
```

V1 legacy `exercises` collection retained read-only; migrated into `exercises_v2` in P1 of migration.

---

## 13. Progression + Performance (new)

```
progression_states {
  id
  client_id
  objective_id                    // per-objective progression
  discipline: enum
  current_metric_snapshot: {      // updated per completion
    load_kg?: number,
    reps?: int,
    sets?: int,
    rpe_last?: number,
    km?: number,
    pace_sec_per_km?: number,
    interval_workload?: any,
    swim_distance_m?: number,
    swim_interval_workload?: any
  }
  history: [                       // append-only exposure results
    { exposure_id, date, metric_snapshot, outcome, notes }, …
  ]
  next_prescription_deltas: {      // computed by rules
    load_delta_pct?, reps_delta?, sets_delta?, rpe_delta?, km_delta?, pace_delta_sec?
  }
  status_label: "progressing_well"|"maintain"|"reduce_load"|"deload"
  reason: string
  updated_at
}

performance_records {
  id
  client_id
  assignment_id
  implementation_id
  exposure_id
  date
  exercise_records: [
    {
      exercise_id,
      sets_completed: int,
      reps_per_set: [int, …],
      load_per_set_kg: [number, …],
      rpe_per_set: [number, …],
      duration_sec?,
      distance_m?,
      pace_sec_per_km?,
      notes?
    }, …
  ]
  session_rpe?: number
  perceived_difficulty?: 1..10
  substitutions_used: [ { slot_role, original_exercise_id, actual_exercise_id, reason } ]
  session_completion_pct: 0..100
  session_notes: string
  submitted_at
}
```

---

## 14. Readiness (evolved from V1 live_state)

```
readiness_states {
  id
  client_id
  as_of_date
  window: 7|14|28 (days)
  signals: {
    sleep_score_avg: number,
    energy_score_avg: number,
    soreness_score_avg: number,
    stress_score_avg: number,
    rpe_trend: number,
    adherence_pct: number,
    missed_sessions_count: int,
    pain_flags: [ { region, first_seen_at, source } ],
    motivation_flag: "low"|"steady"|"high",
    focus_shift_request?: { target, raw_text },
    life_change_flag: boolean,
    auto_deload_trigger: boolean
  }
  band: "normal"|"slight_reduce"|"recover_priority"|"coach_review"
  avoid_movement_patterns: [pattern, …]  // derived from pain_flags
  computed_at
}

check_ins {  // canonical — dedup from V1 `check_ins` vs `checkins`
  id
  client_id
  submitted_at
  kind: "weekly"|"daily_pulse"|"post_workout"|"pain_report"
  scores: { energy, sleep, soreness, stress }
  free_text: string
  extracted_signals: { pain_regions[], focus_shift?, life_change? }
}
```

---

## 15. Coach Directive (new — structured)

Replaces V1's `users.coach_notes` free-text slots.

```
coach_directives {
  id
  client_id
  coach_id
  kind: "avoid_movement"|"require_movement"|"limit_frequency"|"limit_volume"|"limit_intensity"|"skip_objective"|"add_objective"|"change_goal"|"note_only"
  scope: {
    dates?: [date, …]        // specific dates
    date_range?: {from, to}  // range
    trip?: {trip_start, trip_end}
    planning_window_id?
    phase_id?
    persistent: boolean      // until changed
  }
  parameters: {              // schema depends on kind
    movement_pattern?, discipline?, exercise_id?, objective_id?,
    max_frequency_per_window?, max_intensity_rpe?, …
  }
  free_text: string          // Louis's own words for context
  status: "active"|"expired"|"revoked"
  created_at, updated_at, revoked_by?, revoked_at?
}
```

Preserves V1 `coach_notes.preferences|cautions|goal_override|weekly_shape|notes` — migrated by parser into structured `coach_directives` records. V1 `notes` free text kept as-is on a per-directive `free_text` field.

Precedence: tier 3 in the precedence engine.

---

## 16. Restrictions (persistent) vs Pain flags (temporary)

```
restrictions {
  id
  client_id
  region: string             // "left_shoulder", "lower_back", …
  severity: 1..5
  since_date
  review_date?
  source: "client"|"coach"|"assessment"
  affects_movement_patterns: [pattern, …]  // derived + editable
  affects_disciplines: [discipline, …]
  affects_exercise_ids: [exercise_id, …]   // explicit block list
  status: "active"|"cleared"
  notes
}
```

Pain flags remain on `readiness_states.signals.pain_flags` (temporary, decays out of 14-day window).

---

## 17. EquipmentContext + SafeAdaptationBoundary

```
equipment_contexts {
  id
  client_id
  source: "profile"|"client_selected"|"coach_selected"|"reality_flow"
  scope: "permanent"|"date_range"|"today"|"this_session"
  equipment: [enum, …]        // structured list — see below
  detail: {
    dumbbell_max_kg?: number,
    barbell_available?: boolean,
    plate_range?: [min_kg, max_kg],
    machines_familiar?: boolean,
    room_size?: "cramped"|"normal"|"spacious",
    ceiling?: "low"|"normal",
    noise_ok?: boolean,       // e.g. hotel room jumping
    outdoor_running_safe?: boolean,
    notes?: string
  }
  valid_from, valid_until
  created_at, created_by
}
```

**Equipment enum (canonical — single vocabulary; kills V1's two lists):**
```
[bodyweight, mat, foam_roller, band, resistance_band,
 dumbbells, adjustable_dumbbells, kettlebell,
 barbell, plates, bench_flat, bench_adjustable, squat_rack, smith_machine,
 cable_stack, machine_chest_press, machine_row, machine_lat_pulldown,
 machine_leg_press, machine_leg_extension, machine_leg_curl, machine_pec_deck,
 pull_up_bar, dip_station, trx, gymnastic_rings, medicine_ball,
 treadmill, stationary_bike, air_bike, rower, cross_trainer, skierg,
 pool, box_plyo, sled,
 outdoor_run_safe, floor_space]
```

**SafeAdaptationBoundary (SAB):**
```
type SAB = {
  allow_equipment_swap: boolean,
  allow_duration_reduce_pct: number,   // 0..60
  allow_convert_to_recovery: boolean,
  allow_convert_to_mobility: boolean,
  allow_skip: boolean,
  allow_move_within_planning_window: boolean,
  allow_move_across_windows: boolean,
  allow_substitute_exercise_from_approved_pool: boolean,
  key_session_hardened: boolean,       // if true, KEY sessions can only reduce 20%
  overrides: {                          // per-objective_kind overrides
    long_run: Partial<SAB>,
    heavy_strength: Partial<SAB>
  }
}
```

Default at `users.profile.safe_adaptation_boundary_default`. Copied onto every `workout_assignments` at creation; coach can widen/narrow per assignment.

---

## 18. Plan Draft / Live / Version (new)

```
plan_drafts {
  id
  programme_id
  client_id
  parent_plan_version_id?      // baseline version this draft is derived from
  changes: [change_set_id, …]  // pending change sets
  status: "building"|"ready_for_review"|"partially_approved"|"promoted"|"discarded"
  build_started_at, build_completed_at
  metrics: { ready_count, needs_review_count, conflict_count, coach_edited_count, blocked_count }
  updated_at
}

plan_versions {
  id
  programme_id
  version: int (monotonic)
  published_at, published_by
  snapshot_ref                   // → plan_snapshots
  supersedes_version_id?
  approvals: [approval_id, …]    // approvals that promoted this version
}

plan_snapshots {
  id
  version_id
  workout_assignments_snapshot: [ … ]      // immutable copies
  workout_implementations_snapshot: [ … ]  // immutable copies
  objective_exposures_snapshot: [ … ]
  created_at
}

change_sets {
  id
  draft_id
  kind: "assignment_moved"|"implementation_changed"|"objective_added"|"objective_removed"|"exposure_deferred"|"phase_transition"|"equipment_context_changed"|"coach_directive_applied"|"readiness_response"
  scope_assignment_ids: [id, …]
  before_snapshot: object
  after_snapshot: object
  triggered_by: "system"|"coach"|"client"|"ai_command_bar"
  triggered_event_id: string
  proposed_by: "system"|"coach"|"client"
  status: "proposed"|"accepted"|"rejected"|"auto_applied"
  human_readable_summary: string
  created_at, resolved_at?, resolved_by?
}

approvals {
  id
  draft_id
  scope: "workout"|"day"|"date_range"|"planning_window"|"phase"|"programme"|"batch_ready"
  scope_ref: id | [id, …]
  approved_by (coach)
  approved_at
  notes
}

locks {
  id
  client_id
  target_kind: "exercise"|"workout"|"day"|"objective"|"exposure"|"phase"|"programme"|"directive"
  target_id
  locked_by, locked_at
  reason
  auto_release_at?
}
```

Invariants:
- `plan_versions` are immutable after publish
- Every `plan_versions` maps 1:1 to a `plan_snapshots` for point-in-time recovery
- Client's LIVE view queries via `plan_versions` at `programmes.live_plan_version`

---

## 19. Exception (new)

```
exceptions {
  id
  draft_id
  client_id
  kind: "roster_change"|"insufficient_recovery"|"session_cannot_fit"|"event_session_unscheduled"|"goal_conflict"|"unusual_fatigue"|"pain_reported"|"missing_equipment"|"objective_missed"|"volume_anomaly"|"progression_stalled"|"low_confidence_roster_parse"|"coach_directive_conflict"|"multi_a_conflict"|"unrealistic_timeline"
  severity: "info"|"warning"|"blocker"
  scope_ref
  triggered_at, triggered_by_event_id
  proposed_resolutions: [
    { id, kind, summary, one_click_apply: boolean }
  ]
  status: "open"|"resolved"|"dismissed"|"escalated"
  resolved_by?, resolved_at?, resolution_change_set_id?
}
```

Coach dashboard's "Need Review" list is a query of open exceptions with severity ≥ warning.

---

## 20. DecisionRecord (new)

```
decision_records {
  id
  timestamp
  actor: "system"|"coach"|"client"|"ai"
  event_id?                     // event that triggered
  layer: "WHAT"|"WHEN"|"HOW"|"VALIDATE"|"PUBLISH"|"ADAPT"|"CLIENT_COMPLETION"
  scope_kind: "assignment"|"implementation"|"exposure"|"programme"|"phase"|"objective"
  scope_id
  input_summary: string
  rule_or_prompt: { id, kind: "rule"|"prompt", tier?, version }
  confidence: 0..1
  previous_state_ref?, new_state_ref?
  outcome: "READY"|"FLAGGED"|"REPAIRED"|"BLOCKED"|"PROPOSED"|"APPLIED"|"REJECTED"
  human_readable_reason: string
  llm_call_ref?: { call_id, tokens_in, tokens_out, model, latency_ms }
}
```

Indexes: `{scope_id, timestamp}`, `{actor, layer}`, `{layer, outcome, timestamp}`

Retention: 12 months hot; older archived to cold storage (S3-equivalent) — do not delete.

---

## 21. Automation / Job Runner (new)

```
jobs {
  id
  kind: string             // "roster_parse"|"draft_build"|"phase_transition"|"reality_polish"|…
  target_scope: { client_id, programme_id?, draft_id?, assignment_id? }
  status: "queued"|"in_progress"|"succeeded"|"failed"|"cancelled"|"dead_letter"
  attempts: int
  max_attempts: int
  idempotency_key: string    // (event_id, kind)
  input: object
  output?: object
  error?: object
  progress?: { stage, pct, message }
  scheduled_at, started_at?, completed_at?
  worker_id?
  dependencies: [job_id, …]
}
```

Runner guarantees:
- Idempotency by `idempotency_key`
- Retries with backoff, dead-letter after `max_attempts`
- Coach dashboard shows per-client job status

---

## 22. Metrics (new — separate collection for analytics)

```
metrics_events {
  id
  event_name: string
  client_id?, coach_id?
  numeric_value?: number
  labels: { … }
  timestamp
}
```

Common event names:
`roster_upload_to_draft_ready_seconds`,
`llm_calls_per_plan`,
`workout_adaptation_within_sab`,
`workout_adaptation_escalated`,
`plan_approval_time_minutes`,
`objective_completion_rate`,
`decision_records_written`,
`exception_raised`,
`exception_resolved`,
`sab_expansion_event`.

---

## 23. Indexes summary (critical for latency)

```
users:                    {id} unique · {email} unique · {role}
goals:                    {client_id, status} · {client_id, priority}
events:                   {client_id, status, priority, date}
programmes:               {client_id, status}
programme_phases:         {programme_id, ordinal} unique · {status}
training_objectives:      {programme_id, phase_id} · {kind}
objective_exposures:      {objective_id, sequence} unique · {client_id, status} · {assignment_id}
planning_windows:         {programme_id, start_date} · {status}
schedule_days:            {client_id, date} unique · {source_roster_id}
roster_duties:            {schedule_day_id}
flight_sectors:           {duty_id, ordinal}
workout_assignments:      {client_id, date} · {objective_exposure_id} unique · {status}
workout_implementations:  {assignment_id, variant_type} · {client_id, date}
performance_records:      {client_id, date} · {exposure_id}
progression_states:       {client_id, objective_id} unique
readiness_states:         {client_id, as_of_date}
coach_directives:         {client_id, status} · {kind}
plan_drafts:              {programme_id, status}
plan_versions:            {programme_id, version} unique
change_sets:              {draft_id, status}
exceptions:               {client_id, status, severity, triggered_at}
decision_records:         {scope_id, timestamp} · {actor, layer}
jobs:                     {kind, status, scheduled_at} · {idempotency_key} unique
```

---

## 24. Migration mapping summary

| V1 entity | V2 destination |
|---|---|
| `users.profile.main_goal_key` + free text | `goals` records |
| `events` | `events` (add priority + required_disciplines) |
| `rosters.days[]` | `schedule_days` + `roster_duties` + `flight_sectors` |
| `workouts` (approved by coach) | best-effort `objective_exposures` + `workout_assignments` + `workout_implementations` |
| `progression_snapshots` | `progression_states` per objective |
| `users.coach_notes.{preferences,cautions,goal_override,weekly_shape,notes}` | `coach_directives[]` (parsed) |
| `check_ins` + `checkins` | canonical `check_ins` (dedupe on write) |
| `daily_pulse` | `check_ins.kind="daily_pulse"` |
| `reality_events` | `change_sets` (kind=`readiness_response`) |
| `hotels` | Coach-facing notes only; NOT into training path (per §19 of Architecture) |
| `exercises` + `exercises_v2` | canonical `exercises_v2` only |
| `personal_activities` | retained; unrelated to core training path |

Detail sequencing in `V2_MIGRATION.md`.

---

**End of schema document.**
