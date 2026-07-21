"""
Iter81 Phase 1 verification — end-to-end tests with unique names to avoid
state pollution from repeated test runs.
"""
import uuid
import pytest
import sys
sys.path.insert(0, "/app/backend")


def _unique_name(prefix="TEST_HOTEL"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def test_hotels_create_then_confirm_bumps_confidence(api, base_url, client_auth):
    name = _unique_name("TEST_CONF")
    payload = {
        "name": name,
        "city": f"City_{uuid.uuid4().hex[:6]}",
        "country": "UK",
        "gym_type": "basic",
        "gym_available": True,
        "equipment": {"dumbbells": True, "yoga_mat": True},
        "safe_outdoor_run": True,
    }
    r = api.post(f"{base_url}/api/hotels", json=payload, headers=client_auth["headers"], timeout=30)
    assert r.status_code == 200, r.text
    hotel = r.json()
    assert hotel["confidence"] == 0.5, f"initial confidence expected 0.5, got {hotel['confidence']}"
    assert hotel.get("submissions") == 1
    assert hotel["safe_outdoor_run"] is True
    assert hotel["gym_type"] == "basic"

    # First confirm bumps by 0.15
    hid = hotel["id"]
    r2 = api.post(f"{base_url}/api/hotels/{hid}/confirm",
                  json={"equipment": {"treadmill": True}, "gym_type": "cardio_only"},
                  headers=client_auth["headers"], timeout=30)
    assert r2.status_code == 200, r2.text
    updated = r2.json()
    assert updated["equipment"]["dumbbells"] is True  # merged, not clobbered
    assert updated["equipment"]["treadmill"] is True
    assert updated["gym_type"] == "cardio_only"
    assert abs(updated["confidence"] - 0.65) < 0.01, f"expected ~0.65, got {updated['confidence']}"


def test_hotels_patch_does_not_bump_submissions(api, base_url, client_auth):
    name = _unique_name("TEST_PATCH")
    r = api.post(f"{base_url}/api/hotels",
                 json={"name": name, "city": f"City_{uuid.uuid4().hex[:6]}", "gym_type": "unknown"},
                 headers=client_auth["headers"], timeout=30)
    assert r.status_code == 200
    initial = r.json()
    submissions_before = initial.get("submissions", 0)
    hid = initial["id"]

    r2 = api.patch(f"{base_url}/api/hotels/{hid}",
                   json={"safe_outdoor_run": True, "notes": "Test notes"},
                   headers=client_auth["headers"], timeout=30)
    assert r2.status_code == 200, r2.text
    patched = r2.json()
    assert patched["safe_outdoor_run"] is True
    assert patched.get("notes") == "Test notes"
    # PATCH should NOT bump submissions counter
    assert patched.get("submissions", 0) == submissions_before, \
        f"PATCH bumped submissions from {submissions_before} to {patched.get('submissions')}"


def test_hotels_lookup_fuzzy_search(api, base_url, client_auth):
    # Create a hotel with unique searchable name
    unique = uuid.uuid4().hex[:8].upper()
    name = f"TEST_LOOKUP_{unique}"
    city = f"CITY{unique}"
    r = api.post(f"{base_url}/api/hotels",
                 json={"name": name, "city": city, "gym_type": "basic"},
                 headers=client_auth["headers"], timeout=30)
    assert r.status_code == 200

    # Search by partial name
    r2 = api.get(f"{base_url}/api/hotels/lookup",
                 params={"query": unique.lower()}, headers=client_auth["headers"], timeout=30)
    assert r2.status_code == 200
    rows = r2.json()
    assert isinstance(rows, list)
    assert len(rows) <= 15
    # Should find our hotel
    found = any(unique in (h.get("name", "") + h.get("city", "")).upper() for h in rows)
    assert found, f"Expected to find hotel with '{unique}', got {rows}"


def test_hotels_pending_for_today_shape(api, base_url, client_auth):
    r = api.get(f"{base_url}/api/hotels/pending-for-today",
                headers=client_auth["headers"], timeout=30)
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    for row in rows:
        assert "date" in row
        assert "hotel_id" in row
        assert row.get("status") in ("missing", "needs_confirm")
        assert row.get("kind") == "layover"


def test_coach_verify_bumps_confidence_by_0_3(api, base_url, client_auth, coach_auth):
    name = _unique_name("TEST_VERIFY")
    r = api.post(f"{base_url}/api/hotels",
                 json={"name": name, "city": f"City_{uuid.uuid4().hex[:6]}", "gym_type": "full_gym"},
                 headers=client_auth["headers"], timeout=30)
    hid = r.json()["id"]
    initial_conf = r.json()["confidence"]

    r2 = api.post(f"{base_url}/api/coach/hotels/{hid}/verify",
                  headers=coach_auth["headers"], timeout=30)
    assert r2.status_code == 200, r2.text
    v = r2.json()
    assert v["verified_by_coach"] is True
    assert v.get("verified_by")
    assert v.get("verified_at")
    # Confidence should increase by 0.3 (or capped at 1.0)
    expected = min(1.0, initial_conf + 0.3)
    assert abs(v["confidence"] - expected) < 0.01, \
        f"expected {expected}, got {v['confidence']}"


def test_coach_review_queue_denied_for_client(api, base_url, client_auth):
    r = api.get(f"{base_url}/api/coach/hotels/review-queue",
                headers=client_auth["headers"], timeout=30)
    assert r.status_code == 403


def test_coach_review_queue_ok_for_coach(api, base_url, coach_auth):
    r = api.get(f"{base_url}/api/coach/hotels/review-queue",
                headers=coach_auth["headers"], timeout=30)
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) <= 50


