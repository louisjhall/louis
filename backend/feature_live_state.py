"""
feature_live_state — Phase 2: Living Profile Wire-Back.

Turns each check-in submission into structured signals and rolls them up into
a compact "live_state" snapshot on users.profile that the plan builder consumes
before every roster/workout generation.

Signals extracted per check-in:
  * energy_delta         — normalised 1-10 rating vs. baseline of 5
  * sleep_score          — 1-10
  * soreness_score       — 1-10 (higher = more sore)
  * stress_score         — 1-10
  * rpe_trend            — computed from workouts.rpe last 14d
  * adherence_pct        — completed / planned last 14d
  * missed_sessions      — count last 14d
  * pain_flags           — [{region, side?, first_seen_at, source}]
  * motivation_flag      — "low" | "steady" | "high"
  * focus_shift_request  — {"target": "strength"|"running"|"mobility"|..., "raw": "..."}
  * life_change_flag     — bool + note (roster change, injury, life event)
  * sleep_quality_trend  — mean of last 3 check-ins

Auto-deload rule (user-approved 2026-07):
  If adherence_pct < 0.50 AND avg_rpe_last_7d >= 8 → force deload flag next build.

Auto-pain-avoid rule:
  If a pain_flag exists AND first_seen_at within last 14d → LLM must avoid the
  matching movement pattern (overhead press if shoulder pain, deep squat if
  knee pain, deadlift/hinge if lower-back pain).
"""

from __future__ import annotations

import re
import datetime as _dt
from typing import Any, Optional

# --- Body-region → movement pattern to avoid --------------------------------# Iter 165 · Shared helper — is an ISO date-string within the last N days?
def _within_last_days(date_str: Optional[str], days: int) -> bool:
    if not date_str:
        return False
    try:
        d = _dt.date.fromisoformat(str(date_str)[:10])
    except Exception:
        return False
    today = _dt.date.today()
    return (today - d).days < days


PAIN_REGION_AVOID = {
    "shoulder":     ["overhead_press", "military_press", "handstand", "kipping_pullup"],
    "left_shoulder":["overhead_press", "military_press"],
    "right_shoulder":["overhead_press", "military_press"],
    "knee":         ["deep_squat", "pistol_squat", "box_jump", "high_impact_run"],
    "left_knee":    ["deep_squat", "pistol_squat", "box_jump"],
    "right_knee":   ["deep_squat", "pistol_squat", "box_jump"],
    "lower_back":   ["deadlift", "hinge", "loaded_carry", "heavy_squat"],
    "back":         ["deadlift", "hinge", "loaded_carry"],
    "hip":          ["deep_squat", "long_lunges"],
    "ankle":        ["high_impact_run", "box_jump", "deep_squat"],
    "wrist":        ["push_up", "handstand", "front_squat"],
    "elbow":        ["chin_up", "heavy_pull", "close_grip_press"],
    "neck":         ["overhead_press", "front_squat", "loaded_carry"],
    "hamstring":    ["deadlift", "sprint_intervals"],
    "calf":         ["sprint_intervals", "high_impact_run"],
    "foot":         ["high_impact_run", "box_jump"],
    "achilles":     ["sprint_intervals", "high_impact_run"],
}

# --- Focus-shift keyword patterns ------------------------------------------
FOCUS_SHIFT_PATTERNS = [
    (re.compile(r"\bmore\s+(strength|lifting|weights?)\b", re.I),   "strength"),
    (re.compile(r"\bmore\s+(cardio|running|runs?)\b", re.I),        "running"),
    (re.compile(r"\bmore\s+(mobility|stretching|yoga)\b", re.I),    "mobility"),
    (re.compile(r"\bmore\s+(muscle|hypertrophy|size)\b", re.I),     "hypertrophy"),
    (re.compile(r"\bmore\s+(recovery|rest)\b", re.I),               "recovery"),
    (re.compile(r"\bless\s+(strength|lifting|weights?)\b", re.I),   "less_strength"),
    (re.compile(r"\bless\s+(running|cardio)\b", re.I),              "less_running"),
    (re.compile(r"\btoo\s+(hard|tough|intense)\b", re.I),           "too_hard"),
    (re.compile(r"\btoo\s+(easy|light)\b", re.I),                   "too_easy"),
    (re.compile(r"\b(focus|prioritise|prioritize)\s+(on\s+)?strength\b", re.I), "strength"),
    (re.compile(r"\b(focus|prioritise|prioritize)\s+(on\s+)?running\b", re.I),  "running"),
]

