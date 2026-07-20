CrewFit Programme Generation System — Full Handover Report

Date: July 2026. Direct static audit of the codebase. Nothing was newly built during this audit.


==========================================================
SECTION 1 — CURRENT VERDICT
==========================================================

- Programme generation working?      PARTIAL. Workouts are created but no periodised "programme" object.
- Does it create workouts?           YES.
- Is it roster-aware?                YES.
- Is it goal-specific?               PARTIAL. profile.main_goal is passed to the LLM but not enforced downstream.
- Is it periodised?                  NO for normal clients. PARTIAL for event-training clients (base/build/peak/taper).
- Does it progress week to week?     NO. Each roster upload = fresh LLM decision; no explicit progression.
- Does it feel like real coaching?   ALMOST. Sessions are sensible and roster-aware, but not top-down structured.
- Safe for beta (3–5 testers)?       ALMOST. Only if Emergent LLM key is topped up; template fallback covers outages.
- Safe for paid users?               NO. Missing periodisation, progression, validation-gated quality.

Why: workout generation is a per-week LLM call with strong roster context and Coaching DNA, but there is no "programme" state machine — no phase, no weekly target, no progression, no validation gate. The scaffolding module (feature_programme_quality.py) exists but is not wired into the generator.


==========================================================
SECTION 2 — PROGRAMME CREATION TRIGGERS
==========================================================

Every place that creates or updates workouts today:

After onboarding:                    NO auto-generation. Client must upload a roster.
After Coaching DNA:                  NO auto-generation. DNA is stored and later injected into workout prompts.
After roster upload:                 YES. POST /api/roster/upload-and-generate calls _generate_month inside _worker(). Overwrites unlocked workouts, preserves coach_locked and completed.
After roster retry:                  YES. POST /api/roster/jobs/{id}/retry calls the same _generate_month via _retry_worker(). Same overwrite rules.
After coach regeneration:            YES. POST /api/workouts/regenerate for a subset (dates or full roster).
After client goal change:            NO trigger. Goal change is stored on the profile but doesn't rebuild the plan until the next roster upload.
After event added/changed:           NO auto-regenerate. Event context IS picked up on the NEXT generation call.
After personal activity added:       NO. The activity is stored in personal_activities but not injected into the LLM prompt yet.
After weekly check-in:               NO. Check-in stored, not used to adjust future workouts.
After workout completion:            NO. Progression not adjusted.
After missed workouts:               NO. No regression logic.
After manual coach action:           When Louis edits a workout, only that workout changes. No cascade.

Louis reviews it? Only via the coach_alerts inbox for new-roster events + coach_tasks on failures. There is no "approve programme" gate.


==========================================================
SECTION 3 — DATA USED TO BUILD A PROGRAMME
==========================================================

- profile (up to 2 KB serialised): USED. Includes job_title, airline, home_base, aircraft, route_focus, height, weight, main_goal, experience, training_days_per_week, hotel_gyms, injury notes.
- Coaching DNA (dna_history latest, up to 2.5 KB): USED. Includes motivation_style, coaching_style, recovery_risk, training_availability, biggest_weakness, next_event.
- Active event (with phase info):    USED. From db.events where is_active=true.
- Roster days for the 7-day chunk:   USED. day_type, duty_hours, flights[], hotel_id, layover_city.
- Hotel gym info:                    USED. Attached per day via hotel_cache when day.hotel_id is set.
- Layover city / country:            USED as part of hotel context.
- Standby days:                      USED via day_type.
- Days off / annual leave / sick:    USED via day_type.
- Sleep / recovery data:             NOT USED as structured input (Coaching DNA recovery_risk is the closest proxy).
- Nutrition data:                    NOT USED.
- Habits:                            NOT USED for programme generation.
- Weekly check-ins:                  NOT USED for programme generation.
- Previous workout logs / RPE:       NOT USED.
- Missed sessions:                   NOT USED.
- Personal activities / sports:      NOT USED (backend collection exists, not injected into prompt).
- Medical / health goals:            PARTIAL. Only via profile.main_goal free-text if the client entered it there. Event category "medical" exists but doesn't feed the workout LLM prompt directly.
- Coach notes / coach locks:         RESPECTED. Coach-locked or completed workouts are skipped on regenerate.
- Client preferences (equipment):    USED via profile.hotel_gyms + roster hotel data + Coaching DNA.


==========================================================
SECTION 4 — PROGRAMME STRUCTURE
==========================================================

Actually stored today:
- programme goal:               NOT STORED (only profile.main_goal free-text).
- programme phase:               PARTIAL. Only event_phase per workout when an event is active.
- start_date / end_date:         Roster has start/end dates. No programme entity has them.
- week_number:                   NOT STORED.
- training_block:                NOT STORED.
- weekly_target_sessions:        NOT STORED.
- session_types (planned mix):   NOT STORED as a plan; each workout has a focus string.
- progression_model:             NOT STORED.
- deload_week:                   NOT STORED.
- recovery_week:                 NOT STORED.
- movement_balance:              NOT VALIDATED. Only informally implied by the LLM.
- programme_version:             NOT STORED.
- coach_approval_status:         Only per-workout (workout.approved), not per programme.

