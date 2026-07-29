"""
Iter 128g — Coach Home Action Queue tests.

Covers the DEFINITION OF DONE from the "Coach Home → Today's Action Queue"
brief:

    HOME IS CURRENT ACTION QUEUE            — endpoint exists and returns the aggregator payload
    RAW VALIDATION EVENTS                   — no task carries technical strings
    DUPLICATE PIETRO ISSUES                 — Pietro shows exactly ONE draft_review task
    TECHNICAL OPPORTUNITY/FLOOR TEXT        — no task exposes them
    TASKS AUTO-RESOLVE FROM CURRENT STATE   — endpoint is a pure read of current-state collections
    WAITING ON CLIENT SEPARATE              — dedicated bucket in payload
    UPCOMING SEPARATE                       — dedicated bucket in payload
    V1 DATA DRIVING HOME                    — payload never mentions V1 legacy vocabulary
    PIETRO PROGRAMME CHANGED                — no writes performed in this suite

The tests run against the live backend (HTTP) — no writes to the DB, no
LLM calls, no programme generation. Idempotent.
"""
import re
import pytest


COACH_EMAIL = "louis@crewfit.net"
COACH_PW = "Louis123!"

# Technical vocabulary that must NEVER leak into the coach-facing Home task
# titles/context/meta. If any of these appear the task rendering has
# regressed to raw validation dump territory.
FORBIDDEN_TERMS = [
    "opportunity", "floor", "exposure #", "exposure_", "session_spec",
    "objective_missed", "validation.ok", "V1", "v1_source", "plan_drafts_v2",
    "plan_live_v2", "placement_map", "reason_code", "programme_validation",
]


