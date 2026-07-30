"""Iter 129 — Crew Base UAT (§50–54).

Sync HTTP tests against the live backend. Matches the existing pytest
convention used by tests/test_iter128*.py — no async fixtures, no LLM
calls, no programme writes.
"""
from __future__ import annotations

import os
import time
from typing import Any

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

BASE = os.environ.get("EXPO_BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ.get("DB_NAME", "crewfit")

COACH = ("louis@crewfit.net", "Louis123!")
CLIENT_A = ("pietrosangermano1992@hotmail.com", "Crewfit2026!")
CLIENT_B = ("cbtest_b@crewfit.net", "CrewBase2026!")


def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def H(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def tokens():
    # Wipe collections before running
    m = MongoClient(MONGO_URL)[DB_NAME]
    m.crew_base_posts.delete_many({})
    m.crew_base_comments.delete_many({})
    m.crew_base_reactions.delete_many({})
    return {
        "coach": _login(*COACH),
        "a": _login(*CLIENT_A),
        "b": _login(*CLIENT_B),
    }


# ---------------------------------------------------------------------------
# Session state (post + comment ids shared across tests in module scope)
# ---------------------------------------------------------------------------
STATE: dict[str, Any] = {}


def test_01_coach_can_publish_and_client_sees_it(tokens):
    r = requests.post(f"{BASE}/crew-base/posts", headers=H(tokens["coach"]), json={
        "text": "Welcome to Crew Base 👋",
        "media_type": "none",
        "status": "published",
    }, timeout=15)
    assert r.status_code == 200, r.text
    p = r.json()["post"]
    assert p["status"] == "published"
    STATE["welcome_post_id"] = p["id"]

    feed = requests.get(f"{BASE}/crew-base/feed", headers=H(tokens["a"]), timeout=15).json()
    assert any(x["id"] == p["id"] for x in feed["posts"])


def test_02_initials_privacy_client_to_client(tokens):
    """§51 — Client A in initials mode. Client B must NOT see A's full name,
    email, or profile photo. Coach viewer receives coach_only.real_name."""
    # Force A into initials mode
    r = requests.patch(f"{BASE}/crew-base/settings", headers=H(tokens["a"]),
                       json={"crew_base_identity_mode": "initials"}, timeout=15)
    assert r.status_code == 200 and r.json()["crew_base_identity_mode"] == "initials"

    post_id = STATE["welcome_post_id"]
    r = requests.post(f"{BASE}/crew-base/posts/{post_id}/comments", headers=H(tokens["a"]),
                      json={"text": "Hotel gym today."}, timeout=15)
    assert r.status_code == 200

    # Client B fetch → author.public_name must be initials only, no photo, no coach_only
    b_view = requests.get(f"{BASE}/crew-base/posts/{post_id}/comments", headers=H(tokens["b"]), timeout=15).json()
    a_comment = next(c for c in b_view["comments"] if c["text"] == "Hotel gym today.")
    author = a_comment["author"]
    assert author["avatar_kind"] == "initials", author
    assert " " not in author["public_name"], f"full-name leak: {author['public_name']}"
    assert not author.get("avatar_photo_url"), "profile photo leaked in initials mode"
    assert "coach_only" not in author, "coach_only leaked to client viewer"
    # Ensure no email leaks
    payload_str = str(b_view)
    assert "pietrosangermano" not in payload_str.lower(), "email/username string leaked"

    # Coach view MUST include coach_only.real_name
    coach_view = requests.get(f"{BASE}/crew-base/posts/{post_id}/comments", headers=H(tokens["coach"]), timeout=15).json()
    ac = next(c for c in coach_view["comments"] if c["text"] == "Hotel gym today.")
    assert ac["author"].get("coach_only", {}).get("real_name")


def test_03_full_name_mode_updates_history(tokens):
    """§52 — Flipping identity_mode → full_name updates the public_name
    on historic comments (dynamic resolution, no migration required)."""
    r = requests.patch(f"{BASE}/crew-base/settings", headers=H(tokens["a"]),
                       json={"crew_base_identity_mode": "full_name"}, timeout=15)
    assert r.status_code == 200

    post_id = STATE["welcome_post_id"]
    b_view = requests.get(f"{BASE}/crew-base/posts/{post_id}/comments", headers=H(tokens["b"]), timeout=15).json()
    a_comment = next(c for c in b_view["comments"] if c["text"] == "Hotel gym today.")
    # Full name must contain a space now
    assert " " in a_comment["author"]["public_name"], f"history did not flip: {a_comment['author']['public_name']}"

    # Reset to initials for downstream tests
    requests.patch(f"{BASE}/crew-base/settings", headers=H(tokens["a"]),
                   json={"crew_base_identity_mode": "initials"}, timeout=15)


def test_04_wings_reaction_toggle(tokens):
    """One aviation-themed reaction. Toggle-on then toggle-off."""
    post_id = STATE["welcome_post_id"]

    r = requests.post(f"{BASE}/crew-base/posts/{post_id}/react", headers=H(tokens["a"]), json={}, timeout=15).json()
    assert r["viewer_reacted"] is True and r["kind"] == "wings" and r["count"] >= 1

    r2 = requests.post(f"{BASE}/crew-base/posts/{post_id}/react", headers=H(tokens["a"]), json={}, timeout=15).json()
    assert r2["viewer_reacted"] is False and r2["count"] == r["count"] - 1


def test_05_notification_toggle_isolated_from_messages_and_flight_support(tokens):
    """§50 + §16 + §37 + §38 — turning Crew Base OFF must not disable
    Messages / Flight Support / Training notifications."""
    db = MongoClient(MONGO_URL)[DB_NAME]
    b_user = db.users.find_one({"email": CLIENT_B[0]}, {"_id": 0, "id": 1})
    b_id = b_user["id"]

    # Baseline other categories to True
    db.users.update_one({"id": b_id}, {"$set": {
        "notification_settings.coach_messages": True,
        "notification_settings.flight_support": True,
        "notification_settings.workouts": True,
    }})

    # Toggle Crew Base OFF via API
    r = requests.patch(f"{BASE}/crew-base/settings", headers=H(tokens["b"]),
                       json={"crew_base_notifications_enabled": False}, timeout=15).json()
    assert r["crew_base_notifications_enabled"] is False

    fresh = db.users.find_one({"id": b_id}, {"_id": 0, "notification_settings": 1})
    ns = fresh.get("notification_settings") or {}
    assert ns.get("crew_base") is False
    assert ns.get("coach_messages") is True, "Messages toggle was affected"
    assert ns.get("flight_support") is True, "Flight Support toggle was affected"
    assert ns.get("workouts") is True, "Training toggle was affected"

    # Coach publishes a new post; B must NOT receive a crew_base_new_post row.
    before = db.notifications.count_documents({"user_id": b_id, "notif_type": "crew_base_new_post"})
    new_post = requests.post(f"{BASE}/crew-base/posts", headers=H(tokens["coach"]), json={
        "text": "Second post — after B toggled off",
        "media_type": "none",
        "status": "published",
    }, timeout=15).json()
    assert new_post["ok"]
    STATE["second_post_id"] = new_post["post"]["id"]

    time.sleep(1.5)   # fan-out is synchronous but async task-based
    after = db.notifications.count_documents({"user_id": b_id, "notif_type": "crew_base_new_post"})
    assert after == before, f"B got a crew_base notif despite OFF (before={before} after={after})"

    # B can still see the post — OFF means no push, NOT hidden feed
    feed = requests.get(f"{BASE}/crew-base/feed", headers=H(tokens["b"]), timeout=15).json()
    assert any(p["id"] == new_post["post"]["id"] for p in feed["posts"])

    # Re-enable
    requests.patch(f"{BASE}/crew-base/settings", headers=H(tokens["b"]),
                   json={"crew_base_notifications_enabled": True}, timeout=15)


def test_06_schedule_hidden_until_publish(tokens):
    """§54 — scheduled post must NOT surface in the client feed
    until it's published."""
    future_iso = "2099-12-31T00:00:00Z"
    r = requests.post(f"{BASE}/crew-base/posts", headers=H(tokens["coach"]), json={
        "text": "Future scheduled post",
        "media_type": "none",
        "status": "scheduled",
        "scheduled_at": future_iso,
    }, timeout=15).json()
    pid = r["post"]["id"]
    STATE["scheduled_post_id"] = pid

    feed = requests.get(f"{BASE}/crew-base/feed", headers=H(tokens["a"]), timeout=15).json()
    assert not any(p["id"] == pid for p in feed["posts"]), "scheduled post leaked to client feed"

    sched = requests.get(f"{BASE}/crew-base/coach/scheduled", headers=H(tokens["coach"]), timeout=15).json()
    assert any(p["id"] == pid for p in sched["posts"])

    # Coach forces publish now
    requests.post(f"{BASE}/crew-base/posts/{pid}/publish", headers=H(tokens["coach"]), json={}, timeout=15)

    feed2 = requests.get(f"{BASE}/crew-base/feed", headers=H(tokens["a"]), timeout=15).json()
    assert any(p["id"] == pid for p in feed2["posts"])


def test_07_client_cannot_create_post(tokens):
    r = requests.post(f"{BASE}/crew-base/posts", headers=H(tokens["a"]), json={
        "text": "Trying as client", "media_type": "none", "status": "published"
    }, timeout=15)
    assert r.status_code in (401, 403), f"client managed to create post: {r.status_code} / {r.text}"


def test_08_coach_can_delete_comment(tokens):
    post_id = STATE["welcome_post_id"]
    made = requests.post(f"{BASE}/crew-base/posts/{post_id}/comments", headers=H(tokens["a"]),
                        json={"text": "This will be moderated."}, timeout=15).json()
    cid = made["comment"]["id"]
    r = requests.delete(f"{BASE}/crew-base/comments/{cid}", headers=H(tokens["coach"]), timeout=15)
    assert r.status_code == 200
    listing = requests.get(f"{BASE}/crew-base/posts/{post_id}/comments", headers=H(tokens["a"]), timeout=15).json()
    assert not any(c["id"] == cid for c in listing["comments"])


def test_09_reactions_expose_only_count_not_reactor_names(tokens):
    """§30 — feed post payload includes a numeric count only, never a
    reactor list."""
    feed = requests.get(f"{BASE}/crew-base/feed", headers=H(tokens["b"]), timeout=15).json()
    for p in feed["posts"]:
        assert "reactions" in p
        assert "count" in p["reactions"]
        assert "viewer_reacted" in p["reactions"]
        # Should not expose a list of who reacted
        assert "reactor_ids" not in p["reactions"]
        assert "reactors" not in p["reactions"]


def test_10_test_accounts_excluded_from_fanout(tokens):
    """§41 + §55 — Test/sandbox/reviewer accounts must be excluded from
    the notification fan-out. Reviewer account is tagged with 'reviewer'
    email + reviewer role in most orgs. We simply verify that clients
    tagged as such receive zero crew_base_new_post rows across the
    session."""
    db = MongoClient(MONGO_URL)[DB_NAME]
    # Tag reviewer explicitly
    db.users.update_one(
        {"email": CLIENT_B[0]},
        {"$addToSet": {"tags": "reviewer"}},
    )
    # Publish another post — B should get zero
    before = db.notifications.count_documents(
        {"user_id": {"$exists": True}, "notif_type": "crew_base_new_post"}
    )
    r = requests.post(f"{BASE}/crew-base/posts", headers=H(tokens["coach"]), json={
        "text": "Fan-out with reviewer tagged",
        "media_type": "none",
        "status": "published",
    }, timeout=15)
    assert r.status_code == 200

    time.sleep(1.2)
    # Find reviewer id
    b_id = db.users.find_one({"email": CLIENT_B[0]}, {"_id": 0, "id": 1})["id"]
    b_rows = db.notifications.count_documents(
        {"user_id": b_id, "notif_type": "crew_base_new_post",
         "related_id": r.json()["post"]["id"]}
    )
    assert b_rows == 0, "reviewer-tagged account still received crew_base fan-out"
    # cleanup tag
    db.users.update_one({"email": CLIENT_B[0]}, {"$pull": {"tags": "reviewer"}})
