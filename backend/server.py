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
    key_session: Optional[bool] = None
    event_phase: Optional[str] = None

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
# Workout Intelligence + Weekly Video Script models
# ------------------------------------------------------------------
COACH_STYLES = [
    "professional", "friendly", "high_performance", "military",
    "encouraging", "direct", "humorous",
]

PREFERRED_CHANNELS = [
    "Jeff Nippard", "Squat University", "Renaissance Periodization",
    "Mind Pump", "Athlean-X", "N1 Education", "Built With Science",
]


class ExerciseVideoBody(BaseModel):
    video_url: str
    video_channel: Optional[str] = None
    video_length_sec: Optional[int] = None
    is_coach_video: bool = False


class CheckinQuestionsBody(BaseModel):
    context: Optional[str] = None  # optional free hint from client


class CheckinAdaptiveBody(BaseModel):
    week_start: str
    answers: dict  # question_id -> answer (string or int)
    energy: int = Field(ge=1, le=10)
    sleep: int = Field(ge=1, le=10)
    soreness: int = Field(ge=1, le=10)
    stress: int = Field(ge=1, le=10)
    weight_kg: Optional[float] = None
    notes: Optional[str] = None


class ScriptGenerateBody(BaseModel):
    client_id: str
    style: Optional[str] = None  # override


class ScriptUpdateBody(BaseModel):
    script: Optional[str] = None
    summary_bullets: Optional[list[str]] = None
    whatsapp: Optional[str] = None
    push_text: Optional[str] = None
    approved: Optional[bool] = None
    sent_at: Optional[str] = None


class CoachStyleBody(BaseModel):
    style: str  # one of COACH_STYLES


# ------------------------------------------------------------------
# Dynamic Schedule Engine (§24) & Workout Player (§25) models
# ------------------------------------------------------------------
DAILY_HAPPENED_TAGS = [
    "yes_as_planned", "flight_delayed", "called_from_standby", "slept_badly",
    "ill", "family_plans", "hotel_changed", "workout_completed",
    "workout_missed", "less_time", "other",
]

SCHEDULE_MODES = ["normal", "standby", "sickness", "holiday", "recovery", "paused"]
WORKOUT_PLAYERS = ["free", "guided_strength", "guided_timer", "auto"]  # 'auto' = ask each time
HOLIDAY_TYPES = ["business_trip", "beach", "city", "cruise", "adventure", "ski", "family", "staycation"]


class DailyHappenedBody(BaseModel):
    date: Optional[str] = None
    tag: str  # one of DAILY_HAPPENED_TAGS
    note: Optional[str] = None


class ScheduleEventBody(BaseModel):
    kind: str  # e.g. "standby_on", "sickness_on", "holiday_on", "roster_change"
    details: dict = {}
    change_type: Optional[str] = None  # minor | moderate | major
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class StandbyBody(BaseModel):
    active: bool
    date: Optional[str] = None


class SicknessBody(BaseModel):
    active: bool
    illness: Optional[str] = None
    severity: Optional[int] = Field(default=None, ge=1, le=10)
    started_at: Optional[str] = None
    doctor_advised_rest: Optional[bool] = None


class HolidayBody(BaseModel):
    active: bool
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    holiday_type: Optional[str] = None
    goal: Optional[str] = None  # maintain | improve | relax | normal | break
    equipment: list[str] = []


class PlayerPrefBody(BaseModel):
    default_player: str  # one of WORKOUT_PLAYERS
    auto_flow: Optional[bool] = None
    rest_timer_mode: Optional[str] = None  # auto | manual | none


class SmartReplanBody(BaseModel):
    reason: str  # short human explanation
    dates: Optional[list[str]] = None
    scope: str = "affected"  # affected | week | month


# ------------------------------------------------------------------
# Event Training Mode
# ------------------------------------------------------------------
EVENT_TYPES = [
    "5K", "10K", "half marathon", "marathon", "ultramarathon",
    "sprint triathlon", "Olympic triathlon", "Ironman 70.3", "full Ironman",
    "cycling event", "swimming event", "HYROX",
    "strength goal", "military/police/fire test", "custom",
]

class EventBody(BaseModel):
    user_id: Optional[str] = None            # coach may set on behalf of a client
    event_type: str
    event_name: str
    event_date: str                          # YYYY-MM-DD
    current_ability: Optional[str] = None
    previous_time: Optional[str] = None
    target_time: Optional[str] = None
    weekly_availability_min: Optional[int] = None
    longest_recent: Optional[str] = None
    injury_history: Optional[str] = None
    preferred_days: list[str] = []
    access_gym: bool = False
    access_pool: bool = False
    access_bike: bool = False
    access_treadmill: bool = False
    include_strength: bool = True
    include_mobility: bool = True
    notes: Optional[str] = None


def _event_phase(event_date_iso: str) -> dict:
    """Compute weeks-to-race + training phase for the given race date."""
    try:
        ed = datetime.fromisoformat(event_date_iso).date()
    except Exception:
        return {"weeks_to_race": None, "phase": "unknown", "days_to_race": None}
    today = date.today()
    days = (ed - today).days
    weeks = days // 7 if days >= 0 else -((-days) // 7)
    if days < 0 and abs(days) <= 14:
        phase = "recovery"
    elif days < 0:
        phase = "post"
    elif days <= 7:
        phase = "race_week"
    elif days <= 21:
        phase = "taper"
    elif weeks <= 8:
        phase = "peak"
    elif weeks <= 14:
        phase = "build"
    else:
        phase = "base"
    return {"weeks_to_race": weeks, "days_to_race": days, "phase": phase}


@api.post("/events")
async def event_upsert(body: EventBody, user: dict = Depends(current_user)):
    # coach may set on behalf of a client; client only for themselves
    owner_id = body.user_id if (user["role"] == "coach" and body.user_id) else user["id"]
    doc = {
        "id": new_id(),
        "user_id": owner_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "is_active": True,
        **body.model_dump(exclude={"user_id"}),
    }
    # deactivate previous events for this user (never delete — history)
    await db.events.update_many({"user_id": owner_id, "is_active": True}, {"$set": {"is_active": False}})
    await db.events.insert_one(doc)
    return clean_doc(doc)


