"""
feature_coach_v1 — extracted from server.py.
"""
# ---------------------------------------------------------------------------
# Auto-extracted from server.py during 2026-07 refactor.
# Endpoint contracts are IDENTICAL to the pre-refactor version.
# Imports happen from `server` after all shared symbols are defined
# (server imports this module at the very bottom).
# ---------------------------------------------------------------------------

from fastapi import Depends, HTTPException
from typing import Any, Optional
import json

from server import (
    api,
    db,
    current_user,
    require_role,
    new_id,
    now_iso,
    clean_doc,
    call_claude,
    parse_json_from_text,
    send_push,
    logger,
    _create_coach_task,
    _log_change,
    MessageDraftGenerateBody,
    MessageDraftToneBody,
    MessageDraftEditBody,
    CoachClientControlsBody,
)

# --- ORIGINAL SOURCE ---


# Lazy imports to avoid circular deps between feature modules.
async def notify_coach_draft_ready(*a, **kw):
    from feature_notifications import notify_coach_draft_ready as _f
    return await _f(*a, **kw)

async def notify_coach_message(*a, **kw):
    from feature_notifications import notify_coach_message as _f
    return await _f(*a, **kw)


# ------------------------------------------------------------------
# Coach Message Drafts + Coach Controls + Change Log (V1)
#
# Collections:
#   message_drafts     — Atlas-authored replies awaiting Louis's approval
#   coach_change_log   — history of controls edits, message approvals, etc.
#
# Rules:
#   * Atlas NEVER auto-sends. Every draft lands as `waiting_approval`.
#   * Every message the client sends triggers a draft (regardless of risk).
#   * Coach can Edit / Shorten / Warm / Send / Dismiss the draft.
# ------------------------------------------------------------------

MSG_DRAFT_SYSTEM = (
    "You are Atlas, an assistant coach helping Louis run CrewFit — a personal "
    "training service for airline cabin crew. Louis is the human coach; you are "
    "his silent drafter. NEVER auto-send. Louis reviews and approves every reply.\n\n"
    "Draft a message reply Louis could send to this client. Match Louis's tone: "
    "warm but direct, practical, uses first names, avoids corporate fitness jargon. "
    "Keep it under 90 words unless the client asked for detailed info. British English. "
    "Do not sign off with a name — Louis will add that.\n\n"
    "Return STRICT JSON with these keys:\n"
    "  atlas_draft         — the reply text (string, plain text, no markdown)\n"
    "  risk_level          — 'low' | 'medium' | 'high'  (see rules below)\n"
    "  risk_reason         — one-line reason (string)\n"
    "  action_hint         — one of 'answer' | 'adjust_programme' | 'escalate' | 'safety_check'\n"
    "  tone_used           — 'warm' | 'direct' | 'shorter' | 'clearer' | 'custom'\n"
    "  summary             — one-line summary of the client's message for the To-Do feed (string)\n\n"
    "Risk rules:\n"
    "  * low     — routine acknowledgement, encouragement, simple question that has a clear answer.\n"
    "  * medium  — programme change, deload, kit swap, missed sessions, motivation dip, "
    "sleep/nutrition query that needs Louis's judgement.\n"
    "  * high    — pain, injury, medical, dizziness, chest, sharp pain, mental health, "
    "safety-of-flight concerns, disordered eating flags, extreme fatigue. Escalate always.\n"
)


async def _summarise_thread(client_id: str, coach_id: str, limit: int = 20) -> list[dict]:
    msgs = await db.messages.find(
        {"$or": [{"from_user_id": client_id, "to_user_id": coach_id},
                 {"from_user_id": coach_id, "to_user_id": client_id}]}, {"_id": 0}
    ).sort("created_at", -1).to_list(limit)
    msgs.reverse()
    out = []
    for m in msgs:
        who = "client" if m.get("from_user_id") == client_id else "coach"
        out.append({"who": who, "text": (m.get("text") or "")[:600], "at": m.get("created_at")})
    return out


