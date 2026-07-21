"""
Iter 82 — /api/assessment/start pre-seeds biological_sex and role from signup
data so the DNA assessment does not re-ask questions the client answered
during signup.
"""
import sys
import uuid as _uuid
sys.path.insert(0, "/app/backend")


def _signup_client(api, base_url, *, sex: str, job_title: str) -> dict:
    tag = _uuid.uuid4().hex[:8]
    email = f"prefill_{tag}@test.com"
    payload = {
        "email": email,
        "password": "Test123!",
        "name": f"Prefill {tag}",
        "first_name": "Prefill",
        "last_name": tag[:4],
        "role": "client",
        "age_confirmed": True,
        "age": 28,
        "sex": sex,
        "height_cm": 172,
        "weight_kg": 70,
        "airline": "British Airways",
        "job_title": job_title,
        "home_base": "LHR",
    }
    r = api.post(f"{base_url}/api/auth/signup", json=payload, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    return {"token": body["token"], "user": body["user"], "email": email}


def test_signup_seeds_sex_and_role_into_profile(api, base_url):
    auth = _signup_client(api, base_url, sex="female", job_title="Cabin Crew")
    me = api.get(f"{base_url}/api/auth/me", headers={"Authorization": f"Bearer {auth['token']}"}, timeout=30)
    assert me.status_code == 200
    profile = (me.json().get("profile") or {})
    assert profile.get("sex") == "female"
    assert profile.get("job_title") == "Cabin Crew"


def test_assessment_start_prefills_biological_sex_and_role_cabin_crew(api, base_url):
    auth = _signup_client(api, base_url, sex="female", job_title="Cabin Crew")
    r = api.post(
        f"{base_url}/api/assessment/start",
        json={},
        headers={"Authorization": f"Bearer {auth['token']}"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    aid = body["assessment_id"]

    # Fetch the assessment doc to inspect pre-seeded answers
    cur = api.get(
        f"{base_url}/api/assessment/current",
        headers={"Authorization": f"Bearer {auth['token']}"},
        timeout=30,
    )
    assert cur.status_code == 200
    assessment = cur.json().get("assessment") or {}
    assert assessment.get("id") == aid
    answers = assessment.get("answers") or []
    answered_ids = {a.get("question_id") for a in answers}
    assert "biological_sex" in answered_ids, "biological_sex must be pre-seeded from signup"
    assert "role" in answered_ids, "aviation role must be pre-seeded from signup"

    # Values must be correctly normalised
    sex_ans = next(a for a in answers if a["question_id"] == "biological_sex")
    role_ans = next(a for a in answers if a["question_id"] == "role")
    assert sex_ans["answer"] == "female"
    assert role_ans["answer"] == "cabin_crew"
    assert sex_ans.get("prefilled_from") == "signup"
    assert role_ans.get("prefilled_from") == "signup"

    # Next question offered must NOT be biological_sex or role
    nxt = body.get("next_question") or {}
    assert nxt.get("id") not in ("biological_sex", "role"), \
        f"DNA should not re-ask a prefilled question — got {nxt.get('id')}"


def test_assessment_start_prefills_pilot_role_for_first_officer(api, base_url):
    auth = _signup_client(api, base_url, sex="male", job_title="First Officer")
    r = api.post(
        f"{base_url}/api/assessment/start",
        json={},
        headers={"Authorization": f"Bearer {auth['token']}"},
        timeout=30,
    )
    assert r.status_code == 200
    cur = api.get(
        f"{base_url}/api/assessment/current",
        headers={"Authorization": f"Bearer {auth['token']}"},
        timeout=30,
    )
    assessment = cur.json().get("assessment") or {}
    answers = assessment.get("answers") or []
    role_ans = next((a for a in answers if a["question_id"] == "role"), None)
    sex_ans = next((a for a in answers if a["question_id"] == "biological_sex"), None)
    assert role_ans is not None and role_ans["answer"] == "pilot"
    assert sex_ans is not None and sex_ans["answer"] == "male"


def test_assessment_start_prefill_captain_maps_to_pilot(api, base_url):
    auth = _signup_client(api, base_url, sex="male", job_title="Captain")
    r = api.post(
        f"{base_url}/api/assessment/start",
        json={},
        headers={"Authorization": f"Bearer {auth['token']}"},
        timeout=30,
    )
    assert r.status_code == 200
    cur = api.get(
        f"{base_url}/api/assessment/current",
        headers={"Authorization": f"Bearer {auth['token']}"},
        timeout=30,
    )
    answers = (cur.json().get("assessment") or {}).get("answers") or []
    role_ans = next((a for a in answers if a["question_id"] == "role"), None)
    assert role_ans and role_ans["answer"] == "pilot"


def test_assessment_start_prefer_not_to_say_maps_to_intersex_prefer_not(api, base_url):
    auth = _signup_client(api, base_url, sex="prefer_not_to_say", job_title="Cabin Crew")
    r = api.post(
        f"{base_url}/api/assessment/start",
        json={},
        headers={"Authorization": f"Bearer {auth['token']}"},
        timeout=30,
    )
    assert r.status_code == 200
    cur = api.get(
        f"{base_url}/api/assessment/current",
        headers={"Authorization": f"Bearer {auth['token']}"},
        timeout=30,
    )
    answers = (cur.json().get("assessment") or {}).get("answers") or []
    sex_ans = next((a for a in answers if a["question_id"] == "biological_sex"), None)
    assert sex_ans and sex_ans["answer"] == "intersex_prefer_not"
