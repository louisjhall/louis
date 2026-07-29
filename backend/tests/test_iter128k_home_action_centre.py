"""
Iter 128k — Coach Home Action Centre (media + system tasks) tests.

Covers DEFINITION OF DONE for the "Coach Home Action Centre" brief:

    TOP CARDS include Needs Attention / Ready to Publish / Needs Media /
    Messages / Check-ins (no Upcoming top card)                            §1
    Needs Media is a first-class first-class task, appears in the queue   §2/§6
    Media priority derives from client exposure (client_facing > 0 →
    attention; else upcoming)                                              §3
    Media counts dedupe coach_tasks + media_queue by exercise_id           §30
    Orphan free-text exercises → exercise_review (not counted as media)   §31/§4
    System tasks carry `scope=="system"` (no client_id required)          §29
    Test/sandbox/reviewer clients excluded by default                     §18
    All deep-links resolve to canonical destinations                      §40
"""
import pytest


COACH_EMAIL = "louis@crewfit.net"
COACH_PW = "Louis123!"


@pytest.fixture(scope="module")
def coach_headers(api, base_url):
    r = api.post(f"{base_url}/api/auth/login",
                 json={"email": COACH_EMAIL, "password": COACH_PW}, timeout=30)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def queue(api, base_url, coach_headers):
    r = api.get(f"{base_url}/api/v2/coach/home/action-queue",
                headers=coach_headers, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _all_tasks(q):
    return (q.get("needs_attention") or []) + (q.get("upcoming") or []) + (q.get("waiting_on_client") or [])


def test_top_card_counts_present(queue):
    for k in ("needs_action", "ready_to_publish", "needs_media",
              "needs_media_client_facing", "needs_media_training",
              "needs_media_flight_support", "needs_media_unresolved",
              "messages", "checkins"):
        assert k in queue["counts"], f"missing top-card count key: {k}"


def test_test_and_reviewer_accounts_excluded_from_action_queue(queue):
    """§18 — sandbox / test / reviewer accounts must not appear."""
    for t in _all_tasks(queue):
        name = (t.get("client_name") or "").lower()
        assert "reviewer" not in name, f"reviewer client leaked into queue: {name!r}"
        assert "briefing test" not in name, f"briefing test client leaked: {name!r}"


def test_media_required_system_task_shape(queue):
    tasks = _all_tasks(queue)
    media = [t for t in tasks if t.get("type") == "media_required"]
    if queue["counts"]["needs_media"] == 0:
        assert media == [], "no media task should surface when count is zero"
        return
    assert len(media) == 1, f"expected exactly one grouped media task, got {len(media)}"
    m = media[0]
    assert m.get("scope") == "system"
    assert m.get("client_id") is None or "client_id" not in m
    assert m["action_label"].lower().startswith("open media")
    assert m["deep_link"].startswith("/(coach)/library") or m["deep_link"].startswith("/library")
    # Deterministic id — the same across polls
    assert m["id"] == "media_required:system"


def test_media_priority_reflects_client_exposure(queue):
    tasks = _all_tasks(queue)
    media = next((t for t in tasks if t.get("type") == "media_required"), None)
    if not media:
        pytest.skip("no media work in DB")
    cf = queue["counts"]["needs_media_client_facing"]
    if cf > 0:
        assert media["priority"] == "attention", (
            "client-facing media work must sit in NEEDS ACTION, not UPCOMING"
        )
    else:
        assert media["priority"] == "upcoming"


def test_no_upcoming_top_card_semantics_broken(queue):
    """§1/§24 — Upcoming is a section, not a top card. The payload still
    exposes `counts.upcoming` (used by the header sub-line), and a separate
    `upcoming[]` list — but the top-card frontend now consumes:
      needs_action, ready_to_publish, needs_media, messages, checkins
    Confirm those keys exist and are ints.
    """
    c = queue["counts"]
    for k in ("needs_action", "ready_to_publish", "needs_media", "messages", "checkins"):
        assert isinstance(c[k], int), f"{k} must be int, got {type(c[k]).__name__}"


def test_needs_media_count_matches_task_counts(queue):
    tasks = _all_tasks(queue)
    media = next((t for t in tasks if t.get("type") == "media_required"), None)
    if not media:
        assert queue["counts"]["needs_media"] == 0
        return
    counts = media.get("counts") or {}
    assert counts.get("total") == queue["counts"]["needs_media"]
    assert counts.get("client_facing") == queue["counts"]["needs_media_client_facing"]
    assert counts.get("training") == queue["counts"]["needs_media_training"]
    assert counts.get("flight_support") == queue["counts"]["needs_media_flight_support"]


def test_exercise_review_split_from_media(queue):
    """§4/§31 — orphan/free-text names surface as exercise_review, never
    inflate media counts."""
    if queue["counts"]["needs_media_unresolved"] == 0:
        return
    tasks = _all_tasks(queue)
    er = [t for t in tasks if t.get("type") == "exercise_review"]
    assert len(er) == 1, "unresolved exercise names must surface as ONE exercise_review task"
    assert er[0]["scope"] == "system"


def test_pietro_task_still_aggregated_and_test_clients_gone(queue):
    """Iter 128g invariant preserved after 128k changes:
       Pietro shows exactly one draft_review; sandbox clients are gone."""
    tasks = _all_tasks(queue)
    pietro_reviews = [
        t for t in tasks
        if t.get("type") == "draft_review"
        and (t.get("client_name") or "").lower().startswith("pietro")
    ]
    assert len(pietro_reviews) == 1
    # No test-account names in the queue.
    names = {(t.get("client_name") or "").lower() for t in tasks if t.get("client_name")}
    assert not any("reviewer" in n or "briefing test" in n for n in names)


def test_all_deep_links_resolve_to_canonical_destinations(queue):
    tasks = _all_tasks(queue)
    for t in tasks:
        dl = t.get("deep_link") or ""
        if t.get("scope") == "system":
            # Library or library-scoped destination
            assert "library" in dl.lower(), f"system task deep link should target Library: {dl}"
        else:
            assert dl.startswith("/coach/client/") and "/workspace" in dl, (
                f"client task deep link must target workspace: {dl}"
            )


def test_endpoint_read_only_deterministic(api, base_url, coach_headers):
    r1 = api.get(f"{base_url}/api/v2/coach/home/action-queue",
                 headers=coach_headers, timeout=30).json()
    r2 = api.get(f"{base_url}/api/v2/coach/home/action-queue",
                 headers=coach_headers, timeout=30).json()
    ids1 = sorted(t["id"] for t in _all_tasks(r1))
    ids2 = sorted(t["id"] for t in _all_tasks(r2))
    assert ids1 == ids2
    assert r1["counts"] == r2["counts"]
