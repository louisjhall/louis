"""
Iter 94g follow-up — the "Finalise failed / Louis needs a few more answers"
modal that showed up at the end of DNA even though every essential was
already on the profile (written by /training-setup).

The bug was in `_missing_essential_fields`: it only checked `profile.*` for
`flying_type`. Every other essential was required in the assessment answers
list — profile equivalents were IGNORED. So a user who filled /training-setup
first (which writes profile.equipment / .training_days_per_week / .time_home_min
/ .primary_goal_id / etc.) would be blocked at finalize even though they'd
answered everything.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8001/api")


def _make_answer_for(q: dict) -> Any:
    qtype = q.get("type")
    opts = q.get("options") or []
    if qtype == "single_select":
        return (opts[0]["id"] if opts else "yes")
    if qtype == "multi_select":
        return [opts[0]["id"]] if opts else ["none"]
    if qtype == "long_text":
        return "no issues"
    if qtype == "short_text":
        return "test"
    if qtype == "number":
        return (q.get("meta") or {}).get("min", 1)
    if qtype == "range":
        return (q.get("meta") or {}).get("min", 5)
    if qtype == "date":
        return "2026-12-31"
    if qtype == "event_builder":
        return []
    if qtype == "equipment_picker":
        return {"location": (q.get("meta") or {}).get("location", "home"),
                "equipment": ["bodyweight_only", "dumbbells"]}
    return "test"


def _signup_and_setup(c: httpx.Client, email: str) -> dict:
    r = c.post("/auth/signup", json={
        "name": "T", "email": email, "password": "Passw0rd!",
        "age_confirmed": True, "role": "client",
        "sex": "male", "job_title": "Cabin Crew",
    })
    assert r.status_code in (200, 201), r.text
    j = r.json()
    h = {"Authorization": f"Bearer {j.get('token') or j.get('access_token')}"}
    r = c.post("/profile/training-setup", json={
        "flying_type": "short_haul",
        "primary_goal": "lose_fat",
        "training_days": 4,
        "time_home": 45,
        "equipment_home": ["bodyweight_only", "dumbbells"],
        "injuries": "None",
        "no_go_movements": [],
    }, headers=h)
    assert r.status_code == 200, r.text
    return h


def test_finalize_succeeds_after_training_setup_only():
    """
    User completes /training-setup FIRST, then walks the DNA assessment.
    DNA now only asks bonus questions. When the user hits should_end and
    the client calls /assessment/finalize, we must NOT block with
    'Louis needs a few more answers' — every essential is on the profile.
    """
    email = f"iter94g_fin_{int(time.time()*1000)}@t.com"
    with httpx.Client(base_url=BASE_URL, timeout=90) as c:
        h = _signup_and_setup(c, email)

        # Start & walk the DNA assessment (only bonus questions expected).
        r = c.post("/assessment/start", json={"seed_from_profile": True}, headers=h)
        assert r.status_code == 200, r.text
        d = r.json()
        aid = d["assessment_id"]
        q = d.get("next_question")

        answered_qids: list[str] = []
        loops = 0
        while q and loops < 25:
            loops += 1
            qid = q["id"]
            answered_qids.append(qid)
            ans = _make_answer_for(q)
            r = c.post("/assessment/answer", json={
                "assessment_id": aid, "question_id": qid, "answer": ans,
            }, headers=h)
            assert r.status_code == 200, r.text
            d = r.json()
            if d.get("should_end"):
                break
            q = d.get("next_question")

        # Now the client-side calls /assessment/finalize.
        r = c.post("/assessment/finalize", json={"assessment_id": aid}, headers=h)
        assert r.status_code == 200, (
            f"Finalize BLOCKED even though profile has every essential. "
            f"Response: {r.status_code} {r.text}. "
            f"DNA questions answered: {answered_qids}"
        )
        dna = r.json().get("dna")
        assert dna, f"Finalize succeeded but no DNA returned: {r.json()}"
        print(f"OK — finalize succeeded, DNA v{dna.get('version', '?')} created. "
              f"DNA-side bonus qs answered: {answered_qids}")


def test_finalize_blocked_when_actually_missing():
    """
    Sanity: if user really hasn't given essentials, finalize DOES still block
    with the profile_incomplete error (safety net still works).
    """
    email = f"iter94g_finblock_{int(time.time()*1000)}@t.com"
    with httpx.Client(base_url=BASE_URL, timeout=60) as c:
        # SKIP /training-setup — signup only, so profile is nearly empty.
        r = c.post("/auth/signup", json={
            "name": "T", "email": email, "password": "Passw0rd!",
            "age_confirmed": True, "role": "client",
            "sex": "male", "job_title": "Cabin Crew",
        })
        j = r.json()
        h = {"Authorization": f"Bearer {j.get('token') or j.get('access_token')}"}

        r = c.post("/assessment/start", json={"seed_from_profile": True}, headers=h)
        aid = r.json()["assessment_id"]

        # Try to finalize immediately with basically nothing answered.
        r = c.post("/assessment/finalize", json={"assessment_id": aid}, headers=h)
        assert r.status_code == 400, (
            f"Expected 400 profile_incomplete but got {r.status_code}: {r.text}"
        )
        detail = r.json().get("detail") or {}
        assert detail.get("code") == "profile_incomplete", detail
        assert detail.get("missing_fields"), detail
        print(f"OK — safety-net finalize block still works: "
              f"missing={detail.get('missing_fields')}")
