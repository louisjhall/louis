"""CrewFit V1 backend.

Aviation-crew fitness coaching:
    - JWT auth (client / coach roles)
    - Roster upload + AI extraction (Gemini) + Green/Amber/Red scoring
    - AI weekly workout generation (Claude Sonnet 4.5)
    - Coach approval + workout editing
    - Nutrition log w/ AI meal feedback
    - Weekly check-ins, progress photos, messaging, exercise library
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
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Any, Literal, Optional

import bcrypt
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

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGO = os.environ.get("JWT_ALGORITHM", "HS256")
EMERGENT_LLM_KEY = os.environ["EMERGENT_LLM_KEY"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
logger = logging.getLogger("crewfit")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="CrewFit V1")
api = APIRouter(prefix="/api")


# ------------------------------------------------------------------
# Auth helpers
# ------------------------------------------------------------------
def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_pw(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def make_token(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(days=30),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


async def current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Bad token: {e}")
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


def require_role(role: str):
    async def _dep(user: dict = Depends(current_user)) -> dict:
        if user["role"] != role:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"{role} role required")
        return user

    return _dep


# ------------------------------------------------------------------
# Models
# ------------------------------------------------------------------
Role = Literal["client", "coach"]
DayLoad = Literal["green", "amber", "red"]


class SignupBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str
    role: Role = "client"


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class OnboardingBody(BaseModel):
    airline: Optional[str] = None
    position: Optional[str] = None  # pilot / cabin crew
    experience_level: Optional[str] = None  # beginner / intermediate / advanced
    training_days_per_week: int = 4
    goals: Optional[str] = None
    equipment: Optional[list[str]] = None  # dumbbells / bands / hotel-room-only
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    calorie_target: Optional[int] = 2200
    protein_target: Optional[int] = 150


class RosterExtractBody(BaseModel):
    file_base64: str  # data URL or raw base64
    mime_type: str  # application/pdf, image/png, image/jpeg
    week_start: Optional[str] = None  # ISO date


class RosterConfirmBody(BaseModel):
    days: list[dict]  # confirmed day objects


class WorkoutGenerateBody(BaseModel):
    roster_id: str


class WorkoutUpdateBody(BaseModel):
    title: Optional[str] = None
    exercises: Optional[list[dict]] = None
    day_load: Optional[DayLoad] = None
    coach_notes: Optional[str] = None
    approved: Optional[bool] = None


class WorkoutCompleteBody(BaseModel):
    completed_exercises: list[dict]
    rpe: Optional[int] = None  # rate of perceived exertion 1-10
    notes: Optional[str] = None


class ExerciseBody(BaseModel):
    name: str
    category: str  # push / pull / legs / core / mobility / cardio
    equipment: list[str] = []
    demo_url: Optional[str] = None
    notes: Optional[str] = None


class CheckInBody(BaseModel):
    week_start: str
    energy: int = Field(ge=1, le=10)
    sleep: int = Field(ge=1, le=10)
    soreness: int = Field(ge=1, le=10)
    stress: int = Field(ge=1, le=10)
    weight_kg: Optional[float] = None
    notes: Optional[str] = None


class MealBody(BaseModel):
    meal_type: str  # breakfast / lunch / dinner / snack
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


# ------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------
def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_doc(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


def strip_data_url(b64: str) -> str:
    if b64.startswith("data:"):
        return b64.split(",", 1)[1]
    return b64


async def write_temp(b64: str, mime: str) -> str:
    ext = {
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
    }.get(mime, ".bin")
    fd, path = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    with open(path, "wb") as f:
        f.write(base64.b64decode(strip_data_url(b64)))
    return path


def parse_json_from_text(text: str) -> Any:
    """Robust JSON extraction from LLM responses."""
    # Try direct
    try:
        return json.loads(text)
    except Exception:
        pass
    # Try fenced code block
    m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # Try to find first { ... } or [ ... ]
    for open_c, close_c in [("{", "}"), ("[", "]")]:
        s = text.find(open_c)
        e = text.rfind(close_c)
        if s != -1 and e > s:
            try:
                return json.loads(text[s : e + 1])
            except Exception:
                continue
    raise ValueError(f"No JSON found in LLM response: {text[:200]}")


async def call_claude(system: str, prompt: str, session_id: Optional[str] = None) -> str:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id or new_id(),
        system_message=system,
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")
    resp = await chat.send_message(UserMessage(text=prompt))
    return resp if isinstance(resp, str) else str(resp)


async def call_gemini_with_file(system: str, prompt: str, file_path: str, mime: str) -> str:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=new_id(),
        system_message=system,
    ).with_model("gemini", "gemini-2.5-flash")
    fc = FileContentWithMimeType(file_path=file_path, mime_type=mime)
    resp = await chat.send_message(UserMessage(text=prompt, file_contents=[fc]))
    return resp if isinstance(resp, str) else str(resp)


# ------------------------------------------------------------------
# Auth routes
# ------------------------------------------------------------------
@api.post("/auth/signup")
async def signup(body: SignupBody):
    existing = await db.users.find_one({"email": body.email.lower()})
    if existing:
        raise HTTPException(400, "Email already registered")
    user = {
        "id": new_id(),
        "email": body.email.lower(),
        "name": body.name,
        "role": body.role,
        "password_hash": hash_pw(body.password),
        "created_at": now_iso(),
        "onboarded": False,
        "coach_id": None,
        "profile": {},
    }
    await db.users.insert_one(user)
    token = make_token(user["id"], user["role"])
    user.pop("password_hash", None)
    user.pop("_id", None)
    return {"token": token, "user": user}


@api.post("/auth/login")
async def login(body: LoginBody):
    user = await db.users.find_one({"email": body.email.lower()})
    if not user or not verify_pw(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    token = make_token(user["id"], user["role"])
    clean_doc(user)
    user.pop("password_hash", None)
    return {"token": token, "user": user}


@api.get("/auth/me")
async def me(user: dict = Depends(current_user)):
    return user


@api.post("/auth/onboarding")
async def onboarding(body: OnboardingBody, user: dict = Depends(current_user)):
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"profile": body.model_dump(), "onboarded": True}},
    )
    updated = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})
    return updated


# ------------------------------------------------------------------
# Roster
# ------------------------------------------------------------------
ROSTER_SYSTEM = (
    "You are an aviation roster parser for airline crew (pilots / cabin crew). "
    "Extract flights, duties, layovers, standbys, training, and days off from the uploaded roster. "
    "Output STRICT JSON only with schema: "
    '{"days":[{"date":"YYYY-MM-DD","type":"flight|layover|standby|off|training","flights":[{"from":"IATA","to":"IATA","dep":"HH:MM","arr":"HH:MM"}],"notes":"..."}]} '
    "Infer dates in the current or given week. Return nothing but JSON."
)


def score_day(day: dict) -> DayLoad:
    """Rules: off/layover with rest → green. Standby / training / short flight → amber.
    Multi-flight, red-eye, big timezone jump → red."""
    dtype = day.get("type", "off")
    flights = day.get("flights", []) or []
    if dtype == "off":
        return "green"
    if dtype in ("training",):
        return "amber"
    if dtype == "standby":
        return "amber"
    if dtype == "layover":
        return "green"
    if dtype == "flight":
        if len(flights) >= 2:
            return "red"
        # red-eye if departure between 22:00-05:59
        for fl in flights:
            dep = fl.get("dep", "")
            if len(dep) >= 2 and dep[:2].isdigit():
                h = int(dep[:2])
                if h >= 22 or h < 6:
                    return "red"
        return "amber"
    return "amber"


@api.post("/roster/extract")
async def roster_extract(body: RosterExtractBody, user: dict = Depends(current_user)):
    path = await write_temp(body.file_base64, body.mime_type)
    raw = ""
    parsed: Any = {}
    try:
        raw = await call_gemini_with_file(
            ROSTER_SYSTEM,
            "Extract every duty for the visible week. Return only JSON.",
            path,
            body.mime_type,
        )
    except Exception as e:
        logger.warning("roster gemini call failed: %s", e)
        raw = ""
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass
    try:
        parsed = parse_json_from_text(raw) if raw else {}
    except Exception as e:
        logger.warning("roster parse failed: %s", e)
        parsed = {}
    days = parsed.get("days", []) if isinstance(parsed, dict) else parsed
    if not days:
        # Fallback: 7-day off-week starting from week_start (or today)
        try:
            base = datetime.fromisoformat(body.week_start) if body.week_start else datetime.now(timezone.utc)
        except Exception:
            base = datetime.now(timezone.utc)
        days = [
            {"date": (base + timedelta(days=i)).date().isoformat(), "type": "off", "flights": [], "notes": ""}
            for i in range(7)
        ]
    for d in days:
        d["load"] = score_day(d)
    roster = {
        "id": new_id(),
        "user_id": user["id"],
        "created_at": now_iso(),
        "week_start": body.week_start or (days[0]["date"] if days else date.today().isoformat()),
        "days": days,
        "confirmed": False,
        "raw_response": raw[:4000],
    }
    await db.rosters.insert_one(roster)
    clean_doc(roster)
    return roster


@api.post("/roster/{roster_id}/confirm")
async def roster_confirm(roster_id: str, body: RosterConfirmBody, user: dict = Depends(current_user)):
    # rescore after edits
    for d in body.days:
        d["load"] = score_day(d)
    await db.rosters.update_one(
        {"id": roster_id, "user_id": user["id"]},
        {"$set": {"days": body.days, "confirmed": True, "confirmed_at": now_iso()}},
    )
    r = await db.rosters.find_one({"id": roster_id}, {"_id": 0})
    return r


@api.get("/roster/current")
async def roster_current(user: dict = Depends(current_user)):
    r = await db.rosters.find_one(
        {"user_id": user["id"]}, {"_id": 0}, sort=[("created_at", -1)]
    )
    return r or {}


# ------------------------------------------------------------------
# Workouts (AI generation + CRUD)
# ------------------------------------------------------------------
WORKOUT_SYSTEM = (
    "You are CrewFit, an elite S&C coach specializing in training airline crew around brutal rosters. "
    "Given the client's profile and a week of days with load status (green/amber/red), design one workout per training day. "
    "Rules: RED day = mobility/recovery/short zone-2 only. AMBER day = shorter session, lower volume. GREEN day = full session. "
    "Respect the client's training_days_per_week: pick days with best load first. "
    "Return STRICT JSON: "
    '{"workouts":[{"date":"YYYY-MM-DD","day_load":"green|amber|red","title":"...","duration_min":45,'
    '"focus":"push|pull|legs|full|mobility|zone2","exercises":['
    '{"name":"Goblet Squat","sets":3,"reps":"10","rest_sec":60,"notes":"..."}'
    "],\"rationale\":\"why this workout fits this day\"}]}"
)


@api.post("/workouts/generate")
async def workouts_generate(body: WorkoutGenerateBody, user: dict = Depends(current_user)):
    roster = await db.rosters.find_one({"id": body.roster_id, "user_id": user["id"]}, {"_id": 0})
    if not roster:
        raise HTTPException(404, "Roster not found")
    profile = user.get("profile", {})
    prompt = (
        f"Client profile: {json.dumps(profile)}\n"
        f"Week days: {json.dumps(roster['days'])}\n"
        "Design the week now."
    )
    raw = await call_claude(WORKOUT_SYSTEM, prompt)
    try:
        parsed = parse_json_from_text(raw)
        workouts_list = parsed.get("workouts", []) if isinstance(parsed, dict) else parsed
    except Exception as e:
        logger.warning("workout gen parse fail: %s", e)
        workouts_list = []

    # Persist as individual workouts
    saved = []
    # Delete existing workouts for this roster week
    await db.workouts.delete_many({"user_id": user["id"], "roster_id": body.roster_id})
    for w in workouts_list:
        w_doc = {
            "id": new_id(),
            "user_id": user["id"],
            "roster_id": body.roster_id,
            "date": w.get("date"),
            "day_load": w.get("day_load", "green"),
            "title": w.get("title", "Session"),
            "duration_min": w.get("duration_min", 45),
            "focus": w.get("focus", "full"),
            "exercises": w.get("exercises", []),
            "rationale": w.get("rationale", ""),
            "approved": False,
            "completed": False,
            "coach_notes": "",
            "created_at": now_iso(),
        }
        await db.workouts.insert_one(w_doc)
        clean_doc(w_doc)
        saved.append(w_doc)
    return {"workouts": saved, "raw_rationale": raw[:2000]}


@api.get("/workouts/week")
async def workouts_week(user: dict = Depends(current_user)):
    rows = await db.workouts.find({"user_id": user["id"]}, {"_id": 0}).sort("date", 1).to_list(200)
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
    w = await db.workouts.find_one({"id": wid}, {"_id": 0})
    return w


@api.post("/workouts/{wid}/complete")
async def workout_complete(wid: str, body: WorkoutCompleteBody, user: dict = Depends(current_user)):
    await db.workouts.update_one(
        {"id": wid, "user_id": user["id"]},
        {
            "$set": {
                "completed": True,
                "completed_at": now_iso(),
                "completion": body.model_dump(),
            }
        },
    )
    w = await db.workouts.find_one({"id": wid}, {"_id": 0})
    return w


# ------------------------------------------------------------------
# Exercises library
# ------------------------------------------------------------------
@api.get("/exercises")
async def exercises_list(user: dict = Depends(current_user)):
    rows = await db.exercises.find({}, {"_id": 0}).to_list(500)
    return rows


@api.post("/exercises")
async def exercises_create(body: ExerciseBody, coach: dict = Depends(require_role("coach"))):
    doc = {"id": new_id(), **body.model_dump(), "created_at": now_iso()}
    await db.exercises.insert_one(doc)
    clean_doc(doc)
    return doc


@api.delete("/exercises/{eid}")
async def exercises_delete(eid: str, coach: dict = Depends(require_role("coach"))):
    await db.exercises.delete_one({"id": eid})
    return {"ok": True}


# ------------------------------------------------------------------
# Check-ins
# ------------------------------------------------------------------
@api.post("/checkins")
async def checkin_create(body: CheckInBody, user: dict = Depends(current_user)):
    doc = {
        "id": new_id(),
        "user_id": user["id"],
        "created_at": now_iso(),
        **body.model_dump(),
    }
    await db.checkins.insert_one(doc)
    clean_doc(doc)
    return doc


@api.get("/checkins")
async def checkin_list(user: dict = Depends(current_user)):
    rows = await db.checkins.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(50)
    return rows


# ------------------------------------------------------------------
# Nutrition
# ------------------------------------------------------------------
MEAL_SYSTEM = (
    "You are a nutrition coach for airline crew. Given a meal photo + description, give a 3-sentence assessment: "
    "estimate calories & protein (grams), rate quality 1-10, one improvement tip. "
    'Return STRICT JSON: {"calories":Int,"protein_g":Int,"quality":Int,"tip":"...","summary":"..."}'
)


@api.post("/nutrition/meals")
async def meal_create(body: MealBody, user: dict = Depends(current_user)):
    doc = {
        "id": new_id(),
        "user_id": user["id"],
        "created_at": now_iso(),
        **body.model_dump(),
        "ai_feedback": None,
    }
    # AI feedback if photo present
    if body.photo_base64 and body.photo_mime:
        path = await write_temp(body.photo_base64, body.photo_mime)
        try:
            raw = await call_gemini_with_file(
                MEAL_SYSTEM,
                f"Meal type: {body.meal_type}. Description: {body.description}",
                path,
                body.photo_mime,
            )
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
                os.unlink(path)
            except Exception:
                pass
    await db.meals.insert_one(doc)
    clean_doc(doc)
    return doc


@api.get("/nutrition/meals")
async def meal_list(user: dict = Depends(current_user), date_filter: Optional[str] = None):
    q = {"user_id": user["id"]}
    if date_filter:
        q["created_at"] = {"$regex": f"^{date_filter}"}
    rows = await db.meals.find(q, {"_id": 0}).sort("created_at", -1).to_list(100)
    return rows


@api.get("/nutrition/summary")
async def nutrition_summary(user: dict = Depends(current_user)):
    today = date.today().isoformat()
    rows = await db.meals.find(
        {"user_id": user["id"], "created_at": {"$regex": f"^{today}"}}, {"_id": 0}
    ).to_list(50)
    cal = sum(r.get("calories") or 0 for r in rows)
    pro = sum(r.get("protein_g") or 0 for r in rows)
    profile = user.get("profile", {})
    return {
        "date": today,
        "calories": cal,
        "protein_g": pro,
        "calorie_target": profile.get("calorie_target", 2200),
        "protein_target": profile.get("protein_target", 150),
        "meals": rows,
    }


# ------------------------------------------------------------------
# Progress
# ------------------------------------------------------------------
@api.post("/progress")
async def progress_create(body: ProgressBody, user: dict = Depends(current_user)):
    doc = {"id": new_id(), "user_id": user["id"], "created_at": now_iso(), **body.model_dump()}
    await db.progress.insert_one(doc)
    clean_doc(doc)
    return doc


@api.get("/progress")
async def progress_list(user: dict = Depends(current_user)):
    rows = await db.progress.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return rows


# ------------------------------------------------------------------
# Messages
# ------------------------------------------------------------------
@api.post("/messages")
async def message_send(body: MessageBody, user: dict = Depends(current_user)):
    doc = {
        "id": new_id(),
        "from_user_id": user["id"],
        "to_user_id": body.to_user_id,
        "text": body.text,
        "created_at": now_iso(),
        "read": False,
    }
    await db.messages.insert_one(doc)
    clean_doc(doc)
    return doc


@api.get("/messages/{other_id}")
async def message_thread(other_id: str, user: dict = Depends(current_user)):
    rows = await db.messages.find(
        {
            "$or": [
                {"from_user_id": user["id"], "to_user_id": other_id},
                {"from_user_id": other_id, "to_user_id": user["id"]},
            ]
        },
        {"_id": 0},
    ).sort("created_at", 1).to_list(500)
    return rows


@api.get("/messages")
async def message_partners(user: dict = Depends(current_user)):
    # For clients: their coach. For coaches: all their clients.
    if user["role"] == "client":
        coach_id = user.get("coach_id")
        coach = await db.users.find_one({"id": coach_id}, {"_id": 0, "password_hash": 0}) if coach_id else None
        if not coach:
            coach = await db.users.find_one({"role": "coach"}, {"_id": 0, "password_hash": 0})
        return [coach] if coach else []
    else:
        rows = await db.users.find(
            {"role": "client", "coach_id": user["id"]}, {"_id": 0, "password_hash": 0}
        ).to_list(200)
        if not rows:
            rows = await db.users.find({"role": "client"}, {"_id": 0, "password_hash": 0}).to_list(200)
        return rows


# ------------------------------------------------------------------
# Coach: clients
# ------------------------------------------------------------------
@api.get("/coach/clients")
async def coach_clients(coach: dict = Depends(require_role("coach"))):
    rows = await db.users.find(
        {"role": "client"}, {"_id": 0, "password_hash": 0}
    ).to_list(500)
    # attach latest roster + pending approvals
    for r in rows:
        pending = await db.workouts.count_documents({"user_id": r["id"], "approved": False})
        roster = await db.rosters.find_one({"user_id": r["id"]}, {"_id": 0}, sort=[("created_at", -1)])
        r["pending_approvals"] = pending
        r["latest_roster"] = roster or None
    return rows


@api.get("/coach/clients/{client_id}")
async def coach_client_detail(client_id: str, coach: dict = Depends(require_role("coach"))):
    client_user = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not client_user:
        raise HTTPException(404, "Client not found")
    roster = await db.rosters.find_one({"user_id": client_id}, {"_id": 0}, sort=[("created_at", -1)])
    workouts = await db.workouts.find({"user_id": client_id}, {"_id": 0}).sort("date", 1).to_list(200)
    checkins = await db.checkins.find({"user_id": client_id}, {"_id": 0}).sort("created_at", -1).to_list(10)
    return {"client": client_user, "roster": roster, "workouts": workouts, "checkins": checkins}


@api.get("/coach/pending-approvals")
async def coach_pending(coach: dict = Depends(require_role("coach"))):
    rows = await db.workouts.find({"approved": False}, {"_id": 0}).sort("date", 1).to_list(200)
    # attach client name
    for r in rows:
        u = await db.users.find_one({"id": r["user_id"]}, {"_id": 0, "name": 1, "email": 1})
        r["client_name"] = u.get("name") if u else "Unknown"
    return rows


# ------------------------------------------------------------------
# Seed
# ------------------------------------------------------------------
DEFAULT_EXERCISES = [
    {"name": "Goblet Squat", "category": "legs", "equipment": ["dumbbell"]},
    {"name": "Push-Up", "category": "push", "equipment": ["bodyweight"]},
    {"name": "Dumbbell Row", "category": "pull", "equipment": ["dumbbell"]},
    {"name": "Hip Hinge", "category": "legs", "equipment": ["bodyweight"]},
    {"name": "Plank", "category": "core", "equipment": ["bodyweight"]},
    {"name": "Zone 2 Walk", "category": "cardio", "equipment": ["bodyweight"]},
    {"name": "World's Greatest Stretch", "category": "mobility", "equipment": ["bodyweight"]},
    {"name": "Band Pull-Apart", "category": "pull", "equipment": ["band"]},
    {"name": "Bulgarian Split Squat", "category": "legs", "equipment": ["dumbbell"]},
    {"name": "Dead Bug", "category": "core", "equipment": ["bodyweight"]},
    {"name": "Overhead Press", "category": "push", "equipment": ["dumbbell"]},
    {"name": "90/90 Hip Rotation", "category": "mobility", "equipment": ["bodyweight"]},
]


async def seed():
    coach_email = "coach@crewfit.com"
    client_email = "client@crewfit.com"
    coach = await db.users.find_one({"email": coach_email})
    if not coach:
        coach_id = new_id()
        await db.users.insert_one(
            {
                "id": coach_id,
                "email": coach_email,
                "name": "Coach Kai",
                "role": "coach",
                "password_hash": hash_pw("Coach123!"),
                "created_at": now_iso(),
                "onboarded": True,
                "coach_id": None,
                "profile": {"bio": "Head Coach, Aviation Fitness"},
            }
        )
    else:
        coach_id = coach["id"]

    client_user = await db.users.find_one({"email": client_email})
    if not client_user:
        await db.users.insert_one(
            {
                "id": new_id(),
                "email": client_email,
                "name": "Alex Rivera",
                "role": "client",
                "password_hash": hash_pw("Client123!"),
                "created_at": now_iso(),
                "onboarded": True,
                "coach_id": coach_id,
                "profile": {
                    "airline": "Skyline Air",
                    "position": "First Officer",
                    "experience_level": "intermediate",
                    "training_days_per_week": 4,
                    "goals": "Stay strong on rotations, drop 4kg",
                    "equipment": ["dumbbell", "band", "bodyweight"],
                    "height_cm": 180,
                    "weight_kg": 82,
                    "calorie_target": 2400,
                    "protein_target": 160,
                },
            }
        )

    # attach any un-attached clients to coach
    await db.users.update_many(
        {"role": "client", "coach_id": None}, {"$set": {"coach_id": coach_id}}
    )

    # seed exercises
    if await db.exercises.count_documents({}) == 0:
        for e in DEFAULT_EXERCISES:
            await db.exercises.insert_one({"id": new_id(), "created_at": now_iso(), **e})
    logger.info("Seed complete.")


@app.on_event("startup")
async def _startup():
    await seed()


@app.on_event("shutdown")
async def _shutdown():
    client.close()


@api.get("/")
async def root():
    return {"service": "CrewFit V1", "ok": True}


# Register router + CORS
app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
