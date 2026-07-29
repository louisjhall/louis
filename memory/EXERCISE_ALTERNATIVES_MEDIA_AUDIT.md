# CrewFit — Exercise Alternatives & Substitution Audit  ·  Iter 128j
_Read-only. Audits every current pathway that can present an alternative movement to a client or coach._

## 1. Pathways found

| # | Pathway | File / function | Kind | Uses `exercise_id`? | Uses free-text `name`? | Can create new name? | Client-visible? |
|---|---------|-----------------|------|:-:|:-:|:-:|:-:|
| 1 | V1 Workout Fallback library                | `feature_workout_fallback.py` `_stub_for_session_type` (lines 246+)          | Session stub with `alternatives{home,hotel,no_equipment,easier,harder}` | ❌ | ✅ (English sentences) | ❌ (hardcoded strings) | ✅ (still rendered on V1 workouts) |
| 2 | Guardrails movement-pattern substitution   | `feature_workout_guardrails._SUBSTITUTIONS` (lines 70+)                     | Rule-based swap by pattern → replacement `name` | ❌ | ✅ | ❌ | ✅ (writes new name into workout doc) |
| 3 | Coach workout editor swap                  | `feature_coach_workout_editor.coach_workout_swap_exercise` (line 232)       | Coach picks a Library row → replaces exercise | **✅** (requires `replacement_exercise_id`, checks `exercises_v2`) | ⛔ | ⛔ | ✅ |
| 4 | Change-Setup / Equipment adaptation (P7)   | `feature_v2_p7_equipment._adapt` (line 141)                                 | Rebuilds slots for new equipment set via `_select_exercise_for_slot` | **✅** (stores `exercise_id`) | Display-only | ⛔ | ✅ |
| 5 | V2 construction — session_specs.payload    | `feature_v2_construction_v2.*` → `_spec_to_exercises` (`feature_v2_client_bridge.py:133`) | Free-text `name` list; NO alternatives, NO ids | ❌ | ✅ | ⛔ | ✅ |
| 6 | Ask CrewFit / Command Bar                  | `feature_v2_coach_command_bar._call_llm` + `_SYSTEM_PROMPT`                 | LLM parses coach intent; can propose `swap_exercise`; execution deterministic in Python | Intent only | Intent only | **NO** (schema has no `new_exercise_name` field, LLM cannot invent) | Coach preview only |
| 7 | Exercise Library CRUD                      | `feature_exercise_content.ex_create` (line 454)                             | Coach types name → row created with UUID id | ✅ (writes) | ✅ | **✅** | Only via subsequent use |
| 8 | Aviation Support protocols                 | `feature_aviation_support.PROTOCOLS[*].blocks[]`                            | Hardcoded `[{name, cue, duration_sec}]` | ❌ | ✅ | ⛔ | ✅ |
| 9 | Aviation Support alternatives              | none exist today                                                            | – | – | – | – | – |
| 10| Legacy `exercises_v2.alternatives[]` field | schema field, populated on 120/364 rows                                     | Free-text names | ❌ | ✅ | ⛔ | ⚠ Only if a client actually opens the exercise detail (needs UI confirmation) |
| 11| Standby / Personal activity swaps          | `feature_standby.py`, `feature_personal_activities.py`                      | Free-text session titles | ❌ | ✅ | ⛔ | ✅ |