async def _build_draft_context(client: dict, incoming_message: Optional[dict], tone_hint: Optional[str], custom_instruction: Optional[str]) -> dict:
    dna = client.get("coaching_dna") or {}
    controls = client.get("coach_controls") or {}
    latest_checkin = await db.check_ins.find_one({"user_id": client["id"]}, {"_id": 0}, sort=[("submitted_at", -1)])
    last_workouts = await db.workouts.find(
        {"user_id": client["id"]}, {"_id": 0, "title": 1, "date": 1, "completed": 1, "day_type": 1, "day_load": 1}
    ).sort("date", -1).to_list(6)
    coach = await db.users.find_one({"role": "coach"}, {"_id": 0, "name": 1, "id": 1})
    coach_id = (coach or {}).get("id") or ""
    thread = await _summarise_thread(client["id"], coach_id, limit=20)
    return {
        "client": {
            "name": client.get("name"),
            "first_name": (client.get("name") or "").split(" ")[0],
            "crew_role": dna.get("crew_role") or client.get("crew_role"),
            "primary_goals": dna.get("primary_goals") or [],
            "training_style": dna.get("training_style"),
            "obstacles": dna.get("obstacles") or [],
            "communication_preference": dna.get("communication_style"),
        },
        "coach_controls": {
            "programme_flexibility": controls.get("programme_flexibility", "flexible"),
            "progression_speed": controls.get("progression_speed", "standard"),
            "injury_caution": controls.get("injury_caution", "medium"),
            "video_frequency": controls.get("video_frequency", "weekly"),
            "auto_approval_risk_threshold": controls.get("auto_approval_risk_threshold", "none"),
        },
        "latest_check_in": (latest_checkin or {}).get("atlas_coach_summary") if latest_checkin else None,
        "check_in_flags": {
            "urgent_safety_flag": (latest_checkin or {}).get("urgent_safety_flag"),
            "injury_flag": (latest_checkin or {}).get("injury_flag"),
            "recovery_score": (latest_checkin or {}).get("recovery_score"),
        } if latest_checkin else None,
        "recent_workouts": last_workouts,
        "thread_history": thread,
        "incoming_message": (incoming_message or {}).get("text"),
        "coach_tone_hint": tone_hint,
        "custom_instruction": custom_instruction,
    }


async def _atlas_draft_reply(client: dict, incoming_message: Optional[dict], tone_hint: Optional[str] = None, custom_instruction: Optional[str] = None) -> dict:
    ctx = await _build_draft_context(client, incoming_message, tone_hint, custom_instruction)
    prompt = "Draft Louis's reply for this thread. CLIENT + CONTEXT:\n" + json.dumps(ctx, default=str)[:8000]
    parsed: dict[str, Any] = {}
    try:
        raw = await call_claude(MSG_DRAFT_SYSTEM, prompt, max_out=1200)
        parsed = parse_json_from_text(raw) or {}
    except Exception:
        logger.exception("Atlas message draft failed")
    if not parsed.get("atlas_draft"):
        parsed = {
            "atlas_draft": "Thanks for the message — I'll come back to you shortly.",
            "risk_level": "medium",
            "risk_reason": "Atlas draft failed; coach must write from scratch.",
            "action_hint": "answer",
            "tone_used": tone_hint or "warm",
            "summary": (incoming_message or {}).get("text", "")[:120] if incoming_message else "Coach initiated draft",
        }
    parsed.setdefault("risk_level", "medium")
    parsed.setdefault("tone_used", tone_hint or "warm")
    return parsed


def _priority_from_risk(risk: str) -> str:
    if risk == "high":
        return "urgent"
    if risk == "medium":
        return "high"
    return "normal"


