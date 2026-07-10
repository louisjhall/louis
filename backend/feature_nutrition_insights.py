"""feature_nutrition_insights — Nutrition Centre Phase 5.

Closes out the Nutrition Centre spec with three integrated pieces:

    1. Adaptive Weekly Atlas Insights
       Atlas analyses the past 14 days of logs, hydration, targets, hunger and
       roster context, then classifies the client into one of the actions:
         keep | simplify | protein_focus | adjust_calories |
         add_travel_strategy | flag_coach_review
       Result is stored in `nutrition_insights` and (when needed) turned into a
       Coach To-Do task.
    2. Sunday check-in enrichment
       Extra nutrition-only questions injected server-side by
       `nutrition_checkin_questions()` and consumed by the existing check-in
       submit endpoint (no schema change needed — answers land in `answers`).
    3. Coach To-Do integration
       `POST /coach/nutrition/scan-todos` runs the adaptive analyser across
       every client with active nutrition targets and creates dedupe'd
       coach_tasks for anything needing review.

Endpoints:
    POST /nutrition/insights/generate            — client-initiated generate
    GET  /nutrition/insights/latest              — most recent insight
    GET  /nutrition/insights/mine                — history
    GET  /nutrition/checkin/questions            — dynamic nutrition questions
    POST /coach/nutrition/insights/{id}/approve  — coach approves a target change
    POST /coach/nutrition/insights/{id}/dismiss  — coach dismisses
    POST /coach/nutrition/scan-todos             — sweep all clients
    GET  /coach/nutrition/insights/pending       — coach queue
"""
from __future__ import annotations

import os
import json
import re
import datetime as _dt
from typing import Any, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import (
    api, db, current_user, require_admin, new_id, now_iso, logger,
    EMERGENT_LLM_KEY, _create_coach_task,
)
from feature_nutrition import _active_target, _sanitize_target, _today_iso

INSIGHTS_MODEL = os.environ.get("NUTR_INSIGHTS_MODEL", "claude-sonnet-4-5-20250929")

ACTIONS = [
    "keep",
    "simplify",
    "protein_focus",
    "adjust_calories",
    "add_travel_strategy",
    "flag_coach_review",
]

BANNED_WORDS = ("cheat meal", "cheat", "diet", "bad food", "dirty food", "failed")

# ---------------------------------------------------------------------------
# Analytics helpers
# ---------------------------------------------------------------------------

def _sanitise(t: str) -> str:
    out = t or ""
    subs = {
        "cheat meal": "higher-calorie meal",
        "cheat": "flexible choice",
        "diet ": "nutrition ",
        "diets ": "nutrition plans ",
        "bad food": "less-supportive choice",
        "dirty food": "less-supportive choice",
        "failed": "adjusted",
    }
    for k, v in subs.items():
        out = re.sub(k, v, out, flags=re.IGNORECASE)
    return out


def _clean(x: Any) -> Any:
    if isinstance(x, str): return _sanitise(x).strip()
    if isinstance(x, list): return [_clean(v) for v in x]
    if isinstance(x, dict): return {k: _clean(v) for k, v in x.items()}
    return x


