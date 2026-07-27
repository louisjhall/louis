"""
feature_v2_coach_command_bar — Coach Dashboard V2 · Command Bar

Free-text coach input → structured ChangeSet proposals for review.

Flow (per §31-32 of the build brief):
    1. Coach types a natural-language instruction in the workspace header
    2. Backend routes to Claude Sonnet 4.5 via the Emergent LLM key
    3. LLM returns a JSON list of proposed actions (move / edit / directive / etc.)
    4. Backend translates each into a preview payload (before/after snapshots)
    5. Coach reviews and clicks Apply → proposals become real change_sets
       (which then flow through the existing P1 draft/approval pipeline)

Nothing on this endpoint mutates the client's LIVE plan. Every applied
proposal writes a change_set with `triggered_by=ai_command_bar` +
DecisionRecord for full audit.

Ships behind `v2_flags.coach_dashboard_v2_enabled` (per-coach).
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from server import api, db, require_role, new_id, now_iso, logger, EMERGENT_LLM_KEY
from feature_v2_common import write_decision, emit_metric


# ---------------------------------------------------------------------------
# Flag helpers (matches feature_v2_coach_dashboard)
# ---------------------------------------------------------------------------

async def _coach_has_v2_flag(coach_id: str) -> bool:
    coach = await db.users.find_one({"id": coach_id}, {"_id": 0, "profile.v2_flags": 1})
    if not coach:
        return False
    v2 = ((coach.get("profile") or {}).get("v2_flags") or {})
    return bool(v2.get("coach_dashboard_v2_enabled") or v2.get("v2_default"))


# ---------------------------------------------------------------------------
# LLM parsing
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are the CrewFit programming assistant. You do NOT invent new training rules;
you translate coach intent into structured proposals that CrewFit's V2 planner will apply after coach approval.

Return STRICT JSON only. No prose. Schema:

{
  "proposals": [
    {
      "kind": "move_assignment" | "edit_duration" | "convert_to_mobility"
            | "convert_to_recovery" | "swap_exercise" | "add_directive"
            | "reduce_volume" | "skip_session" | "lock_session" | "note_only",
      "assignment_id": "<optional, if targeting a specific session>",
      "target_date": "YYYY-MM-DD (optional)",
      "new_date": "YYYY-MM-DD (optional, for move)",
      "target_kind_or_pattern": "<optional, e.g. long_run>",
      "duration_min_new": <optional number>,
      "duration_min_delta_pct": <optional number, negative to reduce>,
      "directive_kind": "avoid_movement" | "require_movement" | "limit_frequency"
                     | "limit_volume" | "limit_intensity" | "note_only" (optional),
      "directive_scope": "today" | "this_week" | "this_trip" | "phase" | "until_changed" (optional),
      "reason": "<short coach-readable explanation of why this proposal makes sense>",
      "summary": "<one-line human-readable summary of the change>"
    }
  ]
}

Rules:
- If the request is ambiguous, return "note_only" with a summary asking the coach to clarify.
- Never propose more than 6 items in one response.
- Only reference assignments that appear in the provided context.
- Do NOT reference AI, algorithms, or automation in `summary` or `reason` — write as a coach would.
- Prefer `directive_scope="until_changed"` for permanent avoidance requests.
"""


async def _call_llm(session_id: str, prompt: str) -> dict:
    """Call Claude Sonnet 4.5 via emergentintegrations; return parsed JSON."""
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        raise HTTPException(500, f"emergentintegrations missing: {e}")

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=_SYSTEM_PROMPT,
    )
    chat.with_model("anthropic", "claude-sonnet-4-5-20250929")
    try:
        text = await chat.send_message(UserMessage(text=prompt))
    except Exception as e:
        raise HTTPException(502, f"LLM call failed: {str(e)[:200]}")

    # Extract JSON — LLM occasionally wraps in ```json fences
    if not isinstance(text, str):
        text = str(text)
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return {"proposals": [{"kind": "note_only",
                                "summary": "Sorry, I couldn't understand that.",
                                "reason": "Rephrase in coach terms (e.g. 'Move Tuesday's long run to Sunday')."}]}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"proposals": [{"kind": "note_only",
                                "summary": "Sorry, I couldn't parse that.",
                                "reason": text[:200]}]}


# ---------------------------------------------------------------------------
# Context builder — passes the LLM only what it needs
# ---------------------------------------------------------------------------