async def _persist_draft(client: dict, coach_id: str, incoming_message: Optional[dict], atlas_result: dict, previous_draft_id: Optional[str] = None) -> dict:
    draft_id = new_id()
    doc = {
        "id": draft_id,
        "client_id": client["id"],
        "client_name": client.get("name") or client.get("email"),
        "coach_id": coach_id,
        "thread_id": f"{client['id']}::{coach_id}",
        "source_message_id": (incoming_message or {}).get("id"),
        "source_message_text": (incoming_message or {}).get("text"),
        "source_message_at": (incoming_message or {}).get("created_at"),
        "atlas_draft": atlas_result.get("atlas_draft"),
        "coach_edited_text": None,
        "tone_used": atlas_result.get("tone_used"),
        "risk_level": atlas_result.get("risk_level", "medium"),
        "risk_reason": atlas_result.get("risk_reason"),
        "action_hint": atlas_result.get("action_hint"),
        "summary": atlas_result.get("summary"),
        "status": "waiting_approval",
        "regenerated_from": previous_draft_id,
        "created_at": now_iso(),
        "sent_at": None,
        "dismissed_at": None,
        "sent_message_id": None,
    }
    await db.message_drafts.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def _bg_generate_message_draft(client: dict, incoming_message: dict) -> None:
    """Background task: fetch coach, run Atlas, persist draft, create coach_task."""
    try:
        coach = await db.users.find_one({"role": "coach"}, {"_id": 0, "id": 1, "name": 1})
        coach_id = (coach or {}).get("id") or ""
        result = await _atlas_draft_reply(client, incoming_message)
        draft = await _persist_draft(client, coach_id, incoming_message, result)
        summary = (result.get("summary") or (incoming_message.get("text") or "")[:80]).strip()
        risk = draft["risk_level"]
        prefix = "URGENT · " if risk == "high" else ("REVIEW · " if risk == "medium" else "")
        title = f"{prefix}Reply to {client.get('name') or client.get('email')}"
        await _create_coach_task(
            client, "message_draft_ready", title,
            summary or "Atlas has drafted a reply. Review, edit and send.",
            priority=_priority_from_risk(risk),
            message_draft_id=draft["id"],
            risk_level=risk,
            category="messages",
            payload={"source_message_id": incoming_message.get("id")},
        )
        # Notify the coach in-app about the ready draft
        try:
            coach_id_now = coach_id or (await db.users.find_one({"role": "coach"}, {"id": 1}) or {}).get("id")
            if coach_id_now:
                await notify_coach_draft_ready(coach_id_now, client.get("name") or client.get("email"), draft["id"])
        except Exception:
            logger.exception("coach draft notify failed")
    except Exception:
        logger.exception("_bg_generate_message_draft failed")


# --- Coach change log helper ------------------------------------------------
# Moved back to server.py post-refactor so multiple feature modules can import it.
# (Was: async def _log_change ...)


# ---- Endpoints -------------------------------------------------------------

