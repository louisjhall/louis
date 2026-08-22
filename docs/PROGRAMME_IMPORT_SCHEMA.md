# CrewFit · Monthly Programme JSON Import — Schema & ChatGPT Master Prompt

**Version:** iter189n · June 2026  
**Endpoint:** `POST /api/coach/programme-import/preview` → `POST /api/coach/programme-import/apply`  
**Source of truth:** `/app/backend/feature_programme_import.py`  
**Design note:** `/app/memory/MONTHLY_PROGRAMME_JSON_IMPORT_DESIGN.md`

---

## Part 1 · JSON Envelope Schema

### 1.1 Envelope

```jsonc
{
  "$schema": "crewfit://programme-import/v1",   // REQUIRED · exact string
  "meta":  { … ImportMeta … },                   // REQUIRED
  "workouts": [ … WorkoutEnvelopeItem … ],        // REQUIRED · 1 – 62 rows
  "roster_hints": { … free-form dict … },         // OPTIONAL
  "override_policy": "replace_conflicts"          // OPTIONAL · enum below
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `$schema` | string | ✅ | MUST equal `"crewfit://programme-import/v1"` |
| `meta` | ImportMeta | ✅ | See §1.2 |
| `workouts` | list<WorkoutEnvelopeItem> | ✅ | Max 62. Payload cap 512 KB |
| `roster_hints` | dict | ⭕ | Passed through untouched — put flight/duty notes here |
| `override_policy` | enum | ⭕ | `"replace_conflicts"` (default) · `"reject_conflicts"` · `"skip_conflicts"` |

**Hard limits:** `MAX_WORKOUTS = 62`, `MAX_PAYLOAD_BYTES = 512 * 1024`, preview TTL = 10 min.

### 1.2 `ImportMeta`

```jsonc
{
  "client_email":         "louis@example.com",   // one of email or client_id REQUIRED
  "client_id":            "uuid…",               // alternative to email
  "month":                "2026-07",             // REQUIRED · YYYY-MM
  "timezone":             "Europe/London",       // OPTIONAL
  "generated_by":         "chatgpt",             // OPTIONAL · free-form
  "source_prompt_hash":   "sha256:…",            // OPTIONAL
  "author_notes":         "Deload week 3"        // OPTIONAL
}
```

Dates in `workouts[].date` must fall inside `meta.month ± 3 days` (Sun 30th → next-month import is fine).

### 1.3 `WorkoutEnvelopeItem`

```jsonc
{
  "date":              "2026-07-01",              // REQUIRED · YYYY-MM-DD (ISO)
  "title":             "Lower · Strength",         // REQUIRED
  "workout_type":      "strength",                 // OPTIONAL enum · default "other"
  "duration_min":      45,                         // OPTIONAL · positive int
  "location":          "home | gym | hotel | airport | outdoors",  // OPTIONAL · free string
  "equipment_context": "hotel_or_bodyweight",      // OPTIONAL free string
  "rpe":               7,                          // OPTIONAL · 1 – 10
  "coach_notes":       "Deload session, watch RPE",  // OPTIONAL
  "warmup":            [ FlatItem, … ],            // OPTIONAL · default []
  "exercises":         [ MainExerciseBlock, … ],   // REQUIRED slot · may be []
  "cooldown":          [ FlatItem, … ],            // OPTIONAL · default []
  "external_ref":      "coach:louis/2026-07/day-01"  // OPTIONAL · idempotency key
}
```

**Enum · `workout_type`:** `"strength" | "run" | "cardio" | "mobility" | "recovery" | "other"`. Values outside this set do NOT fail — they become tags — but stick to the set for correct client-side classification.

**`external_ref`** — recommended. When set, re-running `/apply` will move a workout to a different day instead of duplicating it (idempotent by ref, not date).

### 1.4 `FlatItem` (warm-up / cool-down)

```jsonc
{
  "ref":          { "name": "Cat-Cow" },   // REQUIRED · see ExerciseRef §1.5
  "sets":         2,                        // OPTIONAL · positive int
  "reps":         "10/side",                // OPTIONAL · int OR string ("8-10", "30 sec", "1 min")
  "duration_sec": 60,                       // OPTIONAL · positive int
  "rest_sec":     30,                       // OPTIONAL · positive int
  "load":         "bodyweight",             // OPTIONAL · free string ("60kg", "@RPE7")
  "tempo":        "3-1-1-0",                // OPTIONAL · eccentric-pause-concentric-pause
  "rpe":          6,                        // OPTIONAL · 1 – 10
  "notes":        "Focus on breath"         // OPTIONAL · free text (also becomes on-screen cue)
}
```

### 1.5 `ExerciseRef` (canonical lookup)

```jsonc
{
  "exercise_id": "uuid…",     // preferred if you know it
  "name":        "Back Squat", // fallback · MUST match CrewFit library exactly for direct match
  "aliases":     ["barbell back squat", "highbar squat"]  // OPTIONAL · fed into fuzzy scorer
}
```

**One of `exercise_id` OR `name` is required.** Direct-match score threshold is **50** — if lower, the resolver flags as `fuzzy_substituted`. Below **10** → new draft is queued (spends LLM credits later; avoid by using canonical names).

### 1.6 `MainExerciseBlock` (discriminated union on `kind`)

#### 1.6a `SingleMainExercise` — `"kind": "single"`

```jsonc
{
  "kind":                       "single",           // REQUIRED · literal "single"
  "ref":                        { "name": "Back Squat" },  // REQUIRED
  "sets":                       4,
  "reps":                       "5-8",              // string OR int
  "duration_sec":               null,               // only for timer/carry moves
  "rest_sec":                   180,
  "load":                       "80% 1RM",
  "tempo":                      "3-1-1-0",
  "rpe":                        8,
  "notes":                      "Pause 1s at depth",
  "equipment":                  "barbell",
  "alternative_exercise_id":    null,               // single alt library id
  "alternative_name":           "Goblet Squat"      // single alt library name
}
```

⚠️ The import envelope carries **one** alternative per exercise (`alternative_*`). The **3-max-alternatives** rule (equipment_swap, easier_regression, injury_mobility) lives in `db.exercises_v2.alternatives_meta[]` and is generated separately by the coach's "Generate Alternatives" button in the library UI — do NOT try to smuggle three via this envelope.

#### 1.6b `GroupBlock` — `"kind": "group"` (supersets · circuits · EMOM · AMRAP · tabata · intervals · complexes)

```jsonc
{
  "kind":                        "group",
  "group_type":                  "superset",              // REQUIRED · enum below
  "group_label":                 "A1/A2",                 // OPTIONAL · label for player UI
  "rounds":                      4,                       // used as sets for each member
  "rest_between_rounds_sec":     120,
  "rest_between_items_sec":      15,                      // default per-item rest
  "work_sec":                    30,                      // EMOM / tabata / interval
  "rest_sec":                    15,                      // EMOM / tabata / interval
  "cap_min":                     12,                      // AMRAP cap
  "notes":                       "As many quality rounds",
  "items": [
    { "ref": { "name": "Bench Press" }, "reps": "6-8", "load": "@RPE 8", "rest_sec": null },
    { "ref": { "name": "Dumbbell Row" }, "reps": "8-10", "rest_sec": null }
  ]
}
```

**Enum · `group_type`:** `"superset" | "triset" | "giantset" | "circuit" | "emom" | "amrap" | "tabata" | "interval" | "complex"`.

`items[i]` is a `GroupMemberItem` — same fields as FlatItem but without its own `sets` (that comes from `rounds`).

---

## Part 2 · Storage — how it lands in Mongo

Once `/apply` runs, each `WorkoutEnvelopeItem` becomes a document in `db.workouts` with:

```jsonc
{
  "id":              "uuid",
  "user_id":         "<client id>",
  "date":            "2026-07-01",
  "title":           "Lower · Strength",
  "focus":           "strength",         // = workout_type
  "workout_type":    "strength",
  "location":        …,
  "equipment_context": …,
  "duration_min":    45,
  "rpe":             7,
  "coach_notes":     …,
  "warmup":          [ /* per-exercise row */ ],
  "exercises":       [ /* per-exercise row · cooldown merged in */ ],
  "cooldown":        [ /* per-exercise row */ ],
  "alternatives":    {},                  // per-workout override map (starts empty)
  "source":          "coach_manual",
  "manual_lock":     true,
  "coach_locked":    true,
  "import_ref":      "<external_ref>",    // used for idempotent re-imports
  "created_at":      "iso",
  "updated_at":      "iso"
}
```

Each per-exercise row has the shape:

```jsonc
{
  "exercise_id":    "uuid | null",         // null → will be draft-created
  "name":           "canonical or raw",
  "sets":           4,
  "reps":           "8-10",
  "duration_sec":   null,
  "load":           "80% 1RM",
  "rest_sec":       180,
  "tempo":          "3-1-1-0",
  "rpe":            8,
  "notes":          "…",
  "cue":            "…",                   // mirrored from notes for guided narration
  "equipment":      "barbell",
  "alternative_exercise_id": "uuid | null",
  "section":        "warmup | main | cooldown",
  "order":          0,
  "logging_type":   "weighted",            // ENRICHED after import (see §3)
  "category":       "legs",                // ENRICHED
  "movement_pattern": "squat",             // ENRICHED
  // Group metadata (only present for GroupBlock rows)
  "group_id":       "grp_ab12ef34",
  "group_type":     "superset",
  "group_position": 0,
  "group_rounds":   4,
  "group_rest_between_rounds_sec": 120,
  "group_label":    "A1/A2",
  "group_work_sec": 30,
  "group_rest_sec": 15,
  "group_cap_min":  12
}
```

---

## Part 3 · `logging_type` — how the client player picks a UI

This field is **enriched by the backend after import** from `exercises_v2.logging_type`. You do NOT set it in the envelope — but you MUST name exercises so the library's `logging_type` matches the intended UI. The valid values are:

| `logging_type` | UI shown to client | Use when |
|---|---|---|
| `"weighted"` | reps × weight grid | Barbell / dumbbell / machine strength |
| `"bodyweight"` | reps × RPE grid | Push-ups, pull-ups, dips, bodyweight squats |
| `"timer"` | live hold timer (mm:ss) | Planks, farmer's carry, dead hang, wall sit, mobility holds |
| `"cardio"` | distance + time logger | Running, walking, biking, rowing, treadmill, swim, erg |
| `"mobility"` | duration-only mobility flow | Stretches, breathwork, cool-down flow |

**Iter189m contract:** an explicit `logging_type` on the library row ALWAYS wins over category/name heuristics. This means the coach can force the correct UI by ensuring library rows carry the right value.

If a library row has no `logging_type` set, the frontend falls back to a name-regex classifier (`workoutMode.ts::isCardioExercise`) which recognises: `run|running|jog|zone[\s-]?[1235]|z[1235]|intervals?|treadmill|row|rowing|erg|bike|biking|cycling|cycle|assault|swim|swimming|sprint|walk|walking|hike|hiking|ruck|rucking|stair(s|master)?|stepper|incline\s?walk|power\s?walk|brisk\s?walk|recovery\s?walk` and holds via `plank|side plank|hollow hold|wall sit|dead hang|l-sit|farmer's carry|suitcase carry|overhead carry|superman hold|bridge hold|hollow rock|dish hold|bear crawl hold|copenhagen (hold|plank)|couch stretch|pigeon (hold|stretch)|isometric`.

