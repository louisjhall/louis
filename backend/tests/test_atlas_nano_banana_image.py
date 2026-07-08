"""Tests for Atlas Nano Banana exercise image generation endpoint.

Endpoint: POST /api/coach/exercises/{name}/generate-image
- Requires coach role
- Uses Louis Hall reference image (/app/backend/assets/louis_ref.png)
- Uses Gemini gemini-3.1-flash-image-preview via emergentintegrations
- Returns {exercise: {custom_image_b64, image_source, image_prompt_summary,...}, source: "atlas_nano_banana"}

NOTE: Real Gemini call — set generous timeout (up to ~180s).
Do NOT log full base64 (large). Only prefix + length.
"""
import os
import time
import urllib.parse
import pytest
import requests

TIMEOUT = 180  # generation can take up to 60s+


def _preview(b64: str, n: int = 40) -> str:
    return f"{b64[:n]}...len={len(b64)}"


# ---- helpers ------------------------------------------------------------
def _get_exercise(base_url, headers, name):
    """Fetch exercise record via the coach exercises listing / public content endpoint."""
    # Use public content endpoint to grab the persisted image + image_source
    r = requests.get(
        f"{base_url}/api/exercises/content",
        headers=headers,
        params={"name": name},
        timeout=30,
    )
    if r.status_code == 200:
        return r.json().get("exercise")
    return None


# ---- Auth / permissions -------------------------------------------------
class TestAtlasImageGenAuth:
    def test_client_forbidden(self, api, base_url, client_auth):
        """Non-coach (client) must receive 403."""
        name = "Assault Bike Zone 2"
        r = requests.post(
            f"{base_url}/api/coach/exercises/{urllib.parse.quote(name, safe='')}/generate-image",
            headers=client_auth["headers"],
            json={},
            timeout=30,
        )
        assert r.status_code == 403, f"expected 403 for client, got {r.status_code}: {r.text[:200]}"

    def test_unauth_rejected(self, api, base_url):
        """No auth -> 401/403."""
        r = requests.post(
            f"{base_url}/api/coach/exercises/PushUp/generate-image",
            json={},
            timeout=30,
        )
        assert r.status_code in (401, 403), f"expected 401/403 unauth, got {r.status_code}"


