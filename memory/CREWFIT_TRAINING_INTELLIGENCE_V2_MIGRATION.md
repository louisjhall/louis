# CrewFit V2 — Migration & Roadmap

Companion to `V2_ARCHITECTURE.md`. Sequences the V1 → V2 transition safely.

Design principle: **no live client is disrupted until their coach explicitly opts them in.** V2 runs alongside V1 in shadow, then per-client behind flags, then default.

---

## 1. Migration philosophy

Three axes we protect at every phase:

1. **Client data integrity** — no historical workouts, PRs, check-ins, or roster records are lost or altered
2. **Coach control continuity** — coach can always fall back to V1 for a client at any time
3. **No silent behaviour change** — clients only see V2-generated plans after coach promotes them

---

## 2. V1 → V2 gap analysis (per subsystem)

| System | V1 | V2 requirement | Action | Complexity | Risk |
|---|---|---|---|---:|---|
| Goal storage | Free-text `main_goal_key` + 4 fallback fields | `goals[]` records with primary/secondary/weights/target_date/timeline | **BUILD + MIGRATE** | M | M |
| Goal engine | `_resolve_goal_key` regex + `GOAL_MATRIX` | `GoalDefinition` catalog + weighted allocation | **BUILD** | M | L |
| Multi-goal | None | First-class | **BUILD** | M | M |
| Phase engine | Modulo 4 + race-anchored heuristics | `programme_phases` records with entry/exit gates | **REPLACE** | M | M |
| Event engine | Only newest active event read | Multi-event A/B/C with conflict engine | **MODIFY** | M | M |
| Roster parser | Etihad + Emirates + LLM fallback | Same parsers, feed `schedule_days`+`roster_duties`+`flight_sectors` | **KEEP + WRITE-ADAPTER** | S | L |
| Roster storage | `rosters.days[]` embedded | Normalised entities | **BUILD + MIGRATE** | M | M |
| Duty burden | Not computed | Deterministic 0-100 score | **BUILD** | S | L |
| Training-opportunity score | Not computed | Deterministic 0-100 score | **BUILD** | S | L |
| Workout generation | `_generate_month` monolithic prompt | 3-layer pipeline (WHAT/WHEN/HOW) | **REPLACE** | XL | H |
| Slot templates | None | `workout_slot_templates` seeded library | **BUILD** | L | M |
| Exercise library | `exercises` + `exercises_v2` | Consolidated `exercises_v2` only | **MODIFY + DEDUPE** | M | M |
| Progression | `progression_snapshots` weekly + strength_overload matrix | Per-objective `progression_states` with per-exercise load memory | **REPLACE** | L | M |
| Performance capture | `workouts.completion{}` + `workout_sets` | `performance_records` with per-set arrays | **MODIFY** | M | L |
| Readiness | `feature_live_state` | `readiness_states` (very similar) | **KEEP + RENAME** | S | L |
| Injury enforcement | LLM-only (Rule 5b) | Deterministic post-filter | **BUILD** | S | M |
| Coach notes | `users.coach_notes` free-text slots | `coach_directives[]` structured | **BUILD + PARSE** | M | M |
| Reality flow | Full LLM every time | Structured resolver + LLM fallback | **MODIFY** | M | L |
| DRAFT vs LIVE | None (workouts always LIVE) | Two states, versioning, snapshots | **BUILD** | L | H |
| Approval | Per-workout coach_locked | Batch, per-scope | **REPLACE** | M | M |
| Locks | `coach_locked` bool | Explicit `locks` entity across target types | **MODIFY** | S | L |
| Regeneration | Full-month `_generate_month` re-run | Incremental replan | **REPLACE** | L | H |
| Command bar | None | AI intent parser → structured proposal | **BUILD** | M | L |
| Decision audit | None | `decision_records` per material decision | **BUILD** | M | L |
| Job runner | `asyncio.create_task` fire-and-forget | Reliable queue + idempotency + retries | **REPLACE** | M | M |
| Hotel database | Global `hotels` collection with confidence | REMOVED from training path; kept as coach notes only | **DEPRECATE** | S | L |
| Equipment | `HOTEL_EQUIPMENT_FIELDS` + `HOTEL_EQUIPMENT_KEYS` (two vocabularies) | Single canonical enum + `EquipmentContext` | **MODIFY** | M | L |
| Client change-equipment flow | Not implemented (partial via reality) | Full flow with SAB | **BUILD** | M | L |
| Coach dashboard | Client-months navigator | ROSTER + PLAN workspace with batch approve | **REPLACE** | L | M |
| Client dashboard | Programme status card + calendar | LIVE-only view, no DRAFT visibility | **MODIFY** | S | L |
| Coach roster upload (Iter 109) | Already built | KEEP; wire into V2 pipeline | **KEEP** | S | L |
| `parser_constraints` safety net | Retained | Runs as tier-6 rule in V2 precedence | **KEEP** | S | L |
| Traffic-light variants | Green/amber/red per workout | Persist as WorkoutImplementation variants | **KEEP** | S | L |
| PAIN_REGION_AVOID | LLM Rule 5b only | Deterministic tier-1 rule | **KEEP + PROMOTE** | S | L |
| `feature_v2_resolver` | Snaps LLM names → approved | Now unused because construction is slot-based | **DEPRECATE** | S | L |
| `feature_workout_fallback` templates | Deterministic fallback | Absorbed into `workout_slot_templates` | **MODIFY** | M | L |