Only scaffolded (module exists, NOT wired):
- feature_programme_quality.py — has GOAL_MATRIX (fat_loss / build_muscle / general_fitness / health_markers / event / aviation_consistency / improve_energy / return_to_training), PHASES (foundation / build / peak / deload), programme_context_for_llm(), validate_programme(), persist_programme_record(). GET /api/programme/current and GET /api/coach/clients/{id}/programme endpoints exist. But _generate_month never calls it, so db.programmes is empty in practice.


==========================================================
SECTION 5 — PERIODISATION
==========================================================

Foundation / Build / Peak / Deload for normal clients: NOT IMPLEMENTED in the live path.
Base / Build / Peak / Taper / Race Week / Recovery for event clients: IMPLEMENTED via _event_phase(event.event_date) at server.py; passed to _generate_month via event_context.phase and read by the LLM inside WORKOUT_SYSTEM prompt.
Strength / Conditioning phases: NOT IMPLEMENTED as separate phases.
Maintenance phase: NOT IMPLEMENTED.

Where periodisation lives today:
- Event-based only (based on days_to_race from event date).
- Every non-event client gets a single "generic" plan with no phase tracking.

Does it progress week to week? NO. There is no memory of "last week's volume" because we don't persist a programme row.
Does it know when to deload? NO for normal clients. Event clients get taper via prompt instruction.
Does it adapt around roster changes? Yes at the SESSION level (LLM sees the roster) but not at the PROGRAMME level.
Does it survive roster changes? Roster upload wipes and regenerates unlocked workouts.
Does it avoid random rebuilding? Not really — every roster upload calls _generate_month afresh.

What needs to be built:
1. Wire feature_programme_quality into _generate_month so a phase key + week_index + weekly target are injected into the prompt.
2. Persist a programmes row per generation so the next generation can look up "last week phase / volume" and progress.
3. Include a deload rule (every 4th week reduce sets by 1 and RPE cap by 1).


==========================================================
SECTION 6 — GOAL-SPECIFIC LOGIC
==========================================================

Today the LLM receives profile.main_goal as free-text and Coaching DNA. There is NO deterministic goal → structure mapping in the code path.

- fat_loss:              Currently the LLM decides. No enforced 3–4 session target. No enforced conditioning bias.
- build_strength / muscle: LLM decides. No enforced progressive overload. Coaching DNA may hint at it.
- general_fitness:       LLM decides. Balanced by default because that's the WORKOUT_SYSTEM prompt intent.
- improve_energy:        LLM decides.
- improve_health_markers: LLM decides. Event category "medical" exists but does NOT feed the workout prompt with a health-specific instruction.
- improve_cardio:        LLM decides.
- improve_mobility:      LLM decides.
- return_to_training:    LLM decides. No ramp-in rule enforced.
- event_training:        Structured phases via event_context. This is the ONE goal-type where periodisation exists.
- aviation_consistency:  LLM decides with roster context.
- body_confidence:       Not a distinct goal; folded into fat_loss or general_fitness.
- injury-aware:          Only the free-text injury note passed through. No hard-coded avoid rules.

Honest summary: only event training truly changes behaviour. Everything else is "sensible LLM defaults" in a single mode.


==========================================================
SECTION 7 — ROSTER-AWARE PROGRAMMING
==========================================================

Signals used by the LLM (per WORKOUT_SYSTEM prompt at server.py:3970 area):

- Early starts / late finishes:  LLM sees report_time / off_duty_time in the chunk.
- Night flights:                 Detected; setup-day gate skips them for first workout. LLM told not to schedule hard sessions after night flights.
- Long haul:                     LLM told to add recovery. Setup-day gate no longer treats it as heavy (bug fix).
- Ultra long haul:               Treated same as long haul.
- Multi-sector days:             LLM sees flights[] array.
- Standby:                       Prompt says amber, short session.
- Layovers:                      LLM sees layover_city + hotel data; picks hotel/bodyweight workouts.
- Hotel gym access:              Yes — hotel.equipment[] is injected per day.
- Days off:                      LLM told to use for main strength progression.
- Annual leave / sick:           LLM told full training allowed / rest.
- Simulator / training days:     Amber activation only per prompt rule.
- Flight recovery days:          Handled by the LLM plus the template fallback.
- Heavy duty blocks:             LLM sees the pattern in the 7-day chunk and generally lightens; not deterministically enforced.

Enforced deterministically (not just LLM prompt):
- Setup-day gate (first workout goes to tomorrow, max +2 days).
- Template fallback classification for LLM outage (flight_heavy vs flight_light vs layover vs standby vs home).

