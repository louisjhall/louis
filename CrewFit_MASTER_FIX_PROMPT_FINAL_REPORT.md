# CrewFit — MASTER FIX PROMPT · FINAL REPORT

**Date:** 2026-07-21
**Iteration:** 81 (Phases 1-6)
**Handover reference:** `/app/CrewFit_Roster_Programme_Equipment_Hotel_Progression_Handover.md`
**Test status:** 110/110 tests pass across all 5 phases + 1 designed-skip

---

## Executive Summary

The Master Fix Prompt (submitted at message #418) identified four structural gaps
between what the app promised and what it actually delivered:

1. **No true hotel/layover system** — clients on layovers got generic hotel workouts
   that didn't match the actual gym at the hotel.
2. **No strict equipment matching** — bench-press exercises could appear even when
   the client had no bench, with no signal to coach or client.
3. **No reactive progression** — the same programme regenerated each week regardless
   of whether the client crushed it or missed sessions.
4. **No client-visible "why this changed" explanations** — regenerated workouts felt
   opaque and arbitrary to the client.

All four gaps are now closed. The system is roster-aware, hotel-aware,
equipment-strict, and progression-reactive. The client sees the reasons; the coach
sees the queue.

---

## What shipped (by phase)

### Phase 1 — Hotel System · **DONE**
- New `feature_hotel_system.py`:
  - `compute_layover_hours(day, next_day)` — measures the free-time window
  - `classify_stay()` — returns `layover` / `turnaround` / `home` / `off` / `flight` / `unknown` with **18-hour** threshold
  - `resolve_gym_equipment()` — maps `gym_type` → equipment presets
  - `is_bodyweight_only()` — unknown hotel / gym_type="none" / empty equipment → bodyweight-safe fallback
  - `is_low_confidence()` / `confidence_score()` — powers coach review queue
  - `reason_for()` — client-facing "Why this changed" strings
- Extended `HotelBody` model with `gym_type`, `safe_outdoor_run`, `verified_by_coach`.
- 6 new endpoints:
  - `GET /api/hotels/lookup?query=` — unified fuzzy search
  - `POST /api/hotels/{id}/confirm` — client bumps confidence, merges equipment
  - `PATCH /api/hotels/{id}` — non-bumping field update
  - `GET /api/hotels/pending-for-today` — client queue: layovers ≤7 days out with missing/low-conf hotels
  - `GET /api/coach/hotels/review-queue` — coach queue
  - `POST /api/coach/hotels/{id}/verify` — coach verification (+0.3 confidence)
- Wired hotel context into `feature_workout_fallback.build_template_plan(hotel_lookup=...)` at all 5 callsites.
- Bodyweight-safe `strength_support` template for unknown-hotel layovers.

**Frontend:**
- `HotelSetupCard` on client `/home` — auto-hides when no pending layovers.
- New `/hotel-setup` screen — fuzzy hotel search (verified badge), 5 gym-type presets, 13 equipment chips, outdoor-run toggle, notes. Save = upsert → attach → confirm.

### Phase 2 — Strict Equipment Matching · **DONE**
- New `feature_equipment_matcher.py`:
  - `CANONICAL_EQUIPMENT` + aliases (`"DB" → dumbbells`, `"Hotel Gym" → FULL_GYM_EXPANSION`)
  - ~35 regex patterns covering barbell / bench / cable / machine / dumbbell / kettlebell / pull-up / cardio / bands / TRX / box / med ball
  - `required_equipment()` — library `equipment_type` first, then name regex
  - `validate_exercise_equipment()` — any-of matching + friendly reason strings
  - `enforce_equipment_gate()` — mutates workout with `equipment_check` / `equipment_reason` / `equipment_required` per exercise and `needs_coach_review` + `change_reason` on workout
- Wired into `feature_v2_resolver.apply_resolver_to_workouts`:
  - Layover w/ known hotel → uses `resolve_gym_equipment(hotel_doc)`
  - Layover w/ unknown hotel → bodyweight-only
  - Home day → client profile equipment
- New resolver stats: `equipment_failures`, `workouts_needs_review`.
- Extended `WorkoutUpdateBody` with `change_reason` + `needs_coach_review` for coach manual override.

**Frontend:**
- `/home` — compact reason pill on each workout row (testID `workout-reason-<id>`).
- `/workout/[id]` — brand-tinted "WHY THIS CHANGED" banner above rationale (testID `workout-change-reason`).
- Per-exercise amber warning (testID `ex-eq-warn-<idx>`) when `equipment_check === "fail"`.

### Phase 3 — Reactive Progression + Your Progress · **DONE**
- New `feature_progression.py`:
  - `iso_week_bounds()` / `week_key()` helpers.
  - `compute_status(workouts, week_start, week_end)` — pure rule engine:
    - `progressing_well` (adherence ≥80% + RPE 6-8.5) → bump load
    - `maintain` (adherence 60-79%) → hold
    - `reduce_load` (adherence <60% OR avg RPE ≥9 OR missed key session)
    - `deload` (2+ sessions ≥9.5 RPE + 3+ completed) → planned deload
  - Emits `status_label` / client `reason` / `coach_note`.
  - Persists to `progression_snapshots` collection.
  - `on_workout_completed(db, user, workout)` — fires ONLY when workout was the LAST planned session of the ISO week.
- 5 new endpoints:
  - `GET /api/progress/current` — latest snapshot or {}
  - `GET /api/progress/history?weeks=8` — last N (clamped 1..52)
  - `POST /api/progress/recompute` — manual refresh
  - `GET /api/coach/clients/{cid}/progress/current` — coach-only
  - `GET /api/coach/clients/{cid}/progress/history` — coach-only

**Frontend:**
- `ProgressCard` on client `/home` (testID `progress-card`) — auto-hides with no snapshot; status pill + reason + 3-col metrics.
- New `/your-progress` screen — history list of last 8 snapshots, recompute button, empty state.

### Phase 4 — Coach Dashboard (Hotels + Progression) · **DONE**
- Backend: `_client_summary()` and `coach_client_detail` attach `progression_pill` (latest snapshot).
- `counts.hotels_pending_review` on `/api/coach/dashboard`.
- Frontend:
  - Coach `/(coach)/overview` — new KPI "HOTELS TO REVIEW" (tappable), tappable alert row, HOTELS header button, `ProgressionPill` on each client row.
  - New `/coach/hotels` review queue — chip toggles (PATCH), Verify button (POST + removes from queue), empty state.
  - Coach client detail — progression pill + coach_note under name.

### Phase 5 — Progression-Aware Marathon · **DONE**
- `feature_progression.py` additions:
  - `PROGRESSION_SCALARS` = `{progressing_well: 1.07, maintain: 1.00, reduce_load: 0.88, deload: 0.55}`
  - `PROGRESSION_REASONS` — 4 client-facing "why this changed" strings
  - `scale_endurance_session()` — scales `duration_min` (nearest 5 min, floored 15) and reps regex ranges; stamps `progression_status`; appends to (never clobbers) existing `change_reason` from Phase 1/2.
  - `get_current_status(db, user_id)` — reads latest snapshot.
- Wired `progression_status` kwarg into `build_template_plan` at all 5 callsites. Only `long_run` / `tempo` / `intervals` / `easy_run` slots get scaled.

### Phase 6 — Final Report + Test Closeout · **DONE (this document)**

---

## Test Coverage

| Phase | Test file | Cases | Passing |
|-------|-----------|------:|--------:|
| 1 | `test_iter81_phase1_hotel_system.py` | 27 | 27 |
| 1 | `test_iter81_phase1_verify.py` (testing-agent added) | 11 | 11 |
| 2 | `test_iter81_phase2_equipment_gate.py` | 25 | 25 |
| 2 | `test_iter81_phase2_resolver_integration.py` (testing-agent added) | 4 | 4 |
| 3 | `test_iter81_phase3_progression.py` | 19 | 19 |
| 3 | `test_iter81_phase3_integration.py` (testing-agent added) | 3 | 3 |
| 4 | `test_iter81_phase4_coach_dashboard.py` | 5 | 5 |
| 5 | `test_iter81_phase5_progression_scaling.py` | 14 | 14 |
| 5 | `test_iter81_phase5_http_flow.py` (testing-agent added) | 2 | 2 |
| **Total** | | **110** | **110** |

Plus **1 designed skip** (Phase 5 end-to-end propagation — requires marathon-profile seed client).

Zero regressions vs pre-existing failing tests in iter58 / iter64 / iter68 / iter79.
Lint clean across all Python + TypeScript files.

---

## New / modified files

**Backend (new modules):**
- `feature_hotel_system.py` (~230 LOC) — Phase 1
- `feature_equipment_matcher.py` (~275 LOC) — Phase 2
- `feature_progression.py` (~330 LOC) — Phase 3 + 5

**Backend (extended):**
- `server.py` — HotelBody+HotelConfirmBody models, 6 hotel endpoints, 5 progression endpoints, WorkoutUpdateBody extended, _client_summary+coach_client_detail attach progression_pill, coach_dashboard exposes hotels_pending_review
- `feature_workout_fallback.py` — `build_template_plan(hotel_lookup, progression_status)` kwargs; bodyweight-safe strength_support; endurance scaling on long_run/tempo/intervals/easy_run
- `feature_v2_resolver.py` — strict equipment gate integration; hotel/home equipment routing
- `feature_programme_quality.py`, `feature_roster_confirmation.py`, `feature_coach_workout_editor.py` — updated `build_template_plan` callsites

**Frontend (new screens & components):**
- `src/components/HotelSetupCard.tsx`
- `app/hotel-setup.tsx`
- `src/components/ProgressCard.tsx`
- `app/your-progress.tsx`
- `app/coach/hotels.tsx`

**Frontend (extended):**
- `app/(client)/home.tsx` — HotelSetupCard + ProgressCard + workout-reason pill
- `app/workout/[id]/index.tsx` — WHY THIS CHANGED banner + per-exercise amber equipment warning
- `app/(coach)/overview.tsx` — HOTELS TO REVIEW KPI + tappable alert row + HOTELS header + ProgressionPill
- `app/coach/client/[id].tsx` — progression pill + coach_note

**Tests:** 9 new files, 110 cases.

**Docs:**
- `/app/test_result.md` — updated with 5 iteration blocks
- `/app/memory/test_credentials.md` — unchanged (credentials still valid)
- `/app/CrewFit_MASTER_FIX_PROMPT_FINAL_REPORT.md` (this file)

---

## Design decisions / trade-offs

1. **Layover threshold set to 18h** — confirmed with product. Anything below is turnaround = mobility only.
2. **Crowd-sourced hotels, no Google Places API** — deferred to MVP with client submissions + coach verification for now. Confidence system provides a natural filter.
3. **Snapshot trigger fires only on last workout of week** — avoids computing multiple times per week and gives the client the most complete data. Manual `/progress/recompute` still available.
4. **Change reason is APPEND, not REPLACE** — a Phase 1 hotel reason + Phase 2 equipment reason + Phase 5 progression reason can all coexist on the same workout, joined by "  · ".
5. **Server.py refactor was deferred** — not in the master fix prompt scope; still a valid backlog item.

---

## Known behaviour / limitations

- **Hotel Places API integration** is deferred — clients enter hotels manually. When we onboard the API later, the same `POST /api/hotels` endpoint accepts a `place_id` field.
- **Progression snapshot requires ≥1 planned workout with content in the week** — placeholder days (empty exercises) are excluded from `sessions_planned`.
- **Sim-day / annual-leave classifier** — currently returns `off` and produces no card, matching the pre-Phase-1 behaviour.

---

## Beta readiness

The four handover gaps are closed. The system now:

- Matches workouts to the actual gym at the actual hotel on the actual layover day
- Refuses to prescribe bench exercises when the client has no bench (flags for coach review)
- Adapts next week's plan to how last week actually went (completed vs missed, RPE)
- Explains every regenerated workout to the client in plain English

Combined with the existing goal-aware programme generator (marathon prep, strength, phases, weekly-shape idealisation) and the coach UX polish work from iter 75-80, this closes the beta-readiness gap for 20-50 cabin-crew users.

---

*Report generated 2026-07-21 · CrewFit iter 81 Phase 6*
