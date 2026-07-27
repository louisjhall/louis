"""
feature_v2_p4_roster — V2 Phase 4: Structured roster facets.

Normalises V1's embedded `rosters.days[]` into first-class
`schedule_days` + `roster_duties` + `flight_sectors` records, with computed
`duty_burden` and `training_opportunity` scores per day.

Non-destructive: reads V1 rosters, writes into V2 tables only.
Gated by `v2_flags.roster_facets_enabled`.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import api, db, require_role, new_id, now_iso, logger
from feature_v2_common import (
    require_client_and_flag, write_decision, ensure_indexes, bg
)

FLAG = "roster_facets_enabled"


# ---------------------------------------------------------------------------
# Deterministic scoring
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Categorical baseline burden by roster day_type.
# These are absolute floors — a "layover_arrival" is ALWAYS at least HIGH
# burden no matter how short the duty was, because the physiological cost
# of arriving at a hotel after crossing timezones is inescapable.
# ---------------------------------------------------------------------------
_DAY_TYPE_BASELINE_BURDEN: dict[str, int] = {
    # HIGH-burden aviation states
    "layover_arrival":   75,   # just arrived at hotel, tz-crossed, exhausted
    "layover_departure": 70,   # about to fly back, prep for another duty
    "turnaround":        72,   # short-turn to base — same-day sortie
    "flight":            65,   # active flight duty (fallback if we lack detail)
    "duty":              60,   # generic duty catch-all
    # MEDIUM-burden states
    "standby":           45,   # on call, can't guarantee training window
    "sim":               50,   # simulator duty — mentally taxing
    "training":          40,   # ground/office training
    "medical":           35,
    # LAYOVER MID-STAY (recovered enough to train)
    "layover_full":      25,   # full-day layover — well-rested
    "layover":           30,   # generic layover fallback
    "hotel":             30,
    # LOW-burden home states
    "home_day":          10,
    "home":              10,
    "off":               5,
    "rest":              5,
    "day_off":           5,
    "leave":             0,
    "vacation":          0,
    "annual_leave":      0,
    "sickness":          0,
    "sick":              0,
    "sick_leave":        0,
}


def _resolve_day_type(day: dict) -> str:
    """Coerce whatever the roster parser wrote into a lower-case day_type key."""
    raw = day.get("day_type") or day.get("classification") or ""
    return str(raw).lower().strip()


def _duty_burden(day: dict) -> tuple[int, str]:
    """Return (score 0-100, band).

    NEW MODEL (post P0-3):
      1. Categorical baseline from `day_type` (aviation states like
         layover_arrival ALWAYS start HIGH).
      2. Additive load from duty duration, crossings of midnight, sectors,
         ULR, early report.
      3. Prior/next-24h duty (recovery window) — short recovery bumps score.
      4. Timezone crossings (tz_offset_from_base_hours) — >4h bumps.
    Never allowed to go below the categorical baseline.
    """
    day_type = _resolve_day_type(day)
    baseline = _DAY_TYPE_BASELINE_BURDEN.get(day_type, 30)  # unknown → moderate default

    score = baseline
    duties = day.get("duties") or []
    total_min = 0
    for d in duties:
        try:
            if d.get("duty_start_time") and d.get("duty_finish_time"):
                s = _dt.datetime.fromisoformat(d["duty_start_time"])
                f = _dt.datetime.fromisoformat(d["duty_finish_time"])
                mins = int((f - s).total_seconds() / 60)
                if mins < 0: mins += 24 * 60
                total_min += mins
        except Exception:
            pass
        if d.get("crossed_midnight"): score += 8
        if d.get("duty_type") == "standby": score += 4
        if d.get("duty_type") == "flight":  score += 4

    # Sector count (light additive on top of baseline)
    sector_count = sum(len(d.get("sectors") or []) for d in duties)
    if sector_count >= 3: score += 10
    elif sector_count == 2: score += 5

    # Total duty duration
    if total_min > 12 * 60:      score += 20
    elif total_min > 9 * 60:     score += 15
    elif total_min > 6 * 60:     score += 10
    elif total_min > 3 * 60:     score += 5

    # ULR flag (ultra-long-range flight = big burden)
    if any((d.get("ulr") or (d.get("notes") or "").upper().find("ULR") >= 0) for d in duties):
        score += 15

    # Early report
    for d in duties:
        try:
            if d.get("report_time"):
                hr = _dt.datetime.fromisoformat(d["report_time"]).hour
                if hr <= 5:  score += 8
                elif hr <= 7: score += 4
        except Exception:
            pass

    # Recovery window from prior duty (short = high burden carryover)
    prior_recovery = day.get("recovery_window_hours_from_prior_duty")
    if isinstance(prior_recovery, (int, float)):
        if prior_recovery < 12: score += 12
        elif prior_recovery < 18: score += 6

    # Timezone crossings
    tz = day.get("tz_offset_from_base_hours") or 0
    try:
        tz_abs = abs(int(tz))
    except Exception:
        tz_abs = 0
    if tz_abs >= 7:      score += 12
    elif tz_abs >= 4:    score += 6

    # HARD FLOORS by categorical day_type (never dip below baseline)
    score = max(baseline, score)

    # Zero-out leave/sick
    if day_type in ("leave", "vacation", "annual_leave", "sickness", "sick", "sick_leave"):
        score = 0

    score = max(0, min(100, score))
    if score < 20:      band = "light"
    elif score < 50:    band = "moderate"
    elif score < 75:    band = "heavy"
    else:               band = "extreme"
    return score, band


def _training_opportunity(day: dict, burden_score: int) -> tuple[int, str, int]:
    """Return (score 0-100, recommended_intensity_ceiling, available_time_min).

    NEW MODEL (post P0-3):
      Categorical ceiling by day_type FIRST, then reduced by burden.
      A layover_arrival can never score above 30 no matter what;
      a home_day can never score below 70 without an explicit reason.
    """
    day_type = _resolve_day_type(day)

    # Categorical CEILING (max opportunity permitted for this day_type)
    ceilings = {
        "layover_arrival":    30,
        "layover_departure":  25,
        "turnaround":         25,
        "flight":             30,
        "duty":               35,
        "standby":            50,   # on call — some flexibility for a light session
        "sim":                45,
        "training":           55,
        "medical":            40,
        "layover_full":       75,   # full rest day at destination
        "layover":            65,
        "hotel":              70,
        "home_day":           95,
        "home":               95,
        "off":                100,
        "rest":               100,
        "day_off":            100,
        "leave":              95,   # coach might want lighter workouts on vacation
        "vacation":           95,
        "annual_leave":       95,
        "sickness":           0,
        "sick":               0,
        "sick_leave":         0,
    }
    ceiling = ceilings.get(day_type, 60)

    # Categorical FLOOR (min opportunity we won't dip below on rest-like days)
    floors = {
        "home_day":  70,
        "home":      70,
        "off":       80,
        "rest":      80,
        "day_off":   80,
    }
    floor = floors.get(day_type, 0)

    # Base = ceiling minus a proportional bite of burden
    base = ceiling - int(burden_score * 0.6)
    base = max(floor, min(ceiling, base))

    # Zero-out sick
    if day_type in ("sickness", "sick", "sick_leave"):
        base = 0

    # Available time heuristic (minutes)
    time_by_type = {
        "home_day": 90, "home": 90, "off": 120, "rest": 120,
        "day_off": 120, "leave": 90, "vacation": 90, "annual_leave": 90,
        "layover_full": 60, "layover": 50, "hotel": 50,
        "layover_arrival": 25, "layover_departure": 20, "turnaround": 15,
        "flight": 20, "duty": 25, "standby": 45, "sim": 30, "training": 35,
        "sickness": 0, "sick": 0, "sick_leave": 0,
    }
    avail = time_by_type.get(day_type, max(0, 60 - burden_score // 5))

    # Recommended intensity ceiling (based on burden, categorical-aware)
    if day_type in ("layover_arrival", "layover_departure", "turnaround"):
        rec = "rpe4"    # only easy movement on high-fatigue transitions
    elif burden_score >= 75:      rec = "rpe4"
    elif burden_score >= 55:      rec = "rpe6"
    elif burden_score >= 30:      rec = "rpe7"
    elif burden_score >= 10:      rec = "rpe8"
    else:                         rec = "any"
    return base, rec, avail


# ---------------------------------------------------------------------------
# Adapter: V1 roster.days[] → V2 schedule_days + duties + sectors
# ---------------------------------------------------------------------------

class BuildRosterFacetsBody(BaseModel):
    roster_id: Optional[str] = None
    all_active: bool = True


@api.post("/v2/coach/clients/{client_id}/roster-facets/build")
async def roster_facets_build(
    client_id: str, body: BuildRosterFacetsBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Regenerate V2 schedule_days/duties/sectors from V1 rosters for this client."""
    await require_client_and_flag(client_id, FLAG)
    return await _build_roster_facets(
        client_id=client_id,
        roster_id=body.roster_id,
        all_active=body.all_active,
        actor_id=coach["id"],
    )


