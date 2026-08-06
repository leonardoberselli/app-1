from fastapi import FastAPI, APIRouter, HTTPException, Header, Depends
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
import httpx
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime, timezone, timedelta


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI()
api_router = APIRouter(prefix="/api")

EMERGENT_SESSION_API = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"


# ============================== Models ==============================

class User(BaseModel):
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    gender: Optional[Literal["male", "female", "other"]] = None
    age: Optional[int] = None
    profile_complete: bool = False
    created_at: datetime


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    picture: Optional[str] = None  # base64 data URI or URL
    gender: Optional[Literal["male", "female", "other"]] = None
    age: Optional[int] = Field(default=None, ge=0, le=120)


class SessionRequest(BaseModel):
    session_id: str


class AuthResponse(BaseModel):
    session_token: str
    user: User


class GroupCreate(BaseModel):
    title: str
    category: str
    category_label: str
    location: str
    description: Optional[str] = ""
    date: str  # YYYY-MM-DD
    time: str  # HH:MM
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


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def get_current_user(authorization: Optional[str] = Header(None)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1].strip()
    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    if _aware(session["expires_at"]) < _now():
        raise HTTPException(status_code=401, detail="Session expired")
    user_doc = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    return User(**user_doc)


def _strip(d: dict) -> dict:
    d.pop("_id", None)
    return d


# ============================== Auth ==============================

@api_router.post("/auth/session", response_model=AuthResponse)
async def auth_session(req: SessionRequest):
    """Exchange Emergent session_id for our session_token + user."""
    async with httpx.AsyncClient(timeout=20.0) as http:
        try:
            resp = await http.get(
                EMERGENT_SESSION_API,
                headers={"X-Session-ID": req.session_id},
            )
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Auth upstream error: {e}")
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session_id")
    data = resp.json()
    email = data["email"]
    name = data.get("name") or email.split("@")[0]
    picture = data.get("picture")
    session_token = data["session_token"]

    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        # Only update name from Google; keep custom picture if user already set one.
        updates = {"name": name}
        if not existing.get("picture"):
            updates["picture"] = picture
        await db.users.update_one({"user_id": user_id}, {"$set": updates})
        user_doc = {**existing, **updates}
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user_doc = {
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
            "gender": None,
            "age": None,
            "profile_complete": False,
            "created_at": _now(),
        }
        await db.users.insert_one(dict(user_doc))
        user_doc = _strip(user_doc)

    await db.user_sessions.update_one(
        {"session_token": session_token},
        {"$set": {
            "session_token": session_token,
            "user_id": user_id,
            "expires_at": _now() + timedelta(days=7),
            "created_at": _now(),
        }},
        upsert=True,
    )
    return AuthResponse(session_token=session_token, user=User(**user_doc))


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
    # Recompute profile_complete flag
    fresh = await db.users.find_one({"user_id": user.user_id}, {"_id": 0})
    complete = bool(fresh.get("gender")) and fresh.get("age") is not None and bool(fresh.get("picture"))
    if fresh.get("profile_complete") != complete:
        await db.users.update_one(
            {"user_id": user.user_id}, {"$set": {"profile_complete": complete}}
        )
        fresh["profile_complete"] = complete
    return User(**fresh)


@api_router.post("/auth/logout")
async def auth_logout(authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        await db.user_sessions.delete_one({"session_token": token})
    return {"ok": True}


# ============================== Groups ==============================

def _group_doc_to_model(d: dict) -> Group:
    d = _strip(dict(d))
    return Group(**d)


@api_router.post("/groups", response_model=Group)
async def create_group(payload: GroupCreate, user: User = Depends(get_current_user)):
    if payload.max_participants < payload.min_participants:
        raise HTTPException(status_code=400, detail="max_participants < min_participants")
    if payload.max_age < payload.min_age:
        raise HTTPException(status_code=400, detail="max_age < min_age")
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
    g = await db.groups.find_one({"group_id": group_id}, {"_id": 0})
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    return Group(**g)


@api_router.post("/groups/{group_id}/join", response_model=Group)
async def join_group(group_id: str, user: User = Depends(get_current_user)):
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
        await db.users.create_index("email", unique=True)
        await db.users.create_index("user_id", unique=True)
        await db.user_sessions.create_index("session_token", unique=True)
        await db.user_sessions.create_index("user_id")
        await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)
        await db.groups.create_index("group_id", unique=True)
        await db.groups.create_index("category")
        await db.messages.create_index("group_id")
    except Exception as e:
        logger.warning(f"index creation issue: {e}")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
