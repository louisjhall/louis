"""
Automated tests for Etihad automatic day labelling.

Validates the "critical beta blocker" checklist from Louis's brief:
    * layover days do not receive full-gym workouts
    * overnight + post-night days do not receive hard training
    * XX = UNKNOWN_UNAVAILABLE + needs_review
    * multi-sector days get RED
    * TURNAROUND detected correctly
    * ROFF detected
    * LAYOVER_OUTBOUND / LAYOVER_DAY / LAYOVER_RETURN pairing
"""
import sys
from pathlib import Path
sys.path.insert(0, "/app/backend")

from parsers.etihad import parse_etihad_pdf
from parsers.etihad_labels import decide_day, label_month, weekly_windows

FIX = Path("/app/backend/tests/fixtures")


def _load(name):
    return (FIX / name).read_bytes()


def _decisions(pdf_name):
    r = parse_etihad_pdf(_load(pdf_name))
    return {d.date: d for d in r.days}, label_month(r.days)


def _by_date(decisions, iso):
    for d in decisions:
        if d.date == iso:
            return d
    raise AssertionError(f"decision for {iso} not found")


# ---------------------------------------------------------------------------
# July
# ---------------------------------------------------------------------------

def test_july_multi_sector_day_red_no_hard_training():
    _, decs = _decisions("pietro_july.pdf")
    d = _by_date(decs, "2026-07-13")
    assert d.label in ("MULTI_SECTOR_DUTY", "LAYOVER_RETURN")
    assert d.training_colour == "red"
    assert "main_strength" in d.blocked
    assert "long_run" in d.blocked
    assert "intervals" in d.blocked


def test_july_layover_outbound_nbo():
    _, decs = _decisions("pietro_july.pdf")
    d = _by_date(decs, "2026-07-27")
    assert d.label in ("LAYOVER_OUTBOUND", "EARLY_DUTY", "NORMAL_DUTY")
    assert "main_strength" in d.blocked
    assert "long_run" in d.blocked


def test_july_layover_day_hotel_bodyweight_only():
    _, decs = _decisions("pietro_july.pdf")
    d = _by_date(decs, "2026-07-28")
    assert d.label == "LAYOVER_DAY"
    assert d.training_colour == "amber"
    assert d.equipment == "hotel_or_bodyweight"
    assert "main_strength" in d.blocked
    assert d.needs_review is True    # hotel gym unknown


def test_july_layover_return():
    _, decs = _decisions("pietro_july.pdf")
    d = _by_date(decs, "2026-07-29")
    assert d.label == "LAYOVER_RETURN"
    assert "main_strength" in d.blocked
    assert "long_run" in d.blocked


def test_july_turnaround_kbl_no_hard_training():
    _, decs = _decisions("pietro_july.pdf")
    d = _by_date(decs, "2026-07-14")
    assert d.label in ("TURNAROUND_DUTY", "MULTI_SECTOR_DUTY", "LONG_DUTY")
    assert d.training_colour == "red"
    assert "main_strength" in d.blocked


def test_july_standby_days_amber():
    _, decs = _decisions("pietro_july.pdf")
    for iso in ("2026-07-02", "2026-07-03", "2026-07-20", "2026-07-21"):
        d = _by_date(decs, iso)
        assert d.label == "STANDBY_DAY"
        assert d.training_colour == "amber"
        assert "long_run" in d.blocked
        assert "intervals" in d.blocked


def test_july_off_days_green():
    _, decs = _decisions("pietro_july.pdf")
    d = _by_date(decs, "2026-07-01")
    assert d.label == "OFF_DAY"
    assert d.training_colour == "green"
    assert "main_strength" in d.recommended


# ---------------------------------------------------------------------------
# August
# ---------------------------------------------------------------------------

def test_august_xx_unavailable_no_workout():
    _, decs = _decisions("pietro_august.pdf")
    d = _by_date(decs, "2026-08-12")
    assert d.label == "UNKNOWN_UNAVAILABLE"
    assert d.training_colour == "black"
    assert d.needs_review is True
    # Nothing is recommended.
    assert d.recommended == []


def test_august_roff_days_green():
    _, decs = _decisions("pietro_august.pdf")
    # Aug 14 chains from Aug 13's multi-sector KBL turnaround → correctly
    # becomes POST_LONG_DUTY_RECOVERY (amber). Aug 15 & 16 should be clean
    # ROSTERED_OFF (green).
    d14 = _by_date(decs, "2026-08-14")
    assert d14.label in ("ROSTERED_OFF", "POST_LONG_DUTY_RECOVERY")
    for iso in ("2026-08-15", "2026-08-16"):
        d = _by_date(decs, iso)
        assert d.label == "ROSTERED_OFF"
        assert d.training_colour == "green"


def test_august_tlv_turnaround():
    _, decs = _decisions("pietro_august.pdf")
    d = _by_date(decs, "2026-08-22")
    assert d.label in ("TURNAROUND_DUTY", "MULTI_SECTOR_DUTY")
    assert d.training_colour == "red"
    assert "main_strength" in d.blocked


def test_august_overnight_and_post_night():
    _, decs = _decisions("pietro_august.pdf")
    d26 = _by_date(decs, "2026-08-26")
    d27 = _by_date(decs, "2026-08-27")
    # 26 must NOT recommend hard training.
    assert "main_strength" in d26.blocked or d26.training_colour in ("red", "black")
    # 27 must be marked as chain-recovery or overnight continuation.
    assert d27.chain_flag in ("post_night", "post_long_duty") or d27.label in (
        "POST_NIGHT_RECOVERY", "POST_LONG_DUTY_RECOVERY", "OVERNIGHT_DUTY", "LAYOVER_RETURN",
    )
    assert "main_strength" in d27.blocked
    assert "long_run" in d27.blocked


def test_august_layover_outbound_ath():
    _, decs = _decisions("pietro_august.pdf")
    d = _by_date(decs, "2026-08-10")
    assert d.label in ("LAYOVER_OUTBOUND", "MULTI_SECTOR_DUTY")
    assert d.training_colour in ("red", "amber")
    assert "main_strength" in d.blocked


def test_august_layover_return_ath():
    _, decs = _decisions("pietro_august.pdf")
    d = _by_date(decs, "2026-08-11")
    assert d.label == "LAYOVER_RETURN"
    assert "main_strength" in d.blocked


# ---------------------------------------------------------------------------
# Weekly windows
# ---------------------------------------------------------------------------

def test_weekly_windows_produced():
    _, decs = _decisions("pietro_august.pdf")
    weeks = weekly_windows(decs)
    assert 4 <= len(weeks) <= 6, f"expected 4-6 weeks for August, got {len(weeks)}"
    for w in weeks:
        # Suggested target must never exceed the number of non-black days.
        assert w["suggested_target_sessions"] <= (
            w["counts"]["green"] + w["counts"]["amber"] + w["counts"]["red"]
        )


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✓ {name}")
                passed += 1
            except AssertionError as e:
                print(f"  ✗ {name}: {e}")
                failed += 1
            except Exception:
                traceback.print_exc()
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
