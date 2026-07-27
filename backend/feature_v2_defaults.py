"""
feature_v2_defaults — Default V2 flag bundles.

Ships all newly-created users (both clients via signup + clients created
by coaches + coaches themselves) onto V2 by default. Also exposes a
`enable_v2_for_user` helper used by the migration script and by manual
flag flips from the coach dashboard.
"""
from __future__ import annotations

from typing import Any


def default_client_v2_flags() -> dict[str, Any]:
    """The full V2 engine flag bundle for a client.

    Turns on every V2 subsystem so the client is running end-to-end on
    the new architecture:
      - state_foundation:   Live-vs-Draft plan boundary
      - goals_phases:       Goal→Phase→Objective pipeline (P2/P3)
      - roster_facets:      Roster-driven reality inputs (P4)
      - scheduling_v2:      Draft calendar builder (P5)
      - construction_v2:    Workout implementation builder (P6)
      - equipment_adaptation_v2: Location/equipment lookaheads (P7)
      - progression_v2:     Weekly progression signals (P8)
      - reality_v2:         Reality reconciliation (P9)
      - events_v2:          Target events + phase math (P10)
      - automation_v2:      Coach directive engine + scheduled jobs (P12)
      - demand_engine:      Coach demand queue triage
    Also flips the `v2_default` master switch (used by resolvers /
    guards that only care whether V2 is on in aggregate).
    """
    return {
        "v2_default": True,
        "state_foundation_enabled": True,
        "goals_phases_enabled": True,
        "roster_facets_enabled": True,
        "scheduling_v2_enabled": True,
        "construction_v2_enabled": True,
        "equipment_adaptation_v2_enabled": True,
        "progression_v2_enabled": True,
        "reality_v2_enabled": True,
        "events_v2_enabled": True,
        "automation_v2_enabled": True,
        "demand_engine_enabled": True,
    }


def default_coach_v2_flags() -> dict[str, Any]:
    """The full V2 dashboard flag bundle for a coach."""
    return {
        "v2_default": True,
        "coach_dashboard_v2_enabled": True,
        "state_foundation_enabled": True,
        "goals_phases_enabled": True,
        "roster_facets_enabled": True,
        "scheduling_v2_enabled": True,
        "construction_v2_enabled": True,
        "equipment_adaptation_v2_enabled": True,
        "progression_v2_enabled": True,
        "reality_v2_enabled": True,
        "events_v2_enabled": True,
        "automation_v2_enabled": True,
        "demand_engine_enabled": True,
    }


def merge_v2_flags(existing: dict | None, defaults: dict) -> dict:
    """Merge default flags into an existing dict; existing True overrides
    do not get demoted. Used by the migration."""
    out = dict(defaults)
    if existing:
        for k, v in existing.items():
            # Only preserve non-flag audit fields ("updated_at", "updated_by").
            if k in ("updated_at", "updated_by"):
                out[k] = v
            # If someone had explicitly disabled a flag, we still promote
            # it to True during the V2-by-default migration — this is the
            # entire point.
    return out
