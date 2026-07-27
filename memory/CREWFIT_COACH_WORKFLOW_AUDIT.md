# CrewFit Coach — Workflow Audit

**Version:** Iter 111 · 2026-07-27
**Companion to:** `CREWFIT_COACH_DASHBOARD_CURRENT_STATE_AUDIT.md` · `CREWFIT_COACH_DASHBOARD_V2_GAP_MAP.md` · `CREWFIT_COACH_DASHBOARD_V2_OPERATING_MODEL.md`

**Purpose:** For each real workflow the coach actually performs, trace it end-to-end on today's V1 UI. Count clicks, tabs, latency and friction. Show where V2 collapses the flow.

---

## 0. Reading this document

Every workflow section has four fields:

- **Trigger** — what starts it
- **V1 path (today)** — literal click-by-click trace
- **Friction** — the specific cognitive or UX cost
- **V2 target path** — what the flow becomes after `P11 Coach Dashboard V2`

Click counts are conservative estimates from the current codebase (`/app/frontend/app/(coach)/*.tsx` and `/app/frontend/app/coach/**/*.tsx`).

---

## 1. Morning triage — "what needs me today?"

**Trigger:** Louis opens the app.

**V1 path (today):**
1. Land on `(coach)/overview` — activity feed
2. Open `(coach)/approvals` — read pending roster-generated tasks
3. Open `(coach)/checkins` — scan new check-ins
4. Open `(coach)/messages` — scan new messages
5. For each flagged client: open `/coach/client/[id]` → decide what to do
6. If a client changed something: open their `overview` tab → scroll → hop into `programme` or `roster` tab

**Click / tab count:** ~12-25 depending on flagged-client count. **Time:** 8-15 min.

**Friction:**
- No single queue — coach has to visit 3 tabs to see the full picture
- Age of the oldest un-handled item is not visible anywhere
- Approvals nav is roster-centric, not workout-centric — coach misses individual workouts needing eyes
- Overview scrolls chronologically; latest changes bury older un-handled items

**V2 target path:**
1. Land on Attention Panel — one queue
2. Filter or scroll — every row has kind, severity, age, one-line reason
3. Batch-approve or one-click resolve inline

**Target clicks:** 3-8. **Target time:** 2-4 min.

---

## 2. A client uploads a new roster

**Trigger:** Push/badge indicates a new roster arrived (or coach uploads on their behalf via Iter 109 button).

**V1 path (today):**
1. Coach opens `/coach/client/[id]`
2. Overview → sees "roster uploaded"
3. Opens `roster` tab → scrolls new days
4. Opens `programme` tab OR `client-months` page → waits for `_generate_month` job to finish (p50 60-90s, p95 3-5 min)
5. When ready → opens each affected workout → reviews → approves
6. If a chunk fails → coach must know to re-trigger regeneration manually
7. Coach may need to re-open notes tab to nudge context and regenerate again

**Click / tab count:** ~15-40 per roster confirm. **Time:** 5-15 min of coach attention (spread over minutes of wait).

**Friction:**
- No preview of the plan **before** confirmation
- No incremental replan — every full-month rebuild
- No template cache — identical weeks rebuild from LLM every time
- Coach polls at 2s intervals; frontend can't stream partial results
- Coach must re-read the roster to guess what changed relative to previous version

**V2 target path:**
1. New roster arrives → P4 builds ScheduleDays automatically
2. P5+P6 build an incremental DRAFT (only affected days) in ≤60 s
3. Attention Panel shows: "Roster changed · 3 days affected · DRAFT ready"
4. Coach opens Roster+Plan workspace → sees DRAFT delta highlighted → command bar available for tweaks → batch approves

**Target clicks:** 4-8. **Target time:** 2-5 min.

---

## 3. Reviewing an LLM-produced workout for the first time

**Trigger:** Coach opens the client's programme.

**V1 path (today):**
1. `/coach/client/[id]` → `programme` tab OR `workouts` tab
2. Sees list of workouts — no filter by "needs review"
3. Clicks a workout → `/coach/workout/edit/[wid]` opens full editor
4. Reads the exercise list — no rationale visible
5. Coach opens `notes` tab in a separate hop if they need to check goal/preferences
6. Decides: edit / regenerate / approve / lock
7. Clicks Approve → `needs_coach_review=false`
8. Clicks Lock (optional) → `coach_locked=true`