@api.post("/coach/messages/generate")
async def coach_msg_generate(body: MessageDraftGenerateBody, coach: dict = Depends(require_role("coach"))):
    """Manually ask Atlas to draft a reply (e.g. coach opens the thread and wants a suggestion)."""
    client = await db.users.find_one({"id": body.client_id}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(404, "client not found")
    incoming = None
    if body.source_message_id:
        incoming = await db.messages.find_one({"id": body.source_message_id}, {"_id": 0})
    else:
        incoming = await db.messages.find_one(
            {"from_user_id": body.client_id, "to_user_id": coach["id"]}, {"_id": 0}, sort=[("created_at", -1)]
        )
    result = await _atlas_draft_reply(client, incoming, tone_hint=body.tone_hint, custom_instruction=body.custom_instruction)
    draft = await _persist_draft(client, coach["id"], incoming, result)
    # Only create a task if there wasn't one already for this message
    existing = None
    if incoming:
        existing = await db.coach_tasks.find_one({"task_type": "message_draft_ready",
                                                  "payload.source_message_id": incoming.get("id"),
                                                  "status": {"$in": ["todo", "in_progress"]}})
    if not existing:
        risk = draft["risk_level"]
        await _create_coach_task(
            client, "message_draft_ready",
            f"Reply to {client.get('name') or client.get('email')}",
            (result.get("summary") or "Atlas has drafted a reply.")[:200],
            priority=_priority_from_risk(risk),
            message_draft_id=draft["id"],
            risk_level=risk, category="messages",
            payload={"source_message_id": (incoming or {}).get("id")},
        )
    # Notify the coach in-app about the ready draft (manual path)
    try:
        await notify_coach_draft_ready(coach["id"], client.get("name") or client.get("email"), draft["id"])
    except Exception:
        logger.exception("notify_coach_draft_ready failed")
    return {"draft": draft}


@api.post("/coach/messages/{draft_id}/regenerate")
async def coach_msg_regenerate(draft_id: str, body: MessageDraftToneBody, coach: dict = Depends(require_role("coach"))):
    d = await db.message_drafts.find_one({"id": draft_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "draft not found")
    if d["status"] != "waiting_approval":
        raise HTTPException(400, "draft is not editable")
    client = await db.users.find_one({"id": d["client_id"]}, {"_id": 0, "password_hash": 0})
    incoming = await db.messages.find_one({"id": d.get("source_message_id")}, {"_id": 0}) if d.get("source_message_id") else None
    result = await _atlas_draft_reply(client, incoming, tone_hint=body.tone, custom_instruction=body.custom_instruction)
    # Update in place — we keep same draft record but stash the previous atlas text into history
    history = d.get("regeneration_history") or []
    history.append({"atlas_draft": d.get("atlas_draft"), "tone_used": d.get("tone_used"), "at": now_iso()})
    updates = {
        "atlas_draft": result.get("atlas_draft"),
        "tone_used": result.get("tone_used") or body.tone,
        "risk_level": result.get("risk_level", d.get("risk_level")),
        "risk_reason": result.get("risk_reason", d.get("risk_reason")),
        "action_hint": result.get("action_hint", d.get("action_hint")),
        "regeneration_history": history[-5:],
        "updated_at": now_iso(),
    }
    await db.message_drafts.update_one({"id": draft_id}, {"$set": updates})
    d = await db.message_drafts.find_one({"id": draft_id}, {"_id": 0})
    return {"draft": d}


@api.patch("/coach/messages/{draft_id}")
async def coach_msg_edit(draft_id: str, body: MessageDraftEditBody, coach: dict = Depends(require_role("coach"))):
    d = await db.message_drafts.find_one({"id": draft_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "draft not found")
    if d["status"] != "waiting_approval":
        raise HTTPException(400, "draft is not editable")
    await db.message_drafts.update_one({"id": draft_id}, {"$set": {
        "coach_edited_text": body.coach_edited_text,
        "edited_at": now_iso(),
    }})
    d = await db.message_drafts.find_one({"id": draft_id}, {"_id": 0})
    return {"draft": d}


@api.post("/coach/messages/{draft_id}/approve")
async def coach_msg_approve(draft_id: str, body: Optional[MessageDraftEditBody] = None, coach: dict = Depends(require_role("coach"))):
    """Send the drafted (and optionally edited) reply as a real message from the coach."""
    d = await db.message_drafts.find_one({"id": draft_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "draft not found")
    if d["status"] != "waiting_approval":
        raise HTTPException(400, "draft already resolved")
    final_text = None
    if body and body.coach_edited_text is not None:
        final_text = body.coach_edited_text
    else:
        final_text = d.get("coach_edited_text") or d.get("atlas_draft") or ""
    final_text = (final_text or "").strip()
    if not final_text:
        raise HTTPException(400, "empty message")
    msg = {
        "id": new_id(),
        "from_user_id": coach["id"],
        "to_user_id": d["client_id"],
        "text": final_text,
        "created_at": now_iso(),
        "read": False,
        "source_draft_id": draft_id,
    }
    await db.messages.insert_one(msg)
    clean_doc(msg)
    now = now_iso()
    await db.message_drafts.update_one({"id": draft_id}, {"$set": {
        "status": "sent",
        "coach_edited_text": final_text,
        "sent_at": now,
        "sent_message_id": msg["id"],
    }})
    await db.coach_tasks.update_many(
        {"message_draft_id": draft_id, "status": {"$in": ["todo", "in_progress"]}},
        {"$set": {"status": "done", "completed_at": now}},
    )
    try:
        await send_push([d["client_id"]], {"title": coach.get("name", "CrewFit"), "message": final_text[:120], "action_url": "/(client)/messages"})
    except Exception as e:
        logger.warning("push send fail: %s", e)
    # In-app notification record for the client
    try:
        await notify_coach_message(coach["id"], d["client_id"], final_text, source_message_id=msg["id"])
    except Exception:
        logger.exception("coach message notify failed")
    await _log_change(coach["id"], d["client_id"], "message",
                      f"Sent reply to {d.get('client_name')}",
                      final_text[:180], actor="coach",
                      meta={"draft_id": draft_id, "risk_level": d.get("risk_level"),
                            "atlas_original": d.get("atlas_draft"), "was_edited": d.get("atlas_draft") != final_text})
    return {"ok": True, "message": msg, "draft_id": draft_id}


@api.post("/coach/messages/{draft_id}/dismiss")
async def coach_msg_dismiss(draft_id: str, coach: dict = Depends(require_role("coach"))):
    d = await db.message_drafts.find_one({"id": draft_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "draft not found")
    now = now_iso()
    await db.message_drafts.update_one({"id": draft_id}, {"$set": {
        "status": "dismissed", "dismissed_at": now,
    }})
    await db.coach_tasks.update_many(
        {"message_draft_id": draft_id, "status": {"$in": ["todo", "in_progress"]}},
        {"$set": {"status": "dismissed", "dismissed_at": now, "completed_at": now}},
    )
    await _log_change(coach["id"], d["client_id"], "message",
                      f"Dismissed Atlas draft for {d.get('client_name')}",
                      d.get("atlas_draft", "")[:180], actor="coach",
                      meta={"draft_id": draft_id, "risk_level": d.get("risk_level")})
    return {"ok": True}


@api.get("/coach/messages/drafts")
async def coach_msg_drafts_list(coach: dict = Depends(require_role("coach")),
                                status: Optional[str] = None,
                                client_id: Optional[str] = None,
                                limit: int = 100):
    q: dict[str, Any] = {}
    q["status"] = status or "waiting_approval"
    if client_id:
        q["client_id"] = client_id
    rows = await db.message_drafts.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return {"drafts": rows, "count": len(rows)}


@api.get("/coach/messages/drafts/{draft_id}")
async def coach_msg_draft_get(draft_id: str, coach: dict = Depends(require_role("coach"))):
    d = await db.message_drafts.find_one({"id": draft_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "draft not found")
    # attach thread history
    thread = await db.messages.find(
        {"$or": [{"from_user_id": d["client_id"], "to_user_id": coach["id"]},
                 {"from_user_id": coach["id"], "to_user_id": d["client_id"]}]}, {"_id": 0}
    ).sort("created_at", 1).to_list(200)
    return {"draft": d, "thread": thread}


# ---- Per-client Coach Controls --------------------------------------------

DEFAULT_COACH_CONTROLS = {
    "programme_flexibility": "flexible",
    "progression_speed": "standard",
    "injury_caution": "medium",
    "video_frequency": "weekly",
    "auto_approval_risk_threshold": "none",
}


@api.get("/coach/clients/{client_id}/controls")
async def coach_controls_get(client_id: str, coach: dict = Depends(require_role("coach"))):
    c = await db.users.find_one({"id": client_id}, {"_id": 0, "coach_controls": 1, "name": 1})
    if not c:
        raise HTTPException(404, "client not found")
    controls = {**DEFAULT_COACH_CONTROLS, **(c.get("coach_controls") or {})}
    return {"controls": controls, "defaults": DEFAULT_COACH_CONTROLS}


@api.put("/coach/clients/{client_id}/controls")
async def coach_controls_put(client_id: str, body: CoachClientControlsBody, coach: dict = Depends(require_role("coach"))):
    c = await db.users.find_one({"id": client_id}, {"_id": 0, "coach_controls": 1, "name": 1, "email": 1})
    if not c:
        raise HTTPException(404, "client not found")
    prev = {**DEFAULT_COACH_CONTROLS, **(c.get("coach_controls") or {})}
    updates: dict[str, Any] = {}
    for k in ("programme_flexibility", "progression_speed", "injury_caution",
              "video_frequency", "auto_approval_risk_threshold"):
        v = getattr(body, k)
        if v is not None:
            updates[k] = v
    if not updates:
        raise HTTPException(400, "no updates")
    merged = {**prev, **updates}
    await db.users.update_one({"id": client_id}, {"$set": {"coach_controls": merged}})
    # log which fields changed
    diff = {k: {"from": prev.get(k), "to": merged[k]} for k in updates if prev.get(k) != merged[k]}
    if diff:
        await _log_change(coach["id"], client_id, "controls",
                          f"Updated controls for {c.get('name') or c.get('email')}",
                          ", ".join(f"{k}: {v['from']}→{v['to']}" for k, v in diff.items()),
                          actor="coach", meta={"diff": diff})
    return {"controls": merged}


# ---- Change Log endpoints --------------------------------------------------

@api.get("/coach/change-log")
async def coach_change_log_all(coach: dict = Depends(require_role("coach")),
                               client_id: Optional[str] = None,
                               category: Optional[str] = None,
                               limit: int = 100):
    q: dict[str, Any] = {}
    if client_id:
        q["client_id"] = client_id
    if category:
        q["category"] = category
    rows = await db.coach_change_log.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return {"entries": rows, "count": len(rows)}


@api.get("/coach/clients/{client_id}/change-log")
async def coach_change_log_client(client_id: str, coach: dict = Depends(require_role("coach")), limit: int = 60):
    rows = await db.coach_change_log.find({"client_id": client_id}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return {"entries": rows, "count": len(rows)}

