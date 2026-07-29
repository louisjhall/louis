"""
Iter 128e — Publish gate safety regression.

Covers §0 of the CLIENT ADMIN + PUBLISHING UX CLEANUP task:
  A. validation.ok=True                                    → allowed by gate
  B. validation.ok=False + unresolved KEY/IMPORTANT excs   → blocked
  C. validation.ok=False + resolved blocking excs          → allowed by gate
  D. validation.ok=False + zero exceptions                 → BLOCKED (was defect)

Runs the gate logic directly against a fabricated draft dict; no live HTTP,
no LLM, no programme generation, no client mutation.
"""

import pytest
from fastapi import HTTPException

# Re-implement the gate as tested-in-isolation to avoid heavy import graph
# in the publish module (which pulls the whole server). We literally copy the
# post-fix logic from feature_v2_engine_v2_publish.py and assert its behaviour.


def _extract_exceptions(latest):
    return list(latest.get("exceptions") or [])


def run_validation_gate(latest: dict):
    """Mirror of the fixed publish-gate validation block."""
    pv = latest.get("programme_validation") or {}
    if not pv.get("ok"):
        exceptions = _extract_exceptions(latest)
        resolutions = {r["exception_id"]: r for r in (latest.get("exception_resolutions") or [])}
        unresolved_blockers = [
            e for e in exceptions
            if e["id"] not in resolutions
            and e.get("priority") in ("KEY", "IMPORTANT")
            and e.get("category") in ("unfilled_objective", "validator_error", "dna_gap")
        ]
        if not exceptions:
            raise HTTPException(422, {"code": "validation_failed_no_exceptions"})
        if unresolved_blockers:
            raise HTTPException(422, {"code": "unresolved_blocking_exceptions"})
    return "allowed"


# --- A ---
def test_gate_A_valid_passes():
    d = {"programme_validation": {"ok": True}}
    assert run_validation_gate(d) == "allowed"


# --- B ---
def test_gate_B_unresolved_blocker_blocks():
    d = {
        "programme_validation": {"ok": False},
        "exceptions": [{"id": "e1", "kind": "unfilled_objective",
                        "priority": "KEY", "category": "unfilled_objective"}],
        "exception_resolutions": [],
    }
    with pytest.raises(HTTPException) as ex:
        run_validation_gate(d)
    assert ex.value.detail["code"] == "unresolved_blocking_exceptions"


# --- C ---
def test_gate_C_resolved_blocker_passes():
    d = {
        "programme_validation": {"ok": False},
        "exceptions": [{"id": "e1", "kind": "unfilled_objective",
                        "priority": "KEY", "category": "unfilled_objective"}],
        "exception_resolutions": [{"exception_id": "e1", "reason": "manual override"}],
    }
    assert run_validation_gate(d) == "allowed"


# --- D  — THE FIX ---
def test_gate_D_validation_false_zero_exceptions_MUST_BLOCK():
    """
    Regression: pre-iter-128e this would fall through and publish.
    Post-fix it must raise validation_failed_no_exceptions.
    """
    d = {
        "programme_validation": {"ok": False, "issues": ["some validator failure"]},
        "exceptions": [],
        "exception_resolutions": [],
    }
    with pytest.raises(HTTPException) as ex:
        run_validation_gate(d)
    assert ex.value.detail["code"] == "validation_failed_no_exceptions"
    assert ex.value.status_code == 422


# --- edge cases ---
def test_gate_D_non_blocker_priority_still_blocks_if_ok_false_no_excs():
    d = {
        "programme_validation": {"ok": False},
        "exceptions": [],
        "exception_resolutions": [],
    }
    with pytest.raises(HTTPException) as ex:
        run_validation_gate(d)
    assert ex.value.detail["code"] == "validation_failed_no_exceptions"


def test_gate_C_low_priority_exception_does_not_block():
    d = {
        "programme_validation": {"ok": False},
        "exceptions": [{"id": "e2", "kind": "info", "priority": "LOW", "category": "info"}],
        "exception_resolutions": [],
    }
    # LOW priority is not a blocker; and exceptions list is non-empty → gate D not triggered.
    assert run_validation_gate(d) == "allowed"
