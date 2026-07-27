# CrewFit V2 — Coach UX

Companion to `V2_ARCHITECTURE.md`. Defines the coach's workspace: what they see, what they touch, and what they never have to touch.

Design principle: **coach operates by exception**. Automation handles the 90%; coach approves the batch and reviews the 10%.

---

## 1. Coach top-level navigation

Bottom tabs (native mobile) / left rail (desktop):
- **Roster** — inbox of clients whose plans need attention
- **Clients** — full client list
- **Library** — exercises + templates + directives repository
- **Approvals** — cross-client approval queue (batch actions)
- **Content** — messages, scripts, video briefings
- **Insights** — automation metrics + programme health

The single most-used surface is per-client **ROSTER + PLAN**.

---

## 2. Coach Roster inbox (landing screen)

Shows every client with a state badge. Sorted by "needs your attention first".

```
┌──────────────────────────────────────────────────────────────┐
│ ROSTER — 4 clients need review                                │
├──────────────────────────────────────────────────────────────┤
│ ● Louis Hall     · Marathon (A) · 12 wks                     │
│   ⚠ 2 review · 1 conflict · Draft ready 3 min ago            │
├──────────────────────────────────────────────────────────────┤
│ ● Sarah Chen     · Muscle gain · Phase: Hypertrophy wk 3     │
│   ⚠ 1 review · new roster                                    │
├──────────────────────────────────────────────────────────────┤
│ ○ James Ward     · Fat loss                                  │
│   ✓ All ready — batch approve                                │
├──────────────────────────────────────────────────────────────┤
│ ○ Priya Singh    · 70.3 (A) · 18 wks                        │
│   ✓ All ready — batch approve                                │
└──────────────────────────────────────────────────────────────┘

State legend:
● red   = blocker exception (cannot promote)
● amber = warnings need review
○ green = all READY, one-tap approve
```

Filter chips at top: `All · Needs Review · Ready to Approve · No Roster · New Client`.

---

## 3. Client Roster + Plan workspace (the heart)

Landing when coach opens a client. Split view — desktop side-by-side, mobile toggled tabs.

### 3.1 Top ribbon

```
┌─────────────────────────────────────────────────────────────┐
│ Louis Hall                                              [•••]│
│ Marathon (A) · 12 wks · Phase: Build (wk 3 of 6)             │
│ Weight 0.7 · Secondary: General Strength (0.3)               │
│                                                              │
│ AUGUST 2026     ‹ July · August · September ›               │
│                                                              │
│ 27 Ready · 2 Review · 1 Conflict · 3 Coach Edited            │
│                                                              │
│ [ Tell CrewFit… ────────────────────────────────────── ]    │
│                                                              │
│ [ APPROVE 27 READY ]   [ Review 3 ]   [ New Directive ]      │
└─────────────────────────────────────────────────────────────┘
```

- **Programme summary line** — Goal + priority + timeline class + active phase (with week/total).
- **Month navigator** — click to jump; underline = current month.
- **Status counts** — one glance summary of the DRAFT state.
- **Command bar** — free text → structured proposal (§8).
- **Batch actions** — approve everything READY; jump straight to review.

### 3.2 Side-by-side rows

Each row = one date. Left = roster (real life), right = CrewFit plan.

```
┌────────────────────────────────────┬─────────────────────────────────┐
│ Mon 3 Aug · Home Day               │ Upper Strength · 45m · Home     │
│                                    │ Exposure #4 · Build wk 3        │
│                                    │ ✓ READY                          │
├────────────────────────────────────┼─────────────────────────────────┤
│ Tue 4 Aug · LHR→JFK · 07:00–16:30  │ Post-Flight Mobility · 15m       │
│ Duty 9.5h · 1 sector · Heavy       │ Recovery-first day               │
│                                    │ ✓ READY                          │
├────────────────────────────────────┼─────────────────────────────────┤
│ Wed 5 Aug · JFK Layover · 32h free │ Lower Strength · 40m · Hotel gym│
│                                    │ Exposure #4 · Build wk 3         │
│                                    │ ✓ READY                          │
├────────────────────────────────────┼─────────────────────────────────┤
│ Thu 6 Aug · JFK→LHR Overnight      │ ULR Recovery Protocol · 25m      │
│ Duty 14h · Extreme                 │ ⚠ Long run deferred (event risk) │
├────────────────────────────────────┼─────────────────────────────────┤
│ Fri 7 Aug · Home Day               │ Long Run · 22km · Outdoor        │
│                                    │ KEY · Marathon wk 3 · Exposure #6│
│                                    │ ⚠ Recovery gap 20h < 24h minimum │
├────────────────────────────────────┼─────────────────────────────────┤
│ Sat 8 Aug · Home Day               │ Easy Run · 8km + Strength Sup 20m│
│                                    │ ✓ READY                          │
├────────────────────────────────────┼─────────────────────────────────┤
│ Sun 9 Aug · Standby (home)         │ Mobility · 20m                   │
│                                    │ ✓ READY · client can execute     │
└────────────────────────────────────┴─────────────────────────────────┘
```

