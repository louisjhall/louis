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
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Header, Request, status
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

# Optional Sentry crash reporting. Silent no-op if SENTRY_DSN is not set,
# so dev + preview environments never phone home. Set SENTRY_ENABLED=0 to
# force-disable even when a DSN is present.
def _init_sentry() -> None:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn or os.environ.get("SENTRY_ENABLED", "1") == "0":
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        sentry_sdk.init(
            dsn=dsn,
            environment=os.environ.get("SENTRY_ENV", "beta"),
            traces_sample_rate=0.0,       # perf off for beta
            send_default_pii=False,       # no IPs, no cookies, no request bodies
            attach_stacktrace=True,
            request_bodies="never",
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                StarletteIntegration(transaction_style="endpoint"),
            ],
        )
    except Exception:
        # Never let Sentry init crash the app.
        pass

_init_sentry()

# Louis Hall reference photo used to generate exercise demo images with Nano Banana.
LOUIS_REF_IMAGE_PATH = ROOT_DIR / "assets" / "louis_ref.png"
_LOUIS_REF_B64_CACHE: Optional[str] = None

# Iter 103 — CrewFit brand logo. Passed as an additional reference image on
# every exercise generation so Nano Banana can copy the real logo onto the
# model's t-shirt/top instead of hallucinating a red blob. Applies to both
# male and female generations.
CREWFIT_LOGO_IMAGE_PATH = ROOT_DIR / "assets" / "crewfit_logo.png"
_CREWFIT_LOGO_B64_CACHE: Optional[str] = None


def _louis_ref_b64() -> str:
    """Cache Louis reference photo base64 so we don't re-encode ~1.8MB on every request."""
    global _LOUIS_REF_B64_CACHE
    if _LOUIS_REF_B64_CACHE is None:
        if not LOUIS_REF_IMAGE_PATH.exists():
            raise FileNotFoundError(str(LOUIS_REF_IMAGE_PATH))
        with open(LOUIS_REF_IMAGE_PATH, "rb") as f:
            _LOUIS_REF_B64_CACHE = base64.b64encode(f.read()).decode("utf-8")
    return _LOUIS_REF_B64_CACHE


def _crewfit_logo_b64() -> str:
    """Cache the CrewFit brand logo base64. Kept lazy so a missing file
    doesn't take the whole app down at import — the caller falls back to
    text-only prompt guidance if the logo is unavailable."""
    global _CREWFIT_LOGO_B64_CACHE
    if _CREWFIT_LOGO_B64_CACHE is None:
        if not CREWFIT_LOGO_IMAGE_PATH.exists():
            raise FileNotFoundError(str(CREWFIT_LOGO_IMAGE_PATH))
        with open(CREWFIT_LOGO_IMAGE_PATH, "rb") as f:
            _CREWFIT_LOGO_B64_CACHE = base64.b64encode(f.read()).decode("utf-8")
    return _CREWFIT_LOGO_B64_CACHE


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
    # Preview-mode claims flow through so handlers/audit can see them.
    if payload.get("preview"):
        u["_is_preview"] = True
        u["_preview_by"] = payload.get("preview_by")
        u["_preview_by_email"] = payload.get("preview_by_email")
    return u

def require_role(role: str):
    async def _dep(user: dict = Depends(current_user)) -> dict:
        if user["role"] != role:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"{role} role required")
        return user
    return _dep


def require_admin():
    """Admin-only guard. Coach role is accepted in dev/single-coach setup."""
    async def _dep(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in ("admin", "coach"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "admin role required")
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
    # Apple + Play require age gating. Privacy policy states 16+.
    # Field is required for new accounts; older seed rows are grandfathered.
    age_confirmed: bool = False
    # Iter 82 — richer signup payload (asked BEFORE DNA assessment).
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    age: Optional[int] = None
    sex: Optional[str] = None            # "male" | "female" | "other" | "prefer_not_to_say"
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    airline: Optional[str] = None
    job_title: Optional[str] = None      # "Cabin Crew" | "Purser" | "Captain" | "First Officer" | ...
    home_base: Optional[str] = None      # airport code e.g. "LHR"
    photo_base64: Optional[str] = None   # optional avatar
    photo_mime: Optional[str] = None

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
    # Basic Profile Setup — aviation context for the coaching system (Phase 1 support).
    job_title: Optional[str] = None       # e.g. "Captain", "First Officer", "Senior Cabin Crew", "Purser"
    route_focus: Optional[str] = None     # "long_haul" | "short_haul" | "mixed" | "charter" | "cargo"
    aircraft_type: Optional[str] = None   # optional, e.g. "A380", "777"
    main_goal_key: Optional[str] = None   # structured goal key mapping to GOAL_MATRIX
    # Iter 121b — V2 training-style preferences
    variety_preference: Optional[str] = None  # "low" | "moderate" | "high"
    cardio_preference: Optional[str] = None   # "walk" | "run" | "bike" | "rower" | "elliptical" | "swim" | "no_preference"

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
    # Phase 1 additions — Hotel System
    gym_type: Optional[str] = None          # "full_gym" | "cardio_only" | "basic" | "bodyweight_only" | "none" | "unknown"
    safe_outdoor_run: Optional[bool] = None  # explicit outdoor run safety
    verified_by_coach: Optional[bool] = None  # coach-verified flag (coach-only writes)


class HotelConfirmBody(BaseModel):
    """Client-side confirmation payload for a hotel on a workout day."""
    equipment: Optional[dict] = None         # override / patch equipment map
    gym_type: Optional[str] = None
    gym_available: Optional[bool] = None
    safe_outdoor_run: Optional[bool] = None
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
    # Phase 2 — Strict Equipment Matching (coach manual override)
    change_reason: Optional[str] = None
    needs_coach_review: Optional[bool] = None
    # Iter 102 — coach edited title; layover_naming pass must skip this workout.
    title_manually_edited_by_coach: Optional[bool] = None
    duration_min: Optional[int] = None
    focus: Optional[str] = None
    date: Optional[str] = None
    rationale: Optional[str] = None

class WorkoutCompleteBody(BaseModel):
    completed_exercises: list[dict] = []
    rpe: Optional[int] = None
    notes: Optional[str] = None
    # --- Iter 101 · Quick post-workout rating (low-friction) ---------------
    # rating ∈ {"smooth_flight","light_turbulence","heavy_turbulence","diverted"}
    rating: Optional[str] = None
    optional_note: Optional[str] = None
    pain_reported: Optional[bool] = None   # None = never asked, True/False = client answered
    pain_note: Optional[str] = None

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
    attachment_ids: Optional[list[str]] = None
    include_in_next_plan: Optional[bool] = False   # Iter 92 (Phase 2, Task 2.4)

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

# Iter 123 — Body for unregister-push. Removes THIS device's token from the
# user's push registration so notifications no longer target it after logout.
class UnregisterPushBody(BaseModel):
    user_id: str
    device_token: str
    platform: Optional[str] = None


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
    category: Optional[str] = None           # race | medical | aviation_work | sport_hobby | personal (inferred if omitted)
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
    payload = body.model_dump(exclude={"user_id"})
    # Infer category if omitted so cards use correct wording.
    try:
        from feature_event_categories import _categorise_by_name
        if not payload.get("category"):
            cat, _meta = _categorise_by_name(payload.get("event_name", ""), payload.get("event_type", ""))
            payload["category"] = cat
    except Exception:
        payload.setdefault("category", "race")
    doc = {
        "id": new_id(),
        "user_id": owner_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "is_active": True,
        **payload,
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
    try:
        from feature_event_categories import enrich_event
        ev = enrich_event(ev)
    except Exception:
        pass
    return ev


@api.get("/events/history")
async def event_history(user: dict = Depends(current_user)):
    rows = await db.events.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(50)
    try:
        from feature_event_categories import enrich_event
        for e in rows:
            e["phase_info"] = _event_phase(e.get("event_date", ""))
            enrich_event(e)
    except Exception:
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


# Iter181e · Fire-and-forget task tracking.
# Python's `asyncio.create_task` keeps only a WEAK reference to the task —
# under prod load / worker recycle the GC can silently drop it mid-run.
# `_spawn_bg` stores each task in the module-level set and removes it on
# completion. Use everywhere in server.py instead of bare `create_task`.
_BG_TASKS: set = set()

def _spawn_bg(coro):
    """Fire-and-forget wrapper — strongly references the task so the GC
    can't drop it mid-execution. Returns the created Task."""
    t = asyncio.create_task(coro)
    _BG_TASKS.add(t)
    t.add_done_callback(_BG_TASKS.discard)
    return t

def _merge_variants(w: dict, prev: Optional[dict]) -> dict:
    """Pick the best traffic-light variants when persisting a workout.
    Priority: LLM-returned (green shape valid) > previously stored > stub."""
    v = w.get("variants") if isinstance(w, dict) else None
    if isinstance(v, dict) and isinstance(v.get("green"), dict):
        return v
    if prev and isinstance(prev.get("variants"), dict) and isinstance(prev["variants"].get("green"), dict):
        return prev["variants"]
    return {"green": None, "amber": None, "red": None}


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


async def call_claude_tracked(user: dict, feature: str, system: str, prompt: str,
                               max_out: int = 8000, enforce: bool = True) -> str:
    """Rate-limited + telemetered variant of call_claude. Prefer this in new
    code — old sites can migrate incrementally."""
    import ai_limits
    MODEL = "claude-sonnet-4-5-20250929"
    async with ai_limits.ai_call(db, user, feature, model=MODEL,
                                  provider="anthropic", enforce=enforce) as call:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=new_id(),
            system_message=system,
        ).with_model("anthropic", "claude-sonnet-4-5-20250929")
        r = await chat.send_message(UserMessage(text=prompt))
        text = r if isinstance(r, str) else str(r)
        call.set_tokens(
            in_=ai_limits.estimate_tokens_from_text(system, prompt),
            out_=ai_limits.estimate_tokens_from_text(text),
        )
        return text

async def call_gemini_file(system: str, prompt: str, file_path: str, mime: str) -> str:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=new_id(),
        system_message=system,
    ).with_model("gemini", "gemini-2.5-flash")
    fc = FileContentWithMimeType(file_path=file_path, mime_type=mime)
    r = await chat.send_message(UserMessage(text=prompt, file_contents=[fc]))
    return r if isinstance(r, str) else str(r)


async def call_claude_file(system: str, prompt: str, file_path: str, mime: str) -> str:
    """Claude Sonnet 4.5 with vision — used as a diversified fallback when
    Gemini repeatedly fails to parse a roster. Different provider means
    different failure modes, which is exactly what bulletproof reliability
    needs (a Gemini rate-limit blip is uncorrelated with Anthropic capacity).
    """
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=new_id(),
        system_message=system,
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")
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
    if not body.age_confirmed:
        raise HTTPException(400, "You must confirm you are 16 or older to sign up.")
    if await db.users.find_one({"email": body.email.lower()}):
        raise HTTPException(400, "Email already registered")
    now = now_iso()
    # Iter 82 — SECURITY: self-service signup always creates a CLIENT.
    # Coach accounts can only be created by Louis (the head coach) via the
    # coach onboarding flow. Any client-supplied role != "client" is silently
    # ignored here.
    role: Role = "client"
    # Iter 82 — compose a canonical display name from first_name / last_name
    # when provided; fall back to whatever the client sent in `name`.
    display_name = body.name
    if body.first_name or body.last_name:
        display_name = f"{(body.first_name or '').strip()} {(body.last_name or '').strip()}".strip()
        if not display_name:
            display_name = body.name
    # Seed a partial profile so downstream (DNA assessment, roster, meal plan)
    # has these fields immediately without a second onboarding round-trip.
    seeded_profile: dict = {}
    for k, v in [
        ("age", body.age),
        ("sex", body.sex),
        ("height_cm", body.height_cm),
        ("weight_kg", body.weight_kg),
        ("airline", body.airline),
        ("job_title", body.job_title),
        ("home_base", body.home_base),
    ]:
        if v is not None and (not isinstance(v, str) or v.strip()):
            seeded_profile[k] = v.strip() if isinstance(v, str) else v
    # V2 is default for all new signups — enables the LIVE/DRAFT plan
    # boundary, P2-P12 pipelines, and the V2 client UI.
    try:
        from feature_v2_defaults import default_client_v2_flags
        seeded_profile["v2_flags"] = {
            **default_client_v2_flags(),
            "updated_at": now, "updated_by": "system_signup",
        }
    except Exception:
        logger.exception("signup — could not attach default V2 flags")
    u = {
        "id": new_id(), "email": body.email.lower(), "name": display_name,
        "first_name": (body.first_name or "").strip() or None,
        "last_name": (body.last_name or "").strip() or None,
        "role": role, "password_hash": hash_pw(body.password),
        "created_at": now, "onboarded": False, "coach_id": None,
        "profile": seeded_profile,
        "age_confirmed": True,
        "age_confirmed_at": now,
        "status": "active",
    }
    # Photo (optional) — stored as data-URL friendly base64 + mime
    if body.photo_base64:
        u["photo_base64"] = body.photo_base64
        u["photo_mime"] = body.photo_mime or "image/jpeg"
    # Auto-assign new clients to Louis (default admin) so messaging routes work.
    try:
        louis = await db.users.find_one({"email": "louis@crewfit.net"}, {"_id": 0, "id": 1, "name": 1})
        if louis and louis.get("id"):
            u["assigned_coach_id"] = louis["id"]
            u["assigned_coach_name"] = louis.get("name") or "Louis Hall"
    except Exception:
        pass
    await db.users.insert_one(u)
    token = make_token(u["id"], u["role"])
    clean_doc(u)
    u.pop("password_hash", None)
    return {"token": token, "user": u}


# ------------------------------------------------------------------
# Coach-side manual client creation
# Louis (or any coach) can hand-create a client from the coach dashboard
# for people who couldn't get through self-service signup. Age confirmation
# is vouched-for by the coach and recorded to the audit log.
# ------------------------------------------------------------------
class CoachCreateClientBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    name: Optional[str] = None
    age: Optional[int] = None
    sex: Optional[str] = None
    airline: Optional[str] = None
    job_title: Optional[str] = None
    home_base: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    notes: Optional[str] = None


@api.post("/coach/clients/create")
async def coach_create_client(body: CoachCreateClientBody, coach: dict = Depends(require_role("coach"))):
    email = body.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email already registered")

    display_name = (body.name or "").strip()
    if body.first_name or body.last_name:
        composed = f"{(body.first_name or '').strip()} {(body.last_name or '').strip()}".strip()
        display_name = composed or display_name
    if not display_name:
        display_name = email.split("@")[0]

    seeded_profile: dict = {}
    for k, v in [
        ("age", body.age),
        ("sex", body.sex),
        ("height_cm", body.height_cm),
        ("weight_kg", body.weight_kg),
        ("airline", body.airline),
        ("job_title", body.job_title),
        ("home_base", body.home_base),
    ]:
        if v is not None and (not isinstance(v, str) or v.strip()):
            seeded_profile[k] = v.strip() if isinstance(v, str) else v

    now = now_iso()
    # V2 is default for all clients — enables LIVE/DRAFT plan boundary +
    # P2-P12 pipelines + V2 client UI.
    try:
        from feature_v2_defaults import default_client_v2_flags
        seeded_profile["v2_flags"] = {
            **default_client_v2_flags(),
            "updated_at": now, "updated_by": coach.get("id") or "system_coach_create",
        }
    except Exception:
        logger.exception("coach_create_client — could not attach default V2 flags")
    u = {
        "id": new_id(),
        "email": email,
        "name": display_name,
        "first_name": (body.first_name or "").strip() or None,
        "last_name":  (body.last_name  or "").strip() or None,
        "role": "client",
        "password_hash": hash_pw(body.password),
        "created_at": now,
        "onboarded": False,
        "coach_id": None,
        "profile": seeded_profile,
        "age_confirmed": True,
        "age_confirmed_at": now,
        "age_confirmed_by_coach_id": coach.get("id"),
        "created_by_coach_id": coach.get("id"),
        "created_by_coach_name": coach.get("name") or coach.get("email"),
        "manual_create_notes": (body.notes or "").strip() or None,
        "status": "active",
        "assigned_coach_id": coach.get("id"),
        "assigned_coach_name": coach.get("name") or "Louis Hall",
    }

    await db.users.insert_one(u)

    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "actor_id": coach.get("id"),
            "actor_email": coach.get("email"),
            "action": "coach_created_client",
            "target_user_id": u["id"],
            "target_email": email,
            "created_at": now,
            "notes": body.notes or "",
        })
    except Exception:
        logger.exception("coach_create_client — audit_logs insert failed")

    clean_doc(u)
    u.pop("password_hash", None)
    return {"status": "created", "client": u}


@api.post("/auth/login")
async def login(body: LoginBody):
    # Iter 130c/d — duplicate-email safe login with V2-plan-aware ranking.
    # Production has historically ended up with more than one user row
    # sharing the same email (a stale signup + a coach-created row, etc.).
    # We fetch every row matching the email, keep only rows whose password
    # verifies, and then rank so the row with the *active V2 plan* wins.
    # This means when duplicates linger, the client lands on the profile
    # that actually has their coaching data — not the stale shell.
    email = body.email.lower().strip()
    candidates = await db.users.find({"email": email}).to_list(10)
    verified: list[dict] = []
    for cand in candidates:
        try:
            if cand.get("password_hash") and verify_pw(body.password, cand["password_hash"]):
                verified.append(cand)
        except Exception:
            continue
    if not verified:
        raise HTTPException(401, "Invalid credentials")

    # Rank verified rows so the one with the richest coaching footprint wins:
    #   1) has an active V2 plan_live_v2 row
    #   2) has a coach assigned
    #   3) has ANY V2 implementation
    #   4) has schedule_days (roster uploaded)
    #   5) most recent password_changed_at (proxy for "most recently touched")
    #   6) most recent created_at
    async def _score(u: dict) -> tuple:
        uid = u.get("id")
        has_active_v2 = await db.plan_live_v2.count_documents({"client_id": uid, "active": True}) > 0
        has_v2_impl = await db.plan_live_v2_implementations.count_documents({"client_id": uid}) > 0
        has_sched = await db.schedule_days.count_documents({"client_id": uid}) > 0
        return (
            1 if has_active_v2 else 0,
            1 if (u.get("coach_id") or u.get("assigned_coach_id")) else 0,
            1 if has_v2_impl else 0,
            1 if has_sched else 0,
            str(u.get("password_changed_at") or ""),
            str(u.get("created_at") or ""),
        )
    if len(verified) == 1:
        u = verified[0]
    else:
        scored = [(await _score(v), v) for v in verified]
        scored.sort(key=lambda x: x[0], reverse=True)
        u = scored[0][1]

    # Client lifecycle gate — paused / deletion_pending / deleted accounts cannot log in.
    lifecycle_status = str(u.get("status") or "active").lower()
    if lifecycle_status in ("paused", "deletion_pending", "deleted"):
        raise HTTPException(
            403,
            "This account is currently unavailable. Please contact your coach if you believe this is a mistake."
        )
    token = make_token(u["id"], u["role"])
    # Iter 160 — stamp last_login_at so the coach client list can show a
    # "LAST SEEN" column with a relative-time label. Best-effort: a failure
    # here must never block a valid login.
    try:
        now = now_iso()
        await db.users.update_one({"id": u["id"]}, {"$set": {"last_login_at": now}})
        u["last_login_at"] = now
    except Exception:
        logger.exception("failed to stamp last_login_at for user %s", u.get("id"))
    clean_doc(u)
    u.pop("password_hash", None)
    return {"token": token, "user": u}


@api.get("/auth/me")
async def me(user: dict = Depends(current_user)):
    return user


# ------------------------------------------------------------------
# Change password (self-service, from Profile)
# Requires the current password + new password (min 6 chars). Best-practice:
# rotates the token so any other logged-in sessions are silently invalidated.
# ------------------------------------------------------------------
class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6)


@api.post("/auth/change-password")
async def change_password(body: ChangePasswordBody, user: dict = Depends(current_user)):
    # Re-fetch to get password_hash (current_user usually strips it).
    u = await db.users.find_one({"id": user["id"]})
    if not u or not verify_pw(body.current_password, u.get("password_hash", "")):
        raise HTTPException(400, "Current password is incorrect")
    if body.current_password == body.new_password:
        raise HTTPException(400, "New password must be different from your current password")

    new_hash = hash_pw(body.new_password)
    await db.users.update_one({"id": user["id"]}, {"$set": {
        "password_hash": new_hash,
        "password_changed_at": now_iso(),
    }})

    # Re-issue token so client can keep going without a re-login.
    token = make_token(u["id"], u["role"])
    return {"status": "ok", "token": token}


# ----- Admin: force-reset a client's password ---------------------------
# Iter 128b. Coach-only. Lets Louis reset a client's password without
# needing the client's old one — same UX as the "Send temporary password"
# flow you'd expect from any coaching platform. Never exposes the hash.

class AdminResetPasswordBody(BaseModel):
    new_password: str = Field(min_length=6)


@api.post("/coach/clients/{client_id}/reset-password")
async def coach_reset_client_password(
    client_id: str,
    body: AdminResetPasswordBody,
    admin: dict = Depends(require_admin()),
):
    client = await db.users.find_one({"id": client_id})
    if not client:
        raise HTTPException(404, "client not found")
    if (client.get("role") or "").lower() not in ("client", "trial"):
        raise HTTPException(400, "target user is not a client")

    new_hash = hash_pw(body.new_password)
    # Iter 130c — Reset the password on EVERY row sharing this client's
    # email. Production has historically had duplicate user rows for the
    # same email (a stale signup + a coach-created row). If we only
    # update `client_id`, login (which looks up by email) may hit the
    # other row and still fail. Belt-and-suspenders: touch them all.
    email = (client.get("email") or "").strip().lower()
    now = now_iso()
    update_payload = {"$set": {
        "password_hash": new_hash,
        "password_changed_at": now,
        "password_reset_by": admin["id"],
    }}
    updated_ids: list[str] = [client_id]
    matched = 1
    await db.users.update_one({"id": client_id}, update_payload)
    if email:
        # Find every row that shares this email (excluding the one we
        # already updated) and update them too. Cap at 10 to avoid runaway.
        siblings = await db.users.find(
            {"email": email, "id": {"$ne": client_id}},
            {"_id": 0, "id": 1},
        ).to_list(10)
        for s in siblings:
            sid = s.get("id")
            if not sid:
                continue
            await db.users.update_one({"id": sid}, update_payload)
            updated_ids.append(sid)
            matched += 1
    # Best-effort audit log — never fatal.
    try:
        await db.auth_events.insert_one({
            "id": new_id(),
            "user_id": client_id,
            "actor_id": admin["id"],
            "kind": "coach_password_reset",
            "created_at": now,
            "matched_rows": matched,
            "updated_ids": updated_ids,
        })
    except Exception:
        pass
    return {
        "status": "ok",
        "client_id": client_id,
        "email": client.get("email"),
        "matched_rows": matched,
    }


# ----- Duplicate account cleanup (coach-only) ----------------------------
# Iter 130d. Production has accumulated duplicate user rows sharing the
# same email (stale signup + coach-created row). The coach needs a way to
# view both rows and hard-delete the one they don't want to keep — usually
# the one *without* the V2 plan/roster.

async def _client_row_summary(u: dict) -> dict:
    """Build a compact summary for a duplicate user row so the coach can
    tell them apart on screen: has V2 plan? has roster? last activity?
    Kept cheap — counts only, no full docs."""
    uid = u.get("id")
    # V2 plan indicators.
    plan_live = await db.plan_live_v2.count_documents({"client_id": uid, "active": True}) if uid else 0
    plan_impl = await db.plan_live_v2_implementations.count_documents({"client_id": uid}) if uid else 0
    plan_draft = await db.plan_drafts_v2.count_documents({"client_id": uid}) if uid else 0
    # Roster / schedule days.
    sched = await db.schedule_days.count_documents({"client_id": uid}) if uid else 0
    # Workouts / assessment.
    workouts_v2 = await db.plan_live_v2_implementations.count_documents({"client_id": uid, "is_active": True}) if uid else 0
    return {
        "id": uid,
        "name": u.get("name") or u.get("display_name"),
        "email": u.get("email"),
        "created_at": u.get("created_at"),
        "password_changed_at": u.get("password_changed_at"),
        "coach_id": u.get("coach_id") or u.get("assigned_coach_id"),
        "status": u.get("status") or "active",
        "has_v2_plan": plan_live > 0 or plan_impl > 0,
        "has_v2_draft": plan_draft > 0,
        "has_roster": sched > 0,
        "roster_days": sched,
        "plan_implementations": plan_impl,
        "workouts_v2_active": workouts_v2,
        # Simple "keep" recommendation: prefer the row with an active V2
        # plan; fall back to whichever has a coach + more roster data.
        "recommend_keep": plan_live > 0 or plan_impl > 0,
    }


@api.get("/coach/clients/{client_id}/duplicates")
async def coach_list_client_duplicates(
    client_id: str,
    admin: dict = Depends(require_admin()),
):
    """Return every user row sharing this client's email, with a compact
    summary so the coach can decide which to delete."""
    client = await db.users.find_one({"id": client_id})
    if not client:
        raise HTTPException(404, "client not found")
    email = (client.get("email") or "").strip().lower()
    if not email:
        return {"email": None, "rows": []}
    all_rows = await db.users.find({"email": email}).to_list(20)
    rows = [await _client_row_summary(u) for u in all_rows]
    # Sort: recommended-keep first, then newest.
    rows.sort(key=lambda r: (0 if r.get("recommend_keep") else 1, str(r.get("created_at") or "")), reverse=False)
    return {"email": email, "rows": rows, "total": len(rows)}


class DuplicateDeleteBody(BaseModel):
    target_id: str
    confirm_email: str


@api.post("/coach/clients/{client_id}/duplicates/delete")
async def coach_delete_client_duplicate(
    client_id: str,
    body: DuplicateDeleteBody,
    admin: dict = Depends(require_admin()),
):
    """Hard-delete a specific duplicate user row. Safety guards:
      * Refuses to delete if it would leave zero rows for that email.
      * Requires `confirm_email` to match the target row's email.
      * Refuses to delete a coach or admin row.
      * Refuses to delete a row that has an active V2 plan (would nuke
        the client's actual data — coach must archive that one instead).
    """
    # Locate the target row.
    target = await db.users.find_one({"id": body.target_id})
    if not target:
        raise HTTPException(404, "target row not found")
    target_email = (target.get("email") or "").strip().lower()
    confirm_email = (body.confirm_email or "").strip().lower()
    if not target_email or target_email != confirm_email:
        raise HTTPException(400, "confirm_email does not match target row's email")

    # Locate the anchor client to confirm they share an email.
    anchor = await db.users.find_one({"id": client_id})
    if not anchor:
        raise HTTPException(404, "anchor client not found")
    anchor_email = (anchor.get("email") or "").strip().lower()
    if anchor_email != target_email:
        raise HTTPException(400, "target row does not share this client's email")

    role = (target.get("role") or "").lower()
    if role not in ("client", "trial"):
        raise HTTPException(400, "can only delete client/trial rows via this endpoint")

    # Safety: refuse to delete the last remaining row for this email.
    remaining = await db.users.count_documents({"email": target_email, "id": {"$ne": body.target_id}})
    if remaining < 1:
        raise HTTPException(400, "cannot delete the only remaining row for this email")

    # Safety: refuse to delete a row that owns an active V2 plan.
    active_plan = await db.plan_live_v2.count_documents({"client_id": body.target_id, "active": True})
    if active_plan > 0:
        raise HTTPException(
            400,
            "target row has an active V2 plan — pick the other duplicate to delete, "
            "or archive this client normally instead of hard-delete."
        )

    # Hard delete the row + best-effort cleanup of orphan data owned by it.
    # We deliberately don't chase every collection; the goal is to unstick
    # login/UX and let the client-level flows recreate what they need.
    await db.users.delete_one({"id": body.target_id})
    for coll_name in (
        "plan_drafts_v2",
        "plan_live_v2_implementations",
        "schedule_days",
        "assessments",
    ):
        try:
            await db[coll_name].delete_many({"client_id": body.target_id})
        except Exception:
            logger.exception("duplicate-delete cleanup failed for %s", coll_name)

    # Audit trail.
    try:
        await db.auth_events.insert_one({
            "id": new_id(),
            "user_id": body.target_id,
            "actor_id": admin["id"],
            "kind": "duplicate_row_hard_deleted",
            "created_at": now_iso(),
            "email": target_email,
            "anchor_client_id": client_id,
        })
    except Exception:
        pass

    return {
        "status": "ok",
        "deleted_id": body.target_id,
        "email": target_email,
        "remaining_rows": remaining,
    }


# ----- Coach restriction management (Iter 130f) --------------------------
# Minimum reuse-based coach endpoint to write into the existing
# `db.restrictions` collection so Engine V2 picks up injury data on the
# next regeneration. No new schema — reuses source="coach" convention
# already handled by feature_v2_common.sync_restrictions_from_profile
# (that helper preserves non-profile source rows).

class CoachRestrictionBody(BaseModel):
    region: str
    severity: Optional[str] = "moderate"
    avoid_patterns: Optional[list[str]] = None
    raw_text: Optional[str] = None
    status: Optional[str] = "active"


@api.post("/coach/clients/{client_id}/restrictions")
async def coach_add_client_restriction(
    client_id: str,
    body: CoachRestrictionBody,
    admin: dict = Depends(require_admin()),
):
    """Insert a coach-authored restriction into `db.restrictions`.
    Read by feature_v2_engine_v2_kickoff._load_effective_context; applied
    to exercise-selection guards on next Engine V2 regeneration."""
    client = await db.users.find_one({"id": client_id})
    if not client:
        raise HTTPException(404, "client not found")
    doc = {
        "id": new_id(),
        "client_id": client_id,
        "region": (body.region or "").strip().lower() or "general",
        "severity": (body.severity or "moderate").strip().lower(),
        "avoid_patterns": [str(p).strip().lower() for p in (body.avoid_patterns or []) if str(p).strip()],
        "raw_text": (body.raw_text or "").strip(),
        "source": "coach",
        "status": (body.status or "active").strip().lower(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": admin["id"],
    }
    await db.restrictions.insert_one(doc)
    return {"status": "ok", "restriction_id": doc["id"]}


@api.get("/coach/clients/{client_id}/restrictions")
async def coach_list_client_restrictions(
    client_id: str,
    admin: dict = Depends(require_admin()),
):
    rows = await db.restrictions.find(
        {"client_id": client_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    return {"restrictions": rows, "count": len(rows)}


@api.post("/auth/onboarding")
async def onboarding(body: HomeEquipmentBody, user: dict = Depends(current_user)):
    # Merge instead of overwriting the profile object so re-running onboarding
    # never wipes fields that live outside HomeEquipmentBody (assessment DNA
    # snippets, coach-set notes, later features like aircraft_type additions).
    payload = body.model_dump(exclude_none=True)
    updates = {f"profile.{k}": v for k, v in payload.items()}
    updates["onboarded"] = True
    updates["profile.updated_at"] = now_iso()
    await db.users.update_one({"id": user["id"]}, {"$set": updates})
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
6. Aim for **12-16 quality questions max** (fewer if answers are clear). We're not making a form — every question must earn its place.
7. Adapt language & tone to their motivation style — supportive if they're returning from injury, sharper if they're driven / competitive.
8. Progress numbers are handled by the app — you can return any number for `progress`, it will be overridden. Focus purely on picking the best NEXT question.

SECTIONS YOU CAN COVER (only when relevant):
Who You Are · Your Aviation · Your Why · Your Goals · Your Events · Training History · Fitness Level · Lifestyle · Recovery · Nutrition Habits · Equipment · Time Available · Injuries · Motivation · Psychology · Coach Preferences · Wearables · Future Plans

QUESTION TYPES you can return:
- "single_select" with options: [{"id":"...", "label":"...", "icon":"..."}] — one choice. The `icon` MUST be an Ionicons v5 name (e.g. "airplane", "barbell", "moon", "flame", "leaf", "stats-chart"). Do NOT use emoji characters.
- "multi_select" with options — multiple choices
- "short_text" — one-line answer
- "long_text" — paragraph answer
- "number" with meta:{min, max, step, unit} — numeric
- "date" — ISO date
- "range" with meta:{min, max, step, unit, left_label, right_label}
- "event_builder" — client adds one or more upcoming events {name, event_type, date, priority}
- "equipment_picker" — multi-select equipment at a location; meta:{location:"home"|"hotel"|"commercial_gym"|"parents"}

REQUIRED QUESTIONS — YOU MUST COLLECT ALL OF THE FOLLOWING BEFORE YOU MAY SET
`should_end: true`. If ANY are missing from the answers so far, keep asking. Do
NOT emit `should_end:true` under any circumstances until every one of these is
present. This is a HARD contract — Louis needs these to plan a real programme.

  1. **biological_sex** (id: `biological_sex`) — single_select {male, female, intersex_prefer_not}. Skip only if already provided at signup. NEVER skippable via allow_skip. Used to derive pronouns automatically (male→he/him, female→she/her, intersex_prefer_not→they/them). Do NOT ask a separate pronouns question.
  2. **aviation_role** (id: `crew_role`) — single_select from Pilot / Cabin Crew / Ground Ops / Corporate Aviation / Other. Skip only if already at signup.
  3. **flying_type** (id: `flying_type`) — single_select from {short_haul, mixed, long_haul, charter, cargo, ground_only}. MUST be asked BEFORE any layover-related question. If the answer is `short_haul` or `ground_only`, DO NOT ask questions 8 or 10 (they are auto-answered).
  4. **primary_goal** (id: `primary_goal`) — single_select from the goal catalogue below. This is the ONE main thing they care about most.
  5. **secondary_goals** (id: `secondary_goals`) — multi_select, 0-3 allowed, from the goal catalogue below. Optional in count but MUST be asked.
  6. **training_days_per_week** (id: `training_days`) — integer 1-7. Ask "How many days per week can you realistically train?"
  7. **time_home_min** (id: `time_home`) — single_select from [15, 30, 45, 60, 75, 90] min. "How much time do you have per session when you're at home?"
  8. **time_layover_min** (id: `time_layover`) — single_select from [0, 15, 30, 45, 60] min. **SKIP** if flying_type ∈ {short_haul, ground_only}.
  9. **equipment_home** (id: `equipment_home`) — equipment_picker with meta:{location:"home"}, MULTI-SELECT ≥1 required. Options MUST include "bodyweight_only" as a valid explicit pick. NEVER `allow_skip: true`.
  10. **hotel_gym_reliability** (id: `hotel_gyms`) — single_select from [always, often, sometimes, rare, never]. **SKIP** if flying_type ∈ {short_haul, ground_only}.
  11. **injuries** (id: `injuries`) — long_text with an explicit "No injuries currently" pick alongside. NEVER `allow_skip: true`. If they type nothing but tick "No injuries currently", that's valid.
  12. **no_go_movements** (id: `no_go_movements`) — multi_select from [none, running, jumping, overhead_pressing, deep_squatting, deadlifts, heavy_lifting]. "No" (none) is a valid explicit pick.

Goal catalogue (used by both primary_goal and secondary_goals):
[Lose body fat, Build muscle, General fitness, Improve health, Improve confidence, Ironman, 70.3, Sprint Triathlon, Olympic Triathlon, Marathon, Half Marathon, HYROX, 5K, 10K, Improve mobility, Reduce pain, Return from injury, Reduce jet lag, Improve sleep, Pass airline medical, Maintain fitness, Other]

You may ask up to 4 additional context questions AFTER the 11 above (e.g. sectors,
long/short haul, target event date if applicable, wearables). NEVER ask context
questions before the 11 are complete. NEVER emit `should_end:true` until all 11
are present in the answers.

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
    "options": [{"id":"long_haul","label":"Long haul","icon":"airplane"}],  // Ionicons name only — NEVER emoji characters
    "meta": {"min":0,"max":100,"step":1,"unit":"min"},                 // when applicable
    "allow_skip": true|false
  },
  "should_end": false,
  "progress": 45,
  "section_context": "Building your flying profile..."
}

When you have enough context (usually after 10-14 quality answers), respond with:
{ "should_end": true, "progress": 100, "section_context": "Building your Coaching DNA..." }

Do NOT return next_question when should_end is true. Return ONLY valid JSON."""


DNA_SYSTEM = """You are Atlas — the CrewFit Intelligence™ engine built by Louis Hall.

Given a completed assessment transcript, synthesise the client's permanent **Coaching DNA** — the coaching mental model Louis will use to guide every AI decision going forward. Everything you produce operates within Louis' coaching philosophy.

RULES:
- Be specific and personal. Reference their actual answers.
- Never generic. Every field should feel like it was written FOR THIS PERSON.
- **PRONOUNS**: derive from the client's `biological_sex` answer — male → he/him, female → she/her, intersex_prefer_not → they/them. If no sex was recorded, use they/them. NEVER default to she/her or he/him based on job or role. NEVER assume gender from job (cabin crew ≠ female, pilot ≠ male).
- If information is missing, say "Unknown — will learn over time".
- Assign a realistic `ai_confidence_score` (30-95). New clients rarely hit 90+.
- `recommended_weekly_training` should be a day-agnostic outline anchored to a session count, NEVER weekday names. Crew rosters change every week, so fixed days (Mon/Wed/Fri) never apply. Use the form: `<N> sessions/week: Training Day 1 <focus>, Training Day 2 <focus>, ...`. Example: "4 sessions/week: Training Day 1 strength, Training Day 2 Z2 run, Training Day 3 mobility, Training Day 4 long run — dates assigned when the roster is uploaded."
- The `summary` field should be written in Atlas voice ("I've analysed...", "I've identified..."). Never claim to coach — reference Louis' methodology.

RESPOND WITH STRICT JSON only:
{
  "biological_sex": "male|female|intersex_prefer_not|unknown",
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
    """Feed the current transcript to Claude and get the next question / end signal.

    Iter 82 fixes:
      * `progress` is now DETERMINISTIC (monotonic, based on answer count) — the
        LLM's own progress number is ignored because it flaps back and forth.
      * Hard cap: after MAX_ASSESSMENT_QUESTIONS answers we force `should_end`
        regardless of what the LLM says, and never re-ask a prefilled question.

    Iter 94e fixes (batched user complaints):
      * The MANDATORY onboarding questions (biological_sex, role, flying_type,
        primary_goal, training_days, time_home, time_layover, equipment_home,
        hotel_gyms, injuries, no_go_movements) are now served DETERMINISTICALLY
        from `_assessment_fallback_next` — no LLM round-trip. This removes the
        multi-second pause between each of the first ~11 questions.
      * `flying_type` is now asked as question #3, BEFORE any layover-related
        question so the flow doesn't presume everyone does layovers.
      * If `flying_type` is short_haul / ground_only, we AUTO-INJECT answers
        for `time_layover=0` and `hotel_gyms=never` and DO NOT ask them.
      * No question is emitted twice — the fallback list is now deduplicated.
    """
    # Hard bounds. Anything above these creates fatigue and dropout.
    TARGET_QUESTIONS = 14   # what the % is scaled to (80% at 11, 100% at end)
    MAX_QUESTIONS    = 18   # hard cap — after this we END even if LLM disagrees

    transcript = []
    prefilled_ids: list[str] = []
    for a in (assessment.get("answers") or []):
        transcript.append({
            "q_id": a.get("question_id"),
            "section": a.get("section"),
            "question": a.get("question_text"),
            "answer": a.get("answer"),
        })
        if a.get("prefilled_from"):
            prefilled_ids.append(str(a.get("question_id")))
    answered_ids = {t["q_id"] for t in transcript if t.get("q_id")}
    n_answered = len(transcript)

    # Deterministic monotonic progress — never goes backwards.
    deterministic_progress = min(99, int(round(100 * n_answered / TARGET_QUESTIONS)))

    # HARD CAP — end the assessment ourselves
    if n_answered >= MAX_QUESTIONS:
        return {
            "should_end": True,
            "progress": 100,
            "section_context": "Building your Coaching DNA...",
        }

    # Iter 94e — Fast path: if the NEXT missing question is one of our
    # deterministic mandatory questions, serve it INSTANTLY without an LLM call.
    # This kills the pause between questions during the onboarding sequence.
    fast = _assessment_fallback_next(assessment)
    fast_q = fast.get("next_question") if isinstance(fast, dict) else None
    if fast_q and str(fast_q.get("id")) in _MANDATORY_DETERMINISTIC_IDS:
        if fast_q.get("id") not in answered_ids:
            fast["progress"] = deterministic_progress
            return fast

    # Iter 94f — STRICT LLM GATE. If ANY mandatory essential is still
    # unanswered, we NEVER hand control to the LLM. Instead, serve whatever
    # `_assessment_fallback_next` returned (it may be a non-mandatory q like
    # `why` that sits between mandatory ones — that's fine, it's still
    # deterministic). The LLM only gets to run bonus questions AFTER every
    # mandatory ID is present. Without this, the LLM would hallucinate a
    # rephrase of a mandatory question (e.g. `weekly_frequency` instead of
    # `training_days`) and the fast path would ask the real mandatory q
    # next round → user sees the topic twice.
    still_missing_mandatory = set(_MANDATORY_DETERMINISTIC_IDS) - answered_ids
    # Drop layover-only mandatory IDs if the client explicitly doesn't do layovers.
    _answered_map = {a.get("question_id"): a.get("answer") for a in (assessment.get("answers") or [])}
    _ft = str(_answered_map.get("flying_type") or "").lower()
    if _ft in _NON_LAYOVER_FLYING_TYPES:
        still_missing_mandatory -= {"time_layover", "hotel_gyms"}
    if still_missing_mandatory:
        # Serve fb.next deterministically. If fb has nothing → end.
        if fast_q and fast_q.get("id") not in answered_ids:
            fast["progress"] = deterministic_progress
            return fast
        return {"should_end": True, "progress": 100,
                "section_context": "Building your Coaching DNA..."}

    prefill_note = ""
    if prefilled_ids:
        prefill_note = (
            f"\n\nIMPORTANT: The client answered these question_ids DURING SIGNUP: "
            f"{prefilled_ids}. Do NOT re-ask them under any circumstance. "
            "Skip straight to the next unanswered question in your flow.\n"
        )
    # Iter 94e2 — HARD guard against LLM re-asking any mandatory question that
    # the deterministic fast path already served. This is the fix for the
    # "asked flying_type twice" complaint. We tell the LLM the full list of
    # question_ids already answered and instruct it explicitly not to ask
    # any of them again — even in slightly reworded form.
    if answered_ids:
        prefill_note += (
            f"\nALREADY ANSWERED question_ids (do NOT re-ask any of these, "
            f"even rephrased): {sorted(answered_ids)}. If your next question "
            "would land on any of these ids, pick the next unanswered topic instead.\n"
        )
    prompt = (
        f"CLIENT NAME: {assessment.get('client_name') or 'the client'}\n"
        f"ASSESSMENT SO FAR ({n_answered} answers out of a target of {TARGET_QUESTIONS}):\n"
        f"{json.dumps(transcript)[:8500]}\n"
        f"{prefill_note}\n"
        "Return the next question JSON now. If enough context, set should_end true."
    )
    try:
        raw = await call_claude(ASSESSMENT_INTERVIEWER_SYSTEM, prompt, max_out=1800)
        parsed = parse_json_from_text(raw)
        if not isinstance(parsed, dict):
            raise ValueError("bad shape")
    except Exception:
        logger.exception("assessment_next AI failed")
        parsed = _assessment_fallback_next(assessment)

    # Sanitise: LLM sometimes re-asks a prefilled/answered question — swap to
    # deterministic fallback in that case so we always move forward.
    # Iter 94f — expanded from a naive id-match to a full SEMANTIC-collision
    # check so rephrased duplicates ("flying_pattern" for `flying_type`,
    # "main_goal" for `primary_goal`) also get caught.
    q = parsed.get("next_question") if isinstance(parsed, dict) else None
    if q and _semantic_collision(q, answered_ids):
        logger.warning(
            "assessment_next: rejecting LLM question '%s' — collides with "
            "already-answered topic (answered_ids=%s)",
            q.get("id"), sorted(answered_ids),
        )
        parsed = _assessment_fallback_next(assessment)
        # If the fallback ALSO collides (shouldn't, but belt-and-braces),
        # force end so we never get stuck in a loop.
        q2 = parsed.get("next_question") if isinstance(parsed, dict) else None
        if q2 and _semantic_collision(q2, answered_ids):
            logger.error(
                "assessment_next: fallback ALSO collided (id=%s). Forcing end.",
                q2.get("id"),
            )
            parsed = {"should_end": True, "progress": 100,
                      "section_context": "Building your Coaching DNA..."}

    # OVERRIDE progress with the deterministic value so the UI can't flap.
    if isinstance(parsed, dict):
        if parsed.get("should_end"):
            parsed["progress"] = 100
        else:
            parsed["progress"] = deterministic_progress
    return parsed


# Iter 94e — the deterministic-fast-path set. Any question whose id is in this
# set will be served WITHOUT an LLM round-trip. Order in _assessment_fallback_next
# controls the sequence.
_MANDATORY_DETERMINISTIC_IDS: frozenset[str] = frozenset({
    "biological_sex", "role", "primary_goal",
    "flying_type",  # NEW — asked BEFORE any layover-related question
    "training_days", "time_home", "time_layover",
    "equipment_home", "hotel_gyms",
    "injuries", "no_go_movements",
})

_NON_LAYOVER_FLYING_TYPES: frozenset[str] = frozenset({"short_haul", "ground_only"})

# Iter 94f — SEMANTIC-COLLISION guard. For any answered question_id, the LLM
# must NEVER emit a NEW question whose id (or text) hits any of these
# keywords. If it does, we reject and fall back to deterministic. This is
# the fix for "the LLM asked me about my goals / flights again".
#
# Rule: substring match, case-insensitive. Add generously — false positives
# just push us to fallback (safe); false negatives cause duplicates (unsafe).
_TOPIC_KEYWORDS: dict[str, set[str]] = {
    "biological_sex":   {"biological_sex", "sex_at_birth", "gender", "sex"},
    "role":             {"aviation_role", "crew_role", "your_role", "role_in_aviation"},
    "flying_type":      {"flying_type", "flying_pattern", "flight_type", "haul_type",
                         "haul_mix", "route_focus", "route_type", "sector_mix",
                         "flying_style", "type_of_flying", "kind_of_flying"},
    "primary_goal":     {"primary_goal", "main_goal", "top_goal", "biggest_goal",
                         "your_goal", "training_goal", "fitness_goal", "goal_priority"},
    "secondary_goals":  {"secondary_goal", "other_goal", "additional_goal"},
    "why":              {"why_it_matters", "your_why", "reason_why"},
    "events":           {"upcoming_event", "event_builder", "event_timeline",
                         "race_calendar", "target_event"},
    "experience":       {"training_experience", "experience_level",
                         "lifting_experience", "years_training"},
    "training_days":    {"training_days", "days_per_week", "sessions_per_week",
                         "weekly_frequency", "weekly_sessions", "weekly_training_days"},
    "time_home":        {"time_home", "home_time", "session_length_home",
                         "home_session_length", "home_minutes"},
    "time_layover":     {"time_layover", "layover_time", "layover_length",
                         "layover_minutes", "layover_duration",
                         "session_length_layover"},
    "equipment_home":   {"equipment_home", "home_equipment", "home_gear",
                         "home_setup", "gym_setup", "training_equipment"},
    "hotel_gyms":       {"hotel_gyms", "hotel_gym", "hotel_gym_reliability",
                         "gym_in_hotel"},
    "injuries":         {"injuries", "current_injury", "injury_history",
                         "pain_history", "recent_injury"},
    "no_go_movements":  {"no_go_movement", "movements_to_avoid",
                         "avoid_movement", "avoid_pattern", "forbidden_movement",
                         "restricted_movement"},
    "sleep_quality":    {"sleep_quality", "sleep_score"},
    "stress":           {"stress_level"},
    "family":           {"family_commitments"},
    "nutrition_habits": {"nutrition_habits", "eating_habits", "food_habits"},
    "diet_style":       {"diet_style", "diet_type", "dietary_preference"},
    "motivation":       {"motivation_style", "what_motivates"},
    "blocker":          {"training_blocker", "what_stops_you", "obstacle_to_training"},
    "coaching_style_pref": {"coaching_style", "coach_style_pref", "coach_preference"},
}


def _semantic_collision(candidate_q: dict, answered_ids: set[str]) -> bool:
    """Return True iff a candidate LLM question re-asks an already-answered topic.

    Checks the candidate's `id` AND `text` against `_TOPIC_KEYWORDS` for every
    already-answered id. Substring match, case-insensitive. Cheap.
    """
    if not candidate_q or not isinstance(candidate_q, dict):
        return False
    cid = str(candidate_q.get("id") or "").lower().strip()
    ctext = str(candidate_q.get("text") or "").lower().strip()
    if cid in answered_ids:
        return True
    for aid in answered_ids:
        kws = _TOPIC_KEYWORDS.get(aid, set())
        for kw in kws:
            kw_l = kw.lower()
            if kw_l and (kw_l in cid or kw_l in ctext):
                return True
    return False


def _assessment_fallback_next(assessment: dict) -> dict:
    """Deterministic fallback flow if AI fails — always keeps the interview moving.

    Iter 94e — the flow is now:
      1. biological_sex
      2. role (aviation role)
      3. flying_type (NEW — asked BEFORE any layover question)
      4. primary_goal
      5. why
      6. events
      7. experience
      8. training_days
      9. time_home  (SINGLE entry — the range-slider duplicate was removed)
      10. time_layover  (SKIPPED if flying_type ∈ {short_haul, ground_only})
      11. equipment_home
      12. hotel_gyms  (SKIPPED if flying_type ∈ {short_haul, ground_only})
      13. injuries
      14. no_go_movements
      (then optional context: sleep_quality, stress, family, nutrition_habits,
       diet_style, motivation, blocker, coaching_style_pref)
    """
    answered_map = {a.get("question_id"): a.get("answer") for a in (assessment.get("answers") or [])}
    answered = set(answered_map.keys())
    flying_type_answer = str(answered_map.get("flying_type") or "").lower()
    non_layover = flying_type_answer in _NON_LAYOVER_FLYING_TYPES

    fb: list[dict] = [
        {"id": "biological_sex", "section": "About You",
         "text": "What is your biological sex? (used for training load, protein targets and recovery science — kept private)",
         "type": "single_select", "options": [
             {"id": "male", "label": "Male", "icon": "male"},
             {"id": "female", "label": "Female", "icon": "female"},
             {"id": "intersex_prefer_not", "label": "Intersex / Prefer not to say", "icon": "person"},
         ], "allow_skip": False},
        {"id": "role", "section": "Your Aviation", "text": "What is your role in aviation?",
         "type": "single_select", "options": [
             {"id": "pilot", "label": "Pilot", "icon": "airplane"},
             {"id": "cabin_crew", "label": "Cabin Crew", "icon": "briefcase"},
             {"id": "ground_ops", "label": "Ground Ops", "icon": "cube"},
             {"id": "corporate", "label": "Corporate Aviation", "icon": "business"},
             {"id": "other", "label": "Other", "icon": "globe"},
         ], "allow_skip": False},
        # Iter 94e — flying pattern asked BEFORE any layover-related question.
        {"id": "flying_type", "section": "Your Aviation",
         "text": "What kind of flying do you mainly do?",
         "help_text": "This tells us whether to plan hotel sessions or focus entirely on home training.",
         "type": "single_select", "options": [
             {"id": "short_haul",  "label": "Short-haul / turnarounds only",
              "sub": "Home every night — no layovers.", "icon": "return-up-back"},
             {"id": "mixed",       "label": "Mixed",
              "sub": "Some turnarounds, some layovers.", "icon": "swap-horizontal"},
             {"id": "long_haul",   "label": "Long-haul",
              "sub": "Mostly overnight layovers away.", "icon": "airplane"},
             {"id": "charter",     "label": "Charter / ad-hoc",
              "sub": "Irregular pattern — layovers possible.", "icon": "shuffle"},
             {"id": "cargo",       "label": "Cargo",
              "sub": "Freight ops — mostly overnight.", "icon": "cube"},
             {"id": "ground_only", "label": "Ground / office based",
              "sub": "No flying. Fixed schedule.", "icon": "business"},
         ], "allow_skip": False},
        {"id": "primary_goal", "section": "Your Goals",
         "text": "What are you trying to achieve? Pick everything that matters.",
         "type": "multi_select", "options": [
             {"id": "lose_fat", "label": "Lose body fat", "icon": "trending-down"},
             {"id": "build_muscle", "label": "Build muscle", "icon": "barbell"},
             {"id": "general_fitness", "label": "General fitness", "icon": "pulse"},
             {"id": "marathon", "label": "Marathon", "icon": "flag"},
             {"id": "half_marathon", "label": "Half Marathon", "icon": "walk"},
             {"id": "ironman", "label": "Ironman", "icon": "trophy"},
             {"id": "seventy_three", "label": "70.3", "icon": "medal"},
             {"id": "hyrox", "label": "HYROX", "icon": "flame"},
             {"id": "sprint_tri", "label": "Sprint Triathlon", "icon": "speedometer"},
             {"id": "olympic_tri", "label": "Olympic Triathlon", "icon": "medal-outline"},
             {"id": "five_k", "label": "5K", "icon": "footsteps"},
             {"id": "ten_k", "label": "10K", "icon": "footsteps-outline"},
             {"id": "mobility", "label": "Improve mobility", "icon": "body"},
             {"id": "reduce_pain", "label": "Reduce pain", "icon": "bandage"},
             {"id": "return_injury", "label": "Return from injury", "icon": "medkit"},
             {"id": "reduce_jetlag", "label": "Reduce jet lag", "icon": "moon"},
             {"id": "improve_sleep", "label": "Improve sleep", "icon": "bed"},
             {"id": "airline_medical", "label": "Pass airline medical", "icon": "medical"},
             {"id": "maintain", "label": "Maintain fitness", "icon": "repeat"},
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
             {"id": "beginner", "label": "Beginner", "icon": "leaf"},
             {"id": "intermediate", "label": "Intermediate", "icon": "star-half"},
             {"id": "advanced", "label": "Advanced", "icon": "star"},
         ]},
        {"id": "training_days", "section": "Time Available", "text": "How many days a week can you train?",
         "type": "single_select", "options": [
             {"id": "1", "label": "1 day",  "icon": "calendar-outline"},
             {"id": "2", "label": "2 days", "icon": "calendar-outline"},
             {"id": "3", "label": "3 days", "icon": "calendar-outline"},
             {"id": "4", "label": "4 days", "icon": "calendar-outline"},
             {"id": "5", "label": "5 days", "icon": "calendar-outline"},
             {"id": "6", "label": "6 days", "icon": "calendar-outline"},
             {"id": "7", "label": "7 days", "icon": "calendar-outline"},
         ]},
        # Iter 84 (Task 1.2) — Time-per-session gates. Required so the plan
        # builder can size sessions accurately instead of silently defaulting.
        # Iter 94e — deduplicated: was appearing twice (range + single_select).
        {"id": "time_home", "section": "Time Available", "text": "How much time do you have per session at home?",
         "type": "single_select", "options": [
             {"id": "15", "label": "15 min", "icon": "time-outline"},
             {"id": "30", "label": "30 min", "icon": "time-outline"},
             {"id": "45", "label": "45 min", "icon": "time-outline"},
             {"id": "60", "label": "60 min", "icon": "time-outline"},
             {"id": "75", "label": "75 min", "icon": "time-outline"},
             {"id": "90", "label": "90 min", "icon": "time-outline"},
         ]},
        # Iter 94e — SKIPPED entirely if flying_type is non-layover. Also
        # deduplicated (was appearing as both range and single_select before).
        {"id": "time_layover", "section": "Time Available",
         "text": "How much time do you typically have on a layover?",
         "type": "single_select", "options": [
             {"id": "0",  "label": "I don't train on layovers", "icon": "close-circle"},
             {"id": "15", "label": "15 min", "icon": "time-outline"},
             {"id": "30", "label": "30 min", "icon": "time-outline"},
             {"id": "45", "label": "45 min", "icon": "time-outline"},
             {"id": "60", "label": "60 min", "icon": "time-outline"},
         ],
         "_skip_if_non_layover": True},
        # Iter 84 (Task 1.2) — Equipment is now HARD required (no allow_skip).
        # "bodyweight_only" is a valid explicit pick.
        {"id": "equipment_home", "section": "Equipment", "text": "What equipment do you have at home?",
         "type": "equipment_picker", "meta": {"location": "home"}},
        {"id": "hotel_gyms", "section": "Your Aviation", "text": "Do you usually find gyms in your hotels?",
         "type": "single_select", "options": [
             {"id": "always", "label": "Always", "icon": "checkmark-done"},
             {"id": "often", "label": "Often", "icon": "checkmark-circle"},
             {"id": "sometimes", "label": "Sometimes", "icon": "help-circle"},
             {"id": "rare", "label": "Rarely", "icon": "remove-circle"},
             {"id": "never", "label": "Never", "icon": "close-circle"},
         ],
         "_skip_if_non_layover": True},
        # Iter 84 (Task 1.2) — Injuries required, but "No injuries currently"
        # is an explicit valid pick so users don't need to type "none".
        {"id": "injuries", "section": "Injuries", "text": "Any current injuries, or things you must avoid?",
         "type": "long_text",
         "meta": {"explicit_none_label": "No injuries currently"}},
        {"id": "no_go_movements", "section": "Injuries", "text": "Any movement patterns to avoid entirely?",
         "type": "multi_select", "options": [
             {"id": "none", "label": "None — I can do all movements", "icon": "checkmark-done"},
             {"id": "running", "label": "Running / impact", "icon": "walk"},
             {"id": "jumping", "label": "Jumping", "icon": "trending-up"},
             {"id": "overhead_pressing", "label": "Overhead pressing", "icon": "arrow-up"},
             {"id": "deep_squatting", "label": "Deep squatting", "icon": "arrow-down"},
             {"id": "deadlifts", "label": "Deadlifts", "icon": "barbell"},
             {"id": "heavy_lifting", "label": "Heavy lifting", "icon": "barbell-outline"},
         ]},
        {"id": "sleep_quality", "section": "Recovery", "text": "On average, how would you rate your sleep?",
         "type": "range", "meta": {"min": 1, "max": 10, "step": 1, "unit": "/10", "left_label": "Poor", "right_label": "Great"}},
        {"id": "stress", "section": "Lifestyle", "text": "How would you rate your daily stress?",
         "type": "range", "meta": {"min": 1, "max": 10, "step": 1, "unit": "/10", "left_label": "Low", "right_label": "High"}},
        {"id": "family", "section": "Lifestyle", "text": "Family commitments?",
         "type": "multi_select", "options": [
             {"id": "kids_young", "label": "Young children", "icon": "happy"},
             {"id": "kids_school", "label": "School-age kids", "icon": "school"},
             {"id": "partner", "label": "Partner", "icon": "heart"},
             {"id": "pets", "label": "Pets", "icon": "paw"},
             {"id": "elders", "label": "Caring for elders", "icon": "people-circle"},
             {"id": "none", "label": "None", "icon": "person"},
         ], "allow_skip": True},
        {"id": "nutrition_habits", "section": "Nutrition Habits", "text": "How do you usually eat on trips?",
         "type": "multi_select", "options": [
             {"id": "airport_food", "label": "Airport food", "icon": "restaurant"},
             {"id": "crew_meals", "label": "Crew meals", "icon": "cafe"},
             {"id": "hotel_restaurants", "label": "Hotel restaurants", "icon": "wine"},
             {"id": "meal_prep", "label": "Meal prep from home", "icon": "nutrition"},
             {"id": "supermarket", "label": "Supermarket / snacks", "icon": "cart"},
             {"id": "delivery", "label": "Food delivery apps", "icon": "bag"},
         ], "allow_skip": True},
        {"id": "diet_style", "section": "Nutrition Habits", "text": "Any dietary preferences?",
         "type": "multi_select", "options": [
             {"id": "none", "label": "No restrictions", "icon": "restaurant-outline"},
             {"id": "vegetarian", "label": "Vegetarian", "icon": "leaf"},
             {"id": "vegan", "label": "Vegan", "icon": "leaf-outline"},
             {"id": "halal", "label": "Halal", "icon": "moon-outline"},
             {"id": "kosher", "label": "Kosher", "icon": "star-outline"},
             {"id": "gluten_free", "label": "Gluten free", "icon": "flower"},
             {"id": "dairy_free", "label": "Dairy free", "icon": "close-circle-outline"},
         ], "allow_skip": True},
        {"id": "motivation", "section": "Motivation", "text": "What keeps you motivated?",
         "type": "multi_select", "options": [
             {"id": "progress", "label": "Progress", "icon": "trending-up"},
             {"id": "competition", "label": "Competition", "icon": "trophy"},
             {"id": "routine", "label": "Routine", "icon": "repeat"},
             {"id": "coach", "label": "Coach accountability", "icon": "person-circle"},
             {"id": "aesthetics", "label": "Looking better", "icon": "eye"},
             {"id": "health", "label": "Feeling healthier", "icon": "heart"},
             {"id": "events", "label": "Events", "icon": "flag"},
             {"id": "data", "label": "Data", "icon": "stats-chart"},
         ]},
        {"id": "blocker", "section": "Psychology", "text": "What usually stops you training?",
         "type": "multi_select", "options": [
             {"id": "jetlag", "label": "Jet lag", "icon": "airplane"},
             {"id": "family", "label": "Family", "icon": "people"},
             {"id": "pain", "label": "Pain", "icon": "bandage"},
             {"id": "time", "label": "Time", "icon": "time"},
             {"id": "motivation", "label": "Motivation", "icon": "sad"},
             {"id": "sleep", "label": "Sleep", "icon": "moon"},
             {"id": "travel", "label": "Travel", "icon": "car"},
             {"id": "stress", "label": "Stress", "icon": "warning"},
             {"id": "nothing", "label": "Nothing usually", "icon": "checkmark-done"},
         ]},
        {"id": "coaching_style_pref", "section": "Coach Preferences",
         "text": "What kind of coach do you respond to?",
         "type": "single_select", "options": [
             {"id": "strict", "label": "Strict", "icon": "ribbon"},
             {"id": "supportive", "label": "Supportive", "icon": "hand-left"},
             {"id": "data_driven", "label": "Data driven", "icon": "stats-chart"},
             {"id": "flexible", "label": "Flexible", "icon": "swap-horizontal"},
             {"id": "high_accountability", "label": "High accountability", "icon": "flag"},
             {"id": "hands_off", "label": "Hands off", "icon": "sparkles"},
             {"id": "motivational", "label": "Motivational", "icon": "flame"},
             {"id": "educational", "label": "Educational", "icon": "book"},
         ]},
    ]

    # Iter 94e — Filter out layover-specific questions if the client's flying
    # pattern doesn't include layovers. Return them a synthetic "already
    # answered" state so downstream code sees them as satisfied.
    if non_layover:
        fb = [q for q in fb if not q.get("_skip_if_non_layover")]

    for q in fb:
        if q["id"] not in answered:
            # Strip the internal filter flag before returning to the client.
            clean_q = {k: v for k, v in q.items() if not k.startswith("_")}
            return {"next_question": clean_q, "should_end": False,
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
        "biological_sex": ans_map.get("biological_sex") or profile.get("biological_sex") or "unknown",
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
        "recommended_weekly_training": "4 sessions/week: Training Day 1 strength, Training Day 2 conditioning, Training Day 3 mobility, Training Day 4 optional — mapped to roster after upload.",
        "recommended_recovery_strategy": "Prioritise sleep windows; light mobility on jet-lag days.",
        "recommended_nutrition_strategy": "Consistent protein at each meal; hydrate on flights.",
        "recommended_coaching_style": "Supportive, empathetic, with clear structure.",
        "summary": "CrewFit is beginning to learn your patterns. Confidence will rise with every roster and workout.",
    }



# Iter 94g — SIGN-UP + /training-setup + coach-edit answers must ALL be treated
# as "already answered" by the DNA assessment. Otherwise the client sees the
# same question ("How do you fly?" / "What are your goals?") on the training-
# setup screen AND on the DNA screen. This helper merges every profile-derived
# field into the assessment.answers list, deduping by question_id.
_SEX_MAP = {
    "male": "male", "female": "female",
    "other": "intersex_prefer_not", "prefer_not_to_say": "intersex_prefer_not",
    "intersex": "intersex_prefer_not", "intersex_prefer_not": "intersex_prefer_not",
}
_JOB_TO_ROLE_MAP = {
    "cabin crew": "cabin_crew", "senior cabin crew": "cabin_crew", "purser": "cabin_crew",
    "first officer": "pilot", "captain": "pilot", "pilot": "pilot",
    "ground crew": "ground_ops", "ground ops": "ground_ops",
    "corporate": "corporate", "corporate aviation": "corporate",
    "other": "other",
}


async def _seed_assessment_from_profile(assessment: dict, user: dict) -> None:
    """Merge every essential profile field into `assessment["answers"]`, deduped.

    Runs at both /assessment/start (new assessment) and /assessment/start
    (resumed) so a user who filled /training-setup FIRST never gets those
    same questions re-asked by the DNA flow.

    Mutates `assessment["answers"]` in place and persists to Mongo if any
    new answers were added.
    """
    profile = (user or {}).get("profile") or {}
    if not profile:
        return
    existing_ids = {
        a.get("question_id") for a in (assessment.get("answers") or [])
        if a.get("question_id")
    }
    added: list[dict] = []
    now = now_iso()

    def _add(qid: str, section: str, text: str, qtype: str, ans: Any,
             src: str = "profile") -> None:
        if qid in existing_ids or ans in (None, "", []):
            return
        added.append({
            "question_id": qid,
            "section": section,
            "question_text": text,
            "question_type": qtype,
            "answer": ans,
            "answered_at": now,
            "prefilled_from": src,
        })
        existing_ids.add(qid)

    # --- biological_sex (signup: profile.sex, or existing profile.biological_sex)
    bio = profile.get("biological_sex")
    if not bio and profile.get("sex"):
        bio = _SEX_MAP.get(str(profile.get("sex")).lower().strip())
    if bio:
        _add("biological_sex", "About You",
             "What is your biological sex?", "single_select", bio, src="signup")

    # --- role / crew_role (signup: profile.job_title, /training-setup: crew_role)
    role_val = profile.get("crew_role") or profile.get("role")
    if not role_val and profile.get("job_title"):
        role_val = _JOB_TO_ROLE_MAP.get(str(profile.get("job_title")).lower().strip())
    if role_val:
        _add("role", "Your Aviation",
             "What is your role in aviation?", "single_select",
             str(role_val).lower(), src="signup")

    # --- flying_type (/training-setup writes profile.flying_type + route_focus)
    ft = profile.get("flying_type") or profile.get("route_focus")
    if ft:
        _add("flying_type", "Your Aviation",
             "What kind of flying do you mainly do?", "single_select",
             str(ft).lower(), src="training_setup")
        # If short-haul / ground-only, mirror the auto-injected layover answers
        # so the DNA flow doesn't try to ask them either.
        if str(ft).lower() in _NON_LAYOVER_FLYING_TYPES:
            _add("time_layover", "Time Available",
                 "How much time do you typically have on a layover?",
                 "single_select", "0", src="training_setup_auto")
            _add("hotel_gyms", "Your Aviation",
                 "Do you usually find gyms in your hotels?",
                 "single_select", "never", src="training_setup_auto")

    # --- primary_goal (/training-setup writes primary_goal_id + main_goal_key)
    pg = profile.get("primary_goal_id") or profile.get("main_goal_key") or profile.get("main_goal")
    if pg:
        _add("primary_goal", "Your Goals",
             "What are you trying to achieve?", "multi_select",
             [str(pg)], src="training_setup")

    # --- secondary_goals (list) — training-setup writes secondary_goal_ids
    sg = profile.get("secondary_goal_ids") or profile.get("secondary_goals")
    if sg and isinstance(sg, list) and len(sg) > 0:
        _add("secondary_goals", "Your Goals",
             "Any other goals that matter to you?", "multi_select",
             [str(x) for x in sg], src="training_setup")

    # --- training_days
    td = profile.get("training_days_per_week") or profile.get("training_days")
    if isinstance(td, (int, float)) and 1 <= int(td) <= 7:
        _add("training_days", "Time Available",
             "How many days per week can you train?", "single_select",
             str(int(td)), src="training_setup")

    # --- time_home
    th = profile.get("time_home_min")
    if th is not None:
        _add("time_home", "Time Available",
             "How much time do you have per session at home?",
             "single_select", str(int(th)), src="training_setup")

    # --- time_layover (only if profile explicitly has it — else the flying_type
    #     short-circuit above will have handled non-layover crews)
    tl = profile.get("time_layover_min")
    if tl is not None:
        _add("time_layover", "Time Available",
             "How much time do you typically have on a layover?",
             "single_select", str(int(tl)), src="training_setup")

    # --- equipment_home
    eq = profile.get("equipment")
    if isinstance(eq, list) and len(eq) > 0:
        _add("equipment_home", "Equipment",
             "What equipment do you have at home?", "equipment_picker",
             {"location": "home", "equipment": list(eq)}, src="training_setup")

    # --- hotel_gyms
    hg = profile.get("hotel_gym_reliability") or profile.get("hotel_gyms")
    if hg:
        _add("hotel_gyms", "Your Aviation",
             "Do you usually find gyms in your hotels?", "single_select",
             str(hg).lower(), src="training_setup")

    # --- injuries
    inj = profile.get("injuries")
    if isinstance(inj, str) and inj.strip():
        _add("injuries", "Injuries",
             "Any current injuries, or things to avoid?", "long_text",
             inj.strip(), src="training_setup")
    elif profile.get("no_injuries") or profile.get("injuries_none"):
        _add("injuries", "Injuries",
             "Any current injuries, or things to avoid?", "long_text",
             {"__explicit_none": True}, src="training_setup")

    # --- no_go_movements
    ng = profile.get("no_go_movements")
    if isinstance(ng, list) and len(ng) > 0:
        _add("no_go_movements", "Injuries",
             "Any movement patterns to avoid entirely?", "multi_select",
             [str(x) for x in ng], src="training_setup")
    elif profile.get("no_go_none") is True:
        _add("no_go_movements", "Injuries",
             "Any movement patterns to avoid entirely?", "multi_select",
             ["none"], src="training_setup")

    # Persist.
    if added:
        assessment.setdefault("answers", []).extend(added)
        try:
            await db.assessments.update_one(
                {"id": assessment["id"]},
                {"$set": {"answers": assessment["answers"]}},
            )
        except Exception:
            logger.exception("seed_assessment_from_profile: persist failed")



@api.post("/assessment/start")
async def assessment_start(body: AssessmentStartBody = AssessmentStartBody(), user: dict = Depends(current_user)):
    # If an in-progress assessment exists, resume it
    existing = await db.assessments.find_one({"user_id": user["id"], "status": "in_progress"}, {"_id": 0}, sort=[("created_at", -1)])
    if existing:
        # Iter 94g — seed any profile-derived fields into the existing assessment
        # too, so users who did /training-setup first don't get re-asked in DNA.
        await _seed_assessment_from_profile(existing, user)
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
    # Iter 82 — Pre-seed answers from signup data so the DNA assessment doesn't
    # re-ask questions already answered during signup (sex, aviation role).
    # Iter 94g — Extended to seed from EVERY profile field that /training-setup
    # or a previous coach edit has already written. This is the actual fix for
    # the "asked flying_type twice" complaint — the training-setup screen and
    # the DNA assessment used to ask the same questions independently.
    await _seed_assessment_from_profile(doc, user)

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
    # Iter 94f — Idempotency: if the same question_id is already answered,
    # UPDATE it in-place instead of appending a duplicate row. This stops
    # duplicated transcript entries when the frontend accidentally re-submits
    # (e.g. double-tap or a stale replay). Without this dedup the answered_ids
    # set still works but the assessment doc grows with noise.
    existing_idx = next(
        (i for i, ans in enumerate(a["answers"]) if ans.get("question_id") == q_id),
        None,
    )
    new_answer_row = {
        "question_id": q_id,
        "section": cq.get("section"),
        "question_text": cq.get("text"),
        "question_type": cq.get("type"),
        "answer": body.answer,
        "answered_at": now_iso(),
    }
    if existing_idx is not None:
        # Preserve the prefilled_from flag if it was set at signup.
        prev = a["answers"][existing_idx]
        if prev.get("prefilled_from"):
            new_answer_row["prefilled_from"] = prev.get("prefilled_from")
        a["answers"][existing_idx] = new_answer_row
    else:
        a["answers"].append(new_answer_row)
    await db.assessments.update_one({"id": a["id"]}, {"$set": {"answers": a["answers"]}})

    # Persist critical demographic answers straight onto user.profile so the
    # whole app (DNA generator, programme builder, nutrition targets) can
    # read them without walking the assessment transcript.
    if q_id == "biological_sex" and isinstance(body.answer, (str, int, float)):
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"profile.biological_sex": str(body.answer)}},
        )

    # Iter 94e — Persist aviation role directly onto profile.crew_role so the
    # essentials check passes without training-setup re-asking.
    if q_id == "role" and isinstance(body.answer, (str,)):
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"profile.crew_role": str(body.answer).lower()}},
        )

    # Iter 94e — Persist primary_goal too. It may arrive as a list (multi_select)
    # or a string. First goal becomes main_goal_key.
    if q_id == "primary_goal":
        val = body.answer
        first_goal = None
        if isinstance(val, list) and val:
            first_goal = str(val[0])
        elif isinstance(val, str) and val:
            first_goal = val
        if first_goal:
            await db.users.update_one(
                {"id": user["id"]},
                {"$set": {
                    "profile.primary_goal_id": first_goal,
                    "profile.main_goal_key": first_goal,
                    "profile.main_goal": first_goal,
                }},
            )

    # Iter 94e — Persist flying_type onto profile AND auto-inject layover
    # answers when the client does not do layovers so we never ask them.
    if q_id == "flying_type" and isinstance(body.answer, (str,)):
        ft = str(body.answer).lower().strip()
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {
                "profile.flying_type": ft,
                "profile.route_focus": ft,
                "profile.does_layovers": ft not in ("short_haul", "ground_only"),
            }},
        )
        if ft in ("short_haul", "ground_only"):
            now = now_iso()
            already_ids = {ans.get("question_id") for ans in a["answers"]}
            for auto_qid, auto_val, auto_text in (
                ("time_layover", "0", "How much time do you typically have on a layover?"),
                ("hotel_gyms",   "never", "Do you usually find gyms in your hotels?"),
            ):
                if auto_qid in already_ids:
                    continue
                a["answers"].append({
                    "question_id": auto_qid,
                    "section": "Time Available" if auto_qid == "time_layover" else "Your Aviation",
                    "question_text": auto_text,
                    "question_type": "single_select",
                    "answer": auto_val,
                    "answered_at": now,
                    "auto_injected_from": "flying_type",
                })
            await db.assessments.update_one({"id": a["id"]}, {"$set": {"answers": a["answers"]}})
            # Also mirror onto profile so essentials check passes without a retry.
            await db.users.update_one(
                {"id": user["id"]},
                {"$set": {
                    "profile.time_layover_min": 0,
                    "profile.hotel_gym_reliability": "never",
                    "profile.hotel_gyms": "never",
                }},
            )

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

# ---------------------------------------------------------------------------
# Iter 82 — Louis welcome message (fires once on assessment completion)
# ---------------------------------------------------------------------------

async def _send_louis_welcome_message_if_needed(user: dict) -> None:
    """
    Send a personalised welcome from Louis to a newly onboarded client, exactly
    once. The message explains beta testing, invites feedback, and prompts a
    roster upload if none exists.

    Idempotent: uses `users.louis_welcome_sent` sentinel to avoid duplicates.
    Falls back silently if Louis' account isn't seeded (dev environments).
    """
    if user.get("role") != "client":
        return
    # Idempotency guard
    fresh = await db.users.find_one({"id": user["id"]}, {"louis_welcome_sent": 1})
    if fresh and fresh.get("louis_welcome_sent"):
        return
    # Locate Louis (head coach) — prefer the canonical email; fall back to
    # ANY coach so dev environments without seeded Louis still get a sender.
    louis = await db.users.find_one(
        {"email": "louis@crewfit.net"},
        {"_id": 0, "id": 1, "name": 1, "email": 1},
    )
    if not louis:
        louis = await db.users.find_one(
            {"role": "coach"},
            {"_id": 0, "id": 1, "name": 1, "email": 1},
        )
    if not louis or not louis.get("id"):
        # No coach seeded — non-fatal, just mark as sent so we don't retry forever
        await db.users.update_one({"id": user["id"]}, {"$set": {"louis_welcome_sent": True}})
        return
    # Roster check — do they need to upload one?
    has_roster = await db.rosters.count_documents({"user_id": user["id"]}) > 0
    first_name = (user.get("first_name") or (user.get("name") or "").split(" ")[0] or "there").strip()
    # Iter 94k — Welcome message rewritten per beta support spec + adds the
    # WhatsApp support link. The frontend renders a "Message Louis on WhatsApp"
    # button whenever `whatsapp_support_url` is present on a message.
    lines = [
        f"Hi {first_name}, welcome to CrewFit — it's Louis here.",
        "",
        "Thanks for joining the private beta.",
        "",
        "A quick heads-up: CrewFit is still in beta, and the system is learning to read company rosters step-by-step. Every airline formats theirs a little differently, so our roster reader is being taught new patterns as we go.",
        "",
        "First thing I need you to do is upload the most detailed roster you have. The more detail you upload, the better CrewFit can understand your flying schedule and build your training around it.",
        "",
        "Please include as much as possible, such as duties, sectors, report times, finish times, layovers, standby, days off, nights, early starts and hotels if shown.",
        "",
        "If the automated roster upload doesn't work for your format, no problem — you can attach the file directly to a message here in this chat and I'll get it into the system manually.",
        "",
        "If anything else looks wrong, or if the app gets stuck, message me here straight away.",
        "",
        "You can also message me directly on WhatsApp if you run into any problems during beta.",
        "",
        "Once your roster is in, CrewFit can start building your schedule properly.",
        "",
        "Louis",
    ]
    text = "\n".join(lines)
    now = now_iso()
    doc = {
        "id": new_id(),
        "from_user_id": louis["id"],
        "to_user_id": user["id"],
        "text": text,
        "created_at": now,
        "read": False,
        "attachment_ids": [],
        "welcome_message": True,
        # Iter 94k — attach the WhatsApp button metadata to this message.
        "whatsapp_support_url": "https://wa.link/k9x12s",
        "whatsapp_support_context": "welcome",
    }
    await db.messages.insert_one(doc)
    # Also stamp the sentinel + assigned_coach if it wasn't already set
    updates: dict = {"louis_welcome_sent": True, "louis_welcome_sent_at": now}
    if not user.get("assigned_coach_id"):
        updates["assigned_coach_id"] = louis["id"]
        updates["assigned_coach_name"] = louis.get("name") or "Louis Hall"
    await db.users.update_one({"id": user["id"]}, {"$set": updates})


# ---------------------------------------------------------------------------
# Iter 94k — WhatsApp support click tracking
# ---------------------------------------------------------------------------

class WhatsAppSupportBody(BaseModel):
    screen: str
    context: Optional[str] = None
    roster_id: Optional[str] = None
    programme_id: Optional[str] = None
    workout_id: Optional[str] = None


@api.post("/support/whatsapp-clicked")
async def support_whatsapp_clicked(body: WhatsAppSupportBody, user: dict = Depends(current_user)):
    """Log a WhatsApp support click. Writes:

      1. An audit row into `support_events` for analytics.
      2. A timeline entry into `programme_timeline` (if we have a programme_id)
         so Louis sees "Client opened WhatsApp support" in the client's
         coach-side timeline.

    We DO NOT store any WhatsApp message content — only the click event.
    Idempotency is intentionally NOT enforced: repeat clicks are useful signal
    (client is stuck / trying repeatedly).
    """
    now = now_iso()
    ev = {
        "id": new_id(),
        "type": "support_whatsapp_clicked",
        "user_id": user["id"],
        "user_name": user.get("name"),
        "screen": body.screen,
        "context": body.context,
        "roster_id": body.roster_id,
        "programme_id": body.programme_id,
        "workout_id": body.workout_id,
        "created_at": now,
    }
    try:
        await db.support_events.insert_one(ev)
    except Exception:
        logger.exception("support_whatsapp_clicked: audit write failed (non-fatal)")

    # Add to programme timeline for coach visibility. Fall back to the
    # currently-active programme when the client didn't pass one.
    prog_id = body.programme_id
    if not prog_id:
        try:
            p = await db.programmes.find_one({"user_id": user["id"]}, {"_id": 0, "id": 1}, sort=[("created_at", -1)])
            prog_id = (p or {}).get("id")
        except Exception:
            prog_id = None
    if prog_id:
        try:
            await db.programme_timeline.insert_one({
                "id": new_id(),
                "user_id": user["id"],
                "programme_id": prog_id,
                "type": "support_whatsapp_clicked",
                "title": "Client opened WhatsApp support",
                "screen": body.screen,
                "context": body.context,
                "roster_id": body.roster_id,
                "workout_id": body.workout_id,
                "created_at": now,
            })
        except Exception:
            logger.exception("support_whatsapp_clicked: timeline write failed (non-fatal)")
    return {"ok": True, "id": ev["id"]}




# ---------------------------------------------------------------------------
# Iter 84 (Task 1.2) — Mandatory-fields helper for /assessment/finalize.
#
# These are the 8 essential DNA fields (plus biological_sex + crew_role which
# are locked at signup, checked separately). Every client MUST have them before
# we finalize the assessment and build their programme.
# ---------------------------------------------------------------------------
_ESSENTIAL_DNA_FIELDS: list[str] = [
    "primary_goal",
    # secondary_goals is 0-3 — asked but empty list is OK
    "flying_type",         # Iter 94e2 — gates layover / hotel_gyms
    "training_days",
    "time_home",
    "time_layover",
    "equipment_home",
    "hotel_gyms",
    "injuries",
    "no_go_movements",
]
_FRIENDLY_ESSENTIAL_LABELS: dict[str, str] = {
    "primary_goal":     "Your primary goal",
    "flying_type":      "The type of flying you do",
    "training_days":    "How many days per week you can train",
    "time_home":        "Time per session at home",
    "time_layover":     "Time per session on a layover",
    "equipment_home":   "Equipment you have at home",
    "hotel_gyms":       "How reliable hotel gyms are for you",
    "injuries":         "Current injuries or things to avoid",
    "no_go_movements":  "Movements you must avoid",
    "biological_sex":   "Biological sex",
    "crew_role":        "Aviation role",
}


def _missing_essential_fields(assessment: dict, user: dict) -> list[str]:
    """
    Return the list of essential-field IDs missing from the assessment / user
    profile. Empty list = all fields present, safe to finalize.

    Assessment.answers is a LIST of {question_id, answer} entries. We flatten
    it into a dict for O(1) lookups. If the same question was answered twice,
    the LATER answer wins (users can revise).

    Iter 94g — Profile is now checked for EVERY essential (not just flying_type),
    because `/training-setup` writes these fields DIRECTLY to profile. Without
    this, a user who filled `/training-setup` and then reached the end of DNA
    would see "Louis needs a few more answers" even though every essential is
    already on their profile.

    Special rules:
      * "equipment_home" — must be a non-empty list. "bodyweight_only" is OK.
      * "no_go_movements" — must be a non-empty list. ["none"] is OK.
      * "injuries" — either non-empty text OR the explicit-none payload
        ({"__explicit_none": true, ...}) OR the boolean-flag "no_injuries".
    """
    profile = (user or {}).get("profile") or {}
    # Flatten answers list into dict (latest-wins)
    answers_flat: dict[str, Any] = {}
    for a in (assessment or {}).get("answers") or []:
        if not isinstance(a, dict):
            continue
        qid = a.get("question_id")
        if qid:
            answers_flat[qid] = a.get("answer")

    missing: list[str] = []

    if not (answers_flat.get("biological_sex") or profile.get("biological_sex") or profile.get("sex")):
        missing.append("biological_sex")
    if not (answers_flat.get("crew_role") or profile.get("crew_role") or profile.get("role") or profile.get("job_title")):
        missing.append("crew_role")

    for fid in _ESSENTIAL_DNA_FIELDS:
        v = answers_flat.get(fid)
        if fid == "flying_type":
            if not (v or profile.get("flying_type") or profile.get("route_focus")):
                missing.append(fid)
        elif fid == "primary_goal":
            has_answer = bool(v)  # multi_select list, non-empty
            has_profile = bool(
                profile.get("primary_goal_id")
                or profile.get("main_goal_key")
                or profile.get("main_goal")
            )
            if not (has_answer or has_profile):
                missing.append(fid)
        elif fid == "training_days":
            has_answer = v not in (None, "", [])
            has_profile = bool(
                profile.get("training_days_per_week")
                or profile.get("training_days")
            )
            if not (has_answer or has_profile):
                missing.append(fid)
        elif fid == "time_home":
            has_answer = v not in (None, "", [])
            has_profile = profile.get("time_home_min") is not None
            if not (has_answer or has_profile):
                missing.append(fid)
        elif fid == "time_layover":
            has_answer = v not in (None, "", [])
            has_profile = profile.get("time_layover_min") is not None
            if not (has_answer or has_profile):
                missing.append(fid)
        elif fid == "equipment_home":
            has_answer = isinstance(v, list) and len(v) > 0
            prof_eq = profile.get("equipment")
            has_profile = isinstance(prof_eq, list) and len(prof_eq) > 0
            if not (has_answer or has_profile):
                missing.append(fid)
        elif fid == "hotel_gyms":
            has_answer = v not in (None, "", [])
            has_profile = bool(
                profile.get("hotel_gym_reliability")
                or profile.get("hotel_gyms")
            )
            if not (has_answer or has_profile):
                missing.append(fid)
        elif fid == "no_go_movements":
            if isinstance(v, list) and len(v) > 0:
                pass  # answered
            elif answers_flat.get("no_go_none") or answers_flat.get("no_no_go_movements"):
                pass  # explicit-none flag
            elif isinstance(v, list) and any(str(x).lower() == "none" for x in v):
                pass  # ["none"] sentinel — belt & braces
            elif profile.get("no_go_none") is True:
                pass  # /training-setup wrote explicit "no restrictions"
            elif isinstance(profile.get("no_go_movements"), list):
                # empty list also counts as "answered no restrictions" from
                # /training-setup, which submits [] when nothing is ticked.
                pass
            else:
                missing.append(fid)
        elif fid == "injuries":
            has_explicit_none = (
                (isinstance(v, dict) and v.get("__explicit_none"))
                or bool(answers_flat.get("no_injuries"))
                or bool(answers_flat.get("injuries_none"))
                or bool(profile.get("no_injuries"))
                or bool(profile.get("injuries_none"))
            )
            has_text = bool(v and isinstance(v, str) and v.strip())
            has_profile_text = bool(
                profile.get("injuries")
                and isinstance(profile.get("injuries"), str)
                and profile.get("injuries").strip()
            )
            if not (has_explicit_none or has_text or has_profile_text):
                missing.append(fid)
        else:
            if v in (None, "", []):
                missing.append(fid)
    # Iter 94b — If the client's profile explicitly says they don't do layovers,
    # drop layover-only essentials so they never get asked (or blocked).
    prof_route = profile.get("route_focus") or profile.get("flying_type")
    if profile.get("does_layovers") is False or prof_route in ("short_haul", "ground_only", "ground"):
        missing = [f for f in missing if f not in ("time_layover", "hotel_gyms")]
    return missing


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

    # Iter 94g — Belt-and-braces: re-seed from profile just before we run the
    # missing-check. Salvages any assessments created before the seeding fix
    # was live (or where the user filled `/training-setup` mid-assessment).
    await _seed_assessment_from_profile(a, user)

    # Iter 84 (Task 1.2) — Mandatory-fields guard.
    # Refuse to finalize until the 8 essential fields are present.
    # (biological_sex, aviation_role are locked at signup; the other 8 are DNA.)
    missing = _missing_essential_fields(a, user)
    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "profile_incomplete",
                "message": "Louis needs a few more answers before finalising your plan.",
                "missing_fields": missing,
                "friendly_labels": [_FRIENDLY_ESSENTIAL_LABELS.get(f, f) for f in missing],
            },
        )

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

    # Plan A1 + A2 — copy structured assessment answers into users.profile
    # (main_goal_key, training_days_per_week, experience_level, etc.) and
    # create endurance event stubs if needed. WITHOUT this handoff the
    # workout generator has no idea the client picked marathon or 4 days.
    handoff_summary: dict[str, Any] = {}
    try:
        handoff_summary = await _apply_assessment_answers_to_profile(user["id"], a)
    except Exception:
        logger.exception("assessment→profile handoff failed (non-fatal)")

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

    # Iter 82 — Send Louis's welcome message as soon as the assessment is
    # completed. Idempotent — only fires once per user.
    try:
        await _send_louis_welcome_message_if_needed(user)
    except Exception:
        logger.exception("welcome message send failed")

    # Seed the starter habits (async — don't block the finalize response)
    try:
        asyncio.create_task(_seed_habits_for_user_by_id(user["id"]))
    except Exception:
        logger.exception("habit seed trigger failed")

    return {"dna": dna_doc_clean, "events_created": events_created, "already_completed": False, "profile_handoff": handoff_summary}


# ---------------------------------------------------------------------------
# Assessment → users.profile handoff (Plan A1 + A2)
# The assessment collects `training_days`, `primary_goal` (multi-select),
# `experience`, `role`, `hotel_gyms`, `time_home`, `equipment_home`, `injuries`,
# but historically these lived only inside `coaching_dna`. The workout
# generator + `feature_programme_quality._resolve_goal_key` read from
# `users.profile`, so the answers must be back-copied here on finalize.
# Without this handoff, marathon clients silently fall back to
# `general_fitness` at 3 sessions/week.
# ---------------------------------------------------------------------------
_GOAL_ID_TO_KEY: dict[str, str] = {
    "lose_fat": "lose_fat",
    "build_muscle": "build_muscle",
    "general_fitness": "general_fitness",
    "marathon": "event",
    "half_marathon": "event",
    "ironman": "event",
    "seventy_three": "event",
    "hyrox": "event",
    "sprint_tri": "event",
    "olympic_tri": "event",
    "five_k": "event",
    "ten_k": "event",
    "mobility": "improve_energy",
    "reduce_pain": "return_to_training",
    "return_injury": "return_to_training",
    "reduce_jetlag": "aviation_consistency",
    "improve_sleep": "aviation_consistency",
    "airline_medical": "health_markers",
    "maintain": "aviation_consistency",
}

_GOAL_ID_TO_LABEL: dict[str, str] = {
    "lose_fat": "Lose body fat",
    "build_muscle": "Build muscle",
    "general_fitness": "General fitness",
    "marathon": "Marathon",
    "half_marathon": "Half Marathon",
    "ironman": "Ironman",
    "seventy_three": "Ironman 70.3",
    "hyrox": "HYROX",
    "sprint_tri": "Sprint Triathlon",
    "olympic_tri": "Olympic Triathlon",
    "five_k": "5K",
    "ten_k": "10K",
    "mobility": "Improve mobility",
    "reduce_pain": "Reduce pain",
    "return_injury": "Return from injury",
    "reduce_jetlag": "Reduce jet lag",
    "improve_sleep": "Improve sleep",
    "airline_medical": "Pass airline medical",
    "maintain": "Maintain fitness",
}

_GOAL_ID_TO_EVENT_TYPE: dict[str, str] = {
    "marathon": "marathon",
    "half_marathon": "half_marathon",
    "ironman": "ironman",
    "seventy_three": "half_ironman",
    "hyrox": "hyrox",
    "sprint_tri": "sprint_tri",
    "olympic_tri": "olympic_tri",
    "five_k": "5k",
    "ten_k": "10k",
}


async def _apply_assessment_answers_to_profile(user_id: str, assessment: dict) -> dict[str, Any]:
    """Copy structured assessment answers into `users.profile` and create
    endurance-event stubs where relevant. Returns a summary dict.

    IMPORTANT: this fills the exact fields the workout generator reads
    (`main_goal_key`, `training_days_per_week`, `experience_level`, etc.).
    Without this, a marathon client is invisible to the generator.

    Assessment question IDs are DYNAMIC (Claude adaptive interview) so we use
    a mix of:
      1. Exact-id lookups for the static seed questions
      2. Fuzzy id/section pattern matching for adaptive follow-ups
      3. Fallback to the Coaching DNA which is already structured
    """
    ans_map: dict[str, Any] = {}
    ans_meta: list[dict] = []
    for a in (assessment.get("answers") or []):
        qid = a.get("question_id")
        if qid:
            ans_map[qid] = a.get("answer")
            ans_meta.append({
                "id": qid,
                "section": (a.get("section") or "").lower(),
                "text": (a.get("question_text") or "").lower(),
                "answer": a.get("answer"),
            })

    def _find_by_pattern(patterns: list[str]) -> Any:
        """Return the first answer whose question_id / section / text matches
        any of the given lowercase substring patterns."""
        for m in ans_meta:
            for pat in patterns:
                if pat in m["id"] or pat in m["section"] or pat in m["text"]:
                    return m["answer"]
        return None

    profile_updates: dict[str, Any] = {}

    # --- training_days_per_week: try common id patterns ---
    td_raw = (
        ans_map.get("training_days")
        or ans_map.get("training_days_per_week")
        or ans_map.get("weekly_training_days")
        or ans_map.get("days_per_week")
        or _find_by_pattern([
            "days_per_week", "training_days", "weekly_training_time",
            "how many days a week", "days a week can you train",
        ])
    )
    if td_raw is not None:
        try:
            profile_updates["training_days_per_week"] = int(str(td_raw).strip())
        except Exception:
            pass

    # --- primary_goal (single or multi) ---
    goals = (
        ans_map.get("primary_goal")
        or ans_map.get("primary_goals")
        or ans_map.get("goals")
        or _find_by_pattern(["primary_goal", "primary_goals", "main goal", "what are you trying to achieve"])
    )
    if isinstance(goals, str):
        goals = [goals]
    if isinstance(goals, list) and goals:
        endurance_priority = [
            "marathon", "ironman", "seventy_three", "half_marathon",
            "hyrox", "olympic_tri", "sprint_tri", "ten_k", "five_k",
        ]
        primary_id: Optional[str] = None
        for eid in endurance_priority:
            if eid in goals:
                primary_id = eid
                break
        if primary_id is None:
            primary_id = str(goals[0])
        primary_id = str(primary_id)
        key = _GOAL_ID_TO_KEY.get(primary_id, "general_fitness")
        label = _GOAL_ID_TO_LABEL.get(primary_id, str(primary_id).replace("_", " ").title())
        profile_updates["main_goal_key"] = key
        profile_updates["main_goal"] = label
        profile_updates["primary_goal_id"] = primary_id
        profile_updates["secondary_goal_ids"] = [g for g in goals if g != primary_id][:4]
        ev_type = _GOAL_ID_TO_EVENT_TYPE.get(primary_id)
        if ev_type:
            profile_updates["event_type_pref"] = ev_type

    # --- experience level ---
    exp = (
        ans_map.get("experience")
        or ans_map.get("experience_level")
        or ans_map.get("training_experience")
        or _find_by_pattern(["training_experience", "experience_level", "training history"])
    )
    if exp:
        profile_updates["experience_level"] = str(exp).lower()

    # --- aviation role → job_title ---
    role_id = (
        ans_map.get("role")
        or ans_map.get("aviation_role")
        or _find_by_pattern(["aviation_role"])
    )
    if role_id:
        role_map = {
            "pilot": "Pilot", "cabin_crew": "Cabin Crew",
            "ground_ops": "Ground Ops", "corporate": "Corporate Aviation",
            "other": "Other",
        }
        profile_updates["job_title"] = role_map.get(str(role_id), str(role_id).replace("_", " ").title())

    # --- long/short haul ---
    haul = ans_map.get("pilot_operation_type") or _find_by_pattern(["operation_type", "haul_mix", "long_haul", "short_haul"])
    if haul:
        profile_updates["route_focus"] = str(haul)

    # --- hotel_gyms ---
    hg = (
        ans_map.get("hotel_gyms")
        or ans_map.get("equipment_access_layover")
        or _find_by_pattern(["hotel_gym", "layover_gym", "equipment_access_layover"])
    )
    if hg:
        profile_updates["hotel_gyms"] = str(hg)

    # --- time_home / minutes ---
    th = ans_map.get("time_home") or ans_map.get("max_home_minutes")
    if th is not None:
        try:
            profile_updates["max_home_minutes"] = int(th)
        except Exception:
            pass

    # --- equipment (list OR dict {location, equipment: [...]}) ---
    eq = (
        ans_map.get("equipment_home")
        or ans_map.get("equipment_access_home")
        or _find_by_pattern(["equipment_access_home", "equipment_home", "home equipment"])
    )
    if isinstance(eq, dict):
        eq = eq.get("equipment") or []
    if isinstance(eq, list) and eq:
        profile_updates["equipment"] = [str(e) for e in eq if e]
        profile_updates["home_equipment"] = [str(e) for e in eq if e]

    # --- injuries free-text ---
    inj = (
        ans_map.get("injuries")
        or ans_map.get("injury_history_current")
        or _find_by_pattern(["injury_history", "current injuries", "things you must avoid"])
    )
    if inj:
        profile_updates["injury_notes"] = str(inj)

    # --- biological_sex mirroring ---
    bs = ans_map.get("biological_sex")
    if bs:
        profile_updates["biological_sex"] = str(bs)

    # --- DNA fallback for missing structured fields ---
    dna_row = await db.coaching_dna.find_one({"user_id": user_id}, {"_id": 0}, sort=[("version", -1)])
    if dna_row:
        # primary_goal from DNA if we didn't get one from answers
        if "main_goal_key" not in profile_updates:
            dna_goal = str(dna_row.get("primary_goal") or "").lower()
            if dna_goal:
                # Simple keyword map to our GOAL_MATRIX keys
                if "marathon" in dna_goal or "10k" in dna_goal or "5k" in dna_goal or "ironman" in dna_goal or "hyrox" in dna_goal or "triathlon" in dna_goal:
                    profile_updates["main_goal_key"] = "event"
                    profile_updates["main_goal"] = dna_row.get("primary_goal")
                    if "marathon" in dna_goal and "half" not in dna_goal:
                        profile_updates["event_type_pref"] = "marathon"
                    elif "half marathon" in dna_goal:
                        profile_updates["event_type_pref"] = "half_marathon"
                    elif "10k" in dna_goal:
                        profile_updates["event_type_pref"] = "10k"
                    elif "5k" in dna_goal:
                        profile_updates["event_type_pref"] = "5k"
                    elif "ironman" in dna_goal:
                        profile_updates["event_type_pref"] = "ironman"
                    elif "hyrox" in dna_goal:
                        profile_updates["event_type_pref"] = "hyrox"
                elif "fat" in dna_goal or "weight" in dna_goal or "lose" in dna_goal:
                    profile_updates["main_goal_key"] = "lose_fat"
                    profile_updates["main_goal"] = dna_row.get("primary_goal")
                elif "muscle" in dna_goal or "strength" in dna_goal or "build" in dna_goal:
                    profile_updates["main_goal_key"] = "build_muscle"
                    profile_updates["main_goal"] = dna_row.get("primary_goal")
        # training availability from DNA (best-effort parse of minutes/day pattern)
        if "training_days_per_week" not in profile_updates:
            avail = dna_row.get("training_availability") or {}
            # e.g. "4 days/week" or "240min/week" — try to sniff a small int 1-7 mentioned
            import re
            for v in avail.values() if isinstance(avail, dict) else []:
                if not isinstance(v, str):
                    continue
                m = re.search(r"\b([1-7])\s*(?:days?|d/w|d/wk|sessions?)", v.lower())
                if m:
                    profile_updates["training_days_per_week"] = int(m.group(1))
                    break

    if profile_updates:
        set_doc = {f"profile.{k}": v for k, v in profile_updates.items()}
        set_doc["profile.updated_at"] = now_iso()
        await db.users.update_one({"id": user_id}, {"$set": set_doc})

    # --- Endurance event materialisation (Plan A2) ---
    events_created = 0
    primary_id = profile_updates.get("primary_goal_id")
    ev_type = profile_updates.get("event_type_pref")
    # dated events may be inside adaptive answers as event_builder outputs.
    dated_events: list[dict] = []
    for m in ans_meta:
        v = m["answer"]
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and item.get("date") and item.get("name"):
                    dated_events.append(item)
    # DNA next_event
    if dna_row and isinstance(dna_row.get("next_event"), dict) and dna_row["next_event"].get("date"):
        dated_events.append(dna_row["next_event"])

    if dated_events:
        for ev in dated_events:
            dup = await db.events.find_one({"user_id": user_id, "event_date": ev["date"]}, {"_id": 0})
            if dup:
                continue
            name = str(ev.get("name") or "").strip()
            etype = _guess_event_type(name) or ev_type or "other"
            await db.events.insert_one({
                "id": new_id(),
                "user_id": user_id,
                "event_type": etype,
                "event_name": name or etype,
                "event_date": ev["date"],
                "priority": ev.get("priority") or "A",
                "is_active": True,
                "source": "assessment_v1_dated",
                "created_at": now_iso(),
            })
            events_created += 1
    elif ev_type:
        # No dated event but the goal implies one — insert a date-pending stub.
        dup = await db.events.find_one(
            {"user_id": user_id, "event_type": ev_type, "is_active": True},
            {"_id": 0},
        )
        if not dup:
            await db.events.insert_one({
                "id": new_id(),
                "user_id": user_id,
                "event_type": ev_type,
                "event_name": _GOAL_ID_TO_LABEL.get(primary_id or "", ev_type.replace("_", " ").title()),
                "event_date": None,
                "needs_date_confirmation": True,
                "priority": "B",
                "is_active": True,
                "source": "assessment_v1_goal_only",
                "created_at": now_iso(),
            })
            events_created += 1

    return {
        "profile_updates": list(profile_updates.keys()),
        "events_created": events_created,
    }


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


# ---------------------------------------------------------------------------
# Iter 84 (Task 1.3) — Profile setup-status + training-setup endpoints.
#
# `GET  /api/profile/setup-status` — tells the frontend whether the user still
#   needs to fill in essential fields. Frontend uses this on app boot to
#   decide whether to redirect to the /training-setup screen.
#
# `POST /api/profile/training-setup` — persists any subset of the essential
#   fields directly onto users.profile with the correct normalized keys the
#   plan builder actually reads. Idempotent, partial payloads OK.
# ---------------------------------------------------------------------------

_PROFILE_KEY_MAP = {
    # incoming setup field → users.profile.* key(s) to write
    "primary_goal":         ["primary_goal_id", "main_goal_key", "main_goal"],
    "secondary_goals":      ["secondary_goal_ids"],
    # Iter 94b — flying pattern
    "flying_type":          ["flying_type", "route_focus"],
    "route_focus":          ["route_focus"],
    "does_layovers":        ["does_layovers"],
    "training_days":        ["training_days_per_week", "training_days"],
    "time_home":            ["time_home_min"],
    "time_layover":         ["time_layover_min"],
    "equipment_home":       ["equipment"],
    "hotel_gym_reliability": ["hotel_gym_reliability", "hotel_gyms"],
    "injuries":             ["injuries"],
    "no_go_movements":      ["no_go_movements"],
}


async def _user_essentials_present(user_id: str) -> tuple[bool, list[str]]:
    """
    Compute setup-completeness for a given user by looking at BOTH:
      1. Any latest assessment (so answered-in-DNA fields count)
      2. Their profile fields (in case they went through /training-setup)
    Returns (complete, missing_field_ids).
    """
    u = await db.users.find_one({"id": user_id}, {"_id": 0}) or {}
    profile = u.get("profile") or {}
    # Grab the latest assessment even if it's in_progress (some fields may be
    # answered already even before the finalize step).
    a = await db.assessments.find_one(
        {"user_id": user_id}, {"_id": 0}, sort=[("updated_at", -1), ("created_at", -1)],
    ) or {"answers": []}
    missing_from_asmnt = set(_missing_essential_fields(a, u))
    # For each field, if the profile already has the corresponding value, drop
    # it from the missing set. This is what makes the top-up flow work.
    def _prof_has(fid: str) -> bool:
        if fid == "biological_sex":
            return bool(profile.get("biological_sex") or profile.get("sex"))
        if fid == "crew_role":
            return bool(profile.get("crew_role") or profile.get("role") or profile.get("job_title"))
        if fid == "primary_goal":
            return bool(profile.get("primary_goal_id") or profile.get("main_goal_key") or profile.get("main_goal"))
        if fid == "training_days":
            v = profile.get("training_days_per_week")
            return isinstance(v, (int, float)) and 1 <= int(v) <= 7
        if fid == "time_home":
            return profile.get("time_home_min") is not None
        if fid == "time_layover":
            return profile.get("time_layover_min") is not None
        if fid == "equipment_home":
            eq = profile.get("equipment")
            return isinstance(eq, list) and len(eq) > 0
        if fid == "hotel_gyms":
            return bool(profile.get("hotel_gym_reliability") or profile.get("hotel_gyms"))
        if fid == "injuries":
            return profile.get("injuries") not in (None, "")
        if fid == "no_go_movements":
            v = profile.get("no_go_movements")
            if isinstance(v, list) and len(v) > 0:
                return True
            # Explicit sentinel written by training-setup when user has none.
            if profile.get("no_go_none") is True or profile.get("no_go_movements_answered") is True:
                return True
            return False
        if fid == "flying_type":
            return bool(profile.get("flying_type") or profile.get("route_focus"))
        return False
    still_missing = sorted(fid for fid in missing_from_asmnt if not _prof_has(fid))
    # Iter 94b — If the client explicitly does NOT do layovers, drop layover-only
    # fields from the essentials list. `time_layover=0` and `hotel_gyms="never"`
    # are auto-persisted at flying_type submission time, so this is defence-in-depth.
    does_layovers = profile.get("does_layovers")
    route_focus = profile.get("route_focus") or profile.get("flying_type")
    non_layover_route = route_focus in ("short_haul", "ground_only", "ground")
    if does_layovers is False or non_layover_route:
        still_missing = [f for f in still_missing if f not in ("time_layover", "hotel_gyms")]
    return (len(still_missing) == 0, still_missing)


async def _assert_profile_complete_or_409(user_id: str, coach_hint: bool = False) -> None:
    """
    Iter 84 (Task 1.4) — Defence-in-depth for plan builds. Raises HTTP 409
    with a structured `profile_incomplete` payload if any essential field is
    missing. Callers should NOT catch this — let it bubble to the client.

    When `coach_hint=True` (called from a coach-scoped endpoint), we include
    a hint the coach UI can display alongside the missing-fields list.
    """
    complete, missing = await _user_essentials_present(user_id)
    if complete:
        return
    detail: dict[str, Any] = {
        "code": "profile_incomplete",
        "message": "Louis needs a few more details before he can plan.",
        "missing_fields": missing,
        "friendly_labels": [_FRIENDLY_ESSENTIAL_LABELS.get(f, f) for f in missing],
    }
    if coach_hint:
        detail["coach_hint"] = (
            "This client hasn't finished their training setup. Until they do, "
            "we can't rebuild without silently guessing equipment / time / days."
        )
    raise HTTPException(status_code=409, detail=detail)


# ---------------------------------------------------------------------------
# Iter 84 (Task 1.5) — Reconcile primary goal + registered events.
# ---------------------------------------------------------------------------

_ENDURANCE_EVENT_TYPES = {
    "marathon", "half_marathon", "10k", "5k", "ultra",
    "hyrox", "ironman", "70.3", "olympic_tri", "sprint_tri",
}

_ENDURANCE_GOAL_KEYS = {
    "marathon", "half_marathon", "10k", "5k", "hyrox",
    "ironman", "olympic_tri", "sprint_tri", "70.3",
}

async def _resolve_effective_goal_and_event(user_id: str) -> dict:
    """
    Iter 84 (Task 1.5) — Effective-goal resolver. Considers BOTH primary
    goal AND any registered endurance event within 24 weeks. Returns the
    struct the plan builder / home banner uses. Never raises.
    """
    from datetime import date as _date
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0}) or {}
    profile = u.get("profile") or {}
    primary = (
        profile.get("primary_goal_id")
        or profile.get("main_goal_key")
        or profile.get("main_goal")
        or "general_fitness"
    )
    primary_norm = str(primary).strip().lower()

    # Look for the priority-A endurance event first (Iter 84 Task 1.7 gives
    # the user explicit control). Fallback: soonest endurance within 24w.
    event = None
    weeks_to_event: Optional[int] = None
    try:
        today = _date.today()
        # First pass: priority=A endurance event
        cursor_a = db.events.find({
            "user_id": user_id,
            "event_date": {"$gte": today.isoformat()},
            "is_active": {"$ne": False},
            "priority": "A",
        }).sort([("event_date", 1)]).limit(3)
        candidates_a = await cursor_a.to_list(3)
        # Second pass: fallback = soonest endurance regardless of priority
        cursor_b = db.events.find({
            "user_id": user_id,
            "event_date": {"$gte": today.isoformat()},
            "is_active": {"$ne": False},
        }).sort([("event_date", 1)]).limit(5)
        candidates_b = await cursor_b.to_list(5)
        for pool in (candidates_a, candidates_b):
            for ev in pool:
                et = str(ev.get("event_type") or "").strip().lower().replace(" ", "_")
                if et in _ENDURANCE_EVENT_TYPES:
                    try:
                        ed = _date.fromisoformat(ev["event_date"][:10])
                        wks = (ed - today).days // 7
                        if 0 <= wks <= 24:
                            event = ev
                            weeks_to_event = wks
                            break
                    except Exception:
                        continue
            if event:
                break
    except Exception:
        pass

    # Decide effective goal_key + volume_bias
    if event:
        et = str(event.get("event_type") or "").strip().lower().replace(" ", "_")
        goal_key = "event"
        event_type = et
        event_date = event.get("event_date")
        # Volume bias — driven by the client's primary goal even though the
        # event drives session selection.
        if primary_norm in ("lose_fat", "fat_loss", "cut", "leaner"):
            volume_bias = "deficit"
            secondary_note = f"maintaining fat-loss deficit"
        elif primary_norm in ("build_muscle", "hypertrophy", "muscle", "size"):
            volume_bias = "surplus"
            secondary_note = f"retaining strength blocks alongside"
        else:
            volume_bias = "neutral"
            secondary_note = None
        pretty_event = event_type.replace("_", " ").title()
        explanation = f"{pretty_event} in {weeks_to_event} weeks"
        # Iter 84 (Task 1.6) — enrich banner with phase + this-week's long run
        try:
            from feature_programme_quality import _phase_for_weeks_to_race, _long_run_km_for_week, _is_cutback_week
            _phase = _phase_for_weeks_to_race(weeks_to_event)
            explanation += f" · {_phase.get('label')}"
            _lr = _long_run_km_for_week(event_type, weeks_to_event, cutback=_is_cutback_week(weeks_to_event))
            if isinstance(_lr, (int, float)) and _lr > 0:
                explanation += f" · long run {_lr}km"
            elif _lr == "RACE":
                explanation += f" · RACE DAY this week"
        except Exception:
            pass
        if secondary_note:
            explanation += f" · {secondary_note}"
    elif primary_norm in _ENDURANCE_GOAL_KEYS:
        # Primary goal IS an endurance goal — treat as event even without
        # a registered event. weeks_to_event unknown (None).
        goal_key = "event"
        event_type = primary_norm
        event_date = None
        volume_bias = "neutral"
        explanation = f"{event_type.replace('_',' ').title()} focus · no event date set"
    else:
        goal_key = primary_norm or "general_fitness"
        event_type = None
        event_date = None
        volume_bias = "neutral"
        explanation = f"{goal_key.replace('_',' ').title()} · no event registered"

    return {
        "goal_key": goal_key,
        "event_type": event_type,
        "event_date": event_date,
        "weeks_to_event": weeks_to_event,
        "primary_goal_key": primary_norm,
        "volume_bias": volume_bias,
        "explanation": explanation,
        # Iter 84 (Task 1.6) — periodisation extras
        "phase": _phase_for_periodisation_key(goal_key, weeks_to_event),
        "this_weeks_long_run_km": _long_run_km_or_none(event_type, weeks_to_event),
    }


def _phase_for_periodisation_key(goal_key: str, weeks_to_race: Optional[int]) -> Optional[str]:
    """Thin wrapper — return the human phase label the frontend banner shows."""
    if goal_key != "event":
        return None
    try:
        from feature_programme_quality import _phase_for_weeks_to_race
        return _phase_for_weeks_to_race(weeks_to_race).get("label")
    except Exception:
        return None


def _long_run_km_or_none(event_type: Optional[str], weeks_to_race: Optional[int]) -> Optional[float]:
    if not event_type:
        return None
    try:
        from feature_programme_quality import _long_run_km_for_week, _is_cutback_week
        v = _long_run_km_for_week(event_type, weeks_to_race, cutback=_is_cutback_week(weeks_to_race))
        return v if isinstance(v, (int, float)) else None
    except Exception:
        return None


@api.get("/programme/focus")
async def programme_focus(user: dict = Depends(current_user)):
    """Return the reconciled goal+event summary the home screen banner shows."""
    eff = await _resolve_effective_goal_and_event(user["id"])
    return {
        **eff,
        "banner_text": eff["explanation"],
    }


# ---------------------------------------------------------------------------
# Iter 84 (Task 1.7) — Multi-event dashboard + priority-aware periodisation.
# ---------------------------------------------------------------------------

@api.get("/events/active")
async def events_active(user: dict = Depends(current_user)):
    """List all currently-active events with priority + weeks-remaining."""
    from datetime import date as _date
    today = _date.today()
    rows = await db.events.find({
        "user_id": user["id"],
        "event_date": {"$gte": today.isoformat()},
        "is_active": {"$ne": False},
    }, {"_id": 0}).sort([("event_date", 1)]).to_list(20)
    out = []
    for ev in rows:
        et = str(ev.get("event_type") or "").strip().lower().replace(" ", "_")
        try:
            ed = _date.fromisoformat(ev["event_date"][:10])
            weeks = max(0, (ed - today).days // 7)
        except Exception:
            weeks = None
        out.append({
            **ev,
            "priority": ev.get("priority") or "C",
            "weeks_to_event": weeks,
            "is_endurance": et in _ENDURANCE_EVENT_TYPES,
        })
    # Auto-elect an implicit Priority A if none set: the soonest endurance event.
    has_a = any(e.get("priority") == "A" for e in out)
    if not has_a:
        for e in out:
            if e.get("is_endurance"):
                e["priority"] = "A"
                e["_implicit_priority_a"] = True
                break
    return {"events": out}


class EventPriorityBody(BaseModel):
    priority: str    # "A" | "B" | "C"


@api.patch("/events/{eid}/priority")
async def event_set_priority(eid: str, body: EventPriorityBody, user: dict = Depends(current_user)):
    p = (body.priority or "").upper().strip()
    if p not in ("A", "B", "C"):
        raise HTTPException(400, "priority must be A, B or C")
    ev = await db.events.find_one({"id": eid, "user_id": user["id"]})
    if not ev:
        raise HTTPException(404, "Event not found")
    # If promoting to A, demote current A → B (only one A allowed).
    if p == "A":
        await db.events.update_many(
            {"user_id": user["id"], "priority": "A", "id": {"$ne": eid}},
            {"$set": {"priority": "B", "updated_at": now_iso()}},
        )
    await db.events.update_one({"id": eid}, {"$set": {"priority": p, "updated_at": now_iso()}})
    return {"id": eid, "priority": p, "success": True}





@api.get("/profile/setup-status")
async def profile_setup_status(user: dict = Depends(current_user)):
    """Return whether the user still needs to fill in essential setup fields."""
    complete, missing = await _user_essentials_present(user["id"])
    return {
        "complete": complete,
        "missing_fields": missing,
        "friendly_labels": [_FRIENDLY_ESSENTIAL_LABELS.get(f, f) for f in missing],
        "setup_completed_at": (user.get("profile") or {}).get("setup_completed_at"),
    }


class TrainingSetupBody(BaseModel):
    primary_goal:         Optional[str] = None
    secondary_goals:      Optional[list[str]] = None
    # Iter 94b — flying pattern gates whether layover-related fields are essential.
    flying_type:          Optional[str] = None           # short_haul/mixed/long_haul/charter/cargo/ground_only
    route_focus:          Optional[str] = None           # alias set from flying_type
    does_layovers:        Optional[bool] = None
    training_days:        Optional[int] = None
    time_home:            Optional[int] = None          # minutes
    time_layover:         Optional[int] = None          # minutes
    equipment_home:       Optional[list[str]] = None
    hotel_gym_reliability: Optional[str] = None         # always/often/sometimes/rare/never
    injuries:             Optional[str] = None
    no_go_movements:      Optional[list[str]] = None
    biological_sex:       Optional[str] = None
    crew_role:            Optional[str] = None


@api.post("/profile/training-setup")
async def profile_training_setup(body: TrainingSetupBody, user: dict = Depends(current_user)):
    """
    Persist any subset of essential fields onto users.profile. Idempotent —
    call once with everything, or repeatedly with individual fields. Only
    non-None fields are written; existing values are preserved otherwise.
    """
    payload = body.model_dump(exclude_none=True)
    profile_updates: dict[str, Any] = {}
    # Iter 91 — genuinely healthy users need a way to answer "no restrictions".
    # If no_go_movements is submitted as [] we treat that as an explicit answer
    # and set a companion flag so essentials-present sees it.
    if "no_go_movements" in payload and isinstance(payload["no_go_movements"], list) and len(payload["no_go_movements"]) == 0:
        profile_updates["profile.no_go_none"] = True
    for setup_key, val in payload.items():
        prof_keys = _PROFILE_KEY_MAP.get(setup_key)
        # Fields not in the map (biological_sex, crew_role) are written directly.
        if not prof_keys:
            profile_updates[f"profile.{setup_key}"] = val
            continue
        for pk in prof_keys:
            profile_updates[f"profile.{pk}"] = val
    profile_updates["profile.updated_at"] = now_iso()
    # Stamp setup_completed_at if the resulting state is complete.
    if profile_updates:
        await db.users.update_one({"id": user["id"]}, {"$set": profile_updates})
    complete, missing = await _user_essentials_present(user["id"])
    if complete:
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"profile.setup_completed_at": now_iso()}},
        )
    return {
        "complete": complete,
        "missing_fields": missing,
        "friendly_labels": [_FRIENDLY_ESSENTIAL_LABELS.get(f, f) for f in missing],
    }


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
    # Iter 82 — Don't emit prompts for brand-new users (< 3 days old AND no
    # completed workouts). Prevents "you missed 10 sessions" nag on first login.
    try:
        from datetime import datetime as _dt2, timezone as _tz2
        u = await db.users.find_one({"id": user_id}, {"_id": 0, "created_at": 1})
        if u and u.get("created_at"):
            created_dt = _dt2.fromisoformat(str(u["created_at"]).replace("Z", "+00:00"))
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=_tz2.utc)
            age_days = (_dt2.now(_tz2.utc) - created_dt).total_seconds() / 86400.0
            if age_days < 3.0:
                completed = await db.workouts.count_documents({"user_id": user_id, "completed": True})
                if completed == 0:
                    return
    except Exception:
        pass
    # Cool-down: don't re-emit the same kind if there's a pending prompt in the last 3 days
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    cutoff = (_dt.now(_tz.utc) - _td(days=3)).isoformat()
    existing = await db.reassessment_prompts.find_one({
        "user_id": user_id, "kind": kind, "dismissed": False, "created_at": {"$gte": cutoff},
    })
    if existing:
        return

    # Iter172 · SMART DISMISS. If the user recently tapped "Not Now" on a
    # `missed_workouts` prompt, respect that decision for the rest of the
    # day — don't immediately re-emit a fresh copy the next time the
    # analyser runs. This is what turns "Not Now" from a one-second hide
    # into a real dismissal until tomorrow.
    if kind == "missed_workouts":
        dismiss_cutoff = (_dt.now(_tz.utc) - _td(hours=24)).isoformat()
        recently_dismissed = await db.reassessment_prompts.find_one({
            "user_id": user_id,
            "kind": "missed_workouts",
            "dismissed": True,
            "dismissed_at": {"$gte": dismiss_cutoff},
        })
        if recently_dismissed:
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
    """Return active (undismissed) re-assessment prompts for the user.

    Iter 82 — Grace period for brand-new users. A user who "just logged in for
    the first time" should not be nagged about missed sessions or roster
    confirmation. Suppress ALL prompts when:
      * the account was created in the last 3 days AND
      * the user has < 1 completed workout AND
      * the user has < 3 days of app engagement.
    Additionally, suppress `missed_workouts` for any user with 0 completed
    workouts ever — you can't miss what you never started.
    """
    from datetime import datetime as _dt2, timezone as _tz2, timedelta as _td2

    # Compute account age
    created_at = user.get("created_at") or user.get("onboarded_at")
    is_new = False
    try:
        if created_at:
            created_dt = _dt2.fromisoformat(str(created_at).replace("Z", "+00:00"))
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=_tz2.utc)
            age_days = (_dt2.now(_tz2.utc) - created_dt).total_seconds() / 86400.0
            is_new = age_days < 3.0
    except Exception:
        is_new = False

    completed = await db.workouts.count_documents({"user_id": user["id"], "completed": True})

    # Fresh account with no completions → suppress everything for the grace period.
    if is_new and completed == 0:
        return {"prompts": []}

    rows = await db.reassessment_prompts.find(
        {"user_id": user["id"], "dismissed": False},
        {"_id": 0},
    ).sort("created_at", -1).to_list(20)

    # Never surface a missed_workouts prompt for users who have zero
    # completed workouts (they can't have "missed sessions" — they're
    # brand new / haven't started training).
    if completed == 0:
        rows = [r for r in rows if r.get("kind") != "missed_workouts"]

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
    # Aviation-branding fields (§34)
    job_title: Optional[str] = None       # Captain, First Officer, Cabin Crew, Purser, …
    airline: Optional[str] = None
    home_base: Optional[str] = None       # e.g. "Dubai (DXB)"
    aircraft_type: Optional[str] = None
    route_focus: Optional[str] = None     # long-haul | short-haul | mixed
    preferred_visual_gender: Optional[str] = None


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

    Iter189g · Coach spec — return AT MOST 3 alternatives, each with a
    distinct `purpose`:
      * "equipment_swap"            — same movement, different kit
      * "easier_regression"         — same movement, lower demand
      * "injury_mobility_friendly"  — safer variant for a niggling injury / mobility limit

    Purpose-tagged alternatives come from `exercises_v2.alternatives_meta`
    if present. Legacy flat `alternatives: [name, name]` lists are still
    honoured for backward compat but capped at 3 items (no purpose label).

    Filter priority: equipment match > location fit > general fallback.
    """
    wanted = (name or "").strip()

    # 1) Coach-authored alternatives stored on exercises_v2 --------------
    try:
        v2 = await db.exercises_v2.find_one(
            {"exercise_name": {"$regex": f"^{re.escape(wanted)}$", "$options": "i"}},
            {"_id": 0, "alternatives": 1, "alternatives_meta": 1, "exercise_name": 1},
        )
        if v2:
            v2_alts: list[dict] = []
            # Prefer the new purpose-tagged shape.
            meta = v2.get("alternatives_meta") or []
            if isinstance(meta, list) and meta:
                # Iter189g · Deduplicate by purpose so we never return
                # two "equipment_swap" cards. Keep first occurrence.
                seen_purposes: set[str] = set()
                for entry in meta:
                    if not isinstance(entry, dict):
                        continue
                    n = str(entry.get("name") or "").strip()
                    p = str(entry.get("purpose") or "").strip().lower()
                    if not n or p in seen_purposes:
                        continue
                    if p not in ("equipment_swap", "easier_regression", "injury_mobility_friendly"):
                        continue
                    seen_purposes.add(p)
                    v2_alts.append({
                        "name": n,
                        "equipment": entry.get("equipment") or [],
                        "purpose": p,
                        "purpose_label": {
                            "equipment_swap": "Equipment swap",
                            "easier_regression": "Easier regression",
                            "injury_mobility_friendly": "Injury-friendly",
                        }[p],
                        "why": entry.get("why") or entry.get("reason") or "Coach-authored alternative.",
                    })
            # Fallback to legacy flat list (no purpose label). Cap at 3.
            elif v2.get("alternatives"):
                for a in v2["alternatives"]:
                    if isinstance(a, str) and a.strip():
                        v2_alts.append({"name": a.strip(), "equipment": [],
                                        "why": "Coach-authored alternative.",
                                        "purpose": None, "purpose_label": None})
                    elif isinstance(a, dict) and a.get("name"):
                        v2_alts.append({
                            "name": a["name"],
                            "equipment": a.get("equipment") or [],
                            "why": a.get("why") or a.get("reason") or "Coach-authored alternative.",
                            "purpose": None, "purpose_label": None,
                        })
                    if len(v2_alts) >= 3:
                        break
            if v2_alts:
                # Iter189g · Hard cap at 3, no matter the source.
                return {
                    "source": "v2_library",
                    "reason": "Louis has authored these alternatives for this exercise.",
                    "alternatives": v2_alts[:3],
                }
    except Exception as e:
        logger.warning(f"v2 alternatives lookup failed for {wanted}: {e}")

    # 2) Legacy hardcoded catalog -----------------------------------------
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
        # Iter189g · Cap at 3 with no purpose labels (legacy catalog
        # doesn't carry them).
        alts_scored = [
            {**a, "purpose": None, "purpose_label": None}
            for a in alts_scored[:3]
        ]
        return {
            "source": "catalog",
            "reason": "Atlas alternatives keep the same training objective using the equipment you have available.",
            "alternatives": alts_scored,
        }

    # Iter189g · No key match — return EMPTY list so the client can
    # render the "No alternatives available" empty state cleanly. The
    # previous generic bodyweight+dumbbell placeholders were confusing
    # (they weren't real exercises and had no video/how-to).
    return {
        "source": "none",
        "reason": "No alternatives configured for this exercise yet.",
        "alternatives": [],
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


# Iter 123 — Unregister this specific device's push token from the given
# user. Called on logout so notifications never leak to another user who
# logs into the same device. Never fails the logout: any transport error is
# logged non-fatally.
@api.post("/unregister-push", status_code=200)
async def unregister_push(body: UnregisterPushBody):
    try:
        resp = await push_client().post(
            "/api/v1/push/users/unregister",
            json=body.model_dump(exclude_none=True),
        )
        if resp.status_code == 401:
            logger.warning("EMERGENT_PUSH_KEY missing/placeholder — unregister skipped")
        elif resp.status_code == 404:
            # Endpoint variant fallback — some Emergent push versions use
            # DELETE on the device endpoint.
            try:
                await push_client().request(
                    "DELETE", "/api/v1/push/users/devices",
                    json=body.model_dump(exclude_none=True),
                )
            except Exception:
                pass
        elif resp.status_code >= 400:
            logger.warning("unregister_push non-2xx %s: %s",
                            resp.status_code, resp.text[:200])
    except Exception as e:
        # Non-blocking — logout must succeed even if the push service is down
        logger.warning("unregister_push failed (non-blocking): %s", e)
    return {"status": "unregistered"}


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
# ---------------------------------------------------------------------------
# Iter 82 — Day-of-week sanity check helper (used by roster upload path)
# ---------------------------------------------------------------------------

def _align_days_to_weekday_labels(days: list[dict]) -> tuple[list[dict], int, int]:
    """
    Detect and correct off-by-one day parsing on European DD/MM rosters
    (Etihad, Emirates, Qatar, BA, easyJet, Ryanair, KLM, LH, AF, TK, SQ).

    The vision model occasionally shifts every date by ±1 day when parsing a
    DD/MM column — for example, treating "Wed 01/07/2026" as 2 July because of
    a timezone or ordering ambiguity. This makes the ENTIRE calendar wrong.

    Logic:
      For every day dict that has BOTH a parsed `date` (ISO YYYY-MM-DD) and a
      printed `day_of_week` (Mon-Sun), compute the offset needed so that
      `datetime.date.fromisoformat(date).weekday()` == printed weekday. Take
      the mode offset across the whole roster. If a strong majority (≥50% of
      labelled rows) disagree with their printed weekday, shift EVERY day's
      date by that mode offset.

    Returns (days, shift_applied_days, n_labelled_disagreements).
    """
    import datetime as _dt_dow
    _WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    offsets: list[int] = []
    for d in days:
        ds = d.get("date")
        dow = str(d.get("day_of_week") or "").strip().lower()[:3]
        if not ds or dow not in _WEEKDAYS:
            continue
        try:
            parsed_day = _dt_dow.date.fromisoformat(ds)
        except Exception:
            continue
        diff = (_WEEKDAYS[dow] - parsed_day.weekday()) % 7
        if diff > 3:
            diff -= 7
        offsets.append(diff)
    if not offsets:
        return days, 0, 0
    from collections import Counter as _Counter
    mode_offset, mode_count = _Counter(offsets).most_common(1)[0]
    n_disagree = sum(1 for o in offsets if o != 0)
    if mode_offset != 0 and mode_count >= max(3, len(offsets) // 2):
        for d in days:
            ds = d.get("date")
            if not ds:
                continue
            try:
                d["date"] = (
                    _dt_dow.date.fromisoformat(ds) + _dt_dow.timedelta(days=mode_offset)
                ).isoformat()
            except Exception:
                pass
        days.sort(key=lambda d: d.get("date") or "")
        return days, mode_offset, n_disagree
    return days, 0, n_disagree



def _ensure_workout_content(doc: dict, user: dict) -> dict:
    """
    Iter 82 / Iter 83 — Hard gate: never persist a workout with zero *main*
    content on a training day.

    If the LLM / equipment resolver returns an empty `exercises` list on a
    non-rest day, we:
      * Replace the exercises with a bodyweight-safe strength_support fallback
        (works on any layover, home day, or unknown roster context).
      * Preserve any existing warmup / cooldown content instead of clobbering.
      * Set `needs_coach_review = True`.
      * Stamp a client-facing `change_reason` explaining the fallback.
      * Bump `validation_status` to `needs_review`.

    Rest days (day_type = 'off' / 'rest') are exempt — they intentionally have
    no content. Recovery walks / mobility-only sessions are also allowed to
    have zero `exercises` if they carry a mobility-oriented title AND warmup
    is populated (heuristic: "recovery", "mobility flow", "walk").
    """
    exs = doc.get("exercises") or []
    warm = doc.get("warmup") or []
    day_type = str(doc.get("day_type") or "").lower()
    title = str(doc.get("title") or "").lower()
    workout_type = str(doc.get("workout_type") or "").lower()
    focus_lc = str(doc.get("focus") or "").lower()
    src = str(doc.get("source") or "").lower()
    duration_min = doc.get("duration_min")
    # Iter 161 · Full Rest protection.
    # A day that is EXPLICITLY marked recovery / rest / off — either by
    # day_type, workout_type, focus, or title — must NEVER be automatically
    # converted into a bodyweight training session. Same protection for a
    # 0-minute "Full Rest" from the monthly-JSON importer, and any workout
    # authored by the coach (source=coach_manual) which is by definition
    # intentional. The coach can still edit these manually.
    is_rest = (
        ("rest" in day_type) or ("off" in day_type)
        or title.startswith("rest") or title.startswith("off")
        or "full rest" in title
        or workout_type in ("rest", "recovery", "off", "day_off")
        or focus_lc in ("rest", "recovery", "off")
        or (isinstance(duration_min, (int, float)) and int(duration_min) == 0)
        or src == "coach_manual"
    )
    # A pure mobility / recovery session (no equipment needed, warmup-only is OK)
    is_mobility_only = (
        (title.startswith("recovery ") or "recovery walk" in title
         or title == "mobility flow" or "pre/post-flight mobility" in title
         or "optional recovery" in title or title.startswith("standby activation"))
        and bool(warm)
    )
    # Iter 83.1 — thin-plan detection: a strength/conditioning workout with 1-2
    # exercises is broken (equipment resolver dropped most items). Treat as
    # empty and rebuild with the bodyweight fallback so the client sees a
    # proper session, not a single Goblet Squat pretending to be Upper Body.
    is_endurance = ("run" in (doc.get("session_type") or "").lower()
                    or "run" in title or (doc.get("focus") or "").lower() in {"long_run","easy_run","tempo","intervals"})
    is_strength_or_cond = (
        (doc.get("focus") or "").lower() in {"push", "pull", "legs", "full", "conditioning"}
        or ("strength" in title) or ("conditioning" in title)
    )
    thin_plan = (
        len(exs) < 3
        and is_strength_or_cond
        and not is_endurance
        and not is_rest
        and not is_mobility_only
    )
    if (exs and not thin_plan) or is_rest or is_mobility_only:
        return doc
    # Empty MAIN exercises on a training day — inject a session-type-matched fallback
    # so a "Long Run" day fills with a long run, not a strength block.
    try:
        from feature_workout_fallback import _stub_for_session_type
        # Pick the best fallback session_type from the doc metadata; default to strength_support.
        session_type = str(doc.get("session_type") or "").strip().lower()
        focus = str(doc.get("focus") or "").strip().lower()
        title_norm = title
        # Title has the strongest signal — override stored session_type if it's
        # clearly a different session on the tin (e.g. focus="long_run" but
        # title="Easy Run" was previously mis-tagged upstream).
        if "easy run" in title_norm and session_type != "easy_run":
            session_type = "easy_run"
        elif "tempo" in title_norm and session_type != "tempo":
            session_type = "tempo"
        elif "interval" in title_norm and session_type != "intervals":
            session_type = "intervals"
        elif "long run" in title_norm and session_type != "long_run":
            session_type = "long_run"
        # Iter 83.1 — strength/conditioning title routing → all map to
        # strength_support (bodyweight-safe) which gives a full 6-exercise plan.
        elif ("upper body" in title_norm or "lower body" in title_norm
              or "full body" in title_norm or "strength" in title_norm
              or "conditioning circuit" in title_norm) and session_type not in (
              "strength_support", "conditioning"):
            session_type = "strength_support"
        if not session_type:
            # Title first (more specific), then focus (broad bucket).
            if "long run" in title_norm:
                session_type = "long_run"
            elif "easy run" in title_norm:
                session_type = "easy_run"
            elif "tempo" in title_norm:
                session_type = "tempo"
            elif "interval" in title_norm:
                session_type = "intervals"
            elif "strength for runner" in title_norm:
                session_type = "strength_support"
            elif "conditioning" in title_norm:
                session_type = "conditioning"
            elif "swim" in title_norm:
                session_type = "swim"
            elif "bike" in title_norm or "cycle" in title_norm:
                session_type = "bike"
            elif focus == "long_run":
                session_type = "long_run"
            elif focus == "easy_run":
                session_type = "easy_run"
            elif focus == "tempo":
                session_type = "tempo"
            elif focus == "intervals":
                session_type = "intervals"
            elif focus == "strength_support":
                session_type = "strength_support"
            elif focus == "conditioning":
                session_type = "conditioning"
            else:
                session_type = "strength_support"
        # Iter 95h — honour the client's actual equipment. Previously the
        # heal forced `hotel_pref="bodyweight"` which stripped dumbbells /
        # kettlebells / barbells even if the client owned them at home.
        _profile = (user or {}).get("profile") or {}
        _equip = (
            (user or {}).get("equipment")
            or (user or {}).get("home_equipment")
            or _profile.get("equipment")
            or _profile.get("home_equipment")
            or []
        )
        _hotel_pref = (
            (user or {}).get("hotel_pref")
            or _profile.get("hotel_pref")
            or ("home" if any(e in {"dumbbells", "dumbbell", "kettlebells", "kettlebell", "barbell", "cable", "rower", "bench"} for e in _equip) else "bodyweight")
        )
        _ctx = {"hotel_pref": _hotel_pref, "equipment": _equip}
        stub = _stub_for_session_type(session_type, doc.get("date"), _ctx)
        if not stub:
            stub = _stub_for_session_type("strength_support", doc.get("date"), _ctx)
        if stub:
            # Preserve existing warmup if the plan already had one; only fill
            # gaps so we never overwrite legitimate warmup content.
            if not warm:
                doc["warmup"] = stub.get("warmup", [])
            doc["exercises"] = stub.get("exercises", [])
            if not doc.get("cooldown"):
                doc["cooldown"] = stub.get("cooldown", []) or [
                    "Slow diaphragmatic breathing x 10",
                    "Chest opener stretch 30s",
                    "Hip flexor stretch 30s each side",
                ]
            doc["title"] = doc.get("title") or stub.get("title") or "Strength Support"
            doc["location"] = doc.get("location") or stub.get("location") or "Home Workout"
            doc["duration_min"] = doc.get("duration_min") or stub.get("duration_min") or 40
            if not doc.get("focus"):
                doc["focus"] = stub.get("focus")
            if not doc.get("session_type"):
                doc["session_type"] = session_type
    except Exception:
        logger.exception("workout content fallback failed")
    doc["needs_coach_review"] = True
    # Iter 94i — clearer validation status. "adjusted_fallback" tells the client
    # UI (and Louis) that this workout was healed from empty, not just flagged.
    doc["validation_status"] = "adjusted_fallback"
    existing_reason = doc.get("change_reason")
    # Iter 94i — friendly wording per user directive: no more "content was
    # missing" scare copy. The coach task carries the full technical reason
    # for Louis.
    from feature_workout_fallback_v2 import CLIENT_FRIENDLY_FALLBACK_REASON
    fill_reason = CLIENT_FRIENDLY_FALLBACK_REASON
    doc["change_reason"] = f"{existing_reason}  · {fill_reason}" if existing_reason else fill_reason
    doc["insufficient_content_reason"] = doc.get("insufficient_content_reason") or "llm_returned_empty_exercises"
    doc["fallback_used"] = True
    doc["fallback_type"] = "safe_bodyweight_stub"
    return doc


async def _heal_workouts_batch(rows: list[dict], user: dict) -> list[dict]:
    """
    Iter 83 — Defence layer 2 of 4.

    Runs `_ensure_workout_content` over a batch of workout docs read from the
    DB. If any doc gets healed (empty exercises → filled), we persist the fix
    back to Mongo so the next read (from any client, any device) sees the
    healed version. Idempotent; safe to call on every read.

    Returns the (possibly-mutated) list of rows.
    """
    if not rows:
        return rows
    healed_rows: list[dict] = []
    to_persist: list[dict] = []
    to_unheal: list[dict] = []
    for w in rows:
        before_ex = w.get("exercises") or []
        # Never rewrite completed / user-touched sessions — respect the user's log.
        if w.get("completed") or w.get("override_applied") or w.get("override_generated"):
            healed_rows.append(w)
            continue
        # Iter 161 · Self-healing REVERT for the "Full Rest turned into a
        # bodyweight workout" bug. When a row was previously healed but the
        # underlying signal says it was originally a rest day, undo the heal
        # on first read after this code deploys — production DBs that
        # persisted the broken state get automatically corrected.
        wt = str(w.get("workout_type") or "").lower()
        title_lc = str(w.get("title") or "").lower()
        src_lc = str(w.get("source") or "").lower()
        was_healed = bool(
            w.get("fallback_used")
            or w.get("validation_status") == "adjusted_fallback"
            or w.get("auto_healed_at")
        )
        looks_rest_originally = (
            wt in ("recovery", "rest", "off", "day_off")
            or title_lc.startswith("rest") or title_lc.startswith("off")
            or "full rest" in title_lc
            or (src_lc == "coach_manual" and wt in ("recovery", "rest"))
        )
        if was_healed and looks_rest_originally and before_ex:
            # Reset to Full Rest shape.
            fixed = dict(w)
            fixed["exercises"] = []
            fixed["warmup"] = []
            fixed["cooldown"] = []
            fixed["duration_min"] = 0
            fixed["fallback_used"] = False
            fixed["validation_status"] = None
            fixed["fallback_type"] = None
            fixed["insufficient_content_reason"] = None
            fixed["needs_coach_review"] = False
            # Iter 161 · Also clear the Traffic-Light variants — otherwise the
            # client can still tap into green/amber/red and see the same
            # bodyweight-fallback content that was healed into place.
            variants = fixed.get("variants") or {}
            if isinstance(variants, dict):
                cleaned_variants: dict = {}
                for k, v in variants.items():
                    if not isinstance(v, dict):
                        cleaned_variants[k] = v
                        continue
                    vv = dict(v)
                    vv["exercises"] = []
                    vv["warmup"] = []
                    vv["cooldown"] = []
                    vv["duration_min"] = 0
                    cleaned_variants[k] = vv
                fixed["variants"] = cleaned_variants
            # Clean the client-facing "SESSION ADJUSTED / couldn't safely match"
            # boilerplate from change_reason, keep anything else the coach set.
            cr = fixed.get("change_reason") or ""
            if "couldn't safely match" in cr or "safe fallback" in cr.lower():
                parts = [p.strip() for p in cr.split("·")
                         if "couldn't safely match" not in p and "safe fallback" not in p.lower()]
                fixed["change_reason"] = " · ".join(p for p in parts if p) or None
            to_unheal.append(fixed)
            healed_rows.append(fixed)
            continue
        healed = _ensure_workout_content(dict(w), user)
        after_ex = healed.get("exercises") or []
        # Iter 84 (Task 1.1) — persist when the healer added ANY exercises, not
        # just when the doc was completely empty. Fixes the class where a
        # workout persisted with 1-2 exercises (equipment resolver dropped
        # everything but the bodyweight fallback) never reached the client
        # because the old `not before_ex` check treated it as already-content.
        if len(after_ex) > len(before_ex):
            # Persist the heal so it sticks — one document per touched row.
            to_persist.append(healed)
            healed_rows.append(healed)
        else:
            healed_rows.append(w)
    # Iter 161 · Persist reverts once per read.
    if to_unheal:
        for h in to_unheal:
            try:
                await db.workouts.update_one({"id": h["id"]}, {
                    "$set": {
                        "exercises": [],
                        "warmup": [],
                        "cooldown": [],
                        "duration_min": 0,
                        "fallback_used": False,
                        "validation_status": None,
                        "fallback_type": None,
                        "insufficient_content_reason": None,
                        "needs_coach_review": False,
                        "change_reason": h.get("change_reason"),
                        "variants": h.get("variants") or {},
                        "restored_from_fallback_at": now_iso(),
                    },
                    "$unset": {"auto_healed_at": ""},
                })
                logger.info(
                    "workout %s: reverted Full-Rest heal (user=%s date=%s title=%r)",
                    h.get("id"), h.get("user_id"), h.get("date"), h.get("title"),
                )
            except Exception:
                logger.exception("workout revert failed (non-fatal)")
    if to_persist:
        for h in to_persist:
            try:
                await db.workouts.update_one({"id": h["id"]}, {"$set": {
                    "exercises": h.get("exercises") or [],
                    "warmup": h.get("warmup") or [],
                    "cooldown": h.get("cooldown") or [],
                    "title": h.get("title"),
                    "location": h.get("location"),
                    "duration_min": h.get("duration_min"),
                    "focus": h.get("focus"),
                    "session_type": h.get("session_type"),
                    "needs_coach_review": h.get("needs_coach_review", True),
                    "validation_status": h.get("validation_status"),
                    "change_reason": h.get("change_reason"),
                    "insufficient_content_reason": h.get("insufficient_content_reason"),
                    "fallback_used": h.get("fallback_used", True),
                    "fallback_type": h.get("fallback_type", "safe_bodyweight_stub"),
                    "auto_healed_at": now_iso(),
                }})
                # Iter 94i — emit a coach task for every heal so Louis sees exactly
                # which workout got healed, when, and why. Dedup'd by workout_id.
                try:
                    from feature_workout_fallback_v2 import create_workout_fallback_task
                    prof = (user or {}).get("profile") or {}
                    await create_workout_fallback_task(
                        user=user,
                        workout=h,
                        reason=(
                            h.get("insufficient_content_reason")
                            or "Workout generator returned empty content. "
                               "Healed with safe bodyweight stub."
                        ),
                        equipment_available=prof.get("equipment") or [],
                        validation_errors=["empty_exercises_after_generation"],
                    )
                except Exception:
                    logger.exception("workout heal: coach task creation failed (non-fatal)")
            except Exception:
                logger.exception("heal-persist failed for workout %s", h.get("id"))
        # Iter 95h — after healing, sanity-check equipment alignment.
        # Notifies Louis + flags the doc if a client with real gear ended up
        # with a bodyweight-only workout.
        try:
            from feature_equipment_guard import enforce_and_notify
            for h in healed_rows:
                await enforce_and_notify(db, user, h, reason_source="heal")
        except Exception:
            logger.exception("equipment-guard sweep failed (non-fatal)")
        logger.info("workout heal-on-read: healed %d workouts for user=%s",
                    len(to_persist), user.get("id"))

    # ─── Iter189j · Stamp coach's `logging_type_override` onto embedded
    # exercises so the client's workout player reads the correct mode
    # (Timer / Cardio / Reps). The override was previously only visible
    # via /coach/library APIs — the client-facing /workouts/* endpoints
    # never merged it. Root cause of the "still shows reps for cardio
    # exercises" bug reported by the coach on production.
    #
    # Cost: ONE query per batch keyed on the union of (exercise_id +
    # exercise_name) referenced across all workouts. Non-fatal — a DB
    # hiccup here must never mask the healed workouts.
    try:
        overrides_by_id: dict[str, str] = {}
        overrides_by_name: dict[str, str] = {}
        wanted_ids: set[str] = set()
        wanted_names: set[str] = set()
        for wk in healed_rows:
            for block in ("exercises", "warmup", "cooldown"):
                for ex in (wk.get(block) or []):
                    if not isinstance(ex, dict):
                        continue
                    eid = ex.get("exercise_id")
                    nm = ex.get("name") or ex.get("exercise_name")
                    if eid:
                        wanted_ids.add(eid)
                    if nm and isinstance(nm, str):
                        wanted_names.add(nm.strip().lower())
        if wanted_ids or wanted_names:
            q_conds: list[dict] = []
            if wanted_ids:
                q_conds.append({"id": {"$in": list(wanted_ids)}})
            if wanted_names:
                q_conds.append({"$expr": {"$in": [
                    {"$toLower": {"$ifNull": ["$exercise_name", ""]}},
                    list(wanted_names),
                ]}})
            q = {
                "logging_type_override": {"$in": ["timer", "cardio", "reps"]},
                "$or": q_conds,
            }
            async for row in db.exercises_v2.find(
                q, {"_id": 0, "id": 1, "exercise_name": 1, "logging_type_override": 1},
            ):
                lt = row.get("logging_type_override")
                if not lt:
                    continue
                if row.get("id"):
                    overrides_by_id[row["id"]] = lt
                nm = (row.get("exercise_name") or "").strip().lower()
                if nm:
                    overrides_by_name[nm] = lt
        if overrides_by_id or overrides_by_name:
            for wk in healed_rows:
                for block in ("exercises", "warmup", "cooldown"):
                    for ex in (wk.get(block) or []):
                        if not isinstance(ex, dict):
                            continue
                        if ex.get("logging_type_override"):
                            continue
                        eid = ex.get("exercise_id")
                        nm = ex.get("name") or ex.get("exercise_name")
                        nm_lc = (nm or "").strip().lower() if isinstance(nm, str) else ""
                        lt = (
                            overrides_by_id.get(eid) if eid else None
                        ) or overrides_by_name.get(nm_lc)
                        if lt:
                            ex["logging_type_override"] = lt
    except Exception:
        logger.exception("iter189j: logging_type_override merge failed (non-fatal)")
    return healed_rows




ROSTER_SYSTEM = f"""You are an aviation-roster parser for airline crew (pilots and cabin crew).

Extract EVERY duty and off day the roster shows. Handle 3-day rosters up to multi-month rosters.
For each date output ONE object with these fields (populate what you can, leave unknown as null):
  date (YYYY-MM-DD, required)
  day_of_week — the exact 3-letter day-of-week label as printed next to the date in the roster ("Mon"|"Tue"|"Wed"|"Thu"|"Fri"|"Sat"|"Sun"). REQUIRED if visible — we use this to sanity-check the date and detect any off-by-one.
  day_type — one of: {", ".join(DAY_TYPES)}
  home_or_away — "home" | "away" | "unknown"
  report_time (HH:MM)
  duty_end_time (HH:MM)
  flights: [{{flight_no, from (IATA), to (IATA), dep (HH:MM), arr (HH:MM)}}]
  layover_city, layover_country, layover_nights (int)
  notes (short free text of any airline codes/duty codes you saw)
  confidence 0..1 — how sure you are about this day; put low confidence and day_type "Unknown/Needs Confirmation" if unsure.

CRITICAL DATE-FORMAT RULES (Etihad, Emirates, BA, Ryanair, easyJet, Qatar all use European DD/MM/YYYY):
 * European roster date columns are ALWAYS **DD/MM** or **DD/MM/YYYY** — never US MM/DD.
   Examples: "01/07/2026" MUST parse as 1 July 2026 (NOT January 7). "12/03/2026" MUST parse as 12 March 2026.
 * If the header shows a coverage range like "01/07/2026 - 31/07/2026" that unambiguously names ONE MONTH (July here), assume the ENTIRE roster is inside that month unless a row clearly straddles into the next.
 * DO NOT shift dates by timezone offsets. The date printed next to "Wed 01/07" IS Wed 1 July local — never Tue 30 June UTC.
 * When you emit a date, it must satisfy: `weekday_of(date) == day_of_week` (as printed in the roster). If your parse would violate this, RE-CHECK the date column before emitting.

AIRLINE-SPECIFIC HINTS (recognise these format variations):
 - **Emirates (EK)** — "DXB" base, [CA]/[FO]/[SFO]/[CP] position codes, flights like "EK508 DXB-BOM-DXB", "Day Off" / "Rest Day" text, "Pickup Time HH:MM" for report time, hotel + local contact on layover days, "DXB LT" timezone.
 - **British Airways (BA/EZG/CityFlyer)** — "LHR/LGW/LCY" base, "BA" flight prefix, "DO"/"OFF"/"REST"/"AL" codes, "SU"/"ES"/"LS" for standby types, "SIM" for sim, "RST" for rest.
 - **easyJet (U2/EZY)** — "LGW/STN/LTN/etc" base, "U2" flight prefix, "OFF"/"DO"/"HB"/"AB" codes, "STBY-AM/PM" split standby.
 - **Ryanair (FR)** — "DUB/STN/etc" base, "FR" flight prefix, "D/O" for day off, "STBY", "REST".
 - **Qatar (QR)** — "DOH" base, "QR" flight prefix, position codes CSD/CS/BS/CA/FA, "OFF"/"AL"/"REST"/"SIM".
 - **Etihad (EY)** — "AUH" base, "EY" flight prefix, "R"/"O"/"AL"/"SIM"/"OFC"/"STBY".
 - **Lufthansa (LH/CLH)** — "FRA/MUC" base, "LH" flight prefix, German codes: "F" (frei/off), "URL" (leave), "SBY", "PIC/FO/PU/FB".
 - **Air France (AF)** — "CDG/ORY" base, "AF" flight prefix, French codes: "REP" (rest), "CS" (standby), "VAC" (leave).
 - **KLM (KL)** — "AMS" base, "KL" flight prefix, "DO"/"RST"/"SBY"/"SIM".
 - **Delta/United/American (DL/UA/AA)** — 3-letter US bases (ATL/ORD/DFW etc), "F5"/"F4" reserve codes, "R"/"RES"/"VAC"/"OP" for open time.
 - **Turkish (TK)** — "IST" base, "TK" flight prefix, "OFF"/"REP"/"SIM"/"STBY".
 - **Singapore (SQ)** — "SIN" base, "SQ" flight prefix, "OFF"/"AL"/"MED"/"SIM".

GENERIC PATTERN RECOGNITION (apply across ALL airlines):
 - Any all-day cell containing only "OFF", "DO", "D/O", "REST", "R", "RST", "F", "FREE" → day_type = "Rest Day" or "Home Day". If followed/preceded by duty, prefer "Rest Day".
 - Any cell containing "AL", "VAC", "URL", "LEAVE", "ANNUAL", "ANN LV" → day_type = "Annual Leave".
 - Any cell containing "SIM", "SIMULATOR", "REC", "RECURRENT", "TRG", "TRAINING", "CBT" → day_type = "Simulator/Training Day".
 - Any cell containing "MED", "SICK", "OFC" (off-sick), "S/L" → set day_type to "Rest Day" and add a note.
 - Time-zone abbreviations: "LT" = local, "Z"/"UTC"/"GMT" = zulu, "BASE LT" = base local. Always emit report_time in the local timezone of the crew base.
 - Multi-leg trips: consecutive duty rows starting away-from-base → treat as Layover Arrival → Layover Full → Layover Departure sequence.
 - "SIM" alone on a day without a flight → day_type = "Simulator/Training Day".
 - Rows with "*" or "+" markers usually indicate next-day arrival — do NOT create a fake extra day; keep the entry on the departure date and note the arrival is next-day in `notes`.
 - Rows spanning multiple midnight boundaries (long-haul + layover) → the departure date is the "Layover Arrival Day", the return leg date is a "Layover Departure Day"; days in between are "Layover Full Day".

STANDBY DETECTION — when the row's code contains any of these tokens, day_type MUST be "Standby":
  STBY, SBY, RES, RSV, RESERVE, STDBY, HSBY, ASBY, SC (short-call), LC (long-call), on-call, "on call",
  "airport standby", "home standby", "available", "reserve duty", "night standby", "early standby",
  "STBY-AM", "STBY-PM", "F5", "F4", "OP" (open time reserve).
For any Standby day ALSO output these extra fields:
  standby_type — one of: "home_standby" | "airport_standby" | "reserve" | "short_call" | "long_call" |
                          "night_standby" | "early_standby" | "unknown_standby"
                  Rules:
                    * HSBY / "home standby" → home_standby
                    * ASBY / "airport standby" → airport_standby
                    * RES / RSV / RESERVE → reserve
                    * SC / "short call" / "short-call" → short_call
                    * LC / "long call" / "long-call" → long_call
                    * night/late-evening standby window → night_standby
                    * early-morning standby window → early_standby
                    * anything else → unknown_standby (also set standby_needs_confirmation=true)
  standby_start_time (HH:MM)   — start of the standby window if visible
  standby_end_time   (HH:MM)   — end of the window if visible
  standby_location   — "home" | "airport" | "unknown"
  standby_needs_confirmation — true when the type is uncertain

Classify carefully:
 - single-day duty starting and ending at the same base = Turnaround Duty (also Short-Haul or Long-Haul as appropriate)
 - overnight in another city = Layover Arrival Day (arrival day) followed by Layover Full Day(s) and Layover Departure Day (last)
 - duty starting before 05:00 = Early Report; ending after 23:00 = Late Finish; block covering 02:00-05:00 = Night Flight
 - do NOT invent dates or airports; if unclear, day_type="Unknown/Needs Confirmation" and confidence=0.3
 - do NOT skip days — if a date is present in the roster range but you cannot classify it, still emit it with day_type="Unknown/Needs Confirmation" so the client can edit.
 - RETURN AS MANY DAYS AS THE ROSTER SHOWS. Partial output is better than a giant error — extract every row you can confidently read.

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
    # Iter 109 — Phase A · A1
    # The client dashboard used to only see the newest active roster. When a
    # client uploaded July then August, July's days silently disappeared even
    # though both rosters remained active (they cover non-overlapping months).
    # We now return the newest roster as the "primary" but MERGE `days[]`
    # from every currently-active roster the user owns, preserving each day's
    # source roster id so the day-picker can route edits correctly.
    rosters = await db.rosters.find(
        {"user_id": user["id"], "is_active": True},
        {"_id": 0},
    ).sort("created_at", -1).to_list(60)
    if not rosters:
        return {}
    primary = rosters[0]
    merged_days: dict[str, dict] = {}
    for r in rosters:  # newest first
        rid = r.get("id")
        for d in (r.get("days") or []):
            ds = str(d.get("date") or "")[:10]
            if not ds or ds in merged_days:
                continue
            enriched = dict(d)
            enriched.setdefault("_source_roster_id", rid)
            merged_days[ds] = enriched
    days_out = sorted(merged_days.values(), key=lambda x: x.get("date") or "")
    out = dict(primary)
    out["days"] = days_out
    if days_out:
        out["start_date"] = days_out[0].get("date") or primary.get("start_date")
        out["end_date"] = days_out[-1].get("date") or primary.get("end_date")
    out["day_count"] = len(days_out)
    out["active_roster_ids"] = [r.get("id") for r in rosters if r.get("id")]
    out["expiry"] = _roster_expiry(primary)
    return out


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


async def _generation_heartbeat(job_id: str, start_progress: int = 80, cap_progress: int = 95, interval_s: float = 15.0) -> None:
    """Text-only heartbeat while the LLM generates workouts. The progress
    bar is driven exclusively by the per-week `_on_week_ready` callback so
    it reflects **real** completion, not wall-clock decay. This heartbeat
    only updates the message so the user sees the app is alive even if a
    Claude call takes a while — it never touches `progress` (that used to
    cause the bar to jump to 94% while weeks 3/4/5 were still cooking).
    """
    import asyncio as _asyncio
    ticks = 0
    try:
        while True:
            await _asyncio.sleep(interval_s)
            ticks += 1
            # Only add the "(still working)" tag after ~30s of silence so
            # short generations never see it at all.
            if ticks >= 2:
                try:
                    # Read current message so we can preserve any "Building
                    # week N of M" text set by _on_week_ready and just append
                    # a gentle "still working" nudge.
                    j = await db.roster_jobs.find_one({"id": job_id}, {"_id": 0, "message": 1, "progress": 1})
                    if not j:
                        return
                    prog = int(j.get("progress") or 0)
                    if prog >= cap_progress:
                        return
                    msg = str(j.get("message") or "Generating your personalised plan...")
                    if "(still working)" not in msg:
                        msg = f"{msg.rstrip('. ')} (still working)..."
                    await _set_job(job_id, message=msg)
                except Exception:
                    return
    except _asyncio.CancelledError:
        return


async def _open_coach_task_for_stuck_generation(client: dict, roster: dict, job_id: str, reason: str) -> None:
    """When plan generation times out or fails hard, notify the coach with a
    high-priority to-do so someone reviews the client's roster."""
    try:
        await _create_coach_task(
            client,
            "roster_plan_generation_issue",
            f"Roster plan generation issue: {client.get('name') or client.get('email')}",
            (
                f"{client.get('name') or client.get('email')}'s roster was uploaded successfully but the training "
                f"plan couldn't be generated automatically ({reason}). Roster ID {roster.get('id')} is saved and "
                f"visible in their calendar. Please retry plan generation or build a manual plan."
            ),
            priority="high",
            risk_level="high",
            category="programme",
            payload={"job_id": job_id, "roster_id": roster.get("id"), "reason": reason},
        )
    except Exception:
        logger.exception("could not create coach task for stuck plan generation")



@api.post("/roster/upload-and-generate")
async def roster_upload_and_generate(body: RosterUploadGenerateBody, user: dict = Depends(current_user)):
    """One-shot background job: parse roster → detect overlap → save → generate month.

    Returns {job_id} immediately. Poll GET /roster/jobs/{job_id} for progress."""
    # Iter 84 (Task 1.4) — defence-in-depth. Refuse to spin up a plan build
    # if the client is missing essentials. The frontend routes them to
    # /training-setup and re-tries.
    await _assert_profile_complete_or_409(user["id"])
    import asyncio as _asyncio
    job_id = new_id()
    _now = now_iso()
    await db.roster_jobs.insert_one({
        "id": job_id, "user_id": user["id"],
        "status": "queued", "stage": "uploading",
        "message": "Uploading your roster...",
        "progress": 1, "created_at": _now, "updated_at": _now,
        "filename": body.filename or "roster",
        "roster_id": None, "error": None, "overlap": None, "retry_count": 0,
    })

    async def _worker():
        path: Optional[str] = None
        try:
            await _set_job(job_id, status="processing", stage="uploading", progress=5, message="Uploading your roster...")
            path = await write_temp(body.file_base64, body.mime_type)
            await _set_job(job_id, stage="reading", progress=15, message="Reading your duty pattern...")

            # Gemini is intermittently flaky under load — a first attempt can
            # return empty text, a truncated JSON, or a transient 5xx. Retry
            # up to 3 times with exponential backoff before falling back to
            # Claude Sonnet 4.5 Vision. Different providers = uncorrelated
            # failure modes, which is exactly what bulletproof reliability
            # needs at production scale across many airlines.
            raw = ""
            parsed: Any = {}
            days: list[dict] = []
            last_err: Optional[str] = None
            parser_used = "gemini"

            async def _attempt(model_fn, model_label: str, timeout_s: float) -> tuple[str, Any, list[dict], Optional[str]]:
                try:
                    raw_ = await _asyncio.wait_for(
                        model_fn(
                            ROSTER_SYSTEM,
                            "Extract the complete roster shown. Return only JSON.",
                            path, body.mime_type,
                        ),
                        timeout=timeout_s,
                    )
                except Exception as ex:
                    return "", {}, [], f"{model_label} call: {ex}"
                try:
                    parsed_ = parse_json_from_text(raw_) if raw_ else {}
                except Exception as ex:
                    return raw_, {}, [], f"{model_label} JSON parse: {ex}"
                d_ = parsed_.get("days", []) if isinstance(parsed_, dict) else (parsed_ or [])
                if not d_:
                    return raw_, parsed_, [], f"{model_label}: parsed 0 days"
                return raw_, parsed_, d_, None

            # 1) Gemini x3 with backoff
            for attempt in range(3):
                if attempt > 0:
                    await _asyncio.sleep(2 ** attempt)  # 2s, 4s backoff
                    await _set_job(
                        job_id, stage="reading", progress=15,
                        message=f"Re-reading (attempt {attempt + 1} of 3)...",
                        retry_count=attempt,
                    )
                raw, parsed, days, last_err = await _attempt(call_gemini_file, "Gemini", 60.0)
                if days:
                    if attempt > 0:
                        logger.info("roster parse succeeded on Gemini attempt %d", attempt + 1)
                    break

            # 2) Claude Vision fallback — different provider, different failure
            # modes. Only reached when all 3 Gemini attempts failed.
            if not days:
                logger.warning("Gemini exhausted (last_err=%s) — falling back to Claude Vision", last_err)
                await _set_job(
                    job_id, stage="reading", progress=20,
                    message="Trying a second reader for accuracy...",
                    retry_count=3,
                )
                raw2, parsed2, days2, err2 = await _attempt(call_claude_file, "Claude", 90.0)
                if days2:
                    logger.info("roster parse succeeded via Claude Vision fallback")
                    raw, parsed, days = raw2, parsed2, days2
                    parser_used = "claude_vision"
                else:
                    last_err = f"{last_err} | claude: {err2}"

            await _set_job(job_id, stage="extracting", progress=30, message="Extracting duties...")
            if not days:
                # Both providers exhausted — surface an actionable message and
                # log the file for coach review so we never dead-end a client.
                logger.warning("roster extract exhausted ALL parsers; last_err=%s", last_err)
                # Best-effort: stash the raw response snapshot so Louis can
                # eyeball what the LLMs saw when they failed.
                try:
                    await db.roster_parse_failures.insert_one({
                        "id": new_id(),
                        "user_id": user["id"],
                        "job_id": job_id,
                        "filename": body.filename,
                        "mime": body.mime_type,
                        "last_err": last_err,
                        "raw_snippet": (raw or "")[:2000],
                        "created_at": now_iso(),
                    })
                except Exception:
                    logger.exception("failed to log roster parse failure — non-fatal")
                await _set_job(
                    job_id, status="failed", stage="extracting", progress=30,
                    error=(
                        "We tried Gemini three times and Claude once but couldn't extract duties. "
                        "This is very rare and usually means the file is scanned at very low resolution. "
                        "Please re-upload a clearer image, or paste your duty pattern into the manual entry below — "
                        "Louis has been notified and will review the file."
                    ),
                    message="Roster could not be read (after 4 attempts)",
                )
                return

            # Record which model succeeded so we can track real-world accuracy.
            await _set_job(job_id, parser_used=parser_used)

            # British Airways iOS-calendar adapter — isolated post-processor.
            # Runs only when BA-specific signatures (Rpt:HH:MMz, ends HH:MM,
            # BA route shape) score above the confidence threshold. Emirates /
            # RAK / easyJet / Qatar rosters pass through untouched.
            try:
                from feature_ba_roster_adapter import maybe_apply as _ba_maybe_apply
                _ba_res = _ba_maybe_apply(days, raw_text=raw)
                if _ba_res.get("applied"):
                    logger.info(
                        "roster job %s: BA adapter applied (confidence=%s, trips=%d, leave=%d)",
                        job_id,
                        _ba_res["detection"]["confidence"],
                        len(_ba_res.get("trips") or []),
                        len(_ba_res.get("leave_blocks") or []),
                    )
                    days = _ba_res["days"]
                    parser_used = f"{parser_used}+ba_adapter"
                    await _set_job(job_id, parser_used=parser_used)
            except Exception:
                logger.exception("BA adapter check failed — falling back to LLM output as-is")

            await _set_job(job_id, stage="detecting", progress=50, message="Detecting layovers and turnarounds...")
            days.sort(key=lambda d: d.get("date") or "")
            # Iter 82 — sanity check parsed dates against printed day_of_week labels.
            # Fixes off-by-one on Etihad / Emirates / Qatar DD/MM rosters.
            try:
                days, dow_shift, dow_disagree = _align_days_to_weekday_labels(days)
                if dow_shift != 0:
                    logger.warning(
                        f"[roster:{job_id}] day-of-week validator: shifted dates by {dow_shift:+d} "
                        f"day(s) — {dow_disagree} rows disagreed with printed weekday"
                    )
            except Exception:
                logger.exception("day-of-week sanity check failed (non-fatal)")

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
            # Programme context (goal, phase, target sessions) — computed once and
            # passed through generation → validation → persistence.
            programme_ctx = None
            try:
                from feature_programme_quality import programme_context_for_llm
                programme_ctx = await programme_context_for_llm(user, roster)
            except Exception:
                logger.exception("programme_context_for_llm failed — continuing without")
            # Generate workouts inline — with a hard timeout and a background
            # progress heartbeat so the client is never left at exactly 80% forever.
            heartbeat_task = _asyncio.create_task(_generation_heartbeat(job_id))

            # Streaming progress: as each 7-day chunk lands, bump the job progress
            # bar and stamp a human-readable message so the UI feels alive during
            # the 15-30s window when Claude is running.
            async def _on_week_ready(idx: int, total: int, weekly: list[dict]) -> None:
                # Progress spans 80% -> 95% during workout generation; 95->100 is
                # persistence + validation after gather completes.
                span = 15  # 80 -> 95
                pct = 80 + int(round(span * (idx + 1) / max(1, total)))
                await _set_job(
                    job_id,
                    progress=pct,
                    stage="generating",
                    message=f"Building week {idx + 1} of {total}...",
                )
            try:
                workouts = await _asyncio.wait_for(
                    _generate_month(user, roster, programme_ctx=programme_ctx, on_chunk=_on_week_ready),
                    timeout=180.0,
                )
            except _asyncio.TimeoutError:
                logger.warning("plan generation TIMEOUT in job %s (>180s) — falling back to template", job_id)
                workouts = []
            except Exception as e:
                logger.exception("plan generation raised in job %s: %s — falling back to template", job_id, e)
                workouts = []

            # Deterministic fallback: if the LLM produced nothing usable (budget
            # exceeded / timeout / provider error), give the client a real
            # starter plan built from templates and flag Louis to upgrade it.
            used_template = False
            try:
                from feature_workout_fallback import build_template_plan, is_empty_or_llm_failure
                from feature_hotel_system import load_hotel_lookup_for_roster
                from feature_progression import get_current_status
                if is_empty_or_llm_failure(workouts):
                    hotel_lookup = await load_hotel_lookup_for_roster(db, roster)
                    prog_status = await get_current_status(db, user["id"])
                    _eff = await _resolve_effective_goal_and_event(user["id"])
                    # Iter 94 (Phase 3.5) — pull live_state so the fallback
                    # respects auto-deload + pain-avoid the same way the LLM path does.
                    _live = (programme_ctx or {}).get("live_state") if programme_ctx else None
                    workouts = build_template_plan(
                        user, roster,
                        hotel_lookup=hotel_lookup,
                        progression_status=prog_status,
                        effective_goal=_eff,
                        live_state=_live,
                    )
                    used_template = bool(workouts)
                    if workouts:
                        try:
                            from feature_v2_resolver import apply_resolver_to_workouts
                            await apply_resolver_to_workouts(workouts, user=user, roster=roster)
                        except Exception:
                            logger.exception("v2_resolver on fallback failed (non-fatal)")
                        # Plan A3/A4 also apply to the deterministic fallback —
                        # the resolver may drop exercises which changes cap +
                        # min-content assessments.
                        try:
                            _apply_days_cap_and_min_content(workouts, user.get("profile") or {})
                        except Exception:
                            logger.exception("days-cap / min-content pass on fallback failed (non-fatal)")
                    if used_template:
                        logger.warning("plan generation used TEMPLATE fallback for job %s (LLM unavailable)", job_id)
            except Exception:
                logger.exception("template fallback failed unexpectedly")
            finally:
                heartbeat_task.cancel()
            # Safety guard (Plan D5) — if the roster was deleted/cancelled
            # while generation was running, abort persistence. A late job
            # completion must not repopulate a deleted plan.
            _roster_check = await db.rosters.find_one({"id": roster["id"]}, {"_id": 0, "is_active": 1, "status": 1})
            if _roster_check and (not _roster_check.get("is_active") or _roster_check.get("status") == "deleted_by_client"):
                logger.warning("roster %s was deleted/deactivated during generation — aborting job %s persist", roster["id"], job_id)
                await _set_job(
                    job_id, status="cancelled", stage="cancelled", progress=100,
                    message="Roster was replaced or deleted while your plan was being built.",
                    error=None, workouts_generated=0,
                )
                return
            _job_check = await db.gen_jobs.find_one({"id": job_id}, {"_id": 0, "status": 1})
            if _job_check and _job_check.get("status") == "cancelled":
                logger.warning("job %s was cancelled while generation was running — skipping persist", job_id)
                return

            # Iter 93 (Phase 3) — Post-LLM guardrail pass.
            # Enforce avoid_movement_patterns, strength_overload deltas,
            # duration bands, and weekly_shape_ideal BEFORE persistence.
            guardrail_report = None
            try:
                from feature_workout_guardrails import validate_batch
                gr = validate_batch(workouts, programme_ctx or {})
                workouts = gr["workouts"]
                guardrail_report = gr["report"]
                logger.info(
                    "guardrails: total=%d ok=%d healed=%d flagged=%d viol=%d",
                    guardrail_report["total"], guardrail_report["ok"],
                    guardrail_report["healed"], guardrail_report["flagged"],
                    len(guardrail_report["violations"]),
                )
            except Exception:
                logger.exception("guardrail validation failed — persisting raw workouts")

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
                    "source": "template" if used_template else "coaching_system",
                    # Plan A4 — carry through per-workout validation flags
                    "needs_coach_review": bool(used_template or w.get("needs_coach_review")),
                    "validation_status": w.get("validation_status") or ("ok" if not (used_template or w.get("needs_coach_review")) else "needs_review"),
                    "insufficient_content_reason": w.get("insufficient_content_reason"),
                    # Iter 93 (Phase 3) — carry guardrail violations for coach visibility
                    "guardrail_violations": w.get("guardrail_violations") or [],
                    # Plan A3 — optional-recovery flag from days-per-week cap
                    "optional": bool(w.get("optional", False)),
                    "source_reason": w.get("source_reason"),
                    # Traffic-light variants (Phase 3): LLM inline output preferred; falls back to prior stored or stub.
                    "variants": _merge_variants(w, prev),
                    "approved": prev.get("approved", False) if prev else False,
                    "completed": False,
                    "coach_notes": prev.get("coach_notes", "") if prev else "",
                    "coach_locked": False,
                    "created_at": prev.get("created_at", now_iso()) if prev else now_iso(),
                    "updated_at": now_iso(),
                }
                # Delete by (user_id, date) — the actual unique index key — so we
                # sweep collisions from prior rosters, manual entries, or seed
                # data. Deleting by "id" alone missed cross-roster collisions
                # and triggered E11000 on insert.
                try:
                    doc = _ensure_workout_content(doc, user)
                    await db.workouts.delete_many({"user_id": user["id"], "date": d})
                    await db.workouts.insert_one(doc)
                except Exception as e:
                    # One bad row must not kill the whole plan generation. Log
                    # + move on; user still gets the rest of their plan.
                    logger.warning("workout upsert failed for date=%s: %s", d, e)
                    continue
            # Safety net: if no workouts were actually persisted, do NOT silently
            # publish a "complete" job. Notify the coach with a high-priority
            # task and mark the job as needing review so the client sees a
            # helpful status instead of an empty 7-day view.
            persisted_count = await db.workouts.count_documents({"user_id": user["id"], "roster_id": roster["id"]})

            # Programme quality gate: validate the freshly generated batch and
            # persist a lightweight `programmes` record for coach visibility.
            # Failures here MUST NOT block the client's plan — they only flag
            # the programme as needs_review and open a coach task.
            try:
                if programme_ctx is not None:
                    from feature_programme_quality import validate_programme, persist_programme_record
                    persisted_workouts = await db.workouts.find(
                        {"user_id": user["id"], "roster_id": roster["id"]}, {"_id": 0}
                    ).sort("date", 1).to_list(500)
                    validation = validate_programme(user, roster, persisted_workouts, programme_ctx)
                    await persist_programme_record(
                        user, roster, persisted_workouts, programme_ctx, validation,
                        guardrail_report=guardrail_report,
                    )
                    if not validation.get("ok"):
                        # Flag all non-completed, non-locked workouts as needing review.
                        await db.workouts.update_many(
                            {"user_id": user["id"], "roster_id": roster["id"], "completed": {"$ne": True}, "coach_locked": {"$ne": True}},
                            {"$set": {"needs_coach_review": True, "updated_at": now_iso()}},
                        )
                        try:
                            await _open_coach_task_for_stuck_generation(
                                user, roster, job_id,
                                reason=f"programme validation failed: {', '.join(validation.get('errors') or [])[:200]}",
                            )
                        except Exception:
                            pass
            except Exception:
                logger.exception("programme quality gate failed — non-fatal, continuing")

            if persisted_count == 0:
                logger.warning("plan generation produced 0 workouts for user=%s roster=%s", user["id"], roster["id"])
                await _set_job(
                    job_id, status="needs_review", stage="generating", progress=95,
                    error="Your roster uploaded successfully, but your training plan needs review. Louis has been notified.",
                    message="Roster saved — plan needs review",
                    workouts_generated=0,
                )
                await _open_coach_task_for_stuck_generation(user, roster, job_id, reason="0 workouts generated")
                return

            # Iter 95n — hide workouts from the client for ~12-20 min and
            # queue a Louis chat message that lands at the same moment.
            # Non-fatal on failure — the workouts still exist, we just skip
            # the review-delay feel.
            try:
                from feature_roster_review_delay import apply_review_delay
                await apply_review_delay(db, user, roster)
            except Exception:
                logger.exception("apply_review_delay failed — non-fatal, workouts will be visible immediately")

            await _set_job(job_id, stage="coach", progress=98, message="Louis is looking over your week...")
            # Best-effort coach notification (silent-fail if push disabled)
            try:
                await _notify_coaches_of_new_roster(user, roster, job_id)
            except Exception:
                pass
            # If we used the template fallback, open a HIGH priority coach task
            # so Louis knows to upgrade the plan when LLM budget is restored.
            if used_template:
                try:
                    await _open_coach_task_for_stuck_generation(
                        user, roster, job_id,
                        reason="template fallback used (LLM unavailable — budget/timeout/error)",
                    )
                except Exception:
                    logger.exception("could not create fallback coach task")
            # Living Profile trigger — new roster invites a quick review
            try:
                await _emit_reassessment_prompt(
                    user["id"], "roster_uploaded",
                    "New roster detected — take 90s to update your availability so CrewFit adapts perfectly.",
                    {"roster_id": roster.get("id"), "days": len(roster.get("days") or [])},
                )
            except Exception:
                pass
            complete_message = (
                "Starter plan ready — Louis will refine your sessions soon."
                if used_template else "Your new plan is ready"
            )
            await _set_job(
                job_id,
                status="complete", stage="complete", progress=100,
                message=complete_message, completed_at=now_iso(),
                workouts_generated=len(workouts),
                used_template=used_template,
            )
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
    """Return the user's most recent job that the client should be aware of.

    Includes still-running jobs AND recently-failed / needs-review jobs (within
    the last 7 days) so the home screen can show an amber "plan needs review"
    banner and route to Retry Plan Generation. The client can dismiss stale
    review banners by setting job.client_acknowledged=true.
    """
    import datetime as _dtimp
    cutoff = (_dtimp.datetime.utcnow() - _dtimp.timedelta(days=7)).isoformat()
    j = await db.roster_jobs.find_one(
        {
            "user_id": user["id"],
            "$or": [
                {"status": {"$in": ["queued", "processing"]}},
                {
                    "status": {"$in": ["needs_review", "partial", "failed"]},
                    "updated_at": {"$gte": cutoff},
                    "client_acknowledged": {"$ne": True},
                },
            ],
        },
        {"_id": 0},
        sort=[("updated_at", -1), ("created_at", -1)],
    )
    return j or {}


@api.post("/roster/jobs/{job_id}/acknowledge")
async def roster_job_acknowledge(job_id: str, user: dict = Depends(current_user)):
    """Client dismisses a needs-review / failed / partial banner."""
    r = await db.roster_jobs.update_one(
        {"id": job_id, "user_id": user["id"]},
        {"$set": {"client_acknowledged": True, "acknowledged_at": now_iso()}},
    )
    if not r.matched_count:
        raise HTTPException(404, "Job not found")
    return {"ok": True}


@api.get("/roster/jobs/{job_id}")
async def roster_job_status(job_id: str, user: dict = Depends(current_user)):
    # Bugfix: when a coach uploads a roster on behalf of a client, the job
    # is stored with user_id = client_id and coach_id = coach.id. The
    # coach must be allowed to poll that job — otherwise the compact
    # roster upload button in the V2 workspace spins forever.
    query: dict = {"id": job_id}
    if user.get("role") == "coach":
        query["$or"] = [
            {"user_id": user["id"]},
            {"coach_id": user["id"]},
        ]
    else:
        query["user_id"] = user["id"]
    j = await db.roster_jobs.find_one(query, {"_id": 0})
    if not j:
        raise HTTPException(404, "Job not found")
    return j


@api.post("/roster/jobs/{job_id}/retry")
async def roster_job_retry(job_id: str, user: dict = Depends(current_user)):
    """Re-run ONLY the plan generation step for a job that timed out or failed.
    The client does not need to re-upload their roster."""
    import asyncio as _asyncio
    # Bugfix: coach must be able to retry jobs they created on behalf of a client.
    q: dict = {"id": job_id}
    if user.get("role") == "coach":
        q["$or"] = [{"user_id": user["id"]}, {"coach_id": user["id"]}]
    else:
        q["user_id"] = user["id"]
    j = await db.roster_jobs.find_one(q, {"_id": 0})
    if not j:
        raise HTTPException(404, "Job not found")
    if j.get("status") in ("queued", "processing"):
        return {"job_id": job_id, "status": j["status"]}
    roster_id = j.get("roster_id")
    if not roster_id:
        raise HTTPException(400, "This job did not save a roster — please re-upload the file.")
    # Roster is always stored under the CLIENT's user_id (even when coach uploaded).
    client_user_id = j.get("user_id") or user["id"]
    roster = await db.rosters.find_one({"id": roster_id, "user_id": client_user_id}, {"_id": 0})
    if not roster:
        raise HTTPException(404, "Original roster not found — please re-upload.")

    await _set_job(
        job_id,
        status="processing", stage="generating", progress=80,
        error=None, error_detail=None,
        message="Retrying plan generation...",
        retry_count=int(j.get("retry_count") or 0) + 1,
        retried_at=now_iso(),
    )

    async def _retry_worker():
        heartbeat_task = _asyncio.create_task(_generation_heartbeat(job_id))
        # Programme context (goal / phase / weekly target) — used for prompt
        # injection + validation + persistence, computed once.
        programme_ctx = None
        try:
            from feature_programme_quality import programme_context_for_llm
            programme_ctx = await programme_context_for_llm(user, roster)
        except Exception:
            logger.exception("retry: programme_context_for_llm failed")
        try:
            workouts = await _asyncio.wait_for(_generate_month(user, roster, programme_ctx=programme_ctx), timeout=180.0)
        except _asyncio.TimeoutError:
            logger.warning("retry TIMEOUT for job %s — falling back to template", job_id)
            workouts = []
        except Exception as e:
            logger.exception("retry plan generation raised for job %s: %s — falling back to template", job_id, e)
            workouts = []
        finally:
            heartbeat_task.cancel()

        # Deterministic fallback if the LLM is unavailable.
        used_template = False
        try:
            from feature_workout_fallback import build_template_plan, is_empty_or_llm_failure
            from feature_hotel_system import load_hotel_lookup_for_roster
            from feature_progression import get_current_status
            if is_empty_or_llm_failure(workouts):
                hotel_lookup = await load_hotel_lookup_for_roster(db, roster)
                prog_status = await get_current_status(db, user["id"])
                _eff = await _resolve_effective_goal_and_event(user["id"])
                workouts = build_template_plan(user, roster, hotel_lookup=hotel_lookup, progression_status=prog_status, effective_goal=_eff)
                used_template = bool(workouts)
                if workouts:
                    try:
                        from feature_v2_resolver import apply_resolver_to_workouts
                        await apply_resolver_to_workouts(workouts, user=user, roster=roster)
                    except Exception:
                        logger.exception("retry: v2_resolver on fallback failed (non-fatal)")
                if used_template:
                    logger.warning("retry job %s used TEMPLATE fallback (LLM unavailable)", job_id)
        except Exception:
            logger.exception("retry template fallback failed unexpectedly")

        # Reuse the same upsert logic as the main worker.
        # Iter 93 (Phase 3) — Post-LLM guardrail pass on retry path.
        guardrail_report_retry = None
        try:
            from feature_workout_guardrails import validate_batch
            gr = validate_batch(workouts, programme_ctx or {})
            workouts = gr["workouts"]
            guardrail_report_retry = gr["report"]
            logger.info("retry guardrails: total=%d flagged=%d",
                        guardrail_report_retry["total"], guardrail_report_retry["flagged"])
        except Exception:
            logger.exception("retry: guardrail validation failed")

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
                "source": "template" if used_template else "coaching_system",
                "needs_coach_review": bool(used_template or w.get("needs_coach_review")),
                "validation_status": w.get("validation_status") or ("ok" if not (used_template or w.get("needs_coach_review")) else "needs_review"),
                "guardrail_violations": w.get("guardrail_violations") or [],
                "variants": _merge_variants(w, prev),
                "approved": prev.get("approved", False) if prev else False,
                "completed": False,
                "coach_notes": prev.get("coach_notes", "") if prev else "",
                "coach_locked": False,
                "created_at": prev.get("created_at", now_iso()) if prev else now_iso(),
                "updated_at": now_iso(),
            }
            try:
                doc = _ensure_workout_content(doc, user)
                await db.workouts.delete_many({"user_id": user["id"], "date": d})
                await db.workouts.insert_one(doc)
            except Exception as e:
                logger.warning("retry workout upsert failed for date=%s: %s", d, e)
                continue
        persisted_count = await db.workouts.count_documents({"user_id": user["id"], "roster_id": roster["id"]})

        # Programme quality gate (retry path): validate + persist programme row.
        try:
            if programme_ctx is not None:
                from feature_programme_quality import validate_programme, persist_programme_record
                persisted_workouts = await db.workouts.find(
                    {"user_id": user["id"], "roster_id": roster["id"]}, {"_id": 0}
                ).sort("date", 1).to_list(500)
                validation = validate_programme(user, roster, persisted_workouts, programme_ctx)
                await persist_programme_record(
                    user, roster, persisted_workouts, programme_ctx, validation,
                    guardrail_report=guardrail_report_retry,
                )
                if not validation.get("ok"):
                    await db.workouts.update_many(
                        {"user_id": user["id"], "roster_id": roster["id"], "completed": {"$ne": True}, "coach_locked": {"$ne": True}},
                        {"$set": {"needs_coach_review": True, "updated_at": now_iso()}},
                    )
        except Exception:
            logger.exception("retry: programme quality gate failed — non-fatal")

        if persisted_count == 0:
            logger.warning("retry plan generation produced 0 workouts for user=%s roster=%s", user["id"], roster["id"])
            await _set_job(
                job_id, status="needs_review", stage="generating", progress=95,
                error="Your training plan still needs review. Louis has been notified.",
                message="Roster saved — plan needs review",
                workouts_generated=0,
            )
            await _open_coach_task_for_stuck_generation(user, roster, job_id, reason="0 workouts on retry")
            return
        await _set_job(job_id, stage="coach", progress=98, message="Preparing coach review...")
        try:
            await _notify_coaches_of_new_roster(user, roster, job_id)
        except Exception:
            pass
        if used_template:
            try:
                await _open_coach_task_for_stuck_generation(
                    user, roster, job_id,
                    reason="template fallback used on retry (LLM still unavailable)",
                )
            except Exception:
                pass
        complete_message = (
            "Starter plan ready — Louis will refine your sessions soon."
            if used_template else "Your new plan is ready"
        )
        await _set_job(
            job_id, status="complete", stage="complete", progress=100,
            message=complete_message, completed_at=now_iso(),
            workouts_generated=len(workouts),
            used_template=used_template,
        )

    _asyncio.create_task(_retry_worker())
    return {"job_id": job_id, "status": "processing"}


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


async def _reality_resolve_exercises(
    items: list[dict], *, user_id: str, workout_id: Optional[str], reason: str,
) -> list[dict]:
    """Iter 143 — Route every exercise item that appears inside a Today's
    Reality applied workout through the unified Exercise Library pipeline.

    Reuses ``resolve_or_draft_exercise`` (Iter 141/142) — no new resolver
    logic. Phase B fuzzy dedup applies. Approved rows are reused; genuinely
    new names get a draft filed. Every returned item carries a valid
    ``exercise_id`` and ``library_source`` so ``db.workouts`` never stores
    plain-text names via this path.
    """
    if not items:
        return items or []
    from feature_media_queue import resolve_or_draft_exercise
    user_stub = await db.users.find_one({"id": user_id}, {"_id": 0}) or {"id": user_id}
    out: list[dict] = []
    for raw in items:
        if not isinstance(raw, dict):
            out.append(raw)
            continue
        item = dict(raw)
        name = item.get("name") or item.get("exercise_name")
        if not name:
            out.append(item)
            continue
        try:
            ex_id = await resolve_or_draft_exercise(
                name, user=user_stub, reason=reason, workout_id=workout_id,
            )
        except Exception:
            logger.exception("reality_resolve: failed for %r", name)
            ex_id = None
        item["exercise_name"] = name
        if ex_id:
            item["exercise_id"] = ex_id
            row = await db.exercises_v2.find_one(
                {"id": ex_id},
                {"_id": 0, "status": 1, "approval_status": 1, "exercise_name": 1},
            ) or {}
            item["library_source"] = (
                "approved_match"
                if str(row.get("status")) in ("Approved", "Live")
                or str(row.get("approval_status")).lower() == "approved"
                else "draft"
            )
            if row.get("exercise_name"):
                item["exercise_name_display"] = row["exercise_name"]
        else:
            item["library_source"] = "unresolved"
        out.append(item)
    return out


async def _apply_reality_action(user_id: str, action: dict) -> dict:
    """Execute a single Reality action against db.workouts. Returns a change record."""
    # Iter 114 — Engine V2 clients: route to the V2 helper which mutates
    # plan_live_v2 placements + session_specs. Legacy V1 clients continue
    # through the block below untouched.
    #
    # Manual-Mode fix — V2 clients may carry `v2_flags.v2_default=True` yet
    # have NO active `plan_live_v2` doc (their workouts are coach-manual
    # rows in `db.workouts`). Previously we blindly called
    # `apply_reality_action_v2` for these clients, which returned
    # `changed: False` for every action because there was no placement to
    # mutate — so Today's Reality selections silently did nothing.
    # We now only route to V2 when both (a) the flag is set AND (b) an
    # active plan_live_v2 doc exists. Otherwise fall through to the V1 /
    # manual `db.workouts` mutator below.
    try:
        from feature_v2_client_bridge import user_is_v2, apply_reality_action_v2
        user_doc = await db.users.find_one(
            {"id": user_id}, {"_id": 0, "id": 1, "profile.v2_flags": 1},
        )
        if user_doc and await user_is_v2(db, user_doc):
            has_active_v2_plan = await db.plan_live_v2.find_one(
                {"client_id": user_id, "active": True}, {"_id": 1},
            )
            if has_active_v2_plan:
                v2_change = await apply_reality_action_v2(db, user_id, action)
                # Iter 162 · Legacy fallback. V2 users can carry mixed histories
                # (an active plan_live_v2 doc AND older `db.workouts` rows for
                # dates that pre-date the plan's start, or coach-manual
                # overrides that never made it into V2 placements). Previously
                # a "no placement found" returned `changed: False` and Today's
                # Reality did nothing on those older days — clients saw
                # "Nothing found" and the fatigue action silently no-op'd. We
                # now fall through to the legacy `db.workouts` mutator below
                # so the reality adjustment still lands on the actual workout
                # doc the client is looking at.
                if v2_change.get("changed"):
                    return v2_change
                logger.info(
                    "reality V2 miss for user=%s date=%s kind=%s — falling back to db.workouts",
                    user_id, action.get("date"), action.get("kind"),
                )
    except Exception:
        logger.exception("V2 reality action routing failed — falling back to V1")

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
        # Today's Reality is a client-initiated SITUATIONAL adaptation — not a
        # coach override. In Manual Mode every coach-manual workout carries
        # `coach_locked=True`, so the earlier "refuse to mutate locked" gate
        # blocked the entire feature. We now snapshot the original into
        # `reality_original_snapshot` and allow the adaptation. Completed
        # workouts are still protected — you can't retro-edit finished
        # sessions.
        if w.get("completed"):
            change["skipped_reason"] = "completed"
            return change
        if not w.get("reality_original_snapshot"):
            snap = {k: w.get(k) for k in (
                "title", "location", "duration_min", "focus", "day_load",
                "warmup", "exercises", "cooldown", "alternatives",
                "rationale", "key_session",
            )}
            snap["snapshotted_at"] = now_iso()
            try:
                await db.workouts.update_one(
                    {"id": w["id"]},
                    {"$set": {"reality_original_snapshot": snap}},
                )
                w["reality_original_snapshot"] = snap
            except Exception:
                logger.exception("reality: snapshot failed for wid=%s", w.get("id"))
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
            # Iter 143 — route every mobility exercise through the unified
            # Exercise Library pipeline before persisting.
            mob["exercises"] = await _reality_resolve_exercises(
                mob.get("exercises") or [],
                user_id=user_id, workout_id=w.get("id"),
                reason=f"reality_convert_mobility:{action.get('date') or ''}",
            )
            mob["warmup"] = await _reality_resolve_exercises(
                mob.get("warmup") or [],
                user_id=user_id, workout_id=w.get("id"),
                reason=f"reality_convert_mobility_warmup:{action.get('date') or ''}",
            )
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
            # Iter 143 — resolve exercise through Library pipeline.
            patch["exercises"] = await _reality_resolve_exercises(
                [{"name": "Easy walk or spin", "sets": 1, "reps": "20 min", "notes": "Nose-only breathing, zone 1"}],
                user_id=user_id, workout_id=w.get("id"),
                reason=f"reality_convert_recovery:{action.get('date') or ''}",
            )
            patch["rationale"] = (w.get("rationale") or "") + "  |  Converted to recovery."
        elif kind == "convert_walk":
            target = int(action.get("target_min") or 30)
            patch["day_load"] = "green"
            patch["title"] = "Walk"
            patch["location"] = "Outdoor"
            patch["duration_min"] = target
            patch["focus"] = "recovery"
            patch["warmup"] = []
            # Iter 143 — resolve exercise through Library pipeline.
            patch["exercises"] = await _reality_resolve_exercises(
                [{"name": "Steady walk", "sets": 1, "reps": f"{target} min", "notes": "Easy pace"}],
                user_id=user_id, workout_id=w.get("id"),
                reason=f"reality_convert_walk:{action.get('date') or ''}",
            )
            patch["rationale"] = (w.get("rationale") or "") + f"  |  Converted to {target}m walk."
        elif kind == "skip":
            rest = _build_rest_workout(d, action.get("reason") or "Client reality: skip today.")
            for k in ("day_load", "title", "location", "duration_min", "focus", "warmup", "exercises",
                     "alternatives", "rationale", "key_session", "override_generated", "override_reason"):
                patch[k] = rest.get(k, patch.get(k))
            patch["override_applied"] = True

        patch["override_applied"] = True
        patch["reality_adapted"] = True
        patch["reality_adapted_at"] = now_iso()
        patch["reality_action_kind"] = kind
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

    # Workouts — hide any whose `visible_from` review-delay is still in the
    # future so the client sees the plan appear naturally.
    _now_val = now_iso()
    workouts = await db.workouts.find({
        "user_id": user["id"], "date": {"$gte": start_iso, "$lte": end_iso},
        "$or": [
            {"visible_from": {"$exists": False}},
            {"visible_from": {"$lte": _now_val}},
        ],
    }, {"_id": 0}).sort("date", 1).to_list(2000)
    wk_map = {w["date"]: w for w in workouts}

    # Iter 109 — splice in Engine V2 synthetic workouts for engine_v2 clients
    # so the calendar timeline reflects the published Live plan.
    try:
        from feature_v2_client_bridge import synth_workouts_for_user
        v2_rows = await synth_workouts_for_user(
            db, user["id"], start_iso=start_iso, end_iso=end_iso,
        )
        for r in v2_rows:
            d = r.get("date")
            if not d:
                continue
            # Prefer legacy row on date collision; V2-flagged clients don't
            # have legacy workouts in practice but this keeps things safe.
            if d not in wk_map:
                wk_map[d] = r
    except Exception:
        logger.exception("calendar/timeline: V2 client bridge failed")

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
                # Iter 100 — expose roster context (flights + layover) so
                # calendar cells + home cards can render a tiny chip like
                # "BA113" / "DXB" next to the workout.
                "flights": (rday or {}).get("flights") or [],
                "layover_city": (rday or {}).get("layover_city"),
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


# === Iter 82 — client-side roster day correction ============================

class RosterDayCorrectionBody(BaseModel):
    date: str                          # YYYY-MM-DD of the day to correct
    day_type: Optional[str] = None     # any value from DAY_TYPES
    layover_city: Optional[str] = None
    layover_country: Optional[str] = None
    notes: Optional[str] = None


@api.patch("/roster/{rid}/day")
async def roster_day_correct(rid: str, body: RosterDayCorrectionBody, user: dict = Depends(current_user)):
    """
    Client-side quick correction of a roster day. Used from the client home
    when the parsed roster is wrong (e.g., off-by-one, wrong day_type).

    Surgically patches the single day and re-emits its load score. Downstream
    workouts on that date get `needs_coach_review` so Louis can rebuild.
    """
    r = await db.rosters.find_one({"id": rid, "user_id": user["id"]})
    if not r:
        raise HTTPException(404, "Roster not found")
    days = list(r.get("days") or [])
    target = None
    for i, d in enumerate(days):
        if d.get("date") == body.date:
            target = i
            break
    if target is None:
        raise HTTPException(404, f"No roster day found for {body.date}")
    day = days[target]
    if body.day_type is not None:
        day["day_type"] = body.day_type
        day["home_or_away"] = (
            "away" if "layover" in body.day_type.lower()
            else ("home" if "home" in body.day_type.lower() else day.get("home_or_away"))
        )
    if body.layover_city is not None:
        day["layover_city"] = body.layover_city.strip() or None
    if body.layover_country is not None:
        day["layover_country"] = body.layover_country.strip() or None
    if body.notes is not None:
        day["notes"] = body.notes
    day["client_corrected"] = True
    day["client_corrected_at"] = now_iso()
    try:
        day["load"] = score_load(day)
    except Exception:
        pass
    days[target] = day
    await db.rosters.update_one({"id": rid}, {"$set": {"days": days, "updated_at": now_iso()}})
    # Iter 94p — Client-driven day corrections DO NOT need coach approval.
    # Re-place the workout for that date immediately based on the new day_type.
    # Louis still gets a timeline entry so he can see what the client changed,
    # but the workout is NOT gated behind `needs_coach_review`.
    new_dtype = str(body.day_type or "").lower()
    # If the new day type is a heavy duty and there IS a workout, soft-cancel
    # it so the client sees an honest picture. If it's a home/off day and
    # there's no workout, that's the coach's job to re-plan — we don't invent
    # one out of thin air.
    heavy_terms = ("long", "night", "red_eye", "red-eye", "overnight", "heavy",
                   "direct flight", "flight", "layover")
    is_heavy = any(k in new_dtype for k in heavy_terms)
    rest_terms = ("off", "home")
    is_rest = any(k in new_dtype for k in rest_terms)
    if is_heavy:
        await db.workouts.update_many(
            {"user_id": user["id"], "date": body.date, "completed": {"$ne": True}, "coach_locked": {"$ne": True}},
            {"$set": {
                "day_type": body.day_type,
                "optional": True,
                "role": "roster_correction_soft",
                "change_reason": (
                    f"You changed today's duty to {body.day_type}. This session "
                    "is now optional — it will be re-placed automatically to a "
                    "more suitable day."
                ),
                "updated_at": now_iso(),
            }},
        )
    elif is_rest:
        # Client says today is home/off — clear any load restrictions on the
        # workout so it renders as normal.
        await db.workouts.update_many(
            {"user_id": user["id"], "date": body.date, "completed": {"$ne": True}, "coach_locked": {"$ne": True}},
            {"$set": {
                "day_type": body.day_type,
                "optional": False,
                "role": None,
                "change_reason": (
                    f"You changed today's duty to {body.day_type}. Your session is "
                    "ready to train."
                ),
                "updated_at": now_iso(),
            }},
        )
    else:
        # Other duty types: keep the workout intact, just mirror the day_type so
        # the UI shows the correct chip. Don't gate on coach review.
        await db.workouts.update_many(
            {"user_id": user["id"], "date": body.date, "completed": {"$ne": True}, "coach_locked": {"$ne": True}},
            {"$set": {
                "day_type": body.day_type,
                "change_reason": (
                    f"You updated today's duty to {body.day_type}."
                ),
                "updated_at": now_iso(),
            }},
        )
    # Timeline entry for Louis (audit, not a gate).
    try:
        await db.programme_timeline.insert_one({
            "id": new_id(),
            "user_id": user["id"],
            "roster_id": rid,
            "type": "client_roster_day_correction",
            "date": body.date,
            "new_day_type": body.day_type,
            "layover_city": body.layover_city,
            "created_at": now_iso(),
        })
    except Exception:
        pass
    return {"day": day}



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
    # Phase 1 additions (only overwrite if provided — don't clobber prior data)
    if body.gym_type is not None:
        payload["gym_type"] = body.gym_type
    if body.safe_outdoor_run is not None:
        payload["safe_outdoor_run"] = body.safe_outdoor_run
    # verified_by_coach can only be set via coach endpoint — never trust client
    if existing:
        new_conf = min(1.0, (existing.get("confidence", 0.5) + 0.15))
        await db.hotels.update_one({"id": existing["id"]}, {"$set": {**payload, "confidence": new_conf}, "$inc": {"submissions": 1}})
        return await db.hotels.find_one({"id": existing["id"]}, {"_id": 0})
    hotel = {
        "id": new_id(), "name_lower": q["name_lower"], "city_lower": q["city_lower"],
        "created_at": now, "submissions": 1, "confidence": 0.5,
        "gym_type": body.gym_type or "unknown",
        "safe_outdoor_run": body.safe_outdoor_run,
        "verified_by_coach": False,
        **payload,
    }
    await db.hotels.insert_one(hotel)
    return await db.hotels.find_one({"id": hotel["id"]}, {"_id": 0})


@api.get("/hotels/lookup")
async def hotels_lookup(query: Optional[str] = None, user: dict = Depends(current_user)):
    """
    Unified lookup: matches on name OR city (case-insensitive fuzzy).
    Returns hotels sorted by confidence desc, capped at 15.
    """
    q: dict = {}
    if query:
        s = query.strip().lower()
        if s:
            q = {"$or": [
                {"name_lower": {"$regex": re.escape(s)}},
                {"city_lower": {"$regex": re.escape(s)}},
            ]}
    rows = await db.hotels.find(q, {"_id": 0}).limit(50).to_list(50)
    rows.sort(key=lambda h: -(h.get("confidence") or 0.0))
    return rows[:15]


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


@api.post("/hotels/{hid}/confirm")
async def hotels_confirm(hid: str, body: HotelConfirmBody, user: dict = Depends(current_user)):
    """
    Client-side confirmation. Bumps confidence and optionally patches equipment.
    Never sets verified_by_coach — that's coach-only.
    """
    existing = await db.hotels.find_one({"id": hid})
    if not existing:
        raise HTTPException(404, "Hotel not found")
    patch: dict = {"last_confirmed_at": now_iso(), "last_submitted_by": user["id"]}
    if body.equipment is not None:
        # Shallow merge to preserve previously known items
        merged = dict(existing.get("equipment") or {})
        for k, v in (body.equipment or {}).items():
            merged[k] = bool(v)
        patch["equipment"] = merged
    if body.gym_type is not None:
        patch["gym_type"] = body.gym_type
    if body.gym_available is not None:
        patch["gym_available"] = body.gym_available
    if body.safe_outdoor_run is not None:
        patch["safe_outdoor_run"] = body.safe_outdoor_run
    if body.notes is not None:
        patch["notes"] = body.notes
    new_conf = min(1.0, (existing.get("confidence", 0.5) + 0.15))
    await db.hotels.update_one({"id": hid}, {"$set": {**patch, "confidence": new_conf}, "$inc": {"submissions": 1}})
    return await db.hotels.find_one({"id": hid}, {"_id": 0})


@api.patch("/hotels/{hid}")
async def hotels_patch(hid: str, body: HotelConfirmBody, user: dict = Depends(current_user)):
    """PATCH — same semantics as confirm, but does NOT bump submissions counter."""
    existing = await db.hotels.find_one({"id": hid})
    if not existing:
        raise HTTPException(404, "Hotel not found")
    patch: dict = {}
    if body.equipment is not None:
        merged = dict(existing.get("equipment") or {})
        for k, v in (body.equipment or {}).items():
            merged[k] = bool(v)
        patch["equipment"] = merged
    if body.gym_type is not None:
        patch["gym_type"] = body.gym_type
    if body.gym_available is not None:
        patch["gym_available"] = body.gym_available
    if body.safe_outdoor_run is not None:
        patch["safe_outdoor_run"] = body.safe_outdoor_run
    if body.notes is not None:
        patch["notes"] = body.notes
    if patch:
        await db.hotels.update_one({"id": hid}, {"$set": patch})
    return await db.hotels.find_one({"id": hid}, {"_id": 0})


@api.get("/hotels/pending-for-today")
async def hotels_pending_for_today(user: dict = Depends(current_user)):
    """
    For the client home: which upcoming (next 7 days) roster days are
    layovers that either:
      (a) have NO hotel attached, or
      (b) have a low-confidence hotel that needs re-confirmation.

    Returns a list of {date, layover_city, hotel_id, hotel_name, status, kind}
    """
    from feature_hotel_system import classify_stay, is_low_confidence
    import datetime as _dt
    r = await db.rosters.find_one({"user_id": user["id"], "active": True}, {"_id": 0})
    if not r:
        return []
    today = _dt.date.today().isoformat()
    horizon = (_dt.date.today() + _dt.timedelta(days=7)).isoformat()
    days = [d for d in (r.get("days") or []) if today <= (d.get("date") or "") <= horizon]
    # Order by date so we always sort chronologically
    days.sort(key=lambda d: d.get("date") or "")
    out: list[dict] = []
    for i, d in enumerate(days):
        nxt = days[i + 1] if i + 1 < len(days) else None
        kind = classify_stay(d, nxt)
        if kind != "layover":
            continue
        hid = d.get("hotel_id")
        if not hid:
            out.append({
                "date": d.get("date"),
                "layover_city": d.get("layover_city"),
                "layover_country": d.get("layover_country"),
                "hotel_id": None,
                "hotel_name": d.get("hotel_name"),
                "status": "missing",   # no hotel attached
                "kind": kind,
            })
            continue
        hotel = await db.hotels.find_one({"id": hid}, {"_id": 0})
        if not hotel:
            out.append({
                "date": d.get("date"), "layover_city": d.get("layover_city"),
                "hotel_id": hid, "hotel_name": d.get("hotel_name"),
                "status": "missing", "kind": kind,
            })
            continue
        if is_low_confidence(hotel):
            out.append({
                "date": d.get("date"), "layover_city": d.get("layover_city"),
                "layover_country": d.get("layover_country"),
                "hotel_id": hid, "hotel_name": hotel.get("name"),
                "status": "needs_confirm", "kind": kind,
                "confidence": hotel.get("confidence"),
            })
    return out


@api.get("/coach/hotels/review-queue")
async def coach_hotels_review_queue(user: dict = Depends(require_role("coach"))):
    """
    Coach review queue: low-confidence hotel submissions, most recent first.
    """
    rows = await db.hotels.find(
        {"$and": [
            {"$or": [{"verified_by_coach": {"$ne": True}}, {"verified_by_coach": {"$exists": False}}]},
            {"$or": [{"confidence": {"$lt": 0.7}}, {"confidence": {"$exists": False}}]},
        ]},
        {"_id": 0},
    ).sort([("last_confirmed_at", -1)]).limit(50).to_list(50)
    return rows


@api.post("/coach/hotels/{hid}/verify")
async def coach_hotels_verify(hid: str, user: dict = Depends(require_role("coach"))):
    """Coach marks a hotel profile as verified — bumps confidence and locks it."""
    existing = await db.hotels.find_one({"id": hid})
    if not existing:
        raise HTTPException(404, "Hotel not found")
    await db.hotels.update_one(
        {"id": hid},
        {"$set": {
            "verified_by_coach": True,
            "verified_by": user["id"],
            "verified_at": now_iso(),
            "confidence": min(1.0, (existing.get("confidence", 0.5) + 0.3)),
        }},
    )
    return await db.hotels.find_one({"id": hid}, {"_id": 0})


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

MARATHON & RUNNING-RACE RULES (STRICT — apply whenever profile.event_type_pref is
 marathon / half_marathon / 10k / 5k OR goal_key = "event" with a running race):
 - The weekly plan MUST include at least ONE long_run and ONE easy_run per week (unless
   the roster is a hard duty week with 6+ heavy days, in which case reduce to 1 easy_run).
 - Every "run" workout MUST use `focus` from: easy_run, long_run, tempo, intervals, zone2.
 - NEVER label a marathon client's session "Full Body Strength" — strength for runners is
   `title: "Strength for Runners"`, `focus: "full"`, with posterior-chain + single-leg emphasis,
   and NO heavy squat/deadlift in the 48h before the long run.
 - A "one-exercise long_run session" is ACCEPTABLE (e.g. Easy Run 40min) — but MUST include
   a warm-up (5min walk/jog), pace/RPE guidance, cool-down, and hydration/coaching notes.
 - Do NOT invent running paces if `current_ability`/`longest_recent` are unknown — use
   RPE 4–5 for easy, RPE 6–7 for tempo, RPE 8–9 for intervals with walk-jog recovery.
 - Respect `programme_context.weekly_shape_ideal` — it is the ideal session-type slot list
   for the client's phase. Deviate ONLY when the roster forces it (log the reason in the
   session's `rationale`).

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


async def _generate_month(
    user: dict, roster: dict,
    programme_ctx: Optional[dict] = None,
    on_chunk: Optional[Any] = None,
) -> list[dict]:
    """Chunk by 7-day windows so each Claude call stays well under the
    Cloudflare edge timeout (~60s). Concurrent by week.

    If `programme_ctx` is not supplied, we compute it here via
    `feature_programme_quality.programme_context_for_llm`. Callers that want
    to reuse the same context (for validation + persistence) should compute
    it once and pass it in.

    `on_chunk(chunk_index, total_chunks, chunk_workouts)` is invoked (awaited
    if coroutine) as each week's workouts come back from the LLM, so callers
    can stream progress to the client and persist incrementally. This is the
    key to the "workouts stream in as they're ready" UX — the calendar fills
    week-by-week instead of appearing all at once at the end.
    """
    import asyncio as _asyncio

    profile = user.get("profile", {}) or {}
    all_days = roster.get("days", []) or []
    if not all_days:
        return []

    # Programme context — goal, phase, weekly target, roster summary. Deterministic.
    if programme_ctx is None:
        try:
            from feature_programme_quality import programme_context_for_llm
            programme_ctx = await programme_context_for_llm(user, roster)
        except Exception:
            logger.exception("programme_context_for_llm failed — proceeding without it")
            programme_ctx = None

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

    # Attach hotel info once for the whole prompt set (parallelised — was
    # sequential and cost 1-3s of pure DB latency for a 28-day roster).
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

    # Pre-warm hotel_cache so `_day_for_prompt` is fully async-safe when we
    # gather. First pass: gather unique hotel ids and fetch concurrently.
    unique_hids = list({d.get("hotel_id") for d in all_days if d.get("hotel_id")})
    if unique_hids:
        fetched = await _asyncio.gather(
            *[db.hotels.find_one({"id": hid}, {"_id": 0}) for hid in unique_hids],
            return_exceptions=True,
        )
        for hid, h in zip(unique_hids, fetched):
            if isinstance(h, Exception) or not h:
                hotel_cache[hid] = {}
            else:
                hotel_cache[hid] = h

    enriched = await _asyncio.gather(*[_day_for_prompt(d) for d in all_days])

    # ---- Parser constraint injection ----
    # If any day has parser-generated labels (client_label, training_colour,
    # blocked, equipment_assumption from Etihad/Emirates parsers), surface
    # those into the prompt so the LLM understands what's on-limits and
    # what to avoid. Post-LLM we ALSO run enforce_constraints_on_workouts
    # as a deterministic safety net.
    try:
        from parser_constraints import constraint_block_for_prompt
        constraint_block = constraint_block_for_prompt(enriched)
    except Exception:
        logger.exception("constraint_block_for_prompt failed — continuing without block")
        constraint_block = []

    # ---- Coach Notes injection ----
    # Structured per-client overrides typed in by Louis (preferences,
    # cautions, goal override, weekly shape, free-form notes). BINDING —
    # takes precedence over inferred DNA where they conflict.
    try:
        from feature_coach_notes import coach_notes_for_prompt, apply_coach_note_overrides
        coach_notes_payload = coach_notes_for_prompt(user)
        # Iter 108 — extract structured signals (goal, freq, equipment) from
        # coach notes and OVERRIDE the profile dict passed to the LLM so
        # the model doesn't fall back to a mobility-heavy template when the
        # client's profile.goal is empty but the coach note says "marathon".
        profile = apply_coach_note_overrides(profile, user)
        try:
            _ov = {
                "goal": profile.get("_coach_note_override_goal"),
                "days": profile.get("_coach_note_override_days"),
                "equipment": profile.get("_coach_note_override_equipment"),
                "final_goal": profile.get("goal_type") or profile.get("goal"),
                "final_days": profile.get("training_days_per_week"),
            }
            if any(_ov[k] for k in ("goal","days","equipment")):
                logger.info("coach_note overrides applied for user=%s: %s", user.get("id"), _ov)
        except Exception:
            pass
    except Exception:
        logger.exception("coach_notes_for_prompt failed — continuing without coach notes")
        coach_notes_payload = None

    # Chunk into weeks of 7
    chunks = [enriched[i : i + 7] for i in range(0, len(enriched), 7)]

    async def _run_chunk(idx: int, total: int, chunk: list[dict]) -> list[dict]:
        # Constraint slice for THIS week only (dates in the chunk).
        chunk_dates = {d.get("date") for d in chunk}
        chunk_constraints = [c for c in constraint_block if c.get("date") in chunk_dates]
        prompt = (
            f"Client profile: {json.dumps(profile)[:2000]}\n"
            f"Coaching DNA (living profile): {json.dumps(dna_ctx)[:2500] if dna_ctx else 'not yet built'}\n"
            f"Coach Notes (BINDING overrides typed by Louis for this client — preferences, cautions, goal override, weekly shape): {json.dumps(coach_notes_payload)[:2200] if coach_notes_payload else 'None'}\n"
            f"Programme context (goal, phase, weekly target, roster summary, weekly_shape_ideal, strength_overload, live_state): {json.dumps(programme_ctx)[:4200] if programme_ctx else 'None'}\n"
            f"Event context: {json.dumps(event_context)[:1000] if event_context else 'None'}\n"
            f"Parser constraints (per-date labels from Etihad/Emirates roster analysis — BINDING): {json.dumps(chunk_constraints)[:2200] if chunk_constraints else 'None'}\n"
            f"Days to plan (chronological, 7-day chunk): {json.dumps(chunk)[:7500]}\n"
            "Design exactly one workout per date in this chunk. Return JSON. "
            "HARD RULES: (1) The number of REAL training sessions (focus not in recovery/mobility/rest) "
            "in each 7-day chunk MUST NOT exceed `profile.training_days_per_week`. Extra days MUST be "
            "focus='recovery' cards with title 'Optional Recovery Walk' or 'Mobility Flow'. "
            "(2) If `programme_context.weekly_shape_ideal` is present, hit those session-type slots in that "
            "order across the training days — DO NOT swap slots without a roster reason. "
            "(3) For endurance/event goals with `event_type_pref` set, the week MUST include at least one "
            "long_run and one easy_run (unless the roster is a hard duty week). "
            "(4) For NON-endurance goals, if `programme_context.strength_overload` is present, APPLY IT to primary lifts: "
            "adjust sets by `sets_delta`, target the `reps_target` range, apply `load_delta_pct` on the primary compound "
            "(BW load stays), and coach cues at the given `rpe`. If `adherence_note` is 'hold — <50% completed last week', "
            "DO NOT progress load or sets — repeat last week. Otherwise follow the delta. "
            "(5) LIVE STATE — if `programme_context.live_state` is present, obey it: "
            "(a) If `auto_deload_trigger=true` — this IS a deload week: cut volume 30-40%, drop hard sessions, keep movement quality high, and mention 'we're pulling back this week' in the rationale. "
            "(b) If `avoid_movement_patterns` is non-empty (e.g. ['overhead_press','deep_squat']) — DO NOT program any exercise matching those patterns. Substitute a safe alternative (e.g. floor press instead of overhead press, box squat instead of deep squat). "
            "(c) If `focus_shift_request.target` is set — bias the week toward it (e.g. 'strength' → protect the strength slot; 'running' → add an easy run; 'recovery' → convert one session to mobility). "
            "(d) If `coach_directives` has entries — TREAT THEM AS BINDING coaching instructions from the head coach; work them into the plan and reference them in the rationale for that day. "
            "(e) If `motivation_flag=='low'` — favour shorter, more achievable sessions (60% duration or one fewer set). "
            "(6) RECOVERY-FIRST DAYS — if a date appears in `programme_context.roster_summary.recovery_first_days`, that day is a long-haul flight into an 18h+ layover. DO NOT prescribe a hard session or a long run. Instead: (i) open the session with 10 min of mobility/breathing to decompress from the flight, (ii) follow with a moderate strength or easy run capped at RPE 7, (iii) keep total duration ≤45 min, (iv) explain in the rationale 'recovery mobility first, then a moderated session to use the layover window.' "
            "(7) TIERED FLIGHT RECOVERY — for each entry in `programme_context.roster_summary.recovery_tiered_days`, TAILOR the post-flight session to duty_hours: "
            "tier='short' (<6h) → 8-min airport-friendly mobility (standing only, no floor work); "
            "tier='medium' (6-11h) → 15-min classic mobility + breathing; "
            "tier='ulr' (≥12h) → 25-min ULR protocol with thoracic decompression, glute activation, and 4-7-8 / box breathing for sleep prep. Include hydration prompts on ULR days. "
            "Ensure workouts respect the client's Coaching DNA (motivation_style, coaching_style, recovery_risk, training_availability, biggest_weakness/opportunity, next_event) when available. "
            "Follow the Programme context strictly: match the weekly session target, keep the movement-mix hint balanced across the week, respect the current phase (Foundation/Build/Peak/Deload) — Deload weeks reduce volume by 30–40%. "
            "For EVERY workout, populate the `rationale` field with 1–2 short sentences answering 'Why this session?' — reference the phase, the roster context (e.g. long-haul day tomorrow, standby, layover in city X), and the client's goal. No client-facing 'AI' wording. "
            "TRAFFIC LIGHT VARIANTS — for EVERY workout, also populate a `variants` object with three keys: green, amber, red. "
            "`green` = the full planned session (identical to the top-level workout — title, duration_min, focus, warmup, exercises, rationale, plus `intensity_note` set to the target RPE guidance). "
            "`amber` = a ~65%-volume version of green for tired / short-on-time days: keep the same movement pattern but drop the last accessory if there are 5+ exercises, reduce sets ~35%, and shorten `duration_min` to about 65% of green. For any CARDIO exercise (run/walk/bike/row/swim/erg/treadmill/zone-2/steady-state/interval — anything logged by time or distance, not reps × weight), you MUST ALSO scale that exercise's per-exercise duration and distance to ~65% — reduce `duration_sec`, `duration_min`, `distance_m`, `distance_km` AND any time value embedded in the `reps` string (e.g. '30 min' → '20 min', '45s' → '29s', '5:00' → '3:15'). Do NOT reduce sets/reps on cardio; scale time/distance instead. Set `intensity_note` to guide RPE 6 / stop 2 reps shy. "
            "`red` = a context-aware recovery session (no strength work) of 10–15 minutes made of mobility + breathwork tailored to the roster day — e.g. long-haul day = calf drain + hip flexor release + box breathing; night flight = physiological sigh + 4-7-8 breath; layover = gentle mobility + nasal-breathing walk; standby = quiet flow you can do without changing clothes. Give it a clear `title`, `duration_min`, `focus='recovery'`, `exercises` (mobility/breath items with sets/reps or time durations), `rationale`, and `intensity_note='Restorative — no effort'`."
            " "
            "(8) PARSER CONSTRAINTS ARE BINDING. If a date appears in the `parser_constraints` block above, it comes from a strict Etihad/Emirates roster reader — TREAT IT AS TRUTH about that day's fatigue and equipment. Rules per `action`: "
            "action='rest_only' → prescribe focus='rest' with no exercises, duration_min=0, title 'Rest & Recovery'. "
            "action='recovery_only' → prescribe focus='recovery' with mobility + breath ONLY, duration_min ≤ `max_duration_min` (default 25). Never program strength, running, or intervals on a recovery_only day. "
            "action='moderated' → allowed session but cap `duration_min` at `max_duration_min` and drop any category listed in `blocked`. Bias toward mobility, easy_run, or hotel_strength. "
            "action='full_session' → normal programming allowed. "
            "For EVERY parser day, NEVER include any exercise mapped to a category in that day's `blocked` list (e.g. blocked=['main_strength','long_run'] → no barbell/kettlebell strength and no run >30 min). "
            "If `equipment` is 'hotel_or_bodyweight', constrain exercises to hotel-room or bodyweight variants only — no gym equipment. "
            "In the day's `rationale`, transparently reference the `client_label` (e.g. 'Louis kept this to mobility because you're returning from Sydney tonight'). NEVER mention 'AI', 'auto', or 'generated'."
            " "
            "(9) COACH NOTES ARE BINDING. If a `Coach Notes` block is present above, treat every non-empty slot as instructions typed by Louis for THIS client:"
            " `preferences` = things they love/hate/have access to (bias exercise selection accordingly);"
            " `cautions` = injuries or restrictions (NEVER program anything that violates them — even at the cost of an entire session);"
            " `goal_override` = the actual training goal (overrides `profile.goal_type` where they conflict);"
            " `weekly_shape` = the coach's preferred day-by-day pattern (respect it unless the roster forces otherwise);"
            " `notes` = free-form catch-all (interpret in context)."
            " Where Coach Notes and Coaching DNA conflict, Coach Notes ALWAYS win."
            " In the `rationale`, transparently reference the coach's note when it changed the session (e.g. 'Louis noted your left shoulder — swapped OHP for a landmine press today')."
        )
        chunk_workouts: list[dict] = []
        try:
            # Per-chunk cap so one slow LLM call cannot block sibling chunks or
            # the outer 3-minute deadline in the roster worker.
            raw = await _asyncio.wait_for(call_claude(WORKOUT_SYSTEM, prompt), timeout=75.0)
            parsed = parse_json_from_text(raw)
            chunk_workouts = parsed.get("workouts", []) if isinstance(parsed, dict) else (parsed or [])
        except _asyncio.TimeoutError:
            logger.warning("chunk gen TIMEOUT (75s) — skipping week %d/%d", idx + 1, total)
        except Exception as e:
            logger.warning("chunk gen failed for week %d/%d: %s", idx + 1, total, e)
        # Fire the streaming callback the moment this week's workouts are ready.
        # Errors in the callback must NOT propagate — they're a UX-nice-to-have,
        # not part of the generation contract.
        if on_chunk is not None and chunk_workouts:
            try:
                res = on_chunk(idx, total, chunk_workouts)
                if _asyncio.iscoroutine(res):
                    await res
            except Exception:
                logger.exception("on_chunk callback failed (non-fatal, week %d/%d)", idx + 1, total)
        return chunk_workouts

    # `return_exceptions=False` because _run_chunk swallows its own errors.
    # gather returns partial lists — even if some chunks are empty, we still
    # persist whatever the LLM produced instead of failing the entire plan.
    total_chunks = len(chunks)
    results = await _asyncio.gather(*[_run_chunk(i, total_chunks, c) for i, c in enumerate(chunks)])
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

    # ---- Phase 2 (Parser constraint enforcement) ----
    # Deterministic safety net that runs AFTER the LLM. Guarantees that no
    # workout violates the parser's per-day training_colour / blocked[] /
    # equipment_assumption / action. Ensures aviation crew never receive a
    # heavy strength session after a ULR / long-haul return, regardless of
    # what the LLM produced.
    try:
        from parser_constraints import enforce_constraints_on_workouts
        enforce_stats = enforce_constraints_on_workouts(unique, all_days)
        logger.info("parser_constraints stats: %s", enforce_stats)
    except Exception:
        logger.exception("parser constraint enforcement failed — continuing without")

    # Phase 5: Constrain every client-visible exercise to the approved V2
    # Exercise Library. Any exercise the LLM produced that has no library
    # match gets replaced with the closest approved substitute, and a
    # deduplicated draft exercise request is filed for Louis to review.
    # Unresolvable items are DROPPED (user directive: never expose unapproved
    # exercise names to clients).
    try:
        from feature_v2_resolver import apply_resolver_to_workouts
        stats = await apply_resolver_to_workouts(unique, user=user, roster=roster)
        logger.info("v2_resolver stats: %s", stats)
    except Exception:
        logger.exception("v2_resolver failed — falling through with raw LLM output")

    # Plan A3 — hard cap sessions per rolling 7-day window to
    # `profile.training_days_per_week`. Excess "real" training sessions
    # (non recovery/mobility/rest) are demoted to Optional Recovery so the
    # client never sees more workouts than they signed up for. Key sessions
    # (long runs, key strength) are preserved first.
    # Plan A4 — flag insufficient content on strength/gym/hotel/bodyweight
    # cards where duration doesn't match remaining exercises after resolver drops.
    try:
        _apply_days_cap_and_min_content(unique, profile)
    except Exception:
        logger.exception("days-cap / min-content pass failed (non-fatal)")

    # Iter 102 — Deterministic layover-day naming. Rewrite titles like
    #   "Hotel Gym Strength" → "ICN Layover Hotel Gym Strength"
    # so clients immediately see the workout was built around their roster.
    # Runs LAST (after LLM + resolver + days cap) so title stays accurate.
    try:
        from feature_layover_naming import apply_layover_naming
        _ln_stats = apply_layover_naming(unique, roster, airline=(roster or {}).get("airline"))
        if _ln_stats.get("renamed"):
            logger.info("layover_naming stats: %s", _ln_stats)
    except Exception:
        logger.exception("layover naming pass failed (non-fatal)")

    return unique


def _apply_days_cap_and_min_content(workouts: list[dict], profile: dict) -> None:
    """In-place: enforce training_days_per_week and flag incomplete cards.

    Rules (Plan A3):
    - If `training_days_per_week` is set (int 1-7), for each Mon-Sun window,
      count "real" training sessions (focus not in recovery/mobility/rest).
    - If count > cap, demote the LOWEST-priority extras to Optional Recovery
      (focus='recovery', title='Optional Recovery Walk', duration_min=20).
      Priority order preserved: key_session, long_run, then rest.

    Rules (Plan A4):
    - For any workout with duration_min >= 30 and focus not in
      (recovery, mobility, rest, long_run, tempo, intervals, zone2, swim, bike)
      that has fewer than 3 main exercises, set:
        needs_coach_review = True
        validation_status = "incomplete_content"
        insufficient_content_reason = "45-min strength card has <3 exercises"
    """
    import datetime as _dt

    ENDURANCE_FOCI = {"long_run", "long", "tempo", "intervals", "zone2", "swim", "bike", "brick", "race_prep"}
    LIGHT_FOCI = {"recovery", "mobility", "rest"}
    MIN_STRENGTH_EX = 3

    # ---- A3 first (days-per-week cap): demote excess sessions to Optional
    # Recovery so A4 (below) doesn't falsely flag demoted cards.
    try:
        cap = int(profile.get("training_days_per_week")) if profile.get("training_days_per_week") else None
    except Exception:
        cap = None
    if cap and 1 <= cap <= 7:
        def _week_key(iso: str) -> str:
            try:
                d = _dt.date.fromisoformat(iso[:10])
                monday = d - _dt.timedelta(days=d.weekday())
                return monday.isoformat()
            except Exception:
                return iso[:10]

        weeks: dict[str, list[dict]] = {}
        for w in workouts:
            iso = w.get("date")
            if not iso:
                continue
            weeks.setdefault(_week_key(iso), []).append(w)

        for wk, items in weeks.items():
            real = [w for w in items if str(w.get("focus") or "").lower() not in LIGHT_FOCI]
            if len(real) <= cap:
                continue

            def _priority(w: dict) -> int:
                if w.get("key_session"):
                    return 0
                f = str(w.get("focus") or "").lower()
                if f in ENDURANCE_FOCI:
                    return 1
                if f in ("push", "pull", "hinge", "squat", "legs", "full"):
                    return 2
                return 3

            real.sort(key=_priority)
            demote = real[cap:]
            for w in demote:
                w["title"] = "Optional Recovery Walk"
                w["focus"] = "recovery"
                w["day_load"] = "amber"
                w["duration_min"] = 20
                w["exercises"] = []
                w["warmup"] = [{"name": "Deep breathing x 5", "duration_sec": 45}]
                w["rationale"] = (
                    f"You picked {cap} training days per week — this day is now "
                    "an optional easy recovery walk. Skip it if you're tired; do it "
                    "if you're moving well."
                )
                w["optional"] = True
                w["source_reason"] = "days_per_week_cap"

    # ---- A4 (min-content) — runs AFTER A3 so demoted recovery cards are exempt
    for w in workouts:
        focus = str(w.get("focus") or "").lower()
        dur = int(w.get("duration_min") or 0)
        exs = w.get("exercises") or []
        if focus in LIGHT_FOCI or focus in ENDURANCE_FOCI:
            continue
        if dur >= 30 and len(exs) < MIN_STRENGTH_EX:
            w["needs_coach_review"] = True
            w["validation_status"] = "incomplete_content"
            w["insufficient_content_reason"] = (
                f"{dur}-min strength/gym card has only {len(exs)} exercise(s) — "
                f"needs at least {MIN_STRENGTH_EX}."
            )


@api.post("/workouts/generate-month")
async def workouts_generate_month(body: WorkoutGenerateMonthBody, user: dict = Depends(current_user)):
    """Kick off month generation in the background and return a job id immediately.
    The client polls /workouts/job/{id} until status='done'."""
    # Iter 84 (Task 1.4) — defence-in-depth for plan builds.
    await _assert_profile_complete_or_409(user["id"])
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
            # Programme context — reused for prompt injection, validation, persistence.
            programme_ctx = None
            try:
                from feature_programme_quality import programme_context_for_llm
                programme_ctx = await programme_context_for_llm(user, r)
            except Exception:
                logger.exception("generate-month: programme_context_for_llm failed")
            workouts = await _generate_month(user, r, programme_ctx=programme_ctx)
            # Setup-day gate: for BRAND-NEW clients, drop any workouts scheduled
            # on/before the gate so their first workout starts tomorrow (or the
            # next suitable roster day). Existing clients pass through unchanged.
            try:
                from feature_setup_day import filter_new_client_workouts
                workouts, _gate_meta = await filter_new_client_workouts(user, r, workouts)
            except Exception:
                logger.exception("setup-day gate skipped due to error")
            # Iter 93 (Phase 3) — Post-LLM guardrail pass (generate-month path).
            guardrail_report_month = None
            try:
                from feature_workout_guardrails import validate_batch
                gr = validate_batch(workouts, programme_ctx or {})
                workouts = gr["workouts"]
                guardrail_report_month = gr["report"]
            except Exception:
                logger.exception("generate-month: guardrail validation failed")
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
                    "source": "coaching_system",
                    "needs_coach_review": bool(w.get("needs_coach_review", False)),
                    "validation_status": w.get("validation_status") or ("ok" if not w.get("needs_coach_review") else "needs_review"),
                    "guardrail_violations": w.get("guardrail_violations") or [],
                    "variants": _merge_variants(w, prev),
                    "approved": prev.get("approved", False) if prev else False,
                    "completed": False,
                    "coach_notes": prev.get("coach_notes", "") if prev else "",
                    "coach_locked": False,
                    "created_at": prev.get("created_at", now_iso()) if prev else now_iso(),
                    "updated_at": now_iso(),
                }
                # Sweep by (user_id, date) — the true unique-index key — to
                # avoid E11000 when a prior roster or manual entry occupies
                # the same slot. See iteration 44 fix.
                try:
                    doc = _ensure_workout_content(doc, user)
                    await db.workouts.delete_many({"user_id": user["id"], "date": d})
                    await db.workouts.insert_one(doc)
                except Exception as e:
                    logger.warning("workout upsert failed for date=%s: %s", d, e)
                    continue
            dates_now = {w["date"] for w in workouts}
            await db.workouts.delete_many({
                "user_id": user["id"], "roster_id": body.roster_id,
                "date": {"$nin": list(dates_now)},
                "coach_locked": {"$ne": True}, "completed": {"$ne": True},
            })
            # Programme quality gate — validate + persist (parity with roster worker).
            try:
                if programme_ctx is not None:
                    from feature_programme_quality import validate_programme, persist_programme_record
                    persisted_workouts = await db.workouts.find(
                        {"user_id": user["id"], "roster_id": body.roster_id}, {"_id": 0}
                    ).sort("date", 1).to_list(500)
                    validation = validate_programme(user, r, persisted_workouts, programme_ctx)
                    await persist_programme_record(
                        user, r, persisted_workouts, programme_ctx, validation,
                        guardrail_report=guardrail_report_month,
                    )
                    if not validation.get("ok"):
                        await db.workouts.update_many(
                            {"user_id": user["id"], "roster_id": body.roster_id, "completed": {"$ne": True}, "coach_locked": {"$ne": True}},
                            {"$set": {"needs_coach_review": True, "updated_at": now_iso()}},
                        )
            except Exception:
                logger.exception("generate-month: programme quality gate failed — non-fatal")
            await db.gen_jobs.update_one({"id": job_id}, {"$set": {"status": "done", "done": len(workouts), "finished_at": now_iso()}})
            # JIT exercise-media scan: alert Louis if any newly generated
            # workouts reference exercises with missing artwork / video /
            # coaching points / approval within the next 7 days.
            try:
                from feature_exercise_content import run_exercise_media_scan
                asyncio.create_task(run_exercise_media_scan())
            except Exception:
                logger.exception("exercise media scan failed to enqueue after gen_month")
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
    # Iter 84 (Task 1.4) — defence-in-depth for plan builds.
    await _assert_profile_complete_or_409(user["id"])
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
            # Setup-day gate for brand-new clients.
            try:
                from feature_setup_day import filter_new_client_workouts
                workouts, _gate_meta = await filter_new_client_workouts(user, r, workouts)
            except Exception:
                logger.exception("setup-day gate skipped (regenerate)")
            # Phase 1 Manual Workout Builder — load active date-level overrides
            # once. Regenerate must NEVER silently overwrite a manual workout
            # or a date the coach has explicitly replaced/suppressed.
            try:
                from feature_coach_manual_workouts import get_active_override_dates
                _override_dates = set((await get_active_override_dates(user["id"])).keys())
            except Exception:
                _override_dates = set()
            skipped_dates: list[str] = []
            for w in workouts:
                d = w.get("date")
                if not d:
                    continue
                existing = await db.workouts.find_one({"user_id": user["id"], "roster_id": body.roster_id, "date": d}, {"_id": 0})
                if existing and (existing.get("coach_locked") or existing.get("completed") or existing.get("manual_lock")):
                    skipped_dates.append(d)
                    continue
                if d in _override_dates:
                    skipped_dates.append(d)
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
                    "source": "coaching_system",
                    "needs_coach_review": False,
                    "variants": _merge_variants(w, existing),
                    "approved": False,
                    "completed": False,
                    "coach_notes": existing.get("coach_notes", "") if existing else "",
                    "coach_locked": False,
                    "created_at": existing.get("created_at", now_iso()) if existing else now_iso(),
                    "updated_at": now_iso(),
                }
                # Sweep by (user_id, date) — see iteration 44 fix.
                try:
                    doc = _ensure_workout_content(doc, user)
                    await db.workouts.delete_many({"user_id": user["id"], "date": d})
                    await db.workouts.insert_one(doc)
                except Exception as e:
                    logger.warning("workout regenerate upsert failed for date=%s: %s", d, e)
                    continue
            await db.gen_jobs.update_one({"id": job_id}, {"$set": {"status": "done", "done": len(workouts), "finished_at": now_iso(), "skipped_dates": skipped_dates}})
            # JIT exercise-media scan after regenerate too.
            try:
                from feature_exercise_content import run_exercise_media_scan
                asyncio.create_task(run_exercise_media_scan())
            except Exception:
                logger.exception("exercise media scan failed to enqueue after regenerate")
        except Exception as e:
            logger.exception("regenerate job %s failed", job_id)
            await db.gen_jobs.update_one({"id": job_id}, {"$set": {"status": "failed", "error": str(e)[:400], "finished_at": now_iso()}})

    _asyncio.create_task(_worker())
    return {"status": "queued", "job_id": job_id, "total": len(sub_days)}


@api.get("/workouts/week")
async def workouts_week(user: dict = Depends(current_user)):
    rows = await db.workouts.find({"user_id": user["id"]}, {"_id": 0}).sort("date", 1).to_list(500)
    # Iter 95n — client must not see workouts that are still inside the
    # roster review window. Coach endpoints do NOT call this filter so Louis
    # can see + tweak them during the window.
    try:
        from feature_roster_review_delay import prune_pending
        rows = prune_pending(rows)
    except Exception:
        logger.exception("workouts/week: prune_pending failed — showing all")
    # Phase 1 Manual Workout Builder — apply active date-level overrides.
    # For every date that has an active replace_day/suppress_day override,
    # hide legacy GENERATED rows (source != coach_manual). Manual rows
    # (source == coach_manual) are always kept.
    override_dates: set[str] = set()
    try:
        from feature_coach_manual_workouts import get_active_override_dates, MANUAL_SOURCE
        overrides = await get_active_override_dates(user["id"])
        override_dates = set(overrides.keys())
        if override_dates:
            rows = [
                r for r in rows
                if (r.get("date") not in override_dates) or (r.get("source") == MANUAL_SOURCE)
            ]
    except Exception:
        logger.exception("workouts/week: manual override filter failed")
    # Iter 109 — Engine V2 clients read their published plan from plan_live_v2
    # (placements + session_specs), not from the legacy `workouts` collection.
    # Splice V2-derived rows in so the client home / calendar / workout screen
    # all "just work" without frontend changes. Rows are read-only.
    try:
        from feature_v2_client_bridge import synth_workouts_for_user
        v2_rows = await synth_workouts_for_user(
            db, user["id"], override_dates=override_dates,
        )
        if v2_rows:
            # Legacy rows for the same date should not double up with a V2
            # row (unlikely in practice — V2 clients have no legacy workouts —
            # but defend against it anyway).
            legacy_dates = {r.get("date") for r in rows if r.get("date")}
            for r in v2_rows:
                if r.get("date") not in legacy_dates:
                    rows.append(r)
            rows.sort(key=lambda r: r.get("date") or "")
    except Exception:
        logger.exception("workouts/week: V2 client bridge failed")
    # Iter 83 — Defence layer 2: read-time healing. Any workout that slipped
    # through the persistence guards with empty main exercises on a training
    # day gets healed on-read AND the DB row is updated so subsequent reads
    # (and other clients) see the fixed version. Silent, idempotent, safe.
    try:
        rows = await _heal_workouts_batch(rows, user)
    except Exception:
        logger.exception("workouts/week read-time healing failed")
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
    # Iter 109 — Engine V2 synthetic id path (v2p:{live_id}:{exposure_id})
    if wid.startswith("v2p:"):
        try:
            from feature_v2_client_bridge import synth_workout_by_wid
            # Coaches viewing a client's V2 workout still need the correct
            # owner in the query — accept the client id path when applicable.
            target_uid = user["id"]
            if user.get("role") == "coach":
                # Coach fetches: we don't know which client without the URL —
                # accept from Referer-less contexts by scanning any active
                # plan_live_v2 that contains this exposure_id.
                # (There's no cross-client leakage risk because the id embeds
                # the live_id which is tied to a specific client.)
                parts = wid.split(":", 2)
                if len(parts) == 3:
                    live_id = parts[1]
                    live = await db.plan_live_v2.find_one(
                        {"id": live_id, "active": True},
                        {"_id": 0, "client_id": 1},
                    )
                    if live:
                        target_uid = live["client_id"]
            row = await synth_workout_by_wid(db, wid, target_uid)
        except Exception:
            logger.exception("workout_get: V2 synthetic lookup failed for %s", wid)
            row = None
        if not row:
            raise HTTPException(404, "Not found")
        return row
    w = await db.workouts.find_one({"id": wid}, {"_id": 0})
    if not w:
        raise HTTPException(404, "Not found")
    if user["role"] == "client" and w["user_id"] != user["id"]:
        raise HTTPException(403, "Forbidden")
    # Iter 83 — Defence layer 2: read-time healing on the single-workout GET
    # too, so opening a workout page can never show an empty session.
    try:
        healed = await _heal_workouts_batch([w], user)
        w = healed[0] if healed else w
    except Exception:
        logger.exception("workout_get heal failed for %s", wid)
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


class SwapExerciseBody(BaseModel):
    exercise_index: int
    new_name: str
    reason: Optional[str] = None


@api.post("/workouts/{wid}/swap-exercise")
async def workout_swap_exercise(wid: str, body: SwapExerciseBody, user: dict = Depends(current_user)):
    """Client-driven exercise swap.

    Replaces the exercise at ``exercise_index`` with a new one selected from
    the Atlas alternatives list. Preserves sets / reps / rest / RPE / order /
    section — only the exercise identity changes. Writes an audit row to
    ``workout_exercise_swaps`` so Louis sees the change in the coach
    dashboard.

    Iter 130c — Engine V2 support. V2 workouts don't exist in
    ``db.workouts`` (they're synthesised on read from ``plan_live_v2``), so
    for `v2p:*` workout ids we persist the swap in
    ``plan_live_v2_exercise_swaps`` and let the client bridge apply it on
    every subsequent read. Prescription fields (sets/reps/rest/rpe) stay
    exactly as the coach programmed them because we only override the
    exercise NAME.
    """
    # Iter 130c — V2 workout branch (synthetic id `v2p:{live_id}:{eid}`)
    from feature_v2_client_bridge import V2_WORKOUT_ID_PREFIX, synth_workout_by_wid
    if (wid or "").startswith(V2_WORKOUT_ID_PREFIX):
        parts = wid.split(":", 2)
        if len(parts) < 3:
            raise HTTPException(400, "invalid V2 workout id")
        live_id, exposure_id = parts[1], parts[2]
        # Ownership + live plan lookup
        live = await db.plan_live_v2.find_one(
            {"id": live_id, "active": True},
            {"_id": 0, "id": 1, "client_id": 1, "placements": 1, "session_specs": 1},
        )
        if not live:
            raise HTTPException(404, "workout not found")
        client_id = live.get("client_id")
        if user["role"] == "client" and client_id != user["id"]:
            raise HTTPException(403, "forbidden")
        # Find the placement + spec so we can resolve the original name
        placement = next(
            (p for p in (live.get("placements") or []) if p.get("exposure_id") == exposure_id),
            None,
        )
        if not placement:
            raise HTTPException(404, "placement not found for this workout")
        spec = (live.get("session_specs") or {}).get(exposure_id) or {}
        pay_ex = ((spec.get("payload") or {}).get("exercises") or [])
        # An earlier swap may already exist for this (client, exposure, date,
        # index) — use it as our "current" name for audit continuity.
        existing_swap = await db.plan_live_v2_exercise_swaps.find_one(
            {"client_id": client_id, "exposure_id": exposure_id,
             "date": placement.get("date"),
             "exercise_index": body.exercise_index, "is_active": True},
            {"_id": 0}, sort=[("created_at", -1)],
        )
        if body.exercise_index < 0 or body.exercise_index >= len(pay_ex):
            raise HTTPException(400, "exercise_index out of range")
        original_name = (existing_swap or {}).get("original_name") or pay_ex[body.exercise_index].get("name")
        new_name = (body.new_name or "").strip()
        if not new_name:
            raise HTTPException(400, "new_name required")
        # Supersede any prior swap on the same slot
        await db.plan_live_v2_exercise_swaps.update_many(
            {"client_id": client_id, "exposure_id": exposure_id,
             "date": placement.get("date"),
             "exercise_index": body.exercise_index, "is_active": True},
            {"$set": {"is_active": False, "superseded_at": now_iso(),
                       "superseded_by": "swap"}},
        )
        await db.plan_live_v2_exercise_swaps.insert_one({
            "id": new_id(),
            "client_id": client_id,
            "live_id": live_id,
            "exposure_id": exposure_id,
            "date": placement.get("date"),
            "exercise_index": body.exercise_index,
            "original_name": original_name,
            "replacement_name": new_name,
            "reason": body.reason or "client_selected_alternative",
            "replaced_by": user["role"],
            "replaced_at": now_iso(),
            "created_at": now_iso(),
            "is_active": True,
        })
        # Audit trail (mirrors V1 swap for coach visibility)
        await db.workout_exercise_swaps.insert_one({
            "id": new_id(),
            "workout_id": wid,
            "user_id": client_id,
            "coach_id": None,
            "exercise_index": body.exercise_index,
            "original_name": original_name,
            "replacement_name": new_name,
            "reason": body.reason or "client_selected_alternative",
            "replaced_by": user["role"],
            "replaced_at": now_iso(),
            "date": placement.get("date"),
            "v2": True,
            "v2_exposure_id": exposure_id,
        })
        # Coach to-do — same shape as V1 branch
        if user["role"] == "client":
            try:
                client_meta = await db.users.find_one(
                    {"id": client_id}, {"_id": 0, "name": 1, "email": 1, "assigned_coach_id": 1},
                )
                await db.coach_tasks.insert_one({
                    "id": new_id(),
                    "kind": "client_exercise_swap",
                    "task_type": "client_exercise_swap",
                    "status": "todo",
                    "priority": "normal",
                    "user_id": client_id,
                    "client_id": client_id,
                    "workout_id": wid,
                    "date": placement.get("date"),
                    "exercise_index": body.exercise_index,
                    "original_name": original_name,
                    "replacement_name": new_name,
                    "reason": body.reason,
                    "assigned_coach_id": (client_meta or {}).get("assigned_coach_id"),
                    "client_name": (client_meta or {}).get("name") or (client_meta or {}).get("email"),
                    "created_at": now_iso(),
                    "title": f"Client swapped an exercise · {(client_meta or {}).get('name') or 'client'}",
                    "summary": f"{original_name} → {new_name}"
                               + (f" ({body.reason})" if body.reason else ""),
                })
            except Exception:
                logger.exception("Failed to create coach task for V2 exercise swap")
        # Return the synthesised workout with the swap applied
        fresh = await synth_workout_by_wid(db, wid, client_id)
        return {"ok": True, "workout": fresh, "swapped_index": body.exercise_index, "new_name": new_name}

    # Legacy V1 branch (unchanged)
    w = await db.workouts.find_one({"id": wid})
    if not w:
        raise HTTPException(404, "workout not found")
    if user["role"] == "client" and w.get("user_id") != user["id"]:
        raise HTTPException(403, "forbidden")

    exercises = list(w.get("exercises") or [])
    idx = body.exercise_index
    if idx < 0 or idx >= len(exercises):
        raise HTTPException(400, "exercise_index out of range")

    new_name = (body.new_name or "").strip()
    if not new_name:
        raise HTTPException(400, "new_name required")

    original = exercises[idx]
    # Preserve every prescription field, replace identity + media-linked bits.
    swapped = {
        **original,
        "name": new_name,
        "exercise_id": None,      # will re-resolve by name on next read
        "notes": body.reason or original.get("notes"),
        "swapped_from": original.get("name"),
        "swapped_at": now_iso(),
        "swapped_by": user["role"],
    }
    exercises[idx] = swapped
    await db.workouts.update_one(
        {"id": wid},
        {"$set": {"exercises": exercises, "updated_at": now_iso()}},
    )

    # Audit — coach visibility.
    await db.workout_exercise_swaps.insert_one({
        "id": new_id(),
        "workout_id": wid,
        "user_id": w.get("user_id"),
        "coach_id": w.get("coach_id"),
        "exercise_index": idx,
        "original_name": original.get("name"),
        "replacement_name": new_name,
        "reason": body.reason or "client_selected_alternative",
        "replaced_by": user["role"],
        "replaced_at": now_iso(),
        "date": w.get("date"),
    })

    # Coach to-do: when the CLIENT swaps an exercise, surface it in Louis's
    # exercise-review queue so he can eyeball whether the replacement fits
    # the client's programme + roster context.
    if user["role"] == "client":
        try:
            client_meta = await db.users.find_one(
                {"id": w.get("user_id")}, {"_id": 0, "name": 1, "email": 1, "assigned_coach_id": 1}
            )
            await db.coach_tasks.insert_one({
                "id": new_id(),
                "kind": "client_exercise_swap",
                "task_type": "client_exercise_swap",
                "status": "todo",
                "priority": "normal",
                "user_id": w.get("user_id"),
                "client_id": w.get("user_id"),
                "workout_id": wid,
                "date": w.get("date"),
                "exercise_index": idx,
                "original_name": original.get("name"),
                "replacement_name": new_name,
                "reason": body.reason,
                "assigned_coach_id": (client_meta or {}).get("assigned_coach_id"),
                "client_name": (client_meta or {}).get("name") or (client_meta or {}).get("email"),
                "created_at": now_iso(),
                "title": f"Client swapped an exercise · {(client_meta or {}).get('name') or 'client'}",
                "summary": f"{original.get('name')} → {new_name}"
                           + (f" ({body.reason})" if body.reason else ""),
            })
        except Exception:
            logger.exception("Failed to create coach task for client exercise swap")

    fresh = await db.workouts.find_one({"id": wid}, {"_id": 0})
    return {"ok": True, "workout": fresh, "swapped_index": idx, "new_name": new_name}


@api.get("/coach/exercise-swaps")
async def coach_recent_swaps(days: int = 30, user: dict = Depends(current_user)):
    """Recent client-initiated exercise swaps. Coach + admin only."""
    if user["role"] not in ("coach", "admin"):
        raise HTTPException(403, "forbidden")
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 90)))).isoformat()
    rows = await db.workout_exercise_swaps.find(
        {"replaced_at": {"$gte": since}}, {"_id": 0},
    ).sort("replaced_at", -1).to_list(200)
    # Enrich with user name for the dashboard.
    user_ids = {r.get("user_id") for r in rows if r.get("user_id")}
    users = {u["id"]: u.get("name") async for u in db.users.find({"id": {"$in": list(user_ids)}}, {"id": 1, "name": 1})}
    for r in rows:
        r["user_name"] = users.get(r.get("user_id"), "Client")
    return {"swaps": rows, "count": len(rows)}



# ------------------------------------------------------------------
# Client-driven "Move this session to another day" — reuses the same
# reality-move logic Louis uses so guard-rails (locked / completed /
# same-day) are enforced consistently. Louis is CC'd automatically.
# ------------------------------------------------------------------

class MoveWorkoutBody(BaseModel):
    to_date: str  # ISO YYYY-MM-DD
    reason: Optional[str] = None


@api.post("/workouts/{wid}/move")
async def workout_move(wid: str, body: MoveWorkoutBody, user: dict = Depends(current_user)):
    """Client (or coach) moves a session from its current date to another day.

    Reuses the existing `_apply_reality_action("move")` swap semantics so:
      * if the target date has a session, the two swap payloads.
      * if the target date is empty, the session's date is updated and a rest
        day is left behind on the old date.
    Guard-rails:
      * refuses if source is completed / coach-locked
      * refuses if target is completed / coach-locked
      * refuses if to_date is in the past
    Records to `move_history` and notifies Louis so it appears in the coach
    change log — never mentions "AI", framed as the client rearranging their
    own plan.
    """
    w = await db.workouts.find_one({"id": wid}, {"_id": 0})
    if not w:
        raise HTTPException(404, "workout not found")
    if user["role"] == "client" and w.get("user_id") != user["id"]:
        raise HTTPException(403, "forbidden")

    from_date = w.get("date")
    to_date = (body.to_date or "").strip()
    if not from_date or not to_date:
        raise HTTPException(400, "invalid dates")
    if to_date == from_date:
        raise HTTPException(400, "target is the same as current date")

    # Past-date guard (allow today).
    try:
        today = datetime.now(timezone.utc).date().isoformat()
    except Exception:
        today = None
    if today and to_date < today:
        raise HTTPException(400, "cannot move a session to a past date")

    if w.get("completed"):
        raise HTTPException(400, "session already completed — can't move")
    if w.get("coach_locked") and user.get("role") == "client":
        raise HTTPException(400, "session is locked by Louis — message him to swap")

    # Delegate to the proven reality-move engine.
    change = await _apply_reality_action(w["user_id"], {
        "kind": "move",
        "from_date": from_date,
        "to_date": to_date,
    })
    if not change.get("changed"):
        reason = change.get("skipped_reason") or "unable to move"
        raise HTTPException(400, reason)

    # Audit trail — surfaced in the coach change log and reality history.
    try:
        await db.move_history.insert_one({
            "id": new_id(),
            "user_id": w["user_id"],
            "reality_event_id": None,
            "reality_kind": "client_move",
            "reality_label": "Session moved by client",
            "date": from_date,
            "option_id": "client_move",
            "option_title": f"Moved to {to_date}",
            "option_why": body.reason or "",
            "changes": [change],
            "actor_id": user["id"],
            "actor_role": user.get("role", "client"),
            "coach_mode": "self_serve",
            "created_at": now_iso(),
        })
    except Exception:
        logger.exception("client move — move_history insert failed")

    # Notify Louis so the change appears in the coach dashboard change log.
    try:
        await db.coach_alerts.insert_one({
            "id": new_id(),
            "client_id": w["user_id"],
            "client_name": user.get("name") or user.get("email"),
            "kind": "client_moved_session",
            "date": from_date,
            "to_date": to_date,
            "workout_id": w["id"],
            "reason": body.reason or "",
            "created_at": now_iso(),
            "read": False,
        })
    except Exception:
        logger.exception("client move — coach_alerts insert failed")

    return {
        "status": "moved",
        "from_date": from_date,
        "to_date": to_date,
        "change": change,
    }


@api.post("/workouts/{wid}/complete")
async def workout_complete(wid: str, body: WorkoutCompleteBody, user: dict = Depends(current_user)):
    # --- Iter 101 · Quick rating + selective coach-review task ------------
    # Ratings that require Louis's attention. Client notes and pain reports
    # also lift this to needs_coach_review, per spec.
    ATTN_RATINGS = {"heavy_turbulence", "diverted"}
    rating = body.rating if body.rating in {
        "smooth_flight", "light_turbulence", "heavy_turbulence", "diverted",
    } else None
    optional_note = (body.optional_note or "").strip() or None
    pain_reported = bool(body.pain_reported) if body.pain_reported is not None else None
    pain_note = (body.pain_note or "").strip() or None
    # Pain only asked for heavy_turbulence / diverted per spec; ignore
    # accidental pain payload from other ratings.
    if rating not in ATTN_RATINGS:
        pain_reported = None
        pain_note = None

    needs_coach_review = bool(
        (rating in ATTN_RATINGS)
        or (pain_reported is True)
        or (optional_note is not None)
    )

    completed_at = now_iso()
    completion_meta = body.model_dump()
    # Overwrite normalised values so the DB record matches server rules.
    completion_meta.update({
        "rating": rating,
        "optional_note": optional_note,
        "pain_reported": pain_reported,
        "pain_note": pain_note,
        "needs_coach_review": needs_coach_review,
    })

    update_set = {
        "completed": True,
        "completed_at": completed_at,
        "completion": completion_meta,
        # Duplicated top-level for cheap coach-side filtering.
        "rating": rating,
        "needs_coach_review": needs_coach_review,
    }
    await db.workouts.update_one(
        {"id": wid, "user_id": user["id"]},
        {"$set": update_set},
    )
    doc = await db.workouts.find_one({"id": wid}, {"_id": 0})

    # Emit a coach task ONLY when the rules trigger.
    if needs_coach_review and doc:
        try:
            reasons: list[str] = []
            if rating == "heavy_turbulence":
                reasons.append("Rated Heavy turbulence")
            if rating == "diverted":
                reasons.append("Rated Diverted (couldn't finish)")
            if pain_reported is True:
                reasons.append("Reported pain / discomfort")
            if optional_note is not None:
                reasons.append("Client left a note")
            summary_bits: list[str] = list(reasons)
            if pain_note:
                summary_bits.append(f"Pain location: {pain_note}")
            if optional_note:
                summary_bits.append(f'Note: "{optional_note[:180]}"')
            await db.coach_tasks.insert_one({
                "id": new_id(),
                "task_type": "workout_review",
                "kind": "workout_review",
                "status": "todo",
                "priority": "high" if (rating in ATTN_RATINGS or pain_reported is True) else "normal",
                "user_id": user["id"],
                "client_id": user["id"],
                "client_name": user.get("name") or user.get("email"),
                "workout_id": wid,
                "workout_date": doc.get("date"),
                "workout_title": doc.get("title"),
                "rating": rating,
                "reasons": reasons,
                "title": f"Review workout · {user.get('name') or 'client'}",
                "summary": " · ".join(summary_bits) or "Client flagged this session for review.",
                "created_at": completed_at,
                "assigned_coach_id": user.get("assigned_coach_id"),
            })
        except Exception:
            logger.exception("workout_complete — coach_tasks insert failed")

    # Phase 3 — reactive progression: if this was the last workout of the ISO
    # week, compute the progression snapshot. Non-fatal on error.
    try:
        from feature_progression import on_workout_completed
        snap = await on_workout_completed(db, user, doc or {})
        if snap:
            doc = doc or {}
            doc["_progression_snapshot"] = snap
    except Exception as _e:
        logger.warning(f"progression trigger failed for workout {wid}: {_e}")
    return doc


# ------------------------------------------------------------------
# Phase 3 — Progression endpoints
# ------------------------------------------------------------------

@api.get("/progress/current")
async def progress_current(user: dict = Depends(current_user)):
    """Return the latest progression snapshot for the logged-in client.

    Returns {} if none exists yet (client hasn't completed a full week).
    """
    from feature_progression import latest_snapshot
    snap = await latest_snapshot(db, user["id"])
    return snap or {}


@api.get("/progress/history")
async def progress_history(weeks: int = 8, user: dict = Depends(current_user)):
    """Return the last `weeks` progression snapshots (most recent first)."""
    from feature_progression import snapshot_history
    weeks = max(1, min(52, int(weeks or 8)))
    return await snapshot_history(db, user["id"], limit=weeks)


@api.post("/progress/recompute")
async def progress_recompute(user: dict = Depends(current_user)):
    """
    Client / coach manual trigger to recompute this week's progression snapshot.
    Used by the "Your Progress" card refresh button.
    """
    from feature_progression import compute_and_store_week
    import datetime as _dt
    today = _dt.date.today()
    snap = await compute_and_store_week(db, user["id"], today, force=True)
    return snap or {}


@api.get("/coach/clients/{cid}/progress/current")
async def coach_client_progress(cid: str, _: dict = Depends(require_role("coach"))):
    """Coach view — latest progression snapshot for a specific client."""
    from feature_progression import latest_snapshot
    snap = await latest_snapshot(db, cid)
    return snap or {}


@api.get("/coach/clients/{cid}/progress/history")
async def coach_client_progress_history(cid: str, weeks: int = 8, _: dict = Depends(require_role("coach"))):
    """Coach view — progression history for a specific client."""
    from feature_progression import snapshot_history
    weeks = max(1, min(52, int(weeks or 8)))
    return await snapshot_history(db, cid, limit=weeks)


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

logging_type — MANDATORY CLASSIFICATION RULE (iter167):
- If the exercise NAME contains the word "run", "walk", "row", or "cycle" (as a
  standalone word — case-insensitive), you MUST return `logging_type: "cardio"`.
  Examples: "Easy Run", "Zone 2 Run", "Long Run — Steady Pace", "Easy Walk",
  "Incline Walk", "Recovery Row", "Zone 2 Row", "Erg Row", "Assault Bike Cycle",
  "Recovery Cycle". This overrides every other consideration.
- EXCEPTIONS — the words above appearing inside a strength lift name do NOT
  make it cardio. Return `logging_type: "weighted"` (or "bodyweight" if
  unloaded) for these: "Bent-over Row", "Barbell Row", "Dumbbell Row",
  "Pendlay Row", "Seal Row", "Chest-supported Row", "Meadows Row", "Kroc Row",
  "T-bar Row", "Inverted Row", "Renegade Row", "Upright Row", "Cable Row",
  "Face Pull", "Walking Lunge", "Walking Plank", "Walking Push-up".
- For anything else, choose from: weighted | bodyweight | cardio | timer | mobility.

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
    """Client-facing lookup used by workout preview / How-To / warm-up / guided
    flow. Returns coach-authored content (instructions/cues/mistakes/image/
    video/alternatives) for the named exercise.

    Manual mode writes exercises to `exercises_v2`, not the legacy
    `exercises` collection. We check V2 first with an exact-name preference,
    then fall back to V1 for any legacy content that predates the V2 library.
    """
    wanted = (name or "").strip()
    if not wanted:
        return {"exercise": None}

    # ---- Try V2 (exercises_v2) first, exact match only -------------------
    # We deliberately avoid a fuzzy fallback here — matching "Band Pull-Apart"
    # to "Band pull-apart or shoulder pass-through" leaks wrong media into
    # workouts. Exact case-insensitive only.
    rx = {"$regex": f"^{re.escape(wanted)}$", "$options": "i"}
    v2 = await db.exercises_v2.find_one({"exercise_name": rx}, {"_id": 0})

    # Legacy V1 record
    v1 = await db.exercises.find_one({"name": rx}, {"_id": 0})

    if not v2 and not v1:
        return {"exercise": None}

    # Prefer V2 for coaching content; fall back to V1 per field.
    def _pick(*vals):
        for v in vals:
            if v not in (None, "", []):
                return v
        return None

    cp = (v2 or {}).get("coaching_points") or []
    if isinstance(cp, str):
        cp = [cp]
    v1_cues = (v1 or {}).get("cues") or []
    mistakes_v2 = (v2 or {}).get("common_mistakes") or []
    if isinstance(mistakes_v2, str):
        mistakes_v2 = [mistakes_v2]

    # Alternatives — V2 stores as list[str], normalise to {name, equipment, why}.
    alts_v2_raw = (v2 or {}).get("alternatives") or []
    alts: list[dict] = []
    for a in (alts_v2_raw if isinstance(alts_v2_raw, list) else []):
        if isinstance(a, str):
            alts.append({"name": a, "equipment": [], "why": None})
        elif isinstance(a, dict) and a.get("name"):
            alts.append({
                "name": a.get("name"),
                "equipment": a.get("equipment") or [],
                "why": a.get("why") or a.get("reason") or None,
            })

    # Instructions: V2 uses a single `instructions` string usually; V1 stores list.
    v2_instr = (v2 or {}).get("instructions")
    if isinstance(v2_instr, str):
        v2_instr = [line.strip() for line in v2_instr.split("\n") if line.strip()]
    v1_instr = (v1 or {}).get("instructions") or []

    return {"exercise": {
        "name": _pick((v2 or {}).get("exercise_name"), (v1 or {}).get("name"), wanted),
        # Cues -> coaching points (V2 preferred). If both exist, V2 wins and
        # any V1 cues get appended so the coach never loses their old work.
        "cues": (cp or []) + [c for c in v1_cues if c not in (cp or [])] if cp else v1_cues,
        # Coaching points also exposed under their canonical name for
        # any future consumer that reads coaching_points directly.
        "coaching_points": cp or v1_cues,
        "instructions": v2_instr or v1_instr,
        "mistakes": mistakes_v2 or (v1 or {}).get("mistakes") or [],
        "common_mistakes": mistakes_v2 or (v1 or {}).get("mistakes") or [],
        "alternatives": alts,
        # Image: expose the V2 image_id + a resolved stream URL so RN can
        # render without a second round-trip. Legacy V1 fields kept for
        # backwards compatibility with old callers.
        "primary_image_id":    (v2 or {}).get("primary_image_id"),
        "demo_start_image_id": (v2 or {}).get("demo_start_image_id"),
        "demo_end_image_id":   (v2 or {}).get("demo_end_image_id"),
        "custom_image_b64":    (v1 or {}).get("custom_image_b64"),
        "coach_image_url":     (v1 or {}).get("coach_image_url"),
        # Video: V2 preferred; V1 fallback.
        "coach_video_url": _pick((v2 or {}).get("coach_video_url"), (v1 or {}).get("coach_video_url")),
        "video_url":       _pick((v2 or {}).get("primary_video_url"), (v2 or {}).get("video_url"), (v1 or {}).get("video_url")),
        "video_channel":   _pick((v2 or {}).get("video_channel"), (v1 or {}).get("video_channel")),
        "default_rest_sec": (v1 or {}).get("default_rest_sec"),
        "logging_type":     _pick((v2 or {}).get("logging_type"), (v1 or {}).get("logging_type")),
        "content_source":   "v2" if v2 else "v1",
        "content_status":   (v2 or {}).get("content_status"),
        "approved":         (v1 or {}).get("approved", True) if not v2 else ((v2 or {}).get("status") in ("Approved", "Live")),
        "v2_id":            (v2 or {}).get("id"),
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
    # Iter 92 (Phase 2) — extract structured signals
    try:
        from feature_live_state import extract_signals_from_checkin
        doc["signals"] = extract_signals_from_checkin(doc)
    except Exception:
        logger.exception("adaptive-checkin signal extract failed")
    await db.checkins.insert_one(doc)
    # Refresh rolling live_state
    try:
        from feature_live_state import refresh_and_persist_live_state
        await refresh_and_persist_live_state(db, user["id"])
    except Exception:
        logger.exception("adaptive-checkin live_state refresh failed")
    # Fire-and-forget: generate weekly script for the coach.
    # Iter181e — routed through _spawn_bg so Python's weak-ref GC cannot
    # drop it under prod load / worker recycle.
    if user.get("coach_id"):
        try:
            _spawn_bg(_generate_script_for(user["id"], user["coach_id"]))
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
    # Iter169 · Weekly check-ins live in db.check_ins (with submitted_at),
    # NOT db.checkins (daily). The video script generator wants the LATEST
    # weekly submission so it can reference concrete weekly numbers.
    checkin = await db.check_ins.find_one({"user_id": client_id}, {"_id": 0}, sort=[("submitted_at", -1)])
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
    # Iter 92 (Phase 2) — extract structured signals + refresh live_state
    try:
        from feature_live_state import extract_signals_from_checkin, refresh_and_persist_live_state
        doc["signals"] = extract_signals_from_checkin(doc)
    except Exception:
        logger.exception("checkin signal extract failed — non-fatal")
    await db.checkins.insert_one(doc)
    try:
        from feature_live_state import refresh_and_persist_live_state
        await refresh_and_persist_live_state(db, user["id"])
    except Exception:
        logger.exception("checkin live_state refresh failed — non-fatal")
    return clean_doc(doc)

@api.get("/checkins")
async def checkin_list(user: dict = Depends(current_user)):
    return await db.checkins.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(50)


# ------------------------------------------------------------------
# Iter 92 — Phase 2: Living Profile Wire-Back
# ------------------------------------------------------------------

@api.get("/profile/live-state")
async def profile_live_state_get(user: dict = Depends(current_user)):
    """Return the rolling 14-day live_state snapshot for THIS user."""
    from feature_live_state import compute_live_state, receipt_for_client
    state = await compute_live_state(db, user["id"])
    # Merge in stored coach_directives
    stored = ((user.get("profile") or {}).get("live_state") or {}).get("coach_directives")
    if stored:
        state["coach_directives"] = stored
    return {
        "live_state": state,
        "receipt": receipt_for_client(state),
    }


@api.post("/profile/live-state/refresh")
async def profile_live_state_refresh(user: dict = Depends(current_user)):
    from feature_live_state import refresh_and_persist_live_state, receipt_for_client
    state = await refresh_and_persist_live_state(db, user["id"])
    return {"live_state": state, "receipt": receipt_for_client(state)}


@api.get("/coach/clients/{client_id}/live-state")
async def coach_live_state_for_client(client_id: str, coach: dict = Depends(require_role("coach"))):
    from feature_live_state import compute_live_state, receipt_for_client
    client = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(404, "client not found")
    state = await compute_live_state(db, client_id)
    stored = ((client.get("profile") or {}).get("live_state") or {}).get("coach_directives")
    if stored:
        state["coach_directives"] = stored
    return {
        "client_id": client_id,
        "live_state": state,
        "receipt": receipt_for_client(state),
    }


class CoachDirectiveBody(BaseModel):
    text: str
    source_message_id: Optional[str] = None
    ttl_days: Optional[int] = 21


@api.post("/coach/clients/{client_id}/directives")
async def coach_add_directive(
    client_id: str, body: CoachDirectiveBody, coach: dict = Depends(require_role("coach"))
):
    """Pin a coaching directive so the next plan build honours it."""
    from feature_live_state import add_coach_directive
    if not (body.text or "").strip():
        raise HTTPException(400, "text required")
    doc = await add_coach_directive(db, client_id, {
        "text": body.text.strip(),
        "coach_id": coach["id"],
        "source_message_id": body.source_message_id,
        "ttl_days": body.ttl_days,
    })
    return {"directive": doc}


@api.delete("/coach/clients/{client_id}/directives/{directive_id}")
async def coach_remove_directive(
    client_id: str, directive_id: str, coach: dict = Depends(require_role("coach"))
):
    u = await db.users.find_one({"id": client_id}, {"_id": 0}) or {}
    live = ((u.get("profile") or {}).get("live_state") or {})
    existing = live.get("coach_directives") or []
    new_list = [d for d in existing if d.get("id") != directive_id]
    await db.users.update_one(
        {"id": client_id},
        {"$set": {"profile.live_state.coach_directives": new_list}},
    )
    return {"removed": len(existing) - len(new_list), "remaining": len(new_list)}


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
    # Guard-rails on the attachment shape so a bad client can't over-attach.
    att_ids = list(body.attachment_ids or [])
    if len(att_ids) > 7:  # 5 images + 1 video + 1 voice = 7 legit maximum
        raise HTTPException(413, {"error": "too_many_attachments", "detail": "Maximum 5 images + 1 video + 1 voice note per message."})
    # Validate every attachment exists, belongs to the sender, isn't already bound.
    valid_ids: list[str] = []
    kinds: dict[str, int] = {"image": 0, "video": 0, "voice": 0}
    if att_ids:
        rows = await db.message_attachments.find({"id": {"$in": att_ids}}).to_list(len(att_ids))
        by_id = {r["id"]: r for r in rows}
        for aid in att_ids:
            r = by_id.get(aid)
            if not r or r.get("uploaded_by") != user["id"] or r.get("message_id"):
                raise HTTPException(400, {"error": "bad_attachment", "detail": "Attachment missing, already sent, or not yours.", "id": aid})
            kinds[r["type"]] = kinds.get(r["type"], 0) + 1
            valid_ids.append(aid)
        if kinds.get("image", 0) > 5:
            raise HTTPException(413, {"error": "too_many_images", "detail": "Max 5 images per message."})
        if kinds.get("video", 0) > 1:
            raise HTTPException(413, {"error": "too_many_videos", "detail": "Max 1 video per message."})
        if kinds.get("voice", 0) > 1:
            raise HTTPException(413, {"error": "too_many_voice_notes", "detail": "Max 1 voice note per message."})

    doc = {"id": new_id(), "from_user_id": user["id"], "to_user_id": body.to_user_id,
           "text": body.text or "", "created_at": now_iso(), "read": False,
           "attachment_ids": valid_ids,
           "include_in_next_plan": bool(body.include_in_next_plan)}
    await db.messages.insert_one(doc)
    clean_doc(doc)

    # Iter 92 (Phase 2, Task 2.4) — If coach flagged this message as
    # "include in next plan", pin it as a live_state coach_directive.
    try:
        if body.include_in_next_plan and user.get("role") == "coach":
            from feature_live_state import add_coach_directive
            await add_coach_directive(db, body.to_user_id, {
                "text": (body.text or "").strip(),
                "coach_id": user["id"],
                "source_message_id": doc["id"],
                "ttl_days": 21,
            })
    except Exception:
        logger.exception("coach directive pin failed — non-fatal")

    # Bind attachments to this message now that it exists.
    if valid_ids:
        await db.message_attachments.update_many(
            {"id": {"$in": valid_ids}, "uploaded_by": user["id"]},
            {"$set": {"message_id": doc["id"]}},
        )
        # Hydrate for the response so the client can render bubbles instantly.
        from feature_message_attachments import hydrate_message_attachments
        await hydrate_message_attachments(db, doc)

    try:
        preview = body.text[:120] if body.text else (
            "📎 Attachment" if valid_ids else ""
        )
        await send_push([body.to_user_id], {
            "title": user.get("name", "CrewFit"),
            "message": preview or "New message",
            "action_url": "/(client)/messages",
        })
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

@api.delete("/messages/{message_id}")
async def msg_delete(message_id: str, user: dict = Depends(current_user)):
    """Iter189w · Delete a sent message. Sender-only. Removes the row so
    both the sender and recipient views drop it immediately on next
    fetch. Attachments bound to the message are cascaded so no orphans
    linger.
    """
    m = await db.messages.find_one({"id": message_id}, {"_id": 0})
    if not m:
        raise HTTPException(404, "message_not_found")
    if m.get("from_user_id") != user["id"] and m.get("sender_id") != user["id"]:
        raise HTTPException(403, "forbidden — only the sender can delete a message")
    try:
        att_ids = m.get("attachment_ids") or []
        if att_ids:
            await db.message_attachments.delete_many(
                {"id": {"$in": att_ids}, "uploaded_by": user["id"]},
            )
    except Exception:
        logger.exception("message-delete attachment cleanup failed for %s", message_id)
    await db.messages.delete_one({"id": message_id})
    return {"ok": True, "deleted_id": message_id}


@api.get("/messages/{other_id}")
async def msg_thread(other_id: str, user: dict = Depends(current_user)):
    rows = await db.messages.find(
        {"$or": [{"from_user_id": user["id"], "to_user_id": other_id},
                 {"from_user_id": other_id, "to_user_id": user["id"]}]}, {"_id": 0}
    ).sort("created_at", 1).to_list(500)
    # Iter 95n — hide scheduled auto-messages (e.g. Louis's roster-ack) until
    # their visible_from timestamp lands, so the "review" feels real.
    try:
        from feature_roster_review_delay import prune_pending
        rows = prune_pending(rows)
    except Exception:
        pass
    if rows:
        from feature_message_attachments import hydrate_message_attachments
        for r in rows:
            await hydrate_message_attachments(db, r)
    # Iter 82 — mark incoming messages as read now that they've been opened.
    try:
        await db.messages.update_many(
            {"to_user_id": user["id"], "from_user_id": other_id, "read": {"$ne": True}},
            {"$set": {"read": True, "read_at": now_iso()}},
        )
    except Exception:
        pass
    return rows


@api.get("/messages-unread/count")
async def msg_unread_count(user: dict = Depends(current_user)):
    """Iter 82 — total unread messages FOR the current user. Powers the
    tab-bar badge on the client bottom nav (and coach dashboard alerts)."""
    # Iter 95n — a pending roster-ack message must not bump the badge until
    # it actually lands, otherwise the client sees an unread indicator with
    # nothing behind it (breaks the illusion).
    now_iso_val = now_iso()
    count = await db.messages.count_documents({
        "to_user_id": user["id"],
        "read": {"$ne": True},
        "$or": [
            {"visible_from": {"$exists": False}},
            {"visible_from": {"$lte": now_iso_val}},
        ],
    })
    return {"count": int(count)}


@api.get("/messages")
async def msg_partners(user: dict = Depends(current_user)):
    if user["role"] == "client":
        cid = user.get("coach_id")
        c = await db.users.find_one({"id": cid}, {"_id": 0, "password_hash": 0}) if cid else None
        if not c:
            # Prefer the primary coach (Louis) as fallback, never a legacy row.
            c = await db.users.find_one({"role": "coach", "is_primary_coach": True}, {"_id": 0, "password_hash": 0})
        if not c:
            c = await db.users.find_one({"role": "coach"}, {"_id": 0, "password_hash": 0})
        return [c] if c else []
    rows = await db.users.find({"role": "client", "coach_id": user["id"]}, {"_id": 0, "password_hash": 0}).to_list(200)
    if not rows:
        rows = await db.users.find({"role": "client"}, {"_id": 0, "password_hash": 0}).to_list(200)
    return rows


@api.get("/coach/profile/main")
async def coach_profile_main():
    """Public, unauthenticated Louis identity for the messages UI and any
    other client-facing surface that needs the coach card. Returns a stable
    shape even if the DB row is missing (so a fresh install can still render
    the app before seed()."""
    doc = await db.users.find_one({"role": "coach", "is_primary_coach": True}, {"_id": 0, "password_hash": 0})
    if not doc:
        # Hard-coded fallback matches frontend/src/lib/coachProfile.ts.
        return {
            "id": None,
            "email": "louis@crewfit.net",
            "name": "Louis Hall",
            "display_name": "Louis",
            "initials": "LH",
            "title": "Founder & Aviation Performance Coach",
            "tagline": "CrewFit Coach",
            "avatar_url": "https://customer-assets.emergentagent.com/job_flight-fit-plans/artifacts/q32k4b7w_Screenshot%202026-07-12%20153226.png",
        }
    prof = doc.get("profile", {}) or {}
    return {
        "id": doc.get("id"),
        "email": doc.get("email"),
        "name": doc.get("name") or "Louis Hall",
        "display_name": doc.get("display_name") or "Louis",
        "initials": "LH",
        "title": prof.get("title") or "Founder & Aviation Performance Coach",
        "tagline": prof.get("tagline") or "CrewFit Coach",
        "avatar_url": doc.get("avatar_url"),
    }


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
    # Phase 4: attach a compact programme pill so the coach list can scan
    # goal / phase / week / target-sessions at a glance without opening the
    # client detail page.
    prog = await db.programmes.find_one({"user_id": u["id"]}, {"_id": 0}, sort=[("created_at", -1)])
    programme_pill = None
    if prog:
        phase = prog.get("phase") or {}
        gr = prog.get("guardrail_report") or {}
        # Iter 94j — compute display_week from programme_start_date_local (or
        # start_date fallback) so a Day-1 client's coach card also shows Week 1.
        try:
            from feature_programme_quality import _display_week_for as _dw
            _display_week = _dw(prog)
        except Exception:
            _display_week = prog.get("week_index") or 1
        programme_pill = {
            "goal_key": prog.get("goal_key"),
            "goal_label": prog.get("goal_label"),
            "phase_key": phase.get("key") if isinstance(phase, dict) else None,
            "phase_label": phase.get("label") if isinstance(phase, dict) else None,
            "week_index": prog.get("week_index"),
            "display_week": _display_week,
            "target_sessions_per_week": prog.get("target_sessions_per_week"),
            "validation_status": prog.get("validation_status"),
            "coach_approved": bool(prog.get("coach_approved")),
            "updated_at": prog.get("updated_at") or prog.get("created_at"),
            # Iter 93 (Phase 3) — surface guardrail summary
            "guardrail_healed": int(gr.get("healed") or 0),
            "guardrail_flagged": int(gr.get("flagged") or 0),
            # Iter 94j — first-day choice visible on coach clients list
            "first_day_choice": prog.get("first_day_choice"),
            "first_day_block_reason": prog.get("first_day_block_reason"),
        }
    # Iter 81 Phase 4: attach the latest weekly progression snapshot so the
    # coach can see 'PROGRESSING / STEADY / PULL BACK / DELOAD' at a glance.
    progression_pill = None
    try:
        snap = await db.progression_snapshots.find_one(
            {"user_id": u["id"]}, {"_id": 0}, sort=[("week_key", -1)]
        )
        if snap:
            progression_pill = {
                "status": snap.get("status"),
                "status_label": snap.get("status_label"),
                "reason": snap.get("reason"),
                "coach_note": snap.get("coach_note"),
                "week_key": snap.get("week_key"),
                "week_start": snap.get("week_start"),
                "week_end": snap.get("week_end"),
                "metrics": snap.get("metrics") or {},
            }
    except Exception:
        progression_pill = None
    # Iter 91 (Task 1.10) — Profile completeness pill so the coach can see at
    # a glance which clients haven't finished their training setup yet.
    profile_incomplete_pill = None
    try:
        complete, missing = await _user_essentials_present(u["id"])
        if not complete and missing:
            profile_incomplete_pill = {
                "missing_fields": missing,
                "friendly_labels": [_FRIENDLY_ESSENTIAL_LABELS.get(f, f) for f in missing],
                "missing_count": len(missing),
            }
    except Exception:
        profile_incomplete_pill = None
    return {
        **u,
        "latest_roster": r or None,
        "roster_expiry": expiry,
        "pending_approvals": pending,
        "red_days": red_days,
        "missed_workouts": missed,
        "programme_pill": programme_pill,
        "progression_pill": progression_pill,
        "profile_incomplete_pill": profile_incomplete_pill,
    }


@api.get("/coach/clients")
async def coach_clients(
    status: Optional[str] = None,
    include_archived: bool = False,
    _: dict = Depends(require_role("coach")),
):
    """List clients. By default, hides archived / paused / deletion_pending /
    deleted accounts. Pass `?status=archived` (or `?include_archived=true`) to
    see them."""
    q: dict[str, Any] = {"role": "client"}
    if status:
        q["status"] = status
    elif not include_archived:
        # Exclude archived/paused/deleted AND the preview sandbox (we surface
        # sandbox separately via `preview_sandbox` field on the response).
        q["status"] = {"$nin": ["archived", "paused", "deletion_pending", "deleted", "preview_sandbox"]}
    rows = await db.users.find(q, {"_id": 0, "password_hash": 0}).to_list(500)
    return [await _client_summary(u) for u in rows]


@api.get("/coach/dashboard")
async def coach_dashboard(filter: Optional[str] = None, include_archived: bool = False, _: dict = Depends(require_role("coach"))):
    q: dict[str, Any] = {"role": "client"}
    if not include_archived:
        q["status"] = {"$nin": ["archived", "paused", "deletion_pending", "deleted", "preview_sandbox"]}
    rows = await db.users.find(q, {"_id": 0, "password_hash": 0}).to_list(500)
    summaries = [await _client_summary(u) for u in rows]
    # Persistent preview sandbox: always surface separately so Louis can find it.
    sandbox_user = await db.users.find_one(
        {"is_preview_sandbox": True}, {"_id": 0, "password_hash": 0},
    )
    sandbox_summary = None
    if sandbox_user:
        try:
            sandbox_summary = await _client_summary(sandbox_user)
            sandbox_summary["is_preview_sandbox"] = True
            sandbox_summary["client_type"] = "preview_sandbox"
        except Exception:
            logger.exception("preview-sandbox summary failed")
    buckets = {
        "expiring_soon": [s for s in summaries if s["roster_expiry"].get("coverage") in ("low", "critical")],
        "expired": [s for s in summaries if s["roster_expiry"].get("expired")],
        "no_roster": [s for s in summaries if not s.get("latest_roster")],
        "needs_confirmation": [s for s in summaries if s.get("latest_roster") and not s["latest_roster"].get("confirmed")],
        "pending_approval": [s for s in summaries if s.get("pending_approvals", 0) > 0],
        "red_days": [s for s in summaries if s.get("red_days", 0) > 0],
        "missed": [s for s in summaries if s.get("missed_workouts", 0) > 0],
        # Slice 3: programme validation flagged the plan for coach review.
        "needs_review": [s for s in summaries
                         if (s.get("programme_pill") or {}).get("validation_status") == "needs_review"
                         and not (s.get("programme_pill") or {}).get("coach_approved")],
        # Iter 91 (Task 1.10) — clients who haven't finished training setup.
        "profile_incomplete": [s for s in summaries if s.get("profile_incomplete_pill")],
        "all": summaries,
    }
    if filter and filter in buckets:
        return {"clients": buckets[filter], "counts": {k: len(v) for k, v in buckets.items() if k != "all"}, "total": len(summaries), "preview_sandbox": sandbox_summary}
    # Iter 81 Phase 4: expose the hotel review-queue depth on the overview
    try:
        hotels_pending_review = await db.hotels.count_documents({
            "$and": [
                {"$or": [{"verified_by_coach": {"$ne": True}}, {"verified_by_coach": {"$exists": False}}]},
                {"$or": [{"confidence": {"$lt": 0.7}}, {"confidence": {"$exists": False}}]},
            ],
        })
    except Exception:
        hotels_pending_review = 0
    counts = {k: len(v) for k, v in buckets.items() if k != "all"}
    counts["hotels_pending_review"] = int(hotels_pending_review)
    return {"clients": summaries, "counts": counts, "total": len(summaries), "preview_sandbox": sandbox_summary}


@api.get("/coach/clients/{client_id}")
async def coach_client_detail(client_id: str, _: dict = Depends(require_role("coach"))):
    c = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not c:
        raise HTTPException(404, "Client not found")
    r = await db.rosters.find_one({"user_id": client_id, "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    if not r:
        # Fallback: latest roster of any status so the coach can still edit/view.
        r = await db.rosters.find_one({"user_id": client_id}, {"_id": 0}, sort=[("created_at", -1)])
    if r:
        r["expiry"] = _roster_expiry(r)
    workouts = await db.workouts.find({"user_id": client_id}, {"_id": 0}).sort("date", 1).to_list(500)
    # Iter169 · Coach client-detail must surface WEEKLY check-ins so the
    # CheckinsPanel matches what the client submitted via /weekly-checkin.
    # These live in db.check_ins (not db.checkins) and are ordered by
    # submitted_at, not created_at.
    checkins = await db.check_ins.find({"user_id": client_id}, {"_id": 0}).sort("submitted_at", -1).to_list(10)
    history = await db.rosters.find({"user_id": client_id}, {"_id": 0, "raw_response": 0}).sort("created_at", -1).to_list(20)
    ev = await db.events.find_one({"user_id": client_id, "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    if ev:
        ev["phase_info"] = _event_phase(ev.get("event_date", ""))
    overrides = await db.day_overrides.find({"user_id": client_id}, {"_id": 0}).sort("date", -1).to_list(60)
    change_log = await db.day_change_log.find({"user_id": client_id}, {"_id": 0}).sort("created_at", -1).to_list(30)
    # Iter 81 Phase 4 — attach latest weekly progression snapshot for coach view
    progression_pill = None
    try:
        snap = await db.progression_snapshots.find_one(
            {"user_id": client_id}, {"_id": 0}, sort=[("week_key", -1)]
        )
        if snap:
            progression_pill = {
                "status": snap.get("status"),
                "status_label": snap.get("status_label"),
                "reason": snap.get("reason"),
                "coach_note": snap.get("coach_note"),
                "week_key": snap.get("week_key"),
                "metrics": snap.get("metrics") or {},
            }
    except Exception:
        progression_pill = None
    if c is not None:
        c["progression_pill"] = progression_pill
    return {
        "client": c, "roster": r, "workouts": workouts, "checkins": checkins,
        "roster_history": history, "event": ev or None,
        "overrides": overrides, "change_log": change_log,
    }


@api.get("/coach/pending-approvals")
async def coach_pending(_: dict = Depends(require_role("coach"))):
    # Iter 128d — V1 workout approvals retired. With zero V1 clients the
    # legacy `workouts.approved=False` list is meaningless. Approvals now
    # flow through the V2 draft change-set pathway on the workspace Plan tab
    # (see /v2/coach/clients/{id}/engine-v2/publish and /engine-v2/exceptions).
    # This endpoint is retained returning an empty list so any lingering
    # frontend caller doesn't 404 during the retirement window.
    return []


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
        # Iter 128d — for V2 clients (which is now ALL current clients) V1
        # `workouts` yields empty scheduled_past → return `None` so the UI
        # shows "—" instead of a misleading 0%. Analytics on V2 completion
        # (workout_implementations) is on the backlog; see COACH_DASHBOARD_
        # CONSOLIDATION_PLAN.md §22.
        if scheduled_past:
            compliance = round(100 * len(completed) / len(scheduled_past))
        else:
            compliance = None
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
    global_compliance = round(100 * tot_completed / tot_scheduled) if tot_scheduled else None
    global_avg_rpe = round(sum(all_rpes) / len(all_rpes), 1) if all_rpes else None
    per_client.sort(key=lambda x: -(x["compliance"] or -1))
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


async def _resolve_library_video(
    *, exercise_id: Optional[str] = None, exercise_name: Optional[str] = None,
) -> Optional[dict]:
    """Iter 161 · Prefer the Exercise Library video over the YouTube cache.

    Looks up the canonical `exercises_v2` row by:
      1. explicit exercise_id (with canonical_id follow-through), or
      2. exact case-insensitive name, or
      3. canonical singularised-token name fingerprint.

    Returns a video dict shaped like the /exercises/video response's
    `video` field when a valid primary_video_url is present, else None.
    NEVER performs a YouTube fetch — that's the caller's fallback.
    """
    lib = None
    try:
        if exercise_id:
            lib = await db.exercises_v2.find_one(
                {"id": exercise_id},
                {"_id": 0, "id": 1, "exercise_name": 1, "canonical_id": 1,
                 "primary_video_url": 1, "backup_video_url": 1, "status": 1},
            )
            # Follow canonical alias if present (workout stored alias id)
            if lib and lib.get("canonical_id"):
                canon = await db.exercises_v2.find_one(
                    {"id": lib["canonical_id"]},
                    {"_id": 0, "id": 1, "exercise_name": 1,
                     "primary_video_url": 1, "backup_video_url": 1, "status": 1},
                )
                if canon:
                    lib = canon
        if not lib and exercise_name:
            # Exact case-insensitive name
            rx = {"$regex": f"^{re.escape(exercise_name.strip())}$", "$options": "i"}
            lib = await db.exercises_v2.find_one(
                {"exercise_name": rx},
                {"_id": 0, "id": 1, "exercise_name": 1, "canonical_id": 1,
                 "primary_video_url": 1, "backup_video_url": 1, "status": 1},
            )
            if lib and lib.get("canonical_id"):
                canon = await db.exercises_v2.find_one(
                    {"id": lib["canonical_id"]},
                    {"_id": 0, "id": 1, "exercise_name": 1,
                     "primary_video_url": 1, "backup_video_url": 1, "status": 1},
                )
                if canon:
                    lib = canon
        if not lib and exercise_name:
            # Canonical fingerprint lookup as a last shot (singular/plural)
            try:
                from feature_v2_resolver import _canonical_tokens
                fp = " ".join(_canonical_tokens(exercise_name))
                if fp:
                    cursor = db.exercises_v2.find(
                        {"status": {"$in": ["Approved", "Live"]},
                         "primary_video_url": {"$nin": [None, ""]}},
                        {"_id": 0, "id": 1, "exercise_name": 1,
                         "primary_video_url": 1, "backup_video_url": 1},
                    )
                    async for cand in cursor:
                        if " ".join(_canonical_tokens(cand.get("exercise_name"))) == fp:
                            lib = cand
                            break
            except Exception:
                pass
    except Exception:
        logger.exception("_resolve_library_video: lookup failed (non-fatal)")
        return None
    if not lib:
        return None
    url = lib.get("primary_video_url") or lib.get("backup_video_url")
    if not url:
        return None
    # If it looks like a YouTube URL, wrap as a native YT embed so the
    # existing player still renders. Otherwise treat as a custom upload.
    yt_id = _parse_youtube_url(url) if callable(globals().get("_parse_youtube_url", None)) else None
    if yt_id:
        return {
            "video_id": yt_id,
            "video_url": url,
            "title": lib.get("exercise_name"),
            "channel": "CrewFit Library",
            "source": "library_youtube",
            "approval_status": "approved",
            "thumbnail_url": f"https://img.youtube.com/vi/{yt_id}/mqdefault.jpg",
        }
    return {
        "video_id": None,
        "video_url": url,
        "title": lib.get("exercise_name"),
        "channel": "CrewFit Library",
        "source": "custom_upload",
        "approval_status": "approved",
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
async def get_exercise_video(
    name: str,
    variant: str = "default",
    exercise_id: Optional[str] = None,
    user: dict = Depends(current_user),
):
    """Return the current video record for an exercise.

    Iter 161 · Precedence:
      1. Exercise Library primary_video_url (matched by exercise_id, then
         exact name, then canonical fingerprint) — always wins when present.
      2. Cached exercise_videos row (custom uploads / YT hand-picks).
      3. Fresh YouTube scrape on miss.
    """
    lib_video = await _resolve_library_video(
        exercise_id=exercise_id, exercise_name=name,
    )
    if lib_video:
        return {"exercise": name, "video": lib_video, "source": "library"}
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
        # Iter 161 · Library video wins over the YT cache even for cache hits.
        lib_v = await _resolve_library_video(exercise_name=n)
        if lib_v:
            out[n] = {"key": k, "video": lib_v, "id": None}
            continue
        d = cached.get(k)
        if d:
            resolved = _resolve_display_video(d, variant=variant)
            out[n] = {"key": k, "video": resolved, "id": d.get("id")} if resolved else None
        else:
            to_fetch.append(n)
    sem = asyncio.Semaphore(4)

    async def one(nm: str):
        async with sem:
            # Iter 161 · Library video wins over YT scrape.
            lib_v = await _resolve_library_video(exercise_name=nm)
            if lib_v:
                return nm, {"key": _normalize_ex_key(nm), "video": lib_v, "id": None}
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
    # -----------------------------------------------------------
    # Main coach: Louis Hall — client-facing identity for CrewFit.
    # Kept email-based so future multi-coach support can just add
    # rows without touching this seed. The legacy `coach@crewfit.com`
    # account is still created (test tooling depends on it) but is
    # marked non-primary and its clients are migrated to Louis.
    # -----------------------------------------------------------
    louis_email = "louis@crewfit.net"
    legacy_coach_email = "coach@crewfit.com"
    client_email = "client@crewfit.com"

    louis = await db.users.find_one({"email": louis_email})
    if not louis:
        louis_id = new_id()
        await db.users.insert_one({
            "id": louis_id,
            "email": louis_email,
            "name": "Louis Hall",
            "display_name": "Louis",
            "role": "coach",
            "is_admin": True,
            "is_primary_coach": True,
            "password_hash": hash_pw("Louis123!"),
            "created_at": now_iso(),
            "onboarded": True,
            "coach_id": None,
            "avatar_url": "https://customer-assets.emergentagent.com/job_flight-fit-plans/artifacts/q32k4b7w_Screenshot%202026-07-12%20153226.png",
            "profile": {
                "bio": "Founder & Aviation Performance Coach",
                "title": "Founder & Aviation Performance Coach",
                "tagline": "CrewFit Coach",
            },
            "age_confirmed": True,
            "age_confirmed_at": now_iso(),
        })
    else:
        louis_id = louis["id"]
        # Backfill new identity fields on existing Louis row without clobbering
        # a real password if the user rotated it.
        await db.users.update_one({"id": louis_id}, {"$set": {
            "name": "Louis Hall",
            "display_name": "Louis",
            "role": "coach",
            "is_admin": True,
            "is_primary_coach": True,
            "avatar_url": "https://customer-assets.emergentagent.com/job_flight-fit-plans/artifacts/q32k4b7w_Screenshot%202026-07-12%20153226.png",
            "profile.bio": "Founder & Aviation Performance Coach",
            "profile.title": "Founder & Aviation Performance Coach",
            "profile.tagline": "CrewFit Coach",
        }})

    # Iter 130a — Emergency admin password reset.
    # Two independent triggers, either of which will force-reset Louis's
    # password to "Louis123!" on backend boot:
    #   (a) env var `RESET_ADMIN_ON_STARTUP=1` (preferred, easy to disable), OR
    #   (b) marker doc missing in `system_bootstrap` collection — a one-shot
    #       fallback that runs exactly once per deployment even if env vars
    #       don't propagate. After it runs it writes a marker so subsequent
    #       restarts skip it.
    # Intended as an unblock for early-MVP deploys where the production
    # password has drifted from the documented dev credential.
    try:
        env_flag = str(os.environ.get("RESET_ADMIN_ON_STARTUP", "")).strip().lower() in ("1", "true", "yes")
        marker = None
        try:
            marker = await db.system_bootstrap.find_one({"_id": "admin_password_unlock_iter130a"})
        except Exception:
            marker = None
        should_reset = env_flag or (marker is None)
        if should_reset:
            # Iter182b · deployment health-check — no source-known default.
            # If `ADMIN_STARTUP_PASSWORD` isn't set, this branch is a no-op
            # so we never reset the coach to a leaked / recoverable value.
            forced_pw = os.environ.get("ADMIN_STARTUP_PASSWORD")
            if not forced_pw:
                logger.info(
                    "seed: admin startup password reset skipped — "
                    "ADMIN_STARTUP_PASSWORD is not set.",
                )
            else:
                await db.users.update_one(
                    {"email": louis_email},
                    {"$set": {
                        "password_hash": hash_pw(forced_pw),
                        "password_reset_by": "startup_env_reset",
                        "password_changed_at": now_iso(),
                    }},
                )
                try:
                    await db.system_bootstrap.update_one(
                        {"_id": "admin_password_unlock_iter130a"},
                        {"$set": {"ran_at": now_iso(), "trigger": "env" if env_flag else "one_shot"}},
                        upsert=True,
                    )
                except Exception:
                    pass
                logger.warning(
                    "seed: admin password force-reset (trigger=%s) — REMOVE the "
                    "RESET_ADMIN_ON_STARTUP env once you've regained access.",
                    "env" if env_flag else "one_shot",
                )
    except Exception:
        logger.exception("seed: admin startup password reset failed")

    # Legacy coach (kept for backward-compat with pytest suites) — RENAMED and
    # ARCHIVED so he never appears in Louis' visible UI or coach lists.
    legacy = await db.users.find_one({"email": legacy_coach_email})
    if not legacy:
        legacy_id = new_id()
        await db.users.insert_one({
            "id": legacy_id, "email": legacy_coach_email, "name": "Legacy Coach (archived)", "role": "coach",
            "password_hash": hash_pw("Coach123!"), "created_at": now_iso(),
            "onboarded": True, "coach_id": None,
            "is_primary_coach": False,
            "status": "archived",
            "coach_tier": "assistant",
            "profile": {"bio": "Legacy coach account. Reassign clients to Louis in production."},
        })
    else:
        # Force-rename any historical "Coach Kai" row and archive it so the UI
        # never surfaces the legacy identity anywhere.
        await db.users.update_one({"id": legacy["id"]}, {"$set": {
            "name": "Legacy Coach (archived)",
            "is_primary_coach": False,
            "status": "archived",
            "coach_tier": "assistant",
        }})
    coach_id = louis_id  # For all new clients, default coach is Louis.

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

    # Migrate every existing client to Louis so no one gets orphaned on the
    # legacy Kai coach after this deploy.
    await db.users.update_many({"role": "client"}, {"$set": {"coach_id": coach_id}})

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

    # Iter181c — ensure unique partial index on canonical_name_key +
    # supporting index on exercise_duplicate_candidates. Idempotent.
    try:
        from feature_exercise_dedup import ensure_indexes as _dedup_ensure_indexes
        await _dedup_ensure_indexes()
    except Exception:
        logger.exception("feature_exercise_dedup: ensure_indexes failed at startup")

    # Zombie backfill_jobs — any 'running' job left over from a previous
    # process is dead now. Mark them 'failed' so the UI stops polling.
    try:
        await db.backfill_jobs.update_many(
            {"status": {"$in": ["queued", "running"]}},
            {"$set": {
                "status": "failed",
                "finished_at": now_iso(),
                "error": "server restart — worker did not survive",
            }},
        )
    except Exception:
        logger.exception("backfill_jobs zombie cleanup failed")

    # Iter 128 — one-shot: backfill persona field on legacy exercise images
    # so the new Flight Support media resolver can pick louis/female/pilot
    # correctly. Idempotent — no-op after the first run.
    try:
        from feature_flight_support_media import backfill_personas
        result = await backfill_personas(db)
        if result.get("female_backfilled") or result.get("louis_backfilled"):
            logger.info("persona backfill: %s", result)
    except Exception:
        logger.exception("persona backfill failed")

    # Iter 158 — draft every Flight Support protocol block into the
    # exercises_v2 library so coaches see them alongside manual-workout
    # exercises. Idempotent: the resolver's fuzzy-match short-circuits
    # existing rows.
    try:
        from feature_aviation_support import ensure_flight_support_blocks_in_library
        await ensure_flight_support_blocks_in_library()
    except Exception:
        logger.exception("flight_support library seed failed")

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

    # Iter 130e — frontend↔backend goal-key parity lint.
    # If someone ships a new option in the mobile onboarding picker
    # without adding a corresponding entry to `_GOAL_ALIASES`, log a
    # loud WARN at startup so the mismatch is caught before a real
    # client hits `critical_dna_missing` on Build Plan. The parity test
    # already blocks CI, this is the belt-and-suspenders runtime check.
    try:
        from feature_v2_sport_configs import _GOAL_ALIASES, SPORT_CONFIGS
        from tests.test_iter130e_frontend_goal_key_parity import (
            FRONTEND_GOAL_KEYS,
        )
        missing = [
            k for k in FRONTEND_GOAL_KEYS
            if k.lower() not in SPORT_CONFIGS and k.lower() not in _GOAL_ALIASES
        ]
        if missing:
            logger.warning(
                "GOAL-KEY PARITY WARNING — the following frontend "
                "onboarding keys have no backend alias and will fail "
                "Engine V2 Build Plan with critical_dna_missing: %s. "
                "Add each to _GOAL_ALIASES in feature_v2_sport_configs.py.",
                missing,
            )
    except Exception:
        # Never let this diagnostic block startup.
        logger.exception("goal-key parity lint at startup failed")

    # Roster jobs — the asyncio worker dies with the process on restart /
    # deploy / crash. Any job still "processing" is a zombie; the user is
    # staring at 94% forever. Mark it failed with an actionable message.
    #
    # Iter 157 — SAFETY GUARD: never stamp `failed` on a job that has
    # already reached 100% progress OR has a `pending_roster_id`. Those
    # jobs succeeded in doing the actual parsing work — the process just
    # died before the terminal status transition (e.g. bg task cancelled
    # between the roster insert and the final `_set_job(..., status=...)`
    # call). Failing them would show the user a red "PROCESSING FAILED"
    # even though their roster is sitting in the DB ready to confirm.
    try:
        stuck = await db.roster_jobs.update_many(
            {
                "status": "processing",
                "progress": {"$lt": 100},
                "pending_roster_id": {"$in": [None, ""]},
            },
            {"$set": {
                "status": "failed",
                "stage": "interrupted",
                "message": "The server restarted while your plan was generating.",
                "error": "Your generation was interrupted by a server restart. Please tap Retry to upload again — no data was lost.",
                "updated_at": now_iso(),
                "interrupted_by": "startup_sweep",
            }},
        )
        if stuck.modified_count:
            logger.info("startup: swept %d zombie roster_jobs", stuck.modified_count)
    except Exception:
        logger.exception("startup zombie cleanup failed for roster_jobs")

    # Iter 83 — Defence layer 3 of 4: on every backend boot, heal any workouts
    # that got persisted with empty main exercises on a training day. This
    # catches anything the read-time healer missed (e.g. a user who hasn't
    # opened the app since a broken write) and gets rid of the whole class of
    # "empty workout" bug at rest.
    try:
        from datetime import date as _date
        today_iso = _date.today().isoformat()
        broken = await db.workouts.find(
            {
                "$or": [{"exercises": []}, {"exercises": {"$exists": False}}, {"exercises": None}],
                "date": {"$gte": today_iso},
                "completed": {"$ne": True},
            },
        ).to_list(2000)
        if broken:
            per_user: dict[str, list[dict]] = {}
            for w in broken:
                per_user.setdefault(w.get("user_id"), []).append(w)
            healed_total = 0
            for uid, rows in per_user.items():
                user = await db.users.find_one({"id": uid})
                if not user:
                    continue
                try:
                    healed_rows = await _heal_workouts_batch(rows, user)
                    for r in healed_rows:
                        if r.get("exercises"):
                            healed_total += 1
                except Exception:
                    logger.exception("startup heal failed for user=%s", uid)
            logger.info("startup: healed %d/%d empty workouts across %d users",
                        healed_total, len(broken), len(per_user))
    except Exception:
        logger.exception("startup empty-workout sweep failed")

    # Watchdog: any roster_job whose updated_at is >5 minutes old and still
    # "processing" is orphaned. Kick off a background task that periodically
    # sweeps these so users don't stare at a frozen bar in production either.
    async def _roster_watchdog() -> None:
        import asyncio as _asyncio
        from datetime import datetime, timedelta, timezone as _tz
        while True:
            try:
                await _asyncio.sleep(60)
                # Iter 94h — Sweep BOTH `processing` AND `queued`. A queued job
                # can be orphaned too (background worker never picked it up
                # after a container restart). Previously only "processing" was
                # swept, which meant queued zombies stayed silent forever and
                # the client never saw a failure state. Also tightened to 3
                # minutes so the client is told sooner.
                cutoff = (datetime.now(_tz.utc) - timedelta(minutes=3)).isoformat()
                # Iter 157 — same guard as startup_sweep: don't fail jobs
                # that already crossed 100% or already produced a pending
                # roster ID. Those are already "done in spirit".
                r = await db.roster_jobs.update_many(
                    {
                        "status": {"$in": ["processing", "queued"]},
                        "updated_at": {"$lt": cutoff},
                        "progress": {"$lt": 100},
                        "pending_roster_id": {"$in": [None, ""]},
                    },
                    {"$set": {
                        "status": "failed",
                        "stage": "interrupted",
                        "message": "This generation stopped responding.",
                        "error": "The upload timed out or was interrupted. Please tap Retry — this is usually a transient blip.",
                        "updated_at": now_iso(),
                        "interrupted_by": "watchdog",
                    }},
                )
                if r.modified_count:
                    logger.warning("roster watchdog: cleared %d stalled jobs", r.modified_count)
            except Exception:
                logger.exception("roster watchdog tick failed")
    try:
        _asyncio_module = __import__("asyncio")
        _asyncio_module.create_task(_roster_watchdog())
    except Exception:
        logger.exception("could not launch roster watchdog")
    # Reset stale brand-image generation jobs (see feature_brand_images).
    try:
        from feature_brand_images import _reconcile_stale_jobs
        await _reconcile_stale_jobs()
    except Exception:
        logger.exception("brand_images reconciliation on startup failed")
    try:
        from feature_exercise_content import _reconcile_ex_stale
        await _reconcile_ex_stale()
    except Exception:
        logger.exception("exercise image reconciliation on startup failed")
    # Phase 5 — one-shot backfill of visibility / safe_for_programming on
    # approved exercises. Idempotent, cheap, non-fatal.
    try:
        from feature_v2_resolver import backfill_client_flags_once
        await backfill_client_flags_once()
    except Exception:
        logger.exception("v2_resolver backfill on startup failed")
    # Phase 5 P1 — just-in-time media sweep: every 15 minutes, look for
    # approved exercises referenced by upcoming workouts and queue image
    # generation for any that still lack a demo image.
    try:
        from feature_v2_resolver import jit_media_sweep_loop
        asyncio.create_task(jit_media_sweep_loop())
    except Exception:
        logger.exception("JIT media sweep failed to start")
    # Coach dashboard Slice 1 — ensure Louis is flagged as the default admin.
    # Idempotent: only writes when the flag is missing/false.
    try:
        await db.users.update_many(
            {"email": "louis@crewfit.net"},
            {"$set": {"is_admin": True, "role": "coach", "coach_tier": "admin", "status": "active"}},
        )
    except Exception:
        logger.exception("Louis admin migration failed (non-fatal)")
    # Slice 2 — backfill: any existing coach without a tier is treated as
    # 'full'. Any client without an assigned_coach_id gets Louis.
    try:
        await db.users.update_many(
            {"role": "coach", "coach_tier": {"$exists": False}},
            {"$set": {"coach_tier": "full"}},
        )
        louis = await db.users.find_one({"email": "louis@crewfit.net"}, {"_id": 0, "id": 1})
        if louis and louis.get("id"):
            await db.users.update_many(
                {"role": "client", "$or": [{"assigned_coach_id": {"$exists": False}}, {"assigned_coach_id": None}]},
                {"$set": {"assigned_coach_id": louis["id"], "assigned_coach_name": "Louis Hall"}},
            )
    except Exception:
        logger.exception("Slice 2 coach/assignment migration failed (non-fatal)")
    # ------------------------------------------------------------------
    # Iter 140a — one-off idempotent setup for restored client
    # `pietrosangermano1992@hotmail.com` (production user id
    # bd7f3e31-2bba-49b6-980b-e60a539c927b). Sets the three flags his
    # workspace needs so the coach can build a V2 Draft + publish while
    # global MANUAL_MODE remains active:
    #     profile.v2_flags.engine_v2            = True   (unlocks kickoff)
    #     profile.v2_flags.manual_draft_override = True  (bypass MANUAL_MODE)
    #     profile.main_goal                     = "running.marathon"
    #     profile.primary_goal_type             = "running.marathon"
    # Runs at every startup but a) skips cleanly if the user id isn't in
    # this DB (dev pod), and b) no-ops any field that's already at the
    # target value. Every outcome is logged for verification from deploy
    # logs.
    #
    # Iter 162c · Match by EMAIL too. When a client is deleted+restored
    # the row may come back with a fresh UUID — matching by id alone would
    # miss it. We now look up either the hard-coded prod id OR the
    # canonical email, use whichever wins, and apply the same $set patch.
    # ------------------------------------------------------------------
    try:
        _PIETRO_PROD_ID = "bd7f3e31-2bba-49b6-980b-e60a539c927b"
        _PIETRO_EMAIL = "pietrosangermano1992@hotmail.com"
        _u_before = await db.users.find_one(
            {"$or": [
                {"id": _PIETRO_PROD_ID},
                {"email": {"$regex": f"^{re.escape(_PIETRO_EMAIL)}$", "$options": "i"}},
            ]},
            {"_id": 0, "id": 1, "email": 1, "profile": 1},
        )
        if not _u_before:
            logger.info(
                f"startup_migration[pietro_v2_setup]: neither id={_PIETRO_PROD_ID} "
                f"nor email={_PIETRO_EMAIL} present in this database — skipping "
                f"(harmless on dev pod)."
            )
        else:
            # From here on match by the id we actually found so subsequent
            # writes hit the same row (fresh UUID after restore is OK).
            _resolved_id = _u_before.get("id") or _PIETRO_PROD_ID
            _profile_before = _u_before.get("profile") or {}
            _flags_before = _profile_before.get("v2_flags") or {}
            _needs_engine_v2 = _flags_before.get("engine_v2") is not True
            _needs_override = _flags_before.get("manual_draft_override") is not True
            _needs_main_goal = (
                _profile_before.get("main_goal") != "running.marathon"
                or _profile_before.get("primary_goal_type") != "running.marathon"
            )
            if not (_needs_engine_v2 or _needs_override or _needs_main_goal):
                logger.info(
                    f"startup_migration[pietro_v2_setup]: all fields already at "
                    f"target values for {_u_before.get('email')} (id={_resolved_id}) "
                    f"— no-op (idempotent)."
                )
            else:
                _now_str = now_iso()
                _updates: dict = {
                    "profile.v2_flags.engine_v2": True,
                    "profile.v2_flags.manual_draft_override": True,
                    "profile.v2_flags.manual_draft_override_at": _now_str,
                    "profile.v2_flags.manual_draft_override_by":
                        "startup_migration:iter-140a",
                    "profile.v2_flags.manual_draft_override_reason": (
                        "Restored client — one-off V2 draft build during "
                        "global MANUAL_MODE=true so ChatGPT-generated "
                        "monthly JSON can be imported with replace_conflicts."
                    ),
                    "profile.v2_flags.updated_at": _now_str,
                    "profile.v2_flags.updated_by": "startup_migration:iter-140a",
                    "profile.main_goal": "running.marathon",
                    "profile.primary_goal_type": "running.marathon",
                    "profile.main_goal_set_at": _now_str,
                    "profile.main_goal_set_by": "startup_migration:iter-140a",
                    "updated_at": _now_str,
                }
                _res = await db.users.update_one(
                    {"id": _resolved_id},
                    {"$set": _updates},
                )
                # Read the document back and log the STORED values + Python
                # types so the receipt is verifiable from deploy logs.
                _u_after = await db.users.find_one(
                    {"id": _resolved_id},
                    {"_id": 0, "email": 1, "profile": 1},
                )
                _p_after = (_u_after or {}).get("profile") or {}
                _flags_after = _p_after.get("v2_flags") or {}
                _stored_eng = _flags_after.get("engine_v2")
                _stored_over = _flags_after.get("manual_draft_override")
                _stored_goal = _p_after.get("main_goal")
                logger.info(
                    f"startup_migration[pietro_v2_setup]: "
                    f"matched={_res.matched_count} modified={_res.modified_count} "
                    f"resolved_id={_resolved_id} "
                    f"engine_v2={_stored_eng!r}({type(_stored_eng).__name__}) "
                    f"manual_draft_override={_stored_over!r}({type(_stored_over).__name__}) "
                    f"main_goal={_stored_goal!r} "
                    f"email={(_u_after or {}).get('email')!r}"
                )
    except Exception:
        logger.exception("startup_migration[pietro_v2_setup] failed (non-fatal)")
    # ------------------------------------------------------------------
    # Iter 140b — backfill: any client whose coach turned on
    # `manual_draft_override` via the workspace toggle BEFORE we started
    # coupling engine_v2 in the same PATCH is stuck with the override ON
    # but engine_v2 missing → Build plan returns 409 "Engine V2 not
    # enabled". This idempotent sweep flips engine_v2=True on every such
    # client. Safe to run every startup.
    # ------------------------------------------------------------------
    try:
        _fix_q = {
            "profile.v2_flags.manual_draft_override": True,
            "$or": [
                {"profile.v2_flags.engine_v2": {"$exists": False}},
                {"profile.v2_flags.engine_v2": False},
                {"profile.v2_flags.engine_v2": None},
            ],
        }
        _fix_count = await db.users.count_documents(_fix_q)
        if _fix_count:
            _now = now_iso()
            _res = await db.users.update_many(
                _fix_q,
                {"$set": {
                    "profile.v2_flags.engine_v2": True,
                    "profile.v2_flags.engine_v2_backfilled_at": _now,
                    "profile.v2_flags.engine_v2_backfilled_by":
                        "startup_migration:iter-140b",
                    "updated_at": _now,
                }},
            )
            logger.info(
                f"startup_migration[override_engine_v2_backfill]: "
                f"scanned={_fix_count} matched={_res.matched_count} "
                f"modified={_res.modified_count} — flipped engine_v2=True "
                f"on clients with manual_draft_override already on."
            )
        else:
            logger.info(
                "startup_migration[override_engine_v2_backfill]: "
                "no clients need engine_v2 backfill — no-op (idempotent)."
            )
    except Exception:
        logger.exception(
            "startup_migration[override_engine_v2_backfill] failed (non-fatal)"
        )
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
    """Return this week's check-in for the client (may be null if not yet submitted).

    Iter 83 — Sunday gating: `should_show_card` tells the home surface whether
    to render the Weekly Check-in card at all. Rule: only surface it once the
    client has been through their first Sunday of training. Specifically:

      * Never on the day they sign up (no data to reflect on).
      * Only when `today` is Sunday OR Monday (grace day) in the client's TZ.
      * AND account is at least 24h old.
      * If they already submitted this week, we still return the doc so the
        card can flip to "waiting for video" / "video ready" states.
    """
    ws, we = _current_week_bounds(user)
    doc = await db.check_ins.find_one({"user_id": user["id"], "week_start": ws}, {"_id": 0})
    tz_name = user.get("current_time_zone") or user.get("home_time_zone") or "Europe/London"
    tz = _user_tz(user)
    now_local = _dt.datetime.now(tz)
    weekday_local = now_local.weekday()   # Mon=0 … Sun=6
    is_sunday = weekday_local == 6
    is_monday_grace = weekday_local == 0
    # Account age gate — never on day-zero.
    account_old_enough = True
    try:
        created_at = user.get("created_at")
        if created_at:
            created_dt = _dt.datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=_dt.timezone.utc)
            hours_since_signup = (_dt.datetime.now(_dt.timezone.utc) - created_dt).total_seconds() / 3600.0
            account_old_enough = hours_since_signup >= 24
            # Also — user's first Sunday hasn't passed yet? Only allow the card
            # once at least one Sunday has occurred since signup.
            days_since_signup = hours_since_signup / 24.0
            if days_since_signup < 6 and weekday_local != 6:
                # Less than a week old + not Sunday → definitely not yet.
                account_old_enough = False
    except Exception:
        pass
    # If they already submitted, always show (state 2/3 of the card).
    already_submitted = bool(doc)
    should_show_card = already_submitted or (
        account_old_enough and (is_sunday or is_monday_grace)
    )
    # Next scheduled Sunday (in local TZ, 09:00) — displayed to the user.
    days_until_sun = (6 - weekday_local) % 7 or 7   # if today is Sunday, next Sunday = 7d away
    next_sun_local = (now_local + _dt.timedelta(days=days_until_sun)).replace(hour=9, minute=0, second=0, microsecond=0)
    return {
        "check_in": doc,
        "week_start": ws,
        "week_end": we,
        "time_zone": tz_name,
        "is_sunday_local": is_sunday,
        "is_monday_grace": is_monday_grace,
        "account_old_enough": account_old_enough,
        "should_show_card": should_show_card,
        "next_scheduled": f"{ws} 09:00 {tz_name}",
        "next_sunday_local": next_sun_local.isoformat(),
    }


# ---------------------------------------------------------------------------
# Iter181e · Check-in question generation — LLM-first, coach-editable.
# ---------------------------------------------------------------------------
# Storage: one doc per client per (week_start, type) in the new
# `check_in_questions` collection:
#   { user_id, week_start, type: "weekly"|"monthly",
#     questions: [ {id, label, type, options?, min?, max?}, … ],
#     generated_at, generated_by: "atlas"|"coach",
#     coach_edited_at, coach_edited_by }
#
# Read semantics:
#   * GET /checkins/questions returns the stored set if one exists for the
#     current week — coach edits are the source of truth.
#   * If no doc exists, we call the Atlas LLM to generate exactly 10
#     questions tuned to the client's primary goal, upsert the doc, and
#     return it. Never > 10 questions.
#   * "monthly" mode kicks in on the LAST Sunday of the local month —
#     switches to the zoom-out prompt and heading.
#
# Coach control surface:
#   * GET  /coach/checkins/questions/{client_id}?type=weekly|monthly
#   * PUT  /coach/checkins/questions/{client_id}         (replace list)
#   * POST /coach/checkins/questions/{client_id}/regenerate
# ---------------------------------------------------------------------------

_MAX_CHECKIN_QUESTIONS = 10

WEEKLY_QUESTIONS_SYSTEM = """You are Atlas — CrewFit's coaching AI. Given a client's profile, primary goal, event (if any) and latest roster snapshot, produce EXACTLY 10 questions for their WEEKLY check-in.

Rules:
 - EXACTLY 10 questions. Not 9. Not 11.
 - Questions must be relevant to the client's PRIMARY GOAL first, then their aviation duty context second.
 - Marathoner → cover long run, pacing, niggles, legs-ready. Fat-loss → hunger, adherence, protein, weight trend. Muscle/strength → lifts, PRs, appetite. Ironman → swim/bike/run split. Pilot/cabin crew → jet-lag, layover access.
 - Include at LEAST ONE 1-5 scale question for RECOVERY.
 - Mix formats: ~4 scale (1-5), ~3 choice, ~3 text.
 - Choice options: 3-5 items, short, mutually exclusive.
 - British spelling. Warm, direct, human. No motivational-poster language.
 - IDs must be snake_case. Labels are the actual question the client reads.

Return STRICT JSON only:
{"questions":[
  {"id":"snake_case_id","label":"…","type":"scale|choice|text","min":1,"max":5,"options":["…"]}
]}"""

MONTHLY_QUESTIONS_SYSTEM = """You are Atlas — CrewFit's coaching AI. Given a client's profile, primary goal, event and last four weeks' training/roster context, produce EXACTLY 10 questions for their MONTHLY REVIEW check-in.

This is a ZOOM-OUT review — bigger picture than the weekly. Cover:
 - What worked this month (training patterns, sessions they enjoyed, nutrition wins).
 - What did NOT work (missed sessions, energy dips, roster clashes, habits that fell off).
 - What they want MORE of / LESS of next month.
 - Concrete progress against their PRIMARY GOAL (numbers, PRs, weight, adherence, subjective feel).
 - One forward-looking question about the next month's biggest challenge or event.

Rules:
 - EXACTLY 10 questions.
 - Include at LEAST ONE 1-5 scale for overall-month progress-toward-goal.
 - Mix formats: ~3 scale, ~3 choice, ~4 text (reflective).
 - British spelling. Reflective, honest, non-judgemental tone. No motivational-poster language.
 - IDs must be snake_case.

Return STRICT JSON only:
{"questions":[
  {"id":"snake_case_id","label":"…","type":"scale|choice|text","min":1,"max":5,"options":["…"]}
]}"""


def _is_last_sunday_of_month(local_d: _dt.date) -> bool:
    """True iff `local_d` is a Sunday AND no later Sunday exists in the
    same month. Works because Sundays are 7 days apart — if adding 7 days
    lands us in a different month, this Sunday is the last."""
    if local_d.weekday() != 6:
        return False
    return (local_d + _dt.timedelta(days=7)).month != local_d.month


def _resolve_primary_goal(user: dict) -> tuple[str, list[str]]:
    """Return (human-readable goal label, list of raw goal signals) for prompt
    injection. Consolidates the same fallback chain used elsewhere so LLM
    prompts and coach display are consistent."""
    dna = user.get("coaching_dna") or {}
    profile = user.get("profile") or {}
    bits: list[str] = []
    bits += [str(g).lower() for g in (dna.get("primary_goals") or [])]
    for k in ("primary_goal_id", "main_goal_key", "main_goal",
              "event_type_pref", "secondary_goal_ids"):
        v = profile.get(k)
        if isinstance(v, str): bits.append(v.lower())
        elif isinstance(v, list): bits += [str(x).lower() for x in v]
    blob = " ".join(bits)

    def has(*ks: str) -> bool: return any(k in blob for k in ks)
    labels: list[str] = []
    if has("marathon", "half_marathon", "10k", "5k", "run", "running"): labels.append("Marathon / running")
    if has("fat", "lose_fat", "cut", "weight_loss", "leaner"):          labels.append("Fat loss")
    if has("muscle", "gain", "hypertrophy", "strength", "size"):        labels.append("Muscle / strength")
    if has("iron", "tri", "triathlon"):                                  labels.append("Triathlon")
    if has("health", "wellbeing", "longevity", "energy", "stress"):     labels.append("Health / wellbeing")
    return (" · ".join(labels) or "General fitness"), bits


async def _generate_checkin_questions_via_llm(user: dict, *, mode: str) -> list[dict]:
    """Call Atlas → return exactly `_MAX_CHECKIN_QUESTIONS` question dicts.
    Falls back to a safe hardcoded 10-item core set if the LLM fails."""
    dna = user.get("coaching_dna") or {}
    profile = user.get("profile") or {}
    goal_label, _bits = _resolve_primary_goal(user)
    role_hint = (dna.get("crew_role") or profile.get("role") or
                 profile.get("job_title") or "").lower()
    ev = None
    try:
        ev = await db.events.find_one({"user_id": user["id"], "is_active": True},
                                      {"_id": 0}, sort=[("created_at", -1)])
    except Exception:
        pass
    roster = None
    try:
        roster = await db.rosters.find_one({"user_id": user["id"], "is_active": True},
                                           {"_id": 0}, sort=[("created_at", -1)])
    except Exception:
        pass
    roster_snap = None
    if roster:
        roster_snap = {
            "start_date": roster.get("start_date"),
            "end_date": roster.get("end_date"),
            "types": list({d.get("day_type") for d in (roster.get("days", []) or []) if d.get("day_type")}),
        }

    ctx = {
        "primary_goal_label": goal_label,
        "crew_role": role_hint,
        "profile_snippet": {k: profile.get(k) for k in
                            ("primary_goal_id", "main_goal_key", "main_goal",
                             "event_type_pref", "airline", "position")},
        "coaching_dna_snippet": {k: dna.get(k) for k in
                                 ("primary_goals", "crew_role", "training_days_per_week")},
        "active_event": ev,
        "roster": roster_snap,
    }
    system = WEEKLY_QUESTIONS_SYSTEM if mode == "weekly" else MONTHLY_QUESTIONS_SYSTEM
    prompt = f"Client context:\n{json.dumps(ctx, default=str)[:2500]}\n\nGenerate the questions now."
    qs: list[dict] = []
    try:
        raw = await call_claude(system, prompt, max_out=2000)
        parsed = parse_json_from_text(raw)
        if isinstance(parsed, dict):
            qs = [q for q in (parsed.get("questions") or []) if isinstance(q, dict)]
    except Exception:
        logger.exception("check-in LLM question generation failed — falling back")

    # Safety-net: normalise + cap + backfill on failure.
    cleaned: list[dict] = []
    for q in qs[: _MAX_CHECKIN_QUESTIONS]:
        qid = str(q.get("id") or "").strip().lower().replace(" ", "_")
        label = str(q.get("label") or "").strip()
        qtype = q.get("type") or "text"
        if qtype not in ("scale", "choice", "text"):
            qtype = "text"
        if not qid or not label:
            continue
        row = {"id": qid, "label": label, "type": qtype}
        if qtype == "scale":
            row["min"] = int(q.get("min") or 1)
            row["max"] = int(q.get("max") or 5)
        elif qtype == "choice":
            opts = q.get("options") or []
            row["options"] = [str(o) for o in opts if str(o).strip()][:5]
            if len(row["options"]) < 2:
                # Bad choice question — coerce to text so client can still answer.
                row["type"] = "text"; row.pop("options", None)
        cleaned.append(row)

    if len(cleaned) < _MAX_CHECKIN_QUESTIONS:
        fallback = [
            {"id": "overall",           "label": "How was your overall training week?", "type": "choice",
             "options": ["Excellent", "Good", "Okay", "Difficult", "Poor"]},
            {"id": "energy",            "label": "Energy this week",            "type": "scale", "min": 1, "max": 5},
            {"id": "sleep",             "label": "Sleep quality this week",     "type": "scale", "min": 1, "max": 5},
            {"id": "stress",            "label": "Stress level this week",      "type": "scale", "min": 1, "max": 5},
            {"id": "recovery",          "label": "Recovery / soreness this week", "type": "scale", "min": 1, "max": 5},
            {"id": "pain",              "label": "Any pain, injury or discomfort?", "type": "choice",
             "options": ["No", "Yes, minor", "Yes, moderate", "Yes, severe"]},
            {"id": "nutrition",         "label": "Nutrition consistency this week", "type": "choice",
             "options": ["Very consistent", "Mostly consistent", "Mixed", "Poor", "Not focused on nutrition"]},
            {"id": "biggest_win",       "label": "Biggest win this week",       "type": "text"},
            {"id": "biggest_challenge", "label": "Biggest challenge this week", "type": "text"},
            {"id": "for_louis",         "label": "Anything else Louis needs to know?", "type": "text"},
        ]
        used = {q["id"] for q in cleaned}
        for f in fallback:
            if len(cleaned) >= _MAX_CHECKIN_QUESTIONS:
                break
            if f["id"] not in used:
                cleaned.append(f)
    return cleaned[: _MAX_CHECKIN_QUESTIONS]


async def _get_or_generate_checkin_questions(
    user: dict, *, week_start: str, mode: str,
) -> dict:
    """Return `check_in_questions` doc for this (user, week_start, mode) —
    generating + persisting via LLM if none exists.  Coach edits are
    preserved: if `coach_edited_at` is set, we NEVER regenerate over
    them unless the coach explicitly calls the regenerate endpoint."""
    existing = await db.check_in_questions.find_one(
        {"user_id": user["id"], "week_start": week_start, "type": mode},
        {"_id": 0},
    )
    if existing and existing.get("questions"):
        return existing

    qs = await _generate_checkin_questions_via_llm(user, mode=mode)
    doc = {
        "id": new_id(),
        "user_id": user["id"],
        "week_start": week_start,
        "type": mode,
        "questions": qs,
        "generated_at": now_iso(),
        "generated_by": "atlas",
        "coach_edited_at": None,
        "coach_edited_by": None,
    }
    await db.check_in_questions.update_one(
        {"user_id": user["id"], "week_start": week_start, "type": mode},
        {"$set": doc}, upsert=True,
    )
    return doc


@api.get("/checkins/questions")
async def sunday_checkin_questions(user: dict = Depends(current_user)):
    """Return the check-in question set for this client + week.

    Iter181e — always LLM-generated, coach-editable, capped at 10 questions.
    On the LAST Sunday of the client's local month, the set switches to
    the "monthly review" zoom-out prompt. The UI renders a different
    heading + intro when `type == "monthly"`.
    """
    ws, _we = _current_week_bounds(user)
    tz = _user_tz(user)
    local_today = _dt.datetime.now(tz).date()
    mode = "monthly" if _is_last_sunday_of_month(local_today) else "weekly"
    goal_label, _ = _resolve_primary_goal(user)
    doc = await _get_or_generate_checkin_questions(user, week_start=ws, mode=mode)

    intro = (
        "This is your monthly zoom-out. Answer honestly — Louis uses these "
        "to reshape next month's plan around what actually worked for you."
        if mode == "monthly"
        else "Answer honestly. Louis reads every one of these before recording your weekly video."
    )
    heading = "MONTHLY REVIEW" if mode == "monthly" else "WEEKLY CHECK-IN"

    return {
        # Legacy shape — checkin.tsx used to consume `core` + `dynamic`
        # separately.  We now return a single list under `questions`;
        # `core` is populated with the same list to preserve rendering
        # for older client builds.  `dynamic` is deliberately empty so
        # nothing gets appended twice.
        "core": doc.get("questions", []),
        "dynamic": [],
        "questions": doc.get("questions", []),
        "type": doc.get("type") or mode,
        "heading": heading,
        "intro": intro,
        "goal_label": goal_label,
        "tailored": True,
        "coach_edited": bool(doc.get("coach_edited_at")),
        "generated_at": doc.get("generated_at"),
    }


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
    # Iter 165b · Prefer the client's explicit assigned_coach_id. Falls back
    # to Louis (the primary head coach) if the client hasn't been assigned,
    # and only as a last resort to the first coach in the DB. This prevents
    # tasks from being silently routed to a random coach when multi-coach
    # support is enabled.
    coach_id: Optional[str] = user.get("assigned_coach_id") or user.get("coach_id")
    if not coach_id:
        louis = await db.users.find_one(
            {"role": "coach", "email": "louis@crewfit.net"}, {"_id": 0, "id": 1}
        )
        coach_id = (louis or {}).get("id")
    if not coach_id:
        any_coach = await db.users.find_one({"role": "coach"}, {"_id": 0, "id": 1})
        coach_id = (any_coach or {}).get("id")
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


# --- Shared change-log helper (used by multiple feature modules) -----------
async def _log_change(coach_id: Optional[str], client_id: Optional[str], category: str,
                      title: str, description: str = "", actor: str = "coach",
                      meta: Optional[dict] = None,
                      kind: Optional[str] = None,
                      at: Optional[str] = None) -> None:
    """Append a change-log entry.

    Writes to BOTH `db.coach_change_log` (legacy coach-only view) and
    `db.change_log` (unified stream read by the programme timeline in
    feature_coach_programme_overview). Idempotent under retries via random id.
    """
    ts = at or now_iso()
    doc = {
        "id": new_id(),
        "coach_id": coach_id,
        "client_id": client_id,
        "category": category,          # message / programme / controls / script / workout / roster / coach_note / other
        "kind": kind,                  # optional finer-grained event type (edit / swap / regenerate / etc.)
        "title": title,
        "description": description,
        "actor": actor,                # coach / atlas / client / system
        "meta": meta or {},
        "created_at": ts,
        "at": ts,
    }
    # Best-effort dual write — either failure is non-fatal.
    try:
        await db.coach_change_log.insert_one({**doc})
    except Exception:
        logger.exception("coach_change_log insert failed")
    try:
        # Same doc but with a fresh _id to satisfy Mongo's unique constraint
        # since Motor assigns _id to the dict passed to insert_one.
        await db.change_log.insert_one({**doc, "id": new_id()})
    except Exception:
        logger.exception("change_log insert failed")


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
        # Iter 145 — preserve original Atlas outputs alongside the editable
        # working copies. The main `atlas_client_summary` / `weekly_video_script`
        # fields hold the coach-approved version shown to the client; the
        # `_original` fields hold Atlas's untouched first draft so the coach
        # can always reset.
        "atlas_client_summary": parsed.get("atlas_client_summary"),
        "atlas_client_summary_original": parsed.get("atlas_client_summary"),
        "atlas_coach_summary": coach_summary,
        "next_week_focus": parsed.get("next_week_focus"),
        "suggested_programme_adjustments": parsed.get("suggested_programme_adjustments"),
        "weekly_video_script": parsed.get("weekly_video_script"),
        "weekly_video_script_original": parsed.get("weekly_video_script"),
        "summary_edited_by": None, "summary_edited_at": None,
        "script_edited_by":  None, "script_edited_at":  None,
        "whatsapp_short": parsed.get("whatsapp_short"),
        "push_notification": parsed.get("push_notification"),
        "coach_review_status": "pending",
        "coach_review_required": coach_review_required,
        "weekly_video_status": "script_ready",
        "weekly_video_id": None,
        "reviewed_by": None,
        "reviewed_at": None,
    }
    # Iter 145 — unified weekly aggregation. Store the same numeric review
    # that the legacy Weekly Review would compute, so both surfaces read
    # from a single record. Reuses the existing helpers in
    # feature_weekly_review.py — no duplicate LLM call, no duplicate query
    # logic. Failure is non-fatal; the check-in still submits.
    try:
        from feature_weekly_review import (
            _training_stats, _nutrition_stats, _habit_stats,
            _roster_summary, _has_progress_this_week,
        )
        import datetime as _dt
        ws_d = _dt.date.fromisoformat(ws)
        we_d = _dt.date.fromisoformat(we)
        doc["weekly_review_snapshot"] = {
            "training":  await _training_stats(user["id"], ws_d, we_d),
            "nutrition": await _nutrition_stats(user["id"], ws_d, we_d),
            "habits":    await _habit_stats(user["id"], ws_d, we_d),
            "roster_summary": await _roster_summary(user["id"], ws_d, we_d),
            "has_progress": await _has_progress_this_week(user["id"], ws_d, we_d),
            "generated_at": now_iso(),
            "source": "checkin_submit_unified",
        }
    except Exception:
        logger.exception("unified weekly aggregation failed — non-fatal")
        doc["weekly_review_snapshot"] = None
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

    # Trigger the Atlas habit review in background so the check-in can return quickly.
    # Iter181e — _spawn_bg keeps a strong reference so the task can't be
    # GC-dropped mid-run.
    try:
        _spawn_bg(_run_habit_review_after_checkin(user["id"], doc["id"], ws, we))
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
    # Iter 145 — first edit preserves the original if the pre-Iter-145 row
    # didn't capture one. Subsequent edits just update the working copy.
    ci = await db.check_ins.find_one({"id": checkin_id}, {"_id": 0, "weekly_video_script_original": 1, "weekly_video_script": 1})
    if not ci:
        raise HTTPException(404, "check-in not found")
    updates: dict[str, Any] = {
        "weekly_video_script": body.weekly_video_script,
        "script_edited_by": coach["id"], "script_edited_at": now_iso(),
    }
    if not ci.get("weekly_video_script_original"):
        updates["weekly_video_script_original"] = ci.get("weekly_video_script") or ""
    await db.check_ins.update_one({"id": checkin_id}, {"$set": updates})
    ci = await db.check_ins.find_one({"id": checkin_id}, {"_id": 0})
    return {"check_in": ci}


# Iter 145 — editable client-facing summary with original preservation.
class SummaryEditBody(BaseModel):
    atlas_client_summary: str


@api.put("/coach/checkins/{checkin_id}/summary")
async def coach_edit_summary(checkin_id: str, body: SummaryEditBody,
                             coach: dict = Depends(require_role("coach"))):
    ci = await db.check_ins.find_one({"id": checkin_id}, {"_id": 0,
                                     "atlas_client_summary_original": 1,
                                     "atlas_client_summary": 1})
    if not ci:
        raise HTTPException(404, "check-in not found")
    updates: dict[str, Any] = {
        "atlas_client_summary": body.atlas_client_summary,
        "summary_edited_by": coach["id"], "summary_edited_at": now_iso(),
    }
    if not ci.get("atlas_client_summary_original"):
        updates["atlas_client_summary_original"] = ci.get("atlas_client_summary") or ""
    await db.check_ins.update_one({"id": checkin_id}, {"$set": updates})
    ci = await db.check_ins.find_one({"id": checkin_id}, {"_id": 0})
    return {"check_in": ci}


@api.post("/coach/checkins/{checkin_id}/script/reset")
async def coach_reset_script(checkin_id: str, coach: dict = Depends(require_role("coach"))):
    ci = await db.check_ins.find_one({"id": checkin_id}, {"_id": 0, "weekly_video_script_original": 1})
    if not ci:
        raise HTTPException(404, "check-in not found")
    original = ci.get("weekly_video_script_original")
    if not original:
        raise HTTPException(400, "no original Atlas script preserved for this check-in")
    await db.check_ins.update_one({"id": checkin_id}, {"$set": {
        "weekly_video_script": original,
        "script_edited_by": None, "script_edited_at": None,
    }})
    ci = await db.check_ins.find_one({"id": checkin_id}, {"_id": 0})
    return {"check_in": ci}


@api.post("/coach/checkins/{checkin_id}/summary/reset")
async def coach_reset_summary(checkin_id: str, coach: dict = Depends(require_role("coach"))):
    ci = await db.check_ins.find_one({"id": checkin_id}, {"_id": 0, "atlas_client_summary_original": 1})
    if not ci:
        raise HTTPException(404, "check-in not found")
    original = ci.get("atlas_client_summary_original")
    if not original:
        raise HTTPException(400, "no original Atlas summary preserved for this check-in")
    await db.check_ins.update_one({"id": checkin_id}, {"$set": {
        "atlas_client_summary": original,
        "summary_edited_by": None, "summary_edited_at": None,
    }})
    ci = await db.check_ins.find_one({"id": checkin_id}, {"_id": 0})
    return {"check_in": ci}


# ---------------------------------------------------------------------------
# Iter181e · Coach management of the LLM-generated check-in question set.
# ---------------------------------------------------------------------------
# The coach sees the same list the client will see, and can add/remove
# questions from either the WEEKLY or MONTHLY set BEFORE the client submits.
# Any edit stamps the doc as coach_edited and never gets overwritten by
# subsequent LLM regeneration unless the coach explicitly asks for one.
# ---------------------------------------------------------------------------

class CheckinQuestionsPatchBody(BaseModel):
    type: Optional[str] = "weekly"        # "weekly" | "monthly"
    questions: list[dict]                 # full replacement list, ≤ 10


@api.get("/coach/checkins/questions/{client_id}")
async def coach_checkin_questions_get(
    client_id: str,
    type: str = "weekly",
    coach: dict = Depends(require_role("coach")),
):
    if type not in ("weekly", "monthly"):
        raise HTTPException(400, "type must be 'weekly' or 'monthly'")
    client_user = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not client_user:
        raise HTTPException(404, "client not found")
    ws, _we = _current_week_bounds(client_user)
    doc = await _get_or_generate_checkin_questions(
        client_user, week_start=ws, mode=type,
    )
    doc.pop("_id", None)
    return {"check_in_questions": doc}


@api.put("/coach/checkins/questions/{client_id}")
async def coach_checkin_questions_put(
    client_id: str,
    body: CheckinQuestionsPatchBody,
    coach: dict = Depends(require_role("coach")),
):
    """Replace the client's question list. Coach can add / remove items
    freely — server enforces the 10-item cap and validates shape."""
    if body.type not in ("weekly", "monthly"):
        raise HTTPException(400, "type must be 'weekly' or 'monthly'")
    client_user = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not client_user:
        raise HTTPException(404, "client not found")
    ws, _we = _current_week_bounds(client_user)

    cleaned: list[dict] = []
    seen_ids: set[str] = set()
    for q in (body.questions or [])[: _MAX_CHECKIN_QUESTIONS]:
        qid = str((q or {}).get("id") or "").strip().lower().replace(" ", "_")
        label = str((q or {}).get("label") or "").strip()
        qtype = (q or {}).get("type") or "text"
        if qtype not in ("scale", "choice", "text"):
            qtype = "text"
        if not qid or not label or qid in seen_ids:
            continue
        seen_ids.add(qid)
        row: dict = {"id": qid, "label": label, "type": qtype}
        if qtype == "scale":
            row["min"] = int((q or {}).get("min") or 1)
            row["max"] = int((q or {}).get("max") or 5)
        elif qtype == "choice":
            opts = [str(o) for o in ((q or {}).get("options") or []) if str(o).strip()]
            if len(opts) < 2:
                row["type"] = "text"
            else:
                row["options"] = opts[:5]
        cleaned.append(row)
    if not cleaned:
        raise HTTPException(400, "At least one valid question is required")
    if len(cleaned) > _MAX_CHECKIN_QUESTIONS:
        cleaned = cleaned[: _MAX_CHECKIN_QUESTIONS]

    await db.check_in_questions.update_one(
        {"user_id": client_id, "week_start": ws, "type": body.type},
        {"$set": {
            "user_id": client_id, "week_start": ws, "type": body.type,
            "questions": cleaned,
            "coach_edited_at": now_iso(),
            "coach_edited_by": coach["id"],
            "generated_by": "coach",
        }},
        upsert=True,
    )
    doc = await db.check_in_questions.find_one(
        {"user_id": client_id, "week_start": ws, "type": body.type},
        {"_id": 0},
    )
    return {"check_in_questions": doc}


@api.post("/coach/checkins/questions/{client_id}/regenerate")
async def coach_checkin_questions_regenerate(
    client_id: str,
    type: str = "weekly",
    coach: dict = Depends(require_role("coach")),
):
    """Force-regenerate the LLM question set (discards coach edits for
    this week). Coach opt-in — the regular GET never overwrites edits."""
    if type not in ("weekly", "monthly"):
        raise HTTPException(400, "type must be 'weekly' or 'monthly'")
    client_user = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not client_user:
        raise HTTPException(404, "client not found")
    ws, _we = _current_week_bounds(client_user)
    qs = await _generate_checkin_questions_via_llm(client_user, mode=type)
    doc = {
        "id": new_id(),
        "user_id": client_id, "week_start": ws, "type": type,
        "questions": qs,
        "generated_at": now_iso(),
        "generated_by": "atlas",
        "coach_edited_at": None,
        "coach_edited_by": None,
    }
    await db.check_in_questions.update_one(
        {"user_id": client_id, "week_start": ws, "type": type},
        {"$set": doc}, upsert=True,
    )
    return {"check_in_questions": doc}


# Iter 162 · Welcome Video script generator ------------------------------
#
# Called from the coach's Record-Welcome-Video button. Pulls the client's
# first name, primary goal ("why it matters"), and 1-2 salient DNA
# findings, then asks Claude Sonnet to write a 30-45 second first-person
# welcome script the coach reads on camera. Ends with the mandatory
# "Welcome to CrewFit." sign-off.

class WelcomeScriptGenBody(BaseModel):
    client_id: str


def _extract_first_name(user: dict) -> str:
    """Best-effort first name from a user doc."""
    for key in ("display_name", "name"):
        v = user.get(key)
        if v:
            first = str(v).strip().split()[0]
            if first:
                return first
    # Fall back to email local-part.
    email = user.get("email") or ""
    if "@" in email:
        return email.split("@", 1)[0].split(".")[0].title()
    return "there"


def _pick_dna_highlights(dna: dict) -> list[str]:
    """Return up to two short human-readable highlights from the DNA payload
    so the LLM has concrete material to reference. Never returns an empty
    list — even a fresh assessment yields *something* to greet on."""
    picks: list[str] = []
    if dna.get("biggest_strength"):
        picks.append(f"biggest strength — {dna['biggest_strength']}")
    if dna.get("biggest_opportunity") and len(picks) < 2:
        picks.append(f"biggest opportunity — {dna['biggest_opportunity']}")
    if dna.get("recovery_risk") and len(picks) < 2:
        picks.append(f"recovery risk profile — {dna['recovery_risk']}")
    if dna.get("motivation_style") and len(picks) < 2:
        picks.append(f"motivation style — {dna['motivation_style']}")
    if not picks and dna.get("flying_style"):
        picks.append(f"aviation profile — {dna['flying_style']}")
    return picks or ["their commitment to getting started with CrewFit"]


@api.post("/coach/welcome-script/generate")
async def coach_generate_welcome_script(
    body: WelcomeScriptGenBody,
    coach: dict = Depends(require_role("coach")),
):
    """Generate a personalised welcome-video script for a client.

    Response shape::

        {
          "script": "<30-45s first-person script>",
          "client_first_name": "<name>",
          "used_fallback": <bool>  # true when DNA / goal are missing
        }
    """
    client = await db.users.find_one(
        {"id": body.client_id},
        {"_id": 0, "id": 1, "name": 1, "display_name": 1, "email": 1,
         "profile": 1, "role": 1},
    )
    if not client:
        raise HTTPException(404, "client not found")
    if client.get("role") not in (None, "client"):
        raise HTTPException(400, "target user is not a client")

    first_name = _extract_first_name(client)
    dna = await _get_dna_context(body.client_id)

    goal = dna.get("primary_goal") or None
    why = dna.get("why_it_matters") or None
    highlights = _pick_dna_highlights(dna)
    airline = ((client.get("profile") or {}).get("airline")) or None
    role = ((client.get("profile") or {}).get("job_title")) or None

    used_fallback = not bool(goal or dna)
    if used_fallback:
        # No DNA yet — still write something warm and personal from name +
        # role/airline. Keeps the coach unblocked before assessment lands.
        script = (
            f"Hey {first_name}, welcome aboard. I'm really glad you're here. "
            f"We're going to build a plan that fits around your flying, your recovery, "
            f"and the goals that matter to you — one honest week at a time. "
            f"Once you've completed your assessment I'll dial the whole thing in around your DNA, "
            f"but until then, know that I've got your back. "
            f"Welcome to CrewFit."
        )
        return {
            "script": script,
            "client_first_name": first_name,
            "used_fallback": True,
        }

    system_msg = (
        "You are Louis, the head coach at CrewFit — a training platform built "
        "for airline crew (pilots and cabin crew). Your voice is warm, direct, "
        "grounded, and human. You never sound like an ad. You never over-promise. "
        "Every script you write is meant to be read on-camera by the coach and "
        "delivered to the client as a personalised welcome message. Aim for 30-45 "
        "seconds when read aloud (roughly 90-130 words). Use the client's first "
        "name once at the start and never again. Do NOT use emojis, headers, or "
        "bullet points — the script must read as flowing spoken language. "
        "The final line MUST be exactly: 'Welcome to CrewFit.'"
    )

    user_prompt = (
        f"Write a 30-45 second welcome-video script for a new CrewFit client.\n\n"
        f"CLIENT PROFILE\n"
        f"  First name: {first_name}\n"
        f"  Role: {role or 'aviation professional'}\n"
        f"  Airline: {airline or '(not specified)'}\n\n"
        f"WHAT MATTERS TO THEM\n"
        f"  Primary goal: {goal or '(not yet stated)'}\n"
        f"  Why it matters: {why or '(not yet stated)'}\n\n"
        f"DNA ASSESSMENT HIGHLIGHTS (reference ONE of these — the most personal / "
        f"training-relevant — do NOT list all of them):\n"
        + "\n".join(f"  - {h}" for h in highlights)
        + "\n\n"
        f"STRUCTURE (must follow, in order, in flowing speech — not headings):\n"
        f"  1. Greet {first_name} by first name.\n"
        f"  2. Restate their primary goal in your own words and acknowledge why "
        f"it matters to them.\n"
        f"  3. Reference ONE concrete finding from the DNA highlights that "
        f"tells them you've read their assessment.\n"
        f"  4. One sentence about how CrewFit will approach the work with them.\n"
        f"  5. Sign off with the exact line: 'Welcome to CrewFit.'\n\n"
        f"Return ONLY the script text — no preamble, no quotation marks, no "
        f"labels, no bullet numbers."
    )

    try:
        text = await call_claude_tracked(
            coach, feature="welcome_video_script",
            system=system_msg, prompt=user_prompt,
            max_out=800, enforce=True,
        )
    except Exception as e:
        logger.exception("welcome-script LLM call failed")
        raise HTTPException(502, f"failed to generate script: {e}")

    script = (text or "").strip().strip('"')
    # Belt-and-braces: enforce the mandatory sign-off even if the LLM drifts.
    if not script.rstrip(".").rstrip().endswith("Welcome to CrewFit"):
        script = script.rstrip(".").rstrip() + ". Welcome to CrewFit."

    return {
        "script": script,
        "client_first_name": first_name,
        "used_fallback": False,
    }


# ---- Coach Videos (storage abstraction) -----------------------------------
def _transcode_webm_to_mp4_sync(webm_bytes: bytes) -> bytes:
    """Transcode WebM bytes → MP4 (H.264/AAC + faststart) using the ffmpeg
    binary bundled by imageio-ffmpeg. Runs synchronously; call from a worker
    thread. Raises RuntimeError on ffmpeg failure.
    """
    import subprocess
    import imageio_ffmpeg  # local import — resolved lazily so cold-start is cheap
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    # Use two temp files (input + output) — piping mp4 through stdout is
    # unreliable because the mp4 muxer needs to seek back to write the
    # moov atom (which +faststart also relocates to the front).
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tin, \
         tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tout:
        in_path, out_path = tin.name, tout.name
        tin.write(webm_bytes)
        tin.flush()
    try:
        proc = subprocess.run(
            [
                ffmpeg, "-y", "-loglevel", "error",
                "-i", in_path,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                out_path,
            ],
            capture_output=True,
        )
        if proc.returncode != 0:
            err = (proc.stderr or b"").decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"ffmpeg failed (rc={proc.returncode}): {err}")
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        try:
            Path(in_path).unlink(missing_ok=True)
        except Exception:
            pass
        try:
            Path(out_path).unlink(missing_ok=True)
        except Exception:
            pass


async def _save_coach_video(video_bytes: bytes, mime: str, video_id: str) -> dict:
    """Persist a coach video via the abstracted storage driver so it survives
    server restarts and container churn.

    Iter 155 — routed through `storage.py`. When `R2_*` env vars are set,
    `storage` is the R2 driver and bytes land in the CrewFit R2 bucket.
    Falls back to the on-disk driver in dev.

    Iter190 — Incoming WebM (Chrome/Firefox MediaRecorder default) is
    transcoded to MP4 (H.264/AAC, +faststart) before storage so native
    iOS/Android players can play the file without a compatibility shim.
    QuickTime .mov is left alone — iOS players handle it natively.

    Returns::

        {
            "file_url":    str,   # served via /api/coach/videos/{id}/file
            "storage_key": str,   # canonical key in the object store
            "ext":         str,   # normalised file extension (mp4|webm|mov)
            "mime":        str,   # normalised content type
        }

    The caller is responsible for writing `storage_key` into the
    `db.weekly_videos` document alongside `file_url` so the download route
    can look the bytes back up.
    """
    ext = "mp4"
    content_type = "video/mp4"
    lower = (mime or "").lower()
    if "webm" in lower:
        # Transcode WebM → MP4 in a worker thread so the event loop stays hot.
        try:
            loop = asyncio.get_running_loop()
            video_bytes = await loop.run_in_executor(
                None, _transcode_webm_to_mp4_sync, video_bytes,
            )
            ext, content_type = "mp4", "video/mp4"
        except Exception:
            logger.exception("webm→mp4 transcode failed for %s — falling back to raw webm", video_id)
            ext, content_type = "webm", "video/webm"
    elif "quicktime" in lower or "mov" in lower:
        ext, content_type = "mov", "video/quicktime"
    # Import locally so we don't perturb the top-of-file import block; the
    # module is otherwise unused in server.py.
    from storage import storage
    storage_key = f"coach_videos/{video_id}.{ext}"
    await storage.write_bytes(storage_key, video_bytes, content_type=content_type)
    # ALSO mirror to the legacy on-disk directory when the active driver is
    # the disk one (idempotent — write_bytes has already done this). For
    # cloud drivers we skip this, since restart-persistence is guaranteed
    # by the object store and we don't want to waste ephemeral pod disk.
    return {
        "file_url": f"/api/coach/videos/{video_id}/file",
        "storage_key": storage_key,
        "ext": ext,
        "mime": content_type,
    }


class CoachVideoCreateBody(BaseModel):
    check_in_id: Optional[str] = None
    user_id: str
    script: str
    duration_seconds: Optional[int] = None
    file_b64: Optional[str] = None
    file_mime: Optional[str] = None
    file_url: Optional[str] = None
    # Iter 155 — video kind. Defaults to "weekly" for backward compatibility;
    # "welcome" is used for the one-shot onboarding message a coach records
    # for a client (surfaced by GET /videos/welcome-for-me).
    video_kind: Optional[str] = None


@api.post("/coach/videos")
async def coach_create_video(body: CoachVideoCreateBody, coach: dict = Depends(require_role("coach"))):
    video_kind = (body.video_kind or "weekly").strip().lower()
    if video_kind not in {"weekly", "welcome"}:
        raise HTTPException(400, "video_kind must be one of 'weekly' or 'welcome'")
    ci = None
    if body.check_in_id:
        ci = await db.check_ins.find_one({"id": body.check_in_id}, {"_id": 0})
        if not ci and video_kind == "weekly":
            raise HTTPException(404, "check_in not found")
    elif video_kind == "weekly":
        raise HTTPException(400, "check_in_id is required for weekly videos")
    video_id = new_id()
    file_url = body.file_url
    storage_key: Optional[str] = None
    file_ext: Optional[str] = None
    file_mime: Optional[str] = None
    if body.file_b64 and not file_url:
        try:
            raw = base64.b64decode(body.file_b64.split(",")[-1])
            saved = await _save_coach_video(raw, body.file_mime or "video/mp4", video_id)
            file_url = saved["file_url"]
            storage_key = saved["storage_key"]
            file_ext = saved["ext"]
            file_mime = saved["mime"]
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"invalid file_b64: {e}")
    doc = {
        "id": video_id,
        "user_id": body.user_id,
        "coach_id": coach["id"],
        "check_in_id": body.check_in_id,
        "video_kind": video_kind,
        "script": body.script,
        "file_url": file_url,
        "storage_key": storage_key,
        "file_ext": file_ext,
        "file_mime": file_mime,
        "thumbnail_url": None,
        "duration_seconds": body.duration_seconds,
        "status": "draft" if not file_url else "recorded",
        "created_at": now_iso(),
        "sent_at": None,
        "watched_at": None,
    }
    await db.weekly_videos.insert_one(doc)
    # Iter186+ · Generate a 3-5 bullet summary for EVERY video (welcome
    # + weekly) — client screen renders these under the player. Fires
    # in the background so upload latency isn't affected. `_spawn_bg`
    # holds a strong ref so Python's GC can't drop the task under load.
    if body.script:
        try:
            from feature_welcome_video_summary import stamp_welcome_summary
            _spawn_bg(stamp_welcome_summary(db, video_id, body.script))
        except Exception:
            logger.exception("video-summary bg spawn failed for %s", video_id)
    # Iter 145 — prevent orphan uploads: only attach to a check_in that
    # doesn't already have a SENT video. If the check_in already has a
    # different sent video, this becomes a new draft attached but the
    # sent record stays authoritative.
    # (Skipped for welcome videos — they are not check-in scoped.)
    if body.check_in_id and video_kind == "weekly":
        ci_row = await db.check_ins.find_one({"id": body.check_in_id}, {"_id": 0, "weekly_video_status": 1})
        current_status = str((ci_row or {}).get("weekly_video_status") or "")
        if current_status != "sent":
            set_updates = {"weekly_video_id": video_id, "weekly_video_status": doc["status"]}
            if file_url:
                set_updates["weekly_video_uploaded_at"] = doc["created_at"]
            await db.check_ins.update_one({"id": body.check_in_id}, {"$set": set_updates})
    doc.pop("_id", None)
    return {"video": doc}


@api.post("/coach/videos/{video_id}/send")
async def coach_send_video(video_id: str, coach: dict = Depends(require_role("coach"))):
    v = await db.weekly_videos.find_one({"id": video_id}, {"_id": 0})
    if not v:
        raise HTTPException(404, "video not found")
    # Iter 145 — idempotent re-send guard: if already sent, return the
    # existing sent_at without firing another push notification or
    # creating another message record.
    if v.get("status") == "sent" and v.get("sent_at"):
        return {"ok": True, "sent_at": v["sent_at"], "already_sent": True}
    if not v.get("file_url"):
        raise HTTPException(400, "video has no uploaded file — cannot send")
    now = now_iso()
    await db.weekly_videos.update_one({"id": video_id}, {"$set": {"status": "sent", "sent_at": now}})
    # Iter 156 — welcome videos have no check_in_id → skip the check-in
    # / coach-task stamping for them. Weekly videos still update both.
    if v.get("check_in_id"):
        await db.check_ins.update_one({"id": v["check_in_id"]}, {"$set": {
            "weekly_video_status": "sent", "weekly_video_sent_at": now,
        }})
        await db.coach_tasks.update_many(
            {"check_in_id": v["check_in_id"], "task_type": "record_weekly_video"},
            {"$set": {"status": "sent", "completed_at": now, "video_id": video_id}},
        )
    # Notify the client (push + in-app). Iter187 · Pass video_kind so the
    # welcome video sends the "Welcome Video from Your Coach" copy
    # instead of the legacy "Weekly Coaching Review" title.
    try:
        await notify_weekly_video_ready(
            v["user_id"], video_id, video_kind=str(v.get("video_kind") or "weekly"),
        )
    except Exception:
        logger.exception("weekly video notify failed")
    # Create client-facing message record
    is_welcome = v.get("video_kind") == "welcome"
    await db.messages.insert_one({
        "id": new_id(),
        "from_id": coach["id"],
        "to_id": v["user_id"],
        "kind": "welcome_video" if is_welcome else "weekly_video",
        "video_id": video_id,
        "body": (
            "Your coach recorded a welcome video for you."
            if is_welcome else
            "Your weekly coaching review is ready."
        ),
        "created_at": now,
        "read_at": None,
    })
    return {"ok": True, "sent_at": now}


# Iter 145 — client marks the video as viewed (first-view analytics only).
@api.post("/coach/videos/{video_id}/viewed")
async def video_viewed(video_id: str, user: dict = Depends(current_user)):
    v = await db.weekly_videos.find_one({"id": video_id}, {"_id": 0, "user_id": 1, "watched_at": 1, "check_in_id": 1})
    if not v:
        raise HTTPException(404, "video not found")
    if v.get("user_id") != user["id"]:
        raise HTTPException(403, "not your video")
    if v.get("watched_at"):
        return {"ok": True, "first_view": False}
    now = now_iso()
    await db.weekly_videos.update_one({"id": video_id}, {"$set": {"watched_at": now, "status": "viewed"}})
    # Iter 156 — welcome videos have no check_in_id; only stamp the check-in
    # row when this is a weekly video linked to one.
    if v.get("check_in_id"):
        await db.check_ins.update_one({"id": v["check_in_id"]}, {"$set": {
            "weekly_video_status": "viewed", "weekly_video_viewed_at": now,
        }})
    return {"ok": True, "first_view": True, "watched_at": now}


@api.get("/coach/videos/{video_id}/file")
async def coach_video_file(video_id: str, request: Request):
    """Serve a coach-recorded video.

    Iter 155 — routed through `storage.py`. Behaviour:
      1. Look up the video doc to get its `storage_key` (new schema).
      2. Read the bytes via the active storage driver (R2 or disk).
      3. Fall back to the legacy on-disk directory for videos recorded
         BEFORE the storage migration (docs without a `storage_key`).

    Iter190 — Emits `Accept-Ranges: bytes` on every 200 response and
    honours `Range: bytes=start-end` by slicing the buffer and returning
    a 206 Partial Content response so native <video> players (iOS
    AVPlayer, Android ExoPlayer) can seek/stream instead of downloading
    the whole file up-front.

    No auth for MVP — swap for signed URLs when we start putting these
    behind a public CDN.
    """
    # Local imports avoid disturbing the top-of-file import block.
    from storage import storage
    from fastapi.responses import Response

    doc = await db.weekly_videos.find_one(
        {"id": video_id},
        {"_id": 0, "storage_key": 1, "file_ext": 1, "file_mime": 1},
    )
    mimes = {"mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime"}

    data: Optional[bytes] = None
    media_type = "video/mp4"
    file_ext = "mp4"

    if doc and doc.get("storage_key"):
        data = await storage.read_bytes(doc["storage_key"])
        if data is not None:
            file_ext = doc.get("file_ext") or "mp4"
            media_type = doc.get("file_mime") or mimes.get(file_ext, "video/mp4")

    # Legacy fallback: on-disk file laid down before the migration.
    if data is None:
        for ext in ("mp4", "webm", "mov"):
            p = COACH_VIDEO_DIR / f"{video_id}.{ext}"
            if p.exists():
                try:
                    data = p.read_bytes()
                    file_ext = ext
                    media_type = mimes[ext]
                    break
                except Exception:
                    logger.exception("coach video legacy read failed for %s", p)

    if data is None:
        raise HTTPException(404, "video file not found")

    total = len(data)
    filename = f"{video_id}.{file_ext}"
    range_header = request.headers.get("range") or request.headers.get("Range")

    # Handle HTTP Range requests (RFC 7233) — required for native players
    # to seek. We only support a single `bytes=start-end` range which is
    # what iOS/Android request in practice.
    if range_header:
        try:
            units, _, rng = range_header.partition("=")
            if units.strip().lower() != "bytes":
                raise ValueError("unsupported range units")
            first_range = rng.split(",")[0].strip()
            start_s, _, end_s = first_range.partition("-")
            if start_s == "":
                # Suffix range: "-500" → last 500 bytes.
                length = int(end_s)
                if length <= 0:
                    raise ValueError("invalid suffix length")
                start = max(0, total - length)
                end = total - 1
            else:
                start = int(start_s)
                end = int(end_s) if end_s else total - 1
            if start > end or start >= total:
                # RFC 7233 §4.4 — 416 Range Not Satisfiable.
                return Response(
                    status_code=416,
                    headers={
                        "Content-Range": f"bytes */{total}",
                        "Accept-Ranges": "bytes",
                    },
                )
            end = min(end, total - 1)
            chunk = data[start:end + 1]
            return Response(
                content=chunk,
                status_code=206,
                media_type=media_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{total}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(len(chunk)),
                    "Cache-Control": "private, max-age=3600",
                    "Content-Disposition": f'inline; filename="{filename}"',
                },
            )
        except (ValueError, TypeError):
            # Malformed Range — fall through to full 200 response.
            pass

    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(total),
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": f'inline; filename="{filename}"',
        },
    )


@api.get("/videos/for-me")
async def videos_for_me(user: dict = Depends(current_user)):
    """Client fetches their weekly videos.

    Iter 165 — Now includes:
      * All `status: "sent"` (unwatched) videos.
      * Recently-viewed videos still inside a 24-hour grace period so the
        client can re-open the card if they closed it before finishing.

    Iter188 · Lazy self-heal for ANY row that has a script but no
    `script_summary` (previously the heal only fired on the direct
    `/videos/{id}` lookup, but the frontend hits this list endpoint
    FIRST, so the heal never got a chance to run for videos surfaced
    through the client home banner).
    """
    grace_cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=24)).isoformat()
    rows = await db.weekly_videos.find(
        {
            "user_id": user["id"],
            "$or": [
                {"status": "sent"},
                {"status": "viewed", "watched_at": {"$gte": grace_cutoff}},
            ],
        },
        {"_id": 0},
    ).sort("sent_at", -1).to_list(20)
    try:
        from feature_welcome_video_summary import stamp_welcome_summary
        for r in rows:
            if not r.get("script_summary") and (r.get("script") or "").strip():
                _spawn_bg(stamp_welcome_summary(db, r["id"], r.get("script") or ""))
    except Exception:
        logger.exception("lazy video-summary spawn (for-me) failed")
    return {"videos": rows}


@api.get("/videos/welcome-for-me")
async def videos_welcome_for_me(user: dict = Depends(current_user)):
    """Iter 155 — return the current welcome video for the caller.

    Iter 165 — Persistence rules:
      * Return the video while it is unwatched (`status: "sent"`).
      * ALSO return the video for 24 hours after first view so a client
        who accidentally closed it can find it again.
      * After the grace period expires the endpoint returns `video: null`
        and the banner disappears permanently.

    Iter188 · Same lazy self-heal as the list endpoint — welcome videos
    created before the summary generator got backfilled will now spawn
    their bullets on first open.
    """
    grace_cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=24)).isoformat()
    row = await db.weekly_videos.find_one(
        {
            "user_id": user["id"],
            "video_kind": "welcome",
            "$or": [
                {"status": "sent"},
                {"status": "viewed", "watched_at": {"$gte": grace_cutoff}},
            ],
        },
        {"_id": 0},
        sort=[("sent_at", -1)],
    )
    try:
        if row and not row.get("script_summary") and (row.get("script") or "").strip():
            from feature_welcome_video_summary import stamp_welcome_summary
            _spawn_bg(stamp_welcome_summary(db, row["id"], row.get("script") or ""))
    except Exception:
        logger.exception("lazy video-summary spawn (welcome-for-me) failed")
    return {"video": row}


@api.get("/videos/{video_id}")
async def videos_get_one(video_id: str, user: dict = Depends(current_user)):
    """Iter 165 — Direct lookup by ID, bypasses status filters.

    The player screen needs to keep working even if the row transitions
    from `sent → viewed` while it is being loaded (e.g. banner tap fires
    the mark-viewed request in the background while the player still
    needs to fetch the video). The list endpoints filter by status; this
    endpoint does not, so the player is always resilient.

    Iter186 · Self-healing summary — if this is a WELCOME video that
    was created *before* the summary generator was deployed (or the
    background stamp failed), spawn it lazily on the very next fetch.
    Fire-and-forget so the request stays snappy; the client falls back
    to the "Summary generating…" placeholder and gets the bullets on
    the next open. Prevents the "no bullets" regression that hits the
    first cohort of videos post-deploy.
    """
    row = await db.weekly_videos.find_one(
        {"id": video_id, "user_id": user["id"]}, {"_id": 0}
    )
    if not row:
        raise HTTPException(404, "video not found")
    try:
        if (
            not row.get("script_summary")
            and (row.get("script") or "").strip()
        ):
            # Iter186+ · Lazy self-heal for ANY video (welcome + weekly)
            # that has a script but no summary. Fire-and-forget so the
            # request stays snappy; the client falls back to the
            # "Summary generating…" placeholder and gets the bullets on
            # the next open. Covers the backfill gap + any race where
            # the create-time hook missed.
            from feature_welcome_video_summary import stamp_welcome_summary
            _spawn_bg(stamp_welcome_summary(db, video_id, row.get("script") or ""))
    except Exception:
        logger.exception("lazy video-summary spawn failed for %s", video_id)
    return {"video": row}


@api.post("/videos/{video_id}/watched")
async def video_watched(video_id: str, user: dict = Depends(current_user)):
    await db.weekly_videos.update_one(
        {"id": video_id, "user_id": user["id"]},
        {"$set": {"watched_at": now_iso()}},
    )
    return {"ok": True}


# ---- Reminder Scheduler Worker --------------------------------------------
REMINDER_SLOTS: list = []  # Iter181e — killed; retained only as an empty
# placeholder in case any external import still references the symbol.


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


# Iter181e · Tick A killed. All weekly-check-in reminders now come from
# `feature_notifications._tick_roster_and_workout_reminders` (Tick B),
# which is the single source of truth. `_tick_reminders` below is kept
# as a NO-OP so any legacy call site importing the symbol still works,
# but it never touches the DB.
async def _tick_reminders() -> None:
    return None


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








# ---------------------------------------------------------------------------
# Extracted feature modules — imported at the bottom so they can `from server
# import ...` all the symbols they need (which are all defined above).
# ---------------------------------------------------------------------------
import feature_coach_v1        # noqa: E402,F401  registers coach draft/controls/change-log endpoints on `api`
import feature_habits          # noqa: E402,F401  registers habit endpoints on `api`
import feature_notifications   # noqa: E402,F401  registers notification endpoints on `api`
import feature_standby         # noqa: E402,F401  registers standby endpoints on `api`
import feature_social_studio   # noqa: E402,F401  registers admin social-studio endpoints on `api`
import feature_profile         # noqa: E402,F401  registers profile-photo + location endpoints on `api`
import feature_brand_images    # noqa: E402,F401  registers CrewFit AI-image library endpoints on `api`
import feature_exercise_content  # noqa: E402,F401  unified Exercise Content Library endpoints
import feature_nutrition        # noqa: E402,F401  Nutrition Centre — Phase 1 (targets, logs, hydration, atlas tip)
import feature_nutrition_barcode  # noqa: E402,F401  Nutrition Centre — Phase 2 (barcode + food-DB lookup)
import feature_nutrition_photo   # noqa: E402,F401  Nutrition Centre — Phase 3 (AI photo meal scanner)
import feature_nutrition_travel  # noqa: E402,F401  Nutrition Centre — Phase 4 (roster/airport/timing/guide)
import feature_nutrition_insights  # noqa: E402,F401  Nutrition Centre — Phase 5 (adaptive insights + coach todos)
import feature_admin_migrations  # noqa: E402,F401  Ops: storage backfill + exercise-library migration
import feature_coach_docs  # noqa: E402,F401  Serves /api/docs/* markdown
import feature_admin_telemetry   # noqa: E402,F401  Ops: AI usage + cost telemetry admin dashboard
import feature_crew_base         # noqa: E402,F401  Iter 129: Crew Base community MVP (posts/comments/reactions/scheduler)
import feature_coach_inbox       # noqa: E402,F401  Iter 129d: Coach Messages inbox + client-context aggregation
import feature_gdpr              # noqa: E402,F401  GDPR: soft-delete, data export, purge cron
import feature_preview           # noqa: E402,F401  Coach preview-as-client + UI issue reporter
import feature_beta_readiness    # noqa: E402,F401  Beta wiring: storage smoke test + disclaimer
import feature_personal_activities  # noqa: E402,F401  Personal Activity Planner (client sports/hobbies)
import feature_setup_day             # noqa: E402,F401  Setup-day gate — first workout starts tomorrow
import feature_event_categories      # noqa: E402,F401  Category-aware Event Training
import feature_programme_quality     # noqa: E402,F401  Programme quality: goals/phase/validation/persistence
import feature_roster_confirmation   # noqa: E402,F401  Phase 2: parse → confirm → build roster flow
import feature_traffic_light         # noqa: E402,F401  Phase 3: Green/Amber/Red workout variants
import feature_v2_resolver           # noqa: E402,F401  Phase 5: V2 Library resolver + demand-driven exercise requests
import feature_exercise_request_tasks  # noqa: E402,F401  Plan D1-3: exercise-request → coach To-Do + reconciliation
import feature_admin_lifecycle       # noqa: E402,F401  Coach dashboard slice 1: archive / delete / audit log
import feature_coach_deep_edit       # noqa: E402,F401  Coach dashboard slice 3.5: workout/roster deep-edit endpoints
import feature_preview_sandbox       # noqa: E402,F401  Persistent New Client Preview sandbox + reset
import feature_roster_lifecycle      # noqa: E402,F401  Plan D4-7: client roster delete + restart + cascade cleanup
import feature_reassessment_micro    # noqa: E402,F401  Short kind-specific reassessment forms (no full DNA rebuild)
import feature_coach_programme_overview  # noqa: E402,F401  Plan C3: coach programme overview + timeline
import feature_coach_workout_editor      # noqa: E402,F401  Plan C4-C7: coach workout editor, exercise swap, single/programme regen
import feature_coach_manual_workouts     # noqa: E402,F401  Phase 1 Manual Workout Builder + day-level overrides
import feature_coach_admin_actions       # noqa: E402,F401  Iter 140b: manual_draft_override toggle + workouts bulk-delete
import feature_programme_import          # noqa: E402,F401  Phase 1: Monthly programme JSON import (preview / dry-run)
import feature_manual_mode_reset         # noqa: E402,F401  Phase 1B programme reset (dry-run + execute)
import feature_flight_support_coverage   # noqa: E402,F401  Manual Mode Stage C — Flight Support library backfill
import feature_exercise_pipeline_audit   # noqa: E402,F401  Manual Mode Stage A — pipeline audit + fuzzy dedup
import feature_hotel_conversion_repair   # noqa: E402,F401  Hotel Gym conversion — library-first + validation
import feature_client_issues             # noqa: E402,F401  Report an Issue — client bug report inbox
import feature_coach_roster_months       # noqa: E402,F401  Phase 1: coach monthly roster/programme control centre
import feature_coach_roster_upload       # noqa: E402,F401  Phase A · A2: coach uploads roster on behalf of client
import feature_v2_state_foundation        # noqa: E402,F401  V2 Phase 1: DRAFT/LIVE state layer (feature-flagged, off by default)
import feature_v2_common                  # noqa: E402,F401  V2 shared helpers (flag gate + DecisionRecord)
import feature_v2_p2_goals                # noqa: E402,F401  V2 Phase 2: Goals + Programmes + Phases catalog + engine
import feature_v2_p3_demand               # noqa: E402,F401  V2 Phase 3: Training-demand engine (WHAT)
import feature_v2_p4_roster               # noqa: E402,F401  V2 Phase 4: Structured roster facets (schedule_days/duties/sectors)
import feature_v2_p5_scheduling           # noqa: E402,F401  V2 Phase 5: Scheduling engine (WHEN) + validation V1..V6
import feature_v2_p6_construction         # noqa: E402,F401  V2 Phase 6: Workout construction (HOW) + slot templates
import feature_v2_p7_equipment            # noqa: E402,F401  V2 Phase 7: EquipmentContext + SAB + adapt flow
import feature_v2_p8_progression          # noqa: E402,F401  V2 Phase 8: Progression states + PerformanceRecord
import feature_v2_p9_events               # noqa: E402,F401  V2 Phase 9: Event countdown + phase transitions
import feature_v2_p10_reality             # noqa: E402,F401  V2 Phase 10: Readiness + Today's Reality chip resolver
import feature_v2_p12_automation          # noqa: E402,F401  V2 Phase 12: Job runner + shadow mode + metrics
import feature_v2_coach_dashboard         # noqa: E402,F401  V2 Phase 11: Coach Dashboard V2 aggregate endpoints
import feature_v2_coach_command_bar       # noqa: E402,F401  V2 Phase 11: Coach Dashboard V2 · Command Bar (LLM → structured proposals)
import feature_v2_coach_directives        # noqa: E402,F401  V2 Phase 11: Coach Dashboard V2 · Directive editor + generation status + programme summary
import feature_v2_coach_publish           # noqa: E402,F401  V2 Phase 11: Coach Dashboard V2 · Draft-vs-Live diff + selective publish
import feature_v2_coach_inline_editor     # noqa: E402,F401  V2 Phase 11: Coach Dashboard V2 · Inline workout implementation editor
import feature_v2_coach_kickoff           # noqa: E402,F401  V2 Phase 11: One-click plan scaffold (programme + phases + P3 + P5 + P6)
import feature_v2_coach_client_admin     # noqa: E402,F401  V2 Phase 11: Coach Dashboard V2 · Delete client + all references
import feature_v2_coach_training_availability  # noqa: E402,F401  Iter 130j: Coach lift of per-client training caps
import feature_v2_coach_home              # noqa: E402,F401  Iter 128g: Coach Home action queue (deterministic aggregator)
import feature_v2_engine_v2_kickoff       # noqa: E402,F401  V2 Engine V2: WHAT→WHEN→HOW→VALIDATE pipeline (feature-flagged Draft-only)
import feature_v2_engine_v2_publish       # noqa: E402,F401  V2 Engine V2: Coach Dashboard Draft integration + Client Live read
import feature_aviation_support_api        # noqa: E402,F401  Aviation Support Phase B: coach controls + client today
import feature_v2_plan_live_adapt          # noqa: E402,F401  Iter 118 Change Setup — HOW-only adapt

import feature_coach_audit_bundle         # noqa: E402,F401  Serves the collated Coach Dashboard audit bundle at a stable URL
import feature_coach_live_feed           # noqa: E402,F401  Phase 2: main coach dashboard live feed (next-5-days cross-client)
import feature_roster_versions           # noqa: E402,F401  Phase 3: multi-roster overlap resolution + version history
import feature_coach_workout_swap        # noqa: E402,F401  Phase 5: coach inline workout-swap picker (alternative presets)
import feature_coach_notes               # noqa: E402,F401  Phase 6: per-client structured coach notes injected into plan generator
import feature_coach_reset               # noqa: E402,F401  Phase 6: coach reset-programme utility
import feature_programme_status         # noqa: E402,F401  Phase 7A: programme status + coach approve-programme
import feature_timezone_current           # noqa: E402,F401  Iter 94m: home base + current timezone card + confirm endpoint
import feature_calendar_recovery          # noqa: E402,F401  Iter 94s: calendar range + missed workout recovery
import feature_app_config                 # noqa: E402,F401  Iter 94t Phase 1: remote config + feature flags
import feature_media_reconciliation       # noqa: E402,F401  Iter 94t Phase 1: exercise media reconciliation + coach tasks
import feature_progress_dynamic           # noqa: E402,F401  Iter 94t Phase 3: goal-adaptive progress + charts
import feature_daily_briefing             # noqa: E402,F401  Iter 94u: Daily briefing from Louis + coach profile
import feature_weekly_review              # noqa: E402,F401  Iter 94w: Sunday weekly review from Louis
import feature_dual_session               # noqa: E402,F401  Iter 95a: Short-haul dual-session (airport activation) suggestions
import feature_equipment_guard            # noqa: E402,F401  Iter 95h: Prevents equipment-mismatch workouts (client owns gear, gets bodyweight)
import feature_client_summary             # noqa: E402,F401  Detailed Client Summary (renamed from Goals tab) + cached LLM coach briefing
import feature_auto_media_gen             # noqa: E402,F401  Auto-generate exercise media (Nano Banana + coaching points) on creation. Coach still approves.
import feature_youtube_video_finder       # noqa: E402,F401  Iter183 · YouTube ≤60s exercise-demo finder + bulk sweep.

# Rebind feature-module functions into the server namespace so pre-existing
# call sites in server.py (which look these up at runtime) continue to work.
_seed_habits_for_user_by_id = feature_habits._seed_habits_for_user_by_id
_run_habit_review_after_checkin = feature_habits._run_habit_review_after_checkin
_bg_generate_message_draft = feature_coach_v1._bg_generate_message_draft
notify_coach_message = feature_notifications.notify_coach_message
notify_coach_draft_ready = feature_notifications.notify_coach_draft_ready
notify_weekly_video_ready = feature_notifications.notify_weekly_video_ready
notify_roster_approved = feature_notifications.notify_roster_approved
notify_programme_updated = feature_notifications.notify_programme_updated
enqueue_notification = feature_notifications.enqueue_notification

# Compose the reminder tick chain now that all feature modules are loaded.
_tick_base = _tick_reminders

async def _tick_reminders_all() -> None:
    await _tick_base()
    try:
        await feature_habits._tick_habit_reminders()
    except Exception:
        logger.exception("habit tick failed")
    try:
        await feature_notifications._tick_roster_and_workout_reminders()
    except Exception:
        logger.exception("roster/workout tick failed")
    try:
        await feature_roster_lifecycle._tick_roster_no_replacement_warning()
    except Exception:
        logger.exception("roster no-replacement tick failed")
    # Iter189w · Auto-approval REMOVED per user request. A programme /
    # roster must only become live when the coach explicitly approves.
    # No timer, no automatic status change, no background job promoting
    # a programme to live, and no automatic client message. The coach's
    # manual approval is the sole trigger. Tick preserved below only
    # for future reintroduction — currently a no-op.
    # try:
    #     import feature_roster_coach_review as _rcr
    #     await _rcr._tick_auto_approve_stale_reviews(db)
    # except Exception:
    #     logger.exception("roster coach-review auto-approve tick failed")
    try:
        await feature_social_studio._tick_daily_social()
    except Exception:
        logger.exception("daily social tick failed")
    # Iter182b · deployment health-check — auto-destructive scheduler
    # paths (GDPR expired-user hard-delete and preview throwaway hard-
    # delete) are now GATED behind explicit env flags. Both default to
    # OFF so the scheduler never destructively touches user data unless
    # an operator has consciously enabled the flag on that environment.
    # Flip on via .env when you actually want the purge to run.
    if os.environ.get("GDPR_AUTO_PURGE", "false").strip().lower() in ("1","true","yes","on"):
        try:
            # GDPR purge: bounded to 100 users per run and idempotent.
            await feature_gdpr.gdpr_purge_expired()
        except Exception:
            logger.exception("gdpr purge tick failed")
    if os.environ.get("PREVIEW_AUTO_PURGE", "false").strip().lower() in ("1","true","yes","on"):
        try:
            # Preview throwaway purge: removes new-client preview accounts past 24h.
            await feature_preview.preview_purge_throwaways()
        except Exception:
            logger.exception("preview purge tick failed")
    # Iter 127 — Flight Support duty-aware push scheduler.
    try:
        from feature_flight_support_notifier import flight_support_scheduler_tick
        from feature_notifications import enqueue_notification as _en_notif
        await flight_support_scheduler_tick(db, _en_notif)
    except Exception:
        logger.exception("flight support tick failed")

_tick_reminders = _tick_reminders_all

# --- Message attachments (media on chat messages) -----------------------
try:
    from feature_message_attachments import register as _register_msg_attachments
    from storage import storage as _storage_for_msg
    _register_msg_attachments(
        api,
        db=db,
        current_user=current_user,
        storage=_storage_for_msg,
        new_id=new_id,
        now_iso=now_iso,
        clean_doc=clean_doc,
        send_push=send_push,
    )
except Exception:
    logger.exception("feature_message_attachments failed to register")

# --- Food Search (Nutrition Centre) --------------------------------------
try:
    from feature_food_search import register as _register_food_search
    _register_food_search(
        api,
        db=db,
        current_user=current_user,
        emergent_llm_key=os.environ.get("EMERGENT_LLM_KEY"),
    )
except Exception:
    logger.exception("feature_food_search failed to register")

# Iter 95n — mount the roster review-delay status endpoint under /api.
try:
    from feature_roster_review_delay import make_router as _rrd_make_router
    api.include_router(_rrd_make_router(db, current_user))
    logger.info("feature_roster_review_delay: /roster/status registered")
except Exception:
    logger.exception("feature_roster_review_delay failed to register")

# Iter186 — mount roster coach-review state machine (submission-state
# for the client lock card + coach approve/reject + auto-approve tick).
try:
    from feature_roster_coach_review import make_router as _rcr_make_router
    api.include_router(_rcr_make_router(db, current_user, require_role))
    logger.info("feature_roster_coach_review: submission-state + coach review registered")
except Exception:
    logger.exception("feature_roster_coach_review failed to register")

# Iter186 — mount welcome-video summary + coach welcome-lookup endpoints.
try:
    from feature_welcome_video_summary import make_router as _wvs_make_router
    api.include_router(_wvs_make_router(db, require_role))
    logger.info("feature_welcome_video_summary: welcome summary + coach lookup registered")
except Exception:
    logger.exception("feature_welcome_video_summary failed to register")

# Iter 128 — Flight Support media resolver (3-stage carousel + Pilot persona)
try:
    from feature_flight_support_media import register_routes as _fs_media_register
    _fs_media_register(app, current_user)
except Exception:
    logger.exception("feature_flight_support_media failed to register")

# Iter188 — Coach-facing logging-type override for the workout player
# (timer vs reps vs cardio). Long-tail escape hatch for any exercise the
# client-side classifier miscategorises.
try:
    from feature_logging_type_override import register as _logtype_register
    _logtype_register(api, db, require_role)
except Exception:
    logger.exception("feature_logging_type_override failed to register")

app.include_router(api)


# ---------------------------------------------------------------------------
# Preview-mode write guard.
# Blocks all POST/PUT/PATCH/DELETE requests when the JWT has preview:true,
# with a small allow-list for exit + issue reporting. This is the safety net
# that keeps coaches from accidentally mutating a real client's data while
# they are inspecting the app from the client perspective.
# ---------------------------------------------------------------------------
_PREVIEW_WRITE_ALLOWLIST = {
    "/api/coach/preview/exit",
    "/api/preview/ui-issue",
    "/api/auth/logout",   # allow the coach to escape via logout too
}


@app.middleware("http")
async def preview_readonly_guard(request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        auth = request.headers.get("authorization") or ""
        if auth.startswith("Bearer "):
            try:
                payload = jwt.decode(auth.split(" ", 1)[1], JWT_SECRET, algorithms=[JWT_ALGO])
            except Exception:
                payload = None
            if payload and payload.get("preview"):
                # Sandbox preview is fully writable by design — Louis needs to
                # walk through onboarding, roster upload, workouts, etc. as a
                # brand-new client. Only real-client impersonation stays R/O.
                if payload.get("preview_kind") == "sandbox":
                    return await call_next(request)
                path = request.url.path
                if path not in _PREVIEW_WRITE_ALLOWLIST:
                    from fastapi.responses import JSONResponse
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": {
                                "error": "preview_readonly",
                                "message": "Preview mode is read-only. Exit preview to make changes.",
                            }
                        },
                    )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)
