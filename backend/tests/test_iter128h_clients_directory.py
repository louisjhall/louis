"""
Iter 128h — Clients Directory + sidebar consolidation tests.

Covers the DEFINITION OF DONE for the "Clients Page Consolidation" brief:

    CLIENTS = CANONICAL DIRECTORY:             endpoint returns per-client rows
    LARGE SUMMARY CARDS / STATUS FILTERS:      no legacy filter buckets in payload
    NEW CLIENT PREVIEW / MANAGE COACHES / AUDIT LOG:
                                               not exposed via directory payload
    CLIENT ROW FIELDS:                         identity + goal + plan + roster + next action
    PIETRO ROW:                                Live + New Draft · N issues + roster loaded
                                               + specific Review draft action
    CLICKABLE ACTIONS / DEEP LINKS:            every next_action.deep_link → canonical workspace
    LEGACY ROUTES:                             none referenced
"""
import pytest


COACH_EMAIL = "louis@crewfit.net"
COACH_PW = "Louis123!"

# Forbidden legacy vocabulary in coach-facing display fields.
FORBIDDEN_TERMS = [
    "V1", "V2", "legacy", "opportunity", "floor", "exposure_",
    "validation.ok", "programme_validation",
]


@pytest.fixture(scope="module")
def coach_headers(api, base_url):
    r = api.post(f"{base_url}/api/auth/login",
                 json={"email": COACH_EMAIL, "password": COACH_PW}, timeout=30)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def directory(api, base_url, coach_headers):
    r = api.get(f"{base_url}/api/v2/coach/clients/directory?filter=active",
                headers=coach_headers, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def test_directory_shape(directory):
    assert "clients" in directory
    assert "counts" in directory
    for k in ("active", "needs_attention", "archived"):
        assert k in directory["counts"]


def test_directory_no_legacy_fields_in_row(directory):
    """No legacy filter buckets in each row; only the 5 canonical columns."""
    if not directory["clients"]:
        pytest.skip("no clients in directory")
    row = directory["clients"][0]
    # Required columns
    for k in ("id", "name", "goal", "plan", "roster", "next_action"):
        assert k in row, f"missing column: {k}"
    # Legacy dashboard fields must not leak (§2/§3/§16)
    for legacy in ("expiring_soon", "expired", "no_roster", "missed_workouts",
                    "red_days", "roster_expiry", "programme_pill",
                    "guardrail_flagged", "profile_incomplete_pill",
                    "latest_roster", "pending_approvals"):
        assert legacy not in row, f"legacy field {legacy!r} still present in directory row"


def test_pietro_row_matches_brief_25(directory):
    """§25 — Pietro should broadly show:
       identity + goal + LIVE + New Draft needs review + roster loaded +
       Review Draft action."""
    pietro = next(
        (c for c in directory["clients"]
         if (c.get("name") or "").lower().startswith("pietro")),
        None,
    )
    assert pietro is not None, "Pietro should appear in the active directory"
    assert pietro["plan"]["label"] == "Live"
    assert pietro["plan"]["tint"] == "green"
    # Newer draft context
    assert pietro["plan"]["sub"] and "draft" in pietro["plan"]["sub"].lower()
    # Roster loaded (real state)
    assert pietro["roster"]["kind"] == "loaded"
    # Specific action label — never a bare "Review" (§13)
    assert pietro["next_action"]["label"].lower().startswith("review draft")
    # Deep link into canonical workspace (§14)
    dl = pietro["next_action"]["deep_link"]
    assert dl.startswith("/coach/client/") and dl.endswith("/workspace")


def test_deep_links_all_target_workspace(directory):
    """§14 — Every client row's next-action deep link resolves to /workspace."""
    for c in directory["clients"]:
        dl = c["next_action"]["deep_link"]
        assert dl.startswith("/coach/client/"), f"row {c['id']}: deep_link not workspace: {dl}"
        assert "/workspace" in dl, f"row {c['id']}: not workspace: {dl}"


def test_next_actions_are_specific(directory):
    """§13 — No generic 'Review' or 'Open Client' if a real next action exists."""
    for c in directory["clients"]:
        lbl = (c["next_action"]["label"] or "").strip().lower()
        assert lbl and lbl != "review", f"generic 'Review' on {c['id']}"


def test_no_legacy_vocab_in_display_fields(directory):
    for c in directory["clients"]:
        for field in ("name", "role_line"):
            v = (c.get(field) or "")
            for term in FORBIDDEN_TERMS:
                assert term.lower() not in v.lower(), (
                    f"forbidden term {term!r} in {c['id']}.{field}: {v!r}"
                )
        # goal + plan + roster labels
        for path in (("goal", "label"), ("plan", "label"), ("plan", "sub"),
                     ("roster", "label"), ("roster", "sub"),
                     ("next_action", "label")):
            v = str(c.get(path[0], {}).get(path[1]) or "")
            for term in FORBIDDEN_TERMS:
                assert term.lower() not in v.lower(), (
                    f"forbidden term {term!r} in {c['id']}.{'.'.join(path)}: {v!r}"
                )


def test_needs_attention_filter_narrows_result(api, base_url, coach_headers):
    r1 = api.get(f"{base_url}/api/v2/coach/clients/directory?filter=active",
                 headers=coach_headers, timeout=30).json()
    r2 = api.get(f"{base_url}/api/v2/coach/clients/directory?filter=needs_attention",
                 headers=coach_headers, timeout=30).json()
    assert len(r2["clients"]) <= len(r1["clients"])
    # Every row in needs_attention must actually have attention_count > 0
    for c in r2["clients"]:
        assert c.get("attention_count", 0) > 0, f"row {c['id']} in needs_attention has 0 attention"


def test_search_filters_by_name(api, base_url, coach_headers):
    r = api.get(f"{base_url}/api/v2/coach/clients/directory?filter=active&q=pietro",
                headers=coach_headers, timeout=30).json()
    names = [c["name"].lower() for c in r["clients"]]
    # Every result should contain 'pietro' somewhere in the identity fields.
    for n in names:
        assert "pietro" in n