**Legend:** KEEP · MODIFY · REPLACE · BUILD · DEPRECATE

**Complexity:** S ≤ 3 dev-days · M 4-10 · L 2-4 weeks · XL 1-3 months

---

## 3. Twelve implementation phases (dependency-ordered)

| # | Phase | Complexity | Depends on | Shippable behind flag |
|---:|---|---:|---|---|
| P1 | **State foundation** — Draft/Live/Version/Approval/Lock/ChangeSet/DecisionRecord entities + APIs | L | — | yes |
| P2 | **Goals + Timelines + Phases** — new entities, admin catalog of GoalDefinition & PhaseDefinition | M | P1 | yes |
| P3 | **Training-demand engine (WHAT)** — TrainingObjective + ObjectiveExposure + planning_windows | L | P2 | yes |
| P4 | **Roster structured facets** — schedule_days + roster_duties + flight_sectors + duty_burden + opportunity | M | P1 | yes |
| P5 | **Scheduling engine (WHEN)** — assignment planner + cascade + precedence engine + validation V1..V16 | L | P3, P4 | yes |
| P6 | **Workout construction (HOW)** — slot templates + eligibility + ranking + AI polish + validation | XL | P3, P5 | yes |
| P7 | **EquipmentContext + adapt flow** — client change-equipment, coach override, SAB machinery | M | P6 | yes |
| P8 | **Progression state + PerformanceRecord** — per-objective state, per-exercise load memory feed-forward | L | P6 | yes |
| P9 | **Event countdown + phase transitions** — deterministic countdown, transition proposals, coach approval | M | P2, P3 | yes |
| P10 | **Readiness + Today's Reality structured layer** — chip resolver, escalation to LLM | M | P3, P6 | yes |
| P11 | **Coach Dashboard V2 (ROSTER + PLAN)** — full workspace, command bar, batch approve, exceptions | L | P1-P8 | yes |
| P12 | **Automation pipelines + shadow mode + observability** — job runner, metrics, shadow evaluation | M | all | yes |

**Total est.** ~5-7 months for two-engineer team with full test coverage.

---

## 4. Ordering rationale

- **P1 first** — nothing else is safe without Draft/Live state
- **P2, P3 before P5** — must define WHAT before scheduling WHEN
- **P4 in parallel with P2/P3** — roster normalisation is independent of goals
- **P5 before P6** — must schedule before constructing
- **P6 is the largest** — slot templates + AI polish + validation
- **P7 depends on P6** — equipment adaptation needs the construction engine
- **P8 in parallel with P7** — progression only needs completed workouts to feed on
- **P9 in parallel with P6** — event countdown can be built early
- **P10 after P3** — reality flow modifies exposures
- **P11 (UX) last of client-facing** — build once the engine is solid
- **P12 throughout** — job runner should be scaffolded during P1 and expanded across phases

---

## 5. Feature flags

Every phase ships behind a per-client flag:

