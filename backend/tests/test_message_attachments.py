"""End-to-end tests for CrewFit message attachments feature (iter-47).

Covers:
  - Upload happy paths (image/voice/video)
  - Hydration on send + read
  - Access control (sender, coach recipient, third-party, unauth)
  - Size / type / duration guard-rails
  - Max 5 images per message
  - Delete pre-send vs post-send
  - Regressions: text-only messages + client.coach_id sanity
"""
import io
import os
import struct
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PASS = "Client123!"
LOUIS_EMAIL = "louis@crewfit.net"
LOUIS_PASS = "Louis123!"
LEGACY_COACH_EMAIL = "coach@crewfit.com"
LEGACY_COACH_PASS = "Coach123!"


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------
def _login(email: str, password: str) -> dict:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    assert "token" in data and "user" in data
    return data


@pytest.fixture(scope="module")
def client_sess():
    d = _login(CLIENT_EMAIL, CLIENT_PASS)
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {d['token']}"})
    s.user = d["user"]  # type: ignore
    return s


@pytest.fixture(scope="module")
def louis_sess():
    d = _login(LOUIS_EMAIL, LOUIS_PASS)
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {d['token']}"})
    s.user = d["user"]  # type: ignore
    return s


@pytest.fixture(scope="module")
def legacy_coach_sess():
    d = _login(LEGACY_COACH_EMAIL, LEGACY_COACH_PASS)
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {d['token']}"})
    s.user = d["user"]  # type: ignore
    return s


def _make_tiny_jpeg() -> bytes:
    try:
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (1, 1), (255, 0, 0)).save(buf, format="JPEG")
        return buf.getvalue()
    except Exception:
        # Fallback: a canonical minimal JPEG SOI+APP0+EOI-ish blob (may not decode but has jpeg mime bytes).
        return bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")


_TINY_JPEG = _make_tiny_jpeg()


def _upload(sess, kind: str, data: bytes, mime: str, filename: str, duration=None):
    files = {"file": (filename, data, mime)}
    payload = {"kind": kind}
    if duration is not None:
        payload["duration_seconds"] = str(duration)
    return sess.post(f"{API}/messages/attachments", files=files, data=payload, timeout=30)


# ---------------------------------------------------------------------------
# 0. Health / identity regression
# ---------------------------------------------------------------------------
def test_regression_client_has_louis_as_coach(client_sess, louis_sess):
    r = client_sess.get(f"{API}/messages", timeout=10)
    assert r.status_code == 200
    partners = r.json()
    assert isinstance(partners, list) and partners, "client should see at least one message partner (Louis)"
    # If client has a coach_id, it must be Louis's id.
    louis_id = louis_sess.user["id"]  # type: ignore
    ids = [p.get("id") for p in partners]
    assert louis_id in ids, f"Louis {louis_id} not in client partners: {ids}"
    assert louis_sess.user["email"].lower() == LOUIS_EMAIL  # type: ignore


# ---------------------------------------------------------------------------
# 1. Happy path — image upload
# ---------------------------------------------------------------------------
def test_01_upload_image_happy(client_sess):
    r = _upload(client_sess, "image", _TINY_JPEG, "image/jpeg", "TEST_1x1.jpg")
    assert r.status_code == 200, f"upload image failed: {r.status_code} {r.text[:300]}"
    doc = r.json()
    assert doc["type"] == "image"
    assert doc["status"] == "uploaded"
    assert doc.get("url"), "url must be present"
    assert doc.get("id")
    assert doc.get("mime_type") == "image/jpeg"
    pytest.att_image_id = doc["id"]  # type: ignore


# ---------------------------------------------------------------------------
# 2. Send message with attachment
# ---------------------------------------------------------------------------
def test_02_send_message_with_attachment(client_sess, louis_sess):
    att_id = pytest.att_image_id  # type: ignore
    louis_id = louis_sess.user["id"]  # type: ignore
    r = client_sess.post(f"{API}/messages", json={
        "to_user_id": louis_id,
        "text": "TEST_Form check",
        "attachment_ids": [att_id],
    }, timeout=15)
    assert r.status_code == 200, f"send failed: {r.status_code} {r.text[:300]}"
    doc = r.json()
    assert isinstance(doc.get("attachments"), list) and len(doc["attachments"]) == 1
    att = doc["attachments"][0]
    assert att["id"] == att_id
    assert att["type"] == "image"
    assert att.get("url")
    pytest.msg_id = doc["id"]  # type: ignore


# ---------------------------------------------------------------------------
# 3. Hydration on thread read
# ---------------------------------------------------------------------------
def test_03_hydration_on_read(client_sess, louis_sess):
    louis_id = louis_sess.user["id"]  # type: ignore
    r = client_sess.get(f"{API}/messages/{louis_id}", timeout=15)
    assert r.status_code == 200
    rows = r.json()
    target = next((m for m in rows if m.get("id") == pytest.msg_id), None)  # type: ignore
    assert target is not None, "sent message not found in thread"
    assert isinstance(target.get("attachments"), list) and len(target["attachments"]) == 1
    a = target["attachments"][0]
    assert a["id"] == pytest.att_image_id and a["type"] == "image" and a.get("url")  # type: ignore