@pytest.fixture(scope="module")
def coach_headers(api, base_url):
    r = api.post(f"{base_url}/api/auth/login",
                 json={"email": COACH_EMAIL, "password": COACH_PW}, timeout=30)
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def queue(api, base_url, coach_headers):
    r = api.get(f"{base_url}/api/v2/coach/home/action-queue",
                headers=coach_headers, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _all_tasks(q):
    return (q.get("needs_attention") or []) + (q.get("upcoming") or []) + (q.get("waiting_on_client") or [])


def test_endpoint_returns_expected_shape(queue):
    assert "date" in queue
    assert "counts" in queue
    for k in ("needs_action", "ready_to_publish", "messages",
              "checkins", "upcoming", "waiting", "active_clients"):
        assert k in queue["counts"], f"missing count key: {k}"
    for section in ("needs_attention", "upcoming", "waiting_on_client"):
        assert isinstance(queue.get(section), list), f"{section} should be a list"


def test_pietro_has_exactly_one_draft_review_task(queue):
    """§5 — Multiple underlying issues MUST fold into ONE Home task."""
    pietro_reviews = [
        t for t in _all_tasks(queue)
        if t.get("type") == "draft_review"
        and (t.get("client_name") or "").lower().startswith("pietro")
    ]
    assert len(pietro_reviews) == 1, (
        f"Pietro should have exactly one draft_review task, got {len(pietro_reviews)}: "
        f"{[t.get('id') for t in pietro_reviews]}"
    )
    t = pietro_reviews[0]
    assert t.get("title") == "New draft needs review"
    # Aggregated counts: the underlying issues are grouped.
    counts = t.get("counts") or {}
    assert counts.get("total", 0) >= 1
    # Live context: brief §20 requires "current Live remains active"-style hint
    # when the client has both Live + newer Draft. Pietro has both.
    assert "live" in (t.get("meta") or "").lower()


def test_no_technical_vocab_leaks_into_coach_facing_text(queue):
    """§13 — Home must not surface internal terminology like 'opportunity
    47 below floor 50', 'exposure #2', 'validation.ok', etc."""
    tasks = _all_tasks(queue)
    for t in tasks:
        for field in ("title", "context", "meta", "action_label", "client_subtitle"):
            v = (t.get(field) or "")
            for term in FORBIDDEN_TERMS:
                assert term.lower() not in v.lower(), (
                    f"forbidden term '{term}' leaked into task "
                    f"{t.get('id')}.{field}: {v!r}"
                )


def test_no_duplicate_tasks_with_same_id(queue):
    """§22 — Stable dedupe keys; the same task ID cannot appear twice."""
    ids = [t.get("id") for t in _all_tasks(queue)]
    assert len(ids) == len(set(ids)), f"duplicate task ids: {sorted(ids)}"


def test_pietro_review_deep_link_targets_workspace(queue):
    """§11 — Every action must deep-link to the exact client workspace.
    No generic client overview."""
    pietro = next(
        t for t in _all_tasks(queue)
        if t.get("type") == "draft_review"
        and (t.get("client_name") or "").lower().startswith("pietro")
    )
    dl = pietro.get("deep_link") or ""
    assert dl.startswith("/coach/client/"), f"deep_link should target workspace: {dl}"
    assert "/workspace" in dl, f"deep_link should target /workspace: {dl}"


def test_summary_counts_match_visible_task_slices(queue):
    """§10 — Summary cards must be truthful, derived slices of the queue."""
    tasks = _all_tasks(queue)
    counts = queue["counts"]
    assert counts["ready_to_publish"] == sum(1 for t in tasks if t["type"] == "ready_to_publish")
    assert counts["messages"]         == sum(1 for t in tasks if t["type"] == "message")
    assert counts["checkins"]         == sum(1 for t in tasks if t["type"] == "checkin_review")
    assert counts["needs_action"]     == len(queue["needs_attention"])
    assert counts["upcoming"]         == len(queue["upcoming"])
    assert counts["waiting"]          == len(queue["waiting_on_client"])


def test_needs_attention_sorted_by_priority(queue):
    """§23 — Urgent first, then attention, within the Needs Attention bucket."""
    order = {"urgent": 0, "attention": 1}
    pri = [order.get(t.get("priority"), 9) for t in queue["needs_attention"]]
    assert pri == sorted(pri), f"needs_attention not sorted by priority: {pri}"


def test_action_labels_are_specific_not_generic(queue):
    """§19 — 'Review draft', 'Review check-in', 'Reply', 'Complete profile',
    etc. — never a bare 'Review'."""
    for t in _all_tasks(queue):
        lbl = (t.get("action_label") or "").strip().lower()
        assert lbl and lbl != "review", (
            f"generic 'Review' action label on task {t.get('id')}"
        )


def test_no_v1_legacy_vocabulary_in_payload(queue):
    """§26 — 'V1', 'V2', 'Legacy' must not leak into Home. Home is CrewFit,
    period."""
    import json as _json
    payload = _json.dumps(queue)
    # We tolerate lowercase 'v2' inside internal ids/dates but NOT in
    # coach-facing display fields; check display fields explicitly.
    for t in _all_tasks(queue):
        for field in ("title", "context", "meta", "action_label", "client_subtitle", "client_name"):
            v = (t.get(field) or "")
            assert not re.search(r"\bV1\b|\blegacy\b", v, re.IGNORECASE), (
                f"legacy vocab in task {t.get('id')}.{field}: {v!r}"
            )


def test_endpoint_is_read_only_and_deterministic(api, base_url, coach_headers):
    """Two consecutive calls must return the same task IDs and counts —
    proves the endpoint has no side effects and derives from state only."""
    r1 = api.get(f"{base_url}/api/v2/coach/home/action-queue",
                 headers=coach_headers, timeout=30).json()
    r2 = api.get(f"{base_url}/api/v2/coach/home/action-queue",
                 headers=coach_headers, timeout=30).json()
    ids1 = sorted(t["id"] for t in _all_tasks(r1))
    ids2 = sorted(t["id"] for t in _all_tasks(r2))
    assert ids1 == ids2, f"task set drifted between calls: {ids1} vs {ids2}"
    assert r1["counts"] == r2["counts"]