```
users.profile.v2_flags = {
  state_foundation_enabled: bool,      // P1
  demand_engine_enabled: bool,         // P3
  scheduling_v2_enabled: bool,         // P5
  construction_v2_enabled: bool,       // P6
  equipment_adaptation_v2_enabled: bool,// P7
  progression_v2_enabled: bool,        // P8
  events_v2_enabled: bool,             // P9
  reality_v2_enabled: bool,            // P10
  coach_dashboard_v2_enabled: bool,    // P11
  shadow_mode: bool,                   // P12
  v2_default: bool,                    // master switch
}
```

Default state after each phase ships: `false` for existing clients, `false` for new clients. Coach flips per-client via admin panel.

Fallback: if any V2 code path throws, the request falls back to V1 automatically, and a `DecisionRecord` marked `outcome=BLOCKED` captures the failure.

---

## 6. Data migration steps

### Phase M1 — read-only preparation (before P1 ships)
1. Add all V2 collections with correct indexes
2. Add `v2_flags` to `users.profile`
3. Snapshot production DB to isolated staging

### Phase M2 — Draft/Live foundation (with P1)
1. Backfill each active `programme` record: current LIVE = latest coach-approved snapshot of `workouts` for that client (best effort — for clients without coach-approved workouts, treat the current `workouts` set as v1 LIVE)
2. Create initial `plan_version` per programme = v1 LIVE
3. Create `plan_snapshots` immutable copies

### Phase M3 — Goals (with P2)
1. Read each client's `profile.main_goal_key` and free-text fields
2. Emit primary `goals` doc with derived `goal_id_taxonomy`
3. If `coach_notes.goal_override` present → override
4. Preserve original V1 fields (read-only) for revert path

### Phase M4 — Roster (with P4)
1. For each active roster, expand `rosters.days[]` → `schedule_days` + `roster_duties` + `flight_sectors` records
2. Compute `duty_burden` + `training_opportunity` for each day
3. Older/superseded rosters: migrated read-only for history

### Phase M5 — Workouts (with P5+P6)
1. Existing `workouts` docs migrated to `workout_implementations` (data copy)
2. Best-effort reconstruction of `workout_assignments` from `workouts.roster_id + date + user_id`
3. Best-effort `objective_exposures` reconstruction:
   - Map V1 workout `focus` → V2 objective_kind
   - Assign `sequence` in chronological order per (client, objective_kind)
4. All migrated records marked `source: "migrated_v1"` so we can identify them
5. Progression sequence starts from the migrated count

### Phase M6 — Coach notes (with P2 & P11)
1. Parse `users.coach_notes.cautions` → `coach_directives(kind=avoid_movement or note_only)`
2. Parse `users.coach_notes.goal_override` → active goal already set in M3
3. Parse `users.coach_notes.weekly_shape` → free-text `coach_directives(kind=note_only)` for coach reference
4. Parse `users.coach_notes.preferences` → structured preferences on `users.profile`
5. `users.coach_notes` retained read-only for revert

### Phase M7 — Progression (with P8)
1. Read latest `progression_snapshots` per client
2. Compose initial `progression_states` per (client, objective) using the snapshot's counts
3. Per-exercise load memory bootstraps empty; fills as completions land

### Phase M8 — Exercises consolidation (before P6)
1. Verify all `exercises` legacy library have `exercises_v2` counterparts
2. Any missing → migrate on demand
3. Retire read paths from `exercises` (write nothing new)
4. Keep read fallback for 6 months

### Phase M9 — Check-ins dedupe (with P10)
1. Combine `check_ins` + `checkins` collections
2. `checkins` (typo) moved into `check_ins` canonical
3. `daily_pulse` retained as separate collection but linked via `client_id + date`

### Phase M10 — Hotels demotion (with P11)
1. `hotels` collection remains but coach dashboard removes the "search hotel" step from workout construction
2. Coach can still browse/edit `hotels` as annotations
3. Training path no longer reads `hotels`

---

## 7. Shadow mode (with P12)

Before V2 makes plans "for real":
```
for opted_in_client in shadow_clients:
    v1_plan = build_v1_plan(client)     // normal V1 path
    v2_plan = build_v2_plan(client)     // new pipeline
    persist(v1_plan → workouts)          // client sees v1
    persist(v2_plan → plan_shadows)      // internal only

Coach dashboard shows:
   "V1 said X · V2 proposed Y" per day
   Diff summary at week/month level
   Coach rates V2 output (thumbs up/down + reason)
```

