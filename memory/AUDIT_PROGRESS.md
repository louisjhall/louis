# CrewFit Training Intelligence — Forensic Audit Progress

## Session started
Iter 110 — audit only, no code changes.

## Deliverables
- `/app/memory/CREWFIT_TRAINING_INTELLIGENCE_CURRENT_ARCHITECTURE.md` — long-form
- `/app/memory/CREWFIT_TRAINING_INTELLIGENCE_CURRENT_ARCHITECTURE.json` — structured mirror

## Rules
- No code, prompt, or schema mutations.
- Honesty labels: ✅ IMPLEMENTED · ⚠️ PARTIAL · ❓ AMBIGUOUS/DUPLICATED · ❌ NOT IMPLEMENTED · 🧪 PLACEHOLDER
- Inline: full prompts + material rule-engine code. Wiring: path + function only.
- Distinguish competing code paths + which is actually reachable from UI/API.
- Do not infer missing behaviour.

## Progress checklist

### Phase 1 — Repo mapping
- [ ] backend feature_*.py inventory
- [ ] backend collections inventory (real writes/reads)
- [ ] router / api registration map
- [ ] frontend screens + coach vs client separation
- [ ] background tasks / crons

### Phase 2 — Core engines
- [ ] Goal system enumeration + programming behaviour
- [ ] Phase / periodisation engine
- [ ] Event training engine
- [ ] Exercise database schema
- [ ] Progression engine
- [ ] Roster / duty types enumeration
- [ ] Hotel gym architecture
- [ ] Facility/equipment logic
- [ ] Today's Reality
- [ ] Readiness engine
- [ ] Coach directives
- [ ] Regeneration paths

### Phase 3 — Prompts (verbatim)
- [ ] Roster parse prompts
- [ ] Programme generation prompts
- [ ] Workout generation prompts
- [ ] Hotel gym / equipment prompts
- [ ] Today's Reality / adaptation prompts
- [ ] Coach notes / directive prompts
- [ ] Progression / readiness prompts

### Phase 4 — Composition
- [ ] Section-by-section markdown
- [ ] Scenario traces A–J
- [ ] Capability matrix
- [ ] Scorecard
- [ ] Structured JSON

## Key files observed so far
- `/app/backend/server.py` (11,981 lines)
- `/app/backend/feature_*.py` (many)
- `/app/backend/parsers/etihad.py`, `emirates.py`
- `/app/backend/tests/*`

## Notes / hazards
- `emergentintegrations` for LLM calls — Claude Sonnet 4.5 / Gemini via Emergent LLM key
- Multiple generators exist (see server.py + feature_workout_fallback.py + feature_v2_resolver.py)
- Ambiguity zones expected: template vs LLM path, coach-notes-injection, layover naming
