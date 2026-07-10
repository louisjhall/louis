"""
feature_habits — extracted from server.py.
"""
# ---------------------------------------------------------------------------
# Auto-extracted from server.py during 2026-07 refactor.
# Endpoint contracts are IDENTICAL to the pre-refactor version.
# Imports happen from `server` after all shared symbols are defined
# (server imports this module at the very bottom).
# ---------------------------------------------------------------------------

from fastapi import Depends, HTTPException
from typing import Any, Optional
from zoneinfo import ZoneInfo
import datetime as _dt
import json

from server import (
    api,
    db,
    current_user,
    require_role,
    new_id,
    now_iso,
    logger,
    call_claude,
    parse_json_from_text,
    _create_coach_task,
    _current_week_bounds,
    _in_quiet_hours,
    _log_change,
    HabitLogBody,
    HabitCoachCreateBody,
    HabitCoachEditBody,
    HabitReviewApproveBody,
    HabitReviewRejectBody,
    HabitRemindersToggleBody,
)

# --- ORIGINAL SOURCE ---

# ============================================================================
# GOAL-BASED HABIT TRACKING (V1)
#
# Collections:
#   habits          — per-user habit definitions (active + paused + archived)
#   habit_logs      — daily done/skipped/not_possible entries
#   habit_reviews   — weekly Atlas-generated review with recommendations
#
# Principles:
#   * Atlas seeds 3-5 starter habits at end of Coaching DNA.
#   * Habits are day-type-aware — filtered by roster/workout context.
#   * Reviews run after each Sunday check-in; scale up/down/pause/replace/etc.
#   * Coach approves only meaningful changes (respecting coach_controls.auto_approval_risk_threshold).
#   * Skipped or "not possible" never breaks streak — kind by design.
# ============================================================================

MAX_ACTIVE_HABITS_DEFAULT = 5

HABIT_SEED_SYSTEM = (
    "You are Atlas, an assistant coach for CrewFit — a personal training service for airline "
    "cabin crew (pilots + cabin crew). You are drafting the FIRST 3-5 daily habits for a new "
    "client based on their Coaching DNA and lifestyle. Louis (the coach) approves anything major.\n\n"
    "RULES:\n"
    "1. Produce 3, 4 or 5 habits — never more. Fewer is better if the client has heavy roster/injury load.\n"
    "2. Mix: aim for ~2 goal habits, 1 recovery, 1 nutrition, 1 aviation/lifestyle habit if relevant.\n"
    "3. Habits must be simple, specific, realistic, roster-aware.\n"
    "4. Do NOT create workout duplicates (the programme handles training).\n"
    "5. Each habit must link back to a goal or lifestyle need in the DNA.\n"
    "6. Use realistic targets. Start small.\n\n"
    "Return STRICT JSON: { \"habits\": [ { title, reason, linked_goal, habit_type, "
    "day_type_rules, frequency, target, unit, difficulty_level } ] }.\n\n"
    "habit_type values: daily | weekly | training-day-only | rest-day-only | flight-day | "
    "layover-day | home-day | post-flight | pre-flight | recovery-day | after-workout | event-specific | custom.\n"
    "day_type_rules examples: [\"home_day\",\"rest\"], [\"layover_arrival\",\"layover_full\"], [\"flight\",\"duty\"].\n"
    "difficulty_level: starter | standard | stretch.\n"
    "Use British English. Keep title <= 60 chars. Keep reason to one warm supportive sentence."
)

HABIT_REVIEW_SYSTEM = (
    "You are Atlas, running the weekly HABIT REVIEW for a CrewFit client after their Sunday check-in.\n"
    "You are given: their active habits, last 7 days of habit logs, this week's check-in answers, "
    "workout adherence, roster context, coach_controls and any injury flag.\n\n"
    "Recommend adjustments so habits SUPPORT — never overwhelm — the client. Consistency first, "
    "then progression. Never shame. Never keep pushing habits that clearly aren't working.\n\n"
    "Rules:\n"
    "- If completion < 40% for two weeks OR client says habits are too much → SCALE DOWN or PAUSE.\n"
    "- If completion > 80% for two weeks AND client feels good → suggest small SCALE UP.\n"
    "- If a habit is repeatedly skipped for the same environmental reason (layover, night flight, "
    "no equipment, family) → REPLACE with something that fits.\n"
    "- Injury/pain reported → PAUSE loading habits, require coach review.\n"
    "- Never exceed 5 active habits total after applying changes.\n"
    "- Assign risk_level: low (frequency tweak, wording, day-scope) | medium (target change, replace, "
    "add habit, pause) | high (injury-related change, event-window change).\n\n"
    "Return STRICT JSON with keys:\n"
    "  atlas_summary          — one-line reassurance-first summary Atlas will show the client\n"
    "  coach_summary          — one-line summary Atlas will show Louis if approval needed\n"
    "  completion_rate        — 0.0 to 1.0 across all habits this week (compute from logs)\n"
    "  what_worked            — string\n"
    "  what_did_not           — string\n"
    "  recommendations        — array of { habit_id, action, change, reason, risk_level, "
    "                             new_target?, new_frequency?, new_day_type_rules?, new_title?, new_reason?, replacement? }\n"
    "  new_habits             — array of { title, reason, linked_goal, habit_type, day_type_rules, "
    "                             frequency, target, unit, difficulty_level, risk_level }\n"
    "  requires_coach_review  — boolean (true if ANY recommendation is medium/high risk OR injury-related)\n"
    "action values: keep | scale_down | scale_up | pause | resume | replace | simplify | make_specific | remove.\n"
    "Use British English. Warm, non-judgemental."
)