async def _build_workspace_context(client_id: str, month: str) -> dict:
    """Produce a compact JSON view of the client's month for the LLM.
    Reads directly from Mongo — does not go through the coach-flag-gated
    HTTP endpoint (which would 409)."""
    from calendar import monthrange
    try:
        year, mo = int(month[:4]), int(month[5:7])
        _, last = monthrange(year, mo)
    except Exception:
        raise HTTPException(400, "month must be YYYY-MM")
    sd_str = f"{year:04d}-{mo:02d}-01"
    ed_str = f"{year:04d}-{mo:02d}-{last:02d}"

    client = await db.users.find_one({"id": client_id}, {"_id": 0, "name": 1, "display_name": 1, "email": 1})
    if not client:
        raise HTTPException(404, "Client not found")

    sched_days = await db.schedule_days.find(
        {"client_id": client_id, "date": {"$gte": sd_str, "$lte": ed_str}}, {"_id": 0}
    ).sort("date", 1).to_list(50)

    # V1 fallback for schedule context (LLM can still reason about it)
    if not sched_days:
        for r in await db.rosters.find({"user_id": client_id, "is_active": True}, {"_id": 0}).to_list(10):
            for d in (r.get("days") or []):
                if (d.get("date") or "").startswith(f"{year:04d}-{mo:02d}"):
                    sched_days.append({
                        "date": d.get("date"),
                        "derived": {"classification": d.get("classification") or "home",
                                     "duty_burden_band": None},
                    })

    assignments = await db.workout_assignments.find(
        {"client_id": client_id, "date": {"$gte": sd_str, "$lte": ed_str}}, {"_id": 0}
    ).sort("date", 1).to_list(200)

    days_slim: list[dict] = []
    by_date: dict[str, dict] = {}
    for sd in sched_days:
        d = sd.get("date")
        by_date.setdefault(d, {"date": d, "assignments": []})
        by_date[d]["classification"] = (sd.get("derived") or {}).get("classification")
        by_date[d]["duty_burden_band"] = (sd.get("derived") or {}).get("duty_burden_band")
    for a in assignments:
        d = a.get("date")
        by_date.setdefault(d, {"date": d, "assignments": []})
        by_date[d]["assignments"].append({
            "assignment_id": a.get("id"),
            "kind": a.get("kind"),
            "duration_min": a.get("planned_duration_min"),
            "importance": a.get("importance"),
            "status": a.get("status"),
            "locked": a.get("locked"),
        })
    days_slim = [by_date[k] for k in sorted(by_date.keys())]

    return {
        "client_name": client.get("display_name") or client.get("name") or client.get("email") or "Client",
        "month": month,
        "days": days_slim,
    }


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

class CommandParseBody(BaseModel):
    month: str = Field(..., description="YYYY-MM window the coach is currently viewing")
    text: str = Field(..., min_length=1, max_length=1000)
    draft_id: Optional[str] = None


