# CrewFit Training Intelligence — Current Architecture (Forensic Audit)

**Version:** Iter 110 · Session 2026-07-27
**Scope:** Read-only forensic capture. No code or prompt changes made.
**Purpose:** Reference document for designing CrewFit Training Intelligence V2 outside Emergent.

## Honesty labels used
- ✅ **IMPLEMENTED** — code path exists, is reachable from UI/API, and demonstrably runs
- ⚠️ **PARTIALLY IMPLEMENTED** — code exists but only some inputs / branches work
- ❓ **AMBIGUOUS / DUPLICATED** — multiple code paths make the same decision; which one wins depends on entry point
- ❌ **NOT IMPLEMENTED** — no code found
- 🧪 **PLACEHOLDER** — stub / hard-coded default / feature-flagged off

## Reading this document
Prompts are quoted **verbatim** where they materially describe behaviour. Rule engines are quoted where they enforce something. Wiring/boilerplate is referenced by file+function only. Where prompts *instruct* behaviour but persisted state doesn't allow it, the discrepancy is called out explicitly.

---

# 0. High-level snapshot

| Metric | Value |
|---|---|
| Backend files | 60 `feature_*.py` modules + 11 981-line `server.py` monolith |
| Backend Python LOC | ~42 100 (excluding tests) |
| MongoDB collections in production use | **92** (see §44) |
| API routes | 490 (176 in `server.py` + 314 in feature files) |
| Frontend Expo Router screens | 76 (`app/` tree) |
| Reusable frontend components | 66 (`src/components/`) |
| LLM providers wired | Anthropic Claude Sonnet 4.5 (text), Google Gemini (roster parsing, image gen), OpenAI Whisper (STT), all via `emergentintegrations` |
| LLM key | Emergent Universal Key (single env var `EMERGENT_LLM_KEY`) |
| Roster parsers | 2 airline-specific (Etihad, Emirates) + 1 LLM fallback |
| Deterministic template generators | 2 (`feature_workout_fallback.py`, `feature_workout_fallback_v2.py`) — ❓ AMBIGUOUS (see §54) |
| Progression snapshot store | `progression_snapshots` collection, computed weekly |
| Exercise library collections | **2 in production** — `exercises` (legacy) + `exercises_v2` (new). ❓ DUPLICATED (see §21) |

---

# 1. Complete training pipeline (life-of-a-workout)

The following is the actual sequence when a client uploads a roster and receives a plan. Every step is annotated by where the decision is made (rule / LLM / template / DB / coach / client / automatic).

```
Client joins
  → POST /api/auth/signup            [client, hand-typed]
  → POST /api/profile/onboarding     [client — collects age/sex/height/weight/airline/job_title/home_base/photo]
  → assessment.tsx (Atlas interview) [LLM — ASSESSMENT_INTERVIEWER_SYSTEM]
  → coaching-dna.tsx build            [LLM — DNA_SYSTEM writes dna_ctx.living_profile]
  → training-setup.tsx                [client — equipment, days/week, disliked exercises, injuries]
  → hotel-setup.tsx                   [client — known hotel gyms]
  → event.tsx (optional)              [client → events collection]
  → first-day-choice.tsx              [client — "start tomorrow" gate]

Roster obtained
  → roster-upload.tsx client path OR CoachRosterUploadButton coach path
  → POST /api/roster/upload-parse       [background worker]
      → parsers/etihad.py::detect_etihad → parse_etihad_pdf   [rule-based coordinate parser]
      → parsers/emirates.py::detect_emirates → parse_emirates_pdf [rule-based]
      → LLM fallback: call_gemini_file(ROSTER_SYSTEM, ...)     [Gemini]
      → apply_day_defaults()                                    [rule-based]
      → _detect_overlap()                                       [rule-based]
      → _persist_pending_roster()                               [DB write into rosters, status=pending_confirmation]

Confirm
  → client: POST /api/roster/pending/{rid}/confirm  OR
    coach : POST /api/coach/clients/{cid}/roster/pending/{rid}/confirm  (Iter 109)
  → overlap-aware deactivation of prior rosters                  [rule-based]
  → mark is_active=True, status=confirmed                        [DB]
  → Trigger _generate_month worker                                [async task]

Plan generation (_generate_month in server.py:7135)
  Step 1: programme_context_for_llm(user, roster)                 [DETERMINISTIC rule-engine — see §7]
    - resolves goal_key from profile via _resolve_goal_key
    - computes week_index from prior programmes                   [DB read]
    - _phase_for_week(week_index-1)                                [modulo 4 → Foundation/Build/Peak/Deload]
    - _phase_for_weeks_to_race()  if endurance event               [race-anchored override]
    - weekly_shape_ideal = event_weekly_shape / strength_weekly_shape
    - strength_overload_for(goal_key, phase, prev-week adherence)  [rule matrix]
    - _roster_summary — counts long-haul, night, recovery_first_days, recovery_tiered_days
    - compute_live_state(db, user_id)                              [rule-based; see §37]
  Step 2: _get_dna_context(user_id)                                [DB read of coaching_dna]
  Step 3: db.events.find_one(active) → event_context                [DB read]
  Step 4: hotel_cache pre-warm                                       [DB parallel gather]
  Step 5: constraint_block_for_prompt(days)                          [parser_constraints deterministic]
  Step 6: coach_notes_for_prompt(user)                               [DB read of users.coach_notes]
  Step 7: apply_coach_note_overrides(profile, user)                  [regex extraction → profile mutation]
  Step 8: Chunk into 7-day windows, run concurrently via _run_chunk
    → call_claude(WORKOUT_SYSTEM, prompt)                            [LLM — Anthropic Claude Sonnet 4.5]
    → parse_json_from_text(raw)
  Step 9: dedupe by date
  Step 10: enforce_constraints_on_workouts(unique, all_days)         [parser_constraints DETERMINISTIC SAFETY NET]
  Step 11: apply_resolver_to_workouts(unique, user, roster)          [V2 exercise resolver — see §22]
  Step 12: _apply_days_cap_and_min_content(unique, profile)          [Plan A3 rule engine — see §25]
  Step 13: apply_layover_naming(unique, roster, airline)             [Iter 102 rule-based rename]
  Step 14: Persist to db.workouts (deletes+inserts by date)
  Step 15: _notify_coaches_of_new_roster()                            [creates coach_task]

If LLM returns empty (any chunk):
  → feature_workout_fallback.build_template_plan(...)                 [DETERMINISTIC TEMPLATE]
      - Reads goal_key + phase from programme_ctx
      - Picks weekly_shape via strength/event helpers
      - Fills SESSION_TYPE_META presets by date
      - Applies flight_recovery_template_for(duty_hours)
      - Applies apply_resolver_to_workouts afterwards
  → sets workouts.source='template', needs_coach_review=True
  → opens coach_task 'stuck_generation'

Client sees workouts
  → home.tsx polls /workouts/week, /calendar/range
  → completions: POST /workouts/{wid}/complete
  → feature_progression.on_workout_completed()                      [rule engine]
      → if last session of the ISO week → compute_status() + upsert progression_snapshots

Adaptation
  → Client hits "Today's Reality" (RealityModal.tsx)
  → POST /api/reality/submit
  → call_claude(REALITY_SYSTEM, ...)                                 [LLM]
  → client accepts option A/B/C
  → POST /api/reality/apply
      → in-place mutation of workouts.date (reduce/replace/skip/move…)

Coach directives
  → Coach opens /coach/client/[id]
  → PUT /api/coach/clients/{cid}/coach-notes                         [DB write of users.coach_notes]
  → Next _generate_month reads these BINDING notes

Regeneration
  → POST /api/workouts/regenerate?dates=…                            [server.py]
  → runs same _generate_month for scope
  → protected: coach_locked=True workouts are NOT overwritten (see §42)
```

## What each stage actually decides

| Stage | Where | Decision type |
|---|---|---|
| Onboarding profile | `server.py::signup`, `feature_profile.py` | Client-controlled, DB-write |
| DNA capture | `ASSESSMENT_INTERVIEWER_SYSTEM` + `DNA_SYSTEM` (server.py:1191,1280) | LLM-driven |
| Goal resolution | `feature_programme_quality._resolve_goal_key` | Rule-based keyword match + structured key |
| Phase selection | `_phase_for_week` (modulo 4) OR `_phase_for_weeks_to_race` (event) | Rule-based |
| Weekly shape | `event_weekly_shape` / `strength_weekly_shape` | Hard-coded matrix |
| Roster interpretation | `parsers/etihad.py`, `parsers/emirates.py`, `ROSTER_SYSTEM` LLM fallback | Hybrid rule + LLM |
| Workout envelope decision | `WORKOUT_SYSTEM` prompt + `parser_constraints` enforcement | LLM proposes, rules override |
| Exercise selection | `WORKOUT_SYSTEM` LLM + `feature_v2_resolver` matching to `exercises_v2` | LLM + rule-based library snapping |
| Progression | `feature_programme_quality.strength_overload_for` + `feature_progression.compute_status` | Hard-coded matrices |
| Regeneration protection | `coach_locked`, `completed` flags | Rule-based |

---

# 2. Backend module inventory

## 2.1 Feature modules (grouped by concern)

### Roster / duty
- `parsers/etihad.py` (26,547 bytes) — coordinate-based Etihad PDF parser. Returns `parse_confidence`, days with `day_type`, flights, layovers.
- `parsers/etihad_labels.py` (14,948 bytes) — assigns `training_colour`, `equipment_assumption`, `blocked[]`, `client_label` per Etihad day.
- `parsers/emirates.py` (20,830 bytes) — coordinate-based Emirates PDF parser.
- `parsers/emirates_labels.py` (5,592 bytes) — Emirates equivalent of etihad_labels.
- `parser_constraints.py` — unified interpreter of parser labels → enforceable constraints.
- `feature_roster_confirmation.py` (1,269 LOC) — /roster/upload-parse, /roster/pending/{rid}/confirm, /roster/upload-and-generate, job polling.
- `feature_roster_lifecycle.py` — active/superseded/expired transitions.
- `feature_roster_review_delay.py` — Iter 92 "review delay" mechanic.
- `feature_roster_versions.py` — version snapshotting.
- `feature_coach_roster_months.py` — coach's monthly navigator endpoint.
- `feature_coach_roster_upload.py` (Iter 109, new) — coach uploads on behalf of client.
- `feature_standby.py` — standby toggle + amber-day generation.
- `feature_calendar_recovery.py` — /calendar/range endpoint + `_roster_days_between` (multi-roster merge, Iter 109).
- `feature_layover_naming.py` — post-generation rename pass ("ICN Layover Hotel Gym Strength").

### Programme + plan
- `feature_programme_quality.py` (1,558 LOC) — `GOAL_MATRIX`, `PHASES`, `EVENT_WEEKLY_SHAPES`, `STRENGTH_WEEKLY_SHAPES`, `strength_overload_for`, `programme_context_for_llm`, `validate_programme`, `persist_programme_record`.
- `feature_programme_status.py` — client-side polling endpoint + coach approval task creation.
- `feature_workout_fallback.py` (874 LOC) — deterministic template generator.
- `feature_workout_fallback_v2.py` — newer template variant (❓ AMBIGUOUS — see §54).
- `feature_workout_guardrails.py` — post-hoc content guardrails.
- `feature_v2_resolver.py` — maps LLM-emitted exercise names → approved `exercises_v2` docs.
- `feature_equipment_matcher.py` — matches workouts to available equipment.
- `feature_equipment_guard.py` — post-hoc equipment consistency check.
- `feature_progression.py` (378 LOC) — weekly progression status (`progressing_well`/`maintain`/`reduce_load`/`deload`).
- `feature_dual_session.py` — optional secondary short-haul activation session.

### Client state + adaptation
- `feature_live_state.py` — Living Profile Wire-Back; extracts pain/motivation/focus-shift from check-ins.
- `feature_traffic_light.py` — Green/Amber/Red workout variants + lazy backfill.
- `feature_reassessment_micro.py` — micro re-check-in prompts.
- `feature_weekly_review.py` — weekly summary.
- `feature_daily_briefing.py` — morning briefing card.
- `feature_setup_day.py` — first-day gate ("plan starts tomorrow").

### Coach control
- `feature_coach_v1.py` — coach dashboard + message drafting.
- `feature_coach_notes.py` — structured per-client coach overrides (see §40).
- `feature_coach_deep_edit.py` — coach edits inside a client's schedule.
- `feature_coach_workout_editor.py` — coach edits individual exercises inside a workout.
- `feature_coach_workout_swap.py` — coach swaps workouts between days.
- `feature_coach_programme_overview.py` — programme-wide coach view.
- `feature_coach_live_feed.py` — realtime coach activity feed.
- `feature_coach_reset.py` — client reset flow.

### Hotel + facility
- `feature_hotel_system.py` (285 LOC) — turnaround vs layover detection, gym-type presets, confidence scoring.

### Exercise + content
- `feature_exercise_content.py` (1,018 LOC) — `exercises_v2` collection, image generation via Nano Banana.
- `feature_exercise_request_tasks.py` — draft exercise requests when the resolver can't find a match.
- `feature_media_reconciliation.py` — media asset consolidation.

### Ancillary
- `feature_habits.py` — habit engine.
- `feature_nutrition.py`, `feature_nutrition_photo.py`, `feature_nutrition_barcode.py`, `feature_nutrition_insights.py`, `feature_nutrition_travel.py`, `feature_food_search.py`.
- `feature_events.py` — actually inside `server.py` (see EventBody:659).
- `feature_event_categories.py` — event category catalog + enrichment.
- `feature_personal_activities.py` — non-CrewFit activity logging.
- `feature_progress_dynamic.py` — Your Progress dashboard.
- `feature_notifications.py`, `feature_message_attachments.py`, `feature_social_studio.py`, `feature_gdpr.py`, `feature_brand_images.py`, `feature_admin_*.py`, `feature_beta_readiness.py`, `feature_app_config.py`, `feature_timezone_current.py`, `feature_preview.py`, `feature_preview_sandbox.py`.

## 2.2 Server.py inventory of route prefixes
```
57  /coach/*           (deep — see below)
12  /workouts/*
11  /roster/*
10  /exercises/*
 8  /checkins/*
 7  /schedule/*
 7  /hotels/*
 7  /events/*
 7  /auth/*
 5  /reality/*
 5  /progress/*
 5  /assessment/*
 4  /profile/*
 4  /personal-records/*
 4  /calendar/*
 3  /videos/*
 3  /nutrition/*
 3  /messages/*
```
(Feature modules add 314 more routes on top of these 176.)

---

# 3. AI prompts (verbatim)

## 3.1 ROSTER_SYSTEM (Gemini — roster parse)
**Location:** `server.py:4429`
**Model:** Gemini via `call_gemini_file(system, prompt, path, mime)` (see server.py:857-ish)
**Input:** multipart PDF or image, file path passed as blob
**Output schema:** `{"days":[{date, day_of_week, day_type, home_or_away, report_time, duty_end_time, flights:[…], layover_city, layover_country, layover_nights, notes, confidence}]}`
**Fallback if LLM returns empty:** deterministic 7-day placeholder starting `week_start` with day_type="Home Day" and confidence 0.2 (server.py:4536-4543).