async def _analytics(user_id: str, days: int = 14) -> dict:
    """Compute rolling nutrition metrics used by both the insight generator and
    the coach scanner."""
    today = _dt.date.today()
    dates = [(today - _dt.timedelta(days=i)).isoformat() for i in range(days)]
    logs = await db.nutrition_logs.find(
        {"user_id": user_id, "date_local": {"$in": dates}},
        {"_id": 0, "date_local": 1, "calories": 1, "protein_g": 1,
         "meal_type": 1, "source": 1, "roster_context": 1},
    ).to_list(4000)
    hyd = await db.nutrition_hydration.find(
        {"user_id": user_id, "date_local": {"$in": dates}},
        {"_id": 0, "date_local": 1, "amount_ml": 1},
    ).to_list(days + 1)

    per_day: dict[str, dict] = {d: {"cal": 0, "pro": 0.0} for d in dates}
    for r in logs:
        d = r.get("date_local")
        if d in per_day:
            per_day[d]["cal"] += int(r.get("calories") or 0)
            per_day[d]["pro"] += float(r.get("protein_g") or 0)
    hyd_by_day = {r["date_local"]: int(r.get("amount_ml") or 0) for r in hyd}

    days_logged = sum(1 for v in per_day.values() if v["cal"] > 0)
    avg_cal = int(round(sum(v["cal"] for v in per_day.values()) / max(1, days_logged))) if days_logged else 0
    avg_pro = round(sum(v["pro"] for v in per_day.values()) / max(1, days_logged), 1) if days_logged else 0.0

    target = await _active_target(user_id)
    tp = float(target.get("protein_g") or 0)
    tc = float(target.get("calories") or 0)
    th = float(target.get("hydration_ml") or 0)

    low_pro_days = sum(1 for v in per_day.values() if tp and v["cal"] > 0 and v["pro"] < 0.75 * tp)
    low_hyd_days = sum(1 for d in dates if th and hyd_by_day.get(d, 0) < 0.6 * th)
    no_log_days = sum(1 for v in per_day.values() if v["cal"] == 0)
    layover_logs = sum(1 for r in logs if (r.get("roster_context") or "").startswith("layover"))
    photo_scans = sum(1 for r in logs if r.get("source") == "photo")
    barcode_scans = sum(1 for r in logs if r.get("source") == "barcode")

    # Trend: split into first half vs last half (roughly)
    half = days // 2
    early = dates[half:]     # dates is reverse-chronological
    late = dates[:half]
    def sum_pro(subset):
        return sum(per_day[d]["pro"] for d in subset)
    def sum_cal(subset):
        return sum(per_day[d]["cal"] for d in subset)

    pro_trend = "flat"
    if sum_pro(late) > 1.15 * (sum_pro(early) or 1):
        pro_trend = "improving"
    elif sum_pro(late) < 0.85 * (sum_pro(early) or 1):
        pro_trend = "declining"

    return {
        "days_total": days,
        "days_logged": days_logged,
        "no_log_days": no_log_days,
        "avg_calories": avg_cal,
        "avg_protein_g": avg_pro,
        "low_protein_days": low_pro_days,
        "low_hydration_days": low_hyd_days,
        "layover_logs": layover_logs,
        "photo_scans": photo_scans,
        "barcode_scans": barcode_scans,
        "pro_trend": pro_trend,
        "target_calories": tc,
        "target_protein_g": tp,
        "target_hydration_ml": th,
        "goal": target.get("goal") or "general_health",
        "target_is_default": bool(target.get("is_default")),
    }


def _rule_action(a: dict) -> tuple[str, str]:
    """Deterministic fallback action classifier. Returns (action, main_issue)."""
    if a["target_protein_g"] and a["low_protein_days"] >= 6:
        return ("protein_focus", "Protein below 75% of target on 6+ of the last 14 days.")
    if a["goal"] == "fat_loss" and a["no_log_days"] >= 8:
        return ("simplify", "Fat-loss client has logged fewer than half the days — tracking may be too heavy.")
    if a["goal"] == "endurance" and a["low_protein_days"] >= 5:
        return ("protein_focus", "Endurance client is under-fuelling on protein — recovery is at risk.")
    if a["target_is_default"] and a["days_logged"] >= 7:
        return ("adjust_calories", "Client has logged consistently — targets can move from Atlas defaults to a coach-set plan.")
    if a["layover_logs"] >= 4:
        return ("add_travel_strategy", "Multiple layover meals logged — a travel strategy could help.")
    if a["no_log_days"] >= 12:
        return ("flag_coach_review", "Almost no logs in the last 14 days — needs a coach conversation.")
    return ("keep", "Protein and consistency look healthy — keep the current plan.")