# ---- Helpers ---------------------------------------------------------------

def _today_local_str(user: dict) -> str:
    tz_name = user.get("current_time_zone") or user.get("home_time_zone") or "Europe/London"
    try:
        tz = ZoneInfo(tz_name)
        return _dt.datetime.now(tz).date().isoformat()
    except Exception:
        return _dt.datetime.utcnow().date().isoformat()


def _clean_habit_row(h: dict) -> dict:
    h.pop("_id", None)
    return h


def _habit_relevant_today(habit: dict, day_type: Optional[str], has_workout: bool, is_flight_day: bool) -> bool:
    """Decide whether a habit should appear on the client's home screen today."""
    ht = (habit.get("habit_type") or "daily").lower()
    dt = (day_type or "").lower()
    rules = [r.lower() for r in (habit.get("day_type_rules") or [])]
    if ht == "daily":
        return True
    if ht == "weekly":
        # Weekly habits show every day so the client can tick them off at any point
        return True
    if ht in ("training-day-only", "training-day", "after-workout"):
        return has_workout
    if ht in ("rest-day-only", "rest-day", "recovery-day", "recovery-day-only"):
        return any(k in dt for k in ("rest", "home_day", "home training", "annual leave"))
    if ht in ("flight-day", "flight-day-only", "pre-flight"):
        return is_flight_day
    if ht in ("post-flight",):
        return is_flight_day or any(k in dt for k in ("layover", "flight"))
    if ht in ("layover-day", "layover-day-only"):
        return "layover" in dt
    if ht in ("home-day", "home-day-only"):
        return "home_day" in dt or "home" in dt or "rest" in dt
    if ht in ("event-specific",):
        return True  # calendar filters this elsewhere
    # custom or unknown → obey day_type_rules if provided, otherwise show daily
    if rules:
        return any(r in dt for r in rules)
    return True


def _is_flight_day(day_type: Optional[str]) -> bool:
    dt = (day_type or "").lower()
    return any(k in dt for k in ("flight", "duty", "standby", "layover"))


def _log_effective_status_counts(logs: list[dict]) -> tuple[int, int, int, int]:
    """(done, skipped, not_possible, total_qualifying) where qualifying excludes not_possible for completion calc."""
    done = sum(1 for l in logs if l.get("status") == "done")
    skipped = sum(1 for l in logs if l.get("status") == "skipped")
    not_possible = sum(1 for l in logs if l.get("status") == "not_possible")
    total = done + skipped  # not_possible ignored for completion — kind design
    return done, skipped, not_possible, total


async def _compute_streak(habit_id: str, user_id: str, tz_name: str) -> int:
    """Preserve streak on skipped/not_possible per user's requirement (option b).
    Count backwards from today: consecutive days where the habit was DONE, SKIPPED or NOT_POSSIBLE.
    A streak breaks only when a day has ZERO log and the habit was expected that day.
    """
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Europe/London")
    today = _dt.datetime.now(tz).date()
    logs = await db.habit_logs.find(
        {"habit_id": habit_id, "user_id": user_id}, {"_id": 0}
    ).sort("date_local", -1).to_list(180)
    log_by_date = {l["date_local"]: l for l in logs}
    streak = 0
    for i in range(0, 60):
        d = (today - _dt.timedelta(days=i)).isoformat()
        if d in log_by_date:
            streak += 1
        else:
            # allow first missing day if today isn't logged yet
            if i == 0:
                continue
            break
    return streak


# ---- Atlas seeding ---------------------------------------------------------