Full prompt already quoted in the audit exploration (server.py:4429-4506). Key rules:
- European DD/MM date format mandatory
- weekday_of(date) MUST match printed day_of_week
- Airline-specific hints for 12 airlines (EK, BA, U2, FR, QR, EY, LH, AF, KL, DL/UA/AA, TK, SQ)
- Standby detection with `standby_type ∈ {home_standby, airport_standby, reserve, short_call, long_call, night_standby, early_standby, unknown_standby}`
- Overnight duty spans handled as Layover Arrival → Full → Departure sequence
- Confidence 0.3 sentinel triggers "Unknown/Needs Confirmation"

## 3.2 WORKOUT_SYSTEM (Claude Sonnet 4.5 — plan generation)
**Location:** `server.py:7064`
**Model:** Anthropic Claude Sonnet 4.5 via `call_claude(system, prompt, max_out=8000)`
**Injected context (built in `_run_chunk`, server.py:7280-7340):**
- `Client profile` (2 000 chars, JSON dump of `user.profile`)
- `Coaching DNA (living profile)` (2 500 chars, DB `coaching_dna` doc)
- `Coach Notes` (2 200 chars, from `users.coach_notes` — BINDING)
- `Programme context` (4 200 chars) with `goal_key`, `phase`, `weekly_shape_ideal`, `strength_overload`, `live_state`, `roster_summary`
- `Event context` (1 000 chars) — active event from `db.events`
- `Parser constraints` (2 200 chars) — per-date `training_colour`, `equipment_assumption`, `blocked[]`, `action`, `client_label`
- `Days to plan` (7 500 chars) — the 7-day chunk with hotel enrichment
**Cap:** `_asyncio.wait_for(call_claude(...), timeout=75.0)` per week.
**Output schema:** `{"workouts":[{date, day_load, title, location, duration_min, focus, warmup, exercises, alternatives, key_session, event_phase, rationale, variants:{green,amber,red}}]}`
**Post-processing:** `parser_constraints.enforce_constraints_on_workouts` → `feature_v2_resolver.apply_resolver_to_workouts` → `_apply_days_cap_and_min_content` → `apply_layover_naming`.

The prompt body itself is fully quoted at server.py:7064-7132. Key mandates:
- 9 numbered HARD RULES injected as the tail of every chunk prompt
- Rule 1: real training days ≤ `profile.training_days_per_week`
- Rule 2: obey `weekly_shape_ideal` slot order
- Rule 3: endurance goal → ≥1 long_run + ≥1 easy_run per week
- Rule 4: apply `strength_overload` deltas to primary lifts
- Rule 5: LIVE STATE — auto-deload / avoid_movement_patterns / focus_shift_request / coach_directives / motivation_flag
- Rule 6: `recovery_first_days` — 10 min mobility → moderated session ≤ RPE 7 ≤ 45 min
- Rule 7: `recovery_tiered_days` short/medium/ULR templates
- Rule 8: parser constraints BINDING — action `rest_only`/`recovery_only`/`moderated`/`full_session`
- Rule 9: Coach Notes BINDING — cautions override everything, goal_override overrides profile.goal_type

## 3.3 REALITY_SYSTEM (Claude — Today's Reality)
**Location:** `server.py:5893`
**Model:** Claude Sonnet 4.5 via `call_claude`
**Called by:** POST /api/reality/submit
**Context:** DNA + roster window (-2 → +7 days) + workouts in window + `reality_kind` + `notes` + `time_available_min`
**Output schema:** `{recovery_score:0-100, context_summary, options:[{id:"A","B","C", label, title, why, risk, actions:[…]}]}`
**Action kinds:** `keep`, `reduce`, `extend`, `replace`, `convert_mobility`, `convert_recovery`, `convert_walk`, `skip`, `move`, `bring_forward`, `push_back`, `note`, `ask_coach`
**Rules baked into prompt:** 12 numbered rules covering injury preservation, key-session protection, high-intensity gating after night flights, heavy-lower + long-run 48h buffer, coach_locked handling.

Full prompt quoted at server.py:5893-5961.

## 3.4 ASSESSMENT_INTERVIEWER_SYSTEM (Claude — Atlas interview)
**Location:** `server.py:1191`
Runs the DNA capture interview turn-by-turn. Uses "Atlas" voice ("I've prepared…"), asks about:
- primary_goal (fat_loss / muscle_gain / performance / consistency)
- next_event (name + date)
- training_availability (minutes/session, days/week)
- recovery_risk (low/med/high)
- coaching_style (strict/supportive/data/story)
- motivation_style (streak/competition/community)
- biggest_weakness, biggest_opportunity

## 3.5 DNA_SYSTEM (Claude — DNA synthesis)
**Location:** `server.py:1280`
After the interview transcript is complete, DNA_SYSTEM converts it into a structured `living_profile` object written to `db.coaching_dna` and referenced by every `_generate_month` call via `_get_dna_context`.

## 3.6 EXERCISE_CONTENT_SYSTEM + ATLAS_EXERCISE_IMAGE_SYSTEM
**Location:** `server.py:8265`, `server.py:8429`
Draft coaching-point + client-facing-instruction copy for `exercises_v2`, plus Nano Banana image prompts (see `EXERCISE_STYLE_MALE` / `EXERCISE_STYLE_FEMALE` in `feature_exercise_content.py:48-103` — fully quoted in the raw scan).

## 3.7 QUESTIONS_SYSTEM (Claude — check-in questions)
**Location:** `server.py:8937`
Generates a **personalised 6-question weekly check-in** based on profile + active event + latest roster. Result stored on `db.check_ins` for the coach to draft a script from.

## 3.8 SCRIPT_SYSTEM (Claude — coach video script)
**Location:** `server.py:9018`
Ghostwrites a weekly personal coaching video script for Louis to record and send. Uses check-in answers + weekly workouts + progression snapshot.

## 3.9 MEAL_SYSTEM (Claude vision — meal photo)
**Location:** `server.py:9406`
`'You are a nutrition coach for airline crew. Given a meal photo + description, output STRICT JSON: {"calories":Int,"protein_g":Int,"quality":Int (1-10),"tip":"...","summary":"..."}'`

## 3.10 CHECKIN_SYSTEM (Claude — weekly review synthesis)
**Location:** `server.py:11041`
Voices "Atlas prepares the weekly review for Louis Hall to deliver". Reads check-in answers + workouts completed + adherence + RPE trend, produces coach-facing summary + client-facing message.

## 3.11 Secondary prompts (feature modules)
- `MSG_DRAFT_SYSTEM` — `feature_coach_v1.py:61` — coach message drafting
- `HABIT_SEED_SYSTEM` + `HABIT_REVIEW_SYSTEM` — `feature_habits.py:59,79`
- `SOCIAL_SYSTEM` — `feature_social_studio.py:142`

## 3.12 Retry / fallback behaviour
| Prompt | Timeout | On timeout | On exception |
|---|---|---|---|
| WORKOUT_SYSTEM (per chunk) | 75s | Skip week, produce nothing for it | Skip week |
| ROSTER_SYSTEM | (implicit call_gemini_file timeout) | Fallback to 7-day placeholder | Fallback |
| REALITY_SYSTEM | (implicit) | 502 → client sees error | 502 |
| ASSESSMENT / DNA | (implicit) | User sees error | User sees error |
| Nano Banana (image gen) | (implicit) | 502 → coach retry | 502 |

**When _generate_month returns 0 workouts:** `feature_workout_fallback.build_template_plan` runs deterministically. Result stored with `source='template'`, `needs_coach_review=True`, and a `coach_task` is opened.


---

# 4. Client variables that affect training

Fields are grouped by concern. Each row: **stored where** · **captured where** · **required?** · **used by generator?** (YES / NO / PARTIAL).

## 4.1 Profile identity (users.profile)
| Field | Stored | Captured | Required | Used by generator |
|---|---|---|---|---|
| `first_name`, `last_name`, `name` | users | signup | Y | NO (display only) |
| `age` | users.profile | signup | N | ⚠️ PARTIAL — passed inside `Client profile` string but no explicit rule |
| `sex` | users.profile | signup | N | ⚠️ PARTIAL — same |
| `height_cm`, `weight_kg` | users.profile | signup + settings | N | ⚠️ PARTIAL — appear in dump; used by nutrition targets |
| `airline` | users.profile | signup | N | ✅ used by roster parser (airline hints), naming pass |
| `job_title` | users.profile | signup / training-setup | N | ✅ appears in `profile_snapshot` context |
| `home_base` (IATA) | users.profile | signup / training-setup | N | ✅ used by timezone + roster context |
| `route_focus` (long_haul/short_haul/mixed/charter) | users.profile | training-setup | N | ✅ dual_session eligibility, `profile_snapshot` |
| `aircraft_type` | users.profile | training-setup | N | ⚠️ PARTIAL — surfaced in context but no rule |
| `photo_base64` | users.profile.photo | signup | N | NO |

## 4.2 Goals (users.profile)
| Field | Stored | Captured | Required | Used by generator |
|---|---|---|---|---|
| `main_goal_key` | users.profile | Basic Profile Setup | N | ✅ **primary** — maps directly to `GOAL_MATRIX` |
| `main_goal` (free text) | users.profile | onboarding | N | ✅ **fallback** — keyword-matched by `_resolve_goal_key` |
| `primary_goal` | users.profile | assessment | N | ⚠️ tertiary fallback |
| `goal` (legacy) | users.profile | legacy | N | ⚠️ quaternary fallback |
| `goal_type` | users.profile | coach_notes override | N | ✅ overridden by coach notes |
| `event_type_pref` | users.profile | event.tsx or assessment | N | ✅ selects `EVENT_WEEKLY_SHAPES` |
| `primary_goal_id` | users.profile | onboarding v2 | N | ⚠️ surfaced but not consumed |
| Coaching DNA `primary_goal` + `next_event` | coaching_dna | Atlas interview | N | ✅ referenced in prompt via `dna_ctx` |

## 4.3 Experience / preferences
| Field | Stored | Captured | Required | Used by generator |
|---|---|---|---|---|
| `experience_level` (beginner/intermediate/advanced) | users.profile | training-setup | N | ✅ caps `target_sessions_per_week` (see feature_programme_quality.py:567-572) |
| `strength_level` | users.profile | training-setup | N | ⚠️ surfaced only |
| `disliked_exercises` | users.profile | training-setup | N | ⚠️ appears in `Client profile` dump; no deterministic filter |
| `preferred_days` | users.profile | training-setup | N | ⚠️ surfaced only; not enforced |
| `training_days_per_week` | users.profile | training-setup | N | ✅ **HARD CAP** — `_apply_days_cap_and_min_content` demotes excess days to Recovery |
| `max_home_minutes` | users.profile | training-setup | N | ⚠️ passed to prompt but no per-session cap |
| `will_run_outside` | users.profile | training-setup | N | ⚠️ affects `event_context.access` |
| `swim_cycle` | users.profile | training-setup | N | ⚠️ same |

## 4.4 Injuries / restrictions
| Field | Stored | Captured | Required | Used by generator |
|---|---|---|---|---|
| `injury_notes` / `injuries` | users.profile | training-setup | N | ✅ passed in `profile_snapshot.injury_notes` |
| `coach_notes.cautions` | users.coach_notes | coach-only edit | N | ✅ **BINDING** — Rule 9 in WORKOUT_SYSTEM prompt |
| `pain_flags` (live_state) | derived from check_ins | weekly check-in text | N | ✅ **BINDING** — via `PAIN_REGION_AVOID` mapping (feature_live_state.py:41-59) |

## 4.5 Fitness (persisted metrics)
| Field | Stored | Captured | Used |
|---|---|---|---|
| `strength_metrics.*` | strength_metrics | client logs sets | ⚠️ appears in Your Progress dashboard, **not fed back to generator** — see §28 |
| `running_metrics.*` | running_metrics | manual entry | ⚠️ same |
| `personal_records.*` | personal_records | manual entry | ⚠️ same |
| `body_metrics.*` | body_metrics | manual entry | NO |
| `progression_snapshots.*.metrics` | progression_snapshots | auto | ✅ read by `strength_overload_for` via `sessions_completed_prev` |

## 4.6 Recovery / readiness
| Field | Stored | Captured | Used |
|---|---|---|---|
| CheckInBody: `energy`, `sleep`, `soreness`, `stress` | check_ins | weekly check-in | ✅ feeds `feature_live_state.compute_live_state` → `programme_context.live_state` |
| `daily_pulse` collection | daily_pulse | daily nudge (partial UI) | ⚠️ read by live_state; not always populated |
| `motivation_flag` | derived → users.profile.live_state | live_state | ✅ Rule 5(e) — favours shorter sessions |
| `pain_flags` | derived → users.profile.live_state | check-in text | ✅ Rule 5(b) |
| `focus_shift_request` | derived → users.profile.live_state | check-in text | ✅ Rule 5(c) |

## 4.7 Aviation (roster-level)
| Field | Stored | Captured | Used |
|---|---|---|---|
| `rosters.days[].day_type` | rosters | parser | ✅ every downstream stage |
| `rosters.days[].report_time`, `duty_end_time` | rosters | parser | ✅ `compute_layover_hours`, tiered recovery |
| `rosters.days[].flights[]` | rosters | parser | ✅ passed to LLM as day dump |
| `rosters.days[].layover_city/country/nights` | rosters | parser | ✅ used by layover_naming rename pass |
| `rosters.days[].hotel_id` | rosters | client picker or coach | ✅ enrichment via `hotel_cache` |
| Standby: `standby_type`, `standby_start_time`, `standby_end_time`, `standby_location` | rosters | parser | ⚠️ populated by parser; standby handling limited to amber day-load |
| `duty_hours` (derived) | rosters.days | derived in `_roster_summary` | ✅ tiered recovery + recovery_first_days |

## 4.8 Facilities / equipment
| Field | Stored | Captured | Used |
|---|---|---|---|
| `HOME_EQUIPMENT_OPTIONS` selections | users.profile.equipment | training-setup | ⚠️ appears in `Client profile` dump — no deterministic filter runs unless resolver drops the exercise |
| `training_location` | users.profile | training-setup | ⚠️ surfaced |
| `cardio_equipment[]` | users.profile | training-setup | ⚠️ surfaced |
| `hotels.equipment` (per hotel gym) | hotels | client / coach / seeded | ✅ enriched into every layover day (see §13-16) |
| `hotels.gym_type` | hotels | picker | ✅ **primary** — `GYM_TYPE_PRESETS` fallback |
| `event.access_gym/pool/bike/treadmill` | events | event.tsx | ✅ appears in `event_context.access` |

---

# 5. Goal system

