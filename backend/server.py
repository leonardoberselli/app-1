from fastapi import FastAPI, APIRouter, HTTPException, Header, Depends
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import re
import asyncio
import logging
import uuid
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime, timezone, timedelta

try:
    # stdlib on Python 3.9+; container has 3.11
    from zoneinfo import ZoneInfo
    _APP_TZ = ZoneInfo("Europe/Rome")
except Exception:  # pragma: no cover
    _APP_TZ = timezone.utc


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# ============================== MongoDB ==============================
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI()
api_router = APIRouter(prefix="/api")


# ============================== Models ==============================

class User(BaseModel):
    user_id: str            # Device UUID (bearer token)
    name: str = ""
    picture: Optional[str] = None
    gender: Optional[Literal["male", "female", "other"]] = None
    age: Optional[int] = None
    profile_complete: bool = False
    created_at: datetime


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    picture: Optional[str] = None
    gender: Optional[Literal["male", "female", "other"]] = None
    age: Optional[int] = Field(default=None, ge=0, le=120)


class GroupCreate(BaseModel):
    title: str
    category: str
    category_label: str
    location: str
    description: Optional[str] = ""
    date: str
    time: str
    min_participants: int = Field(ge=1, le=200)
    max_participants: int = Field(ge=1, le=200)
    min_age: int = Field(ge=0, le=120)
    max_age: int = Field(ge=0, le=120)


class Group(BaseModel):
    group_id: str
    title: str
    category: str
    category_label: str
    location: str
    description: str
    date: str
    time: str
    min_participants: int
    max_participants: int
    min_age: int
    max_age: int
    owner_id: str
    owner_name: str
    owner_picture: Optional[str] = None
    participants: List[dict] = []
    created_at: datetime


class MessageCreate(BaseModel):
    text: str


class Message(BaseModel):
    message_id: str
    group_id: str
    user_id: str
    user_name: str
    user_picture: Optional[str] = None
    text: str
    created_at: datetime


# ============================== Helpers ==============================

def _now():
    return datetime.now(timezone.utc)


def _strip(d: dict) -> dict:
    d.pop("_id", None)
    return d


_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{8,128}$")


def _user_from_doc(doc: dict) -> User:
    doc = _strip(dict(doc))
    # Drop obsolete Firebase fields if present
    for k in ("email", "email_verified", "providers"):
        doc.pop(k, None)
    doc.setdefault("name", "")
    doc.setdefault("picture", None)
    doc.setdefault("gender", None)
    doc.setdefault("age", None)
    doc.setdefault("profile_complete", False)
    return User(**doc)


async def _get_or_create_user(device_id: str) -> dict:
    """Find or create a MongoDB user keyed by the device UUID.

    There is no login: the frontend sends a locally-generated device UUID as a
    Bearer token; we treat it as the user_id. The first call for a new device
    auto-creates an empty profile; the user then fills in name (mandatory) and
    optionally photo/gender/age via /auth/me.
    """
    existing = await db.users.find_one({"user_id": device_id}, {"_id": 0})
    if existing:
        return existing

    doc = {
        "user_id": device_id,
        "name": "",
        "picture": None,
        "gender": None,
        "age": None,
        "profile_complete": False,
        "created_at": _now(),
    }
    await db.users.insert_one(dict(doc))
    return _strip(doc)


