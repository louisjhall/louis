"""Backend tests for On Demand content library (Stage 1).

Covers categories, tags, items (workout/video/audio) CRUD, publish toggle,
visibility rules, and presigned media/thumbnail URL endpoints.

All test-created rows are prefixed with "TEST_" and cleaned up at teardown.
"""
from __future__ import annotations

import base64
import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

COACH_EMAIL = "louis@crewfit.net"
COACH_PASSWORD = "Louis123!"
CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PASSWORD = "Client123!"


# ----- Helpers -----------------------------------------------------------------

def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return r.json()["token"]


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _tiny_b64(nbytes: int = 512, header: bytes = b"\x00") -> str:
    # A few hundred bytes so the R2 upload actually completes.
    payload = header + os.urandom(nbytes)
    return base64.b64encode(payload).decode("ascii")


# ----- Fixtures ----------------------------------------------------------------

@pytest.fixture(scope="module")
def coach_token() -> str:
    return _login(COACH_EMAIL, COACH_PASSWORD)


@pytest.fixture(scope="module")
def client_token() -> str:
    return _login(CLIENT_EMAIL, CLIENT_PASSWORD)


@pytest.fixture(scope="module")
def created_ids():
    """Tracker for cleanup: {"categories": [...], "tags": [...], "items": [...]}"""
    tracker = {"categories": [], "tags": [], "items": []}
    yield tracker
    # Teardown — best-effort cleanup with coach token
    try:
        tok = _login(COACH_EMAIL, COACH_PASSWORD)
        for iid in tracker["items"]:
            requests.delete(f"{API}/on-demand/coach/items/{iid}", headers=_hdr(tok), timeout=30)
        for cid in tracker["categories"]:
            requests.delete(f"{API}/on-demand/coach/categories/{cid}", headers=_hdr(tok), timeout=30)
        for tid in tracker["tags"]:
            requests.delete(f"{API}/on-demand/coach/tags/{tid}", headers=_hdr(tok), timeout=30)
    except Exception as e:  # noqa: BLE001
        print(f"cleanup failed: {e}")


# ----- Auth / role tests -------------------------------------------------------

class TestAuthAndRoles:
    def test_login_coach(self, coach_token):
        assert coach_token

    def test_login_client(self, client_token):
        assert client_token

    def test_client_forbidden_from_coach_endpoints(self, client_token):
        r = requests.post(
            f"{API}/on-demand/coach/categories",
            headers=_hdr(client_token),
            json={"name": "TEST_should_fail"},
            timeout=30,
        )
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}: {r.text}"


# ----- Categories --------------------------------------------------------------