**Click / tab count:** ~8-15 per workout. **Time:** 2-5 min per workout.

**Friction:**
- No "Why this?" — coach has to infer the rationale from goal + phase + exercise list
- Editor is a full-page nav away; loses roster context
- No batch approve
- No filter by "needs review" on the workouts tab

**V2 target path:**
1. Attention Panel row: "3 KEY workouts need review"
2. Multi-select → batch approve
3. For any workout, click "Why this?" → DecisionRecord chain drawer (rule id, confidence, previous state)
4. Edit inline in a drawer on the same page

**Target clicks:** 2-3 per approved workout · 4-6 per edited workout.

---

## 4. Client reports pain in a check-in

**Trigger:** Client submits a check-in mentioning knee pain.

**V1 path (today):**
1. `(coach)/checkins` list → click the check-in
2. `/coach/checkin/[id]` opens with free-text and scores
3. Coach reads → identifies pain region
4. Nav to `/coach/client/[id]` → `notes` tab → adds pain to `cautions` free-text
5. Nav to `programme` tab → triggers full-month regeneration (so LLM Rule 5b avoids knee patterns)
6. Waits for regeneration
7. Reviews affected workouts

**Click / tab count:** ~10-15. **Time:** 5-10 min plus regen wait.

**Friction:**
- Pain is captured as free-text in one place, but the deterministic plan gate is spread across a separate rule engine.
- Coach must remember to trigger regeneration explicitly.
- No structured directive — future coach's-eyes-view can't easily list active cautions.

**V2 target path:**
1. Attention Panel row (auto-generated): "Client X · pain flag: knee (from check-in)"
2. Coach clicks "Add directive" → structured `coach_directives(kind=avoid_movement, parameters={pattern:'deep_squat'})`
3. P5 auto-recomputes ONLY affected assignments within the SAB rules
4. DRAFT delta ready → batch approve

**Target clicks:** 3-5. Regeneration is incremental and background.

---

## 5. Client wants to swap an exercise

**Trigger:** Client messages "can I swap barbell squat for goblet squat this week?"

**V1 path (today):**
1. `(coach)/messages` → read the request
2. Nav to `/coach/client/[id]` → programme tab → find the workout
3. `/coach/workout/edit/[wid]` → find the exercise in the list → replace it
4. Save → reply to the client in messages

**Click / tab count:** ~8-12. **Time:** 3-8 min.

**Friction:**
- Two round-trips through separate screens
- Every swap loses history (no audit of "coach honoured this request")
- Client can't do this themselves

**V2 target path:**
- If SAB permits → **client does it themselves** (P7 adapt endpoint). Coach never sees it.
- If SAB blocked → Attention Panel row: "Client X requested exercise swap on {date}"; coach clicks "Approve" → applied automatically.

**Target clicks:** 0 (SAB-permitted) or 1-2 (escalated).

---

## 6. Adding a new client's programme from scratch

**Trigger:** A new client finishes DNA / onboarding.

**V1 path (today):**
1. `(coach)/clients` → find the new client → open profile
2. `notes` tab → set goal_override, cautions, weekly_shape, preferences (5 free-text fields)
3. `programme` tab → verify goal detected
4. If a race event is entered → coach adds an event via `/coach/client/[id]` (implementation varies by event category feature)
5. Confirm the roster (if uploaded)
6. Wait for `_generate_month` → review each workout → approve

**Click / tab count:** ~15-30. **Time:** 15-25 min.

**Friction:**
- Goal is a free-text `main_goal_key` field, not a first-class object
- Coach notes are 5 buckets of unstructured text
- No timeline classification is shown ("this goal is compressed / high_risk")
- Events → discipline mapping is inferred, not explicit

**V2 target path:**
1. Coach opens client → sees onboarding intake pre-mapped to a `goals[]` primary goal + timeline_class banner ("compressed — 8 weeks to a marathon")
2. Coach adjusts weight / priority if needed → programme built automatically (phase machine picks the sequence)
3. Coach reviews the auto-built Attention Panel items and approves

**Target clicks:** 4-8 for a straightforward client.

---

## 7. Adjusting a phase transition

**Trigger:** Coach knows client's foundation phase should extend by 1 week (their week has been hard).

**V1 path (today):**
1. `/coach/client/[id]` → programme tab
2. Read what "phase" the plan is in (modulo 4-week bucket + heuristics)
3. Add a note in `weekly_shape` → save
4. Trigger a regenerate → wait
5. Re-check that next 7 days shifted

