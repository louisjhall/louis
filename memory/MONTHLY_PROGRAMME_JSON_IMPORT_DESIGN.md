# Monthly Programme JSON Import — Design Document

> Scope: Design-only. No code changes. Purpose is to review the schema,
> workflow, and phased build plan before authorisation.

## 1. Goals & Constraints

**Primary goal:** Louis pastes/uploads a JSON file (produced by ChatGPT or
hand-written) representing a full month of workouts for a client. The
system parses it, matches every exercise against the V2 library, previews
the outcome, and — on his approval — writes real manual workouts to
`db.workouts` using the exact same pipeline as the manual builder.

**Non-negotiable constraints (grounded in the current codebase):**

1. Manual mode stays king. Everything the importer writes MUST have
   `source="coach_manual"`, `manual_lock=True`, `coach_locked=True` (same
   markers `feature_coach_manual_workouts.py` uses). No auto-gen path is
   revived.
2. One workout per (client, date). The existing unique index on
   `db.workouts (user_id, date)` is the source of truth. Overlaps must be
   surfaced BEFORE writes.
3. Exercise identity comes from `db.exercises_v2.id`. Any exercise the
   coach references by name only must be matched via the existing
   `feature_v2_resolver._score_candidate` / `resolve_exercise_need` path
   (already used for LLM-side matching) so we get one unified matcher
   across the app.
4. Media queue is shared. Any unmatched or media-less exercise is queued
   via `feature_media_queue.scan_media_queue_for_sections` — never a
   parallel implementation.
5. R2 media, budget, and LLM key stay untouched. No image generation is
   triggered during import; auto-media-gen fires later per its existing
   toggles (`feature_auto_media_gen.py`).
6. Deterministic — no LLM inside the import path. ChatGPT builds the
   JSON off-platform; the platform only validates and applies it.

---

## 2. Proposed JSON Schema

Everything is documented as JSON Schema draft-2020-12 at a conceptual
level. The **month-programme envelope** wraps zero-to-many workouts and
optional roster context. The **workout object** is intentionally a
superset of the manual builder shape so we can reuse `_norm_exercise` /
`_normalise_sections` verbatim.

### 2.1 Envelope

```jsonc
{
  "$schema": "crewfit://programme-import/v1",   // sentinel — required
  "meta": {
    "client_email": "pietro@example.com",        // OR "client_id"
    "client_id": null,                            // uuid — either/or
    "month": "2026-07",                           // ISO YYYY-MM
    "timezone": "Europe/London",                  // client-side default
    "generated_by": "chatgpt-2026-06",            // free text for audit
    "source_prompt_hash": "sha256:abc...",        // optional, for audit
    "author_notes": "Cutting block · week 3-4 volume dip"
  },
  "roster_hints": {                               // optional
    "airline": "BA",                              // maps to adapters
    "raw_month_calendar": null                    // pass-through blob
  },
  "workouts": [ /* WorkoutObject[] — see 2.2 */ ],
  "override_policy": "replace_conflicts"          // see §3.3
}
```

* `$schema` is a magic string. Importer refuses anything else.
* `client_email` OR `client_id` — one required. Email lookup uses
  `db.users.find_one({"email": ...})` (case-insensitive) so Louis can
  paste with either.
* `month` gives us the calendar boundary so the preview UI can highlight
  which days are in/out of scope.
* `override_policy` values: `"reject_conflicts"` (safest — refuses if any
  target date already has a workout), `"replace_conflicts"` (deletes
  non-manual rows only, refuses to overwrite manual), or
  `"skip_conflicts"` (leaves existing day alone, imports the rest).
  Default: `"reject_conflicts"`.

### 2.2 WorkoutObject

```jsonc
{
  "date": "2026-07-14",                    // ISO
  "title": "Push · Strength",              // free text, ≤80 chars
  "workout_type": "strength",              // enum, see §2.5
  "duration_min": 55,                       // optional
  "location": "hotel_gym",                 // free text, matches existing
  "equipment_context": "dumbbells + bench",// free text, informational
  "rpe": 7.5,                               // optional
  "coach_notes": "Focus horizontal press. Keep RIR ≥1.",

  "warmup":   [ /* ExerciseItem[]  (§2.3) */ ],
  "exercises":[ /* ExerciseBlock[] (§2.4) */ ],   // main work
  "cooldown": [ /* ExerciseItem[]  (§2.3) */ ],

  "external_ref": "chatgpt-run-42-day-14"   // optional idempotency key
}
```