Not deterministically enforced:
- "No hard leg session before a long duty" — left to LLM.
- "Reduce intensity after 3 consecutive long-haul days" — left to LLM.


==========================================================
SECTION 8 — FIRST WORKOUT RULE
==========================================================

Implemented in /app/backend/feature_setup_day.py.

- Signup day = setup day (dropped from the plan).
- First workout falls on tomorrow (client local date).
- If tomorrow is a heavy day (night flight / overnight / red-eye / duty ≥14 h), gate advances by 1 day. Cap at +2 days.
- Timezone: client current_time_zone from profile, fallback home_time_zone, fallback Europe/London. Not UTC.
- Louis override: POST /api/coach/clients/{id}/programme/start-today sets setup_day_override=true. Reverse: /programme/clear-override.
- Previous empty-week bugs: caused by threshold set at duty_hours >= 10 AND +7 day advance. Both fixed.


==========================================================
SECTION 9 — WORKOUT SELECTION LOGIC
==========================================================

Two paths:

Path A (LLM path): _generate_month → Claude Sonnet 4.5 chooses per date the workout title, focus, location, duration, warmup, exercises, alternatives, rationale, key_session, event_phase. Guided by WORKOUT_SYSTEM system prompt and the injected client + DNA + event + 7-day roster context. No template lookup — Claude authors the exercises directly.

Path B (Template fallback): feature_workout_fallback.build_template_plan → hardcoded templates based on day classification.

For each workout today:
- title:           Path A: LLM invents (e.g. "Home Push + Core"). Path B: fixed titles per day type.
- workout_type:    Path A: focus string chosen by LLM. Path B: preset per day type.
- duration:        Path A: LLM. Path B: preset.
- exercises:       Path A: LLM invents with sets/reps/rest/RPE/notes. Path B: five hand-authored exercises per template.
- sets/reps/rest/RPE: Path A: LLM. Path B: preset.
- warm-up:         Path A: LLM. Path B: 4 preset moves.
- alternatives:    Path A: LLM. Path B: preset.
- traffic light version: Not a separate output — day_load field is set (green/amber/red) but exercises are not split into 3 variants.
- location:        LLM or template picks Home / Hotel / Bodyweight / Outdoor based on roster + hotel data.
- rationale:       Path A: LLM writes 2–3 sentences. Path B: preset per template.

NOT selected from a curated pool. The V2 Exercise Library is NOT queried by the workout generator. Exercise names in workouts.exercises[] are strings — matched to the Exercise Library later only for media rendering.


==========================================================
SECTION 10 — EXERCISE SELECTION
==========================================================

- Does it use the V2 Exercise Library at generation time?  NO. The LLM invents exercise names. V2 is used later to resolve media / demos when the workout is displayed.
- Prefer approved / live exercises?                         NO.
- Avoid missing media?                                      NO — mismatches trigger a JIT media generation task after the fact.
- Respect equipment?                                        YES via prompt (hotel/home/bodyweight).
- Respect injury notes?                                     PARTIAL — passed in profile free-text; no hard rule.
- Balance push/pull/hinge/squat/lunge/core/mobility?        NOT VALIDATED. Left to LLM.
- Avoid repeating the same exercises?                       NOT ENFORCED.
- Choose alternatives?                                      YES — LLM outputs alternatives{home,hotel,no_equipment,easier,harder}.
- Coach tasks for unapproved / missing-media exercises?     YES — feature_exercise_content raises Just-In-Time coach tasks when a workout references an exercise without primary media.

The core weakness: the workout generator and the Exercise Library are not integrated. If the goal is "coach-approved everywhere", every generation should first pick from approved exercises_v2 rows.


==========================================================
SECTION 11 — TRAFFIC LIGHT SYSTEM
==========================================================

- Are Green / Amber / Red separate workouts?    NO. Each date has ONE workout with a day_load enum (green | amber | red | blue | purple | grey).
- Are they variations of the same workout?      Partially — the alternatives field has easier/harder/home/hotel variants but not a full G/A/R triple.
- Do all sessions have three variants?          NO.
- How does the client choose?                    Currently they see one workout with alternatives text; no toggle UI for green/amber/red.
- How does roster/recovery affect the default?   day_load is set by the LLM based on the day's roster context.
- Does it preserve programme intent?             Yes at the day level; not at the weekly programme level.


==========================================================
SECTION 12 — PROGRESSION LOGIC
==========================================================

Nothing enforced. Details:

- Load progression:                Not tracked.
- Rep progression:                 Not tracked.
- Set progression:                 Not tracked.
- Difficulty progression:          Not tracked.
- Session density:                 Not tracked.
- Conditioning progression:        Not tracked.
- Mobility progression:            Not tracked.
- Deloading (auto every 4 weeks):  Not implemented.
- Progression after completions:   Not implemented.
- Regression after missed sessions: Not implemented.
- Adaptation after poor check-in:  Not implemented.
- Progression based on RPE:        Not implemented.

