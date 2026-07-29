# Pietro Admin Page — Full Audit

**Scope:** every section rendered by `/app/frontend/app/coach/client/[id].tsx` when a coach opens the Admin/Legacy client page for Pietro (`c4c7c7dd-4303-4645-af2c-b70212495360`).

**Audit only — no code changes.**

## Section-by-section map

| # | Label (top→bottom) | Component/file | Data source(s) | Class | Duplicated in canonical workspace? | Recommended destination |
|---|---|---|---|---|---|---|
| 1 | **LIVE SIGNALS · LAST 14D** (Energy/RPE/Adherence/Missed) | `[id].tsx:661-708` | `GET /coach/clients/{id}/live-signals` | Reads V1 `workouts`+`check_ins` (`get_live_signals` in `feature_coach_live_signals.py`) | LEGACY-mixed (V1 workouts collection empty → shows 0) | Yes, `progress` tab uses `/v2/coach/clients/{id}/plan/progress` | **REMOVE from Admin.** Migrate to workspace `progress` tab. |
| 2 | **COACH DIRECTIVES · PINNED** | `[id].tsx:709-770` | `GET/POST/DELETE /coach/clients/{id}/directives` | SHARED (same collection V2 also reads) | Yes, workspace has `add-directive-btn` writing to same collection | **REMOVE from Admin.** Directives already live in workspace ribbon. |
| 3 | **PROGRAMME BY MONTH** button | `[id].tsx:773` | Routes to `/coach/client-months/{id}` (now redirects to workspace) | LEGACY UI (now redirected) | Yes, workspace already shows monthly grid | **REMOVE** the button entirely. |
| 4 | **WEEKLY SCRIPT** button | `[id].tsx:783` | Routes to `/coach/scripts/{id}` | CURRENT (separate script domain) | No | **MOVE** into workspace `messages` tab or into Admin drawer as "Compose script". |
| 5 | **DRAFT REPLY** button | `[id].tsx:789-798` | `POST /coach/messages/generate` | CURRENT (LLM assistant) | No | **MOVE** to workspace `messages` tab. |
| 6 | **OVERVIEW** section header | `[id].tsx:845` | — | Duplicate of workspace header | Yes | **REMOVE**. |
| 7 | **PROGRAMME OVERVIEW** card ("No programme yet" / This Week / Missed / Review / Locked / Template / Source) | `[id].tsx:866-920` (renders `programme` state) | `GET /coach/clients/{id}/programme` returns V1 `programmes` row (which does not exist for Pietro → shows "No programme yet") | **LEGACY, MISLEADING** | Workspace shows V2 Programme Draft correctly | **REMOVE.** Any residual programme summary belongs in the workspace Plan tab where it reads V2. |
| 8 | **PROGRAMME TIMELINE** | `[id].tsx:921` | `GET /coach/clients/{id}/programme/timeline` (V1) | **LEGACY** | No (V2 Change Log covers this) | **REMOVE.** |
| 9 | **ASSIGNED COACH · CHANGE** | `[id].tsx:994` | `POST /admin/clients/{id}/assign-coach` | CURRENT (admin) | No | **KEEP** in Admin drawer. |
| 10 | **RESET PASSWORD** | `[id].tsx:322, 1006` | `POST /coach/clients/{id}/reset-password` | CURRENT (admin) | No | **KEEP** in Admin drawer. |
| 11 | **ARCHIVE / RESTORE / DELETE / PERMANENT DELETE** | `[id].tsx:245-309` | `POST /admin/clients/{id}/archive|restore|soft-delete|permanent-delete` | CURRENT (admin) | No | **KEEP** in Admin drawer. |
| 12 | **MANAGE COACHES** link | `[id].tsx:1415` | Routes to `/coach/admin/coaches` | ADMIN | No | **KEEP** but move to sidebar Admin submenu (already there). |
| 13 | **PREVIEW AS THIS CLIENT** | `[id].tsx:1083` | Preview-launcher mechanism | CURRENT | Yes, also on `/clients` cards | **REMOVE** from Admin (already on Clients card). |
| 14 | **COACH CONTROLS** (Flexibility / Progression / Injury Caution / Video Touchpoint / Auto-approval risk) | `[id].tsx:1091-1116` | `GET/POST /coach/clients/{id}/controls` (`user.coach_controls.*`) | See §Coach Controls deep-dive below | Partially (goals tab covers some) | **MOVE** relevant controls to workspace `goals` tab; **REMOVE** dead ones. |
| 15 | **PROFILE** summary (airline, position, level, days/week, weight, calorie target) | `[id].tsx:1117` | Reads user.profile.* fields | READ-ONLY duplicate | Yes, workspace `goals` shows the canonical DNA | **REMOVE**. Editable DNA belongs in workspace `goals`. |
| 16 | **ROSTER · <week>** rendering | `[id].tsx:1129` | `GET /coach/clients/{id}/roster/...` | CURRENT roster but wrong location | Yes, workspace Plan tab | **REMOVE.** Roster belongs on workspace Plan. |
| 17 | **WEEK PLAN · N WORKOUTS** ("0 WORKOUTS" for Pietro) | `[id].tsx:1167` | Reads V1 `workouts` collection | **LEGACY, MISLEADING** — V1 collection empty for Pietro | Yes, workspace Plan tab shows real V2 sessions | **REMOVE.** |
| 18 | **HABITS · N ACTIVE** | `[id].tsx:1247` | `GET /coach/clients/{id}/habits` (from `feature_habit_engine.py`) | CURRENT (Atlas-seeded habits system, separate from programme) | No (workspace does not have a habits tab) | **NEEDS DECISION.** Either add a `habits` tab to workspace OR keep in Admin as coach-only setting. |
| 19 | **CHANGE LOG · N** | `[id].tsx:1336` | `GET /coach/clients/{id}/change-log` (V1 change-log) | LEGACY duplicate | Yes, workspace `history` tab reads `/v2/coach/clients/{id}/decisions` | **REMOVE.** |
| 20 | **PROGRAMME (V1) card + regenerate/approve/preview/apply** | (removed iter 128d) | — | — | — | (already removed) |