Metrics collected in shadow:
- `v2_matches_v1_pct` — how often V2 agrees with V1
- `v2_coach_thumbs_up_pct` — coach approval rate of V2 output
- `v2_generation_latency_seconds`
- `v2_llm_calls_per_plan`

**Green criteria to advance to coach-only beta:** 3 weeks of shadow with `v2_coach_thumbs_up_pct ≥ 75%` across ≥ 5 clients.

---

## 8. Coach-only beta (post-shadow)

Enable V2 as PRIMARY for opted-in clients but require **coach approval on everything**:
- No workout goes LIVE without explicit coach batch approval
- SafeAdaptationBoundary set to most restrictive default (`allow_move_within_planning_window: false`)
- Client sees V2-generated LIVE plans but the coach has personally batch-approved every one

**Green criteria to advance to default:** 4 weeks with:
- `coach_edits_per_client_per_week ≤ 3`
- `plan_approval_time_minutes p95 ≤ 8`
- Zero data-integrity incidents
- Coach subjective sign-off

---

## 9. Progressive automation rollout (post-beta)

Only after coach-only beta green:
- Enable `allow_move_within_planning_window: true` default
- Enable batch auto-approve for OPTIONAL and SUPPORTING importance sessions (still creates DecisionRecord)
- Increase `SAB.allow_duration_reduce_pct` default from 20 → 40
- Enable coach-side "auto-approve READY items on plan build" toggle (still requires initial flag)

Each step behind a feature flag + metric-gated. Coach can revert to previous level any time.

---

## 10. What can be built without affecting current clients

- All of P1-P4 (pure data-model additions)
- Shadow-mode V2 for opted-in clients
- Coach Dashboard V2 (feature-flagged per coach)
- All new admin catalogs (`GoalDefinition`, `PhaseDefinition`, `workout_slot_templates`)
- New endpoints (V2 lives at `/api/v2/*` initially)
- `metrics_events` collection

Everything in this list can be deployed to production without any client seeing a change.

---

## 11. What REQUIRES data migration (one-way or two-way)

- Goals (M3) — one-way, but original fields kept for revert
- Rosters (M4) — one-way, but embedded `days[]` kept read-only
- Workouts (M5) — one-way, but original `workouts` collection kept read-only for 6 months
- Coach notes (M6) — one-way, `users.coach_notes` retained for revert
- Progression (M7) — bootstrap only; production writes go to new collection immediately
- Exercises (M8) — dedupe write path; legacy library kept for 6 months
- Check-ins (M9) — canonical merge; both collections kept read-only for 3 months

**Revert plan:** if any client's V2 experience breaks, disable `v2_default` flag → V1 path resumes reading from original untouched collections. Both models coexist safely for the migration window.

---

## 12. What must be complete before V2 draft generation is trusted

Non-negotiable pre-requisites before ANY client sees a V2-generated plan (even in coach-only beta):

1. **P1 Draft/Live** — cannot experiment without a safety layer
2. **P2 Goals + Timelines + Phases** — WHAT engine needs foundations
3. **P3 Training-demand** — otherwise nothing to plan against
4. **P5 Scheduling** — deterministic placement
5. **P6 Construction** — actual workouts
6. **P8 Progression** — otherwise sequence identity meaningless
7. **P10 Reality resolver** — clients need adaptation
8. **P11 Coach Dashboard V2** — coach needs to see and approve
9. **Validation checks V1-V16 fully implemented**
10. **DecisionRecord logging fully instrumented**
11. **Job runner with idempotency proven in production traffic (7 days)**
12. **Rollback procedure tested with a real client (staged rollback rehearsal)**

Any missing → coach-only beta cannot start.

---

## 13. What could create the largest reduction in coach workload

Ranked expected impact (highest first):
1. **Batch approve READY items** (P11 + P1) — coach touches 3 items instead of 30
2. **Client change-equipment within SAB** (P7) — coach never sees these
3. **Incremental replan on roster change** (P4 + P5) — no full-month regen for a Tuesday flip
4. **Command bar for natural-language changes** (P11) — 10× faster than manual edits
5. **Exception review with one-click apply** (P5 validation + P11) — no context-hunting
6. **Missed-session auto-cascade** (P8 + P10) — coach doesn't manually reshuffle
7. **Structured Reality flow** (P10) — reduces LLM latency + coach escalations
8. **Decision "Why?" tooltips** (P1 records → P11 UI) — coach doesn't hunt for context
9. **Multi-active-roster preservation** (already Iter 109) — no re-work when uploading next month
10. **Automation metrics dashboard** (P12) — helps coach verify it's actually reducing load