## 5.1 Actual goals shipped (from `feature_programme_quality.py:55-120`)
| Key | Label | Sessions/wk | Session style | Movement mix (per week) |
|---|---|---|---|---|
| `lose_fat` | Fat loss | 3 | full-body strength + moderate conditioning | push:1, pull:1, hinge:1, squat:1, core:2, conditioning:1, mobility:1 |
| `build_muscle` | Build strength / muscle | 4 | progressive strength on the big lifts | push:2, pull:2, hinge:1, squat:1, core:2, mobility:1 |
| `general_fitness` | General fitness | 3 | balanced strength/conditioning/mobility | push:1, pull:1, hinge:1, squat:1, core:1, conditioning:1, mobility:1 |
| `health_markers` | Health markers / medical | 3 | moderate strength + aerobic base + mobility | push:1, pull:1, hinge:1, squat:1, core:1, conditioning:1, mobility:2 |
| `event` | Event training | 4 | event-specific + protected key sessions | long:1, intervals:1, tempo:1, strength:1, mobility:1, recovery:1 |
| `aviation_consistency` | Aviation consistency | 3 | minimum effective dose, roster-aware | push:1, pull:1, hinge:1, squat:1, core:1, mobility:2 |
| `improve_energy` | Improve energy | 3 | aerobic base + mobility + light strength | conditioning:1, mobility:2, strength:1, recovery:1 |
| `return_to_training` | Return to training | 2 | rebuild volume gently | push:1, pull:1, hinge:1, squat:1, core:1, mobility:2 |

**Default:** `DEFAULT_GOAL_KEY = "general_fitness"` when no key resolves.

## 5.2 Goal resolution logic (`_resolve_goal_key`, feature_programme_quality.py:430-461)
Priority:
1. `profile.main_goal_key` (must match `GOAL_MATRIX` key exactly)
2. Free-text keyword match against `main_goal` / `primary_goal` / `goal`:
   - "fat", "weight loss", "lose" → `lose_fat`
   - "muscle", "build", "strength", "hypertrophy" → `build_muscle`
   - "event", "race", "marathon", "triathlon", "ironman", "hyrox", "5k", "10k" → `event`
   - "health", "medical", "blood pressure", "cholesterol" → `health_markers`
   - "energy", "vitality" → `improve_energy`
   - "return", "come back", "post-injury", "rehab" → `return_to_training`
   - "consist", "roster", "aviation", "flying" → `aviation_consistency`
   - "fitness" → `general_fitness`
3. Fallback: `general_fitness`

**Coach notes override:** `apply_coach_note_overrides` reads `coach_notes.goal_override` free text and can force `profile.goal_type` to `endurance` / `hypertrophy` / `strength` / `fat_loss` / `general_fitness` (see `feature_coach_notes.py:103-118`).

## 5.3 Does CrewFit genuinely program differently per goal? — MIXED VERDICT
- ✅ **Deterministic differences:**
  - `target_sessions_per_week` — hard cap via `_apply_days_cap_and_min_content`
  - `weekly_shape_ideal` — actual different session-type slot orders (`STRENGTH_WEEKLY_SHAPES` for goals 1-6, `EVENT_WEEKLY_SHAPES` for goal 5)
  - `strength_overload` matrix — real per-goal sets/reps/RPE deltas for `build_muscle`, `get_stronger`, `lose_fat`, `general_fitness` (feature_programme_quality.py:371-395). **Note:** `_STRENGTH_OVERLOAD` has 4 branches; the remaining GOAL_MATRIX keys (`event`, `health_markers`, `aviation_consistency`, `improve_energy`, `return_to_training`) fall through to `general_fitness` — ⚠️ PARTIAL
- ⚠️ **LLM-only differences:**
  - `focus_copy`, `avoid`, `session_style` are string-only fields passed to WORKOUT_SYSTEM. They influence LLM wording but there is **no deterministic guard** ensuring the LLM actually respects them.
  - "conditioning" and "mobility" balance — no counter-based enforcement; only the LLM sees the movement mix hint.
- ❌ **Not differentiated by goal:** exercise selection (all goals draw from the same `exercises_v2` library filtered only by equipment/location, not by goal). No goal-specific movement-pattern priority in the resolver.

---

# 6. Multiple goals

**❌ NOT IMPLEMENTED.** Only ONE goal key resolves per client. Coach notes can override it, but the pipeline does not carry a secondary goal.

- No `primary_goal + secondary_goal` schema.
- No hierarchy engine.
- No concurrent-training rules (e.g. fat-loss + muscle-retention, muscle-gain + running).
- The `event` goal is the closest to concurrent because `WORKOUT_SYSTEM` runs both event rules AND strength rules — but there's no explicit balance calculator; the LLM makes the trade-off.

---

# 7. Phase / periodisation engine

## 7.1 Non-endurance clients (modulo cycling)
`PHASES` in `feature_programme_quality.py:274`:
| key | label | note |
|---|---|---|
| foundation | Foundation | Baseline movement quality; slightly conservative loads. |
| build | Build | Small progression on sets/reps/load. |
| peak | Peak | Strongest week — highest quality effort, still within recovery capacity. |
| deload | Deload | Reduce volume by 30–40%; keep movement quality high. |

Cycle: `_phase_for_week(week_index) = PHASES[week_index % 4]`.
`week_index` derived from `db.programmes` history — resumes on next roster upload; **does not reset**. If a programme already exists for this specific roster, its `week_index` is reused (stable across retries).

**Progression:**
- Automatic advance every 7 days (roster upload boundary).
- `strength_overload` matrix advances with the phase (foundation → build → peak → deload).
- Deload reduces volume ~30-40% via prompt Rule 5(a) if `auto_deload_trigger=true`, plus `strength_overload_for` `sets_delta -1, load_delta_pct -10`.

## 7.2 Endurance clients (race-anchored)
`_phase_for_weeks_to_race(weeks_to_race)` — see `feature_programme_quality.py:291-301`:
| Condition | Phase |
|---|---|
| weeks_to_race > 16 or None | base |
| 8 < weeks_to_race ≤ 16 | build |
| 4 < weeks_to_race ≤ 8 | peak |
| 2 < weeks_to_race ≤ 4 | taper |
| weeks_to_race ≤ 2 | race_week |

**Race-week override:** shape becomes `["easy_run","recovery_walk","shakeout","rest","event_race","rest","rest"]`.

`_EVENT_PEAK_LONG_KM` (feature_programme_quality.py:305-316) caps long-run KM per event type (marathon 32, half 20, 10k 14, 5k 8, ironman 30 run leg, hyrox 10, ultra 40).

`_long_run_km_for_week` runs a linear ramp from `base=6 km` at 16 weeks out to `peak` at 4 weeks out, then `× 0.75` at 3 weeks, `× 0.5` at 1 week, then "RACE" sentinel.

**Cutback weeks:** every 4th week during build/peak, `long_run × 0.7` (deterministic).

## 7.3 Interaction with roster
- Recovery-first days computed in `_roster_summary` — long-haul into ≥18h layover → LLM Rule 6 forces recovery mobility first, then RPE ≤7 session ≤45 min.
- Tiered flight recovery — `duty_hours < 6 → short`, `6-11 → medium`, `≥12 → ULR`. Templates in `feature_workout_fallback.py:75-108`.

---

# 8. Training split / weekly structure

## 8.1 Actual weekly shapes (from STRENGTH_WEEKLY_SHAPES, feature_programme_quality.py:200-208)
```
lose_fat              → upper_strength, conditioning, lower_strength, mobility, recovery, recovery, recovery
build_muscle          → push_strength, pull_strength, leg_strength, upper_strength, mobility, recovery, recovery
general_fitness       → upper_strength, conditioning, lower_strength, mobility, recovery, recovery, recovery
aviation_consistency  → upper_strength, mobility, lower_strength, mobility, recovery, recovery, recovery
health_markers        → easy_run, upper_strength, mobility, lower_strength, mobility, recovery, recovery
improve_energy        → easy_run, mobility, upper_strength, mobility, recovery, recovery, recovery
return_to_training    → upper_strength, mobility, mobility, recovery, recovery, recovery, recovery
```

**Split families supported explicitly:**
- Full-body strength (`upper_strength`+`lower_strength` alternating for most goals)
- Push/pull/legs (only `build_muscle`)
- Running-focused (`event` + `health_markers` + `improve_energy`)
- Event-specific (see §10)

**❌ NOT DIRECTLY SUPPORTED:** Upper/Lower split named as such, hybrid, running-focused for non-event clients, event-only shapes for medical.

## 8.2 Frequency → shape resolution
`event_weekly_shape(event_type, phase_key, target_sessions)` consumes the front of the shape until `target_sessions` are filled. Remaining slots are recovery/mobility tail.
- No user-selectable "days-per-week schedule" — it's derived from `training_days_per_week`.
- Recovery/mobility go to whichever weekdays remain; **the calendar decision (Monday vs Thursday) is made by the LLM inside the prompt** with no deterministic slotter.

---

# 9. Aviation roster engine

## 9.1 Day types recognised (server.py:227-232)
`DAY_TYPES` (17 total):
`Home Day, Home Training Day, Turnaround Duty, Layover Arrival Day, Layover Full Day, Layover Departure Day, Long-Haul Duty, Short-Haul Duty, Night Flight, Early Report, Late Finish, Rest Day, Recovery Day, Standby, Simulator/Training Day, Annual Leave, Unknown/Needs Confirmation`

Additional standby subtypes injected by the parser: `home_standby, airport_standby, reserve, short_call, long_call, night_standby, early_standby, unknown_standby`.

Roster-to-training-window mapping is codified in the WORKOUT_SYSTEM prompt (server.py:7067-7081):
| Day type | Training envelope |
|---|---|
| Long-Haul / Night Flight | No heavy lower within 24h. No hard intervals same/next day. |
| Layover Arrival | Walking + mobility + post-flight recovery only |
| Layover Full + hotel gym | Strongest opportunity — upper/lower splits ok |
| Layover Departure | Short mobility, well clear of report |
| Turnaround (early <05:00 / late >23:00) | Short mobility only |
| 3+ consecutive duty | Reduce load + insert recovery |
| Home Day | Main strength progression, full home equipment |
| Standby | Amber; short 30 min |
| Simulator/Training | Amber; light activation |
| Annual Leave | Green; full training |

**Enforcement level:**
- ⚠️ **Advisory (LLM-obeyed only)** for most of the above.
- ✅ **Deterministically enforced** by `parser_constraints.enforce_constraints_on_workouts` when the roster came from Etihad/Emirates parsers (which write `training_colour`+`blocked[]`+`action`).
- ❌ **Not enforced for LLM-parsed rosters** — Gemini extracts day_type but does NOT emit `training_colour`/`blocked[]`, so no deterministic safety net kicks in.

## 9.2 Standby handling
`feature_standby.py` — client toggles standby; generates amber day-load workouts. Standby type from the parser (`home/airport/reserve/etc.`) is stored but **not consumed** by the generator beyond the WORKOUT_SYSTEM prompt hint.

---

# 10. Duty times and flight detail

| Field | Extracted | Used by generator |
|---|---|---|
| `report_time` | ✅ parser | ✅ `compute_layover_hours`, LLM prompt |
| `duty_end_time` | ✅ parser | ✅ same |
| `departure` / `arrival` (per leg) | ✅ parser | ⚠️ LLM sees them in `days[].flights[]`; no per-leg rule |
| `block_time` | ❌ Not extracted separately | — |
| `duty_hours` | ✅ derived in `_roster_summary` | ✅ tiered flight recovery + recovery_first_days |
| Number of sectors | ✅ parser writes `flights[]` length | ⚠️ LLM sees it; used only for `feature_dual_session` |
| Overnight flight flag | ✅ parser day_type "Night Flight" | ✅ LLM rule + parser_constraints |
| Local times vs UTC | ⚠️ Parser attempts base-local; ROSTER_SYSTEM prompt insists no TZ shifts | LLM only |
| Home-base time | ⚠️ `home_base` in profile | ⚠️ passed as string, no clock math |
| Rest between duties | ✅ `compute_layover_hours(day, next_day)` | ✅ 18h threshold → layover vs turnaround |

---

# 11. Time zones / circadian / jet lag

`feature_timezone_current.py` exposes `/api/timezone/current` — reads the client's current local timezone from their reported home_base or destination. Used by the frontend `TimezoneCard.tsx`.

**❌ NOT USED BY TRAINING GENERATION:**
- No UTC-offset math in `programme_context`
- No `time_zones_crossed` calculation
- No eastbound / westbound distinction
- No biological-night window
- No circadian adjustment
- No jet-lag scoring

The only jet-lag-adjacent behaviour: `recovery_first_days` (long-haul into ≥18h layover) and `recovery_tiered_days` (short/medium/ULR by duty hours). Both are duty-hours-based, not time-zone-based.

---

# 12. Location / training environment engine

## 12.1 Explicit `location` string values (from WORKOUT_SYSTEM prompt, server.py:7119-7121)
- `"Home Workout"`
- `"Commercial Gym Workout"`
- `"Hotel Gym Workout"`
- `"Bodyweight Layover Workout"`
- `"Flight Recovery Mobility"`
- `"Pre-Flight Mobility"`
- `"Post-Flight Mobility"`
- `"Turnaround Recovery"`
- `"Outdoor Run"`
- `"Pool Swim"`
- `"Bike Session"`
- `"Rest Day"`

## 12.2 How location is chosen
- **Layover Full Day + `hotel_id` present + not bodyweight-only** → LLM tends toward "Hotel Gym Workout" via prompt rule + hotel enrichment in the day dump.
- **Layover Full Day + no hotel or bodyweight-only** → "Bodyweight Layover Workout".
- **Layover Arrival / Departure** → "Flight Recovery Mobility" / "Post-Flight Mobility".
- **Home Day** → "Home Workout" or "Commercial Gym Workout" depending on profile equipment (LLM decision, not deterministic).
- **Turnaround** → "Turnaround Recovery" (`feature_hotel_system.classify_stay` returns `turnaround` → mobility only).
- **Outdoor Run** — LLM chooses when running is prescribed.

⚠️ There is **no explicit environment picker**. The choice is made inside the LLM prompt based on the day-type + hotel context. The parser_constraints layer will DEMOTE (e.g. drop a "Commercial Gym Workout" back to "Bodyweight" if `equipment_assumption='hotel_or_bodyweight_only'`) but does not INJECT specific locations.



---

# 13. Hotel gym architecture

## 13.1 Storage — `hotels` collection
Field | Source | Description
---|---|---
`id` | new_id() | UUID
`name` | HotelBody | Free text (Hilton XYZ)
`city` | HotelBody | Free text
`country` | HotelBody | Optional
`gym_available` | HotelBody / client / coach | Bool
`gym_type` | HotelBody | `full_gym`, `cardio_only`, `basic`, `bodyweight_only`, `none`, `unknown`
`equipment` | dict[key → bool] | Keys from `HOTEL_EQUIPMENT_KEYS` (see §14)
`safe_outdoor_run` | HotelBody | Bool
`pool` | HotelBody | Bool
`opening_hours` | HotelBody | Free text
`verified_by_coach` | HotelBody | Bool (coach-only writes)
`confidence` | derived | 0.0-1.0 — see `confidence_score` (feature_hotel_system.py:204)
`notes` | free text | client / coach

**Additional collections:**
- `hotels` — the profiles above (shared across all clients — see §46)
- ⚠️ There is **no separate `hotel_gyms` collection**. Gym info lives on the hotel doc.
- ⚠️ There is **no `hotel_images` collection**. Photos are not persisted (see §17).

## 13.2 Hotel identification for a client
1. Client uploads roster → parser extracts `layover_city, layover_country, layover_nights`
2. If day has `hotel_id` set (from a previous confirmed selection), the generator uses that hotel doc.
3. If `hotel_id` is NOT set:
   - `hotels` collection is NOT auto-searched by city — client must pick from a searchable list in the client app (`hotel-setup.tsx`) OR the coach can attach via `HotelAttachBody`.
   - If no attachment happens → the generator treats it as "unknown hotel gym" → bodyweight-safe (see §15).

