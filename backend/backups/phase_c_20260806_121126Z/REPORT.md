# Phase C1 — Exercise Library Reset — DRY-RUN Report
_Generated: 2026-08-06T12:11:27Z_
_Backup dir: `/app/backend/backups/phase_c_20260806_121126Z`_

## ⚖️ Retention Rule (Option A)
**RETAIN** if any of:
- `status ∈ {Approved, Live}` OR `approval_status == "approved"`  → *approved core*
- Referenced by an active client's workout (by id or normalised name)
- Referenced by an active client's programme

**PROPOSED FOR DELETION** = everything else.

## 📊 Headline Numbers
- **Total rows in `exercises_v2`**: 4500
- **Total to RETAIN**: 81
  - Approved / Live core: 14
  - Retained ONLY because referenced by active data: 67
- **Total PROPOSED FOR DELETION**: 4419

### Delete pile — sub-buckets
- other_unreferenced_rows: 213
- unapproved_generated_drafts: 4206
- (unreferenced duplicate rows folded into the above): 322

## 👥 Active Clients
- App Store Reviewer — `reviewer@crewfit.net` — id `u_reviewer_63d24c1c`
- [deleted client 8d24515c] — `deleted+8d24515c@crewfit.deleted` — id `8d24515c-5255-483d-9f10-2261c8d86400`
- Louis Hall — `louishallpt@outlook.com` — id `7a708652-5635-4c3a-a8cc-033220f1f03d`
- Alex Rivera — `client@crewfit.com` — id `0b0651e2-3453-4c39-b858-b377e8284f8c`
- Pietro Sangermano — `pietrosangermano1992@hotmail.com` — id `6f945cdb-1a64-4411-bf47-058d0e3160ec`

Workouts scanned: **49**  |  Programmes scanned: **0**

## 🔗 Active Workout / Programme Exercise References
- Unique exercise ids referenced by active data: **37**
- Unique canonical exercise names referenced: **56**
- Unique exercises actually required across the 5 active client(s): **56**

## 🛠️ Rebuild Plan
- Names already covered by retained rows: **56**
- Names to be rebuilt via `create_exercise_request_if_missing` (Needs Review / Needs Media): **0**
- All rebuilt entries go through **Phase B fuzzy-dedup**, so re-adding the same movement won't create a second row.

## 🛡️ Safety Checks
- Workout refs pointing to a `exercises_v2` id that **doesn't exist**: **1** (pre-existing orphans — will be rebuilt during rescan)
- Workout names that don't match ANY current row (case-insensitive, singularised): **0** (pre-existing orphans — will be rebuilt)
- **Deletes that would break a live reference**: **0**  ← must be 0

## 🖼️ Obsolete Media Metadata
- `exercise_content_images` rows tied to to-be-deleted `exercises_v2` ids: **4192**
- These metadata rows would be removed in C2. **R2 objects themselves stay intact** (per scope).

## 🔄 Auto-Repopulation Surfaces (would recreate drafts unless guarded)
The following code paths automatically create new rows in `exercises_v2` by calling `create_exercise_request_if_missing`:
1. `GET /api/exercise-requests/grouped` → auto-runs `backfill_missing_exercise_requests_from_workouts` on every coach visit (14d back / 21d fwd, cap 100).
2. `POST /api/exercise-requests/scan-workouts` → manual coach button (60d/60d, cap 500).
3. `feature_v2_resolver.py` V2 generation path — writes drafts as workouts are constructed.
4. `feature_programme_import.py` — Monthly JSON Import files a draft for any unknown name.
5. `feature_coach_manual_workouts.py` — manual-builder saves trigger the resolver.
6. `feature_flight_support_media.py` / mobility flow — writes drafts for pre/post-flight moves.
7. `feature_traffic_light.py` → `backfill_exercise_ids`.
8. `feature_auto_media_gen.py` — mutates media state on `exercises_v2` and `exercise_content_images`.
9. `server.py` startup migrations (idempotent — do not recreate deleted rows unless flagged).

### Proposed Guard (for C2)
- Introduce env flag `EXERCISE_BACKFILL_DISABLED=true` guarding **all** call sites above (single early return + log).
- Toggle to `false` only during the **controlled rescan** step of C2, with the window narrowed to future workouts only.
- Confirms via unit assertion that historical workouts (>0 days in the past) do not create drafts while the flag is set.

## 📜 Exact C2 Deletion Criteria (reference for later approval)
```
DELETE FROM exercises_v2 WHERE
    NOT (status IN ('Approved','Live') OR approval_status = 'approved')
  AND id NOT IN <active_workout+programme id refs>
  AND canonical(exercise_name) NOT IN <active canonical name refs>
  AND canonical(requested_name)  NOT IN <active canonical name refs>
```
Companion deletion:
```
DELETE FROM exercise_content_images WHERE exercise_id IN <delete_ids>
```
Companion action:
- After deletion, run `backfill_missing_exercise_requests_from_workouts` once with a **future-only** window (`days_back=0`, `days_forward=60`) for the 4 active clients only — everything else stays quiet.

## 📁 Artefacts Written (no DB writes performed)
- `/app/backend/backups/phase_c_20260806_121126Z/exercises_v2.json` — full collection backup
- `/app/backend/backups/phase_c_20260806_121126Z/exercise_content_images.json` — full media metadata backup
- `/app/backend/backups/phase_c_20260806_121126Z/active_clients.json`
- `/app/backend/backups/phase_c_20260806_121126Z/delete_ids.json` — ids that C2 would delete
- `/app/backend/backups/phase_c_20260806_121126Z/retain_ids.json` — ids that C2 would keep
- `/app/backend/backups/phase_c_20260806_121126Z/rebuild_names.json` — canonical names to rebuild after reset
- `/app/backend/backups/phase_c_20260806_121126Z/orphan_name_refs.json` — pre-existing orphaned workout refs
- `/app/backend/backups/phase_c_20260806_121126Z/summary.json` — machine-readable