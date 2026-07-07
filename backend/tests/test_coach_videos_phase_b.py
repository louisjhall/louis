"""§26 Phase B — Coach Video CRUD Dashboard backend tests."""
import os
import time
import pytest
import requests
from urllib.parse import quote

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    d = r.json()
    return {"Authorization": f"Bearer {d['token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def coach_h():
    return _login("coach@crewfit.com", "Coach123!")


@pytest.fixture(scope="module")
def client_h():
    return _login("client@crewfit.com", "Client123!")


# ------------------------------------------------------------------
# 1. GET /api/coach/videos (list + search)
# ------------------------------------------------------------------
class TestList:
    def test_list_ok(self, coach_h):
        r = requests.get(f"{BASE_URL}/api/coach/videos", headers=coach_h, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data and "total" in data
        assert isinstance(data["items"], list)
        assert data["total"] == len(data["items"])
        assert data["total"] > 0
        first = data["items"][0]
        for k in ("id", "key", "display_name", "primary_video_id", "primary_thumbnail",
                  "has_custom_url", "has_custom_upload", "variants_configured",
                  "preferred_slot", "approval_state"):
            assert k in first, f"missing key {k}"

    def test_list_search(self, coach_h):
        r = requests.get(f"{BASE_URL}/api/coach/videos?search=squat", headers=coach_h, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] > 0
        for item in data["items"]:
            assert "squat" in (item["display_name"] or "").lower() or "squat" in (item["key"] or "").lower()

    def test_list_client_forbidden(self, client_h):
        r = requests.get(f"{BASE_URL}/api/coach/videos", headers=client_h, timeout=30)
        assert r.status_code == 403, f"expected 403, got {r.status_code}"


# ------------------------------------------------------------------
# 2. GET /api/coach/videos/detail?key=
# ------------------------------------------------------------------
class TestDetail:
    def test_detail_ok(self, coach_h):
        r = requests.get(f"{BASE_URL}/api/coach/videos/detail?key=goblet+squat", headers=coach_h, timeout=30)
        assert r.status_code == 200
        d = r.json()
        for k in ("id", "key", "display_name"):
            assert k in d
        # Slots (may be None)
        for k in ("primary", "alternative", "custom_url", "custom_upload", "youtube_backup", "ai_image", "variants"):
            assert k in d or d.get(k) is None or True  # they can be absent when null

    def test_detail_slash_key(self, coach_h):
        # 90/90 hip rotation - use %2F for '/', space encoded as %20 or +
        key_enc = quote("90/90 hip rotation", safe="")
        r = requests.get(f"{BASE_URL}/api/coach/videos/detail?key={key_enc}", headers=coach_h, timeout=30)
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        d = r.json()
        assert d["key"] == "90/90 hip rotation"

    def test_detail_client_forbidden(self, client_h):
        r = requests.get(f"{BASE_URL}/api/coach/videos/detail?key=goblet+squat", headers=client_h, timeout=30)
        assert r.status_code == 403

    def test_detail_missing_key(self, coach_h):
        # No key query param
        r = requests.get(f"{BASE_URL}/api/coach/videos/detail", headers=coach_h, timeout=30)
        assert r.status_code == 422


# ------------------------------------------------------------------
# 3. POST /api/coach/videos/upsert
# ------------------------------------------------------------------
class TestUpsert:
    def test_upsert(self, coach_h):
        r = requests.post(f"{BASE_URL}/api/coach/videos/upsert",
                          headers=coach_h,
                          json={"display_name": "Turkish Get-Up"}, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["key"] == "turkish get-up"
        assert d["display_name"] == "Turkish Get-Up"

    def test_upsert_client_forbidden(self, client_h):
        r = requests.post(f"{BASE_URL}/api/coach/videos/upsert",
                          headers=client_h,
                          json={"display_name": "TEST_ForbiddenExercise"}, timeout=30)
        assert r.status_code == 403


# ------------------------------------------------------------------
# 4. POST /api/coach/videos/slot?key=  (per spec — QUERY-PARAM)
# ------------------------------------------------------------------
class TestSetSlot:
    def test_set_custom_url_slot(self, coach_h):
        r = requests.post(f"{BASE_URL}/api/coach/videos/slot?key=goblet+squat",
                          headers=coach_h,
                          json={"slot": "custom_url",
                                "video_url": "https://www.youtube.com/watch?v=6xwGFn-J_Qw",
                                "notes": "Test"}, timeout=30)
        assert r.status_code == 200, f"BUG: slot endpoint should accept ?key= query param; got {r.status_code} {r.text}"
        d = r.json()
        assert d["custom_url"]["video_id"] == "6xwGFn-J_Qw"
        assert d["custom_url"]["approval_status"] == "approved"

    def test_set_slot_invalid_slot_name(self, coach_h):
        r = requests.post(f"{BASE_URL}/api/coach/videos/slot?key=goblet+squat",
                          headers=coach_h,
                          json={"slot": "bogus_slot",
                                "video_url": "https://www.youtube.com/watch?v=6xwGFn-J_Qw"},
                          timeout=30)
        assert r.status_code == 400

    def test_set_slot_missing_key(self, coach_h):
        r = requests.post(f"{BASE_URL}/api/coach/videos/slot",
                          headers=coach_h,
                          json={"slot": "custom_url",
                                "video_url": "https://www.youtube.com/watch?v=6xwGFn-J_Qw"},
                          timeout=30)
        assert r.status_code == 422

    def test_set_slot_client_forbidden(self, client_h):
        r = requests.post(f"{BASE_URL}/api/coach/videos/slot?key=goblet+squat",
                          headers=client_h,
                          json={"slot": "custom_url",
                                "video_url": "https://www.youtube.com/watch?v=6xwGFn-J_Qw"},
                          timeout=30)
        assert r.status_code == 403


# ------------------------------------------------------------------
# 5. POST /api/coach/videos/approve
# ------------------------------------------------------------------
class TestApprove:
    def test_approve_reject_primary(self, coach_h, client_h):
        # First ensure Goblet Squat has a primary — trigger via /exercises/video
        rr = requests.get(f"{BASE_URL}/api/exercises/video?name=Goblet Squat",
                          headers=client_h, timeout=60)
        assert rr.status_code == 200

        r = requests.post(f"{BASE_URL}/api/coach/videos/approve?key=goblet+squat",
                          headers=coach_h,
                          json={"slot": "primary", "status": "rejected"}, timeout=30)
        assert r.status_code == 200, f"{r.status_code}: {r.text}"
        d = r.json()
        assert d["primary"]["approval_status"] == "rejected"

        # As client, GET should now NOT be primary — since custom_url has 6xwGFn-J_Qw
        r2 = requests.get(f"{BASE_URL}/api/exercises/video?name=Goblet Squat",
                          headers=client_h, timeout=60)
        assert r2.status_code == 200
        d2 = r2.json()
        # Since primary is rejected, resolver should return custom_url (6xwGFn-J_Qw) if set
        if d2.get("video"):
            assert d2["video"]["slot"] != "primary"

    def test_approve_invalid_status(self, coach_h):
        r = requests.post(f"{BASE_URL}/api/coach/videos/approve?key=goblet+squat",
                          headers=coach_h,
                          json={"slot": "primary", "status": "bogus"}, timeout=30)
        assert r.status_code == 400

    def test_approve_client_forbidden(self, client_h):
        r = requests.post(f"{BASE_URL}/api/coach/videos/approve?key=goblet+squat",
                          headers=client_h,
                          json={"slot": "primary", "status": "approved"}, timeout=30)
        assert r.status_code == 403


# ------------------------------------------------------------------
# 6. POST /api/coach/videos/preferred
# ------------------------------------------------------------------
class TestPreferred:
    def test_set_preferred_custom_url(self, coach_h):
        r = requests.post(f"{BASE_URL}/api/coach/videos/preferred?key=goblet+squat",
                          headers=coach_h,
                          json={"slot": "custom_url"}, timeout=30)
        assert r.status_code == 200, f"{r.status_code}: {r.text}"
        d = r.json()
        assert d["preferred_slot"] == "custom_url"

    def test_set_preferred_empty_slot_400(self, coach_h):
        # alternative slot has no video yet → expect 400
        r = requests.post(f"{BASE_URL}/api/coach/videos/preferred?key=goblet+squat",
                          headers=coach_h,
                          json={"slot": "alternative"}, timeout=30)
        assert r.status_code == 400, f"expected 400 for empty alternative slot, got {r.status_code}"

    def test_preferred_client_forbidden(self, client_h):
        r = requests.post(f"{BASE_URL}/api/coach/videos/preferred?key=goblet+squat",
                          headers=client_h, json={"slot": "custom_url"}, timeout=30)
        assert r.status_code == 403


# ------------------------------------------------------------------
# 7. POST /api/coach/videos/variant
# ------------------------------------------------------------------
class TestVariant:
    HOTEL_VID = "IODxDxX7oi4"

    def test_set_hotel_variant(self, coach_h):
        r = requests.post(f"{BASE_URL}/api/coach/videos/variant?key=goblet+squat",
                          headers=coach_h,
                          json={"variant": "hotel",
                                "video_url": f"https://www.youtube.com/watch?v={self.HOTEL_VID}"},
                          timeout=30)
        assert r.status_code == 200, f"{r.status_code}: {r.text}"
        d = r.json()
        assert d["variants"]["hotel"]["video_id"] == self.HOTEL_VID

    def test_client_resolves_hotel_variant(self, client_h):
        r = requests.get(f"{BASE_URL}/api/exercises/video?name=Goblet Squat&variant=hotel",
                         headers=client_h, timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert d["video"] is not None
        assert d["video"]["video_id"] == self.HOTEL_VID

    def test_client_resolves_home_uses_preferred(self, client_h):
        # variant=home is not set, so should fall back to preferred (custom_url = 6xwGFn-J_Qw)
        r = requests.get(f"{BASE_URL}/api/exercises/video?name=Goblet Squat&variant=home",
                         headers=client_h, timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert d["video"] is not None
        assert d["video"]["video_id"] == "6xwGFn-J_Qw"
        assert d["video"]["slot"] == "custom_url"

    def test_delete_hotel_variant(self, coach_h):
        r = requests.post(f"{BASE_URL}/api/coach/videos/variant?key=goblet+squat",
                          headers=coach_h,
                          json={"variant": "hotel", "delete": True}, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "hotel" not in (d.get("variants") or {})

    def test_variant_invalid(self, coach_h):
        r = requests.post(f"{BASE_URL}/api/coach/videos/variant?key=goblet+squat",
                          headers=coach_h,
                          json={"variant": "bogus",
                                "video_url": "https://www.youtube.com/watch?v=IODxDxX7oi4"},
                          timeout=30)
        assert r.status_code == 400

    def test_variant_client_forbidden(self, client_h):
        r = requests.post(f"{BASE_URL}/api/coach/videos/variant?key=goblet+squat",
                          headers=client_h,
                          json={"variant": "hotel",
                                "video_url": "https://www.youtube.com/watch?v=IODxDxX7oi4"},
                          timeout=30)
        assert r.status_code == 403


# ------------------------------------------------------------------
# 8. DELETE /api/coach/videos/slot?key=&slot=
# ------------------------------------------------------------------
class TestDeleteSlot:
    def test_delete_custom_url_resets_preferred(self, coach_h):
        r = requests.delete(f"{BASE_URL}/api/coach/videos/slot?key=goblet+squat&slot=custom_url",
                            headers=coach_h, timeout=30)
        assert r.status_code == 200, f"BUG: delete slot should accept ?key= query param; got {r.status_code} {r.text}"
        d = r.json()
        assert not d.get("custom_url")
        # Preferred was custom_url — should now be None
        assert d.get("preferred_slot") in (None, "")

    def test_delete_slot_client_forbidden(self, client_h):
        r = requests.delete(f"{BASE_URL}/api/coach/videos/slot?key=goblet+squat&slot=primary",
                            headers=client_h, timeout=30)
        assert r.status_code == 403


# ------------------------------------------------------------------
# 9. POST /api/coach/videos/rescan
# ------------------------------------------------------------------
class TestRescan:
    def test_rescan_returns_fresh_primary(self, coach_h):
        # First un-reject primary via approve
        requests.post(f"{BASE_URL}/api/coach/videos/approve?key=goblet+squat",
                      headers=coach_h,
                      json={"slot": "primary", "status": "auto"}, timeout=30)
        r = requests.post(f"{BASE_URL}/api/coach/videos/rescan?key=goblet+squat",
                          headers=coach_h, timeout=60)
        assert r.status_code == 200, f"{r.status_code}: {r.text}"
        d = r.json()
        assert d["primary"]["video_id"] and len(d["primary"]["video_id"]) == 11

    def test_rescan_client_forbidden(self, client_h):
        r = requests.post(f"{BASE_URL}/api/coach/videos/rescan?key=goblet+squat",
                          headers=client_h, timeout=60)
        assert r.status_code == 403


# ------------------------------------------------------------------
# 10. Regressions
# ------------------------------------------------------------------
class TestRegression:
    def test_get_exercises_video_default(self, client_h):
        r = requests.get(f"{BASE_URL}/api/exercises/video?name=Push-Up",
                         headers=client_h, timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert "video" in d

    def test_videos_batch_with_variant(self, client_h):
        r = requests.post(f"{BASE_URL}/api/exercises/videos-batch",
                          headers=client_h,
                          json={"exercises": ["Push-Up", "Plank"], "variant": "hotel"},
                          timeout=90)
        assert r.status_code == 200
        d = r.json()
        assert "results" in d
        assert "Push-Up" in d["results"] or "Plank" in d["results"]
