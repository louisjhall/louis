# V2 Publishing Lifecycle Audit

Audit only. Reconstructs the ACTUAL current V2 lifecycle from code + verifies Pietro's real state against what the coach UI shows.

## Two coexisting V2 publish paths (source of most confusion)

The code contains TWO distinct publish endpoints, both mounted under `/v2/coach/clients/{id}/…`:

| Path | Endpoint | Draft collection | Live collection | Implementations | Approach |
|---|---|---|---|---|---|
| **A. "Engine V2" (canonical, newer)** | `POST /v2/coach/clients/{id}/engine-v2/publish` in `feature_v2_engine_v2_publish.py` | `plan_drafts_v2` | `plan_live_v2` | via placements + session_specs | Whole-draft immutable Live version |
| **B. "Plan publish" (older selective)** | `POST /v2/coach/clients/{id}/plan/publish` in `feature_v2_coach_publish.py` | `plan_drafts` | `workout_assignments.status=live` | `workout_assignments.live_implementation_id` | Selective per-assignment + change_sets |

**Path A is what Pietro's data is on** (`plan_drafts_v2` + `plan_live_v2` rows present).
**Path B still writes to `workout_assignments`** which is otherwise a legacy collection — its residual use by the "plan publish" model is the reason the audit had to keep the collection alive.

The workspace `EngineV2DraftPanel` calls Path A. The workspace ribbon "Publish changes" button also calls Path A. Path B is called only by an older `PublishPanel` sheet that appears when there are `change_sets`; the sheet is still reachable via the workspace but underused.

## Actual Engine V2 lifecycle (Path A — canonical)

```
Client DNA        (users.profile: goal, event, days, duration, equipment, injuries, prefs, aviation_role)
       +
Roster            (rosters + roster_versions)
       +
Programme state   (previous plan_live_v2 if any, previous progression_states, decision_records)
       ↓
[STAGE 1] roster_uploaded           → set when roster upload succeeds
[STAGE 2] roster_parsed             → set when parser normalises days/flights
[STAGE 3] schedule_created          → set when schedule_days written
[STAGE 4] planning_programme (WHAT)  ObjectiveExposures + ProgrammePhases planned
[STAGE 5] generating_workouts (HOW) session_specs built for every placement
[STAGE 6] validating                 programme_validation.ok + exceptions computed
[STAGE 7] ready_for_review           Draft persisted with status="needs_review"
[STAGE 8] published                  plan_live_v2 row inserted; previous Live deactivated
       ↓
plan_live_v2  ←  authoritative source for client "Today" screen
plan_live_v2_implementations ← per-day HOW overlays (Universal Travel / Change Setup writes)
workout_implementations ← client completion records
```

### Stage-by-stage trace (from `/generation/status` endpoint in `feature_v2_coach_directives.py:177`)

| Stage | Display label | Backend state stored at | Cleared when | Stale risk |
|---|---|---|---|---|
| `roster_uploaded` | Roster uploaded | `rosters.uploaded_at` | Never | Low |
| `roster_parsed` | Roster parsed | `rosters.parsed_at` + `roster_versions.parsed` | Never | Low |
| `schedule_created` | Schedule created | `schedule_days` count > 0 for month | Never | Low |
| `planning_programme` | Planning programme | `plan_drafts_v2.stages.what` timestamp | On next kickoff | Low |
| `generating_workouts` | Generating workouts | `plan_drafts_v2.stages.how` timestamp | On next kickoff | Low |
| `validating` | Validating | `plan_drafts_v2.stages.validate` timestamp | On next kickoff | Low |
| `ready_for_review` | Ready for review | `plan_drafts_v2.status == "needs_review"` | On publish or supersession | **HIGH** — this stage stays lit permanently once a Draft exists, even after publish |
| `published` | Published | `plan_live_v2.published_at` (of currently-active Live) | On new publish (previous Live deactivated) | Low but visually dominant |

**Problem**: once a client has ANY Draft ever generated, all seven upstream stages stay green forever. The pipeline card thus dominates the workspace permanently even for a client in a normal Live state with no build in progress. That is the root cause of the "why is the pipeline still shown when Pietro already has Live?" confusion.

## Publish gates (Path A, `feature_v2_engine_v2_publish.py:476-540`)

