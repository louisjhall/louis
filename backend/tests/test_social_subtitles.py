"""
Test suite for §33 Social Studio subtitle pipeline (Whisper-1 + ffmpeg burn-in).

Covers:
  - POST /social/assets/{asset_id}/subtitles/generate  (kick off whisper job, poll to ready)
  - GET  /social/subtitles/{id}                        (poll)
  - PATCH /social/subtitles/{id}                       (edit segments, srt/vtt rebuild, burn invalidation)
  - POST /social/subtitles/{id}/burn                   (ffmpeg burn-in, poll burned_video_path)
  - GET  /social/subtitles/{id}/download?fmt=srt|vtt   (both auth paths; invalid fmt 400)
  - GET  /social/subtitles/{id}/burned/stream          (both auth paths; 404 when not ready)
  - GET  /social/assets/{id}/subtitles                 (latest doc / null)
  - Client-role gating on every new endpoint          (401/403)
  - Burning while status invalid (pending/generating) → 400
  - Regression: §32 asset upload/list/detail still works
"""
import os
import time
import datetime as _dt
from pathlib import Path

import pytest
import requests

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or "https://flight-fit-plans.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"

VIDEO_FIXTURE = Path("/tmp/whispertest/test.mp4")

# Shared module state (avoids uploading a fresh video per test)
_state: dict = {}


# ---- Auth helpers ---------------------------------------------------------

@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    return s


