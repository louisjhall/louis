"""
Iter 94g — the REAL P0 fix.

Mirrors the exact real-world flow the user hit:

  1. Sign up (writes profile.sex + profile.job_title).
  2. Complete /training-setup — this writes flying_type, primary_goal,
     training_days, time_home, equipment, hotel_gyms, injuries, no_go_movements
     directly onto users.profile.
  3. Start /assessment (the DNA flow).

BEFORE the fix: step 3 asked flying_type AND primary_goal again because
`assessment_start` didn't seed from `profile.flying_type` /
`profile.primary_goal_id`.

AFTER the fix: `_seed_assessment_from_profile` merges every profile-derived
essential into the assessment.answers list at start (and resume) time, so
none of those questions are re-asked.
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
        meta = q.get("meta") or {}
        return meta.get("min", 1)
    if qtype == "range":
        meta = q.get("meta") or {}
        return meta.get("min", 5)
    if qtype == "date":
        return "2026-12-31"
    if qtype == "event_builder":
        return []
    if qtype == "equipment_picker":
        return {"location": (q.get("meta") or {}).get("location", "home"),
                "equipment": ["bodyweight_only", "dumbbells"]}
    return "test"


def _signup(c: httpx.Client, email: str, job: str = "Cabin Crew") -> dict:
    r = c.post("/auth/signup", json={
        "name": "T",
        "email": email,
        "password": "Passw0rd!",
        "age_confirmed": True,
        "role": "client",
        "sex": "male",
        "job_title": job,
    })
    assert r.status_code in (200, 201), r.text
    j = r.json()
    tok = j.get("access_token") or j.get("token")
    assert tok, f"No token in signup: {j}"
    return {"Authorization": f"Bearer {tok}"}


def test_training_setup_then_dna_never_repeats_flying_or_goal():
    """
    The REAL P0. If a user completes /training-setup first, the DNA assessment
    MUST NOT re-ask flying_type or primary_goal.
    """
    email = f"iter94g_{int(time.time()*1000)}@t.com"
    with httpx.Client(base_url=BASE_URL, timeout=60) as c:
        h = _signup(c, email)

        # STEP A — the user completes /training-setup with the same fields
        # our real UI submits (flying_type, primary_goal, training_days,
        # time_home, equipment_home, hotel_gyms, injuries, no_go_movements).
        r = c.post("/profile/training-setup", json={
            "flying_type": "short_haul",   # short_haul → no layover questions
            "primary_goal": "lose_fat",
            "training_days": 4,
            "time_home": 45,
            "equipment_home": ["bodyweight_only", "dumbbells"],
            "injuries": "None",
            "no_go_movements": [],         # explicit "no restrictions"
        }, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["complete"] is True, (
            f"Expected training-setup to mark profile complete, got {r.json()}"
        )

        # STEP B — start DNA assessment. It must NOT re-ask flying_type or
        # primary_goal because both are already in the profile.
        r = c.post("/assessment/start", json={"seed_from_profile": True}, headers=h)
        assert r.status_code == 200, r.text
        d = r.json()
        aid = d["assessment_id"]
        q = d.get("next_question")

        seen_ids: list[str] = []
        loops = 0
        while q and loops < 25:
            loops += 1
            qid = q["id"]
            # THE ASSERTIONS THAT MATTER:
            assert qid != "flying_type", (
                f"DNA re-asked flying_type after /training-setup already saved it. "
                f"Seen so far: {seen_ids}"
            )
            assert qid != "primary_goal", (
                f"DNA re-asked primary_goal after /training-setup already saved it. "
                f"Seen so far: {seen_ids}"
            )
            assert qid != "training_days", (
                f"DNA re-asked training_days. Seen so far: {seen_ids}"
            )
            assert qid != "time_home", (
                f"DNA re-asked time_home. Seen so far: {seen_ids}"
            )
            assert qid != "equipment_home", (
                f"DNA re-asked equipment_home. Seen so far: {seen_ids}"
            )
            assert qid != "hotel_gyms", (
                f"DNA re-asked hotel_gyms even though flying_type=short_haul. "
                f"Seen so far: {seen_ids}"
            )
            assert qid != "time_layover", (
                f"DNA re-asked time_layover even though flying_type=short_haul. "
                f"Seen so far: {seen_ids}"
            )
            assert qid != "no_go_movements", (
                f"DNA re-asked no_go_movements. Seen so far: {seen_ids}"
            )
            assert qid != "injuries", (
                f"DNA re-asked injuries. Seen so far: {seen_ids}"
            )
            assert qid not in seen_ids, (
                f"Duplicate id {qid!r} within DNA flow. Seen: {seen_ids}"
            )
            seen_ids.append(qid)

            ans = _make_answer_for(q)
            r = c.post("/assessment/answer", json={
                "assessment_id": aid, "question_id": qid, "answer": ans,
            }, headers=h)
            assert r.status_code == 200, r.text
            d = r.json()
            if d.get("should_end"):
                break
            q = d.get("next_question")

        print(f"OK — after /training-setup, DNA only asked bonus qs: {seen_ids}")


def test_dna_only_no_training_setup_still_asks_essentials():
    """
    Sanity check the fix didn't break the other path: if a user goes STRAIGHT
    to DNA without completing /training-setup, DNA MUST still ask all the
    essentials.
    """
    email = f"iter94g_direct_{int(time.time()*1000)}@t.com"
    with httpx.Client(base_url=BASE_URL, timeout=60) as c:
        h = _signup(c, email)

        r = c.post("/assessment/start", json={"seed_from_profile": True}, headers=h)
        d = r.json()
        aid = d["assessment_id"]
        q = d.get("next_question")

        seen_ids: list[str] = []
        loops = 0
        while q and loops < 30:
            loops += 1
            qid = q["id"]
            assert qid not in seen_ids, f"DUPLICATE {qid} in DNA-only flow. Seen: {seen_ids}"
            seen_ids.append(qid)

            answer = _make_answer_for(q)
            if qid == "flying_type":
                answer = "long_haul"  # so time_layover & hotel_gyms get asked
            r = c.post("/assessment/answer", json={
                "assessment_id": aid, "question_id": qid, "answer": answer,
            }, headers=h)
            d = r.json()
            if d.get("should_end"):
                break
            q = d.get("next_question")

        needed = {"flying_type", "primary_goal", "training_days", "time_home",
                  "equipment_home", "injuries", "no_go_movements",
                  "time_layover", "hotel_gyms"}
        missing = needed - set(seen_ids)
        assert not missing, (
            f"DNA-only flow failed to ask essentials: {missing}. Seen: {seen_ids}"
        )
        print(f"OK — DNA-only flow asked all essentials: {seen_ids}")