Scaffolded (not wired): feature_programme_quality has phase logic that could drive progression across weeks if it were called from the generator and the phase were persisted to db.programmes.


==========================================================
SECTION 13 — PROGRAMME VALIDATION
==========================================================

- At least one workout in next 7 days:            PARTIAL — the roster worker checks count > 0 and opens a coach task if zero.
- Not all rest/recovery:                          NOT CHECKED.
- Sessions match client goal:                     NOT CHECKED.
- First workout not on signup day:                CHECKED (setup-day gate).
- Exercises not empty:                            PARTIAL — soft check in the retry safety net.
- Exercises match equipment:                      NOT CHECKED after generation.
- Injuries respected:                             NOT CHECKED.
- Roster-heavy days not overloaded:               NOT CHECKED.
- Movement patterns balanced:                     NOT CHECKED.
- Weekly volume realistic:                        NOT CHECKED.
- Progression phase exists:                       NOT CHECKED.
- Rationale exists:                               NOT CHECKED, but LLM prompt requires it.
- No client-facing AI wording:                    Handled via the earlier sweep (frontend copy already updated).
- Fallback template marked for coach review:      YES for the main worker. NO for the retry worker (2-line bug — retry-worker doc dict missing source='template' and needs_coach_review=true).

feature_programme_quality.validate_programme() implements 6 of these checks. NOT called by production code today.


==========================================================
SECTION 14 — FALLBACK PROGRAMME SYSTEM
==========================================================

Module: /app/backend/feature_workout_fallback.py

- When does it run?          When _generate_month returns [] or all-empty workouts (LLM budget / timeout / provider error).
- What triggers it?          feature_workout_fallback.is_empty_or_llm_failure(workouts) returns True inside the roster worker (or retry worker).
- Templates created:
    home / off-duty     → 45-min Full Body Strength (5 dumbbell exercises, warmup + rationale)
    layover / hotel     → 30-min Hotel / Bodyweight Session (5 exercises)
    flight heavy (night/overnight/long-haul/red-eye) → 15-min Flight Recovery Mobility (5 items)
    flight light        → 12-min Pre/Post-Flight Mobility
    standby / reserve   → 20-min Standby Activation
    simulator / training → 20-min Light Activation
    rest / off / annual_leave → NO workout (day intentionally rest)
- Number of workouts per week: 2–5 depending on roster composition.
- Uses goals?               PARTIAL — only via profile.hotel_gyms preference (bodyweight vs hotel vs home) for home-day template picking.
- Uses roster?              YES — every day is classified by day_type.
- Uses equipment?           PARTIAL — bodyweight vs hotel vs home only.
- source="template"?        YES on main worker path. NO on retry-worker path (known 2-line bug).
- needs_coach_review=true?  YES on main worker. NO on retry-worker.
- Coach task created?       YES via _open_coach_task_for_stuck_generation with reason="template fallback used".
- Client status:            Job.completion_message = "Starter plan ready — Louis will refine your sessions soon."
- Job flag:                  job.used_template = true.

Limitations:
- Templates are generic — no differentiation by main_goal (fat loss vs strength both get "Full Body Strength").
- No progression between weeks.
- Only 5 exercises per session.
- Not tied to V2 Exercise Library.


==========================================================
SECTION 15 — PROGRAMME VERSIONING
==========================================================

- programmes collection:     SCAFFOLDED in feature_programme_quality. NOT written by _generate_month today. db.programmes is empty in production.
- programme_id:              Field exists in scaffolded schema but not linked to workouts.
- version_number:            Scaffolded, never incremented.
- previous versions:         Not preserved.
- current active programme:  Cannot be queried today (no rows).
- changed_by:                Not tracked.
- created_at / updated_at:   Fields exist in scaffold.
- roster_id link:            Field exists in scaffold; workouts.roster_id links to roster (works today).
- goal link:                 Would live in programmes.goal_key. Not written.
- coach_approved:            Field exists in scaffold; only per-workout .approved is used today.
- validation_status:         Field exists in scaffold.
- reason for change:         Not tracked.

Workouts today are linked to a roster_id but NOT to a programme_id. This is the biggest structural gap.


==========================================================
SECTION 16 — ADAPTATION AFTER CHANGES
==========================================================

- New roster uploaded:       Full _generate_month runs. Unlocked workouts overwritten. Locked/completed preserved.
- Roster edited:             Not automatically regenerated. Coach or client must trigger regenerate.
- Workout missed:            No effect on future workouts.
- Workout completed:         Progress logged; no forward adjustment.
- Client reports fatigue:    No hook.
- Client reports injury/pain: No hook — must be manually added to profile.
- Weekly check-in:           Data captured, not used for programme adjustment.
- Personal activity added:   Suggestion engine runs, coach task may open. Programme itself does not adapt.
- Goal changed:              Stored on profile. Next generation picks it up. Existing plan is not rewritten.
- Event added:               Same as goal change. Next generation includes event_context.
- Coach locks a workout:     Respected — that date will not be overwritten on regenerate.
- Louis edits manually:      Respected as an isolated change; no cascade.