# --- Pain phrase patterns ---------------------------------------------------
PAIN_PATTERNS = [
    # Region then pain word (allow up to a few words between: "shoulder has been sore")
    re.compile(r"\b(left|right)?\s*(shoulder|knee|hip|elbow|wrist|ankle|foot|calf|hamstring|achilles|neck|lower[\s-]?back|back)\b(?:\s+\w+){0,4}\s+(pain|sore|hurt|hurts|hurting|hurted|tight|niggle|niggling|injury|injured|strain|strained|aching|ache|sprain|sprained)", re.I),
    # Pain word then region ("pain in my shoulder")
    re.compile(r"\b(pain|sore|hurt|hurts|hurting|tight|niggle|niggling|injury|injured|strain|strained|aching|ache|sprain|sprained)\b(?:\s+\w+){0,4}\s+(left|right)?\s*(shoulder|knee|hip|elbow|wrist|ankle|foot|calf|hamstring|achilles|neck|lower[\s-]?back|back)\b", re.I),
]

# --- Life-change phrase patterns --------------------------------------------
LIFE_CHANGE_PATTERNS = [
    re.compile(r"\b(new\s+roster|schedule\s+change|different\s+base|moved|moving|new\s+job|promotion|standby|training\s+course|holiday|vacation|leave)\b", re.I),
    re.compile(r"\b(pregnant|pregnancy|baby|newborn|got\s+sick|illness|surgery|operation)\b", re.I),
]


def _clip(v: Any, lo: int = 1, hi: int = 10) -> Optional[int]:
    if v is None:
        return None
    try:
        n = int(v)
        return max(lo, min(hi, n))
    except Exception:
        return None


