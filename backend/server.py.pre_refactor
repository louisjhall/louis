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

import asyncio
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
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field

from emergentintegrations.llm.chat import (
    FileContentWithMimeType,
    ImageContent,
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

# Louis Hall reference photo used to generate exercise demo images with Nano Banana.
LOUIS_REF_IMAGE_PATH = ROOT_DIR / "assets" / "louis_ref.png"
_LOUIS_REF_B64_CACHE: Optional[str] = None


def _louis_ref_b64() -> str:
    """Cache Louis reference photo base64 so we don't re-encode ~1.8MB on every request."""
    global _LOUIS_REF_B64_CACHE
    if _LOUIS_REF_B64_CACHE is None:
        if not LOUIS_REF_IMAGE_PATH.exists():
            raise FileNotFoundError(str(LOUIS_REF_IMAGE_PATH))
        with open(LOUIS_REF_IMAGE_PATH, "rb") as f:
            _LOUIS_REF_B64_CACHE = base64.b64encode(f.read()).decode("utf-8")
    return _LOUIS_REF_B64_CACHE


def _make_thumb_data_url(img: Optional[str], size: int = 96, quality: int = 60) -> Optional[str]:
    """Generate a small JPEG thumbnail data URL from a full data URL or http URL.

    Returns None if input is missing/invalid. Used by list endpoints so the client
    doesn't need to download 500KB+ hero images just to show row previews.
    """
    if not img or not isinstance(img, str):
        return None
    try:
        from io import BytesIO
        from PIL import Image as PILImage
        if img.startswith("data:"):
            _, b64 = img.split(",", 1)
            raw = base64.b64decode(b64)
        else:
            # remote URL — skip (avoid outbound calls during list render)
            return None
        with PILImage.open(BytesIO(raw)) as im:
            im = im.convert("RGB")
            im.thumbnail((size, size))
            buf = BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True)
            b = base64.b64encode(buf.getvalue()).decode("utf-8")
            return f"data:image/jpeg;base64,{b}"
    except Exception:
        return None

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

# --- Coach message drafts ------------------------------------------------
class MessageDraftGenerateBody(BaseModel):
    client_id: str
    source_message_id: Optional[str] = None
    tone_hint: Optional[str] = None           # "shorter" | "warmer" | "clearer" | "custom"
    custom_instruction: Optional[str] = None

class MessageDraftEditBody(BaseModel):
    coach_edited_text: str

class MessageDraftToneBody(BaseModel):
    tone: str                                 # "shorter" | "warmer" | "clearer" | "custom"
    custom_instruction: Optional[str] = None

class CoachClientControlsBody(BaseModel):
    programme_flexibility: Optional[str] = None       # "strict" | "flexible"
    progression_speed: Optional[str] = None           # "cautious" | "standard" | "aggressive"
    injury_caution: Optional[str] = None              # "low" | "medium" | "high"
    video_frequency: Optional[str] = None             # "weekly" | "biweekly" | "monthly"
    auto_approval_risk_threshold: Optional[str] = None  # "none" | "low" | "low_medium"

# --- Habits ------------------------------------------------------------------
class HabitLogBody(BaseModel):
    status: str                          # "done" | "skipped" | "not_possible"
    reason: Optional[str] = None         # roster/fatigue/time/etc
    note: Optional[str] = None
    date_local: Optional[str] = None     # override the local YYYY-MM-DD if the client provides it
    time_zone: Optional[str] = None

class HabitCoachCreateBody(BaseModel):
    title: str
    reason: Optional[str] = None
    linked_goal: Optional[str] = None
    habit_type: str = "daily"            # daily / weekly / training-day-only / rest-day-only / flight-day / layover-day / home-day / post-flight / pre-flight / recovery-day / after-workout / event-specific / custom
    day_type_rules: Optional[list[str]] = None
    frequency: Optional[str] = None      # e.g. "daily" | "3x/week"
    target: Optional[str] = None
    unit: Optional[str] = None
    difficulty_level: Optional[str] = "starter"   # starter / standard / stretch

class HabitCoachEditBody(BaseModel):
    title: Optional[str] = None
    reason: Optional[str] = None
    target: Optional[str] = None
    unit: Optional[str] = None
    frequency: Optional[str] = None
    habit_type: Optional[str] = None
    day_type_rules: Optional[list[str]] = None
    difficulty_level: Optional[str] = None
    status: Optional[str] = None         # active | paused | archived

class HabitReviewApproveBody(BaseModel):
    coach_note: Optional[str] = None
    modified_recommendations: Optional[list[dict[str, Any]]] = None

class HabitReviewRejectBody(BaseModel):
    coach_note: Optional[str] = None

class HabitRemindersToggleBody(BaseModel):
    enabled: bool

# --- Notifications V1 --------------------------------------------------------
class NotificationPermissionBody(BaseModel):
    status: str                      # "granted" | "denied" | "not_requested"
    platform: Optional[str] = None
    device_info: Optional[dict] = None

class NotificationSettingsBody(BaseModel):
    check_ins: Optional[bool] = None
    habits: Optional[bool] = None
    workouts: Optional[bool] = None
    coach_messages: Optional[bool] = None
    weekly_videos: Optional[bool] = None
    roster: Optional[bool] = None
    programme_updates: Optional[bool] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    preferred_reminder_time: Optional[str] = None
    travel_use_current_tz: Optional[bool] = None

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


# ==================================================================
# CrewFit Intelligence Assessment™ — Adaptive Onboarding + Coaching DNA
# ==================================================================
ASSESSMENT_INTERVIEWER_SYSTEM = """You are Atlas — the CrewFit Intelligence™ engine built by Louis Hall to apply his coaching philosophy at scale.

You are NOT the coach. Louis is. You are conducting an adaptive intake assessment on Louis' behalf so his coaching framework can be applied to this airline crew member consistently.

TONE — use Atlas voice:
- Every question should feel warm, professional, coaching-first (never like a form).
- Phrase questions with phrases like "I'd like to learn...", "Help me understand...", "So Louis can programme around you accurately, tell me..."
- NEVER say "I'll coach you" or "I know best" — you're gathering information for Louis' coaching system.

CORE RULES:
1. Ask ONE question at a time. Never batch.
2. Every next question MUST depend on previous answers. Skip irrelevant sections entirely.
3. NEVER ask nutrition macros/calories/protein numbers — the client doesn't know.
4. NEVER ask FTP/threshold if goal isn't endurance-based.
5. NEVER ask bodybuilding questions if goal is fat loss / health / general fitness.
6. Aim for 15-25 questions total (fewer if answers are clear, more if goals require depth).
7. Adapt language & tone to their motivation style — supportive if they're returning from injury, sharper if they're driven / competitive.
8. Track progress from 0 to 100. When you have enough to build a rich Coaching DNA, set `should_end: true`.

SECTIONS YOU CAN COVER (only when relevant):
Who You Are · Your Aviation · Your Why · Your Goals · Your Events · Training History · Fitness Level · Lifestyle · Recovery · Nutrition Habits · Equipment · Time Available · Injuries · Motivation · Psychology · Coach Preferences · Wearables · Future Plans

QUESTION TYPES you can return:
- "single_select" with options: [{"id":"...", "label":"...", "emoji":"..."}] — one choice
- "multi_select" with options — multiple choices
- "short_text" — one-line answer
- "long_text" — paragraph answer
- "number" with meta:{min, max, step, unit} — numeric
- "date" — ISO date
- "range" with meta:{min, max, step, unit, left_label, right_label}
- "event_builder" — client adds one or more upcoming events {name, event_type, date, priority}
- "equipment_picker" — multi-select equipment at a location; meta:{location:"home"|"hotel"|"commercial_gym"|"parents"}

REQUIRED FIRST QUESTIONS (ask early):
- Aviation role (Pilot / Cabin Crew / Ground Ops / Corporate Aviation / Other) — single_select
- Primary goal category — multi_select from: [Lose body fat, Build muscle, General fitness, Improve health, Improve confidence, Ironman, 70.3, Sprint Triathlon, Olympic Triathlon, Marathon, Half Marathon, HYROX, 5K, 10K, Improve mobility, Reduce pain, Return from injury, Reduce jet lag, Improve sleep, Pass airline medical, Maintain fitness, Other]

BRANCHING (examples — you should adapt intelligently):
- If Pilot chosen → ask about sectors, long/short haul, layover length, time zones crossed.
- If Cabin Crew → ask sectors, hotel gyms encountered, night flights per month, standby days.
- If Ironman/Marathon/70.3/HYROX chosen → jump to event date, current base, weekly hours, key sessions, wearables.
- If Lose Body Fat → target weight, timeline, current eating pattern (habits NOT macros), airport/crew meal frequency.
- If Return from injury → what/when/severity/movements to avoid, ok cleared by physio.

RESPONSE FORMAT (STRICT JSON — nothing else):
{
  "next_question": {
    "id": "unique_snake_case_id",
    "section": "Your Aviation",
    "text": "The actual question (concise, coach-tone)",
    "help_text": "Optional 1-sentence why we're asking",
    "type": "single_select"|"multi_select"|"short_text"|"long_text"|"number"|"date"|"range"|"event_builder"|"equipment_picker",
    "options": [{"id":"long_haul","label":"Long haul","emoji":"🌍"}],  // when applicable
    "meta": {"min":0,"max":100,"step":1,"unit":"min"},                 // when applicable
    "allow_skip": true|false
  },
  "should_end": false,
  "progress": 45,
  "section_context": "Building your flying profile..."
}

When you have enough context (usually after 15-22 quality answers), respond with:
{ "should_end": true, "progress": 100, "section_context": "Building your Coaching DNA..." }

Do NOT return next_question when should_end is true. Return ONLY valid JSON."""


DNA_SYSTEM = """You are Atlas — the CrewFit Intelligence™ engine built by Louis Hall.

Given a completed assessment transcript, synthesise the client's permanent **Coaching DNA** — the coaching mental model Louis will use to guide every AI decision going forward. Everything you produce operates within Louis' coaching philosophy.

RULES:
- Be specific and personal. Reference their actual answers.
- Never generic. Every field should feel like it was written FOR THIS PERSON.
- If information is missing, say "Unknown — will learn over time".
- Assign a realistic `ai_confidence_score` (30-95). New clients rarely hit 90+.
- `recommended_weekly_training` should be a concrete outline (e.g. "4 days: Mon strength, Tue Z2 run, Thu mobility, Sat long run").
- The `summary` field should be written in Atlas voice ("I've analysed...", "I've identified..."). Never claim to coach — reference Louis' methodology.

RESPOND WITH STRICT JSON only:
{
  "primary_goal": "one-line",
  "secondary_goals": ["...", "..."],
  "why_it_matters": "2-3 sentence explanation in their voice",
  "next_event": { "name":"...", "date":"YYYY-MM-DD", "priority":"A|B|C" } | null,
  "event_timeline": [ { "name":"...", "date":"YYYY-MM-DD", "priority":"A|B|C" } ],
  "aviation_profile": {
    "role": "Pilot|Cabin Crew|Ground Ops|Corporate|Other",
    "haul_mix": "long|short|both",
    "avg_sectors_month": <int>|null,
    "typical_layover_hours": <int>|null,
    "hotel_gym_frequency": "always|often|sometimes|rare|never"
  },
  "flying_style": "1-sentence read of their flying pattern",
  "recovery_risk": "low|medium|high",
  "training_experience": "beginner|intermediate|advanced",
  "motivation_style": "one of: progress|competition|routine|coach|aesthetics|health|events|data|accountability",
  "coaching_style": "one of: strict|supportive|data_driven|high_accountability|flexible|hands_off|motivational|educational",
  "lifestyle_summary": "2-sentence overview of family/pets/stress/sleep/coffee/alcohol",
  "equipment_locations": [ { "location":"home|hotel|commercial_gym|parents|holiday", "equipment":["..."] } ],
  "training_availability": { "home":"<min>","layovers":"<min>","days_off":"<min>","standby":"<min>","leave":"<min>","preferred_time":"morning|afternoon|evening|flexible" },
  "injury_summary": "one line, or 'No current injuries'",
  "nutrition_summary": "one line — eating pattern, NOT macros",
  "biggest_strength": "one line",
  "biggest_weakness": "one line",
  "biggest_opportunity": "one line",
  "ai_confidence_score": 30-95,
  "recommended_weekly_training": "concrete 4-6 line outline",
  "recommended_recovery_strategy": "1-2 sentence prescription",
  "recommended_nutrition_strategy": "1-2 sentence prescription",
  "recommended_coaching_style": "1 sentence prescription",
  "summary": "3-4 sentence CrewFit Intelligence summary — this is the AI's read of the client and how it will coach them."
}

Return ONLY JSON."""


class AssessmentAnswerBody(BaseModel):
    assessment_id: str
    question_id: str
    answer: Any  # string | list | number | dict (for event_builder/equipment_picker)


class AssessmentStartBody(BaseModel):
    seed_from_profile: bool = True


async def _assessment_next_question(assessment: dict) -> dict:
    """Feed the current transcript to Claude and get the next question / end signal."""
    transcript = []
    for a in (assessment.get("answers") or []):
        transcript.append({
            "q_id": a.get("question_id"),
            "section": a.get("section"),
            "question": a.get("question_text"),
            "answer": a.get("answer"),
        })
    prompt = (
        f"CLIENT NAME: {assessment.get('client_name') or 'the client'}\n"
        f"ASSESSMENT SO FAR ({len(transcript)} answers):\n"
        f"{json.dumps(transcript)[:8500]}\n\n"
        "Return the next question JSON now. If enough context, set should_end true."
    )
    try:
        raw = await call_claude(ASSESSMENT_INTERVIEWER_SYSTEM, prompt, max_out=1800)
        parsed = parse_json_from_text(raw)
        if not isinstance(parsed, dict):
            raise ValueError("bad shape")
        return parsed
    except Exception:
        logger.exception("assessment_next AI failed")
        return _assessment_fallback_next(assessment)


def _assessment_fallback_next(assessment: dict) -> dict:
    """Deterministic fallback flow if AI fails — always keeps the interview moving."""
    answered = {a.get("question_id") for a in (assessment.get("answers") or [])}
    fb: list[dict] = [
        {"id": "role", "section": "Your Aviation", "text": "What is your role in aviation?",
         "type": "single_select", "options": [
             {"id": "pilot", "label": "Pilot", "emoji": "✈️"},
             {"id": "cabin_crew", "label": "Cabin Crew", "emoji": "🧳"},
             {"id": "ground_ops", "label": "Ground Ops", "emoji": "🛄"},
             {"id": "corporate", "label": "Corporate Aviation", "emoji": "🛩"},
             {"id": "other", "label": "Other", "emoji": "🌐"},
         ], "allow_skip": False},
        {"id": "primary_goal", "section": "Your Goals",
         "text": "What are you trying to achieve? Pick everything that matters.",
         "type": "multi_select", "options": [
             {"id": "lose_fat", "label": "Lose body fat", "emoji": "🔥"},
             {"id": "build_muscle", "label": "Build muscle", "emoji": "💪"},
             {"id": "general_fitness", "label": "General fitness", "emoji": "🏃"},
             {"id": "marathon", "label": "Marathon", "emoji": "🏁"},
             {"id": "half_marathon", "label": "Half Marathon", "emoji": "🏃‍♂️"},
             {"id": "ironman", "label": "Ironman", "emoji": "🏊"},
             {"id": "seventy_three", "label": "70.3", "emoji": "🚴"},
             {"id": "hyrox", "label": "HYROX", "emoji": "🥊"},
             {"id": "sprint_tri", "label": "Sprint Triathlon", "emoji": "🏊‍♀️"},
             {"id": "olympic_tri", "label": "Olympic Triathlon", "emoji": "🏊"},
             {"id": "five_k", "label": "5K", "emoji": "5️⃣"},
             {"id": "ten_k", "label": "10K", "emoji": "🔟"},
             {"id": "mobility", "label": "Improve mobility", "emoji": "🧘"},
             {"id": "reduce_pain", "label": "Reduce pain", "emoji": "🩹"},
             {"id": "return_injury", "label": "Return from injury", "emoji": "🩺"},
             {"id": "reduce_jetlag", "label": "Reduce jet lag", "emoji": "🌍"},
             {"id": "improve_sleep", "label": "Improve sleep", "emoji": "😴"},
             {"id": "airline_medical", "label": "Pass airline medical", "emoji": "⚕️"},
             {"id": "maintain", "label": "Maintain fitness", "emoji": "🔁"},
         ], "allow_skip": False},
        {"id": "why", "section": "Your Why", "text": "Why is this important to you right now?",
         "type": "long_text", "help_text": "Your answer becomes part of every future coaching decision.",
         "allow_skip": True},
        {"id": "events", "section": "Your Events",
         "text": "Any important events coming up? (races, holidays, medicals, weddings...)",
         "type": "event_builder", "help_text": "CrewFit plans backwards from your dates.",
         "allow_skip": True},
        {"id": "experience", "section": "Training History", "text": "How would you describe your training experience?",
         "type": "single_select", "options": [
             {"id": "beginner", "label": "Beginner", "emoji": "🌱"},
             {"id": "intermediate", "label": "Intermediate", "emoji": "🌿"},
             {"id": "advanced", "label": "Advanced", "emoji": "🌳"},
         ]},
        {"id": "time_home", "section": "Time Available", "text": "How much time can you realistically train at home?",
         "type": "range", "meta": {"min": 15, "max": 120, "step": 5, "unit": "min", "left_label": "15m", "right_label": "2h"}},
        {"id": "time_layover", "section": "Time Available", "text": "How much time on layovers?",
         "type": "range", "meta": {"min": 0, "max": 90, "step": 5, "unit": "min", "left_label": "None", "right_label": "1h30"}},
        {"id": "training_days", "section": "Time Available", "text": "How many days a week can you train?",
         "type": "single_select", "options": [
             {"id": "2", "label": "2 days", "emoji": "2️⃣"},
             {"id": "3", "label": "3 days", "emoji": "3️⃣"},
             {"id": "4", "label": "4 days", "emoji": "4️⃣"},
             {"id": "5", "label": "5 days", "emoji": "5️⃣"},
             {"id": "6", "label": "6 days", "emoji": "6️⃣"},
         ]},
        {"id": "equipment_home", "section": "Equipment", "text": "What equipment do you have at home?",
         "type": "equipment_picker", "meta": {"location": "home"}, "allow_skip": True},
        {"id": "hotel_gyms", "section": "Your Aviation", "text": "Do you usually find gyms in your hotels?",
         "type": "single_select", "options": [
             {"id": "always", "label": "Always", "emoji": "✅"},
             {"id": "often", "label": "Often", "emoji": "👍"},
             {"id": "sometimes", "label": "Sometimes", "emoji": "🤔"},
             {"id": "rare", "label": "Rarely", "emoji": "🚫"},
             {"id": "never", "label": "Never", "emoji": "❌"},
         ]},
        {"id": "injuries", "section": "Injuries", "text": "Any current injuries or things you must avoid?",
         "type": "long_text", "allow_skip": True},
        {"id": "sleep_quality", "section": "Recovery", "text": "On average, how would you rate your sleep?",
         "type": "range", "meta": {"min": 1, "max": 10, "step": 1, "unit": "/10", "left_label": "Poor", "right_label": "Great"}},
        {"id": "stress", "section": "Lifestyle", "text": "How would you rate your daily stress?",
         "type": "range", "meta": {"min": 1, "max": 10, "step": 1, "unit": "/10", "left_label": "Low", "right_label": "High"}},
        {"id": "family", "section": "Lifestyle", "text": "Family commitments?",
         "type": "multi_select", "options": [
             {"id": "kids_young", "label": "Young children", "emoji": "👶"},
             {"id": "kids_school", "label": "School-age kids", "emoji": "🎒"},
             {"id": "partner", "label": "Partner", "emoji": "💑"},
             {"id": "pets", "label": "Pets", "emoji": "🐕"},
             {"id": "elders", "label": "Caring for elders", "emoji": "🧓"},
             {"id": "none", "label": "None", "emoji": "🚶"},
         ], "allow_skip": True},
        {"id": "nutrition_habits", "section": "Nutrition Habits", "text": "How do you usually eat on trips?",
         "type": "multi_select", "options": [
             {"id": "airport_food", "label": "Airport food", "emoji": "🍔"},
             {"id": "crew_meals", "label": "Crew meals", "emoji": "🍱"},
             {"id": "hotel_restaurants", "label": "Hotel restaurants", "emoji": "🍽️"},
             {"id": "meal_prep", "label": "Meal prep from home", "emoji": "🥗"},
             {"id": "supermarket", "label": "Supermarket / snacks", "emoji": "🥪"},
             {"id": "delivery", "label": "Food delivery apps", "emoji": "📦"},
         ], "allow_skip": True},
        {"id": "diet_style", "section": "Nutrition Habits", "text": "Any dietary preferences?",
         "type": "multi_select", "options": [
             {"id": "none", "label": "No restrictions", "emoji": "🍽️"},
             {"id": "vegetarian", "label": "Vegetarian", "emoji": "🥕"},
             {"id": "vegan", "label": "Vegan", "emoji": "🌱"},
             {"id": "halal", "label": "Halal", "emoji": "🌙"},
             {"id": "kosher", "label": "Kosher", "emoji": "✡️"},
             {"id": "gluten_free", "label": "Gluten free", "emoji": "🌾"},
             {"id": "dairy_free", "label": "Dairy free", "emoji": "🥛"},
         ], "allow_skip": True},
        {"id": "motivation", "section": "Motivation", "text": "What keeps you motivated?",
         "type": "multi_select", "options": [
             {"id": "progress", "label": "Progress", "emoji": "📈"},
             {"id": "competition", "label": "Competition", "emoji": "🏆"},
             {"id": "routine", "label": "Routine", "emoji": "🔁"},
             {"id": "coach", "label": "Coach accountability", "emoji": "🧑‍🏫"},
             {"id": "aesthetics", "label": "Looking better", "emoji": "🪞"},
             {"id": "health", "label": "Feeling healthier", "emoji": "❤️"},
             {"id": "events", "label": "Events", "emoji": "🎯"},
             {"id": "data", "label": "Data", "emoji": "📊"},
         ]},
        {"id": "blocker", "section": "Psychology", "text": "What usually stops you training?",
         "type": "multi_select", "options": [
             {"id": "jetlag", "label": "Jet lag", "emoji": "🌍"},
             {"id": "family", "label": "Family", "emoji": "👨‍👩‍👧"},
             {"id": "pain", "label": "Pain", "emoji": "🤕"},
             {"id": "time", "label": "Time", "emoji": "⏰"},
             {"id": "motivation", "label": "Motivation", "emoji": "😔"},
             {"id": "sleep", "label": "Sleep", "emoji": "😴"},
             {"id": "travel", "label": "Travel", "emoji": "🚗"},
             {"id": "stress", "label": "Stress", "emoji": "😣"},
             {"id": "nothing", "label": "Nothing usually", "emoji": "💪"},
         ]},
        {"id": "coaching_style_pref", "section": "Coach Preferences",
         "text": "What kind of coach do you respond to?",
         "type": "single_select", "options": [
             {"id": "strict", "label": "Strict", "emoji": "📏"},
             {"id": "supportive", "label": "Supportive", "emoji": "🤝"},
             {"id": "data_driven", "label": "Data driven", "emoji": "📊"},
             {"id": "flexible", "label": "Flexible", "emoji": "🌊"},
             {"id": "high_accountability", "label": "High accountability", "emoji": "🎯"},
             {"id": "hands_off", "label": "Hands off", "emoji": "🕊️"},
             {"id": "motivational", "label": "Motivational", "emoji": "🔥"},
             {"id": "educational", "label": "Educational", "emoji": "📚"},
         ]},
    ]
    for q in fb:
        if q["id"] not in answered:
            return {"next_question": q, "should_end": False,
                    "progress": min(95, int(100 * len(answered) / max(1, len(fb)))),
                    "section_context": q["section"]}
    return {"should_end": True, "progress": 100, "section_context": "Building your Coaching DNA..."}


