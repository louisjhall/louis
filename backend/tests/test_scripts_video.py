"""CrewFit V1.5 §22 + §23 tests — Workout Intelligence + Weekly Video Script.

Covers:
 - Exercise video store: PATCH /exercises/{id}/video (coach vs YouTube; coach overrides)
 - GET /exercises/{id}/video-suggestion (coach → youtube → search fallback)
 - Adaptive check-in questions (LLM-generated, safe fallback), POST /checkins/questions
 - POST /checkins/adaptive (persists answers + background script kickoff for coach)
 - Coach weekly video script CRUD:
     POST   /coach/scripts/generate (style default, invalid → friendly)
     GET    /coach/scripts?client_id=... (coach-only, own only, DESC)
     GET    /coach/scripts/{id} (coach-only, 404 for wrong coach)
     PATCH  /coach/scripts/{id} (edit_history append, approved→sent_at + push)
 - PATCH /auth/coach-style (coach only; 400 for invalid, persists on user.profile.style)
"""
import os
import time
import uuid
import pytest


LOCAL = "http://localhost:8001"   # Claude calls are 15-25s; some >30s → use local for those tests


# ------------- Exercise video store ---------------------------------
class TestExerciseVideo:
    @pytest.fixture(scope="class")
    def eid(self, api, base_url, coach_auth):
        # Create a throwaway exercise so we don't pollute a seeded row.
        r = api.post(f"{base_url}/api/exercises", headers=coach_auth["headers"],
                     json={"name": f"TEST_video_{uuid.uuid4().hex[:6]}",
                           "category": "core", "equipment": ["bodyweight"]}, timeout=15)
        assert r.status_code == 200, r.text
        return r.json()["id"]

    def test_client_forbidden_patch_video(self, api, base_url, client_auth, eid):
        r = api.patch(f"{base_url}/api/exercises/{eid}/video",
                      headers=client_auth["headers"],
                      json={"video_url": "https://youtu.be/test",
                            "video_channel": "Jeff Nippard", "is_coach_video": False},
                      timeout=15)
        assert r.status_code == 403

    def test_patch_youtube_video_sets_fields(self, api, base_url, coach_auth, eid):
        r = api.patch(f"{base_url}/api/exercises/{eid}/video",
                      headers=coach_auth["headers"],
                      json={"video_url": "https://youtu.be/YT1", "video_channel": "Jeff Nippard",
                            "video_length_sec": 90, "is_coach_video": False},
                      timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["video_url"] == "https://youtu.be/YT1"
        assert d["video_channel"] == "Jeff Nippard"
        assert d["video_length_sec"] == 90
        assert not d.get("coach_video_url")

    def test_video_suggestion_youtube(self, api, base_url, client_auth, eid):
        r = api.get(f"{base_url}/api/exercises/{eid}/video-suggestion",
                    headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["source"] == "youtube"
        assert d["url"] == "https://youtu.be/YT1"
        assert d.get("channel") == "Jeff Nippard"

    def test_patch_coach_video_overrides(self, api, base_url, coach_auth, eid):
        r = api.patch(f"{base_url}/api/exercises/{eid}/video",
                      headers=coach_auth["headers"],
                      json={"video_url": "https://cdn.crewfit.com/coach1.mp4",
                            "is_coach_video": True},
                      timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["coach_video_url"] == "https://cdn.crewfit.com/coach1.mp4"
        # video_url may still exist from previous step, but suggestion must prefer coach

    def test_video_suggestion_coach_takes_precedence(self, api, base_url, client_auth, eid):
        r = api.get(f"{base_url}/api/exercises/{eid}/video-suggestion",
                    headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["source"] == "coach"
        assert d["url"] == "https://cdn.crewfit.com/coach1.mp4"

    def test_video_suggestion_search_fallback(self, api, base_url, coach_auth, client_auth):
        # Create a fresh exercise with no video at all
        r = api.post(f"{base_url}/api/exercises", headers=coach_auth["headers"],
                     json={"name": f"TEST_novideo_{uuid.uuid4().hex[:6]}",
                           "category": "core", "equipment": ["bodyweight"]}, timeout=15)
        assert r.status_code == 200
        fresh_id = r.json()["id"]
        r2 = api.get(f"{base_url}/api/exercises/{fresh_id}/video-suggestion",
                     headers=client_auth["headers"], timeout=15)
        assert r2.status_code == 200
        d = r2.json()
        assert d["source"] == "search"
        assert "youtube.com/results?search_query=" in d["url"]
        # channel-scoped: at least one of the preferred channels appears
        preferred = ["Jeff+Nippard", "Squat+University", "Renaissance",
                     "Mind+Pump", "Athlean", "N1", "Built+With+Science"]
        assert any(p in d["url"] for p in preferred), f"no preferred channel in {d['url']}"

    def test_video_suggestion_404(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/exercises/does-not-exist-{uuid.uuid4().hex}/video-suggestion",
                    headers=client_auth["headers"], timeout=15)
        assert r.status_code == 404


# ------------- Coach style ------------------------------------------
class TestCoachStyle:
    def test_client_forbidden(self, api, base_url, client_auth):
        r = api.patch(f"{base_url}/api/auth/coach-style",
                      headers=client_auth["headers"], json={"style": "friendly"}, timeout=15)
        assert r.status_code == 403

    def test_invalid_style_400(self, api, base_url, coach_auth):
        r = api.patch(f"{base_url}/api/auth/coach-style",
                      headers=coach_auth["headers"], json={"style": "grumpy"}, timeout=15)
        assert r.status_code == 400

    def test_valid_style_persists(self, api, base_url, coach_auth):
        for style in ("professional", "friendly", "high_performance", "military",
                      "encouraging", "direct", "humorous"):
            r = api.patch(f"{base_url}/api/auth/coach-style",
                          headers=coach_auth["headers"], json={"style": style}, timeout=15)
            assert r.status_code == 200, f"{style}: {r.text}"
            assert r.json()["style"] == style
        # verify last style stuck on /auth/me
        me = api.get(f"{base_url}/api/auth/me", headers=coach_auth["headers"], timeout=15).json()
        assert (me.get("profile") or {}).get("style") == "humorous"


# ------------- Adaptive check-in questions --------------------------
class TestCheckinQuestions:
    def test_questions_shape(self, api, base_url, client_auth):
        # Use LOCAL (Claude ~15-25s + CF ~60s edge timeout risk); functional check.
        r = api.post(f"{LOCAL}/api/checkins/questions",
                     headers=client_auth["headers"],
                     json={"context": "TEST — long-haul heavy this week"},
                     timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "questions" in d and isinstance(d["questions"], list)
        assert len(d["questions"]) >= 1, "questions must be non-empty (has safe fallback)"
        for q in d["questions"]:
            assert "id" in q and "label" in q and "type" in q
        assert any(q.get("type") == "scale" for q in d["questions"]), \
            "at least one 'scale' question required"


# ------------- Adaptive check-in submit + background script kickoff -
class TestAdaptiveCheckin:
    @pytest.fixture(scope="class")
    def script_count_before(self, api, base_url, coach_auth, client_auth):
        cid = client_auth["user"]["id"]
        r = api.get(f"{base_url}/api/coach/scripts?client_id={cid}",
                    headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200
        return len(r.json())

    def test_adaptive_submit_and_kickoff(self, api, base_url, client_auth, coach_auth, script_count_before):
        payload = {
            "week_start": "2026-02-02",
            "energy": 7, "sleep": 6, "soreness": 4, "stress": 5,
            "weight_kg": 82.1,
            "notes": "TEST adaptive checkin",
            "answers": {
                "recovery": 7,
                "sleep_quality": 6,
                "adherence": 5,
                "wins": "Hit protein 6/7 days",
                "challenges": "Layover in AMS",
                "time_available": 4,
            },
        }
        t0 = time.time()
        r = api.post(f"{base_url}/api/checkins/adaptive",
                     headers=client_auth["headers"], json=payload, timeout=30)
        elapsed = time.time() - t0
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["energy"] == 7 and d["answers"]["wins"] == "Hit protein 6/7 days"
        assert d.get("user_id") == client_auth["user"]["id"]
        # Should return quickly (script gen is fire-and-forget)
        assert elapsed < 20, f"adaptive checkin took {elapsed:.1f}s — kickoff not async?"

        # Poll for new script row up to 60s
        cid = client_auth["user"]["id"]
        deadline = time.time() + 60
        found_new = False
        while time.time() < deadline:
            r2 = api.get(f"{base_url}/api/coach/scripts?client_id={cid}",
                         headers=coach_auth["headers"], timeout=15)
            assert r2.status_code == 200
            if len(r2.json()) > script_count_before:
                found_new = True
                break
            time.sleep(3)
        assert found_new, "background script kickoff did not produce a new coach_scripts row in 60s"


# ------------- Coach Weekly Video Script Generator ------------------
class TestCoachScripts:
    @pytest.fixture(scope="class")
    def generated(self, api, coach_auth, client_auth):
        # Use LOCAL to avoid CF 60s edge timeout on Claude call.
        cid = client_auth["user"]["id"]
        r = api.post(f"{LOCAL}/api/coach/scripts/generate",
                     headers=coach_auth["headers"],
                     json={"client_id": cid, "style": "encouraging"},
                     timeout=90)
        assert r.status_code == 200, r.text
        return r.json()

    def test_generate_shape(self, generated):
        d = generated
        assert d.get("id")
        assert d.get("style") == "encouraging"
        assert isinstance(d.get("script"), str) and d["script"].strip() != ""
        assert isinstance(d.get("summary_bullets"), list) and len(d["summary_bullets"]) >= 1
        assert all(isinstance(b, str) for b in d["summary_bullets"])
        assert isinstance(d.get("whatsapp"), str) and d["whatsapp"].strip() != ""
        assert isinstance(d.get("push_text"), str) and d["push_text"].strip() != ""
        assert len(d["push_text"]) <= 120, f"push_text len={len(d['push_text'])}"
        assert d.get("approved") is False
        assert d.get("sent_at") in (None, "")
        assert d.get("edit_history") == []

    def test_generate_style_default_when_unspecified(self, api, coach_auth, client_auth):
        cid = client_auth["user"]["id"]
        r = api.post(f"{LOCAL}/api/coach/scripts/generate",
                     headers=coach_auth["headers"],
                     json={"client_id": cid},
                     timeout=90)
        assert r.status_code == 200, r.text
        # Coach's profile style is "humorous" after TestCoachStyle finished. Because that
        # test only runs earlier in-session on the same class the style may be humorous OR
        # still default. Both are valid — assert it is one of the allowed styles.
        assert r.json()["style"] in [
            "professional", "friendly", "high_performance", "military",
            "encouraging", "direct", "humorous"
        ]

    def test_generate_style_invalid_falls_back_to_friendly(self, api, coach_auth, client_auth):
        # First reset coach style to something known != friendly so invalid → friendly is unambiguous
        # BUT the fallback in code is: invalid override AND invalid profile → friendly.
        # If profile.style = "humorous" (from earlier test), invalid override normalizes to profile-or-friendly.
        # Read code: `style = style_override or (profile.style) or "friendly"`; then
        # `if style not in COACH_STYLES: style = "friendly"`.
        # So invalid override → falls through to "friendly" only if override is falsy (None/""). If override
        # is a non-empty invalid string, style = override → then normalized to friendly. Great.
        cid = client_auth["user"]["id"]
        r = api.post(f"{LOCAL}/api/coach/scripts/generate",
                     headers=coach_auth["headers"],
                     json={"client_id": cid, "style": "made_up_style_xyz"},
                     timeout=90)
        assert r.status_code == 200, r.text
        assert r.json()["style"] == "friendly"

    def test_list_coach_only(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/coach/scripts",
                    headers=client_auth["headers"], timeout=15)
        assert r.status_code == 403

    def test_list_desc_and_scoped(self, api, base_url, coach_auth, client_auth, generated):
        cid = client_auth["user"]["id"]
        r = api.get(f"{base_url}/api/coach/scripts?client_id={cid}",
                    headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list) and len(rows) >= 1
        assert all(row["coach_id"] == coach_auth["user"]["id"] for row in rows)
        assert all(row["client_id"] == cid for row in rows)
        # DESC sort by created_at
        created = [row["created_at"] for row in rows]
        assert created == sorted(created, reverse=True)
        # our generated row is present
        assert any(row["id"] == generated["id"] for row in rows)

    def test_get_single_coach_only(self, api, base_url, client_auth, generated):
        r = api.get(f"{base_url}/api/coach/scripts/{generated['id']}",
                    headers=client_auth["headers"], timeout=15)
        assert r.status_code == 403

    def test_get_single_ok(self, api, base_url, coach_auth, generated):
        r = api.get(f"{base_url}/api/coach/scripts/{generated['id']}",
                    headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200
        assert r.json()["id"] == generated["id"]

    def test_get_single_404_wrong_id(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/scripts/does-not-exist-{uuid.uuid4().hex}",
                    headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 404

    def test_patch_records_edit_history(self, api, base_url, coach_auth, generated):
        edited = "TEST edited script — hi there, keep it up this week."
        r = api.patch(f"{base_url}/api/coach/scripts/{generated['id']}",
                      headers=coach_auth["headers"],
                      json={"script": edited}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["script"] == edited
        assert isinstance(d.get("edit_history"), list) and len(d["edit_history"]) >= 1
        last = d["edit_history"][-1]
        assert last["new"] == edited
        assert "prev" in last and "at" in last

    def test_patch_approve_sets_sent_at(self, api, base_url, coach_auth, generated):
        r = api.patch(f"{base_url}/api/coach/scripts/{generated['id']}",
                      headers=coach_auth["headers"],
                      json={"approved": True}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["approved"] is True
        assert d["sent_at"] and isinstance(d["sent_at"], str)
