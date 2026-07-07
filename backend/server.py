"""CrewFit V1.5 — aviation-crew fitness coaching backend.

Phase A additions on top of V1:
 - Extended onboarding (home equipment + training preferences)
 - Full-month roster parsing with 17 day types & confidence flags
 - Roster expiry tracking, history (never overwrite prior rosters)
 - Shared community hotel-equipment database
 - Location-aware, equipment-aware monthly workout generation
 - Turnaround / layover / long-haul logic + AI explanations
 - Coach locks, regenerate day/week/month, filters
 - Roster diff on re-upload (preserves completed + coach-locked days)
 - Emergent managed push (endpoint + helper)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional

import bcrypt
import httpx
import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Header, status
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field

from emergentintegrations.llm.chat import (
    FileContentWithMimeType,
    LlmChat,
    UserMessage,
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGO = os.environ.get("JWT_ALGORITHM", "HS256")
EMERGENT_LLM_KEY = os.environ["EMERGENT_LLM_KEY"]
EMERGENT_PUSH_KEY = os.environ.get("EMERGENT_PUSH_KEY", "placeholder")
PUSH_BASE_URL = "https://integrations.emergentagent.com"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
logger = logging.getLogger("crewfit")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

_push_client: Optional[httpx.AsyncClient] = None

def push_client() -> httpx.AsyncClient:
    global _push_client
    if _push_client is None:
        _push_client = httpx.AsyncClient(
            base_url=PUSH_BASE_URL,
            headers={"X-Push-Key": EMERGENT_PUSH_KEY},
            timeout=10.0,
        )
    return _push_client

app = FastAPI(title="CrewFit V1.5")
api = APIRouter(prefix="/api")


# ------------------------------------------------------------------
# Auth
# ------------------------------------------------------------------
def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

def verify_pw(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False

def make_token(user_id: str, role: str) -> str:
    payload = {"sub": user_id, "role": role, "exp": datetime.now(timezone.utc) + timedelta(days=30)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

async def current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Bad token: {e}")
    u = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    if not u:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return u

def require_role(role: str):
    async def _dep(user: dict = Depends(current_user)) -> dict:
        if user["role"] != role:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"{role} role required")
        return user
    return _dep


# ------------------------------------------------------------------
# Constants: day types, home equipment, hotel equipment
# ------------------------------------------------------------------
Role = Literal["client", "coach"]
DayLoad = Literal["green", "amber", "red", "blue", "purple", "grey"]

DAY_TYPES = [
    "Home Day", "Home Training Day", "Turnaround Duty", "Layover Arrival Day",
    "Layover Full Day", "Layover Departure Day", "Long-Haul Duty", "Short-Haul Duty",
    "Night Flight", "Early Report", "Late Finish", "Rest Day", "Recovery Day",
    "Standby", "Simulator/Training Day", "Annual Leave", "Unknown/Needs Confirmation",
]

HOME_EQUIPMENT_OPTIONS = [
    "no equipment", "yoga mat", "resistance bands", "pull-up bar", "dumbbells",
    "adjustable dumbbells", "kettlebells", "barbell", "squat rack", "bench",
    "cable machine", "treadmill", "bike/turbo trainer", "rowing machine",
    "assault bike", "skipping rope", "medicine ball", "TRX/suspension trainer",
    "foam roller", "mobility tools",
]

HOTEL_EQUIPMENT_FIELDS = [
    "dumbbells", "treadmill", "bike", "rower", "cable_machine", "machines",
    "bench", "squat_rack", "free_weights", "pool", "outdoor_running",
]


# ------------------------------------------------------------------
# Models
# ------------------------------------------------------------------
class SignupBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str
    role: Role = "client"

class LoginBody(BaseModel):
    email: EmailStr
    password: str

class HomeEquipmentBody(BaseModel):
    equipment: list[str] = []
    training_location: Optional[str] = None
    max_home_minutes: Optional[int] = 60
    preferred_days: list[str] = []
    disliked_exercises: Optional[str] = None
    injuries: Optional[str] = None
    goal: Optional[str] = None
    experience_level: Optional[str] = None
    strength_level: Optional[str] = None
    cardio_equipment: list[str] = []
    will_run_outside: bool = True
    swim_cycle: Optional[str] = None
    airline: Optional[str] = None
    position: Optional[str] = None
    home_base: Optional[str] = None
    training_days_per_week: int = 4
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    calorie_target: Optional[int] = 2200
    protein_target: Optional[int] = 150

class RosterExtractBody(BaseModel):
    file_base64: str
    mime_type: str
    week_start: Optional[str] = None

class RosterDay(BaseModel):
    date: str
    day_type: str = "Unknown/Needs Confirmation"
    load: DayLoad = "grey"
    home_or_away: Literal["home", "away", "unknown"] = "unknown"
    report_time: Optional[str] = None
    duty_end_time: Optional[str] = None
    flights: list[dict] = []
    layover_city: Optional[str] = None
    layover_country: Optional[str] = None
    layover_nights: Optional[int] = None
    hotel_id: Optional[str] = None
    hotel_name: Optional[str] = None
    notes: Optional[str] = None
    confidence: float = 0.7
    coach_locked: bool = False

class RosterConfirmBody(BaseModel):
    days: list[dict]

class HotelBody(BaseModel):
    name: str
    city: str
    country: Optional[str] = None
    gym_available: Optional[bool] = None
    equipment: dict = {}  # keys from HOTEL_EQUIPMENT_FIELDS -> bool
    outdoor_safe: Optional[bool] = None
    pool: Optional[bool] = None
    opening_hours: Optional[str] = None
    notes: Optional[str] = None

class HotelAttachBody(BaseModel):
    date: str
    hotel: HotelBody

class WorkoutGenerateMonthBody(BaseModel):
    roster_id: str

class WorkoutRegenerateBody(BaseModel):
    roster_id: str
    dates: Optional[list[str]] = None  # specific dates
    week_start: Optional[str] = None   # regenerate that ISO week
    all: bool = False                  # entire month

class WorkoutUpdateBody(BaseModel):
    title: Optional[str] = None
    exercises: Optional[list[dict]] = None
    day_load: Optional[DayLoad] = None
    coach_notes: Optional[str] = None
    approved: Optional[bool] = None
    coach_locked: Optional[bool] = None
    location: Optional[str] = None

class WorkoutCompleteBody(BaseModel):
    completed_exercises: list[dict]
    rpe: Optional[int] = None
    notes: Optional[str] = None

class ExerciseBody(BaseModel):
    name: str
    category: str
    equipment: list[str] = []
    movement_pattern: Optional[str] = None
    muscle_group: Optional[str] = None
    home_ok: bool = True
    hotel_ok: bool = True
    bodyweight_ok: bool = False
    level: str = "intermediate"
    knee_friendly: int = 8
    back_friendly: int = 8
    shoulder_friendly: int = 8
    fatigue_cost: str = "medium"
    ok_before_flight: bool = True
    ok_after_flight: bool = True
    demo_url: Optional[str] = None
    notes: Optional[str] = None
    common_mistakes: Optional[str] = None
    regressions: Optional[str] = None
    progressions: Optional[str] = None

class CheckInBody(BaseModel):
    week_start: str
    energy: int = Field(ge=1, le=10)
    sleep: int = Field(ge=1, le=10)
    soreness: int = Field(ge=1, le=10)
    stress: int = Field(ge=1, le=10)
    weight_kg: Optional[float] = None
    notes: Optional[str] = None

class MealBody(BaseModel):
    meal_type: str
    description: str
    photo_base64: Optional[str] = None
    photo_mime: Optional[str] = None
    calories: Optional[int] = None
    protein_g: Optional[int] = None

class ProgressBody(BaseModel):
    weight_kg: Optional[float] = None
    photo_base64: Optional[str] = None
    photo_mime: Optional[str] = None
    notes: Optional[str] = None

class MessageBody(BaseModel):
    to_user_id: str
    text: str

class RegisterPushBody(BaseModel):
    user_id: str
    platform: str
    device_token: str


# ------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------
def new_id() -> str:
    return str(uuid.uuid4())

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def today_str() -> str:
    return date.today().isoformat()

def clean_doc(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc

def strip_data_url(b64: str) -> str:
    return b64.split(",", 1)[1] if b64.startswith("data:") else b64

async def write_temp(b64: str, mime: str) -> str:
    ext = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg",
           "image/jpg": ".jpg", "image/webp": ".webp"}.get(mime, ".bin")
    fd, path = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    with open(path, "wb") as f:
        f.write(base64.b64decode(strip_data_url(b64)))
    return path

def parse_json_from_text(text: str) -> Any:
    if not text:
        raise ValueError("empty")
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    for op, cl in [("{", "}"), ("[", "]")]:
        s = text.find(op); e = text.rfind(cl)
        if s != -1 and e > s:
            try:
                return json.loads(text[s : e + 1])
            except Exception:
                continue
    raise ValueError(f"No JSON found in LLM response: {text[:200]}")

async def call_claude(system: str, prompt: str, max_out: int = 8000) -> str:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=new_id(),
        system_message=system,
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")
    r = await chat.send_message(UserMessage(text=prompt))
    return r if isinstance(r, str) else str(r)

async def call_gemini_file(system: str, prompt: str, file_path: str, mime: str) -> str:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=new_id(),
        system_message=system,
    ).with_model("gemini", "gemini-2.5-flash")
    fc = FileContentWithMimeType(file_path=file_path, mime_type=mime)
    r = await chat.send_message(UserMessage(text=prompt, file_contents=[fc]))
    return r if isinstance(r, str) else str(r)


# ------------------------------------------------------------------
# Day-type & load scoring
# ------------------------------------------------------------------
def score_load(day: dict, prev_day: Optional[dict] = None, next_day: Optional[dict] = None) -> str:
    dt = (day.get("day_type") or "").lower()
    if "annual leave" in dt or "rest" in dt or "home training" in dt:
        return "green"
    if "home day" in dt:
        return "green"
    if "unknown" in dt:
        return "grey"
    if "standby" in dt or "simulator" in dt:
        return "amber"
    if "layover arrival" in dt:
        return "red"
    if "layover full" in dt:
        return "green"
    if "layover departure" in dt:
        return "amber"
    if "long-haul" in dt or "night flight" in dt:
        return "red"
    if "turnaround" in dt or "short-haul" in dt:
        flights = day.get("flights") or []
        if len(flights) >= 3:
            return "red"
        rep = day.get("report_time") or ""
        if rep[:2].isdigit():
            h = int(rep[:2])
            if h < 5:
                return "red"
        return "amber"
    if "recovery" in dt:
        return "red"
    return "blue"

def day_location(day: dict) -> str:
    dt = (day.get("day_type") or "").lower()
    if "home" in dt or "rest" in dt or "annual" in dt or "recovery" in dt:
        return "home"
    if "layover" in dt:
        return "hotel"
    if "turnaround" in dt or "short-haul" in dt or "long-haul" in dt or "night flight" in dt or "duty" in dt:
        return "home"  # crew based at home end of duty (turnarounds)
    if "standby" in dt or "simulator" in dt:
        return "home"
    return "unknown"


# ------------------------------------------------------------------
# Auth routes
# ------------------------------------------------------------------
@api.post("/auth/signup")
async def signup(body: SignupBody):
    if await db.users.find_one({"email": body.email.lower()}):
        raise HTTPException(400, "Email already registered")
    u = {
        "id": new_id(), "email": body.email.lower(), "name": body.name,
        "role": body.role, "password_hash": hash_pw(body.password),
        "created_at": now_iso(), "onboarded": False, "coach_id": None, "profile": {},
    }
    await db.users.insert_one(u)
    token = make_token(u["id"], u["role"])
    clean_doc(u); u.pop("password_hash", None)
    return {"token": token, "user": u}


@api.post("/auth/login")
async def login(body: LoginBody):
    u = await db.users.find_one({"email": body.email.lower()})
    if not u or not verify_pw(body.password, u["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    token = make_token(u["id"], u["role"])
    clean_doc(u); u.pop("password_hash", None)
    return {"token": token, "user": u}


@api.get("/auth/me")
async def me(user: dict = Depends(current_user)):
    return user


@api.post("/auth/onboarding")
async def onboarding(body: HomeEquipmentBody, user: dict = Depends(current_user)):
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"profile": body.model_dump(), "onboarded": True}},
    )
    return await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})


# ------------------------------------------------------------------
# Push
# ------------------------------------------------------------------
@api.post("/register-push", status_code=201)
async def register_push(body: RegisterPushBody):
    try:
        resp = await push_client().post("/api/v1/push/users/register", json=body.model_dump())
        if resp.status_code == 401:
            raise HTTPException(500, "EMERGENT_PUSH_KEY missing or invalid")
        if resp.status_code >= 500:
            raise HTTPException(502, "Push provider unavailable")
        resp.raise_for_status()
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("register_push failed (non-blocking): %s", e)
    return {"status": "registered"}


async def send_push(recipients: list[str], data: dict, idempotency_key: Optional[str] = None) -> None:
    if not recipients:
        return
    if len(recipients) > 100:
        raise ValueError("max 100 recipients per /trigger call")
    if "title" not in data or "message" not in data:
        raise ValueError("data must include title and message")
    payload: dict = {"recipients": recipients, "data": data}
    if idempotency_key:
        payload["$idempotency_key"] = idempotency_key
    try:
        resp = await push_client().post("/api/v1/push/trigger", json=payload)
        if resp.status_code == 401:
            raise HTTPException(500, "EMERGENT_PUSH_KEY missing or invalid")
        if resp.status_code >= 500:
            raise HTTPException(502, "Push provider unavailable")
        resp.raise_for_status()
    except Exception as e:
        logger.warning("send_push failed (non-blocking): %s", e)


# ------------------------------------------------------------------
# Roster: extract full month
# ------------------------------------------------------------------
ROSTER_SYSTEM = f"""You are an aviation-roster parser for airline crew (pilots and cabin crew).
Extract EVERY duty and off day the roster shows. Handle 3-day rosters up to multi-month rosters.
For each date output ONE object with these fields (populate what you can, leave unknown as null):
  date (YYYY-MM-DD, required)
  day_type — one of: {", ".join(DAY_TYPES)}
  home_or_away — "home" | "away" | "unknown"
  report_time (HH:MM)
  duty_end_time (HH:MM)
  flights: [{{flight_no, from (IATA), to (IATA), dep (HH:MM), arr (HH:MM)}}]
  layover_city, layover_country, layover_nights (int)
  notes (short free text of any airline codes/duty codes you saw)
  confidence 0..1 — how sure you are about this day; put low confidence and day_type "Unknown/Needs Confirmation" if unsure.

