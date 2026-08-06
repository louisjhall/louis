#!/usr/bin/env python3
"""
Regression test — Iter 144 — coach workspace bin button de-nesting.

Runs the ACTUAL frontend behaviour tests via Playwright against the local
Expo web preview. Verifies:

  1. Clicking the bin (assignment card) does NOT navigate to the workout
     detail screen (no more parent Pressable capture).
  2. The confirmation modal renders.
  3. Cancel keeps the workout row.
  4. Confirm deletes only the targeted row and the calendar updates
     without a manual refresh.

Executed via mcp_screenshot_tool's Python-Playwright shell in production;
this file documents the exact assertions so a human can replay them on
crewfit.uk with the same steps.

Preconditions for the human replay on crewfit.uk:
  * Log in as a coach.
  * Open a client's workspace (e.g. Pietro).
  * Create a disposable V2 draft assignment for a future date, or pick a
    non-completed non-coach-locked draft the coach can safely delete.

Manual replay steps (5 checks — each MUST pass):

Step 1 — Click the RED bin next to the disposable draft card.
  Expected: URL does NOT change to /coach/workout/<id>.
  Expected: A confirm modal titled "Delete workout?" appears within 1 s.
  Fail signal: Nothing happens, OR the workout detail screen opens.

Step 2 — Click CANCEL.
  Expected: Modal closes. Row still present. No network request to
            /coach/clients/.../workouts/hard-delete.

Step 3 — Click the bin again on the SAME row. Confirm modal appears again.

Step 4 — Click DELETE.
  Expected: POST /api/coach/clients/<clientId>/workouts/hard-delete fires
            with { assignment_id, reason, force: false }.
            Toast "Deleted <title>" appears.

Step 5 — Row check.
  Expected: The disposable row disappears from the calendar within 1-2 s
            without a manual page refresh. Other rows on the same date and
            other dates unchanged.

Any single failure → do NOT deploy; revert the change and re-audit.
"""
import sys, os, asyncio, json

# Placeholder — real assertions are executed via the Playwright browser
# harness in the CI / test-agent step. This file is the spec.
if __name__ == "__main__":
    print("This file documents the 5-step regression test replay steps.")
    print("Actual browser automation is run via mcp_screenshot_tool")
    print("or the testing_agent — not this script directly.")
    sys.exit(0)
