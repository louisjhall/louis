# Pietro Pre/Post Roster+Draft Reset State

**Client ID**: `c4c7c7dd-4303-4645-af2c-b70212495360`  
**Email**: `pietrosangermano1992@hotmail.com`  
**Reset at**: `2026-07-27T21:01:00.973544Z`

## Before

```json
{
  "tag": "PRE_RESET",
  "timestamp": "2026-07-27T21:01:00.965952Z",
  "roster": {
    "schedule_days": 62,
    "roster_jobs": 5,
    "rosters": 3
  },
  "drafts_v2": {
    "total": 11,
    "published": 3,
    "needs_review": 5,
    "ready_for_review": 3,
    "superseded_by_reset": 0,
    "other": 0
  },
  "lives_v2": {
    "total": 3,
    "active": 1,
    "ids": [
      {
        "id": "d433c97f-b9b3-4e7c-9814-0f465e4d3e10",
        "active": false
      },
      {
        "id": "da16d278-f024-4f6d-8ebc-faed067e9cb0",
        "active": false
      },
      {
        "id": "d8caa689-4c74-469f-963b-9049c88e09bf",
        "active": true
      }
    ]
  },
  "exceptions": {
    "total": 70,
    "roster_change": 62
  },
  "history_preserved": {
    "workouts": 21,
    "workout_assignments": 18,
    "workout_implementations": 18,
    "objective_exposures": 26,
    "training_objectives": 15,
    "programme_phases_v2": 6,
    "decision_records": 70
  }
}
```

## After

```json
{
  "tag": "POST_RESET",
  "timestamp": "2026-07-27T21:01:00.975124Z",
  "roster": {
    "schedule_days": 0,
    "roster_jobs": 0,
    "rosters": 0
  },
  "drafts_v2": {
    "total": 11,
    "published": 3,
    "needs_review": 0,
    "ready_for_review": 0,
    "superseded_by_reset": 8,
    "other": 0
  },
  "lives_v2": {
    "total": 3,
    "active": 1,
    "ids": [
      {
        "id": "d433c97f-b9b3-4e7c-9814-0f465e4d3e10",
        "active": false
      },
      {
        "id": "da16d278-f024-4f6d-8ebc-faed067e9cb0",
        "active": false
      },
      {
        "id": "d8caa689-4c74-469f-963b-9049c88e09bf",
        "active": true
      }
    ]
  },
  "exceptions": {
    "total": 8,
    "roster_change": 0
  },
  "history_preserved": {
    "workouts": 21,
    "workout_assignments": 18,
    "workout_implementations": 18,
    "objective_exposures": 26,
    "training_objectives": 15,
    "programme_phases_v2": 6,
    "decision_records": 70
  }
}
```