Classify carefully:
 - single-day duty starting and ending at the same base = Turnaround Duty (also Short-Haul or Long-Haul as appropriate)
 - overnight in another city = Layover Arrival Day (arrival day) followed by Layover Full Day(s) and Layover Departure Day (last)
 - duty starting before 05:00 = Early Report; ending after 23:00 = Late Finish; block covering 02:00-05:00 = Night Flight
 - do NOT invent dates or airports; if unclear, day_type="Unknown/Needs Confirmation" and confidence=0.3

Return STRICT JSON only:
{{"days":[{{...}}]}}"""


@api.post("/roster/extract")
async def roster_extract(body: RosterExtractBody, user: dict = Depends(current_user)):
    path = await write_temp(body.file_base64, body.mime_type)
    raw = ""
    try:
        raw = await call_gemini_file(
            ROSTER_SYSTEM,
            "Extract the complete roster shown. Return only JSON.",
            path, body.mime_type,
        )
    except Exception as e:
        logger.warning("Gemini roster call failed: %s", e)
    finally:
        try: os.unlink(path)
        except Exception: pass

    parsed: Any = {}
    try:
        parsed = parse_json_from_text(raw) if raw else {}
    except Exception as e:
        logger.warning("roster parse failed: %s", e)

    days = parsed.get("days", []) if isinstance(parsed, dict) else parsed
    if not days:
        try:
            base = datetime.fromisoformat(body.week_start) if body.week_start else datetime.now(timezone.utc)
        except Exception:
            base = datetime.now(timezone.utc)
        days = [{"date": (base + timedelta(days=i)).date().isoformat(),
                 "day_type": "Home Day", "flights": [], "notes": "auto-generated",
                 "confidence": 0.2} for i in range(7)]

    # sort and score
    days.sort(key=lambda d: d.get("date") or "")
    for d in days:
        d.setdefault("flights", [])
        d.setdefault("day_type", "Unknown/Needs Confirmation")
        d.setdefault("confidence", 0.5)
        d["load"] = score_load(d)
        d["home_or_away"] = d.get("home_or_away") or ("away" if "layover" in d["day_type"].lower() else "home" if "home" in d["day_type"].lower() else "unknown")

    first = days[0]["date"]
    last = days[-1]["date"]

    roster = {
        "id": new_id(),
        "user_id": user["id"],
        "created_at": now_iso(),
        "week_start": body.week_start or first,
        "start_date": first,
        "end_date": last,
        "days": days,
        "confirmed": False,
        "is_active": True,
        "raw_response": raw[:6000],
        "previous_roster_id": None,
    }
    # mark all previous rosters as inactive (but keep them — history)
    await db.rosters.update_many({"user_id": user["id"], "is_active": True}, {"$set": {"is_active": False}})
    await db.rosters.insert_one(roster)
    clean_doc(roster)
    return roster


@api.post("/roster/{rid}/confirm")
async def roster_confirm(rid: str, body: RosterConfirmBody, user: dict = Depends(current_user)):
    r = await db.rosters.find_one({"id": rid, "user_id": user["id"]})
    if not r:
        raise HTTPException(404, "Roster not found")
    days = body.days
    days.sort(key=lambda d: d.get("date") or "")
    for d in days:
        d.setdefault("flights", [])
        d["load"] = score_load(d)
    updates = {
        "days": days,
        "confirmed": True,
        "confirmed_at": now_iso(),
        "start_date": days[0]["date"] if days else r.get("start_date"),
        "end_date": days[-1]["date"] if days else r.get("end_date"),
    }
    await db.rosters.update_one({"id": rid}, {"$set": updates})
    return await db.rosters.find_one({"id": rid}, {"_id": 0})


def _roster_expiry(r: dict) -> dict:
    end = r.get("end_date")
    if not end:
        return {"days_remaining": 0, "coverage": "unknown", "expired": True}
    end_d = datetime.fromisoformat(end).date()
    today = date.today()
    remaining = (end_d - today).days
    total = 0
    try:
        total = (end_d - datetime.fromisoformat(r["start_date"]).date()).days + 1
    except Exception:
        pass
    if remaining < 0:
        coverage = "expired"
    elif remaining <= 3:
        coverage = "critical"
    elif remaining <= 7:
        coverage = "low"
    elif remaining <= 14:
        coverage = "limited"
    else:
        coverage = "good"
    return {"days_remaining": remaining, "total_days": total, "coverage": coverage, "expired": remaining < 0}


@api.get("/roster/current")
async def roster_current(user: dict = Depends(current_user)):
    r = await db.rosters.find_one({"user_id": user["id"], "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    if not r:
        return {}
    r["expiry"] = _roster_expiry(r)
    return r


@api.get("/roster/history")
async def roster_history(user: dict = Depends(current_user)):
    rows = await db.rosters.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(50)
    for r in rows:
        r["expiry"] = _roster_expiry(r)
    return rows


@api.post("/roster/{rid}/hotel")
async def roster_attach_hotel(rid: str, body: HotelAttachBody, user: dict = Depends(current_user)):
    r = await db.rosters.find_one({"id": rid, "user_id": user["id"]})
    if not r:
        raise HTTPException(404, "Roster not found")
    # upsert hotel in shared DB
    h = await _upsert_hotel(body.hotel, user["id"])
    updated = False
    days = r.get("days", [])
    for d in days:
        if d.get("date") == body.date:
            d["hotel_id"] = h["id"]
            d["hotel_name"] = h["name"]
            updated = True
            break
    if not updated:
        raise HTTPException(404, "Date not found on roster")
    await db.rosters.update_one({"id": rid}, {"$set": {"days": days}})
    return {"day": next(d for d in days if d["date"] == body.date), "hotel": h}


# ------------------------------------------------------------------
# Hotels (shared community DB)
# ------------------------------------------------------------------
async def _upsert_hotel(body: HotelBody, submitted_by: str) -> dict:
    q = {"name_lower": body.name.strip().lower(), "city_lower": body.city.strip().lower()}
    existing = await db.hotels.find_one(q)
    now = now_iso()
    payload = {
        "name": body.name.strip(),
        "city": body.city.strip(),
        "country": body.country,
        "gym_available": body.gym_available,
        "equipment": body.equipment or {},
        "outdoor_safe": body.outdoor_safe,
        "pool": body.pool,
        "opening_hours": body.opening_hours,
        "notes": body.notes,
        "last_confirmed_at": now,
        "last_submitted_by": submitted_by,
    }
    if existing:
        new_conf = min(1.0, (existing.get("confidence", 0.5) + 0.15))
        await db.hotels.update_one({"id": existing["id"]}, {"$set": {**payload, "confidence": new_conf}, "$inc": {"submissions": 1}})
        return await db.hotels.find_one({"id": existing["id"]}, {"_id": 0})
    hotel = {
        "id": new_id(), "name_lower": q["name_lower"], "city_lower": q["city_lower"],
        "created_at": now, "submissions": 1, "confidence": 0.5, **payload,
    }
    await db.hotels.insert_one(hotel)
    return await db.hotels.find_one({"id": hotel["id"]}, {"_id": 0})


@api.get("/hotels/search")
async def hotels_search(name: Optional[str] = None, city: Optional[str] = None, user: dict = Depends(current_user)):
    q: dict = {}
    if name:
        q["name_lower"] = {"$regex": name.strip().lower(), "$options": "i"}
    if city:
        q["city_lower"] = {"$regex": city.strip().lower(), "$options": "i"}
    rows = await db.hotels.find(q, {"_id": 0}).limit(20).to_list(20)
    return rows


@api.post("/hotels")
async def hotels_upsert(body: HotelBody, user: dict = Depends(current_user)):
    return await _upsert_hotel(body, user["id"])


@api.get("/hotels/{hid}")
async def hotels_get(hid: str, user: dict = Depends(current_user)):
    h = await db.hotels.find_one({"id": hid}, {"_id": 0})
    if not h:
        raise HTTPException(404, "Not found")
    return h


# ------------------------------------------------------------------
# Workouts: monthly generation & regenerate
# ------------------------------------------------------------------
WORKOUT_SYSTEM = f"""You are CrewFit's elite S&C coach for airline crew.
Given a client profile with home equipment + preferences AND a chronological month of roster days (each with day_type, load, home/away, hotel info if any), produce a full month training plan.