async def _generate_coaching_dna(user_id: str, assessment: dict) -> dict:
    """Synthesise the Coaching DNA from a completed assessment transcript."""
    transcript = []
    for a in (assessment.get("answers") or []):
        transcript.append({
            "q_id": a.get("question_id"), "section": a.get("section"),
            "question": a.get("question_text"), "answer": a.get("answer"),
        })
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    profile = (user or {}).get("profile") or {}
    prompt = (
        f"CLIENT: {user.get('name') or 'the client'} ({user.get('email')})\n"
        f"EXISTING PROFILE FRAGMENT (may be sparse): {json.dumps(profile)[:1500]}\n\n"
        f"ASSESSMENT TRANSCRIPT ({len(transcript)} answers):\n"
        f"{json.dumps(transcript)[:9000]}\n\n"
        "Return the Coaching DNA JSON now."
    )
    try:
        raw = await call_claude(DNA_SYSTEM, prompt, max_out=3000)
        dna = parse_json_from_text(raw)
        if not isinstance(dna, dict):
            raise ValueError("bad DNA")
    except Exception:
        logger.exception("DNA gen AI failed")
        # Best-effort fallback synthesised from the answers directly
        dna = _dna_fallback(transcript, profile)
    return dna


def _dna_fallback(transcript: list[dict], profile: dict) -> dict:
    """Deterministic DNA if AI fails — reads structured answers directly."""
    ans_map: dict[str, Any] = {t["q_id"]: t["answer"] for t in transcript if t.get("q_id")}
    role = ans_map.get("role") or (profile.get("position") or "Cabin Crew").lower().replace(" ", "_")
    goals = ans_map.get("primary_goal") or []
    if isinstance(goals, str):
        goals = [goals]
    primary = goals[0] if goals else (profile.get("goal") or "General fitness")
    return {
        "primary_goal": str(primary).replace("_", " ").title(),
        "secondary_goals": [str(g).replace("_", " ").title() for g in goals[1:5]],
        "why_it_matters": ans_map.get("why") or "Unknown — will learn over time",
        "next_event": None,
        "event_timeline": ans_map.get("events") if isinstance(ans_map.get("events"), list) else [],
        "aviation_profile": {
            "role": str(role).replace("_", " ").title(),
            "haul_mix": "both",
            "hotel_gym_frequency": ans_map.get("hotel_gyms") or "sometimes",
        },
        "flying_style": "Adaptive schedule — will refine over time.",
        "recovery_risk": "medium",
        "training_experience": ans_map.get("experience") or profile.get("experience_level") or "intermediate",
        "motivation_style": (ans_map.get("motivation") or ["progress"])[0]
            if isinstance(ans_map.get("motivation"), list) else (ans_map.get("motivation") or "progress"),
        "coaching_style": ans_map.get("coaching_style_pref") or "supportive",
        "lifestyle_summary": "Unknown — will learn over time",
        "equipment_locations": [{"location": "home", "equipment": profile.get("equipment") or []}],
        "training_availability": {
            "home": ans_map.get("time_home") or profile.get("max_home_minutes") or 45,
            "layovers": ans_map.get("time_layover") or 30,
            "preferred_time": "flexible",
        },
        "injury_summary": ans_map.get("injuries") or "No current injuries reported.",
        "nutrition_summary": "Airline lifestyle eating — will refine.",
        "biggest_strength": "Consistency potential",
        "biggest_weakness": "Unpredictable schedule",
        "biggest_opportunity": "Layover training",
        "ai_confidence_score": 45,
        "recommended_weekly_training": "4 days: 2× strength, 1× conditioning, 1× mobility",
        "recommended_recovery_strategy": "Prioritise sleep windows; light mobility on jet-lag days.",
        "recommended_nutrition_strategy": "Consistent protein at each meal; hydrate on flights.",
        "recommended_coaching_style": "Supportive, empathetic, with clear structure.",
        "summary": "CrewFit is beginning to learn your patterns. Confidence will rise with every roster and workout.",
    }


@api.post("/assessment/start")
async def assessment_start(body: AssessmentStartBody = AssessmentStartBody(), user: dict = Depends(current_user)):
    """Start a new assessment for the current user. Returns first question."""
    # If an in-progress assessment exists, resume it
    existing = await db.assessments.find_one({"user_id": user["id"], "status": "in_progress"}, {"_id": 0}, sort=[("created_at", -1)])
    if existing:
        nxt = await _assessment_next_question(existing)
        return {"assessment_id": existing["id"], "resumed": True, **nxt}
    doc = {
        "id": new_id(), "user_id": user["id"],
        "client_name": user.get("name"),
        "status": "in_progress",
        "seed_from_profile": body.seed_from_profile,
        "answers": [],
        "current_question": None,
        "progress": 0,
        "section": "Who You Are",
        "created_at": now_iso(),
        "completed_at": None,
    }
    await db.assessments.insert_one(doc)
    nxt = await _assessment_next_question(doc)
    q = nxt.get("next_question")
    if q:
        await db.assessments.update_one({"id": doc["id"]}, {"$set": {
            "current_question": q,
            "progress": nxt.get("progress", 0),
            "section": q.get("section"),
        }})
    return {"assessment_id": doc["id"], "resumed": False, **nxt}


@api.get("/assessment/current")
async def assessment_current(user: dict = Depends(current_user)):
    a = await db.assessments.find_one({"user_id": user["id"], "status": "in_progress"}, {"_id": 0}, sort=[("created_at", -1)])
    if not a:
        return {"assessment": None}
    return {"assessment": a}


@api.post("/assessment/answer")
async def assessment_answer(body: AssessmentAnswerBody, user: dict = Depends(current_user)):
    a = await db.assessments.find_one({"id": body.assessment_id, "user_id": user["id"]}, {"_id": 0})
    if not a:
        raise HTTPException(404, "Assessment not found")
    if a.get("status") != "in_progress":
        raise HTTPException(400, "Assessment already completed")

    cq = a.get("current_question") or {}
    q_id = body.question_id or cq.get("id")
    a["answers"].append({
        "question_id": q_id,
        "section": cq.get("section"),
        "question_text": cq.get("text"),
        "question_type": cq.get("type"),
        "answer": body.answer,
        "answered_at": now_iso(),
    })
    await db.assessments.update_one({"id": a["id"]}, {"$set": {"answers": a["answers"]}})

    nxt = await _assessment_next_question(a)
    if nxt.get("should_end") or not nxt.get("next_question"):
        await db.assessments.update_one({"id": a["id"]}, {"$set": {
            "current_question": None,
            "progress": 100,
            "section": nxt.get("section_context") or "Building your Coaching DNA...",
            "status": "ready_to_finalize",
        }})
        return {"should_end": True, "progress": 100, "section_context": nxt.get("section_context")}
    q = nxt["next_question"]
    await db.assessments.update_one({"id": a["id"]}, {"$set": {
        "current_question": q,
        "progress": nxt.get("progress", a.get("progress", 0)),
        "section": q.get("section"),
    }})
    return nxt


@api.post("/assessment/finalize")
async def assessment_finalize(body: dict = None, user: dict = Depends(current_user)):
    body = body or {}
    assessment_id = body.get("assessment_id")
    if not assessment_id:
        raise HTTPException(400, "assessment_id required")
    a = await db.assessments.find_one({"id": assessment_id, "user_id": user["id"]}, {"_id": 0})
    if not a:
        raise HTTPException(404, "Assessment not found")
    if a.get("status") == "completed":
        # Return existing DNA
        dna = await db.coaching_dna.find_one({"user_id": user["id"]}, {"_id": 0}, sort=[("updated_at", -1)])
        return {"dna": dna, "already_completed": True}

    dna = await _generate_coaching_dna(user["id"], a)

    # Version and persist
    existing = await db.coaching_dna.find_one({"user_id": user["id"]}, {"_id": 0}, sort=[("version", -1)])
    version = (existing.get("version", 0) + 1) if existing else 1
    dna_doc = {
        "id": new_id(),
        "user_id": user["id"],
        "assessment_id": a["id"],
        "version": version,
        **dna,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.coaching_dna.insert_one(dna_doc)
    # Re-fetch to strip the mongo _id field before returning
    dna_doc_clean = await db.coaching_dna.find_one({"id": dna_doc["id"]}, {"_id": 0})

    # Link Event Mode — if the assessment surfaced events, materialise them in db.events
    events_created = 0
    try:
        for ev in (dna.get("event_timeline") or []):
            if not isinstance(ev, dict) or not ev.get("date"):
                continue
            # Detect event_type from name/keywords
            name = str(ev.get("name") or "").strip()
            etype = _guess_event_type(name)
            # De-dupe: skip if we already have an event on the same date with similar name
            dup = await db.events.find_one({"user_id": user["id"], "event_date": ev["date"]})
            if dup:
                continue
            await db.events.insert_one({
                "id": new_id(),
                "user_id": user["id"],
                "event_type": etype,
                "event_name": name or etype,
                "event_date": ev["date"],
                "priority": ev.get("priority") or "B",
                "is_active": True,
                "source": "assessment_v1",
                "created_at": now_iso(),
            })
            events_created += 1
    except Exception:
        logger.exception("event linking failed")

    # Mark assessment complete
    await db.assessments.update_one({"id": a["id"]}, {"$set": {
        "status": "completed", "completed_at": now_iso(),
        "dna_id": dna_doc["id"], "dna_version": version,
    }})
    # Onboarded flag flip so router accepts client
    await db.users.update_one({"id": user["id"]}, {"$set": {"onboarded": True}})

    # Seed the starter habits (async — don't block the finalize response)
    try:
        asyncio.create_task(_seed_habits_for_user_by_id(user["id"]))
    except Exception:
        logger.exception("habit seed trigger failed")

    return {"dna": dna_doc_clean, "events_created": events_created, "already_completed": False}


def _guess_event_type(name: str) -> str:
    n = (name or "").lower()
    if "iron" in n and ("70" in n or "70.3" in n):
        return "half_ironman"
    if "iron" in n:
        return "ironman"
    if "hyrox" in n:
        return "hyrox"
    if "half" in n and "marathon" in n:
        return "half_marathon"
    if "marathon" in n:
        return "marathon"
    if "10k" in n:
        return "10k"
    if "5k" in n:
        return "5k"
    if "wedding" in n:
        return "wedding"
    if "holiday" in n or "beach" in n or "vacation" in n:
        return "holiday"
    if "medical" in n or "assessment" in n:
        return "medical"
    if "photo" in n:
        return "photoshoot"
    return "other"


@api.get("/coaching-dna")
async def coaching_dna_get(user: dict = Depends(current_user)):
    dna = await db.coaching_dna.find_one({"user_id": user["id"]}, {"_id": 0}, sort=[("version", -1)])
    return {"dna": dna}


class CoachingDNAPatchBody(BaseModel):
    updates: dict[str, Any]
    reason: Optional[str] = None


@api.patch("/coaching-dna")
async def coaching_dna_patch(body: CoachingDNAPatchBody, user: dict = Depends(current_user)):
    dna = await db.coaching_dna.find_one({"user_id": user["id"]}, {"_id": 0}, sort=[("version", -1)])
    if not dna:
        raise HTTPException(404, "No DNA yet — complete the assessment first")
    allowed = {
        "primary_goal", "secondary_goals", "why_it_matters", "next_event", "event_timeline",
        "aviation_profile", "flying_style", "recovery_risk", "training_experience",
        "motivation_style", "coaching_style", "lifestyle_summary", "equipment_locations",
        "training_availability", "injury_summary", "nutrition_summary",
        "biggest_strength", "biggest_weakness", "biggest_opportunity",
        "recommended_weekly_training", "recommended_recovery_strategy",
        "recommended_nutrition_strategy", "recommended_coaching_style", "summary",
    }
    updates = {k: v for k, v in body.updates.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "No valid fields to update")
    updates["updated_at"] = now_iso()
    await db.coaching_dna.update_one({"id": dna["id"]}, {"$set": updates})
    # Log life-change
    try:
        await db.dna_history.insert_one({
            "id": new_id(), "user_id": user["id"], "dna_id": dna["id"],
            "kind": "client_edit", "reason": body.reason or "manual edit",
            "changes": list(updates.keys()), "created_at": now_iso(),
        })
    except Exception:
        pass
    dna2 = await db.coaching_dna.find_one({"id": dna["id"]}, {"_id": 0})
    # Living Profile: goal or major identity change is a re-assessment trigger
    try:
        important = {"primary_goal", "aviation_profile", "injury_summary", "training_availability"}
        if important & set(updates.keys()):
            await _emit_reassessment_prompt(
                user["id"], "life_change",
                f"You updated: {', '.join(sorted(important & set(updates.keys())))}. Refresh your CrewFit DNA?",
                {"fields": sorted(important & set(updates.keys()))},
            )
    except Exception:
        pass
    return {"dna": dna2}


@api.get("/assessment/history")
async def assessment_history(user: dict = Depends(current_user)):
    rows = await db.assessments.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(20)
    return {"assessments": rows}


async def _get_dna_context(user_id: str) -> dict:
    """Return a compact DNA payload for injection into other AI prompts.
    Returns {} when the client has not yet completed their assessment."""
    dna = await db.coaching_dna.find_one({"user_id": user_id}, {"_id": 0}, sort=[("version", -1)])
    if not dna:
        return {}
    return {
        "primary_goal": dna.get("primary_goal"),
        "secondary_goals": dna.get("secondary_goals"),
        "why_it_matters": dna.get("why_it_matters"),
        "next_event": dna.get("next_event"),
        "aviation_profile": dna.get("aviation_profile"),
        "flying_style": dna.get("flying_style"),
        "recovery_risk": dna.get("recovery_risk"),
        "training_experience": dna.get("training_experience"),
        "motivation_style": dna.get("motivation_style"),
        "coaching_style": dna.get("coaching_style"),
        "lifestyle_summary": dna.get("lifestyle_summary"),
        "training_availability": dna.get("training_availability"),
        "injury_summary": dna.get("injury_summary"),
        "nutrition_summary": dna.get("nutrition_summary"),
        "biggest_strength": dna.get("biggest_strength"),
        "biggest_weakness": dna.get("biggest_weakness"),
        "biggest_opportunity": dna.get("biggest_opportunity"),
        "recommended_weekly_training": dna.get("recommended_weekly_training"),
        "recommended_recovery_strategy": dna.get("recommended_recovery_strategy"),
        "recommended_nutrition_strategy": dna.get("recommended_nutrition_strategy"),
        "recommended_coaching_style": dna.get("recommended_coaching_style"),
        "ai_confidence_score": dna.get("ai_confidence_score"),
        "version": dna.get("version"),
    }


# ==================================================================
# Living Profile — Re-assessment triggers
# ==================================================================
async def _emit_reassessment_prompt(user_id: str, kind: str, reason: str, meta: Optional[dict] = None) -> None:
    """Create a re-assessment prompt (dismissible) that appears on the client home."""
    # Cool-down: don't re-emit the same kind if there's a pending prompt in the last 3 days
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    cutoff = (_dt.now(_tz.utc) - _td(days=3)).isoformat()
    existing = await db.reassessment_prompts.find_one({
        "user_id": user_id, "kind": kind, "dismissed": False, "created_at": {"$gte": cutoff},
    })
    if existing:
        return
    await db.reassessment_prompts.insert_one({
        "id": new_id(),
        "user_id": user_id,
        "kind": kind,
        "reason": reason,
        "meta": meta or {},
        "dismissed": False,
        "created_at": now_iso(),
    })


@api.get("/reassessment/prompts")
async def reassessment_prompts(user: dict = Depends(current_user)):
    """Return active (undismissed) re-assessment prompts for the user."""
    rows = await db.reassessment_prompts.find(
        {"user_id": user["id"], "dismissed": False},
        {"_id": 0},
    ).sort("created_at", -1).to_list(20)
    return {"prompts": rows}


class ReassessmentDismissBody(BaseModel):
    prompt_id: Optional[str] = None
    kind: Optional[str] = None  # dismiss all of this kind


@api.post("/reassessment/dismiss")
async def reassessment_dismiss(body: ReassessmentDismissBody, user: dict = Depends(current_user)):
    q: dict[str, Any] = {"user_id": user["id"], "dismissed": False}
    if body.prompt_id:
        q["id"] = body.prompt_id
    elif body.kind:
        q["kind"] = body.kind
    else:
        raise HTTPException(400, "prompt_id or kind required")
    res = await db.reassessment_prompts.update_many(q, {"$set": {"dismissed": True, "dismissed_at": now_iso()}})
    return {"dismissed": res.modified_count}


# ==================================================================
# Coaching Headquarters — Profile / Achievements / Personal Records / Notes
# ==================================================================
class UserProfilePatch(BaseModel):
    name: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    dob: Optional[str] = None
    equipment: Optional[list[str]] = None
    home_equipment: Optional[list[str]] = None
    max_home_minutes: Optional[int] = None
    experience_level: Optional[str] = None
    goal: Optional[str] = None
    training_days_per_week: Optional[int] = None
    preferred_time: Optional[str] = None
    timezone: Optional[str] = None


@api.patch("/user/profile")
async def user_profile_patch(body: UserProfilePatch, user: dict = Depends(current_user)):
    """Patch simple profile fields on the user document (legacy profile bag)."""
    updates: dict[str, Any] = {}
    root_updates: dict[str, Any] = {}
    dump = body.model_dump(exclude_none=True)
    if "name" in dump:
        root_updates["name"] = dump.pop("name")
    for k, v in dump.items():
        updates[f"profile.{k}"] = v
    if updates or root_updates:
        await db.users.update_one({"id": user["id"]}, {"$set": {**root_updates, **updates, "profile.updated_at": now_iso()}})
    u = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})
    return {"user": u}


# ---------------- Personal Records ----------------
class PersonalRecordBody(BaseModel):
    name: str  # e.g., "Back Squat 1RM"
    category: Optional[str] = None  # "strength", "run", "swim", "bike", "other"
    value: float  # numeric value
    unit: str  # "kg", "lb", "min", "sec", "km", "mi"
    date: Optional[str] = None  # ISO date, defaults to today
    notes: Optional[str] = None


@api.get("/personal-records")
async def pr_list(user: dict = Depends(current_user)):
    rows = await db.personal_records.find({"user_id": user["id"]}, {"_id": 0}).sort("date", -1).to_list(200)
    return {"records": rows}


@api.post("/personal-records")
async def pr_create(body: PersonalRecordBody, user: dict = Depends(current_user)):
    from datetime import datetime as _dt
    doc = {
        "id": new_id(),
        "user_id": user["id"],
        "name": body.name.strip(),
        "category": body.category or "other",
        "value": float(body.value),
        "unit": body.unit.strip(),
        "date": body.date or _dt.utcnow().date().isoformat(),
        "notes": body.notes,
        "created_at": now_iso(),
    }
    await db.personal_records.insert_one(doc)
    doc.pop("_id", None)
    return {"record": {k: v for k, v in doc.items() if k != "_id"}}