## 13.3 Identity resolution: known-hotel → equipment → workout
```
Roster day has layover_city + hotel_id
   ↓ (hotel_id set)
db.hotels.find_one({id: hotel_id})
   ↓ (present)
resolve_gym_equipment(hotel_doc):
   - If equipment dict is present → use it
   - Else fall back to GYM_TYPE_PRESETS[gym_type]
   ↓
Hotel enrichment injected into day dump: {name, city, gym_available, equipment, confidence}
   ↓
WORKOUT_SYSTEM prompt sees it, prescribes accordingly.
```
`is_bodyweight_only(hotel_doc)` returns True when: no doc, `gym_available=False`, `gym_type ∈ {none, bodyweight_only}`, or `gym_type ∈ {"", unknown}` with empty equipment. → Path routes to `Bodyweight Layover Workout`.

---

# 14. Hotel gym equipment model

## 14.1 Canonical keys (`feature_hotel_system.py:31-36`)
```
dumbbells, adjustable_dumbbells, barbell, bench, cable_stack, smith_machine,
treadmill, stationary_bike, rowing_machine, kettlebell, resistance_bands,
pull_up_bar, medicine_ball, trx, yoga_mat, foam_roller, pool
```

## 14.2 Duplicate / competing keys
- `server.py:242-245` defines `HOTEL_EQUIPMENT_FIELDS = [dumbbells, treadmill, bike, rower, cable_machine, machines, bench, squat_rack, free_weights, pool, outdoor_running]`
- ❓ **AMBIGUOUS / DUPLICATED** — different key sets between `feature_hotel_system.HOTEL_EQUIPMENT_KEYS` (17 keys, more specific) and `server.HOTEL_EQUIPMENT_FIELDS` (11 keys, coarser). Which set is used depends on the API endpoint.

## 14.3 Recording model
- **Binary only.** No quantified fields (e.g., "dumbbells up to 30 kg" is not persisted). Coach or client can only toggle bool.
- **Confidence:** starts at 0.5 on first submission, +0.15 per subsequent confirmation, +0.2 for coach-verified, capped at 1.0.

## 14.4 Home equipment
`HOME_EQUIPMENT_OPTIONS` (server.py:234-240) — separate list, different vocabulary:
```
no equipment, yoga mat, resistance bands, pull-up bar, dumbbells,
adjustable dumbbells, kettlebells, barbell, squat rack, bench,
cable machine, treadmill, bike/turbo trainer, rowing machine,
assault bike, skipping rope, medicine ball, TRX/suspension trainer,
foam roller, mobility tools
```
❓ AMBIGUOUS — no bridge or mapping between the home vocab and the hotel vocab. `feature_v2_resolver` handles the fuzzy matching per-exercise.

## 14.5 Does the generator use equipment data?
- ✅ YES for hotel: `_day_for_prompt` injects `hotel.equipment` into the day dump; parser_constraints downgrades to bodyweight; WORKOUT_SYSTEM prompt has rule "Never prescribe an exercise the client doesn't have equipment for".
- ✅ YES for home: passed to LLM in `Client profile` dump.
- ⚠️ NO deterministic pre-generation filter for home equipment. If the LLM ignores the profile, `feature_v2_resolver` may drop or swap exercises based on the `exercises_v2.equipment_type` field.

---

# 15. Unknown hotel gym behaviour

- **Hotel unknown + `hotel_id` absent**: WORKOUT_SYSTEM prompt rule triggers (server.py:7080): "If hotel equipment is unknown, ONLY prescribe bodyweight/dumbbell-safe options." — LLM-enforced.
- **`is_bodyweight_only(hotel_doc)` returns True**: LLM chooses "Bodyweight Layover Workout"; `feature_workout_fallback` template branch is `BODYWEIGHT_LAYOVER` (see feature_workout_fallback.py:41-47).
- **Client not asked**: No modal prompts the client to enter equipment on the fly (except via `hotel-setup.tsx` before the plan is generated, and `HotelConfirmBody` post-hoc from the day view).
- **Client-facing reason strings** (`feature_hotel_system.py:243-267`):
  - `hotel_unknown` → "This session is bodyweight-safe because we don't yet know what equipment is available at your hotel. Confirm the gym setup to unlock a stronger plan."
  - `hotel_bodyweight_only` → "Your hotel has no gym — this session uses your bodyweight only…"
  - `hotel_confirmed` → "Session matched to the equipment you confirmed at this hotel."
  - `hotel_needs_confirm` → "This hotel is in our database from other crew — confirm the equipment is still accurate before training."

---

# 16. Hotel gym discovery / learning

## 16.1 What exists
- ✅ Client can submit hotel equipment via `HotelConfirmBody` in the client app.
- ✅ Coach can verify via `verified_by_coach=True` flag.
- ✅ Once submitted, the hotel is **shared across all clients** — the next crew member staying there benefits (see §46).
- ✅ Confidence score accumulates with each confirmation.

## 16.2 What does not exist
- ❌ **AI vision equipment recognition from photos** — no code path uploads a gym photo, runs vision, and writes to `hotels.equipment`.
- ❌ **Photo storage** — `hotels` schema has no `photos[]` field. No `hotel_images` collection.
- ❌ **Duplicate detection** — if client A adds "Hilton Singapore" and client B adds "Hilton Sing SG", they become two separate rows.
- ❌ **Coach moderation queue** — no dedicated review queue for hotel gyms. Coach can only edit via ad-hoc edits.
- ❌ **Version history** — updates overwrite in place; no `hotels_versions` collection.

---

# 17. Hotel gym photo → workout

**❌ NOT IMPLEMENTED end-to-end.**
- No endpoint accepts a hotel gym photo.
- No Nano Banana / Gemini vision call for equipment recognition.
- `feature_exercise_content.py` uses Nano Banana for exercise images ONLY, not for gym equipment inference.
- Coach dashboard `/coach/hotels` (frontend route) exists — but only for text-based editing (name, city, gym_type, equipment toggles).

---

# 18. Hotel room workouts

- ✅ `BODYWEIGHT_LAYOVER` template (feature_workout_fallback.py:41-47) with 5 exercises (bodyweight squat, push-up, reverse lunge, superman, hollow hold) is routed to any layover day with `is_bodyweight_only(hotel_doc)=True`.
- ✅ `FLIGHT_RECOVERY_MOBILITY` (5 exercises) applies to arrival / departure / turnaround.
- ✅ `SHORT_HAUL_AIRPORT_MOBILITY` (4 standing exercises, no floor work) for `duty_hours < 6h`.
- ✅ `ULR_RECOVERY_PROTOCOL` (7 exercises, 25 min, sleep-prep breathing) for `duty_hours ≥ 12h`.
- ⚠️ **No dedicated "gym is closed" pivot** — the client must submit a Reality event ("no gym") for the plan to swap.
- ⚠️ **No "quiet exercises" mode** — no filter for exercises safe for hotel neighbours (e.g. no jumping). LLM is not instructed.

---

# 19. Gym variants

## 19.1 Traffic-light variants (implemented)
Every workout has `variants: {green, amber, red}` (see §37). This is orthogonal to gym vs bodyweight — it's about **effort / time**, not equipment.

## 19.2 Equipment variants (partial)
- `WORKOUT_SYSTEM` output schema requires `alternatives: {home, hotel, no_equipment, easier, harder}` — the LLM populates these string fields.
- ⚠️ These alternatives are **text-only substitutions** ("swap dumbbell RDL for single-leg RDL if no DBs"). No deterministic equipment-variant plan is generated per-session.
- ❌ No pre-computed "Full Gym / Hotel Gym / Dumbbell / Bodyweight" workout matrix per date.

## 19.3 Preserving stimulus across variants
- `feature_v2_resolver` maps LLM exercise names → approved `exercises_v2` docs. If no exact match, it picks the closest `movement_pattern` + `body_area` neighbour.
- ⚠️ **No stimulus-equivalence math** (volume × intensity across variants). The `alternatives` field is a string, not a structured swap.

---

# 20. Facility changes during the day

- ✅ **Reality flow handles it**: client hits "Today's Reality" → `reality_kind="no_gym"` or `"less_time"` or `"hotel_gym_changed"` → REALITY_SYSTEM produces A/B/C options with `kind:"replace"` and new `new_location`, `new_focus`, `target_min`.
- ⚠️ **Progression preservation**: the reality prompt says (Rule 10): "MAINTAIN the training objective. Replace with bodyweight or outdoor equivalent." — LLM-enforced only.
- ❌ **No structural swap engine** — reality replies are LLM-generated JSON; there's no rule-based "if planned=push_strength and equipment=bodyweight then use bodyweight_push template".
- ✅ **Historical trace preserved**: original workout is not overwritten silently — `reality_events` collection persists what was changed and why.

---

# 21. Exercise database

## 21.1 Two schemas in production
1. **`exercises` (legacy)** — server.py's `ExerciseBody`:
```
name, category, equipment[], movement_pattern, muscle_group,
home_ok, hotel_ok, bodyweight_ok, level,
knee_friendly, back_friendly, shoulder_friendly (0-10),
fatigue_cost, ok_before_flight, ok_after_flight,
demo_url, notes, common_mistakes, regressions, progressions
```
- Reads happen in server.py:8248, 8305, 8629, 10283 etc.

2. **`exercises_v2` (new, `feature_exercise_content.py`)**:
```
id, exercise_name, category, subcategory, movement_pattern, body_area,
equipment_type[], training_type, difficulty_level, tags[],
coaching_points[], common_mistakes[], client_facing_instructions,
primary_video_url, backup_video_url, notes,
alternatives[], regressions[], progressions[],
status ∈ {Draft, Needs Review, Artwork Needed, Coaching Points Needed,
         Video Needed, Ready for Approval, Approved, Live,
         Needs Update, Rejected, Archived},
approval ∈ {pending, approved, rejected},
approved_image_status, approved_video_status,
created_at, updated_at
```
- Reads/writes in `feature_exercise_content.py` and `feature_v2_resolver`.

## 21.2 Duplication + reachability
❓ **AMBIGUOUS / DUPLICATED** — both collections are read from at runtime:
- Legacy `db.exercises` is read by server.py endpoints and by workout building in some legacy paths.
- `exercises_v2` is the target of `feature_v2_resolver.apply_resolver_to_workouts` (see server.py:7402) — this is **the reachable path from the current `_generate_month` pipeline**.

## 21.3 Migration status
`feature_admin_migrations.py:100-190` — a one-off migration copies `exercises` → `exercises_v2` on admin trigger. Not all fields transfer 1:1 (fatigue_cost, knee/back/shoulder_friendly do not map).

---

# 22. Exercise approval system

Status pipeline (feature_exercise_content.py:108-114):
`Draft → Needs Review → Artwork Needed → Coaching Points Needed → Video Needed → Ready for Approval → Approved → Live → Needs Update / Rejected / Archived`

Approval scopes (`ApproveBody.scope`): `all, images, coaching, video, mark_live, needs_update`.

**Enforcement:** `feature_v2_resolver.apply_resolver_to_workouts` explicitly filters to approved exercises. Per WORKOUT_SYSTEM code path (server.py:7395-7407): *"Constrain every client-visible exercise to the approved V2 Exercise Library. Any exercise the LLM produced that has no library match gets replaced with the closest approved substitute, and a deduplicated draft exercise request is filed for Louis to review. Unresolvable items are DROPPED (user directive: never expose unapproved exercise names to clients)."*

**Bypass risk:** If `feature_v2_resolver` fails/errors, the code catches and continues with **raw LLM output** (see server.py:7405 "falling through with raw LLM output"). This is a documented failure mode.

---

# 23. Exercise selection logic

- **LLM decides:** movement pattern balance, order, priority, variety — via WORKOUT_SYSTEM movement_mix_hint + coaching prompts.
- **`feature_v2_resolver` snaps:** each LLM name → nearest approved `exercises_v2` doc using name similarity + `movement_pattern` + `equipment_type` matching.
- **`parser_constraints.enforce_constraints_on_workouts`** — drops exercises in `blocked[]` categories (e.g. `main_strength` after ULR return).
- **`feature_live_state.PAIN_REGION_AVOID`** — LLM Rule 5(b) instructs it to avoid mapped patterns. **No deterministic post-filter** enforces this.

**Rules preventing bad programming — status:**
| Rule | Enforcement |
|---|---|
| No repeated movement pattern back-to-back | ⚠️ LLM-only via `movement_mix_hint` |
| Session duration matches exercise count | ✅ `_apply_days_cap_and_min_content` flags too-empty cards |
| Injury contraindication | ⚠️ LLM-only unless `parser_constraints.blocked[]` is set |
| Recent exposure / variety | ❌ No memory of last-week exercises passed to the LLM |
| Exercise order | ❌ LLM discretion |

---

# 24. Sets / reps / load / RPE / rest

## 24.1 Where each is set
- **LLM**: sets, reps (int OR range like "8-10"), rest_sec, rpe (1-10), notes — every workout returned by `WORKOUT_SYSTEM`.
- **Strength overload matrix** (`_STRENGTH_OVERLOAD`, see §7) — deltas applied by the LLM to primary lifts (goal-aware).
- **Template fallback** — `feature_workout_fallback.py` templates hard-code sets/reps/rest_sec/rpe per exercise.

## 24.2 Not prescribed by the system
- ❌ **Load (weight)** — never prescribed in kg. `load_delta_pct` is a directive to the LLM (server.py Rule 4) but no persisted `load_kg` field on exercises. Clients log weights per-set via `db.workout_sets` but this is not fed back to the LLM (see §28).
- ❌ **RIR** — no explicit reps-in-reserve field; RPE substitutes.
- ❌ **% 1RM** — not tracked in structured form.
- ❌ **Tempo** — mentioned only in `notes` field per exercise.
- ❌ **Heart-rate zones** — no HR data source.
- ❌ **Pace (min/km)** — RPE substitutes; no pace lookup.
- ❌ **Distance** — for runs, `duration_min` is set, distance is inferred from `_long_run_km_for_week` and included in the LLM prompt but not persisted separately.

---

# 25. Session duration

## 25.1 Duration is set by
- LLM (`duration_min` field) per prompt guidance
- `_apply_days_cap_and_min_content` (Plan A3) — enforces minimum content per duration bucket:
  - <25 min duration ✕ >5 exercises → "too many for duration"
  - >45 min ✕ <3 exercises → "insufficient content"
  - Flags the workout with `needs_coach_review=True`

## 25.2 Session-type presets (feature_programme_quality.py:212-229)
| session_type | duration_min |
|---|---|
| easy_run | 40 |
| long_run | 75 |
| tempo | 45 |
| intervals | 45 |
| strength_support | 40 |
| push_strength / pull_strength | 45 |
| leg_strength / lower_strength | 50 |
| upper_strength | 45 |
| conditioning | 30 |
| swim | 45 |
| easy_bike | 60 |
| long_bike | 90 |
| brick | 60 |
| mobility | 20 |
| recovery | 25 |

