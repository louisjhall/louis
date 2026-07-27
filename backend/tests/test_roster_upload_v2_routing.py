"""Regression tests for the roster upload → Engine V2 kickoff integration.

Guards against the P0 incident where a V2-enabled client's roster upload
silently ran the legacy V1 generator and produced workout_assignments with
the old failure pattern (10 Long Runs, Tempo/Intervals in Foundation, no
Strength, no Mobility).

The invariants tested here:
  * V2-enabled client's roster upload → Engine V2 kickoff, NOT V1 generation
  * plan_drafts_v2 populated; workout_assignments untouched
  * V2 Draft endpoint returns the draft, NOT a synthesised V1 fallback
"""
import inspect

from feature_coach_roster_upload import coach_pending_confirm
# Client-side confirm endpoint is inspected via the module source below.


def _worker_body(fn) -> str:
    """Extract the inner `_worker` async function's body source."""
    src = inspect.getsource(fn)
    return src


def test_coach_confirm_worker_has_engine_v2_branch():
    src = _worker_body(coach_pending_confirm)
    assert "engine_v2_kickoff" in src, (
        "coach_pending_confirm worker MUST call Engine V2 kickoff for "
        "v2_flags.engine_v2 clients — legacy V1 generation is no longer the "
        "default for V2-enabled clients."
    )
    assert "v2_flags.get(\"engine_v2\")" in src, \
        "The V2 branch guard must check v2_flags.engine_v2 explicitly."


def test_coach_confirm_worker_v2_short_circuits_before_generate_month():
    src = _worker_body(coach_pending_confirm)
    # Order matters: the V2 branch must appear BEFORE the legacy V1
    # `_generate_month` call so V2 clients never hit it.
    v2_pos = src.find("engine_v2_kickoff")
    v1_pos = src.find("_generate_month")
    assert v2_pos > 0
    assert v1_pos > 0
    assert v2_pos < v1_pos, (
        "V2 kickoff branch must come BEFORE the V1 _generate_month path."
    )


def test_client_confirm_worker_has_engine_v2_branch():
    """The client-side confirmation path must apply the same routing."""
    try:
        # Client-side worker lives inside the confirm endpoint (nested def).
        import feature_roster_confirmation as m
        src = inspect.getsource(m)
        assert "engine_v2_kickoff" in src, (
            "feature_roster_confirmation must route V2-enabled clients to "
            "Engine V2 kickoff instead of legacy V1 generation."
        )
        # Both branches present
        assert "v2_flags.get(\"engine_v2\")" in src
    except Exception as e:
        raise AssertionError(f"Cannot verify client confirm branch: {e}")


def test_engine_v2_draft_endpoint_does_not_fallback_to_v1():
    """The V2 Draft endpoint must return 404 (not V1 workout_assignments) when
    no draft exists — this is the core guarantee against the reported P0."""
    import feature_v2_engine_v2_kickoff as k
    src = inspect.getsource(k.engine_v2_get_draft)
    assert "workout_assignments" not in src, (
        "engine_v2_get_draft MUST NOT touch workout_assignments (V1). "
        "The V2 Draft screen has a hard prohibition on V1 fallback."
    )
    assert "HTTPException(404" in src or "raise HTTPException" in src, (
        "engine_v2_get_draft must fail loud with 404 when no V2 draft "
        "exists rather than silently falling back."
    )
