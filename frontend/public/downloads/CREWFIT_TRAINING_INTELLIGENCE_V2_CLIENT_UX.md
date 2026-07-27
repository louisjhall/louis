# CrewFit V2 — Client UX

Companion to `V2_ARCHITECTURE.md`. Defines the client's experience: simple, fast, honest, always usable.

Design principle: **the client should never have to know how the system works.** Open app → see today → train.

---

## 1. Client top-level navigation

Bottom tabs (5, max):
- **Today** — today's session, quick actions
- **Plan** — upcoming 7 days from LIVE plan
- **Progress** — completed sessions, PRs, weekly windows
- **Nutrition** — (unchanged from V1)
- **Profile** — settings, goals, roster, coach

The Today tab is the default landing.

---

## 2. Today screen

The most important screen in the app.

```
┌───────────────────────────────────────┐
│ TODAY · Wed 5 Aug                    │
│                                       │
│ ┌───────────────────────────────────┐ │
│ │  Lower Strength                   │ │
│ │  40 min · Hotel Gym               │ │
│ │  Exposure #4 · Marathon build     │ │
│ │                                    │ │
│ │  [ START ]                         │ │
│ │  [ Change equipment ]              │ │
│ │  [ Today's Reality ]               │ │
│ └───────────────────────────────────┘ │
│                                       │
│ Roster: JFK Layover · 32h free       │
│                                       │
│ Habits · 3 of 5 today                 │
│  ○ 8 000 steps                        │
│  ✓ Water · 2.5 L                     │
│  ✓ Sleep · 8h logged                  │
│  ○ Weekly check-in                    │
│  ○ Protein target                     │
│                                       │
│ [ Coach message from Louis ]          │
└───────────────────────────────────────┘
```

Key rules for this card:
- **One workout maximum** per day at the top
- Duration + location are the two most important pieces of info
- KEY badge appears in colour if this is a race-critical session
- Objective sequence ("Exposure #4") shown small — reassures returning client
- **No progress bars, no charts on Today.** Progress lives in Plan/Progress.

---

## 3. Workout card details (before Start)

Tap the workout card:
```
┌───────────────────────────────────────┐
│ Lower Strength · 40 min             ✕│
│ Hotel Gym · Exposure #4                │
├───────────────────────────────────────┤
│ 5-min warmup                           │
│  · Bodyweight squat · 60s              │
│  · Hip flexor stretch · 45s each        │
│                                        │
│ Main session · 30m                     │
│  1. Trap-bar Deadlift        4×6      │
│  2. Bulgarian Split Squat    3×8 e/s  │
│  3. Leg Press                3×10     │
│  4. Kettlebell Swing         3×15     │
│  5. Plank                    3×45s    │
│                                        │
│ 5-min cooldown                         │
│  · Foam roll quads · 60s               │
│  · Couch stretch · 45s each             │
│                                        │
│ Why this?                              │
│ "Second lower exposure this week…"    │
├───────────────────────────────────────┤
│ [ START ]                              │
│ [ Change equipment ]  [ Reality ]     │
└───────────────────────────────────────┘
```

- Exercises list without loads by default (loads shown inside execution)
- "Why this?" tap opens a Louis-voiced explanation (from DecisionRecord)
- No LLM-buzzwords ("AI-generated") anywhere

---

## 4. Change Equipment flow (< 20 seconds target)

Tap **Change equipment** on the workout card:

```
Screen 1 — quick chip picker
┌───────────────────────────────────────┐
│ Where are you training?           ✕  │
│                                       │
│  [ Bodyweight ]                       │
│  [ Full Gym ]                         │
│  [ Limited Gym ]                      │
│  [ Dumbbells only ]                   │
│  [ Outdoors ]                         │
│  [ Pool ]                             │
│  [ Something else ]                   │
└───────────────────────────────────────┘
```

If **Full Gym** or **Limited Gym** chosen:
```
Screen 2 — multi-select equipment
┌───────────────────────────────────────┐
│ What's here?                      ✕  │
│                                       │
│  ☑ Dumbbells                          │
│  ☑ Adjustable bench                   │
│  ☑ Cable machine                      │
│  ☐ Smith machine                      │
│  ☐ Barbell / rack                     │
│  ☑ Treadmill                          │
│  ☐ Bike                                │
│  ☑ Floor space                         │
│                                       │
│  Dumbbells go up to?                  │
│  ○ 15 kg  ● 20 kg  ○ 25 kg  ○ 30 kg+ │
│  ○ Not sure                           │
│                                       │
│  [ ADAPT WORKOUT ]                    │
└───────────────────────────────────────┘
```

Result:
```
┌───────────────────────────────────────┐
│ Adapting your session…               │
│  ●●●○○○                                │
└───────────────────────────────────────┘
```

Then the new workout appears in the same card format. Same objective, new implementation.

Total taps: 1 (open) + 1 (pick "Limited Gym") + N (select boxes) + 1 (adapt) → ~5 taps.

