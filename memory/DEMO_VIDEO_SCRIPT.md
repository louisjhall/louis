# CrewFit — Full Demo Script

**Target runtime:** ~8–10 minutes (full walkthrough) with sub-clips extractable for 30-, 60-, and 90-second cutdowns.
**Voice direction:** Warm, confident British male. Aviation-professional cadence — think airline captain PA, not gym bro. Never says "AI", "algorithm", "auto-generated", or "bot". Everything is "Louis" or "CrewFit".
**On-screen aesthetic:** Dark premium CrewFit palette (matte black + red accent). Mobile portrait 9:16 for social cut, 16:9 for landing page.
**Music:** Low, cinematic bass under the intro & outro; drop out during voice-only scenes.

---

## 0. COLD OPEN — 0:00 – 0:10  *(hero clip, 10s)*

**Visual:** Fast montage — a crew member rolling a case through an airport, a phone showing CrewFit's home screen with today's flight `[airplane] BA113`, cut to a workout timer counting down, cut to a plate of food being logged, close on the CrewFit red mark.

**Narration:**
> Your roster changes every week. Your training shouldn't fall apart because of it. This is CrewFit — the training and nutrition app built specifically for airline crew, by a coach who's been in your seat.

---

## 1. SIGN-UP & ONBOARDING — 0:10 – 0:55

**Screens:** `welcome.tsx` → `signup.tsx` → `onboarding.tsx` → `assessment.tsx` → `coaching-dna.tsx` → `training-setup.tsx` → `first-day-choice.tsx`

**Shots:**
1. Welcome screen — CrewFit branding
2. Signup form filling out
3. Onboarding questions — role (pilot / cabin crew), airline picker, flying type
4. Assessment: goals, experience, injuries, hotel gym history
5. Coaching DNA card revealed
6. Training availability sliders — home / layover / days off
7. First-day choice — "Start with a strength day? A mobility day? Or a roster upload?"

**Narration:**
> Onboarding takes under two minutes. You tell CrewFit who you are, what you fly, and what you want out of training. From there, Louis builds your Coaching DNA — a profile that shapes every session you'll ever see. Set your training availability for home, layovers, and days off, then choose how you want your first day to feel.

---

## 2. ROSTER UPLOAD & PARSING — 0:55 – 1:35

**Screens:** `roster-upload.tsx` → `roster/confirm/[id].tsx` → `roster/manage.tsx`

**Shots:**
1. Roster upload landing — big drop zone
2. Selecting a PDF (Emirates or Etihad roster shown as prop)
3. Parsing spinner
4. Confirmation screen — each duty day laid out visually: flights, layovers, standby, rest
5. Long-press to correct a mis-parsed day
6. "Roster confirmed" → moves to programme approval waiting state

**Narration:**
> Drop in your Emirates or Etihad roster PDF. CrewFit reads every duty — flights, layovers, standby, rest — and lays it out day by day. If anything looks off, long-press to correct it. Once you confirm, it goes straight to Louis for a final polish before your programme goes live.

---

## 3. PROGRAMME STATUS & COACH APPROVAL — 1:35 – 2:05

**Screens:** `home.tsx` (waiting state) → `ProgrammeStatusCard` timeline

**Shots:**
1. Client home showing the "PROGRAMME UNDER FINAL REVIEW" card
2. Four-step timeline: Uploaded → Reviewed → Approved → Live
3. Cut to coach dashboard, Louis tapping APPROVE PROGRAMME
4. Cut back to client — the card auto-transitions to a live workout

**Narration:**
> Every programme is checked by Louis personally before it lands in your calendar. You'll see a clear timeline — uploaded, reviewed, approved, live — so you always know what's happening. The moment Louis approves, your first session is right there.

---

## 4. HOME DASHBOARD — 2:05 – 2:45

**Screens:** `(client)/home.tsx`

