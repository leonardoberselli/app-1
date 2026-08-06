from fastapi import FastAPI, APIRouter, HTTPException, Header, Depends
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
import hashlib
import secrets
import httpx
import jwt as pyjwt
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Literal
from datetime import datetime, timezone, timedelta
from passlib.context import CryptContext


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI()
api_router = APIRouter(prefix="/api")

EMERGENT_SESSION_API = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
EMAIL_BASE_URL = "https://integrations.emergentagent.com"
EMERGENT_EMAIL_KEY = os.environ.get("EMERGENT_EMAIL_KEY", "")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "GroupUp")
APP_PUBLIC_URL = os.environ.get("APP_PUBLIC_URL", "https://example.com").rstrip("/")
APPLE_AUDIENCES = [a.strip() for a in os.environ.get("APPLE_AUDIENCES", "").split(",") if a.strip()]

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
DUMMY_HASH = pwd_ctx.hash("constant-dummy-password-do-not-use")


# ============================== Models ==============================

class User(BaseModel):
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    gender: Optional[Literal["male", "female", "other"]] = None
    age: Optional[int] = None
    profile_complete: bool = False
    email_verified: bool = False
    providers: List[str] = []
    created_at: datetime


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    picture: Optional[str] = None
    gender: Optional[Literal["male", "female", "other"]] = None
    age: Optional[int] = Field(default=None, ge=0, le=120)


class SessionRequest(BaseModel):
    session_id: str


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=60)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenRequest(BaseModel):
    token: str = Field(min_length=10)


class ResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class RequestReset(BaseModel):
    email: EmailStr


class AppleAuthRequest(BaseModel):
    identity_token: str
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None


class AuthResponse(BaseModel):
    session_token: str
    user: User


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


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _strip(d: dict) -> dict:
    d.pop("_id", None)
    return d


def _norm_email(e: str) -> str:
    return e.strip().lower()


def _user_from_doc(doc: dict) -> User:
    doc = _strip(dict(doc))
    doc.pop("password_hash", None)
    doc.pop("apple_sub", None)
    doc.setdefault("providers", [])
    doc.setdefault("email_verified", False)
    return User(**doc)


def _random_token():
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


async def _create_session(user_id: str, days: int = 7) -> str:
    token = f"gu_{secrets.token_urlsafe(32)}"
    await db.user_sessions.insert_one({
        "session_token": token,
        "user_id": user_id,
        "expires_at": _now() + timedelta(days=days),
        "created_at": _now(),
    })
    return token