class TestCategories:
    def test_list_categories_public(self, coach_token):
        r = requests.get(f"{API}/on-demand/categories", headers=_hdr(coach_token), timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "categories" in data and isinstance(data["categories"], list)

    def test_create_category(self, coach_token, created_ids):
        name = f"TEST_Cat_{uuid.uuid4().hex[:8]}"
        r = requests.post(
            f"{API}/on-demand/coach/categories",
            headers=_hdr(coach_token),
            json={"name": name},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["already_exists"] is False
        cat = data["category"]
        assert cat["name"] == name.strip()
        assert cat["slug"]
        assert cat["id"]
        created_ids["categories"].append(cat["id"])
        pytest.cat_id = cat["id"]
        pytest.cat_slug = cat["slug"]

    def test_create_category_duplicate_variant_is_idempotent(self, coach_token, created_ids):
        # Send whitespace + case variant of the same base name — same slug -> already_exists
        base = f"TEST_Dup_{uuid.uuid4().hex[:6]}"
        r1 = requests.post(
            f"{API}/on-demand/coach/categories",
            headers=_hdr(coach_token),
            json={"name": base},
            timeout=30,
        )
        assert r1.status_code == 200
        cid = r1.json()["category"]["id"]
        created_ids["categories"].append(cid)

        # Variant: uppercase + trailing whitespace + extra separators
        variant = f"  {base.upper()}  "
        r2 = requests.post(
            f"{API}/on-demand/coach/categories",
            headers=_hdr(coach_token),
            json={"name": variant},
            timeout=30,
        )
        assert r2.status_code == 200, r2.text
        data = r2.json()
        assert data["already_exists"] is True, f"expected already_exists=True, got {data}"
        assert data["category"]["id"] == cid

    def test_rename_category(self, coach_token):
        cat_id = getattr(pytest, "cat_id", None)
        assert cat_id, "prerequisite test_create_category did not run"
        new_name = f"TEST_Renamed_{uuid.uuid4().hex[:6]}"
        r = requests.patch(
            f"{API}/on-demand/coach/categories/{cat_id}",
            headers=_hdr(coach_token),
            json={"name": new_name},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json()["category"]["name"] == new_name.strip()

    def test_rename_missing_category_404(self, coach_token):
        r = requests.patch(
            f"{API}/on-demand/coach/categories/nonexistent-id-xyz",
            headers=_hdr(coach_token),
            json={"name": "TEST_none"},
            timeout=30,
        )
        assert r.status_code == 404


# ----- Tags --------------------------------------------------------------------

class TestTags:
    def test_create_tag_and_idempotent(self, coach_token, created_ids):
        name = f"TEST_Tag_{uuid.uuid4().hex[:8]}"
        r = requests.post(
            f"{API}/on-demand/coach/tags",
            headers=_hdr(coach_token),
            json={"name": name},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json()["already_exists"] is False
        tid = r.json()["tag"]["id"]
        created_ids["tags"].append(tid)
        pytest.tag_id = tid

        # Idempotent
        r2 = requests.post(
            f"{API}/on-demand/coach/tags",
            headers=_hdr(coach_token),
            json={"name": f"  {name.upper()}  "},
            timeout=30,
        )
        assert r2.status_code == 200
        assert r2.json()["already_exists"] is True
        assert r2.json()["tag"]["id"] == tid

    def test_list_tags(self, coach_token):
        r = requests.get(f"{API}/on-demand/tags", headers=_hdr(coach_token), timeout=30)
        assert r.status_code == 200
        assert "tags" in r.json()

    def test_rename_tag(self, coach_token):
        tid = getattr(pytest, "tag_id", None)
        assert tid
        r = requests.patch(
            f"{API}/on-demand/coach/tags/{tid}",
            headers=_hdr(coach_token),
            json={"name": f"TEST_TagRen_{uuid.uuid4().hex[:6]}"},
            timeout=30,
        )
        assert r.status_code == 200


# ----- Items — validation ------------------------------------------------------

class TestItemValidation:
    def test_workout_requires_workout_json(self, coach_token):
        r = requests.post(
            f"{API}/on-demand/coach/items",
            headers=_hdr(coach_token),
            json={"title": "TEST_bad_workout", "content_type": "workout"},
            timeout=30,
        )
        assert r.status_code == 400, r.text
        assert "workout_json" in r.text

    def test_video_requires_media(self, coach_token):
        r = requests.post(
            f"{API}/on-demand/coach/items",
            headers=_hdr(coach_token),
            json={"title": "TEST_bad_video", "content_type": "video"},
            timeout=30,
        )
        assert r.status_code == 400, r.text
        assert "media.file_b64" in r.text or "requires media" in r.text

    def test_audio_requires_media(self, coach_token):
        r = requests.post(
            f"{API}/on-demand/coach/items",
            headers=_hdr(coach_token),
            json={"title": "TEST_bad_audio", "content_type": "audio"},
            timeout=30,
        )
        assert r.status_code == 400

    def test_invalid_content_type(self, coach_token):
        r = requests.post(
            f"{API}/on-demand/coach/items",
            headers=_hdr(coach_token),
            json={"title": "TEST_bad_ct", "content_type": "podcast", "workout_json": {"a": 1}},
            timeout=30,
        )
        assert r.status_code == 400
        assert "content_type" in r.text.lower()

    def test_bad_category_id_returns_400(self, coach_token):
        r = requests.post(
            f"{API}/on-demand/coach/items",
            headers=_hdr(coach_token),
            json={
                "title": "TEST_bad_cat",
                "content_type": "workout",
                "workout_json": {"title": "x", "blocks": []},
                "category_id": "not-a-real-cat-id",
            },
            timeout=30,
        )
        assert r.status_code == 400
        assert "category_not_found" in r.text

    def test_bad_tag_ids_returns_400(self, coach_token):
        r = requests.post(
            f"{API}/on-demand/coach/items",
            headers=_hdr(coach_token),
            json={
                "title": "TEST_bad_tag",
                "content_type": "workout",
                "workout_json": {"title": "x", "blocks": []},
                "tag_ids": ["totally-bogus-tag-id"],
            },
            timeout=30,
        )
        assert r.status_code == 400
        assert "tag_ids_not_found" in r.text or "tag" in r.text.lower()


# ----- Items — happy paths -----------------------------------------------------

class TestItemsHappyPath:
    def test_create_workout_item(self, coach_token, created_ids):
        cat_id = getattr(pytest, "cat_id", None)
        tag_id = getattr(pytest, "tag_id", None)
        assert cat_id and tag_id, "need category+tag from prior tests"
        payload = {
            "title": "TEST_Workout_Item",
            "description": "test workout description",
            "content_type": "workout",
            "category_id": cat_id,
            "tag_ids": [tag_id],
            "duration_seconds": 900,
            "workout_json": {"title": "TEST", "blocks": []},
            "published": False,
        }
        r = requests.post(f"{API}/on-demand/coach/items", headers=_hdr(coach_token), json=payload, timeout=60)
        assert r.status_code == 200, r.text
        item = r.json()["item"]
        for f in ("id", "title", "description", "content_type", "category_id", "tag_ids",
                  "duration_seconds", "thumbnail_storage_key", "thumbnail_mime", "thumbnail_ext",
                  "media_storage_key", "media_mime", "media_ext", "workout_json",
                  "published", "created_at", "updated_at"):
            assert f in item, f"missing field {f} in response"
        assert item["content_type"] == "workout"
        assert item["workout_json"] == {"title": "TEST", "blocks": []}
        assert item["media_storage_key"] is None
        assert item["published"] is False
        created_ids["items"].append(item["id"])
        pytest.workout_item_id = item["id"]

    def test_create_video_item(self, coach_token, created_ids):
        payload = {
            "title": "TEST_Video_Item",
            "description": "test video",
            "content_type": "video",
            "duration_seconds": 30,
            "media": {"file_b64": _tiny_b64(1024), "file_mime": "video/mp4", "file_name": "clip.mp4"},
            "thumbnail": {"file_b64": _tiny_b64(256), "file_mime": "image/jpeg", "file_name": "thumb.jpg"},
            "published": True,
        }
        r = requests.post(f"{API}/on-demand/coach/items", headers=_hdr(coach_token), json=payload, timeout=90)
        assert r.status_code == 200, r.text
        item = r.json()["item"]
        assert item["content_type"] == "video"
        assert item["media_storage_key"], "media_storage_key should be set"
        assert item["media_mime"] == "video/mp4"
        assert item["media_ext"] == "mp4"
        assert item["thumbnail_storage_key"]
        assert item["published"] is True
        # workout_json is null for non-workout content
        assert item.get("workout_json") is None
        created_ids["items"].append(item["id"])
        pytest.video_item_id = item["id"]

    def test_create_audio_item(self, coach_token, created_ids):
        payload = {
            "title": "TEST_Audio_Item",
            "content_type": "audio",
            "duration_seconds": 60,
            "media": {"file_b64": _tiny_b64(1024), "file_mime": "audio/mpeg", "file_name": "clip.mp3"},
            "published": False,
        }
        r = requests.post(f"{API}/on-demand/coach/items", headers=_hdr(coach_token), json=payload, timeout=60)
        assert r.status_code == 200, r.text
        item = r.json()["item"]
        assert item["content_type"] == "audio"
        assert item["media_ext"] == "mp3"
        assert item["published"] is False
        created_ids["items"].append(item["id"])
        pytest.audio_item_id = item["id"]

    def test_coach_list_strips_workout_json(self, coach_token):
        r = requests.get(f"{API}/on-demand/coach/items", headers=_hdr(coach_token), timeout=30)
        assert r.status_code == 200
        rows = r.json()["items"]
        assert isinstance(rows, list)
        for row in rows:
            assert "workout_json" not in row, "list rows must not include workout_json blob"

    def test_coach_list_filters(self, coach_token):
        r = requests.get(
            f"{API}/on-demand/coach/items",
            headers=_hdr(coach_token),
            params={"content_type": "video", "search": "TEST_Video"},
            timeout=30,
        )
        assert r.status_code == 200
        rows = r.json()["items"]
        for row in rows:
            assert row["content_type"] == "video"
            assert "TEST_Video" in row["title"]

    def test_coach_get_item_detail_includes_workout_json(self, coach_token):
        wid = pytest.workout_item_id
        r = requests.get(f"{API}/on-demand/coach/items/{wid}", headers=_hdr(coach_token), timeout=30)
        assert r.status_code == 200
        assert r.json()["item"]["workout_json"] == {"title": "TEST", "blocks": []}


# ----- Items — PATCH -----------------------------------------------------------

class TestItemPatch:
    def test_partial_update_title(self, coach_token):
        vid = pytest.video_item_id
        r = requests.patch(
            f"{API}/on-demand/coach/items/{vid}",
            headers=_hdr(coach_token),
            json={"title": "TEST_Video_Item_Renamed"},
            timeout=30,
        )
        assert r.status_code == 200
        assert r.json()["item"]["title"] == "TEST_Video_Item_Renamed"

    def test_content_type_immutable(self, coach_token):
        """PATCH body has no content_type field on the Pydantic model → server ignores it."""
        vid = pytest.video_item_id
        # Attempt to send content_type in raw body — ItemPatchBody ignores it.
        r = requests.patch(
            f"{API}/on-demand/coach/items/{vid}",
            headers=_hdr(coach_token),
            json={"content_type": "audio", "description": "still video"},
            timeout=30,
        )
        assert r.status_code == 200
        assert r.json()["item"]["content_type"] == "video", "content_type must be immutable"

    def test_workout_json_ignored_on_non_workout(self, coach_token):
        vid = pytest.video_item_id
        r = requests.patch(
            f"{API}/on-demand/coach/items/{vid}",
            headers=_hdr(coach_token),
            json={"workout_json": {"blocks": ["should_be_ignored"]}},
            timeout=30,
        )
        assert r.status_code == 200
        item = r.json()["item"]
        assert item.get("workout_json") is None, "workout_json only writable for workout content"

    def test_workout_json_editable_on_workout(self, coach_token):
        wid = pytest.workout_item_id
        new_json = {"title": "TEST_updated", "blocks": [{"kind": "warmup"}]}
        r = requests.patch(
            f"{API}/on-demand/coach/items/{wid}",
            headers=_hdr(coach_token),
            json={"workout_json": new_json},
            timeout=30,
        )
        assert r.status_code == 200
        assert r.json()["item"]["workout_json"] == new_json

    def test_replace_media(self, coach_token):
        vid = pytest.video_item_id
        get_r = requests.get(f"{API}/on-demand/coach/items/{vid}", headers=_hdr(coach_token), timeout=30)
        old_key = get_r.json()["item"]["media_storage_key"]

        r = requests.patch(
            f"{API}/on-demand/coach/items/{vid}",
            headers=_hdr(coach_token),
            json={"media": {"file_b64": _tiny_b64(2048), "file_mime": "video/webm", "file_name": "clip.webm"}},
            timeout=90,
        )
        assert r.status_code == 200, r.text
        item = r.json()["item"]
        assert item["media_ext"] == "webm"
        assert item["media_mime"] == "video/webm"
        # key changes because extension changed
        assert item["media_storage_key"] != old_key


# ----- Publish toggle ----------------------------------------------------------

class TestPublish:
    def test_publish_true(self, coach_token):
        aid = pytest.audio_item_id
        r = requests.post(
            f"{API}/on-demand/coach/items/{aid}/publish",
            headers=_hdr(coach_token),
            json={"published": True},
            timeout=30,
        )
        assert r.status_code == 200
        assert r.json()["published"] is True

    def test_publish_false(self, coach_token):
        aid = pytest.audio_item_id
        r = requests.post(
            f"{API}/on-demand/coach/items/{aid}/publish",
            headers=_hdr(coach_token),
            json={"published": False},
            timeout=30,
        )
        assert r.status_code == 200
        assert r.json()["published"] is False

    def test_publish_unknown_item_404(self, coach_token):
        r = requests.post(
            f"{API}/on-demand/coach/items/no-such-id/publish",
            headers=_hdr(coach_token),
            json={"published": True},
            timeout=30,
        )
        assert r.status_code == 404


# ----- Public read + media URL visibility -------------------------------------

class TestPublicRead:
    def test_client_cannot_see_unpublished(self, client_token):
        wid = pytest.workout_item_id  # unpublished
        r = requests.get(f"{API}/on-demand/items/{wid}", headers=_hdr(client_token), timeout=30)
        assert r.status_code == 404

    def test_coach_can_see_unpublished(self, coach_token):
        wid = pytest.workout_item_id
        r = requests.get(f"{API}/on-demand/items/{wid}", headers=_hdr(coach_token), timeout=30)
        assert r.status_code == 200
        assert r.json()["item"]["id"] == wid

    def test_client_can_see_published(self, client_token):
        vid = pytest.video_item_id  # published in create test
        r = requests.get(f"{API}/on-demand/items/{vid}", headers=_hdr(client_token), timeout=30)
        assert r.status_code == 200

    def test_media_url_workout_returns_400(self, coach_token):
        wid = pytest.workout_item_id
        r = requests.get(f"{API}/on-demand/items/{wid}/media-url", headers=_hdr(coach_token), timeout=30)
        assert r.status_code == 400
        assert "workout" in r.text.lower()

    def test_media_url_unpublished_hidden_from_client(self, client_token, coach_token):
        # Ensure video item is unpublished, then check client 404
        vid = pytest.video_item_id
        requests.post(
            f"{API}/on-demand/coach/items/{vid}/publish",
            headers=_hdr(coach_token),
            json={"published": False},
            timeout=30,
        )
        rc = requests.get(f"{API}/on-demand/items/{vid}/media-url", headers=_hdr(client_token), timeout=30)
        assert rc.status_code == 404
        # Coach still gets a URL
        rk = requests.get(f"{API}/on-demand/items/{vid}/media-url", headers=_hdr(coach_token), timeout=30)
        assert rk.status_code == 200, rk.text
        body = rk.json()
        assert body.get("url")
        assert body.get("mime")
        assert body.get("expires_in") == 30 * 60
        assert body.get("driver")

    def test_media_url_published_visible_to_client(self, coach_token, client_token):
        vid = pytest.video_item_id
        # Re-publish
        requests.post(
            f"{API}/on-demand/coach/items/{vid}/publish",
            headers=_hdr(coach_token),
            json={"published": True},
            timeout=30,
        )
        r = requests.get(f"{API}/on-demand/items/{vid}/media-url", headers=_hdr(client_token), timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("url")

    def test_thumbnail_url(self, coach_token, client_token):
        vid = pytest.video_item_id
        r = requests.get(f"{API}/on-demand/items/{vid}/thumbnail-url", headers=_hdr(client_token), timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("url")

    def test_item_without_media_returns_404_on_media_url(self, coach_token, created_ids):
        # Create a workout with no media then try to fetch media-url — content_type=workout blocks it at 400
        # For a true 'item_has_no_media', we'd need a non-workout item with cleared media which the API
        # does not currently allow. Skip that specific edge case.
        pytest.skip("Cannot construct non-workout item with no media via current API surface")


# ----- Category deletion cascades to items ------------------------------------

class TestCategoryTagDeletionCascade:
    def test_delete_category_clears_from_item(self, coach_token, created_ids):
        # Create a new category and item referencing it
        cat_r = requests.post(
            f"{API}/on-demand/coach/categories",
            headers=_hdr(coach_token),
            json={"name": f"TEST_CascadeCat_{uuid.uuid4().hex[:6]}"},
            timeout=30,
        )
        assert cat_r.status_code == 200
        cid = cat_r.json()["category"]["id"]

        item_r = requests.post(
            f"{API}/on-demand/coach/items",
            headers=_hdr(coach_token),
            json={
                "title": "TEST_CascadeItem",
                "content_type": "workout",
                "workout_json": {"title": "t", "blocks": []},
                "category_id": cid,
            },
            timeout=30,
        )
        assert item_r.status_code == 200
        iid = item_r.json()["item"]["id"]
        created_ids["items"].append(iid)

        # Delete category
        d = requests.delete(f"{API}/on-demand/coach/categories/{cid}", headers=_hdr(coach_token), timeout=30)
        assert d.status_code == 200

        # Item should have category_id = None
        after = requests.get(f"{API}/on-demand/coach/items/{iid}", headers=_hdr(coach_token), timeout=30)
        assert after.status_code == 200
        assert after.json()["item"]["category_id"] is None

    def test_delete_tag_pulls_from_items(self, coach_token, created_ids):
        tag_r = requests.post(
            f"{API}/on-demand/coach/tags",
            headers=_hdr(coach_token),
            json={"name": f"TEST_CascadeTag_{uuid.uuid4().hex[:6]}"},
            timeout=30,
        )
        assert tag_r.status_code == 200
        tid = tag_r.json()["tag"]["id"]

        item_r = requests.post(
            f"{API}/on-demand/coach/items",
            headers=_hdr(coach_token),
            json={
                "title": "TEST_TagCascadeItem",
                "content_type": "workout",
                "workout_json": {"title": "t", "blocks": []},
                "tag_ids": [tid],
            },
            timeout=30,
        )
        assert item_r.status_code == 200
        iid = item_r.json()["item"]["id"]
        created_ids["items"].append(iid)

        d = requests.delete(f"{API}/on-demand/coach/tags/{tid}", headers=_hdr(coach_token), timeout=30)
        assert d.status_code == 200

        after = requests.get(f"{API}/on-demand/coach/items/{iid}", headers=_hdr(coach_token), timeout=30)
        assert after.status_code == 200
        assert tid not in (after.json()["item"].get("tag_ids") or [])


# ----- Delete item -------------------------------------------------------------

class TestDeleteItem:
    def test_delete_item(self, coach_token, created_ids):
        # Create a throwaway to delete
        r = requests.post(
            f"{API}/on-demand/coach/items",
            headers=_hdr(coach_token),
            json={
                "title": "TEST_Delete_me",
                "content_type": "workout",
                "workout_json": {"title": "d", "blocks": []},
            },
            timeout=30,
        )
        assert r.status_code == 200
        iid = r.json()["item"]["id"]

        d = requests.delete(f"{API}/on-demand/coach/items/{iid}", headers=_hdr(coach_token), timeout=30)
        assert d.status_code == 200
        assert d.json()["deleted_id"] == iid

        g = requests.get(f"{API}/on-demand/coach/items/{iid}", headers=_hdr(coach_token), timeout=30)
        assert g.status_code == 404

    def test_delete_missing_item(self, coach_token):
        r = requests.delete(f"{API}/on-demand/coach/items/does-not-exist", headers=_hdr(coach_token), timeout=30)
        assert r.status_code == 404