### 3.3 Roster cell information density

**Home day / off:**
```
Mon 3 Aug · Home Day
```

**Single-sector flight:**
```
Tue 4 Aug · LHR→JFK
Report 07:00 · Depart 08:30 · Arrive (local) 12:00
Duty finish 12:30 local · Duty 9.5h
```

**Multi-sector turnaround:**
```
Wed 5 Aug · LHR→AMS→LHR
Report 05:30 · 2 sectors · Finish 14:20
Duty 8.8h
```

**Layover full day:**
```
Wed 5 Aug · JFK Layover
32h free · Next report Thu 20:15 local
```

**Standby:**
```
Sun 9 Aug · Standby (home) 06:00–18:00
```

No backend labels ("Layover Full Day", "Turnaround Duty") shown to coach — they're derived and displayed as human copy.

### 3.4 Plan cell information density

```
[Objective] · [duration] · [location]
[Exposure #N · phase wk M] or [KEY badge]
[Status: READY / REVIEW / CONFLICT / EDITED / LOCKED]
```

Colour coding:
- ✓ READY → subtle green tick
- ⚠ REVIEW → amber flag
- ✕ CONFLICT / BLOCKED → red
- ✎ COACH EDITED → blue pencil
- 🔒 LOCKED → grey padlock

### 3.5 Per-row long-press / right-click actions