def _default_habit_pack(dna: dict) -> list[dict]:
    """Deterministic fallback pack if the LLM call fails — always shippable."""
    goals = [str(g).lower() for g in (dna.get("primary_goals") or [])]
    packs: list[dict] = []
    if any(k in " ".join(goals) for k in ("fat", "loss", "leaner", "cutting", "weight")):
        packs.append({"title": "Protein with first meal", "reason": "Supports fat loss, appetite control and muscle retention.", "linked_goal": "fat_loss", "habit_type": "daily", "day_type_rules": [], "frequency": "daily", "target": "1 palm of protein", "unit": "portion", "difficulty_level": "starter"})
    else:
        packs.append({"title": "Protein with first meal", "reason": "Sets recovery + energy up early in your day.", "linked_goal": (goals[0] if goals else "general"), "habit_type": "daily", "day_type_rules": [], "frequency": "daily", "target": "1 palm of protein", "unit": "portion", "difficulty_level": "starter"})
    packs.append({"title": "8,000 steps on home days", "reason": "Keeps daily movement up without adding gym time.", "linked_goal": (goals[0] if goals else "general_health"), "habit_type": "home-day", "day_type_rules": ["home_day","rest","annual leave"], "frequency": "daily", "target": "8000", "unit": "steps", "difficulty_level": "starter"})
    packs.append({"title": "Hydrate after landing", "reason": "Supports recovery after flying.", "linked_goal": "recovery", "habit_type": "post-flight", "day_type_rules": ["layover","flight","layover_arrival"], "frequency": "per_flight", "target": "500ml", "unit": "ml", "difficulty_level": "starter"})
    packs.append({"title": "5-minute mobility after duty", "reason": "Reduces stiffness after flights and layovers.", "linked_goal": "mobility", "habit_type": "post-flight", "day_type_rules": ["layover","flight","standby"], "frequency": "per_flight", "target": "5", "unit": "minutes", "difficulty_level": "starter"})
    packs.append({"title": "Sunday weekly check-in", "reason": "Keeps Atlas + Louis honest about your week.", "linked_goal": "coaching", "habit_type": "weekly", "day_type_rules": [], "frequency": "weekly", "target": "1", "unit": "check-in", "difficulty_level": "starter"})
    return packs[:5]


async def _atlas_seed_habits(user: dict) -> list[dict]:
    dna = await db.coaching_dna.find_one({"user_id": user["id"]}, {"_id": 0}, sort=[("version", -1)])
    ctx = {
        "client_name": user.get("name"),
        "crew_role": user.get("crew_role"),
        "primary_goals": (dna or {}).get("primary_goals"),
        "obstacles": (dna or {}).get("obstacles"),
        "training_style": (dna or {}).get("training_style"),
        "coaching_style": (dna or {}).get("coaching_style"),
        "injury_history": (dna or {}).get("injury_history"),
        "event_timeline": (dna or {}).get("event_timeline"),
        "sleep_notes": (dna or {}).get("sleep_notes"),
        "nutrition_notes": (dna or {}).get("nutrition_notes"),
    }
    parsed: dict[str, Any] = {}
    try:
        raw = await call_claude(HABIT_SEED_SYSTEM, "Seed the starter habits for this client.\n\nDNA CONTEXT:\n" + json.dumps(ctx, default=str)[:5000], max_out=1400)
        parsed = parse_json_from_text(raw) or {}
    except Exception:
        logger.exception("Atlas habit seeding LLM failed — using deterministic pack")
    habits = parsed.get("habits") if isinstance(parsed, dict) else None
    if not isinstance(habits, list) or not habits:
        habits = _default_habit_pack(dna or {})
    return habits[:MAX_ACTIVE_HABITS_DEFAULT]


async def _seed_habits_for_user_by_id(user_id: str) -> int:
    user = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not user:
        return 0
    # Idempotent — skip if the user already has any active habits
    existing = await db.habits.count_documents({"user_id": user_id, "status": {"$in": ["active", "paused"]}})
    if existing:
        return 0
    habits = await _atlas_seed_habits(user)
    now = now_iso()
    docs = []
    for h in habits:
        docs.append({
            "id": new_id(),
            "user_id": user_id,
            "coach_id": None,
            "title": (h.get("title") or "").strip()[:80],
            "reason": (h.get("reason") or "").strip(),
            "linked_goal": h.get("linked_goal") or "general",
            "habit_type": h.get("habit_type") or "daily",
            "day_type_rules": h.get("day_type_rules") or [],
            "frequency": h.get("frequency") or "daily",
            "target": h.get("target"),
            "unit": h.get("unit"),
            "difficulty_level": h.get("difficulty_level") or "starter",
            "status": "active",
            "current_level": 1,
            "created_by": "atlas",
            "requires_coach_approval": False,
            "approved_by": "atlas",
            "created_at": now,
            "updated_at": now,
            "paused_at": None,
            "deleted_at": None,
        })
    if docs:
        await db.habits.insert_many(docs)
    await _log_change(None, user_id, "programme",
                      f"Atlas seeded {len(docs)} starter habits", "", actor="atlas",
                      meta={"count": len(docs)})
    return len(docs)


# ---- Habit review ----------------------------------------------------------