async def _send_email(to: str, subject: str, html: str):
    if not EMERGENT_EMAIL_KEY:
        logger = logging.getLogger(__name__)
        logger.warning(f"Email skipped (no key): to={to} subject={subject}")
        return
    payload = {
        "to": [to],
        "subject": subject,
        "html": html,
        "from_name": EMAIL_FROM_NAME,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as http:
            resp = await http.post(
                f"{EMAIL_BASE_URL}/api/v1/email/send",
                headers={"X-Email-Key": EMERGENT_EMAIL_KEY},
                json=payload,
            )
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logging.getLogger(__name__).error(f"Email failed {e.response.status_code}: {e.response.text}")
    except Exception as e:
        logging.getLogger(__name__).error(f"Email error: {e}")


def _verify_email_html(name: str, link: str) -> str:
    return f"""
    <div style="font-family: -apple-system, Segoe UI, sans-serif; max-width:520px; margin:0 auto; padding:24px; background:#FDFBF7;">
      <div style="background:#FFE600; border:2px solid #000; border-radius:24px; padding:20px; text-align:center;">
        <h1 style="margin:0; font-size:28px; color:#0A0A0A;">GroupUp 🎯</h1>
      </div>
      <h2 style="color:#0A0A0A;">Ciao {name}, benvenuto/a!</h2>
      <p style="color:#525252; font-size:15px; line-height:22px;">
        Verifica la tua email cliccando sul pulsante qui sotto per iniziare a creare e unirti ai gruppi.
      </p>
      <p style="text-align:center; margin:24px 0;">
        <a href="{link}" style="background:#FF4747; color:#fff; text-decoration:none; padding:14px 28px; border-radius:999px; font-weight:900; letter-spacing:0.5px; border:2px solid #000;">VERIFICA EMAIL</a>
      </p>
      <p style="color:#8A8A8A; font-size:13px;">
        Se il pulsante non funziona, copia questo link:<br>{link}
      </p>
      <p style="color:#8A8A8A; font-size:12px; margin-top:24px;">Il link scade tra 24 ore.</p>
    </div>
    """


def _reset_email_html(name: str, link: str) -> str:
    return f"""
    <div style="font-family: -apple-system, Segoe UI, sans-serif; max-width:520px; margin:0 auto; padding:24px; background:#FDFBF7;">
      <div style="background:#FF4747; border:2px solid #000; border-radius:24px; padding:20px; text-align:center;">
        <h1 style="margin:0; font-size:28px; color:#fff;">GroupUp 🔐</h1>
      </div>
      <h2 style="color:#0A0A0A;">Ciao {name}!</h2>
      <p style="color:#525252; font-size:15px; line-height:22px;">
        Hai richiesto di reimpostare la password. Clicca qui sotto per crearne una nuova.
      </p>
      <p style="text-align:center; margin:24px 0;">
        <a href="{link}" style="background:#FFE600; color:#0A0A0A; text-decoration:none; padding:14px 28px; border-radius:999px; font-weight:900; letter-spacing:0.5px; border:2px solid #000;">REIMPOSTA PASSWORD</a>
      </p>
      <p style="color:#8A8A8A; font-size:13px;">
        Se il pulsante non funziona, copia questo link:<br>{link}
      </p>
      <p style="color:#8A8A8A; font-size:12px; margin-top:24px;">Il link scade tra 30 minuti. Se non sei stato tu, ignora questa email.</p>
    </div>
    """


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
    return _user_from_doc(user_doc)


# ============================== Auth: Google (Emergent) ==============================

@api_router.post("/auth/session", response_model=AuthResponse)
async def auth_session(req: SessionRequest):
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
    email = _norm_email(data["email"])
    name = data.get("name") or email.split("@")[0]
    picture = data.get("picture")
    session_token = data["session_token"]

    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        updates = {"name": name}
        if not existing.get("picture"):
            updates["picture"] = picture
        providers = existing.get("providers", [])
        if "google" not in providers:
            providers.append("google")
            updates["providers"] = providers
        # Google auto-verifies email
        if not existing.get("email_verified"):
            updates["email_verified"] = True
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
            "email_verified": True,
            "providers": ["google"],
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
    return AuthResponse(session_token=session_token, user=_user_from_doc(user_doc))


# ============================== Auth: Email/Password ==============================

@api_router.post("/auth/signup")
async def signup(req: SignupRequest):
    email = _norm_email(req.email)
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing and existing.get("password_hash"):
        raise HTTPException(status_code=409, detail="Email già registrata")

    hashed = pwd_ctx.hash(req.password)
    if existing:
        # User exists via social (Google/Apple) -> attach password
        providers = existing.get("providers", [])
        if "password" not in providers:
            providers.append("password")
        await db.users.update_one(
            {"email": email},
            {"$set": {
                "password_hash": hashed,
                "providers": providers,
                "name": req.name.strip() or existing.get("name"),
            }},
        )
        user_id = existing["user_id"]
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id,
            "email": email,
            "name": req.name.strip(),
            "picture": None,
            "gender": None,
            "age": None,
            "profile_complete": False,
            "email_verified": False,
            "password_hash": hashed,
            "providers": ["password"],
            "created_at": _now(),
        })

    # Send verification email
    raw, digest = _random_token()
    await db.auth_tokens.insert_one({
        "user_id": user_id,
        "token_hash": digest,
        "kind": "verify_email",
        "expires_at": _now() + timedelta(hours=24),
        "used_at": None,
        "created_at": _now(),
    })
    link = f"{APP_PUBLIC_URL}/verify-email?token={raw}"
    await _send_email(
        to=email,
        subject="Verifica la tua email · GroupUp",
        html=_verify_email_html(req.name.strip() or "amico", link),
    )
    return {"message": "Registrazione completata! Controlla la tua email per verificare l'account."}


