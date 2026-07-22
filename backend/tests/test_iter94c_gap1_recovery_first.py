"""
Iter 94c · Gap 1 — long-haul into 18h+ layover no longer gets stranded on
a 15-min recovery mobility. Verifies:

  * Roster day with day_type='long_haul' + next-day report ≥ 18h later + a
    known hotel_id gets a recovery_first=True session (not the safety override).
  * That session has FLIGHT_RECOVERY_MOBILITY prepended to warmup.
  * RPE capped at 7 on main exercises.
  * Long-run / tempo / intervals slots downshifted to easy_run.
  * day_load == 'amber'.
  * If NO hotel_id, we keep the safety override (15-min mobility, RED).
  * roster_summary.recovery_first_days lists the correct dates.
"""

import datetime as _dt
from feature_workout_fallback import build_template_plan
from feature_programme_quality import _roster_summary


HOTEL = {"id": "hotel_dxb_01", "name": "DXB Airport Hyatt", "has_gym": True,
        "gym_type": "hotel_gym"}
HOTEL_LOOKUP = {HOTEL["id"]: HOTEL}


def _make_user(main_goal="build_muscle"):
    return {
        "id": "user_iter94c", "email": "gap1@test.local", "role": "client",
        "profile": {
            "main_goal_key": main_goal,
            "training_days_per_week": 4,
            "time_home_min": 45, "time_layover_min": 45,
            "equipment": ["dumbbells", "bench"],
            "hotel_gym_reliability": "sometimes",
        },
    }


def _make_roster_long_haul_into_layover(hotel_id="hotel_dxb_01"):
    """LHR→DXB long-haul lands 10:00 on day 1. Next flight reports 08:00 day 3 → 22h+ free."""
    today = _dt.date.today()
    return {
        "id": "roster_iter94c",
        "days": [
            # Long-haul leg with a KNOWN hotel — 22h free window
            {"date": today.isoformat(), "day_type": "long_haul",
             "duty_hours": 12, "duty_end_time": "10:00",
             "hotel_id": hotel_id},
            # Layover rest day (no duty)
            {"date": (today + _dt.timedelta(days=1)).isoformat(),
             "day_type": "layover", "hotel_id": hotel_id,
             "duty_end_time": None, "report_time": None},
            # Return duty starts 08:00 two days later
            {"date": (today + _dt.timedelta(days=2)).isoformat(),
             "day_type": "flight", "report_time": "08:00"},
            {"date": (today + _dt.timedelta(days=3)).isoformat(), "day_type": "rest"},
            {"date": (today + _dt.timedelta(days=4)).isoformat(), "day_type": "home"},
            {"date": (today + _dt.timedelta(days=5)).isoformat(), "day_type": "home"},
            {"date": (today + _dt.timedelta(days=6)).isoformat(), "day_type": "rest"},
        ],
    }


class TestGap1RecoveryFirstLayover:
    def test_recovery_first_session_replaces_15min_mobility(self):
        u = _make_user("build_muscle")
        r = _make_roster_long_haul_into_layover()
        plan = build_template_plan(u, r, hotel_lookup=HOTEL_LOOKUP)
        day0 = r["days"][0]["date"]
        session_day0 = next((w for w in plan if w["date"] == day0), None)
        assert session_day0 is not None, "no session on the long-haul day"
        # The safety override title would be 'Flight Recovery Mobility' with 15 min.
        # Recovery-first session is a normal template with mobility PREPENDED.
        assert session_day0.get("recovery_first") is True, session_day0
        assert session_day0.get("day_load") == "amber"
        # Duration should be longer than the 15-min override (real session ran).
        assert (session_day0.get("duration_min") or 0) > 20

    def test_rpe_capped_at_seven(self):
        u = _make_user("build_muscle")
        r = _make_roster_long_haul_into_layover()
        plan = build_template_plan(u, r, hotel_lookup=HOTEL_LOOKUP)
        day0 = plan[0]  # first session
        assert day0.get("recovery_first") is True
        for ex in day0.get("exercises") or []:
            rpe = ex.get("rpe")
            if isinstance(rpe, (int, float)):
                assert rpe <= 7, f"RPE {rpe} on {ex.get('name')} exceeds cap 7"

    def test_flight_recovery_prepended_to_warmup(self):
        u = _make_user("build_muscle")
        r = _make_roster_long_haul_into_layover()
        plan = build_template_plan(u, r, hotel_lookup=HOTEL_LOOKUP)
        day0 = plan[0]
        warmup_names = [w.get("name") for w in (day0.get("warmup") or [])]
        # The FLIGHT_RECOVERY_MOBILITY set includes "Hip flexor stretch" and "Diaphragmatic breathing".
        assert any("hip flexor" in (n or "").lower() for n in warmup_names)
        assert any("diaphragmatic" in (n or "").lower() for n in warmup_names)

    def test_no_hotel_still_forces_safety_override(self):
        """If we don't know the hotel, we must NOT try to run a full session."""
        u = _make_user("build_muscle")
        r = _make_roster_long_haul_into_layover(hotel_id=None)
        # Remove hotel_id so lookup misses.
        r["days"][0].pop("hotel_id", None)
        plan = build_template_plan(u, r, hotel_lookup=HOTEL_LOOKUP)
        day0 = r["days"][0]["date"]
        session = next((w for w in plan if w["date"] == day0), None)
        # Safety override kicks in — 15-min mobility with RED load.
        assert session is not None
        assert session.get("day_load") == "red"
        assert (session.get("duration_min") or 0) <= 20
        assert not session.get("recovery_first")

    def test_endurance_slot_downshifted(self):
        """A marathon client whose weekly-shape wanted a long_run on the long-haul day
        should get an easy_run instead (never long_run) when recovery_first fires."""
        u = _make_user("event")
        u["profile"]["event_type_pref"] = "marathon"
        u["profile"]["weeks_to_race"] = 12
        r = _make_roster_long_haul_into_layover()
        plan = build_template_plan(u, r, hotel_lookup=HOTEL_LOOKUP)
        day0 = plan[0]
        title = (day0.get("title") or "").lower()
        assert "long run" not in title, day0
        # Long_run is >45 min; recovery_first easy run must be shorter.
        assert (day0.get("duration_min") or 999) <= 50


class TestRosterSummaryAnnotation:
    def test_recovery_first_days_populated(self):
        r = _make_roster_long_haul_into_layover()
        summary = _roster_summary(r)
        rfd = summary.get("recovery_first_days") or []
        assert r["days"][0]["date"] in rfd
        # Rest days are NOT recovery-first
        assert r["days"][3]["date"] not in rfd

    def test_no_hotel_no_flag(self):
        r = _make_roster_long_haul_into_layover()
        r["days"][0].pop("hotel_id", None)
        summary = _roster_summary(r)
        assert r["days"][0]["date"] not in (summary.get("recovery_first_days") or [])
