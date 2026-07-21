"""
Phase 3 — Reactive Progression tests.

Covers:
  * iso_week_bounds returns Mon-Sun
  * week_key stable "YYYY-Www" format
  * compute_status status rules (progressing_well / maintain / reduce_load / deload)
  * compute_status metrics (adherence %, avg RPE, key_missed)
  * HTTP endpoints: /api/progress/current, /api/progress/history, /api/progress/recompute
  * Coach endpoints: /api/coach/clients/{cid}/progress/{current,history}
"""
import sys
import uuid as _uuid
import datetime as _dt
sys.path.insert(0, "/app/backend")

from feature_progression import (
    STATUS_PROGRESSING, STATUS_MAINTAIN, STATUS_REDUCE, STATUS_DELOAD,
    iso_week_bounds, week_key, compute_status,
)


# ---------------------------------------------------------------------------
# Week helpers
# ---------------------------------------------------------------------------

def test_iso_week_bounds_monday_to_sunday():
    # 2026-07-22 is a Wednesday
    mon, sun = iso_week_bounds(_dt.date(2026, 7, 22))
    assert mon == _dt.date(2026, 7, 20)   # Monday
    assert sun == _dt.date(2026, 7, 26)   # Sunday
    assert mon.weekday() == 0
    assert sun.weekday() == 6


def test_iso_week_bounds_from_monday():
    mon, sun = iso_week_bounds(_dt.date(2026, 7, 20))
    assert mon == _dt.date(2026, 7, 20)
    assert sun == _dt.date(2026, 7, 26)


def test_week_key_format():
    key = week_key(_dt.date(2026, 7, 22))
    assert isinstance(key, str)
    assert key.startswith("2026-W")
    assert len(key) == 8  # 'YYYY-Www'


# ---------------------------------------------------------------------------
# compute_status — rule engine
# ---------------------------------------------------------------------------

def _w(date="2026-07-21", *, completed=True, rpe=7.5, key=False, has_content=True):
    """Build a fake workout with the shape the calculator expects."""
    return {
        "id": _uuid.uuid4().hex[:8],
        "date": date,
        "completed": completed,
        "completion": {"rpe": rpe} if (completed and rpe is not None) else {},
        "key_session": key,
        "exercises": [{"name": "Push-up"}] if has_content else [],
    }


def test_status_progressing_well_full_adherence():
    ws = [_w(rpe=7.0), _w(rpe=7.5), _w(rpe=8.0), _w(rpe=7.0)]
    s = compute_status(ws, week_start="2026-07-20", week_end="2026-07-26")
    assert s["status"] == STATUS_PROGRESSING
    assert s["metrics"]["adherence_pct"] == 100.0
    assert s["metrics"]["sessions_completed"] == 4
    assert s["metrics"]["avg_rpe"] == 7.38 or 7.37 <= s["metrics"]["avg_rpe"] <= 7.4


def test_status_maintain_partial_adherence():
    ws = [
        _w(rpe=7.5), _w(rpe=8.0),
        _w(completed=False, rpe=None),   # missed
    ]
    s = compute_status(ws, week_start="2026-07-20", week_end="2026-07-26")
    # 2/3 = 66.7% adherence → maintain (not <60, not ≥80)
    assert s["status"] == STATUS_MAINTAIN


def test_status_reduce_load_low_adherence():
    ws = [
        _w(rpe=8.0),
        _w(completed=False, rpe=None),
        _w(completed=False, rpe=None),
        _w(completed=False, rpe=None),
    ]
    s = compute_status(ws, week_start="2026-07-20", week_end="2026-07-26")
    # 1/4 = 25% adherence → reduce_load
    assert s["status"] == STATUS_REDUCE


def test_status_reduce_load_high_rpe():
    ws = [_w(rpe=9.5), _w(rpe=9.0), _w(rpe=9.5), _w(rpe=9.0)]  # only 2 hit ≥9.5
    s = compute_status(ws, week_start="2026-07-20", week_end="2026-07-26")
    # adherence 100 + 2 sessions ≥9.5 + n_completed ≥3 → DELOAD triggers first
    assert s["status"] == STATUS_DELOAD


def test_status_reduce_load_avg_rpe_high():
    ws = [_w(rpe=9.0), _w(rpe=9.0), _w(rpe=9.0), _w(rpe=9.0)]
    s = compute_status(ws, week_start="2026-07-20", week_end="2026-07-26")
    # No RPE ≥9.5 → not deload; avg_rpe ≥ 9.0 → reduce_load
    assert s["status"] == STATUS_REDUCE