* Field names deliberately mirror `ManualWorkoutBody` so the transformer
  is one-to-one.
* `external_ref` — when present, re-imports become idempotent. We store
  it on the workout doc; a second import with the same ref updates in
  place instead of inserting a duplicate.

### 2.3 ExerciseItem (warm-up / cool-down · flat)

Warm-ups and cool-downs are simple flat drills. They map straight to the
existing warmup/cooldown shape.

```jsonc
{
  "ref": {                          // one of these keys is required
    "exercise_id": "uuid-...",      //   preferred — exact library link
    "name": "World's greatest stretch", //   fallback — matched via resolver
    "aliases": ["WGS", "world greatest"]  // optional additional match tokens
  },
  "sets": 1,                         // default 1 for warmup/cooldown
  "reps": null,
  "duration_sec": 45,
  "rest_sec": 10,
  "notes": "Deep breath at bottom."  // becomes `cue` in guided flow
}
```

### 2.4 ExerciseBlock (main work · supports supersets + circuits)

Main-work items can be **standalone** exercises or **grouped blocks**
(superset / circuit / EMOM / AMRAP). The importer flattens groups into
the on-disk shape without breaking the existing storage contract.

**Standalone form** (identical shape to §2.3 with all prescription fields
allowed):

```jsonc
{
  "kind": "single",
  "ref": { "exercise_id": "…" or "name": "…" },
  "sets": 4, "reps": 8, "load": "70% 1RM",
  "rest_sec": 120, "tempo": "3-0-1-0",
  "rpe": 8, "notes": "Pause at chest 1s.",
  "alternative_exercise_id": "uuid-...",   // optional
  "alternative_name": "Machine chest press"// resolver fallback
}
```

**Group form** (superset / circuit / EMOM / AMRAP / tabata):

```jsonc
{
  "kind": "group",
  "group_type": "superset",          // see enum §2.5
  "group_label": "A1/A2",            // optional coach-facing tag
  "rounds": 4,                        // superset: sets; circuit: rounds
  "rest_between_rounds_sec": 90,
  "rest_between_items_sec": 15,       // in-group rest between stations
  "work_sec": null, "rest_sec": null, // for EMOM / interval / tabata
  "cap_min": null,                    // for AMRAP
  "notes": "Explosive concentric on A1, control on A2.",
  "items": [
    {
      "ref": { "name": "Barbell bench press" },
      "reps": 8, "load": "72.5kg", "tempo": "3-0-1-0"
    },
    {
      "ref": { "name": "Chest-supported row" },
      "reps": 10, "load": "22.5kg each"
    }
  ]
}
```

**How groups persist** (kept fully backwards-compatible):

* On write, every `items[]` entry becomes a normal exercise row in
  `db.workouts.exercises[]` (via `_norm_exercise`) with three extra
  fields:
  * `group_id: "grp_<uuid8>"` — shared across the block
  * `group_type: "superset"` (etc.)
  * `group_position: 0..n` — order within the round
  * `group_rounds: 4`, `group_rest_between_rounds_sec: 90`
* Row-level `sets` becomes `rounds`; row-level `rest_sec` stays as the
  in-item rest (defaults to `rest_between_items_sec`).
* Players / editors that don't know about `group_id` still see a valid
  sequential list. Ones that do know (Guided Flow after Phase 3) render
  the "A1 → A2 → rest → repeat" UX.

### 2.5 Enums

* `workout_type`: reuse `_ALLOWED_TYPES` — `strength | run | cardio |
  mobility | recovery | other`.
* `group_type`: `superset | triset | giantset | circuit | emom | amrap |
  tabata | interval | complex`.
* `override_policy`: `reject_conflicts | replace_conflicts | skip_conflicts`.

### 2.6 End-to-end realistic example