**Click / tab count:** ~6-10. **Time:** 3-5 min + regen wait.

**Friction:**
- Phase is not an editable entity — coach can only nudge via free-text notes
- No visibility of when the phase is scheduled to change
- No structured "extend phase by 1 week" control

**V2 target path:**
1. Client workspace → phase strip at top (per `programme_phases`)
2. Coach clicks current phase → "Extend by 1 week" → DecisionRecord written, DRAFT delta produced
3. Coach approves

**Target clicks:** 3.

---

## 8. Missing a KEY session

**Trigger:** Client didn't complete Tuesday's key strength session (marked missed).

**V1 path (today):**
1. `/coach/client/[id]` → overview shows adherence dropped
2. Coach must open workouts tab → find the missed session → decide whether to re-schedule this week or absorb into next
3. If reschedule → coach edits the date directly → saves
4. Adherence updates on next check-in aggregation cycle

**Click / tab count:** ~7-12. **Time:** 4-8 min.

**Friction:**
- No automatic cascade proposal — coach must invent the fix
- Progression memory not visible (would the next KEY session be too heavy given the missed exposure? unclear)

**V2 target path:**
1. Attention Panel row (auto): "Client X · missed KEY upper_strength (Tuesday). Proposed: re-place Thursday, shift Thursday's easy_run to Friday."
2. Coach clicks "Apply proposal" → DRAFT delta ready → approve

**Target clicks:** 2.

---

## 9. Regenerating a whole month because coach notes changed

**Trigger:** Coach updates `weekly_shape` note in `/coach/client/[id]` → notes tab.

**V1 path (today):**
1. Save note (implicit trigger)
2. Next roster confirmation triggers full-month regeneration (Iter 108 behaviour)
3. All non-locked workouts rebuild
4. Coach must re-review each workout

**Click / tab count:** ~10-30 (per re-review workout). **Time:** 10-25 min.

**Friction:**
- Full-month regen instead of impact-limited replan
- Coach must re-review every workout to trust it

**V2 target path:**
1. Note becomes a `coach_directive` on save
2. P3 (demand engine) evaluates whether the directive touches active phase priorities
3. If yes → incremental replan of affected windows only
4. Attention Panel: "Directive applied · N assignments touched · DRAFT delta ready"
5. Coach reviews delta only

**Target clicks:** 2-5.

---

## 10. Reviewing decision provenance ("Why is this workout on Tuesday?")

**Trigger:** Coach questions why a specific day has a specific session.

**V1 path (today):**
1. Coach must reconstruct the reasoning from:
   - `main_goal_key` on user profile
   - Latest active event + priority
   - Current phase (bucketed by modulo 4)
   - Coach notes free-text
   - The workout's `focus` and `source` fields
2. No single place shows the causal chain

**Click / tab count:** ~10-15 across 4-5 tabs.

**Friction:**
- Coach doesn't trust the plan when they can't explain it
- Time spent on this is pure overhead

**V2 target path:**
1. Coach clicks any assignment → "Why this?" drawer
2. Chain of DecisionRecords rendered oldest→newest: goal → phase → objective → assignment → implementation
3. Every entry has a human_readable_reason field
4. Coach reads and moves on in seconds

**Target clicks:** 2.

---

## 11. Cross-client portfolio management

**Trigger:** Louis wants to know: which of my 30 clients are at risk this week?

**V1 path (today):**
1. `(coach)/clients` → scroll list → open each in turn
2. Adherence + RPE badges vary by tab
3. No sort by "risk"
4. No "quiet" state visible

**Click / tab count:** ~30-60 (linear scan). **Time:** 15-30 min.

**Friction:**
- Everything is per-client
- No portfolio scorecard

**V2 target path:**
1. `(coach)/clients` shows a scorecard: name · timeline_class · adherence trend · attention items · next KEY date
2. Sort by any column
3. Filter: "unread ≥24h", "adherence <70%", "event within 4 weeks"

**Target clicks:** 1-3 to identify at-risk clients.

---

## 12. Publishing preview before it goes live

**Trigger:** Coach wants to see the next 4 weeks before the client does.

**V1 path (today):** **Not possible.** Every LLM output is client-visible immediately. Coach's only knob is `coach_locked`, which is per-workout.

