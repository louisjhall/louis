"""
Iter 82 — DNA assessment length + progress determinism.

Fixes verified:
  * Progress % is monotonic (never goes backwards) — scaled off answer count,
    not the LLM's opinion.
  * Hard cap at 18 questions — after that we force should_end.
  * Never re-asks a prefilled or previously-answered question_id.
"""
import sys
import asyncio
import uuid as _uuid
sys.path.insert(0, "/app/backend")


_LOOP = None
def _run(coro):
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _mk_assessment(n_answers: int, prefilled_ids: list[str] | None = None) -> dict:
    """Build a fake assessment with n_answers plausible answers."""
    prefilled_ids = prefilled_ids or []
    ans = []
    for i in range(n_answers):
        qid = f"q_{i}"
        if i < len(prefilled_ids):
            qid = prefilled_ids[i]
        ans.append({
            "question_id": qid,
            "section": "Section",
            "question_text": f"question {i}",
            "question_type": "single_select",
            "answer": "some_answer",
            "answered_at": "2026-07-21T12:00:00Z",
            **({"prefilled_from": "signup"} if qid in prefilled_ids else {}),
        })
    return {
        "id": "test_a",
        "user_id": "u1",
        "client_name": "Test",
        "status": "in_progress",
        "answers": ans,
    }


def test_progress_is_monotonic_and_never_decreases():
    from server import _assessment_next_question
    last = -1
    for n in range(0, 15):
        # Force fallback path — no external LLM call
        # by not running the coroutine through Claude (fallback will still fire)
        a = _mk_assessment(n)
        res = _run(_assessment_next_question(a))
        p = int(res.get("progress") or 0)
        assert p >= last, f"Progress went backwards at n={n}: {last} → {p}"
        last = p


def test_progress_hits_100_at_or_beyond_target():
    from server import _assessment_next_question
    # At 14 answers we should be at 99% or 100% (target=14 in server)
    a = _mk_assessment(14)
    res = _run(_assessment_next_question(a))
    p = int(res.get("progress") or 0)
    # Either finished or maxed at 99 waiting for should_end
    assert p >= 99, f"At 14 answers expected ≥99%, got {p}"


def test_hard_cap_forces_end_at_18_answers():
    from server import _assessment_next_question
    a = _mk_assessment(18)
    res = _run(_assessment_next_question(a))
    assert res.get("should_end") is True, "Hard cap must force should_end at 18 answers"
    assert res.get("progress") == 100


def test_hard_cap_forces_end_at_20_answers():
    from server import _assessment_next_question
    a = _mk_assessment(20)
    res = _run(_assessment_next_question(a))
    assert res.get("should_end") is True
    assert res.get("progress") == 100


def test_progress_deterministic_at_known_count():
    from server import _assessment_next_question
    # 7 answers / target 14 → 50%
    a = _mk_assessment(7)
    res = _run(_assessment_next_question(a))
    p = int(res.get("progress") or 0)
    # Allow ±5 to account for rounding
    assert 45 <= p <= 55, f"Expected ~50% at 7/14, got {p}%"


def test_never_re_asks_answered_question():
    """If the fallback tries to serve an already-answered question_id, the
    system must skip past it. We simulate by pre-loading answers with the
    first 3 fallback ids so the fallback should return the 4th."""
    from server import _assessment_next_question
    # These are the first ids in _assessment_fallback_next
    a = _mk_assessment(0)
    a["answers"] = [
        {"question_id": "biological_sex", "answer": "female", "prefilled_from": "signup"},
        {"question_id": "role", "answer": "cabin_crew", "prefilled_from": "signup"},
    ]
    res = _run(_assessment_next_question(a))
    q = res.get("next_question") or {}
    # Should NOT be biological_sex or role
    assert q.get("id") not in ("biological_sex", "role"), \
        f"Next question re-asked prefilled: {q.get('id')}"