@api_router.post("/auth/verify-email", response_model=AuthResponse)
async def verify_email(req: TokenRequest):
    digest = hashlib.sha256(req.token.encode()).hexdigest()
    record = await db.auth_tokens.find_one({
        "token_hash": digest,
        "kind": "verify_email",
        "used_at": None,
    }, {"_id": 0, "token_hash": 0})
    if not record:
        raise HTTPException(status_code=400, detail="Link non valido o già usato")
    if _aware(record["expires_at"]) < _now():
        raise HTTPException(status_code=400, detail="Link scaduto")
    await db.users.update_one(
        {"user_id": record["user_id"]},
        {"$set": {"email_verified": True}},
    )
    await db.auth_tokens.update_one(
        {"token_hash": digest},
        {"$set": {"used_at": _now()}},
    )
    user_doc = await db.users.find_one({"user_id": record["user_id"]}, {"_id": 0})
    session_token = await _create_session(user_doc["user_id"])
    return AuthResponse(session_token=session_token, user=_user_from_doc(user_doc))


@api_router.post("/auth/login", response_model=AuthResponse)
async def login(req: LoginRequest):
    email = _norm_email(req.email)
    user_doc = await db.users.find_one({"email": email}, {"_id": 0})
    ok = pwd_ctx.verify(req.password, user_doc.get("password_hash") if user_doc else DUMMY_HASH)
    if not user_doc or not user_doc.get("password_hash") or not ok:
        raise HTTPException(status_code=401, detail="Email o password non validi")
    if not user_doc.get("email_verified", False):
        raise HTTPException(status_code=403, detail="Verifica prima la tua email")
    session_token = await _create_session(user_doc["user_id"])
    return AuthResponse(session_token=session_token, user=_user_from_doc(user_doc))


@api_router.post("/auth/request-password-reset")
async def request_password_reset(req: RequestReset):
    email = _norm_email(req.email)
    user_doc = await db.users.find_one({"email": email}, {"_id": 0})
    if user_doc and user_doc.get("password_hash"):
        await db.auth_tokens.update_many(
            {"user_id": user_doc["user_id"], "kind": "password_reset", "used_at": None},
            {"$set": {"used_at": _now()}},
        )
        raw, digest = _random_token()
        await db.auth_tokens.insert_one({
            "user_id": user_doc["user_id"],
            "token_hash": digest,
            "kind": "password_reset",
            "expires_at": _now() + timedelta(minutes=30),
            "used_at": None,
            "created_at": _now(),
        })
        link = f"{APP_PUBLIC_URL}/reset-password?token={raw}"
        await _send_email(
            to=email,
            subject="Reimposta la tua password · GroupUp",
            html=_reset_email_html(user_doc.get("name", "amico"), link),
        )
    return {"message": "Se l'email è registrata riceverai le istruzioni"}


@api_router.post("/auth/confirm-reset")
async def confirm_reset(req: ResetConfirm):
    digest = hashlib.sha256(req.token.encode()).hexdigest()
    record = await db.auth_tokens.find_one({
        "token_hash": digest,
        "kind": "password_reset",
        "used_at": None,
    }, {"_id": 0, "token_hash": 0})
    if not record or _aware(record["expires_at"]) < _now():
        raise HTTPException(status_code=400, detail="Token non valido o scaduto")
    hashed = pwd_ctx.hash(req.new_password)
    await db.users.update_one(
        {"user_id": record["user_id"]},
        {"$set": {"password_hash": hashed}},
    )
    await db.auth_tokens.update_one(
        {"token_hash": digest},
        {"$set": {"used_at": _now()}},
    )
    # Revoke all existing sessions
    await db.user_sessions.delete_many({"user_id": record["user_id"]})
    return {"message": "Password aggiornata"}