async def _build_roster_facets(
    client_id: str,
    roster_id: Optional[str] = None,
    all_active: bool = True,
    actor_id: str = "system",
) -> dict:
    """Reusable helper — regenerate V2 schedule_days/duties/sectors from V1
    rosters. Safe to call from any post-confirmation worker without
    needing coach auth (the caller is expected to have already
    authenticated the coach or is running as system).
    """
    q: dict = {"user_id": client_id}
    if roster_id:
        q["id"] = roster_id
    elif all_active:
        q["is_active"] = True
    rosters = await db.rosters.find(q, {"_id": 0}).to_list(50)
    if not rosters:
        return {"schedule_days": 0, "duties": 0, "sectors": 0, "note": "no rosters found"}

    roster_ids = [r["id"] for r in rosters]

    # Snapshot prior schedule_days for change detection (per-date derived state)
    prior_map: dict[str, dict] = {}
    async for sd in db.schedule_days.find(
        {"client_id": client_id, "source_roster_id": {"$in": roster_ids}}, {"_id": 0}
    ):
        prior_map[sd["date"]] = {"derived": sd.get("derived") or {}}

    await db.schedule_days.delete_many({"client_id": client_id, "source_roster_id": {"$in": roster_ids}})
    await db.roster_duties.delete_many({"client_id": client_id, "source_roster_id": {"$in": roster_ids}})
    await db.flight_sectors.delete_many({"client_id": client_id, "source_roster_id": {"$in": roster_ids}})

    # Also clear any lingering schedule_days for the exact date range of the
    # rosters we're about to insert — this prevents a
    # DuplicateKeyError on the (client_id, date) unique index when a NEW
    # roster overlaps with a previous confirmed roster that we're now
    # superseding.
    all_dates: list[str] = []
    for r in rosters:
        for d in r.get("days") or []:
            if d.get("date"):
                all_dates.append(d["date"])
    if all_dates:
        await db.schedule_days.delete_many(
            {"client_id": client_id, "date": {"$in": all_dates}}
        )

    total_days, total_duties, total_sectors = 0, 0, 0

    for roster in rosters:
        rid = roster["id"]
        for day in (roster.get("days") or []):
            date_str = day.get("date")
            if not date_str:
                continue
            duty_ids: list[str] = []
            all_day_duties = day.get("duties") or []
            if not all_day_duties and day.get("duty_type"):
                # V1 may store single duty at top-level of day
                all_day_duties = [{
                    "duty_type": day.get("duty_type"),
                    "report_time": day.get("report_time"),
                    "duty_start_time": day.get("start_time"),
                    "duty_finish_time": day.get("finish_time"),
                    "crossed_midnight": day.get("crossed_midnight", False),
                    "sectors": day.get("sectors") or [],
                    "notes": day.get("notes") or "",
                }]
            for duty in all_day_duties:
                dtid = new_id()
                sector_ids: list[str] = []
                for i, sec in enumerate(duty.get("sectors") or [], start=1):
                    sid = new_id()
                    await db.flight_sectors.insert_one({
                        "id": sid,
                        "duty_id": dtid,
                        "client_id": client_id,
                        "source_roster_id": rid,
                        "ordinal": i,
                        "departure_iata": sec.get("dep") or sec.get("departure_iata") or "",
                        "arrival_iata": sec.get("arr") or sec.get("arrival_iata") or "",
                        "departure_time": sec.get("dep_time") or sec.get("departure_time"),
                        "arrival_time": sec.get("arr_time") or sec.get("arrival_time"),
                        "aircraft": sec.get("aircraft"),
                        "duration_min": sec.get("duration_min"),
                    })
                    sector_ids.append(sid)
                    total_sectors += 1
                await db.roster_duties.insert_one({
                    "id": dtid,
                    "schedule_day_id": None,   # backfilled after we insert the day
                    "client_id": client_id,
                    "source_roster_id": rid,
                    "duty_type": duty.get("duty_type") or "off",
                    "report_time": duty.get("report_time"),
                    "duty_start_time": duty.get("duty_start_time") or duty.get("start_time"),
                    "duty_finish_time": duty.get("duty_finish_time") or duty.get("finish_time"),
                    "crossed_midnight": bool(duty.get("crossed_midnight")),
                    "standby": duty.get("standby"),
                    "sectors": sector_ids,
                    "notes": duty.get("notes") or "",
                    "created_at": now_iso(), "updated_at": now_iso(),
                    "created_by": actor_id,
                })
                duty_ids.append(dtid)
                total_duties += 1

            burden_score, burden_band = _duty_burden({**day, "duties": all_day_duties})
            opp_score, ceiling, avail = _training_opportunity(day, burden_score)

            # Preserve granular day_type from the roster (home_day, standby,
            # layover, flight, off, duty, sickness, leave, etc). If the
            # parser didn't classify beyond duty vs rest, fall back to a
            # coarse rest/flight bucket.
            day_type_raw = (day.get("day_type") or day.get("classification") or "").lower()
            if day_type_raw:
                classification = day_type_raw
            elif all_day_duties:
                classification = "flight"
            else:
                classification = "rest"

            sdid = new_id()
            await db.schedule_days.insert_one({
                "id": sdid,
                "client_id": client_id,
                "date": date_str,
                "day_type": classification,      # top-level for direct read
                "home_or_away": day.get("home_or_away") or ("home" if classification in ("home_day", "off", "rest", "leave", "sick", "sickness") else "away" if classification in ("layover", "hotel") else "unknown"),
                "tz_offset_from_base_hours": day.get("tz_offset_from_base_hours") or 0,
                "recovery_window_hours_to_next_duty": day.get("recovery_window_hours_to_next_duty"),
                "recovery_window_hours_from_prior_duty": day.get("recovery_window_hours_from_prior_duty"),
                "duties": duty_ids,
                "overnight_location": day.get("overnight_location") or day.get("layover_city") or day.get("layover_iata"),
                "derived": {
                    "duty_burden_score": burden_score,
                    "duty_burden_band": burden_band,
                    "training_opportunity": opp_score,
                    "recommended_intensity_ceiling": ceiling,
                    "available_time_min": avail,
                    "classification": classification,
                },
                "source_roster_id": rid,
                "parser_confidence": day.get("parser_confidence") or 0.9,
                "version": 1,
                "updated_at": now_iso(),
                "updated_by": actor_id,
            })
            # Backfill schedule_day_id on duties
            if duty_ids:
                await db.roster_duties.update_many(
                    {"id": {"$in": duty_ids}}, {"$set": {"schedule_day_id": sdid}}
                )
            total_days += 1

    await write_decision(
        actor="coach", layer="WHEN", scope_kind="client", scope_id=client_id,
        client_id=client_id, outcome="APPLIED",
        reason=f"Roster facets built: {total_days} days, {total_duties} duties, {total_sectors} sectors from {len(rosters)} rosters",
    )

    # Emit ROSTER_CHANGED exceptions where derived state materially changed.
    try:
        from feature_v2_directive_engine import emit_roster_change_exceptions
        new_map: dict[str, dict] = {}
        async for sd in db.schedule_days.find(
            {"client_id": client_id, "source_roster_id": {"$in": roster_ids}}, {"_id": 0}
        ):
            new_map[sd["date"]] = {"derived": sd.get("derived") or {}}
        change_count = await emit_roster_change_exceptions(client_id, prior_map, new_map)
    except Exception as _e:
        change_count = 0

    return {"schedule_days": total_days, "duties": total_duties,
            "sectors": total_sectors, "roster_changes_detected": change_count}


