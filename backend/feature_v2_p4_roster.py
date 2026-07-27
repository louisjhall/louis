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

def _duty_burden(day: dict) -> tuple[int, str]:
    """Return (score 0-100, band).

    Heuristic based on: duty duration total, crossings of midnight, ULR flag,
    early report time, layover status, number of sectors, standby.
    """
    score = 0
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
        if d.get("crossed_midnight"): score += 12
        if d.get("duty_type") == "standby": score += 8
        if d.get("duty_type") == "flight":  score += 6

    # Sector count
    sector_count = sum(len(d.get("sectors") or []) for d in duties)
    if sector_count >= 3: score += 15
    elif sector_count == 2: score += 8

    # Total duty duration
    if total_min > 12 * 60:      score += 40
    elif total_min > 9 * 60:     score += 30
    elif total_min > 6 * 60:     score += 20
    elif total_min > 3 * 60:     score += 10

    # ULR flag
    if any((d.get("ulr") or (d.get("notes") or "").upper().find("ULR") >= 0) for d in duties):
        score += 25

    # Early report
    for d in duties:
        try:
            if d.get("report_time"):
                hr = _dt.datetime.fromisoformat(d["report_time"]).hour
                if hr <= 5:  score += 12
                elif hr <= 7: score += 6
        except Exception:
            pass

    # Classification-based fine-tuning
    cls = day.get("classification") or ""
    if cls == "layover_full":     score = max(score, 15)
    if cls == "layover_departure": score += 10
    if cls == "leave":            score = 0
    if cls in ("rest", "off"):    score = 0

    score = max(0, min(100, score))
    if score < 25:      band = "light"
    elif score < 55:    band = "moderate"
    elif score < 80:    band = "heavy"
    else:               band = "extreme"
    return score, band


def _training_opportunity(day: dict, burden_score: int) -> tuple[int, str, int]:
    """Return (score 0-100, recommended_intensity_ceiling, available_time_min)."""
    # Baseline is inverse of burden, bumped by rest/layover_full days.
    base = max(0, 100 - burden_score)
    cls = day.get("classification") or ""
    if cls in ("rest", "off", "home"): base = min(100, base + 15)
    if cls == "layover_full":          base = min(100, base + 8)
    if cls == "leave":                 base = min(100, base + 5)
    if cls == "standby":               base = max(0, base - 15)

    # Available time heuristic (minutes)
    if cls in ("rest", "off", "home", "leave"):     avail = 90
    elif cls == "layover_full":                     avail = 60
    elif cls == "layover_arrival":                  avail = 30
    elif cls == "layover_departure":                avail = 20
    elif cls == "standby":                          avail = 45
    else:                                           avail = max(0, 60 - burden_score // 5)

    # Recommended intensity ceiling
    if burden_score >= 80:      rec = "rpe4"
    elif burden_score >= 55:    rec = "rpe6"
    elif burden_score >= 30:    rec = "rpe7"
    elif burden_score >= 10:    rec = "rpe8"
    else:                       rec = "any"
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

    q: dict = {"user_id": client_id}
    if body.roster_id:
        q["id"] = body.roster_id
    elif body.all_active:
        q["is_active"] = True
    rosters = await db.rosters.find(q, {"_id": 0}).to_list(50)
    if not rosters:
        return {"schedule_days": 0, "duties": 0, "sectors": 0, "note": "no rosters found"}

    # Wipe existing V2 records for this client from these source rosters
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
                    "created_by": coach["id"],
                })
                duty_ids.append(dtid)
                total_duties += 1

            burden_score, burden_band = _duty_burden({**day, "duties": all_day_duties})
            opp_score, ceiling, avail = _training_opportunity(day, burden_score)
            sdid = new_id()
            await db.schedule_days.insert_one({
                "id": sdid,
                "client_id": client_id,
                "date": date_str,
                "home_or_away": day.get("home_or_away") or "unknown",
                "tz_offset_from_base_hours": day.get("tz_offset_from_base_hours") or 0,
                "recovery_window_hours_to_next_duty": day.get("recovery_window_hours_to_next_duty"),
                "recovery_window_hours_from_prior_duty": day.get("recovery_window_hours_from_prior_duty"),
                "duties": duty_ids,
                "overnight_location": day.get("overnight_location"),
                "derived": {
                    "duty_burden_score": burden_score,
                    "duty_burden_band": burden_band,
                    "training_opportunity": opp_score,
                    "recommended_intensity_ceiling": ceiling,
                    "available_time_min": avail,
                    "classification": day.get("classification") or ("rest" if not all_day_duties else "flight"),
                },
                "source_roster_id": rid,
                "parser_confidence": day.get("parser_confidence") or 0.9,
                "version": 1,
                "updated_at": now_iso(),
                "updated_by": coach["id"],
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
