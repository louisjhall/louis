"""
Iter 94f — DNA assessment MUST NOT ask duplicate / semantically-overlapping
questions.

Reproduces the P0 user-reported bug:
  "asking what flights they do again and what their goals are again"

Two levels of coverage:

1. UNIT — the pure functions
   * `_semantic_collision` catches rephrased LLM re-asks (e.g. `main_goal`,
     `flying_pattern`, `weekly_frequency`).
   * `_assessment_next_question` NEVER hands control to the LLM while any
     mandatory ID is still unanswered.

2. E2E — walk a real signup + assessment flow through the HTTP API using the
   short_haul short-circuit (so we don't need to answer time_layover /
   hotel_gyms). Assert every question_id is unique across the transcript
   and none re-asks an already-answered topic.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx
import pytest
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8001/api")


# ---------------------------------------------------------------------------
# UNIT LEVEL
# ---------------------------------------------------------------------------

def test_semantic_collision_catches_rephrased_flying():
    from server import _semantic_collision
    answered = {"biological_sex", "role", "flying_type", "primary_goal"}
    # These SHOULD collide.
    for cand in [
        {"id": "flying_pattern", "text": "What kind of flying do you mainly do?"},
        {"id": "flight_type", "text": "Do you fly long or short haul?"},
        {"id": "haul_mix", "text": "How's the haul mix?"},
        {"id": "route_focus", "text": "What's your route focus?"},
        {"id": "type_of_flying", "text": "Type of flying?"},
    ]:
        assert _semantic_collision(cand, answered), f"Should collide: {cand}"


def test_semantic_collision_catches_rephrased_goal():
    from server import _semantic_collision
    answered = {"biological_sex", "role", "flying_type", "primary_goal"}
    for cand in [
        {"id": "main_goal", "text": "What's your main training goal?"},
        {"id": "top_goal", "text": "Your top priority?"},
        {"id": "training_goal", "text": "Primary training goal?"},
        {"id": "your_goal", "text": "Your goal?"},
    ]:
        assert _semantic_collision(cand, answered), f"Should collide: {cand}"


def test_semantic_collision_allows_legit_new_topics():
    from server import _semantic_collision
    answered = {"biological_sex", "role", "flying_type", "primary_goal"}
    for cand in [
        {"id": "sleep_quality", "text": "How's your sleep?"},
        {"id": "wearables", "text": "Do you use a wearable?"},
        {"id": "family", "text": "Family commitments?"},
        {"id": "coffee_habits", "text": "How much caffeine per day?"},
    ]:
        assert not _semantic_collision(cand, answered), \
            f"Should NOT collide: {cand}"


def test_next_question_stays_deterministic_while_mandatory_missing():
    """The LLM must NEVER be invoked while any essential is unanswered."""
    from server import _assessment_next_question
    # Simulate a partial short_haul flow — primary_goal answered but
    # training_days / time_home / equipment_home / injuries / no_go_movements
    # still missing.
    assessment = {
        "answers": [
            {"question_id": "biological_sex", "answer": "male"},
            {"question_id": "role", "answer": "pilot"},
            {"question_id": "flying_type", "answer": "short_haul"},
            {"question_id": "time_layover", "answer": "0"},
            {"question_id": "hotel_gyms", "answer": "never"},
            {"question_id": "primary_goal", "answer": ["marathon"]},
        ],
        "client_name": "T",
    }
    result = asyncio.get_event_loop().run_until_complete(
        _assessment_next_question(assessment)
    )
    q = result.get("next_question") or {}
    # The next question MUST come from the deterministic fb catalogue — never
    # an invented rephrase. And it must NOT duplicate any answered id.
    already = {a["question_id"] for a in assessment["answers"]}
    assert q.get("id") not in already
    # Reasonable next in fb order once mandatory-only guard kicks in: `why`
    # (non-mandatory, allowed) OR `training_days` (next mandatory). Either is fine.
    assert q.get("id") in {
        "why", "events", "experience", "training_days",
        "time_home", "equipment_home", "injuries", "no_go_movements",
    }, f"Unexpected next q_id={q.get('id')}"


# ---------------------------------------------------------------------------
# E2E — full flow through HTTP
# ---------------------------------------------------------------------------

def test_e2e_no_duplicate_ids_short_haul():
    """Sign up a fresh user, walk the whole DNA assessment, assert unique ids
    and no semantic collisions. Sync so pytest works without pytest-asyncio."""
    _run_e2e()


def _run_e2e():
    from server import _semantic_collision

    email = f"iter94f_{int(time.time()*1000)}@t.com"
    password = "Passw0rd!"
    with httpx.Client(base_url=BASE_URL, timeout=60) as c:
        r = c.post("/auth/signup", json={
            "name": "T",
            "email": email,
            "password": password,
            "age_confirmed": True,
            "role": "client",
            "profile": {"sex": "male", "job_title": "Cabin Crew"},
        })
        assert r.status_code in (200, 201), r.text
        j = r.json()
        token = j.get("access_token") or j.get("token")
        assert token, f"No token in signup response: {j}"
        h = {"Authorization": f"Bearer {token}"}

        r = c.post("/assessment/start", json={"seed_from_profile": True}, headers=h)
        assert r.status_code == 200, r.text
        d = r.json()
        aid = d["assessment_id"]
        q = d.get("next_question")

        asked_ids: list[str] = []
        loops = 0
        while q and loops < 30:
            loops += 1
            qid = q["id"]
            assert qid not in asked_ids, (
                f"DUPLICATE ID {qid!r} — already asked at position "
                f"{asked_ids.index(qid)} of {asked_ids}"
            )
            assert not _semantic_collision(q, set(asked_ids)), (
                f"SEMANTIC DUPLICATE — q={qid!r} text={q.get('text')!r} "
                f"already_asked={asked_ids}"
            )
            asked_ids.append(qid)
            answer = _make_answer_for(q)
            r = c.post("/assessment/answer", json={
                "assessment_id": aid,
                "question_id": qid,
                "answer": answer,
            }, headers=h)
            assert r.status_code == 200, r.text
            d = r.json()
            if d.get("should_end"):
                break
            q = d.get("next_question")

        expected_mandatory = {
            "biological_sex", "role", "flying_type", "primary_goal",
            "training_days", "time_home", "equipment_home",
            "injuries", "no_go_movements",
        }
        # signup prefilled biological_sex + role
        expected_mandatory -= {"biological_sex", "role"}
        missing = expected_mandatory - set(asked_ids)
        assert not missing, (
            f"Mandatory questions were never asked: {missing}. "
            f"Actually asked: {asked_ids}"
        )
        print(f"OK — E2E walked {len(asked_ids)} unique questions: {asked_ids}")


def _make_answer_for(q: dict) -> Any:
    """Return a valid answer for a question we're auto-answering in tests."""
    qtype = q.get("type")
    qid = q.get("id")
    opts = q.get("options") or []
    if qid == "flying_type":
        return "short_haul"           # so time_layover / hotel_gyms are skipped
    if qtype == "single_select":
        # Pick the first non-explicit-none option.
        return (opts[0]["id"] if opts else "yes")
    if qtype == "multi_select":
        return [opts[0]["id"]] if opts else ["none"]
    if qtype == "short_text":
        return "test"
    if qtype == "long_text":
        return "no issues"
    if qtype == "number":
        meta = q.get("meta") or {}
        return meta.get("min", 1)
    if qtype == "date":
        return "2026-12-31"
    if qtype == "range":
        meta = q.get("meta") or {}
        return meta.get("min", 5)
    if qtype == "event_builder":
        return []
    if qtype == "equipment_picker":
        return {"location": (q.get("meta") or {}).get("location", "home"),
                "equipment": ["bodyweight_only", "dumbbells"]}
    return "test"
