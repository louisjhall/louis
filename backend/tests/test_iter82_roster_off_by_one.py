"""
Iter 82 — Roster off-by-one fix (Etihad DD/MM parsing).

Verifies `_align_days_to_weekday_labels`:
  * Shifts EVERY date by the mode offset when ≥50% of labelled rows disagree
  * Does NOT shift when the parsed dates align with the printed weekdays
  * Handles both +1 and -1 shifts
  * Ignores rows without day_of_week labels (e.g., legacy parsers)
"""
import sys
sys.path.insert(0, "/app/backend")

from server import _align_days_to_weekday_labels


def _mk_day(date: str, dow: str, day_type: str = "Home Day") -> dict:
    return {"date": date, "day_of_week": dow, "day_type": day_type}


def test_no_shift_when_all_aligned():
    """User's Etihad roster: Wed 01/07/2026 → parsed date = 2026-07-01
    which IS a Wednesday. Everything aligned → no shift."""
    days = [
        _mk_day("2026-07-01", "Wed"),
        _mk_day("2026-07-02", "Thu"),
        _mk_day("2026-07-03", "Fri"),
        _mk_day("2026-07-04", "Sat"),
        _mk_day("2026-07-05", "Sun"),
    ]
    result, shift, disagree = _align_days_to_weekday_labels(days)
    assert shift == 0
    assert disagree == 0
    # Dates unchanged
    assert result[0]["date"] == "2026-07-01"
    assert result[-1]["date"] == "2026-07-05"


def test_shifts_minus_one_day_when_parser_moved_forward():
    """Parser mistakenly emitted dates 1 day AHEAD. Labels say Wed/Thu/Fri but
    dates are Thu/Fri/Sat. Fix: shift ALL dates back by 1."""
    days = [
        _mk_day("2026-07-02", "Wed"),   # 07-02 is Thu → should be 07-01 (Wed)
        _mk_day("2026-07-03", "Thu"),   # 07-03 is Fri → should be 07-02 (Thu)
        _mk_day("2026-07-04", "Fri"),
        _mk_day("2026-07-05", "Sat"),
        _mk_day("2026-07-06", "Sun"),
    ]
    result, shift, disagree = _align_days_to_weekday_labels(days)
    assert shift == -1, f"Expected shift=-1 got {shift}"
    assert disagree == 5
    assert result[0]["date"] == "2026-07-01"
    assert result[1]["date"] == "2026-07-02"
    assert result[-1]["date"] == "2026-07-05"


def test_shifts_plus_one_day_when_parser_moved_backward():
    """Parser mistakenly emitted dates 1 day BEHIND. Labels say Wed/Thu but
    dates are Tue/Wed. Fix: shift ALL dates forward by 1."""
    days = [
        _mk_day("2026-06-30", "Wed"),   # 06-30 is Tue → should be 07-01
        _mk_day("2026-07-01", "Thu"),   # 07-01 is Wed → should be 07-02
        _mk_day("2026-07-02", "Fri"),
        _mk_day("2026-07-03", "Sat"),
        _mk_day("2026-07-04", "Sun"),
    ]
    result, shift, _ = _align_days_to_weekday_labels(days)
    assert shift == 1, f"Expected shift=+1 got {shift}"
    assert result[0]["date"] == "2026-07-01"
    assert result[-1]["date"] == "2026-07-05"


def test_ignores_rows_without_day_of_week():
    """Rows without a day_of_week label shouldn't skew the vote."""
    days = [
        _mk_day("2026-07-01", "Wed"),
        {"date": "2026-07-02"},              # no day_of_week
        _mk_day("2026-07-03", "Fri"),
        {"date": "2026-07-04"},
        _mk_day("2026-07-05", "Sun"),
    ]
    result, shift, disagree = _align_days_to_weekday_labels(days)
    assert shift == 0
    assert result[0]["date"] == "2026-07-01"


def test_single_stray_disagreement_does_not_trigger_shift():
    """One row with a wrong day_of_week label shouldn't shift the whole roster."""
    days = [
        _mk_day("2026-07-01", "Wed"),
        _mk_day("2026-07-02", "Thu"),
        _mk_day("2026-07-03", "Fri"),
        _mk_day("2026-07-04", "Sat"),
        _mk_day("2026-07-05", "Mon"),   # WRONG label — should be Sun
    ]
    result, shift, disagree = _align_days_to_weekday_labels(days)
    assert shift == 0, "Single stray label should NOT trigger a mass shift"
    assert disagree == 1
    # Dates unchanged
    assert result[0]["date"] == "2026-07-01"


def test_empty_days_returns_empty():
    result, shift, disagree = _align_days_to_weekday_labels([])
    assert shift == 0
    assert disagree == 0
    assert result == []


def test_full_etihad_roster_july_2026_stays_correct():
    """Fingerprint of the user's Etihad July 2026 roster — 31 days all aligned.
    Regression guard: this SHOULD NOT shift."""
    import datetime as _dt
    days = []
    for dom in range(1, 32):
        d = _dt.date(2026, 7, dom)
        dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d.weekday()]
        days.append(_mk_day(d.isoformat(), dow))
    result, shift, disagree = _align_days_to_weekday_labels(days)
    assert shift == 0
    assert disagree == 0
    # Wed 01/07/2026 stays Wed 01/07/2026
    assert result[0]["date"] == "2026-07-01"
    assert result[0]["day_of_week"] == "Wed"


def test_full_etihad_roster_shifted_forward_gets_corrected():
    """Same July 2026 roster, but parser shifted every date forward by 1.
    All 31 rows should be shifted back by 1."""
    import datetime as _dt
    days = []
    for dom in range(1, 32):
        real = _dt.date(2026, 7, dom)
        dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][real.weekday()]
        wrong_date = (real + _dt.timedelta(days=1)).isoformat()
        days.append(_mk_day(wrong_date, dow))
    result, shift, disagree = _align_days_to_weekday_labels(days)
    assert shift == -1
    assert disagree == 31
    # Every row corrected to the intended date
    for i, d in enumerate(result):
        assert d["date"] == _dt.date(2026, 7, i + 1).isoformat()