```json
{
  "$schema": "crewfit://programme-import/v1",
  "meta": {
    "client_email": "pietro@example.com",
    "month": "2026-07",
    "timezone": "Europe/London",
    "generated_by": "chatgpt-2026-06",
    "author_notes": "July · hypertrophy · 4-week accumulation"
  },
  "override_policy": "replace_conflicts",
  "workouts": [
    {
      "date": "2026-07-01",
      "title": "Upper · Push emphasis",
      "workout_type": "strength",
      "duration_min": 55,
      "location": "home_gym",
      "coach_notes": "Keep 1-2 RIR. Push volume, not intensity.",
      "warmup": [
        { "ref": { "name": "Cat-cow" }, "duration_sec": 40 },
        { "ref": { "name": "Band pull-apart" }, "sets": 2, "reps": 15 },
        { "ref": { "name": "Scap push-up" }, "sets": 2, "reps": 8 }
      ],
      "exercises": [
        {
          "kind": "single",
          "ref": { "name": "Barbell bench press" },
          "sets": 4, "reps": 6, "load": "77.5kg",
          "rest_sec": 150, "tempo": "3-0-1-0",
          "notes": "Pause 1s on chest set 3+4."
        },
        {
          "kind": "group",
          "group_type": "superset",
          "group_label": "B1/B2",
          "rounds": 3,
          "rest_between_rounds_sec": 90,
          "rest_between_items_sec": 15,
          "items": [
            { "ref": { "name": "Incline dumbbell press" },
              "reps": 10, "load": "24kg" },
            { "ref": { "name": "Chest-supported row" },
              "reps": 12, "load": "20kg" }
          ]
        },
        {
          "kind": "group",
          "group_type": "circuit",
          "rounds": 3,
          "rest_between_rounds_sec": 60,
          "items": [
            { "ref": { "name": "Push-up" }, "reps": 12 },
            { "ref": { "name": "TRX row" }, "reps": 12 },
            { "ref": { "name": "Plank" }, "duration_sec": 30 }
          ]
        }
      ],
      "cooldown": [
        { "ref": { "name": "Pec doorway stretch" }, "duration_sec": 45 },
        { "ref": { "name": "Child's pose" }, "duration_sec": 60 }
      ],
      "external_ref": "chatgpt-run-42-day-01"
    },
    {
      "date": "2026-07-02",
      "title": "Recovery mobility",
      "workout_type": "mobility",
      "duration_min": 25,
      "warmup": [],
      "exercises": [
        { "kind": "single", "ref": { "name": "90/90 hip switch" },
          "sets": 3, "reps": 8, "notes": "Slow. Breathe out on rotation." }
      ],
      "cooldown": []
    }
  ]
}
```

---

## 3. Import & Validation Workflow

Two-endpoint contract mirrors the existing roster upload pattern
(`upload-parse` → confirm) so the coach UI shape is familiar.

### 3.1 Endpoint contract

* **POST `/api/coach/programme-import/preview`**
  * Body: the JSON envelope above.
  * Returns a **`PreviewResult`** (§3.2) — nothing is written yet.
* **POST `/api/coach/programme-import/apply`**
  * Body: `{ "preview_id": "…", "confirm_conflicts": true, ...overrides }`
  * Requires the preview to have `blocking_errors == 0`. Rewrites are
    inline; response is the `ApplyResult` with created/updated workout
    ids.

Both are coach-only (`require_role("coach")`). Preview results are
stored for **10 minutes** in `db.programme_import_previews` to guarantee
apply consistency.

### 3.2 Preview / dry-run result shape