---

## 14. Risk register + mitigations

| Risk | Mitigation |
|---|---|
| Objective identity drift during migration | Post-migration audit script counts exposures per (client, objective_kind) matches V1 completions; alerts if drift > 5% |
| DRAFT accidentally becomes LIVE without approval | Add unit test for every write path proving no direct writes to `plan_versions` outside `Approval` handler |
| Coach cannot revert to V1 mid-migration | Keep original V1 collections read-only for 6 months; `v2_default=false` restores V1 behaviour |
| Slot template quality — V2 workouts feel generic | Seed templates from V1's best-performing workouts (top-completed exercises per objective); coach can promote client-specific patterns to templates |
| AI polish drift creating client-facing "AI" language | Validation V18 blocks forbidden vocabulary; regenerate rationale on failure |
| Template cache staleness after coach edit | Cache keys include coach's edit timestamp; invalidate cascade on template change |
| Multi-goal weighted allocation surprises coach | First 4 weeks of coach-only beta: force coach acknowledgement on any goal-weight change |
| Incremental replan misses a downstream dependency | Comprehensive dependency graph unit tests; opt-in "full replan" button for coach when suspicious |
| Job queue backlog delays draft-ready | Alerting: p95 > 90s → page on-call; dead-letter inspection UI |
| Coach dashboard V2 slower than V1 for coach | Load test with production data volume before rollout |

---

## 15. Testing strategy per phase

**P1 (Draft/Live):**
- Property tests: cannot publish DRAFT without approval; every LIVE version reachable from snapshot; revert produces identical state
- Integration: coach approves → client sees within 15s; coach reverts → client sees within 15s
- Negative: concurrent approval attempts → optimistic-locking rejects the loser

**P2-P3 (Goals + Objectives):**
- Snapshot tests per goal_id: given a goal + phase + timeline, exposures emitted match golden
- Property: sequence counters strictly monotonic; deletion of a WorkoutAssignment does NOT delete its ObjectiveExposure

**P4 (Roster facets):**
- Golden tests: sample Etihad/Emirates PDFs produce known duty_burden + opportunity scores
- Migration: V1 roster.days[] → V2 entities has 100% field coverage

**P5 (Scheduling):**
- Every session type × every duty band × every readiness band → scheduling produces expected placement or expected exception
- Cascade: missed KEY → placement in next best day; if no fit → exception

**P6 (Construction):**
- Slot templates × equipment context → every combination produces a valid workout
- No exercise ever appears with `approval != approved`
- Injury post-filter: pain flag on knee → no deep_squat in output for 14 days
- AI polish: output structurally identical when LLM disabled (fallback to template rationale)

**P7 (Equipment adapt):**
- Client selects each equipment combination → adapt returns workout within 5s (with warm cache)
- SAB boundary tests: within-boundary swap does not create ChangeSet; outside-boundary swap creates one

**P8 (Progression):**
- Sequence: 6 exposures of Upper Strength → load progresses correctly per double_progression
- Missed session doesn't reset counter; deload triggers correctly

**P9 (Events):**
- Countdown math correct against pytest date fixtures
- Two priority-A events 21 days apart → blocker exception

**P10 (Reality):**
- Every intent chip resolves in < 100ms; only "Other" escalates to LLM

**P11 (Coach UX):**
- E2E: coach uploads roster → within 60s → sees DRAFT → batch approves → client sees LIVE
- E2E: command bar sentence → structured proposal within 3s

**P12 (Automation):**
- Chaos test: kill worker mid-job → retries; idempotency prevents duplicates
- Observability: every metric emits under load

---

## 16. Acceptance criteria per phase

Formal PASS/FAIL for each phase. Selected examples:

**P1 PASS iff:**
- AI can create DRAFT changes
- Client's LIVE plan never changes without approval
- Coach can compare DRAFT vs LIVE
- Coach can edit DRAFT freely
- Coach can approve any scope (workout/day/week/…)
- Every approval creates an immutable PlanVersion
- Previous PlanVersions remain queryable
- Revert to any previous version works and creates a new version (not destructive)