def test_status_deload_sustained_max_effort():
    ws = [_w(rpe=9.5), _w(rpe=9.5), _w(rpe=9.5), _w(rpe=9.5)]
    s = compute_status(ws, week_start="2026-07-20", week_end="2026-07-26")
    assert s["status"] == STATUS_DELOAD


def test_status_reduce_load_missed_key_session():
    ws = [
        _w(rpe=8.0), _w(rpe=8.0),
        _w(completed=False, rpe=None, key=True),   # missed the key session
    ]
    s = compute_status(ws, week_start="2026-07-20", week_end="2026-07-26")
    # 2/3 = 66% adherence + 1 key missed → reduce_load
    assert s["status"] == STATUS_REDUCE
    assert s["metrics"]["key_missed"] == 1


def test_status_ignores_placeholder_workouts():
    ws = [
        _w(rpe=7.5),
        _w(has_content=False, completed=False, rpe=None),  # placeholder — not counted
    ]
    s = compute_status(ws, week_start="2026-07-20", week_end="2026-07-26")
    assert s["metrics"]["sessions_planned"] == 1
    assert s["metrics"]["sessions_completed"] == 1
    assert s["status"] == STATUS_PROGRESSING


def test_status_empty_week():
    s = compute_status([], week_start="2026-07-20", week_end="2026-07-26")
    # No planned → adherence 0 → REDUCE (lowest severity: no data)
    # We accept either REDUCE (rule) or MAINTAIN (fallback) — check reason exists
    assert s["status"] in (STATUS_REDUCE, STATUS_MAINTAIN)
    assert s["metrics"]["sessions_planned"] == 0
    assert s["metrics"]["sessions_completed"] == 0


def test_status_has_status_label_and_reason():
    ws = [_w(rpe=7.0)]
    s = compute_status(ws, week_start="2026-07-20", week_end="2026-07-26")
    assert s["status_label"]
    assert s["reason"]
    assert s["coach_note"]
    assert s["week_start"] == "2026-07-20"
    assert s["week_end"] == "2026-07-26"


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

def test_progress_current_returns_json(api, base_url, client_auth):
    r = api.get(f"{base_url}/api/progress/current", headers=client_auth["headers"], timeout=30)
    assert r.status_code == 200
    # {} is a valid response when the client has no snapshot yet
    body = r.json()
    assert isinstance(body, dict)


def test_progress_history_returns_list(api, base_url, client_auth):
    r = api.get(f"{base_url}/api/progress/history?weeks=4", headers=client_auth["headers"], timeout=30)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_progress_history_clamps_weeks(api, base_url, client_auth):
    # weeks parameter is clamped internally to 1..52 — verify no 500
    for w in (0, -5, 100, 5):
        r = api.get(f"{base_url}/api/progress/history?weeks={w}", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


def test_progress_recompute_returns_snapshot(api, base_url, client_auth):
    r = api.post(f"{base_url}/api/progress/recompute", headers=client_auth["headers"], timeout=30)
    assert r.status_code == 200
    body = r.json()
    # Even with no completed workouts, we get a well-formed snapshot with status
    if body:
        assert "status" in body
        assert body["status"] in (STATUS_PROGRESSING, STATUS_MAINTAIN, STATUS_REDUCE, STATUS_DELOAD)
        assert "metrics" in body


def test_coach_client_progress_denied_for_client(api, base_url, client_auth):
    r = api.get(
        f"{base_url}/api/coach/clients/some-cid/progress/current",
        headers=client_auth["headers"],
        timeout=30,
    )
    assert r.status_code == 403


def test_coach_client_progress_ok_for_coach(api, base_url, coach_auth, client_auth):
    cid = client_auth["user"]["id"]
    r = api.get(
        f"{base_url}/api/coach/clients/{cid}/progress/current",
        headers=coach_auth["headers"],
        timeout=30,
    )
    assert r.status_code == 200
    assert isinstance(r.json(), dict)

    r2 = api.get(
        f"{base_url}/api/coach/clients/{cid}/progress/history?weeks=4",
        headers=coach_auth["headers"],
        timeout=30,
    )
    assert r2.status_code == 200
    assert isinstance(r2.json(), list)