**Shots:**
1. Today's session hero card with roster chip inline `[airplane] BA113 · LHR → DXB`
2. NEXT 5 DAYS strip: each row with day-of-week + roster chip (`[bed] DXB`, `[repeat] T/R`, `[moon] OFF`) + workout title + KEY pill
3. Quick-btn row: MONTHLY / CHECK-IN / PROGRESS
4. Nutrition Today card
5. Habit Today card

**Narration:**
> Your home screen shows exactly what today looks like — the flight you're on, the workout Louis's built around it, and what's coming next. Rest days, layover days, and flying days are marked clearly so you're never asking "wait, am I training today?"

---

## 5. CALENDAR VIEW — 2:45 – 3:05

**Screens:** `(client)/calendar.tsx`

**Shots:**
1. Monthly calendar grid
2. Each day cell shows a tiny roster chip icon (airplane / bed / moon)
3. Load dot colours (green / amber / red)
4. Key session stars
5. Tap into a specific day

**Narration:**
> Zoom out to the month. Every day tells you what it is at a glance — flying, layover, rest, or session — plus the load Louis has set. Tap any day to see the full plan.

---

## 6. WORKOUT DETAIL — 3:05 – 3:35

**Screens:** `workout/[id]/index.tsx`

**Shots:**
1. Workout title (e.g. "ICN Layover Hotel Gym Strength")
2. LAYOVER CONTEXT card — "Built around your ICN layover with hotel gym access."
3. WHY THIS SESSION? rationale block
4. Warm-up list
5. Exercise cards with reps, sets, RPE targets
6. Media carousel per exercise

**Narration:**
> Every session tells you why it's there. Layover in Seoul? You'll see the workout titled around the airport, with a note explaining Louis has adjusted it for your hotel setup. Warm-up, working sets, target reps — all clean, all deliberate.

---

## 7. GUIDED WORKOUT MODE — 3:35 – 4:25

**Screens:** `workout/[id]/guided.tsx` → `play.tsx`

**Shots:**
1. Mode picker — Standard vs Guided
2. Guided starts — big "Set 1 of 4" timer
3. Voice cue playing: British male voice — "Set 1 of 4. Goblet squat. 10 reps."
4. Exercise media auto-plays
5. Set complete → auto rest timer starts
6. "Rest 60 seconds. Next up, Romanian deadlift."
7. Workout complete screen

**Narration:**
> When you're in the gym, tap into Guided mode. Louis's voice walks you through every set — what's next, how many reps, when to rest, when to go. Hands-free, headphones-only if you want it, so you focus on the lift, not the phone.

---

## 8. POST-WORKOUT QUICK RATING — 4:25 – 4:50

**Screens:** `PostWorkoutRatingSheet` (opens on complete)

**Shots:**
1. "Session complete" hero
2. Four aviation options: Smooth flight / Light turbulence / Heavy turbulence / Diverted
3. Client taps SMOOTH FLIGHT → LOG WORKOUT → confirmation ("Nice work — logged.")
4. Second take: taps HEAVY TURBULENCE → pain check appears → NO → LOG WORKOUT → confirmation ("Louis can review this if needed.")

**Narration:**
> After each session, one tap. Smooth flight, light turbulence, heavy turbulence, or diverted. If it was tough, CrewFit checks in on pain quietly and only then flags it to Louis. No forms. No essays. Done in five seconds.

---

## 9. TODAY'S REALITY — 4:50 – 5:15

**Screens:** decision / reality flow

**Shots:**
1. Client on a layover taps "Today's Reality"
2. Options: hotel gym unavailable / feeling wiped / short on time / travel disruption
3. Louis re-plans on the spot with an alternative session
4. Reality history log

**Narration:**
> Your day never goes exactly to plan. Tap Today's Reality and tell CrewFit what changed — hotel gym is closed, you slept badly, your flight got moved. Louis re-plans in real time. Nothing wasted, nothing punitive.

---

## 10. NUTRITION SYSTEM — 5:15 – 6:15