## 25.3 Adaptive session lengths
- ✅ Amber variant → `duration = 0.65 × green.duration` (feature_traffic_light.py:87-91)
- ✅ Red variant → 10-15 min mobility+breath template
- ⚠️ No "X-minute available" pre-generation — the client sets availability once in profile (`max_home_minutes`), not per-session.

---

# 26. Warm-up / mobility / cool-down

- `warmup` is a WORKOUT_SYSTEM output field (2-4 short items, per `{name, duration_sec}`).
- No dedicated cool-down field — LLM may append to exercises or rationale.
- Flight-specific mobility templates (§18) are the only "mobility-first" structured template.
- ❌ No dedicated mobility generator or mobility-only prompt.

---

# 27. Progression engine

## 27.1 Weekly progression status (`feature_progression.py`, 378 LOC)
Fires on last workout completion of the ISO week (`on_workout_completed`).

Rule engine (feature_progression.py:141-153):
```python
if very_high_rpe_count >= 2 and n_completed >= 3:   → deload
elif adherence_pct < 60.0:                          → reduce_load
elif avg_rpe >= 9.0:                                → reduce_load
elif key_missed >= 1 and adherence_pct < 80.0:      → reduce_load
elif adherence_pct >= 80 and 6.0 <= avg_rpe <= 8.5: → progressing_well
else:                                               → maintain
```
Persists to `progression_snapshots` with `metrics`, `reason`, `coach_note`.

## 27.2 Strength overload matrix (feature_programme_quality.py:371-395)
See §7. Adjusts sets_delta, reps_target, load_delta_pct, rpe by (goal_key × phase_key), scaled by prior-week adherence multiplier.

## 27.3 What the LLM actually gets
`programme_context.strength_overload` — the concrete deltas for THIS week. The LLM is prompted to apply them to "primary lifts" (Rule 4). Result quality depends on the LLM correctly identifying primary lifts.

## 27.4 What's missing / not enforced
- ❌ **No per-exercise load memory.** The `workout_sets` collection stores what the client logged, but the LLM prompt does NOT include "last week's sets/loads for exercise X".
- ❌ **No plateau detection.**
- ❌ **No PB tracking cross-referenced to prescriptions.** `personal_records` exists but is display-only.
- ⚠️ Missed session behaviour: `_adherence_multiplier` dampens next-week progression (0.0× if <50%, 0.5× if <75%). Deload phase is *not* dampened.

---

# 28. Training history / memory

**⚠️ PARTIAL / LIMITED.**

What the generator can see:
- ✅ Prior weeks' adherence (`sessions_completed_prev`, `sessions_planned_prev`) — scalar counts only
- ✅ Prior weeks' avg_rpe (from `progression_snapshots`)
- ✅ Live state pain flags (from check-ins)
- ✅ Focus shift requests (from check-in text extraction)
- ✅ Coach notes (structured overrides)

What the generator **cannot** see:
- ❌ Specific exercise loads / reps performed last week
- ❌ Which exercises were done recently (variety enforcement)
- ❌ Personal records
- ❌ Long-term trend of a specific movement pattern
- ❌ Historical injuries beyond the free-text `injury_notes` field
- ❌ Response to previous progression (did the load increase actually work?)

The `strength_metrics`, `running_metrics`, `personal_records`, `workout_sets` collections are all **write-only from the generator's perspective**.

---

# 29. Deload / fatigue management

- ✅ **Scheduled deload** — every 4th week for non-endurance (modulo cycle in `_phase_for_week`).
- ✅ **Race-anchored taper** — endurance events → taper phase at 4 weeks out, race_week at 2.
- ✅ **Reactive deload trigger** — `feature_live_state` sets `auto_deload_trigger=True` when `adherence < 0.50 AND avg_rpe_last_7d >= 8`.
- ✅ **`compute_status` deload trigger** — `very_high_rpe_count >= 2 AND n_completed >= 3` in a single week → next-week snapshot flagged as deload.
- ✅ **Prompt-level enforcement** — Rule 5(a) instructs LLM to cut 30-40% volume.
- ⚠️ No deterministic post-hoc volume-reduction pass — the LLM has to comply.
- ⚠️ Endurance cutback weeks (`_is_cutback_week`) apply to long_run distance only (`× 0.7`); other sessions unchanged.

---

# 30. Event training engine

## 30.1 Event types
`EVENT_TYPES` (server.py:645-648):
```
5K, 10K, half marathon, marathon, ultramarathon,
sprint triathlon, Olympic triathlon, Ironman 70.3, full Ironman,
cycling event, swimming event, HYROX,
strength goal, military/police/fire test, custom
```

Category catalog (`feature_event_categories.py`):
- `race` (Race / Endurance)
- `medical` (Aviation Medical / Health Check — with medical disclaimer)
- `aviation_work` (Sim Check / Line Check / Recurrent)
- `sport_hobby` (Tennis / Padel / Football / Diving / Hiking)
- `personal` (Holiday / Wedding / Photoshoot / Uniform Confidence)

## 30.2 Per-event programming (only race category is deep)
`EVENT_WEEKLY_SHAPES` (feature_programme_quality.py:139-196) has explicit shapes for:
`marathon, half_marathon, 10k, 5k, hyrox, ironman, half_ironman, sprint_tri, olympic_tri`.
Each shape has `foundation / build / peak / deload` variants.

For non-race categories, WORKOUT_SYSTEM prompt is generic ("event") and `EVENT_WEEKLY_SHAPES.get(event_type) or EVENT_WEEKLY_SHAPES['marathon']` — ⚠️ so an aviation medical event silently falls back to marathon shape when `goal_key='event'`. This looks like a bug but is functioning by design.

## 30.3 Race-week / taper / recovery
- `_event_phase(event_date)`: sets `phase = race_week` if `days_to_race <= 7`, `taper` at 8-21 days, `peak` at 4-8 weeks, `build` at 8-14 weeks, `base` at >14 weeks, `recovery` at 1-14 days post.
- `event_weekly_shape(..., "race_week", ...)` returns `[easy_run, recovery_walk, shakeout, rest, event_race, rest, rest]` — dominant volume collapse.
- Post-race recovery: `phase="recovery"` for 2 weeks after race — but no explicit recovery shape; falls back to `foundation` shape ⚠️.

## 30.4 A/B/C races, multiple events
- ✅ Multiple events supported (upsert allows). The generator reads `db.events.find_one({user_id, is_active: True}, sort=[created_at,-1])` — **only the newest active event is passed to `event_context`**.
- ❌ No A/B/C race hierarchy.
- ❌ No "event + physique goal" hybrid — the single `goal_key` decides which matrix runs.

---

# 31. Event + roster interaction

**⚠️ WEEKLY OBJECTIVES ARE NOT TRACKED AS OBJECTIVES.**

The generator does NOT think "this week we need to complete 1 long run, 1 tempo, 1 strength". It thinks calendar-day-by-calendar-day:
- `_run_chunk` produces exactly one workout per date in a 7-day window.
- `weekly_shape_ideal` is a suggested slot ordering, not a set of objectives to place around roster gaps.

**In practice:**
- The LLM tries to obey the shape order.
- If duty days conflict, WORKOUT_SYSTEM Rule "If a key session must move because of roster, MOVE it to the best day, do NOT double up" is present but LLM-enforced only.
- The `_apply_days_cap_and_min_content` hard-caps sessions at `training_days_per_week`, demoting excess to Recovery.

**No "did the long run happen this week?" backtracking.** If the LLM produced a long_run for Sunday and the client got standby-called, the reality flow can `move` it — but nothing sweeps up missed weekly objectives at the next roster generation.

---

# 32. Event priority

- ❌ No A/B/C race labelling.
- ❌ No priority engine when two events overlap.
- ❌ No "physique + event" concurrent path — a client with a marathon in 6 weeks who ALSO wants muscle gain gets only the `event` shape (no strength-focus overlay).

---

# 33. Cardio architecture

## 33.1 Cardio focuses recognised by the LLM
`focus ∈ {zone2, long_run, tempo, intervals, easy_run, swim, bike, brick, cardio, hiit, run}`.

## 33.2 Explicit progressions
- `_long_run_km_for_week` — linear ramp to peak KM (race-anchored).
- `_weekly_km_for_race` — total weekly mileage (`~3.5× long_run` build/peak, `~3× ` early).
- ❌ No pace prescription (RPE substitutes).
- ❌ No HR zones.
- ❌ No power targets for bike sessions.
- ❌ No swim distance/interval builder — the SESSION_TYPE_META swim is `{duration_min:45, focus:"swim", intensity:"RPE 5-7"}` — that's it.

## 33.3 Location interaction
- ✅ `event.access_treadmill` → LLM knows treadmill available
- ✅ `event.access_pool` → LLM knows swimming possible
- ✅ `will_run_outside` → LLM biases indoor vs outdoor
- ⚠️ No weather awareness (no weather API integration).

---

# 34. Swim / bike / run architecture

Each has minimal deep specification:
- **Swim:** `SESSION_TYPE_META["swim"]` = 45 min, RPE 5-7, "technique-first". No drills, no interval builder.
- **Bike:** `easy_bike` (60 min conversational), `long_bike` (90 min steady, key_session=True), `brick` (60 min race-prep). No power targets.
- **Run:** `easy_run`, `long_run`, `tempo`, `intervals` — each with duration + RPE guidance. No pace tables.

**⚠️ For pilots preparing for tri or IM, the actual training stimulus depends heavily on LLM discretion within these thin frameworks.**

---

# 35. Injuries / pain

## 35.1 Persistence
- `users.profile.injury_notes` / `injuries` — free text
- `users.coach_notes.cautions` — coach-only override, BINDING
- `daily_pulse` / `check_ins` — client-reported pain, extracted into `pain_flags`

## 35.2 Extraction (`feature_live_state.py`)
`PAIN_REGION_AVOID` maps 18 body regions to movement patterns to avoid:
- shoulder → overhead_press, military_press, handstand, kipping_pullup
- knee → deep_squat, pistol_squat, box_jump, high_impact_run
- lower_back → deadlift, hinge, loaded_carry, heavy_squat
- ankle → high_impact_run, box_jump, deep_squat
- wrist → push_up, handstand, front_squat
- (plus 13 more)

## 35.3 Enforcement
- ✅ WORKOUT_SYSTEM Rule 5(b): "If `avoid_movement_patterns` is non-empty — DO NOT program any exercise matching those patterns. Substitute a safe alternative."
- ⚠️ **LLM-enforced only.** No deterministic post-filter drops exercises whose `movement_pattern` field matches an avoid pattern.
- ⚠️ **Vocabulary mismatch risk.** The avoid patterns use snake_case names like "overhead_press"; `exercises_v2.movement_pattern` uses similar tokens, but there is no canonicalisation table proving they match 1:1.

## 35.4 Volume / coach review
- No injury-triggered volume reduction (unless the coach_notes.cautions text mentions it).
- No automatic coach task created on injury flag ⚠️ (should probably exist).

---

# 36. Today's Reality

See §3.3 for the prompt. **✅ IMPLEMENTED end-to-end.**

Adaptation kinds handled: `keep, reduce, extend, replace, convert_mobility, convert_recovery, convert_walk, skip, move, bring_forward, push_back, note, ask_coach`.

**What happens to today / tomorrow / week:**
- Applied changes mutate `db.workouts` directly (see `POST /api/reality/apply` in server.py).
- If `move`/`bring_forward`/`push_back` — the target date's workout is replaced.
- No "week objectives" resync afterward — the change is local.

**Structure preservation:** The prompt instructs it, but there's no guarantee — LLM discretion.

---

# 37. Readiness engine

## 37.1 Signals collected
- **Weekly check-in** (`CheckInBody`): energy, sleep, soreness, stress (1-10) + free-text notes
- **Daily pulse** (`db.daily_pulse`): daily nudge
- **Workout completion**: RPE, `completion.rpe`, timestamp

## 37.2 Signals used by generator
`feature_live_state.compute_live_state()` produces:
- `energy_delta`, `sleep_score`, `soreness_score`, `stress_score`
- `rpe_trend` (from last 14 days of completions)
- `adherence_pct`, `missed_sessions` (last 14d)
- `pain_flags` → `avoid_movement_patterns`
- `motivation_flag` → "low"/"steady"/"high"
- `focus_shift_request` → extracted from check-in text
- `life_change_flag`
- `sleep_quality_trend` (mean of last 3 check-ins)
- `auto_deload_trigger` → bool (`adherence<0.50 AND avg_rpe_7d>=8`)

**Injected as `programme_context.live_state`** into every WORKOUT_SYSTEM prompt. LLM Rule 5 covers all sub-signals.

## 37.3 UI-only signals
- `daily_briefings.card_state` — surfaced in the morning card but not fed to the generator.
- `weekly_reviews.*` — coach view only.

---

# 38. Missed session architecture

- ✅ **Detected**: `_apply_days_cap_and_min_content` counts missed sessions per rolling 7-day window; `feature_live_state` counts missed 14-day.
- ✅ **Progression impact**: `_adherence_multiplier` — 0.0× progression if <50%, 0.5× if <75%.
- ✅ **Reality flow**: client can `move` or `skip` after the fact.
- ❌ **No automatic rescheduling on miss.** Missing yesterday's long_run does not automatically insert one later this week.
- ❌ **No weekly-target catch-up logic.**
- ❌ **No future-volume compensation** — the deload/reduce_load path is the only downstream effect.

**Frontend:** `MissedSessionsCard.tsx` displays missed sessions to the client but only nudges Reality flow.

---

# 39. Weekly objectives vs calendar days

**⚠️ CALENDAR-ANCHORED, NOT OBJECTIVE-ANCHORED.**

- The generator produces exactly one workout per calendar date.
- `weekly_shape_ideal` is a *suggested slot order* — but is applied 1:1 to consecutive days in the chunk.
- No "this week needs 3 strength + 1 long run + 1 mobility, place them wherever the roster allows" scheduler.
- The `_apply_days_cap_and_min_content` pass only counts and demotes; it doesn't relocate.

**Consequence for aviation crew:** if the LLM places long_run on Tuesday but Tuesday becomes a night flight, the reality flow can shift it — but the shift does not preserve any concept of "this was the week's key long run".

---

# 40. Coach directives

## 40.1 `users.coach_notes` (structured, BINDING) — `feature_coach_notes.py`
```
{
  "preferences": str,      # "Loves KBs, hates burpees"
  "cautions": str,         # "Left shoulder — no OHP until Aug"
  "goal_override": str,    # "Actually marathon in Nov"
  "weekly_shape": str,     # "Strength Mon/Wed/Fri, run Tue/Sat"
  "notes": str,            # Free-form catch-all
  "updated_at": iso,
  "updated_by": coach_id,
  "updated_by_name": coach_name,
}
```

- ✅ Injected verbatim into WORKOUT_SYSTEM (via `coach_notes_for_prompt`) as BINDING.
- ✅ `apply_coach_note_overrides` extracts structured signals (goal, frequency, equipment) via regex → mutates `profile` dict passed to LLM (Iter 108 fix).
- Rule 9 in WORKOUT_SYSTEM: cautions NEVER violated even at the cost of an entire session; goal_override wins over `profile.goal_type`; where Coach Notes conflict with Coaching DNA, Coach Notes ALWAYS win.

