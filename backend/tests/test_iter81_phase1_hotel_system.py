"""
Phase 1 — Hotel System tests.

Covers:
  * classify_stay (turnaround < 18h, layover ≥ 18h, edge cases)
  * compute_layover_hours math
  * is_bodyweight_only / gym_type presets
  * reason_for strings
  * /api/hotels/lookup returns rows
  * /api/hotels + /api/hotels/{id}/confirm bumps confidence
  * /api/hotels/pending-for-today surface layover days
  * /api/coach/hotels/review-queue coach-only
"""
import pytest
import sys
sys.path.insert(0, "/app/backend")

from feature_hotel_system import (
    LAYOVER_THRESHOLD_HOURS,
    classify_stay,
    compute_layover_hours,
    is_bodyweight_only,
    is_low_confidence,
    reason_for,
    resolve_gym_equipment,
    REASON_STRINGS,
)


# ---------------------------------------------------------------------------
# Pure module tests (no HTTP)
# ---------------------------------------------------------------------------

def test_compute_layover_hours_normal():
    day = {"date": "2026-07-21", "duty_end_time": "18:00"}
    nxt = {"date": "2026-07-22", "report_time": "14:00"}
    assert compute_layover_hours(day, nxt) == 20.0


def test_compute_layover_hours_short_turnaround():
    day = {"date": "2026-07-21", "duty_end_time": "23:30"}
    nxt = {"date": "2026-07-22", "report_time": "07:30"}
    assert compute_layover_hours(day, nxt) == 8.0


def test_compute_layover_hours_missing():
    assert compute_layover_hours({"date": "2026-07-21"}, None) is None
    assert compute_layover_hours({}, {"date": "2026-07-22", "report_time": "10:00"}) is None


def test_classify_stay_off():
    assert classify_stay({"day_type": "rest"}) == "off"
    assert classify_stay({"day_type": "annual_leave"}) == "off"


def test_classify_stay_long_layover():
    day = {"day_type": "layover_full_day", "date": "2026-07-21", "duty_end_time": "18:00"}
    nxt = {"date": "2026-07-22", "report_time": "14:00"}  # 20h
    assert classify_stay(day, nxt) == "layover"


def test_classify_stay_short_layover_downgrades():
    day = {"day_type": "layover_arrival", "date": "2026-07-21", "duty_end_time": "22:00"}
    nxt = {"date": "2026-07-22", "report_time": "10:00"}  # 12h
    assert classify_stay(day, nxt) == "turnaround"


def test_classify_stay_turnaround():
    day = {"day_type": "turnaround"}
    assert classify_stay(day) == "turnaround"


def test_classify_stay_flight_with_short_gap():
    day = {"day_type": "flight", "date": "2026-07-21", "duty_end_time": "20:00"}
    nxt = {"date": "2026-07-22", "report_time": "05:00"}  # 9h
    assert classify_stay(day, nxt) == "turnaround"


def test_classify_stay_flight_with_long_gap():
    day = {"day_type": "flight", "date": "2026-07-21", "duty_end_time": "12:00"}
    nxt = {"date": "2026-07-22", "report_time": "18:00"}  # 30h
    assert classify_stay(day, nxt) == "layover"


def test_is_bodyweight_only_none_doc():
    assert is_bodyweight_only(None) is True


def test_is_bodyweight_only_no_gym():
    assert is_bodyweight_only({"gym_available": False, "gym_type": "full_gym"}) is True


def test_is_bodyweight_only_unknown_type():
    assert is_bodyweight_only({"gym_type": "unknown", "equipment": {}}) is True


def test_is_bodyweight_only_full_gym():
    assert is_bodyweight_only({"gym_type": "full_gym", "equipment": {"dumbbells": True}}) is False


def test_resolve_gym_equipment_from_preset():
    doc = {"gym_type": "full_gym", "equipment": {}}
    eq = resolve_gym_equipment(doc)
    assert eq.get("dumbbells") is True
    assert eq.get("barbell") is True


def test_resolve_gym_equipment_from_explicit():
    doc = {"gym_type": "basic", "equipment": {"dumbbells": True, "yoga_mat": True}}
    eq = resolve_gym_equipment(doc)
    assert eq == {"dumbbells": True, "yoga_mat": True}


def test_reason_for_unknown_hotel():
    day = {"day_type": "layover", "date": "2026-07-21", "duty_end_time": "18:00"}
    nxt = {"date": "2026-07-22", "report_time": "14:00"}
    r = reason_for(day, None, nxt)
    assert r == REASON_STRINGS["hotel_unknown"]


