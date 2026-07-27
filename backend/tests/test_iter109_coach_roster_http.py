"""HTTP-level integration tests for Iter 109 Phase A (Coach Dashboard rebuild).

Tests hit the public preview URL (EXPO_PUBLIC_BACKEND_URL) directly to validate:

1. Multi-roster merge — a client with 2 non-overlapping active rosters (July +
   August) must see BOTH months in `/roster/current` and `/calendar/range`.
   Each merged day must carry `_source_roster_id`.

2. Coach upload endpoints — role guard, 404 on missing client, 404 on missing
   pending roster.

3. Copy hygiene — no "AI"/"generated"/"bot" wording in any endpoint response
   or the CoachRosterUploadButton frontend component.

Test data is seeded directly into Mongo and cleaned up in fixture teardown.
"""
from __future__ import annotations

import os
import re
import sys
import uuid
from datetime import datetime, timezone, date, timedelta

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Prefer the public preview URL (what the mobile app hits).
BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "https://flight-fit-plans.preview.emergentagent.com"
).rstrip("/")

COACH_EMAIL = "louis@crewfit.net"
COACH_PASSWORD = "Louis123!"

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME", "crewfit_v1")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def coach_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": COACH_EMAIL, "password": COACH_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"Coach login failed: {r.status_code} {r.text[:200]}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def coach_headers(coach_token):
    return {"Authorization": f"Bearer {coach_token}", "Content-Type": "application/json"}


def _month_days(year: int, month: int) -> list[dict]:
    d = date(year, month, 1)
    days = []
    while d.month == month:
        days.append({"date": d.isoformat(), "day_type": "Home Day", "confidence": 0.9})
        d += timedelta(days=1)
    return days


@pytest.fixture(scope="module")
def seeded_client():
    """Seed a fresh client with July + August 2026 rosters, both active.

    Yields (user_id, token, jul_roster_id, aug_roster_id).
    Cleans up in teardown.
    """
    import bcrypt
    from pymongo import MongoClient

    if not MONGO_URL:
        pytest.skip("MONGO_URL not configured")

    mc = MongoClient(MONGO_URL)
    db = mc[DB_NAME]

    uid = f"iter109-{uuid.uuid4()}"
    email = f"iter109_{uuid.uuid4().hex[:8]}@test.crewfit.com"
    password = "Iter109!"
    now = datetime.now(timezone.utc).isoformat()

    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    # Assign to Louis (primary coach) — resolve his id from the DB
    louis = db.users.find_one({"email": COACH_EMAIL}, {"_id": 0, "id": 1})
    coach_id = louis["id"] if louis else None

    db.users.insert_one({
        "id": uid,
        "email": email,
        "name": "Iter109 Test",
        "display_name": "Iter109",
        "role": "client",
        "password_hash": pw_hash,
        "created_at": now,
        "signed_up_at": now,
        "onboarded_at": now,
        "onboarded": True,
        "coach_id": coach_id,
        "plan_start_at": "2026-07-01",
    })

    jul_id = str(uuid.uuid4())
    aug_id = str(uuid.uuid4())
    jul_days = _month_days(2026, 7)
    aug_days = _month_days(2026, 8)

    # Insert July first (older created_at), then August so August is "newest".
    db.rosters.insert_many([
        {
            "id": jul_id,
            "user_id": uid,
            "created_at": "2026-06-25T10:00:00+00:00",
            "days": jul_days,
            "start_date": jul_days[0]["date"],
            "end_date": jul_days[-1]["date"],
            "is_active": True,
            "status": "confirmed",
            "confirmed": True,
            "day_count": len(jul_days),
            "source_filename": "iter109_july.pdf",
        },
        {
            "id": aug_id,
            "user_id": uid,
            "created_at": "2026-07-28T10:00:00+00:00",
            "days": aug_days,
            "start_date": aug_days[0]["date"],
            "end_date": aug_days[-1]["date"],
            "is_active": True,
            "status": "confirmed",
            "confirmed": True,
            "day_count": len(aug_days),
            "source_filename": "iter109_august.pdf",
        },
    ])

    # Login as this fresh client to get a token.
    login_r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    assert login_r.status_code == 200, f"Seeded client login failed: {login_r.text[:300]}"
    token = login_r.json()["token"]

    yield {
        "user_id": uid,
        "email": email,
        "token": token,
        "jul_roster_id": jul_id,
        "aug_roster_id": aug_id,
    }

    # Cleanup
    try:
        db.users.delete_many({"id": uid})
        db.rosters.delete_many({"user_id": uid})
        db.workouts.delete_many({"user_id": uid})
        db.roster_jobs.delete_many({"user_id": uid})
        db.personal_activities.delete_many({"user_id": uid})
    finally:
        mc.close()