Contextual menu (tap the row's ••• or long-press):
```
Open workout
Edit workout
Regenerate this workout
Move to another day
Set equipment for this session
Add coach directive for this date
Lock
Approve just this one
See "Why?"
See history
```

Advanced/rarely used actions live behind "Advanced" submenu — not top-level.

---

## 4. Opening a workout

Tapping the plan cell opens the workout editor drawer.

```
┌────────────────────────────────────────────────────────┐
│ Upper Strength · Aug 3                       [Lock][✕] │
│ Home · 45m · Exposure #4 · Build wk 3 · Louis           │
├────────────────────────────────────────────────────────┤
│ WARMUP (5m)                                              │
│  · Arm circles · 30s                                     │
│  · Wall slides · 45s                                     │
├────────────────────────────────────────────────────────┤
│ MAIN                                                     │
│ 1. Barbell Bench Press          4 × 8   90s   RPE 7-8   │
│    Prev: 4 × 8 @ 60kg RPE 8   → suggest 62.5 kg          │
│ 2. Weighted Pull-up             4 × 6   120s  RPE 8     │
│    Prev: 4 × 6 @ +5kg RPE 8   → suggest +7.5 kg          │
│ 3. DB Row                        3 × 10 · 60s   RPE 7    │
│ 4. DB Overhead Press             3 × 8-10 · 60s · RPE 7  │
│ 5. Face Pull                     3 × 15 · 45s · RPE 7    │
│ 6. Plank                         3 × 45s                 │
├────────────────────────────────────────────────────────┤
│ COOLDOWN (5m)                                            │
│  · Chest doorway stretch · 60s each side                 │
├────────────────────────────────────────────────────────┤
│ Rationale                                                │
│ "Second upper exposure this window; keeping bench heavy  │
│  after Wednesday's heavy pull. Deload not yet needed."   │
│                                                          │
│ ▸ Progression context                                    │
│ ▸ Alternatives (Bodyweight · Hotel · Outdoors)          │
│ ▸ Decision log (12 records)                              │
├────────────────────────────────────────────────────────┤
│ [ Regenerate ]  [ Change equipment ]  [ Save ]  [ Approve ]│
└────────────────────────────────────────────────────────┘
```

**Editing inline:**
- Tap any set/rep/load → inline editor
- Tap exercise name → swap picker (filtered to eligible + approved)
- Add exercise → picker with same filter + explicit "override eligibility" toggle (rare)
- Delete exercise → confirmation with "keep slot empty?" or "drop this slot"

**Save behaviour:**
- Coach edit = stamps `coach_edited=true`, workout auto-locks
- Save without close → returns to same scroll position in the schedule
- Save + Approve → promotes just this workout to LIVE immediately

---

## 5. "Why?" tooltip

Every material decision has a reason. Tap the `Why?` link inside any workout or the ⚠ badge on any row:

```
Long Run · Aug 7 · 22 km
Why here?

- Programme requires 1 KEY long_run per week (marathon build wk 3).
- Aug 7 Friday scored highest opportunity (86) in the week:
    home day · 60+ min available · no next-day duty
- Aug 5 was originally proposed but recovery window 
  from JFK layover (32h) triggered a spacing rule
  (min 24h post-layover before KEY session).
- Distance 22 km follows the marathon build curve:
    week 3 of 16 → 22 km (target long run).
    Peak long-run planned for wk 12: 32 km.

Rule stack applied:
  Tier 5 · Programme objective (obligation)
  Tier 6 · Roster feasibility (opportunity ranking)
  Tier 7 · Readiness (band=normal)
```

Pulled directly from `DecisionRecord`s. No LLM generation at read time.

---

## 6. Exception review

Tap the top ribbon's "Review 3" or the ⚠ badge on a row:

```
┌───────────────────────────────────────────────────┐
│ Review — 3 items                          [Close] │
├───────────────────────────────────────────────────┤
│ 1. Recovery gap 20h < 24h (Long Run · Aug 7)     │
│    Trigger: heavy lower Wed → long run Fri        │
│    ⓘ Suggested: move long_run to Sat 8 Aug        │
│    [Accept]   [Ignore]   [Edit]                   │
├───────────────────────────────────────────────────┤
│ 2. Event session unscheduled (Long Run Aug 10)   │
│    Trigger: no feasible day found                 │
│    ⓘ Suggested: extend planning window +2 days    │
│    [Accept]   [Ignore]   [Edit]                   │
├───────────────────────────────────────────────────┤
│ 3. Multi-A conflict (Marathon Nov + 10K Oct)     │
│    Trigger: two priority-A events 21 days apart   │
│    ⓘ Suggested: demote 10K to priority B          │
│    [Accept]   [Reject]   [Change goal]           │
└───────────────────────────────────────────────────┘
```

Each item = an `exceptions` doc with proposed_resolutions. One-click accept applies the ChangeSet.

---

## 7. Command bar (natural language → proposed changes)

Coach types free text. AI intent parser converts to a structured proposal, which coach previews before applying.

**Examples the system handles:**

Input:
```
Move his long run to Saturday and make Friday recovery
```
Proposal:
```
CREWFIT PROPOSES

- Move Long Run · Aug 7 → Aug 8 (Saturday)
- Convert Fri Aug 7 → Recovery Walk 30m
- Reason: coach directive, retain KEY exposure #6

[Preview changes]   [Apply]   [Discard]
```

Input:
```
Keep this week lighter — he flew Sat and Sun back to back
```
Proposal:
```
CREWFIT PROPOSES

- Cut Upper Strength Aug 3 to 30m (from 45m)
- Cut Lower Strength Aug 5 to 30m
- Convert Aug 9 Mobility → Recovery Walk
- Add coach directive: "Reduce load this week; back-to-back long-haul"
  scope: Aug 3–9

[Apply]   [Discard]
```

Input:
```
No lower body training until Wednesday next week
```
Proposal:
```
CREWFIT PROPOSES

- Create coach directive:
  kind: avoid_movement
  scope: Aug 4–11
  parameters: {movement_pattern: "squat", "hinge", "lunge"}
- Auto-replace Lower Strength Aug 5 → Upper Hypertrophy variant
- Long Run Fri Aug 7 unaffected (running is aerobic not "lower training")

[Apply]   [Discard]
```

Input:
```
Give him three strength sessions across the next four home days
```
Proposal:
```
CREWFIT PROPOSES

- Distribute: Upper Strength Aug 3, Lower Strength Aug 5, Full-Body Strength Aug 9
- Keep Fri Aug 7 as Long Run (KEY session preserved)
- Confidence: high

[Apply]   [Discard]
```

**Never auto-applies.** Coach reviews and clicks Apply.

---

## 8. Batch approval flow

Green "APPROVE 27 READY" button in ribbon:

```
┌──────────────────────────────────────────────────┐
│ Approve 27 READY workouts                        │
├──────────────────────────────────────────────────┤
│ Scope:                                            │
│  ▸ Aug 3–31 (August plan)                        │
│  ▸ 27 workouts marked READY                       │
│  ▸ 3 remain in Review (not affected)              │
│                                                   │
│ Publishes as: August Plan v3                      │
│  Previous version: v2 (published Jul 25)          │
│                                                   │
│ Include reasoning summary for client? [Yes / No]  │
│                                                   │
│ [ Confirm approve 27 ]   [ Cancel ]              │
└──────────────────────────────────────────────────┘
```

On confirm:
1. Snapshot current LIVE version
2. Copy 27 READY items into new snapshot
3. Update pointer `programmes.live_plan_version = v3`
4. Fire `PlanApproved(v3, scope)` event
5. Client sees updates on next poll (typically < 15 s)

If any item has a `blocker` exception, it's excluded from the batch and remains in Review.

---

## 9. Approvals cross-client queue

Left-nav tab. Shows every client with ≥1 READY item and no coach action pending.

```
Approvals — Wednesday 27 July

Louis Hall         · August · 27 ready       [ Review · Approve ]
Sarah Chen         · August · 14 ready       [ Review · Approve ]
James Ward         · August · 22 ready       [ Review · Approve ]
Priya Singh        · August · 25 ready       [ Review · Approve ]

Bulk actions:
[ Approve all ready across all clients (88 items) ]
```

Bulk approve requires a confirmation modal listing every affected client + total item count.

---

## 10. Programme-level view

Second tab within a client's workspace: **Programme**.

```
Programme · Louis Hall
─────────────────────
Primary goal: Marathon (A) · Nov 8 · 12 weeks out
Timeline class: Standard (12wk vs 16wk ideal)

Secondary goal: General Strength (0.3 weight)

Phase: Build · week 3 of 6
  Entry criteria (all met): ✓ 3wk foundation complete · ✓ adherence 78%
  Exit criteria: Timeline 6wk in phase · Performance long_run at 28km
  
Weekly window · rolling 7-day (Aug 3–9)
  Objectives:
    Long Run            1 / 1 · complete ✓
    Tempo Run           0 / 1 · Fri Aug 7 · KEY · READY
    Easy Run × 2        1 / 2 · Sat scheduled
    Upper Strength      1 / 1 · Mon complete ✓
    Lower Strength      1 / 1 · Wed complete ✓
    Mobility            2 / 2 · complete ✓

Event countdown
  Nov 8 Marathon (A) · 96 days · 14 weeks
  Peak long_run wk 12 · 32 km · Sun Oct 25
  Taper begins Oct 25

Active coach directives (2)
  ▸ "Cut lower volume this week" · until Aug 11
  ▸ "Prefer home workouts Mondays" · persistent
  
Recent exceptions resolved (5) · Show
```

This is the strategic view — pure summary, not editable inline.

---

## 11. Directives view

Third client tab: **Directives**. Every active or historical coach directive:

```
Active
─────
Aug 4 – Aug 11 · avoid_movement · squat, hinge, lunge
   ["No lower body training until Wednesday next week"]
   [ Edit ] [ Revoke early ]

Persistent · since Jun 12 · prefer_home_workouts (Mondays)
   [ Edit ] [ Revoke ]

Recent (last 30 days)
─────
Revoked Jul 18 · deload_this_week · Jul 15–21
Expired Jul 8 · avoid_movement · high_impact_run · Jul 1–7
```

Add directive button opens either the structured form OR the command bar with intent parser.

---

## 12. History + versions

Fourth tab: **History**. Shows plan versions, coach edits, client changes.

```
Aug plan · v3 · published Wed 27 Jul 10:14 by Louis
   diff vs v2: 8 assignments modified · 3 new · 0 removed
   [ View diff ] [ Revert to v2 ]

Aug plan · v2 · published Mon 25 Jul 08:02 by Louis
   diff vs v1: 22 assignments modified

Aug plan · v1 · published Sun 24 Jul 17:30 by Louis
   Initial publish after roster confirm
```

Every version is retrievable and viewable. Reverting to v2 creates v4 as a copy of v2 (never destructive).

---

## 13. Coach settings per client

Fifth tab: **Settings**. Rarely visited. Contains:
- Auto-approve preferences per objective_kind (opt-in to skip coach review for low-risk objectives)
- SafeAdaptationBoundary defaults for this client
- Notification preferences (draft ready alerts, exception alerts)
- Sharing settings (secondary coach access)

---

## 14. Automation dashboard (coach-level)

`Insights` top-level tab (cross-client). Metrics from §34 architecture:

```
Automation performance (last 30 days)
─────────────────────────────────────
Roster upload → Draft ready              p50 32s · p95 51s
LLM calls per plan draft                  avg 3.2 · target < 5
% READY without coach edit                87%
% workouts client-adapted within SAB      94%
Coach edits per client per week           avg 2.4

Time spent per client per week
  Approving batches                       9 min
  Reviewing exceptions                    6 min
  Direct edits                            4 min
  Total                                   19 min

Plan quality
  Objective completion rate               91%
  Missed KEY sessions                     3
  Adherence trend                         +2.3%
```

This is the "am I actually saving coach time?" screen. Tracks whether V2 is achieving the reduced-workload goal.

---

## 15. Interaction rules

- **Two clicks max** for any common action (approve, review, apply directive)
- **Contextual actions live on the row**, not in global menus
- **Advanced controls behind •••**
- **Undo available for 60s** on any coach action (soft undo via ChangeSet reversal)
- **No modal dialogs for common flows** — inline expanded rows instead
- **Every AI-authored piece of text has an "AI-authored" glyph** so coach knows what to eyeball; coach-edited text loses the glyph
- **Never show backend labels** ("LayoverFullDay") — always human copy
- **Never show "AI", "bot", "generated", "algorithm"** in client-visible text; internally allowed on coach dashboard
- **Command bar accepts sentences OR fragments** — "long run Friday" is enough

---

## 16. Empty states + first-time coach flow

**New client, no goal set:**
```
Louis Hall
No goal yet.

[ Set goal ]   [ Import from V1 ]
```

**Goal set, no roster:**
```
Louis Hall · Marathon (A) · Nov 8

Plan without roster is available.
CrewFit is using default availability (Mon/Wed/Fri/Sat).

[ Add roster ]   [ View default plan ]
```

**Roster uploaded, draft building:**
```
Louis Hall · August roster confirmed

Building draft… 12 of 31 days ready

[ View progress ]   [ Live status ]
```

Coach can browse the ready portion while remaining days finish.

---

## 17. Roster upload from coach

Existing Iter 109 pattern preserved and extended:
- One-tap UPLOAD ROSTER on client page
- File picker → PDF/image
- Preview screen shows extracted days with confidence scores
- Coach can correct any low-confidence day inline (day_type, hotel_id, layover city)
- Confirm → Stage 5 pipeline fires
- Notice ribbon shows "Draft building — 30-60s"

---

## 18. Coach hotel notes (retained but demoted)

Hotel database is NOT part of the training path in V2 (per architecture §19).
Coach can still leave hotel notes as **coach-facing annotations** on any client (e.g. "In Marriott SG use free-weights, machines here are broken"). These are just free-text notes on the client profile, not machine-consumed.

If coach wants that note to affect training: convert it into a `coach_directive` (which IS machine-consumed). The UI offers one-tap "Turn this note into a directive".

---

## 19. Onboarding tour for coach V2

First time a coach opens the V2 dashboard, three-step tour:
1. "This is your ROSTER inbox. It shows clients who need you first."
2. "Inside a client, work top-to-bottom: ribbon summary → command bar → review list → approve."
3. "Everything CrewFit does, you can override. Locks protect your edits forever."

Skippable. Coach settings has "Show tour again".

---

**End of coach UX document.**