**Canonical link summary**: only **3 of 11 pathways** (#3, #4, #7) resolve to a canonical `exercises_v2` row. All others live on free-text strings.

## 2. Client-visible alternatives — do they exist today?

- **V2 workouts**: `_spec_to_exercises` returns exercises; the wrapper `synth_workout_from_placement` **hardcodes `"alternatives": []` (line 200)**. → No V2 client currently sees any alternative.
- **V1 workouts**: the `alternatives{home,hotel,no_equipment,easier,harder}` dict from `_stub_for_session_type` IS surfaced. These are English coaching sentences ("Treadmill if outdoor isn't possible.") — the client is not offered a swap UI, they are read as text.
- **Client exercise detail screen**: reads `exercises_v2.alternatives[]` (free-text list). If a client opens a strength exercise detail, they see the list. **They cannot tap on an alternative to swap.** So today the alternatives are *displayed* but not *selectable*.
- **Coach Library**: coach can see `alternatives[]` as metadata on an exercise; not a first-class action.
- **Coach workout editor**: the swap dialog searches the whole Library (`exercises_v2`) — not driven by "alternatives on the current exercise".

**Conclusion**: today's alternatives are **read-only English hints**, not tap-to-swap options. That means we do not yet have a "presentation event" to track.

## 3. Client-visible alternative invariant — feasibility

Future rule: any client-visible alternative must be a canonical `exercises_v2` row and enter the media queue when incomplete.

- If we adopt this, the source of the alternative list must be **structured** — a list of `exercise_id`s, not English sentences.
- Migration:
  1. `exercises_v2.alternatives[]` field: change from `list[str]` to `list[exercise_id]` (or a companion `alternatives_v2[]` of ids); back-fill by fuzzy-matching.
  2. `feature_workout_fallback` alternatives block: kill (V1 flow no longer needed post V2 consolidation).
  3. `feature_workout_guardrails._SUBSTITUTIONS`: rewrite to look up `exercises_v2` by `movement_pattern + equipment` and pick a target `exercise_id`. Store the `swapped_to_exercise_id`.
  4. Client detail screen: render alternatives from ids, offering a swap UI. This is where presentation-tracking is easiest to add.

## 4. Alternative-usage states we can distinguish today

| State | Can we know it today? |
|-------|:-:|
| **AVAILABLE ALTERNATIVE** (exists in the pool for this slot) | ⚠ Partial — only for `exercises_v2.alternatives[]` and Change-Setup pool |
| **PRESENTED TO CLIENT** (displayed in an alternative list) | ❌ No event / no telemetry |
| **SELECTED BY CLIENT** | ⚠ Not for V2 (no swap UI); ✅ for V1 coach editor swap → writes `swapped_from` block |
| **CURRENT IMPLEMENTATION** (client is doing it now) | ✅ (workout.exercises[]) |
| **PREVIOUSLY USED** | ⚠ Only via `last_used` on `exercises_v2` (computed by scan) |
| **COACH-SUGGESTED** | ⚠ Via `swapped_by` in coach editor |
| **SYSTEM-SUGGESTED** | ❌ No signal exists |

## 5. LLM — exact role

- Only one LLM pathway currently touches exercises: the **Coach Command Bar** (`feature_v2_coach_command_bar.py`).
- System prompt: "You do NOT invent new training rules; you translate coach intent into structured proposals that CrewFit's V2 planner will apply after coach approval."
- Return schema forbids `new_exercise_name` / `alternative_exercises` / any free-text exercise field. Allowed `kind` values include `swap_exercise` — but the LLM returns intent only; the deterministic Python side maps proposal → mutation.
- **The LLM cannot invent primary exercises. The LLM cannot invent alternatives.** Any exercise a client eventually sees must have entered CrewFit via one of the deterministic pathways in §1.

## 6. Duplicate risk

- The 120 `exercises_v2` rows with populated `alternatives[]` contain **free-text strings** — many of which do not exist as separate rows themselves. Common examples like `"Dumbbell RDL"`, `"Bulgarian Split Squat"`, `"Half-Kneeling Cable Press"` may or may not resolve. A quick sample against `exercises_v2.exercise_name` regex showed ≤ 50% hit rate.
- Risk: **MEDIUM.** Migrating these strings to ids will require a normalisation pass with a confidence threshold + coach review queue (`ALTERNATIVE NEEDS REVIEW` per brief §30).

## 7. Change-Setup / equipment adaptation

- `feature_v2_p7_equipment._adapt` (line 141) is the cleanest example we have: it rebuilds the workout slot-by-slot, uses `_select_exercise_for_slot(slot, equip_set, avoid_regions)` which queries `exercises_v2`, and returns rows carrying `exercise_id` (line 224). Media queue coverage is inherited from the canonical rows.
- Alternatives offered BEFORE the coach commits the setup: none — the current UI presents the SINGLE resulting workout, not multiple options.

## 8. Feasibility of "presentation event" tracking

Given the current UI never actually offers a tap-to-swap, we don't have "presented" events. **Two options going forward:**

- **A. Deterministic exposure inference.** If an alternative list is derived from `exercises_v2.alternatives[]` (once migrated to ids), we can *deterministically* know at scan time which alternatives are exposed for which sessions. No new event needed.
- **B. Explicit UI event.** Emit `alt_presented` when the client opens the alt list. Cheap to add if we ever build the swap UI.

Recommendation: **A**. It avoids client-side telemetry and cleanly ties into the media_queue.

## 9. Queue explosion guard

- Only exercises that are `exercises_v2.alternatives[]` of a currently-scheduled canonical exercise should enter elevated priority — NOT every theoretically-compatible movement in the Library.
- Since alternatives are stored on the parent row, this is a simple SQL/Mongo join once the ids exist.

## 10. Recommended architecture (alternatives + substitutions only)

```
Coach or Change-Setup produces a swap
     │
     ▼
Look up target `exercise_id` in exercises_v2
     │
     ▼
Persist { original_exercise_id, replacement_exercise_id, reason }
     │
     ▼
Recompute exposure → media_queue for replacement
     │
     ▼
Client sees replacement with persona-fallback frames
```

For alternatives displayed on a client's exercise detail:

```
Client opens Goblet Squat detail
     │
     ▼
UI reads exercises_v2.alternatives_v2[] → [id1, id2, id3]
     │
     ▼
Each alt row is a canonical exercises_v2 → media state known
     │
     ▼
Alt entries with incomplete media flagged in media_queue
before client is offered the swap
```

## 11. Component classification

| Component | Class |
|-----------|-------|
| `exercises_v2.alternatives[]` (list[str]) | **EXTEND → list[exercise_id]** |
| `feature_workout_fallback` alternatives dict | **REMOVE LEGACY** |
| `_SUBSTITUTIONS` map in `feature_workout_guardrails` | **REWRITE** to reference `exercise_id` |
| Command Bar `swap_exercise` | **KEEP** (already deterministic) |
| Coach workout editor swap | **KEEP** |
| Change-Setup P7 alternatives | **KEEP** (canonical) |
| Alternatives on client exercise detail | **NEEDS DECISION** — either surface as tappable (add swap UI) or hide until migrated |
