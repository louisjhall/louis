# CrewFit — Marathon Prep Programme Generation Failure

**Formal investigation report**  
Prepared: 29 June 2026  
Author: engineering (backed by live DB inspection, source-code trace, and log review)  
Scope: root-cause analysis. **No code has been changed.** A phased fix plan is proposed at the end for Louis' approval.

---

## 1. Executive summary

The failure is real and it is **worse than a prompt bug**. Three separate defects compounded to produce the "7 days of 45-min Full Body Strength, each with a single exercise, no running" outcome:

1. **Onboarding never wrote the two most important fields** — `profile.main_goal_key` and `profile.training_days_per_week` — into the `users` document. The generator therefore had no idea the client was training for a marathon or that they had capped themselves at 4 days.
2. **The LLM (Claude) call failed / returned nothing** for the affected roster (log evidence + `source: "template"` on every workout in the DB). The deterministic fallback then fired. That fallback is:
   - roster-shaped only (produces a workout for every non-off day → 7/wk),
   - has NO running templates at all,
   - has NO goal-awareness (marathon / event / strength are not differentiated).
3. **The V2 Exercise Library resolver silently dropped 4 of the 5 template exercises** in every Full-Body-Strength card, leaving one lone exercise inside a 45-minute box. Because the workout still had ≥1 exercise, the current programme-quality validator ticked it as "ok".

Together, these three bugs turn a well-intentioned onboarding into an un-tailored, un-safe, un-explainable plan.

---

## 2. What the database actually contains for the affected client

Live query against `users`, `programmes` and `workouts` (mongo `crewfit_v1`):

**User `louishallpt@gmail.com` (id 7ed105f2…)**

| Field | Value in DB |
|---|---|
| `profile.main_goal` | **`None`** |
| `profile.main_goal_key` | **`None`** |
| `profile.training_days_per_week` | **`None`** |
| Programme.goal_key | `general_fitness` *(default fallback)* |
| Programme.target_sessions_per_week | `3` |
| Programme.phase | `foundation` |
| Programme.validation_status | **`ok`** *(false-green)* |
| Programme.validation_errors | `[]` |

**Workouts generated:**

| Date | Title | Duration | Exercises stored |
|---|---|---|---|
| 2026-06-29 | Full Body Strength | 45 min | **1** |
| 2026-06-30 | Full Body Strength | 45 min | **1** |
| 2026-07-01 | Full Body Strength | 45 min | **1** |
| 2026-07-02 | Full Body Strength | 45 min | **1** |
| 2026-07-03 | Full Body Strength | 45 min | **1** |
| 2026-07-04 | Full Body Strength | 45 min | **1** |
| 2026-07-05 | Pre/Post-Flight Mobility | 12 min | 0 warm-up items shown |
| 2026-07-06 → 2026-07-31 | Full Body Strength (repeats) | 45 min | **1** each |
| … | … | … | … |

**Every card has `source = "template"` and `needs_coach_review = true`.**  
The single surviving exercise is the goblet squat (the only one in the FULL_BODY_STRENGTH template that had a direct match in the V2 Exercise Library).

This is the exact symptom Louis reported.

---

## 3. Answers to the 18 investigation questions

### Q1. Was "Marathon prep" actually saved as the client's main goal?
**No.** The DB shows `profile.main_goal = None` and `profile.main_goal_key = None`. The goal answer collected in `/api/assessment/*` was written to `coaching_dna.primary_goal`, but **never back-copied to `users.profile`** — see §4.1.

### Q2. Was "4 days/week" actually saved as `training_days_per_week`?
**No.** `profile.training_days_per_week = None` in the users doc. The assessment writes `coaching_dna.training_availability` but never `profile.training_days_per_week`.

### Q3. Where does `_generate_month` read the goal and days-per-week?
From `user.profile` via `feature_programme_quality.programme_context_for_llm` → `_resolve_goal_key(profile)` and `profile.get("training_days_per_week")`. Because both are `None`, the resolver falls through to `DEFAULT_GOAL_KEY = "general_fitness"` and the target is capped at `3` (beginner default).

### Q4. Does the WORKOUT_SYSTEM prompt teach Claude to respect the days limit?
Partially. The prompt says *"Respect training_days_per_week — insert Rest Day sessions on other days."* But the prompt ALSO says *"For EACH day in the roster, output one workout object"* which is a **direct contradiction** — the model is told to fill every day AND simultaneously to respect a max. In practice, when the client's `training_days_per_week` is empty (as here), Claude has nothing to enforce against.

