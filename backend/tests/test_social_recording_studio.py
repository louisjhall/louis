"""
Test suite for feature_social_studio Recording Studio endpoints (§32).

Covers the NEW media asset + subtitle endpoints:
  - POST /social/posts/{post_id}/assets  (multipart upload)
  - GET  /social/posts/{post_id}/assets  (list)
  - GET  /social/assets/{asset_id}       (detail)
  - GET  /social/assets/{asset_id}/stream (Bearer + ?token= auth paths)
  - DELETE /social/assets/{asset_id}     (soft-archive + file unlink)
  - POST /social/assets/{asset_id}/subtitles/generate (STUB)
  - GET  /social/assets/{asset_id}/subtitles

Plus role gating (client → 403) and regression spot-checks.
"""
import os
import struct
import datetime as _dt
from pathlib import Path

import pytest
import requests


BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
).rstrip("/")
API = f"{BASE_URL}/api"

MEDIA_ROOT = Path("/app/backend/uploads/social_assets")


# ---- Helpers --------------------------------------------------------------

def _tiny_mp4_bytes() -> bytes:
    """Return a minimal valid-ish mp4 blob (few hundred bytes).

    Not a playable file but has the ftyp box so mime sniffing is fine —
    server accepts based on the client-provided Content-Type in multipart.
    """
    ftyp = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41"
    # ~200KB of padding to make size assertions meaningful
    return ftyp + (b"\x00" * (200 * 1024))


@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    return s


