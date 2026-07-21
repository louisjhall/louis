"""
Iter 82 — Unread messages count endpoint powers the client tab-bar badge.
"""
import sys
import uuid as _uuid
sys.path.insert(0, "/app/backend")


def test_unread_count_starts_at_zero_for_client(api, base_url, client_auth):
    r = api.get(f"{base_url}/api/messages-unread/count", headers=client_auth["headers"], timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "count" in body
    assert isinstance(body["count"], int)
    assert body["count"] >= 0


def test_unread_count_increases_when_coach_sends_message(api, base_url, coach_auth, client_auth):
    # Baseline
    r0 = api.get(f"{base_url}/api/messages-unread/count", headers=client_auth["headers"], timeout=30)
    baseline = r0.json()["count"]

    # Coach sends a message to the client
    cid = client_auth["user"]["id"]
    tag = _uuid.uuid4().hex[:6]
    send = api.post(
        f"{base_url}/api/messages",
        json={"to_user_id": cid, "text": f"Test unread {tag}"},
        headers=coach_auth["headers"],
        timeout=30,
    )
    assert send.status_code == 200, send.text

    # Count should be +1 for the client
    r1 = api.get(f"{base_url}/api/messages-unread/count", headers=client_auth["headers"], timeout=30)
    assert r1.json()["count"] == baseline + 1


def test_reading_thread_marks_messages_as_read(api, base_url, coach_auth, client_auth):
    coach_id = coach_auth["user"]["id"]
    cid = client_auth["user"]["id"]

    # Baseline unread count from the current coach
    r_base = api.get(f"{base_url}/api/messages-unread/count", headers=client_auth["headers"], timeout=30)
    baseline_all = r_base.json()["count"]

    # Coach sends 2 fresh messages
    for _ in range(2):
        tag = _uuid.uuid4().hex[:6]
        api.post(
            f"{base_url}/api/messages",
            json={"to_user_id": cid, "text": f"Bump {tag}"},
            headers=coach_auth["headers"],
            timeout=30,
        )

    r_after_send = api.get(f"{base_url}/api/messages-unread/count", headers=client_auth["headers"], timeout=30)
    assert r_after_send.json()["count"] == baseline_all + 2, "count must increase by 2"

    # Client fetches the thread — this should mark THESE two as read
    r = api.get(
        f"{base_url}/api/messages/{coach_id}",
        headers=client_auth["headers"],
        timeout=30,
    )
    assert r.status_code == 200

    # Recount — should be back to the baseline (i.e. the 2 we just sent
    # from THIS coach are now read; anything else was pre-existing).
    r2 = api.get(f"{base_url}/api/messages-unread/count", headers=client_auth["headers"], timeout=30)
    assert r2.json()["count"] <= baseline_all, \
        f"Reading the thread should NOT increase count. baseline={baseline_all}, now={r2.json()['count']}"