### Q5. Does the WORKOUT_SYSTEM prompt teach Claude how to program a marathon?
**No.** There are aviation/roster rules and generic EVENT phase rules (base / build / peak / taper). There is **no marathon-specific weekly template** (easy run + long run + strength support + mobility). If `event_context` is `None` — which it was, because the client never had an actual event row inserted (see Q6) — Claude gets zero marathon-shaped guidance.

### Q6. Was an `events` row created for the marathon?
**No.** `db.events` is only populated when the assessment surfaces an `event_timeline` in the generated Coaching DNA. Because the affected onboarding was minimal (goal picked but no date), no event row was created, so `event_context = None` was passed to Claude.

### Q7. Is the goal keyword "marathon" mapped to `event`?
Yes — `_resolve_goal_key` maps "marathon" → `event`. **BUT** it only fires if `profile.main_goal` or `profile.primary_goal` or `profile.goal` contains the word. In this case all three are `None`, so the mapping never runs.

### Q8. What actually produced the workouts we can see in the DB?
The **deterministic template fallback** (`feature_workout_fallback.build_template_plan`). Every workout has `source: "template"`. This runs when `feature_workout_fallback.is_empty_or_llm_failure(workouts)` returns true — i.e. Claude returned nothing usable.

### Q9. Why did Claude fail?
Two suspects, both plausible from logs:
- The generator now runs concurrently across 7-day chunks, each capped at 75 s (`asyncio.wait_for(call_claude(...), timeout=75.0)`). If any chunk timed out or returned invalid JSON, that chunk silently produced `[]` (see `_run_chunk` in `server.py`, line ~4483).
- Emergent LLM key rate-limit / budget-hit is also a common empty-return failure mode (no exception, just an empty payload).

Either way, **there is no coach-visible signal that the LLM produced nothing.**

### Q10. Why does the fallback have no running plan for a marathon client?
The fallback templates in `feature_workout_fallback.py` are:
`FULL_BODY_STRENGTH`, `BODYWEIGHT_LAYOVER`, `HOTEL_GYM`, `FLIGHT_RECOVERY_MOBILITY`, `STANDBY_ACTIVATION`. **There is no `EASY_RUN`, `LONG_RUN`, `TEMPO_RUN`, `INTERVALS` template.** The fallback doesn't read the goal at all — only `hotel_gyms` preference — so a marathon client and a fat-loss client get identical templates.

### Q11. Why did the fallback produce a workout on EVERY day (7 vs 4)?
Because it iterates `for d in roster.days` and creates one card per non-off day. There is no `target_sessions_per_week` cap and no logic to designate rest days when the roster is home-heavy. This is the direct source of "7 pending workouts a week".

### Q12. Why are the 45-minute strength cards showing only ONE exercise?
Because `feature_v2_resolver.apply_resolver_to_workouts` **drops** any LLM- or template-produced exercise that cannot resolve to an approved V2 Library entry. The comment in-code is explicit:
```py
# Unresolved — drop from the client workout (user directive).
```
The template's 5 strength exercises include DB rows only for "Goblet squat" (matched) — the other four ("Dumbbell Romanian deadlift", "Dumbbell bench press or floor press", "One-arm dumbbell row", "Plank") had no direct match and no substitute was accepted, so they were removed. **The workout duration was NOT re-derived after this drop.** So a 45-min card that now contains a single exercise slips through.

### Q13. Did any validator catch that a 45-min strength workout has 1 exercise?
**No.** `feature_programme_quality.validate_programme` only checks:
- `not workouts` → error;
- `workout has NO exercises and no warmup` → error;
- movement-pattern imbalance → warning.

There is no "duration vs content" rule, no "minimum exercises per strength card" rule, no "marathon has no runs" rule, no "sessions exceed target" rule.

### Q14. Why did the programme end up with `validation_status = "ok"`?
Because every workout technically had ≥1 exercise-or-warm-up item, the "next 7 days have real sessions" check passed (7 planned sessions is trivially > 0), and none of the missing rules exist. The gate is much too permissive.