## 40.2 Coach edits
- `feature_coach_deep_edit.py` — coach edits inside a client's schedule (day/workout).
- `feature_coach_workout_editor.py` — coach edits individual exercises inside a workout.
- `feature_coach_workout_swap.py` — coach swaps workouts between days.
- `PATCH /workouts/{wid}` — sets `coach_locked=True`, `approved=True`, `coach_notes` text.

## 40.3 Coach messages
- `feature_coach_v1.py` — coach draft messages (MSG_DRAFT_SYSTEM).
- `scheduled_messages` collection — timed messages.
- `messages.include_in_next_plan` (Iter 92) — coach can flag a message to be surfaced in next plan generation.

---

# 41. Rule precedence

When rules conflict, actual precedence (traced from code):

```
1. coach_locked=True workout                   → NEVER overwritten by regeneration/reality
2. Coach Notes cautions                        → LLM Rule 9 says NEVER violate, even at cost of session
3. parser_constraints (action rest_only/recovery_only/moderated)
                                              → deterministically enforced post-LLM (etihad/emirates rosters only)
4. auto_deload_trigger from live_state        → LLM Rule 5(a) forces deload week
5. pain_flags (PAIN_REGION_AVOID)             → LLM Rule 5(b) — avoid patterns (NO deterministic filter)
6. training_days_per_week cap                  → _apply_days_cap_and_min_content demotes excess (deterministic)
7. WORKOUT_SYSTEM aviation rules (24h heavy-lower, layover arrival mobility, etc.)
                                              → LLM Rule 1 (LLM-enforced)
8. goal_key + phase strength_overload         → LLM Rule 4 (LLM-enforced)
9. weekly_shape_ideal                          → LLM Rule 2 (LLM-enforced)
10. focus_shift_request                        → LLM Rule 5(c) (LLM-enforced)
11. Coaching DNA (motivation_style etc.)      → passed as context; no explicit rule number
```

**⚠️ Below the parser_constraints step, everything is LLM-enforced.** If the LLM ignores an aviation rule, only the deterministic parser_constraints and days-cap steps catch it.

**❌ NO documented precedence when rules are silent.** E.g. if goal is `build_muscle` (advises against heavy conditioning) but roster is 6 heavy duty days (advises reduce load) — the LLM decides.

---

# 42. Regeneration

`POST /api/workouts/regenerate` triggers the same `_generate_month` for a subset of dates.

## 42.1 What's protected
- ✅ **`coach_locked=True`** — skipped during upsert (see server.py:coach_confirm worker equivalent).
- ✅ **`completed=True`** — skipped (see `feature_coach_roster_upload.py:361`).
- ⚠️ **`approved=True`** — retained via `prev.get("approved", False) if prev else False`.
- ⚠️ **`coach_notes` text on the workout** — retained via `prev.get("coach_notes", "")`.
- ⚠️ **`variants`** — merged via `_merge_variants` helper.

## 42.2 What's overwritten
- Everything else — title, exercises, warmup, duration, focus, day_load, location, rationale, alternatives.

## 42.3 Historical workouts
- ✅ `workouts_archive` collection exists (in the collection list) — but no code writes to it in the paths I traced. May be a future path.
- ⚠️ `move_history` collection exists — records reality moves.
- ❌ No workout-level version history — only the current record survives.

---

# 43. Programme approval

- **What "Needs Review" means**: workout has `needs_coach_review=True` (set by fallback template + `_apply_days_cap_and_min_content` when content is thin).
- **Triggers**:
  - Fallback template used (LLM failed) → `needs_coach_review=True`
  - `parser_constraints` violated (block dropped exercises) → depends on the sanitiser
  - `_apply_days_cap_and_min_content` — too many exercises for duration OR too few
  - Coach manually toggles

- **Client visibility without coach approval**:
  - ⚠️ **Workouts ARE VISIBLE to the client immediately after generation.** `approved` starts as False; there is no gate.
  - `ProgrammeStatusCard.tsx` and `CoachApprovalQueueCard.tsx` (Phase 7B) surface an "under review" state to the client, but the underlying workouts are still shown on the calendar.
  - Coach can lock/approve individual workouts (`coach_locked=True`, `approved=True`), day/week/month/full-programme approval flows exist via `feature_coach_programme_overview`.

---

# 44. Database architecture

92 collections. Grouped by concern (only training-relevant ones detailed):

## 44.1 User + profile
`users` — {id, email, name, role, coach_notes (see §40), profile{…}}
`coaching_dna` — DNA snapshots
`dna_history` — DNA versions
`assessments` — assessment answers

## 44.2 Roster + schedule
`rosters` — {id, user_id, days[…], is_active, status, confirmed, confirmed_at, uploaded_by, uploaded_by_coach_id, start_date, end_date, day_count, source_filename, parser_source, overlap}
`roster_jobs` — job queue for parse/generate
`roster_parse_failures` — parse failures
`roster_audit_log` — roster audit trail
`schedule_events` — client schedule mutations (holiday, sickness, standby, roster_change)

## 44.3 Workouts
`workouts` — {id, user_id, roster_id, date, day_load, title, location, duration_min, focus, warmup[…], exercises[…], alternatives{…}, rationale, key_session, event_phase, source, needs_coach_review, variants{green/amber/red}, approved, completed, coach_notes, coach_locked, coach_locked_by, created_at, updated_at, completion{…}}
`workouts_archive` — archived workouts (present but unused in reachable paths)
`workout_sets` — per-set logged reps/weight/RPE
`workout_exercise_swaps` — client swaps
`move_history` — reality moves

## 44.4 Events
`events` — {id, user_id, event_type, event_name, event_date, category, current_ability, previous_time, target_time, weekly_availability_min, longest_recent, injury_history, preferred_days, access_gym/pool/bike/treadmill, include_strength, include_mobility, notes, is_active}

## 44.5 Hotels
`hotels` — see §13.

## 44.6 Exercises
`exercises` (legacy)
`exercises_v2` (current)
`exercise_content_images` (Nano Banana output)
`exercise_content_log` (change log)
`exercise_videos` (video assets)
`exercise_video_blobs` (video binary storage)

## 44.7 Progression + readiness
`progression_snapshots` — per-week progression status
`check_ins` (canonical) + `checkins` (duplicate collection, ❓ AMBIGUOUS)
`daily_pulse` — daily nudges
`daily_briefings` — morning cards

## 44.8 Coach control
`coach_tasks` — coach to-do queue
`coach_alerts` — realtime alerts
`coach_change_log` — audit log
`coach_notes_history` — historical coach notes
`coach_reset_audit`
`coach_scripts` — video scripts

## 44.9 Programme + progression
`programmes` — programme records (roster_id, week_index, goal_key, phase)
`programme_timeline` — timeline events

## 44.10 Adaptation
`reality_events` — reality submissions + choices

## 44.11 Non-training
`nutrition_*` (13 collections), `messages`, `notifications`, `progress_photos`, `body_metrics`, `strength_metrics`, `running_metrics`, `personal_records`, `personal_activities`, `habits`+`habit_events`+`habit_logs`+`habits_daily`+`habit_reviews`, `notifications`, `social_*`, `scheduled_messages`, `videos`, `weekly_reviews`, `weekly_videos`, `content_jobs`, `crewfit_images`, `ai_usage`, `app_config`+`app_config_audit`, `audit_logs`, `change_log`, `day_change_log`, `day_overrides`, `equipment_mismatches`, `gdpr_audit`, `gen_jobs`, `image_jobs`, `preview_audit`, `reassessment_prompts`+`reassessment_responses`, `support_events`, `timeline_events`, `ui_issues`.

## 44.12 Relationships (informal)
```
users ─┬─→ profile{}  ─→ referenced by rosters, workouts, events, check_ins
       ├─→ coach_notes{} ─→ injected into WORKOUT_SYSTEM
       └─→ coaching_dna ─→ dna_ctx

rosters ─→ days[…] ─→ hotel_id ─→ hotels
rosters ─→ workouts (via roster_id)
events ─→ workouts (via active event → event_context)
workouts ─→ workout_sets (per-set logs)
workouts ─→ progression_snapshots (via ISO week rollup)
check_ins ─→ live_state (on users.profile) ─→ WORKOUT_SYSTEM
reality_events ─→ workouts (via applied actions)
```



---

# 45. Hotel database architecture (detail)

See §13 for schema. Additional observations:

**Fields present:** `id, name, city, country, gym_available, equipment{}, gym_type, safe_outdoor_run, pool, opening_hours, verified_by_coach, confidence, notes`.