async def _run_habit_review_after_checkin(user_id: str, checkin_id: str, ws: str, we: str) -> None:
    try:
        user = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
        if not user:
            return
        habits = await db.habits.find({"user_id": user_id, "status": "active"}, {"_id": 0}).to_list(50)
        if not habits:
            return
        habit_ids = [h["id"] for h in habits]
        logs = await db.habit_logs.find(
            {"user_id": user_id, "habit_id": {"$in": habit_ids}, "date_local": {"$gte": ws, "$lte": we}}, {"_id": 0}
        ).to_list(1000)
        by_habit: dict[str, list[dict]] = {hid: [] for hid in habit_ids}
        for l in logs:
            by_habit.setdefault(l["habit_id"], []).append(l)
        stats = []
        total_done, total_expected = 0, 0
        for h in habits:
            hlogs = by_habit.get(h["id"], [])
            done, skipped, np_, total = _log_effective_status_counts(hlogs)
            total_done += done
            total_expected += (total or 1)
            stats.append({
                "habit_id": h["id"], "title": h["title"], "habit_type": h["habit_type"],
                "linked_goal": h.get("linked_goal"),
                "done": done, "skipped": skipped, "not_possible": np_,
                "completion": (done / total) if total else 0.0,
                "skipped_reasons": [l.get("reason") for l in hlogs if l.get("status") == "skipped" and l.get("reason")],
                "not_possible_reasons": [l.get("reason") for l in hlogs if l.get("status") == "not_possible" and l.get("reason")],
                "notes": [l.get("note") for l in hlogs if l.get("note")],
            })
        checkin = await db.check_ins.find_one({"id": checkin_id}, {"_id": 0})
        controls = user.get("coach_controls") or {}
        ctx = {
            "client_name": user.get("name"),
            "crew_role": user.get("crew_role"),
            "week_start": ws, "week_end": we,
            "habits": stats,
            "check_in_answers": (checkin or {}).get("answers"),
            "energy": (checkin or {}).get("energy_score"),
            "sleep": (checkin or {}).get("sleep_score"),
            "stress": (checkin or {}).get("stress_score"),
            "recovery": (checkin or {}).get("recovery_score"),
            "training_adherence": (checkin or {}).get("training_adherence"),
            "injury_flag": (checkin or {}).get("injury_flag"),
            "urgent_safety_flag": (checkin or {}).get("urgent_safety_flag"),
            "nutrition_flag": (checkin or {}).get("nutrition_flag"),
            "coach_controls": {
                "injury_caution": controls.get("injury_caution", "medium"),
                "progression_speed": controls.get("progression_speed", "standard"),
                "auto_approval_risk_threshold": controls.get("auto_approval_risk_threshold", "none"),
            },
        }
        parsed: dict[str, Any] = {}
        try:
            raw = await call_claude(HABIT_REVIEW_SYSTEM,
                                    "Run the weekly habit review for this client.\n\nCONTEXT:\n" + json.dumps(ctx, default=str)[:8000],
                                    max_out=2000)
            parsed = parse_json_from_text(raw) or {}
        except Exception:
            logger.exception("habit review LLM failed")
        recs = parsed.get("recommendations") or []
        new_habits = parsed.get("new_habits") or []
        rate = float(parsed.get("completion_rate") or ((total_done / total_expected) if total_expected else 0.0))
        requires_review = bool(parsed.get("requires_coach_review"))
        # Determine automatic vs coach-review based on coach_controls.auto_approval_risk_threshold
        threshold = (controls.get("auto_approval_risk_threshold") or "none").lower()
        auto_apply_low = threshold in ("low", "low_medium")
        auto_apply_medium = threshold == "low_medium"
        # If any injury-related recommendation exists → force coach review
        any_high = any((r.get("risk_level") == "high") for r in recs) or any(("injur" in (r.get("reason") or "").lower()) for r in recs)
        any_medium = any((r.get("risk_level") == "medium") for r in recs)
        any_low = any((r.get("risk_level") == "low") for r in recs)
        coach_review_required = requires_review or any_high or (any_medium and not auto_apply_medium) or (any_low and not auto_apply_low)
        review_doc = {
            "id": new_id(),
            "user_id": user_id,
            "user_name": user.get("name") or user.get("email"),
            "check_in_id": checkin_id,
            "week_start": ws,
            "week_end": we,
            "completion_rate": round(rate, 3),
            "atlas_summary": parsed.get("atlas_summary") or "Habits reviewed for this week.",
            "coach_summary": parsed.get("coach_summary") or "Weekly habit review ready.",
            "what_worked": parsed.get("what_worked") or "",
            "what_did_not": parsed.get("what_did_not") or "",
            "stats": stats,
            "recommendations": recs,
            "new_habits": new_habits,
            "coach_review_required": coach_review_required,
            "coach_review_status": "pending" if coach_review_required else "auto_applied",
            "reviewed_by": None,
            "reviewed_at": None,
            "created_at": now_iso(),
            "applied_at": None,
        }
        await db.habit_reviews.insert_one(review_doc)
        # If no coach review required → auto-apply now
        if not coach_review_required:
            await _apply_habit_review(review_doc, actor="atlas")
        else:
            # Create a coach To-Do task for this review
            risk = "high" if any_high else ("medium" if any_medium else "low")
            priority = "urgent" if any_high else ("high" if any_medium else "normal")
            await _create_coach_task(user, "habit_review",
                                     f"Habit review needed for {user.get('name') or user.get('email')}",
                                     (parsed.get("coach_summary") or "Atlas has prepared habit changes.")[:220],
                                     priority=priority,
                                     risk_level=risk,
                                     category="programme",
                                     check_in_id=checkin_id,
                                     payload={"habit_review_id": review_doc["id"]})
        await _log_change(None, user_id, "programme",
                          "Weekly habit review",
                          review_doc["atlas_summary"], actor="atlas",
                          meta={"review_id": review_doc["id"], "coach_review_required": coach_review_required,
                                "completion_rate": review_doc["completion_rate"]})
    except Exception:
        logger.exception("_run_habit_review_after_checkin failed")