### Q15. Where does the client-facing "PENDING" badge come from?
`/app/frontend/app/(client)/home.tsx:476` renders `<Text style={styles.pendPill}>PENDING</Text>` whenever `!w.approved && !w.completed`. Since every fresh workout is `approved: false`, **every workout in the Next 7 Days section shows PENDING** — which is what the client saw and quite reasonably called "confusing". The badge conflates "not yet completed by the client" with "not yet approved by the coach".

### Q16. Are exercise-library gaps escalated to Louis' To-Do list?
Partially. The resolver DOES call `create_exercise_request_if_missing` and INSERTS a row into `exercise_requests` / draft V2 rows. But there is **no automatic creation of a coach task in Louis' to-do list** when a request is filed, and no reconciliation job to recover orphaned requests. So library gaps quietly accumulate and Louis has no counter or filter to attack them.

### Q17. Is the workout linked to a `programme` record?
Yes — one `programmes` row per (user_id, roster_id) is persisted in `persist_programme_record` — but workouts themselves are not stamped with `programme_id`, so a foreign-key relationship exists only through the shared `roster_id`. This works today, but any regeneration flow that keeps the same roster will silently overwrite programme metadata unless carefully guarded.

### Q18. Can a client delete a bad roster and start over?
**No.** There is no "Delete Roster And Start Again" action on the client, no soft-delete/versioning of rosters, and no cleanup pass that removes future workouts / cancels pending gen jobs when a roster is replaced. Bad rosters and bad plans linger until a coach intervenes.

---

## 4. Where the code fails, in detail

### 4.1 Assessment → users.profile handoff missing
`/api/assessment/finalize` (server.py:1451) generates and persists the Coaching DNA, materialises events, flips `onboarded=true`, and seeds habits. It does **not** copy:
- assessed goal (→ `profile.main_goal_key`, `profile.main_goal`)
- assessed training days per week (→ `profile.training_days_per_week`)
- assessed experience level (→ `profile.experience_level`)
- assessed home base / airline / role (→ `profile.job_title` / `profile.airline`)

These fields exist only inside `coaching_dna.*` — but `_generate_month` and `_resolve_goal_key` read them from `users.profile`.

### 4.2 WORKOUT_SYSTEM prompt contradiction
server.py:4324. Prompt tells Claude both "one workout per roster date" (line 4359) **and** "respect training_days_per_week — insert Rest Day sessions on other days" (line 4341). No goal-specific templates (marathon / triathlon / hyrox weekly shapes). No hard-cap enforcement.

### 4.3 Fallback template lacks goal awareness and days-per-week cap
`feature_workout_fallback.build_template_plan` (line 255). Iterates every day. No cap. No running templates. No branch on `profile.main_goal_key`.

### 4.4 V2 resolver silently drops without re-validation
`feature_v2_resolver.apply_resolver_to_workouts` (line 360). Drops unresolved items, updates only `stats["dropped"]`, files a draft library request, but:
- Does not decrement / recompute `duration_min`;
- Does not mark the workout as `needs_coach_review` on drop count > N;
- Does not create a coach task for library gaps;
- Does not require a minimum number of exercises for a strength card.

### 4.5 Validator has no completeness / cap / goal-shape rules
`feature_programme_quality.validate_programme` (line 278). Missing all of:
- Duration vs exercise count coherence
- Weekly sessions ≤ `target_sessions_per_week` (with warn when > and error when >> )
- Marathon prep must include at least one running-focused session per week (unless roster forbids it)
- Repeated identical title/type across the week ("Full Body Strength" x 7)
- Template-source ratio (if >50% of workouts have `source=template`, plan is a fallback plan and needs coach review)

### 4.6 Client "PENDING" badge is misleading
`/app/frontend/app/(client)/home.tsx:476`. Not tied to workout state; it fires whenever `!approved && !completed`, i.e. for the entire fresh week.

### 4.7 No client roster-restart flow
No API, no screen, no confirmation modal, no soft-delete, no dependent-cleanup pass. Client must contact coach.

### 4.8 Exercise-library requests do not create To-Do tasks
`feature_v2_resolver.create_exercise_request_if_missing` inserts a draft V2 row and links the client / workout, but does **not** insert a `coach_tasks` row for Louis, and there is no reconciliation job to backfill orphaned drafts.

---

## 5. Why this looks worse than it is (and why to fix it now)