**Fields NOT present** (frequently expected but absent):
- ❌ Airport IATA association (a hotel isn't linked to a specific airport)
- ❌ Coordinates (lat/long)
- ❌ Photos array
- ❌ Room-workout suitability score (walls thin? floor space?)
- ❌ Last_verified_at (only `confidence` and `verified_by_coach` bool)
- ❌ Source tracking (which client uploaded the data?)
- ❌ Multiple submissions history (all writes overwrite in place)
- ❌ Audit trail

---

# 46. Data sharing between clients

**Hotels are a shared resource.** `db.hotels` is a global collection — no `user_id` scope on the hotel doc.

- ✅ **Reuse works**: if client A adds "Marriott Singapore" with dumbbells+bench+cables, client B who lands there and picks that hotel ID gets the same equipment map.
- ✅ **Confidence accumulates**: each subsequent confirmation nudges `confidence` up.
- ⚠️ **Coach can verify** with `verified_by_coach=True` (+0.2 confidence).
- ❌ **Attribution is lost**: no "originally submitted by" field.
- ❌ **Duplicate risk**: "Marriott SG" and "Marriott Singapore" become 2 rows.
- ❌ **Cross-client de-duplication** relies on the client picking the same row.

---

# 47. Data freshness

- `confidence` score is the only staleness proxy.
- ❌ No `last_verified_at` timestamp.
- ❌ No decay of confidence over time.
- ❌ No prompting after N months to re-verify.
- ❌ No version history.

---

# 48. API map (training-relevant subset)

See §2.2 for counts. Key endpoints:

## Roster
- `POST /api/roster/extract` — legacy sync parse
- `POST /api/roster/upload-parse` — background parse to pending roster
- `POST /api/roster/upload-and-generate` — parse + auto-confirm (dev-only?)
- `POST /api/roster/pending/{rid}/confirm` — client confirms
- `POST /api/coach/clients/{cid}/roster/upload-parse` (Iter 109) — coach uploads on behalf
- `POST /api/coach/clients/{cid}/roster/pending/{rid}/confirm` (Iter 109) — coach confirm
- `GET /api/roster/current` — client's active roster (merged multi-active as of Iter 109)
- `GET /api/roster/jobs/{job_id}` — job progress
- `GET /api/coach/clients/{cid}/roster/months` — coach navigator
- `GET /api/coach/clients/{cid}/roster/months/{key}` — month detail

## Workouts
- `GET /api/workouts/week` — client week
- `POST /api/workouts/generate-month` — trigger generation
- `POST /api/workouts/regenerate` — regenerate scoped dates
- `POST /api/workouts/{wid}/complete` — mark complete + trigger progression
- `PATCH /api/workouts/{wid}` — coach edits
- `PATCH /api/coach/clients/{cid}/workouts/{wid}` — coach patch scope

## Calendar
- `GET /api/calendar/range?from=&to=` — merged workout + roster days + activities

## Events
- `POST /api/events` — upsert event
- `PATCH /api/events/{eid}` — update
- `DELETE /api/events/{eid}` — deactivate
- `GET /api/events/catalog` — category catalog

## Hotels
- `POST /api/hotels/search`, `GET /api/hotels`, `POST /api/hotels`, `PATCH /api/hotels/{hid}`
- `POST /api/roster/{rid}/day/{date}/hotel` — attach hotel to a day
- `POST /api/hotels/{hid}/confirm` — client confirms equipment

## Reality
- `POST /api/reality/submit` — LLM options
- `POST /api/reality/apply` — apply chosen option

## Coach
- `PUT /api/coach/clients/{cid}/coach-notes` — set structured notes
- `GET /api/coach/clients/{cid}/coach-notes`

## Progression
- `GET /api/progress/current` — snapshot of current progression status

## Checkins
- `POST /api/checkins` — submit weekly check-in
- `GET /api/checkins/questions` — personalised 6 questions

## Programme status (Phase 7B)
- `GET /api/programme/status` — client polling snapshot

---

# 49. Frontend → backend flows

**Client uploads roster** → `roster-upload.tsx` → `POST /api/roster/upload-parse` → poll `/api/roster/jobs/{id}` → `POST /api/roster/pending/{rid}/confirm` → generation triggered → poll same job → workouts appear on `/(client)/home.tsx`.

**Coach uploads roster** (Iter 109) → `CoachRosterUploadButton` → `POST /api/coach/clients/{cid}/roster/upload-parse` → poll → auto `POST /api/coach/clients/{cid}/roster/pending/{rid}/confirm` → generation.

**Programme by Month** → `/coach/client-months/[id]` → `GET /api/coach/clients/{cid}/roster/months` → tabs render → click month → `GET /api/coach/clients/{cid}/roster/months/{key}` → shows roster + assigned workouts side-by-side.

**Client "Today's Reality"** → `RealityModal.tsx` → `POST /api/reality/submit` → shows A/B/C cards → user taps → `POST /api/reality/apply` → workouts mutated.

**Client reports no gym** → same Today's Reality flow, `reality_kind="no_gym"`.

**Client uploads hotel gym image** → ❌ **NOT IMPLEMENTED** (see §17).

**Coach edits workout** → `/coach/workout/edit/[wid]` → `PATCH /api/workouts/{wid}` (or `feature_coach_workout_editor` endpoints for per-exercise swap) → workout stamped `coach_locked` if desired.

**Client completes session** → workout screen → `POST /api/workouts/{wid}/complete` → server persists `completion{rpe, notes, sets_done}` → `feature_progression.on_workout_completed` fires → if last of week, `progression_snapshots` upsert.

**Client misses session** → passive (no action). Next generation reads adherence via `strength_overload_for`.

**Client submits weekly check-in** → `checkin.tsx` → `POST /api/checkins` → `feature_live_state.compute_live_state` writes `users.profile.live_state` → next roster generation reads it.

**Client adds event** → `event.tsx` → `POST /api/events` → next `_generate_month` reads active event → `event_context` injected.

---

# 50. Automations / background tasks

- ✅ **Roster parse worker** — `asyncio.create_task` fired inside `POST /roster/upload-parse` and coach variant. In-process, not queued.
- ✅ **Plan generation worker** — same pattern.
- ✅ **Progression trigger** — synchronous inside `POST /workouts/{wid}/complete`.
- ✅ **Coach task creation** — synchronous on plan failure, plan approval, etc.
- ✅ **`_generation_heartbeat`** — updates `roster_jobs` periodically so client UI shows progress.
- ⚠️ **Notification digests** — `feature_notifications.py` includes scheduled paths but requires deploy-side APNs/FCM (currently mocked with `EMERGENT_PUSH_KEY` placeholder).
- ❌ **No cron** — no scheduled generation. Everything is event-driven (roster upload / reality submit / completion / coach edit).
- ❌ **No monitoring job for stale rosters** (e.g., "your roster ends in 3 days — upload next month").

---

# 51. Failure modes

| Failure | Actual behaviour |
|---|---|
| Claude call fails / times out per chunk | Chunk returns 0 workouts; other chunks unaffected. Missing days get template fallback OR remain empty. |
| Whole LLM path returns 0 | `feature_workout_fallback.build_template_plan` runs; workouts stamped `source='template'`, `needs_coach_review=True`; coach task opened. |
| Gemini roster parse fails | ROSTER_SYSTEM fallback: 7-day placeholder with day_type="Home Day", confidence=0.2. |
| Hotel unknown | Bodyweight-safe path (§15). |
| No exercise matches equipment | `feature_v2_resolver` drops the exercise entirely; card may be under-filled → `_apply_days_cap_and_min_content` flags for coach review. |
| No appropriate workout exists for parser action | `sanitize_workout_for_day` in `parser_constraints` replaces with mobility/recovery. |
| Event too close (weeks_to_race < 0) | Phase = `post` (post-race recovery) — but recovery shape isn't defined for negative weeks; falls through to `foundation` shape ⚠️. |
| Client hasn't trained (all missed) | `_adherence_multiplier=0.0` → no progression next week; `progression_snapshots` = `reduce_load`. |
| Profile incomplete (goal missing) | `_resolve_goal_key` returns `general_fitness` default. |
| Severe restrictions | Depends on `coach_notes.cautions` and `pain_flags`. If not populated → LLM only. |
| Plan generation partially succeeds (some chunks fail) | Persist what came back; empty days get NO workout. Client sees a gap. |

---

# 52. Hardcoded programming rules

| Rule | Value | Location | Purpose | Configurable |
|---|---|---|---|---|
| Layover threshold | 18h | feature_hotel_system.py:24 | Layover vs turnaround | No — module const |
| Long-run peak KM cap | Marathon 32, Half 20, 10k 14, 5k 8, IM 30, Hyrox 10, 70.3 18, Olympic 12, Sprint 8, Ultra 40 | feature_programme_quality.py:305-316 | Long-run ramp | No — dict const |
| Long-run base KM | 6.0 | feature_programme_quality.py:328 | Ramp start | No |
| Weekly km multiplier | 3.5× (build/peak) or 3.0× (early) | feature_programme_quality.py:352 | Total weekly mileage | No |
| Cutback week frequency | every 4 weeks in build/peak | feature_programme_quality.py:362 | Endurance cutback | No |
| Cutback multiplier | 0.7× | feature_programme_quality.py:342 | Cutback long-run reduction | No |
| Race-week volume collapse | ×0.75 (3wk), ×0.5 (1wk) | feature_programme_quality.py:335-338 | Taper | No |
| Modulo phase cycle | 4 (Foundation→Build→Peak→Deload) | feature_programme_quality.py:283 | Non-endurance | No |
| Deload volume reduction | 30-40% | Prompt Rule 5(a) + strength_overload | Deload | No |
| training_days_per_week hard cap | Read from profile; if unset → LLM prompt says "match" | server.py:7294 | Session cap | Per-client |
| Deload trigger — very-high-RPE count | ≥2 (with n_completed ≥ 3) | feature_progression.py:142 | Reactive deload | No |
| Auto-deload from live_state | adherence < 0.5 AND avg_rpe_7d ≥ 8 | feature_live_state.py (docstring) | Auto-deload | No |
| Adherence multiplier | 0.0× (<50%), 0.5× (<75%), 1.0× else | feature_programme_quality.py:399-408 | Progression dampen | No |
| Chunk timeout | 75s | server.py:7345 | Per-week LLM cap | No — code const |
| Roster generation timeout | 180s | feature_coach_roster_upload.py:322 | Outer worker cap | No |
| Amber variant factor | 0.65× volume, 0.85× reps | feature_traffic_light.py:63-75 | Amber derivation | No |
| Confidence step | +0.15 per confirmation, +0.2 coach-verified, cap 1.0 | feature_hotel_system.py:204-217 | Hotel confidence | No |
| Session-type presets | See §25.2 | feature_programme_quality.py:212-229 | Duration/RPE per session | No — dict const |

---

# 53. Duplicated logic

## ❓ AMBIGUOUS / DUPLICATED zones

1. **Workout template fallback (V1 vs V2)**
   - `feature_workout_fallback.py` (874 LOC, deterministic templates)
   - `feature_workout_fallback_v2.py` (newer, present but usage unclear)
   - `server.py:_generate_month` imports V1 (`build_template_plan`); V2's role in current pipeline is unclear from reachability trace. **Both exist, both callable, but V1 is the one wired into the main path.**

2. **Exercise library (`exercises` vs `exercises_v2`)** — See §21. Two schemas, two collections, both read at runtime.

3. **Check-in collections (`check_ins` vs `checkins`)**
   - Both appear in the collections list. Likely a historical typo. Which one is authoritative depends on the endpoint.

4. **HOTEL_EQUIPMENT_FIELDS vs HOTEL_EQUIPMENT_KEYS**
   - server.py has 11 keys; feature_hotel_system has 17 keys with different naming.

5. **Goal resolution: `main_goal_key` vs `main_goal` vs `primary_goal` vs `goal` vs `goal_type`**
   - Five fields, each with different resolvers (`_resolve_goal_key`) and different override rules (coach_notes overrides `goal_type` but not `main_goal_key`).

6. **Phase logic: `_phase_for_week` (modulo) vs `_phase_for_weeks_to_race` (race-anchored)**
   - Both are consulted; the code chooses based on whether `goal_key == 'event'` and event is set. Different results for a `event`-goal client with no event.

7. **Roster parsing: 3 paths**
   - `parsers/etihad.py` if detected
   - `parsers/emirates.py` if detected
   - `ROSTER_SYSTEM` LLM fallback otherwise
   - Different confidence + labelling quality per path. Parser-constraints only fire when etihad/emirates ran.

8. **`_generate_month` in server.py vs `_generate_month` in `feature_coach_roster_upload.py`**
   - The coach roster upload imports `_generate_month` from server.py directly. Client roster confirmation also uses `_generate_month`. Both share the same code path — ✅ NOT actually duplicated. ✅ Confirmed single canonical function.

---

# 54. Legacy / unused architecture (documented, not deleted)

- `feature_workout_fallback_v2.py` — present but not wired into main path.
- `db.exercises` — reads still happen but the resolver uses `exercises_v2`.
- `test_iter95a.py`, `test_iter95g.py` in backend root — old test scaffolds.
- `feature_workout_guardrails.py` — role in current pipeline unclear; may be a legacy validator superseded by `parser_constraints` + `_apply_days_cap_and_min_content`.
- `workouts_archive` collection — collection exists; no active write path traced.
- `library-legacy.tsx` (frontend coach route) — kept for reference; `library.tsx` supersedes.
- `feature_media_reconciliation.py` — appears to be a one-off migration utility.
- `feature_admin_migrations.py` — one-off migrations (v1→v2 exercises etc.).

---

# 55. Current capability matrix

| Feature | Status |
|---|---|
| Goals — 8 canonical keys | ✅ IMPLEMENTED |
| Multiple concurrent goals | ❌ NOT IMPLEMENTED |
| Programme phases (Foundation/Build/Peak/Deload) | ✅ IMPLEMENTED (non-endurance: modulo; endurance: race-anchored) |
| Periodisation with race anchor | ✅ IMPLEMENTED |
| Strength progression matrix | ✅ IMPLEMENTED (goal × phase × adherence) |
| Load memory across sessions | ❌ NOT IMPLEMENTED (RPE only) |
| Cardio Zone-based prescription | ⚠️ PARTIALLY — RPE substitutes, no HR |
| Running distance ramp | ✅ IMPLEMENTED (endurance events only) |
| Cycling structured intervals | ❌ NOT IMPLEMENTED |
| Swimming drills / interval builder | ❌ NOT IMPLEMENTED |
| Race distances supported | ✅ 9 (marathon, half, 10k, 5k, hyrox, ironman, half_ironman, sprint_tri, olympic_tri) |
| Tapering | ✅ IMPLEMENTED (race-anchored) |
| Post-race recovery | ⚠️ PARTIALLY (falls back to foundation shape) |
| Aviation roster parsing | ✅ Etihad + Emirates parsers · ⚠️ Others via LLM only |
| Duty timing → training envelope | ✅ IMPLEMENTED via ROSTER_SYSTEM + LLM rules + parser_constraints |
| Time zones / jet lag | ❌ NOT IMPLEMENTED for training decisions |
| Layover ≥18h detection | ✅ IMPLEMENTED |
| Turnaround <18h detection | ✅ IMPLEMENTED |
| Recovery-first days | ✅ IMPLEMENTED (long-haul + ≥18h layover) |
| Tiered flight recovery | ✅ IMPLEMENTED (short/medium/ULR by duty_hours) |
| Hotel gym profiles | ✅ IMPLEMENTED (shared, confidence-scored) |
| Hotel gym database (cross-client reuse) | ✅ IMPLEMENTED |
| Hotel equipment binary tracking | ✅ IMPLEMENTED |
| Hotel equipment QUANTIFIED (dumbbell max kg) | ❌ NOT IMPLEMENTED |
| Hotel gym photo → equipment recognition | ❌ NOT IMPLEMENTED |
| Hotel room bodyweight workouts | ✅ IMPLEMENTED |
| Hotel gym unknown fallback | ✅ IMPLEMENTED |
| Full gym / hotel gym / dumbbell / bodyweight structured variants | ⚠️ PARTIALLY — `alternatives` string field, no matrix |
| Exercise substitutions via approved library | ✅ IMPLEMENTED (feature_v2_resolver) |
| Injury restrictions (pain regions → avoid patterns) | ⚠️ LLM-enforced only |
| Injury restrictions (coach_notes.cautions) | ✅ BINDING via prompt Rule 9 |
| Weekly check-in signals | ✅ IMPLEMENTED |
| Daily pulse | ⚠️ PARTIALLY — endpoint exists, UI usage limited |
| Today's Reality (adaptation) | ✅ IMPLEMENTED (LLM-driven A/B/C options) |
| Missed session automatic reschedule | ❌ NOT IMPLEMENTED |
| Coach directives (structured notes) | ✅ IMPLEMENTED (BINDING) |
| Coach message drafts | ✅ IMPLEMENTED |
| Coach edits protected on regeneration | ✅ IMPLEMENTED (coach_locked, completed) |
| Programme approval | ⚠️ PARTIALLY — approval flag exists but workouts visible pre-approval |
| Programme regeneration (per date / week / month) | ✅ IMPLEMENTED |
| A/B/C race hierarchy | ❌ NOT IMPLEMENTED |
| Coach + client both editable same doc | ✅ (with coach_locked precedence) |

---

# 56. Real-scenario traces

## Scenario A — Short-haul cabin crew + fat loss
**Client:** cabin crew, EK short-haul (mixed), goal `lose_fat`, `training_days_per_week=3`, no event.

Trace:
1. Roster uploaded → Emirates parser detects — `parsers/emirates.py::parse_emirates_pdf`
2. `parsers/emirates_labels.py` writes `training_colour` + `equipment_assumption` + `blocked[]` per day
3. `_persist_pending_roster` → client confirms → `_generate_month` runs
4. `programme_context_for_llm`:
   - goal_key='lose_fat', target=3, weekly_shape_ideal=STRENGTH_WEEKLY_SHAPES['lose_fat'] = `[upper_strength, conditioning, lower_strength, mobility, recovery×3]`
   - phase = `foundation` (week 1)
   - `strength_overload_for('lose_fat','foundation',…)` = `{sets_delta:0, reps_target:"10-12", load_delta_pct:0, rpe:"7", note:"Full-body compounds + short conditioning finisher (6–8 min)."}`
5. Each 7-day chunk → WORKOUT_SYSTEM prompt with hotel enrichment
6. `parser_constraints.enforce_constraints_on_workouts` demotes any early-report day workouts to mobility (Emirates parser catches turnarounds)
7. `_apply_days_cap_and_min_content` caps at 3 training sessions
8. `apply_layover_naming` renames titles referencing layover cities

**Actual output shape:** ~3 real strength/conditioning sessions on home/off days, mobility on turnaround days, recovery on flying days.

## Scenario B — Long-haul pilot + strength
**Client:** pilot, EK long-haul, goal `build_muscle`, `training_days_per_week=4`, UK→SIN 48h layover.

Trace:
1. Emirates parser detects long-haul + layover
2. `_roster_summary` populates `recovery_first_days=[<UK→SIN date>]` and `recovery_tiered_days=[{date, tier:'ulr', duty_hours:14+}]`
3. `weekly_shape_ideal = [push_strength, pull_strength, leg_strength, upper_strength, mobility, recovery, recovery]`
4. `strength_overload_for('build_muscle','foundation')` = `{sets_delta:0, reps_target:"8-12", load_delta_pct:0, rpe:"7", note:"Groove technique. Stop 2–3 reps in reserve."}`
5. WORKOUT_SYSTEM Rule 6 forces the SIN-arrival day to: 10 min mobility → moderated session ≤RPE7 ≤45min
6. WORKOUT_SYSTEM Rule 7 tier='ulr' → ULR_RECOVERY_PROTOCOL is the template if LLM fails; if LLM succeeds it should mirror the protocol (thoracic decompression + glute activation + 4-7-8 breath)
7. Full layover day (SIN, hotel gym known) → LLM picks `Hotel Gym Workout` + upper/lower split
8. Return leg — another `recovery_tiered_days` entry
9. `_apply_days_cap_and_min_content` caps at 4 real training sessions in 7d

## Scenario C — Muscle gain + hotel gym (dumbbells 22kg, adjustable bench, cable, treadmill)
1. Hotel doc exists with `equipment = {dumbbells:True, bench:True, cable_stack:True, treadmill:True}`, `gym_type=basic`
2. `_day_for_prompt` injects hotel info
3. WORKOUT_SYSTEM sees available equipment string and picks accordingly
4. `feature_v2_resolver` maps LLM-produced exercise names to approved `exercises_v2` docs whose `equipment_type` intersects the hotel equipment. **⚠️ No enforcement of the "22kg" limit** — the resolver has no load-cap awareness.
5. **⚠️ No stimulus-preservation math** — a client normally squatting a barbell would get "dumbbell goblet squat" as a text alternative, not a stimulus-equivalent replacement.

## Scenario D — No gym, 25 min in room
1. Client hits Reality → `reality_kind="less_time"` + `time_available_min=25` OR `reality_kind="no_gym"`
2. REALITY_SYSTEM produces A/B/C options
3. Option A likely = `{kind:"replace", new_title:"25 min Hotel Room Session", new_focus:"bodyweight", target_min:25}` — LLM discretion
4. Client picks A → `POST /reality/apply` mutates the workout in-place
5. `feature_workout_fallback.BODYWEIGHT_LAYOVER` template is NOT auto-loaded — the LLM chooses exercises. If LLM fails, no reality fallback engine exists ❌.

## Scenario E — Unknown hotel gym
1. Day has `hotel_id` but hotel doc has empty `equipment` and `gym_type="unknown"`
2. `is_bodyweight_only(hotel_doc)` → True
3. Client reason string: "This hotel is in our database from other crew — confirm the equipment is still accurate before training."
4. Workout builds as bodyweight-safe.

## Scenario F — Hotel gym photo uploaded
**❌ NOT IMPLEMENTED.** No endpoint, no vision call, no equipment writeback.

## Scenario G — Ironman 70.3, 16 weeks out, irregular long-haul roster
1. Event created → `event_type='ironman'` or `half_ironman`
2. `_event_phase` → `phase="build"` (16 weeks = boundary — actually returns `build` since weeks ≤ 14 is `build`, else `base`; 16 weeks-to-race = `base` per rule "weeks <= 14 → build, else base")
3. `_phase_for_weeks_to_race(16) = base`
4. `event_weekly_shape('half_ironman', 'base', 4) = [easy_run, long_bike, swim, strength_support]` (base shape trimmed to 4)
5. `_long_run_km_for_week('half_ironman', 16) ≈ 6-8km` (base ramp start)
6. WORKOUT_SYSTEM sees `weekly_shape_ideal` + event_context
7. **⚠️ The roster with 2 long-haul flights forces the LLM to pack the ideal shape into ~2 home days.** The LLM has to decide whether to drop swim or the long_bike or move them; no algorithmic scheduler intervenes.
8. `_apply_days_cap_and_min_content` will cap at 4 sessions.
9. **Result quality is LLM-dependent.** If the model correctly recognises "long_bike must be on the free Saturday", great. If not, it may distribute suboptimally.

## Scenario H — Knee pain on planned lower workout during layover
1. Client's `pain_flags` include `{region:"knee"}` from a check-in
2. `PAIN_REGION_AVOID["knee"] = [deep_squat, pistol_squat, box_jump, high_impact_run]`
3. WORKOUT_SYSTEM Rule 5(b) instructs LLM to avoid those patterns
4. **⚠️ LLM-enforced only.** If it slips in a deep-squat exercise, `feature_v2_resolver` may not catch it (no post-filter for `movement_pattern` against avoid list).

## Scenario I — Roster changes after programme approval
1. Client re-uploads roster → `_detect_overlap` finds overlap with existing active roster
2. New roster becomes pending; old roster's overlapping dates are marked `superseded`
3. Client confirms → generation runs; `coach_locked=True` and `completed=True` workouts are preserved.
4. Everything else is regenerated.

## Scenario J — Missed strength workout
1. Session not completed by end of day → passive state
2. `feature_progression.on_workout_completed` fires only on the NEXT completion — that's when it checks whether this was "last of week"
3. If Sunday's completion arrives with an earlier missed session: `compute_status` records `key_missed>=1`, `adherence < 80` → `reduce_load` status
4. Next roster generation reads `sessions_completed_prev / sessions_planned_prev` → `_adherence_multiplier` dampens progression 50%
5. **The missed session itself is NOT rescheduled.** No week-objective preservation.

---

# 57. Training quality gaps

**Exercise science:** ✅ Explicit sets/reps/RPE prescriptions per session type. ⚠️ No structured `%1RM`, load memory or PB integration into future prescriptions. ⚠️ Movement pattern balance is LLM-instructed but not enforced. ❌ No exercise variety enforcement (repeated exposure not tracked in prompt).

**Periodisation:** ✅ 4-phase cycle + race-anchored taper. ⚠️ Non-endurance phases advance modulo — no true progression through microcycles. ❌ No block periodisation. ❌ No conjugate/DUP methodologies.

**Strength programming:** ✅ Goal × phase × adherence matrix. ⚠️ Load progressed as `load_delta_pct` — LLM instruction, not persisted. ❌ No auto-regulation via bar speed / velocity.

**Endurance programming:** ✅ Long-run KM ramp, cutback weeks, taper. ⚠️ No pace / HR / zone data. ❌ No lactate threshold / VO2 estimation.

**Event preparation:** ✅ 9 race types with dedicated shapes. ⚠️ Non-running event categories fall back to marathon shape.

**Aviation adaptation:** ✅ Layover / turnaround detection, tiered recovery, recovery-first days. ⚠️ Circadian / TZ math absent.

**Circadian / recovery:** ❌ No circadian modelling.

**Hotel gym intelligence:** ⚠️ Binary equipment tracking; no weight caps; no photo recognition; no cross-client photo library.

**Equipment adaptation:** ⚠️ LLM-based swap; no stimulus-equivalence math.

**Exercise selection:** ✅ Snapping to approved library. ⚠️ No repeated-exposure penalty.

**Progression:** ✅ Weekly snapshot + strength overload matrix. ❌ No specific-exercise memory.

**Injury handling:** ⚠️ PAIN_REGION_AVOID + coach_notes.cautions; not deterministically post-filtered.

**AI consistency:** ⚠️ 75s timeout per chunk; missing chunks silently drop.

**Coach control:** ✅ Coach notes BINDING; coach_locked protection; deep-edit endpoints.

**Data architecture:** ⚠️ 92 collections including 2 duplicate pairs (`check_ins`/`checkins`, `exercises`/`exercises_v2`).

**Testing:** ⚠️ 8 pytest files under `backend/tests`. Programme quality validation tests exist but coverage of prompt-driven paths is limited.

---

# 58. AI cost & performance (per event)

| Event | LLM calls | Model | Duration | Notes |
|---|---|---|---|---|
| Roster parse (Etihad/Emirates) | 0 LLM | rule-based | <5s typical | Falls back to Gemini if detection fails |
| Roster parse fallback (unknown airline) | 1 (Gemini file) | Gemini | 15-60s | Attaches PDF as file |
| Monthly plan generation | N chunks × 1 Claude call | Claude Sonnet 4.5 | ~40-70s per chunk, parallel | 4 chunks = 4 concurrent Claude calls for a 28-day roster |
| Today's Reality | 1 Claude call | Claude Sonnet 4.5 | 10-30s | Context includes -2/+7 window |
| Weekly check-in question generation | 1 Claude call | Claude Sonnet 4.5 | 5-15s | Per weekly cycle |
| Coach script generation | 1 Claude call | Claude Sonnet 4.5 | 15-30s | On demand |
| Meal photo analysis | 1 Claude vision call | Claude Sonnet 4.5 (vision) | 10-30s | Per meal upload |
| Exercise image generation | 1 Nano Banana call per slot | Gemini image | 10-40s | Admin trigger |
| Hotel photo → equipment | ❌ NOT IMPLEMENTED | — | — | — |

**Duplicate LLM work:**
- `programme_context_for_llm` is called TWICE in `_generate_month` if not passed in (once inside if None + caller may compute for validation). Best-practice callers pass it.
- DNA context is fetched once per plan generation, not per chunk.
- Hotel cache warmed once.

---

# 59. Testing coverage

Tests present (`/app/backend/tests/`):
- `test_assessment_engine.py` — DNA/assessment flow
- `test_coach_roster_months.py` — coach navigator
- `test_coach_roster_upload.py` (Iter 109 — added this session)
- `test_roster_month_preservation.py` (Iter 109 — added this session)
- `test_emirates_parser.py`, `test_emirates_labels.py` — Emirates parser
- `test_etihad_labels.py` — Etihad label engine
- `test_iter109_coach_roster_http.py` — HTTP integration (added by testing agent this session)
- `test_layover_naming.py` — Iter 102
- `conftest.py`, `fixtures/`

Also legacy `test_iter95a.py`, `test_iter95g.py` in backend root.

**❌ NO TESTS FOUND FOR:**
- `WORKOUT_SYSTEM` prompt behaviour end-to-end
- Progression rule engine
- Live state pain flag extraction
- Hotel classify_stay logic
- feature_workout_fallback templates
- feature_v2_resolver matching quality
- parser_constraints enforcement
- Reality flow apply logic
- Coach notes override extraction

---

# 60. Data integrity risks

- ⚠️ **Coach change overwrite risk:** `regenerate` protects `coach_locked=True` but NOT `approved=True` alone. If a coach approves without locking, regeneration wipes the edit.
- ✅ **Completed workouts preserved.**
- ✅ **Historical months preserved** (as of Iter 109 fix — see `/app/memory/COACH_DASHBOARD_REBUILD_PLAN.md`).
- ⚠️ **`db.workouts.delete_many({user_id, date})` in coach-confirm worker** — mass delete before insert; if the insert fails partway, data is lost. No transaction.
- ⚠️ **Duplicate schedule days:** `_apply_days_cap_and_min_content` demotes but doesn't remove; multiple rosters covering same date would produce duplicates until the multi-roster merge (Iter 109) added `newest wins` semantics.
- ⚠️ **Hotel data cross-contamination:** shared collection; a wrong equipment toggle by one client shows for all clients until confidence-driven correction.
- ⚠️ **`db.exercises` vs `db.exercises_v2`:** two libraries; a client-visible exercise from `db.exercises` cannot be approved via the v2 approval pipeline.

---

# 63. Scorecard (out of 10)

| Area | Score | Rationale |
|---|---:|---|
| Overall Training Intelligence | 5/10 | Strong periodisation + roster awareness; weak on load memory, injury enforcement, weekly objectives. |
| Goal Programming | 6/10 | 8 distinct goals with matrix + shape + overload; but 4 of the 8 fall through to `general_fitness` overload; no multi-goal. |
| Periodisation | 6/10 | Modulo cycle + race-anchored taper; ✅ deterministic; ❌ no true macrocycle. |
| Workout Construction | 5/10 | LLM-driven with parser safety net; ⚠️ resolver drops silently; no explicit warm-up/cool-down engine. |
| Exercise Selection | 4/10 | Resolver snaps to approved library; no repeated-exposure penalty; no variety mandate. |
| Strength Progression | 5/10 | Matrix + adherence dampening; but load memory absent. |
| Endurance Programming | 5/10 | Long-run KM ramp + cutback weeks; ⚠️ no pace/HR, thin bike/swim. |
| Event Preparation | 6/10 | 9 race types with tapers; multi-race and non-race categories weak. |
| Roster Intelligence | 7/10 | 17 day types, standby subtypes, tiered recovery, layover detection. |
| Flight/Duty Intelligence | 6/10 | Duty hours drive recovery tier; sectors underused. |
| Time-Zone Intelligence | 2/10 | Frontend surfaces TZ; ❌ training never sees it. |
| Recovery Intelligence | 6/10 | Live state pain/motivation/focus-shift + tiered recovery. |
| Hotel Gym Intelligence | 5/10 | Shared confidence-scored profiles; binary equipment; no weight caps; no photo path. |
| Equipment Intelligence | 4/10 | LLM equipment check + resolver drops; no stimulus math. |
| Hotel Room Adaptation | 6/10 | Explicit bodyweight template + reason strings. |
| Injury Handling | 4/10 | PAIN_REGION_AVOID + coach cautions; but LLM-only enforcement. |
| Today's Reality | 7/10 | End-to-end LLM adaptation with 13 action kinds. |
| Coach Control | 7/10 | Structured coach notes BINDING; coach_locked; edit endpoints. |
| AI Reliability | 5/10 | 75s per-chunk cap; fallback template; missing weeks are silent. |
| Data Architecture | 4/10 | 92 collections including duplicates; 2 exercise libraries; hotel schema thin. |
| Testing | 3/10 | ~10 test files; no prompt-behaviour or resolver-quality tests. |

## Top 10 strengths
1. Roster parsers (Etihad + Emirates) with explicit label engine
2. Deterministic parser-constraints safety net after LLM
3. Multi-active-roster merge (Iter 109) preserves history
4. Race-anchored endurance periodisation with KM curves
5. Strength overload matrix keyed on goal × phase × adherence
6. Traffic-light variants (green/amber/red) on every workout
7. Live State pipeline extracting pain / motivation / focus-shift from check-ins
8. Coach Notes system as first-class BINDING override
9. Reality flow with 13 action kinds and 3 ranked options
10. Approved-exercise resolver preventing unapproved names reaching clients

## Top 10 biggest weaknesses
1. No load memory — the LLM cannot see what the client actually lifted last week
2. No time-zone / circadian modelling in training decisions
3. No true weekly-objective tracking — everything is calendar-anchored
4. Missed sessions are not rescheduled; only progression is dampened
5. Injury restrictions are LLM-enforced only; no deterministic post-filter
6. Hotel gym equipment is binary — no weight caps, no room for "DBs to 22kg"
7. Hotel gym photo → equipment recognition entirely missing
8. Multi-goal / A-B-C race hierarchy unsupported
9. Two exercise collections; two check-in collections; ambiguous hotel key sets
10. LLM chunk failures produce silent gaps in the calendar

## Top 10 highest-risk architectural problems
1. Silent LLM chunk drop — a client can end up with 2 weeks of workouts and 2 weeks of nothing
2. `feature_v2_resolver` failure falls through to raw LLM output (unapproved names)
3. Coach `approved=True` without `coach_locked=True` gets overwritten by regeneration
4. Hotel gym cross-contamination (one bad toggle affects all crew)
5. No transaction around `delete_many + insert_one` for workouts; partial failures corrupt state
6. `_generate_month` reads only the newest active event — a client with two events silently ignores one
7. `pain_flags` written to `users.profile.live_state` — global state; if two check-ins mutate concurrently, races possible
8. `programme_context_for_llm` recomputes `week_index` from `db.programmes` — if a programme record is missing/deleted, phase resets to Foundation
9. `_apply_days_cap_and_min_content` demotes real sessions to Recovery when it thinks it's over-capacity — no user warning
10. Recovery `phase` after event date has no dedicated shape — falls back to Foundation, likely inappropriate

## Top 20 opportunities for V2
1. First-class weekly objectives collection (long_run, tempo, key strength) — schedule around roster gaps
2. Load memory: persist prescribed AND performed loads per exercise per set; feed forward into next prescription
3. Circadian / TZ / jet-lag engine that actually modifies training decisions
4. Dedicated Multi-Goal / Race Hierarchy (A/B/C races, physique + event concurrency)
5. Deterministic injury post-filter using `exercises_v2.movement_pattern` cross-referenced with PAIN_REGION_AVOID
6. Hotel gym photo → Gemini/Claude vision → equipment write-back with confidence + coach moderation queue
7. Hotel gym equipment quantified (dumbbell max kg, plate range) with stimulus-equivalence math
8. Structured equipment variants per session (Full Gym / Hotel Gym / Dumbbell / Bodyweight) generated together for one-tap swap
9. Missed-session rescheduler that preserves weekly objectives
10. Transactional workout writes; workout version history
11. Consolidate `exercises` and `exercises_v2` into one library with clear approval status
12. Consolidate `check_ins` and `checkins` — remove the typo
13. Unify HOTEL_EQUIPMENT_KEYS vs HOTEL_EQUIPMENT_FIELDS to a single vocabulary
14. Add `last_verified_at` + confidence decay + version history to hotels
15. Per-airline label engines beyond Etihad/Emirates (BA, U2, LH, AF, etc.)
16. Progression memory that shows the LLM "you asked for 3×10 @ 30kg DB last week; client did 3×10 @ 30kg RPE 7 — bump to 32.5kg"
17. Cardio zones + optional HR data (Apple Health / Health Connect) integration
18. Explicit deload budget: track how many deloads a client has had this quarter; require justification for more
19. Structured "post-race recovery" shape (currently falls back to Foundation)
20. Test harness for prompt behaviour — snapshot expected structural properties (session count, key-session present, no heavy-lower within 48h of long-run)

---

**End of markdown master document.** For structured machine-readable subset see `CREWFIT_TRAINING_INTELLIGENCE_CURRENT_ARCHITECTURE.json`.