```jsonc
{
  "preview_id": "pv_...",
  "expires_at": "…",
  "meta": {
    "client_id": "…",
    "client_display": "Pietro Rossi",
    "month": "2026-07",
    "workout_count": 24,
    "days_covered": 24,
    "override_policy": "replace_conflicts"
  },
  "summary": {
    "workouts_ready": 22,
    "workouts_blocked": 2,
    "exercises_resolved": 78,
    "exercises_fuzzy_substituted": 6,   // matched but different name
    "exercises_new_drafts": 4,          // will become media-queue items
    "media_queue_new_items": 4,
    "date_conflicts": 3,
    "supersets": 8, "circuits": 3, "emom": 0, "amrap": 0
  },
  "per_workout": [
    {
      "date": "2026-07-01",
      "title": "Upper · Push emphasis",
      "status": "ready",
      "warnings": [
        { "code": "fuzzy_match", "exercise_index": 4,
          "raw_name": "TRX row", "matched": "Suspension row",
          "score": 62 }
      ],
      "errors": [],
      "conflict": {
        "existing_workout_id": "wk_...",
        "existing_source": "auto_generated",
        "will_be": "replaced"
      }
    },
    {
      "date": "2026-07-08",
      "title": "Lower · Heavy",
      "status": "blocked",
      "warnings": [],
      "errors": [
        { "code": "unresolved_exercise", "raw_name": "Cluster deadlift",
          "reason": "no library match ≥ 10, will be queued as draft" },
        { "code": "conflict_manual",
          "reason": "target date already has a manual workout; policy=reject_conflicts" }
      ]
    }
  ],
  "blocking_errors": 2,
  "next_actions": [
    "Rename 'Cluster deadlift' to a library name, or set override_policy=skip_conflicts"
  ]
}
```

### 3.3 Conflict handling

For every workout, the importer inspects `db.workouts.find_one({user_id, date})`:

| Existing row source           | policy: reject   | policy: replace                    | policy: skip |
|-------------------------------|-------------------|-------------------------------------|--------------|
| _no row_                      | insert            | insert                              | insert       |
| `auto_generated` (legacy)     | error             | delete existing, insert new         | skip         |
| `coach_manual`                | error             | error (never silently overwrite)    | skip         |
| any completed workout         | error             | error                               | skip         |

The `replace_conflicts` policy re-uses the exact delete-then-insert
sequence already living inside `coach_create_manual_workout`
(`_upsert_day_override` with `replace_day`), so the audit trail matches.

### 3.4 End-to-end step sequence

1. **Client resolution.** Look up user by `client_id` OR
   `client_email` (case-insensitive). 404 fast if missing.
2. **Schema validation.** Pydantic models mirror §2. Errors surface as
   `errors[*].code = "schema"`.
3. **Date validation.** Every `workouts[*].date` must (a) parse ISO, (b)
   fall inside `meta.month` ± 3 days, (c) not repeat within the payload.
4. **Exercise matching (deterministic).**
   * If `ref.exercise_id` is set → direct `db.exercises_v2.find_one`
     lookup. If missing → error `unknown_exercise_id`.
   * Else use `feature_v2_resolver.resolve_exercise_need(item, pool)`
     with the approved pool. Result buckets:
     * `matched` (score ≥ 50) → attach `exercise_id`.
     * `substituted` (10 ≤ score < 50) → attach `exercise_id`, add
       `fuzzy_match` warning with the resolved name so Louis can
       eyeball each substitution in the preview.
     * `unresolved` (< 10) → queue as **draft library entry** via
       `feature_media_queue.resolve_or_draft_exercise`. The row is
       ready for the media queue. Preview flags it under
       `exercises_new_drafts`.
5. **Group flattening.** Group blocks expand to flat exercise rows with
   the six `group_*` fields (§2.4). Row-level `sets`, `rest_sec`, etc.
   derived from the group's `rounds` / `rest_between_items_sec`.
6. **Conflict scan.** Per §3.3.
7. **Media queue simulation.** Run
   `scan_media_queue_for_sections(client, sections, workout_id=None,
   reason="programme_import_dry_run")` per workout in **preview**, but
   pass a `dry_run=True` flag (new, added in Phase 1) so it counts new
   items without inserting them. The count feeds
   `summary.media_queue_new_items`.
8. **Persist preview.** Insert a `db.programme_import_previews` doc
   with the fully-transformed workouts, TTL 10 min.
9. **Apply (POST /apply).**
   * Load preview by id (must be non-expired, must belong to same
     coach). Refuse if `blocking_errors > 0` unless the coach sends
     `force=true` (audited).
   * For each workout: same call sequence as
     `coach_create_manual_workout` (the very same helper is
     factored out into `feature_coach_manual_workouts._create_one_impl`
     during Phase 1 refactor). This guarantees identical audit,
     media-queue, day-override, and Guided-Flow enrichment behaviour.
   * Wrap the batch in a single audit log entry
     (`kind="programme_import"`) with the preview id, envelope hash,
     and workout-id list.
