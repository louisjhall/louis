"""Unit tests for programme_status helpers."""
import sys, os, importlib.util, types, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_fake_server = types.ModuleType("server")
_fake_server.api = types.SimpleNamespace(
    get=lambda *a, **k: (lambda f: f),
    post=lambda *a, **k: (lambda f: f),
)
_fake_server.db = None
_fake_server.require_role = lambda role: lambda: {"id": "coach"}
_fake_server.current_user = lambda: {"id": "u1"}
_fake_server.new_id = lambda: "id"
_fake_server.now_iso = lambda: "2026-07-26T00:00:00Z"
sys.modules["server"] = _fake_server

spec = importlib.util.spec_from_file_location(
    "_ps_test", os.path.join(os.path.dirname(__file__), "..", "feature_programme_status.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_approval_message_session_planned():
    m = mod._approval_message_for_today({"state": "session_planned"})
    assert "session planned today" in m
    assert "AI" not in m and "generated" not in m and "algorithm" not in m


def test_approval_message_rest_day():
    m = mod._approval_message_for_today({"state": "rest_day"})
    assert "rest day" in m
    assert "no training session" in m


def test_approval_message_recovery():
    m = mod._approval_message_for_today({"state": "recovery_planned"})
    assert "recovery-focused day" in m


def test_approval_message_travel():
    m = mod._approval_message_for_today({"state": "travel_day"})
    assert "flying schedule" in m


def test_approval_message_layover():
    m = mod._approval_message_for_today({"state": "layover_day"})
    assert "hotel/bodyweight" in m


def test_approval_message_no_session():
    m = mod._approval_message_for_today({"state": "no_session_planned"})
    assert "no session planned" in m.lower()


def test_all_messages_have_louis_signoff():
    for state in ["session_planned", "recovery_planned", "rest_day",
                  "travel_day", "layover_day", "nutrition_focus",
                  "habit_focus", "no_session_planned"]:
        m = mod._approval_message_for_today({"state": state})
        assert m.strip().endswith("Louis"), f"{state}: missing Louis signoff"


def test_no_ai_wording_in_any_message():
    for state in ["session_planned", "recovery_planned", "rest_day",
                  "travel_day", "layover_day", "nutrition_focus",
                  "habit_focus", "no_session_planned"]:
        m = mod._approval_message_for_today({"state": state}).lower()
        # Client-facing rule: no AI wording
        for banned in ("ai", "algorithm", "generated", "bot", "automated"):
            # Word-boundary check to avoid false-positive on words that
            # contain the substring (e.g. "matched to").
            assert f" {banned} " not in f" {m} ", f"{state}: '{banned}' found in message"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