Aviation coaching rules (STRICT):
 - No heavy lower body within 24h of Long-Haul Duty / Night Flight arrival.
 - No high-intensity intervals after poor sleep, night duty or Layover Arrival.
 - Layover Arrival Day = walking, mobility, post-flight recovery only.
 - Layover Full Day with hotel gym = strongest training opportunity (upper+lower splits ok).
 - Layover Departure Day = short mobility / activation, keep well clear of report time.
 - Turnaround with early report (<05:00) OR late finish (>23:00) = short mobility only.
 - 3+ consecutive duty days = reduce load; insert Recovery Day workouts.
 - Home Day = main strength progression; use FULL home equipment list.
 - Standby = amber; short 30 min session.
 - Simulator/Training Day = amber; light activation.
 - Annual Leave = green; full training allowed.
 - Never prescribe an exercise the client doesn't have equipment for (home OR hotel).
 - If hotel equipment is unknown, ONLY prescribe bodyweight/dumbbell-safe options.
 - Respect training_days_per_week — insert Rest Day sessions on other days.

For EACH day in the roster, output one workout object:
  date (YYYY-MM-DD)
  day_load — green | amber | red | blue | purple | grey (mirror the input where possible)
  title (short, e.g. "Home Push + Core")
  location — one of: "Home Workout", "Commercial Gym Workout", "Hotel Gym Workout",
    "Bodyweight Layover Workout", "Flight Recovery Mobility", "Pre-Flight Mobility",
    "Post-Flight Mobility", "Turnaround Recovery", "Outdoor Run", "Pool Swim", "Bike Session", "Rest Day"
  duration_min (int, integer minutes)
  focus (push|pull|legs|full|mobility|zone2|recovery)
  warmup: [ {{name, duration_sec}} ]  (2-4 short items)
  exercises: [ {{name, sets:int, reps:string, rest_sec:int, rpe:int (1-10), notes:string}} ]
  alternatives: {{home:string, hotel:string, no_equipment:string, easier:string, harder:string}}
  rationale (2-3 sentences: WHY this day, WHY this location, WHY this intensity — reference the roster explicitly)