Target latency < 5 seconds. Progress indicator shown; if longer than 8s, "Louis is picking exercises…" copy appears.

---

## 5. Today's Reality flow

Tap **Today's Reality**:

```
┌───────────────────────────────────────┐
│ Today's Reality                    ✕ │
│ What's changed?                        │
│                                       │
│  [ Tired ]              [ 20 min ]    │
│  [ No gym ]             [ Called ]    │
│  [ Feeling great ]      [ Sore knee ] │
│  [ Bad weather ]        [ Other… ]    │
└───────────────────────────────────────┘
```

Tap a chip → structured resolver runs. If it resolves within Safe Adaptation Boundary:
```
Louis suggests

- Cut session to 25 minutes
- Same movement pattern, fewer sets
- Keep exposure sequence intact

[ Accept ]   [ Do it anyway ]   [ Ask coach ]
```

Accept → adapt in place, back to Today. **Under 3 seconds.**

If chip doesn't fit → falls back to LLM (V1 REALITY_SYSTEM), shows A/B/C options (V1 unchanged).

"Ask coach" → creates a `change_sets` doc requesting coach review; today's session stays as planned in the meantime with a "waiting on coach" badge.

---

## 6. During workout (execution screen)

Once client taps START:
```
┌───────────────────────────────────────┐
│ Lower Strength · Exercise 1 of 5     │
│                                       │
│ Trap-bar Deadlift                    │
│ 4 × 6 · 90 sec rest                   │
│ Louis says: RPE 7-8, stay square       │
│                                       │
│ Prev: 4 × 6 @ 80 kg · RPE 8            │
│ Try: 82.5 kg                          │
│                                       │
│ Set 1:  [80 kg]  [6 reps]  ▸ Done     │
│ Set 2:  [80 kg]  [6 reps]  ▸ Done     │
│ Set 3:  [ ]      [ ]                   │
│ Set 4:  [ ]      [ ]                   │
│                                       │
│ [ Skip exercise ]  [ Swap ]           │
│ [ Video ]  [ Coaching cues ]          │
└───────────────────────────────────────┘
```

- Client logs actual load + reps per set
- Timer between sets auto-starts on Done
- "Try:" suggestion is from progression engine
- Swap → filtered picker (same slot, same eligibility)
- Skip exercise → confirmation; PerformanceRecord captures the skip
- Coaching cues → expandable inline (never a modal)

---

## 7. Post-workout capture

After last exercise:
```
┌───────────────────────────────────────┐
│ Session complete                       │
│                                       │
│ Overall RPE                            │
│  1 · 2 · 3 · 4 · 5 · 6 · 7 · 8 · 9 · 10│
│                          ─▲            │
│                                       │
│ Perceived difficulty                   │
│  Too easy · Right · Bit tough · Hard   │
│                        ─▲              │
│                                       │
│ Notes (optional)                       │
│  [_________________________________]  │
│                                       │
│ [ Save session ]                       │
└───────────────────────────────────────┘
```

Saves to `performance_records`. Fires `WorkoutCompleted` event → progression state updates.

If this was the last session of the planning window, progression snapshot writes and next window's demand computes automatically.

---

## 8. Plan tab — upcoming 7 days

```
┌───────────────────────────────────────┐
│ PLAN — next 7 days                   │
│                                       │
│ Thu 6 Aug · Overnight to LHR         │
│  ULR Recovery · 25m                    │
│                                       │
│ Fri 7 Aug · Home                      │
│  Long Run · 22 km · KEY 🔴             │
│                                       │
│ Sat 8 Aug · Home                      │
│  Easy Run + Strength Support · 60m    │
│                                       │
│ Sun 9 Aug · Standby (home)            │
│  Mobility · 20m · Optional             │
│                                       │
│ Mon 10 Aug · Home                     │
│  Upper Strength · 45m                 │
│                                       │
│ Tue 11 Aug · JFK→LHR                  │
│  Post-Flight Mobility · 15m           │
│                                       │
│ Wed 12 Aug · Home                     │
│  Lower Strength · 40m                 │
└───────────────────────────────────────┘
```

Tap any day → same workout card as Today.

Client can:
- View upcoming
- **Cannot** edit upcoming (only Today is editable via Reality/Change Equipment)
- **Cannot** see DRAFT — only LIVE

---

## 9. Progress tab

Simple, non-technical language:
```
┌───────────────────────────────────────┐
│ PROGRESS                              │
│                                       │
│ This week                              │
│  Strength: 2 of 2 done ✓              │
│  Long run: scheduled Fri              │
│  Mobility: 2 of 2 done ✓              │
│                                       │
│ 30-day trend                           │
│  Sessions completed: 24 of 26 (92%)   │
│  Avg session RPE: 7.1                  │
│                                       │
│ Personal records                       │
│  Trap-bar Deadlift · 105 kg · 3 wks ago│
│  DB Bench Press · 30 kg × 8 · 2 wks ago│
│                                       │
│ Marathon in 96 days                    │
│  Peak long run: 32 km · 12 wks away    │
│                                       │
│ [ Weekly check-in due Sun ]            │
└───────────────────────────────────────┘
```