def test_reason_for_bodyweight_only_hotel():
    day = {"day_type": "layover", "date": "2026-07-21", "duty_end_time": "18:00"}
    nxt = {"date": "2026-07-22", "report_time": "14:00"}
    hotel = {"gym_type": "none", "confidence": 0.8}
    r = reason_for(day, hotel, nxt)
    assert r == REASON_STRINGS["hotel_bodyweight_only"]


def test_reason_for_turnaround():
    day = {"day_type": "flight", "date": "2026-07-21", "duty_end_time": "22:00"}
    nxt = {"date": "2026-07-22", "report_time": "08:00"}
    r = reason_for(day, None, nxt)
    assert r == REASON_STRINGS["turnaround_short"]


def test_is_low_confidence():
    assert is_low_confidence({"confidence": 0.4}) is True
    assert is_low_confidence({"confidence": 0.8}) is False
    # Coach-verified boosts confidence
    assert is_low_confidence({"confidence": 0.4, "verified_by_coach": True}) is False


def test_layover_threshold_is_18():
    assert LAYOVER_THRESHOLD_HOURS == 18


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------

def test_hotels_lookup_public(api, base_url, client_auth):
    r = api.get(f"{base_url}/api/hotels/lookup", params={"query": "dubai"}, headers=client_auth["headers"], timeout=30)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)


def test_hotels_create_and_confirm(api, base_url, client_auth):
    # Create
    payload = {
        "name": "CrewFit Test Hotel",
        "city": "London",
        "country": "UK",
        "gym_type": "basic",
        "gym_available": True,
        "equipment": {"dumbbells": True, "yoga_mat": True},
        "safe_outdoor_run": True,
    }
    r = api.post(f"{base_url}/api/hotels", json=payload, headers=client_auth["headers"], timeout=30)
    assert r.status_code == 200, r.text
    hotel = r.json()
    assert hotel["gym_type"] == "basic"
    assert hotel["equipment"]["dumbbells"] is True
    assert hotel["confidence"] >= 0.5

    # Confirm — bumps confidence + patches equipment
    hid = hotel["id"]
    conf_payload = {"equipment": {"treadmill": True}, "gym_type": "cardio_only"}
    r2 = api.post(f"{base_url}/api/hotels/{hid}/confirm", json=conf_payload, headers=client_auth["headers"], timeout=30)
    assert r2.status_code == 200, r2.text
    updated = r2.json()
    # Equipment merged, not replaced
    assert updated["equipment"]["dumbbells"] is True
    assert updated["equipment"]["treadmill"] is True
    assert updated["gym_type"] == "cardio_only"
    assert updated["confidence"] > hotel["confidence"]


def test_hotels_patch(api, base_url, client_auth):
    payload = {"name": "CrewFit Patch Hotel", "city": "Singapore", "gym_type": "unknown"}
    r = api.post(f"{base_url}/api/hotels", json=payload, headers=client_auth["headers"], timeout=30)
    assert r.status_code == 200
    hid = r.json()["id"]
    r2 = api.patch(f"{base_url}/api/hotels/{hid}", json={"safe_outdoor_run": True}, headers=client_auth["headers"], timeout=30)
    assert r2.status_code == 200
    assert r2.json()["safe_outdoor_run"] is True


def test_hotels_pending_for_today(api, base_url, client_auth):
    r = api.get(f"{base_url}/api/hotels/pending-for-today", headers=client_auth["headers"], timeout=30)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_coach_hotels_review_queue_denied_for_client(api, base_url, client_auth):
    r = api.get(f"{base_url}/api/coach/hotels/review-queue", headers=client_auth["headers"], timeout=30)
    assert r.status_code == 403


def test_coach_hotels_review_queue_ok_for_coach(api, base_url, coach_auth):
    r = api.get(f"{base_url}/api/coach/hotels/review-queue", headers=coach_auth["headers"], timeout=30)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_coach_hotels_verify(api, base_url, coach_auth, client_auth):
    # Client creates a hotel
    r = api.post(f"{base_url}/api/hotels",
                 json={"name": "CrewFit Verify Hotel", "city": "Zurich", "gym_type": "full_gym"},
                 headers=client_auth["headers"], timeout=30)
    hid = r.json()["id"]
    # Coach verifies
    r2 = api.post(f"{base_url}/api/coach/hotels/{hid}/verify", headers=coach_auth["headers"], timeout=30)
    assert r2.status_code == 200, r2.text
    assert r2.json().get("verified_by_coach") is True