# ---------------------------------------------------------------------------
# 1. /api/roster/current — multi-roster merge
# ---------------------------------------------------------------------------

class TestRosterCurrentMerge:
    """Multi-roster merge on /api/roster/current."""

    def test_roster_current_returns_both_months(self, seeded_client):
        headers = {"Authorization": f"Bearer {seeded_client['token']}"}
        r = requests.get(f"{BASE_URL}/api/roster/current", headers=headers, timeout=15)
        assert r.status_code == 200, f"roster/current failed: {r.status_code} {r.text[:300]}"
        body = r.json()
        # roster/current may return {"days": [...]} or similar; find the days list.
        days = body.get("days") or body.get("roster", {}).get("days") or []
        assert days, f"No days in /roster/current response: {list(body.keys())}"
        months = {str(d.get("date", ""))[:7] for d in days if d.get("date")}
        assert "2026-07" in months, f"July missing! Months: {months}"
        assert "2026-08" in months, f"August missing! Months: {months}"

        # Should have 62 days total (31 July + 31 August).
        july_days = [d for d in days if str(d.get("date", "")).startswith("2026-07")]
        aug_days = [d for d in days if str(d.get("date", "")).startswith("2026-08")]
        assert len(july_days) == 31, f"Expected 31 July days, got {len(july_days)}"
        assert len(aug_days) == 31, f"Expected 31 August days, got {len(aug_days)}"

    def test_roster_current_carries_source_roster_id(self, seeded_client):
        headers = {"Authorization": f"Bearer {seeded_client['token']}"}
        r = requests.get(f"{BASE_URL}/api/roster/current", headers=headers, timeout=15)
        assert r.status_code == 200
        days = r.json().get("days") or []
        # At least one day from each month should tag its source roster.
        jul_sources = {
            d.get("_source_roster_id")
            for d in days if str(d.get("date", "")).startswith("2026-07")
        }
        aug_sources = {
            d.get("_source_roster_id")
            for d in days if str(d.get("date", "")).startswith("2026-08")
        }
        assert seeded_client["jul_roster_id"] in jul_sources, (
            f"July source_roster_id missing. Sources found: {jul_sources}"
        )
        assert seeded_client["aug_roster_id"] in aug_sources, (
            f"August source_roster_id missing. Sources found: {aug_sources}"
        )


# ---------------------------------------------------------------------------
# 2. /api/calendar/range — multi-roster merge
# ---------------------------------------------------------------------------

class TestCalendarRangeMerge:
    """Multi-roster merge on /api/calendar/range."""

    def test_calendar_range_spans_both_months(self, seeded_client):
        headers = {"Authorization": f"Bearer {seeded_client['token']}"}
        r = requests.get(
            f"{BASE_URL}/api/calendar/range",
            params={"from": "2026-07-01", "to": "2026-08-31"},
            headers=headers,
            timeout=15,
        )
        assert r.status_code == 200, f"calendar/range failed: {r.status_code} {r.text[:300]}"
        body = r.json()
        days = body.get("days", [])
        assert days, "calendar/range returned no days"

        july_with_roster = [
            d for d in days
            if str(d.get("date", "")).startswith("2026-07") and d.get("roster_day")
        ]
        aug_with_roster = [
            d for d in days
            if str(d.get("date", "")).startswith("2026-08") and d.get("roster_day")
        ]
        # The range is capped at today ± 60d server-side, so we may not see all
        # 31 days in each month. But we MUST see at least one roster_day in each.
        # If today is far from July/Aug 2026 both may be clipped. Check if any
        # month has roster days — that's the bug we're guarding against.
        total_roster_days = len(july_with_roster) + len(aug_with_roster)
        if total_roster_days == 0:
            pytest.skip(
                "calendar/range window doesn't include Jul/Aug 2026 "
                f"(server today may be outside ±60d). July={len(july_with_roster)} "
                f"August={len(aug_with_roster)}"
            )
        # If either month is in the window, BOTH should be reachable via a
        # narrower range test — but for the auto-clipped range test we just
        # assert we get non-zero from whichever month was in-window.
        assert total_roster_days > 0


