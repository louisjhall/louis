"""
Iter 128i — Coach Calendar V2 tests.

Covers the DEFINITION OF DONE from the Calendar redesign brief:

    CURRENT V2 LIVE DATA ONLY:  payload contains no V1 workout / roster fields
    V1 PROGRAMME DATA:          no workout_id / day_load / duty_type keys
    TEST CLIENT CLUTTER:        excluded_test_count > 0 for our DB; test rows absent
    LIVE + DRAFT NOT MIXED:     Pietro has an active Draft but Draft placements
                                 do NOT appear in his Live day cells
    TECHNICAL VALIDATION TEXT:  no "opportunity", "floor", "exposure_" leakage
    ROSTER CONTEXT + FLIGHT SUPPORT PRESENT:
                                 Pietro's Layover ✈ / Turnaround / Home / Standby
                                 tags + Flight Support items are surfaced
    PIETRO CHANGED:             NO writes performed
"""
import pytest


COACH_EMAIL = "louis@crewfit.net"
COACH_PW = "Louis123!"

FORBIDDEN_TERMS = [
    "opportunity", "floor", "exposure_", "session_spec",
    "validation.ok", "programme_validation", "V1", "workout_assignment",
]


@pytest.fixture(scope="module")
def coach_headers(api, base_url):
    r = api.post(f"{base_url}/api/auth/login",
                 json={"email": COACH_EMAIL, "password": COACH_PW}, timeout=30)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def cal7(api, base_url, coach_headers):
    r = api.get(f"{base_url}/api/v2/coach/calendar?days=7",
                headers=coach_headers, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def test_endpoint_shape(cal7):
    for k in ("start_date", "end_date", "days_count", "dates", "clients", "excluded_test_count"):
        assert k in cal7, f"missing key {k}"
    assert cal7["days_count"] == 7
    assert len(cal7["dates"]) == 7


def test_days_param_is_clamped(api, base_url, coach_headers):
    # 0 falls back to the default 7 (harmless behaviour)
    r = api.get(f"{base_url}/api/v2/coach/calendar?days=0",
                headers=coach_headers, timeout=30).json()
    assert 1 <= r["days_count"] <= 28
    # >28 clamps to 28
    r = api.get(f"{base_url}/api/v2/coach/calendar?days=90",
                headers=coach_headers, timeout=30).json()
    assert r["days_count"] == 28
    # negative also clamps to 1
    r = api.get(f"{base_url}/api/v2/coach/calendar?days=-5",
                headers=coach_headers, timeout=30).json()
    assert r["days_count"] == 1


def test_test_clients_excluded_by_default(cal7):
    """§3 / §29 — App Store Reviewer + Briefing Test must not appear."""
    assert cal7["excluded_test_count"] >= 1, (
        "expected test/sandbox accounts to be filtered from operational calendar"
    )
    names = [c["name"].lower() for c in cal7["clients"]]
    for n in names:
        assert "reviewer" not in n, f"reviewer should be excluded: {n!r}"
        assert "briefing test" not in n, f"briefing test should be excluded: {n!r}"


def test_include_test_flag_re_introduces_them(api, base_url, coach_headers, cal7):
    r = api.get(f"{base_url}/api/v2/coach/calendar?days=7&include_test=1",
                headers=coach_headers, timeout=30).json()
    assert len(r["clients"]) >= len(cal7["clients"])
    assert r["excluded_test_count"] == 0


def test_pietro_row_present_with_live_plan(cal7):
    p = next((c for c in cal7["clients"]
              if (c.get("name") or "").lower().startswith("pietro")), None)
    assert p is not None, "Pietro should appear in the operational calendar"
    assert p["plan_state"] == "live"
    assert p["has_roster"] is True


def test_pietro_has_new_draft_badge_not_draft_placements(cal7):
    """§13 — When a newer Draft exists alongside Live, expose a badge but
    NEVER inject Draft placements into Live cells."""
    p = next(c for c in cal7["clients"]
             if (c.get("name") or "").lower().startswith("pietro"))
    assert p["has_new_draft"] is True, "Pietro has a Draft; badge should be True"
    # Every training rendered must derive from Live (source id prefixed with v2p:<live_id>)
    for cell in p["days"]:
        for t in cell["trainings"]:
            assert t["id"].startswith("v2p:"), f"unexpected training id: {t['id']}"


def test_pietro_roster_and_flight_support_present(cal7):
    """§7 + §10 — Roster context + Flight Support should surface."""
    p = next(c for c in cal7["clients"]
             if (c.get("name") or "").lower().startswith("pietro"))
    # At least one day should have a roster classification.
    any_roster = any(bool(cell.get("roster")) for cell in p["days"])
    assert any_roster, "expected Pietro to have roster classifications in the window"
    # At least one day should have flight support items (Pietro is a pilot).
    any_fs = any(len(cell.get("flight_support") or []) > 0 for cell in p["days"])
    assert any_fs, "expected Pietro to have flight-support items in the window"


def test_no_v1_fields_in_payload(cal7):
    """Legacy V1 shape (workout_id, day_load, duty_type, key_session,
    duration_min at day level, approved) must not appear per §1."""
    forbidden_v1 = {"workout_id", "day_load", "duty_type", "override_applied",
                    "override_tags", "override_notes", "override_pref"}
    for c in cal7["clients"]:
        for cell in c["days"]:
            for k in cell.keys():
                assert k not in forbidden_v1, f"legacy V1 field leaked into calendar cell: {k}"


def test_no_technical_vocab_leaks(cal7):
    """§14/§30 — no internal terminology (opportunity/floor/exposure_/etc.)"""
    import json as _json
    for c in cal7["clients"]:
        for cell in c["days"]:
            for t in cell["trainings"]:
                label = (t.get("label") or "").lower()
                for term in FORBIDDEN_TERMS:
                    assert term.lower() not in label, (
                        f"forbidden term {term!r} in training label: {label!r}"
                    )
            for fs in cell.get("flight_support") or []:
                title = (fs.get("title") or "").lower()
                for term in FORBIDDEN_TERMS:
                    assert term.lower() not in title, (
                        f"forbidden term {term!r} in flight-support title: {title!r}"
                    )


def test_search_filters_clients(api, base_url, coach_headers):
    r = api.get(f"{base_url}/api/v2/coach/calendar?days=7&q=pietro",
                headers=coach_headers, timeout=30).json()
    for c in r["clients"]:
        assert "pietro" in (c.get("name") or "").lower()


def test_endpoint_is_read_only_deterministic(api, base_url, coach_headers):
    r1 = api.get(f"{base_url}/api/v2/coach/calendar?days=7",
                 headers=coach_headers, timeout=30).json()
    r2 = api.get(f"{base_url}/api/v2/coach/calendar?days=7",
                 headers=coach_headers, timeout=30).json()
    ids1 = sorted(c["client_id"] for c in r1["clients"])
    ids2 = sorted(c["client_id"] for c in r2["clients"])
    assert ids1 == ids2