1. **Draft freshness** — supplied `draft_id` must match the latest active draft. Else 422 `stale_draft`.
2. **Goal-config gate** — `get_goal_config_status(goal_key)` must not be `MISSING`. If `PARTIAL`, coach must pass `ack_partial_config=true`.
3. **Programme validation gate** — `programme_validation.ok` must be true, OR every KEY/IMPORTANT exception must be resolved via `exception_resolutions[]` (categories: `unfilled_objective`, `validator_error`, `dna_gap`). Non-KEY/IMPORTANT exceptions do not block.
4. **Session-spec completeness** — every non-rest placement must have a `session_specs[exposure_id]`. Else 422 `incomplete_workout_construction`.
5. **Previous Live** — automatically deactivated (kept in history with `superseded_by_draft` link).
6. **New Live** — immutable; `id` generated, `active=true`.

**Any route that bypasses these gates?** No — the only frontend caller is `EngineV2DraftPanel.publish()`. Path B (`plan/publish`) does NOT touch `plan_live_v2`, so it cannot make an Engine-V2 programme "Live" behind the coach's back. But Path B can promote `workout_assignments` to `status=live` (used only when `change_sets` exist), which is confusing terminology — those Live workout_assignments are separate from `plan_live_v2` Live.

**Auto-approval risk threshold** (Admin coach-controls field): grep of publish code shows the field name is referenced but never mutates any gate above. Confirmed not a bypass. The label is misleading but the mechanism is safe.

## Rebuild draft (workspace `EngineV2DraftPanel.tsx:83, 200`)

```
Coach taps "↻ Rebuild draft"
   ↓
POST /v2/coach/clients/{id}/engine-v2/kickoff
   ↓  ( in feature_v2_engine_v2_kickoff.py:140 )
Load DNA + latest roster + previous progression + directives
   ↓ WHAT   → ObjectiveExposures (respects directives + progression)
   ↓ WHEN   → placements (respects roster days + rest rules)
   ↓ HOW    → session_specs (uses exercises_v2 + client equipment/injuries)
   ↓ VALIDATE → programme_validation + exceptions
   ↓
Insert NEW plan_drafts_v2 row with status="needs_review"
Previous draft(s) for same client are NOT physically deleted — they remain queryable but new draft is now "latest". `_ACTIVE_DRAFT_FILTER` (line ~10) selects only the latest active.
   ↓
Live is UNAFFECTED. Client continues to see the current Live plan.
Only when coach calls `/engine-v2/publish` on the new draft does Live change.
```

**LLM use during rebuild**: **NO**. Kickoff is fully deterministic — WHAT/WHEN/HOW/VALIDATE are all deterministic engines. No `emergentintegrations` call in that path.

**Directives / locks respected**: Yes. Kickoff reads `db.directives` and applies them during WHAT. Assignment-level `locked=true` is not consumed by kickoff (Draft is a fresh plan), but manual moves + coach edits on Live are preserved because Live is untouched.

## "Ask CrewFit to adjust this plan…" command bar

`feature_v2_coach_command_bar.py:196` (`/command-bar/parse`) + `:262` (`/command-bar/apply`).

- **Parse**: Uses an LLM (Emergent LLM key, Claude Sonnet 4.5) to interpret the coach's natural-language request into a structured mutation intent (`change_type`, `target_assignments`, `params`). **No mutation yet.**
- **Apply**: Deterministic. Applies the parsed intent to the current Draft (`plan_drafts_v2`) — does NOT touch Live.
- Types of change: `swap_assignment`, `change_placement_date`, `change_intensity`, `add_directive`, `resolve_exception`, `lock_assignment`.
- History logged to `command_bar_history` for audit.

**Publication**: never. The command bar always writes to Draft; Live changes only through the publish endpoint.

**Risk profile**: LOW. Coach previews changes before applying. LLM only interprets intent; it does not construct workouts. Every apply is deterministic and reversible via Draft supersession.

## Client "Change Setup" (Universal Travel) — separate lane

- Coach or client changes environment/equipment for a specific day → writes `plan_live_v2_implementations` overlay row (client_id + assignment_id + date + overlay HOW).
- Does **NOT** create a new `plan_drafts_v2` row.
- Does **NOT** trigger the pipeline stages.
- Live remains the same version.

