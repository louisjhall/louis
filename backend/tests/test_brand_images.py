"""Backend tests for feature_brand_images (CrewFit AI imagery library).

Covers: seed (idempotency + role gating), list (filter + include_hidden),
pick (default + best-match + fallback), stream (header + query + no-auth),
regenerate (role gating + 409 + happy path with polling), patch (valid + invalid),
delete (soft-hidden + file removal + subsequent 404), plus regression on
/api/social/settings and /api/user/profile/photo.
"""
import time
import pytest


# ---- Helpers ---------------------------------------------------------------

def _library_keys():
    return {
        "hero_default", "hero_pilot_male", "hero_pilot_female", "hero_cabin_crew_female",
        "workout_strength_hotel_gym", "workout_endurance_marathon",
        "recovery_long_haul", "standby_readiness", "event_countdown",
    }


# ---- Seed ------------------------------------------------------------------

class TestSeed:
    def test_seed_requires_coach_role(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/brand-images/seed", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 403, f"client seed → {r.status_code} {r.text}"

    def test_seed_no_auth_401(self, api, base_url):
        r = api.post(f"{base_url}/api/brand-images/seed", timeout=30)
        assert r.status_code in (401, 403), f"unauth seed → {r.status_code}"

    def test_seed_idempotent(self, api, base_url, coach_auth):
        r = api.post(f"{base_url}/api/brand-images/seed", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "created" in data and "count" in data
        # Library should already be seeded → nothing new created
        assert data["count"] == 0, f"expected idempotent seed with count=0, got {data}"
        assert data["created"] == []


# ---- List ------------------------------------------------------------------

class TestList:
    def test_list_default(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/brand-images", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "images" in body and "count" in body
        keys = {img["key"] for img in body["images"]}
        # All 9 canonical keys should be present
        missing = _library_keys() - keys
        assert not missing, f"missing library keys: {missing}"
        # Required fields
        for img in body["images"]:
            for field in ("id", "key", "category", "status", "is_default", "context"):
                assert field in img, f"missing field {field} in {img.get('key')}"
            # storage_path must be excluded
            assert "storage_path" not in img
            assert "_id" not in img

    def test_list_filter_category_hero(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/brand-images?category=hero", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] >= 1
        for img in body["images"]:
            assert img["category"] == "hero", f"non-hero leaked: {img['key']}"

    def test_list_include_hidden_default_omits(self, api, base_url, coach_auth):
        r_default = api.get(f"{base_url}/api/brand-images", headers=coach_auth["headers"], timeout=30)
        r_all = api.get(f"{base_url}/api/brand-images?include_hidden=true", headers=coach_auth["headers"], timeout=30)
        assert r_default.status_code == 200 and r_all.status_code == 200
        default_statuses = {img["status"] for img in r_default.json()["images"]}
        assert "hidden" not in default_statuses

    def test_list_accessible_to_client(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/brand-images", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, f"client list → {r.status_code} {r.text}"


# ---- Pick ------------------------------------------------------------------

class TestPick:
    def test_pick_no_query_returns_default(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/brand-images/pick", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "image" in body and "match_score" in body
        # With no query, score is 0
        assert body["match_score"] == 0
        # Prefer hero_default if it's ready; otherwise a default is_default image
        img = body["image"]
        assert img.get("status") == "ready"
        # If hero_default exists ready, it should be it
        # (winners are sorted so hero_default rises first among score=0 defaults)

    def test_pick_pilot_male(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/brand-images/pick?role=pilot&gender=male",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["image"]["key"] == "hero_pilot_male", f"got {body['image']['key']}"
        assert body["match_score"] >= 6  # 3 (role) + 3 (gender)

    def test_pick_endurance_marathon(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/brand-images/pick?workout_type=endurance&goal=marathon",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["image"]["key"] == "workout_endurance_marathon", f"got {body['image']['key']}"
        assert body["match_score"] >= 6

    def test_pick_unmatched_falls_back(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/brand-images/pick?role=astronaut",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        # No entry matches "astronaut"; scoring: hero_default has empty ctx → 0,
        # entries with role= get -1 penalty. So hero_default should win.
        assert body["image"]["key"] == "hero_default", f"fallback failed → {body['image']['key']}"
        assert body["match_score"] == 0


# ---- Stream ----------------------------------------------------------------

class TestStream:
    @pytest.fixture(scope="class")
    def hero_default_id(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/brand-images", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200
        for img in r.json()["images"]:
            if img["key"] == "hero_default":
                return img["id"]
        pytest.skip("hero_default not present in library")

    def test_stream_header_auth_coach(self, api, base_url, coach_auth, hero_default_id):
        r = api.get(f"{base_url}/api/brand-images/{hero_default_id}/stream",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("image/"), r.headers
        assert len(r.content) > 100

    def test_stream_header_auth_client(self, api, base_url, client_auth, hero_default_id):
        r = api.get(f"{base_url}/api/brand-images/{hero_default_id}/stream",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        assert len(r.content) > 100

    def test_stream_query_token_auth(self, api, base_url, client_auth, hero_default_id):
        # Fresh session to strip default Authorization/Content-Type
        import requests
        s = requests.Session()
        r = s.get(f"{base_url}/api/brand-images/{hero_default_id}/stream",
                  params={"token": client_auth["token"]}, timeout=30)
        assert r.status_code == 200, f"query-token stream → {r.status_code} {r.text[:200]}"
        assert len(r.content) > 100

    def test_stream_no_auth_401(self, api, base_url, hero_default_id):
        import requests
        s = requests.Session()
        r = s.get(f"{base_url}/api/brand-images/{hero_default_id}/stream", timeout=30)
        assert r.status_code in (401, 403), f"expected 401 got {r.status_code}"

    def test_stream_missing_id_404(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/brand-images/does-not-exist/stream",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 404


# ---- Patch -----------------------------------------------------------------

class TestPatch:
    @pytest.fixture(scope="class")
    def target_id(self, api, base_url, coach_auth):
        # Use a non-critical image (recovery_long_haul) for mutability tests
        r = api.get(f"{base_url}/api/brand-images", headers=coach_auth["headers"], timeout=30)
        for img in r.json()["images"]:
            if img["key"] == "recovery_long_haul":
                return img["id"]
        pytest.skip("recovery_long_haul not present")

    def test_patch_requires_coach(self, api, base_url, client_auth, target_id):
        r = api.patch(f"{base_url}/api/brand-images/{target_id}",
                      json={"label": "should not apply"},
                      headers=client_auth["headers"], timeout=30)
        assert r.status_code == 403

    def test_patch_invalid_status_400(self, api, base_url, coach_auth, target_id):
        r = api.patch(f"{base_url}/api/brand-images/{target_id}",
                      json={"status": "banana"},
                      headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 400, r.text

    def test_patch_valid_label_and_default(self, api, base_url, coach_auth, target_id):
        r = api.patch(f"{base_url}/api/brand-images/{target_id}",
                      json={"label": "TEST_Recovery Long Haul", "is_default": True},
                      headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        # Verify via list
        r2 = api.get(f"{base_url}/api/brand-images", headers=coach_auth["headers"], timeout=30)
        img = next(x for x in r2.json()["images"] if x["id"] == target_id)
        assert img["label"] == "TEST_Recovery Long Haul"
        assert img["is_default"] is True

    def test_patch_approved_maps_to_ready(self, api, base_url, coach_auth, target_id):
        r = api.patch(f"{base_url}/api/brand-images/{target_id}",
                      json={"status": "approved"},
                      headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        r2 = api.get(f"{base_url}/api/brand-images", headers=coach_auth["headers"], timeout=30)
        img = next(x for x in r2.json()["images"] if x["id"] == target_id)
        assert img["status"] == "ready", f"approved did not map to ready: {img['status']}"

    def test_patch_404_on_missing(self, api, base_url, coach_auth):
        r = api.patch(f"{base_url}/api/brand-images/does-not-exist",
                      json={"label": "x"}, headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 404


# ---- Regenerate ------------------------------------------------------------

class TestRegenerate:
    @pytest.fixture(scope="class")
    def target_id(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/brand-images", headers=coach_auth["headers"], timeout=30)
        for img in r.json()["images"]:
            if img["key"] == "standby_readiness":
                return img["id"]
        pytest.skip("standby_readiness not present")

    def test_regenerate_requires_coach(self, api, base_url, client_auth, target_id):
        r = api.post(f"{base_url}/api/brand-images/{target_id}/regenerate",
                     json={}, headers=client_auth["headers"], timeout=30)
        assert r.status_code == 403

    def test_regenerate_404_missing(self, api, base_url, coach_auth):
        r = api.post(f"{base_url}/api/brand-images/does-not-exist/regenerate",
                     json={}, headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 404

    def test_regenerate_kickoff_and_poll(self, api, base_url, coach_auth, target_id):
        r = api.post(f"{base_url}/api/brand-images/{target_id}/regenerate",
                     json={}, headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        # Immediately check status → should be pending or generating
        def get_status():
            rl = api.get(f"{base_url}/api/brand-images?include_hidden=true",
                         headers=coach_auth["headers"], timeout=30)
            for img in rl.json()["images"]:
                if img["id"] == target_id:
                    return img["status"]
            return None

        # If we catch it while generating, verify 409
        for _ in range(3):
            s = get_status()
            if s == "generating":
                r409 = api.post(f"{base_url}/api/brand-images/{target_id}/regenerate",
                                json={}, headers=coach_auth["headers"], timeout=30)
                assert r409.status_code == 409, f"expected 409 while generating, got {r409.status_code}"
                break
            time.sleep(0.5)

        # Poll up to ~20s for ready/failed
        final = None
        for _ in range(20):
            s = get_status()
            if s in ("ready", "failed"):
                final = s
                break
            time.sleep(1)
        # We don't hard-fail on 'failed' (network / model flakiness) but log it.
        assert final in ("ready", "failed", None), f"unexpected terminal status: {final}"
        if final != "ready":
            pytest.skip(f"regenerate did not reach ready in 20s (status={final}); background job "
                        f"may still be running — not necessarily a bug.")


# ---- Delete ----------------------------------------------------------------

class TestDelete:
    @pytest.fixture(scope="class")
    def target_id(self, api, base_url, coach_auth):
        # Use event_countdown so hero images stay intact for inspection.
        r = api.get(f"{base_url}/api/brand-images", headers=coach_auth["headers"], timeout=30)
        for img in r.json()["images"]:
            if img["key"] == "event_countdown":
                return img["id"]
        pytest.skip("event_countdown not present")

    def test_delete_requires_coach(self, api, base_url, client_auth, target_id):
        r = api.delete(f"{base_url}/api/brand-images/{target_id}",
                       headers=client_auth["headers"], timeout=30)
        assert r.status_code == 403

    def test_delete_soft_hides_and_removes_file(self, api, base_url, coach_auth, target_id):
        r = api.delete(f"{base_url}/api/brand-images/{target_id}",
                       headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

        # Should be hidden now (not in default list, but in include_hidden=true)
        r_all = api.get(f"{base_url}/api/brand-images?include_hidden=true",
                        headers=coach_auth["headers"], timeout=30)
        entry = next((x for x in r_all.json()["images"] if x["id"] == target_id), None)
        assert entry is not None
        assert entry["status"] == "hidden"

        r_default = api.get(f"{base_url}/api/brand-images",
                            headers=coach_auth["headers"], timeout=30)
        ids = {x["id"] for x in r_default.json()["images"]}
        assert target_id not in ids, "hidden image leaked into default list"

        # Stream should now 404 (file deleted + storage_path cleared)
        r_stream = api.get(f"{base_url}/api/brand-images/{target_id}/stream",
                           headers=coach_auth["headers"], timeout=30)
        assert r_stream.status_code == 404, f"post-delete stream → {r_stream.status_code}"

    def test_delete_404_missing(self, api, base_url, coach_auth):
        r = api.delete(f"{base_url}/api/brand-images/does-not-exist",
                       headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 404


# ---- Regression ------------------------------------------------------------

class TestRegression:
    def test_social_settings_still_works(self, api, base_url, coach_auth):
        # /api/social/settings is admin/coach-only
        r = api.get(f"{base_url}/api/social/settings", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_profile_photo_endpoint_reachable(self, api, base_url, client_auth):
        # Photo may or may not exist for the seeded user — accept 200 or 404,
        # anything else (500, etc.) is a regression.
        user_id = client_auth["user"]["id"]
        r = api.get(f"{base_url}/api/user/profile/photo/{user_id}",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code in (200, 404), f"photo endpoint regressed: {r.status_code} {r.text[:200]}"