The `strength_exclude` guard keeps `walking lunge`, `barbell row`, `dumbbell row`, `db row`, `pendlay row`, `seal row`, `meadows row`, `chest-supported row`, `inverted row`, `single-arm row`, `renegade row`, `t-bar row`, `kroc row`, `upright row`, `face pull`, `cable row`, `iso row`, `smith row`, `helms row`, `hip thrust` in the strength bucket.

---

## Part 4 · Response — `/preview`

```jsonc
{
  "preview_id":     "uuid",
  "expires_at":     "iso",
  "counters":       { workouts_ready, workouts_blocked, exercises_resolved,
                       exercises_direct_id, exercises_fuzzy_substituted,
                       exercises_new_drafts, media_queue_new_items,
                       date_conflicts, supersets, circuits, emom_amrap },
  "blocking_errors": 0,
  "per_workout":    [ { date, status, warnings, matches, … }, … ]
}
```

Call `/apply { "preview_id": … }` within 10 min to commit. Rejects if `blocking_errors > 0`.

---

## Part 5 · Canonical Exercise Names (current library snapshot)

**These are the names the coach has actually programmed — direct-match will score ≥ 50 for these.** Anything outside this list will go through fuzzy match (score 10 – 49) or become a new draft (< 10).

### Strength — main lifts
```
Back Squat · Tempo Back Squat · Bulgarian Split Squat · Dumbbell Bulgarian Split Squat
Goblet Squat · Dumbbell Goblet Squat · Bodyweight Squat · Reverse Lunge · Dumbbell Reverse Lunge
Walking Lunge · Dumbbell Step-Up
Bench Press · Dumbbell Bench Press · Dumbbell Bench Press (Floor or Bench)
Push-Up · Push-up (or incline push-up) · Overhead Press · Dip
Pull-Up · Lat Pulldown · Cable Row · Dumbbell Row · Single-Arm Dumbbell Row (each side)
Band Pull-Apart · Face Pull
Romanian Deadlift · Dumbbell Romanian Deadlift · Single-Leg Romanian Deadlift
Kettlebell Swing · Burpee · Pallof Press
```