- The programme integrity code — periodisation phases, roster-context builder, coach-programme APIs, coach approve/regenerate — is **already good**. What's missing is the *guardrails* around it: input propagation, minimum-content validation, goal-specific programming templates, and coach visibility of failures.
- Because the client-facing surface (Home / Calendar / Workout Detail) trusts the DB blindly, a silent generator failure is invisible to the client and to Louis.
- Fixing this well requires ~5 targeted patches, not a rebuild.

---

## 6. Proposed fix plan (A / B / C / D + roster/library additions)

This is the ordered plan Louis asked for. **No code has been changed. Awaiting Louis' approval before implementation.**

### Plan A — Immediate blockers (P0, ships together, ~half a day)
- **A1. Persist assessment answers to `users.profile`** on `/api/assessment/finalize`: copy `main_goal_key`, `main_goal` (raw), `training_days_per_week`, `experience_level`, `job_title`, `airline`, `home_base`. Also: expose an explicit `/api/user/profile` PATCH shape for `main_goal_key`.
- **A2. Materialise a real `events` row** for endurance goals: if `main_goal_key == "event"` and there is a "next event" answer, insert into `db.events` with the correct `event_type` and target date. This is what turns Claude's `event_context` on.
- **A3. Hard cap `training_days_per_week`**: after generation (LLM or template), enforce that no more than `training_days_per_week` non-recovery workouts appear in any rolling 7-day window. Excess sessions demote to "Optional Recovery" or drop, with a coach task.
- **A4. Minimum-content validator**: reject as `needs_coach_review` any strength/gym/hotel/bodyweight card with `< 3` main exercises (running/mobility exempt with clear typed rules — see Part 2 of the URGENT brief). Post-drop, recompute `duration_min` if content shrank.

### Plan B — Programme quality (P0, ~2 days)
- **B1. Add a Marathon (and generic Event) shape** to `GOAL_MATRIX` and to the WORKOUT_SYSTEM prompt. Weekly template = easy run + strength support + optional second run/quality + long run + mobility (per phase). Enforce at least one running-focused session per week for `main_goal_key = "event"` with `event_type in {marathon, half_marathon, 10k, 5k, ultra}`.
- **B2. Add goal-specific templates to the fallback** (`feature_workout_fallback.py`): `EASY_RUN`, `LONG_RUN`, `TEMPO_RUN`, `INTERVALS`, plus `STRENGTH_FOR_RUNNERS`. Fallback now branches on `goal_key` and produces a runnable week.
- **B3. Progression tracking**: extend the `programmes` row with `progression_status`, `next_progression`, `deload_status`, per-week `movement_pattern_counts_actual`, and computed `sessions_this_week` / `sessions_completed_this_week` / `sessions_missed_this_week`.
- **B4. Broaden validator**: add duration↔content coherence check, exceeded-target check, marathon-has-no-runs check, template-source-ratio check, repeated-title check.

### Plan C — Coach UX & workout tooling (P1, ~2 days)
- **C1. "PENDING" wording**: split the badge into three states — `PLANNED` (default), `AWAITING COACH REVIEW` (when `needs_coach_review`), `LOCKED BY COACH` (when `coach_locked`). Remove client-facing "PENDING" entirely.
- **C2. Client Programme Overview card**: on Home, above Next 7 Days, show goal + phase + week + weekly target + focus + next key session (data already lives in `programmes`).
- **C3. Coach Programme Overview + Timeline**: new coach sub-screen listing goal / phase / week / target / actual / validation / next key session, plus a rolled timeline of programme + roster + workout events (already recoverable from existing collections).
- **C4. Coach workout editor** (extend the existing coach workout detail): title/goal/duration/rationale, add/remove/swap/reorder exercises, edit sets-reps-rest-RPE, add warm-up/cooldown items, lock/approve/date-change, all audit-logged.
- **C5. Exercise Swap surface + V2 Library filters** (movement, region, equipment, injury-friendly, hotel-friendly, bodyweight, running-support, mobility, conditioning). Preserve prescription where sensible; log old vs new.
- **C6. Regenerate Single Workout** (with the 12 option variants Louis listed). Preview → apply.
- **C7. Regenerate Programme** with a Preview screen (old vs new weekly structure, count of changed workouts, warnings, validation result).