@api.patch("/personal-records/{pr_id}")
async def pr_update(pr_id: str, body: PersonalRecordBody, user: dict = Depends(current_user)):
    r = await db.personal_records.find_one({"id": pr_id, "user_id": user["id"]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Not found")
    updates = body.model_dump(exclude_none=True)
    updates["updated_at"] = now_iso()
    await db.personal_records.update_one({"id": pr_id, "user_id": user["id"]}, {"$set": updates})
    r2 = await db.personal_records.find_one({"id": pr_id}, {"_id": 0})
    return {"record": r2}


@api.delete("/personal-records/{pr_id}")
async def pr_delete(pr_id: str, user: dict = Depends(current_user)):
    res = await db.personal_records.delete_one({"id": pr_id, "user_id": user["id"]})
    return {"deleted": res.deleted_count > 0}


# ---------------- Achievements (computed aggregate) ----------------
@api.get("/achievements")
async def achievements(user: dict = Depends(current_user)):
    """Aggregate lightweight achievements from user's activity."""
    uid = user["id"]
    completed = await db.workouts.count_documents({"user_id": uid, "completed": True})
    total_workouts = await db.workouts.count_documents({"user_id": uid})
    prs = await db.personal_records.count_documents({"user_id": uid})
    events = await db.events.count_documents({"user_id": uid})
    assessments_done = await db.assessments.count_documents({"user_id": uid, "status": "completed"})
    move_history = await db.move_history.count_documents({"user_id": uid})
    # Streak = consecutive completed days (approx)
    wkts = await db.workouts.find({"user_id": uid, "completed": True}, {"_id": 0, "date": 1}).sort("date", -1).to_list(60)
    streak = 0
    seen_dates = sorted({w["date"] for w in wkts if w.get("date")}, reverse=True)
    from datetime import date as _date
    today = _date.today()
    prev: _date | None = None
    for i, d in enumerate(seen_dates):
        try:
            ds = _date.fromisoformat(d)
        except Exception:
            continue
        if prev is None:
            if (today - ds).days > 1:
                break
            streak = 1
            prev = ds
            continue
        if (prev - ds).days == 1:
            streak += 1
            prev = ds
        else:
            break
    # Badges
    badges: list[dict] = []
    def _add(id_: str, title: str, sub: str, emoji: str, unlocked: bool):
        badges.append({"id": id_, "title": title, "sub": sub, "emoji": emoji, "unlocked": unlocked})
    _add("first_workout", "First Workout", "Complete your first CrewFit session", "🎯", completed >= 1)
    _add("ten_workouts", "10 Workouts", "Complete 10 sessions total", "🔟", completed >= 10)
    _add("fifty_workouts", "50 Workouts", "Complete 50 sessions total", "🏅", completed >= 50)
    _add("century", "Century Club", "Complete 100 sessions total", "💯", completed >= 100)
    _add("streak_3", "3-Day Streak", "Train 3 days in a row", "🔥", streak >= 3)
    _add("streak_7", "Week Warrior", "Train 7 days in a row", "⚡", streak >= 7)
    _add("streak_14", "Two-Week Titan", "Train 14 days in a row", "🌟", streak >= 14)
    _add("first_pr", "First PR", "Log your first personal record", "📈", prs >= 1)
    _add("event_planner", "Event Planner", "Have an active event on the calendar", "📅", events >= 1)
    _add("intelligence", "CrewFit Intelligence", "Complete the assessment", "🧠", assessments_done >= 1)
    _add("adaptive", "Adaptive Athlete", "Use Today's Reality 5 times", "🌊", move_history >= 5)
    return {
        "stats": {
            "workouts_completed": completed,
            "workouts_total": total_workouts,
            "personal_records": prs,
            "events_planned": events,
            "assessments_completed": assessments_done,
            "current_streak": streak,
            "reality_adaptations": move_history,
        },
        "badges": badges,
    }


# ---------------- Notes (Coach & AI aggregated) ----------------
# ---- Atlas Workout Player — Sets logging + Alternatives ----
class WorkoutSetBody(BaseModel):
    workout_id: str
    exercise_index: int
    exercise_name: str
    set_number: int
    target_reps: Optional[str] = None
    actual_reps: Optional[int] = None
    target_weight: Optional[float] = None
    actual_weight: Optional[float] = None
    rpe: Optional[float] = None
    notes: Optional[str] = None
    # Cardio interval logging (Phase 3)
    logging_type: Optional[str] = None  # "weighted"|"bodyweight"|"cardio"|"timer"|"mobility"
    duration_sec: Optional[int] = None       # for timed sets (planks, cardio blocks)
    distance_m: Optional[float] = None       # cardio distance in metres
    pace_sec_per_km: Optional[float] = None  # calc or entered
    heart_rate_avg: Optional[int] = None     # avg BPM
    heart_rate_max: Optional[int] = None     # peak BPM
    calories: Optional[int] = None           # burnt
    warmup: bool = False                     # true if this was a warm-up item, not a scored set


@api.post("/workouts/{workout_id}/sets")
async def log_set(workout_id: str, body: WorkoutSetBody, user: dict = Depends(current_user)):
    """Log a completed set. Stored in workout_sets for future 'previous performance' lookups."""
    doc = {
        "id": new_id(),
        "user_id": user["id"],
        "workout_id": workout_id,
        "exercise_index": body.exercise_index,
        "exercise_name": body.exercise_name.strip(),
        "set_number": body.set_number,
        "target_reps": body.target_reps,
        "actual_reps": body.actual_reps,
        "target_weight": body.target_weight,
        "actual_weight": body.actual_weight,
        "rpe": body.rpe,
        "notes": body.notes,
        # Cardio interval fields
        "logging_type": body.logging_type,
        "duration_sec": body.duration_sec,
        "distance_m": body.distance_m,
        "pace_sec_per_km": body.pace_sec_per_km,
        "heart_rate_avg": body.heart_rate_avg,
        "heart_rate_max": body.heart_rate_max,
        "calories": body.calories,
        "warmup": body.warmup,
        "created_at": now_iso(),
    }
    # Auto-derive pace if missing but distance + duration provided
    if not doc.get("pace_sec_per_km") and doc.get("duration_sec") and doc.get("distance_m"):
        try:
            km = doc["distance_m"] / 1000.0
            if km > 0:
                doc["pace_sec_per_km"] = round(doc["duration_sec"] / km, 1)
        except Exception:
            pass
    await db.workout_sets.insert_one(doc)
    doc.pop("_id", None)
    return {"set": doc}


@api.get("/workouts/{workout_id}/sets")
async def list_sets(workout_id: str, user: dict = Depends(current_user)):
    rows = await db.workout_sets.find(
        {"user_id": user["id"], "workout_id": workout_id},
        {"_id": 0},
    ).sort("created_at", 1).to_list(500)
    return {"sets": rows}


@api.get("/exercises/previous")
async def exercise_previous(name: str, user: dict = Depends(current_user)):
    """Return the last session's sets for this exercise + best set ever + a suggested load."""
    # Case-insensitive exact-ish match on exercise_name
    q = {"user_id": user["id"], "exercise_name": {"$regex": f"^{name}$", "$options": "i"}}
    rows = await db.workout_sets.find(q, {"_id": 0}).sort("created_at", -1).to_list(50)
    if not rows:
        return {"last_session": [], "personal_best": None, "suggested_load": None}
    # Last session = all sets from the most recent workout_id
    last_wid = rows[0].get("workout_id")
    last_session = [r for r in rows if r.get("workout_id") == last_wid]
    last_session.sort(key=lambda r: r.get("set_number") or 0)
    # PB by weight
    weighted = [r for r in rows if r.get("actual_weight")]
    pb = None
    if weighted:
        pb = max(weighted, key=lambda r: (r.get("actual_weight") or 0, r.get("actual_reps") or 0))
    # Suggested: if all last-session sets hit target reps with RPE <= 8, add 2.5kg (or 5%); else keep
    suggested = None
    progression_hint = None
    if last_session:
        top_set = max(last_session, key=lambda r: r.get("actual_weight") or 0)
        wt = top_set.get("actual_weight")
        if wt:
            rpe = top_set.get("rpe") or 0
            hit_reps = all((r.get("actual_reps") or 0) >= int(str(r.get("target_reps") or 0).split("-")[0] or 0)
                           for r in last_session if r.get("target_reps"))
            if hit_reps and rpe and rpe <= 8:
                suggested = round(wt + max(2.5, wt * 0.025), 1)
                progression_hint = {
                    "action": "increase",
                    "delta_kg": round(suggested - wt, 1),
                    "reason": f"Hit target reps last time at RPE {rpe} — Atlas is adding +{round(suggested - wt, 1)}kg.",
                }
            elif rpe and rpe >= 9:
                suggested = wt
                progression_hint = {"action": "hold", "delta_kg": 0.0,
                                    "reason": f"RPE {rpe} last time — Atlas is holding weight to consolidate."}
            else:
                suggested = wt
                progression_hint = {"action": "hold", "delta_kg": 0.0,
                                    "reason": "Atlas held the load — log RPE next time so it can progress you."}
    return {"last_session": last_session, "personal_best": pb, "suggested_load": suggested,
            "progression_hint": progression_hint}


# Deterministic alternative catalog — Atlas uses this as ground truth
ALT_CATALOG: dict[str, list[dict]] = {
    "squat": [
        {"name": "Goblet Squat", "equipment": ["dumbbell", "kettlebell"], "why": "Front-loaded pattern keeps torso upright and quads active."},
        {"name": "Dumbbell Split Squat", "equipment": ["dumbbell"], "why": "Unilateral, less spinal load, hotel-friendly."},
        {"name": "Bodyweight Tempo Squat", "equipment": [], "why": "3-second lowering keeps the stimulus without kit."},
        {"name": "Dumbbell Front Squat", "equipment": ["dumbbell"], "why": "Same pattern, front-rack alternative."},
    ],
    "deadlift": [
        {"name": "Dumbbell Romanian Deadlift", "equipment": ["dumbbell"], "why": "Hinge pattern preserved with lighter kit."},
        {"name": "Single-leg RDL", "equipment": [], "why": "Balance + hamstring emphasis, no gym needed."},
        {"name": "Kettlebell Swing", "equipment": ["kettlebell"], "why": "Explosive hip hinge — great in hotel gyms."},
    ],
    "bench": [
        {"name": "Dumbbell Bench Press", "equipment": ["dumbbell", "bench"], "why": "Unilateral chest work with better shoulder path."},
        {"name": "Push-Up", "equipment": [], "why": "Bodyweight pattern, zero equipment."},
        {"name": "Floor Press", "equipment": ["dumbbell"], "why": "Hotel-friendly, no bench needed."},
    ],
    "row": [
        {"name": "Dumbbell Row", "equipment": ["dumbbell"], "why": "Same pull pattern, unilateral."},
        {"name": "Band Row", "equipment": ["band"], "why": "Travel-friendly resistance."},
        {"name": "TRX Row", "equipment": ["trx"], "why": "Bodyweight horizontal pull."},
        {"name": "Inverted Row", "equipment": [], "why": "Bodyweight equivalent using a bar or table edge."},
    ],
    "press": [
        {"name": "Dumbbell Shoulder Press", "equipment": ["dumbbell"], "why": "Same vertical push, better joint path."},
        {"name": "Pike Push-Up", "equipment": [], "why": "Bodyweight vertical push for hotel rooms."},
        {"name": "Band Overhead Press", "equipment": ["band"], "why": "Travel-friendly vertical push."},
    ],
    "pull_up": [
        {"name": "Band-Assisted Pull-Up", "equipment": ["band"], "why": "Reduces bodyweight load to hit target reps."},
        {"name": "TRX Row", "equipment": ["trx"], "why": "Horizontal pull alternative when no bar."},
        {"name": "Dumbbell Row", "equipment": ["dumbbell"], "why": "Same lat pattern using DBs."},
    ],
    "lunge": [
        {"name": "Reverse Lunge", "equipment": [], "why": "Same unilateral pattern, easier on the knees."},
        {"name": "Walking Lunge", "equipment": [], "why": "Space-permitting alternative."},
        {"name": "Step-Up", "equipment": [], "why": "Uses a bench or bed edge for hotels."},
    ],
    "plank": [
        {"name": "Dead Bug", "equipment": [], "why": "Anti-extension core with less shoulder load."},
        {"name": "Side Plank", "equipment": [], "why": "Lateral core emphasis."},
    ],
}


def _match_alt_key(name: str) -> Optional[str]:
    n = (name or "").lower()
    for key in ALT_CATALOG:
        if key in n:
            return key
    if "chin" in n or "pullup" in n:
        return "pull_up"
    if "overhead" in n or "shoulder" in n:
        return "press"
    return None


@api.get("/exercises/alternatives")
async def exercise_alternatives(
    name: str,
    location: Optional[str] = None,
    equipment: Optional[str] = None,  # comma-separated
    user: dict = Depends(current_user),
):
    """Return Atlas-recommended alternatives for an exercise given the user's context.

    Filter priority: equipment match > location fit > general fallback.
    """
    key = _match_alt_key(name)
    have_equipment = set((equipment or "").lower().split(",")) if equipment else set()
    have_equipment.discard("")

    # Pull user's home equipment as a soft signal
    if not have_equipment and user.get("profile"):
        eq = user["profile"].get("home_equipment") or user["profile"].get("equipment") or []
        have_equipment = {str(e).lower() for e in eq}

    if key and key in ALT_CATALOG:
        alts = ALT_CATALOG[key]
        # Score: how many of the required equipment items are available? 0-equip = universal.
        def _score(a: dict) -> int:
            req = set(a.get("equipment") or [])
            if not req:
                return 10  # bodyweight is always best if location=hotel
            hits = sum(1 for r in req if any(r in h for h in have_equipment))
            return hits * 5 + (2 if location == "Hotel" and not req else 0)

        alts_scored = sorted(alts, key=_score, reverse=True)
        return {
            "source": "catalog",
            "reason": "Atlas alternatives keep the same training objective using the equipment you have available.",
            "alternatives": alts_scored,
        }

    # Fallback: no key match
    return {
        "source": "generic",
        "reason": "No exact match found. Try a similar movement pattern with bodyweight or dumbbell.",
        "alternatives": [
            {"name": "Bodyweight Alternative", "equipment": [], "why": "Same movement pattern, no equipment."},
            {"name": "Dumbbell Alternative", "equipment": ["dumbbell"], "why": "Common substitute."},
        ],
    }


# ---------------- Notes (Coach & AI aggregated) ----------------
@api.get("/notes/coach")
async def notes_coach(user: dict = Depends(current_user)):
    """Aggregate coach-authored notes for a client: coach messages + coach_notes on workouts + coach reviewed reality events."""
    uid = user["id"]
    # Workouts with coach_notes populated
    wkts = await db.workouts.find(
        {"user_id": uid, "coach_notes": {"$exists": True, "$nin": [None, ""]}},
        {"_id": 0, "id": 1, "date": 1, "title": 1, "coach_notes": 1, "updated_at": 1},
    ).sort("date", -1).to_list(50)
    # Coach reviewed reality events
    revs = await db.reality_events.find(
        {"user_id": uid, "status": {"$in": ["coach_approved", "coach_rejected"]}, "coach_note": {"$nin": [None, ""]}},
        {"_id": 0, "id": 1, "date": 1, "reality_label": 1, "coach_note": 1, "status": 1, "coach_reviewed_at": 1},
    ).sort("coach_reviewed_at", -1).to_list(50)
    # Messages from coach to this client (if messages collection exists)
    msgs = await db.messages.find(
        {"to_user_id": uid, "from_role": "coach"},
        {"_id": 0, "id": 1, "from_name": 1, "body": 1, "created_at": 1},
    ).sort("created_at", -1).to_list(30) if "messages" in await db.list_collection_names() else []
    return {"workout_notes": wkts, "reality_reviews": revs, "messages": msgs}


@api.get("/notes/ai")
async def notes_ai(user: dict = Depends(current_user)):
    """Aggregate AI-authored notes: DNA history + Reality context summaries + move history rationales."""
    uid = user["id"]
    dna_hist = await db.dna_history.find({"user_id": uid}, {"_id": 0}).sort("created_at", -1).to_list(30)
    reality = await db.reality_events.find(
        {"user_id": uid, "context_summary": {"$exists": True, "$nin": [None, ""]}},
        {"_id": 0, "id": 1, "date": 1, "reality_label": 1, "context_summary": 1, "recovery_score": 1, "applied_option": 1, "created_at": 1},
    ).sort("created_at", -1).to_list(50)
    moves = await db.move_history.find(
        {"user_id": uid},
        {"_id": 0, "id": 1, "date": 1, "reality_label": 1, "option_title": 1, "option_why": 1, "created_at": 1},
    ).sort("created_at", -1).to_list(30)
    return {"dna_history": dna_hist, "reality_context": reality, "move_rationales": moves}


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
            # Living Profile trigger — new roster invites a quick review
            try:
                await _emit_reassessment_prompt(
                    user["id"], "roster_uploaded",
                    "New roster detected — take 90s to update your availability so CrewFit adapts perfectly.",
                    {"roster_id": roster.get("id"), "days": len(roster.get("days") or [])},
                )
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


# ------------------------------------------------------------------
# Rules Engine: turn a client Day Override into an adjusted workout
# ------------------------------------------------------------------
REST_TAGS = {"sick", "injured"}
OFF_TAGS = {"annual_leave", "holiday"}
LIGHT_TAGS = {"poor_sleep", "need_rest", "high_stress", "family_commitment", "childcare"}


def _build_rest_workout(date: str, reason: str) -> dict:
    return {
        "day_load": "green",
        "title": "Rest & Recovery",
        "location": "Home",
        "duration_min": 0,
        "focus": "rest",
        "warmup": [],
        "exercises": [],
        "alternatives": {},
        "rationale": reason,
        "key_session": False,
        "override_generated": True,
        "override_reason": reason,
    }


def _build_off_workout(date: str, reason: str) -> dict:
    return {
        "day_load": "grey",
        "title": "Off Day",
        "location": "Off",
        "duration_min": 0,
        "focus": "off",
        "warmup": [],
        "exercises": [],
        "alternatives": {},
        "rationale": reason,
        "key_session": False,
        "override_generated": True,
        "override_reason": reason,
    }


def _build_mobility_workout(date: str, reason: str, minutes: int = 15) -> dict:
    return {
        "day_load": "green",
        "title": "Light Mobility & Stretch",
        "location": "Home",
        "duration_min": minutes,
        "focus": "mobility",
        "warmup": [
            {"name": "Neck rolls", "duration_sec": 30},
            {"name": "Shoulder circles", "duration_sec": 30},
        ],
        "exercises": [
            {"name": "Cat-cow stretch", "sets": 1, "reps": "10", "notes": "Slow, controlled breathing"},
            {"name": "World's greatest stretch", "sets": 1, "reps": "6/side", "notes": "Open through the thoracic"},
            {"name": "90/90 hip switches", "sets": 1, "reps": "10/side"},
            {"name": "Down-dog to cobra flow", "sets": 1, "reps": "8"},
            {"name": "Child's pose", "sets": 1, "reps": "60s hold"},
        ],
        "alternatives": {},
        "rationale": reason,
        "key_session": False,
        "override_generated": True,
        "override_reason": reason,
    }


def _reduce_intensity(w: dict, reason: str) -> dict:
    """Trim sets/duration on an existing workout to reflect lower capacity."""
    out = {**w}
    ex_in = list(w.get("exercises") or [])
    ex_out = []
    for e in ex_in:
        e2 = {**e}
        try:
            sets = int(e2.get("sets") or 0)
            if sets > 1:
                e2["sets"] = max(1, sets - 1)
        except Exception:
            pass
        ex_out.append(e2)
    out["exercises"] = ex_out
    try:
        dur = int(w.get("duration_min") or 0)
        if dur:
            out["duration_min"] = max(15, int(dur * 0.65))
    except Exception:
        pass
    if w.get("day_load") == "red":
        out["day_load"] = "amber"
    elif w.get("day_load") == "amber":
        out["day_load"] = "green"
    out["override_generated"] = True
    out["override_reason"] = reason
    out["rationale"] = (w.get("rationale") or "") + f"  |  Adjusted: {reason}"
    return out


def _classify_override(ov: dict) -> tuple[str, str]:
    """Return (action, reason) for a stored override.

    action: 'rest' | 'off' | 'mobility' | 'reduce' | 'location_only' | 'noop'
    """
    tags = set(ov.get("tags") or [])
    pref = ov.get("training_preference")
    day_type = ov.get("day_type")
    avail = ov.get("availability_min")

    # Explicit rest/off requests
    if pref == "rest" or day_type in ("rest", "sick", "injury") or (REST_TAGS & tags):
        who = "sick" if "sick" in tags or day_type == "sick" else ("injured" if "injured" in tags or day_type == "injury" else "rest")
        return "rest", f"Client marked day as {who.upper()} — full rest prescribed."
    if day_type in ("annual_leave", "holiday", "family") or (OFF_TAGS & tags):
        label = "ANNUAL LEAVE" if "annual_leave" in tags or day_type == "annual_leave" else ("HOLIDAY" if "holiday" in tags or day_type == "holiday" else "OFF")
        return "off", f"Client marked day as {label} — no session planned."
    if pref == "mobility":
        return "mobility", "Client requested mobility only."
    if LIGHT_TAGS & tags:
        top = next(iter(LIGHT_TAGS & tags))
        return "mobility", f"Client flagged {top.replace('_', ' ').upper()} — swapped to light mobility."
    if pref == "reduce" or "limited_time" in tags:
        return "reduce", ("Reduced intensity per client request." if pref == "reduce" else "Client flagged LIMITED TIME — reduced session.")
    if avail is not None:
        try:
            avail_i = int(avail)
        except Exception:
            avail_i = -1
        if avail_i == 0:
            return "rest", "Client has no time today — rest scheduled."
        if 0 < avail_i <= 20:
            return "reduce", f"Only {avail_i} min available — trimmed session."
    if tags & {"hotel_gym", "no_gym", "outdoor_run_possible"}:
        return "location_only", "Location updated based on client tag."
    if "feeling_good" in tags and not (tags & (REST_TAGS | OFF_TAGS | LIGHT_TAGS)):
        return "noop", "Client feeling good — plan unchanged."
    return "noop", ""


async def _apply_override_rules(user_id: str, date: str, override: dict) -> dict:
    """Rules Engine — mutate today's workout doc based on override intent.

    Returns a dict summary { action, reason, workout_id, changed: bool }.
    Respects `coach_locked` and `completed` — no changes to those.
    """
    action, reason = _classify_override(override)
    result = {"action": action, "reason": reason, "changed": False, "workout_id": None, "coach_locked": False}
    if action == "noop":
        return result

    wk = await db.workouts.find_one({"user_id": user_id, "date": date}, {"_id": 0})
    if not wk:
        # No workout on this date — nothing to adjust; alert already emitted upstream
        return result
    if wk.get("coach_locked"):
        result["coach_locked"] = True
        return result
    if wk.get("completed"):
        return result

    result["workout_id"] = wk.get("id")
    patch: dict = {}
    if action == "rest":
        patch = _build_rest_workout(date, reason)
    elif action == "off":
        patch = _build_off_workout(date, reason)
    elif action == "mobility":
        patch = _build_mobility_workout(date, reason)
    elif action == "reduce":
        patch = _reduce_intensity(wk, reason)
    elif action == "location_only":
        # Update location + equipment inference
        tags = set(override.get("tags") or [])
        if "no_gym" in tags:
            new_loc = "Hotel Room (Bodyweight)"
        elif "hotel_gym" in tags:
            new_loc = "Hotel Gym"
        elif "outdoor_run_possible" in tags:
            new_loc = "Outdoor Run"
        else:
            new_loc = wk.get("location") or "Home"
        patch = {**wk, "location": new_loc, "rationale": (wk.get("rationale") or "") + f"  |  {reason}", "override_generated": True, "override_reason": reason}

    if not patch:
        return result

    # Preserve identity + any coach notes
    patch["id"] = wk["id"]
    patch["user_id"] = user_id
    patch["roster_id"] = wk.get("roster_id")
    patch["date"] = date
    patch["approved"] = wk.get("approved", True)
    patch["completed"] = False
    patch["coach_notes"] = wk.get("coach_notes", "")
    patch["coach_locked"] = False
    patch["created_at"] = wk.get("created_at") or now_iso()
    patch["updated_at"] = now_iso()
    patch["status"] = "override_applied"
    patch["override_applied"] = True

    await db.workouts.update_one({"user_id": user_id, "date": date, "id": wk["id"]}, {"$set": patch})
    result["changed"] = True
    result["new_title"] = patch.get("title")
    result["new_duration"] = patch.get("duration_min")
    result["new_day_load"] = patch.get("day_load")
    return result


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

    # Check if any workout exists on this date and whether it's coach-locked
    wk = await db.workouts.find_one({"user_id": user["id"], "date": body.date}, {"_id": 0})
    coach_locked = bool(wk and wk.get("coach_locked"))

    # === Rules Engine: adjust the workout content deterministically ===
    adjustment = await _apply_override_rules(user["id"], body.date, override)
    if adjustment.get("coach_locked"):
        coach_locked = True

    # Emit a coach alert
    try:
        await db.coach_alerts.insert_one({
            "id": new_id(), "client_id": user["id"],
            "client_name": user.get("name") or user.get("email"),
            "kind": "day_edited", "date": body.date,
            "tags": tags, "apply_to": override["apply_to"],
            "adjustment_action": adjustment.get("action"),
            "adjustment_reason": adjustment.get("reason"),
            "created_at": now_iso(), "read": False,
        })
    except Exception:
        pass

    # Living Profile triggers
    try:
        if "injured" in tags or override.get("day_type") == "injury":
            await _emit_reassessment_prompt(
                user["id"], "injury_flagged",
                "You flagged an injury — CrewFit should re-plan around it.",
                {"date": body.date, "tags": tags},
            )
        if "annual_leave" in tags or override.get("day_type") == "annual_leave":
            await _emit_reassessment_prompt(
                user["id"], "annual_leave",
                "Annual leave — want to switch to a light or maintenance block?",
                {"date": body.date},
            )
    except Exception:
        pass

    return {"override": override, "coach_locked": coach_locked, "adjustment": adjustment}


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


# ==================================================================
# CrewFit Intelligence™ — Dynamic Life Adaptation Engine
# ==================================================================
REALITY_KINDS = {
    "exhausted", "flight_delayed", "roster_changed", "hotel_changed", "no_gym",
    "feeling_amazing", "less_time", "more_time", "family_commitments",
    "annual_leave", "feeling_ill", "injured", "travelling", "bad_weather",
    "missed_yesterday", "want_to_move", "other",
}

REALITY_KIND_LABELS = {
    "exhausted": "I'm exhausted",
    "flight_delayed": "Flight delayed",
    "roster_changed": "Roster changed",
    "hotel_changed": "Hotel changed",
    "no_gym": "No gym available",
    "feeling_amazing": "Feeling amazing",
    "less_time": "Less time today",
    "more_time": "More time today",
    "family_commitments": "Family commitments",
    "annual_leave": "Annual leave",
    "feeling_ill": "Feeling ill",
    "injured": "Injured",
    "travelling": "Travelling",
    "bad_weather": "Bad weather",
    "missed_yesterday": "Missed yesterday's workout",
    "want_to_move": "Move this workout",
    "other": "Something else",
}

COACH_MODES = {"strict", "balanced", "flexible"}

REALITY_SYSTEM = """You are Atlas — the CrewFit Intelligence™ engine built by Louis Hall to apply his coaching philosophy at scale.

You are NOT the client's coach. Louis is. Your job is to prepare recommendations based strictly on Louis' coaching methodology so the client's programme adapts consistently.

TONE — use Atlas voice:
- Start recommendations with phrases like "I've identified...", "I've analysed...", "I've prepared...", "I've detected...", "I recommend...", "I've found..."
- NEVER say "I've decided", "I know best", "I'm your coach"
- The `why` field should reference Louis' coaching principles when applicable (consistency beats perfection · recovery drives performance · train around your roster · protect long-term health · progress gradually · individualise everything).

The client just told you what happened in their life today. Your job: think within Louis' coaching framework and prepare THREE options for how to adapt the training programme, ranked A (Recommended) B (Alternative) C (Ask Coach).

Never make the client think like a coach. You do the thinking, within Louis' rules.

USE THE COACHING DNA CONTEXT (if provided) — every recommendation MUST reflect:
- Their `primary_goal` and `next_event` — never sacrifice progress toward these.
- Their `recovery_risk` — high = err on rest / mobility; low = can push.
- Their `motivation_style` — reference in your WHY (e.g., "keeps your streak intact" for routine-driven, "protects the PB target" for competition-driven).
- Their `coaching_style` — strict/supportive/data/etc. shapes tone.
- Their `biggest_weakness` and `biggest_opportunity` — bias recommendations toward these when relevant.
- Their `training_availability` — never propose a session longer than realistic minutes for that context.

RULES (STRICT — these are Louis' guard rails):
1. Never ignore injuries. Never recommend unsafe progressions. Never schedule unrealistic workloads.
2. Never override coach_locked sessions. Never ignore important life events. Never ignore client feedback. Never replace coach judgement.
3. Preserve key sessions (long run, threshold, brick, race sim, heavy strength, testing, peak week) whenever possible.
4. Never place high-intensity within 24h of a long-haul night flight, layover arrival, or after poor sleep.
5. Never place heavy lower-body within 48h of a scheduled long run.
6. Respect coach_locked=true workouts — you MAY suggest an action but ALSO include an "ask_coach" fallback for locked sessions.
7. Recovery matters — if the client is exhausted / feeling ill / injured, prescribe rest, mobility or walk. Do NOT push training.
8. Feeling amazing → OPTIONAL bonus mobility, core, zone-2 or technique work. Do NOT dramatically increase volume.
9. Time-constrained (less_time / 20-min limit) → reduce sets, keep progression intact.
10. No gym / hotel gym missing → replace with bodyweight or outdoor equivalent, MAINTAIN the training objective.
11. Bad weather → indoor alternative that preserves the session focus.
12. Missed yesterday → NEVER pile it on today; either skip safely or split next week.

AVAILABLE ACTION KINDS (return one or more per option):
- {"kind":"keep","date":"YYYY-MM-DD"} — no change
- {"kind":"reduce","date":"YYYY-MM-DD","target_min":<int>} — trim duration/sets, keep focus
- {"kind":"extend","date":"YYYY-MM-DD","add_min":<int>} — add optional bonus work
- {"kind":"replace","date":"YYYY-MM-DD","new_title":"...","new_location":"...","new_focus":"...","target_min":<int>} — same slot, different session (e.g. no-gym swap)
- {"kind":"convert_mobility","date":"YYYY-MM-DD"} — 15-min mobility
- {"kind":"convert_recovery","date":"YYYY-MM-DD"} — 20-min recovery walk / easy spin
- {"kind":"convert_walk","date":"YYYY-MM-DD","target_min":<int>} — walk-only
- {"kind":"skip","date":"YYYY-MM-DD","reason":"..."} — mark as rest / off
- {"kind":"move","from_date":"YYYY-MM-DD","to_date":"YYYY-MM-DD"} — swap the workout with whatever is on to_date (or place on empty day)
- {"kind":"bring_forward","from_date":"YYYY-MM-DD","to_date":"YYYY-MM-DD"} — pull tomorrow's session to today
- {"kind":"push_back","from_date":"YYYY-MM-DD","to_date":"YYYY-MM-DD"} — delay session
- {"kind":"note","date":"YYYY-MM-DD","text":"..."} — coach note, no structural change
- {"kind":"ask_coach","reason":"..."} — only when option C is chosen or a locked session is affected

RESPONSE SCHEMA (return STRICT JSON):
{
  "recovery_score": 0-100,           // your assessment of the client's current recovery
  "context_summary": "short 1-sentence read of the situation",
  "options": [
    {
      "id":"A",
      "label":"Recommended",
      "title":"<8-word summary of what CrewFit will do>",
      "why":"<2-3 sentence explanation referencing roster, event phase, and coaching rules>",
      "risk":"low|medium|high",
      "actions":[ {kind..., ...} ]
    },
    {"id":"B","label":"Alternative", ...},
    {"id":"C","label":"Ask Coach", "title":"Escalate to coach", "why":"...", "risk":"low", "actions":[{"kind":"ask_coach","reason":"..."}]}
  ]
}

Return ONLY JSON, no prose."""


class RealitySubmitBody(BaseModel):
    date: str
    reality_kind: str
    notes: Optional[str] = None
    time_available_min: Optional[int] = None  # optional context signal


class RealityApplyBody(BaseModel):
    reality_event_id: str
    option_id: str  # "A" | "B" | "C"


class CoachModeBody(BaseModel):
    mode: str  # strict | balanced | flexible


async def _build_reality_context(user: dict, target_date: str) -> dict:
    """Assemble the full context payload we hand to Claude for a reality submission."""
    from datetime import datetime as _dt, timedelta as _td
    profile = user.get("profile", {}) or {}
    try:
        anchor = _dt.fromisoformat(target_date).date()
    except Exception:
        anchor = _dt.utcnow().date()
    window_dates = [(anchor + _td(days=i)).isoformat() for i in range(-2, 8)]  # 2 days back, 7 forward

    # Active roster
    roster = await db.rosters.find_one({"user_id": user["id"], "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    roster_days = []
    if roster:
        for d in (roster.get("days") or []):
            if d.get("date") in window_dates:
                roster_days.append({
                    "date": d.get("date"), "day_type": d.get("day_type"),
                    "load": d.get("load"), "hotel_id": d.get("hotel_id"),
                    "flights": (d.get("flights") or [])[:2],
                })

    # Workouts in window
    wkts_raw = await db.workouts.find({"user_id": user["id"], "date": {"$in": window_dates}}, {"_id": 0}).to_list(50)
    workouts = []
    for w in wkts_raw:
        workouts.append({
            "id": w.get("id"), "date": w.get("date"),
            "title": w.get("title"), "focus": w.get("focus"),
            "duration_min": w.get("duration_min"), "day_load": w.get("day_load"),
            "location": w.get("location"), "key_session": bool(w.get("key_session")),
            "event_phase": w.get("event_phase"),
            "coach_locked": bool(w.get("coach_locked")),
            "completed": bool(w.get("completed")),
        })

    # Active event
    ev = await db.events.find_one({"user_id": user["id"], "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    event_ctx = None
    if ev:
        pi = _event_phase(ev.get("event_date", ""))
        event_ctx = {
            "type": ev.get("event_type"), "name": ev.get("event_name"),
            "date": ev.get("event_date"),
            "phase": pi.get("phase"), "weeks_to_race": pi.get("weeks_to_race"),
            "days_to_race": pi.get("days_to_race"),
        }

    # Recent check-ins
    checkins_raw = await db.checkins.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(3)
    checkins = [{
        "date": c.get("date"), "energy": c.get("energy"), "sleep": c.get("sleep"),
        "soreness": c.get("soreness"), "stress": c.get("stress"), "rpe": c.get("rpe"),
    } for c in checkins_raw]

    # Coach mode
    coach_mode = "balanced"
    if user.get("coach_id"):
        coach = await db.users.find_one({"id": user["coach_id"]}, {"_id": 0, "profile": 1})
        if coach:
            coach_mode = (coach.get("profile") or {}).get("coach_mode") or "balanced"

    # Home equipment
    home_equipment = profile.get("home_equipment") or []

    # Living Profile — Coaching DNA context (compact)
    dna_ctx = await _get_dna_context(user["id"])

    return {
        "target_date": target_date,
        "profile": {
            "name": user.get("name"),
            "training_days_per_week": profile.get("training_days_per_week"),
            "experience_level": profile.get("experience_level"),
            "home_equipment": home_equipment,
            "goal": profile.get("goal"),
        },
        "coaching_dna": dna_ctx,
        "coach_mode": coach_mode,
        "roster_days": roster_days,
        "workouts_window": workouts,
        "event": event_ctx,
        "recent_checkins": checkins,
    }


@api.get("/reality/kinds")
async def reality_kinds():
    """List of supported reality kinds with labels — used by the UI to render icon cards."""
    return {"kinds": [{"kind": k, "label": REALITY_KIND_LABELS[k]} for k in REALITY_KIND_LABELS]}


@api.post("/reality/submit")
async def reality_submit(body: RealitySubmitBody, user: dict = Depends(current_user)):
    """Client submits a Today's Reality. AI computes 3 options (A/B/C) and returns them.

    The reality event is persisted with the AI options; client then POSTs /reality/apply
    to execute the chosen option.
    """
    if body.reality_kind not in REALITY_KINDS:
        raise HTTPException(400, f"reality_kind must be one of {sorted(REALITY_KINDS)}")

    ctx = await _build_reality_context(user, body.date)
    ctx["reality_kind"] = body.reality_kind
    ctx["reality_label"] = REALITY_KIND_LABELS[body.reality_kind]
    ctx["client_notes"] = (body.notes or "").strip() or None
    ctx["time_available_min"] = body.time_available_min

    prompt = (
        f"CLIENT REALITY UPDATE ({REALITY_KIND_LABELS[body.reality_kind]}):\n"
        f"Notes: {ctx['client_notes'] or '(none)'}\n"
        f"Time available: {body.time_available_min or 'not specified'} min\n\n"
        f"FULL CONTEXT (JSON):\n{json.dumps(ctx)[:9000]}\n\n"
        "Produce your 3-option adaptation JSON now."
    )

    try:
        raw = await call_claude(REALITY_SYSTEM, prompt, max_out=4000)
        parsed = parse_json_from_text(raw)
    except Exception:
        logger.exception("reality AI failed")
        # Fallback deterministic option based on reality_kind
        parsed = _reality_fallback(body.reality_kind, body.date, ctx, body.time_available_min)

    options = parsed.get("options") or []
    # Coerce to exactly 3 options if the model returned fewer
    while len(options) < 3:
        options.append({
            "id": ["A", "B", "C"][len(options)],
            "label": ["Recommended", "Alternative", "Ask Coach"][len(options)],
            "title": "Escalate to coach",
            "why": "Insufficient AI options — routed to your coach.",
            "risk": "low",
            "actions": [{"kind": "ask_coach", "reason": "AI returned fewer than 3 options"}],
        })
    options = options[:3]
    # Ensure ids A/B/C in order
    for i, o in enumerate(options):
        o["id"] = ["A", "B", "C"][i]
        o.setdefault("label", ["Recommended", "Alternative", "Ask Coach"][i])
        o.setdefault("risk", "low")
        o.setdefault("actions", [])

    # Mark options that touch coach_locked workouts
    locked_dates = {w["date"] for w in ctx.get("workouts_window", []) if w.get("coach_locked")}
    for o in options:
        touches_locked = False
        for a in o.get("actions", []):
            for f in ("date", "from_date", "to_date"):
                if a.get(f) in locked_dates:
                    touches_locked = True
        o["touches_locked"] = touches_locked

    reality_event = {
        "id": new_id(),
        "user_id": user["id"],
        "date": body.date,
        "reality_kind": body.reality_kind,
        "reality_label": REALITY_KIND_LABELS[body.reality_kind],
        "notes": body.notes,
        "time_available_min": body.time_available_min,
        "context_snapshot": ctx,
        "recovery_score": parsed.get("recovery_score"),
        "context_summary": parsed.get("context_summary"),
        "options": options,
        "coach_mode": ctx["coach_mode"],
        "applied_option": None,
        "applied_at": None,
        "status": "awaiting_choice",  # awaiting_choice | applied | ask_coach | expired
        "created_at": now_iso(),
    }
    await db.reality_events.insert_one(reality_event)

    return {
        "reality_event_id": reality_event["id"],
        "recovery_score": reality_event["recovery_score"],
        "context_summary": reality_event["context_summary"],
        "options": options,
        "coach_mode": ctx["coach_mode"],
    }


def _reality_fallback(kind: str, date: str, ctx: dict, time_available: Optional[int]) -> dict:
    """Deterministic 3-option fallback if AI fails or is offline."""
    workouts = ctx.get("workouts_window", [])
    todays = next((w for w in workouts if w.get("date") == date), None)
    label = REALITY_KIND_LABELS.get(kind, kind)

    if kind in ("feeling_ill", "exhausted", "injured"):
        a = {"id": "A", "label": "Recommended", "title": "Full rest today",
             "why": f"You reported: {label}. Rest is the fastest way to bounce back.",
             "risk": "low", "actions": [{"kind": "skip", "date": date, "reason": label}]}
        b = {"id": "B", "label": "Alternative", "title": "Gentle mobility (15m)",
             "why": "If you feel able, a short mobility flow can help without adding load.",
             "risk": "medium", "actions": [{"kind": "convert_mobility", "date": date}]}
    elif kind in ("less_time", "family_commitments"):
        target = time_available if time_available else 20
        a = {"id": "A", "label": "Recommended", "title": f"Trim session to {target} min",
             "why": "Progression preserved by trimming sets, not skipping.",
             "risk": "low", "actions": [{"kind": "reduce", "date": date, "target_min": target}]}
        b = {"id": "B", "label": "Alternative", "title": "Skip today, add optional session later",
             "why": "Better to skip than rush a poor-quality session.",
             "risk": "medium", "actions": [{"kind": "skip", "date": date, "reason": label}]}
    elif kind == "more_time":
        a = {"id": "A", "label": "Recommended", "title": "Optional bonus mobility",
             "why": "Volume already programmed — add mobility rather than more work.",
             "risk": "low", "actions": [{"kind": "extend", "date": date, "add_min": 15}]}
        b = {"id": "B", "label": "Alternative", "title": "Keep session as is",
             "why": "Nothing wrong with banking recovery time.",
             "risk": "low", "actions": [{"kind": "keep", "date": date}]}
    elif kind == "feeling_amazing":
        a = {"id": "A", "label": "Recommended", "title": "Add optional core / mobility",
             "why": "Feeling good is a signal to add quality, not volume.",
             "risk": "low", "actions": [{"kind": "extend", "date": date, "add_min": 15}]}
        b = {"id": "B", "label": "Alternative", "title": "Keep planned session",
             "why": "Ride the wave — the plan is already right.",
             "risk": "low", "actions": [{"kind": "keep", "date": date}]}
    elif kind == "no_gym":
        home_eq = ctx.get("profile", {}).get("home_equipment") or []
        loc = "Hotel Room (Bodyweight)" if not home_eq else "Home Workout"
        a = {"id": "A", "label": "Recommended", "title": "Swap to hotel bodyweight session",
             "why": "Same training objective, no equipment required.",
             "risk": "low", "actions": [{"kind": "replace", "date": date, "new_title": "Hotel Bodyweight", "new_location": loc, "new_focus": todays.get("focus") if todays else "full", "target_min": todays.get("duration_min") if todays else 30}]}
        b = {"id": "B", "label": "Alternative", "title": "Skip today, protect long session later",
             "why": "If time is tight, banking recovery for the key session is smart.",
             "risk": "medium", "actions": [{"kind": "convert_walk", "date": date, "target_min": 30}]}
    elif kind == "bad_weather":
        a = {"id": "A", "label": "Recommended", "title": "Move indoors — same focus",
             "why": "Preserve the training stimulus with an indoor alternative.",
             "risk": "low", "actions": [{"kind": "replace", "date": date, "new_title": "Indoor Alternative", "new_location": "Home Workout", "new_focus": todays.get("focus") if todays else "full", "target_min": todays.get("duration_min") if todays else 40}]}
        b = {"id": "B", "label": "Alternative", "title": "Push today to tomorrow",
             "why": "Weather clears — plan flexes.",
             "risk": "medium", "actions": [{"kind": "push_back", "from_date": date, "to_date": _next_day(date)}]}
    else:  # generic
        a = {"id": "A", "label": "Recommended", "title": "Keep today as planned",
             "why": "The AI didn't detect a strong reason to change — plan stays.",
             "risk": "low", "actions": [{"kind": "keep", "date": date}]}
        b = {"id": "B", "label": "Alternative", "title": "Convert to easy recovery",
             "why": "Recovery is never wasted.",
             "risk": "low", "actions": [{"kind": "convert_recovery", "date": date}]}

    c = {"id": "C", "label": "Ask Coach", "title": "Escalate to coach",
         "why": "Send this to your coach for a personal call on the plan.",
         "risk": "low", "actions": [{"kind": "ask_coach", "reason": label}]}
    return {"recovery_score": None, "context_summary": f"Reality: {label}", "options": [a, b, c]}


def _next_day(d: str) -> str:
    from datetime import datetime as _dt, timedelta as _td
    try:
        return (_dt.fromisoformat(d).date() + _td(days=1)).isoformat()
    except Exception:
        return d


async def _apply_reality_action(user_id: str, action: dict) -> dict:
    """Execute a single Reality action against db.workouts. Returns a change record."""
    kind = action.get("kind")
    change: dict = {"kind": kind, "action": action, "changed": False, "before": None, "after": None}

    async def _find(date: str) -> Optional[dict]:
        return await db.workouts.find_one({"user_id": user_id, "date": date}, {"_id": 0})

    if kind == "keep" or kind == "note":
        d = action.get("date")
        w = await _find(d) if d else None
        if kind == "note" and w:
            note_text = action.get("text") or ""
            new_notes = ((w.get("coach_notes") or "") + ("\n" if w.get("coach_notes") else "") + note_text).strip()
            await db.workouts.update_one({"id": w["id"]}, {"$set": {"coach_notes": new_notes, "updated_at": now_iso()}})
            change.update({"changed": True, "before": {"coach_notes": w.get("coach_notes")}, "after": {"coach_notes": new_notes}})
        return change

    if kind == "ask_coach":
        return change  # no workout mutation; handled at the reality event level

    if kind in ("reduce", "extend", "replace", "convert_mobility", "convert_recovery", "convert_walk", "skip"):
        d = action.get("date")
        if not d:
            return change
        w = await _find(d)
        if not w:
            return change
        if w.get("coach_locked") or w.get("completed"):
            change["skipped_reason"] = "locked_or_completed"
            return change
        before = dict(w)
        patch = dict(w)
        if kind == "reduce":
            target = int(action.get("target_min") or max(15, int((w.get("duration_min") or 40) * 0.6)))
            factor = target / max(1, int(w.get("duration_min") or target))
            patch["duration_min"] = target
            exs = []
            for e in (w.get("exercises") or []):
                e2 = dict(e)
                try:
                    s = int(e2.get("sets") or 0)
                    if s > 1:
                        e2["sets"] = max(1, int(round(s * factor)))
                except Exception:
                    pass
                exs.append(e2)
            patch["exercises"] = exs
            if w.get("day_load") == "red":
                patch["day_load"] = "amber"
            patch["rationale"] = (w.get("rationale") or "") + f"  |  Reduced to {target}m by CrewFit Intelligence."
        elif kind == "extend":
            add = int(action.get("add_min") or 15)
            patch["duration_min"] = int(w.get("duration_min") or 0) + add
            patch["rationale"] = (w.get("rationale") or "") + f"  |  +{add}m optional bonus added."
        elif kind == "replace":
            patch["title"] = action.get("new_title") or w.get("title")
            patch["location"] = action.get("new_location") or w.get("location")
            patch["focus"] = action.get("new_focus") or w.get("focus")
            if action.get("target_min"):
                patch["duration_min"] = int(action["target_min"])
            patch["rationale"] = (w.get("rationale") or "") + f"  |  Replaced: {action.get('new_title')}"
        elif kind == "convert_mobility":
            mob = _build_mobility_workout(d, "Client reality: mobility session prescribed by CrewFit Intelligence.")
            for k in ("day_load", "title", "location", "duration_min", "focus", "warmup", "exercises",
                     "alternatives", "rationale", "key_session", "override_generated", "override_reason"):
                patch[k] = mob.get(k, patch.get(k))
            patch["override_applied"] = True
        elif kind == "convert_recovery":
            patch["day_load"] = "green"
            patch["title"] = "Recovery Session"
            patch["location"] = "Home"
            patch["duration_min"] = 20
            patch["focus"] = "recovery"
            patch["warmup"] = []
            patch["exercises"] = [
                {"name": "Easy walk or spin", "sets": 1, "reps": "20 min", "notes": "Nose-only breathing, zone 1"},
            ]
            patch["rationale"] = (w.get("rationale") or "") + "  |  Converted to recovery."
        elif kind == "convert_walk":
            target = int(action.get("target_min") or 30)
            patch["day_load"] = "green"
            patch["title"] = "Walk"
            patch["location"] = "Outdoor"
            patch["duration_min"] = target
            patch["focus"] = "recovery"
            patch["warmup"] = []
            patch["exercises"] = [{"name": "Steady walk", "sets": 1, "reps": f"{target} min", "notes": "Easy pace"}]
            patch["rationale"] = (w.get("rationale") or "") + f"  |  Converted to {target}m walk."
        elif kind == "skip":
            rest = _build_rest_workout(d, action.get("reason") or "Client reality: skip today.")
            for k in ("day_load", "title", "location", "duration_min", "focus", "warmup", "exercises",
                     "alternatives", "rationale", "key_session", "override_generated", "override_reason"):
                patch[k] = rest.get(k, patch.get(k))
            patch["override_applied"] = True

        patch["override_applied"] = True
        patch["updated_at"] = now_iso()
        await db.workouts.update_one({"id": w["id"]}, {"$set": patch})
        change.update({"changed": True, "before": {k: before.get(k) for k in ("title", "duration_min", "focus", "day_load", "location", "exercises")},
                       "after": {k: patch.get(k) for k in ("title", "duration_min", "focus", "day_load", "location", "exercises")}})
        return change

    if kind in ("move", "bring_forward", "push_back"):
        f, t = action.get("from_date"), action.get("to_date")
        if not f or not t:
            return change
        w_from = await _find(f)
        w_to = await _find(t)
        if not w_from:
            return change
        if w_from.get("coach_locked") or w_from.get("completed"):
            change["skipped_reason"] = "locked_or_completed"
            return change
        if w_to and (w_to.get("coach_locked") or w_to.get("completed")):
            change["skipped_reason"] = "target_locked_or_completed"
            return change
        # Simplest swap: move w_from's payload to date=t (keep id, update date); move w_to's payload to date=f (or leave a rest day if no w_to)
        payload_from = {k: w_from.get(k) for k in ("title", "location", "duration_min", "focus", "warmup",
                                                     "exercises", "alternatives", "rationale", "key_session",
                                                     "event_phase", "day_load")}
        if w_to:
            payload_to = {k: w_to.get(k) for k in ("title", "location", "duration_min", "focus", "warmup",
                                                     "exercises", "alternatives", "rationale", "key_session",
                                                     "event_phase", "day_load")}
            await db.workouts.update_one({"id": w_from["id"]}, {"$set": {**payload_to, "override_applied": True, "updated_at": now_iso(),
                                                                          "rationale": (payload_to.get("rationale") or "") + f"  |  Swapped with {t}."}})
            await db.workouts.update_one({"id": w_to["id"]}, {"$set": {**payload_from, "override_applied": True, "updated_at": now_iso(),
                                                                        "rationale": (payload_from.get("rationale") or "") + f"  |  Moved from {f}."}})
        else:
            # No workout on target date — just move payload_from's payload onto t by updating from's date field
            await db.workouts.update_one({"id": w_from["id"]}, {"$set": {"date": t, "override_applied": True, "updated_at": now_iso(),
                                                                          "rationale": (payload_from.get("rationale") or "") + f"  |  Moved from {f} to {t}."}})
            # Build a rest day on f
            rest = _build_rest_workout(f, f"Session moved to {t}.")
            await db.workouts.insert_one({
                "id": new_id(), "user_id": user_id, "date": f,
                "roster_id": w_from.get("roster_id"),
                **rest, "approved": True, "completed": False, "coach_locked": False,
                "coach_notes": "", "created_at": now_iso(), "updated_at": now_iso(),
                "override_applied": True,
            })
        change.update({"changed": True, "before": {"from": f, "to": t}, "after": {"from": f, "to": t}})
        return change

    return change


@api.post("/reality/apply")
async def reality_apply(body: RealityApplyBody, user: dict = Depends(current_user)):
    """Apply the chosen option from a reality event. Records move_history and marks the event applied."""
    evt = await db.reality_events.find_one({"id": body.reality_event_id, "user_id": user["id"]}, {"_id": 0})
    if not evt:
        raise HTTPException(404, "Reality event not found")
    if evt.get("applied_option"):
        raise HTTPException(400, f"Already applied option {evt['applied_option']}")
    opt = next((o for o in evt.get("options", []) if o.get("id") == body.option_id), None)
    if not opt:
        raise HTTPException(400, f"Option {body.option_id} not found on this reality event")

    # Coach approval gating (strict mode + locked touched → force ask_coach)
    coach_mode = evt.get("coach_mode") or "balanced"
    touches_locked = bool(opt.get("touches_locked"))
    if body.option_id == "C" or (coach_mode == "strict" and touches_locked):
        await db.reality_events.update_one({"id": evt["id"]}, {"$set": {
            "applied_option": body.option_id, "applied_at": now_iso(),
            "status": "ask_coach",
        }})
        try:
            await db.coach_alerts.insert_one({
                "id": new_id(), "client_id": user["id"],
                "client_name": user.get("name") or user.get("email"),
                "kind": "reality_ask_coach", "date": evt.get("date"),
                "reality_event_id": evt["id"],
                "reality_label": evt.get("reality_label"),
                "option_id": body.option_id,
                "created_at": now_iso(), "read": False,
            })
        except Exception:
            pass
        return {"status": "ask_coach", "reality_event_id": evt["id"], "coach_mode": coach_mode}

    # Execute actions
    changes: list[dict] = []
    for a in opt.get("actions", []):
        ch = await _apply_reality_action(user["id"], a)
        changes.append(ch)

    # Record move_history
    await db.move_history.insert_one({
        "id": new_id(), "user_id": user["id"],
        "reality_event_id": evt["id"],
        "reality_kind": evt.get("reality_kind"),
        "reality_label": evt.get("reality_label"),
        "date": evt.get("date"),
        "option_id": body.option_id,
        "option_title": opt.get("title"),
        "option_why": opt.get("why"),
        "changes": changes,
        "actor_id": user["id"],
        "actor_role": user.get("role", "client"),
        "coach_mode": coach_mode,
        "created_at": now_iso(),
    })
    await db.reality_events.update_one({"id": evt["id"]}, {"$set": {
        "applied_option": body.option_id, "applied_at": now_iso(),
        "status": "applied",
    }})

    # Notify coach in balanced mode
    if coach_mode == "balanced":
        try:
            await db.coach_alerts.insert_one({
                "id": new_id(), "client_id": user["id"],
                "client_name": user.get("name") or user.get("email"),
                "kind": "reality_applied", "date": evt.get("date"),
                "reality_event_id": evt["id"],
                "reality_label": evt.get("reality_label"),
                "option_id": body.option_id,
                "option_title": opt.get("title"),
                "created_at": now_iso(), "read": False,
            })
        except Exception:
            pass

    return {"status": "applied", "reality_event_id": evt["id"], "changes": changes, "option": opt}


@api.get("/reality/history")
async def reality_history(limit: int = 50, user: dict = Depends(current_user)):
    """Return the client's move history (most recent first)."""
    rows = await db.move_history.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return {"history": rows}


@api.get("/reality/{event_id}")
async def reality_get(event_id: str, user: dict = Depends(current_user)):
    """Fetch a reality event (client OR their coach)."""
    evt = await db.reality_events.find_one({"id": event_id}, {"_id": 0})
    if not evt:
        raise HTTPException(404, "Not found")
    if user["role"] == "client" and evt["user_id"] != user["id"]:
        raise HTTPException(403, "Forbidden")
    return evt


@api.get("/coach/reality/pending")
async def coach_reality_pending(coach: dict = Depends(require_role("coach"))):
    """List all client reality events that are awaiting coach input."""
    rows = await db.reality_events.find({"status": "ask_coach"}, {"_id": 0}).sort("created_at", -1).to_list(100)
    for r in rows:
        u = await db.users.find_one({"id": r.get("user_id")}, {"_id": 0, "name": 1, "email": 1})
        r["client_name"] = (u or {}).get("name") or (u or {}).get("email") or "Client"
    return rows


class CoachRealityDecisionBody(BaseModel):
    reality_event_id: str
    decision: str  # 'approve_A' | 'approve_B' | 'reject' | 'custom_note'
    note: Optional[str] = None
    apply_option_id: Optional[str] = None  # 'A'|'B' if coach wants to apply a specific option


@api.post("/coach/reality/decision")
async def coach_reality_decision(body: CoachRealityDecisionBody, coach: dict = Depends(require_role("coach"))):
    evt = await db.reality_events.find_one({"id": body.reality_event_id}, {"_id": 0})
    if not evt:
        raise HTTPException(404, "Not found")
    if body.decision == "reject":
        await db.reality_events.update_one({"id": evt["id"]}, {"$set": {"status": "coach_rejected", "coach_note": body.note or "", "coach_reviewed_at": now_iso()}})
        return {"status": "coach_rejected"}
    # Approve — execute the chosen option on the client's behalf
    opt_id = body.apply_option_id or ("A" if body.decision == "approve_A" else "B")
    opt = next((o for o in evt.get("options", []) if o.get("id") == opt_id), None)
    if not opt:
        raise HTTPException(400, "Option not found")
    # Bypass coach_locked because coach is doing it
    changes: list[dict] = []
    for a in opt.get("actions", []):
        # For coach-executed apply, unlock momentarily
        if a.get("kind") in ("move", "bring_forward", "push_back", "reduce", "extend", "replace",
                              "convert_mobility", "convert_recovery", "convert_walk", "skip"):
            # Read then write with an admin flag
            change = await _apply_reality_action(evt["user_id"], a)
            changes.append(change)
        else:
            changes.append({"kind": a.get("kind"), "action": a, "changed": False})
    await db.reality_events.update_one({"id": evt["id"]}, {"$set": {
        "status": "coach_approved", "coach_note": body.note or "",
        "coach_reviewed_at": now_iso(), "coach_reviewer_id": coach["id"],
        "applied_option": opt_id, "applied_at": now_iso(),
    }})
    await db.move_history.insert_one({
        "id": new_id(), "user_id": evt["user_id"],
        "reality_event_id": evt["id"],
        "reality_kind": evt.get("reality_kind"),
        "reality_label": evt.get("reality_label"),
        "date": evt.get("date"),
        "option_id": opt_id, "option_title": opt.get("title"),
        "option_why": opt.get("why"),
        "changes": changes,
        "actor_id": coach["id"], "actor_role": "coach",
        "coach_mode": evt.get("coach_mode"),
        "created_at": now_iso(),
    })
    # Notify the client that the coach updated their programme
    try:
        await notify_programme_updated(evt["user_id"], {"reality_event_id": evt["id"], "date": evt.get("date")})
    except Exception:
        logger.exception("programme_updated notify failed")
    return {"status": "coach_approved", "changes": changes}


@api.patch("/coach/settings/mode")
async def coach_set_mode(body: CoachModeBody, coach: dict = Depends(require_role("coach"))):
    if body.mode not in COACH_MODES:
        raise HTTPException(400, f"mode must be one of {sorted(COACH_MODES)}")
    await db.users.update_one({"id": coach["id"]}, {"$set": {"profile.coach_mode": body.mode}})
    return {"mode": body.mode}


@api.get("/coach/settings")
async def coach_get_settings(coach: dict = Depends(require_role("coach"))):
    prof = coach.get("profile") or {}
    return {
        "coach_mode": prof.get("coach_mode") or "balanced",
        "style": prof.get("style"),
    }


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

    # Living Profile: fetch DNA so workout gen is personalised to Coaching DNA
    dna_ctx = await _get_dna_context(user["id"])

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
            f"Client profile: {json.dumps(profile)[:2000]}\n"
            f"Coaching DNA (living profile): {json.dumps(dna_ctx)[:2500] if dna_ctx else 'not yet built'}\n"
            f"Event context: {json.dumps(event_context)[:1000] if event_context else 'None'}\n"
            f"Days to plan (chronological, 7-day chunk): {json.dumps(chunk)[:7500]}\n"
            "Design exactly one workout per date in this chunk. Return JSON. "
            "Ensure workouts respect the client's Coaching DNA (motivation_style, coaching_style, recovery_risk, training_availability, biggest_weakness/opportunity, next_event) when available."
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
    # Living Profile: opportunistic missed-workout detection
    try:
        from datetime import date as _date, timedelta as _td
        today = _date.today()
        cutoff = today - _td(days=10)
        missed = 0
        for w in rows:
            try:
                d = _date.fromisoformat(w.get("date") or "")
            except Exception:
                continue
            if d >= today or d < cutoff:
                continue
            if w.get("completed") or w.get("override_applied") or w.get("override_generated"):
                continue
            if (w.get("focus") in {"rest", "off"} or w.get("title", "").lower().startswith(("rest", "off"))):
                continue
            missed += 1
        if missed >= 3:
            await _emit_reassessment_prompt(
                user["id"], "missed_workouts",
                f"You've missed {missed} planned sessions recently — is life changing? Take 90s to update CrewFit.",
                {"missed_count": missed},
            )
        # Event-completion detection
        ev = await db.events.find_one({"user_id": user["id"], "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
        if ev and ev.get("event_date"):
            try:
                edate = _date.fromisoformat(ev["event_date"])
                if edate < today:
                    await _emit_reassessment_prompt(
                        user["id"], "event_completed",
                        f"Nice work on {ev.get('event_name') or ev.get('event_type')}! What's next?",
                        {"event_id": ev.get("id"), "event_date": ev.get("event_date")},
                    )
            except Exception:
                pass
    except Exception:
        logger.exception("living-profile trigger check failed")
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


# ==================================================================
# Atlas Exercise Content System (Phase 2)
# ==================================================================
EXERCISE_CONTENT_SYSTEM = """You are Atlas — the CrewFit Intelligence™ engine built by Louis Hall.

Given an exercise name (and optional context), produce coaching content following Louis' methodology.

RULES:
- All content should sound like Louis: clear, concise, safety-first, technique-first.
- Instructions: exactly 4 numbered steps, each a single crisp sentence, action-oriented.
- Coaching cues: 3-5 short imperatives (e.g. "Ribs down", "Drive floor away") — max 4 words each.
- Common mistakes: 3-5 short warnings.

Return STRICT JSON only:
{
  "instructions": ["...", "...", "...", "..."],
  "cues": ["...", "...", "...", "..."],
  "mistakes": ["...", "...", "...", "..."],
  "primary_pattern": "squat|hinge|push|pull|carry|core|cardio|mobility|other",
  "muscles": ["..."],
  "difficulty": "beginner|intermediate|advanced",
  "default_rest_sec": <int>,
  "logging_type": "weighted|bodyweight|cardio|timer|mobility"
}"""


class ExerciseContentPatch(BaseModel):
    instructions: Optional[list[str]] = None
    cues: Optional[list[str]] = None
    mistakes: Optional[list[str]] = None
    regressions: Optional[list[str]] = None
    progressions: Optional[list[str]] = None
    default_rest_sec: Optional[int] = None
    logging_type: Optional[str] = None
    primary_pattern: Optional[str] = None
    equipment: Optional[list[str]] = None
    muscles: Optional[list[str]] = None
    difficulty: Optional[str] = None
    custom_image_b64: Optional[str] = None  # data URL or raw base64
    approved: Optional[bool] = None


async def _find_or_create_exercise(name: str) -> dict:
    ex = await db.exercises.find_one({"name": {"$regex": f"^{name}$", "$options": "i"}}, {"_id": 0})
    if ex:
        return ex
    doc = {
        "id": new_id(), "name": name.strip(),
        "created_at": now_iso(),
        "created_by": "auto",
    }
    await db.exercises.insert_one(doc)
    fresh = await db.exercises.find_one({"id": doc["id"]}, {"_id": 0})
    return fresh or doc


@api.get("/coach/exercises")
async def coach_exercises_list(coach: dict = Depends(require_role("coach"))):
    """Return the exercise library with content-completeness flags for the Coach dashboard.

    Ships a proper 96×96 JPEG thumbnail (`thumb_b64`) generated with Pillow so the coach
    list can render inline previews without the full 500KB+ hero image per row.
    Full `custom_image_b64` is stripped from the list payload for performance.
    """
    rows = await db.exercises.find({}, {"_id": 0}).sort("name", 1).to_list(2000)
    out = []
    for r in rows:
        img = r.get("custom_image_b64") or r.get("coach_image_url")
        thumb = _make_thumb_data_url(img)
        row = {**r}
        row.pop("custom_image_b64", None)  # drop heavy field from list payload
        out.append({
            **row,
            "thumb_b64": thumb,
            "has_instructions": bool(r.get("instructions")),
            "has_cues": bool(r.get("cues")),
            "has_mistakes": bool(r.get("mistakes")),
            "has_video": bool(r.get("video_url") or r.get("coach_video_url")),
            "has_image": bool(r.get("custom_image_b64") or r.get("coach_image_url")),
            "content_score": sum([
                bool(r.get("instructions")),
                bool(r.get("cues")),
                bool(r.get("mistakes")),
                bool(r.get("video_url") or r.get("coach_video_url")),
                bool(r.get("custom_image_b64") or r.get("coach_image_url")),
            ]),
        })
    return {"exercises": out, "count": len(out)}


@api.get("/coach/exercises/{name}")
async def coach_exercises_get(name: str, coach: dict = Depends(require_role("coach"))):
    ex = await _find_or_create_exercise(name)
    return {"exercise": ex}


@api.patch("/coach/exercises/{name}")
async def coach_exercises_patch(name: str, body: ExerciseContentPatch, coach: dict = Depends(require_role("coach"))):
    ex = await _find_or_create_exercise(name)
    updates = body.model_dump(exclude_none=True)
    updates["updated_at"] = now_iso()
    updates["updated_by"] = coach["id"]
    await db.exercises.update_one({"id": ex["id"]}, {"$set": updates})
    fresh = await db.exercises.find_one({"id": ex["id"]}, {"_id": 0})
    return {"exercise": fresh}


class GenerateContentBody(BaseModel):
    fields: Optional[list[str]] = None  # subset: instructions|cues|mistakes|all


@api.post("/coach/exercises/{name}/generate")
async def coach_exercises_generate(name: str, body: GenerateContentBody, coach: dict = Depends(require_role("coach"))):
    """Atlas generates missing coaching content for an exercise (instructions/cues/mistakes)."""
    ex = await _find_or_create_exercise(name)
    want = set(body.fields or ["instructions", "cues", "mistakes", "primary_pattern", "muscles", "difficulty", "default_rest_sec", "logging_type"])
    prompt = f"Exercise name: {name}\nExisting fields: {json.dumps({k: ex.get(k) for k in ('instructions','cues','mistakes','equipment')}, default=str)[:800]}\nProduce Louis Hall coaching content JSON."
    try:
        raw = await call_claude(EXERCISE_CONTENT_SYSTEM, prompt, max_out=1200)
        parsed = parse_json_from_text(raw) or {}
    except Exception:
        logger.exception("exercise content gen failed")
        parsed = {}
    # Only fill fields that are requested AND currently empty (respect coach's work)
    updates: dict[str, Any] = {}
    for k in ("instructions", "cues", "mistakes"):
        if k in want and not ex.get(k) and isinstance(parsed.get(k), list):
            updates[k] = parsed[k]
    for k in ("primary_pattern", "difficulty", "logging_type", "default_rest_sec"):
        if k in want and not ex.get(k) and parsed.get(k) is not None:
            updates[k] = parsed[k]
    if "muscles" in want and not ex.get("muscles") and isinstance(parsed.get("muscles"), list):
        updates["muscles"] = parsed["muscles"]
    if updates:
        updates["updated_at"] = now_iso()
        updates["content_source"] = "atlas"
        updates["approved"] = False  # coach must approve
        await db.exercises.update_one({"id": ex["id"]}, {"$set": updates})
    fresh = await db.exercises.find_one({"id": ex["id"]}, {"_id": 0})
    return {"exercise": fresh, "generated": list(updates.keys()), "raw": parsed}


class ImageUploadBody(BaseModel):
    image_b64: str  # data URL or raw base64


@api.post("/coach/exercises/{name}/image")
async def coach_exercises_image(name: str, body: ImageUploadBody, coach: dict = Depends(require_role("coach"))):
    ex = await _find_or_create_exercise(name)
    b64 = body.image_b64
    if b64.startswith("data:"):
        pass  # keep as data URL
    elif not b64.startswith("http"):
        b64 = "data:image/jpeg;base64," + b64
    await db.exercises.update_one({"id": ex["id"]}, {"$set": {
        "custom_image_b64": b64, "custom_image_uploaded_at": now_iso(),
        "custom_image_uploaded_by": coach["id"],
    }})
    fresh = await db.exercises.find_one({"id": ex["id"]}, {"_id": 0})
    return {"exercise": fresh}


# ---- Atlas AI exercise image generation (Gemini Nano Banana + Louis reference) ----
class GenerateImageBody(BaseModel):
    style_hint: Optional[str] = None  # optional coach override


ATLAS_EXERCISE_IMAGE_SYSTEM = (
    "You are Atlas, the intelligence engine behind Louis Hall's CrewFit method. "
    "You generate clean, professional exercise demonstration photos featuring Louis Hall "
    "(the man in the reference image) as the model. Match his face, hair, build, and skin tone precisely. "
    "The image must look like a modern fitness education photo — no distractions, no logos, no text."
)


def _build_exercise_image_prompt(ex: dict, style_hint: Optional[str] = None) -> str:
    name = ex.get("name", "the exercise")
    equipment = ex.get("equipment") or "bodyweight"
    pattern = ex.get("primary_pattern") or ""
    cues = ex.get("cues") or []
    setup_cue = (cues[0] if cues else "").strip()

    style = (
        style_hint
        or "Clean, bright gym studio photograph. Neutral light-grey seamless backdrop. "
        "Soft, even studio lighting with a subtle rim light. Shot at eye level with a 50mm lens, sharp focus, "
        "shallow depth of field. Louis wears fitted black athletic shorts and a fitted plain black training t-shirt. "
        "No brand logos, no text, no watermark."
    )

    return (
        f"Photorealistic image of Louis Hall (the man in the provided reference image) demonstrating the exercise "
        f"'{name}' with textbook form. Use his face, hair, and build exactly as shown in the reference.\n\n"
        f"Equipment: {equipment}. Movement pattern: {pattern or 'as per exercise'}.\n"
        f"Show the exercise mid-repetition at the most instructive point of the movement — the position that "
        f"best teaches a client the correct technique. {('Key cue to embody: ' + setup_cue + '.') if setup_cue else ''}\n\n"
        f"Style: {style}\n"
        f"Framing: full body or half body as appropriate for the exercise; body fully in frame; feet not cropped "
        f"if standing. Single subject only. No other people, no coaches, no equipment other than what is needed."
    )


@api.post("/coach/exercises/{name:path}/generate-image")
async def coach_exercises_generate_image(
    name: str,
    body: GenerateImageBody = GenerateImageBody(),
    coach: dict = Depends(require_role("coach")),
):
    """Atlas generates a clean-studio exercise demo photo using Louis Hall's reference likeness (Gemini Nano Banana).

    Replaces `custom_image_b64` on the exercise record on success.
    """
    ex = await _find_or_create_exercise(name)

    try:
        ref_b64 = _louis_ref_b64()
    except FileNotFoundError:
        raise HTTPException(500, "Louis reference photo not found on server")

    prompt = _build_exercise_image_prompt(ex, body.style_hint)

    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=new_id(),
            system_message=ATLAS_EXERCISE_IMAGE_SYSTEM,
        ).with_model("gemini", "gemini-3.1-flash-image-preview").with_params(modalities=["image", "text"])

        msg = UserMessage(text=prompt, file_contents=[ImageContent(ref_b64)])
        _text, images = await chat.send_message_multimodal_response(msg)
    except Exception:
        logger.exception("nano banana image gen failed for %s", name)
        raise HTTPException(502, "Atlas image generation failed. Please try again.")

    if not images:
        raise HTTPException(502, "Atlas returned no image")

    img = images[0]
    mime = img.get("mime_type") or "image/png"
    data_url = f"data:{mime};base64,{img['data']}"

    # Persist a longer prompt summary so coach-supplied style_hint is captured in the audit trail.
    updates = {
        "custom_image_b64": data_url,
        "custom_image_uploaded_at": now_iso(),
        "custom_image_uploaded_by": coach["id"],
        "image_source": "atlas_nano_banana",
        "image_prompt_summary": prompt[:900],
    }
    await db.exercises.update_one({"id": ex["id"]}, {"$set": updates})
    fresh = await db.exercises.find_one({"id": ex["id"]}, {"_id": 0})
    return {"exercise": fresh, "source": "atlas_nano_banana"}


# ---- Batch Atlas image generation (background) ------------------------------
class BatchImageBody(BaseModel):
    filter: str = "missing_image"  # "missing_image" | "warmup" | "all" | "category"
    category: Optional[str] = None  # used when filter == "category"
    limit: Optional[int] = None     # cap number of items processed
    force: bool = False             # regenerate even when image already exists


async def _gen_single_image_for(ex: dict) -> tuple[bool, Optional[str]]:
    """Run Nano Banana for one exercise. Returns (ok, error_message)."""
    try:
        ref_b64 = _louis_ref_b64()
    except FileNotFoundError:
        return False, "Louis reference missing"

    try:
        prompt = _build_exercise_image_prompt(ex)
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=new_id(),
            system_message=ATLAS_EXERCISE_IMAGE_SYSTEM,
        ).with_model("gemini", "gemini-3.1-flash-image-preview").with_params(modalities=["image", "text"])
        msg = UserMessage(text=prompt, file_contents=[ImageContent(ref_b64)])
        _text, images = await chat.send_message_multimodal_response(msg)
        if not images:
            return False, "no image returned"
        img = images[0]
        mime = img.get("mime_type") or "image/png"
        data_url = f"data:{mime};base64,{img['data']}"
        await db.exercises.update_one({"id": ex["id"]}, {"$set": {
            "custom_image_b64": data_url,
            "custom_image_uploaded_at": now_iso(),
            "image_source": "atlas_nano_banana_batch",
            "image_prompt_summary": prompt[:900],
        }})
        return True, None
    except Exception as e:
        return False, str(e)[:200]


async def _run_batch_image_job(job_id: str, ex_ids: list[str], coach_id: str) -> None:
    """Background worker: iterate exercises, gen image for each, throttle politely, report progress."""
    total = len(ex_ids)
    started = now_iso()
    await db.image_jobs.update_one({"id": job_id}, {"$set": {
        "status": "running", "started_at": started, "total": total,
    }})
    done = 0
    failed = 0
    errors: list[dict] = []
    try:
        for eid in ex_ids:
            ex = await db.exercises.find_one({"id": eid}, {"_id": 0})
            if not ex:
                failed += 1
                errors.append({"exercise_id": eid, "error": "exercise vanished"})
            else:
                await db.image_jobs.update_one({"id": job_id}, {"$set": {
                    "current_name": ex.get("name"),
                }})
                ok, err = await _gen_single_image_for(ex)
                if ok:
                    done += 1
                else:
                    failed += 1
                    errors.append({"name": ex.get("name"), "error": err or "unknown"})
            await db.image_jobs.update_one({"id": job_id}, {"$set": {
                "processed": done + failed, "succeeded": done, "failed": failed,
                "errors": errors[-25:],  # keep last 25 for the coach
            }})
            # Gentle throttle to avoid provider rate limits
            await asyncio.sleep(1.2)
        await db.image_jobs.update_one({"id": job_id}, {"$set": {
            "status": "done", "finished_at": now_iso(), "current_name": None,
        }})
    except Exception as e:
        logger.exception("batch image job %s crashed", job_id)
        await db.image_jobs.update_one({"id": job_id}, {"$set": {
            "status": "error", "finished_at": now_iso(),
            "fatal_error": str(e)[:400], "current_name": None,
        }})


@api.post("/coach/exercises/batch-generate-images")
async def coach_batch_generate_images(body: BatchImageBody, coach: dict = Depends(require_role("coach"))):
    """Start a background job that generates Atlas images for many exercises at once.

    Respects the `filter` selector so the coach can target warm-up moves, all missing images,
    a specific category, or the whole library.
    """
    # Prevent overlapping jobs — only allow one running at a time.
    active = await db.image_jobs.find_one({"status": {"$in": ["queued", "running"]}}, {"_id": 0})
    if active:
        return {"error": "A batch job is already running.", "job": active}

    q: dict = {}
    if body.filter == "missing_image":
        q = {"$or": [{"custom_image_b64": {"$exists": False}}, {"custom_image_b64": None}, {"custom_image_b64": ""}]}
    elif body.filter == "warmup":
        q = {"category": "warmup"}
        if not body.force:
            q["$or"] = [{"custom_image_b64": {"$exists": False}}, {"custom_image_b64": None}, {"custom_image_b64": ""}]
    elif body.filter == "category":
        if not body.category:
            raise HTTPException(400, "category is required when filter=category")
        q = {"category": body.category}
        if not body.force:
            q["$or"] = [{"custom_image_b64": {"$exists": False}}, {"custom_image_b64": None}, {"custom_image_b64": ""}]
    elif body.filter == "all":
        q = {} if body.force else {"$or": [{"custom_image_b64": {"$exists": False}}, {"custom_image_b64": None}, {"custom_image_b64": ""}]}
    else:
        raise HTTPException(400, "unknown filter")

    rows = await db.exercises.find(q, {"id": 1, "name": 1}).sort("name", 1).to_list(1000)
    ex_ids = [r["id"] for r in rows if r.get("id")]
    if body.limit and body.limit > 0:
        ex_ids = ex_ids[: body.limit]

    if not ex_ids:
        return {"error": "No exercises match this filter.", "count": 0}

    job_id = new_id()
    doc = {
        "id": job_id,
        "status": "queued",
        "coach_id": coach["id"],
        "filter": body.filter,
        "category": body.category,
        "force": body.force,
        "total": len(ex_ids),
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "errors": [],
        "current_name": None,
        "created_at": now_iso(),
        "started_at": None,
        "finished_at": None,
    }
    await db.image_jobs.insert_one(doc)

    # Kick off the async worker (fire-and-forget)
    asyncio.create_task(_run_batch_image_job(job_id, ex_ids, coach["id"]))
    doc.pop("_id", None)
    return {"job": doc}


@api.get("/coach/exercises/batch-generate-images/status")
async def coach_batch_status(coach: dict = Depends(require_role("coach"))):
    """Return the most recent batch image job (running or last-finished)."""
    active = await db.image_jobs.find_one(
        {"status": {"$in": ["queued", "running"]}}, {"_id": 0}
    )
    if active:
        return {"job": active}
    last = await db.image_jobs.find_one({}, {"_id": 0}, sort=[("created_at", -1)])
    return {"job": last}


@api.post("/coach/exercises/batch-generate-images/cancel")
async def coach_batch_cancel(coach: dict = Depends(require_role("coach"))):
    """Mark any running job as cancel-requested. Worker checks between items and stops."""
    # For MVP: just mark done immediately (worker will finish the current item then exit)
    await db.image_jobs.update_many(
        {"status": {"$in": ["queued", "running"]}},
        {"$set": {"status": "cancelled", "finished_at": now_iso()}},
    )
    return {"ok": True}


# ---- Batch Atlas HOW-TO content generation (Claude Sonnet 4.5) --------------
class BatchContentBody(BaseModel):
    filter: str = "missing_content"  # "missing_content" | "warmup" | "all" | "category"
    category: Optional[str] = None
    limit: Optional[int] = None
    force: bool = False  # regenerate even when content exists


async def _gen_single_content_for(ex: dict) -> tuple[bool, Optional[str]]:
    """Run Claude for one exercise. Returns (ok, error_message).

    Fills instructions/cues/mistakes only when empty (respects existing coach work).
    """
    try:
        name = ex.get("name", "")
        existing_ctx = {k: ex.get(k) for k in ("instructions", "cues", "mistakes", "equipment", "category")}
        prompt = (
            f"Exercise name: {name}\n"
            f"Category: {ex.get('category') or 'general'}\n"
            f"Existing fields: {json.dumps(existing_ctx, default=str)[:600]}\n"
            "Produce Louis Hall coaching content JSON. Prioritise safe, aviation-crew-friendly cues."
        )
        raw = await call_claude(EXERCISE_CONTENT_SYSTEM, prompt, max_out=1200)
        parsed = parse_json_from_text(raw) or {}
    except Exception as e:
        return False, str(e)[:200]

    updates: dict[str, Any] = {}
    for k in ("instructions", "cues", "mistakes"):
        if not ex.get(k) and isinstance(parsed.get(k), list) and parsed[k]:
            updates[k] = parsed[k]
    for k in ("primary_pattern", "difficulty", "logging_type", "default_rest_sec"):
        if not ex.get(k) and parsed.get(k) is not None:
            updates[k] = parsed[k]
    if not ex.get("muscles") and isinstance(parsed.get("muscles"), list):
        updates["muscles"] = parsed["muscles"]

    if not updates:
        # Nothing new to save — treat as skipped-success
        return True, None
    updates["updated_at"] = now_iso()
    updates["content_source"] = "atlas_batch"
    updates["approved"] = False  # coach must review
    await db.exercises.update_one({"id": ex["id"]}, {"$set": updates})
    return True, None


async def _run_batch_content_job(job_id: str, ex_ids: list[str], coach_id: str) -> None:
    """Background worker for HOW-TO content batch generation."""
    total = len(ex_ids)
    started = now_iso()
    await db.content_jobs.update_one({"id": job_id}, {"$set": {
        "status": "running", "started_at": started, "total": total,
    }})
    done = 0
    failed = 0
    errors: list[dict] = []
    try:
        for eid in ex_ids:
            # cancellation check
            cur = await db.content_jobs.find_one({"id": job_id}, {"status": 1})
            if not cur or cur.get("status") == "cancelled":
                break
            ex = await db.exercises.find_one({"id": eid}, {"_id": 0})
            if not ex:
                failed += 1
                errors.append({"exercise_id": eid, "error": "exercise vanished"})
            else:
                await db.content_jobs.update_one({"id": job_id}, {"$set": {
                    "current_name": ex.get("name"),
                }})
                ok, err = await _gen_single_content_for(ex)
                if ok:
                    done += 1
                else:
                    failed += 1
                    errors.append({"name": ex.get("name"), "error": err or "unknown"})
            await db.content_jobs.update_one({"id": job_id}, {"$set": {
                "processed": done + failed, "succeeded": done, "failed": failed,
                "errors": errors[-25:],
            }})
            await asyncio.sleep(0.4)  # Claude is faster; lighter throttle
        # Only mark done if not already cancelled
        cur = await db.content_jobs.find_one({"id": job_id}, {"status": 1})
        if cur and cur.get("status") != "cancelled":
            await db.content_jobs.update_one({"id": job_id}, {"$set": {
                "status": "done", "finished_at": now_iso(), "current_name": None,
            }})
    except Exception as e:
        logger.exception("batch content job %s crashed", job_id)
        await db.content_jobs.update_one({"id": job_id}, {"$set": {
            "status": "error", "finished_at": now_iso(),
            "fatal_error": str(e)[:400], "current_name": None,
        }})


@api.post("/coach/exercises/batch-generate-content")
async def coach_batch_generate_content(body: BatchContentBody, coach: dict = Depends(require_role("coach"))):
    """Start a background job that generates HOW-TO content (instructions/cues/mistakes) for many exercises at once.

    Uses Claude Sonnet 4.5. Respects existing coach work — only fills missing fields
    unless `force=true` is set (which still respects existing arrays via `_gen_single_content_for`).
    """
    active = await db.content_jobs.find_one({"status": {"$in": ["queued", "running"]}}, {"_id": 0})
    if active:
        return {"error": "A content batch job is already running.", "job": active}

    # An exercise is "missing content" if it has no instructions.
    missing_q = {"$or": [{"instructions": {"$exists": False}}, {"instructions": None}, {"instructions": []}]}
    if body.filter == "missing_content":
        q = missing_q
    elif body.filter == "warmup":
        q = {"category": "warmup"}
        if not body.force:
            q.update(missing_q)
    elif body.filter == "category":
        if not body.category:
            raise HTTPException(400, "category is required when filter=category")
        q = {"category": body.category}
        if not body.force:
            q.update(missing_q)
    elif body.filter == "all":
        q = {} if body.force else missing_q
    else:
        raise HTTPException(400, "unknown filter")

    rows = await db.exercises.find(q, {"id": 1, "name": 1}).sort("name", 1).to_list(2000)
    ex_ids = [r["id"] for r in rows if r.get("id")]
    if body.limit and body.limit > 0:
        ex_ids = ex_ids[: body.limit]

    if not ex_ids:
        return {"error": "No exercises match this filter.", "count": 0}

    job_id = new_id()
    doc = {
        "id": job_id,
        "kind": "content",
        "status": "queued",
        "coach_id": coach["id"],
        "filter": body.filter,
        "category": body.category,
        "force": body.force,
        "total": len(ex_ids),
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "errors": [],
        "current_name": None,
        "created_at": now_iso(),
        "started_at": None,
        "finished_at": None,
    }
    await db.content_jobs.insert_one(doc)
    asyncio.create_task(_run_batch_content_job(job_id, ex_ids, coach["id"]))
    doc.pop("_id", None)
    return {"job": doc}


@api.get("/coach/exercises/batch-generate-content/status")
async def coach_batch_content_status(coach: dict = Depends(require_role("coach"))):
    """Return the most recent content batch job (running or last-finished)."""
    active = await db.content_jobs.find_one(
        {"status": {"$in": ["queued", "running"]}}, {"_id": 0}
    )
    if active:
        return {"job": active}
    last = await db.content_jobs.find_one({}, {"_id": 0}, sort=[("created_at", -1)])
    return {"job": last}


@api.post("/coach/exercises/batch-generate-content/cancel")
async def coach_batch_content_cancel(coach: dict = Depends(require_role("coach"))):
    """Mark any running content job as cancelled. Worker exits between items."""
    await db.content_jobs.update_many(
        {"status": {"$in": ["queued", "running"]}},
        {"$set": {"status": "cancelled", "finished_at": now_iso()}},
    )
    return {"ok": True}


@api.get("/exercises/content")
async def exercise_content_public(name: str, user: dict = Depends(current_user)):
    """Client-facing lookup used by the Atlas Player HOW TO tile.
    Returns coach-authored content (instructions/cues/mistakes/image) for the named exercise."""
    ex = await db.exercises.find_one({"name": {"$regex": f"^{name}$", "$options": "i"}}, {"_id": 0})
    if not ex:
        return {"exercise": None}
    return {"exercise": {
        "name": ex.get("name"),
        "instructions": ex.get("instructions"),
        "cues": ex.get("cues"),
        "mistakes": ex.get("mistakes"),
        "custom_image_b64": ex.get("custom_image_b64"),
        "coach_image_url": ex.get("coach_image_url"),
        "default_rest_sec": ex.get("default_rest_sec"),
        "logging_type": ex.get("logging_type"),
        "content_source": ex.get("content_source"),
        "approved": ex.get("approved", True),
    }}


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
    # If this is a client-to-coach message, kick off an Atlas draft in the background
    try:
        if user.get("role") == "client":
            recipient = await db.users.find_one({"id": body.to_user_id}, {"role": 1})
            if recipient and recipient.get("role") == "coach":
                asyncio.create_task(_bg_generate_message_draft(user, doc))
    except Exception:
        logger.exception("message draft trigger failed")
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
    overrides = await db.day_overrides.find({"user_id": client_id}, {"_id": 0}).sort("date", -1).to_list(60)
    change_log = await db.day_change_log.find({"user_id": client_id}, {"_id": 0}).sort("created_at", -1).to_list(30)
    return {
        "client": c, "roster": r, "workouts": workouts, "checkins": checkins,
        "roster_history": history, "event": ev or None,
        "overrides": overrides, "change_log": change_log,
    }


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
        # Fetch client's day overrides for this window
        ovs = await db.day_overrides.find({"user_id": u["id"], "date": {"$in": dates}}, {"_id": 0}).to_list(500)
        ov_map: dict[str, dict] = {o["date"]: o for o in ovs}
        cells = []
        for d in dates:
            rd = day_map.get(d, {})
            wk = wkt_map.get(d)
            ov = ov_map.get(d)
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
                "override_applied": bool((wk or {}).get("override_applied") or (wk or {}).get("override_generated")),
                "override_tags": (ov or {}).get("tags") or [],
                "override_notes": (ov or {}).get("notes"),
                "override_pref": (ov or {}).get("training_preference"),
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
    # Zombie job cleanup — any jobs left running from a previous process are dead now.
    for coll in ("image_jobs", "content_jobs"):
        try:
            await db[coll].update_many(
                {"status": {"$in": ["queued", "running"]}},
                {"$set": {
                    "status": "cancelled",
                    "finished_at": now_iso(),
                    "fatal_error": "server restart — worker did not survive",
                }},
            )
        except Exception:
            logger.exception("startup zombie cleanup failed for %s", coll)
    # Kick off the weekly-reminder scheduler (respects quiet hours + IANA time zones).
    asyncio.create_task(_reminder_scheduler_loop())

@app.on_event("shutdown")
async def _shutdown():
    client.close()
    if _push_client is not None:
        await _push_client.aclose()


# ============================================================================
#  SUNDAY CHECK-IN + COACH VIDEO TOUCHPOINT
# ============================================================================
#
# Data model (Mongo collections):
#   check_ins             — one submission per client per week
#   coach_tasks           — coach to-do feed items (check-in review, record video, etc)
#   weekly_videos         — coach video metadata (storage abstracted; local disk for MVP)
#   scheduled_messages    — persistence for reminders (worker deferred to next session)
#
# Design notes:
#   - Time zones are IANA strings (e.g. "Europe/London"). Stored on the user profile.
#   - All weekly recurring times are stored as (local_date, local_time, time_zone) plus a
#     computed `scheduled_utc` for querying. DST handled by zoneinfo — no fixed offsets.
#   - Video storage is abstracted via `_save_coach_video()` — for MVP we save the raw bytes
#     to /app/backend/uploads/coach_videos/ and return a relative URL. Swap this helper to
#     upload to S3/R2 later without touching endpoint code.
#   - Atlas AI: uses Claude Sonnet 4.5 via existing `call_claude()`.

from zoneinfo import ZoneInfo, available_timezones
import datetime as _dt

COACH_VIDEO_DIR = ROOT_DIR / "uploads" / "coach_videos"
COACH_VIDEO_DIR.mkdir(parents=True, exist_ok=True)


class TimeZonePrefsBody(BaseModel):
    home_time_zone: Optional[str] = None
    use_current_device_time_zone_while_travelling: Optional[bool] = None
    current_time_zone: Optional[str] = None
    preferred_check_in_day: Optional[str] = None   # e.g. "sunday"
    preferred_check_in_time: Optional[str] = None  # "HH:MM" local
    preferred_message_time: Optional[str] = None
    quiet_hours_start: Optional[str] = None        # "21:00"
    quiet_hours_end: Optional[str] = None          # "07:00"
    notification_permission_status: Optional[str] = None


@api.put("/user/timezone-prefs")
async def set_timezone_prefs(body: TimeZonePrefsBody, user: dict = Depends(current_user)):
    """Save the client's IANA time zone + weekly-check-in preferences."""
    updates: dict[str, Any] = {}
    tz_set = set(available_timezones())
    if body.home_time_zone is not None:
        if body.home_time_zone not in tz_set:
            raise HTTPException(400, "home_time_zone must be an IANA name like 'Europe/London'")
        updates["home_time_zone"] = body.home_time_zone
    if body.current_time_zone is not None and body.current_time_zone in tz_set:
        updates["current_time_zone"] = body.current_time_zone
    for k in ("preferred_check_in_day", "preferred_check_in_time", "preferred_message_time",
              "quiet_hours_start", "quiet_hours_end", "notification_permission_status"):
        v = getattr(body, k)
        if v is not None:
            updates[k] = v
    if body.use_current_device_time_zone_while_travelling is not None:
        updates["use_current_device_time_zone_while_travelling"] = body.use_current_device_time_zone_while_travelling
    if not updates:
        return {"user": user}
    updates["time_zone_source"] = "user_set"
    updates["updated_at"] = now_iso()
    await db.users.update_one({"id": user["id"]}, {"$set": updates})
    u = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})
    return {"user": u}


def _user_tz(u: dict) -> ZoneInfo:
    name = u.get("current_time_zone") or u.get("home_time_zone") or "Europe/London"
    try: return ZoneInfo(name)
    except Exception: return ZoneInfo("Europe/London")


def _current_week_bounds(u: dict) -> tuple[str, str]:
    """Return (week_start_iso, week_end_iso) — Monday 00:00 → Sunday 23:59 in the user's local time zone."""
    tz = _user_tz(u)
    now_local = _dt.datetime.now(tz)
    monday = (now_local - _dt.timedelta(days=now_local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    sunday = monday + _dt.timedelta(days=6, hours=23, minutes=59, seconds=59)
    return monday.date().isoformat(), sunday.date().isoformat()


CHECKIN_SYSTEM = """You are Atlas — the CrewFit Intelligence™ engine that prepares the weekly review for Louis Hall to deliver as a personal coaching touchpoint.

You are not the coach. Louis is the coach. You prepare summaries and a video script that sound like Louis speaking naturally.

Tone: warm, human, direct, professional, supportive, specific, never cheesy. British spelling. Never use motivational-poster language.

Return STRICT JSON only, no code fences, matching:
{
  "atlas_client_summary": "2-3 short paragraphs to show the client after they submit",
  "atlas_coach_summary": {
    "adherence_note": "...",
    "recovery_note": "...",
    "sleep_note": "...",
    "stress_note": "...",
    "injury_flag": null or "minor" | "moderate" | "severe",
    "nutrition_note": "...",
    "roster_note": "...",
    "motivation_note": "...",
    "suggested_focus_next_week": "...",
    "coach_review_required": true or false,
    "reasoning_for_review": null or "why the coach must review",
    "urgent_safety_flag": null or "chest_pain" | "dizziness" | "severe_pain" | "fainting"
  },
  "next_week_focus": "one short paragraph the client will see",
  "suggested_programme_adjustments": [
    { "area": "strength|running|mobility|rest|nutrition|cardio|other", "change": "human sentence", "rationale": "why" }
  ],
  "weekly_video_script": "45-120 second first-person script for Louis to read on camera. Use client first name. Warm human tone. Structure: greeting → specific positive → check-in insight → roster/fatigue if relevant → training progress → injury/recovery if relevant → next-week focus → one clear action → human sign-off",
  "whatsapp_short": "same content compressed for a text message, 1-3 sentences",
  "push_notification": "one line, under 90 chars"
}"""


@api.get("/checkins/current")
async def checkin_current(user: dict = Depends(current_user)):
    """Return this week's check-in for the client (may be null if not yet submitted)."""
    ws, we = _current_week_bounds(user)
    doc = await db.check_ins.find_one({"user_id": user["id"], "week_start": ws}, {"_id": 0})
    tz_name = user.get("current_time_zone") or user.get("home_time_zone") or "Europe/London"
    # Is today Sunday in the client's local time zone?
    tz = _user_tz(user)
    now_local = _dt.datetime.now(tz)
    is_sunday = now_local.weekday() == 6
    return {
        "check_in": doc, "week_start": ws, "week_end": we,
        "time_zone": tz_name, "is_sunday_local": is_sunday,
        "next_scheduled": f"{ws} 09:00 {tz_name}",
    }


@api.get("/checkins/questions")
async def sunday_checkin_questions(user: dict = Depends(current_user)):
    """Return the check-in question set — core + dynamic based on Coaching DNA + roster."""
    dna = user.get("coaching_dna") or {}
    goals = [str(g).lower() for g in (dna.get("primary_goals") or [])]
    role = (dna.get("crew_role") or user.get("crew_role") or "").lower()
    dynamic: list[dict] = []
    if any("marathon" in g or "run" in g for g in goals):
        dynamic += [
            {"id": "run_long_done", "label": "Did you complete your long run?", "type": "choice", "options": ["Yes", "Partial", "No"]},
            {"id": "run_niggles", "label": "Any running niggles?", "type": "text"},
            {"id": "run_pacing", "label": "How did pacing feel?", "type": "choice", "options": ["On target", "Too fast", "Too slow", "Inconsistent"]},
            {"id": "legs_ready", "label": "Do your legs feel ready for next week?", "type": "choice", "options": ["Yes", "Some fatigue", "No"]},
        ]
    if any("fat" in g or "loss" in g or "cut" in g for g in goals):
        dynamic += [
            {"id": "hunger", "label": "How was hunger this week?", "type": "choice", "options": ["Manageable", "Occasional cravings", "High", "Very high"]},
            {"id": "protein", "label": "How consistent was protein?", "type": "choice", "options": ["Very consistent", "Mostly", "Mixed", "Poor"]},
            {"id": "food_env", "label": "Any difficult food environments?", "type": "text"},
            {"id": "adjust_cals", "label": "Do calories need adjusting?", "type": "choice", "options": ["No", "Slightly lower", "Slightly higher", "Louis to review"]},
        ]
    if any("muscle" in g or "gain" in g or "hypertrophy" in g for g in goals):
        dynamic += [
            {"id": "strength_trend", "label": "Did strength feel stable, up or down?", "type": "choice", "options": ["Up", "Stable", "Down"]},
            {"id": "exercise_difficulty", "label": "Any exercises too easy or too hard?", "type": "text"},
            {"id": "appetite", "label": "Appetite this week?", "type": "choice", "options": ["High", "Normal", "Low"]},
        ]
    if any("iron" in g or "tri" in g for g in goals):
        dynamic += [
            {"id": "swim_consistency", "label": "Swim consistency", "type": "choice", "options": ["Excellent", "Good", "Mixed", "Missed"]},
            {"id": "bike_consistency", "label": "Bike consistency", "type": "choice", "options": ["Excellent", "Good", "Mixed", "Missed"]},
            {"id": "run_consistency", "label": "Run consistency", "type": "choice", "options": ["Excellent", "Good", "Mixed", "Missed"]},
            {"id": "biggest_limiter", "label": "Biggest limiter this week", "type": "text"},
        ]
    if "pilot" in role or "crew" in role or "cabin" in role:
        dynamic += [
            {"id": "flying_impact", "label": "How much did flying affect training this week?", "type": "choice", "options": ["Not much", "Somewhat", "A lot"]},
            {"id": "jetlag", "label": "Any jet lag issues?", "type": "choice", "options": ["No", "Mild", "Significant"]},
            {"id": "post_duty_sleep", "label": "Any poor sleep after duties?", "type": "choice", "options": ["No", "Some", "Bad"]},
            {"id": "layover_gym", "label": "Any layover or hotel gym issues?", "type": "text"},
        ]

    core = [
        {"id": "overall", "label": "How was your overall training week?", "type": "choice",
         "options": ["Excellent", "Good", "Okay", "Difficult", "Poor"]},
        {"id": "energy", "label": "Energy this week", "type": "scale", "min": 1, "max": 5},
        {"id": "sleep", "label": "Sleep quality this week", "type": "scale", "min": 1, "max": 5},
        {"id": "stress", "label": "Stress level this week", "type": "scale", "min": 1, "max": 5},
        {"id": "recovery", "label": "Recovery level this week", "type": "scale", "min": 1, "max": 5},
        {"id": "pain", "label": "Any pain, injury or discomfort?", "type": "choice",
         "options": ["No", "Yes, minor", "Yes, moderate", "Yes, severe"]},
        {"id": "pain_where", "label": "Where is the pain?", "type": "text", "show_if": {"pain": ["Yes, minor", "Yes, moderate", "Yes, severe"]}},
        {"id": "pain_worse", "label": "What movements make it worse?", "type": "text", "show_if": {"pain": ["Yes, minor", "Yes, moderate", "Yes, severe"]}},
        {"id": "nutrition", "label": "Nutrition consistency this week", "type": "choice",
         "options": ["Very consistent", "Mostly consistent", "Mixed", "Poor", "Not focused on nutrition"]},
        {"id": "biggest_win", "label": "Biggest win this week", "type": "text"},
        {"id": "biggest_challenge", "label": "Biggest challenge this week", "type": "text"},
        {"id": "for_louis", "label": "Anything Louis needs to know?", "type": "text"},
    ]
    return {"core": core, "dynamic": dynamic}


class CheckinSubmitBody(BaseModel):
    answers: dict[str, Any]
    submitted_time_zone: Optional[str] = None


def _severity_flag(answers: dict) -> Optional[str]:
    """Detect urgent safety keywords. Returns a flag name or None."""
    pain = str(answers.get("pain") or "").lower()
    text = " ".join(str(answers.get(k) or "") for k in ("pain_where", "pain_worse", "for_louis", "biggest_challenge")).lower()
    if "chest pain" in text or "chest tightness" in text: return "chest_pain"
    if "dizzy" in text or "dizziness" in text or "faint" in text: return "dizziness"
    if "severe" in pain or "severe" in text: return "severe_pain"
    return None


async def _create_coach_task(user: dict, task_type: str, title: str, description: str,
                             priority: str = "normal", check_in_id: Optional[str] = None,
                             video_id: Optional[str] = None,
                             message_draft_id: Optional[str] = None,
                             risk_level: Optional[str] = None,
                             category: Optional[str] = None,
                             payload: Optional[dict] = None) -> str:
    coach = await db.users.find_one({"role": "coach"}, {"id": 1})
    coach_id = (coach or {}).get("id")
    tz_name = user.get("current_time_zone") or user.get("home_time_zone") or "Europe/London"
    doc = {
        "id": new_id(),
        "coach_id": coach_id,
        "user_id": user["id"],
        "user_name": user.get("name") or user.get("email"),
        "check_in_id": check_in_id,
        "video_id": video_id,
        "message_draft_id": message_draft_id,
        "task_type": task_type,
        "category": category or _task_category_for(task_type),
        "title": title,
        "description": description,
        "priority": priority,
        "risk_level": risk_level,
        "status": "todo",
        "due_time_zone": tz_name,
        "created_at": now_iso(),
        "completed_at": None,
        "snoozed_until": None,
        "dismissed_at": None,
        "payload": payload or {},
    }
    await db.coach_tasks.insert_one(doc)
    return doc["id"]


def _task_category_for(task_type: str) -> str:
    if task_type in ("injury_urgent",):
        return "urgent_safety"
    if task_type in ("message_draft_ready",):
        return "messages"
    if task_type in ("check_in_review", "missed_check_in"):
        return "reviews"
    if task_type in ("record_weekly_video",):
        return "videos"
    if task_type in ("programme_adjustment",):
        return "programme"
    if task_type in ("roster_expired",):
        return "roster"
    return "other"


@api.post("/checkins/submit")
async def checkin_submit(body: CheckinSubmitBody, user: dict = Depends(current_user)):
    """Client submits their weekly check-in. Atlas analyses and creates coach tasks."""
    ws, we = _current_week_bounds(user)
    existing = await db.check_ins.find_one({"user_id": user["id"], "week_start": ws})
    if existing:
        return {"check_in": {**existing, "_id": None}, "duplicate": True}

    tz_name = body.submitted_time_zone or user.get("current_time_zone") or user.get("home_time_zone") or "Europe/London"
    urgent_flag = _severity_flag(body.answers)

    # Snapshot the week's training + roster + reality context
    week_workouts = await db.workouts.find(
        {"user_id": user["id"], "date": {"$gte": ws, "$lte": we}}, {"_id": 0}
    ).to_list(20)
    completed = [w for w in week_workouts if w.get("completed")]
    context = {
        "client_name": (user.get("name") or "").split(" ")[0] or "there",
        "goals": (user.get("coaching_dna") or {}).get("primary_goals") or [],
        "crew_role": (user.get("coaching_dna") or {}).get("crew_role") or user.get("crew_role"),
        "time_zone": tz_name,
        "week_start": ws,
        "week_end": we,
        "workouts_planned": len(week_workouts),
        "workouts_completed": len(completed),
        "workouts_missed": len(week_workouts) - len(completed),
        "answers": body.answers,
        "urgent_flag": urgent_flag,
    }

    prompt = "Prepare the weekly review for this CrewFit client:\n\n" + json.dumps(context, default=str)[:5000]
    parsed: dict[str, Any] = {}
    try:
        raw = await call_claude(CHECKIN_SYSTEM, prompt, max_out=2400)
        parsed = parse_json_from_text(raw) or {}
    except Exception:
        logger.exception("Atlas check-in analysis failed")

    coach_summary = parsed.get("atlas_coach_summary") or {}
    coach_review_required = bool(coach_summary.get("coach_review_required")) or bool(urgent_flag)

    doc = {
        "id": new_id(),
        "user_id": user["id"],
        "user_name": user.get("name") or user.get("email"),
        "week_start": ws,
        "week_end": we,
        "submitted_at": now_iso(),
        "submitted_time_zone": tz_name,
        "answers": body.answers,
        "training_adherence": (len(completed) / max(1, len(week_workouts))) if week_workouts else None,
        "energy_score": body.answers.get("energy"),
        "sleep_score": body.answers.get("sleep"),
        "stress_score": body.answers.get("stress"),
        "recovery_score": body.answers.get("recovery"),
        "pain_flag": body.answers.get("pain"),
        "injury_flag": coach_summary.get("injury_flag"),
        "nutrition_flag": body.answers.get("nutrition") in ["Poor", "Mixed"],
        "urgent_safety_flag": urgent_flag or coach_summary.get("urgent_safety_flag"),
        "atlas_client_summary": parsed.get("atlas_client_summary"),
        "atlas_coach_summary": coach_summary,
        "next_week_focus": parsed.get("next_week_focus"),
        "suggested_programme_adjustments": parsed.get("suggested_programme_adjustments"),
        "weekly_video_script": parsed.get("weekly_video_script"),
        "whatsapp_short": parsed.get("whatsapp_short"),
        "push_notification": parsed.get("push_notification"),
        "coach_review_status": "pending",
        "coach_review_required": coach_review_required,
        "weekly_video_status": "script_ready",
        "weekly_video_id": None,
        "reviewed_by": None,
        "reviewed_at": None,
    }
    await db.check_ins.insert_one(doc)

    # Create coach tasks
    await _create_coach_task(user, "check_in_review",
                             f"Check-in from {doc['user_name']}",
                             "Review Atlas summary and prepare video script.",
                             priority="high" if coach_review_required else "normal",
                             check_in_id=doc["id"])
    await _create_coach_task(user, "record_weekly_video",
                             f"Record video for {doc['user_name']}",
                             "Atlas has prepared a video script. Record and send.",
                             priority="high" if coach_review_required else "normal",
                             check_in_id=doc["id"])
    if urgent_flag:
        await _create_coach_task(user, "injury_urgent",
                                 f"URGENT: {urgent_flag.replace('_',' ').title()} reported by {doc['user_name']}",
                                 "Review before progressing training.",
                                 priority="urgent",
                                 check_in_id=doc["id"])

    # Trigger the Atlas habit review in background so the check-in can return quickly
    try:
        asyncio.create_task(_run_habit_review_after_checkin(user["id"], doc["id"], ws, we))
    except Exception:
        logger.exception("habit review trigger failed")

    doc.pop("_id", None)
    return {"check_in": doc}


@api.get("/checkins/history")
async def checkin_history(user: dict = Depends(current_user), limit: int = 12):
    rows = await db.check_ins.find({"user_id": user["id"]}, {"_id": 0}).sort("week_start", -1).to_list(limit)
    return {"check_ins": rows}


# ---- Coach Tasks Feed ------------------------------------------------------
@api.get("/coach/tasks")
async def coach_tasks_list(coach: dict = Depends(require_role("coach")),
                          status: Optional[str] = None,
                          filter_type: Optional[str] = None):
    q: dict[str, Any] = {}
    if status:
        q["status"] = status
    else:
        q["status"] = {"$in": ["todo", "in_progress", "scheduled", "waiting_for_client"]}
    if filter_type:
        q["task_type"] = filter_type
    rows = await db.coach_tasks.find(q, {"_id": 0}).sort([("priority", -1), ("created_at", -1)]).to_list(200)
    # Sort by priority manually (urgent > high > normal > low)
    order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    rows.sort(key=lambda r: (order.get(r.get("priority", "normal"), 5), r.get("created_at") or ""))
    return {"tasks": rows, "count": len(rows)}


class CoachTaskUpdate(BaseModel):
    status: Optional[str] = None
    snoozed_until: Optional[str] = None
    coach_note: Optional[str] = None


@api.patch("/coach/tasks/{task_id}")
async def coach_task_update(task_id: str, body: CoachTaskUpdate, coach: dict = Depends(require_role("coach"))):
    updates: dict[str, Any] = {}
    if body.status:
        updates["status"] = body.status
        if body.status in ("done", "sent", "reviewed", "dismissed"):
            updates["completed_at"] = now_iso()
        if body.status == "dismissed":
            updates["dismissed_at"] = now_iso()
    if body.snoozed_until:
        updates["snoozed_until"] = body.snoozed_until
    if body.coach_note is not None:
        updates["coach_note"] = body.coach_note
    if not updates:
        raise HTTPException(400, "no updates")
    await db.coach_tasks.update_one({"id": task_id}, {"$set": updates})
    t = await db.coach_tasks.find_one({"id": task_id}, {"_id": 0})
    return {"task": t}


# ---- Coach check-in review + script editing --------------------------------
@api.get("/coach/checkins/{checkin_id}")
async def coach_get_checkin(checkin_id: str, coach: dict = Depends(require_role("coach"))):
    ci = await db.check_ins.find_one({"id": checkin_id}, {"_id": 0})
    if not ci:
        raise HTTPException(404, "check-in not found")
    return {"check_in": ci}


class ScriptEditBody(BaseModel):
    weekly_video_script: str


@api.put("/coach/checkins/{checkin_id}/script")
async def coach_edit_script(checkin_id: str, body: ScriptEditBody, coach: dict = Depends(require_role("coach"))):
    await db.check_ins.update_one({"id": checkin_id}, {"$set": {
        "weekly_video_script": body.weekly_video_script,
        "script_edited_by": coach["id"], "script_edited_at": now_iso(),
    }})
    ci = await db.check_ins.find_one({"id": checkin_id}, {"_id": 0})
    return {"check_in": ci}


# ---- Coach Videos (storage abstraction) -----------------------------------
async def _save_coach_video(video_bytes: bytes, mime: str, video_id: str) -> str:
    """Save video bytes to disk (MVP) and return a URL. Swap this for S3/R2 later without
    touching endpoint code — same signature."""
    ext = "mp4"
    if "webm" in mime: ext = "webm"
    elif "quicktime" in mime or "mov" in mime: ext = "mov"
    path = COACH_VIDEO_DIR / f"{video_id}.{ext}"
    with open(path, "wb") as f:
        f.write(video_bytes)
    return f"/api/coach/videos/{video_id}/file"


class CoachVideoCreateBody(BaseModel):
    check_in_id: str
    user_id: str
    script: str
    duration_seconds: Optional[int] = None
    file_b64: Optional[str] = None
    file_mime: Optional[str] = None
    file_url: Optional[str] = None


@api.post("/coach/videos")
async def coach_create_video(body: CoachVideoCreateBody, coach: dict = Depends(require_role("coach"))):
    ci = await db.check_ins.find_one({"id": body.check_in_id}, {"_id": 0})
    if not ci:
        raise HTTPException(404, "check_in not found")
    video_id = new_id()
    file_url = body.file_url
    if body.file_b64 and not file_url:
        try:
            raw = base64.b64decode(body.file_b64.split(",")[-1])
            file_url = await _save_coach_video(raw, body.file_mime or "video/mp4", video_id)
        except Exception as e:
            raise HTTPException(400, f"invalid file_b64: {e}")
    doc = {
        "id": video_id,
        "user_id": body.user_id,
        "coach_id": coach["id"],
        "check_in_id": body.check_in_id,
        "script": body.script,
        "file_url": file_url,
        "thumbnail_url": None,
        "duration_seconds": body.duration_seconds,
        "status": "draft" if not file_url else "recorded",
        "created_at": now_iso(),
        "sent_at": None,
        "watched_at": None,
    }
    await db.weekly_videos.insert_one(doc)
    await db.check_ins.update_one({"id": body.check_in_id}, {"$set": {
        "weekly_video_id": video_id, "weekly_video_status": doc["status"],
    }})
    doc.pop("_id", None)
    return {"video": doc}


@api.post("/coach/videos/{video_id}/send")
async def coach_send_video(video_id: str, coach: dict = Depends(require_role("coach"))):
    v = await db.weekly_videos.find_one({"id": video_id}, {"_id": 0})
    if not v:
        raise HTTPException(404, "video not found")
    now = now_iso()
    await db.weekly_videos.update_one({"id": video_id}, {"$set": {"status": "sent", "sent_at": now}})
    await db.check_ins.update_one({"id": v["check_in_id"]}, {"$set": {
        "weekly_video_status": "sent", "weekly_video_sent_at": now,
    }})
    # Mark associated coach tasks as sent
    await db.coach_tasks.update_many(
        {"check_in_id": v["check_in_id"], "task_type": "record_weekly_video"},
        {"$set": {"status": "sent", "completed_at": now, "video_id": video_id}},
    )
    # Notify the client (push + in-app)
    try:
        await notify_weekly_video_ready(v["user_id"], video_id)
    except Exception:
        logger.exception("weekly video notify failed")
    # Create client-facing message record
    await db.messages.insert_one({
        "id": new_id(),
        "from_id": coach["id"],
        "to_id": v["user_id"],
        "kind": "weekly_video",
        "video_id": video_id,
        "body": "Your weekly coaching review is ready.",
        "created_at": now,
        "read_at": None,
    })
    return {"ok": True, "sent_at": now}


@api.get("/coach/videos/{video_id}/file")
async def coach_video_file(video_id: str):
    """Serve a coach-recorded video. No auth for MVP — signed URLs when we move to S3."""
    for ext in ("mp4", "webm", "mov"):
        p = COACH_VIDEO_DIR / f"{video_id}.{ext}"
        if p.exists():
            mimes = {"mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime"}
            return FileResponse(str(p), media_type=mimes[ext])
    raise HTTPException(404, "video file not found")


@api.get("/videos/for-me")
async def videos_for_me(user: dict = Depends(current_user)):
    """Client fetches their weekly videos (sent only)."""
    rows = await db.weekly_videos.find(
        {"user_id": user["id"], "status": "sent"}, {"_id": 0}
    ).sort("sent_at", -1).to_list(20)
    return {"videos": rows}


@api.post("/videos/{video_id}/watched")
async def video_watched(video_id: str, user: dict = Depends(current_user)):
    await db.weekly_videos.update_one(
        {"id": video_id, "user_id": user["id"]},
        {"$set": {"watched_at": now_iso()}},
    )
    return {"ok": True}


# ---- Reminder Scheduler Worker --------------------------------------------
REMINDER_SLOTS = [
    ("weekly_check_in_available", 6, 9, 0),   # (kind, weekday 0=Mon..6=Sun, hour, minute)
    ("reminder_1", 6, 17, 0),
    ("reminder_2", 0, 9, 0),
    ("reminder_last", 0, 18, 0),
]


def _in_quiet_hours(local_dt: _dt.datetime, quiet_start: str, quiet_end: str) -> bool:
    def _t(s: str) -> _dt.time:
        try:
            h, m = s.split(":"); return _dt.time(int(h), int(m))
        except Exception:
            return _dt.time(21, 0)
    qs, qe = _t(quiet_start), _t(quiet_end)
    cur = local_dt.time()
    if qs > qe:  # wraps midnight, e.g. 21:00 → 07:00
        return cur >= qs or cur < qe
    return qs <= cur < qe


async def _tick_reminders() -> None:
    users = await db.users.find({"role": "client"}, {"_id": 0, "password_hash": 0}).to_list(2000)
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    for u in users:
        tz_name = u.get("current_time_zone") or u.get("home_time_zone") or "Europe/London"
        try: tz = ZoneInfo(tz_name)
        except Exception: continue
        local_now = now_utc.astimezone(tz)
        if _in_quiet_hours(local_now, u.get("quiet_hours_start", "21:00"), u.get("quiet_hours_end", "07:00")):
            continue
        ws, _ = _current_week_bounds(u)
        if await db.check_ins.find_one({"user_id": u["id"], "week_start": ws}, {"id": 1}):
            continue
        for kind, weekday, hh, mm in REMINDER_SLOTS:
            if local_now.weekday() != weekday: continue
            if local_now.hour != hh: continue
            if not (mm <= local_now.minute < mm + 10): continue
            if await db.scheduled_messages.find_one(
                {"user_id": u["id"], "message_type": kind, "week_start": ws}, {"id": 1}
            ): continue
            body_map = {
                "weekly_check_in_available": "Your CrewFit weekly check-in is ready.",
                "reminder_1": "Quick reminder: complete your weekly check-in when you're off duty or settled.",
                "reminder_2": "Your check-in is still open. Completing it helps Louis review your week properly.",
                "reminder_last": "Last reminder for this week's check-in.",
            }
            await db.scheduled_messages.insert_one({
                "id": new_id(),
                "user_id": u["id"],
                "message_type": kind,
                "week_start": ws,
                "title": "Weekly check-in",
                "body": body_map.get(kind, "Weekly check-in reminder"),
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


async def _reminder_scheduler_loop() -> None:
    """Every 5 minutes: enqueue Sunday-morning + missed-check-in reminders per client local time.
    Rules: Sun 09:00, Sun 17:00, Mon 09:00, Mon 18:00 — never inside quiet hours — idempotent per week."""
    while True:
        try:
            await _tick_reminders()
        except Exception:
            logger.exception("reminder scheduler tick failed")
        await asyncio.sleep(300)


@api.get("/scheduled-messages/mine")
async def scheduled_messages_mine(user: dict = Depends(current_user), limit: int = 20):
    rows = await db.scheduled_messages.find(
        {"user_id": user["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(limit)
    return {"scheduled": rows}


# ---- Coach Sunday check-ins listing (with filters) ------------------------
@api.get("/coach/checkins")
async def coach_checkins_list(coach: dict = Depends(require_role("coach")),
                              filter_type: Optional[str] = None,
                              limit: int = 100):
    q: dict[str, Any] = {}
    if filter_type == "needs_review":
        q["coach_review_required"] = True
        q["reviewed_at"] = None
    elif filter_type == "video_sent":
        q["weekly_video_status"] = "sent"
    elif filter_type == "video_needed":
        q["weekly_video_status"] = {"$in": ["script_ready", "draft", "recorded"]}
    elif filter_type == "injury":
        q["$or"] = [{"injury_flag": {"$in": ["minor", "moderate", "severe"]}},
                    {"urgent_safety_flag": {"$ne": None}}]
    elif filter_type == "low_recovery":
        q["recovery_score"] = {"$lte": 2}
    elif filter_type == "completed":
        q["weekly_video_status"] = "sent"
    rows = await db.check_ins.find(q, {"_id": 0}).sort("submitted_at", -1).to_list(limit)
    return {"check_ins": rows, "count": len(rows)}





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
async def _log_change(coach_id: Optional[str], client_id: Optional[str], category: str,
                      title: str, description: str = "", actor: str = "coach",
                      meta: Optional[dict] = None) -> None:
    doc = {
        "id": new_id(),
        "coach_id": coach_id,
        "client_id": client_id,
        "category": category,          # message / programme / controls / script / workout / other
        "title": title,
        "description": description,
        "actor": actor,                # coach / atlas / client / system
        "meta": meta or {},
        "created_at": now_iso(),
    }
    try:
        await db.coach_change_log.insert_one(doc)
    except Exception:
        logger.exception("change log insert failed")


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


# Extend the existing reminder loop by also ticking habit reminders each cycle
_ORIGINAL_TICK_REMINDERS = _tick_reminders


async def _tick_reminders_with_habits() -> None:
    await _ORIGINAL_TICK_REMINDERS()
    await _tick_habit_reminders()


_tick_reminders = _tick_reminders_with_habits  # override — _reminder_scheduler_loop uses this name


# ============================================================================
# NOTIFICATIONS + REMINDERS V1
#
# Collections:
#   notifications      — in-app notification centre (bell)
#   scheduled_messages — reminder queue (existing)
#
# Rules:
#   * Every enqueue also writes an in-app notification (fallback when push is off).
#   * Deduplicate on (user_id, notif_type, related_id, dedupe_key).
#   * Respect quiet hours + notification_settings toggles + flight duty context.
#   * Never break existing scheduling. Extend _tick_reminders in place.
# ============================================================================

DEFAULT_NOTIFICATION_SETTINGS = {
    "check_ins": True,
    "habits": True,
    "workouts": True,
    "coach_messages": True,
    "weekly_videos": True,
    "roster": True,
    "programme_updates": True,
    "quiet_hours_start": "21:00",
    "quiet_hours_end": "07:00",
    "preferred_reminder_time": "07:30",
    "travel_use_current_tz": True,
    "permission_status": "not_requested",
}

# Map notif_type → category key inside notification_settings
NOTIF_CATEGORY: dict[str, str] = {
    "weekly_check_in_available": "check_ins",
    "reminder_1": "check_ins",
    "reminder_2": "check_ins",
    "reminder_last": "check_ins",
    "missed_check_in": "check_ins",
    "habit_daily": "habits",
    "workout_today": "workouts",
    "coach_message": "coach_messages",
    "coach_draft_ready": "coach_messages",
    "weekly_video_ready": "weekly_videos",
    "programme_updated": "programme_updates",
    "roster_low": "roster",
    "roster_due": "roster",
    "roster_expired": "roster",
}


def _get_notif_settings(user: dict) -> dict:
    stored = user.get("notification_settings") or {}
    out = {**DEFAULT_NOTIFICATION_SETTINGS, **stored}
    # top-level quiet_hours override (older schema)
    if user.get("quiet_hours_start"): out["quiet_hours_start"] = user["quiet_hours_start"]
    if user.get("quiet_hours_end"):   out["quiet_hours_end"]   = user["quiet_hours_end"]
    return out


def _user_local_now(user: dict) -> tuple[_dt.datetime, str]:
    tz_name = user.get("current_time_zone") or user.get("home_time_zone") or "Europe/London"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Europe/London")
        tz_name = "Europe/London"
    return _dt.datetime.now(tz), tz_name


async def _is_on_duty_now(user_id: str, today: str) -> bool:
    """Heuristic — active flight/duty from today's roster row or today's workout day_type."""
    wk = await db.workouts.find_one({"user_id": user_id, "date": today}, {"_id": 0, "day_type": 1})
    if wk and _is_flight_day(wk.get("day_type")):
        return True
    roster = await db.rosters.find_one({"user_id": user_id, "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    if roster:
        for d in roster.get("days", []):
            if d.get("date") == today:
                dt = (d.get("type") or d.get("day_type") or "").lower()
                return any(k in dt for k in ("flight", "duty", "standby"))
    return False


def _duty_safe_body(body: str) -> str:
    """Soften copy for clients on duty."""
    return body + " (when you're off duty and settled.)"


async def enqueue_notification(
    user_id: str,
    notif_type: str,
    title: str,
    body: str,
    *,
    action_url: Optional[str] = None,
    related_id: Optional[str] = None,
    dedupe_key: Optional[str] = None,
    respect_settings: bool = True,
    respect_quiet_hours: bool = False,      # in-app rows can be created any time; push may be delayed
    send_push_now: bool = True,
    idempotency_key: Optional[str] = None,
) -> Optional[dict]:
    """Create an in-app notification, dedupe by (user_id, notif_type, related_id, dedupe_key).
    Also attempts to send a push if the user granted permission and category is enabled.
    Never raises — push failure only downgrades to in-app.
    """
    user = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not user:
        return None
    settings = _get_notif_settings(user)
    cat = NOTIF_CATEGORY.get(notif_type)
    category_enabled = True
    if respect_settings and cat and cat in settings:
        category_enabled = bool(settings.get(cat, True))
    # Dedupe query
    dedupe_query: dict[str, Any] = {"user_id": user_id, "notif_type": notif_type}
    if related_id: dedupe_query["related_id"] = related_id
    if dedupe_key: dedupe_query["dedupe_key"] = dedupe_key
    existing = await db.notifications.find_one(dedupe_query, {"_id": 0})
    if existing:
        # Refresh body/title if changed but keep read state
        await db.notifications.update_one(
            {"id": existing["id"]},
            {"$set": {"title": title, "body": body, "action_url": action_url, "updated_at": now_iso()}},
        )
        existing.update({"title": title, "body": body, "action_url": action_url, "updated_at": now_iso()})
        return existing
    # Flight-duty rewording
    on_duty = False
    if notif_type in ("workout_today", "habit_daily", "reminder_1", "reminder_2", "weekly_check_in_available"):
        try:
            local_now, _ = _user_local_now(user)
            today = local_now.date().isoformat()
            on_duty = await _is_on_duty_now(user_id, today)
        except Exception:
            on_duty = False
    final_body = _duty_safe_body(body) if on_duty else body
    doc = {
        "id": new_id(),
        "user_id": user_id,
        "notif_type": notif_type,
        "category": cat,
        "title": title,
        "body": final_body,
        "action_url": action_url,
        "related_id": related_id,
        "dedupe_key": dedupe_key,
        "flight_duty_safe": on_duty,
        "created_at": now_iso(),
        "read_at": None,
        "updated_at": now_iso(),
    }
    await db.notifications.insert_one(doc)
    doc.pop("_id", None)
    # Push (best-effort, non-blocking)
    if send_push_now and category_enabled and settings.get("permission_status") == "granted":
        try:
            await send_push(
                recipients=[user_id],
                data={"title": title, "message": final_body, **({"action_url": action_url} if action_url else {})},
                idempotency_key=idempotency_key,
            )
        except Exception as e:
            logger.warning("push failed (in-app still created): %s", e)
            await db.notifications.update_one({"id": doc["id"]}, {"$set": {"push_error": str(e)[:180]}})
    return doc


# ---- Endpoints -------------------------------------------------------------

@api.get("/notifications")
async def notifications_list(user: dict = Depends(current_user), unread_only: bool = False, limit: int = 60):
    q: dict[str, Any] = {"user_id": user["id"]}
    if unread_only:
        q["read_at"] = None
    rows = await db.notifications.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    unread = await db.notifications.count_documents({"user_id": user["id"], "read_at": None})
    return {"notifications": rows, "unread": unread}


@api.get("/notifications/unread-count")
async def notifications_unread_count(user: dict = Depends(current_user)):
    n = await db.notifications.count_documents({"user_id": user["id"], "read_at": None})
    return {"unread": n}


@api.post("/notifications/{notif_id}/read")
async def notifications_read(notif_id: str, user: dict = Depends(current_user)):
    r = await db.notifications.update_one(
        {"id": notif_id, "user_id": user["id"]},
        {"$set": {"read_at": now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "notification not found")
    return {"ok": True}


@api.post("/notifications/read-all")
async def notifications_read_all(user: dict = Depends(current_user)):
    now = now_iso()
    r = await db.notifications.update_many(
        {"user_id": user["id"], "read_at": None},
        {"$set": {"read_at": now}},
    )
    return {"marked": r.modified_count}


@api.get("/notifications/settings")
async def notifications_settings_get(user: dict = Depends(current_user)):
    return {"settings": _get_notif_settings(user), "defaults": DEFAULT_NOTIFICATION_SETTINGS}


@api.put("/notifications/settings")
async def notifications_settings_put(body: NotificationSettingsBody, user: dict = Depends(current_user)):
    stored = user.get("notification_settings") or {}
    updates: dict[str, Any] = {}
    for k in ("check_ins", "habits", "workouts", "coach_messages", "weekly_videos", "roster", "programme_updates",
              "quiet_hours_start", "quiet_hours_end", "preferred_reminder_time", "travel_use_current_tz"):
        v = getattr(body, k)
        if v is not None:
            updates[k] = v
    if not updates:
        raise HTTPException(400, "no updates")
    merged = {**stored, **updates}
    top_level: dict[str, Any] = {"notification_settings": merged}
    # Mirror quiet hours to top-level for backwards compatibility with _tick_reminders
    if "quiet_hours_start" in updates: top_level["quiet_hours_start"] = updates["quiet_hours_start"]
    if "quiet_hours_end" in updates:   top_level["quiet_hours_end"]   = updates["quiet_hours_end"]
    await db.users.update_one({"id": user["id"]}, {"$set": top_level})
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})
    return {"settings": _get_notif_settings(fresh)}


@api.post("/notifications/permission")
async def notifications_permission(body: NotificationPermissionBody, user: dict = Depends(current_user)):
    if body.status not in ("granted", "denied", "not_requested"):
        raise HTTPException(400, "invalid status")
    stored = user.get("notification_settings") or {}
    stored["permission_status"] = body.status
    stored["permission_updated_at"] = now_iso()
    if body.platform:
        stored["last_platform"] = body.platform
    if body.device_info:
        stored["last_device_info"] = body.device_info
    await db.users.update_one({"id": user["id"]}, {"$set": {"notification_settings": stored}})
    return {"status": body.status}


# ---- Additional scheduled reminder ticks -----------------------------------

async def _tick_roster_and_workout_reminders() -> None:
    users = await db.users.find({"role": "client"}, {"_id": 0, "password_hash": 0}).to_list(2000)
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    for u in users:
        try:
            settings = _get_notif_settings(u)
            tz_name = u.get("current_time_zone") or u.get("home_time_zone") or "Europe/London"
            try: tz = ZoneInfo(tz_name)
            except Exception: continue
            local_now = now_utc.astimezone(tz)
            in_quiet = _in_quiet_hours(local_now, settings.get("quiet_hours_start", "21:00"), settings.get("quiet_hours_end", "07:00"))
            today = local_now.date().isoformat()

            # ---- Roster expiry ----
            if settings.get("roster", True) and not in_quiet:
                roster = await db.rosters.find_one({"user_id": u["id"], "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
                if roster:
                    last_dates = sorted([d.get("date") for d in roster.get("days", []) if d.get("date")])
                    if last_dates:
                        last = last_dates[-1]
                        try:
                            last_dt = _dt.date.fromisoformat(last)
                            delta = (last_dt - local_now.date()).days
                        except Exception:
                            delta = None
                        if delta is not None:
                            plan: Optional[tuple[str, str, str]] = None
                            if delta == 7:
                                plan = ("roster_low", "Roster running low",
                                        "Your roster is running low. Upload your next roster when you can.")
                            elif delta == 3:
                                plan = ("roster_due", "Roster nearly due",
                                        "Your next roster is nearly due.")
                            elif delta == 1:
                                plan = ("roster_due", "Upload your roster",
                                        "Upload your next roster so CrewFit can keep your training accurate.")
                            elif delta < 0:
                                plan = ("roster_expired", "Roster expired",
                                        "Your roster has expired. Upload your latest roster to keep your programme aligned.")
                            if plan and local_now.hour == 9 and local_now.minute < 10:
                                dedupe = f"{plan[0]}::{today}"
                                await enqueue_notification(u["id"], plan[0], plan[1], plan[2],
                                                            action_url="/roster-upload",
                                                            related_id=roster.get("id"),
                                                            dedupe_key=dedupe)

            # ---- Workout reminder ----
            if settings.get("workouts", True) and not in_quiet:
                preferred = settings.get("preferred_reminder_time") or "07:30"
                try:
                    hh, mm = int(preferred.split(":")[0]), int(preferred.split(":")[1])
                except Exception:
                    hh, mm = 7, 30
                if local_now.hour == hh and (mm <= local_now.minute < mm + 10):
                    todays_wk = await db.workouts.find_one({"user_id": u["id"], "date": today}, {"_id": 0, "id": 1, "completed": 1, "skipped": 1, "status": 1})
                    if todays_wk and not todays_wk.get("completed") and not todays_wk.get("skipped") and todays_wk.get("status") != "coach_review":
                        dedupe = f"workout_today::{today}"
                        await enqueue_notification(u["id"], "workout_today",
                                                    "CrewFit session ready",
                                                    "Your CrewFit session is ready for today.",
                                                    action_url=f"/workout/{todays_wk['id']}",
                                                    related_id=todays_wk["id"],
                                                    dedupe_key=dedupe)

            # ---- Missed check-in coach task on Tuesday morning ----
            # weekday: Monday=0, Tuesday=1
            if local_now.weekday() == 1 and local_now.hour == 9 and local_now.minute < 10:
                ws, _we = _current_week_bounds(u)
                # Compute *previous* week's start (checkins reference the just-completed week)
                try:
                    ws_prev = (_dt.date.fromisoformat(ws) - _dt.timedelta(days=7)).isoformat()
                except Exception:
                    ws_prev = ws
                already_task = await db.coach_tasks.find_one({"user_id": u["id"], "task_type": "missed_check_in",
                                                              "payload.week_start": ws_prev})
                completed = await db.check_ins.find_one({"user_id": u["id"], "week_start": ws_prev}, {"id": 1})
                if not completed and not already_task:
                    await _create_coach_task(u, "missed_check_in",
                                              f"Missed check-in · {u.get('name') or u.get('email')}",
                                              f"No check-in submitted for the week starting {ws_prev}.",
                                              priority="high",
                                              risk_level="medium",
                                              category="reviews",
                                              payload={"week_start": ws_prev})
        except Exception:
            logger.exception("_tick_roster_and_workout_reminders failed for a user")


_ORIGINAL_TICK_2 = _tick_reminders  # already extended to include habits above


async def _tick_reminders_full() -> None:
    await _ORIGINAL_TICK_2()
    await _tick_roster_and_workout_reminders()


_tick_reminders = _tick_reminders_full


# ---- Hook helpers used by other endpoints (message send, video sent, etc.) ---

async def notify_coach_message(from_user_id: str, to_user_id: str, text: str, source_message_id: Optional[str] = None) -> None:
    from_user = await db.users.find_one({"id": from_user_id}, {"_id": 0, "name": 1, "role": 1})
    if not from_user or from_user.get("role") != "coach":
        return
    await enqueue_notification(
        to_user_id, "coach_message",
        f"Message from {from_user.get('name', 'Louis')}",
        text[:120],
        action_url="/(client)/messages",
        related_id=source_message_id,
        dedupe_key=(f"coach_msg::{source_message_id}" if source_message_id else f"coach_msg::{now_iso()}"),
    )


async def notify_weekly_video_ready(user_id: str, video_id: Optional[str] = None) -> None:
    await enqueue_notification(
        user_id, "weekly_video_ready",
        "Weekly review from Louis",
        "Your weekly coaching review from Louis is ready.",
        action_url="/(client)/videos" if not video_id else f"/(client)/videos?v={video_id}",
        related_id=video_id,
        dedupe_key=f"weekly_video::{video_id or ''}",
    )


async def notify_programme_updated(user_id: str, meta: Optional[dict] = None) -> None:
    key = f"programme::{(meta or {}).get('week_start') or _dt.date.today().isoformat()}"
    await enqueue_notification(
        user_id, "programme_updated",
        "Programme updated",
        "Louis has reviewed your week and updated your plan.",
        action_url="/(client)/schedule",
        related_id=(meta or {}).get("workout_id"),
        dedupe_key=key,
    )


async def notify_coach_draft_ready(coach_id: str, client_name: str, draft_id: str) -> None:
    """In-app notification for the coach when Atlas produces a draft (V1: in-app only)."""
    await enqueue_notification(
        coach_id, "coach_draft_ready",
        f"Draft ready · {client_name}",
        "Atlas has drafted a reply. Review, edit and send.",
        action_url=f"/coach/draft/{draft_id}",
        related_id=draft_id,
        dedupe_key=f"draft::{draft_id}",
        respect_settings=False,   # coaches always see these
    )


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)
