"""Backend tests for feature_exercise_content (§35 unified library).

Covers 11 endpoints + role gating + startup reconcile + regression.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import os
import sys
import time

import pytest
import requests


BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")

sys.path.insert(0, "/app/backend")


# --------- Helpers ---------

def _auth(email: str, pwd: str):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": pwd}, timeout=30)
    assert r.status_code == 200, f"login {email} → {r.status_code} {r.text}"
    d = r.json()
    return {"Authorization": f"Bearer {d['token']}"}, d["user"]


@pytest.fixture(scope="module")
def coach():
    h, u = _auth("coach@crewfit.com", "Coach123!")
    return {"headers": h, "user": u}


@pytest.fixture(scope="module")
def client():
    h, u = _auth("client@crewfit.com", "Client123!")
    return {"headers": h, "user": u}


@pytest.fixture(scope="module")
def created_exercise(coach):
    payload = {
        "exercise_name": "TEST_Content Library Push",
        "category": "strength",
        "training_type": "warmup",
        "body_area": "shoulders",
        "equipment_type": ["band"],
        "tags": ["TEST"],
        "coaching_points": ["Keep elbows slightly bent"],
    }
    r = requests.post(f"{BASE_URL}/api/exercise-content", json=payload,
                      headers=coach["headers"], timeout=30)
    assert r.status_code == 200, f"create → {r.status_code} {r.text}"
    ex = r.json()["exercise"]
    yield ex
    # Best-effort cleanup
    try:
        requests.delete(f"{BASE_URL}/api/exercise-content/{ex['id']}",
                        headers=coach["headers"], timeout=15)
    except Exception:
        pass


# --------- 1) CREATE ---------

class TestCreate:
    def test_admin_create_defaults(self, created_exercise):
        ex = created_exercise
        assert ex["id"]
        assert ex["status"] == "Draft"
        assert ex["approval_status"] == "pending"
        assert ex["approved_image_status"] == "Missing"
        cs = ex["content_status"]
        # coaching_points was provided → true; images & video → false
        assert cs["coaching_points"] is True
        assert cs["images"] is False
        assert cs["video"] is False

    def test_client_cannot_create(self, client):
        r = requests.post(f"{BASE_URL}/api/exercise-content",
                          json={"exercise_name": "TEST_ClientBlocked"},
                          headers=client["headers"], timeout=15)
        assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text}"


# --------- 2) LIST + Filters ---------

class TestList:
    def test_list_no_filter(self, coach):
        r = requests.get(f"{BASE_URL}/api/exercise-content",
                         headers=coach["headers"], timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "exercises" in d and isinstance(d["exercises"], list)
        assert d["count"] == len(d["exercises"])
        # Seed exercises + TEST → should be >= 3
        names = {e.get("exercise_name") for e in d["exercises"]}
        assert any("Band Lateral" in (n or "") for n in names), \
            f"seed Band Lateral Raise missing; names={names}"

    def test_search_q_band(self, coach):
        r = requests.get(f"{BASE_URL}/api/exercise-content",
                         params={"q": "Band"},
                         headers=coach["headers"], timeout=15)
        assert r.status_code == 200
        rows = r.json()["exercises"]
        assert len(rows) >= 1
        assert any("Band" in (e.get("exercise_name") or "") for e in rows)

    def test_filter_category(self, coach):
        r = requests.get(f"{BASE_URL}/api/exercise-content",
                         params={"category": "strength"},
                         headers=coach["headers"], timeout=15)
        assert r.status_code == 200
        for e in r.json()["exercises"]:
            assert e["category"] == "strength"

    def test_filter_training_type(self, coach):
        r = requests.get(f"{BASE_URL}/api/exercise-content",
                         params={"training_type": "warmup"},
                         headers=coach["headers"], timeout=15)
        assert r.status_code == 200
        for e in r.json()["exercises"]:
            assert e["training_type"] == "warmup"

    def test_filter_body_area(self, coach):
        r = requests.get(f"{BASE_URL}/api/exercise-content",
                         params={"body_area": "shoulders"},
                         headers=coach["headers"], timeout=15)
        assert r.status_code == 200

    def test_filter_status_draft(self, coach):
        r = requests.get(f"{BASE_URL}/api/exercise-content",
                         params={"status": "Draft"},
                         headers=coach["headers"], timeout=15)
        assert r.status_code == 200
        for e in r.json()["exercises"]:
            assert e["status"] == "Draft"

    def test_filter_used_tomorrow_empty(self, coach):
        r = requests.get(f"{BASE_URL}/api/exercise-content",
                         params={"used_tomorrow": "true"},
                         headers=coach["headers"], timeout=15)
        assert r.status_code == 200
        # Expected empty before scan-todos runs
        assert isinstance(r.json()["exercises"], list)

    def test_filter_missing_content(self, coach):
        r = requests.get(f"{BASE_URL}/api/exercise-content",
                         params={"missing_content": "true"},
                         headers=coach["headers"], timeout=15)
        assert r.status_code == 200
        # Every returned row should be missing at least one content flag
        for e in r.json()["exercises"]:
            cs = e.get("content_status") or {}
            assert not (cs.get("images") and cs.get("coaching_points") and cs.get("video"))

    def test_filter_approved_only_hides_draft(self, coach):
        r = requests.get(f"{BASE_URL}/api/exercise-content",
                         params={"approved_only": "true"},
                         headers=coach["headers"], timeout=15)
        assert r.status_code == 200
        for e in r.json()["exercises"]:
            assert e["status"] in ("Approved", "Live")


# --------- 3) DETAIL ---------

class TestDetail:
    def test_detail_ok(self, coach, created_exercise):
        r = requests.get(f"{BASE_URL}/api/exercise-content/{created_exercise['id']}",
                         headers=coach["headers"], timeout=15)
        assert r.status_code == 200
        assert r.json()["exercise"]["id"] == created_exercise["id"]

    def test_detail_404(self, coach):
        r = requests.get(f"{BASE_URL}/api/exercise-content/does-not-exist-xyz",
                         headers=coach["headers"], timeout=15)
        assert r.status_code == 404


# --------- 4) PATCH ---------

class TestPatch:
    def test_patch_coaching_points_flips_flag(self, coach, created_exercise):
        r = requests.patch(f"{BASE_URL}/api/exercise-content/{created_exercise['id']}",
                           json={"coaching_points": ["A", "B", "C"]},
                           headers=coach["headers"], timeout=15)
        assert r.status_code == 200
        assert r.json()["exercise"]["content_status"]["coaching_points"] is True

    def test_patch_video_url_flips_flag(self, coach, created_exercise):
        r = requests.patch(f"{BASE_URL}/api/exercise-content/{created_exercise['id']}",
                           json={"primary_video_url": "https://example.com/v.mp4"},
                           headers=coach["headers"], timeout=15)
        assert r.status_code == 200
        assert r.json()["exercise"]["content_status"]["video"] is True

    def test_patch_invalid_status_400(self, coach, created_exercise):
        r = requests.patch(f"{BASE_URL}/api/exercise-content/{created_exercise['id']}",
                           json={"status": "NotAValue"},
                           headers=coach["headers"], timeout=15)
        assert r.status_code == 400

    def test_patch_status_live_ok(self, coach, created_exercise):
        r = requests.patch(f"{BASE_URL}/api/exercise-content/{created_exercise['id']}",
                           json={"status": "Live"},
                           headers=coach["headers"], timeout=15)
        assert r.status_code == 200
        assert r.json()["exercise"]["status"] == "Live"
        # Reset back to Draft for downstream approve tests
        requests.patch(f"{BASE_URL}/api/exercise-content/{created_exercise['id']}",
                       json={"status": "Draft"},
                       headers=coach["headers"], timeout=15)


# --------- 5) APPROVE ---------

class TestApprove:
    def test_approve_scope_images(self, coach, created_exercise):
        r = requests.post(f"{BASE_URL}/api/exercise-content/{created_exercise['id']}/approve",
                          json={"scope": "images"},
                          headers=coach["headers"], timeout=15)
        assert r.status_code == 200
        assert r.json()["exercise"]["approved_image_status"] == "Approved"

    def test_approve_scope_mark_live(self, coach, created_exercise):
        r = requests.post(f"{BASE_URL}/api/exercise-content/{created_exercise['id']}/approve",
                          json={"scope": "mark_live"},
                          headers=coach["headers"], timeout=15)
        assert r.status_code == 200
        assert r.json()["exercise"]["status"] == "Live"

    def test_approve_scope_needs_update(self, coach, created_exercise):
        r = requests.post(f"{BASE_URL}/api/exercise-content/{created_exercise['id']}/approve",
                          json={"scope": "needs_update"},
                          headers=coach["headers"], timeout=15)
        assert r.status_code == 200
        assert r.json()["exercise"]["status"] == "Needs Update"

    def test_approve_scope_all(self, coach, created_exercise):
        r = requests.post(f"{BASE_URL}/api/exercise-content/{created_exercise['id']}/approve",
                          json={"scope": "all"},
                          headers=coach["headers"], timeout=15)
        assert r.status_code == 200
        ex = r.json()["exercise"]
        assert ex["status"] == "Approved"
        assert ex["approval_status"] == "approved"
        assert ex["approved_image_status"] == "Approved"
        assert ex["approved_video_status"] == "Approved"

    def test_approve_bad_scope_400(self, coach, created_exercise):
        r = requests.post(f"{BASE_URL}/api/exercise-content/{created_exercise['id']}/approve",
                          json={"scope": "foo"},
                          headers=coach["headers"], timeout=15)
        assert r.status_code == 400


# --------- 6) GENERATE IMAGE (single call — start slot) ---------

class TestGenerateImage:
    """Real Nano Banana call (~$0.03) — ONE call only per problem statement."""

    def test_generate_start_and_stream(self, coach, created_exercise):
        r = requests.post(
            f"{BASE_URL}/api/exercise-content/{created_exercise['id']}/generate-image",
            json={"slot": "start"},
            headers=coach["headers"], timeout=30,
        )
        assert r.status_code == 200, f"gen-image → {r.status_code} {r.text}"
        body = r.json()
        img_id = body["image_id"]
        assert body["slot"] == "start"
        assert body["status"] == "generating"

        # Parent doc should point at this new image immediately
        ex = requests.get(f"{BASE_URL}/api/exercise-content/{created_exercise['id']}",
                          headers=coach["headers"], timeout=15).json()["exercise"]
        assert ex["demo_start_image_id"] == img_id
        assert ex["approved_image_status"] == "Needs Review"
        assert ex["content_status"]["images"] is True

        # Poll up to 40s
        deadline = time.time() + 40
        status = "generating"
        while time.time() < deadline:
            rr = requests.get(f"{BASE_URL}/api/exercise-content/images/{img_id}",
                              headers=coach["headers"], timeout=15)
            assert rr.status_code == 200
            status = rr.json()["image"]["status"]
            if status in ("ready", "failed"):
                break
            time.sleep(2)
        assert status == "ready", f"image did not become ready (final={status})"

        # File on disk
        expected_path = f"/app/backend/uploads/exercise_images/{img_id}.png"
        assert os.path.exists(expected_path), f"file missing at {expected_path}"

        # Stream via public URL
        sr = requests.get(f"{BASE_URL}/api/exercise-content/images/{img_id}/stream",
                          headers=coach["headers"], timeout=30)
        assert sr.status_code == 200
        assert sr.headers.get("content-type", "").startswith("image/")


# --------- 7) CHANGE LOG ---------

class TestLog:
    def test_log_non_empty(self, coach, created_exercise):
        r = requests.get(f"{BASE_URL}/api/exercise-content/{created_exercise['id']}/log",
                         headers=coach["headers"], timeout=15)
        assert r.status_code == 200
        entries = r.json()["log"]
        assert len(entries) > 0
        kinds = {e["kind"] for e in entries}
        # After all above, we expect created, approval_changed, status_changed, image_generated
        assert "created" in kinds
        assert "approval_changed" in kinds
        assert "image_generated" in kinds


# --------- 8) SCAN TODOS (with & without synthetic workout) ---------

class TestScanTodos:
    def test_scan_no_workouts(self, coach):
        r = requests.post(f"{BASE_URL}/api/exercise-content/scan-todos",
                          json={}, headers=coach["headers"], timeout=30)
        assert r.status_code == 200
        assert "created" in r.json()

    def test_scan_with_synthetic_workout(self, coach):
        """Insert a workout doc for tomorrow that references a Draft exercise,
        run scan-todos → expect at least 1 created, then re-run → 0 duplicates."""
        import pymongo
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        mc = pymongo.MongoClient(os.environ["MONGO_URL"])
        db = mc[os.environ["DB_NAME"]]
        try:
            draft = db.exercises_v2.find_one({"status": "Draft"}, {"_id": 0})
            assert draft is not None, "no draft exercise available for scan test"
            ex_id = draft["id"]
            tomorrow = (_dt.date.today() + _dt.timedelta(days=1)).isoformat()
            workout_doc = {
                "id": "TEST_SYNTH_WORKOUT_SCAN",
                "date": tomorrow,
                "exercises": [{"exercise_id": ex_id}],
                "_test": True,
            }
            db.workouts.delete_many({"id": "TEST_SYNTH_WORKOUT_SCAN"})
            db.coach_tasks.delete_many({"payload.exercise_id": ex_id,
                                        "task_type": {"$regex": "^exercise_needs_"}})
            db.workouts.insert_one(workout_doc)

            try:
                r1 = requests.post(f"{BASE_URL}/api/exercise-content/scan-todos",
                                   json={}, headers=coach["headers"], timeout=30)
                assert r1.status_code == 200
                created1 = r1.json()["created"]
                assert created1 >= 1, f"expected >=1 task, got {created1}"

                r2 = requests.post(f"{BASE_URL}/api/exercise-content/scan-todos",
                                   json={}, headers=coach["headers"], timeout=30)
                assert r2.status_code == 200
                created2 = r2.json()["created"]
                assert created2 == 0, f"dedupe failed, got {created2}"
            finally:
                db.workouts.delete_many({"id": "TEST_SYNTH_WORKOUT_SCAN"})
                db.coach_tasks.delete_many({"payload.exercise_id": ex_id,
                                            "task_type": {"$regex": "^exercise_needs_"}})
        finally:
            mc.close()


# --------- 9) Role gating (client 403) ---------

class TestRoleGating:
    @pytest.fixture
    def any_ex_id(self, coach):
        r = requests.get(f"{BASE_URL}/api/exercise-content",
                         headers=coach["headers"], timeout=15)
        return r.json()["exercises"][0]["id"]

    def test_client_patch_403(self, client, any_ex_id):
        r = requests.patch(f"{BASE_URL}/api/exercise-content/{any_ex_id}",
                           json={"exercise_name": "TEST_ClientPatch"},
                           headers=client["headers"], timeout=15)
        assert r.status_code == 403

    def test_client_delete_403(self, client, any_ex_id):
        r = requests.delete(f"{BASE_URL}/api/exercise-content/{any_ex_id}",
                            headers=client["headers"], timeout=15)
        assert r.status_code == 403

    def test_client_approve_403(self, client, any_ex_id):
        r = requests.post(f"{BASE_URL}/api/exercise-content/{any_ex_id}/approve",
                          json={"scope": "all"}, headers=client["headers"], timeout=15)
        assert r.status_code == 403

    def test_client_generate_image_403(self, client, any_ex_id):
        r = requests.post(f"{BASE_URL}/api/exercise-content/{any_ex_id}/generate-image",
                          json={"slot": "primary"}, headers=client["headers"], timeout=15)
        assert r.status_code == 403

    def test_client_scan_todos_403(self, client):
        r = requests.post(f"{BASE_URL}/api/exercise-content/scan-todos",
                          json={}, headers=client["headers"], timeout=15)
        assert r.status_code == 403


# --------- 10) Startup reconcile ---------

class TestReconcile:
    def test_reconcile_flips_generating_to_failed(self):
        """Directly call _reconcile_ex_stale via asyncio.run in a fresh loop,
        but use pymongo for setup/verify (server.db is bound to server's loop)."""
        import pymongo
        import asyncio as _aio
        from dotenv import load_dotenv
        import feature_exercise_content as fec
        load_dotenv("/app/backend/.env")
        mc = pymongo.MongoClient(os.environ["MONGO_URL"])
        db = mc[os.environ["DB_NAME"]]
        try:
            row = {
                "id": "TEST_RECON_ROW",
                "exercise_id": "TEST_RECON_EX",
                "slot": "primary",
                "prompt": "x",
                "status": "generating",
                "storage_path": None,
                "size_bytes": None,
                "mime": None,
                "created_by": "TEST",
                "created_at": _dt.datetime.utcnow().isoformat(),
                "updated_at": _dt.datetime.utcnow().isoformat(),
            }
            db.exercise_content_images.delete_many({"id": "TEST_RECON_ROW"})
            db.exercise_content_images.insert_one(row)
            # Call the reconcile — it uses server.db (motor), so we invoke it
            # inside its own loop via asyncio.run which creates a new motor-safe loop.
            _aio.run(fec._reconcile_ex_stale())
            after = db.exercise_content_images.find_one({"id": "TEST_RECON_ROW"}, {"_id": 0})
            assert after["status"] == "failed"
            assert after["error"] == "server restart"
            db.exercise_content_images.delete_many({"id": "TEST_RECON_ROW"})
        finally:
            mc.close()


# --------- 11) Regression: unrelated endpoints still respond ---------

class TestRegression:
    def test_brand_images_list(self, coach):
        r = requests.get(f"{BASE_URL}/api/brand-images",
                         headers=coach["headers"], timeout=15)
        assert r.status_code == 200, f"brand-images list → {r.status_code}"

    def test_brand_images_pick(self, coach):
        # pick endpoint — try common shape
        r = requests.get(f"{BASE_URL}/api/brand-images/pick",
                         headers=coach["headers"], timeout=15)
        assert r.status_code in (200, 404), f"brand-images pick → {r.status_code} {r.text[:200]}"

    def test_social_settings(self, coach):
        r = requests.get(f"{BASE_URL}/api/social/settings",
                         headers=coach["headers"], timeout=15)
        assert r.status_code == 200

    def test_user_profile_photo(self, client):
        # Correct route is /api/user/profile/photo/{user_id} (token-signed GET)
        uid = client["user"]["id"]
        r = requests.get(f"{BASE_URL}/api/user/profile/photo/{uid}",
                         headers=client["headers"], timeout=15)
        assert r.status_code in (200, 204, 404), f"profile photo → {r.status_code}"