**P5 PASS iff:**
- Given goal+phase+roster+readiness → placement matches golden for 100% of test scenarios
- Missed KEY session cascades correctly
- Cannot place exercise-restricted movement in blocked window
- All 16 validation checks fire in expected scenarios

**P6 PASS iff:**
- Every slot template has a bodyweight fallback
- Every workout output validates all 16 checks
- No unapproved exercise appears in any output
- AI polish cache-hit rate > 40% on realistic traffic

**P7 PASS iff:**
- Change-equipment produces adapted workout < 5s (p95)
- Objective identity preserved across adapt
- SAB enforcement matches spec on 20 boundary tests
- Coach sees ChangeSet only when SAB exceeded

**P11 PASS iff:**
- Coach can approve 27 items in < 15s wall-clock
- Command bar parses each of 20 sample sentences into correct proposal
- ROSTER + PLAN loads < 2s on production data volume

---

## 17. Rollout timeline (indicative)

Assuming 2 backend + 1 frontend + 1 QA:

- **Month 1:** P1 + P2 + P4 (foundations) → shadow-mode alpha for 1 internal client
- **Month 2:** P3 + P5 (WHAT + WHEN) → shadow-mode grows to 5 opted-in clients
- **Month 3:** P6 (HOW) + P8 (progression) → shadow expands to 10 clients
- **Month 4:** P7 + P9 + P10 → coach-only beta for 3 clients
- **Month 5:** P11 (Coach Dashboard V2) → coach-only beta expands to all V2-flagged clients
- **Month 6:** P12 + polish + acceptance tests → default V2 for new clients only
- **Month 7:** default V2 for all clients; V1 remains as fallback for 6 months

---

## 18. Success metrics (end-state)

Compared with V1 baseline:
- **Coach workload:** −60% time per client per week (from ~50 min → ~20 min)
- **Draft-ready latency:** p95 < 60s (from V1's ~3-5 minutes with LLM chunks)
- **Objective completion rate:** +10 percentage points
- **Client-adapted-without-coach:** > 90% of equipment/reality changes
- **Coach edits per plan:** < 3 per 28-day plan (from V1's ~8-15)
- **Silent chunk drops:** 0 (from V1's occasional partial calendars)
- **AI calls per plan:** < 5 (from V1's 4-12 per monthly build)

---

## 19. What NOT to build (explicit)

Per user directive, this list is non-negotiable for V2:

- ❌ Global hotel database
- ❌ Hotel gym matching / verification network
- ❌ Requirement for clients to identify hotels
- ❌ Assumed equipment based on location
- ❌ Random replacement workouts on equipment change
- ❌ Coach-approval requirement for every small adaptation
- ❌ Auto-publish of significant AI programme changes to LIVE
- ❌ Reliance on one giant LLM prompt for programme quality
- ❌ Time-zone modelling for jet-lag scoring (out of scope; may return later)
- ❌ Wearable/HR integration in V2 (kept optional post-launch)
- ❌ Push notifications as core functionality (opt-in only)

---

## 20. Post-launch runway

Once V2 is default for all clients:
- Remove V1 legacy paths after 6 months of no reads
- Retire `hotels` collection dependency completely (kept as coach annotations only)
- Retire `exercises` legacy collection
- Retire `checkins` (typo) collection
- Consolidate feature flag surface (drop unused flags)
- Publish V2 architecture docs to internal engineering wiki

---

**End of migration document.**

Six deliverables complete:
- `/app/memory/CREWFIT_TRAINING_INTELLIGENCE_V2_ARCHITECTURE.md`
- `/app/memory/CREWFIT_TRAINING_INTELLIGENCE_V2_SCHEMA.md`
- `/app/memory/CREWFIT_TRAINING_INTELLIGENCE_V2_RULE_ENGINE.md`
- `/app/memory/CREWFIT_TRAINING_INTELLIGENCE_V2_COACH_UX.md`
- `/app/memory/CREWFIT_TRAINING_INTELLIGENCE_V2_CLIENT_UX.md`
- `/app/memory/CREWFIT_TRAINING_INTELLIGENCE_V2_MIGRATION.md`