async def _apply_habit_review(review: dict, actor: str = "coach", coach_id: Optional[str] = None) -> dict:
    user_id = review["user_id"]
    now = now_iso()
    applied = {"updated": 0, "paused": 0, "resumed": 0, "removed": 0, "created": 0}
    # Apply recommendations
    for r in (review.get("recommendations") or []):
        hid = r.get("habit_id")
        action = (r.get("action") or "").lower()
        if not hid or action == "keep":
            continue
        updates: dict[str, Any] = {"updated_at": now, "last_review_id": review["id"]}
        if action in ("scale_down", "scale_up", "simplify", "make_specific", "replace"):
            if r.get("new_title"): updates["title"] = r["new_title"]
            if r.get("new_reason"): updates["reason"] = r["new_reason"]
            if r.get("new_target") is not None: updates["target"] = r["new_target"]
            if r.get("new_frequency"): updates["frequency"] = r["new_frequency"]
            if r.get("new_day_type_rules") is not None: updates["day_type_rules"] = r["new_day_type_rules"]
            if action == "scale_down": updates["difficulty_level"] = "starter"
            if action == "scale_up": updates["difficulty_level"] = "standard"
            if action == "replace" and r.get("replacement"):
                rep = r["replacement"]
                if isinstance(rep, dict):
                    if rep.get("title"): updates["title"] = rep["title"]
                    if rep.get("reason"): updates["reason"] = rep["reason"]
                    if rep.get("habit_type"): updates["habit_type"] = rep["habit_type"]
                    if rep.get("day_type_rules") is not None: updates["day_type_rules"] = rep["day_type_rules"]
                    if rep.get("target") is not None: updates["target"] = rep["target"]
                    if rep.get("unit"): updates["unit"] = rep["unit"]
            applied["updated"] += 1
        elif action == "pause":
            updates.update({"status": "paused", "paused_at": now})
            applied["paused"] += 1
        elif action == "resume":
            updates.update({"status": "active", "paused_at": None})
            applied["resumed"] += 1
        elif action == "remove":
            updates.update({"status": "archived", "deleted_at": now})
            applied["removed"] += 1
        await db.habits.update_one({"id": hid, "user_id": user_id}, {"$set": updates})
    # Add new habits (respect max)
    active_count = await db.habits.count_documents({"user_id": user_id, "status": "active"})
    for nh in (review.get("new_habits") or []):
        if active_count >= MAX_ACTIVE_HABITS_DEFAULT:
            break
        doc = {
            "id": new_id(),
            "user_id": user_id,
            "coach_id": coach_id,
            "title": (nh.get("title") or "").strip()[:80],
            "reason": nh.get("reason") or "",
            "linked_goal": nh.get("linked_goal") or "general",
            "habit_type": nh.get("habit_type") or "daily",
            "day_type_rules": nh.get("day_type_rules") or [],
            "frequency": nh.get("frequency") or "daily",
            "target": nh.get("target"),
            "unit": nh.get("unit"),
            "difficulty_level": nh.get("difficulty_level") or "starter",
            "status": "active",
            "current_level": 1,
            "created_by": actor,
            "requires_coach_approval": False,
            "approved_by": actor,
            "created_at": now,
            "updated_at": now,
            "paused_at": None,
            "deleted_at": None,
            "last_review_id": review["id"],
        }
        await db.habits.insert_one(doc)
        active_count += 1
        applied["created"] += 1
    await db.habit_reviews.update_one({"id": review["id"]}, {"$set": {
        "coach_review_status": "auto_applied" if actor == "atlas" else "approved",
        "applied_at": now,
        "reviewed_by": coach_id or actor,
        "reviewed_at": now,
    }})
    return applied


# ---- Client endpoints ------------------------------------------------------

@api.post("/habits/seed")
async def habits_seed(user: dict = Depends(current_user)):
    """Idempotent: seed 3-5 starter habits (used if the DNA-finalize hook missed)."""
    seeded = await _seed_habits_for_user_by_id(user["id"])
    return {"seeded": seeded}


