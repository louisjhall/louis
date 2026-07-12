"""Iter-46: Louis Hall primary coach identity - end-to-end backend verification."""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")

LOUIS_EMAIL = "louis@crewfit.net"
LOUIS_PASSWORD = "Louis123!"
CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PASSWORD = "Client123!"
LEGACY_COACH_EMAIL = "coach@crewfit.com"
LEGACY_COACH_PASSWORD = "Coach123!"


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(api, email, password):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    return r


# Step 1: Public /api/coach/profile/main
def test_1_coach_profile_main_public():
    r = requests.get(f"{BASE_URL}/api/coach/profile/main", timeout=15)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("email") == LOUIS_EMAIL, f"email mismatch: {data.get('email')}"
    assert data.get("name") == "Louis Hall", f"name mismatch: {data.get('name')}"
    assert data.get("display_name") == "Louis", f"display_name mismatch: {data.get('display_name')}"
    assert data.get("initials") == "LH", f"initials mismatch: {data.get('initials')}"
    title = data.get("title", "")
    assert "Founder" in title, f"title should mention 'Founder': {title}"
    avatar = data.get("avatar_url", "")
    assert avatar.startswith("https://customer-assets.emergentagent.com/"), (
        f"avatar_url should start with https://customer-assets.emergentagent.com/: {avatar}"
    )


# Step 2: Login as Louis
def test_2_login_louis(api):
    r = _login(api, LOUIS_EMAIL, LOUIS_PASSWORD)
    assert r.status_code == 200, f"Louis login failed: {r.status_code} {r.text}"
    body = r.json()
    assert "token" in body or "access_token" in body, f"No token: {body}"
    user = body.get("user", {})
    assert user.get("role") == "coach", f"role: {user.get('role')}"
    assert user.get("name") == "Louis Hall", f"name: {user.get('name')}"
    assert user.get("is_admin") is True, f"is_admin: {user.get('is_admin')}"
    assert user.get("is_primary_coach") is True, f"is_primary_coach: {user.get('is_primary_coach')}"


# Step 3: Client login and GET /api/messages should show Louis (not legacy coach)
def test_3_client_messages_partner_is_louis():
    api = requests.Session()
    api.headers.update({"Content-Type": "application/json"})
    r = _login(api, CLIENT_EMAIL, CLIENT_PASSWORD)
    assert r.status_code == 200, f"Client login failed: {r.status_code} {r.text}"
    body = r.json()
    token = body.get("token") or body.get("access_token")
    client_id = body["user"]["id"]
    api.headers["Authorization"] = f"Bearer {token}"

    r = api.get(f"{BASE_URL}/api/messages")
    assert r.status_code == 200, f"GET /api/messages failed: {r.status_code} {r.text}"
    partners = r.json()
    # Response may be a list of partners or a dict with a list
    if isinstance(partners, dict):
        partners = partners.get("partners") or partners.get("items") or partners.get("data") or []
    assert isinstance(partners, list), f"partners not a list: {partners}"
    coach_partners = [p for p in partners if p.get("role") == "coach" or p.get("email", "").endswith("@crewfit.net") or p.get("email", "").endswith("@crewfit.com")]
    # There should be exactly one coach partner and it should be Louis
    assert len(coach_partners) >= 1, f"No coach partner: {partners}"
    louis = None
    for p in coach_partners:
        if p.get("email") == LOUIS_EMAIL:
            louis = p
            break
    assert louis is not None, f"Louis not in partner list: {coach_partners}"
    assert louis.get("name") == "Louis Hall", f"Partner name: {louis.get('name')}"
    # Verify NO legacy coach appears
    legacy_partners = [p for p in partners if p.get("email") == LEGACY_COACH_EMAIL]
    assert len(legacy_partners) == 0, f"Legacy coach still in partner list: {legacy_partners}"

    # Persist Louis id + client id for downstream tests via module-level state file
    import json, tempfile
    with open("/tmp/iter46_ctx.json", "w") as f:
        json.dump({"louis_id": louis.get("id") or louis.get("user_id") or louis.get("_id"),
                   "client_id": client_id,
                   "client_token": token}, f)


