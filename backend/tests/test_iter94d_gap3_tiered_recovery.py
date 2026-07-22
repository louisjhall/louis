"""
Iter 94d · Gap 3 — tiered post-flight recovery templates.

Verifies:
  * flight_recovery_template_for(3h)  → tier='short',  8 min, 4-move standing mobility.
  * flight_recovery_template_for(8h)  → tier='medium', 15 min, classic FLIGHT_RECOVERY_MOBILITY.
  * flight_recovery_template_for(14h) → tier='ulr',    25 min, includes 4-7-8 breathing + hydration cue.
  * _override_for_duty stamps recovery_tier + duty_hours on the output.
  * ULR override is day_load='red' and NOT optional (mandatory sleep prep).
  * Short-haul override is day_load='amber' and optional.
  * build_template_plan picks the right tier based on the roster day's duty_hours.
  * roster_summary.recovery_tiered_days lists each long-haul day with its tier.
"""

import datetime as _dt
from feature_workout_fallback import (
    flight_recovery_template_for,
    _override_for_duty,
    build_template_plan,
    FLIGHT_RECOVERY_MOBILITY,
    SHORT_HAUL_AIRPORT_MOBILITY,
    ULR_RECOVERY_PROTOCOL,
)
from feature_programme_quality import _roster_summary


def _make_user(main_goal="build_muscle"):
    return {
        "id": "user_iter94d", "email": "gap3@test.local", "role": "client",
        "profile": {
            "main_goal_key": main_goal,
            "training_days_per_week": 4,
            "time_home_min": 45, "time_layover_min": 45,
            "equipment": ["dumbbells", "bench"],
            "hotel_gym_reliability": "sometimes",
        },
    }


class TestPicker:
    def test_short_haul(self):
        tpl = flight_recovery_template_for(3)
        assert tpl["tier"] == "short"
        assert tpl["duration_min"] == 8
        assert tpl["exercises"] == SHORT_HAUL_AIRPORT_MOBILITY
        # Sanity: no floor work in the short-haul list.
        names = " ".join(e["name"].lower() for e in tpl["exercises"])
        assert "standing" in names or "doorway" in names

    def test_medium_haul_default(self):
        tpl = flight_recovery_template_for(8)
        assert tpl["tier"] == "medium"
        assert tpl["duration_min"] == 15
        assert tpl["exercises"] == FLIGHT_RECOVERY_MOBILITY

    def test_ulr(self):
        tpl = flight_recovery_template_for(14)
        assert tpl["tier"] == "ulr"
        assert tpl["duration_min"] == 25
        assert tpl["exercises"] == ULR_RECOVERY_PROTOCOL
        names = " ".join(e["name"].lower() for e in tpl["exercises"])
        assert "4-7-8" in names or "box breathing" in names
        # Explicit hydration prompt in the rationale
        assert "hydrate" in tpl["rationale"].lower()

    def test_none_defaults_to_medium(self):
        tpl = flight_recovery_template_for(None)
        assert tpl["tier"] == "medium"


class TestOverride:
    def test_short_haul_override_is_amber_and_optional(self):
        override = _override_for_duty("flight_heavy", "2026-08-01", duty_hours=4)
        assert override is not None
        assert override["day_load"] == "amber"
        assert override["duration_min"] == 8
        assert override["title"] == "Airport Mobility"
        assert override["recovery_tier"] == "short"
        assert override["optional"] is True

    def test_ulr_override_is_red_and_not_optional(self):
        override = _override_for_duty("flight_heavy", "2026-08-01", duty_hours=14)
        assert override is not None
        assert override["day_load"] == "red"
        assert override["duration_min"] == 25
        assert override["title"] == "ULR Recovery + Sleep Prep"
        assert override["recovery_tier"] == "ulr"
        # ULR must NOT be optional — sleep prep is mandatory
        assert override["optional"] is False

    def test_medium_override_current_behaviour_preserved(self):
        override = _override_for_duty("flight_heavy", "2026-08-01", duty_hours=8)
        assert override["duration_min"] == 15
        assert override["title"] == "Flight Recovery Mobility"
        assert override["recovery_tier"] == "medium"


class TestBuildTemplatePlan:
    def _roster_with_duty(self, hours: float):
        today = _dt.date.today()
        return {"id": f"roster_iter94d_{int(hours)}", "days": [
            {"date": today.isoformat(), "day_type": "long_haul", "duty_hours": hours},
            {"date": (today + _dt.timedelta(days=1)).isoformat(), "day_type": "rest"},
            {"date": (today + _dt.timedelta(days=2)).isoformat(), "day_type": "home"},
            {"date": (today + _dt.timedelta(days=3)).isoformat(), "day_type": "home"},
            {"date": (today + _dt.timedelta(days=4)).isoformat(), "day_type": "home"},
            {"date": (today + _dt.timedelta(days=5)).isoformat(), "day_type": "rest"},
            {"date": (today + _dt.timedelta(days=6)).isoformat(), "day_type": "rest"},
        ]}

    def test_short_flight_gets_short_template(self):
        u = _make_user()
        r = self._roster_with_duty(4)
        plan = build_template_plan(u, r)
        day0 = next(w for w in plan if w["date"] == r["days"][0]["date"])
        assert day0["recovery_tier"] == "short"
        assert day0["duration_min"] == 8

    def test_ulr_flight_gets_ulr_template(self):
        u = _make_user()
        r = self._roster_with_duty(14)
        plan = build_template_plan(u, r)
        day0 = next(w for w in plan if w["date"] == r["days"][0]["date"])
        assert day0["recovery_tier"] == "ulr"
        assert day0["duration_min"] == 25
        # ULR must feature the sleep-prep breathing
        ex_names = [e["name"].lower() for e in day0["exercises"]]
        assert any("4-7-8" in n for n in ex_names)


class TestRosterSummaryTiers:
    def test_all_three_tiers_annotated(self):
        today = _dt.date.today()
        r = {"id": "roster_mixed", "days": [
            {"date": today.isoformat(), "day_type": "long_haul", "duty_hours": 3},
            {"date": (today + _dt.timedelta(days=1)).isoformat(),
             "day_type": "long_haul", "duty_hours": 9},
            {"date": (today + _dt.timedelta(days=2)).isoformat(),
             "day_type": "long_haul", "duty_hours": 14},
        ]}
        summary = _roster_summary(r)
        tiered = summary.get("recovery_tiered_days") or []
        tiers = {t["tier"] for t in tiered}
        assert tiers == {"short", "medium", "ulr"}, tiers