@api.post("/v2/coach/clients/{client_id}/command-bar/parse")
async def command_parse(
    client_id: str, body: CommandParseBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Parse a coach's free-text command into structured proposals.
    Nothing is applied. Returns a preview payload the coach can accept."""
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")

    client = await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1, "name": 1, "display_name": 1})
    if not client:
        raise HTTPException(404, "Client not found")

    try:
        context = await _build_workspace_context(client_id, body.month)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Workspace context error: {e}")

    prompt = (
        f"CLIENT: {context['client_name']}\n"
        f"MONTH: {context['month']}\n"
        f"SCHEDULE (compact JSON):\n{json.dumps(context['days'], default=str)[:8000]}\n\n"
        f"COACH INSTRUCTION:\n{body.text}\n\n"
        f"Return the structured proposals JSON now."
    )
    parsed = await _call_llm(session_id=f"cmdbar-{coach['id']}-{new_id()[:8]}", prompt=prompt)
    proposals = parsed.get("proposals") or []

    # Attach a per-proposal id so the frontend can reference on apply
    for p in proposals:
        p["proposal_id"] = new_id()

    # Persist a lightweight preview record for auditability (not a change_set yet)
    preview_id = new_id()
    await db.command_bar_previews.insert_one({
        "id": preview_id,
        "client_id": client_id,
        "coach_id": coach["id"],
        "month": body.month,
        "input_text": body.text,
        "draft_id": body.draft_id,
        "proposals": proposals,
        "created_at": now_iso(),
        "status": "pending",
    })
    await emit_metric("command_bar_parsed", client_id=client_id, coach_id=coach["id"],
                      numeric_value=len(proposals))

    return {
        "preview_id": preview_id,
        "client_id": client_id,
        "month": body.month,
        "input_text": body.text,
        "proposals": proposals,
    }


class CommandApplyBody(BaseModel):
    preview_id: str
    accept_proposal_ids: list[str]     # subset of proposal_ids the coach accepted
    draft_id: Optional[str] = None


@api.post("/v2/coach/clients/{client_id}/command-bar/apply")
async def command_apply(
    client_id: str, body: CommandApplyBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Convert accepted proposals into ChangeSet records against the current draft.
    Nothing published — approval still runs through the existing flow."""
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")
    preview = await db.command_bar_previews.find_one(
        {"id": body.preview_id, "client_id": client_id, "coach_id": coach["id"]}, {"_id": 0}
    )
    if not preview:
        raise HTTPException(404, "Preview not found")

    accepted = [p for p in (preview.get("proposals") or []) if p.get("proposal_id") in set(body.accept_proposal_ids)]
    if not accepted:
        return {"change_sets_created": 0, "applied": []}

    draft_id = body.draft_id or preview.get("draft_id")
    change_sets: list[dict] = []
    directives_created: list[dict] = []
    for p in accepted:
        kind = p.get("kind") or "note_only"
        # Split: directive-family kinds land in coach_directives; others land in change_sets
        if kind == "add_directive":
            did = new_id()
            await db.coach_directives.insert_one({
                "id": did,
                "client_id": client_id,
                "coach_id": coach["id"],
                "kind": p.get("directive_kind") or "note_only",
                "scope": {"scope_kind": p.get("directive_scope") or "until_changed"},
                "parameters": {
                    "pattern": p.get("target_kind_or_pattern"),
                    "target_date": p.get("target_date"),
                },
                "free_text": p.get("summary") or "",
                "status": "active",
                "source": "command_bar",
                "created_at": now_iso(),
                "updated_at": now_iso(),
            })
            directives_created.append({"id": did, "summary": p.get("summary")})
            await write_decision(
                actor="coach", layer="ADAPT", scope_kind="coach_directive", scope_id=did,
                client_id=client_id, outcome="APPLIED",
                reason=f"Command bar directive: {p.get('summary')}",
                rule_or_prompt={"id": "command_bar", "kind": "prompt", "version": "1"},
            )
            continue

        cs_id = new_id()
        cs_kind_map = {
            "move_assignment": "assignment_moved",
            "edit_duration": "implementation_changed",
            "convert_to_mobility": "implementation_changed",
            "convert_to_recovery": "implementation_changed",
            "swap_exercise": "implementation_changed",
            "reduce_volume": "implementation_changed",
            "skip_session": "exposure_deferred",
            "lock_session": "implementation_changed",
            "note_only": "coach_directive_applied",
        }
        await db.change_sets.insert_one({
            "id": cs_id,
            "draft_id": draft_id,
            "client_id": client_id,
            "kind": cs_kind_map.get(kind, "coach_directive_applied"),
            "scope_assignment_ids": [p.get("assignment_id")] if p.get("assignment_id") else [],
            "before_snapshot": None,
            "after_snapshot": {k: v for k, v in p.items() if k not in ("proposal_id",)},
            "triggered_by": "ai_command_bar",
            "triggered_event_id": body.preview_id,
            "proposed_by": "coach",
            "status": "proposed",
            "human_readable_summary": p.get("summary") or kind.replace("_", " ").title(),
            "created_at": now_iso(),
        })
        change_sets.append({"id": cs_id, "kind": kind, "summary": p.get("summary")})
        await write_decision(
            actor="coach", layer="WHEN" if kind == "move_assignment" else "HOW",
            scope_kind="change_set", scope_id=cs_id,
            client_id=client_id, outcome="PROPOSED",
            reason=f"Command bar → {kind}: {p.get('summary')}",
            rule_or_prompt={"id": "command_bar", "kind": "prompt", "version": "1"},
        )

    await db.command_bar_previews.update_one(
        {"id": body.preview_id},
        {"$set": {"status": "applied", "applied_at": now_iso(),
                   "applied_proposal_ids": body.accept_proposal_ids}}
    )
    await emit_metric("command_bar_applied", client_id=client_id, coach_id=coach["id"],
                      numeric_value=len(accepted))

    # Actually execute the change_sets against the DRAFT (P5-level move / edit / skip).
    application_stats = {"applied": 0, "rejected": 0, "seen": 0}
    try:
        from feature_v2_directive_engine import apply_pending_change_sets_for
        application_stats = await apply_pending_change_sets_for(client_id, draft_id=draft_id)
    except Exception as e:
        logger.warning(f"command-bar: change-set application failed: {e}")

    return {
        "change_sets_created": len(change_sets),
        "directives_created": len(directives_created),
        "applied": {"change_sets": change_sets, "directives": directives_created},
        "applier": application_stats,
    }


@api.get("/v2/coach/clients/{client_id}/command-bar/history")
async def command_history(
    client_id: str, limit: int = 20,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")
    rows = await db.command_bar_previews.find(
        {"client_id": client_id, "coach_id": coach["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(max(1, min(100, limit)))
    return {"history": rows}


logger.info("feature_v2_coach_command_bar: /api/v2/coach/clients/*/command-bar/* registered")
