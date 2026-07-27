# CrewFit V2 Generation Incident — Root-Cause Report

**Scope**: Pietro Sangermano's July 2026 V2 kickoff run.
**Verdict**: Multiple simultaneous failures across data pipeline, scheduling, and workout construction. V2 output cannot be trusted or approved.
**Companion artefacts**: `/app/memory/PIETRO_V2_GENERATION_TRACE.md` + `.json`

---
## P0 — CRITICAL (block approval)

### P0-1  Empty implementations shipped as READY
- **Symptom**: 17 of 18 workout_implementations have `exercises: []` and no `blocks`. Coach drawer renders "EXERCISES (0)". Assignments still marked `status=ready`.
- **Root cause**: `feature_v2_p6_construction.py` slot templates only exist for strength_support. Running/mobility focus values enter P6, an impl row is created with metadata (title, duration, focus, key_session) but no per-sport population step runs. There is no `RunningSessionBuilder` and no `blocks[]` schema in use.
- **Why tests missed it**: existing tests assert "impl exists" or "count > 0", never "impl.exercises or impl.blocks is non-empty".
- **Correct behaviour**: no assignment may become READY until the implementation has either (a) `len(exercises) > 0` for gym focuses, or (b) `len(blocks) > 0` for endurance focuses. Otherwise status stays `building`.
- **Recommended fix order**: (1) introduce `blocks[]` sport-session schema, (2) add per-focus builders, (3) tighten READY gating.

### P0-2  READY doesn't require implementation
- **Symptom**: 3 assignments have NO impl at all yet appear on the calendar and count toward "Ready".
- **Root cause**: P5 sets `status="ready"` (or leaves default) at scheduling time; P6 either fails silently or is not invoked for every assignment; nothing downgrades status when impl is missing.
- **Correct behaviour**: status machine `scheduled → building → implemented → validated → ready → published`. UI must render building/missing states distinctly.

### P0-3  Opportunity = 100 for every day (including layovers)
- **Symptom**: All 62 schedule_days have `derived.training_opportunity = 100`. 20 layover_arrival / layover_departure / turnaround days included.
- **Root cause**: `_training_opportunity(day, burden_score)` in `feature_v2_p4_roster.py` returns 100 when there are no aggregated duty items. Because the parser writes duties INSIDE the roster document (`rosters.days[].duties`) rather than into the `roster_duties` collection, the bridge computes burden from an empty duty list → burden=0 → opportunity=100. Prior/next-day duty, sector length, time-zone crossings, and layover semantics are never read.
- **Correct behaviour**: burden must be a function of (categorical day_type, duty hours, prior 24h duty, next 24h duty, tz_offset). Layover arrival = HIGH burden by default; turnaround = HIGH; standby = MEDIUM; home_day = LOW.

### P0-4  Client-frequency preference ignored → over-scheduling risk
- **Symptom**: Pietro's `training_days_per_week=5` is loaded but never used to cap P5. Scheduler is opportunity-driven — because opportunity is always 100, P5 will lay down sessions on every roster day the objective quota can absorb.
- **Root cause**: `feature_v2_p5_scheduling.py` selects candidate days by opportunity, phase, and prior-key-spacing only. No cap on total sessions per rolling week against `client.profile.training_days_per_week`.
- **Correct behaviour**: hard cap = min(client_preferred, phase_cap). Anything above triggers "Needs coach review".

### P0-5  Programme end anchored to wrong date
- **Symptom**: Pietro's plan ends 2026-09-20 despite marathon date 2027-01-17.
- **Root cause**: `_ensure_programme` in `feature_v2_coach_kickoff.py` returns the existing programme without recomputing `end_date` when `force=False`. If the FIRST kickoff run happened before the event was linked, the programme was written with `today + 12w` (standard_prep_weeks). Subsequent runs preserved the stale window.
- **Correct behaviour**: always recompute end_date from the current active event; log a decision_record every time it changes.

### P0-6  Restrictions + Equipment context collections are dead code
- **Symptom**: `restrictions` and `equipment_contexts` collections have 0 rows for Pietro despite non-empty `profile.injuries` and `profile.equipment`.
- **Root cause**: no writer populates these collections during signup / assessment / DNA update. P6 has read-paths but the DB never has data to read.
- **Correct behaviour**: signup + DNA update endpoints must upsert into `restrictions` (from `profile.injuries`) and `equipment_contexts` (from `profile.equipment` + `home_base`).