10. **Response.** `ApplyResult` returns per-workout status + a summary
    the frontend can flash on the calendar.

---

## 4. Technical Design Notes

### 4.1 Exercise matching (reuse)

We deliberately **do not** build a new matcher. We reuse:

* `feature_v2_resolver.get_approved_pool()` — approved + safe +
  client-visible pool (loaded once per import).
* `feature_v2_resolver.resolve_exercise_need()` — deterministic scoring.
* `feature_v2_resolver.create_exercise_request_if_missing()` — the
  dedup-aware draft creator.

The only new helper we need is a thin adapter that maps our
`ref.name` / `ref.aliases` object to the shape those functions expect
(`{"name": "..."}`). Aliases are simply appended to the name string with
a `|` separator so the token-based scorer picks them up (see
`_score_candidate` line 138).

### 4.2 Superset / circuit storage

Kept **inside** the existing `workouts.exercises[]` array — no new
collection, no new table. New fields (opt-in, safe to ignore for older
consumers):

* `group_id: string | null`
* `group_type: string | null`
* `group_position: int | null`
* `group_rounds: int | null`
* `group_rest_between_rounds_sec: int | null`
* `group_label: string | null`

Guided Flow reads flat, so day one behaviour is: supersets play as a
regular sequence with the item-level rest. Phase 3 adds true A1/A2
rendering when the player sees `group_id`.

### 4.3 Database changes (all additive, all backwards compatible)

* `db.workouts` — no schema migration, six new optional fields on
  exercise rows.
* `db.workouts` — new optional top-level field `import_ref` (the
  envelope `external_ref` from §2.2) with a **partial** unique index
  `{ user_id: 1, import_ref: 1 }` where `import_ref` exists → makes
  re-imports idempotent.
* `db.programme_import_previews` — new collection. Fields: `id`,
  `coach_id`, `client_id`, `envelope_hash`, `transformed_workouts[]`,
  `summary`, `blocking_errors`, `expires_at` (TTL index).
* `db.audit_log` (or the existing coach change log used by
  `_log_change`) — one entry per import with kind
  `programme_import`.

### 4.4 Frontend surface (planning only)

* New screen `/app/frontend/app/coach/client/[id]/import.tsx`
  (or a modal inside the existing workspace) with:
  * Drop-zone for a `.json` file OR a paste-JSON box.
  * "Preview" button → renders the §3.2 preview inline (workouts table
    with status pills, warnings, conflict badges).
  * "Fix and re-paste" flow — no partial submits.
  * "Import" button — disabled until `blocking_errors === 0`.
* Existing calendar auto-refreshes via the coach workspace's
  `/workouts/week` polling — no bespoke wiring needed.

### 4.5 Safeguards

* Dry-run is the default. `apply` never runs without a valid preview
  id.