**Screens:** `(client)/nutrition.tsx`, `nutrition/log.tsx`, `nutrition/photo-scan.tsx`, `nutrition/barcode.tsx`, `nutrition/airport.tsx`, `nutrition/travel.tsx`, `nutrition/targets.tsx`, `nutrition/insights.tsx`, `nutrition/timing.tsx`

**Shots:**
1. Nutrition dashboard — calories / protein rings
2. Log a meal — three ways: photo scan, barcode, food search
3. Airport food picker — realistic terminal options
4. Travel mode — layover eating patterns
5. Meal timing card ("post-flight" / "pre-flight" / "layover breakfast")
6. Weekly insights

**Narration:**
> Nutrition is built for how you actually eat. Snap a photo, scan a barcode, or search — CrewFit logs it. On the road, we've built proper airport food menus into the app, plus travel mode for layovers. Louis sets your protein and calorie targets against your flying schedule, not a generic desk-job calculator.

---

## 11. HABITS & CHECK-INS — 6:15 – 6:45

**Screens:** `HabitTodayCard`, `checkin.tsx`, `reassessment/[kind].tsx`

**Shots:**
1. Habit today card — tickable habits (hydration, sleep window, morning walk)
2. Weekly check-in — sliders for energy, sleep, stress
3. Trigger a reassessment mid-block

**Narration:**
> Small habits compound. Track hydration, sleep, and the daily basics with one tap. Once a week, the check-in takes ninety seconds and tells Louis how the block is landing. If something shifts — new event, injury, layoff, life — trigger a reassessment and CrewFit rebuilds around it.

---

## 12. PROGRESS & YOUR PROGRESS — 6:45 – 7:05

**Screens:** `progress.tsx`, `your-progress.tsx`

**Shots:**
1. Volume, sessions completed, streak
2. Body weight / measurements line graph
3. Personal bests
4. Compare-to-last-block card

**Narration:**
> Progress isn't just a number on the scale. Sessions completed, volume moved, key sessions hit, streaks held together across long-haul weeks — CrewFit shows you what actually changed, block by block.

---

## 13. EVENTS & GOALS — 7:05 – 7:25

**Screens:** `event.tsx`, event context in home

**Shots:**
1. Add an event — half marathon in 12 weeks
2. Event dashboard — weeks-to-race, current ability, target
3. Programme auto-reshapes around the event

**Narration:**
> Got a race in mind? A wedding? A crew Everest Base Camp? Add the event and CrewFit orients the whole block around it — miles ramp, strength stays honest, taper on time.

---

## 14. HOTEL SETUP — 7:25 – 7:40

**Screens:** `hotel-setup.tsx`, `coach/hotels.tsx`

**Shots:**
1. Layover coming up
2. "Set your hotel gym"
3. Choose equipment available
4. Save — next layover workout at that hotel is prewritten to match

**Narration:**
> The first time you hit a new layover hotel, tell CrewFit what's in the gym. Rack? Dumbbells only? Bodyweight-safe? From that moment on, every workout there is written for that room.

---

## 15. MESSAGING WITH LOUIS — 7:40 – 8:00

**Screens:** `(client)/messages.tsx`

**Shots:**
1. Inbox with a Louis message
2. Client sends a photo / voice note
3. Louis reply lands
4. Attachments, voice notes, images inline

**Narration:**
> Anytime you need Louis — a question, a nudge, a form check — message him directly. Photos, voice notes, video. This isn't a bot. It's your coach.

---

## 16. SOCIAL STUDIO — 8:00 – 8:20

**Screens:** `social-studio.tsx`, `social-studio/record/[postId].tsx`

**Shots:**
1. Studio landing — content prompts
2. Record a quick 30-second reel with teleprompter
3. Auto-subtitle preview
4. Export

**Narration:**
> Coaches, this one's for you. Record client wins, drills, and stories in one place with a teleprompter and auto-subtitles. Content out the door in minutes, on brand, every time.

---