Return STRICT JSON only:
{{"workouts":[{{...}}]}}"""


async def _generate_month(user: dict, roster: dict) -> list[dict]:
    profile = user.get("profile", {}) or {}
    # attach hotel info to days for prompt
    days_for_prompt = []
    for d in roster.get("days", []):
        entry = dict(d)
        if d.get("hotel_id"):
            h = await db.hotels.find_one({"id": d["hotel_id"]}, {"_id": 0})
            if h:
                entry["hotel"] = {
                    "name": h.get("name"), "city": h.get("city"),
                    "gym_available": h.get("gym_available"),
                    "equipment": h.get("equipment", {}),
                    "confidence": h.get("confidence", 0),
                }
        days_for_prompt.append(entry)

    prompt = (
        f"Client profile: {json.dumps(profile)[:3000]}\n"
        f"Roster (chronological): {json.dumps(days_for_prompt)[:20000]}\n"
        "Design the full month now. Include one entry per date."
    )
    raw = await call_claude(WORKOUT_SYSTEM, prompt)
    try:
        parsed = parse_json_from_text(raw)
        return parsed.get("workouts", []) if isinstance(parsed, dict) else parsed
    except Exception as e:
        logger.warning("workout gen parse fail: %s", e)
        return []


@api.post("/workouts/generate-month")
async def workouts_generate_month(body: WorkoutGenerateMonthBody, user: dict = Depends(current_user)):
    r = await db.rosters.find_one({"id": body.roster_id, "user_id": user["id"]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Roster not found")
    workouts = await _generate_month(user, r)
    # Preserve coach-locked or completed workouts on regeneration
    existing = {w["date"]: w for w in await db.workouts.find({"user_id": user["id"], "roster_id": body.roster_id}, {"_id": 0}).to_list(500)}
    saved = []
    for w in workouts:
        d = w.get("date")
        if not d:
            continue
        prev = existing.get(d)
        if prev and (prev.get("coach_locked") or prev.get("completed")):
            saved.append(prev)
            continue
        doc = {
            "id": prev["id"] if prev else new_id(),
            "user_id": user["id"], "roster_id": body.roster_id,
            "date": d,
            "day_load": w.get("day_load", "green"),
            "title": w.get("title", "Session"),
            "location": w.get("location", "Home Workout"),
            "duration_min": w.get("duration_min", 40),
            "focus": w.get("focus", "full"),
            "warmup": w.get("warmup", []),
            "exercises": w.get("exercises", []),
            "alternatives": w.get("alternatives", {}),
            "rationale": w.get("rationale", ""),
            "approved": prev.get("approved", False) if prev else False,
            "completed": False,
            "coach_notes": prev.get("coach_notes", "") if prev else "",
            "coach_locked": False,
            "created_at": prev.get("created_at", now_iso()) if prev else now_iso(),
            "updated_at": now_iso(),
        }
        # remove existing then insert (upsert)
        await db.workouts.delete_one({"id": doc["id"]})
        await db.workouts.insert_one(doc)
        saved.append(clean_doc(doc))
    # remove workouts whose date is no longer in roster
    dates_now = {w["date"] for w in workouts}
    await db.workouts.delete_many({"user_id": user["id"], "roster_id": body.roster_id, "date": {"$nin": list(dates_now)}, "coach_locked": {"$ne": True}, "completed": {"$ne": True}})
    saved.sort(key=lambda x: x.get("date") or "")
    return {"workouts": saved}


@api.post("/workouts/regenerate")
async def workouts_regenerate(body: WorkoutRegenerateBody, user: dict = Depends(current_user)):
    r = await db.rosters.find_one({"id": body.roster_id, "user_id": user["id"]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Roster not found")

    # narrow the roster days to only what to regenerate
    def in_scope(d_date: str) -> bool:
        if body.all:
            return True
        if body.dates and d_date in body.dates:
            return True
        if body.week_start:
            try:
                ws = datetime.fromisoformat(body.week_start).date()
                dd = datetime.fromisoformat(d_date).date()
                return 0 <= (dd - ws).days < 7
            except Exception:
                return False
        return False

    sub = {**r, "days": [d for d in r.get("days", []) if in_scope(d.get("date", ""))]}
    if not sub["days"]:
        raise HTTPException(400, "No days matched the regenerate scope")

    workouts = await _generate_month(user, sub)
    saved = []
    for w in workouts:
        d = w.get("date")
        if not d:
            continue
        existing = await db.workouts.find_one({"user_id": user["id"], "roster_id": body.roster_id, "date": d}, {"_id": 0})
        if existing and (existing.get("coach_locked") or existing.get("completed")):
            saved.append(existing)
            continue
        doc = {
            "id": existing["id"] if existing else new_id(),
            "user_id": user["id"], "roster_id": body.roster_id, "date": d,
            "day_load": w.get("day_load", "green"),
            "title": w.get("title", "Session"),
            "location": w.get("location", "Home Workout"),
            "duration_min": w.get("duration_min", 40),
            "focus": w.get("focus", "full"),
            "warmup": w.get("warmup", []),
            "exercises": w.get("exercises", []),
            "alternatives": w.get("alternatives", {}),
            "rationale": w.get("rationale", ""),
            "approved": False,
            "completed": False,
            "coach_notes": existing.get("coach_notes", "") if existing else "",
            "coach_locked": False,
            "created_at": existing.get("created_at", now_iso()) if existing else now_iso(),
            "updated_at": now_iso(),
        }
        await db.workouts.delete_one({"id": doc["id"]})
        await db.workouts.insert_one(doc)
        saved.append(clean_doc(doc))
    return {"workouts": saved}


@api.get("/workouts/week")
async def workouts_week(user: dict = Depends(current_user)):
    rows = await db.workouts.find({"user_id": user["id"]}, {"_id": 0}).sort("date", 1).to_list(500)
    return rows


@api.get("/workouts/{wid}")
async def workout_get(wid: str, user: dict = Depends(current_user)):
    w = await db.workouts.find_one({"id": wid}, {"_id": 0})
    if not w:
        raise HTTPException(404, "Not found")
    if user["role"] == "client" and w["user_id"] != user["id"]:
        raise HTTPException(403, "Forbidden")
    return w


@api.patch("/workouts/{wid}")
async def workout_update(wid: str, body: WorkoutUpdateBody, user: dict = Depends(current_user)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No changes")
    updates["updated_at"] = now_iso()
    if user["role"] == "coach":
        updates["last_edited_by"] = "coach"
    await db.workouts.update_one({"id": wid}, {"$set": updates})
    return await db.workouts.find_one({"id": wid}, {"_id": 0})


@api.post("/workouts/{wid}/complete")
async def workout_complete(wid: str, body: WorkoutCompleteBody, user: dict = Depends(current_user)):
    await db.workouts.update_one(
        {"id": wid, "user_id": user["id"]},
        {"$set": {"completed": True, "completed_at": now_iso(), "completion": body.model_dump()}},
    )
    return await db.workouts.find_one({"id": wid}, {"_id": 0})


# ------------------------------------------------------------------
# Exercises
# ------------------------------------------------------------------
@api.get("/exercises")
async def exercises_list(user: dict = Depends(current_user)):
    return await db.exercises.find({}, {"_id": 0}).to_list(1000)

@api.post("/exercises")
async def exercises_create(body: ExerciseBody, _: dict = Depends(require_role("coach"))):
    doc = {"id": new_id(), **body.model_dump(), "created_at": now_iso()}
    await db.exercises.insert_one(doc)
    return clean_doc(doc)

@api.delete("/exercises/{eid}")
async def exercises_delete(eid: str, _: dict = Depends(require_role("coach"))):
    await db.exercises.delete_one({"id": eid})
    return {"ok": True}


# ------------------------------------------------------------------
# Check-ins / Nutrition / Progress / Messages (V1, retained)
# ------------------------------------------------------------------
@api.post("/checkins")
async def checkin_create(body: CheckInBody, user: dict = Depends(current_user)):
    doc = {"id": new_id(), "user_id": user["id"], "created_at": now_iso(), **body.model_dump()}
    await db.checkins.insert_one(doc); return clean_doc(doc)

@api.get("/checkins")
async def checkin_list(user: dict = Depends(current_user)):
    return await db.checkins.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(50)


MEAL_SYSTEM = 'You are a nutrition coach for airline crew. Given a meal photo + description, output STRICT JSON: {"calories":Int,"protein_g":Int,"quality":Int (1-10),"tip":"...","summary":"..."}'

@api.post("/nutrition/meals")
async def meal_create(body: MealBody, user: dict = Depends(current_user)):
    doc = {"id": new_id(), "user_id": user["id"], "created_at": now_iso(), **body.model_dump(), "ai_feedback": None}
    if body.photo_base64 and body.photo_mime:
        p = await write_temp(body.photo_base64, body.photo_mime)
        try:
            raw = await call_gemini_file(MEAL_SYSTEM,
                f"Meal type: {body.meal_type}. Description: {body.description}", p, body.photo_mime)
            try:
                fb = parse_json_from_text(raw)
                doc["ai_feedback"] = fb
                if not doc.get("calories") and fb.get("calories"): doc["calories"] = fb["calories"]
                if not doc.get("protein_g") and fb.get("protein_g"): doc["protein_g"] = fb["protein_g"]
            except Exception:
                doc["ai_feedback"] = {"summary": raw[:400]}
        finally:
            try: os.unlink(p)
            except Exception: pass
    await db.meals.insert_one(doc); return clean_doc(doc)


@api.get("/nutrition/meals")
async def meal_list(user: dict = Depends(current_user), date_filter: Optional[str] = None):
    q = {"user_id": user["id"]}
    if date_filter: q["created_at"] = {"$regex": f"^{date_filter}"}
    return await db.meals.find(q, {"_id": 0}).sort("created_at", -1).to_list(100)

@api.get("/nutrition/summary")
async def nutrition_summary(user: dict = Depends(current_user)):
    t = today_str()
    rows = await db.meals.find({"user_id": user["id"], "created_at": {"$regex": f"^{t}"}}, {"_id": 0}).to_list(50)
    cal = sum(r.get("calories") or 0 for r in rows)
    pro = sum(r.get("protein_g") or 0 for r in rows)
    p = user.get("profile", {}) or {}
    return {"date": t, "calories": cal, "protein_g": pro,
            "calorie_target": p.get("calorie_target", 2200), "protein_target": p.get("protein_target", 150),
            "meals": rows}


@api.post("/progress")
async def progress_create(body: ProgressBody, user: dict = Depends(current_user)):
    doc = {"id": new_id(), "user_id": user["id"], "created_at": now_iso(), **body.model_dump()}
    await db.progress.insert_one(doc); return clean_doc(doc)

@api.get("/progress")
async def progress_list(user: dict = Depends(current_user)):
    return await db.progress.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(100)


@api.post("/messages")
async def msg_send(body: MessageBody, user: dict = Depends(current_user)):
    doc = {"id": new_id(), "from_user_id": user["id"], "to_user_id": body.to_user_id,
           "text": body.text, "created_at": now_iso(), "read": False}
    await db.messages.insert_one(doc); clean_doc(doc)
    try:
        await send_push([body.to_user_id], {"title": user.get("name", "CrewFit"), "message": body.text[:120], "action_url": "/(client)/messages"})
    except Exception as e:
        logger.warning("push send fail: %s", e)
    return doc

@api.get("/messages/{other_id}")
async def msg_thread(other_id: str, user: dict = Depends(current_user)):
    return await db.messages.find(
        {"$or": [{"from_user_id": user["id"], "to_user_id": other_id},
                 {"from_user_id": other_id, "to_user_id": user["id"]}]}, {"_id": 0}
    ).sort("created_at", 1).to_list(500)

@api.get("/messages")
async def msg_partners(user: dict = Depends(current_user)):
    if user["role"] == "client":
        cid = user.get("coach_id")
        c = await db.users.find_one({"id": cid}, {"_id": 0, "password_hash": 0}) if cid else None
        if not c: c = await db.users.find_one({"role": "coach"}, {"_id": 0, "password_hash": 0})
        return [c] if c else []
    rows = await db.users.find({"role": "client", "coach_id": user["id"]}, {"_id": 0, "password_hash": 0}).to_list(200)
    if not rows:
        rows = await db.users.find({"role": "client"}, {"_id": 0, "password_hash": 0}).to_list(200)
    return rows


# ------------------------------------------------------------------
# Coach dashboard
# ------------------------------------------------------------------
async def _client_summary(u: dict) -> dict:
    r = await db.rosters.find_one({"user_id": u["id"], "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    expiry = _roster_expiry(r) if r else {"days_remaining": None, "coverage": "no_roster", "expired": True}
    pending = await db.workouts.count_documents({"user_id": u["id"], "approved": False})
    red_days = 0
    missed = 0
    if r:
        red_days = sum(1 for d in r.get("days", []) if d.get("load") == "red")
    # workouts scheduled up to yesterday not completed
    y = today_str()
    missed = await db.workouts.count_documents({"user_id": u["id"], "date": {"$lt": y}, "completed": {"$ne": True}})
    return {
        **u,
        "latest_roster": r or None,
        "roster_expiry": expiry,
        "pending_approvals": pending,
        "red_days": red_days,
        "missed_workouts": missed,
    }


@api.get("/coach/clients")
async def coach_clients(_: dict = Depends(require_role("coach"))):
    rows = await db.users.find({"role": "client"}, {"_id": 0, "password_hash": 0}).to_list(500)
    return [await _client_summary(u) for u in rows]


@api.get("/coach/dashboard")
async def coach_dashboard(filter: Optional[str] = None, _: dict = Depends(require_role("coach"))):
    rows = await db.users.find({"role": "client"}, {"_id": 0, "password_hash": 0}).to_list(500)
    summaries = [await _client_summary(u) for u in rows]
    buckets = {
        "expiring_soon": [s for s in summaries if s["roster_expiry"].get("coverage") in ("low", "critical")],
        "expired": [s for s in summaries if s["roster_expiry"].get("expired")],
        "no_roster": [s for s in summaries if not s.get("latest_roster")],
        "needs_confirmation": [s for s in summaries if s.get("latest_roster") and not s["latest_roster"].get("confirmed")],
        "pending_approval": [s for s in summaries if s.get("pending_approvals", 0) > 0],
        "red_days": [s for s in summaries if s.get("red_days", 0) > 0],
        "missed": [s for s in summaries if s.get("missed_workouts", 0) > 0],
        "all": summaries,
    }
    if filter and filter in buckets:
        return {"clients": buckets[filter], "counts": {k: len(v) for k, v in buckets.items() if k != "all"}, "total": len(summaries)}
    return {"clients": summaries, "counts": {k: len(v) for k, v in buckets.items() if k != "all"}, "total": len(summaries)}


@api.get("/coach/clients/{client_id}")
async def coach_client_detail(client_id: str, _: dict = Depends(require_role("coach"))):
    c = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not c:
        raise HTTPException(404, "Client not found")
    r = await db.rosters.find_one({"user_id": client_id, "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    if r: r["expiry"] = _roster_expiry(r)
    workouts = await db.workouts.find({"user_id": client_id}, {"_id": 0}).sort("date", 1).to_list(500)
    checkins = await db.checkins.find({"user_id": client_id}, {"_id": 0}).sort("created_at", -1).to_list(10)
    history = await db.rosters.find({"user_id": client_id}, {"_id": 0, "raw_response": 0}).sort("created_at", -1).to_list(20)
    return {"client": c, "roster": r, "workouts": workouts, "checkins": checkins, "roster_history": history}


@api.get("/coach/pending-approvals")
async def coach_pending(_: dict = Depends(require_role("coach"))):
    rows = await db.workouts.find({"approved": False}, {"_id": 0}).sort("date", 1).to_list(500)
    for r in rows:
        u = await db.users.find_one({"id": r["user_id"]}, {"_id": 0, "name": 1})
        r["client_name"] = u.get("name") if u else "Unknown"
    return rows


# ------------------------------------------------------------------
# Seed
# ------------------------------------------------------------------
DEFAULT_EXERCISES = [
    # (name, category, equipment[], mp, muscle, home_ok, hotel_ok, bw, level, joints, fatigue, pre, post)
    ("Goblet Squat", "legs", ["dumbbell", "kettlebell"], "squat", "quads", True, True, False, "intermediate", 8, "medium", False, True),
    ("Push-Up", "push", ["bodyweight"], "push", "chest", True, True, True, "beginner", 9, "low", True, True),
    ("Dumbbell Row", "pull", ["dumbbell"], "pull", "back", True, True, False, "intermediate", 9, "medium", True, True),
    ("Hip Hinge", "legs", ["bodyweight"], "hinge", "hamstring", True, True, True, "beginner", 8, "low", True, True),
    ("Plank", "core", ["bodyweight"], "isometric", "core", True, True, True, "beginner", 10, "low", True, True),
    ("Zone 2 Walk", "cardio", ["bodyweight"], "cardio", "cv", True, True, True, "beginner", 10, "low", True, True),
    ("World's Greatest Stretch", "mobility", ["bodyweight"], "mobility", "full", True, True, True, "beginner", 10, "low", True, True),
    ("Band Pull-Apart", "pull", ["band"], "pull", "rear delt", True, True, False, "beginner", 10, "low", True, True),
    ("Bulgarian Split Squat", "legs", ["dumbbell"], "squat", "quads", True, True, False, "intermediate", 7, "high", False, False),
    ("Dead Bug", "core", ["bodyweight"], "anti-extension", "core", True, True, True, "beginner", 10, "low", True, True),
    ("Overhead Press", "push", ["dumbbell", "barbell"], "push", "shoulder", True, True, False, "intermediate", 7, "medium", False, True),
    ("90/90 Hip Rotation", "mobility", ["bodyweight"], "mobility", "hip", True, True, True, "beginner", 10, "low", True, True),
    ("Kettlebell Swing", "legs", ["kettlebell"], "hinge", "posterior", True, False, False, "intermediate", 7, "high", False, False),
    ("Pike Push-Up", "push", ["bodyweight"], "push", "shoulder", True, True, True, "intermediate", 8, "medium", True, True),
    ("Split Squat", "legs", ["bodyweight", "dumbbell"], "squat", "quads", True, True, True, "beginner", 8, "medium", True, True),
    ("Farmer Carry", "core", ["dumbbell", "kettlebell"], "carry", "grip/core", True, False, False, "intermediate", 10, "medium", True, True),
    ("Glute Bridge", "legs", ["bodyweight"], "hinge", "glute", True, True, True, "beginner", 10, "low", True, True),
    ("Bent-Over Row (band)", "pull", ["band"], "pull", "back", True, True, False, "beginner", 9, "low", True, True),
    ("Incline Walk (treadmill)", "cardio", ["treadmill"], "cardio", "cv", False, True, False, "beginner", 10, "low", True, True),
    ("Assault Bike Zone 2", "cardio", ["assault bike"], "cardio", "cv", True, False, False, "intermediate", 10, "medium", True, True),
]


async def seed():
    coach_email = "coach@crewfit.com"
    client_email = "client@crewfit.com"
    coach = await db.users.find_one({"email": coach_email})
    if not coach:
        coach_id = new_id()
        await db.users.insert_one({
            "id": coach_id, "email": coach_email, "name": "Coach Kai", "role": "coach",
            "password_hash": hash_pw("Coach123!"), "created_at": now_iso(),
            "onboarded": True, "coach_id": None, "profile": {"bio": "Head Coach, Aviation Fitness"},
        })
    else:
        coach_id = coach["id"]

    if not await db.users.find_one({"email": client_email}):
        await db.users.insert_one({
            "id": new_id(), "email": client_email, "name": "Alex Rivera",
            "role": "client", "password_hash": hash_pw("Client123!"),
            "created_at": now_iso(), "onboarded": True, "coach_id": coach_id,
            "profile": {
                "airline": "Skyline Air", "position": "First Officer",
                "home_base": "LHR", "experience_level": "intermediate",
                "training_days_per_week": 4, "goal": "Stay strong on rotations, drop 4kg",
                "equipment": ["dumbbells", "resistance bands", "pull-up bar", "yoga mat", "foam roller"],
                "cardio_equipment": [], "training_location": "home gym",
                "max_home_minutes": 45, "preferred_days": [],
                "disliked_exercises": "", "injuries": "",
                "strength_level": "intermediate", "will_run_outside": True, "swim_cycle": None,
                "height_cm": 180, "weight_kg": 82, "calorie_target": 2400, "protein_target": 160,
            },
        })

    await db.users.update_many({"role": "client", "coach_id": None}, {"$set": {"coach_id": coach_id}})

    if await db.exercises.count_documents({}) == 0:
        for (name, cat, eq, mp, mg, home_ok, hotel_ok, bw, lvl, joint, fat, pre, post) in DEFAULT_EXERCISES:
            await db.exercises.insert_one({
                "id": new_id(), "created_at": now_iso(),
                "name": name, "category": cat, "equipment": eq,
                "movement_pattern": mp, "muscle_group": mg,
                "home_ok": home_ok, "hotel_ok": hotel_ok, "bodyweight_ok": bw,
                "level": lvl, "knee_friendly": joint, "back_friendly": joint, "shoulder_friendly": joint,
                "fatigue_cost": fat, "ok_before_flight": pre, "ok_after_flight": post,
                "demo_url": None, "notes": None, "common_mistakes": None,
                "regressions": None, "progressions": None,
            })

    # Seed a couple hotels (community)
    if await db.hotels.count_documents({}) == 0:
        for h in [
            {"name": "Marina Bay Sands", "city": "Singapore", "country": "SG",
             "gym_available": True, "equipment": {"dumbbells": True, "treadmill": True, "bench": True, "cable_machine": True, "pool": True},
             "outdoor_safe": True, "pool": True, "opening_hours": "24h"},
            {"name": "Sofitel LAX", "city": "Los Angeles", "country": "US",
             "gym_available": True, "equipment": {"dumbbells": True, "treadmill": True, "bike": True, "bench": True},
             "outdoor_safe": False, "pool": False, "opening_hours": "05:00-23:00"},
        ]:
            await _upsert_hotel(HotelBody(**h), coach_id)


@app.on_event("startup")
async def _startup():
    await seed()

@app.on_event("shutdown")
async def _shutdown():
    client.close()
    if _push_client is not None:
        await _push_client.aclose()


@api.get("/")
async def root():
    return {"service": "CrewFit V1.5", "ok": True}


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)