**Pipeline should NOT re-light for Change Setup**. Audit confirms it does not — the stages only advance on `/engine-v2/kickoff`.

## Roster change after Live

Trace of `/coach/roster/upload` (in `feature_coach_roster_upload.py`):

1. Insert new `rosters` row (or `roster_versions` diff).
2. Emit attention item `kind="roster_changed"`.
3. If `engine_v2_enabled`: automatically call `engine_v2_kickoff` to build a **new Draft**. Live is untouched.
4. Coach sees "Roster changed" on Home + workspace ribbon; a new Draft appears in the Programme Draft panel.
5. Coach reviews Draft → publishes → new Live overrides previous Live.
6. Completed history in `workout_implementations` is preserved (Live change doesn't wipe completions).

**Client sees the old Live plan until publish completes.** Correct behaviour.

## DNA change after Live

- Goal / days / duration / equipment / restriction changes on user profile do NOT auto-kickoff.
- Coach must manually rebuild Draft from workspace ("↻ Rebuild draft").
- Live continues until publish.

**No auto-invalidate on DNA change.** This is intentional per audit (avoid accidental regenerations) but means the pipeline shows "Live" while a stale DNA lurks. Coach must remember to rebuild. **Minor gap; not a bug.**

## Pietro's actual state vs Admin page display

| Real state (DB) | Admin page shows | Contradiction? |
|---|---|---|
| Draft `4f72cdf1-…` `needs_review`, 23 placements, validation.ok=False | "No programme yet." | **YES** |
| Live `819ec6c6-…` active, 23 placements, window 2026-07-27→08-30 (5 weeks) | "0 workouts", "Awaiting generation" | **YES** |
| V1 `workouts` count = 0 | "This week 0/0", adherence 0%, missed 0 | Admin reads V1 → the 0 is technically accurate for V1 collection but misleading for Pietro's actual state |
| V2 `workout_implementations` count = 0 (no completions yet) | Admin does not read this at all | **DATA UNAVAILABLE** would be honest; 0 is misleading |
| Draft validation.ok=False, exceptions=0 | No mention on Admin | (workspace shows "2 to review" correctly) |
| Coach controls block persists 5 fields none of which engine reads | Rendered as if functional | **YES** |

**Verdict**: Admin page is a false mirror. Workspace is the source of truth.

## Recommended coach-facing lifecycle

Simplify the eight-stage pipeline into four **product** states that hide technical stages:

| State | When shown | Displayed |
|---|---|---|
| **NO PROGRAMME** | No plan_drafts_v2 AND no plan_live_v2 | "Upload roster + build plan to get started." (single card) |
| **BUILDING DRAFT** | Draft has `stages.what` OR `stages.how` OR `stages.validate` in progress | Progress dots only during active kickoff (~5-15s). Auto-hide when done. |
| **DRAFT NEEDS REVIEW** | plan_drafts_v2.status=`needs_review` and no Live | Single amber "Draft ready — Review" card |
| **LIVE** | plan_live_v2.active=true and no fresher unpublished Draft | Green "Live vN · N placements" pill in ribbon; no pipeline card |
| **LIVE + ROSTER CHANGED** | Live + attention kind=roster_changed unresolved | "Roster changed" banner + prompt to rebuild |
| **LIVE + NEW DRAFT** | Live + a newer plan_drafts_v2 with status=needs_review | "New Draft ready for review — Publish to update Live" |
| **PUBLISHING** | Actively in publish transaction (~1-3s) | Small toast; workspace grid reload on complete |

Only the "BUILDING DRAFT" state should show the technical pipeline. Once complete, collapse it. Never show the pipeline permanently.

## Summary — cleanup impact estimate

- Path A publish is safe and canonical.
- Path B publish (older selective + change_sets) is functional but overlaps with Path A. Recommend deprecating in a later iter after confirming zero call sites still hit it.
- Admin page misreads are UI-only — DB is correct, workspace is correct.
- Pipeline over-persistence is a display heuristic in `GenerationStatusBanner.tsx`.
- Cleanup impact: **SMALL to MEDIUM** — one file changes (`GenerationStatusBanner.tsx` collapse logic) + Admin page thin-out (see `CLIENT_ADMIN_AUDIT.md`) + optional deprecation of Path B.