# ---- Core generation ----------------------------------------------------
class TestAtlasImageGeneration:
    """Uses real Gemini calls — each test triggers an LLM image generation.
    Kept minimal to avoid excessive spend/time."""

    EXERCISE_NAME = "Assault Bike Zone 2"

    def test_coach_generates_image_success(self, base_url, coach_auth):
        """Case 1 + 2: coach can generate; DB is updated with data-URL image."""
        name = self.EXERCISE_NAME
        url = f"{base_url}/api/coach/exercises/{urllib.parse.quote(name, safe='')}/generate-image"
        t0 = time.time()
        r = requests.post(url, headers=coach_auth["headers"], json={}, timeout=TIMEOUT)
        elapsed = time.time() - t0
        print(f"[gen-image] status={r.status_code} elapsed={elapsed:.1f}s")
        assert r.status_code == 200, f"generate-image failed {r.status_code}: {r.text[:400]}"

        data = r.json()
        assert data.get("source") == "atlas_nano_banana"
        ex = data.get("exercise")
        assert ex is not None, "exercise missing in response"
        img = ex.get("custom_image_b64") or ""
        print(f"[gen-image] img preview: {_preview(img)}")
        assert img.startswith("data:image/"), f"custom_image_b64 does not start with data:image/ (got {img[:50]!r})"
        assert len(img) > 10000, f"image data too small: len={len(img)}"
        assert ex.get("image_source") == "atlas_nano_banana"
        assert ex.get("image_prompt_summary"), "image_prompt_summary missing"
        assert name.lower() in ex.get("image_prompt_summary", "").lower(), "exercise name should be in prompt summary"

        # Case 2: verify DB persistence via GET
        persisted = _get_exercise(base_url, coach_auth["headers"], name)
        assert persisted is not None, "exercise not found via GET after generation"
        pimg = persisted.get("custom_image_b64") or persisted.get("image_b64") or ""
        # exercise content endpoint may only expose certain fields — check what's exposed
        print(f"[persist] keys={list(persisted.keys())}")
        if pimg:
            assert pimg == img, "persisted image differs from response image"

    def test_coach_regenerate_replaces_image(self, base_url, coach_auth):
        """Case 3: regenerate replaces existing image."""
        name = self.EXERCISE_NAME
        url = f"{base_url}/api/coach/exercises/{urllib.parse.quote(name, safe='')}/generate-image"

        r1 = requests.post(url, headers=coach_auth["headers"], json={}, timeout=TIMEOUT)
        assert r1.status_code == 200, f"first gen failed: {r1.status_code} {r1.text[:200]}"
        img1 = r1.json()["exercise"]["custom_image_b64"]

        r2 = requests.post(url, headers=coach_auth["headers"], json={}, timeout=TIMEOUT)
        assert r2.status_code == 200, f"regen failed: {r2.status_code} {r2.text[:200]}"
        img2 = r2.json()["exercise"]["custom_image_b64"]

        print(f"[regen] img1 len={len(img1)} img2 len={len(img2)}")
        assert img2.startswith("data:image/")
        assert len(img2) > 10000
        # Gemini image gen is non-deterministic — the raw base64 should differ almost always.
        # We can't guarantee 100% inequality but it should be extremely unlikely.
        assert img1 != img2, "regenerated image is byte-identical to the previous one — replacement may not have occurred"

    def test_unknown_exercise_auto_created(self, base_url, coach_auth):
        """Case 5: unknown name -> _find_or_create_exercise auto-creates, endpoint returns 200."""
        name = f"TEST_NanoBanana_AutoExercise_{int(time.time())}"
        url = f"{base_url}/api/coach/exercises/{urllib.parse.quote(name, safe='')}/generate-image"
        r = requests.post(url, headers=coach_auth["headers"], json={}, timeout=TIMEOUT)
        print(f"[unknown-ex] status={r.status_code}")
        assert r.status_code == 200, f"auto-create + gen failed: {r.status_code} {r.text[:300]}"
        ex = r.json()["exercise"]
        assert ex.get("name", "").lower() == name.lower()
        img = ex.get("custom_image_b64") or ""
        assert img.startswith("data:image/") and len(img) > 10000

    def test_url_encoded_name_with_slash(self, base_url, coach_auth):
        """Case 6: exercise name with URL-unsafe chars (e.g. '90/90 Hip Rotation') must work when properly encoded."""
        name = "90/90 Hip Rotation"
        encoded = urllib.parse.quote(name, safe="")
        url = f"{base_url}/api/coach/exercises/{encoded}/generate-image"
        print(f"[encoded] url={url}")
        r = requests.post(url, headers=coach_auth["headers"], json={}, timeout=TIMEOUT)
        print(f"[encoded] status={r.status_code}")
        assert r.status_code == 200, f"encoded name failed: {r.status_code} {r.text[:300]}"
        ex = r.json()["exercise"]
        # exercise name persisted should match after decoding
        assert ex.get("name") == name, f"persisted name mismatch: {ex.get('name')!r} vs {name!r}"
        img = ex.get("custom_image_b64") or ""
        assert img.startswith("data:image/") and len(img) > 10000

    def test_style_hint_accepted(self, base_url, coach_auth):
        """Case 7: style_hint is accepted (status 200) and reflected in image_prompt_summary.

        After main-agent fix, image_prompt_summary = prompt[:900] so the style block
        (which sits around char ~432) is now captured. We assert:
          - endpoint accepts body {"style_hint": "..."} without validation error
          - image is still generated + persisted
          - image_prompt_summary contains the coach-supplied style_hint text
        """
        name = "Assault Bike Zone 2"
        style_hint = "TEST_MARKER_STUDIO_XZ7 bright cyan seamless backdrop overhead lighting"
        url = f"{base_url}/api/coach/exercises/{urllib.parse.quote(name, safe='')}/generate-image"
        r = requests.post(url, headers=coach_auth["headers"], json={"style_hint": style_hint}, timeout=TIMEOUT)
        assert r.status_code == 200, f"style_hint gen failed: {r.status_code} {r.text[:300]}"
        ex = r.json()["exercise"]
        summary = ex.get("image_prompt_summary") or ""
        print(f"[style_hint] summary_len={len(summary)} summary_head={summary[:200]!r} summary_tail={summary[-200:]!r}")
        assert summary, "image_prompt_summary should be populated when style_hint provided"
        # After fix: prompt[:900] should include the style block containing the coach hint
        assert "TEST_MARKER_STUDIO_XZ7" in summary, (
            f"style_hint text not captured in image_prompt_summary (len={len(summary)}). "
            f"summary tail: {summary[-300:]!r}"
        )
        img = ex.get("custom_image_b64") or ""
        assert img.startswith("data:image/") and len(img) > 10000