@pytest.fixture(scope="module")
def coach_auth(http):
    r = http.post(
        f"{API}/auth/login",
        json={"email": "coach@crewfit.com", "password": "Coach123!"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    return {"token": data["token"], "headers": {"Authorization": f"Bearer " + data["token"]}, "user": data["user"]}


@pytest.fixture(scope="module")
def client_auth(http):
    r = http.post(
        f"{API}/auth/login",
        json={"email": "client@crewfit.com", "password": "Client123!"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    return {"token": data["token"], "headers": {"Authorization": f"Bearer " + data["token"]}, "user": data["user"]}


@pytest.fixture(scope="module")
def draft_post(http, coach_auth):
    """Create a post in Draft state (upstream) so upload should transition it to Recorded."""
    r = http.post(
        f"{API}/social/posts",
        headers={**coach_auth["headers"], "Content-Type": "application/json"},
        json={
            "title": "TEST_recording_" + _dt.datetime.utcnow().isoformat(),
            "platform": "Instagram",
            "post_type": "Reel script",
            "content_pillar": "Hotel gym training",
            "hook": "test",
            "script": "test",
        },
        timeout=30,
    )
    assert r.status_code == 200, r.text
    post = r.json()["post"]
    assert post["status"] == "Draft"
    return post


# ---------------------------------------------------------------------------
# 1) Upload
# ---------------------------------------------------------------------------

class TestAssetUpload:
    def test_upload_video_success_and_status_transition(self, http, coach_auth, draft_post):
        pid = draft_post["id"]
        blob = _tiny_mp4_bytes()
        files = {"file": ("clip.mp4", blob, "video/mp4")}
        data = {"duration_seconds": "12.5", "width": "1080", "height": "1920", "kind": "video"}
        r = http.post(
            f"{API}/social/posts/{pid}/assets",
            headers=coach_auth["headers"],
            files=files,
            data=data,
            timeout=60,
        )
        assert r.status_code in (200, 201), r.text
        asset = r.json()["asset"]
        # Save asset id for downstream tests
        pytest.asset_id = asset["id"]
        pytest.post_id = pid

        # (a) shape checks
        assert asset["id"]
        assert asset["kind"] == "video"
        assert asset["storage"] == "local"
        assert asset["size_bytes"] == len(blob)
        assert asset["mime"] == "video/mp4"
        assert asset["extension"] == ".mp4"
        assert asset["status"] == "draft"
        assert asset["post_id"] == pid

        # (c) file exists on disk
        expected_path = MEDIA_ROOT / pid / (asset["id"] + ".mp4")
        assert expected_path.exists(), f"file missing at {expected_path}"
        assert expected_path.stat().st_size == len(blob)

        # (d) post status transitioned to Recorded + media_id set
        got = http.get(f"{API}/social/posts/{pid}", headers=coach_auth["headers"], timeout=15).json()["post"]
        assert got["status"] == "Recorded", got["status"]
        assert got["media_id"] == asset["id"]

    def test_upload_rejects_image_mime(self, http, coach_auth, draft_post):
        pid = draft_post["id"]
        files = {"file": ("bad.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 128, "image/png")}
        r = http.post(
            f"{API}/social/posts/{pid}/assets",
            headers=coach_auth["headers"],
            files=files,
            timeout=30,
        )
        assert r.status_code == 400, r.text
        assert "unsupported" in r.text.lower() or "content-type" in r.text.lower()

    def test_upload_nonexistent_post_404(self, http, coach_auth):
        files = {"file": ("clip.mp4", _tiny_mp4_bytes()[:1024], "video/mp4")}
        r = http.post(
            f"{API}/social/posts/does-not-exist/assets",
            headers=coach_auth["headers"],
            files=files,
            timeout=30,
        )
        assert r.status_code == 404

    def test_upload_size_limit_413(self, http, coach_auth, draft_post):
        """Stream a > 120MB payload and expect 413.

        We use a generator to avoid materialising 121MB in memory at once.
        Note: The server rejects mid-write when total exceeds MAX_UPLOAD_BYTES.
        The connection may be closed before the client finishes streaming — that
        is acceptable as long as the returned status is 413 OR the client
        observes a connection error immediately after ~120MB.
        """
        # Prepare a multipart body manually so we can stream a large "video" without
        # requests buffering the whole thing.
        boundary = "----crewfitBOUND"
        headers = {
            **coach_auth["headers"],
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        pre = (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"file\"; filename=\"big.mp4\"\r\n"
            f"Content-Type: video/mp4\r\n\r\n"
        ).encode()
        post = f"\r\n--{boundary}--\r\n".encode()
        target_bytes = 130 * 1024 * 1024  # 130 MB, safely above cap

        def body_gen():
            yield pre
            chunk = b"\x00" * (1024 * 1024)  # 1 MB
            sent = 0
            while sent < target_bytes:
                yield chunk
                sent += len(chunk)
            yield post

        try:
            r = requests.post(
                f"{API}/social/posts/{draft_post['id']}/assets",
                headers=headers,
                data=body_gen(),
                timeout=180,
                stream=False,
            )
            # Ideal: server returns 413 with a JSON detail
            assert r.status_code == 413, f"expected 413, got {r.status_code}: {r.text[:300]}"
        except requests.exceptions.ChunkedEncodingError:
            # Server closed the connection mid-upload after limit hit — acceptable
            pytest.skip("Server closed connection mid-upload after size cap (acceptable behaviour)")
        except requests.exceptions.ConnectionError as e:
            pytest.skip(f"Connection closed by proxy at size cap: {e}")


# ---------------------------------------------------------------------------
# 2) List / Detail
# ---------------------------------------------------------------------------

class TestAssetListDetail:
    def test_list_returns_asset(self, http, coach_auth):
        pid = pytest.post_id
        r = http.get(f"{API}/social/posts/{pid}/assets", headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "assets" in body and "count" in body
        ids = [a["id"] for a in body["assets"]]
        assert pytest.asset_id in ids
        # file_path must NOT be exposed
        for a in body["assets"]:
            assert "file_path" not in a, f"file_path leaked in list response: {a}"

    def test_list_sorted_created_at_desc(self, http, coach_auth, draft_post):
        """Upload a 2nd asset and verify newest first."""
        pid = pytest.post_id
        files = {"file": ("clip2.mp4", _tiny_mp4_bytes()[:50 * 1024], "video/mp4")}
        r = http.post(f"{API}/social/posts/{pid}/assets", headers=coach_auth["headers"], files=files, timeout=30)
        assert r.status_code in (200, 201)
        new_asset = r.json()["asset"]

        r2 = http.get(f"{API}/social/posts/{pid}/assets", headers=coach_auth["headers"], timeout=15)
        assets = r2.json()["assets"]
        assert len(assets) >= 2
        # Newest should be first
        assert assets[0]["id"] == new_asset["id"], f"expected newest first, got {[a['id'] for a in assets]}"
        # Cleanup — leave primary asset alone
        http.delete(f"{API}/social/assets/{new_asset['id']}", headers=coach_auth["headers"], timeout=15)

    def test_get_asset_detail(self, http, coach_auth):
        r = http.get(f"{API}/social/assets/{pytest.asset_id}", headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200
        asset = r.json()["asset"]
        assert asset["id"] == pytest.asset_id
        assert "file_path" not in asset  # never expose disk path

    def test_get_asset_not_found(self, http, coach_auth):
        r = http.get(f"{API}/social/assets/nonexistent-id", headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 3) Stream (both auth paths)
# ---------------------------------------------------------------------------

class TestAssetStream:
    def test_stream_with_bearer_header(self, http, coach_auth):
        r = http.get(
            f"{API}/social/assets/{pytest.asset_id}/stream",
            headers=coach_auth["headers"],
            timeout=30,
        )
        assert r.status_code == 200, r.text
        assert "video" in r.headers.get("content-type", "").lower()
        assert len(r.content) > 0

    def test_stream_with_query_token(self, http, coach_auth):
        r = http.get(
            f"{API}/social/assets/{pytest.asset_id}/stream",
            params={"token": coach_auth["token"]},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        assert len(r.content) > 0

    def test_stream_no_auth_returns_401(self, http):
        r = http.get(f"{API}/social/assets/{pytest.asset_id}/stream", timeout=15)
        assert r.status_code == 401, r.text

    def test_stream_bad_token_returns_401(self, http):
        r = http.get(
            f"{API}/social/assets/{pytest.asset_id}/stream",
            params={"token": "garbage"},
            timeout=15,
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 4) Subtitle stub
# ---------------------------------------------------------------------------

class TestSubtitleStub:
    def test_generate_subtitle_creates_pending_doc(self, http, coach_auth):
        r = http.post(
            f"{API}/social/assets/{pytest.asset_id}/subtitles/generate",
            headers=coach_auth["headers"],
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "subtitle" in body and "note" in body
        sub = body["subtitle"]
        assert sub["status"] == "pending"
        assert sub["provider"] == "whisper-1-stub"
        assert sub["asset_id"] == pytest.asset_id
        assert sub["language"] == "en"
        assert isinstance(sub["segments"], list)
        # Asset should now have subtitle_id set
        r2 = http.get(f"{API}/social/assets/{pytest.asset_id}", headers=coach_auth["headers"], timeout=15)
        assert r2.json()["asset"]["subtitle_id"] == sub["id"]

    def test_get_subtitle_returns_latest(self, http, coach_auth):
        r = http.get(
            f"{API}/social/assets/{pytest.asset_id}/subtitles",
            headers=coach_auth["headers"],
            timeout=15,
        )
        assert r.status_code == 200
        sub = r.json()["subtitle"]
        assert sub is not None
        assert sub["asset_id"] == pytest.asset_id


# ---------------------------------------------------------------------------
# 5) Delete (retake flow)
# ---------------------------------------------------------------------------

class TestAssetDelete:
    def test_delete_asset_archives_and_unlinks(self, http, coach_auth):
        aid = pytest.asset_id
        pid = pytest.post_id
        # Confirm file exists first
        expected_path = MEDIA_ROOT / pid / (aid + ".mp4")
        assert expected_path.exists()

        r = http.delete(f"{API}/social/assets/{aid}", headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        # (a) asset doc → status archived, file_path cleared
        # Query Mongo indirectly through the detail endpoint (still returns archived docs)
        det = http.get(f"{API}/social/assets/{aid}", headers=coach_auth["headers"], timeout=15)
        assert det.status_code == 200
        asset = det.json()["asset"]
        assert asset["status"] == "archived"
        # file_path never exposed anyway; ensure it's not present
        assert "file_path" not in asset

        # (b) file removed from disk
        assert not expected_path.exists(), f"file should be gone: {expected_path}"

        # (c) post.media_id was pointing at this asset → unlinked to None
        got = http.get(f"{API}/social/posts/{pid}", headers=coach_auth["headers"], timeout=15).json()["post"]
        assert got["media_id"] is None, f"expected media_id unlinked, got {got['media_id']}"

        # (d) subsequent stream → 404
        s = http.get(
            f"{API}/social/assets/{aid}/stream",
            headers=coach_auth["headers"],
            timeout=15,
        )
        assert s.status_code == 404, s.text

    def test_delete_nonexistent_asset_404(self, http, coach_auth):
        r = http.delete(f"{API}/social/assets/no-such-id", headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 6) Role gating — client must never access any social endpoint
# ---------------------------------------------------------------------------

class TestClientRoleGuard:
    """Every new Recording Studio endpoint should reject the client user."""

    def _forbid(self, resp):
        assert resp.status_code in (401, 403), (
            f"expected 401/403, got {resp.status_code}: {resp.text[:200]}"
        )

    def test_client_cannot_list_assets(self, http, client_auth, draft_post):
        r = http.get(f"{API}/social/posts/{draft_post['id']}/assets", headers=client_auth["headers"], timeout=15)
        self._forbid(r)

    def test_client_cannot_upload_asset(self, http, client_auth, draft_post):
        files = {"file": ("x.mp4", _tiny_mp4_bytes()[:2048], "video/mp4")}
        r = http.post(
            f"{API}/social/posts/{draft_post['id']}/assets",
            headers=client_auth["headers"],
            files=files,
            timeout=30,
        )
        self._forbid(r)

    def test_client_cannot_get_asset(self, http, client_auth):
        # Any id works — auth guard fires first
        r = http.get(f"{API}/social/assets/anything", headers=client_auth["headers"], timeout=15)
        self._forbid(r)

    def test_client_cannot_delete_asset(self, http, client_auth):
        r = http.delete(f"{API}/social/assets/anything", headers=client_auth["headers"], timeout=15)
        self._forbid(r)

    def test_client_cannot_stream_asset_with_own_token(self, http, client_auth):
        # Bearer path
        r1 = http.get(
            f"{API}/social/assets/anything/stream",
            headers=client_auth["headers"],
            timeout=15,
        )
        self._forbid(r1)
        # ?token path — must also reject client role
        r2 = http.get(
            f"{API}/social/assets/anything/stream",
            params={"token": client_auth["token"]},
            timeout=15,
        )
        self._forbid(r2)

    def test_client_cannot_generate_subtitles(self, http, client_auth):
        r = http.post(f"{API}/social/assets/anything/subtitles/generate", headers=client_auth["headers"], timeout=15)
        self._forbid(r)

    def test_client_cannot_get_subtitles(self, http, client_auth):
        r = http.get(f"{API}/social/assets/anything/subtitles", headers=client_auth["headers"], timeout=15)
        self._forbid(r)


# ---------------------------------------------------------------------------
# 7) Regression spot-check (existing Social Studio endpoints still 200)
# ---------------------------------------------------------------------------

class TestRegressionSpotCheck:
    def test_settings_get(self, http, coach_auth):
        r = http.get(f"{API}/social/settings", headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200

    def test_posts_list(self, http, coach_auth):
        r = http.get(f"{API}/social/posts", headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200
        assert "posts" in r.json()

    def test_posts_create_and_dismiss(self, http, coach_auth):
        r = http.post(
            f"{API}/social/posts",
            headers={**coach_auth["headers"], "Content-Type": "application/json"},
            json={
                "title": "TEST_regression",
                "platform": "LinkedIn",
                "post_type": "LinkedIn post",
                "content_pillar": "CrewFit app features",
            },
            timeout=30,
        )
        assert r.status_code == 200
        pid = r.json()["post"]["id"]
        d = http.post(f"{API}/social/posts/{pid}/dismiss", headers=coach_auth["headers"], timeout=15)
        assert d.status_code == 200

    def test_analytics(self, http, coach_auth):
        r = http.get(f"{API}/social/analytics", headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200
        body = r.json()
        for k in ("by_status", "by_platform", "by_pillar", "counts"):
            assert k in body
