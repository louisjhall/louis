"""Iter 130e — Frontend↔backend goal-key parity guard.

Prevents recurrence of the class of bug where the mobile onboarding
picker writes a goal key like ``"lose_fat"`` that the backend engine
kickoff doesn't recognise (because ``_GOAL_ALIASES`` only knows
``"fat_loss"``). When that mismatch happens, Coach ``Build Plan`` fails
silently with ``critical_dna_missing`` and every new client using that
key is dead-on-arrival until we ship an alias update.

Cheapest possible prevention:
  * scrape every goal ``key``/``id`` literal out of the two onboarding
    files
  * assert each one canonicalises to a real SPORT_CONFIGS entry
  * if a new one is added tomorrow, this test goes red BEFORE the app
    hits Production

Also serves as the canonical list for the startup lint warning that
lives in :mod:`server` — keep them in sync (they read from the same
constant here).
"""
from __future__ import annotations

import os
import re
import sys

# Make the backend package importable without pytest rootdir gymnastics.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feature_v2_sport_configs import (  # noqa: E402
    SPORT_CONFIGS,
    _GOAL_ALIASES,
    canonicalise_goal_key,
)


# --- Files that host the picker UI (source of goal keys) -----------------
# If a new onboarding screen ships, add it here.
_FRONTEND_FILES = [
    "/app/frontend/app/(auth)/onboarding.tsx",
    "/app/frontend/app/training-setup.tsx",
]

# Regex captures `key: "value"` or `id: "value"` inside {} option lists.
_KEY_RE = re.compile(r'\b(?:key|id)\s*:\s*"([a-z0-9_\-\.]+)"')

# Frontend keys that intentionally don't map to a specific SPORT_CONFIG
# (they represent broader intents that only become a real config once a
# secondary field like ``event_type_pref`` is set — e.g. "event" needs
# marathon/half_marathon/etc. to resolve). Excluding these keeps the
# guard tight without a false alarm.
_INTENTIONALLY_UNMAPPED = {
    "event",
}


def _extract_frontend_goal_keys() -> set[str]:
    keys: set[str] = set()
    for path in _FRONTEND_FILES:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            body = f.read()
        # Locate each goal-option array by anchoring on the const name and
        # grabbing the block between the `= [` and the matching `];`.
        # Anchoring on the assignment avoids picking up the type-annotation
        # `[]` that also appears right after the const name.
        for m in re.finditer(
            r"(?:GOAL_OPTS|GOAL_OPTIONS|GOALS_LIST|MAIN_GOAL_OPTIONS)"
            r"\s*(?::[^=]*)?=\s*\[(.*?)\];",
            body,
            re.DOTALL,
        ):
            for k in _KEY_RE.findall(m.group(1)):
                keys.add(k)
    return keys


# Public: startup lint imports this list.
FRONTEND_GOAL_KEYS = sorted(_extract_frontend_goal_keys() - _INTENTIONALLY_UNMAPPED)


def test_every_frontend_goal_key_resolves():
    """Every onboarding-side goal key must canonicalise to a real
    SPORT_CONFIG entry. If this fails, add the missing alias to
    ``_GOAL_ALIASES`` in :mod:`feature_v2_sport_configs`."""
    assert FRONTEND_GOAL_KEYS, (
        "No frontend goal keys were extracted — the regex or file list "
        "is stale. Check _FRONTEND_FILES and the marker comments in "
        "onboarding.tsx / training-setup.tsx."
    )
    unresolved: list[str] = []
    for key in FRONTEND_GOAL_KEYS:
        canon = canonicalise_goal_key(key)
        # canonicalise_goal_key falls back to general.fitness on unknown
        # inputs, so we can't rely on that alone. Confirm the input
        # itself is recognised via the alias / config table.
        k = key.strip().lower().replace(" ", "_")
        if k in SPORT_CONFIGS or k in _GOAL_ALIASES:
            continue
        unresolved.append(f"{key!r} → fell through to {canon!r} (no alias)")
    assert not unresolved, (
        "Frontend goal keys not recognised by backend _GOAL_ALIASES / "
        "SPORT_CONFIGS. Add each to _GOAL_ALIASES in "
        "feature_v2_sport_configs.py:\n  " + "\n  ".join(unresolved)
    )


def test_intentionally_unmapped_are_still_used():
    """Sanity: if we listed a key as intentionally unmapped but the
    frontend no longer uses it, prune it — otherwise the exclusion
    silently hides real regressions."""
    all_frontend = _extract_frontend_goal_keys()
    stale = _INTENTIONALLY_UNMAPPED - all_frontend
    assert not stale, (
        f"Prune stale entries from _INTENTIONALLY_UNMAPPED: {stale}"
    )
