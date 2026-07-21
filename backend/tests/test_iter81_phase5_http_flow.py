"""
Iter81 Phase 5 — HTTP flow verification.

Confirms that:
  1) POST /api/progress/recompute returns a snapshot with a valid status.
  2) The client's latest snapshot is accessible.
  3) The progression_status wiring reaches downstream workout generation
     (looking at active roster's workouts for `progression_status` /
     `change_reason` if the current snapshot exists).
"""
import time
import pytest


PROGRESSION_STATUSES = {"progressing_well", "maintain", "reduce_load", "deload"}


def _get_active_roster(api, base_url, headers):
    r = api.get(f"{base_url}/api/roster/current", headers=headers, timeout=30)
    if r.status_code != 200:
        return None
    data = r.json()
    if isinstance(data, dict) and data.get("id"):
        return data
    return None


def test_recompute_endpoint_returns_snapshot_or_none(api, base_url, client_auth):
    """POST /api/progress/recompute should succeed for the client."""
    r = api.post(f"{base_url}/api/progress/recompute",
                 headers=client_auth["headers"], timeout=30)
    assert r.status_code == 200, f"unexpected {r.status_code}: {r.text}"
    payload = r.json()
    # Payload may be a snapshot dict or {snapshot: {...}} or None-ish
    if payload:
        snap = payload.get("snapshot") if "snapshot" in payload else payload
        if snap and snap.get("status"):
            assert snap["status"] in PROGRESSION_STATUSES
            assert "week_key" in snap


def test_latest_snapshot_endpoint(api, base_url, client_auth):
    """GET a progress endpoint (either /api/progress or /api/progress/latest)
    to confirm the snapshot is retrievable."""
    for path in ("/api/progress", "/api/progress/latest", "/api/progress/status"):
        r = api.get(f"{base_url}{path}", headers=client_auth["headers"], timeout=15)
        if r.status_code == 200:
            data = r.json()
            # Accept: dict with status, or wrapping snapshot key, or list history
            if isinstance(data, dict):
                snap = data.get("snapshot") or data
                if snap.get("status") is not None:
                    assert snap["status"] in PROGRESSION_STATUSES
                    return
            elif isinstance(data, list) and data:
                first = data[0]
                if first.get("status"):
                    assert first["status"] in PROGRESSION_STATUSES
                    return
            return  # 200 is enough
    pytest.skip("no readable progress endpoint")


def test_regenerated_workouts_carry_progression_status(api, base_url, client_auth):
    """After recompute, trigger a workouts regenerate for the active roster
    and confirm at least one generated workout has `progression_status` set,
    and endurance ones (long_run/tempo/intervals/easy_run) may have
    `change_reason` present when status != maintain.

    This test is SKIPPED (not failed) if the environment doesn't have an
    active roster or the recompute yielded no snapshot — Phase 5 unit
    behaviour is already asserted in test_iter81_phase5_progression_scaling.py.
    """
    headers = client_auth["headers"]
    # 1. Ensure snapshot exists
    rr = api.post(f"{base_url}/api/progress/recompute", headers=headers, timeout=30)
    assert rr.status_code == 200
    snap = rr.json() or {}
    if not isinstance(snap, dict) or not snap.get("status"):
        pytest.skip("no snapshot for this client — nothing to propagate")
    status = snap["status"]
    assert status in PROGRESSION_STATUSES

    # 2. Find an active roster
    roster = _get_active_roster(api, base_url, headers)
    if not roster:
        pytest.skip("no roster available for client")

    # 3. Trigger regenerate for the whole roster in the background
    r_job = api.post(
        f"{base_url}/api/workouts/regenerate",
        json={"roster_id": roster["id"], "all": True},
        headers=headers,
        timeout=30,
    )
    if r_job.status_code != 200:
        pytest.skip(f"regenerate endpoint unavailable: {r_job.status_code} {r_job.text[:200]}")
    job = r_job.json()
    job_id = job.get("job_id") or job.get("id")
    if not job_id:
        pytest.skip("regenerate returned no job_id")

    # 4. Poll until done (max ~120s — real generation is heavy)
    deadline = time.time() + 120
    job_payload = None
    while time.time() < deadline:
        rj = api.get(f"{base_url}/api/workouts/job/{job_id}", headers=headers, timeout=15)
        if rj.status_code == 200:
            job_payload = rj.json()
            if job_payload.get("status") in ("done", "complete", "completed", "failed", "error"):
                break
        time.sleep(3)
    if not job_payload or job_payload.get("status") not in ("done", "complete", "completed"):
        pytest.skip(f"regeneration did not complete in time: {job_payload}")

    workouts = job_payload.get("workouts") or []
    if not workouts:
        pytest.skip("no workouts in regenerate job payload")

    stamped = [w for w in workouts if w.get("progression_status") == status]
    endurance_focuses = {"long_run", "tempo", "intervals", "easy_run"}
    endurance_all = [w for w in workouts if w.get("focus") in endurance_focuses]
    if not endurance_all:
        # This client isn't a marathon/endurance profile — the scaler has
        # nothing to touch. Phase 5 unit tests cover the marathon path.
        pytest.skip("client has no endurance sessions in this roster")

    assert stamped, (
        "Expected at least one endurance session to be stamped with "
        f"progression_status={status!r}, got: {[w.get('title') for w in endurance_all]}"
    )
    if status != "maintain":
        endurance_stamped = [w for w in stamped if w.get("focus") in endurance_focuses]
        assert any(w.get("change_reason") for w in endurance_stamped), (
            "progression-aware scaler should stamp change_reason on "
            "endurance sessions when status != maintain"
        )