# ---------------------------------------------------------------------------
# 4. Louis (recipient coach) can access
# ---------------------------------------------------------------------------
def test_04_louis_can_access(louis_sess):
    att_id = pytest.att_image_id  # type: ignore
    r = louis_sess.get(f"{API}/messages/attachments/{att_id}/file", timeout=15)
    assert r.status_code == 200, f"louis file GET: {r.status_code} {r.text[:200]}"
    assert r.headers.get("content-type", "").startswith("image/jpeg")
    r2 = louis_sess.get(f"{API}/messages/attachments/{att_id}", timeout=10)
    assert r2.status_code == 200
    assert r2.json().get("id") == att_id


# ---------------------------------------------------------------------------
# 5. Third-party cannot access
# ---------------------------------------------------------------------------
def test_05_third_party_forbidden(legacy_coach_sess):
    att_id = pytest.att_image_id  # type: ignore
    r = legacy_coach_sess.get(f"{API}/messages/attachments/{att_id}/file", timeout=10)
    # Legacy coach is a coach role → per _may_access, they need to be sender/recipient of the referencing message.
    assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:200]}"


# ---------------------------------------------------------------------------
# 6. Unauth cannot access
# ---------------------------------------------------------------------------
def test_06_unauth_forbidden():
    att_id = pytest.att_image_id  # type: ignore
    r = requests.get(f"{API}/messages/attachments/{att_id}/file", timeout=10)
    assert r.status_code == 401, f"expected 401, got {r.status_code}"


# ---------------------------------------------------------------------------
# 7. Voice happy path
# ---------------------------------------------------------------------------
def test_07_voice_upload_and_send(client_sess, louis_sess):
    voice_bytes = b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 32  # tiny fake m4a
    r = _upload(client_sess, "voice", voice_bytes, "audio/m4a", "TEST_note.m4a", duration=12)
    assert r.status_code == 200, f"voice upload: {r.status_code} {r.text[:300]}"
    v = r.json()
    assert v["type"] == "voice" and v.get("url")
    # send
    louis_id = louis_sess.user["id"]  # type: ignore
    r2 = client_sess.post(f"{API}/messages", json={
        "to_user_id": louis_id, "text": "TEST_voice", "attachment_ids": [v["id"]],
    }, timeout=15)
    assert r2.status_code == 200
    doc = r2.json()
    assert len(doc["attachments"]) == 1
    assert doc["attachments"][0]["type"] == "voice"


# ---------------------------------------------------------------------------
# 8. Video happy path
# ---------------------------------------------------------------------------
def test_08_video_upload_and_send(client_sess, louis_sess):
    video_bytes = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 40
    r = _upload(client_sess, "video", video_bytes, "video/mp4", "TEST_clip.mp4", duration=8)
    assert r.status_code == 200, f"video upload: {r.status_code} {r.text[:300]}"
    v = r.json()
    assert v["type"] == "video" and v.get("url")
    louis_id = louis_sess.user["id"]  # type: ignore
    r2 = client_sess.post(f"{API}/messages", json={
        "to_user_id": louis_id, "text": "TEST_video", "attachment_ids": [v["id"]],
    }, timeout=15)
    assert r2.status_code == 200
    doc = r2.json()
    assert doc["attachments"][0]["type"] == "video"


# ---------------------------------------------------------------------------
# 9. Size guard — > 10 MB image
# ---------------------------------------------------------------------------
def test_09_size_guard_image(client_sess):
    big = _TINY_JPEG + b"\x00" * (10 * 1024 * 1024 + 100)
    r = _upload(client_sess, "image", big, "image/jpeg", "TEST_big.jpg")
    assert r.status_code == 413, f"expected 413, got {r.status_code}: {r.text[:200]}"
    body = r.json()
    err = body.get("detail", {}).get("error") if isinstance(body.get("detail"), dict) else body.get("error")
    assert err == "file_too_large", f"unexpected err payload: {body}"


# ---------------------------------------------------------------------------
# 10. Type guard — image kind, text mime
# ---------------------------------------------------------------------------
def test_10_type_guard(client_sess):
    r = _upload(client_sess, "image", b"hello world", "text/plain", "TEST_note.txt")
    assert r.status_code == 415, f"expected 415, got {r.status_code}: {r.text[:200]}"
    body = r.json()
    err = body.get("detail", {}).get("error") if isinstance(body.get("detail"), dict) else body.get("error")
    assert err == "unsupported_type", f"unexpected err payload: {body}"


# ---------------------------------------------------------------------------
# 11. Video length guard
# ---------------------------------------------------------------------------
def test_11_video_too_long(client_sess):
    video_bytes = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 40
    r = _upload(client_sess, "video", video_bytes, "video/mp4", "TEST_long.mp4", duration=200)
    assert r.status_code == 413, f"expected 413, got {r.status_code}: {r.text[:200]}"
    body = r.json()
    err = body.get("detail", {}).get("error") if isinstance(body.get("detail"), dict) else body.get("error")
    assert err == "video_too_long", f"unexpected err payload: {body}"


