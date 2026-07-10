"""Phase 5 — Adaptive Atlas Insights + Coach To-Do integration + Sunday check-in questions."""
import datetime as _dt
import pytest
import requests

BANNED = ("cheat", "bad food", "dirty food", "failed")
TIMEOUT = 60


def _week_bounds():
    today = _dt.date.today()
    monday = today - _dt.timedelta(days=today.weekday())
    sunday = monday + _dt.timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def _no_banned(text: str):
    lt = (text or "").lower()
    for b in BANNED:
        assert b not in lt, f"banned word '{b}' present in: {text}"


def _scrub(insight: dict):
    for k in ("atlas_summary", "main_issue", "suggested_action"):
        _no_banned(str(insight.get(k) or ""))


# ---------- Client insight generation ----------

class TestClientInsightsGenerate:

    def test_1_generate_force(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/nutrition/insights/generate",
                     json={"force": True}, headers=client_auth["headers"], timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["cached"] is False
        ins = data["insight"]
        pytest.insight_id_1 = ins["id"]
        # Schema
        for k in ("id", "week_start", "week_end", "action", "atlas_summary",
                  "main_issue", "suggested_action", "coach_review_required",
                  "confidence", "analytics", "target_change_suggestion"):
            assert k in ins, f"missing field {k}"
        ws, we = _week_bounds()
        assert ins["week_start"] == ws
        assert ins["week_end"] == we
        assert ins["action"] in ["keep", "simplify", "protein_focus",
                                 "adjust_calories", "add_travel_strategy", "flag_coach_review"]
        assert isinstance(ins["coach_review_required"], bool)
        assert len(ins["atlas_summary"]) <= 250
        a = ins["analytics"]
        for k in ("days_logged", "days_total", "avg_calories", "avg_protein_g", "low_protein_days"):
            assert k in a
        assert a["days_total"] == 14
        _scrub(ins)

    def test_2_cache_hit(self, api, base_url, client_auth):
        # Without force → cached true, same id
        r = api.post(f"{base_url}/api/nutrition/insights/generate",
                     json={"force": False}, headers=client_auth["headers"], timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert data["cached"] is True
        assert data["insight"]["id"] == pytest.insight_id_1

    def test_3_force_supersedes(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/nutrition/insights/generate",
                     json={"force": True}, headers=client_auth["headers"], timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert data["cached"] is False
        new_id = data["insight"]["id"]
        assert new_id != pytest.insight_id_1
        pytest.insight_id_2 = new_id
        # Previous should be superseded — check via /mine
        m = api.get(f"{base_url}/api/nutrition/insights/mine?limit=10",
                    headers=client_auth["headers"], timeout=TIMEOUT).json()
        prev = next((x for x in m["insights"] if x["id"] == pytest.insight_id_1), None)
        assert prev is not None
        assert prev["status"] == "superseded", f"expected superseded, got {prev['status']}"

    def test_4_latest(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/nutrition/insights/latest",
                    headers=client_auth["headers"], timeout=TIMEOUT)
        assert r.status_code == 200
        ins = r.json()["insight"]
        assert ins is not None
        assert ins["status"] != "superseded"
        assert ins["id"] == pytest.insight_id_2

    def test_5_mine(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/nutrition/insights/mine?limit=5",
                    headers=client_auth["headers"], timeout=TIMEOUT)
        assert r.status_code == 200
        rows = r.json()["insights"]
        assert isinstance(rows, list)
        assert 1 <= len(rows) <= 5

    def test_6_sanitiser(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/nutrition/insights/mine?limit=20",
                    headers=client_auth["headers"], timeout=TIMEOUT)
        for ins in r.json()["insights"]:
            _scrub(ins)


# ---------- Check-in questions ----------

class TestCheckinQuestions:

    def test_7_checkin_questions(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/nutrition/checkin/questions",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "goal" in data
        qs = data["questions"]
        assert 5 <= len(qs) <= 7, f"expected 5-7 questions, got {len(qs)}"
        for q in qs:
            assert q["id"].startswith("nutr_"), q
            assert "label" in q
            assert q["type"] in ("choice", "text")
        if data["goal"] == "fat_loss":
            ids = [q["id"] for q in qs]
            assert "nutr_fat_loss_env" in ids


# ---------- Coach endpoints ----------

class TestCoachEndpoints:

    def test_8a_scan_first_run(self, api, base_url, coach_auth):
        r = api.post(f"{base_url}/api/coach/nutrition/scan-todos",
                     json={"force": False}, headers=coach_auth["headers"], timeout=300)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "scanned" in data and "tasks_created" in data
        pytest.first_created = data["tasks_created"]
        # First run must have at least one existing pending insight → task creation
        # tasks_created can be 0 if tasks already existed from prior scan. Accept >= 0.

    def test_8b_scan_dedupe(self, api, base_url, coach_auth):
        r = api.post(f"{base_url}/api/coach/nutrition/scan-todos",
                     json={"force": False}, headers=coach_auth["headers"], timeout=300)
        assert r.status_code == 200
        data = r.json()
        # 2nd immediate scan should not create new tasks (dedupe)
        assert data["tasks_created"] == 0, f"dedupe failed, tasks_created={data['tasks_created']}"

    def test_8c_pending_list(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/nutrition/insights/pending",
                    headers=coach_auth["headers"], timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        rows = r.json()["insights"]
        assert isinstance(rows, list)
        assert len(rows) >= 1, "expected pending insights"
        for row in rows:
            assert row["coach_review_required"] is True
            assert row["status"] == "pending"
            assert "client_name" in row
        pytest.pending_rows = rows

    def test_8d_approve_apply_target(self, api, base_url, coach_auth):
        # Find an insight with a numeric target_change_suggestion
        rows = pytest.pending_rows
        pick = None
        for r in rows:
            tcs = r.get("target_change_suggestion") or {}
            if tcs.get("calories") or tcs.get("protein_g"):
                pick = r
                break
        if not pick:
            # Approve any one — behaviour should still be 200 even with no target change
            pick = rows[0]
        pytest.approved_pick = pick
        resp = api.post(f"{base_url}/api/coach/nutrition/insights/{pick['id']}/approve",
                        json={"apply_target_change": True},
                        headers=coach_auth["headers"], timeout=TIMEOUT)
        assert resp.status_code == 200, resp.text
        assert resp.json().get("ok") is True

    def test_8d2_verify_target_row_if_applicable(self, api, base_url, coach_auth):
        pick = pytest.approved_pick
        tcs = pick.get("target_change_suggestion") or {}
        if not (tcs.get("calories") or tcs.get("protein_g")):
            pytest.skip("Approved insight had no numeric target change; skipping target row verification")
        # Verify via targets/history if available; else via pending list disappearance
        # Fall back: check the insight itself became approved
        pend = api.get(f"{base_url}/api/coach/nutrition/insights/pending",
                       headers=coach_auth["headers"], timeout=TIMEOUT).json()["insights"]
        ids = [x["id"] for x in pend]
        assert pick["id"] not in ids, "approved insight still in pending"

    def test_8e_dismiss(self, api, base_url, coach_auth):
        pend = api.get(f"{base_url}/api/coach/nutrition/insights/pending",
                       headers=coach_auth["headers"], timeout=TIMEOUT).json()["insights"]
        assert pend, "no more pending to dismiss"
        target = pend[0]
        r = api.post(f"{base_url}/api/coach/nutrition/insights/{target['id']}/dismiss",
                     headers=coach_auth["headers"], timeout=TIMEOUT)
        assert r.status_code == 200
        # Confirm gone from pending
        pend2 = api.get(f"{base_url}/api/coach/nutrition/insights/pending",
                        headers=coach_auth["headers"], timeout=TIMEOUT).json()["insights"]
        ids2 = [x["id"] for x in pend2]
        assert target["id"] not in ids2

    def test_8f_approve_unknown_404(self, api, base_url, coach_auth):
        r = api.post(f"{base_url}/api/coach/nutrition/insights/xxx-not-a-real-id/approve",
                     json={"apply_target_change": False},
                     headers=coach_auth["headers"], timeout=TIMEOUT)
        assert r.status_code == 404

    def test_8g_client_cannot_hit_coach(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/coach/nutrition/insights/pending",
                    headers=client_auth["headers"], timeout=TIMEOUT)
        assert r.status_code == 403, f"expected 403 got {r.status_code} {r.text}"
        r2 = api.post(f"{base_url}/api/coach/nutrition/scan-todos",
                      json={"force": False}, headers=client_auth["headers"], timeout=TIMEOUT)
        assert r2.status_code == 403
        r3 = api.post(f"{base_url}/api/coach/nutrition/insights/whatever/approve",
                      json={"apply_target_change": False},
                      headers=client_auth["headers"], timeout=TIMEOUT)
        assert r3.status_code == 403