def extract_signals_from_checkin(checkin: dict) -> dict[str, Any]:
    """
    Parse ONE check-in submission and return a structured signals dict.
    Never raises — always returns a dict (may be empty).
    """
    signals: dict[str, Any] = {}
    energy = _clip(checkin.get("energy"))
    sleep = _clip(checkin.get("sleep"))
    soreness = _clip(checkin.get("soreness"))
    stress = _clip(checkin.get("stress"))
    if energy is not None:
        signals["energy_score"] = energy
        signals["energy_delta"] = energy - 5  # baseline
    if sleep is not None:
        signals["sleep_score"] = sleep
    if soreness is not None:
        signals["soreness_score"] = soreness
    if stress is not None:
        signals["stress_score"] = stress

    # Motivation: low if energy<4 or stress>7 or soreness>8
    if any([
        energy is not None and energy < 4,
        stress is not None and stress > 7,
        soreness is not None and soreness > 8,
    ]):
        signals["motivation_flag"] = "low"
    elif energy is not None and energy >= 8 and (stress is None or stress <= 5):
        signals["motivation_flag"] = "high"
    else:
        signals["motivation_flag"] = "steady"

    # Notes-driven signals
    notes = (checkin.get("notes") or "").strip()
    if notes:
        # Focus shift
        for pat, target in FOCUS_SHIFT_PATTERNS:
            if pat.search(notes):
                signals["focus_shift_request"] = {"target": target, "raw": notes[:240]}
                break

        # Pain flags
        pain_flags: list[dict] = []
        for pat in PAIN_PATTERNS:
            for m in pat.finditer(notes):
                groups = [g for g in m.groups() if g]
                region = None
                side = None
                for g in groups:
                    gl = g.lower().replace(" ", "_").replace("-", "_")
                    if gl in ("left", "right"):
                        side = gl
                    elif gl in ("shoulder", "knee", "hip", "elbow", "wrist", "ankle", "foot",
                                "calf", "hamstring", "achilles", "neck", "back", "lower_back"):
                        region = gl
                if region:
                    key = f"{side}_{region}" if side else region
                    if not any(pf.get("key") == key for pf in pain_flags):
                        pain_flags.append({
                            "key": key,
                            "region": region,
                            "side": side,
                            "source": "checkin_notes",
                            "phrase": m.group(0)[:120],
                        })
        if pain_flags:
            signals["pain_flags"] = pain_flags

        # Life change
        if any(pat.search(notes) for pat in LIFE_CHANGE_PATTERNS):
            signals["life_change_flag"] = True
            signals["life_change_note"] = notes[:280]

    # Adaptive answers can carry structured Q&A pairs
    for a in (checkin.get("answers") or []):
        if not isinstance(a, dict):
            continue
        qid = str(a.get("question_id") or "")
        v = a.get("answer")
        if not qid or v is None:
            continue
        # Any 'pain' question with a truthy list/text
        if "pain" in qid.lower() and v:
            body = str(v).lower()
            for region in ("shoulder", "knee", "hip", "elbow", "wrist", "ankle",
                           "back", "hamstring", "calf", "achilles", "neck"):
                if region in body:
                    pf = signals.setdefault("pain_flags", [])
                    key = region
                    if not any(x.get("key") == key for x in pf):
                        pf.append({"key": key, "region": region,
                                   "source": "checkin_answer", "phrase": body[:120]})
        if "focus" in qid.lower() and isinstance(v, str):
            for pat, target in FOCUS_SHIFT_PATTERNS:
                if pat.search(v):
                    signals["focus_shift_request"] = {"target": target, "raw": v[:240]}
                    break

    return signals