**V2 target path:**
1. Coach opens Roster+Plan workspace → DRAFT column always shows the next-scope plan
2. Client sees LIVE (`plan_versions.live_plan_version`)
3. Coach reviews DRAFT → approves scopes → new PlanVersion published → client sees it

Publication is deliberate, not incidental.

---

## 13. Reverting a bad plan

**Trigger:** Coach discovers Monday's plan is wrong (e.g. included a KEY session on a duty day due to a stale roster).

**V1 path (today):**
1. Coach opens each affected workout → edits back
2. Or coach regenerates the month → hopes the roster is right this time
3. History of what changed is not queryable — no version snapshots

**Click / tab count:** ~15-30. **Time:** 10-20 min.

**Friction:**
- No revert — only forward edits
- No ability to see prior state cleanly

**V2 target path:**
1. Coach opens client workspace → History tab → last 5 PlanVersions listed with published_at + approval scope
2. Click prior version → "Revert to this" → new PlanVersion created from old snapshot; previous versions retained
3. Client's LIVE updates within 15 s

**Target clicks:** 2.

---

## 14. Handling a client's equipment change

**Trigger:** Client messages "I'm in a hotel this week — only bodyweight."

**V1 path (today):**
1. `(coach)/messages` → read
2. Coach nav to `/coach/client/[id]` → find each affected day
3. Manually edit each workout to bodyweight versions
4. Reply to client

**Click / tab count:** ~10-20. **Time:** 5-12 min.

**Friction:**
- Client can't declare this themselves
- Coach has to think through movement pattern substitutions per exercise

**V2 target path:**
- Client uses "Change equipment" chip in their app → within SAB → auto-adapted with green-variant workout; coach never notified except in the "informational" tab of Attention Panel.
- If SAB exceeded → escalated → coach one-click accept.

**Target clicks (coach):** 0-1.

---

## 15. Cohort of coach workflows summarised

| Workflow | V1 clicks | V1 time | V2 clicks | V2 time |
|---|---:|---:|---:|---:|
| Morning triage | 12-25 | 8-15 min | 3-8 | 2-4 min |
| Roster upload → published | 15-40 | 5-15 min | 4-8 | 2-5 min |
| Review one workout | 8-15 | 2-5 min | 2-3 | <1 min |
| Handle pain from check-in | 10-15 | 5-10 min | 3-5 | 2-3 min |
| Client requests exercise swap | 8-12 | 3-8 min | 0-2 | 0-1 min |
| Onboard new client | 15-30 | 15-25 min | 4-8 | 6-10 min |
| Extend a phase | 6-10 | 3-5 min | 3 | 1 min |
| Missed KEY session | 7-12 | 4-8 min | 2 | 30 s |
| Regen after notes change | 10-30 | 10-25 min | 2-5 | 2-4 min |
| "Why this?" investigation | 10-15 | 3-8 min | 2 | 30 s |
| Portfolio scan (30 clients) | 30-60 | 15-30 min | 1-3 | 3-5 min |
| Publish preview | not possible | — | native | — |
| Revert bad plan | 15-30 | 10-20 min | 2 | <1 min |
| Client hotel-only week | 10-20 | 5-12 min | 0-1 | 0-1 min |

**Total per-client per-week estimate:** V1 ~50 min → V2 ~20 min (per V2 architecture success metric).

---

## 16. Highest-friction pinch points to eliminate first

Ranked by expected coach-time savings:

1. **No cross-client attention queue** → Attention Panel · P1+P11
2. **Full-month regen bottleneck** → Incremental replan · P5+P6
3. **No DRAFT** — nothing to review before it hits client · P1 (backend done) + P11 UI
4. **11-tab client profile forcing tab-hopping** · P11
5. **No "Why this?" chain** — coach can't trust the plan · P1 (backend done) + P11 UI
6. **Client can't adapt within SAB** → shifts coach load · P7 (backend done) + client UI
7. **Free-text coach notes** — no structured directives · P10 (backend done) + P11 UI
8. **Roster upload → published latency (90+ s)** · P4-P6 incremental + template cache
9. **No revert** — coach lives in fear of pressing regenerate · P1 (backend done) + P11 UI
10. **No portfolio scorecard** — coach scans 30 clients linearly · P11

Backend for items 1, 3, 5, 6, 7, 9 is already shipped through P1–P10 + P12. The remaining lift is P11 (Coach Dashboard V2) + a modest amount of client-side adaptation UI.

---

**End of workflow audit.**
