"""
feature_client_summary — Detailed Client Summary (renamed from "Goals").

Aggregates every data slice the coach needs about a client onto ONE
endpoint, so the workspace "Summary" tab can render a full client
briefing without stitching 6 API calls together in the frontend.

Includes an OPTIONAL LLM-generated coach briefing paragraph — cached
in `db.client_briefings` and only re-generated when either:
  * the client's DNA / event signature changes, OR
  * the coach explicitly presses "Regenerate".

This preserves credits: normal tab opens hit the cache; re-generation
is a deliberate coach action.

Endpoints:
  GET  /api/coach/clients/{cid}/summary
       → structured JSON (identity, goal, DNA, adherence, habits,
         directives, checkins, roster patterns).

  POST /api/coach/clients/{cid}/summary/briefing?refresh=<bool>
       → { briefing, generated_at, model, from_cache }.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from typing import Any, Optional

from fastapi import Depends, HTTPException, Query

from server import (
    api, db, require_role, now_iso, new_id, call_claude_tracked, logger,
    _event_phase,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _as_list(v) -> list:
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [str(x) for x in v if x not in (None, "")]
    if isinstance(v, dict):
        return [f"{k}: {val}" for k, val in v.items() if val]
    return [str(v)]


def _humanise(s: str) -> str:
    return str(s).replace("_", " ").replace("-", " ").strip().title() if s else ""


def _pick(profile: dict, *keys, default=None):
    for k in keys:
        v = profile.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def _briefing_signature(client: dict, event: Optional[dict], counts: dict) -> str:
    """Hash the inputs that would change the narrative. If unchanged,
    we keep serving the cached briefing to save credits."""
    p = (client or {}).get("profile") or {}
    payload = {
        "name": client.get("name"),
        "goal": _pick(p, "main_goal", "primary_goal", "primary_goal_id", "goal"),
        "goal_notes": p.get("goal_notes") or p.get("main_goal_notes"),
        "secondary": p.get("secondary_goals") or p.get("secondary_goal_ids"),
        "days": _pick(p, "training_days_per_week", "days_per_week", "training_days"),
        "session_len": _pick(p, "preferred_session_length", "max_home_minutes"),
        "airline": p.get("airline"),
        "role": _pick(p, "job_title", "crew_role"),
        "home_base": p.get("home_base"),
        "flying_type": p.get("flying_type"),
        "haul": p.get("haul_mix") or p.get("route_focus"),
        "equipment_home": p.get("equipment_home") or p.get("home_equipment"),
        "hotel_gym_reliability": p.get("hotel_gym_reliability") or p.get("hotel_gyms"),
        "injuries": p.get("injuries"),
        "no_go": p.get("no_go_movements") or p.get("disliked_exercises"),
        "constraints": p.get("constraints"),
        "event": (event or {}).get("event_type") if event else None,
        "event_date": (event or {}).get("event_date") if event else None,
        "adherence_4w": counts.get("adherence_pct"),
        "avg_rpe_4w": counts.get("avg_rpe"),
        "active_habits": counts.get("active_habits"),
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


async def _aggregate_summary(client_id: str) -> dict:
    """Read-only aggregation. Same shape used by both the JSON endpoint
    and the LLM briefing generator."""
    client = await db.users.find_one(
        {"id": client_id, "role": "client"},
        {"_id": 0, "password_hash": 0},
    )
    if not client:
        raise HTTPException(404, "Client not found")

    profile = client.get("profile") or {}

    # ------------------------------------------------------------------ event
    event = await db.events.find_one(
        {"user_id": client_id, "is_active": True},
        {"_id": 0}, sort=[("created_at", -1)],
    )
    if event:
        try:
            event["phase_info"] = _event_phase(event.get("event_date", ""))
        except Exception:
            pass

    # ---------------------------------------------------------------- roster
    roster = await db.rosters.find_one(
        {"user_id": client_id, "is_active": True},
        {"_id": 0}, sort=[("created_at", -1)],
    )
    if not roster:
        roster = await db.rosters.find_one(
            {"user_id": client_id}, {"_id": 0}, sort=[("created_at", -1)],
        )

    # ----------------------------------------------------- adherence (28 days)
    today = _dt.date.today()
    cutoff = (today - _dt.timedelta(days=28)).isoformat()
    wkts = await db.workouts.find({
        "user_id": client_id,
        "date": {"$gte": cutoff, "$lte": today.isoformat()},
        "deactivated": {"$ne": True},
    }, {"_id": 0}).sort("date", 1).to_list(500)
    real = [w for w in wkts if str(w.get("focus") or "").lower() not in ("recovery", "mobility", "rest")]
    scheduled_past = [w for w in real if w.get("date", "") <= today.isoformat()]
    completed = [w for w in scheduled_past if w.get("completed")]
    rpes = [int(w["rpe"]) for w in completed if isinstance(w.get("rpe"), (int, float))]
    load_mix = {"green": 0, "amber": 0, "red": 0, "blue": 0, "purple": 0, "grey": 0}
    for w in scheduled_past:
        band = str(w.get("day_load") or w.get("load") or "grey").lower()
        if band in load_mix:
            load_mix[band] += 1
        else:
            load_mix["grey"] += 1
    adherence_pct = round(100 * len(completed) / len(scheduled_past)) if scheduled_past else None
    avg_rpe = round(sum(rpes) / len(rpes), 1) if rpes else None

    adherence = {
        "window_days": 28,
        "planned": len(real),
        "scheduled_past": len(scheduled_past),
        "completed": len(completed),
        "adherence_pct": adherence_pct,
        "avg_rpe": avg_rpe,
        "load_mix": load_mix,
    }

    # ---------------------------------------------------------------- checkins
    checkins = await db.checkins.find(
        {"user_id": client_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(5)

    # ---------------------------------------------------- progression snapshot
    prog_pill = None
    try:
        snap = await db.progression_snapshots.find_one(
            {"user_id": client_id}, {"_id": 0}, sort=[("week_key", -1)]
        )
        if snap:
            prog_pill = {
                "status": snap.get("status"),
                "status_label": snap.get("status_label"),
                "reason": snap.get("reason"),
                "coach_note": snap.get("coach_note"),
                "week_key": snap.get("week_key"),
            }
    except Exception:
        prog_pill = None

    # ------------------------------------------------------------- directives
    directives = ((profile.get("live_state") or {}).get("coach_directives")) or []
    # Trim large payloads
    directives = directives[-20:] if isinstance(directives, list) else []

    # ------------------------------------------------------------------ habits
    habits_active = await db.habits.count_documents({
        "user_id": client_id, "status": {"$in": [None, "active"]},
    }) if hasattr(db, "habits") else 0
    habits_paused = await db.habits.count_documents({
        "user_id": client_id, "status": "paused",
    }) if hasattr(db, "habits") else 0
    habits_archived = await db.habits.count_documents({
        "user_id": client_id, "status": "archived",
    }) if hasattr(db, "habits") else 0
    top_habits = await db.habits.find(
        {"user_id": client_id, "status": {"$in": [None, "active"]}},
        {"_id": 0, "title": 1, "frequency": 1, "streak": 1, "target": 1, "unit": 1},
    ).sort("sort_order", 1).to_list(6) if hasattr(db, "habits") else []

    # ---------------------------------------------------------- overrides / rec
    recent_overrides = await db.day_overrides.find(
        {"user_id": client_id}, {"_id": 0},
    ).sort("date", -1).to_list(10)

    # -------------------------------------------------- open coach tasks count
    open_tasks = await db.coach_tasks.count_documents({
        "client_id": client_id,
        "status": {"$in": ["todo", "in_progress", "snoozed"]},
    })

    return {
        "client": {
            "id": client.get("id"),
            "name": client.get("name"),
            "email": client.get("email"),
            "role": client.get("role"),
            "created_at": client.get("created_at"),
            "last_login_at": client.get("last_login_at"),
            "is_active": client.get("is_active", True),
            "plan_status": client.get("plan_status"),
            "profile": profile,   # full DNA
            "progression_pill": prog_pill,
        },
        "event": event,
        "roster": roster and {
            "id": roster.get("id"),
            "created_at": roster.get("created_at"),
            "expiry": roster.get("expiry"),
            "days": len(roster.get("days") or []),
        },
        "adherence": adherence,
        "checkins": checkins,
        "directives": directives,
        "habits": {
            "active_count": habits_active,
            "paused_count": habits_paused,
            "archived_count": habits_archived,
            "top": top_habits,
        },
        "recent_overrides": recent_overrides,
        "open_coach_tasks": open_tasks,
    }


# ---------------------------------------------------------------------------
# Endpoint: aggregated summary
# ---------------------------------------------------------------------------
@api.get("/coach/clients/{client_id}/summary")
async def coach_client_summary(client_id: str, _: dict = Depends(require_role("coach"))):
    """Comprehensive client summary. Deterministic — no LLM.

    Frontend uses this for the "Summary" tab in the workspace.
    """
    summary = await _aggregate_summary(client_id)
    return summary


# ---------------------------------------------------------------------------
# Endpoint: LLM narrative briefing (cached)
# ---------------------------------------------------------------------------
def _build_briefing_prompt(payload: dict) -> tuple[str, str]:
    """Return (system, prompt) for the LLM briefing."""
    system = (
        "You are Louis, an elite performance coach at CrewFit specialising in "
        "training airline cabin crew and pilots. Write a short, sharp COACH "
        "BRIEFING paragraph (5–8 sentences, ~120 words) about the client below. "
        "It is read by another coach preparing for a call — NOT the client. "
        "Tone: professional, direct, insight-forward. No hype, no emoji, no "
        "greetings. Reference the client by first name. Highlight: primary "
        "goal & event context, training pattern that suits their roster and "
        "constraints, key risks (injuries, adherence, red flags), and the "
        "single most important thing the coach should focus on this week. "
        "If data is missing, say so briefly rather than inventing. "
        "Return plain text ONLY — no JSON, no markdown headings."
    )
    prompt = (
        "CLIENT CONTEXT (JSON below). Write the briefing now.\n\n"
        f"{json.dumps(payload, default=str, ensure_ascii=False)[:12000]}"
    )
    return system, prompt


@api.post("/coach/clients/{client_id}/summary/briefing")
async def coach_client_summary_briefing(
    client_id: str,
    refresh: bool = Query(False, description="Force LLM regeneration (spends credits)."),
    coach: dict = Depends(require_role("coach")),
):
    """Return a coach-facing narrative briefing paragraph.

    Cached in `db.client_briefings` keyed by client_id + signature of the
    inputs. Only re-generates the LLM output when signature changes or
    the coach explicitly forces refresh.
    """
    summary = await _aggregate_summary(client_id)
    sig = _briefing_signature(
        client=summary["client"],
        event=summary.get("event"),
        counts={
            "adherence_pct": summary["adherence"]["adherence_pct"],
            "avg_rpe": summary["adherence"]["avg_rpe"],
            "active_habits": summary["habits"]["active_count"],
        },
    )
    cached = await db.client_briefings.find_one({"client_id": client_id}, {"_id": 0})
    if cached and not refresh and cached.get("signature") == sig:
        return {
            "briefing": cached.get("briefing"),
            "generated_at": cached.get("generated_at"),
            "model": cached.get("model"),
            "signature": sig,
            "from_cache": True,
        }

    # Build lean payload for the LLM (avoid dumping raw workouts).
    p = summary["client"]["profile"] or {}
    llm_payload = {
        "name": summary["client"].get("name") or "Client",
        "age": p.get("age"),
        "sex": p.get("sex") or p.get("biological_sex"),
        "job_title": p.get("job_title") or p.get("crew_role"),
        "airline": p.get("airline"),
        "home_base": p.get("home_base"),
        "flying_type": p.get("flying_type"),
        "route_focus": p.get("route_focus") or p.get("haul_mix"),
        "primary_goal": _pick(p, "main_goal", "primary_goal", "primary_goal_id", "goal"),
        "goal_notes": p.get("goal_notes") or p.get("main_goal_notes"),
        "secondary_goals": p.get("secondary_goals") or p.get("secondary_goal_ids"),
        "training_days_per_week": _pick(p, "training_days_per_week", "days_per_week", "training_days"),
        "preferred_session_length": _pick(p, "preferred_session_length", "max_home_minutes"),
        "equipment_home": p.get("equipment_home") or p.get("home_equipment") or p.get("equipment"),
        "hotel_gym_reliability": p.get("hotel_gym_reliability") or p.get("hotel_gyms"),
        "injuries": p.get("injuries"),
        "injury_notes": p.get("injury_notes"),
        "no_go_movements": p.get("no_go_movements") or p.get("disliked_exercises"),
        "constraints": p.get("constraints"),
        "event": summary.get("event") and {
            "type": summary["event"].get("event_type") or summary["event"].get("title"),
            "date": summary["event"].get("event_date"),
            "phase_info": summary["event"].get("phase_info"),
            "distance": summary["event"].get("distance"),
            "notes": summary["event"].get("notes"),
        },
        "adherence_28d": summary["adherence"],
        "progression_pill": summary["client"].get("progression_pill"),
        "recent_checkins": [
            {k: c.get(k) for k in ("created_at", "rpe", "sleep", "energy", "mood",
                                    "nutrition", "notes", "adherence")}
            for c in (summary.get("checkins") or [])[:3]
        ],
        "recent_directives": [
            {k: d.get(k) for k in ("id", "text", "priority", "created_at")}
            for d in (summary.get("directives") or [])[-5:]
        ],
        "active_habits": [h.get("title") for h in (summary["habits"].get("top") or [])],
    }

    system, prompt = _build_briefing_prompt(llm_payload)
    try:
        text = await call_claude_tracked(
            user=coach, feature="client_summary_briefing",
            system=system, prompt=prompt, max_out=800, enforce=False,
        )
    except Exception as e:
        logger.warning(f"briefing LLM failed for {client_id}: {e}")
        # Fallback: return a deterministic short summary so UI never breaks.
        first = (summary["client"].get("name") or "Client").split(" ")[0]
        goal = _humanise(str(llm_payload.get("primary_goal") or "general fitness"))
        text = (
            f"{first} — goal: {goal}. "
            f"{llm_payload.get('training_days_per_week') or '?'} training days/week. "
            f"Airline: {llm_payload.get('airline') or 'n/a'}. "
            f"28d adherence: {summary['adherence']['adherence_pct']}%. "
            f"(Briefing generator temporarily unavailable — refresh to retry.)"
        )
    briefing = (text or "").strip()
    now = now_iso()
    doc = {
        "id": (cached or {}).get("id") or new_id(),
        "client_id": client_id,
        "signature": sig,
        "briefing": briefing,
        "generated_at": now,
        "generated_by": coach.get("id"),
        "model": "claude-sonnet-4-5-20250929",
    }
    await db.client_briefings.update_one(
        {"client_id": client_id}, {"$set": doc}, upsert=True,
    )
    return {
        "briefing": briefing,
        "generated_at": now,
        "model": doc["model"],
        "signature": sig,
        "from_cache": False,
    }