# ============================== Auth: Apple ==============================

@api_router.post("/auth/apple", response_model=AuthResponse)
async def auth_apple(req: AppleAuthRequest):
    # Fetch Apple's public keys and verify the identity token
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            keys_resp = await http.get("https://appleid.apple.com/auth/keys")
            keys_resp.raise_for_status()
            jwks = keys_resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Cannot fetch Apple keys: {e}")

    try:
        header = pyjwt.get_unverified_header(req.identity_token)
        kid = header["kid"]
        key_data = next(k for k in jwks["keys"] if k["kid"] == kid)
        public_key = pyjwt.algorithms.RSAAlgorithm.from_jwk(key_data)
        claims = pyjwt.decode(
            req.identity_token,
            public_key,
            algorithms=["RS256"],
            audience=APPLE_AUDIENCES if APPLE_AUDIENCES else None,
            issuer="https://appleid.apple.com",
            options={"require": ["sub", "exp"], "verify_aud": bool(APPLE_AUDIENCES)},
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid Apple token: {e}")

    apple_sub = claims["sub"]
    email = _norm_email(claims.get("email") or req.email or "")

    # Look up by apple_sub, then email
    user_doc = await db.users.find_one({"apple_sub": apple_sub}, {"_id": 0})
    if not user_doc and email:
        user_doc = await db.users.find_one({"email": email}, {"_id": 0})

    if user_doc:
        updates = {}
        providers = user_doc.get("providers", [])
        if "apple" not in providers:
            providers.append("apple")
            updates["providers"] = providers
        if not user_doc.get("apple_sub"):
            updates["apple_sub"] = apple_sub
        if not user_doc.get("email_verified"):
            updates["email_verified"] = True
        if updates:
            await db.users.update_one({"user_id": user_doc["user_id"]}, {"$set": updates})
            user_doc.update(updates)
        user_id = user_doc["user_id"]
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        name = (req.full_name or (email.split("@")[0] if email else "Utente Apple"))
        user_doc = {
            "user_id": user_id,
            "email": email or f"{apple_sub}@privaterelay.appleid.com",
            "name": name,
            "picture": None,
            "gender": None,
            "age": None,
            "profile_complete": False,
            "email_verified": True,
            "apple_sub": apple_sub,
            "providers": ["apple"],
            "created_at": _now(),
        }
        await db.users.insert_one(dict(user_doc))
        user_doc = _strip(user_doc)

    session_token = await _create_session(user_id)
    return AuthResponse(session_token=session_token, user=_user_from_doc(user_doc))


# ============================== Auth: common ==============================

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
    complete = bool(fresh.get("gender")) and fresh.get("age") is not None and bool(fresh.get("picture"))
    if fresh.get("profile_complete") != complete:
        await db.users.update_one(
            {"user_id": user.user_id}, {"$set": {"profile_complete": complete}}
        )
        fresh["profile_complete"] = complete
    return _user_from_doc(fresh)


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
        await db.users.create_index("apple_sub", unique=True, sparse=True)
        await db.user_sessions.create_index("session_token", unique=True)
        await db.user_sessions.create_index("user_id")
        await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)
        await db.auth_tokens.create_index("token_hash", unique=True)
        await db.auth_tokens.create_index("expires_at", expireAfterSeconds=0)
        await db.groups.create_index("group_id", unique=True)
        await db.groups.create_index("category")
        await db.messages.create_index("group_id")
    except Exception as e:
        logger.warning(f"index creation issue: {e}")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
