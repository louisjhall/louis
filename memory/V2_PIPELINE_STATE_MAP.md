# V2 Pipeline State Map

Concise per-stage state machine for the coach-facing pipeline vs the actual Engine V2 draft-and-live lifecycle. Companion to `V2_PUBLISHING_LIFECYCLE_AUDIT.md`.

## Displayed pipeline (current — `GenerationStatusBanner.tsx`)

```
[1] Roster uploaded
      ↓
[2] Roster parsed
      ↓
[3] Schedule created
      ↓
[4] Planning programme       (WHAT / ObjectiveExposures)
      ↓
[5] Generating workouts      (HOW / session_specs)
      ↓
[6] Validating               (programme_validation + exceptions)
      ↓
[7] Ready for review         (plan_drafts_v2 persisted needs_review)
      ↓
[8] Published                (plan_live_v2 active row)
```

## Actual Engine V2 state flow

```
Coach uploads roster          rosters + roster_versions
      ↓                       (attention: roster_changed emitted if Live existed)
kickoff endpoint fires        POST /v2/coach/clients/{id}/engine-v2/kickoff
      ↓
WHAT (deterministic)          plan_drafts_v2.exposures, effective_context
      ↓
WHEN (deterministic)          plan_drafts_v2.placements
      ↓
HOW  (deterministic)          plan_drafts_v2.session_specs
      ↓
VALIDATE                      plan_drafts_v2.programme_validation + exceptions
      ↓
Persist Draft                 plan_drafts_v2.status="needs_review"
      ↓
[Coach reviews in workspace]
      ↓
publish endpoint fires        POST /v2/coach/clients/{id}/engine-v2/publish
      ↓
Gate: draft freshness, goal-config, validation.ok OR all KEY/IMPORTANT resolved, specs complete
      ↓
Deactivate previous Live      plan_live_v2 (old).active=false, superseded_by_draft=<id>
      ↓
Insert new Live               plan_live_v2 (new) immutable, active=true
      ↓
[Client sees new Live]
```

## Stage source-of-truth map

| Displayed stage | Real state stored in | Field(s) checked | Cleared when |
|---|---|---|---|
| Roster uploaded | `rosters` | `rosters.uploaded_at` (existence) | Never |
| Roster parsed | `rosters` / `roster_versions` | `rosters.parsed_at` (existence) | Never |
| Schedule created | `schedule_days` | count > 0 for the client's current window | Never |
| Planning programme | `plan_drafts_v2` | `stages.what` timestamp (or absence + `status="planning"`) | Overwritten on next kickoff |
| Generating workouts | `plan_drafts_v2` | `stages.how` timestamp | Overwritten on next kickoff |
| Validating | `plan_drafts_v2` | `stages.validate` timestamp | Overwritten on next kickoff |
| Ready for review | `plan_drafts_v2` | `status == "needs_review"` | On publish (transitions to `promoted`) OR on new kickoff supersession |
| Published | `plan_live_v2` | `active == true AND published_at IS NOT NULL` | Superseded by new publish |

## When each stage advances

- Stages [1]-[3] are **preconditions**, not programme stages. They should be a green "ready" tick, not part of a permanent pipeline.
- Stages [4]-[6] are the actual **generation work**. Deterministic, ~5-15s wall-clock. They advance in `feature_v2_engine_v2_kickoff.py:141`.
- Stage [7] is a **coach product status**, not a technical stage.
- Stage [8] is another **product status**.

Mixing preconditions + generation timers + coach statuses in one visual list is why the pipeline card feels heavy and never disappears.

## When each stage becomes stale / misleading

- **[1]-[3]** never become stale. They just stay green forever.
- **[4]-[6]** never become stale visually — they stay green once the draft finished. There's no "these ran a month ago" indicator.
- **[7]** stays green until either publish OR a new kickoff. After publish, `status="promoted"` — banner should react but currently keeps showing `ready_for_review` if it looks only at "did this stage complete once".
- **[8]** correctly reflects current publish state (there's exactly one active Live at a time).

## Client Change Setup — does NOT touch the pipeline

- Writes `plan_live_v2_implementations` overlay row.
- Does NOT create a plan_drafts_v2 doc.
- Does NOT advance any pipeline stage.
- Live version does NOT change.
- Pipeline banner should never re-appear for a Change Setup.

**Audit confirms code respects this.** The problem is only that the banner permanently displays past stages when it should be idle.

## Flight Support — does NOT touch the pipeline

- `flight_support_activity` completions and `flight_support_overrides` are separate collections.
- Aviation Support selection runs at read-time (deterministic).
- Never advances pipeline stages, never modifies plan_drafts_v2 or plan_live_v2.

## Recommended coach-product state (four states)

Replace the eight-stage banner with:

| Product state | Condition | Coach sees |
|---|---|---|
| **NO PLAN** | no roster OR no `plan_live_v2` and no `plan_drafts_v2` for client | "Upload roster → Build plan" prompt |
| **BUILDING** | active kickoff in progress (in-flight `stages.what/how/validate` timestamps within last ~30s) | Live progress dots. Auto-hide when done. |
| **DRAFT NEEDS REVIEW** | Latest `plan_drafts_v2.status=="needs_review"` AND (no Live OR Live is older than Draft) | Amber "Draft ready — Review" card |
| **LIVE** | `plan_live_v2.active=true` AND no newer unpublished Draft | Green "Live vN · N placements" pill. No pipeline card. |

Sub-badges (secondary):

- "Roster changed" — appears if attention_items unresolved kind=roster_changed
- "N exceptions to resolve" — appears if draft.exceptions.filter(KEY/IMPORTANT unresolved).count > 0
- "New Draft ready" — appears if Live + newer Draft(status=needs_review)

Publish transition is a modal / toast, not a stage.

## Fields Engine V2 actually uses

- `users.profile.goal_key`, `event.date`, `training_days_per_week`, `session_duration_min`, `equipment`, `injuries`, `variety_preference`, `cardio_preference`, `aviation_role`, `body_area_focus`
- `rosters.days[]`, `roster_versions[]`
- `directives`
- `progression_states`
- `objective_exposures`
- `plan_drafts_v2`
- `plan_live_v2`
- `plan_live_v2_implementations`
- `programme_phases`
- `exercises_v2`
- `decision_records`

## Fields Engine V2 does NOT read (dead config on Admin)

- `user.coach_controls.programme_flexibility`
- `user.coach_controls.progression_speed`
- `user.coach_controls.injury_caution_level`
- `user.coach_controls.video_touchpoint_cadence`
- `user.coach_controls.auto_approval_risk` (referenced but never bypasses validation)

All safe to remove from the UI.