# Step 4: Client sends message to Louis
def test_4_client_sends_message_to_louis():
    import json
    with open("/tmp/iter46_ctx.json") as f:
        ctx = json.load(f)
    louis_id = ctx["louis_id"]
    client_id = ctx["client_id"]
    client_token = ctx["client_token"]

    assert louis_id, "louis_id missing from partner list"

    api = requests.Session()
    api.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {client_token}"})

    r = api.post(f"{BASE_URL}/api/messages", json={
        "to_user_id": louis_id,
        "text": "Hi Louis, this is a test."
    })
    assert r.status_code == 200, f"Send message failed: {r.status_code} {r.text}"
    doc = r.json()
    assert doc.get("from_user_id") == client_id, f"from_user_id: {doc.get('from_user_id')} vs {client_id}"
    assert doc.get("to_user_id") == louis_id, f"to_user_id: {doc.get('to_user_id')} vs {louis_id}"


# Step 5: Login as Louis, list partners -> Alex Rivera / client id; then GET conversation
def test_5_louis_lists_messages_and_conversation():
    import json
    with open("/tmp/iter46_ctx.json") as f:
        ctx = json.load(f)
    client_id = ctx["client_id"]

    api = requests.Session()
    api.headers.update({"Content-Type": "application/json"})
    r = _login(api, LOUIS_EMAIL, LOUIS_PASSWORD)
    assert r.status_code == 200
    body = r.json()
    louis_token = body.get("token") or body.get("access_token")
    louis_id = body["user"]["id"]
    api.headers["Authorization"] = f"Bearer {louis_token}"

    r = api.get(f"{BASE_URL}/api/messages")
    assert r.status_code == 200, f"Louis /messages failed: {r.status_code} {r.text}"
    partners = r.json()
    if isinstance(partners, dict):
        partners = partners.get("partners") or partners.get("items") or partners.get("data") or []
    assert isinstance(partners, list)
    ids = [p.get("id") or p.get("user_id") or p.get("_id") for p in partners]
    assert client_id in ids, f"Client id {client_id} not in Louis's partner list: {partners}"

    # GET conversation with client
    r = api.get(f"{BASE_URL}/api/messages/{client_id}")
    assert r.status_code == 200, f"GET /api/messages/{{client_id}} failed: {r.status_code} {r.text}"
    convo = r.json()
    if isinstance(convo, dict):
        convo = convo.get("messages") or convo.get("items") or convo.get("data") or []
    assert isinstance(convo, list) and len(convo) >= 1
    texts = [m.get("text") for m in convo]
    assert "Hi Louis, this is a test." in texts, f"Test message not found: {texts}"

    # Persist Louis token+id for step 6
    ctx["louis_id_verified"] = louis_id
    ctx["louis_token"] = louis_token
    with open("/tmp/iter46_ctx.json", "w") as f:
        json.dump(ctx, f)


# Step 6: Louis replies to client
def test_6_louis_replies_to_client():
    import json
    with open("/tmp/iter46_ctx.json") as f:
        ctx = json.load(f)
    client_id = ctx["client_id"]
    louis_token = ctx["louis_token"]

    api = requests.Session()
    api.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {louis_token}"})
    r = api.post(f"{BASE_URL}/api/messages", json={
        "to_user_id": client_id,
        "text": "Thanks - welcome to CrewFit!"
    })
    assert r.status_code == 200, f"Louis reply failed: {r.status_code} {r.text}"


# Step 7: Backward compat - legacy coach can still log in
def test_7_legacy_coach_login_still_works():
    api = requests.Session()
    api.headers.update({"Content-Type": "application/json"})
    r = _login(api, LEGACY_COACH_EMAIL, LEGACY_COACH_PASSWORD)
    assert r.status_code == 200, f"Legacy coach login failed: {r.status_code} {r.text}"
    body = r.json()
    user = body.get("user", {})
    assert user.get("role") == "coach"
    # Should NOT be primary
    assert user.get("is_primary_coach") in (False, None), f"legacy is_primary_coach: {user.get('is_primary_coach')}"


# Step 8: Regression sanity - beta status + gdpr export for client
def test_8_regression_beta_status_and_gdpr_export():
    api = requests.Session()
    api.headers.update({"Content-Type": "application/json"})
    r = _login(api, CLIENT_EMAIL, CLIENT_PASSWORD)
    assert r.status_code == 200
    token = r.json().get("token") or r.json().get("access_token")
    api.headers["Authorization"] = f"Bearer {token}"

    r = api.get(f"{BASE_URL}/api/beta/status")
    assert r.status_code == 200, f"beta/status: {r.status_code} {r.text}"

    r = api.get(f"{BASE_URL}/api/gdpr/export")
    assert r.status_code == 200, f"gdpr/export: {r.status_code} {r.text}"