### Core
```
Plank · Side Plank · Dead Bug · Bird-Dog · Hollow Hold · Copenhagen Plank
```

### Cardio & conditioning
```
Easy Walk · Easy Run · Long Run — Steady Pace · Incline Walk (treadmill)
Treadmill Warm-up · Cool-down Walk · Zone-2 Intervals · Zone 2 Row · Row 250m
5 min light cardio
```

### Warm-up drills
```
Dynamic Warm-up · Cat-Cow · Cat-cow stretch · Cat-Cow Stretch · Cat-Cow Stretches
Ankle Circles · Ankle Dorsiflexion Mobilisation · Neck Rolls · Shoulder Circles
Band Pull-Aparts · Bird Dogs · Bodyweight Squats · Glute Bridges · Glute Bridge
Single-Leg Glute Bridge · Dynamic Leg Swings (forward/lateral)
Thoracic Rotation (Quadruped) · 90/90 Hip Switch · 90/90 Hip Stretch · 90/90 Hip Switches
World's Greatest Stretch · Down-dog to Cobra Flow · Half-Kneeling Hip Flexor Stretch with Arm Raise
```

### Cool-down & mobility
```
Standing Calf Stretch · Standing Quad + Hip Flexor Stretch · Foam Roll — Calves
Child's Pose · Supine Hip Flexor + Hamstring Stretch · Box Breathing (4-4-4-4)
Deep Breathing x 5 · Green-Space Walk · Calf Raise
```

Case and punctuation matter for the direct-match bonus. If you're unsure of an exact name, still write it clearly — the fuzzy resolver will match it, and if it doesn't, a draft is queued so the same name will match direct-hit next time.

---

## Part 6 · Common failure modes

| Error | Cause | Fix |
|---|---|---|
| `duplicate_dates` | two workouts on same date | one workout per date |
| `envelope has N workouts; hard cap is 62` | > 62 rows | split into two months |
| `payload N bytes exceeds cap 524288` | too much prose in `notes` | trim |
| `preview expired` | > 10 min between preview and apply | re-run preview |
| `blocking_errors_present` | client not resolved, envelope broken | fix and re-preview |
| `skipped_completed` | client already logged that day | change date or leave |
| `skipped_flight_support` | date has an active Flight Support session | leave — flight support wins |
