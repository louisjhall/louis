"""
BA iOS-calendar roster adapter — focused tests.

Fixture 1: The August 2026 screenshot the coach provided.
  - 4 trips (MCO, SAN, MCO, MCO) + LEAVE from 28 Aug
  - Verifies deterministic extraction matches the coach's expectations.

Fixture 2: Emirates (EK) sample — must NOT be touched by BA adapter.

Fixture 3: RAK / easyJet-style — must NOT be touched.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feature_ba_roster_adapter import maybe_apply, detect_ba_calendar, parse_ba_calendar


def _mk_multi(dates: list[str], title: str, ends_time: str | None = None) -> list[dict]:
    """Simulate what an upstream extractor (Gemini/Claude Vision) would
    return for a multi-day trip bar in the iOS Calendar month view: one
    row per date the bar covers, with the same title text on every row,
    and the 'ends HH:MM' string attached to the last row."""
    out: list[dict] = []
    for i, d in enumerate(dates):
        row = {"date": d, "label": title}
        if i == len(dates) - 1 and ends_time:
            row["label"] = f"{title} · ends {ends_time}"
        out.append(row)
    return out


def _make_ba_fixture() -> list[dict]:
    """Rebuild the coach's Aug 2026 screenshot as structured input rows.
    The upstream extractor produces one row per calendar day the bar spans."""
    days: list[dict] = []
    # Trip 1: MCO — 6→9 Aug (Wed→Sun)
    days += _mk_multi(
        ["2026-08-06", "2026-08-07", "2026-08-08", "2026-08-09"],
        "MCO - Rpt:05:50z LHRx-MCO-LHR", ends_time="08:15",
    )
    # Trip 2: SAN — 12→15 Aug
    days += _mk_multi(
        ["2026-08-12", "2026-08-13", "2026-08-14", "2026-08-15"],
        "SAN - Rpt:12:00z LHRx-SAN-LHR", ends_time="14:50",
    )
    # Trip 3: MCO — 19→21 Aug
    days += _mk_multi(
        ["2026-08-19", "2026-08-20", "2026-08-21"],
        "MCO - Rpt:12:00z LGWx-MCO-LGWx", ends_time="11:10",
    )
    # Trip 4: MCO — 25→27 Aug
    days += _mk_multi(
        ["2026-08-25", "2026-08-26", "2026-08-27"],
        "MCO - Rpt:08:00z LGW-MCO-LGWx", ends_time="07:20",
    )
    # LEAVE block starting 28 Aug — iOS calendar duplicates via helpers
    for d in ["2026-08-28", "2026-08-29", "2026-08-30"]:
        days.append({"date": d, "label": "LEAVE"})
    # Extra helper label days that must dedupe into the same leave block
    days.append({"date": "2026-08-29", "label": "Leave (Wraps After)"})
    days.append({"date": "2026-08-30", "label": "Leave (Wraps After)"})
    # Sort by date to look like what upstream would produce
    days.sort(key=lambda r: r["date"])
    return days


def test_ba_detection_confident():
    days = _make_ba_fixture()
    detection = detect_ba_calendar(days)
    assert detection["confidence"] >= 0.6, detection
    assert detection["indicators"]["zulu_report_matches"] >= 4
    assert detection["indicators"]["ends_matches"] >= 4
    assert detection["indicators"]["ba_route_matches"] >= 4
    print(f"✓ BA detection confidence: {detection['confidence']}")


def test_ba_parse_expected_trips():
    days = _make_ba_fixture()
    res = maybe_apply(days)
    assert res["applied"], f"BA parser did not apply: {res.get('reason')}"

    trips = res["trips"]
    assert len(trips) == 4, f"expected 4 trips, got {len(trips)}"

    expected = [
        {
            "start_date": "2026-08-06", "end_date": "2026-08-09",
            "destination": "MCO", "report_time": "05:50",
            "end_display_time": "08:15",
            "raw_route": "LHRx-MCO-LHR",
        },
        {
            "start_date": "2026-08-12", "end_date": "2026-08-15",
            "destination": "SAN", "report_time": "12:00",
            "end_display_time": "14:50",
            "raw_route": "LHRx-SAN-LHR",
        },
        {
            "start_date": "2026-08-19", "end_date": "2026-08-21",
            "destination": "MCO", "report_time": "12:00",
            "end_display_time": "11:10",
            "raw_route": "LGWx-MCO-LGWx",
        },
        {
            "start_date": "2026-08-25", "end_date": "2026-08-27",
            "destination": "MCO", "report_time": "08:00",
            "end_display_time": "07:20",
            "raw_route": "LGW-MCO-LGWx",
        },
    ]
    for exp, got in zip(expected, trips):
        for k, v in exp.items():
            assert got.get(k) == v, f"trip {exp['destination']} field {k}: expected {v!r} got {got.get(k)!r}"
        # Timezone assertions
        assert got["report_time_timezone"] == "utc", f"trip must mark report as UTC: {got}"
        assert got["end_time_timezone"] == "unspecified_local", f"end must be unspecified_local: {got}"
        # No invented flight numbers / hotels
        assert got.get("notes")
    print("✓ 4 BA trips extracted with correct times, routes, and timezones")


def test_ba_parse_leave_dedupe():
    days = _make_ba_fixture()
    res = maybe_apply(days)
    assert res["applied"]
    leaves = res["leave_blocks"]
    assert len(leaves) == 1, f"expected 1 dedup'd leave block, got {len(leaves)}"
    assert leaves[0]["start_date"] == "2026-08-28"
    assert leaves[0]["end_date"] == "2026-08-30"
    # And in the rolled-out days, no duplicates
    leave_days = [d for d in res["days"] if d.get("day_type") == "Annual Leave"]
    assert len(leave_days) == 3, f"expected 3 leave day rows (Aug 28-30), got {len(leave_days)}"
    print("✓ LEAVE block deduplicated (start 28-Aug, 3 days, no overlaps)")


def test_ba_days_rollout():
    """Full rollout — each trip produces N per-day rows with correct
    flags (start day has report_time_utc; end day has release_time)."""
    days = _make_ba_fixture()
    res = maybe_apply(days)
    assert res["applied"]
    by_date = {d["date"]: d for d in res["days"]}
    # Trip 1
    d0 = by_date["2026-08-06"]
    assert d0["day_type"] == "flight"
    assert d0["report_time"] == "05:50"
    assert d0["report_time_timezone"] == "utc"
    assert d0["release_time"] is None
    assert d0["is_overnight"] is True
    assert d0["raw_route"] == "LHRx-MCO-LHR"
    assert d0["destination"] == "MCO"
    assert d0["flights"] == []
    d3 = by_date["2026-08-09"]
    assert d3["release_time"] == "08:15"
    assert d3["release_time_timezone"] == "unspecified_local"
    assert d3["is_layover_day"] is False
    d_mid = by_date["2026-08-07"]
    assert d_mid["is_layover_day"] is True
    assert d_mid["layover_city"] == "MCO"
    print("✓ Per-day rollout preserves timing + never invents flight numbers")


def test_ba_preserves_raw_route_x_char():
    days = _make_ba_fixture()
    res = maybe_apply(days)
    assert res["applied"]
    routes = {t["raw_route"] for t in res["trips"]}
    assert "LGW-MCO-LGWx" in routes, "trailing 'x' must be preserved"
    assert "LGWx-MCO-LGWx" in routes
    print("✓ Raw route preserved verbatim (including trailing 'x')")


def test_regression_emirates_untouched():
    """Emirates roster must NOT be BA-parsed. Signatures should score
    well below the 0.6 threshold and maybe_apply must return unchanged."""
    ek_days = [
        {"date": "2026-08-06", "label": "EK1  DXB-LHR  Pickup Time 22:30 DXB LT", "day_type": "flight"},
        {"date": "2026-08-07", "label": "EK2  LHR-DXB  Layover: London Hilton",   "day_type": "flight"},
        {"date": "2026-08-08", "label": "Rest Day",                                "day_type": "rest"},
    ]
    detection = detect_ba_calendar(ek_days)
    assert detection["confidence"] < 0.6, f"EK falsely flagged as BA: {detection}"
    res = maybe_apply(ek_days)
    assert res["applied"] is False
    assert res["days"] == ek_days, "EK days must pass through untouched"
    print(f"✓ Emirates regression untouched (confidence: {detection['confidence']})")


def test_regression_rak_untouched():
    """RAK Airways-style (no BA calendar signatures)."""
    rak_days = [
        {"date": "2026-08-06", "label": "RT101 RAK-CMN 08:00-10:00",  "day_type": "flight"},
        {"date": "2026-08-07", "label": "OFF",                        "day_type": "rest"},
        {"date": "2026-08-08", "label": "RT102 RAK-DXB 14:00-19:00",  "day_type": "flight"},
    ]
    detection = detect_ba_calendar(rak_days)
    assert detection["confidence"] < 0.6, f"RAK falsely flagged as BA: {detection}"
    res = maybe_apply(rak_days)
    assert res["applied"] is False
    assert res["days"] == rak_days
    print(f"✓ RAK regression untouched (confidence: {detection['confidence']})")


def test_regression_easyjet_untouched():
    ez_days = [
        {"date": "2026-08-06", "label": "U2 8321  LGW-AGP 06:00 STBY-AM", "day_type": "flight"},
        {"date": "2026-08-07", "label": "D/O",                             "day_type": "rest"},
    ]
    detection = detect_ba_calendar(ez_days)
    assert detection["confidence"] < 0.6
    res = maybe_apply(ez_days)
    assert res["applied"] is False
    print(f"✓ easyJet regression untouched (confidence: {detection['confidence']})")


def test_regression_qatar_untouched():
    qr_days = [
        {"date": "2026-08-06", "label": "QR15 DOH-LHR 07:45-13:20", "day_type": "flight"},
        {"date": "2026-08-07", "label": "REST",                     "day_type": "rest"},
    ]
    detection = detect_ba_calendar(qr_days)
    assert detection["confidence"] < 0.6
    res = maybe_apply(qr_days)
    assert res["applied"] is False
    print(f"✓ Qatar regression untouched (confidence: {detection['confidence']})")


def test_confidence_low_when_only_route_shape():
    """A random 'LHR-JFK-LHR' string alone must NOT trigger BA parsing."""
    days = [{"date": "2026-08-06", "label": "LHR-JFK-LHR delay", "day_type": "flight"}]
    detection = detect_ba_calendar(days)
    assert detection["confidence"] < 0.6, detection
    print(f"✓ Route alone does not trigger BA (confidence: {detection['confidence']})")


if __name__ == "__main__":
    tests = [
        test_ba_detection_confident,
        test_ba_parse_expected_trips,
        test_ba_parse_leave_dedupe,
        test_ba_days_rollout,
        test_ba_preserves_raw_route_x_char,
        test_regression_emirates_untouched,
        test_regression_rak_untouched,
        test_regression_easyjet_untouched,
        test_regression_qatar_untouched,
        test_confidence_low_when_only_route_shape,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"✗ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {t.__name__}: unexpected {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(0 if failed == 0 else 1)