async def get_current_user(authorization: Optional[str] = Header(None)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing device id")
    device_id = authorization.split(" ", 1)[1].strip()
    if not _DEVICE_ID_RE.match(device_id):
        raise HTTPException(status_code=401, detail="Device id non valido")
    doc = await _get_or_create_user(device_id)
    return _user_from_doc(doc)


# ============================== Expired-group cleanup ==============================

# Groups auto-delete when their event start time is more than
# EXPIRED_BUFFER_HOURS hours in the past. Rationale: an event at 20:00 is
# usable until at least ~23:00 the same evening.
EXPIRED_BUFFER_HOURS = 3
# Throttle in-request purge so it runs at most once every N seconds.
_PURGE_MIN_INTERVAL_S = 30
_last_purge_at: float = 0.0


def _event_datetime(date_str: str, time_str: str) -> Optional[datetime]:
    """Combine stored `date` (YYYY-MM-DD, or legacy DD/MM/YYYY) + `time`
    (HH:MM) into a timezone-aware datetime in Europe/Rome (the user-facing
    timezone). Returns None if the strings are malformed.
    """
    if not date_str or not time_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M"):
        try:
            dt = datetime.strptime(f"{date_str} {time_str}", fmt)
            return dt.replace(tzinfo=_APP_TZ)
        except ValueError:
            continue
    return None


async def _purge_expired_groups(force: bool = False) -> List[str]:
    """Delete every group whose event start + buffer is in the past, plus
    all chat messages attached to them. Returns the list of deleted group
    ids. Safe to call from any request path; throttled to avoid running on
    every single hit. `force=True` bypasses the throttle and does NOT update
    the throttle timestamp, so it doesn't block in-request purges.
    """
    global _last_purge_at
    loop = asyncio.get_event_loop()
    now_mono = loop.time()
    if not force:
        if (now_mono - _last_purge_at) < _PURGE_MIN_INTERVAL_S:
            return []
        _last_purge_at = now_mono

    threshold = datetime.now(_APP_TZ) - timedelta(hours=EXPIRED_BUFFER_HOURS)
    expired: List[str] = []
    cursor = db.groups.find({}, {"_id": 0, "group_id": 1, "date": 1, "time": 1})
    async for g in cursor:
        dt = _event_datetime(g.get("date", ""), g.get("time", ""))
        if dt is not None and dt < threshold:
            expired.append(g["group_id"])
    if expired:
        await db.groups.delete_many({"group_id": {"$in": expired}})
        await db.messages.delete_many({"group_id": {"$in": expired}})
        try:
            logger.info(f"[cleanup] purged {len(expired)} expired group(s)")
        except Exception:
            pass
    return expired


# ============================== Auth ==============================

@api_router.get("/auth/me", response_model=User)
async def auth_me(user: User = Depends(get_current_user)):
    return user


@api_router.patch("/auth/me", response_model=User)
async def auth_update_me(payload: ProfileUpdate, user: User = Depends(get_current_user)):
    updates: dict = {}
    if payload.name is not None:
        n = payload.name.strip()
        if n:
            updates["name"] = n
    if payload.picture is not None:
        updates["picture"] = payload.picture
    if payload.gender is not None:
        updates["gender"] = payload.gender
    if payload.age is not None:
        updates["age"] = payload.age
    if updates:
        await db.users.update_one({"user_id": user.user_id}, {"$set": updates})
    fresh = await db.users.find_one({"user_id": user.user_id}, {"_id": 0})
    complete = (
        bool(fresh.get("name"))
        and bool(fresh.get("gender"))
        and fresh.get("age") is not None
        and bool(fresh.get("picture"))
    )
    if fresh.get("profile_complete") != complete:
        await db.users.update_one(
            {"user_id": user.user_id}, {"$set": {"profile_complete": complete}}
        )
        fresh["profile_complete"] = complete
    # Also propagate name/picture to existing groups/messages authored by user
    if "name" in updates or "picture" in updates:
        new_name = fresh.get("name") or ""
        new_pic = fresh.get("picture")
        await db.groups.update_many(
            {"owner_id": user.user_id},
            {"$set": {"owner_name": new_name, "owner_picture": new_pic}},
        )
        await db.groups.update_many(
            {"participants.user_id": user.user_id},
            {
                "$set": {
                    "participants.$[p].name": new_name,
                    "participants.$[p].picture": new_pic,
                }
            },
            array_filters=[{"p.user_id": user.user_id}],
        )
    return _user_from_doc(fresh)


# ============================== Groups ==============================

def _group_doc_to_model(d: dict) -> Group:
    d = _strip(dict(d))
    return Group(**d)


@api_router.post("/groups", response_model=Group)
async def create_group(payload: GroupCreate, user: User = Depends(get_current_user)):
    if not user.name:
        raise HTTPException(status_code=400, detail="Completa il profilo (nome) prima di creare un gruppo")
    if payload.max_participants < payload.min_participants:
        raise HTTPException(status_code=400, detail="max_participants < min_participants")
    if payload.max_age < payload.min_age:
        raise HTTPException(status_code=400, detail="max_age < min_age")
    # Reject events that are already expired (past date + buffer) at creation
    event_dt = _event_datetime(payload.date, payload.time)
    if event_dt is None:
        raise HTTPException(status_code=400, detail="Data/ora non valide")
    now_local = datetime.now(_APP_TZ)
    if event_dt + timedelta(hours=EXPIRED_BUFFER_HOURS) < now_local:
        raise HTTPException(status_code=400, detail="Data del gruppo nel passato")
    group_id = f"grp_{uuid.uuid4().hex[:12]}"
    owner_participant = {
        "user_id": user.user_id,
        "name": user.name,
        "picture": user.picture,
    }
    doc = {
        "group_id": group_id,
        "title": payload.title.strip(),
        "category": payload.category,
        "category_label": payload.category_label,
        "location": payload.location.strip(),
        "description": (payload.description or "").strip(),
        "date": payload.date,
        "time": payload.time,
        "min_participants": payload.min_participants,
        "max_participants": payload.max_participants,
        "min_age": payload.min_age,
        "max_age": payload.max_age,
        "owner_id": user.user_id,
        "owner_name": user.name,
        "owner_picture": user.picture,
        "participants": [owner_participant],
        "created_at": _now(),
    }
    await db.groups.insert_one(dict(doc))
    return _group_doc_to_model(doc)


@api_router.get("/groups", response_model=List[Group])
async def list_groups(category: Optional[str] = None, q: Optional[str] = None):
    await _purge_expired_groups()
    query: dict = {}
    if category and category != "all":
        query["category"] = category
    if q:
        query["title"] = {"$regex": q, "$options": "i"}
    cursor = db.groups.find(query, {"_id": 0}).sort("created_at", -1).limit(200)
    items = await cursor.to_list(length=200)
    return [Group(**i) for i in items]


@api_router.get("/groups/mine", response_model=dict)
async def my_groups(user: User = Depends(get_current_user)):
    await _purge_expired_groups()
    created = await db.groups.find(
        {"owner_id": user.user_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(length=200)
    joined = await db.groups.find(
        {"participants.user_id": user.user_id, "owner_id": {"$ne": user.user_id}},
        {"_id": 0},
    ).sort("created_at", -1).to_list(length=200)
    return {
        "created": [Group(**g).model_dump() for g in created],
        "joined": [Group(**g).model_dump() for g in joined],
    }


@api_router.get("/groups/{group_id}", response_model=Group)
async def get_group(group_id: str):
    await _purge_expired_groups()
    g = await db.groups.find_one({"group_id": group_id}, {"_id": 0})
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    return Group(**g)


@api_router.post("/groups/{group_id}/join", response_model=Group)
async def join_group(group_id: str, user: User = Depends(get_current_user)):
    if not user.name:
        raise HTTPException(status_code=400, detail="Completa il profilo (nome) prima di unirti")
    g = await db.groups.find_one({"group_id": group_id}, {"_id": 0})
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    if any(p["user_id"] == user.user_id for p in g["participants"]):
        return Group(**g)
    if len(g["participants"]) >= g["max_participants"]:
        raise HTTPException(status_code=400, detail="Gruppo al completo")
    new_part = {"user_id": user.user_id, "name": user.name, "picture": user.picture}
    await db.groups.update_one(
        {"group_id": group_id},
        {"$push": {"participants": new_part}},
    )
    g["participants"].append(new_part)
    return Group(**g)


@api_router.post("/groups/{group_id}/leave", response_model=Group)
async def leave_group(group_id: str, user: User = Depends(get_current_user)):
    g = await db.groups.find_one({"group_id": group_id}, {"_id": 0})
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    if g["owner_id"] == user.user_id:
        raise HTTPException(status_code=400, detail="Il creatore non può lasciare il gruppo")
    await db.groups.update_one(
        {"group_id": group_id},
        {"$pull": {"participants": {"user_id": user.user_id}}},
    )
    g["participants"] = [p for p in g["participants"] if p["user_id"] != user.user_id]
    return Group(**g)


@api_router.delete("/groups/{group_id}")
async def delete_group(group_id: str, user: User = Depends(get_current_user)):
    g = await db.groups.find_one({"group_id": group_id}, {"_id": 0})
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    if g["owner_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Solo il creatore può eliminare il gruppo")
    await db.groups.delete_one({"group_id": group_id})
    await db.messages.delete_many({"group_id": group_id})
    return {"ok": True}


# ============================== Chat ==============================

@api_router.get("/groups/{group_id}/messages", response_model=List[Message])
async def get_messages(group_id: str, user: User = Depends(get_current_user)):
    g = await db.groups.find_one({"group_id": group_id}, {"_id": 0})
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    if not any(p["user_id"] == user.user_id for p in g["participants"]):
        raise HTTPException(status_code=403, detail="Unisciti al gruppo per vedere la chat")
    items = await db.messages.find(
        {"group_id": group_id}, {"_id": 0}
    ).sort("created_at", 1).to_list(length=1000)
    return [Message(**m) for m in items]


@api_router.post("/groups/{group_id}/messages", response_model=Message)
async def post_message(group_id: str, payload: MessageCreate, user: User = Depends(get_current_user)):
    if not user.name:
        raise HTTPException(status_code=400, detail="Completa il profilo (nome) prima di scrivere")
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Messaggio vuoto")
    g = await db.groups.find_one({"group_id": group_id}, {"_id": 0})
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    if not any(p["user_id"] == user.user_id for p in g["participants"]):
        raise HTTPException(status_code=403, detail="Unisciti al gruppo per inviare messaggi")
    msg = {
        "message_id": f"msg_{uuid.uuid4().hex[:12]}",
        "group_id": group_id,
        "user_id": user.user_id,
        "user_name": user.name,
        "user_picture": user.picture,
        "text": text,
        "created_at": _now(),
    }
    await db.messages.insert_one(dict(msg))
    return Message(**_strip(msg))


# ============================== Health ==============================

@api_router.get("/")
async def root():
    return {"message": "GroupUp API"}


# ============================== App setup ==============================

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def on_startup():
    try:
        await db.users.create_index("user_id", unique=True)
        await db.groups.create_index("group_id", unique=True)
        await db.groups.create_index("category")
        await db.messages.create_index("group_id")
        # Drop any legacy Firebase indexes if they exist
        try:
            await db.users.drop_index("email_1")
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"index creation issue: {e}")

    # Kick off a background loop that purges expired groups every 5 minutes.
    # In-request purges cover fast-path cleanup; this catches idle windows.
    async def _bg_purge_loop():
        while True:
            try:
                await _purge_expired_groups(force=True)
            except Exception as e:
                logger.warning(f"bg purge error: {e}")
            await asyncio.sleep(300)  # 5 min

    app.state._purge_task = asyncio.create_task(_bg_purge_loop())


@app.on_event("shutdown")
async def shutdown_db_client():
    task = getattr(app.state, "_purge_task", None)
    if task:
        task.cancel()
    client.close()
