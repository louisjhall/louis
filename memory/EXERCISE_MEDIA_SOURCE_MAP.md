# CrewFit — Exercise & Media Source Map  ·  Iter 128j
_Read-only. Every pathway that can produce or reference an exercise/movement name in the client experience._

## Table

Legend: **P** = primary  ·  **A** = alternative  ·  **CV** = client-visible

| # | Source | File / function | P/A/Both | Canonical? (`exercise_id`) | Free-text `name`? | Can create new name? | Client-visible? | Media resolution path | Risk |
|---|--------|-----------------|:-:|:-:|:-:|:-:|:-:|--|--|
| 1 | Exercise Library CRUD | `feature_exercise_content.py` `ex_create` / `ex_patch` | P | ✅ writes UUID | ✅ | ✅ | Only via later use | `demo_slots` + Nano-Banana pipeline → `exercise_content_images` | HIGH duplicate risk (no aliases / normalisation) |
| 2 | V2 construction → session_specs | `feature_v2_construction_v2.*` produces `payload.exercises[]` | P | ❌ | ✅ | ❌ (planner picks from templates) | ✅ via `_spec_to_exercises` | Not resolved; free-text names never index into `exercises_v2` | HIGH — largest single break in the chain |
| 3 | V2 warmup / cooldown drills | Same specs, `payload.warmup.drills[]`, `payload.cooldown.drills[]` | Both | ❌ | ✅ | ❌ | ✅ | Not resolved | HIGH |
| 4 | V1 workout fallback library | `feature_workout_fallback._stub_for_session_type` | P + A | ❌ | ✅ | ❌ (hardcoded) | ✅ (V1 clients only; zero remaining today) | Not resolved | LOW-priority (legacy) |
| 5 | Guardrails movement substitution | `feature_workout_guardrails._SUBSTITUTIONS` | A | ❌ | ✅ | ❌ (hardcoded) | ✅ (writes replacement into `workout.exercises[].name`) | Not resolved | MEDIUM |
| 6 | Coach workout editor swap | `feature_coach_workout_editor.coach_workout_swap_exercise` | A | ✅ (validates `exercises_v2`) | – | ❌ | ✅ | Via `exercise_id` → `exercise_content_images` + coach_tasks | LOW |
| 7 | Change-Setup / Equipment adaptation (P7) | `feature_v2_p7_equipment._adapt` → `_select_exercise_for_slot` | A | ✅ | Display only | ❌ | ✅ | Via `exercise_id` | LOW |
| 8 | Variety Engine (GF / Fat Loss / Marathon) | `feature_v2_variety.py` + `workout_slot_templates` | P | ✅ (templates reference `exercise_id`) | – | ❌ | ✅ | Via `exercise_id` | LOW (assuming templates fully populated) |
| 9 | Command Bar (Ask CrewFit LLM) | `feature_v2_coach_command_bar._call_llm` | A (intent) | Intent only | Intent only | **❌ (schema forbids)** | Coach-preview only | – | LOW |
| 10 | Exercises_v2.alternatives[] field | schema field; populated on 120/364 rows | A | ❌ (`list[str]` today) | ✅ | Coach-editable | ⚠ Read-only on client exercise detail | Not resolved (names, not ids) | MEDIUM |
| 11 | Aviation Support protocols | `feature_aviation_support.PROTOCOLS[*].blocks[]` | P | ❌ | ✅ | ❌ (Python-registered) | ✅ | Via `_resolve_frames_and_maybe_queue()` — regex name match | HIGH (5/19 hit rate) |
| 12 | Aviation Support alternatives | Does not exist | – | – | – | – | – | – | – |
| 13 | Personal activity / standby swaps | `feature_personal_activities.py`, `feature_standby.py` | Both | ❌ | ✅ | ✅ (client types name) | ✅ | Not resolved | MEDIUM (client-driven) |
| 14 | Coach deep-edit | `feature_coach_deep_edit.py` | P + A | ⚠ Mixed — can write free-text | ✅ | ✅ | ✅ | Not resolved when free-text | MEDIUM |
| 15 | Roster confirmation / adapt post-roster | `feature_v2_plan_live_adapt.py` | Repopulates specs | Inherits from #2 | – | – | ✅ | – | Inherits HIGH from #2 |

## Aggregate

- **Total unique exercise-name-producing pathways**: 15 (excluding #12 which doesn't exist)
- **Pathways with canonical `exercise_id` throughout**: 4 (#1 writes, #6, #7, #8)
- **Pathways that ship free-text names to clients**: 8+ (worst: #2, #3, #11)
- **Pathways where the LLM can invent an exercise**: **0**
- **Pathways with orphan-to-canonical resolution attempts**: 1 (`feature_flight_support_media` — regex name match, 5/19 hit rate)

## Media-relevant collections

| Collection | Purpose | Populated? |
|-----------|---------|:-:|
| `exercises_v2` | Canonical library | ✅ 364 rows |
| `exercises` | Legacy V1 library | ⚠ still 257 rows |
| `exercise_content` | Old name, unused | ⛔ 0 rows |
| `exercise_content_images` | Persona-slot images | ✅ 144 rows, 133 ready |
| `media_queue` | Needs-media queue (Flight Support) | ⚠ only 4 rows — under-populated |
| `coach_tasks` (`exercise_needs_*`) | Older needs-media todos for training | populated |
| `programme_exercises` | Programme-scope exposure counts | inherited |

## Two independent queues today

1. `run_exercise_media_scan()` writes `coach_tasks` rows (used by Coach Dashboard "Exercise needs media" tile).
2. `_upsert_media_queue()` writes `media_queue` rows (used by Flight Support media resolver).

They do **not** share priority logic, ordering, or a shared "current Live exposure" signal.

## Feasibility summary

- **A single unified `media_queue`**: feasible; just widen the collection to accept training rows and back-fill from `coach_tasks`.
- **Client-visible-alternative tracking**: feasible after migrating `alternatives[]` to id-based.
- **Flight Support canonicalisation**: 14 movements need Library rows created (small).
- **V2 construction canonicalisation** (biggest lift): planner and client bridge need to emit `exercise_id` end-to-end for every primary session exercise + every warmup/cooldown drill.