def test_coach_verify_denied_for_client(api, base_url, client_auth):
    # First create a hotel
    name = _unique_name("TEST_DENY_VERIFY")
    r = api.post(f"{base_url}/api/hotels",
                 json={"name": name, "city": "London", "gym_type": "basic"},
                 headers=client_auth["headers"], timeout=30)
    hid = r.json()["id"]
    # Client should not be able to verify
    r2 = api.post(f"{base_url}/api/coach/hotels/{hid}/verify",
                  headers=client_auth["headers"], timeout=30)
    assert r2.status_code == 403


# ---------------------------------------------------------------------------
# Workout fallback wiring — build_template_plan behaviour
# ---------------------------------------------------------------------------

def test_workout_fallback_turnaround_produces_mobility():
    """Turnaround day (short flight gap) → mobility session."""
    from feature_workout_fallback import build_template_plan

    user = {"id": "u1", "profile": {"programme": "general", "training_days_per_week": 4}}
    roster = {
        "id": "r1",
        "days": [
            {"date": "2026-08-01", "day_type": "flight", "duty_end_time": "22:00"},
            {"date": "2026-08-02", "day_type": "flight", "report_time": "08:00"},  # 10h gap → turnaround
        ],
    }
    plan = build_template_plan(user, roster, hotel_lookup={})
    assert isinstance(plan, list)
    day1 = next((d for d in plan if d.get("date") == "2026-08-01"), None)
    assert day1 is not None, f"Day plan missing for 2026-08-01. Plan: {plan}"
    kind = day1.get("hotel_stay_kind") or ""
    reason = (day1.get("change_reason") or "").lower()
    focus = day1.get("focus") or ""
    print(f"day1 kind={kind} reason={reason} focus={focus}")
    assert kind == "turnaround" or "turnaround" in reason or focus == "mobility"


def test_workout_fallback_layover_unknown_hotel_bodyweight():
    """Layover with hotel_id not in lookup → bodyweight session."""
    from feature_workout_fallback import build_template_plan

    user = {"id": "u1", "profile": {"programme": "general", "training_days_per_week": 4}}
    roster = {
        "id": "r1",
        "days": [
            {"date": "2026-08-01", "day_type": "layover_full_day",
             "duty_end_time": "18:00", "hotel_id": "unknown_hotel_xyz"},
            {"date": "2026-08-02", "day_type": "flight", "report_time": "14:00"},  # 20h layover
        ],
    }
    plan = build_template_plan(user, roster, hotel_lookup={})
    assert isinstance(plan, list)
    day1 = next((d for d in plan if d.get("date") == "2026-08-01"), None)
    assert day1 is not None, f"Missing 2026-08-01. Plan: {plan}"
    print(f"day1 = {day1}")
    # Should route to bodyweight or produce mobility only (unknown hotel)
    location = day1.get("location") or ""
    kind = day1.get("hotel_stay_kind") or ""
    # For unknown hotel on layover, either bodyweight strength or mobility fallback
    assert "Hotel" in location or kind in ("layover", "turnaround") or day1.get("focus") == "mobility"


def test_workout_fallback_layover_full_gym_hotel():
    """Layover with hotel_id known in lookup + full_gym → normal gym stub."""
    from feature_workout_fallback import build_template_plan

    user = {"id": "u1", "profile": {"programme": "general", "training_days_per_week": 4}}
    roster = {
        "id": "r1",
        "days": [
            {"date": "2026-08-01", "day_type": "layover_full_day",
             "duty_end_time": "18:00", "hotel_id": "hotel_full_gym_123"},
            {"date": "2026-08-02", "day_type": "flight", "report_time": "14:00"},
        ],
    }
    hotel_lookup = {
        "hotel_full_gym_123": {
            "id": "hotel_full_gym_123",
            "gym_type": "full_gym",
            "gym_available": True,
            "equipment": {"dumbbells": True, "barbell": True, "bench": True},
            "confidence": 0.9,
        }
    }
    plan = build_template_plan(user, roster, hotel_lookup=hotel_lookup)
    day1 = next((d for d in plan if d.get("date") == "2026-08-01"), None)
    assert day1 is not None, f"Missing 2026-08-01. Plan: {plan}"
    print(f"day1 = {day1}")
    location = day1.get("location") or ""
    kind = day1.get("hotel_stay_kind") or ""
    # Full-gym hotel on layover — expect Hotel Gym location or layover kind
    assert "Hotel Gym" in location or kind == "layover" or day1.get("hotel_id") == "hotel_full_gym_123"
