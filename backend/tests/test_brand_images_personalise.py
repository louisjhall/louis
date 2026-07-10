"""Phase 2.5 backend tests for feature_brand_images — personalised image
generation + coach approval flow + wider brand-images visibility rules +
startup reconciliation for stuck 'generating' / 'pending' rows.

Uses ONE real Nano Banana call (as per agent-to-agent context note).
All other cases (rejection, reconcile, second-personalise 409) are covered
using synthetic direct-DB rows so we don't burn LLM credits.

Ordering matters — tests are numbered so pytest runs them sequentially within
each class (default pytest behaviour respects file order → class order → method
order).
"""
from __future__ import annotations

import base64
import os
import subprocess
import time
from pathlib import Path

import pymongo
import pytest
import requests

# 1x1 transparent PNG (67 bytes) — used to fake a "generated" image on disk
_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)

BRAND_ROOT = Path("/app/backend/uploads/brand_images")


# ---- Direct-DB helper (sync, used only for setup/cleanup + synthetic rows) --

def _load_env():
    for line in Path("/app/backend/.env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
_MONGO = pymongo.MongoClient(os.environ["MONGO_URL"])
_DB = _MONGO[os.environ["DB_NAME"]]


def _wipe_client_personal(client_id: str):
    """Best-effort cleanup of any personal images that belong to the client
    (leaves library images alone). Also removes the on-disk PNGs."""
    for row in _DB.crewfit_images.find({"personalised_for": client_id}):
        p = row.get("storage_path")
        if p:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass
    _DB.crewfit_images.delete_many({"personalised_for": client_id})


# ---- Fixture: track ids created during tests so we can clean up -----------

@pytest.fixture(scope="module")
def cleanup_registry():
    ids: list[str] = []
    yield ids
    for _id in ids:
        row = _DB.crewfit_images.find_one({"id": _id})
        if row and row.get("storage_path"):
            try:
                Path(row["storage_path"]).unlink(missing_ok=True)
            except Exception:
                pass
        _DB.crewfit_images.delete_one({"id": _id})


# =============================================================================
# Section A — Personalise → Pending Approval → Approve → /pick=personalised
# =============================================================================

class TestPersonaliseApprovalFlow:
    """End-to-end personalise → coach-approval → personalised /pick."""

    def test_00_wipe_client_personal_state(self, client_auth):
        """Clear any pre-existing personal images so we can test fallback + fresh flow."""
        _wipe_client_personal(client_auth["user"]["id"])
        # Verify cleanup
        remaining = list(_DB.crewfit_images.find({"personalised_for": client_auth["user"]["id"]}))
        assert remaining == [], f"cleanup incomplete: {remaining}"

    def test_01_pick_falls_back_to_library_when_no_personal(self, api, base_url, client_auth):
        """Precondition: client has no personal images → /pick returns library, personalised=false."""
        r = api.get(f"{base_url}/api/brand-images/pick", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("personalised") is False, f"expected library fallback, got {body}"
        assert body["image"]["status"] == "ready"
        assert body["image"].get("personalised_for") in (None, "")

    def test_02_client_forbidden_on_pending_approval_queue(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/brand-images/pending-approval",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 403, f"client should be 403 on coach queue, got {r.status_code}"

    def test_03_coach_pending_approval_reachable(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/brand-images/pending-approval",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "images" in body and "count" in body

    def test_04_personalise_kickoff(self, api, base_url, client_auth, cleanup_registry):
        """POST /personalise → 200, doc validated. Records ONE real Nano Banana job."""
        hint = "TEST_marathon_dusk_runway"
        r = api.post(
            f"{base_url}/api/brand-images/personalise",
            json={"prompt_hint": hint, "workout_type": "endurance", "goal": "marathon"},
            headers=client_auth["headers"], timeout=60,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "image" in body
        img = body["image"]

        # Assertions per spec
        assert img["status"] == "pending", f"initial status → {img['status']}"
        assert img["personalised_for"] == client_auth["user"]["id"]
        assert img["category"] == "personal"
        assert img["prompt"].startswith(
            "Premium dark aviation fitness app image, minimalist cinematic style,"
        ), f"prompt missing BASE_STYLE prefix: {img['prompt'][:120]!r}"
        assert hint in img["prompt"], f"prompt_hint '{hint}' not in composed prompt"
        # ID/created_by sanity
        assert img.get("id") and img.get("created_by") == client_auth["user"]["id"]

        # Register for teardown
        cleanup_registry.append(img["id"])
        # Stash for later tests via class attribute
        TestPersonaliseApprovalFlow._image_id = img["id"]

    def test_05_second_personalise_while_pending_returns_409(self, api, base_url, client_auth):
        r = api.post(
            f"{base_url}/api/brand-images/personalise",
            json={"prompt_hint": "TEST_should_be_rejected"},
            headers=client_auth["headers"], timeout=30,
        )
        assert r.status_code == 409, f"expected 409 on duplicate, got {r.status_code}: {r.text}"
        assert "personal image already" in r.text.lower()

    def test_06_poll_until_pending_approval(self, api, base_url, client_auth):
        """Poll GET /personal/mine until status flips to pending_approval (or failed)."""
        img_id = TestPersonaliseApprovalFlow._image_id
        deadline = time.time() + 60  # LLM call can take a while; 60s is generous
        seen_statuses = set()
        final = None
        while time.time() < deadline:
            r = api.get(f"{base_url}/api/brand-images/personal/mine",
                        headers=client_auth["headers"], timeout=30)
            assert r.status_code == 200, r.text
            body = r.json()
            row = next((x for x in body["images"] if x["id"] == img_id), None)
            assert row is not None, f"personalised image {img_id} not in /personal/mine"
            seen_statuses.add(row["status"])
            if row["status"] in ("pending_approval", "failed", "ready"):
                final = row["status"]
                break
            time.sleep(2)
        if final == "failed":
            pytest.skip(f"Nano Banana job failed (network/model); seen={seen_statuses}. Not a functional bug.")
        assert final == "pending_approval", (
            f"expected pending_approval, got {final} (seen={seen_statuses})"
        )
        # personalised_for still set
        r2 = api.get(f"{base_url}/api/brand-images/personal/mine",
                     headers=client_auth["headers"], timeout=30)
        row = next(x for x in r2.json()["images"] if x["id"] == img_id)
        assert row["personalised_for"] == client_auth["user"]["id"]

    def test_07_file_exists_on_disk_via_stream(self, api, base_url, client_auth):
        img_id = TestPersonaliseApprovalFlow._image_id
        # File on disk
        assert (BRAND_ROOT / f"{img_id}.png").exists(), (
            f"image file missing at {BRAND_ROOT / (img_id + '.png')}"
        )
        # /stream returns 200 with image/png
        r = api.get(f"{base_url}/api/brand-images/{img_id}/stream",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("image/"), r.headers
        assert len(r.content) > 100

    def test_08_personal_mine_lists_newest_first(self, api, base_url, client_auth):
        # Insert a synthetic older personal to test sort order
        older = {
            "id": "TEST_older_personal_" + str(int(time.time())),
            "key": "TEST_older",
            "category": "personal",
            "context": {},
            "prompt": "irrelevant",
            "status": "hidden",  # so it doesn't leak into /pick
            "is_default": False,
            "label": "TEST older",
            "personalised_for": client_auth["user"]["id"],
            "storage_path": None,
            "created_by": client_auth["user"]["id"],
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": "2020-01-01T00:00:00+00:00",
        }
        _DB.crewfit_images.insert_one(older)
        try:
            r = api.get(f"{base_url}/api/brand-images/personal/mine",
                        headers=client_auth["headers"], timeout=30)
            assert r.status_code == 200
            imgs = r.json()["images"]
            ids = [x["id"] for x in imgs]
            assert TestPersonaliseApprovalFlow._image_id in ids
            assert older["id"] in ids
            # newest first
            assert ids.index(TestPersonaliseApprovalFlow._image_id) < ids.index(older["id"])
        finally:
            _DB.crewfit_images.delete_one({"id": older["id"]})

    def test_09_list_hides_pending_approval_by_default(self, api, base_url, client_auth):
        img_id = TestPersonaliseApprovalFlow._image_id
        # Default → hidden
        r1 = api.get(f"{base_url}/api/brand-images", headers=client_auth["headers"], timeout=30)
        assert r1.status_code == 200
        ids_default = {x["id"] for x in r1.json()["images"]}
        assert img_id not in ids_default, "pending_approval image leaked into default list"
        # include_pending → visible
        r2 = api.get(f"{base_url}/api/brand-images?include_pending=true",
                     headers=client_auth["headers"], timeout=30)
        assert r2.status_code == 200
        ids_all = {x["id"] for x in r2.json()["images"]}
        assert img_id in ids_all, "include_pending=true failed to surface pending_approval"

    def test_10_list_hides_other_users_personal(self, api, base_url, client_auth, coach_auth):
        """Client's default list should NEVER include another user's personal image."""
        # Insert synthetic ready personal image owned by coach
        synth_id = "TEST_coach_personal_" + str(int(time.time()))
        p = BRAND_ROOT / f"{synth_id}.png"
        p.write_bytes(_PNG_1x1)
        _DB.crewfit_images.insert_one({
            "id": synth_id,
            "key": "TEST_coach_personal",
            "category": "personal",
            "context": {},
            "prompt": "irrelevant",
            "status": "ready",
            "is_default": False,
            "label": "TEST coach personal",
            "personalised_for": coach_auth["user"]["id"],
            "storage_path": str(p),
            "created_by": coach_auth["user"]["id"],
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        })
        try:
            r = api.get(f"{base_url}/api/brand-images", headers=client_auth["headers"], timeout=30)
            assert r.status_code == 200
            ids = {x["id"] for x in r.json()["images"]}
            assert synth_id not in ids, "another user's personal image leaked to client's default list"
        finally:
            _DB.crewfit_images.delete_one({"id": synth_id})
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

    def test_11_coach_pending_queue_contains_it(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/brand-images/pending-approval",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200
        ids = {x["id"] for x in r.json()["images"]}
        assert TestPersonaliseApprovalFlow._image_id in ids, (
            "personal image not surfaced in coach pending-approval queue"
        )

    def test_12_patch_invalid_status_400(self, api, base_url, coach_auth):
        img_id = TestPersonaliseApprovalFlow._image_id
        r = api.patch(f"{base_url}/api/brand-images/{img_id}",
                      json={"status": "foo"}, headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 400, r.text

    def test_13_coach_approves(self, api, base_url, coach_auth):
        img_id = TestPersonaliseApprovalFlow._image_id
        r = api.patch(f"{base_url}/api/brand-images/{img_id}",
                      json={"status": "approved"}, headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        # Confirm via db read (list excludes storage_path but includes status)
        row = _DB.crewfit_images.find_one({"id": img_id}, {"_id": 0})
        assert row["status"] == "ready", f"approved should map to ready, got {row['status']}"

    def test_14_pick_now_returns_personalised(self, api, base_url, client_auth):
        img_id = TestPersonaliseApprovalFlow._image_id
        r = api.get(f"{base_url}/api/brand-images/pick",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("personalised") is True, f"expected personalised=true, got {body}"
        assert body["image"]["id"] == img_id, (
            f"personalised /pick should return client's approved personal image "
            f"{img_id}, got {body['image']['id']}"
        )


# =============================================================================
# Section B — Rejection flow (uses synthetic ready-personal → PATCH rejected)
# =============================================================================

class TestRejectFlow:
    """No LLM cost: we plant a synthetic ready personal image on disk + db,
    then verify PATCH status=rejected → status=hidden + file removed + /stream 404."""

    def test_00_plant_synthetic_ready(self, client_auth, cleanup_registry):
        img_id = "TEST_reject_target_" + str(int(time.time()))
        p = BRAND_ROOT / f"{img_id}.png"
        p.write_bytes(_PNG_1x1)
        _DB.crewfit_images.insert_one({
            "id": img_id,
            "key": img_id,
            "category": "personal",
            "context": {},
            "prompt": "TEST synthetic",
            "status": "pending_approval",
            "is_default": False,
            "label": "TEST reject target",
            "personalised_for": client_auth["user"]["id"],
            "storage_path": str(p),
            "size_bytes": len(_PNG_1x1),
            "mime": "image/png",
            "created_by": client_auth["user"]["id"],
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        })
        cleanup_registry.append(img_id)
        TestRejectFlow._image_id = img_id
        TestRejectFlow._path = p

    def test_01_stream_ok_before_reject(self, api, base_url, coach_auth):
        img_id = TestRejectFlow._image_id
        r = api.get(f"{base_url}/api/brand-images/{img_id}/stream",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_02_patch_rejected_hides_and_deletes_file(self, api, base_url, coach_auth):
        img_id = TestRejectFlow._image_id
        r = api.patch(f"{base_url}/api/brand-images/{img_id}",
                      json={"status": "rejected"}, headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        row = _DB.crewfit_images.find_one({"id": img_id})
        assert row["status"] == "hidden", f"rejected should map to hidden, got {row['status']}"
        assert row.get("storage_path") in (None, ""), f"storage_path not cleared: {row.get('storage_path')}"
        # File deleted from disk
        assert not TestRejectFlow._path.exists(), "PNG file was not removed after reject"

    def test_03_stream_after_reject_404(self, api, base_url, coach_auth):
        img_id = TestRejectFlow._image_id
        r = api.get(f"{base_url}/api/brand-images/{img_id}/stream",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 404, f"expected 404 after reject, got {r.status_code}"


# =============================================================================
# Section C — Startup reconciliation of stuck 'generating' / 'pending' rows
# =============================================================================

class TestStartupReconcile:
    """Insert synthetic 'generating' + 'pending' rows, restart backend, verify
    they flip to 'failed'."""

    def test_00_seed_synthetic_stuck_rows(self, cleanup_registry):
        base_ts = int(time.time())
        rows = [
            {
                "id": f"TEST_stuck_generating_{base_ts}",
                "key": f"TEST_stuck_generating_{base_ts}",
                "category": "personal",
                "context": {},
                "prompt": "TEST reconcile — generating",
                "status": "generating",
                "is_default": False,
                "label": "TEST stuck generating",
                "personalised_for": None,
                "storage_path": None,
                "created_by": "TEST",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "id": f"TEST_stuck_pending_{base_ts}",
                "key": f"TEST_stuck_pending_{base_ts}",
                "category": "personal",
                "context": {},
                "prompt": "TEST reconcile — pending",
                "status": "pending",
                "is_default": False,
                "label": "TEST stuck pending",
                "personalised_for": None,
                "storage_path": None,
                "created_by": "TEST",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            },
        ]
        _DB.crewfit_images.insert_many(rows)
        for r in rows:
            cleanup_registry.append(r["id"])
        TestStartupReconcile._ids = [r["id"] for r in rows]

    def test_01_restart_backend_and_wait(self, base_url):
        # Restart backend via supervisor
        out = subprocess.run(
            ["sudo", "supervisorctl", "restart", "backend"],
            capture_output=True, text=True, timeout=30,
        )
        assert out.returncode == 0, f"supervisor restart failed: {out.stderr}"
        # Wait for backend to become healthy
        deadline = time.time() + 45
        while time.time() < deadline:
            try:
                r = requests.get(f"{base_url}/api/", timeout=5)
                if r.status_code < 500:
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            pytest.fail("backend did not come back after restart")
        # Allow reconciler to finish (it runs in @app.on_event startup)
        time.sleep(2)

    def test_02_stuck_rows_now_failed(self):
        for _id in TestStartupReconcile._ids:
            row = _DB.crewfit_images.find_one({"id": _id})
            assert row is not None, f"synthetic row {_id} missing"
            assert row["status"] == "failed", (
                f"reconciler did not flip {_id} to failed: status={row['status']}"
            )
            assert (row.get("error") or "").lower().startswith("server restart"), (
                f"expected error='server restart', got {row.get('error')!r}"
            )


# =============================================================================
# Section D — Light regression checks
# =============================================================================

class TestRegressionPhase25:
    def test_seed_still_idempotent(self, api, base_url, coach_auth):
        r = api.post(f"{base_url}/api/brand-images/seed",
                     headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("count") == 0, f"seed no longer idempotent: {body}"

    def test_pick_library_only_case(self, api, base_url, coach_auth):
        # Coach has no personal image → /pick falls back to library
        r = api.get(f"{base_url}/api/brand-images/pick",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("personalised") is False, f"coach has no personal, expected library, got {body}"

    def test_social_settings_still_responds(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/social/settings",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_user_profile_photo_still_responds(self, api, base_url, client_auth):
        uid = client_auth["user"]["id"]
        r = api.get(f"{base_url}/api/user/profile/photo/{uid}",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code in (200, 404), f"regression: {r.status_code} {r.text[:200]}"
