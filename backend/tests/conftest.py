import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(api, base_url, email, password):
    r = api.post(f"{base_url}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    data = r.json()
    return data["token"], data["user"]


@pytest.fixture(scope="session")
def client_auth(api, base_url):
    token, user = _login(api, base_url, "client@crewfit.com", "Client123!")
    return {"token": token, "user": user, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture(scope="session")
def coach_auth(api, base_url):
    token, user = _login(api, base_url, "coach@crewfit.com", "Coach123!")
    return {"token": token, "user": user, "headers": {"Authorization": f"Bearer {token}"}}