### Plan D — Exercise requests & roster restart (P0/P1 mix, ~2 days)
- **D1. Auto-open a coach task for every draft V2 request** (`task_type = exercise_library_review`). Dedupe by `exercise_request_id` + normalised name; increment `request_count` and `clients_affected`. Priority by soonest workout date.
- **D2. Reconciliation on coach dashboard load**: find orphaned drafts with no open task, backfill.
- **D3. Coach sidebar counter**: "Exercise Reviews (n)".
- **D4. Client roster management screen** with: Review/Edit, Upload Updated, Delete Roster And Start Again. Two-tier delete (Delete Roster And Future Plan / Delete Roster Only). Type DELETE to confirm.
- **D5. Cascade cleanup**: on delete-and-start-again, deactivate roster + linked programme + uncompleted workouts, cancel/invalidate pending gen jobs, preserve completed workouts + logs + check-ins + messages + coach-locked workouts.
- **D6. Restart flow**: client returns to roster-upload; programme status = `awaiting_roster`; new roster generates a new programme version linked only to the confirmed replacement.
- **D7. Audit log** for every step of the delete/restart (actor, timestamp, before/after ids), and a coach activity task on delete + on 48h-no-replacement.

### Plan E — Progression, completeness telemetry, safety net (P2)
- **E1. Per-workout `validation_status` field** (`ok` / `warning` / `failed`), surfaced to coach only.
- **E2. Coach dashboard "Programme Health" tile**: templates-used %, validation-fail %, exercise-substitute %, roster-restart count.
- **E3. Regen preservation contract**: completed workouts and coach-locked workouts are never overwritten.
- **E4. Test coverage**: implement all 38 tests from the URGENT brief (Parts 20 + Testing Addition 20-38).

---

## 7. Files that will change (proposed)

Backend:
- `server.py` (assessment_finalize handoff, event materialisation on marathon, WORKOUT_SYSTEM prompt update, minimum-content post-processor)
- `feature_programme_quality.py` (new validators, Marathon key in GOAL_MATRIX, progression fields)
- `feature_workout_fallback.py` (running templates, goal-aware branching, days-per-week cap)
- `feature_v2_resolver.py` (post-drop duration recompute, coach-task on request creation, reconciliation job)
- `feature_coach_deep_edit.py` (or new `feature_coach_programme_editor.py`) — swap/regen/edit/lock endpoints if not already present
- New `feature_roster_lifecycle.py` — delete + restart + cascade cleanup + audit

Frontend:
- `app/(client)/home.tsx` — Programme Overview card + status labels
- `app/(client)/calendar.tsx` — status labels
- `app/(client)/profile.tsx` or new `app/roster/manage.tsx` — Roster Management screen
- `app/(coach)/clients.tsx` and coach client detail — Programme Overview, Timeline, editor entries, Exercise Reviews counter
- `app/coach/exercise-content.tsx` — new task filters

---

## 8. Testing plan (mirrors Parts 20 + testing addition of the URGENT brief)

Backend unit tests (targeted):
- goal-key propagation (assessment → users.profile)
- days-per-week cap enforcement
- minimum-exercise validator on strength cards
- marathon-must-have-running validator
- V2 drop → duration recompute
- exercise request → coach task creation + dedupe
- roster soft-delete + cascade cleanup

Integration tests (via testing_agent):
- Full marathon-prep onboarding at 4 days/week → generates ≤4 sessions with at least 1 run/week
- 45-min strength has ≥3 exercises or is flagged
- Delete roster + start again preserves history and clears future
- New V2 request appears in Louis' To-Do
- Coach regenerate preserves completed + locked

---

## 9. What we are NOT changing until Louis confirms

- The `emergentintegrations` LLM key (still applies)
- Sentry (still off for EAS builds)
- Any part of the flow that would rebuild the app
- Client-side auth
- Any UI outside the specific components listed

---

## 10. Recommended acceptance order

1. **Plan A** (blockers) — safe to ship first, unblocks all downstream fixes.
2. **Plan B** (programme quality) — the actual "no more random plans" fix.
3. **Plan D** (roster restart + exercise-request tasks) — high user value, unblocks beta.
4. **Plan C** (coach controls) — coach experience polish; needs A+B in place.
5. **Plan E** (telemetry + tests) — safety net after functionality lands.

---

**End of report. Awaiting Louis' green light before writing any code.**
