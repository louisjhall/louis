"""Unit tests for feature_roster_versions helpers."""
import sys, os, importlib.util, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub server
_fake_server = types.ModuleType("server")
_fake_server.api = types.SimpleNamespace(get=lambda *a, **k: (lambda f: f), post=lambda *a, **k: (lambda f: f))
_fake_server.db = None
_fake_server.require_role = lambda role: lambda: {"id": "coach"}
_fake_server.current_user = lambda: {"id": "u1"}
_fake_server.new_id = lambda: "id"
_fake_server.now_iso = lambda: "2026-07-26T00:00:00Z"
sys.modules["server"] = _fake_server

spec = importlib.util.spec_from_file_location(
    "_rv_test", os.path.join(os.path.dirname(__file__), "..", "feature_roster_versions.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_month_key():
    assert mod._month_key("2026-07-15") == "2026-07"
    assert mod._month_key("") == ""


def test_month_label():
    assert mod._month_label("2026-07") == "July 2026"


def test_fingerprint_day_equal_ignores_extra_fields():
    a = {"day_type": "flight", "training_colour": "red", "client_label": "X",
         "report_time": "10:00", "release_time": "18:00", "flights": []}
    b = {"day_type": "flight", "training_colour": "red", "client_label": "X",
         "report_time": "10:00", "release_time": "18:00", "flights": [],
         "notes": "extra", "confidence": 0.9}
    assert mod._fingerprint_day(a) == mod._fingerprint_day(b)


def test_fingerprint_day_differs_on_day_type():
    a = {"day_type": "layover_day", "training_colour": "amber"}
    b = {"day_type": "flight", "training_colour": "amber"}
    assert mod._fingerprint_day(a) != mod._fingerprint_day(b)


def test_diff_adds_removed_changed_unchanged():
    a = [
        {"date": "2026-07-01", "day_type": "off", "training_colour": "green"},
        {"date": "2026-07-02", "day_type": "flight", "training_colour": "red"},
        {"date": "2026-07-03", "day_type": "layover_day", "training_colour": "amber"},
    ]
    b = [
        {"date": "2026-07-01", "day_type": "off", "training_colour": "green"},   # unchanged
        {"date": "2026-07-02", "day_type": "standby", "training_colour": "amber"},  # changed
        # 2026-07-03 removed
        {"date": "2026-07-04", "day_type": "off", "training_colour": "green"},   # added
    ]
    d = mod._diff_two_rosters(a, b)
    assert len(d["added"]) == 1
    assert d["added"][0]["date"] == "2026-07-04"
    assert len(d["removed"]) == 1
    assert d["removed"][0]["date"] == "2026-07-03"
    assert len(d["changed"]) == 1
    assert d["changed"][0]["date"] == "2026-07-02"
    assert d["changed"][0]["prev"]["day_type"] == "flight"
    assert d["changed"][0]["new"]["day_type"] == "standby"
    assert d["unchanged_count"] == 1


def test_diff_respects_month_filter():
    a = [
        {"date": "2026-07-31", "day_type": "flight"},
        {"date": "2026-08-01", "day_type": "off"},
    ]
    b = [
        {"date": "2026-07-31", "day_type": "layover_day"},  # changed but in July
        {"date": "2026-08-01", "day_type": "flight"},         # changed but in August
    ]
    d = mod._diff_two_rosters(a, b, month_filter="2026-07")
    assert len(d["changed"]) == 1
    assert d["changed"][0]["date"] == "2026-07-31"
    assert d["total_dates"] == 1


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
