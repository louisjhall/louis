"""
Phase 4 — Coach dashboard integration tests.

Covers:
  * GET /api/coach/dashboard exposes counts.hotels_pending_review
  * GET /api/coach/dashboard exposes progression_pill on each client summary
  * GET /api/coach/clients/{cid} exposes progression_pill on the client doc
  * Coach hotel review queue + verify still works (regression check for Phase 1)
"""
import sys
import uuid as _uuid
sys.path.insert(0, "/app/backend")


def test_dashboard_returns_hotels_pending_review_count(api, base_url, coach_auth):
    r = api.get(f"{base_url}/api/coach/dashboard", headers=coach_auth["headers"], timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    counts = body.get("counts") or {}
    assert "hotels_pending_review" in counts
    assert isinstance(counts["hotels_pending_review"], int)
    assert counts["hotels_pending_review"] >= 0


def test_dashboard_clients_expose_progression_pill_key(api, base_url, coach_auth):
    r = api.get(f"{base_url}/api/coach/dashboard", headers=coach_auth["headers"], timeout=30)
    assert r.status_code == 200
    clients = r.json().get("clients") or []
    # progression_pill key should be present on every client (may be None)
    for c in clients:
        assert "progression_pill" in c


def test_client_detail_exposes_progression_pill(api, base_url, coach_auth, client_auth):
    cid = client_auth["user"]["id"]
    r = api.get(f"{base_url}/api/coach/clients/{cid}", headers=coach_auth["headers"], timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert "client" in body
    # progression_pill is present on client (may be None if no snapshot yet)
    assert "progression_pill" in (body.get("client") or {})


def test_dashboard_hotels_pending_review_reflects_new_low_conf_submission(
    api, base_url, coach_auth, client_auth
):
    # Baseline
    r0 = api.get(f"{base_url}/api/coach/dashboard", headers=coach_auth["headers"], timeout=30)
    baseline = (r0.json().get("counts") or {}).get("hotels_pending_review", 0)

    # Client submits a fresh hotel (starts at confidence 0.5 → low-conf)
    tag = _uuid.uuid4().hex[:6]
    api.post(
        f"{base_url}/api/hotels",
        json={"name": f"CrewFit Phase4 Hotel {tag}", "city": "Auckland", "gym_type": "unknown"},
        headers=client_auth["headers"],
        timeout=30,
    )

    r1 = api.get(f"{base_url}/api/coach/dashboard", headers=coach_auth["headers"], timeout=30)
    now = (r1.json().get("counts") or {}).get("hotels_pending_review", 0)
    assert now >= baseline + 1, f"Expected review queue depth to grow from {baseline}, got {now}"


def test_coach_can_verify_hotel_from_queue(api, base_url, coach_auth, client_auth):
    # Client creates a fresh low-confidence hotel
    tag = _uuid.uuid4().hex[:6]
    r = api.post(
        f"{base_url}/api/hotels",
        json={"name": f"CrewFit Phase4 Verify {tag}", "city": "Reykjavik", "gym_type": "basic"},
        headers=client_auth["headers"],
        timeout=30,
    )
    hid = r.json()["id"]

    # Queue must include it
    q = api.get(f"{base_url}/api/coach/hotels/review-queue", headers=coach_auth["headers"], timeout=30)
    assert q.status_code == 200
    assert any(h["id"] == hid for h in q.json())

    # Verify
    v = api.post(f"{base_url}/api/coach/hotels/{hid}/verify", headers=coach_auth["headers"], timeout=30)
    assert v.status_code == 200
    assert v.json().get("verified_by_coach") is True

    # After verify → confidence bumped, should NOT reappear in the queue for
    # this hotel (unless another low-conf hotel with the same id — impossible).
    q2 = api.get(f"{base_url}/api/coach/hotels/review-queue", headers=coach_auth["headers"], timeout=30)
    assert not any(h["id"] == hid for h in q2.json())