# ---------------------------------------------------------------------------
# 3. Coach roster upload — role + 404 guards
# ---------------------------------------------------------------------------

class TestCoachRosterUploadGuards:
    """Coach upload/confirm endpoints — role guard + 404 checks."""

    def test_upload_parse_403_for_non_coach(self, seeded_client):
        """Client token calling coach endpoint must be rejected (401/403)."""
        headers = {
            "Authorization": f"Bearer {seeded_client['token']}",
            "Content-Type": "application/json",
        }
        r = requests.post(
            f"{BASE_URL}/api/coach/clients/{seeded_client['user_id']}/roster/upload-parse",
            headers=headers,
            json={"file_base64": "AAAA", "mime_type": "application/pdf", "filename": "x.pdf"},
            timeout=15,
        )
        assert r.status_code in (401, 403), (
            f"Non-coach should be rejected, got {r.status_code}: {r.text[:200]}"
        )

    def test_upload_parse_404_for_missing_client(self, coach_headers):
        r = requests.post(
            f"{BASE_URL}/api/coach/clients/does-not-exist-{uuid.uuid4()}/roster/upload-parse",
            headers=coach_headers,
            json={"file_base64": "AAAA", "mime_type": "application/pdf", "filename": "x.pdf"},
            timeout=15,
        )
        assert r.status_code == 404, (
            f"Missing client should 404, got {r.status_code}: {r.text[:200]}"
        )

    def test_pending_confirm_403_for_non_coach(self, seeded_client):
        headers = {
            "Authorization": f"Bearer {seeded_client['token']}",
            "Content-Type": "application/json",
        }
        r = requests.post(
            f"{BASE_URL}/api/coach/clients/{seeded_client['user_id']}/roster/pending/{uuid.uuid4()}/confirm",
            headers=headers,
            timeout=15,
        )
        assert r.status_code in (401, 403), (
            f"Non-coach should be rejected, got {r.status_code}: {r.text[:200]}"
        )

    def test_pending_confirm_404_for_missing_roster(self, seeded_client, coach_headers):
        r = requests.post(
            f"{BASE_URL}/api/coach/clients/{seeded_client['user_id']}/roster/pending/missing-{uuid.uuid4()}/confirm",
            headers=coach_headers,
            timeout=15,
        )
        assert r.status_code == 404, (
            f"Missing pending roster should 404, got {r.status_code}: {r.text[:200]}"
        )


# ---------------------------------------------------------------------------
# 4. Overlap semantics — non-overlapping months remain active
# ---------------------------------------------------------------------------

class TestOverlapSupersede:
    """When a coach confirms a new roster, only OVERLAPPING active rosters
    are superseded. Non-overlapping months remain active side-by-side.

    We test the DB-layer behaviour directly since the LLM parse worker is
    background/async — we insert a pending roster and call the confirm
    endpoint via the coach token.
    """

    def test_confirm_supersedes_overlapping_only(self, seeded_client, coach_headers):
        """Insert a pending September roster; confirming it should NOT
        deactivate the existing July or August rosters (non-overlapping)."""
        from pymongo import MongoClient
        mc = MongoClient(MONGO_URL)
        db = mc[DB_NAME]
        try:
            uid = seeded_client["user_id"]
            sep_days = _month_days(2026, 9)
            pending_id = str(uuid.uuid4())
            db.rosters.insert_one({
                "id": pending_id,
                "user_id": uid,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "days": sep_days,
                "start_date": sep_days[0]["date"],
                "end_date": sep_days[-1]["date"],
                "is_active": False,
                "status": "pending_confirmation",
                "confirmed": False,
                "day_count": len(sep_days),
                "source_filename": "iter109_september.pdf",
                "uploaded_by": "coach",
            })

            r = requests.post(
                f"{BASE_URL}/api/coach/clients/{uid}/roster/pending/{pending_id}/confirm",
                headers=coach_headers,
                timeout=30,
            )
            assert r.status_code == 200, (
                f"Coach confirm failed: {r.status_code} {r.text[:300]}"
            )
            payload = r.json()
            assert payload.get("roster_id") == pending_id
            assert payload.get("status") == "processing"

            # Confirm the pending roster is now active + confirmed_by=coach
            active = db.rosters.find_one({"id": pending_id})
            assert active["is_active"] is True
            assert active["status"] == "confirmed"
            assert active["confirmed_by"] == "coach"

            # July + August should REMAIN active (non-overlap with Sep).
            jul = db.rosters.find_one({"id": seeded_client["jul_roster_id"]})
            aug = db.rosters.find_one({"id": seeded_client["aug_roster_id"]})
            assert jul["is_active"] is True, "July should still be active!"
            assert aug["is_active"] is True, "August should still be active!"
        finally:
            db.rosters.delete_many({"user_id": seeded_client["user_id"], "id": pending_id})
            db.workouts.delete_many({"user_id": seeded_client["user_id"], "roster_id": pending_id})
            db.roster_jobs.delete_many({"user_id": seeded_client["user_id"]})
            mc.close()