* Max 62 workouts per envelope (2 months' worth) — hard cap to prevent
  runaway imports.
* Payload cap 512 KB.
* Rate-limit apply to 5 per hour per coach.
* All writes stamped `import_ref`, `import_preview_id`,
  `import_source="chatgpt"` (or free text from `meta.generated_by`).
* Rollback: because every workout is a normal manual workout, the
  existing DELETE `/api/coach/workouts/{wid}/manual` cleans them up
  one-by-one. We ALSO add `POST /api/coach/programme-import/{preview_id}/rollback`
  (Phase 3) that deletes all workouts stamped with that preview id.

---

## 5. Phased Implementation Plan

Credit ranges are estimates for MY (Claude) usage, assuming no LLM calls
inside the import path. They exclude UI polish loops.

### Phase 1 · Backend skeleton + schema validation
**Deliverables:**
* `feature_programme_import.py` (new) with:
  * Pydantic models for the envelope, workout, item, group.
  * `POST /preview` returning §3.2 shape (matching only, no writes).
  * Dry-run flag added to `scan_media_queue_for_sections`.
  * `db.programme_import_previews` created with TTL index.
* Unit tests for envelope validation, group flattening, resolver
  wiring against a fixture pool.
**Est. credits:** 40–60.
**Verifiable:** curl a fixture JSON → preview JSON matches expectations.

### Phase 2 · Apply path + media-queue integration
**Deliverables:**
* `POST /apply` — full write pipeline via a refactored
  `_create_one_impl` shared with `coach_create_manual_workout`.
* Idempotency via `import_ref` partial unique index.
* Conflict handling for all three policies.
* Audit-log entry.
* End-to-end integration test using the example envelope in §2.6.
**Est. credits:** 50–70.
**Verifiable:** apply the example envelope, then read
`/api/coach/clients/{cid}/workouts/week` — confirm workouts + audit
entries.

### Phase 3 · Coach frontend (paste + preview + apply)
**Deliverables:**
* `app/coach/client/[id]/import.tsx` route with paste-JSON box, file
  picker, preview table, warnings pills, blocking-error banner, apply
  button.
* Success toast + calendar refresh.
* Empty-state and error-state screens.
**Est. credits:** 45–65.
**Verifiable:** paste envelope in UI, see preview, apply, verify
calendar populated.

### Phase 4 · Group-aware Guided Flow rendering (optional)
**Deliverables:**
* Guided Flow (`/app/workout/[id]/play.tsx`) reads `group_id` /
  `group_type` to render A1/A2 rotation UI (superset + circuit +
  EMOM). Standalone rows unchanged.
* Coach workspace shows a small `A1/A2` chip next to grouped rows.
**Est. credits:** 55–75.
**Verifiable:** manual workout with a superset plays as A1 → A2 →
rest → repeat; screenshot compare.

### Phase 5 · Extras (optional, gated)
* Rollback endpoint (§4.5).
* CLI helper (`scripts/import_programme.py`) so imports can be
  automated by Louis without opening the app.
* Sample generator prompt for ChatGPT bundled with the app so Louis
  can paste one canonical prompt.
**Est. credits:** 20–35 combined.

**Total (Phases 1–3 = the MVP):** ~135–195 credits.
**Full stack (Phases 1–4):** ~190–270 credits.

---

## 6. Reuse Map (what we borrow, not rebuild)

| New capability                    | Existing system reused                                              |
|-----------------------------------|---------------------------------------------------------------------|
| Exercise matching                 | `feature_v2_resolver.resolve_exercise_need` + `get_approved_pool`   |
| Draft creation                    | `feature_v2_resolver.create_exercise_request_if_missing`            |
| Media queue                       | `feature_media_queue.scan_media_queue_for_sections`                 |
| Manual workout persistence        | `feature_coach_manual_workouts._normalise_sections` + `_norm_exercise` + `_enrich_for_guided` + `_merge_cooldown_into_exercises` |
| Day override / replace-day        | `feature_coach_manual_workouts._upsert_day_override`                |
| Client lookup                     | `db.users` (email + id)                                             |
| Audit log                         | `server._log_change`                                                |
| Calendar refresh                  | `/workouts/week` (unchanged; frontend already polls)                |
| Roster context (future)           | `feature_coach_roster_upload` (unchanged; import can piggyback via `roster_hints`) |
| Auto-media pipeline               | `feature_auto_media_gen.py` fires on exercise create, unchanged     |

---

## 7. Open Questions for Louis

1. Should `client_email` OR `client_id` be the required key? Louis will
   likely prefer email because ChatGPT can hard-code it — confirmed?
2. Superset in the FIRST release: render as flat list (Phase 3) with
   an "A1/A2" chip, OR full rotation UX (Phase 4)? Phase 4 is bigger
   spend.
3. Default `override_policy` — `reject_conflicts` (safest) or
   `replace_conflicts` (matches Louis's current manual-day flow)?
4. Do we need a **weekly-only** variant (one week per envelope) for
   short-term use, or is monthly always the unit of work?
5. Should the schema also accept **rest days** as explicit workout
   objects with `workout_type="recovery"` and empty `exercises[]`?
   Recommended: yes, because it lets the importer "own" the whole
   month.