---
## P1 — HIGH (material output error)

### P1-1  Assessments/onboarding answers never reach V2 engines
- **Symptom**: `assessments` collection has 1 doc; not consulted by P2/P3/P5/P6.
- **Fix**: a `dna_snapshot` service must project assessments + profile into a single object consumed by every V2 engine at run start.

### P1-2  Decision records exist but drawer queries by assignment_id only
- **Symptom**: 45 decision_records for Pietro, layers WHY/WHAT/WHEN/HOW populated, but drawer "Why this?" is empty because it filters by `scope_id = assignment_id`. Records for scope_kind=objective / programme are never joined.
- **Fix**: drawer must load records where `scope_id ∈ {assignment_id, objective_id, programme_id}` for the tapped assignment.

### P1-3  Running sessions have no sport-specific structure at all
- **Symptom**: long_run/tempo_run/interval_run/easy_run impls have neither exercises nor pace/HR/blocks.
- **Fix**: introduce a `WorkoutImplementation.blocks[]` array. Each block: `{type: warmup|steady|interval|tempo|cooldown, duration_min, pace_target, hr_zone, effort}`. Build a per-focus builder for running (and later cycling/swim/mobility).

### P1-4  Silent P6 failures
- **Symptom**: 3 assignments with no impl. No error, no decision_record.
- **Fix**: every P6 skip must write `decision_record(layer=HOW, outcome=BLOCKED, reason=...)` and downgrade the assignment status.

---
## P2 — MEDIUM (UX / data-quality)

### P2-1  Duty data lives in two shapes
Roster parser writes `rosters.days[].duties` (inline). V2 P4 bridge tries `roster_duties` collection. Two sources, one is ignored. Consolidate.

### P2-2  No READY validator
No end-to-end validator exists that checks (availability, objective quota, recovery, roster compatibility, restrictions, equipment, phase). Only per-writer checks.

### P2-3  Missing DNA fields
No schema field for `preferred_training_days`, `sessions_per_week_min/max`, `preferred_session_length` at the client level. Only `training_days_per_week` and `max_home_minutes` exist — insufficient for a proper scheduler.

---
## Failure classification (final)

**Multiple simultaneous failures**:
1. **UI PROBLEM** — drawer shows empty rows as complete (P0-1, P0-2, P1-2)
2. **CONSTRUCTION PROBLEM** — no sport-specific builders (P0-1, P1-3, P1-4)
3. **DATA PIPELINE PROBLEM** — restrictions + equipment_contexts never populated; assessments unused (P0-6, P1-1)
4. **SCHEDULING PROBLEM** — opportunity=100 for everything, no client-frequency cap (P0-3, P0-4)
5. **PROGRAMMING PROBLEM** — programme end anchored wrongly, phases compressed (P0-5)

The DNA → goal → phase → programme → roster → scheduling → workout → validation chain is **NOT** connected end-to-end for Pietro.

---
## Recommended fix order (do NOT execute until authorised)
1. **P0-3 + P0-4** first — burden/opportunity redesign + client-frequency cap. Without these, every downstream run is wrong.
2. **P0-6** — populate restrictions + equipment_contexts from DNA (single migration + signup hook).
3. **P0-5** — event-anchored programme end + phase recompute on every kickoff.
4. **P1-3 + P0-1** — introduce `blocks[]` schema + per-focus session builders (start with running: warmup / steady / interval / cooldown).
5. **P0-2** — status machine + READY gating.
6. **P1-2** — drawer "Why this?" scope expansion.
7. **P2-\*** — cleanup.

## Tests that need to exist
- `test_burden_layover_arrival_after_longhaul` — burden must be HIGH, opportunity ≤ 30
- `test_scheduler_respects_client_frequency_cap` — 5 sessions/wk cap holds even when opportunity=100 everywhere
- `test_ready_requires_non_empty_implementation` — status stays `building` when exercises + blocks both empty
- `test_running_impl_has_blocks` — running focus must produce at least one block
- `test_kickoff_recomputes_end_when_event_changes`
- `test_restrictions_populated_from_dna_injuries` — signup path
- `test_equipment_context_written_from_dna` — signup path
- `test_decision_records_visible_from_drawer` — join by assignment + objective + programme

**End of report. Awaiting authorisation to proceed with fixes.**