async def compute_live_state(db, user_id: str, days: int = 14) -> dict[str, Any]:
    """
    Roll the last N days of check-ins + workouts into a compact live_state
    snapshot the plan builder can consume. Also compute auto-deload trigger.
    """
    today = _dt.date.today()
    since = today - _dt.timedelta(days=days)
    since_iso = since.isoformat()
    since_dt_iso = since.strftime("%Y-%m-%dT00:00:00")

    checkins = await db.checkins.find(
        {"user_id": user_id, "created_at": {"$gte": since_dt_iso}},
        {"_id": 0}
    ).sort("created_at", -1).to_list(30)

    # Aggregate signals from most-recent 3 check-ins (recency-weighted)
    energy_scores: list[int] = []
    sleep_scores: list[int] = []
    soreness_scores: list[int] = []
    stress_scores: list[int] = []
    pain_flags_map: dict[str, dict] = {}
    focus_shift = None
    life_change = None
    motivation_flags: list[str] = []
    latest_checkin_iso = checkins[0].get("created_at") if checkins else None

    for c in checkins:
        sig = c.get("signals") or extract_signals_from_checkin(c)
        if sig.get("energy_score") is not None:
            energy_scores.append(sig["energy_score"])
        if sig.get("sleep_score") is not None:
            sleep_scores.append(sig["sleep_score"])
        if sig.get("soreness_score") is not None:
            soreness_scores.append(sig["soreness_score"])
        if sig.get("stress_score") is not None:
            stress_scores.append(sig["stress_score"])
        for pf in sig.get("pain_flags") or []:
            k = pf.get("key")
            if not k:
                continue
            # keep only the earliest first_seen and freshest phrase
            if k not in pain_flags_map:
                pf2 = dict(pf)
                pf2["first_seen_at"] = c.get("created_at")
                pain_flags_map[k] = pf2
        if not focus_shift and sig.get("focus_shift_request"):
            focus_shift = sig["focus_shift_request"]
        if not life_change and sig.get("life_change_flag"):
            life_change = {"note": sig.get("life_change_note"), "at": c.get("created_at")}
        if sig.get("motivation_flag"):
            motivation_flags.append(sig["motivation_flag"])

    def _avg(xs: list[int]) -> Optional[float]:
        return round(sum(xs) / len(xs), 2) if xs else None

    energy_avg = _avg(energy_scores)
    sleep_avg = _avg(sleep_scores)
    soreness_avg = _avg(soreness_scores)
    stress_avg = _avg(stress_scores)

    # Trends (last vs baseline of prior average)
    def _trend(xs: list[int]) -> str:
        if len(xs) < 2:
            return "insufficient_data"
        recent = xs[0]
        rest_avg = sum(xs[1:]) / max(1, len(xs) - 1)
        d = recent - rest_avg
        if d >= 1.5:
            return "up"
        if d <= -1.5:
            return "down"
        return "flat"

    # Workouts adherence
    since_iso_date = since.isoformat()
    wk_last14 = await db.workouts.find(
        {"user_id": user_id, "date": {"$gte": since_iso_date}},
        {"_id": 0, "focus": 1, "completed": 1, "rpe": 1, "date": 1}
    ).to_list(100)
    real_wk = [w for w in wk_last14 if str(w.get("focus") or "").lower() not in ("recovery", "mobility", "rest")]
    completed_wk = [w for w in real_wk if w.get("completed")]
    planned_past = [w for w in real_wk if (w.get("date") or "9999") <= today.isoformat()]
    completed_past = [w for w in planned_past if w.get("completed")]
    missed = [w for w in planned_past if not w.get("completed")]
    adherence_pct = (len(completed_past) / len(planned_past)) if planned_past else None

    # Avg RPE last 7 days (from workouts.rpe)
    since7 = (today - _dt.timedelta(days=7)).isoformat()
    rpe_vals = [
        float(w["rpe"]) for w in wk_last14
        if w.get("completed") and w.get("date") and w["date"] >= since7 and isinstance(w.get("rpe"), (int, float))
    ]
    avg_rpe_7d = round(sum(rpe_vals) / len(rpe_vals), 2) if rpe_vals else None

    # Auto-deload rule (user-approved): adherence < 0.5 AND avg_rpe >= 8
    auto_deload = bool(
        adherence_pct is not None and adherence_pct < 0.50 and
        avg_rpe_7d is not None and avg_rpe_7d >= 8
    )

    # Aggregate pain-based avoid list
    avoid_patterns: list[str] = []
    for pf in pain_flags_map.values():
        avoid_patterns.extend(PAIN_REGION_AVOID.get(pf.get("key") or pf.get("region") or "", []))
    avoid_patterns = sorted(set(avoid_patterns))

    # Latest motivation
    latest_motivation = motivation_flags[0] if motivation_flags else "steady"

    live_state = {
        "computed_at": _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        "window_days": days,
        "latest_checkin_at": latest_checkin_iso,
        "checkin_count": len(checkins),
        "energy_avg": energy_avg,
        "energy_trend": _trend(energy_scores),
        "sleep_avg": sleep_avg,
        "sleep_trend": _trend(sleep_scores),
        "soreness_avg": soreness_avg,
        "stress_avg": stress_avg,
        "motivation_flag": latest_motivation,
        "adherence_pct": adherence_pct,
        "avg_rpe_last_7d": avg_rpe_7d,
        # Iter 165 · Retain the 14-day count (used by programme deload logic)
        # AND expose a 3-day count that matches the tightened window used by
        # the client-facing "Missed Sessions" UI (feature_calendar_recovery).
        "missed_sessions_14d": len(missed),
        "missed_sessions_3d": len([m for m in missed if _within_last_days(m.get("date"), 3)]),
        "missed_sessions": len([m for m in missed if _within_last_days(m.get("date"), 3)]),
        "planned_sessions_14d": len(planned_past),
        "completed_sessions_14d": len(completed_past),
        "pain_flags": list(pain_flags_map.values()),
        "avoid_movement_patterns": avoid_patterns,
        "focus_shift_request": focus_shift,
        "life_change": life_change,
        "auto_deload_trigger": auto_deload,
        "auto_deload_reason": (
            f"Adherence {int(adherence_pct * 100)}% + avg RPE {avg_rpe_7d} (last 7d)"
            if auto_deload else None
        ),
    }
    return live_state