# ---------------------------------------------------------------------------
# 12. Voice length guard
# ---------------------------------------------------------------------------
def test_12_voice_too_long(client_sess):
    voice_bytes = b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 32
    r = _upload(client_sess, "voice", voice_bytes, "audio/m4a", "TEST_long.m4a", duration=600)
    assert r.status_code == 413, f"expected 413, got {r.status_code}: {r.text[:200]}"
    body = r.json()
    err = body.get("detail", {}).get("error") if isinstance(body.get("detail"), dict) else body.get("error")
    assert err == "voice_too_long", f"unexpected err payload: {body}"


# ---------------------------------------------------------------------------
# 13. Max 5 images per message (upload 6, send fails with too_many_images)
# ---------------------------------------------------------------------------
def test_13_max_5_images(client_sess, louis_sess):
    ids = []
    for i in range(6):
        r = _upload(client_sess, "image", _TINY_JPEG, "image/jpeg", f"TEST_multi_{i}.jpg")
        assert r.status_code == 200, f"multi upload {i} failed: {r.status_code} {r.text[:200]}"
        ids.append(r.json()["id"])
    louis_id = louis_sess.user["id"]  # type: ignore
    r = client_sess.post(f"{API}/messages", json={
        "to_user_id": louis_id, "text": "TEST_6imgs", "attachment_ids": ids,
    }, timeout=15)
    # server rejects at either 6-check (413 too_many_attachments) or 5-image cap (413 too_many_images)
    assert r.status_code == 413, f"expected 413, got {r.status_code}: {r.text[:200]}"
    body = r.json()
    err = body.get("detail", {}).get("error") if isinstance(body.get("detail"), dict) else body.get("error")
    assert err in ("too_many_images", "too_many_attachments"), f"unexpected err payload: {body}"


# ---------------------------------------------------------------------------
# 14. Delete pre-send works, referencing yields bad_attachment
# ---------------------------------------------------------------------------
def test_14_delete_pre_send(client_sess, louis_sess):
    r = _upload(client_sess, "image", _TINY_JPEG, "image/jpeg", "TEST_to_delete.jpg")
    assert r.status_code == 200
    aid = r.json()["id"]
    # delete
    d = client_sess.delete(f"{API}/messages/attachments/{aid}", timeout=10)
    assert d.status_code == 200, f"delete: {d.status_code} {d.text[:200]}"
    # try to reference in a message
    louis_id = louis_sess.user["id"]  # type: ignore
    s = client_sess.post(f"{API}/messages", json={
        "to_user_id": louis_id, "text": "TEST_afterdel", "attachment_ids": [aid],
    }, timeout=10)
    assert s.status_code == 400, f"expected 400 bad_attachment, got {s.status_code}: {s.text[:200]}"
    body = s.json()
    err = body.get("detail", {}).get("error") if isinstance(body.get("detail"), dict) else body.get("error")
    assert err == "bad_attachment", f"unexpected err payload: {body}"


# ---------------------------------------------------------------------------
# 15. Delete after send blocked (409)
# ---------------------------------------------------------------------------
def test_15_delete_after_send_blocked(client_sess, louis_sess):
    r = _upload(client_sess, "image", _TINY_JPEG, "image/jpeg", "TEST_after_send.jpg")
    assert r.status_code == 200
    aid = r.json()["id"]
    louis_id = louis_sess.user["id"]  # type: ignore
    s = client_sess.post(f"{API}/messages", json={
        "to_user_id": louis_id, "text": "TEST_send_then_del", "attachment_ids": [aid],
    }, timeout=10)
    assert s.status_code == 200
    d = client_sess.delete(f"{API}/messages/attachments/{aid}", timeout=10)
    assert d.status_code == 409, f"expected 409 already sent, got {d.status_code}: {d.text[:200]}"


# ---------------------------------------------------------------------------
# 17. Regression — text only message still works
# ---------------------------------------------------------------------------
def test_17_regression_text_only(client_sess, louis_sess):
    louis_id = louis_sess.user["id"]  # type: ignore
    r = client_sess.post(f"{API}/messages", json={
        "to_user_id": louis_id, "text": "TEST_text_only",
    }, timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d.get("text") == "TEST_text_only"
    assert d.get("attachment_ids", []) == []


# ---------------------------------------------------------------------------
# 18. Regression — louis identity + coach_id sanity
# ---------------------------------------------------------------------------
def test_18_regression_louis_identity(louis_sess, client_sess):
    lu = louis_sess.user  # type: ignore
    assert lu["email"].lower() == LOUIS_EMAIL
    assert lu["role"] == "coach"
    # client's /auth/me should show coach_id = louis
    me = client_sess.get(f"{API}/auth/me", timeout=10)
    if me.status_code == 200:
        assert me.json().get("coach_id") == lu["id"], f"client's coach_id != louis: {me.json().get('coach_id')} vs {lu['id']}"