async def _call_atlas(prompt: str) -> Optional[dict]:
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"nutr-insight-{new_id()}",
            system_message=(
                "You are Atlas, CrewFit's aviation-nutrition coach. Analyse the "
                "client analytics and return STRICT JSON only. No markdown. Never "
                "diagnose. Never use 'diet', 'cheat', 'failed', 'bad food'. Use "
                "'protein-led', 'timing', 'hydration', 'supportive choice'."
            ),
        ).with_model("anthropic", INSIGHTS_MODEL)
        resp = await chat.send_message(UserMessage(text=prompt))
        text = (resp or "").strip()
        # Strip fences + first JSON block
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```\s*$", "", text)
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m: text = m.group(0)
        return json.loads(text)
    except Exception:
        logger.exception("atlas insight LLM failed")
        return None


async def _build_insight(user: dict, analytics: dict) -> dict:
    fallback_action, fallback_issue = _rule_action(analytics)

    prompt = f"""
Analytics for a CrewFit airline-crew client (14-day window):
{json.dumps(analytics)}

Pick ONE action from this exact list:
{ACTIONS!r}

Return STRICT JSON only:
{{
  "action": "protein_focus",
  "atlas_summary": "One coaching sentence (<= 32 words) summarising the last two weeks.",
  "main_issue": "Short factual statement (<= 20 words).",
  "suggested_action": "What Atlas recommends the coach do next (<= 30 words).",
  "target_change_suggestion": {{ "calories": null, "protein_g": null, "notes": "" }},
  "coach_review_required": true,
  "confidence": "medium"
}}

Rules:
- If action == "keep", coach_review_required MUST be false, target_change_suggestion.notes may be empty.
- If action == "flag_coach_review" or "adjust_calories", coach_review_required MUST be true.
- target_change_suggestion.calories/protein_g may only be numbers if action == "adjust_calories" or "protein_focus". Otherwise null.
- Numbers must respect safety floors (calories >= 1500, protein_g >= 60).
""".strip()

    raw = await _call_atlas(prompt)
    if not raw or raw.get("action") not in ACTIONS:
        raw = {
            "action": fallback_action,
            "atlas_summary": fallback_issue,
            "main_issue": fallback_issue,
            "suggested_action": "Louis to review the last two weeks and confirm the plan for the coming week.",
            "target_change_suggestion": {"calories": None, "protein_g": None, "notes": ""},
            "coach_review_required": fallback_action in ("flag_coach_review", "adjust_calories"),
            "confidence": "low",
        }
    # Force review-required for actions that logically need it.
    if raw["action"] in ("flag_coach_review", "adjust_calories"):
        raw["coach_review_required"] = True
    if raw["action"] == "keep":
        raw["coach_review_required"] = False

    tcs = raw.get("target_change_suggestion") or {}
    # Only allow numeric suggestions for the right actions.
    if raw["action"] not in ("adjust_calories", "protein_focus"):
        tcs = {"calories": None, "protein_g": None, "notes": str(tcs.get("notes") or "")}
    else:
        # Coerce numbers + safety floors.
        c = tcs.get("calories"); p = tcs.get("protein_g")
        try: tcs["calories"] = max(1500, min(5000, int(c))) if c is not None else None
        except Exception: tcs["calories"] = None
        try: tcs["protein_g"] = max(60, min(400, int(p))) if p is not None else None
        except Exception: tcs["protein_g"] = None
        tcs["notes"] = str(tcs.get("notes") or "")

    return _clean({
        "action": raw["action"],
        "atlas_summary": raw.get("atlas_summary", ""),
        "main_issue": raw.get("main_issue", ""),
        "suggested_action": raw.get("suggested_action", ""),
        "target_change_suggestion": tcs,
        "coach_review_required": bool(raw.get("coach_review_required")),
        "confidence": raw.get("confidence") or "medium",
    })


def _week_bounds() -> tuple[str, str]:
    today = _dt.date.today()
    monday = today - _dt.timedelta(days=today.weekday())
    sunday = monday + _dt.timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


async def _persist_insight(user_id: str, analytics: dict, insight: dict,
                            triggered_by: str = "client") -> dict:
    ws, we = _week_bounds()
    doc = {
        "id": new_id(),
        "user_id": user_id,
        "week_start": ws,
        "week_end": we,
        "analytics": analytics,
        "atlas_summary": insight["atlas_summary"],
        "main_issue": insight["main_issue"],
        "action": insight["action"],
        "suggested_action": insight["suggested_action"],
        "target_change_suggestion": insight["target_change_suggestion"],
        "coach_review_required": insight["coach_review_required"],
        "confidence": insight["confidence"],
        "triggered_by": triggered_by,
        "status": "pending" if insight["coach_review_required"] else "info",
        "created_at": now_iso(),
        "reviewed_at": None,
        "reviewed_by": None,
        "reviewer_decision": None,
    }
    # Dedupe: one active insight per user per calendar week.
    await db.nutrition_insights.update_many(
        {"user_id": user_id, "week_start": ws, "status": {"$in": ["pending", "info"]}},
        {"$set": {"status": "superseded", "reviewed_at": now_iso()}},
    )
    await db.nutrition_insights.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# Client endpoints
# ---------------------------------------------------------------------------

class GenerateIn(BaseModel):
    force: bool = False


@api.post("/nutrition/insights/generate")
async def insights_generate(body: GenerateIn, user: dict = Depends(current_user)):
    ws, _we = _week_bounds()
    if not body.force:
        existing = await db.nutrition_insights.find_one(
            {"user_id": user["id"], "week_start": ws, "status": {"$in": ["pending", "info"]}},
            {"_id": 0},
        )
        if existing:
            return {"insight": existing, "cached": True}
    analytics = await _analytics(user["id"], days=14)
    ins = await _build_insight(user, analytics)
    doc = await _persist_insight(user["id"], analytics, ins, triggered_by="client")
    await _maybe_create_task(user, doc)
    return {"insight": doc, "cached": False}


@api.get("/nutrition/insights/latest")
async def insights_latest(user: dict = Depends(current_user)):
    row = await db.nutrition_insights.find_one(
        {"user_id": user["id"], "status": {"$ne": "superseded"}},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    return {"insight": row}


@api.get("/nutrition/insights/mine")
async def insights_mine(limit: int = 12, user: dict = Depends(current_user)):
    limit = max(1, min(50, int(limit)))
    rows = await db.nutrition_insights.find(
        {"user_id": user["id"]}, {"_id": 0}, sort=[("created_at", -1)],
    ).to_list(limit)
    return {"insights": rows}


# ---------------------------------------------------------------------------
# Sunday check-in enrichment
# ---------------------------------------------------------------------------

@api.get("/nutrition/checkin/questions")
async def nutrition_checkin_questions(user: dict = Depends(current_user)):
    """Dynamic nutrition-only questions to inject into the Sunday check-in form.

    The existing /api/checkins/questions call returns core+dynamic sets. To
    keep changes minimal, the client can request THIS endpoint and append the
    returned items to the check-in form under a "Nutrition" heading.
    """
    target = await _active_target(user["id"])
    goal = target.get("goal") or "general_health"
    analytics = await _analytics(user["id"], days=7)

    questions: list[dict] = [
        {"id": "nutr_consistency", "label": "Nutrition consistency this week",
         "type": "choice", "options": ["Very consistent", "Mostly", "Mixed", "Poor", "Not focused on nutrition"]},
        {"id": "nutr_travel_hard", "label": "Did travel make eating harder?",
         "type": "choice", "options": ["No", "Somewhat", "A lot", "N/A"]},
        {"id": "nutr_hunger", "label": "Was hunger manageable?",
         "type": "choice", "options": ["Yes", "Mostly", "Struggled", "Very hard"]},
        {"id": "nutr_protein_hit", "label": "Did you hit protein most days?",
         "type": "choice", "options": ["Yes", "Mostly", "Mixed", "No", "Not tracking protein"]},
        {"id": "nutr_targets_realistic", "label": "Do your nutrition targets feel realistic?",
         "type": "choice", "options": ["Yes", "Too tight", "Too loose", "Louis to review"]},
    ]
    if goal == "fat_loss":
        questions.append({"id": "nutr_fat_loss_env", "label": "Any difficult food environments this week?", "type": "text"})
    if goal == "endurance":
        questions.append({"id": "nutr_endurance_fuelling", "label": "Did you fuel your longer sessions properly?", "type": "choice",
                          "options": ["Yes", "Mostly", "Not really", "Skipped fuelling"]})
    if goal == "muscle_gain":
        questions.append({"id": "nutr_muscle_gain_eating", "label": "Any struggle eating enough for gains?", "type": "choice",
                          "options": ["No", "Somewhat", "Yes", "Very difficult"]})
    if analytics["photo_scans"] + analytics["barcode_scans"] > 0:
        questions.append({"id": "nutr_tools_helpful", "label": "Were photo scan / barcode scanner helpful?", "type": "choice",
                          "options": ["Very", "Somewhat", "Not much", "Haven't used"]})
    return {"questions": questions, "goal": goal}


# ---------------------------------------------------------------------------
# Coach endpoints
# ---------------------------------------------------------------------------

@api.get("/coach/nutrition/insights/pending")
async def coach_insights_pending(admin: dict = Depends(require_admin())):
    rows = await db.nutrition_insights.find(
        {"coach_review_required": True, "status": "pending"},
        {"_id": 0},
        sort=[("created_at", -1)],
    ).to_list(200)
    # Attach the client name/email
    for r in rows:
        u = await db.users.find_one({"id": r["user_id"]}, {"_id": 0, "name": 1, "email": 1})
        r["client_name"] = (u or {}).get("name") or (u or {}).get("email") or "Client"
    return {"insights": rows}


class ApproveIn(BaseModel):
    apply_target_change: bool = True
    notes: Optional[str] = None


@api.post("/coach/nutrition/insights/{insight_id}/approve")
async def coach_insight_approve(insight_id: str, body: ApproveIn, admin: dict = Depends(require_admin())):
    row = await db.nutrition_insights.find_one({"id": insight_id})
    if not row:
        raise HTTPException(404, "not found")
    updates: dict = {"status": "approved", "reviewed_at": now_iso(),
                     "reviewed_by": admin["id"], "reviewer_decision": "approve",
                     "reviewer_notes": (body.notes or "")[:1000]}
    await db.nutrition_insights.update_one({"id": insight_id}, {"$set": updates})

    if body.apply_target_change:
        tcs = row.get("target_change_suggestion") or {}
        patch = {k: v for k, v in tcs.items() if k in ("calories", "protein_g") and v is not None}
        if patch:
            patch = _sanitize_target(patch)
            now = now_iso()
            await db.nutrition_targets.update_many(
                {"user_id": row["user_id"], "active": True},
                {"$set": {"active": False, "active_until": now}},
            )
            target_doc = {
                "id": new_id(), "user_id": row["user_id"], "active": True,
                "active_from": now, "created_by": admin["id"],
                "target_type": "coach_from_atlas",
                "created_at": now, "updated_at": now,
                "notes": f"Applied from Atlas insight ({row['action']}).",
                **patch,
            }
            await db.nutrition_targets.insert_one(target_doc)

    return {"ok": True}


@api.post("/coach/nutrition/insights/{insight_id}/dismiss")
async def coach_insight_dismiss(insight_id: str, admin: dict = Depends(require_admin())):
    r = await db.nutrition_insights.update_one(
        {"id": insight_id},
        {"$set": {"status": "dismissed", "reviewed_at": now_iso(),
                  "reviewed_by": admin["id"], "reviewer_decision": "dismiss"}},
    )
    if not r.matched_count:
        raise HTTPException(404, "not found")
    return {"ok": True}


class ScanIn(BaseModel):
    force: bool = False


@api.post("/coach/nutrition/scan-todos")
async def coach_scan_todos(body: ScanIn, admin: dict = Depends(require_admin())):
    """Sweep every client, generate an insight if none for this week, and
    surface any that need coach review as a Coach To-Do task."""
    created = 0
    scanned = 0
    users = await db.users.find({"role": "client"}, {"_id": 0}).to_list(2000)
    ws, _we = _week_bounds()
    for u in users:
        scanned += 1
        try:
            existing = await db.nutrition_insights.find_one(
                {"user_id": u["id"], "week_start": ws, "status": {"$in": ["pending", "info", "approved", "dismissed"]}},
                {"_id": 0},
            )
            if existing and not body.force:
                doc = existing
            else:
                analytics = await _analytics(u["id"], days=14)
                ins = await _build_insight(u, analytics)
                doc = await _persist_insight(u["id"], analytics, ins, triggered_by="coach_scan")

            if doc.get("coach_review_required") and doc.get("status") == "pending":
                did = await _maybe_create_task(u, doc)
                if did:
                    created += 1
        except Exception:
            logger.exception("scan-todos failed for user %s", u.get("id"))
    return {"scanned": scanned, "tasks_created": created}


# ---------------------------------------------------------------------------
# Coach To-Do dedupe helper
# ---------------------------------------------------------------------------

async def _maybe_create_task(user: dict, insight: dict) -> bool:
    if not insight.get("coach_review_required"):
        return False
    # Dedupe: if a task already exists linked to this insight, do nothing.
    existing = await db.coach_tasks.find_one(
        {"user_id": user["id"], "task_type": "nutrition_review",
         "payload.insight_id": insight["id"]},
        {"_id": 0, "id": 1},
    )
    if existing:
        return False

    title = f"Nutrition review needed for {user.get('name') or user.get('email') or 'client'}"
    action_label = insight["action"].replace("_", " ")
    description = f"{insight['main_issue']} · Atlas action: {action_label}. {insight.get('suggested_action') or ''}".strip()
    payload = {
        "insight_id": insight["id"],
        "action": insight["action"],
        "target_change_suggestion": insight.get("target_change_suggestion"),
        "week_start": insight.get("week_start"),
        "atlas_summary": insight.get("atlas_summary"),
    }
    try:
        await _create_coach_task(
            user, task_type="nutrition_review",
            title=title, description=description,
            priority="normal", category="reviews",
            payload=payload,
        )
        return True
    except Exception:
        logger.exception("could not create nutrition_review coach task")
        return False