## Contradictory data on Pietro's Admin page — root cause

Pietro's actual DB state (verified read-only):

- **Draft**: exists (`4f72cdf1-...`), `status="needs_review"`, `active=None`, placements=23, specs=23, validation.ok=False, exceptions=0
- **Live**: exists (`819ec6c6-...`), `active=True`, placements=23, window=2026-07-27→2026-08-30 (5 weeks)
- **V1 `workouts`**: 0 rows for Pietro
- **V1 `workout_assignments`**: 0 rows for Pietro
- **V1 `programmes`**: 0 rows for Pietro
- **V2 `plan_live_v2_implementations`**: 0 (no HOW overlays yet)
- **V2 `workout_implementations`**: 0 (no completions yet)

Now every "wrong" number on the Admin page:

| Field on Admin | Displayed value | Endpoint | Reads | Why wrong |
|---|---|---|---|---|
| PROGRAMME OVERVIEW → "No programme yet." | (empty) | `GET /coach/clients/{id}/programme` | V1 `programmes` collection | Pietro has 0 rows there. His programme is in `plan_live_v2`, invisible to this endpoint. |
| WEEK PLAN → "0 WORKOUTS" | 0 | Reads V1 `workouts` collection | Empty for Pietro | Workspace Plan tab reads V2 placements → 23 sessions. |
| THIS WEEK → "0/0" | 0/0 | Same V1 read | Empty | Same. |
| ADHERENCE → 0 | 0 | `GET /coach/clients/{id}/live-signals` → V1 workouts | Empty | Should render "—" (no data) not 0 for a V2 client. |
| MISSED → 0 | 0 | Same live-signals endpoint | Empty | Same. |
| SOURCE → "AWAITING GENERATION" | text | Derives from absence of V1 programme row | V1 gap | Wrong — Pietro has V2 Draft+Live. |
| ENERGY / RPE 7D | (empty or 0) | live-signals endpoint | V1 workouts+check_ins | Same fallback. |