async def refresh_and_persist_live_state(db, user_id: str) -> dict[str, Any]:
    """Recompute the live_state and store it on users.profile.live_state."""
    state = await compute_live_state(db, user_id)
    # Merge coach_directives from a lookup so we don't clobber them.
    existing = await db.users.find_one({"id": user_id}, {"_id": 0, "profile.live_state.coach_directives": 1})
    coach_directives = None
    try:
        coach_directives = ((existing or {}).get("profile") or {}).get("live_state", {}).get("coach_directives")
    except Exception:
        coach_directives = None
    if coach_directives:
        state["coach_directives"] = coach_directives
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"profile.live_state": state, "profile.live_state_updated_at": state["computed_at"]}},
    )
    return state


async def add_coach_directive(db, user_id: str, directive: dict) -> dict[str, Any]:
    """Pin a coach directive so the next plan build honours it. `directive` should have
    {text, coach_id, source_message_id, ttl_days}."""
    now = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    ttl_days = int(directive.get("ttl_days") or 21)  # default 3-week TTL
    expires_at = (_dt.datetime.utcnow() + _dt.timedelta(days=ttl_days)).strftime("%Y-%m-%dT%H:%M:%S")
    doc = {
        "id": directive.get("id") or f"cd_{now}",
        "text": directive.get("text", "")[:600],
        "coach_id": directive.get("coach_id"),
        "source_message_id": directive.get("source_message_id"),
        "created_at": now,
        "expires_at": expires_at,
    }
    # Append onto profile.live_state.coach_directives (keep last 8 non-expired).
    u = await db.users.find_one({"id": user_id}, {"_id": 0}) or {}
    live = ((u.get("profile") or {}).get("live_state") or {})
    existing = live.get("coach_directives") or []
    # Filter expired
    now_str = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    existing = [d for d in existing if (d.get("expires_at") or "") > now_str][:7]
    existing.insert(0, doc)
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"profile.live_state.coach_directives": existing}},
    )
    return doc


def receipt_for_client(live_state: dict) -> Optional[dict]:
    """
    Produce a small client-facing 'Because you told us X, next week Y' receipt
    based on the current live_state. Returns None if nothing is actionable.
    """
    if not live_state:
        return None
    lines: list[str] = []
    if live_state.get("auto_deload_trigger"):
        lines.append("Next week is a deload — you've been pushing hard AND missing sessions. We're pulling back to keep you fresh.")
    pain = live_state.get("pain_flags") or []
    if pain:
        regions = ", ".join(sorted({(p.get("region") or "").replace("_", " ") for p in pain if p.get("region")}))
        if regions:
            lines.append(f"You flagged {regions} pain — next week avoids heavy overhead / deep-squat work in that pattern.")
    fsr = live_state.get("focus_shift_request")
    if fsr and fsr.get("target"):
        t = fsr["target"].replace("_", " ")
        if t.startswith("less_"):
            lines.append(f"Heard you — dialling back {t.replace('less_','')} next week.")
        elif t in ("too_hard",):
            lines.append("You said it felt too tough — next week is a step down in intensity.")
        elif t in ("too_easy",):
            lines.append("You said it felt too easy — bumping intensity next week.")
        else:
            lines.append(f"Adding more {t} into next week's plan as you asked.")
    if live_state.get("energy_trend") == "down" and live_state.get("energy_avg") is not None and live_state["energy_avg"] < 5:
        lines.append("Your energy has been dipping — we've protected recovery slots next week.")
    if not lines:
        return None
    return {
        "headline": lines[0],
        "bullets": lines,
        "computed_at": live_state.get("computed_at"),
    }