Duplicates: prevented by delete_many({user_id, date}) before insert — the unique (user_id, date) index sweep.
Preserved on regen: coach_locked=true and completed=true rows.


==========================================================
SECTION 17 — CLIENT EXPERIENCE
==========================================================

- Today screen:              Shows today's workout, roster context, today's personal activity, setup day card if applicable, plan banners.
- Next 7 Days:                7 rows from today, category-aware wording ("Today", "Tomorrow", "Wed 1 Jul"), rest day / flight recovery padding.
- Workout detail:             Title, warm-up, exercises with sets/reps/rest/RPE, alternatives, images from V2 library where available.
- Guided Flow:                Per-exercise timer + progression through the workout.
- Manual mode:                Traditional list view with tick-off.
- Calendar:                   Month view of roster days + workouts + activities + overrides.
- Setup day:                  Clear card ("Your CrewFit Setup Day", first workout tomorrow message, upload roster + message Louis buttons).
- Plan preparing banner:      Red banner during processing.
- Plan needs review banner:   Amber banner post-timeout, with OPEN ROSTER UPLOAD link.
- Starter plan / coach review state: Not surfaced explicitly to client. They just see the plan and the completion message.
- Why this session?           Data exists on workout.rationale. NOT surfaced on the workout screen UI.
- Traffic light options:      Not selectable. Only alternatives text.
- Recovery / rest days:       Rendered as distinct rows in Next 7 Days.

Client CANNOT clearly see: their weekly focus, current phase, or a summary of what the coming month looks like.


==========================================================
SECTION 18 — COACH EXPERIENCE
==========================================================

- Client programme overview:      PARTIAL. Coach client detail shows workouts + coach tasks + messages.
- Current phase:                  NOT SHOWN.
- Goal:                           Shown as profile.main_goal free-text.
- Roster summary:                 YES — day count, next 7 days.
- Workouts generated:             YES — visible in the client's calendar.
- First workout date:             YES.
- Rationale (per workout):        Field exists; coach dashboard displays it inside the workout detail modal.
- Plan quality score:             NOT SHOWN.
- Validation errors:              NOT SHOWN.
- Needs coach review flag:        Backend field workout.needs_coach_review exists; no coach filter uses it yet.
- Fallback / template flag:       Backend workout.source exists; no coach filter uses it yet.
- Regenerate plan button:         NOT WIRED (backend endpoint exists).
- Manual edit options:            YES — coach can PATCH any workout.
- Coach locks:                    YES via PATCH /workouts/{wid} with coach_locked=true.
- Programme history:              NOT AVAILABLE (no programmes rows).
- Messages:                       YES.
- Coach tasks:                    YES — coach_tasks with roster_plan_generation_issue type surfaced in inbox.


==========================================================
SECTION 19 — DATABASE COLLECTIONS
==========================================================

users
- Purpose: profile + auth.
- Key fields: id, role, email, profile{main_goal, experience, hotel_gyms, injury_notes, height, weight, ...}, current_time_zone, first_workout_date, setup_day_override.
- Live.

rosters
- Purpose: parsed rosters with embedded days.
- Key fields: id, user_id, is_active, start_date, end_date, days[].
- Live.

roster_jobs
- Purpose: async job tracking for uploads.
- Key fields: id, user_id, roster_id, status, stage, progress, message, error, workouts_generated, used_template, retry_count, client_acknowledged.
- Live.

workouts
- Purpose: per-day sessions.
- Key fields: id, user_id, roster_id, date, day_load, title, location, focus, warmup[], exercises[], alternatives{}, rationale, key_session, source, needs_coach_review, coach_locked, approved, completed.
- Links: user_id -> users.id. roster_id -> rosters.id. NOT linked to programmes.
- Indexes: unique(user_id, date). user_id + date.
- Live.

programmes
- Purpose: programme versioning (intended).
- Key fields: id, user_id, roster_id, goal_key, phase{key,label,note}, week_index, target_sessions_per_week, session_style, movement_mix_hint, start_date, end_date, roster_context_summary, validation_status, validation_errors, coach_approved, version_number.
- SCAFFOLDED. Not written by the generator. Empty in practice.

dna_history
- Purpose: snapshots of Coaching DNA over time.
- Key fields: id, user_id, snapshot{}, created_at.
- Live.

check_ins / checkins
- Purpose: weekly check-in submissions.
- Key fields: id, user_id, date, energy, sleep, soreness, notes.
- Live but not fed into generation.

habits
- Purpose: habit tracker.
- Live, not used by generation.

personal_activities
- Purpose: client sports/hobbies.
- Live, atlas_suggestion computed, not fed into workout generation.

coach_tasks
- Purpose: coach follow-ups.
- Live.

day_overrides
- Purpose: per-day client overrides.
- Live.

