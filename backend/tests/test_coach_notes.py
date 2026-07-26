"""Unit tests for feature_coach_notes.coach_notes_for_prompt helper."""
import sys, os, importlib.util, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_fake_server = types.ModuleType("server")
_fake_server.api = types.SimpleNamespace(get=lambda *a, **k: (lambda f: f), put=lambda *a, **k: (lambda f: f))
_fake_server.db = None
_fake_server.require_role = lambda role: lambda: {"id": "coach"}
_fake_server.now_iso = lambda: "2026-07-26T00:00:00Z"
sys.modules["server"] = _fake_server

spec = importlib.util.spec_from_file_location(
    "_cn_test", os.path.join(os.path.dirname(__file__), "..", "feature_coach_notes.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_none_user_returns_none():
    assert mod.coach_notes_for_prompt(None) is None
    assert mod.coach_notes_for_prompt({}) is None


def test_all_empty_returns_none():
    u = {"coach_notes": {"preferences": "", "cautions": "", "goal_override": "",
                          "weekly_shape": "", "notes": ""}}
    assert mod.coach_notes_for_prompt(u) is None


def test_any_slot_populated_returns_payload():
    u = {"coach_notes": {"preferences": "Loves KBs", "cautions": "",
                          "goal_override": "", "weekly_shape": "", "notes": ""}}
    p = mod.coach_notes_for_prompt(u)
    assert p is not None
    assert p["preferences"] == "Loves KBs"
    assert p["cautions"] == ""


def test_whitespace_only_counts_as_empty():
    u = {"coach_notes": {"preferences": "   ", "cautions": "\n\t",
                          "goal_override": "", "weekly_shape": "", "notes": ""}}
    assert mod.coach_notes_for_prompt(u) is None


def test_carries_metadata():
    u = {"coach_notes": {"preferences": "X", "cautions": "", "goal_override": "",
                          "weekly_shape": "", "notes": "",
                          "updated_at": "2026-07-26T00:00Z", "updated_by_name": "Louis"}}
    p = mod.coach_notes_for_prompt(u)
    assert p["updated_by_name"] == "Louis"
    assert p["updated_at"] == "2026-07-26T00:00Z"


def test_pydantic_body_enforces_max_length():
    from pydantic import ValidationError
    long = "x" * (mod.MAX_SLOT_LEN + 10)
    try:
        mod.CoachNotesBody(preferences=long)
        assert False, "Should have raised"
    except ValidationError:
        pass


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