**Bottom line**: Every "programme-shaped" field on the Admin page reads V1 collections. Since Pietro has no V1 data, everything says "0 / awaiting / no programme". His actual V2 programme (Draft `needs_review` + Live 23 placements) is completely invisible on this page. The workspace shows the truth.

## Coach Controls deep-dive (§14)

Stored in `user.coach_controls`. Read via `GET /coach/clients/{id}/controls`, written via `POST /coach/clients/{id}/controls`. Findings:

| Control | Storage | Written by | Read by | Engine V2 uses it? | Verdict |
|---|---|---|---|---|---|
| **Programme flexibility** (Strict/Flexible) | `user.coach_controls.programme_flexibility` | Admin page | Only `[id].tsx` (display) | **NO** — grep of V2 engine code shows zero references | **DEAD CONFIG** |
| **Progression speed** (Cautious/Standard/Aggressive) | `user.coach_controls.progression_speed` | Admin page | Only `[id].tsx` | **NO** — V2 progression uses `progression_states` collection, not this field | **DEAD CONFIG** |
| **Injury caution level** (Low/Medium/High) | `user.coach_controls.injury_caution_level` | Admin page | Only `[id].tsx` | **NO** — V2 HOW uses `profile.injuries` directly | **DEAD CONFIG** |
| **Video touchpoint** (Weekly/Bi-weekly/Monthly) | `user.coach_controls.video_touchpoint_cadence` | Admin page | Only `[id].tsx` (unused message assistant loosely) | **NO** | **DEAD CONFIG** |
| **Auto-approval risk threshold** (None/Low/Low+Medium) | `user.coach_controls.auto_approval_risk` | Admin page | **`feature_v2_coach_publish.py`** references it in some paths | **PARTIAL** — hooks exist but never allow bypass of `KEY/IMPORTANT` exception gate | **DANGEROUS BY LABEL** — implies auto-publish; actual publish always goes through validation. Recommend REMOVE from UI to prevent coach expectation mismatch. |

**Recommendation**: Delete all five controls from the Admin page. If any single one is actually desired in the coaching product, port it to workspace `goals` tab as a first-class DNA field with real engine wiring. The current controls block is legacy misdirection.

## Executive verdict on Admin

**Total sections/controls audited**: 20.

**KEEP IN ADMIN (drawer)**:
- Assigned coach · Change
- Reset password
- Archive · Restore
- Delete (soft) · Permanent delete
- Manage Coaches shortcut

That's it — **6 truly administrative controls**.

**MOVE TO WORKSPACE**:
- Directives → Plan tab ribbon (already there — kill duplicate)
- Weekly script + Draft reply → Messages tab
- Habits → new `habits` tab OR merge into Progress
- Roster → Plan tab (already there — kill duplicate)
- Preview as this client → Clients page (already there — kill duplicate)

**REMOVE/LEGACY**:
- Live Signals card (V1 read; workspace `progress` supersedes)
- Programme Overview card ("No programme yet")
- Programme Timeline
- Week Plan (0 workouts)
- Coach Controls (5 dead fields)
- Profile summary duplicate
- Change Log duplicate

**NEEDS DECISION**:
- Habits — real system, no workspace home yet.

## P0 issues on Admin page

1. **Every programme-shaped field reads V1** and is empty for V2 clients → shows misleading "No programme yet" / "0 workouts" / adherence 0% for Pietro whose Live plan has 23 sessions.
2. **`Auto-approval risk threshold` control implies risk-based auto-publish** but real V2 publish always requires validation + resolved KEY/IMPORTANT exceptions. Coaches setting this expecting a shortcut will get inconsistent behaviour.
3. **Dead coach-controls block** persists user setting to a field no engine reads.
4. **Roster + Directives + Preview duplicated** between Admin and Workspace — coach can set the same directive in two places, one write path may be stale.
5. **Workspace ADMIN button** currently opens the entire Admin page (all sections). It should open a narrow drawer with only the 6 truly admin controls.