exercises_v2
- Purpose: V2 Unified Exercise Library.
- Live but not queried at workout generation time.

workout_logs
- Purpose: per-set logs during workout completion.
- Live.

events
- Purpose: goal events (race/medical/aviation_work/sport_hobby/personal).
- Live, category-aware, fed into event_context.


==========================================================
SECTION 20 — API ENDPOINTS
==========================================================

POST  /api/roster/upload-and-generate       — Parse + save + kick off _generate_month. Called by roster-upload.tsx.
POST  /api/roster/jobs/{job_id}/retry       — Re-run _generate_month against saved roster.
POST  /api/roster/jobs/{job_id}/acknowledge — Dismiss banner.
GET   /api/roster/jobs/active               — Any current banner-worthy job. Home banners.
GET   /api/roster/jobs/{job_id}             — Poll status. roster-upload.tsx.
POST  /api/workouts/generate-month          — Legacy generation path (still functional).
POST  /api/workouts/regenerate              — Regenerate a subset of dates. Coach dashboard.
GET   /api/workouts/week                    — Feed for home.tsx NEXT 7 DAYS.
GET   /api/workouts/{wid}                   — Full workout detail.
PATCH /api/workouts/{wid}                   — Edit / approve / lock. Coach or client.
POST  /api/workouts/{wid}/swap-exercise     — Swap a single exercise.
POST  /api/workouts/{wid}/complete          — Mark done. Records to workout_logs.
PATCH /api/workouts/{wid}/player            — Guided player state.
GET   /api/calendar/timeline                — Merged calendar.
POST  /api/calendar/day-override            — Per-day override.
GET   /api/setup-day/status                 — Is today setup day?
POST  /api/coach/clients/{id}/programme/start-today  — Override the setup gate.
POST  /api/coach/clients/{id}/programme/clear-override — Reverse.
GET   /api/programme/current                — Client's most recent programme row (empty today).
GET   /api/coach/clients/{id}/programme     — Coach view of a client's programme (empty today).
GET   /api/coach/clients/{id}/programme/history — Programme history (empty today).

All require Bearer JWT. Coach endpoints require role=coach.


==========================================================
SECTION 21 — FRONTEND FILES
==========================================================

/app/frontend/app/(client)/home.tsx         — Today, banners, NEXT 7 DAYS, setup day card, personal activities.
/app/frontend/app/(client)/calendar.tsx     — Month view + activity dots + FABs.
/app/frontend/app/(client)/messages.tsx     — Chat with Louis.
/app/frontend/app/(client)/profile.tsx     — Coaching Headquarters, sections editable.
/app/frontend/app/workout/[id]/index.tsx    — Workout detail (title, warmup, exercises, alternatives).
/app/frontend/app/workout/[id]/guided.tsx   — Guided flow (per-exercise timer).
/app/frontend/app/workout/[id]/timer.tsx    — Rest/set timer.
/app/frontend/app/workout/[id]/play.tsx     — Play mode with WorkoutMediaCarousel.
/app/frontend/app/roster-upload.tsx         — Upload + progress + retry + slow/stuck banners.
/app/frontend/app/onboarding.tsx            — First-run flow.
/app/frontend/app/coaching-dna.tsx          — DNA assessment.
/app/frontend/app/assessment.tsx            — Initial assessment (now icon-based, no emojis).
/app/frontend/app/event.tsx                 — Event training (category-aware).
/app/frontend/app/(coach)/overview.tsx      — Louis' dashboard.
/app/frontend/app/(coach)/clients.tsx       — Client list.
/app/frontend/app/coach/client/[id].tsx     — Client detail with workouts, roster, messages.
/app/frontend/app/(coach)/library.tsx       — V2 Unified Exercise Library.
/app/frontend/app/coach/exercise-content.tsx — V2 library implementation.

No dedicated programme review UI on client or coach today.


==========================================================
SECTION 22 — BACKEND FILES
==========================================================

/app/backend/server.py                        — Main FastAPI app. Contains _generate_month, WORKOUT_SYSTEM prompt, roster workers, workouts APIs, calendar APIs.
/app/backend/feature_setup_day.py             — First-workout-tomorrow gate + coach override endpoints.
/app/backend/feature_workout_fallback.py      — Deterministic template plan when LLM unavailable.
/app/backend/feature_programme_quality.py     — SCAFFOLDED goal → phase → weekly target → validation. NOT wired.
/app/backend/feature_event_categories.py      — Category-aware events.
/app/backend/feature_personal_activities.py   — Sports/hobbies + Atlas suggestions.
/app/backend/feature_exercise_content.py      — V2 exercise library + JIT media.
/app/backend/feature_habits.py                — Habits + streaks.
/app/backend/feature_coach_v1.py              — Coach dashboard endpoints.
/app/backend/feature_notifications.py         — Coach push notifications.


==========================================================
SECTION 23 — KNOWN BUGS AND GAPS
==========================================================