No decision-record dumps, no charts of RPE trends by exercise, no exposure sequence numbers. Simple.

---

## 10. Profile tab

Contains:
- **My Goal** — current goal + phase + event (read-only summary; goal changes go via "Ask coach")
- **Roster** — link to upload new roster
- **My Equipment** — profile-scoped `EquipmentContext` records (permanent home/gym setups)
- **Coach messages** — chat with Louis
- **Weekly check-in** — the questionnaire when due
- **Settings** — notifications, units, sign-out

---

## 11. No roster state

If client has no active roster:
```
┌───────────────────────────────────────┐
│ TODAY · Wed 5 Aug                    │
│                                       │
│ No roster yet.                         │
│ Louis has set you a default plan       │
│ based on your usual schedule.          │
│                                       │
│ ┌───────────────────────────────────┐ │
│ │  Upper Strength                   │ │
│ │  45 min · Home                    │ │
│ │  [ START ]  [ Change equipment ]  │ │
│ └───────────────────────────────────┘ │
│                                       │
│ [ Upload roster ]                      │
└───────────────────────────────────────┘
```

Session count follows `profile.default_availability.training_days_per_week_target`.

When roster arrives, plan silently updates (incremental replan, no destructive change to already-completed sessions).

---

## 12. First-day gate

Existing V1 pattern: after signup + goal set + roster, client sees:
```
Your plan starts tomorrow.

Louis has set up your first week.
Today is a rest day.

[ See tomorrow ]   [ See the plan ]
```

Retained in V2.

---

## 13. Client cannot see:
- DRAFT vs LIVE distinction (always sees LIVE only)
- Exception list
- DecisionRecords
- SafeAdaptationBoundary settings
- Rule tiers, precedence
- LLM prompts
- Any backend labels

Client **can** see:
- "Why this?" Louis-voiced explanations
- Their objective sequence in small type ("Exposure #4")
- Phase name if they open the Progress tab (human copy: "Build")
- Programme summary + event countdown

---

## 14. Notifications (client-facing)

Sent only for meaningful events:
- Coach approved a new plan (batched — max one per day)
- Weekly check-in due
- Coach sent a message
- Session reminder (opt-in)
- "Louis updated your plan for tomorrow's flight change"

Never notify:
- Individual workout adaptations
- SAB expansions
- DecisionRecord writes
- Ordinary progression updates

---

## 15. Push feature disabled by default

V2 does not require push notifications for core functionality. Kept opt-in. Emergent-managed push key retained for future.

---

## 16. Onboarding + first goal setup

Existing V1 flow retained but tightened:
1. Sign up
2. Basic profile
3. Coaching DNA interview (Louis-voiced)
4. Goal picker with primary + optional secondary (V2 addition)
5. If event goal → event date picker
6. Availability + equipment (permanent)
7. Coach welcome message
8. Roster upload prompt (skippable)
9. Ready → Today

Steps 4-5 are the biggest V2 change from V1. Multi-goal support surfaces here.

---

## 17. Client-facing copy rules (from product principle)

- **Never use**: "AI", "bot", "generated", "algorithm", "personalisation engine", "our system"
- **Prefer**: "Louis", "your coach", "we", or omit subject entirely
- **Objective sequence**: display as "Exposure #4" not "objective_exposure #4"
- **Phase names**: human copy — "Building phase", "Getting stronger", "Peak week", "Recovery" — never "programme_phases.hypertrophy"
- **Roster labels**: "Layover", "Flight", "Standby", "Home" — never enum values
- **Equipment**: "Dumbbells", "Barbell", "Bench" — never "equipment_type=barbell"

---

## 18. Accessibility + performance targets

- 44×44 min touch target
- Colour never sole information carrier (KEY badge has icon + colour)
- Screen readers: every card has semantic label ("Today's session, Lower Strength, 40 minutes, hotel gym")
- Cold-start Today load: < 1.5s
- Change Equipment adapt: < 5s
- No animations blocking primary action

---

## 19. Empty and error states

**Plan generation running:**
```
Your plan is being prepared…
Louis will have it ready in about a minute.

Meanwhile: [ Start a mobility session ]
```

**Plan generation failed:**
```
Louis's system is still catching up on your plan.
Don't worry — nothing's lost.

[ Retry ]   [ Message Louis ]
```

Never say "our AI failed" or expose stack traces.

---

## 20. Client change → coach visibility

When a client adapts within SAB, no coach intervention needed.
When outside SAB, client sees:
```
Louis will review this change.
Meanwhile you can train the adapted version.

[ Got it ]
```

Coach dashboard gets a `change_set` entry. Client's LIVE session updates immediately.

---

**End of client UX document.**
