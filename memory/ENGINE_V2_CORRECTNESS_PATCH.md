# Engine V2 Correctness Patch — 2026-07-27

Fixes applied per user directive after Real Pietro Shadow #1 reveal.

## Files touched (engine only, no dashboard code)

- `/app/backend/feature_v2_sport_configs.py`
  - `PhaseSpec` gained `strength_days_per_week_max: int = 2`
  - New load-bucket classification: `session_load_bucket()`,
    `is_strength_session()`, `is_endurance_hard()`, seven `LOAD_BUCKET_*`
    constants
  - Day-type daily cap helper `profile_daily_cap_for_day_type()`

- `/app/backend/feature_v2_sequencing.py`
  - `PlacementPlan.strength_days_in_week`, `scheduled_minutes_on`,
    `distinct_training_dates_in_week`
  - `hard_days_in_week` now counts ENDURANCE hard only (strength excluded)
  - `validate_placement` re-authored:
    - separate `weekly_strength_cap` reason code
    - `weekly_endurance_hard_cap` (renamed)
    - `daily_time_cap_exceeded` — total minutes ceiling
    - `same_day_endurance_and_strength` (interference rule)
    - support-stacking rule: mobility/activation/recovery may stack on
      a day that already has an anchor IF combined minutes ≤ cap
    - opportunity-floor bypassed for support stacking on an already-anchored day

- `/app/backend/feature_v2_demand_v2.py`
  - `DemandPlan` gained `frequency_derivation`, `dna_gaps`
  - `_client_frequency_bounds` returns full derivation dict
  - `build_demand` produces DNA gap records + full frequency derivation
    (raw quotas, client bounds, phase caps, scaling factor + reason)
  - `schedule_demand` accepts `daily_time_cap_by_date` and does post-schedule
    chronological renumbering of exposure_number per objective_id

- `/app/backend/feature_v2_validators_v2.py`
  - `validate_programme` re-authored:
    - IMPORTANT unfilled → **error** (was silently ignored)
    - SUPPORTING unfilled → warning
    - `weekly_strength_cap_exceeded` check
    - `exposure_numbering_non_chronological` — checks by-date ordering
    - `quota_deficit` fallback error for orphan deficits
    - richer `quota_report` (priority_by_kind, unfilled by priority,
      weekly_strength, daily_totals_min)

- `/app/backend/feature_v2_engine_v2_kickoff.py`
  - Computes `daily_time_cap_by_date` from profile + roster available_time
  - Passes it to scheduler
  - `draft_status` semantics: `ready_for_review` only when validation
    passes; `needs_review` when any error present
  - Draft record now stores `demand.frequency_derivation`, `demand.dna_gaps`,
    top-level `daily_time_caps_min`
  - Response body exposes `frequency_derivation`, `dna_gaps` for coach UI

- `/app/backend/tests/test_engine_v2_invariants.py`
  - Renamed `test_weekly_hard_cap_respected` → `_endurance_hard_cap_`
  - Added:
    - `test_weekly_strength_cap_respected`
    - `test_strength_can_coexist_with_long_run_in_same_week`
    - `test_exposure_numbering_chronologically_monotonic`
  - New `TestCorrectnessPatchDailyTimeCap`:
    - `test_daily_total_never_exceeds_60min_when_max_home_60`
    - `test_no_random_triple_stacking`
    - `test_mobility_may_stack_when_it_fits`
  - New `TestCorrectnessPatchUnfilledSemantics`:
    - `test_unplaced_important_creates_validator_error`
    - `test_no_ready_when_important_missing`
    - `test_supporting_unfilled_is_only_warning`
  - New `TestCorrectnessPatchDNAGaps`
  - New `TestCorrectnessPatchFrequencyDerivation`

## Test result

`python -m unittest tests.test_engine_v2_invariants`
→ **47 tests, 0 failures, 0 errors**

## Real Pietro Shadow #2 result (same window as Shadow #1)

- ok: **False**  status: `needs_review`  (Shadow #1 said ok=True — WRONG)
- required: 20, placed: **19** (was 16), unfilled: 1 (was 4)
- Daily minutes violations: **0** (was 4 days at 115 min > 60 cap)
- Chronological exposure ordering: **all correct** (was [2,1,3,4,6,5,7,8])
- Strength+LR coexist per week: **3 weeks** (was impossible under old buckets)
- Frequency derivation persisted with full scaling reason
- DNA gaps (3) surfaced structurally

## Item-by-item cross-check vs user's Directive

| # | User item | Status |
|---|---|:-:|
| 1 | IMPORTANT unfilled cannot say READY | ✅ needs_review |
| 2 | Strength load bucket separated from endurance | ✅ |
| 3 | Daily availability = total load ceiling | ✅ zero violations |
| 4 | Mobility stacks only when combined fits | ✅ verified in test + real |
| 5 | Exposure ordering chronological | ✅ [1..N] per objective |
| 6 | Failing test that missed old bug | ✅ new by-date test |
| 7 | DNA fallbacks surfaced | ✅ 3 gaps recorded |
| 8 | Single coherent frequency calculation | ✅ derivation dict |
| 9 | Session count vs training days | ✅ distinct-dates helpers |
| 10 | LR not weekend-hardcoded | ✅ still by opportunity |
| 11 | LR spacing configurable | ✅ phase.min_recovery_hours |
| 12 | Deterministic tests run first | ✅ 47 pass before shadow |
| 13 | Then real Pietro shadow | ✅ produced |
| 14 | Acceptance criteria list | ✅ 14/14 covered by tests |
