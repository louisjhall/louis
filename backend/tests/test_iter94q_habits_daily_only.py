"""
Iter 94q — Habits must be DAILY, not weekly workout targets.

Root cause was `_default_habit_pack` seeding a "Sunday weekly check-in" (and
the Atlas LLM being free to invent habits like "one run per week"). The fix
rewrites the deterministic pack (daily-only), adds `_is_bad_habit` validator,
filters the LLM output, and hard-excludes weekly habits from `/habits/today`.
"""
from __future__ import annotations
import sys
sys.path.insert(0, "/app/backend")


def test_is_bad_habit_rejects_weekly():
    from feature_habits import _is_bad_habit
    for h in [
        {"title": "Sunday weekly check-in", "frequency": "weekly"},
        {"title": "Something reasonable", "habit_type": "weekly"},
        {"title": "Run once per week",     "frequency": "daily"},
        {"title": "Hit weekly mileage",    "frequency": "daily"},
        {"title": "Complete your workout", "frequency": "daily"},
        {"title": "Train 4 times",         "frequency": "daily"},
        {"title": "Long run",              "frequency": "daily"},
        {"title": "No carbs today",        "frequency": "daily"},
        {"title": "Eliminate sugar",       "frequency": "daily"},
        {"title": "Lose 1kg this week",    "frequency": "daily"},
        {"title": "", "frequency": "daily"},
    ]:
        bad, why = _is_bad_habit(h)
        assert bad, f"should have been rejected: {h}"
        assert why, f"missing reason for {h}"


def test_is_bad_habit_accepts_daily_actions():
    from feature_habits import _is_bad_habit
    for h in [
        {"title": "Protein with first meal",         "frequency": "daily"},
        {"title": "5-minute mobility reset",         "frequency": "daily"},
        {"title": "Drink water before your first coffee", "frequency": "daily"},
        {"title": "Hydrate before your run",         "frequency": "daily"},
        {"title": "Review today's plan",             "frequency": "daily"},
        {"title": "Pack one high-protein snack",     "frequency": "daily"},
        {"title": "10-minute walk after landing",    "frequency": "daily"},
    ]:
        bad, why = _is_bad_habit(h)
        assert not bad, f"should have been accepted: {h!r} (reason={why!r})"


def test_default_pack_is_daily_only_and_capped_at_3():
    from feature_habits import _default_habit_pack, _is_bad_habit
    for goals in [
        ["fat_loss"], ["marathon"], ["strength"], ["general"], [],
    ]:
        pack = _default_habit_pack({"primary_goals": goals})
        assert len(pack) <= 3, f"pack too big for {goals}: {len(pack)}"
        assert len(pack) >= 2, f"pack too small for {goals}: {len(pack)}"
        for h in pack:
            assert h["frequency"] == "daily", f"non-daily habit in pack for {goals}: {h}"
            assert h["habit_type"] == "daily", f"non-daily habit_type: {h}"
            bad, why = _is_bad_habit(h)
            assert not bad, f"default pack contains a bad habit ({why}): {h}"


def test_default_pack_matches_main_goal():
    from feature_habits import _default_habit_pack
    fat = _default_habit_pack({"primary_goals": ["fat_loss"]})
    mar = _default_habit_pack({"primary_goals": ["marathon"]})
    strn = _default_habit_pack({"primary_goals": ["strength"]})
    assert any("protein" in h["title"].lower() for h in fat), "fat-loss should have a protein habit"
    assert any("hydrate" in h["title"].lower() or "run" in h["title"].lower() for h in mar), "marathon should have a running-support habit"
    assert any("protein" in h["title"].lower() for h in strn), "strength should have a protein habit"
