"""Coach Web Dashboard backend tests (V1.5+).

Covers:
- GET /api/coach/calendar?days=N   (7, 14 default, 28)  + 403 for client
- GET /api/coach/analytics?days=N  (7, 30 default, 90)  + 403 for client
- Regression: /coach/dashboard, /coach/pending-approvals, /coach/clients
- Regression: /auth/login, /roster/current
"""
import pytest


# ---------- /coach/calendar ----------
class TestCoachCalendar:
    def _validate_shape(self, d, expected_days):
        assert isinstance(d, dict)
        for k in ("dates", "clients", "start_date", "end_date"):
            assert k in d, f"missing key {k}"
        assert isinstance(d["dates"], list) and len(d["dates"]) == expected_days
        assert d["start_date"] == d["dates"][0]
        assert d["end_date"] == d["dates"][-1]
        assert isinstance(d["clients"], list)
        # at least one seeded client
        assert len(d["clients"]) >= 1
        c = d["clients"][0]
        for k in ("client_id", "client_name", "email", "days", "has_roster"):
            assert k in c, f"missing client key {k}"
        assert isinstance(c["days"], list) and len(c["days"]) == expected_days
        cell = c["days"][0]
        for k in ("date", "load", "duty_type", "workout_id", "title",
                  "completed", "key_session", "approved", "duration_min", "location"):
            assert k in cell, f"missing cell key {k}"
        assert cell["date"] == d["dates"][0]
        assert isinstance(cell["completed"], bool)
        assert isinstance(cell["key_session"], bool)
        assert isinstance(cell["approved"], bool)

    def test_default_14(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/calendar", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        self._validate_shape(r.json(), 14)

    def test_days_7(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/calendar?days=7", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        self._validate_shape(r.json(), 7)

    def test_days_28(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/calendar?days=28", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        self._validate_shape(r.json(), 28)

    def test_forbidden_for_client(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/coach/calendar", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 403

    def test_missing_auth_401(self, api, base_url):
        r = api.get(f"{base_url}/api/coach/calendar", timeout=15)
        assert r.status_code == 401

    def test_alex_present_and_dates_sequential(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/calendar?days=14", headers=coach_auth["headers"], timeout=30)
        d = r.json()
        # sequential dates (day n+1 == day n + 1 day)
        from datetime import datetime, timedelta
        for i in range(1, len(d["dates"])):
            a = datetime.fromisoformat(d["dates"][i - 1]).date()
            b = datetime.fromisoformat(d["dates"][i]).date()
            assert b - a == timedelta(days=1), f"non-sequential at {i}: {a}->{b}"
        # seeded alex present
        emails = [c["email"] for c in d["clients"]]
        assert "client@crewfit.com" in emails


# ---------- /coach/analytics ----------
class TestCoachAnalytics:
    def _validate_shape(self, d):
        for k in ("total_clients", "total_scheduled", "total_completed",
                  "global_compliance", "global_avg_rpe", "load_distribution", "clients",
                  "start_date", "end_date", "days"):
            assert k in d, f"missing key {k}"
        assert isinstance(d["total_clients"], int)
        assert isinstance(d["total_scheduled"], int)
        assert isinstance(d["total_completed"], int)
        assert isinstance(d["global_compliance"], int)
        assert 0 <= d["global_compliance"] <= 100
        assert d["global_avg_rpe"] is None or isinstance(d["global_avg_rpe"], (int, float))
        ld = d["load_distribution"]
        assert isinstance(ld, dict)
        for lo in ("green", "amber", "red", "blue", "purple", "grey"):
            assert lo in ld
            assert isinstance(ld[lo], int)
        assert isinstance(d["clients"], list)
        if d["clients"]:
            c = d["clients"][0]
            for k in ("client_id", "client_name", "scheduled", "completed",
                     "compliance", "avg_rpe", "loads",
                     "key_sessions_completed", "key_sessions_total"):
                assert k in c, f"missing client key {k}"
            assert 0 <= c["compliance"] <= 100

    def test_default_30(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/analytics", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["days"] == 30
        self._validate_shape(d)

    def test_days_7(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/analytics?days=7", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["days"] == 7
        self._validate_shape(d)

    def test_days_90(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/analytics?days=90", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["days"] == 90
        self._validate_shape(d)

    def test_forbidden_for_client(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/coach/analytics", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 403

    def test_missing_auth_401(self, api, base_url):
        r = api.get(f"{base_url}/api/coach/analytics", timeout=15)
        assert r.status_code == 401

    def test_sorted_by_compliance_desc(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/analytics?days=30", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200
        clients = r.json()["clients"]
        # per spec: sorted by compliance DESC
        comps = [c["compliance"] for c in clients]
        assert comps == sorted(comps, reverse=True), f"clients not sorted desc: {comps}"

    def test_totals_add_up(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/analytics?days=30", headers=coach_auth["headers"], timeout=30)
        d = r.json()
        sum_sched = sum(c["scheduled"] for c in d["clients"])
        sum_done = sum(c["completed"] for c in d["clients"])
        assert sum_sched == d["total_scheduled"]
        assert sum_done == d["total_completed"]


# ---------- Regression: existing coach endpoints ----------
class TestCoachRegression:
    def test_dashboard_still_ok(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/dashboard", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "clients" in d and "counts" in d and "total" in d

    def test_pending_approvals(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/pending-approvals", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        for w in rows:
            assert w.get("approved") is False
            assert "client_name" in w

    def test_pending_approvals_forbidden_for_client(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/coach/pending-approvals", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 403

    def test_clients(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/clients", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list) and len(rows) >= 1


# ---------- Regression: core auth/roster ----------
class TestCoreRegression:
    def test_login_client_ok(self, api, base_url):
        r = api.post(f"{base_url}/api/auth/login",
                     json={"email": "client@crewfit.com", "password": "Client123!"}, timeout=15)
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "client"

    def test_login_coach_ok(self, api, base_url):
        r = api.post(f"{base_url}/api/auth/login",
                     json={"email": "coach@crewfit.com", "password": "Coach123!"}, timeout=15)
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "coach"

    def test_roster_current(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/roster/current", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "id" in d and "days" in d and "expiry" in d