@api.get("/habits/today")
async def habits_today(user: dict = Depends(current_user)):
    today = _today_local_str(user)
    # Determine today's roster day-type + whether there's a workout
    todays_wk = await db.workouts.find_one({"user_id": user["id"], "date": today}, {"_id": 0, "day_type": 1, "id": 1, "completed": 1})
    day_type = (todays_wk or {}).get("day_type")
    if not day_type:
        # try roster
        roster = await db.rosters.find_one({"user_id": user["id"], "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
        if roster:
            for d in roster.get("days", []):
                if d.get("date") == today:
                    day_type = d.get("type") or d.get("day_type")
                    break
    is_flight = _is_flight_day(day_type)
    habits = await db.habits.find({"user_id": user["id"], "status": "active"}, {"_id": 0}).to_list(50)
    habits = [h for h in habits if _habit_relevant_today(h, day_type, bool(todays_wk), is_flight)]
    # Load today's logs
    logs = await db.habit_logs.find(
        {"user_id": user["id"], "habit_id": {"$in": [h["id"] for h in habits]}, "date_local": today}, {"_id": 0}
    ).to_list(50)
    log_by_habit = {l["habit_id"]: l for l in logs}
    tz_name = user.get("current_time_zone") or user.get("home_time_zone") or "Europe/London"
    for h in habits:
        h["today_log"] = log_by_habit.get(h["id"])
        h["streak"] = await _compute_streak(h["id"], user["id"], tz_name)
    return {"habits": habits, "date_local": today, "day_type": day_type, "flight_day": is_flight}


@api.get("/habits/mine")
async def habits_mine(user: dict = Depends(current_user)):
    active = await db.habits.find({"user_id": user["id"], "status": "active"}, {"_id": 0}).sort("created_at", 1).to_list(50)
    paused = await db.habits.find({"user_id": user["id"], "status": "paused"}, {"_id": 0}).sort("paused_at", -1).to_list(50)
    tz_name = user.get("current_time_zone") or user.get("home_time_zone") or "Europe/London"
    for h in active:
        h["streak"] = await _compute_streak(h["id"], user["id"], tz_name)
    return {"active": active, "paused": paused}


@api.post("/habits/{habit_id}/log")
async def habits_log(habit_id: str, body: HabitLogBody, user: dict = Depends(current_user)):
    if body.status not in ("done", "skipped", "not_possible"):
        raise HTTPException(400, "invalid status")
    h = await db.habits.find_one({"id": habit_id, "user_id": user["id"]}, {"_id": 0, "id": 1})
    if not h:
        raise HTTPException(404, "habit not found")
    date_local = body.date_local or _today_local_str(user)
    tz_name = body.time_zone or user.get("current_time_zone") or user.get("home_time_zone") or "Europe/London"
    now = now_iso()
    # Upsert on (habit_id, user_id, date_local)
    set_doc = {
        "log_id": new_id(),
        "habit_id": habit_id,
        "user_id": user["id"],
        "date_local": date_local,
        "time_zone": tz_name,
        "status": body.status,
        "reason": body.reason,
        "note": body.note,
        "updated_at": now,
    }
    await db.habit_logs.update_one(
        {"habit_id": habit_id, "user_id": user["id"], "date_local": date_local},
        {"$set": set_doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    saved = await db.habit_logs.find_one({"habit_id": habit_id, "user_id": user["id"], "date_local": date_local}, {"_id": 0})
    streak = await _compute_streak(habit_id, user["id"], tz_name)
    return {"log": saved, "streak": streak}


@api.get("/habits/{habit_id}/logs")
async def habits_logs(habit_id: str, user: dict = Depends(current_user), limit: int = 90):
    h = await db.habits.find_one({"id": habit_id, "user_id": user["id"]}, {"_id": 0, "id": 1})
    if not h:
        raise HTTPException(404, "habit not found")
    rows = await db.habit_logs.find({"habit_id": habit_id, "user_id": user["id"]}, {"_id": 0}).sort("date_local", -1).to_list(limit)
    return {"logs": rows}


@api.post("/habits/reminders/toggle")
async def habits_reminders_toggle(body: HabitRemindersToggleBody, user: dict = Depends(current_user)):
    await db.users.update_one({"id": user["id"]}, {"$set": {"habit_reminders_enabled": bool(body.enabled)}})
    return {"enabled": bool(body.enabled)}


@api.get("/habits/reviews/latest")
async def habits_reviews_latest(user: dict = Depends(current_user)):
    r = await db.habit_reviews.find_one({"user_id": user["id"]}, {"_id": 0}, sort=[("created_at", -1)])
    return {"review": r}


# ---- Coach endpoints -------------------------------------------------------

@api.get("/coach/clients/{client_id}/habits")
async def coach_habits_get(client_id: str, coach: dict = Depends(require_role("coach"))):
    client = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(404, "client not found")
    active = await db.habits.find({"user_id": client_id, "status": "active"}, {"_id": 0}).sort("created_at", 1).to_list(50)
    paused = await db.habits.find({"user_id": client_id, "status": "paused"}, {"_id": 0}).sort("paused_at", -1).to_list(50)
    archived = await db.habits.find({"user_id": client_id, "status": "archived"}, {"_id": 0}).sort("deleted_at", -1).to_list(30)
    tz_name = client.get("current_time_zone") or client.get("home_time_zone") or "Europe/London"
    # Compute simple 4-week completion + last-7-day trend
    ws_all = [d for d in [ (_dt.datetime.utcnow().date() - _dt.timedelta(days=i)).isoformat() for i in range(28) ] ]
    all_logs = await db.habit_logs.find({"user_id": client_id, "date_local": {"$in": ws_all}}, {"_id": 0}).to_list(2000)
    completion = {}
    for h in active:
        hlogs = [l for l in all_logs if l["habit_id"] == h["id"]]
        d, s, np_, tot = _log_effective_status_counts(hlogs)
        completion[h["id"]] = {"done": d, "skipped": s, "not_possible": np_, "rate": (d / tot) if tot else 0.0}
        h["streak"] = await _compute_streak(h["id"], client_id, tz_name)
    latest_review = await db.habit_reviews.find_one({"user_id": client_id}, {"_id": 0}, sort=[("created_at", -1)])
    pending_review = await db.habit_reviews.find_one({"user_id": client_id, "coach_review_status": "pending"}, {"_id": 0}, sort=[("created_at", -1)])
    return {
        "active": active, "paused": paused, "archived": archived,
        "completion": completion,
        "latest_review": latest_review,
        "pending_review": pending_review,
    }


@api.post("/coach/clients/{client_id}/habits")
async def coach_habit_create(client_id: str, body: HabitCoachCreateBody, coach: dict = Depends(require_role("coach"))):
    # Enforce max active habits (coach can still add if some are paused/archived)
    active_count = await db.habits.count_documents({"user_id": client_id, "status": "active"})
    if active_count >= MAX_ACTIVE_HABITS_DEFAULT:
        raise HTTPException(400, f"client already has {MAX_ACTIVE_HABITS_DEFAULT} active habits — pause or archive one first")
    now = now_iso()
    doc = {
        "id": new_id(),
        "user_id": client_id,
        "coach_id": coach["id"],
        "title": body.title[:80],
        "reason": body.reason or "",
        "linked_goal": body.linked_goal or "coach_defined",
        "habit_type": body.habit_type or "daily",
        "day_type_rules": body.day_type_rules or [],
        "frequency": body.frequency or "daily",
        "target": body.target,
        "unit": body.unit,
        "difficulty_level": body.difficulty_level or "starter",
        "status": "active",
        "current_level": 1,
        "created_by": "coach",
        "requires_coach_approval": False,
        "approved_by": coach["id"],
        "created_at": now,
        "updated_at": now,
        "paused_at": None,
        "deleted_at": None,
    }
    await db.habits.insert_one(doc)
    await _log_change(coach["id"], client_id, "programme",
                      f"Coach added habit: {doc['title']}", doc["reason"], actor="coach",
                      meta={"habit_id": doc["id"]})
    doc.pop("_id", None)
    return {"habit": doc}


@api.patch("/coach/habits/{habit_id}")
async def coach_habit_patch(habit_id: str, body: HabitCoachEditBody, coach: dict = Depends(require_role("coach"))):
    h = await db.habits.find_one({"id": habit_id}, {"_id": 0})
    if not h:
        raise HTTPException(404, "habit not found")
    updates: dict[str, Any] = {"updated_at": now_iso()}
    for k in ("title", "reason", "target", "unit", "frequency", "habit_type", "day_type_rules", "difficulty_level"):
        v = getattr(body, k)
        if v is not None:
            updates[k] = v
    if body.status is not None:
        updates["status"] = body.status
        if body.status == "paused":
            updates["paused_at"] = now_iso()
        elif body.status == "archived":
            updates["deleted_at"] = now_iso()
        elif body.status == "active":
            updates["paused_at"] = None
    if len(updates) == 1:
        raise HTTPException(400, "no updates")
    await db.habits.update_one({"id": habit_id}, {"$set": updates})
    saved = await db.habits.find_one({"id": habit_id}, {"_id": 0})
    await _log_change(coach["id"], h["user_id"], "programme",
                      f"Coach edited habit: {saved['title']}", "", actor="coach",
                      meta={"habit_id": habit_id, "diff": {k: v for k, v in updates.items() if k != "updated_at"}})
    return {"habit": saved}


@api.post("/coach/habits/reviews/{review_id}/approve")
async def coach_habit_review_approve(review_id: str, body: HabitReviewApproveBody, coach: dict = Depends(require_role("coach"))):
    r = await db.habit_reviews.find_one({"id": review_id}, {"_id": 0})
    if not r:
        raise HTTPException(404, "review not found")
    if r.get("coach_review_status") not in ("pending", None):
        raise HTTPException(400, "review already resolved")
    if body.modified_recommendations is not None:
        r["recommendations"] = body.modified_recommendations
    applied = await _apply_habit_review(r, actor="coach", coach_id=coach["id"])
    await db.habit_reviews.update_one({"id": review_id}, {"$set": {"coach_note": body.coach_note or ""}})
    # Resolve related coach task
    await db.coach_tasks.update_many(
        {"payload.habit_review_id": review_id, "status": {"$in": ["todo", "in_progress"]}},
        {"$set": {"status": "done", "completed_at": now_iso()}},
    )
    await _log_change(coach["id"], r["user_id"], "programme",
                      f"Coach approved habit review · {applied.get('updated', 0)} updated, {applied.get('created', 0)} new",
                      body.coach_note or "", actor="coach",
                      meta={"review_id": review_id, "applied": applied})
    saved = await db.habit_reviews.find_one({"id": review_id}, {"_id": 0})
    return {"review": saved, "applied": applied}


@api.post("/coach/habits/reviews/{review_id}/reject")
async def coach_habit_review_reject(review_id: str, body: HabitReviewRejectBody, coach: dict = Depends(require_role("coach"))):
    r = await db.habit_reviews.find_one({"id": review_id}, {"_id": 0})
    if not r:
        raise HTTPException(404, "review not found")
    if r.get("coach_review_status") not in ("pending", None):
        raise HTTPException(400, "review already resolved")
    now = now_iso()
    await db.habit_reviews.update_one({"id": review_id}, {"$set": {
        "coach_review_status": "rejected",
        "reviewed_by": coach["id"],
        "reviewed_at": now,
        "coach_note": body.coach_note or "",
    }})
    await db.coach_tasks.update_many(
        {"payload.habit_review_id": review_id, "status": {"$in": ["todo", "in_progress"]}},
        {"$set": {"status": "dismissed", "dismissed_at": now, "completed_at": now}},
    )
    await _log_change(coach["id"], r["user_id"], "programme",
                      "Coach rejected habit review", body.coach_note or "", actor="coach",
                      meta={"review_id": review_id})
    return {"ok": True}


# ---- Reminder integration --------------------------------------------------

async def _tick_habit_reminders() -> None:
    """Enqueue at most one habit reminder per user per day, respecting quiet hours + toggle."""
    users = await db.users.find({"role": "client"}, {"_id": 0, "password_hash": 0}).to_list(2000)
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    for u in users:
        try:
            if u.get("habit_reminders_enabled") is False:
                continue
            tz_name = u.get("current_time_zone") or u.get("home_time_zone") or "Europe/London"
            try: tz = ZoneInfo(tz_name)
            except Exception: continue
            local_now = now_utc.astimezone(tz)
            # Send at 10:00 local, ±10min
            if local_now.hour != 10 or not (0 <= local_now.minute < 10):
                continue
            if _in_quiet_hours(local_now, u.get("quiet_hours_start", "21:00"), u.get("quiet_hours_end", "07:00")):
                continue
            date_local = local_now.date().isoformat()
            # skip if we already queued a habit reminder for this user today
            if await db.scheduled_messages.find_one({"user_id": u["id"], "message_type": "habit_daily", "date_local": date_local}, {"id": 1}):
                continue
            # Do the client have any relevant habits today? (rough check by day-type from today's workout)
            todays_wk = await db.workouts.find_one({"user_id": u["id"], "date": date_local}, {"_id": 0, "day_type": 1})
            day_type = (todays_wk or {}).get("day_type")
            is_flight = _is_flight_day(day_type)
            habits = await db.habits.find({"user_id": u["id"], "status": "active"}, {"_id": 0}).to_list(20)
            relevant = [h for h in habits if _habit_relevant_today(h, day_type, bool(todays_wk), is_flight)]
            if not relevant:
                continue
            body = f"Your habits today: {relevant[0]['title']}" + (f" · +{len(relevant)-1} more" if len(relevant) > 1 else "")
            await db.scheduled_messages.insert_one({
                "id": new_id(),
                "user_id": u["id"],
                "message_type": "habit_daily",
                "date_local": date_local,
                "title": "Habits today",
                "body": body,
                "scheduled_time_zone": tz_name,
                "scheduled_local_datetime": local_now.isoformat(),
                "scheduled_utc_datetime": now_utc.isoformat(),
                "status": "ready",
                "quiet_hours_checked": True,
                "created_at": now_iso(),
                "sent_at": None,
                "cancelled_at": None,
                "delivery_attempts": 0,
            })
        except Exception:
            logger.exception("habit reminder tick failed for a user")


# Extend the existing reminder loop by also ticking habit reminders each cycle.
# NOTE: post-refactor the composition happens in server.py (after all feature
# modules load) — this module only exposes `_tick_habit_reminders`.