@api.get("/v2/coach/clients/{client_id}/schedule-days")
async def schedule_days_list(
    client_id: str, from_date: Optional[str] = None, to_date: Optional[str] = None,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    q: dict = {"client_id": client_id}
    if from_date or to_date:
        q["date"] = {}
        if from_date: q["date"]["$gte"] = from_date
        if to_date:   q["date"]["$lte"] = to_date
    rows = await db.schedule_days.find(q, {"_id": 0}).sort("date", 1).to_list(400)
    return {"schedule_days": rows}


@api.get("/v2/coach/clients/{client_id}/schedule-days/{date}")
async def schedule_day_detail(
    client_id: str, date: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    sd = await db.schedule_days.find_one({"client_id": client_id, "date": date}, {"_id": 0})
    if not sd:
        raise HTTPException(404, "No schedule day for this date")
    duties = await db.roster_duties.find({"id": {"$in": sd.get("duties") or []}}, {"_id": 0}).to_list(20)
    sector_ids = [sid for d in duties for sid in (d.get("sectors") or [])]
    sectors = await db.flight_sectors.find({"id": {"$in": sector_ids}}, {"_id": 0}).sort("ordinal", 1).to_list(50) if sector_ids else []
    return {"schedule_day": sd, "duties": duties, "sectors": sectors}


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

async def _bootstrap() -> None:
    await ensure_indexes("schedule_days", [
        ([("client_id", 1), ("date", 1)], True, "schedule_days_client_date_unique"),
        ([("source_roster_id", 1)], False, "schedule_days_source_roster"),
    ])
    await ensure_indexes("roster_duties", [
        ([("schedule_day_id", 1)], False, "roster_duties_day"),
        ([("client_id", 1)], False, "roster_duties_client"),
    ])
    await ensure_indexes("flight_sectors", [
        ([("duty_id", 1), ("ordinal", 1)], False, "flight_sectors_duty_ordinal"),
    ])

bg(_bootstrap())


logger.info("feature_v2_p4_roster: /api/v2 roster facets endpoints registered")