# 1  Programme quality module not wired
- Severity: HIGH
- Beta impact: Plan feels session-by-session, not periodised.
- Paid impact: Blocking.
- Cause: Deferred wiring.
- Fix: 1–2 days.
- Action: Inject programme_context_for_llm into _generate_month; persist programmes row per generation.

# 2  No top-down periodisation for non-event clients
- Severity: HIGH
- Beta impact: Sessions don't progress.
- Paid impact: Blocking.
- Cause: Not built.
- Fix: 1 day (after #1).
- Action: Enforce 4-week phase cycle in prompt + validation.

# 3  No weekly session target enforced
- Severity: MEDIUM
- Beta impact: LLM may over- or under-schedule.
- Paid impact: High.
- Cause: Not injected.
- Fix: 2 hours.
- Action: Pass target_sessions_per_week into prompt and validate output.

# 4  No progression week to week
- Severity: MEDIUM
- Beta impact: No sense of improvement.
- Paid impact: Blocking.
- Cause: No persisted history.
- Fix: 0.5 day.
- Action: Read last programme row, bump sets/reps per phase rule.

# 5  No movement balance validation
- Severity: MEDIUM
- Beta impact: Occasional imbalance week.
- Paid impact: Medium.
- Cause: Not called.
- Fix: 1 hour.
- Action: Call validate_programme after generation, log to programme row.

# 6  Fallback template too generic
- Severity: MEDIUM
- Beta impact: Same template regardless of goal.
- Paid impact: Medium.
- Cause: Simplicity-first design.
- Fix: 0.5 day.
- Action: Add goal-branched templates (fat_loss / strength / general / mobility).

# 7  Why this session not visible on client
- Severity: MEDIUM
- Beta impact: Coaching intent hidden.
- Paid impact: Medium.
- Cause: Frontend gap.
- Fix: 30 min.
- Action: Render workout.rationale on workout detail.

# 8  No programme rationale in coach dashboard
- Severity: MEDIUM
- Beta impact: Louis has no summary view.
- Paid impact: Blocking.
- Cause: Not built.
- Fix: 0.5 day.
- Action: Coach client detail programme card.

# 9  No client parsed-roster review before generation
- Severity: MEDIUM
- Beta impact: Occasional mis-parses become workouts.
- Paid impact: High.
- Fix: 0.5 day.

# 10 No coach manual programme builder
- Severity: LOW for beta / MEDIUM for paid.
- Fix: 1–2 days.

# 11 No coach day-edit UI
- Severity: LOW for beta / MEDIUM for paid.
- Fix: 0.5 day.

# 12 LLM / generation budget management
- Severity: HIGH.
- Fix: 5 min (top up + auto top-up).

# 13 Retry-worker missing source='template' + needs_coach_review flags
- Severity: HIGH for coach visibility.
- Fix: 2 min.

# 14 Regeneration duplicates prevented by index; edge cases with multi-roster overlaps historically caused issues (fixed).

# 15 Too many recovery days on long-haul rosters
- Severity: MEDIUM (was HIGH before setup-day gate fix).
- Fix: Applied — now caps at +2 days.

# 16 Not enough workouts generated when LLM budget hit
- Severity: HIGH — covered by template fallback.

# 17 V2 Exercise Library approval not enforced at generation time
- Severity: MEDIUM.
- Fix: 1 day.
- Action: Constrain LLM to a pre-approved exercise pool per generation.

# 18 Missing exercise media
- Severity: LOW (handled by JIT tasks).


==========================================================
SECTION 24 — EXAMPLES
==========================================================

Example 1 — Cabin crew, short-haul, fat loss, hotel gym access, 3 sessions/week
- TARGET: Mon full-body strength, Wed hotel bodyweight session, Fri full-body strength + short conditioning; Tue/Thu mobility around duties; weekend rest.
- CURRENT SYSTEM: The LLM generally produces this shape when the roster is favourable. No enforced 3/week target and no explicit fat-loss branch. Sometimes lands 2 or 4 sessions.
- Verdict: PARTIAL match today; needs Section 25 A improvements to be reliable.

Example 2 — Long-haul pilot, strength goal, inconsistent sleep, 2–3 sessions/week
- TARGET: Two heavy strength days on home windows (squat/hinge focus one day, push/pull one day). Recovery mobility after each long-haul block.
- CURRENT SYSTEM: LLM produces strength sessions when the roster permits, but does not enforce progressive overload week to week and does not distribute movement patterns systematically.
- Verdict: PARTIAL.

Example 3 — Mixed roster cabin crew, general fitness, bodyweight/hotel gym, beginner
- TARGET: 3 short balanced sessions per week (2 strength + 1 conditioning), mobility on layovers, rest on heavy duties.
- CURRENT SYSTEM: Best supported scenario. LLM output is usually reasonable. Template fallback also fits.
- Verdict: MOSTLY YES.

Example 4 — Pilot training for half marathon, 12 weeks away, mixed roster
- TARGET: Base phase now, build phase weeks 4–8, taper last 2 weeks. One key long run per week, one interval/tempo, one strength, plus mobility.
- CURRENT SYSTEM: Event context works — this is the one scenario where phase logic is implemented. LLM prompt has explicit event-training rules.
- Verdict: YES for phase structure; but progression week-to-week (weekly km / interval density) not tracked.

Example 5 — Aviation medical / blood pressure review goal
- TARGET: Moderate strength + walking + mobility, no extreme intensity, safety wording, coach review.
- CURRENT SYSTEM: Event category "medical" carries the disclaimer on the client side. Workout generation does NOT branch on this — the LLM still receives only profile.main_goal. Medical safety is thin at the plan level.
- Verdict: PARTIAL. Needs a medical-branch in feature_programme_quality.GOAL_MATRIX and a prompt fragment injected from it.


==========================================================
SECTION 25 — WHAT NEEDS IMPROVING
==========================================================

A. Must improve before wider beta

A1  Wire feature_programme_quality.programme_context_for_llm into _generate_month
    - Why: injects goal, weekly target, phase, movement mix into every generation.
    - Time: 4 hours.
    - Risk if skipped: plan remains one-mode LLM output.

A2  Persist a programmes row per generation and use it to progress week to week
    - Why: gives the next generation memory (last phase, last week volume).
    - Time: 4 hours.
    - Risk if skipped: no true progression.

A3  Call feature_programme_quality.validate_programme after generation; open coach task if not ok
    - Why: catches empty / imbalanced / random plans before the client sees them.
    - Time: 1 hour.
    - Risk if skipped: silent bad plans reach beta testers.

A4  Surface workout.rationale on the client workout screen ("Why this session?")
    - Why: makes coaching intent visible to the client.
    - Time: 30 min.

A5  Patch retry-worker to add source='template' + needs_coach_review=true
    - Why: coach dashboard visibility on retried fallback plans.
    - Time: 2 min.

A6  Ensure Emergent Universal Key balance is topped up + auto-top-up enabled
    - Why: without this, only the deterministic fallback runs.
    - Time: 5 min.

A7  Add goal-branched templates in feature_workout_fallback (fat_loss / strength / general / mobility)
    - Why: even the fallback should differ by goal.
    - Time: 4 hours.


B. Must improve before paid users

B1  Constrain the workout generator to the approved V2 Exercise Library
    - Why: coach-approved everywhere.
    - Time: 1 day.

B2  Coach programme summary card on the client detail page (goal, phase, week, target sessions, validation status)
    - Why: Louis needs a top-level view.
    - Time: 0.5 day.

B3  Coach "Regenerate plan" button on client detail
    - Why: Louis triggers retry without asking client.
    - Time: 20 min.

B4  Coach day-override edit UI
    - Why: Louis fixes parse errors himself.
    - Time: 0.5 day.

B5  Client parsed-roster review step before generation
    - Why: prevents mis-parses becoming workouts.
    - Time: 0.5 day.

B6  Traffic Light workout variants (green / amber / red) as first-class outputs
    - Why: matches product intent; roster-adaptive.
    - Time: 1 day.

B7  Weekly check-in feeds into next-week generation (energy, sleep, soreness)
    - Why: adaptation to how the client actually feels.
    - Time: 1 day.

B8  Personal activities injected into workout prompt
    - Why: avoid clashes with tennis / football etc.
    - Time: 3 hours.


C. Can improve later

C1  Client programme "This month at a glance" screen — phase, weekly focus, progression preview.
C2  Coach programme history view (versioning UI).
C3  RPE-driven auto-progression.
C4  Injury-aware exercise exclusions at generation time (hard rules, not just prompt hint).
C5  Multi-language parser and prompt.
C6  Nutrition data feeding workout intensity choice.
C7  Cross-programme analytics for Louis (which templates land best).


==========================================================
SECTION 26 — FINAL VERDICT
==========================================================

1. Good enough for 3–5 beta testers?          ALMOST. Yes only with the safety net; usable but plans lack periodisation.
2. Good enough for 20–50 beta testers?        NO. Louis can't visibly see programme state; too much manual review.
3. Good enough for paying clients?            NO. Needs wiring of programme_quality + progression + validation.
4. Creates proper periodised programmes?      NO for normal clients. YES for event clients only.
5. Adapts properly around rosters?            YES at the session level. NO at the programme level.
6. Avoids random workouts?                    ALMOST — LLM guided by prompt, but no enforced structure.
7. Louis has enough control?                  ALMOST — locks and edits work, but no top-down programme UI or one-click regenerate.

Top 5 fixes:
1. Wire feature_programme_quality into _generate_month (A1 + A2).
2. Call validate_programme after generation (A3).
3. Surface "Why this session?" on client workout screen (A4).
4. Coach programme summary card + Regenerate button (B2 + B3).
5. Constrain generation to approved V2 exercises (B1).


End of report. This is a factual audit. Nothing here was newly built.