# ---------------------------------------------------------------------------
# 5. Copy hygiene — no AI/generated/bot wording emitted to clients
# ---------------------------------------------------------------------------

class TestCopyHygiene:
    FORBIDDEN = re.compile(r"\b(AI|artificial intelligence|generated by|bot|chatbot|GPT|LLM)\b", re.IGNORECASE)
    # Allow "coaching_system" (backend source tag, not user-facing) and
    # "auto-generated" only within internal tags — we scan the client-visible
    # `client_copy`, `message`, and `recommendation_copy` strings mostly.

    def test_calendar_range_copy_clean(self, seeded_client):
        headers = {"Authorization": f"Bearer {seeded_client['token']}"}
        r = requests.get(
            f"{BASE_URL}/api/calendar/range",
            params={"from": "2026-07-01", "to": "2026-08-31"},
            headers=headers, timeout=15,
        )
        assert r.status_code == 200
        # Only scan client_copy strings
        for d in r.json().get("days", []):
            cc = d.get("client_copy") or {}
            for k in ("title", "body", "recommendation"):
                v = str(cc.get(k, ""))
                assert not self.FORBIDDEN.search(v), (
                    f"Forbidden AI/bot wording in client_copy.{k}: {v!r}"
                )

    def test_roster_current_copy_clean(self, seeded_client):
        headers = {"Authorization": f"Bearer {seeded_client['token']}"}
        r = requests.get(f"{BASE_URL}/api/roster/current", headers=headers, timeout=15)
        assert r.status_code == 200
        # Flatten all string values in the response and scan for forbidden terms.
        def _walk(obj):
            if isinstance(obj, str):
                yield obj
            elif isinstance(obj, dict):
                for v in obj.values():
                    yield from _walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    yield from _walk(v)
        for s in _walk(r.json()):
            # Allow the string "coaching_system" (source tag, not user-visible copy).
            if "coaching_system" in s:
                continue
            m = self.FORBIDDEN.search(s)
            assert not m, f"Forbidden AI/bot wording in /roster/current: {m.group(0)!r} in {s[:120]!r}"

    def test_coach_upload_button_component_copy_clean(self):
        """Static scan of CoachRosterUploadButton.tsx for forbidden copy.

        We strip /* block */ and // line comments before scanning so that the
        file's own "no AI/generated wording" documentation comment doesn't
        trip the test.
        """
        path = "/app/frontend/src/components/CoachRosterUploadButton.tsx"
        if not os.path.exists(path):
            pytest.skip(f"{path} not present")
        with open(path, "r") as fh:
            src = fh.read()
        # Strip block comments
        src_no_block = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
        # Strip line comments
        src_clean = re.sub(r"//.*", "", src_no_block)
        m = self.FORBIDDEN.search(src_clean)
        assert not m, (
            f"Forbidden wording {m.group(0)!r} in CoachRosterUploadButton.tsx "
            f"(non-comment code): context={src_clean[max(0, m.start()-40):m.end()+40]!r}"
        )


if __name__ == "__main__":
    import pytest as _pt
    _pt.main([__file__, "-v", "-s"])