## 17. COACH DASHBOARD — 8:20 – 9:00

**Screens:** `(coach)/overview.tsx`, `(coach)/clients.tsx`, `coach/client-months/[id].tsx`, `CoachLiveFeed`, `CoachApprovalQueueCard`, `CoachToDoFeed`

**Shots:**
1. Louis's overview — clients by state, pending approvals, live feed
2. Programme approvals card — one-tap approve
3. Live feed of next 5 days across all clients
4. Client roster/programme control centre — month-by-month
5. Inline workout swap picker
6. Coach notes tab (structured client-specific coaching notes injected into the LLM)

**Narration:**
> On the coach side, Louis runs the whole business from one screen. Every client, every roster, every workout — visible, editable, one-tap approvable. Live feed of what's happening in the next five days. Inline swap-workout, coach notes that shape every future session for that client. Louis's operating table.

---

## 18. EXERCISE LIBRARY — 9:00 – 9:20

**Screens:** `(coach)/library.tsx`, `coach/exercise-content.tsx`

**Shots:**
1. Library grid — hundreds of exercises with cinematic dark photography
2. Male and female demo images with the CrewFit chest logo
3. Coaching points, common mistakes, video demos
4. Approved / draft states

**Narration:**
> Every exercise in CrewFit is photographed on brand and coached in-app. Coaching points, common mistakes, video demos. Male and female demo models both wearing the CrewFit kit — nothing generic, nothing off-brand.

---

## 19. ADMIN / TRUST — 9:20 – 9:40

**Screens:** `legal/data-safety.tsx`, `legal/privacy.tsx`, `legal/delete-account.tsx`, `legal/contact.tsx`, `guard-rails.tsx`

**Shots:**
1. Data safety card
2. Delete account flow
3. Guard rails (injuries / medical / no-train days)

**Narration:**
> CrewFit takes your data seriously. Everything you put in belongs to you. Full delete-my-account flow, medical guard rails so you never see a session that risks an injury you've told us about, and clear privacy terms — no surprises.

---

## 20. CLOSING — 9:40 – 10:00  *(hero close)*

**Visual:** Return to montage. Client checking off a workout at 22,000 feet over the Atlantic. Louis approving a programme. Someone crushing a hotel-gym session in Kuala Lumpur. Cut to CrewFit red mark.

**Narration:**
> Every workout, every meal, every layover — built around your actual schedule, checked by your actual coach. CrewFit. Training that flies with you.

**End card:** CrewFit logo + "Now boarding" (private beta call-to-action)

---

## CUT-DOWN GUIDE

- **30-second social teaser:** Sections 0 + 4 + 7 + 8 + 20
- **60-second app store trailer:** 0 + 2 + 4 + 6 + 7 + 10 + 20
- **90-second landing page hero:** 0 + 1 + 2 + 3 + 4 + 7 + 10 + 15 + 20
- **Full pitch deck / investor version:** all sections, keep the coach dashboard (17) prominent

## VOICEOVER PRODUCTION NOTES

- Voice: British male, warm and confident. Aviation-professional. Not a hard-sell voice.
- Suggested TTS options if a live VO is out of budget:
  - **ElevenLabs**: "Adam" (deep, warm) or "Bill" (British, natural)
  - **OpenAI TTS (`gpt-4o-mini-tts`)**: voice `"onyx"` or `"echo"` — echo has a light British lilt
- Read speed: 155–165 wpm — deliberate, not rushed.
- Pause 200–300 ms after aviation terms ("layover", "long-haul", "flying schedule") to let them land.
- Never emphasise "AI" or "automatic" — always emphasise "Louis" or "CrewFit".

## LEGAL / COMPLIANCE STRIP

- Show only test users when recording. Do NOT record with real client data. Use the reviewer + louis accounts we have credentials for.
- On screens showing food images / medical notes, blur names / emails.
- Keep every screen loaded with clean data before recording — regenerate the reviewer roster first.