@pytest.fixture(scope="module")
def coach_auth(http):
    r = http.post(f"{API}/auth/login", json={"email": "coach@crewfit.com", "password": "Coach123!"}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    return {"headers": {"Authorization": f"Bearer {data['token']}"}, "token": data["token"], "user": data["user"]}


@pytest.fixture(scope="module")
def client_auth(http):
    r = http.post(f"{API}/auth/login", json={"email": "client@crewfit.com", "password": "Client123!"}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    return {"headers": {"Authorization": f"Bearer {data['token']}"}, "token": data["token"], "user": data["user"]}


# ---- Session setup: create post + upload video ---------------------------

@pytest.fixture(scope="module", autouse=True)
def _setup_post_and_asset(http, coach_auth):
    """Creates a fresh post + uploads /tmp/whispertest/test.mp4 → registers ids in _state."""
    h = coach_auth["headers"]
    # 1) Create a fresh Draft post
    r = http.post(f"{API}/social/posts", headers=h, json={
        "title": "TEST_subtitle_" + _dt.datetime.utcnow().isoformat(),
        "platform": "LinkedIn",
        "post_type": "LinkedIn post",
        "content_pillar": "Roster-proof fitness",
    }, timeout=30)
    assert r.status_code == 200, r.text
    _state["post_id"] = r.json()["post"]["id"]

    # 2) Upload the test video via multipart
    assert VIDEO_FIXTURE.exists(), f"test video missing at {VIDEO_FIXTURE}"
    files = {"file": ("test.mp4", VIDEO_FIXTURE.read_bytes(), "video/mp4")}
    data = {"kind": "video", "duration_seconds": "5"}
    up = http.post(f"{API}/social/posts/{_state['post_id']}/assets",
                   headers=h, files=files, data=data, timeout=60)
    assert up.status_code == 200, up.text
    _state["asset_id"] = up.json()["asset"]["id"]
    yield
    # No cleanup: main agent asked us to leave artifacts on disk for inspection


def _poll_subtitle(http, headers, sub_id, want, deadline_s=45, interval=1.5):
    """Poll GET /social/subtitles/{id} until status == want (or list of wants)."""
    wants = want if isinstance(want, (list, tuple, set)) else (want,)
    deadline = time.time() + deadline_s
    last = None
    while time.time() < deadline:
        r = http.get(f"{API}/social/subtitles/{sub_id}", headers=headers, timeout=15)
        assert r.status_code == 200, r.text
        last = r.json()["subtitle"]
        if last.get("status") in wants:
            return last
        time.sleep(interval)
    raise AssertionError(f"subtitle {sub_id} did not reach {wants}; last status={last.get('status') if last else None}, error={last.get('error') if last else None}")


# ---- 1. Generate subtitles + poll to ready --------------------------------

class TestGenerateAndPoll:
    def test_generate_kicks_off_pending_job(self, http, coach_auth):
        h = coach_auth["headers"]
        r = http.post(f"{API}/social/assets/{_state['asset_id']}/subtitles/generate",
                      headers=h, json={"language": "en"}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "subtitle" in body and "note" in body
        sub = body["subtitle"]
        assert sub["status"] in ("pending", "generating"), f"expected pending/generating, got {sub['status']}"
        assert sub["asset_id"] == _state["asset_id"]
        assert sub["provider"] == "whisper-1"
        _state["sub_id"] = sub["id"]
        # Asset should now carry subtitle_id
        aget = http.get(f"{API}/social/assets/{_state['asset_id']}", headers=h, timeout=15)
        assert aget.status_code == 200
        assert aget.json()["asset"]["subtitle_id"] == sub["id"]

    def test_generate_idempotent_while_pending(self, http, coach_auth):
        h = coach_auth["headers"]
        r = http.post(f"{API}/social/assets/{_state['asset_id']}/subtitles/generate",
                      headers=h, json={"language": "en"}, timeout=30)
        assert r.status_code == 200
        body = r.json()
        # Should reuse the in-flight job (or a ready one is also acceptable if whisper was very fast)
        assert body["subtitle"]["id"] == _state["sub_id"] or body["subtitle"]["status"] in ("ready", "edited")

    def test_poll_until_ready_with_segments_srt_vtt(self, http, coach_auth):
        h = coach_auth["headers"]
        sub = _poll_subtitle(http, h, _state["sub_id"], want="ready", deadline_s=60)
        # Segments non-empty (whisper may return a single 'you' segment on silent audio; still counts)
        assert isinstance(sub["segments"], list) and len(sub["segments"]) >= 1, sub
        assert sub["srt"] and isinstance(sub["srt"], str) and sub["srt"].startswith("1\n00:00:"), sub["srt"][:100]
        assert sub["vtt"] and sub["vtt"].startswith("WEBVTT"), sub["vtt"][:60]
        assert sub.get("language"), "language should be set"
        assert sub.get("error") in (None, ""), f"unexpected error: {sub.get('error')}"

    def test_sidecar_files_on_disk(self, http, coach_auth):
        h = coach_auth["headers"]
        r = http.get(f"{API}/social/subtitles/{_state['sub_id']}", headers=h, timeout=15)
        sub = r.json()["subtitle"]
        # Server does not expose srt_path in the API projection? Check if present (schema includes it via _run_subtitle_job set)
        srt_path = sub.get("srt_path")
        vtt_path = sub.get("vtt_path")
        # Even if API doesn't project the path, we can find files on disk under uploads/social_assets/<post_id>/
        pdir = Path("/app/backend/uploads/social_assets") / _state["post_id"]
        assert pdir.exists(), f"missing post dir {pdir}"
        srts = list(pdir.glob("*.srt"))
        vtts = list(pdir.glob("*.vtt"))
        assert srts, f"no .srt sidecar under {pdir}"
        assert vtts, f"no .vtt sidecar under {pdir}"
        # If the doc has explicit paths, verify they exist
        if srt_path: assert Path(srt_path).exists()
        if vtt_path: assert Path(vtt_path).exists()


# ---- 2. GET assets/{id}/subtitles -----------------------------------------

class TestSubtitleByAsset:
    def test_get_by_asset_returns_latest(self, http, coach_auth):
        h = coach_auth["headers"]
        r = http.get(f"{API}/social/assets/{_state['asset_id']}/subtitles", headers=h, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["subtitle"] is not None
        assert body["subtitle"]["id"] == _state["sub_id"]

    def test_get_by_asset_null_when_none(self, http, coach_auth):
        h = coach_auth["headers"]
        # Create another (post + asset) with no subtitle
        pr = http.post(f"{API}/social/posts", headers=h, json={
            "title": "TEST_no_sub",
            "platform": "LinkedIn",
            "post_type": "LinkedIn post",
            "content_pillar": "Roster-proof fitness",
        }, timeout=30)
        pid = pr.json()["post"]["id"]
        files = {"file": ("t.mp4", VIDEO_FIXTURE.read_bytes(), "video/mp4")}
        up = http.post(f"{API}/social/posts/{pid}/assets", headers=h,
                       files=files, data={"kind": "video"}, timeout=30)
        aid = up.json()["asset"]["id"]
        r = http.get(f"{API}/social/assets/{aid}/subtitles", headers=h, timeout=15)
        assert r.status_code == 200
        assert r.json()["subtitle"] is None


# ---- 3. Download (fmt=srt, fmt=vtt, invalid, both auth paths) -------------

class TestDownload:
    def test_download_srt_header_auth(self, http, coach_auth):
        h = coach_auth["headers"]
        r = http.get(f"{API}/social/subtitles/{_state['sub_id']}/download?fmt=srt", headers=h, timeout=15)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/x-subrip")
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd and f'{_state["sub_id"]}.srt' in cd
        assert r.text.startswith("1\n00:00:")

    def test_download_vtt_header_auth(self, http, coach_auth):
        h = coach_auth["headers"]
        r = http.get(f"{API}/social/subtitles/{_state['sub_id']}/download?fmt=vtt", headers=h, timeout=15)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("text/vtt")
        assert r.text.startswith("WEBVTT")

    def test_download_srt_query_token_auth(self, http, coach_auth):
        tok = coach_auth["token"]
        r = http.get(f"{API}/social/subtitles/{_state['sub_id']}/download?fmt=srt&token={tok}", timeout=15)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/x-subrip")

    def test_download_vtt_query_token_auth(self, http, coach_auth):
        tok = coach_auth["token"]
        r = http.get(f"{API}/social/subtitles/{_state['sub_id']}/download?fmt=vtt&token={tok}", timeout=15)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("text/vtt")

    def test_download_invalid_fmt(self, http, coach_auth):
        h = coach_auth["headers"]
        r = http.get(f"{API}/social/subtitles/{_state['sub_id']}/download?fmt=xyz", headers=h, timeout=15)
        assert r.status_code == 400


# ---- 4. PATCH segments → status=edited, srt/vtt rebuild, burn cleared ----

class TestPatch:
    def test_patch_rebuilds_srt_vtt_and_flips_status(self, http, coach_auth):
        h = coach_auth["headers"]
        new_segs = [
            {"index": 0, "start": 0.0,  "end": 2.0, "text": "TEST_EDIT_SEG_ONE"},
            {"index": 1, "start": 2.0,  "end": 4.5, "text": "TEST_EDIT_SEG_TWO"},
        ]
        r = http.patch(f"{API}/social/subtitles/{_state['sub_id']}",
                       headers=h, json={"segments": new_segs}, timeout=30)
        assert r.status_code == 200, r.text
        saved = r.json()["subtitle"]
        assert saved["status"] == "edited"
        assert saved["burned_video_path"] is None
        assert "TEST_EDIT_SEG_ONE" in (saved["srt"] or "")
        assert "TEST_EDIT_SEG_TWO" in (saved["srt"] or "")
        assert "TEST_EDIT_SEG_ONE" in (saved["vtt"] or "")
        assert saved["vtt"].startswith("WEBVTT")
        # Sidecar srt on disk must match the new content
        pdir = Path("/app/backend/uploads/social_assets") / _state["post_id"]
        srts = list(pdir.glob("*.srt"))
        assert srts
        assert "TEST_EDIT_SEG_ONE" in srts[0].read_text(encoding="utf-8")


# ---- 5. Burn (happy path + invalid state) --------------------------------

class TestBurn:
    def test_burn_kickoff_and_ready(self, http, coach_auth):
        h = coach_auth["headers"]
        r = http.post(f"{API}/social/subtitles/{_state['sub_id']}/burn",
                      headers=h, json={}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        sub = _poll_subtitle(http, h, _state["sub_id"], want="ready", deadline_s=120, interval=2.0)
        bp = sub.get("burned_video_path")
        assert bp, f"burned_video_path not set: {sub}"
        expected_suffix = "_subtitled.mp4"
        assert bp.endswith(expected_suffix), bp
        assert _state["post_id"] in bp
        p = Path(bp)
        assert p.exists(), f"burned file missing on disk: {p}"
        assert p.stat().st_size > 0, f"burned file empty: {p}"
        _state["burned_path"] = bp

    def test_burn_stream_header_auth(self, http, coach_auth):
        h = coach_auth["headers"]
        r = http.get(f"{API}/social/subtitles/{_state['sub_id']}/burned/stream",
                     headers=h, timeout=30, stream=True)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("video/mp4")
        # Read first ~64KB to prove the stream works
        chunk = next(r.iter_content(chunk_size=65536), b"")
        assert len(chunk) > 0
        r.close()

    def test_burn_stream_query_token_auth(self, http, coach_auth):
        tok = coach_auth["token"]
        r = http.get(f"{API}/social/subtitles/{_state['sub_id']}/burned/stream?token={tok}",
                     timeout=30, stream=True)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("video/mp4")
        r.close()

    def test_burn_stream_404_when_no_burn(self, http, coach_auth):
        """Fresh subtitle with no burn yet → 404 on burned/stream."""
        h = coach_auth["headers"]
        # Create a fresh post+asset+subtitle to test
        pr = http.post(f"{API}/social/posts", headers=h, json={
            "title": "TEST_no_burn", "platform": "LinkedIn",
            "post_type": "LinkedIn post", "content_pillar": "Roster-proof fitness",
        }, timeout=30)
        pid = pr.json()["post"]["id"]
        files = {"file": ("t.mp4", VIDEO_FIXTURE.read_bytes(), "video/mp4")}
        up = http.post(f"{API}/social/posts/{pid}/assets", headers=h,
                       files=files, data={"kind": "video"}, timeout=30)
        aid = up.json()["asset"]["id"]
        gr = http.post(f"{API}/social/assets/{aid}/subtitles/generate",
                       headers=h, json={"language": "en"}, timeout=30)
        sid = gr.json()["subtitle"]["id"]
        # Poll to ready to make sure captions exist but no burn was requested
        _poll_subtitle(http, h, sid, want="ready", deadline_s=60)
        r = http.get(f"{API}/social/subtitles/{sid}/burned/stream", headers=h, timeout=15)
        assert r.status_code == 404
        _state["second_sub_id"] = sid

    def test_burn_400_when_status_invalid(self, http, coach_auth):
        """Burning while status is 'pending'/'generating' → 400."""
        h = coach_auth["headers"]
        # Create yet another asset + kick off but do NOT poll to ready
        pr = http.post(f"{API}/social/posts", headers=h, json={
            "title": "TEST_burn_invalid", "platform": "LinkedIn",
            "post_type": "LinkedIn post", "content_pillar": "Roster-proof fitness",
        }, timeout=30)
        pid = pr.json()["post"]["id"]
        files = {"file": ("t.mp4", VIDEO_FIXTURE.read_bytes(), "video/mp4")}
        up = http.post(f"{API}/social/posts/{pid}/assets", headers=h,
                       files=files, data={"kind": "video"}, timeout=30)
        aid = up.json()["asset"]["id"]
        gr = http.post(f"{API}/social/assets/{aid}/subtitles/generate",
                       headers=h, json={"language": "en"}, timeout=30)
        sid = gr.json()["subtitle"]["id"]
        # Immediately try to burn while status is still pending/generating
        r = http.post(f"{API}/social/subtitles/{sid}/burn", headers=h, json={}, timeout=15)
        assert r.status_code == 400, r.text
        # Best-effort: wait for completion to keep the DB tidy
        _poll_subtitle(http, h, sid, want=("ready", "failed"), deadline_s=45)


# ---- 6. Burn straight after generate (no PATCH first) --------------------

class TestBurnWithoutPatch:
    def test_burn_ready_state_after_generate(self, http, coach_auth):
        """Regression: burning in 'ready' state (never patched) must also succeed."""
        h = coach_auth["headers"]
        sid = _state.get("second_sub_id")
        assert sid, "second_sub_id must exist"
        # subtitle should currently be 'ready'
        rget = http.get(f"{API}/social/subtitles/{sid}", headers=h, timeout=15)
        assert rget.json()["subtitle"]["status"] == "ready"
        r = http.post(f"{API}/social/subtitles/{sid}/burn", headers=h, json={}, timeout=30)
        assert r.status_code == 200
        sub = _poll_subtitle(http, h, sid, want="ready", deadline_s=120, interval=2.0)
        bp = sub.get("burned_video_path")
        assert bp and Path(bp).exists() and Path(bp).stat().st_size > 0


# ---- 7. Role gating: client 401/403 on every new endpoint ----------------

class TestClientRoleGating:
    def test_client_generate_forbidden(self, http, client_auth):
        r = http.post(f"{API}/social/assets/{_state['asset_id']}/subtitles/generate",
                      headers=client_auth["headers"], json={}, timeout=15)
        assert r.status_code in (401, 403), r.status_code

    def test_client_get_subtitle_forbidden(self, http, client_auth):
        r = http.get(f"{API}/social/subtitles/{_state['sub_id']}",
                     headers=client_auth["headers"], timeout=15)
        assert r.status_code in (401, 403), r.status_code

    def test_client_get_by_asset_forbidden(self, http, client_auth):
        r = http.get(f"{API}/social/assets/{_state['asset_id']}/subtitles",
                     headers=client_auth["headers"], timeout=15)
        assert r.status_code in (401, 403), r.status_code

    def test_client_patch_forbidden(self, http, client_auth):
        r = http.patch(f"{API}/social/subtitles/{_state['sub_id']}",
                       headers=client_auth["headers"],
                       json={"segments": [{"index": 0, "start": 0, "end": 1, "text": "x"}]},
                       timeout=15)
        assert r.status_code in (401, 403), r.status_code

    def test_client_burn_forbidden(self, http, client_auth):
        r = http.post(f"{API}/social/subtitles/{_state['sub_id']}/burn",
                      headers=client_auth["headers"], json={}, timeout=15)
        assert r.status_code in (401, 403), r.status_code

    def test_client_download_header_auth_forbidden(self, http, client_auth):
        r = http.get(f"{API}/social/subtitles/{_state['sub_id']}/download?fmt=srt",
                     headers=client_auth["headers"], timeout=15)
        assert r.status_code in (401, 403), r.status_code

    def test_client_download_query_token_forbidden(self, http, client_auth):
        tok = client_auth["token"]
        r = http.get(f"{API}/social/subtitles/{_state['sub_id']}/download?fmt=srt&token={tok}",
                     timeout=15)
        assert r.status_code in (401, 403), r.status_code

    def test_client_burned_stream_header_forbidden(self, http, client_auth):
        r = http.get(f"{API}/social/subtitles/{_state['sub_id']}/burned/stream",
                     headers=client_auth["headers"], timeout=15)
        assert r.status_code in (401, 403), r.status_code

    def test_client_burned_stream_query_token_forbidden(self, http, client_auth):
        tok = client_auth["token"]
        r = http.get(f"{API}/social/subtitles/{_state['sub_id']}/burned/stream?token={tok}",
                     timeout=15)
        assert r.status_code in (401, 403), r.status_code


# ---- 8. Regression: §32 asset endpoints still work -----------------------

class TestRegressionAssets:
    def test_asset_detail(self, http, coach_auth):
        r = http.get(f"{API}/social/assets/{_state['asset_id']}",
                     headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200
        assert r.json()["asset"]["id"] == _state["asset_id"]

    def test_asset_list(self, http, coach_auth):
        r = http.get(f"{API}/social/posts/{_state['post_id']}/assets",
                     headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200
        assert any(a["id"] == _state["asset_id"] for a in r.json()["assets"])

    def test_asset_stream_header_auth(self, http, coach_auth):
        r = http.get(f"{API}/social/assets/{_state['asset_id']}/stream",
                     headers=coach_auth["headers"], timeout=15, stream=True)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("video/")
        r.close()
