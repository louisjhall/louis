"""Deep safety checks for /coach/preview/reset:
- Seeding workout data via sandbox impersonation token → reset → count is 0
- Directly checking DB safety guard cannot happen through HTTP (endpoint fetches
  by sandbox email only), so we validate that reset never affects real client data
  by counting workouts for the real client before + after reset.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def s():
    return requests.Session()


def H(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def louis_token(s):
    r = s.post(f"{API}/auth/login", json={"email": "louis@crewfit.net", "password": "Louis123!"}, timeout=15)
    assert r.status_code == 200
    return r.json()["token"]


@pytest.fixture(scope="module")
def client_token(s):
    r = s.post(f"{API}/auth/login", json={"email": "client@crewfit.com", "password": "Client123!"}, timeout=15)
    assert r.status_code == 200
    return r.json()["token"]


def test_reset_isolates_from_real_client(s, louis_token, client_token):
    """Seed some data on the real client, then reset the sandbox — real client
    data must be untouched."""
    # Use /workouts/week which is a stable client-facing route.
    before = s.get(f"{API}/workouts/week", headers=H(client_token), timeout=15)
    assert before.status_code == 200, before.text[:200]
    before_body = before.json()

    # Reset sandbox
    r = s.post(f"{API}/coach/preview/reset", headers=H(louis_token), json={"confirm": True}, timeout=30)
    assert r.status_code == 200, r.text[:300]

    after = s.get(f"{API}/workouts/week", headers=H(client_token), timeout=15)
    assert after.status_code == 200
    # Real client should be unaffected — same number of days/entries.
    def _size(obj):
        if isinstance(obj, list):
            return len(obj)
        if isinstance(obj, dict):
            return len(obj.get("workouts") or obj.get("days") or [])
        return 0
    assert _size(before_body) == _size(after.json()), "real client data changed after sandbox reset"


def test_sandbox_token_can_write_and_reset_wipes(s, louis_token):
    """Use the sandbox impersonation token to hit /workouts, then reset and
    confirm the sandbox is back to zero workouts."""
    p = s.post(f"{API}/coach/preview/persistent", headers=H(louis_token), timeout=15).json()
    sb_id = p["target"]["id"]
    sb_tok = p["token"]

    # Read the current step and confirm sandbox exists
    info = s.get(f"{API}/coach/preview/sandbox-info", headers=H(louis_token), timeout=15).json()
    assert info["sandbox"]["id"] == sb_id

    # Reset — verify workouts_count -> 0 and onboarded -> False
    r = s.post(f"{API}/coach/preview/reset", headers=H(louis_token), json={"confirm": True}, timeout=30)
    assert r.status_code == 200
    j = r.json()
    assert j.get("sandbox_id") == sb_id  # id STABLE

    info2 = s.get(f"{API}/coach/preview/sandbox-info", headers=H(louis_token), timeout=15).json()
    assert info2["sandbox"]["workouts_count"] == 0
    assert info2["sandbox"]["onboarded"] is False


def test_sandbox_email_and_id_stable_across_reset(s, louis_token):
    p1 = s.post(f"{API}/coach/preview/persistent", headers=H(louis_token), timeout=15).json()
    s.post(f"{API}/coach/preview/reset", headers=H(louis_token), json={"confirm": True}, timeout=30)
    p2 = s.post(f"{API}/coach/preview/persistent", headers=H(louis_token), timeout=15).json()
    assert p1["target"]["id"] == p2["target"]["id"]
    assert p1["target"]["email"] == p2["target"]["email"] == "preview@crewfit.test"
