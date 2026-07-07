"""Preview-URL specific validation of the 3 iteration_3 fixes.

1) POST /api/register-push with placeholder EMERGENT_PUSH_KEY → 201.
2) GET /api/exercises → >= 20 rows with V1.5 metadata.
3) POST /api/workouts/generate-month via CF preview URL completes within ~90s
   (chunked per-week concurrent Claude calls).
"""
import os
import time
import uuid
import pytest

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")

TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="


def _login(api, email, pwd):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pwd}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    return d["token"], d["user"]


def test_fix1_register_push_placeholder_returns_201(api, client_auth):
    """Fix 1: register-push must return 201 non-blocking, not 500."""
    payload = {
        "user_id": client_auth["user"]["id"],
        "platform": "ios",
        "device_token": f"TEST-ci-{uuid.uuid4().hex}",
    }
    r = api.post(f"{BASE_URL}/api/register-push", json=payload, timeout=30)
    assert r.status_code == 201, f"expected 201, got {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert body.get("status") == "registered", body


REQUIRED_V15_METADATA = [
    "movement_pattern", "home_ok", "hotel_ok", "bodyweight_ok", "level",
    "knee_friendly", "back_friendly", "shoulder_friendly", "fatigue_cost",
    "ok_before_flight", "ok_after_flight",
]


def test_fix2_exercises_seeded_to_20_plus_with_v15_metadata(api, client_auth):
    """Fix 2: DEFAULT_EXERCISES upsert should now materialise >= 20 rows."""
    r = api.get(f"{BASE_URL}/api/exercises", headers=client_auth["headers"], timeout=15)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) >= 20, f"expected >=20 exercises, got {len(rows)}"
    # Verify V1.5 metadata is on at least one row (upsert must have written it)
    with_meta = [x for x in rows if all(k in x for k in REQUIRED_V15_METADATA)]
    assert len(with_meta) >= 20, (
        f"expected >=20 rows to carry V1.5 metadata, got {len(with_meta)}/{len(rows)}"
    )


def test_fix3_generate_month_via_cf_preview_within_edge_timeout(api, client_auth):
    """Fix 3: chunked per-week concurrent Claude calls must fit under CF edge (~60s).
    We give it 90s of client timeout and expect a 200 with workouts[].
    """
    rc = api.get(f"{BASE_URL}/api/roster/current", headers=client_auth["headers"], timeout=15).json()
    rid = rc["id"]
    n_days = len(rc.get("days") or [])
    assert n_days >= 1, "no active roster"

    t0 = time.time()
    r = api.post(
        f"{BASE_URL}/api/workouts/generate-month",
        headers=client_auth["headers"],
        json={"roster_id": rid},
        timeout=90,
    )
    elapsed = time.time() - t0
    print(f"[generate-month via CF] roster days={n_days} elapsed={elapsed:.1f}s status={r.status_code}")
    if r.status_code == 502:
        pytest.fail(
            f"CF edge timeout: 502 after {elapsed:.1f}s — chunking did not shorten wall-clock."
        )
    assert r.status_code == 200, f"got {r.status_code}: {r.text[:300]}"
    d = r.json()
    assert "workouts" in d and isinstance(d["workouts"], list)
    ws = d["workouts"]
    # one workout per date in the roster
    dates = {w.get("date") for w in ws}
    assert len(dates) == len(ws), "duplicate dates in workouts"
    assert len(ws) >= 1

    # Validate V1.5 shape on the first workout
    w = ws[0]
    for k in ("id", "date", "day_load", "title", "location", "duration_min",
              "focus", "warmup", "exercises", "alternatives", "rationale"):
        assert k in w, f"missing key {k}"
    assert isinstance(w["warmup"], list)
    if w["exercises"]:
        ex = w["exercises"][0]
        for k in ("name", "sets", "reps", "rest_sec", "rpe"):
            assert k in ex
    for k in ("home", "hotel", "no_equipment", "easier", "harder"):
        assert k in w["alternatives"], f"missing alternatives.{k}"
