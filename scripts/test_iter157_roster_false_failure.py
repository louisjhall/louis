"""
Iter 157 — Roster false-failure verification.

Covers:
  A. `_call_gemini_file_with_retries` retries up to 3 times with backoff
     before propagating the final exception.
  B. It returns immediately on the first successful attempt (no wasted retries).
  C. Empty-string response counts as a soft failure that triggers a retry.
  D. Watchdog / startup-sweep queries skip jobs at progress >= 100 or
     with a `pending_roster_id` attached.

Run:
    cd /app/backend && python /app/scripts/test_iter157_roster_false_failure.py
"""
import asyncio
import sys

sys.path.insert(0, "/app/backend")


async def main():
    import server as srv  # noqa: F401  boot deps
    import feature_roster_confirmation as rc

    # ---------------------------------------------------------------
    # A. Retries 3× then raises last error
    # ---------------------------------------------------------------
    calls = {"n": 0}

    async def failing(*_a, **_kw):
        calls["n"] += 1
        raise RuntimeError(f"attempt {calls['n']}: 503")

    # Speed test up: swap backoff to 0 so we don't wait 13s in a unit test.
    orig_backoff = rc._GEMINI_RETRY_BACKOFF_S
    rc._GEMINI_RETRY_BACKOFF_S = (0, 0, 0)  # type: ignore
    orig_call = rc.call_gemini_file
    rc.call_gemini_file = failing  # type: ignore
    try:
        raised = False
        try:
            await rc._call_gemini_file_with_retries("sys", "prompt", "/tmp/x", "application/pdf", context="test-A")
        except RuntimeError as e:
            raised = True
            assert "attempt 3" in str(e), f"should surface last error, got: {e}"
        assert raised, "should have raised after exhausting retries"
        assert calls["n"] == 3, f"expected 3 attempts, got {calls['n']}"
        print("A OK — retries 3× then propagates final exception.")

        # ---------------------------------------------------------------
        # B. Succeeds on first attempt → no wasted retries
        # ---------------------------------------------------------------
        calls["n"] = 0

        async def good(*_a, **_kw):
            calls["n"] += 1
            return '{"days":[{"date":"2026-06-01","day_type":"Rest"}]}'

        rc.call_gemini_file = good  # type: ignore
        out = await rc._call_gemini_file_with_retries("sys", "p", "/tmp/x", "application/pdf", context="test-B")
        assert calls["n"] == 1, f"first success should not retry, got {calls['n']} calls"
        assert "days" in out
        print("B OK — first success short-circuits retry loop.")

        # ---------------------------------------------------------------
        # C. Empty string → soft failure → retries
        # ---------------------------------------------------------------
        calls["n"] = 0
        responses = ["", "", '{"days":[]}']

        async def empty_then_good(*_a, **_kw):
            r = responses[min(calls["n"], len(responses) - 1)]
            calls["n"] += 1
            return r

        rc.call_gemini_file = empty_then_good  # type: ignore
        out = await rc._call_gemini_file_with_retries("sys", "p", "/tmp/x", "application/pdf", context="test-C")
        assert calls["n"] == 3, f"empty responses should trigger retry until success, got {calls['n']}"
        assert "days" in out
        print("C OK — empty response counts as soft failure and retries.")
    finally:
        rc.call_gemini_file = orig_call  # type: ignore
        rc._GEMINI_RETRY_BACKOFF_S = orig_backoff  # type: ignore

    # ---------------------------------------------------------------
    # D. Watchdog + startup-sweep query MUST exclude progress>=100 and
    #    pending_roster_id-attached jobs. We test this by pattern-matching
    #    the source lines — cheap regression guard.
    # ---------------------------------------------------------------
    src = open("/app/backend/server.py").read()
    startup_block = src[src.index("Roster jobs — the asyncio worker dies"):]
    # Find the startup-sweep update_many query first (nearest one).
    startup_query_idx = startup_block.index("db.roster_jobs.update_many(")
    startup_query = startup_block[startup_query_idx:startup_query_idx + 800]
    assert '"progress": {"$lt": 100}' in startup_query, "startup_sweep must exclude progress >= 100"
    assert '"pending_roster_id": {"$in": [None, ""]}' in startup_query, "startup_sweep must exclude jobs with a roster attached"
    print("D.1 OK — startup_sweep excludes progress>=100 and jobs with pending_roster_id.")

    watchdog_block = src[src.index("_roster_watchdog"):]
    watchdog_query_idx = watchdog_block.index("db.roster_jobs.update_many(")
    watchdog_query = watchdog_block[watchdog_query_idx:watchdog_query_idx + 800]
    assert '"progress": {"$lt": 100}' in watchdog_query, "watchdog must exclude progress >= 100"
    assert '"pending_roster_id": {"$in": [None, ""]}' in watchdog_query, "watchdog must exclude jobs with a roster attached"
    print("D.2 OK — watchdog excludes progress>=100 and jobs with pending_roster_id.")

    print("\nAll Iter 157 false-failure guards verified.")


if __name__ == "__main__":
    asyncio.run(main())
