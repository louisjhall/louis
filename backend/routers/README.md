# CrewFit — Backend Routers
This directory contains APIRouter modules extracted from the historic monolithic
`server.py`. New endpoints should be added here in feature-scoped files. Existing
endpoints in `server.py` will be migrated incrementally.

## Migration status
- [x] `hq.py` — Coaching Headquarters (Personal Records, Achievements, Notes aggregators, User Profile PATCH)
- [x] `reassessment.py` — Living Profile re-assessment prompts (list/dismiss)
- [ ] `reality.py` — Dynamic Life Adaptation Engine (Today's Reality)
- [ ] `assessment.py` — CrewFit Intelligence Assessment™ (start/answer/finalize/DNA)
- [ ] `roster.py` — Roster upload, parsing, timeline
- [ ] `workouts.py` — Workout CRUD, generation, week/month
- [ ] `coach.py` — Coach dashboard, calendar, videos, scripts
- [ ] `exercises.py` — Exercise video system

## Import pattern
Each module exposes a top-level `router: APIRouter` that `server.py` mounts via
`app.include_router(router)` (or `api.include_router(...)` for the /api prefix).

Shared helpers (db handle, current_user dep, new_id/now_iso) are imported from
`shared.py` to avoid circular imports.