@api.get("/events/current")
async def event_current(user: dict = Depends(current_user)):
    ev = await db.events.find_one({"user_id": user["id"], "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    if not ev:
        return {}
    ev["phase_info"] = _event_phase(ev.get("event_date", ""))
    return ev


@api.get("/events/history")
async def event_history(user: dict = Depends(current_user)):
    rows = await db.events.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(50)
    for e in rows:
        e["phase_info"] = _event_phase(e.get("event_date", ""))
    return rows


@api.patch("/events/{eid}")
async def event_update(eid: str, body: EventBody, user: dict = Depends(current_user)):
    ev = await db.events.find_one({"id": eid})
    if not ev:
        raise HTTPException(404, "Event not found")
    if user["role"] == "client" and ev["user_id"] != user["id"]:
        raise HTTPException(403, "Forbidden")
    updates = body.model_dump(exclude={"user_id"})
    updates["updated_at"] = now_iso()
    await db.events.update_one({"id": eid}, {"$set": updates})
    return await db.events.find_one({"id": eid}, {"_id": 0})


@api.delete("/events/{eid}")
async def event_delete(eid: str, user: dict = Depends(current_user)):
    ev = await db.events.find_one({"id": eid})
    if not ev:
        raise HTTPException(404, "Event not found")
    if user["role"] == "client" and ev["user_id"] != user["id"]:
        raise HTTPException(403, "Forbidden")
    await db.events.update_one({"id": eid}, {"$set": {"is_active": False}})
    return {"ok": True}


@api.get("/coach/clients/{client_id}/event")
async def coach_client_event(client_id: str, _: dict = Depends(require_role("coach"))):
    ev = await db.events.find_one({"user_id": client_id, "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    if not ev:
        return {}
    ev["phase_info"] = _event_phase(ev.get("event_date", ""))
    return ev


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
        s = text.find(op)
        e = text.rfind(cl)
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
    clean_doc(u)
    u.pop("password_hash", None)
    return {"token": token, "user": u}


@api.post("/auth/login")
async def login(body: LoginBody):
    u = await db.users.find_one({"email": body.email.lower()})
    if not u or not verify_pw(body.password, u["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    token = make_token(u["id"], u["role"])
    clean_doc(u)
    u.pop("password_hash", None)
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
            logger.warning("EMERGENT_PUSH_KEY missing/placeholder — push disabled until deploy")
        elif resp.status_code >= 400:
            logger.warning("register_push non-2xx %s: %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("register_push failed (non-blocking): %s", e)
    return {"status": "registered"}


async def send_push(recipients: list[str], data: dict, idempotency_key: Optional[str] = None) -> None:
    if not recipients:
        return
    if len(recipients) > 100:
        logger.warning("send_push skipped: too many recipients")
        return
    if "title" not in data or "message" not in data:
        return
    payload: dict = {"recipients": recipients, "data": data}
    if idempotency_key:
        payload["$idempotency_key"] = idempotency_key
    try:
        resp = await push_client().post("/api/v1/push/trigger", json=payload)
        if resp.status_code >= 400:
            logger.warning("send_push non-2xx: %s", resp.status_code)
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
    """Legacy synchronous extract — kept for backwards-compat.
    Prefer POST /roster/upload-and-generate for the new one-shot background flow."""
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
        try:
            os.unlink(path)
        except Exception:
            pass

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


# ------------------------------------------------------------------
# Unified upload → parse → generate BACKGROUND JOB (fixes 504)
# ------------------------------------------------------------------
class RosterUploadGenerateBody(BaseModel):
    file_base64: str
    mime_type: str
    filename: Optional[str] = None


ROSTER_JOB_STAGES = [
    ("uploading", "Uploading roster", 5),
    ("reading", "Reading file", 15),
    ("extracting", "Extracting duties", 30),
    ("detecting", "Detecting layovers, turnarounds and days off", 50),
    ("overlap", "Checking for roster overlaps", 60),
    ("calendar", "Building your CrewFit calendar", 70),
    ("generating", "Generating your personalised plan", 90),
    ("coach", "Preparing coach review", 98),
    ("complete", "Your new plan is ready", 100),
]


async def _set_job(job_id: str, **fields):
    fields["updated_at"] = now_iso()
    await db.roster_jobs.update_one({"id": job_id}, {"$set": fields})


async def _detect_overlap(user_id: str, new_days: list[dict]) -> dict:
    """Given new days, find overlapping active roster days for the same user."""
    if not new_days:
        return {"overlapping_dates": [], "changes": []}
    new_by_date = {d["date"]: d for d in new_days if d.get("date")}
    start, end = min(new_by_date), max(new_by_date)
    active = await db.rosters.find({
        "user_id": user_id, "is_active": True,
        "start_date": {"$lte": end}, "end_date": {"$gte": start},
    }, {"_id": 0}).to_list(20)
    overlaps: list[str] = []
    changes: list[dict] = []
    for r in active:
        for d in r.get("days") or []:
            dt = d.get("date")
            if not dt or dt not in new_by_date:
                continue
            overlaps.append(dt)
            nd = new_by_date[dt]
            if (d.get("day_type") != nd.get("day_type")) or (d.get("load") != nd.get("load")):
                changes.append({
                    "date": dt,
                    "prev": {"day_type": d.get("day_type"), "load": d.get("load")},
                    "new": {"day_type": nd.get("day_type"), "load": nd.get("load")},
                })
    return {"overlapping_dates": sorted(set(overlaps)), "changes": changes}


@api.post("/roster/upload-and-generate")
async def roster_upload_and_generate(body: RosterUploadGenerateBody, user: dict = Depends(current_user)):
    """One-shot background job: parse roster → detect overlap → save → generate month.

    Returns {job_id} immediately. Poll GET /roster/jobs/{job_id} for progress."""
    import asyncio as _asyncio
    job_id = new_id()
    await db.roster_jobs.insert_one({
        "id": job_id, "user_id": user["id"],
        "status": "queued", "stage": "uploading",
        "message": "Uploading your roster...",
        "progress": 1, "created_at": now_iso(),
        "filename": body.filename or "roster",
        "roster_id": None, "error": None, "overlap": None, "retry_count": 0,
    })

    async def _worker():
        path: Optional[str] = None
        try:
            await _set_job(job_id, status="processing", stage="uploading", progress=5, message="Uploading your roster...")
            path = await write_temp(body.file_base64, body.mime_type)
            await _set_job(job_id, stage="reading", progress=15, message="Reading your duty pattern...")
            raw = ""
            try:
                raw = await call_gemini_file(ROSTER_SYSTEM, "Extract the complete roster shown. Return only JSON.", path, body.mime_type)
            except Exception as e:
                logger.warning("Gemini roster call failed: %s", e)
            await _set_job(job_id, stage="extracting", progress=30, message="Extracting duties...")
            parsed: Any = {}
            try:
                parsed = parse_json_from_text(raw) if raw else {}
            except Exception as e:
                logger.warning("roster parse failed: %s", e)
            days = parsed.get("days", []) if isinstance(parsed, dict) else parsed
            if not days:
                # Friendly failure — return actionable message rather than 504/stack trace
                await _set_job(job_id, status="failed", stage="extracting", progress=30,
                               error="We couldn't read this roster clearly. Please upload a clearer file or enter the details manually.",
                               message="Roster could not be read")
                return
            await _set_job(job_id, stage="detecting", progress=50, message="Detecting layovers and turnarounds...")
            days.sort(key=lambda d: d.get("date") or "")
            for d in days:
                d.setdefault("flights", [])
                d.setdefault("day_type", "Unknown/Needs Confirmation")
                d.setdefault("confidence", 0.5)
                d["load"] = score_load(d)
                d["home_or_away"] = d.get("home_or_away") or ("away" if "layover" in d["day_type"].lower() else "home" if "home" in d["day_type"].lower() else "unknown")
            first = days[0]["date"]
            last = days[-1]["date"]
            await _set_job(job_id, stage="overlap", progress=60, message="Checking for roster overlaps...")
            overlap = await _detect_overlap(user["id"], days)
            await _set_job(job_id, overlap=overlap)
            # Save roster (mark previous as inactive, preserving history)
            await _set_job(job_id, stage="calendar", progress=70, message="Building your CrewFit calendar...")
            roster = {
                "id": new_id(),
                "user_id": user["id"],
                "created_at": now_iso(),
                "week_start": first,
                "start_date": first,
                "end_date": last,
                "days": days,
                "confirmed": True,  # auto-confirmed for now; user can edit later
                "confirmed_at": now_iso(),
                "is_active": True,
                "raw_response": raw[:6000] if raw else "",
                "source_filename": body.filename,
                "upload_job_id": job_id,
                "day_count": len(days),
                "confidence_avg": round(sum(d.get("confidence", 0.5) for d in days) / max(1, len(days)), 2),
            }
            await db.rosters.update_many({"user_id": user["id"], "is_active": True}, {"$set": {"is_active": False}})
            await db.rosters.insert_one(roster)
            await _set_job(job_id, roster_id=roster["id"], stage="generating", progress=80, message="Generating your personalised plan...")
            # Generate workouts inline
            try:
                workouts = await _generate_month(user, roster)
            except Exception:
                logger.exception("generation failed in job %s", job_id)
                # Roster is saved so user can view calendar; mark job partial
                await _set_job(job_id, status="partial", stage="generating", progress=85,
                               error="Your roster was saved but the training plan couldn't be generated automatically. Tap Retry to try again.",
                               message="Plan generation failed - roster saved")
                return
            existing = {w["date"]: w for w in await db.workouts.find({"user_id": user["id"], "roster_id": roster["id"]}, {"_id": 0}).to_list(500)}
            for w in workouts:
                d = w.get("date")
                if not d:
                    continue
                prev = existing.get(d)
                if prev and (prev.get("coach_locked") or prev.get("completed")):
                    continue
                doc = {
                    "id": prev["id"] if prev else new_id(),
                    "user_id": user["id"], "roster_id": roster["id"], "date": d,
                    "day_load": w.get("day_load", "green"),
                    "title": w.get("title", "Session"),
                    "location": w.get("location", "Home Workout"),
                    "duration_min": w.get("duration_min", 40),
                    "focus": w.get("focus", "full"),
                    "warmup": w.get("warmup", []),
                    "exercises": w.get("exercises", []),
                    "alternatives": w.get("alternatives", {}),
                    "rationale": w.get("rationale", ""),
                    "key_session": bool(w.get("key_session", False)),
                    "event_phase": w.get("event_phase"),
                    "approved": prev.get("approved", False) if prev else False,
                    "completed": False,
                    "coach_notes": prev.get("coach_notes", "") if prev else "",
                    "coach_locked": False,
                    "created_at": prev.get("created_at", now_iso()) if prev else now_iso(),
                    "updated_at": now_iso(),
                }
                await db.workouts.delete_one({"id": doc["id"]})
                await db.workouts.insert_one(doc)
            await _set_job(job_id, stage="coach", progress=98, message="Preparing coach review...")
            # Best-effort coach notification (silent-fail if push disabled)
            try:
                await _notify_coaches_of_new_roster(user, roster, job_id)
            except Exception:
                pass
            await _set_job(job_id, status="complete", stage="complete", progress=100,
                           message="Your new plan is ready", completed_at=now_iso(),
                           workouts_generated=len(workouts))
        except Exception as e:
            logger.exception("roster upload job %s failed", job_id)
            await _set_job(job_id, status="failed", error=str(e)[:400], message="Roster processing failed")
        finally:
            if path:
                try:
                    os.unlink(path)
                except Exception:
                    pass

    _asyncio.create_task(_worker())
    return {"job_id": job_id, "status": "queued", "poll": f"/roster/jobs/{job_id}"}


async def _notify_coaches_of_new_roster(client: dict, roster: dict, job_id: str) -> None:
    """Insert a coach-side alert doc so coach dashboard can highlight new roster.

    Silently no-ops if push/notifications are not configured."""
    await db.coach_alerts.insert_one({
        "id": new_id(),
        "client_id": client["id"],
        "client_name": client.get("name") or client.get("email"),
        "kind": "roster_uploaded",
        "roster_id": roster["id"],
        "job_id": job_id,
        "start_date": roster.get("start_date"),
        "end_date": roster.get("end_date"),
        "day_count": len(roster.get("days") or []),
        "created_at": now_iso(),
        "read": False,
    })


@api.get("/roster/jobs/active")
async def roster_active_job(user: dict = Depends(current_user)):
    """Return the user's most recent still-running job for banner display."""
    j = await db.roster_jobs.find_one(
        {"user_id": user["id"], "status": {"$in": ["queued", "processing"]}},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    return j or {}


@api.get("/roster/jobs/{job_id}")
async def roster_job_status(job_id: str, user: dict = Depends(current_user)):
    j = await db.roster_jobs.find_one({"id": job_id, "user_id": user["id"]}, {"_id": 0})
    if not j:
        raise HTTPException(404, "Job not found")
    return j


@api.post("/roster/jobs/{job_id}/retry")
async def roster_job_retry(job_id: str, user: dict = Depends(current_user)):
    j = await db.roster_jobs.find_one({"id": job_id, "user_id": user["id"]}, {"_id": 0})
    if not j:
        raise HTTPException(404, "Job not found")
    if j.get("status") in ("queued", "processing"):
        return {"job_id": job_id, "status": j["status"]}
    # Reset job, but we need the original file bytes — we didn't store them.
    # Instead, mark the job as needs-reupload and let the client re-send the file.
    raise HTTPException(400, "Please re-upload the file to retry.")


@api.get("/coach/roster-alerts")
async def coach_roster_alerts(unread: bool = True, coach: dict = Depends(require_role("coach"))):
    q: dict = {}
    if unread:
        q["read"] = False
    rows = await db.coach_alerts.find(q, {"_id": 0}).sort("created_at", -1).to_list(50)
    return rows


@api.post("/coach/roster-alerts/mark-read")
async def coach_mark_alerts_read(coach: dict = Depends(require_role("coach"))):
    await db.coach_alerts.update_many({"read": False}, {"$set": {"read": True}})
    return {"ok": True}


# ------------------------------------------------------------------
# Client calendar day override + change history
# ------------------------------------------------------------------
VALID_DAY_TAGS = {
    "annual_leave", "holiday", "sick", "injured", "poor_sleep", "high_stress",
    "family_commitment", "childcare", "travel_day", "no_gym", "hotel_gym",
    "outdoor_run_possible", "limited_time", "extra_time", "standby", "called_out",
    "duty_cancelled", "flight_delayed", "flight_extended", "need_rest", "feeling_good",
}
VALID_DAY_TYPES = {
    "home_day", "turnaround", "layover_arrival", "layover_full", "layover_departure",
    "standby", "reserve", "simulator", "annual_leave", "holiday", "sick", "injury",
    "family", "busy", "rest", "custom",
}
VALID_AVAILABILITY = {"none", "10", "20", "30", "45", "60", "90", "custom"}
VALID_EQUIPMENT = {
    "home_equipment", "gym", "hotel_gym", "bodyweight", "dumbbells",
    "outdoor_run", "pool", "bike", "unknown",
}
VALID_TRAIN_PREF = {"normal", "reduce", "mobility", "rest", "ask_coach", "auto"}


class DayOverrideBody(BaseModel):
    date: str
    day_type: Optional[str] = None
    location: Optional[str] = None
    availability_min: Optional[int] = None
    equipment: Optional[list[str]] = None
    training_preference: Optional[str] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    custom_day_type: Optional[str] = None
    apply_to: Optional[str] = "day"  # 'day' | 'week' | 'forward' | 'note_only'


@api.post("/calendar/day-override")
async def day_override(body: DayOverrideBody, user: dict = Depends(current_user)):
    """Create/update a per-day client override and log the change history entry.

    Overrides are stored in the `day_overrides` collection keyed by (user_id, date).
    They take priority over roster/AI interpretations in `_resolve_display_video`-style
    fashion (see the client home & workout screens which will pick them up)."""
    if not body.date:
        raise HTTPException(400, "date is required")

    prev = await db.day_overrides.find_one({"user_id": user["id"], "date": body.date}, {"_id": 0})

    tags = [t for t in (body.tags or []) if t in VALID_DAY_TAGS or t.startswith("custom:")]

    override = {
        "id": prev.get("id") if prev else new_id(),
        "user_id": user["id"],
        "date": body.date,
        "day_type": body.day_type if body.day_type in VALID_DAY_TYPES else prev.get("day_type") if prev else None,
        "custom_day_type": body.custom_day_type,
        "location": body.location,
        "availability_min": body.availability_min,
        "equipment": [e for e in (body.equipment or []) if e in VALID_EQUIPMENT],
        "training_preference": body.training_preference if body.training_preference in VALID_TRAIN_PREF else None,
        "tags": tags,
        "notes": (body.notes or "").strip() or None,
        "apply_to": body.apply_to or "day",
        "created_by": user["id"],
        "created_by_role": user.get("role", "client"),
        "updated_at": now_iso(),
        "created_at": prev.get("created_at") if prev else now_iso(),
    }

    await db.day_overrides.update_one(
        {"user_id": user["id"], "date": body.date},
        {"$set": override},
        upsert=True,
    )

    # Log the change
    await db.day_change_log.insert_one({
        "id": new_id(),
        "user_id": user["id"],
        "date": body.date,
        "created_at": now_iso(),
        "actor_id": user["id"],
        "actor_role": user.get("role", "client"),
        "prev": prev or {},
        "new": override,
        "apply_to": override["apply_to"],
        "coach_notified": False,
    })

    # If a workout exists on this date and it's not coach-locked, mark it "updating"
    wk = await db.workouts.find_one({"user_id": user["id"], "date": body.date}, {"_id": 0})
    coach_locked = False
    if wk and not wk.get("coach_locked") and not wk.get("completed"):
        set_updates: dict[str, Any] = {"status": "updating", "override_applied": True, "updated_at": now_iso()}
        # Apply hard rules based on override
        if any(t in tags for t in ("annual_leave", "holiday", "sick", "injured", "need_rest")):
            set_updates["status"] = "coach_reviewing"
        await db.workouts.update_one({"id": wk["id"]}, {"$set": set_updates})
    elif wk and wk.get("coach_locked"):
        coach_locked = True

    # Emit a coach alert
    try:
        await db.coach_alerts.insert_one({
            "id": new_id(), "client_id": user["id"],
            "client_name": user.get("name") or user.get("email"),
            "kind": "day_edited", "date": body.date,
            "tags": tags, "apply_to": override["apply_to"],
            "created_at": now_iso(), "read": False,
        })
    except Exception:
        pass

    return {"override": override, "coach_locked": coach_locked}


@api.get("/calendar/day-override")
async def get_day_override(date: str, user: dict = Depends(current_user)):
    o = await db.day_overrides.find_one({"user_id": user["id"], "date": date}, {"_id": 0})
    hist = await db.day_change_log.find({"user_id": user["id"], "date": date}, {"_id": 0}).sort("created_at", -1).to_list(20)
    return {"override": o or None, "history": hist}


@api.delete("/calendar/day-override")
async def clear_day_override(date: str, user: dict = Depends(current_user)):
    prev = await db.day_overrides.find_one({"user_id": user["id"], "date": date}, {"_id": 0})
    if prev:
        await db.day_overrides.delete_one({"user_id": user["id"], "date": date})
        await db.day_change_log.insert_one({
            "id": new_id(), "user_id": user["id"], "date": date, "created_at": now_iso(),
            "actor_id": user["id"], "actor_role": user.get("role", "client"),
            "prev": prev, "new": None, "action": "cleared",
        })
    return {"ok": True}


# ------------------------------------------------------------------
# Multi-month calendar timeline
# ------------------------------------------------------------------
@api.get("/calendar/timeline")
async def calendar_timeline(months_back: int = 2, months_ahead: int = 4, user: dict = Depends(current_user)):
    """Combined multi-month timeline of roster + workouts for the user.

    Uses ALL active rosters (not just most recent) so overlapping / stacked
    rosters render as a continuous timeline.
    """
    from datetime import date as _date
    today = _date.today()
    # Compute start/end range
    y, m = today.year, today.month
    start_m_index = m - months_back
    while start_m_index <= 0:
        start_m_index += 12
        y -= 1
    start_iso = _date(y, start_m_index, 1).isoformat()
    ny, nm = today.year, today.month + months_ahead
    while nm > 12:
        nm -= 12
        ny += 1
    # last day of end month
    from calendar import monthrange
    last_day = monthrange(ny, nm)[1]
    end_iso = _date(ny, nm, last_day).isoformat()

    active_rosters = await db.rosters.find(
        {"user_id": user["id"], "is_active": True}, {"_id": 0},
    ).sort("start_date", 1).to_list(50)
    all_rosters = await db.rosters.find(
        {"user_id": user["id"]}, {"_id": 0, "raw_response": 0},
    ).sort("start_date", 1).to_list(100)

    # Merge all active roster days (latest upload wins on overlap)
    day_map: dict[str, dict] = {}
    for r in active_rosters:
        for d in r.get("days") or []:
            dt = d.get("date")
            if not dt:
                continue
            if dt < start_iso or dt > end_iso:
                continue
            day_map[dt] = {**d, "roster_id": r["id"]}

    # Also collect roster metadata for the History tab
    rosters_meta = [
        {
            "id": r["id"], "start_date": r.get("start_date"), "end_date": r.get("end_date"),
            "created_at": r.get("created_at"), "is_active": r.get("is_active", False),
            "source_filename": r.get("source_filename"), "day_count": len(r.get("days") or []),
            "confidence_avg": r.get("confidence_avg"),
        }
        for r in all_rosters
    ]

    workouts = await db.workouts.find({
        "user_id": user["id"], "date": {"$gte": start_iso, "$lte": end_iso},
    }, {"_id": 0}).sort("date", 1).to_list(2000)
    wk_map = {w["date"]: w for w in workouts}

    # Build month buckets covering the whole range (including blank months for future upload)
    months: list[dict] = []
    cy, cm = _date.fromisoformat(start_iso).year, _date.fromisoformat(start_iso).month
    end_y, end_m = ny, nm
    while (cy, cm) <= (end_y, end_m):
        ldm = monthrange(cy, cm)[1]
        days_out: list[dict] = []
        for dd in range(1, ldm + 1):
            iso = _date(cy, cm, dd).isoformat()
            rday = day_map.get(iso)
            wk = wk_map.get(iso)
            days_out.append({
                "date": iso,
                "day": dd,
                "load": (rday or {}).get("load"),
                "duty_type": (rday or {}).get("day_type"),
                "has_roster": bool(rday),
                "workout_id": (wk or {}).get("id"),
                "workout_title": (wk or {}).get("title"),
                "completed": bool((wk or {}).get("completed")),
                "key_session": bool((wk or {}).get("key_session")),
                "location": (wk or {}).get("location"),
            })
        months.append({
            "year": cy, "month": cm,
            "label": _date(cy, cm, 1).strftime("%B %Y"),
            "iso": _date(cy, cm, 1).isoformat(),
            "days": days_out,
            "has_data": any(d["has_roster"] or d["workout_id"] for d in days_out),
        })
        cm += 1
        if cm > 12:
            cm = 1
            cy += 1

    return {
        "today": today.isoformat(),
        "start_date": start_iso,
        "end_date": end_iso,
        "months": months,
        "rosters": rosters_meta,
        "active_roster_ids": [r["id"] for r in active_rosters],
    }


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
WORKOUT_SYSTEM = """You are CrewFit's elite S&C coach for airline crew.
Given a client profile with home equipment + preferences, a chronological month of roster days (each with day_type, load, home/away, hotel info if any), AND (optionally) an EVENT the client is training for (with target date, phase and remaining weeks), produce a full month training plan.

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

EVENT TRAINING RULES (apply only if an event is provided):
 - Long runs / long rides / long swims should preferably land on home or off-duty days.
 - Hard intervals must NOT be scheduled after night flights, layover arrivals, or poor sleep.
 - Heavy lower-body strength must NOT be placed within 48h before a long run.
 - Phase-aware volume:
     base phase → gradual aerobic build, 1 key long session/week, add strength.
     build phase → intervals + tempo + long session; strength maintained.
     peak phase → highest specific work; still respect roster fatigue.
     taper phase → sharply reduce volume, keep intensity brief and crisp.
     race_week → minimal volume, one short opener 2-3 days out, else mobility/rest.
     recovery → mobility + easy aerobic only for 1-2 weeks post race.
 - If a key session must move because of roster, MOVE it to the best day, do NOT double up.
 - Mark the week's most important session in each workout's `key_session: true`.
 - For triathlon: rotate swim / bike / run and include one brick/week when possible.
 - Balance: if the roster forces cutting volume, prefer to keep the KEY session and drop optional sessions.

For EACH day in the roster, output one workout object:
  date (YYYY-MM-DD)
  day_load — green | amber | red | blue | purple | grey (mirror the input where possible)
  title (short, e.g. "Home Push + Core" or "Long Run — 22km easy")
  location — one of: "Home Workout", "Commercial Gym Workout", "Hotel Gym Workout",
    "Bodyweight Layover Workout", "Flight Recovery Mobility", "Pre-Flight Mobility",
    "Post-Flight Mobility", "Turnaround Recovery", "Outdoor Run", "Pool Swim", "Bike Session", "Rest Day"
  duration_min (int, integer minutes)
  focus (push|pull|legs|full|mobility|zone2|recovery|long_run|intervals|tempo|swim|bike|brick|race_prep)
  warmup: [ {name, duration_sec} ]  (2-4 short items)
  exercises: [ {name, sets:int, reps:string, rest_sec:int, rpe:int (1-10), notes:string} ]
  alternatives: {home:string, hotel:string, no_equipment:string, easier:string, harder:string}
  key_session: bool  (true only for the week's most important session, at most 1-2 per week)
  event_phase: string  (mirror the phase from event_context if provided, else null)
  rationale (2-3 sentences: WHY this day, WHY this location, WHY this intensity — reference the roster AND the event phase if provided)

Return STRICT JSON only:
{"workouts":[{...}]}"""


async def _generate_month(user: dict, roster: dict) -> list[dict]:
    """Chunk by 7-day windows so each Claude call stays well under the
    Cloudflare edge timeout (~60s). Concurrent by week."""
    import asyncio as _asyncio

    profile = user.get("profile", {}) or {}
    all_days = roster.get("days", []) or []
    if not all_days:
        return []

    # Fetch active event for the user (if any) and build event_context
    event_context: Optional[dict] = None
    ev = await db.events.find_one({"user_id": user["id"], "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    if ev:
        pi = _event_phase(ev.get("event_date", ""))
        event_context = {
            "type": ev.get("event_type"),
            "name": ev.get("event_name"),
            "date": ev.get("event_date"),
            "target_time": ev.get("target_time"),
            "current_ability": ev.get("current_ability"),
            "longest_recent": ev.get("longest_recent"),
            "weekly_availability_min": ev.get("weekly_availability_min"),
            "include_strength": ev.get("include_strength", True),
            "include_mobility": ev.get("include_mobility", True),
            "access": {
                "gym": ev.get("access_gym"),
                "pool": ev.get("access_pool"),
                "bike": ev.get("access_bike"),
                "treadmill": ev.get("access_treadmill"),
            },
            "phase": pi.get("phase"),
            "weeks_to_race": pi.get("weeks_to_race"),
            "days_to_race": pi.get("days_to_race"),
            "injury_history": ev.get("injury_history"),
        }

    # Attach hotel info once for the whole prompt set
    hotel_cache: dict[str, dict] = {}
    async def _day_for_prompt(d: dict) -> dict:
        entry = dict(d)
        hid = d.get("hotel_id")
        if hid:
            if hid not in hotel_cache:
                h = await db.hotels.find_one({"id": hid}, {"_id": 0})
                hotel_cache[hid] = h or {}
            h = hotel_cache[hid] or {}
            if h:
                entry["hotel"] = {
                    "name": h.get("name"), "city": h.get("city"),
                    "gym_available": h.get("gym_available"),
                    "equipment": h.get("equipment", {}),
                    "confidence": h.get("confidence", 0),
                }
        return entry

    enriched = [await _day_for_prompt(d) for d in all_days]

    # Chunk into weeks of 7
    chunks = [enriched[i : i + 7] for i in range(0, len(enriched), 7)]

    async def _run_chunk(chunk: list[dict]) -> list[dict]:
        prompt = (
            f"Client profile: {json.dumps(profile)[:2500]}\n"
            f"Event context: {json.dumps(event_context)[:1000] if event_context else 'None'}\n"
            f"Days to plan (chronological, 7-day chunk): {json.dumps(chunk)[:8000]}\n"
            "Design exactly one workout per date in this chunk. Return JSON."
        )
        try:
            raw = await call_claude(WORKOUT_SYSTEM, prompt)
            parsed = parse_json_from_text(raw)
            return parsed.get("workouts", []) if isinstance(parsed, dict) else parsed
        except Exception as e:
            logger.warning("chunk gen failed: %s", e)
            return []

    results = await _asyncio.gather(*[_run_chunk(c) for c in chunks])
    merged: list[dict] = []
    for r in results:
        merged.extend(r or [])
    # Deduplicate by date (keep first)
    seen = set()
    unique: list[dict] = []
    for w in merged:
        d = w.get("date")
        if not d or d in seen:
            continue
        seen.add(d)
        unique.append(w)
    return unique


@api.post("/workouts/generate-month")
async def workouts_generate_month(body: WorkoutGenerateMonthBody, user: dict = Depends(current_user)):
    """Kick off month generation in the background and return a job id immediately.
    The client polls /workouts/job/{id} until status='done'."""
    import asyncio as _asyncio

    r = await db.rosters.find_one({"id": body.roster_id, "user_id": user["id"]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Roster not found")

    job_id = new_id()
    total = len(r.get("days", []))
    await db.gen_jobs.insert_one({
        "id": job_id, "user_id": user["id"], "roster_id": body.roster_id,
        "status": "running", "created_at": now_iso(),
        "total": total, "done": 0, "errors": [],
    })

    async def _worker():
        try:
            workouts = await _generate_month(user, r)
            existing = {w["date"]: w for w in await db.workouts.find({"user_id": user["id"], "roster_id": body.roster_id}, {"_id": 0}).to_list(500)}
            for w in workouts:
                d = w.get("date")
                if not d:
                    continue
                prev = existing.get(d)
                if prev and (prev.get("coach_locked") or prev.get("completed")):
                    continue
                doc = {
                    "id": prev["id"] if prev else new_id(),
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
                    "key_session": bool(w.get("key_session", False)),
                    "event_phase": w.get("event_phase"),
                    "approved": prev.get("approved", False) if prev else False,
                    "completed": False,
                    "coach_notes": prev.get("coach_notes", "") if prev else "",
                    "coach_locked": False,
                    "created_at": prev.get("created_at", now_iso()) if prev else now_iso(),
                    "updated_at": now_iso(),
                }
                await db.workouts.delete_one({"id": doc["id"]})
                await db.workouts.insert_one(doc)
            dates_now = {w["date"] for w in workouts}
            await db.workouts.delete_many({
                "user_id": user["id"], "roster_id": body.roster_id,
                "date": {"$nin": list(dates_now)},
                "coach_locked": {"$ne": True}, "completed": {"$ne": True},
            })
            await db.gen_jobs.update_one({"id": job_id}, {"$set": {"status": "done", "done": len(workouts), "finished_at": now_iso()}})
        except Exception as e:
            logger.exception("gen_job %s failed", job_id)
            await db.gen_jobs.update_one({"id": job_id}, {"$set": {"status": "failed", "error": str(e), "finished_at": now_iso()}})

    _asyncio.create_task(_worker())
    return {"status": "queued", "job_id": job_id, "total": total}


@api.get("/workouts/job/{job_id}")
async def workouts_job_status(job_id: str, user: dict = Depends(current_user)):
    j = await db.gen_jobs.find_one({"id": job_id, "user_id": user["id"]}, {"_id": 0})
    if not j:
        raise HTTPException(404, "Job not found")
    if j.get("status") == "done":
        j["workouts"] = await db.workouts.find({"user_id": user["id"], "roster_id": j["roster_id"]}, {"_id": 0}).sort("date", 1).to_list(500)
    return j


@api.post("/workouts/regenerate")
async def workouts_regenerate(body: WorkoutRegenerateBody, user: dict = Depends(current_user)):
    """Background regeneration to avoid Cloudflare/ingress 504 timeouts.

    Returns {job_id} immediately. Poll GET /workouts/job/{job_id} for progress."""
    import asyncio as _asyncio

    r = await db.rosters.find_one({"id": body.roster_id, "user_id": user["id"]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Roster not found")

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

    sub_days = [d for d in r.get("days", []) if in_scope(d.get("date", ""))]
    if not sub_days:
        raise HTTPException(400, "No days matched the regenerate scope")
    sub = {**r, "days": sub_days}

    job_id = new_id()
    await db.gen_jobs.insert_one({
        "id": job_id, "user_id": user["id"], "roster_id": body.roster_id,
        "status": "running", "created_at": now_iso(),
        "total": len(sub_days), "done": 0, "errors": [], "kind": "regenerate",
    })

    async def _worker():
        try:
            workouts = await _generate_month(user, sub)
            for w in workouts:
                d = w.get("date")
                if not d:
                    continue
                existing = await db.workouts.find_one({"user_id": user["id"], "roster_id": body.roster_id, "date": d}, {"_id": 0})
                if existing and (existing.get("coach_locked") or existing.get("completed")):
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
                    "key_session": bool(w.get("key_session", False)),
                    "event_phase": w.get("event_phase"),
                    "approved": False,
                    "completed": False,
                    "coach_notes": existing.get("coach_notes", "") if existing else "",
                    "coach_locked": False,
                    "created_at": existing.get("created_at", now_iso()) if existing else now_iso(),
                    "updated_at": now_iso(),
                }
                await db.workouts.delete_one({"id": doc["id"]})
                await db.workouts.insert_one(doc)
            await db.gen_jobs.update_one({"id": job_id}, {"$set": {"status": "done", "done": len(workouts), "finished_at": now_iso()}})
        except Exception as e:
            logger.exception("regenerate job %s failed", job_id)
            await db.gen_jobs.update_one({"id": job_id}, {"$set": {"status": "failed", "error": str(e)[:400], "finished_at": now_iso()}})

    _asyncio.create_task(_worker())
    return {"status": "queued", "job_id": job_id, "total": len(sub_days)}


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


def youtube_search_url(name: str, channel: Optional[str] = None) -> str:
    q = f"{channel} {name}" if channel else name
    return "https://www.youtube.com/results?search_query=" + q.replace(" ", "+")


@api.patch("/exercises/{eid}/video")
async def exercises_set_video(eid: str, body: ExerciseVideoBody, coach: dict = Depends(require_role("coach"))):
    ex = await db.exercises.find_one({"id": eid})
    if not ex:
        raise HTTPException(404, "Exercise not found")
    updates: dict = {
        "video_last_verified_at": now_iso(),
    }
    if body.is_coach_video:
        # Coach uploads always win
        updates["coach_video_url"] = body.video_url
    else:
        # Only set the YT video if a coach video isn't already set
        if not ex.get("coach_video_url"):
            updates["video_url"] = body.video_url
            updates["video_channel"] = body.video_channel
            updates["video_length_sec"] = body.video_length_sec
    await db.exercises.update_one({"id": eid}, {"$set": updates})
    return await db.exercises.find_one({"id": eid}, {"_id": 0})


@api.get("/exercises/{eid}/video-suggestion")
async def exercises_video_suggestion(eid: str, user: dict = Depends(current_user)):
    ex = await db.exercises.find_one({"id": eid}, {"_id": 0})
    if not ex:
        raise HTTPException(404, "Exercise not found")
    # Preference order: coach_video → stored yt → search-url fallback
    if ex.get("coach_video_url"):
        return {"url": ex["coach_video_url"], "source": "coach", "channel": "CrewFit"}
    if ex.get("video_url"):
        return {"url": ex["video_url"], "source": "youtube", "channel": ex.get("video_channel")}
    # Fallback: build a channel-scoped YouTube search URL, prefer channel by movement pattern
    channel = PREFERRED_CHANNELS[0]
    return {
        "url": youtube_search_url(ex["name"], channel),
        "source": "search",
        "channel": channel,
        "note": "no video linked yet — this is a YouTube search fallback",
    }


# ------------------------------------------------------------------
# Adaptive check-in questions (AI-generated per client)
# ------------------------------------------------------------------
QUESTIONS_SYSTEM = """You are CrewFit's coaching AI. Given a client's profile + active event (if any) + latest roster snapshot, produce a personalised 6-question weekly check-in.
Rules:
 - Questions must be relevant to their goal, event and aviation context. Marathoner? Ask about long run. Long-haul pilot? Ask about jet lag & sleep on layovers. Fat loss client? Ask about hunger & adherence. Ironman? Ask separately about swim, bike, run.
 - Mix numeric scales (1-10) with 1-2 short free-text questions.
 - Every set must include one 1-10 question for RECOVERY.
Return STRICT JSON:
{"questions":[{"id":"snake_case_id","label":"...","type":"scale|text","scale_max":10,"placeholder":"..."}]}"""


@api.post("/checkins/questions")
async def checkin_questions(body: CheckinQuestionsBody, user: dict = Depends(current_user)):
    profile = user.get("profile", {}) or {}
    ev = await db.events.find_one({"user_id": user["id"], "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    roster = await db.rosters.find_one({"user_id": user["id"], "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    roster_snap = None
    if roster:
        roster_snap = {
            "start_date": roster.get("start_date"),
            "end_date": roster.get("end_date"),
            "types": list({d.get("day_type") for d in (roster.get("days", []) or []) if d.get("day_type")}),
        }
    prompt = (
        f"Profile: {json.dumps(profile)[:1500]}\n"
        f"Event: {json.dumps(ev)[:600] if ev else 'None'}\n"
        f"Roster: {json.dumps(roster_snap)[:600] if roster_snap else 'None'}\n"
        f"Extra: {body.context or ''}\nGenerate the questions now."
    )
    try:
        raw = await call_claude(QUESTIONS_SYSTEM, prompt)
        parsed = parse_json_from_text(raw)
        qs = parsed.get("questions", []) if isinstance(parsed, dict) else []
    except Exception as e:
        logger.warning("checkin questions fail: %s", e)
        qs = []
    if not qs:
        qs = [
            {"id": "recovery", "label": "How's your overall recovery?", "type": "scale", "scale_max": 10},
            {"id": "sleep_quality", "label": "How was sleep this week?", "type": "scale", "scale_max": 10},
            {"id": "adherence", "label": "How many planned sessions did you hit?", "type": "scale", "scale_max": 10},
            {"id": "wins", "label": "One win from this week?", "type": "text", "placeholder": "e.g. hit protein 6/7 days"},
            {"id": "challenges", "label": "Biggest challenge next week?", "type": "text"},
            {"id": "time_available", "label": "Hours available for training next week", "type": "scale", "scale_max": 10},
        ]
    return {"questions": qs}


@api.post("/checkins/adaptive")
async def checkin_adaptive(body: CheckinAdaptiveBody, user: dict = Depends(current_user)):
    doc = {
        "id": new_id(), "user_id": user["id"], "created_at": now_iso(),
        "week_start": body.week_start,
        "energy": body.energy, "sleep": body.sleep, "soreness": body.soreness, "stress": body.stress,
        "weight_kg": body.weight_kg, "notes": body.notes,
        "answers": body.answers,
    }
    await db.checkins.insert_one(doc)
    # Fire-and-forget: generate weekly script for the coach
    if user.get("coach_id"):
        try:
            import asyncio as _asyncio
            _asyncio.create_task(_generate_script_for(user["id"], user["coach_id"]))
        except Exception as e:
            logger.warning("script gen kickoff failed: %s", e)
    return clean_doc(doc)


# ------------------------------------------------------------------
# Coach Weekly Video Script Generator
# ------------------------------------------------------------------
SCRIPT_SYSTEM = """You are ghostwriting a weekly personal coaching video script for CrewFit's head coach to record and send to an aviation-crew client.

Requirements:
 - Length: 45-120 seconds spoken (roughly 120-260 words).
 - Sound natural and conversational, never robotic. Use the client's first name.
 - Structure: greeting → celebrate specific win → recovery comment → nutrition/adherence comment → roster/travel comment → this week's focus → highlight KEY session or a challenge → motivational close.
 - Reference concrete facts from the data (specific numbers, dates, layover cities, session titles).

Also produce:
 - summary_bullets: 5-7 short bullet points for the coach's own use (numbers first)
 - whatsapp: 3-5 sentence WhatsApp-friendly version
 - push_text: ONE motivational push notification, ≤80 chars

Coach style: {style}

Return STRICT JSON:
{{"script":"...","summary_bullets":["..."],"whatsapp":"...","push_text":"..."}}"""


async def _generate_script_for(client_id: str, coach_id: str, style_override: Optional[str] = None) -> dict:
    client_user = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    coach_user = await db.users.find_one({"id": coach_id}, {"_id": 0, "password_hash": 0})
    if not client_user or not coach_user:
        raise HTTPException(404, "Client or coach not found")
    style = style_override or (coach_user.get("profile", {}) or {}).get("style") or "friendly"
    if style not in COACH_STYLES:
        style = "friendly"

    # gather data
    roster = await db.rosters.find_one({"user_id": client_id, "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    ev = await db.events.find_one({"user_id": client_id, "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    if ev:
        ev["phase_info"] = _event_phase(ev.get("event_date", ""))
    checkin = await db.checkins.find_one({"user_id": client_id}, {"_id": 0}, sort=[("created_at", -1)])
    recent_workouts = await db.workouts.find({"user_id": client_id}, {"_id": 0}).sort("date", -1).to_list(20)
    completed = [w for w in recent_workouts if w.get("completed")]
    missed = [w for w in recent_workouts if not w.get("completed") and w.get("date", "") < today_str()]

    payload = {
        "client_first_name": (client_user.get("name") or "").split(" ")[0] or "there",
        "goal": client_user.get("profile", {}).get("goal"),
        "position": client_user.get("profile", {}).get("position"),
        "airline": client_user.get("profile", {}).get("airline"),
        "event": ev,
        "last_checkin": checkin,
        "recent_completed_titles": [w.get("title") for w in completed[:5]],
        "recent_missed_titles": [w.get("title") for w in missed[:5]],
        "upcoming_days": (roster.get("days", []) if roster else [])[:7],
    }

    try:
        raw = await call_claude(SCRIPT_SYSTEM.format(style=style), json.dumps(payload)[:6000])
        parsed = parse_json_from_text(raw)
    except Exception as e:
        logger.warning("script gen fail: %s", e)
        parsed = {
            "script": f"Hi {payload['client_first_name']}, great work this week. Keep the consistency going.",
            "summary_bullets": ["auto-fallback — LLM failed"],
            "whatsapp": "Great effort this week — keep going!",
            "push_text": "Your weekly plan is ready.",
        }

    doc = {
        "id": new_id(),
        "client_id": client_id,
        "coach_id": coach_id,
        "created_at": now_iso(),
        "style": style,
        "script": parsed.get("script", ""),
        "summary_bullets": parsed.get("summary_bullets", []),
        "whatsapp": parsed.get("whatsapp", ""),
        "push_text": parsed.get("push_text", ""),
        "approved": False,
        "sent_at": None,
        "edit_history": [],
    }
    await db.coach_scripts.insert_one(doc)
    return clean_doc(doc)


@api.post("/coach/scripts/generate")
async def coach_script_generate(body: ScriptGenerateBody, coach: dict = Depends(require_role("coach"))):
    return await _generate_script_for(body.client_id, coach["id"], body.style)


@api.get("/coach/scripts")
async def coach_scripts_list(client_id: Optional[str] = None, coach: dict = Depends(require_role("coach"))):
    q: dict = {"coach_id": coach["id"]}
    if client_id:
        q["client_id"] = client_id
    return await db.coach_scripts.find(q, {"_id": 0}).sort("created_at", -1).to_list(50)


@api.get("/coach/scripts/{sid}")
async def coach_script_get(sid: str, coach: dict = Depends(require_role("coach"))):
    s = await db.coach_scripts.find_one({"id": sid, "coach_id": coach["id"]}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Not found")
    return s


@api.patch("/coach/scripts/{sid}")
async def coach_script_update(sid: str, body: ScriptUpdateBody, coach: dict = Depends(require_role("coach"))):
    s = await db.coach_scripts.find_one({"id": sid, "coach_id": coach["id"]}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    # Track edit history when script text changed (learning input)
    if "script" in updates and updates["script"] != s.get("script"):
        s.setdefault("edit_history", []).append({"at": now_iso(), "prev": s.get("script"), "new": updates["script"]})
        updates["edit_history"] = s["edit_history"][-10:]
    if updates.get("sent_at") is None and body.approved and not s.get("sent_at"):
        # Mark send-time when coach approves + push
        updates["sent_at"] = now_iso()
        try:
            await send_push([s["client_id"]], {
                "title": (coach.get("name") or "Coach"),
                "message": s.get("push_text") or "Your weekly plan is ready.",
                "deeplink": "/(client)/messages",
            })
        except Exception as e:
            logger.warning("script push fail: %s", e)
    updates["updated_at"] = now_iso()
    await db.coach_scripts.update_one({"id": sid}, {"$set": updates})
    return await db.coach_scripts.find_one({"id": sid}, {"_id": 0})


@api.patch("/auth/coach-style")
async def set_coach_style(body: CoachStyleBody, coach: dict = Depends(require_role("coach"))):
    if body.style not in COACH_STYLES:
        raise HTTPException(400, f"style must be one of {COACH_STYLES}")
    await db.users.update_one({"id": coach["id"]}, {"$set": {"profile.style": body.style}})
    return {"style": body.style}


# ------------------------------------------------------------------
# Dynamic Schedule Engine — daily check-in, standby, sickness, holiday, replan
# ------------------------------------------------------------------
async def _log_schedule_event(user_id: str, kind: str, details: dict, change_type: str = "minor") -> dict:
    doc = {
        "id": new_id(),
        "user_id": user_id,
        "kind": kind,
        "details": details or {},
        "change_type": change_type,
        "created_at": now_iso(),
        "resolved": False,
    }
    await db.schedule_events.insert_one(doc)
    return clean_doc(doc)


@api.post("/schedule/daily-happened")
async def daily_happened(body: DailyHappenedBody, user: dict = Depends(current_user)):
    if body.tag not in DAILY_HAPPENED_TAGS:
        raise HTTPException(400, f"tag must be one of {DAILY_HAPPENED_TAGS}")
    d = body.date or today_str()
    doc = {
        "id": new_id(), "user_id": user["id"], "date": d,
        "tag": body.tag, "note": body.note, "created_at": now_iso(),
    }
    await db.daily_pulse.update_one({"user_id": user["id"], "date": d}, {"$set": doc}, upsert=True)
    if body.tag not in ("yes_as_planned", "workout_completed"):
        change = "minor"
        if body.tag in ("ill", "called_from_standby"):
            change = "moderate"
        await _log_schedule_event(user["id"], f"daily_{body.tag}", {"date": d, "note": body.note}, change)
    return clean_doc(doc)


@api.get("/schedule/daily-happened")
async def daily_happened_list(user: dict = Depends(current_user)):
    return await db.daily_pulse.find({"user_id": user["id"]}, {"_id": 0}).sort("date", -1).to_list(30)


@api.post("/schedule/standby")
async def schedule_standby(body: StandbyBody, user: dict = Depends(current_user)):
    mode = "standby" if body.active else "normal"
    await db.users.update_one({"id": user["id"]}, {"$set": {"profile.schedule_mode": mode, "profile.standby_active": body.active}})
    await _log_schedule_event(user["id"], "standby_on" if body.active else "standby_off", {"date": body.date or today_str()}, "minor")
    return {"schedule_mode": mode}


@api.post("/schedule/sickness")
async def schedule_sickness(body: SicknessBody, user: dict = Depends(current_user)):
    mode = "sickness" if body.active else "normal"
    payload = {"profile.schedule_mode": mode, "profile.sickness_active": body.active}
    if body.active:
        payload["profile.sickness"] = {
            "illness": body.illness, "severity": body.severity,
            "started_at": body.started_at or now_iso(),
            "doctor_advised_rest": body.doctor_advised_rest,
        }
    await db.users.update_one({"id": user["id"]}, {"$set": payload})
    await _log_schedule_event(user["id"], "sickness_on" if body.active else "sickness_off", body.model_dump(), "moderate" if body.active else "minor")
    return {"schedule_mode": mode}


@api.post("/schedule/holiday")
async def schedule_holiday(body: HolidayBody, user: dict = Depends(current_user)):
    mode = "holiday" if body.active else "normal"
    payload = {"profile.schedule_mode": mode, "profile.holiday_active": body.active}
    if body.active:
        payload["profile.holiday"] = {
            "start_date": body.start_date, "end_date": body.end_date,
            "holiday_type": body.holiday_type, "goal": body.goal, "equipment": body.equipment,
        }
    await db.users.update_one({"id": user["id"]}, {"$set": payload})
    await _log_schedule_event(user["id"], "holiday_on" if body.active else "holiday_off", body.model_dump(), "moderate")
    return {"schedule_mode": mode}


@api.get("/schedule/events")
async def schedule_events(user: dict = Depends(current_user)):
    return await db.schedule_events.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(100)


@api.post("/schedule/smart-replan")
async def smart_replan(body: SmartReplanBody, user: dict = Depends(current_user)):
    """Kick off a targeted regenerate driven by a schedule change. Uses the
    existing background job model. Preserves coach_locked & completed workouts."""
    roster = await db.rosters.find_one({"user_id": user["id"], "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    if not roster:
        raise HTTPException(400, "No active roster to replan")

    dates = body.dates or []
    if body.scope == "week" and dates:
        try:
            base = datetime.fromisoformat(dates[0]).date()
            dates = [(base + timedelta(days=i)).isoformat() for i in range(7)]
        except Exception:
            pass

    # Reuse the regenerate flow synchronously (small scope — few days)
    class _Body:
        pass
    b = _Body()
    b.roster_id = roster["id"]
    b.dates = dates if dates and body.scope != "month" else None
    b.week_start = None
    b.all = (body.scope == "month")

    # Log event + rationale
    await _log_schedule_event(user["id"], "smart_replan", {"reason": body.reason, "scope": body.scope, "dates": dates}, "moderate")
    # Call the shared inner function
    result = await workouts_regenerate(WorkoutRegenerateBody(roster_id=b.roster_id, dates=b.dates, week_start=b.week_start, all=b.all), user)
    return {"reason": body.reason, "scope": body.scope, "dates": dates, **result}


# ------------------------------------------------------------------
# Workout Player (§25)
# ------------------------------------------------------------------
@api.patch("/auth/player-pref")
async def set_player_pref(body: PlayerPrefBody, user: dict = Depends(current_user)):
    if body.default_player not in WORKOUT_PLAYERS:
        raise HTTPException(400, f"default_player must be one of {WORKOUT_PLAYERS}")
    upd = {"profile.default_player": body.default_player}
    if body.auto_flow is not None:
        upd["profile.auto_flow"] = body.auto_flow
    if body.rest_timer_mode:
        upd["profile.rest_timer_mode"] = body.rest_timer_mode
    await db.users.update_one({"id": user["id"]}, {"$set": upd})
    return await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})


class WorkoutPlayerOverrideBody(BaseModel):
    player: str  # one of WORKOUT_PLAYERS


@api.patch("/workouts/{wid}/player")
async def workout_set_player(wid: str, body: WorkoutPlayerOverrideBody, user: dict = Depends(current_user)):
    if body.player not in WORKOUT_PLAYERS:
        raise HTTPException(400, f"player must be one of {WORKOUT_PLAYERS}")
    w = await db.workouts.find_one({"id": wid})
    if not w:
        raise HTTPException(404, "Not found")
    if user["role"] == "client" and w["user_id"] != user["id"]:
        raise HTTPException(403, "Forbidden")
    await db.workouts.update_one({"id": wid}, {"$set": {"player": body.player, "updated_at": now_iso()}})
    return await db.workouts.find_one({"id": wid}, {"_id": 0})


# ------------------------------------------------------------------
# Check-ins / Nutrition / Progress / Messages (V1, retained)
# ------------------------------------------------------------------
@api.post("/checkins")
async def checkin_create(body: CheckInBody, user: dict = Depends(current_user)):
    doc = {"id": new_id(), "user_id": user["id"], "created_at": now_iso(), **body.model_dump()}
    await db.checkins.insert_one(doc)
    return clean_doc(doc)

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
                if not doc.get("calories") and fb.get("calories"):
                    doc["calories"] = fb["calories"]
                if not doc.get("protein_g") and fb.get("protein_g"):
                    doc["protein_g"] = fb["protein_g"]
            except Exception:
                doc["ai_feedback"] = {"summary": raw[:400]}
        finally:
            try:
                os.unlink(p)
            except Exception:
                pass
    await db.meals.insert_one(doc)
    return clean_doc(doc)


@api.get("/nutrition/meals")
async def meal_list(user: dict = Depends(current_user), date_filter: Optional[str] = None):
    q = {"user_id": user["id"]}
    if date_filter:
        q["created_at"] = {"$regex": f"^{date_filter}"}
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
    await db.progress.insert_one(doc)
    return clean_doc(doc)

@api.get("/progress")
async def progress_list(user: dict = Depends(current_user)):
    return await db.progress.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(100)


@api.post("/messages")
async def msg_send(body: MessageBody, user: dict = Depends(current_user)):
    doc = {"id": new_id(), "from_user_id": user["id"], "to_user_id": body.to_user_id,
           "text": body.text, "created_at": now_iso(), "read": False}
    await db.messages.insert_one(doc)
    clean_doc(doc)
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
        if not c:
            c = await db.users.find_one({"role": "coach"}, {"_id": 0, "password_hash": 0})
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
    if r:
        r["expiry"] = _roster_expiry(r)
    workouts = await db.workouts.find({"user_id": client_id}, {"_id": 0}).sort("date", 1).to_list(500)
    checkins = await db.checkins.find({"user_id": client_id}, {"_id": 0}).sort("created_at", -1).to_list(10)
    history = await db.rosters.find({"user_id": client_id}, {"_id": 0, "raw_response": 0}).sort("created_at", -1).to_list(20)
    ev = await db.events.find_one({"user_id": client_id, "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    if ev:
        ev["phase_info"] = _event_phase(ev.get("event_date", ""))
    return {"client": c, "roster": r, "workouts": workouts, "checkins": checkins, "roster_history": history, "event": ev or None}


@api.get("/coach/pending-approvals")
async def coach_pending(_: dict = Depends(require_role("coach"))):
    rows = await db.workouts.find({"approved": False}, {"_id": 0}).sort("date", 1).to_list(500)
    for r in rows:
        u = await db.users.find_one({"id": r["user_id"]}, {"_id": 0, "name": 1})
        r["client_name"] = u.get("name") if u else "Unknown"
    return rows


@api.get("/coach/calendar")
async def coach_calendar(days: int = 14, _: dict = Depends(require_role("coach"))):
    """Return a per-client roster/workout grid for the next N days from today."""
    from datetime import datetime, timedelta
    start = datetime.utcnow().date()
    dates: list[str] = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    users = await db.users.find({"role": "client"}, {"_id": 0, "password_hash": 0}).to_list(500)
    rows: list[dict] = []
    for u in users:
        r = await db.rosters.find_one({"user_id": u["id"], "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
        day_map: dict[str, dict] = {d["date"]: d for d in (r or {}).get("days", []) if d.get("date")}
        wkts = await db.workouts.find({"user_id": u["id"], "date": {"$in": dates}}, {"_id": 0}).to_list(500)
        wkt_map: dict[str, dict] = {}
        for w in wkts:
            wkt_map[w["date"]] = w
        cells = []
        for d in dates:
            rd = day_map.get(d, {})
            wk = wkt_map.get(d)
            cells.append({
                "date": d,
                "load": rd.get("load") or (wk.get("day_load") if wk else None),
                "duty_type": rd.get("duty_type"),
                "workout_id": (wk or {}).get("id"),
                "title": (wk or {}).get("title"),
                "completed": bool((wk or {}).get("completed")),
                "key_session": bool((wk or {}).get("key_session")),
                "approved": bool((wk or {}).get("approved", True)),
                "duration_min": (wk or {}).get("duration_min"),
                "location": (wk or {}).get("location"),
            })
        rows.append({
            "client_id": u["id"],
            "client_name": u.get("name") or u.get("email"),
            "email": u.get("email"),
            "days": cells,
            "has_roster": bool(r),
        })
    return {"start_date": dates[0], "end_date": dates[-1], "dates": dates, "clients": rows}


@api.get("/coach/analytics")
async def coach_analytics(days: int = 30, _: dict = Depends(require_role("coach"))):
    """Aggregate per-client and global compliance/RPE metrics for the last N days."""
    from datetime import datetime, timedelta
    cutoff_date = (datetime.utcnow().date() - timedelta(days=days)).isoformat()
    today = today_str()
    users = await db.users.find({"role": "client"}, {"_id": 0, "password_hash": 0}).to_list(500)
    per_client: list[dict] = []
    tot_scheduled = 0
    tot_completed = 0
    all_rpes: list[int] = []
    load_totals: dict[str, int] = {"green": 0, "amber": 0, "red": 0, "blue": 0, "purple": 0, "grey": 0}
    for u in users:
        wkts = await db.workouts.find(
            {"user_id": u["id"], "date": {"$gte": cutoff_date, "$lte": today}}, {"_id": 0}
        ).to_list(500)
        scheduled_past = [w for w in wkts if w.get("date", "") <= today]
        completed = [w for w in scheduled_past if w.get("completed")]
        rpes = [int(w.get("rpe")) for w in completed if isinstance(w.get("rpe"), (int, float))]
        avg_rpe = round(sum(rpes) / len(rpes), 1) if rpes else None
        compliance = round(100 * len(completed) / len(scheduled_past)) if scheduled_past else 0
        # count loads
        c_loads: dict[str, int] = {}
        for w in wkts:
            lo = w.get("day_load") or "grey"
            c_loads[lo] = c_loads.get(lo, 0) + 1
            if lo in load_totals:
                load_totals[lo] += 1
        # key sessions completed
        key_done = sum(1 for w in completed if w.get("key_session"))
        key_total = sum(1 for w in scheduled_past if w.get("key_session"))
        per_client.append({
            "client_id": u["id"],
            "client_name": u.get("name") or u.get("email"),
            "email": u.get("email"),
            "scheduled": len(scheduled_past),
            "completed": len(completed),
            "compliance": compliance,
            "avg_rpe": avg_rpe,
            "loads": c_loads,
            "key_sessions_completed": key_done,
            "key_sessions_total": key_total,
        })
        tot_scheduled += len(scheduled_past)
        tot_completed += len(completed)
        all_rpes.extend(rpes)
    global_compliance = round(100 * tot_completed / tot_scheduled) if tot_scheduled else 0
    global_avg_rpe = round(sum(all_rpes) / len(all_rpes), 1) if all_rpes else None
    per_client.sort(key=lambda x: -x["compliance"])
    return {
        "days": days,
        "start_date": cutoff_date,
        "end_date": today,
        "total_clients": len(users),
        "total_scheduled": tot_scheduled,
        "total_completed": tot_completed,
        "global_compliance": global_compliance,
        "global_avg_rpe": global_avg_rpe,
        "load_distribution": load_totals,
        "clients": per_client,
    }


# ------------------------------------------------------------------
# §26 — Embedded Exercise Video System (Phase A: in-app YouTube playback)
# ------------------------------------------------------------------
YOUTUBE_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"

# Channels well-known to allow embedding — prefer these when picking demo videos
EMBED_FRIENDLY_CHANNELS = [
    "athlean-x", "athleanx", "jeff nippard", "renaissance periodization",
    "built with science", "juggernaut training systems", "hybrid athletics",
    "calisthenicmovement", "buffdudes", "buff dudes", "team evolve",
    "james smith", "jeremy ethier", "mind pump",
]
# Channels known to have embedding disabled — deprioritise
EMBED_BLOCKED_CHANNELS = ["squat university"]

PREFERRED_CHANNELS = [
    "Athlean-X", "Jeff Nippard", "Built With Science",
    "Renaissance Periodization", "Jeremy Ethier",
]


def _pick_channel_hint(name: str) -> str:
    n = (name or "").lower()
    if re.search(r"(run|zone 2|walk|cardio|z2|incline|jog|sprint)", n):
        return "Athlean-X"
    if re.search(r"(mobility|stretch|90/90|world|foam)", n):
        return "Jeremy Ethier"
    if re.search(r"(press|bench|row|pull-up|push-up|curl|db |dumbbell|shoulder)", n):
        return "Jeff Nippard"
    if re.search(r"(squat|deadlift|hinge|lunge|split|hip thrust|glute)", n):
        return "Athlean-X"  # Squat U blocks embeds — use Athlean-X for legs
    return PREFERRED_CHANNELS[0]


def _normalize_ex_key(name: str) -> str:
    key = re.sub(r"\s+", " ", (name or "").strip().lower())
    key = re.sub(r"[^a-z0-9 /-]", "", key)
    return key


async def _youtube_search_first_video(query: str) -> Optional[dict]:
    """Scrape YouTube search results and pick the best embed-friendly video (no API key)."""
    from urllib.parse import quote_plus
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp=EgIQAQ%253D%253D"  # filter: videos only
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as hc:
            r = await hc.get(
                url,
                headers={
                    "User-Agent": YOUTUBE_UA,
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            if r.status_code != 200:
                logger.warning(f"YT search HTTP {r.status_code} for '{query}'")
                return None
            html = r.text
    except Exception as e:
        logger.warning(f"YT scrape error for '{query}': {e}")
        return None
    # Extract up to 10 candidate videos from the HTML
    candidates: list[dict] = []
    seen: set[str] = set()
    for m in re.finditer(r'"videoRenderer":\{"videoId":"([a-zA-Z0-9_-]{11})"(.{0,6000}?)(?="videoRenderer"|"reelShelfRenderer"|"shelfRenderer"|"playlistRenderer"|"radioRenderer"|$)', html, re.DOTALL):
        vid = m.group(1)
        if vid in seen:
            continue
        seen.add(vid)
        block = m.group(2)
        # title
        title = None
        tm = re.search(r'"title":\{"runs":\[\{"text":"([^"]+)"', block)
        if tm:
            title = tm.group(1)
        # channel name
        channel = None
        cm = re.search(r'"ownerText":\{"runs":\[\{"text":"([^"]+)"', block)
        if not cm:
            cm = re.search(r'"longBylineText":\{"runs":\[\{"text":"([^"]+)"', block)
        if cm:
            channel = cm.group(1)
        candidates.append({"video_id": vid, "title": title, "channel": channel})
        if len(candidates) >= 10:
            break
    if not candidates:
        # Last resort: naive first videoId in HTML
        m = re.search(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
        if not m:
            return None
        vid = m.group(1)
        candidates.append({"video_id": vid, "title": None, "channel": None})

    def channel_score(c: Optional[str]) -> int:
        cl = (c or "").lower()
        if any(b in cl for b in EMBED_BLOCKED_CHANNELS):
            return -10
        if any(f in cl for f in EMBED_FRIENDLY_CHANNELS):
            return 10
        return 0

    # Sort with stable order (search rank) but push friendly channels to top and blocked to bottom
    ranked = sorted(enumerate(candidates), key=lambda t: (-channel_score(t[1].get("channel")), t[0]))
    best = ranked[0][1]
    return {
        "video_id": best["video_id"],
        "title": best.get("title"),
        "channel": best.get("channel"),
        "thumbnail_url": f"https://img.youtube.com/vi/{best['video_id']}/mqdefault.jpg",
        "candidates": [c["video_id"] for _, c in ranked[:5]],
    }


async def _lookup_or_fetch_video(exercise_name: str) -> Optional[dict]:
    """Return a cached exercise_video doc; if none, scrape YouTube and cache."""
    key = _normalize_ex_key(exercise_name)
    if not key:
        return None
    existing = await db.exercise_videos.find_one({"key": key}, {"_id": 0})
    if existing:
        has_any = any(
            (existing.get(s) or {}).get("video_id") or (existing.get(s) or {}).get("video_url")
            for s in ("primary", "alternative", "custom_url", "custom_upload", "youtube_backup")
        )
        if has_any:
            return existing
    # Fetch fresh
    channel_hint = _pick_channel_hint(exercise_name)
    query = f"{channel_hint} {exercise_name} tutorial"
    result = await _youtube_search_first_video(query)
    if not result:
        # Try again without channel qualifier
        result = await _youtube_search_first_video(f"{exercise_name} exercise tutorial")
    if not result:
        return None
    doc = {
        "id": str(uuid.uuid4()),
        "key": key,
        "display_name": exercise_name,
        "primary": {
            "source": "youtube_search",
            "video_id": result["video_id"],
            "title": result.get("title"),
            "channel": result.get("channel") or channel_hint,
            "channel_hint": channel_hint,
            "thumbnail_url": result["thumbnail_url"],
            "approval_status": "auto",
            "added_by": None,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "search_query": query,
        },
        "alternatives": [],
        "last_reviewed_at": None,
        "reviewed_by": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await db.exercise_videos.update_one({"key": key}, {"$set": doc}, upsert=True)
    except Exception as e:
        logger.warning(f"cache write failed for '{key}': {e}")
    return doc


@api.get("/exercises/video")
async def get_exercise_video(name: str, variant: str = "default", user: dict = Depends(current_user)):
    """Return the current video record for an exercise. Fetches from YouTube on miss."""
    doc = await _lookup_or_fetch_video(name)
    if not doc:
        return {"exercise": name, "video": None, "message": "Demo coming soon. Follow the written coaching cues."}
    resolved = _resolve_display_video(doc, variant=variant)
    if not resolved:
        return {"exercise": name, "video": None, "message": "Demo coming soon. Follow the written coaching cues."}
    return {"exercise": name, "video": resolved, "key": doc.get("key"), "id": doc.get("id")}


class VideoBatchReq(BaseModel):
    exercises: list[str]
    variant: Optional[str] = "default"


@api.post("/exercises/videos-batch")
async def batch_exercise_videos(req: VideoBatchReq, user: dict = Depends(current_user)):
    """Return video records for a batch of exercise names in one call."""
    import asyncio
    unique_names = list({(n or "").strip(): n for n in req.exercises if n and n.strip()}.values())
    keys = [_normalize_ex_key(n) for n in unique_names]
    cached = {}
    if keys:
        async for d in db.exercise_videos.find({"key": {"$in": keys}}, {"_id": 0}):
            cached[d["key"]] = d
    out: dict[str, Any] = {}
    to_fetch: list[str] = []
    variant = req.variant or "default"
    for n in unique_names:
        k = _normalize_ex_key(n)
        d = cached.get(k)
        if d:
            resolved = _resolve_display_video(d, variant=variant)
            out[n] = {"key": k, "video": resolved, "id": d.get("id")} if resolved else None
        else:
            to_fetch.append(n)
    sem = asyncio.Semaphore(4)

    async def one(nm: str):
        async with sem:
            d = await _lookup_or_fetch_video(nm)
            if not d:
                return nm, None
            resolved = _resolve_display_video(d, variant=variant)
            return nm, ({"key": d.get("key"), "video": resolved, "id": d.get("id")} if resolved else None)

    if to_fetch:
        results = await asyncio.gather(*(one(n) for n in to_fetch[:8]))
        for nm, val in results:
            out[nm] = val
        for nm in to_fetch[8:]:
            out[nm] = None
    return {"results": out, "fetched": len(to_fetch)}


def _parse_youtube_url(url: Optional[str]) -> Optional[str]:
    """Extract 11-char video ID from various YouTube URL formats."""
    if not url:
        return None
    m = re.search(r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/|v/)|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
    return m.group(1) if m else None


def _resolve_display_video(record: dict, variant: str = "default") -> Optional[dict]:
    """Given a record, resolve which slot to show, honoring variants, preferred slot, and approvals."""
    if not record:
        return None
    v = variant if variant in ("home", "hotel", "gym") else None
    if v:
        vslot = (record.get("variants") or {}).get(v)
        if vslot and (vslot.get("video_id") or vslot.get("video_url")) and vslot.get("approval_status") != "rejected":
            return {**vslot, "slot": f"variant.{v}"}
    order: list[str] = []
    pref = record.get("preferred_slot")
    if pref and pref in ("primary", "alternative", "custom_url", "custom_upload", "youtube_backup", "ai_image"):
        order.append(pref)
    for s in ("custom_upload", "custom_url", "youtube_backup", "primary", "alternative", "ai_image"):
        if s not in order:
            order.append(s)
    for slot_name in order:
        slot = record.get(slot_name)
        if not slot:
            continue
        if slot.get("approval_status") == "rejected":
            continue
        if slot.get("video_id") or slot.get("video_url"):
            return {**slot, "slot": slot_name}
    return None


# ------------------------------------------------------------------
# §26 Phase B — Coach Video CRUD Management
# ------------------------------------------------------------------
VALID_SLOTS = {"primary", "alternative", "custom_url", "custom_upload", "youtube_backup", "ai_image"}
VALID_VARIANTS = {"home", "hotel", "gym"}


class VideoSlotBody(BaseModel):
    slot: str
    video_id: Optional[str] = None
    video_url: Optional[str] = None
    title: Optional[str] = None
    channel: Optional[str] = None
    notes: Optional[str] = None
    source: Optional[str] = None


class VideoApprovalBody(BaseModel):
    slot: str
    status: str


class VideoPreferredBody(BaseModel):
    slot: str


class VideoVariantBody(BaseModel):
    variant: str
    video_id: Optional[str] = None
    video_url: Optional[str] = None
    title: Optional[str] = None
    channel: Optional[str] = None
    delete: bool = False


class VideoUpsertBody(BaseModel):
    display_name: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _touch_review(key: str, coach_id: Optional[str]) -> None:
    await db.exercise_videos.update_one(
        {"key": key},
        {"$set": {"last_reviewed_at": _now_iso(), "reviewed_by": coach_id, "updated_at": _now_iso()}},
    )


@api.get("/coach/videos")
async def coach_videos_list(search: Optional[str] = None, coach: dict = Depends(require_role("coach"))):
    q: dict = {}
    if search:
        q["$or"] = [
            {"key": {"$regex": re.escape(search.lower())}},
            {"display_name": {"$regex": re.escape(search), "$options": "i"}},
        ]
    rows = await db.exercise_videos.find(q, {"_id": 0}).sort("display_name", 1).to_list(500)
    have_keys = {r["key"] for r in rows}
    lib = await db.exercises.find({}, {"_id": 0, "name": 1, "category": 1}).to_list(1000)
    for ex in lib:
        k = _normalize_ex_key(ex["name"])
        if k and k not in have_keys and (not search or search.lower() in k or search.lower() in ex["name"].lower()):
            rows.append({
                "id": None, "key": k, "display_name": ex["name"], "category": ex.get("category"),
                "primary": None, "alternative": None, "custom_url": None,
                "custom_upload": None, "youtube_backup": None, "ai_image": None,
                "variants": {}, "preferred_slot": None,
                "last_reviewed_at": None, "reviewed_by": None,
            })
            have_keys.add(k)

    def sort_key(r: dict):
        primary = r.get("primary") or {}
        needs = 0
        if not primary.get("video_id"):
            needs = 3
        elif primary.get("approval_status") == "rejected":
            needs = 2
        elif not r.get("last_reviewed_at"):
            needs = 1
        return (-needs, (r.get("display_name") or "").lower())

    rows.sort(key=sort_key)
    items = []
    for r in rows:
        primary = r.get("primary") or {}
        custom = r.get("custom_url") or {}
        custom_up = r.get("custom_upload") or {}
        variants = r.get("variants") or {}
        approval = primary.get("approval_status") if primary.get("video_id") else "missing"
        items.append({
            "id": r.get("id"), "key": r.get("key"), "display_name": r.get("display_name"),
            "category": r.get("category"),
            "primary_video_id": primary.get("video_id"),
            "primary_channel": primary.get("channel") or primary.get("channel_hint"),
            "primary_thumbnail": primary.get("thumbnail_url"),
            "has_custom_url": bool(custom.get("video_id") or custom.get("video_url")),
            "has_custom_upload": bool(custom_up.get("video_id") or custom_up.get("video_url")),
            "variants_configured": [v for v in ("home", "hotel", "gym") if variants.get(v, {}).get("video_id") or variants.get(v, {}).get("video_url")],
            "preferred_slot": r.get("preferred_slot") or "primary",
            "approval_state": approval,
            "last_reviewed_at": r.get("last_reviewed_at"),
        })
    return {"items": items, "total": len(items)}


@api.get("/coach/videos/detail")
async def coach_video_detail(key: str, coach: dict = Depends(require_role("coach"))):
    doc = await db.exercise_videos.find_one({"key": key}, {"_id": 0})
    if not doc:
        lib_row = None
        for ex in await db.exercises.find({}, {"_id": 0}).to_list(1000):
            if _normalize_ex_key(ex["name"]) == key:
                lib_row = ex
                break
        if not lib_row:
            raise HTTPException(404, "No such exercise")
        doc = {
            "id": str(uuid.uuid4()), "key": key, "display_name": lib_row["name"],
            "primary": None, "created_at": _now_iso(), "updated_at": _now_iso(),
        }
        await db.exercise_videos.update_one({"key": key}, {"$set": doc}, upsert=True)
    return doc


@api.post("/coach/videos/upsert")
async def coach_video_upsert(body: VideoUpsertBody, coach: dict = Depends(require_role("coach"))):
    key = _normalize_ex_key(body.display_name)
    if not key:
        raise HTTPException(400, "Invalid display_name")
    existing = await db.exercise_videos.find_one({"key": key}, {"_id": 0})
    if existing:
        return existing
    doc = {
        "id": str(uuid.uuid4()), "key": key, "display_name": body.display_name.strip(),
        "primary": None, "created_at": _now_iso(), "updated_at": _now_iso(),
    }
    await db.exercise_videos.update_one({"key": key}, {"$set": doc}, upsert=True)
    return doc


@api.post("/coach/videos/slot")
async def coach_video_set_slot(key: str, body: VideoSlotBody, coach: dict = Depends(require_role("coach"))):
    if body.slot not in VALID_SLOTS:
        raise HTTPException(400, f"Invalid slot. Allowed: {sorted(VALID_SLOTS)}")
    vid = body.video_id or _parse_youtube_url(body.video_url)
    if not vid and not body.video_url:
        raise HTTPException(400, "Provide either video_id or video_url")
    doc = await db.exercise_videos.find_one({"key": key}, {"_id": 0}) or {
        "id": str(uuid.uuid4()), "key": key, "display_name": key.title(),
        "created_at": _now_iso(),
    }
    slot_doc: dict[str, Any] = {
        "source": body.source or ("youtube_manual" if vid else "custom_url"),
        "approval_status": "approved",
        "added_by": coach.get("id"),
        "added_at": _now_iso(),
    }
    if vid:
        slot_doc["video_id"] = vid
        slot_doc["thumbnail_url"] = f"https://img.youtube.com/vi/{vid}/mqdefault.jpg"
    if body.video_url and not vid:
        slot_doc["video_url"] = body.video_url
    if body.title:
        slot_doc["title"] = body.title
    if body.channel:
        slot_doc["channel"] = body.channel
    if body.notes:
        slot_doc["notes"] = body.notes
    doc[body.slot] = slot_doc
    doc["updated_at"] = _now_iso()
    await db.exercise_videos.update_one({"key": key}, {"$set": doc}, upsert=True)
    await _touch_review(key, coach.get("id"))
    return await db.exercise_videos.find_one({"key": key}, {"_id": 0})


@api.post("/coach/videos/approve")
async def coach_video_approve(key: str, body: VideoApprovalBody, coach: dict = Depends(require_role("coach"))):
    if body.slot not in VALID_SLOTS:
        raise HTTPException(400, "Invalid slot")
    if body.status not in ("approved", "rejected", "auto", "pending"):
        raise HTTPException(400, "Invalid status")
    doc = await db.exercise_videos.find_one({"key": key})
    if not doc:
        raise HTTPException(404, "No such exercise video")
    slot = doc.get(body.slot)
    if not slot:
        raise HTTPException(404, f"Slot {body.slot} is empty")
    slot["approval_status"] = body.status
    slot["reviewed_by"] = coach.get("id")
    slot["reviewed_at"] = _now_iso()
    await db.exercise_videos.update_one({"key": key}, {"$set": {body.slot: slot, "updated_at": _now_iso()}})
    await _touch_review(key, coach.get("id"))
    return await db.exercise_videos.find_one({"key": key}, {"_id": 0})


@api.post("/coach/videos/preferred")
async def coach_video_set_preferred(key: str, body: VideoPreferredBody, coach: dict = Depends(require_role("coach"))):
    if body.slot not in VALID_SLOTS:
        raise HTTPException(400, "Invalid slot")
    doc = await db.exercise_videos.find_one({"key": key})
    if not doc:
        raise HTTPException(404, "No such exercise video")
    if not doc.get(body.slot):
        raise HTTPException(400, f"Slot {body.slot} has no video")
    await db.exercise_videos.update_one({"key": key}, {"$set": {"preferred_slot": body.slot, "updated_at": _now_iso()}})
    await _touch_review(key, coach.get("id"))
    return await db.exercise_videos.find_one({"key": key}, {"_id": 0})


@api.post("/coach/videos/variant")
async def coach_video_set_variant(key: str, body: VideoVariantBody, coach: dict = Depends(require_role("coach"))):
    if body.variant not in VALID_VARIANTS:
        raise HTTPException(400, f"Invalid variant. Allowed: {sorted(VALID_VARIANTS)}")
    doc = await db.exercise_videos.find_one({"key": key})
    if not doc:
        raise HTTPException(404, "No such exercise video")
    variants = doc.get("variants") or {}
    if body.delete:
        variants.pop(body.variant, None)
    else:
        vid = body.video_id or _parse_youtube_url(body.video_url)
        if not vid and not body.video_url:
            raise HTTPException(400, "Provide video_id or video_url")
        variants[body.variant] = {
            "source": "coach_variant",
            "approval_status": "approved",
            "video_id": vid,
            "video_url": body.video_url if not vid else None,
            "thumbnail_url": f"https://img.youtube.com/vi/{vid}/mqdefault.jpg" if vid else None,
            "title": body.title,
            "channel": body.channel,
            "added_by": coach.get("id"),
            "added_at": _now_iso(),
        }
    await db.exercise_videos.update_one({"key": key}, {"$set": {"variants": variants, "updated_at": _now_iso()}})
    await _touch_review(key, coach.get("id"))
    return await db.exercise_videos.find_one({"key": key}, {"_id": 0})


@api.delete("/coach/videos/slot")
async def coach_video_delete_slot(key: str, slot: str, coach: dict = Depends(require_role("coach"))):
    if slot not in VALID_SLOTS:
        raise HTTPException(400, "Invalid slot")
    doc = await db.exercise_videos.find_one({"key": key})
    if not doc:
        raise HTTPException(404, "No such exercise video")
    # Clean up custom_upload blob if that's the slot being deleted
    if slot == "custom_upload":
        blob_id = (doc.get("custom_upload") or {}).get("blob_id")
        if blob_id:
            try:
                await db.exercise_video_blobs.delete_one({"id": blob_id})
            except Exception:
                pass
    updates: dict = {slot: None, "updated_at": _now_iso()}
    if doc.get("preferred_slot") == slot:
        updates["preferred_slot"] = None
    await db.exercise_videos.update_one({"key": key}, {"$set": updates})
    await _touch_review(key, coach.get("id"))
    return await db.exercise_videos.find_one({"key": key}, {"_id": 0})


@api.post("/coach/videos/rescan")
async def coach_video_rescan(key: str, coach: dict = Depends(require_role("coach"))):
    doc = await db.exercise_videos.find_one({"key": key})
    if not doc:
        raise HTTPException(404, "No such exercise video")
    name = doc.get("display_name") or key
    channel_hint = _pick_channel_hint(name)
    query = f"{channel_hint} {name} tutorial"
    result = await _youtube_search_first_video(query)
    if not result:
        result = await _youtube_search_first_video(f"{name} exercise tutorial")
    if not result:
        raise HTTPException(502, "Could not find a video for this exercise")
    primary = {
        "source": "youtube_search",
        "video_id": result["video_id"],
        "title": result.get("title"),
        "channel": result.get("channel") or channel_hint,
        "channel_hint": channel_hint,
        "thumbnail_url": result["thumbnail_url"],
        "approval_status": "auto",
        "added_by": coach.get("id"),
        "added_at": _now_iso(),
        "search_query": query,
    }
    await db.exercise_videos.update_one({"key": key}, {"$set": {"primary": primary, "updated_at": _now_iso()}})
    await _touch_review(key, coach.get("id"))
    return await db.exercise_videos.find_one({"key": key}, {"_id": 0})


# ------------------------------------------------------------------
# §26 Phase C — Custom video uploads (base64 in MongoDB, <=10 MB)
# ------------------------------------------------------------------
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB raw
ALLOWED_UPLOAD_MIME = {"video/mp4", "video/quicktime", "video/webm", "video/x-m4v"}


class VideoUploadBody(BaseModel):
    filename: str
    mime_type: str
    data_base64: str
    title: Optional[str] = None
    notes: Optional[str] = None
    make_preferred: bool = False


@api.post("/coach/videos/upload")
async def coach_video_upload(
    key: str,
    body: VideoUploadBody,
    coach: dict = Depends(require_role("coach")),
):
    """Upload a custom video (base64) to the custom_upload slot.

    Body: {filename, mime_type, data_base64, title?, notes?, make_preferred?}
    """
    import base64
    if body.mime_type not in ALLOWED_UPLOAD_MIME:
        raise HTTPException(400, f"Unsupported mime type. Allowed: {sorted(ALLOWED_UPLOAD_MIME)}")
    # Strip data-URI prefix if present
    data = body.data_base64
    if data.startswith("data:"):
        _, _, data = data.partition(",")
    try:
        raw = base64.b64decode(data, validate=True)
    except Exception:
        raise HTTPException(400, "Invalid base64 payload")
    if len(raw) == 0:
        raise HTTPException(400, "Empty payload")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"Video too large ({len(raw)/1_048_576:.1f} MB). Max is 10 MB.")

    doc = await db.exercise_videos.find_one({"key": key}, {"_id": 0}) or {
        "id": str(uuid.uuid4()), "key": key, "display_name": key.title(),
        "created_at": _now_iso(),
    }

    # Clean up any prior blob for this exercise's custom_upload slot
    old = (doc.get("custom_upload") or {}).get("blob_id")
    if old:
        try:
            await db.exercise_video_blobs.delete_one({"id": old})
        except Exception:
            pass

    blob_id = str(uuid.uuid4())
    await db.exercise_video_blobs.insert_one({
        "id": blob_id,
        "exercise_key": key,
        "slot": "custom_upload",
        "filename": body.filename,
        "mime_type": body.mime_type,
        "size_bytes": len(raw),
        "data_base64": data,  # keep as base64 string to avoid BSON binary size limits vs streaming
        "uploaded_by": coach.get("id"),
        "uploaded_at": _now_iso(),
    })
    slot_doc = {
        "source": "custom_upload",
        "blob_id": blob_id,
        "filename": body.filename,
        "mime_type": body.mime_type,
        "size_bytes": len(raw),
        "video_url": f"/api/videos/blob/{blob_id}",
        "title": body.title or body.filename,
        "channel": "CrewFit Upload",
        "approval_status": "approved",
        "added_by": coach.get("id"),
        "added_at": _now_iso(),
        "notes": body.notes,
    }
    doc["custom_upload"] = slot_doc
    doc["updated_at"] = _now_iso()
    if body.make_preferred or not doc.get("preferred_slot"):
        doc["preferred_slot"] = "custom_upload"
    await db.exercise_videos.update_one({"key": key}, {"$set": doc}, upsert=True)
    await _touch_review(key, coach.get("id"))
    return await db.exercise_videos.find_one({"key": key}, {"_id": 0})


@api.get("/videos/blob/{blob_id}")
async def get_video_blob(blob_id: str):
    """Stream the custom-upload video bytes with the correct Content-Type.

    Public GET so <video> elements and native players can load it directly (blob_id
    is a UUID; not enumerable). Auth still required to know which exercise it maps
    to, so we intentionally do not require auth here."""
    import base64
    from fastapi.responses import Response
    doc = await db.exercise_video_blobs.find_one({"id": blob_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Blob not found")
    try:
        raw = base64.b64decode(doc.get("data_base64") or "", validate=True)
    except Exception:
        raise HTTPException(500, "Corrupted blob")
    return Response(
        content=raw,
        media_type=doc.get("mime_type", "video/mp4"),
        headers={
            "Content-Length": str(len(raw)),
            "Cache-Control": "private, max-age=86400",
            "Accept-Ranges": "bytes",  # Note: not truly ranged; browsers still accept full response
        },
    )


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

    if await db.exercises.count_documents({}) < len(DEFAULT_EXERCISES):
        for (name, cat, eq, mp, mg, home_ok, hotel_ok, bw, lvl, joint, fat, pre, post) in DEFAULT_EXERCISES:
            existing = await db.exercises.find_one({"name": name})
            doc = {
                "name": name, "category": cat, "equipment": eq,
                "movement_pattern": mp, "muscle_group": mg,
                "home_ok": home_ok, "hotel_ok": hotel_ok, "bodyweight_ok": bw,
                "level": lvl, "knee_friendly": joint, "back_friendly": joint, "shoulder_friendly": joint,
                "fatigue_cost": fat, "ok_before_flight": pre, "ok_after_flight": post,
                "demo_url": None, "notes": None, "common_mistakes": None,
                "regressions": None, "progressions": None,
            }
            if existing:
                await db.exercises.update_one({"id": existing["id"]}, {"$set": doc})
            else:
                await db.exercises.insert_one({"id": new_id(), "created_at": now_iso(), **doc})

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
