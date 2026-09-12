from fastapi import (
    FastAPI,
    APIRouter,
    HTTPException,
    Header,
    Depends,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import re
import math
import asyncio
import logging
import uuid
import base64
import binascii
import json
import time
import ipaddress
import hashlib
import secrets as py_secrets
from collections import defaultdict, deque
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse
import httpx
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import List, Optional, Literal, Tuple, Dict, Set, Any
from datetime import datetime, timezone, timedelta

try:
    import jwt as pyjwt  # type: ignore
except Exception:  # pragma: no cover
    pyjwt = None  # type: ignore

try:
    from pwdlib import PasswordHash  # type: ignore
    _pwd_hash = PasswordHash.recommended()
    _DUMMY_PWD_HASH = _pwd_hash.hash("__constant-dummy-pw__")
except Exception:  # pragma: no cover
    _pwd_hash = None
    _DUMMY_PWD_HASH = ""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

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
    user_id: str            # Custom app id (user_{uuid_hex[:12]})
    email: Optional[str] = None   # Verified via Google/Apple, or set at signup
    name: str = ""
    picture: Optional[str] = None
    gender: Optional[Literal["male", "female", "other"]] = None
    age: Optional[int] = None
    profile_complete: bool = False
    # Terms & liability acceptance tracking (see /api/auth/accept-terms).
    terms_version: Optional[str] = None
    terms_accepted_at: Optional[datetime] = None
    # Multi-provider auth (Iteration 19). `email_verified` is True for Google/
    # Apple accounts (IdP already verifies) and toggles True for password
    # accounts only after the emailed link is confirmed.
    email_verified: bool = True
    auth_providers: List[str] = Field(default_factory=list)
    created_at: datetime


class GoogleSessionExchange(BaseModel):
    session_id: str


class AcceptTermsIn(BaseModel):
    version: str


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    picture: Optional[str] = None
    gender: Optional[Literal["male", "female", "other"]] = None
    # Minimum registration age is 14 (per app policy). Allow None only when
    # the caller is NOT setting the age; the endpoint validates presence
    # separately for gated actions (create/join group).
    age: Optional[int] = Field(default=None, ge=14, le=120)


class PublicUser(BaseModel):
    user_id: str
    name: str
    picture: Optional[str] = None
    gender: Optional[Literal["male", "female", "other"]] = None
    age: Optional[int] = None
    created_at: datetime


class GroupCreate(BaseModel):
    title: str
    category: str
    category_label: str
    location: str
    city: str
    province: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    description: Optional[str] = ""
    date: str
    time: str
    min_participants: int = Field(ge=3, le=200)
    max_participants: int = Field(ge=3, le=200)
    min_age: int = Field(ge=14, le=120)
    max_age: int = Field(ge=14, le=120)
    # Optional gender filter for who can join the group.
    # - "male"   → only men
    # - "female" → only women
    # - "any"    → anyone (default, backward compatible)
    gender_filter: Literal["male", "female", "any"] = "any"


class Group(BaseModel):
    group_id: str
    title: str
    category: str
    category_label: str
    location: str
    city: Optional[str] = None
    province: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    description: str
    date: str
    time: str
    min_participants: int
    max_participants: int
    min_age: int
    max_age: int
    gender_filter: Literal["male", "female", "any"] = "any"
    owner_id: str
    owner_name: str
    owner_picture: Optional[str] = None
    participants: List[dict] = []
    created_at: datetime


class GroupPage(BaseModel):
    """Cursor-paginated group feed page. `next_cursor` is `null` when the
    caller has reached the end of the stream. Cursors are opaque strings —
    the client MUST NOT parse them."""

    items: List[Group]
    next_cursor: Optional[str] = None


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


# ============================== Reports ==============================
# User-generated reports against a group, another user's profile, or a
# specific chat message. Persisted in the `reports` collection for later
# review. When the same target accumulates too many reports we log a
# warning; automatic take-down is out-of-scope for this MVP.

REPORT_TARGET_TYPES = ("group", "user", "message")
REPORT_REASONS = (
    "illegal_content",
    "sexual_content",
    "harassment",
    "scam",
    "spam",
    "violence",
    "personal_info",
    "other",
)

# Threshold at which we log a warning about a heavily-reported target.
REPORT_ALERT_THRESHOLD = 3


class ReportCreate(BaseModel):
    """Payload for POST /api/reports."""

    target_type: Literal["group", "user", "message"]
    target_id: str = Field(min_length=1, max_length=128)
    reason: Literal[
        "illegal_content",
        "sexual_content",
        "harassment",
        "scam",
        "spam",
        "violence",
        "personal_info",
        "other",
    ]
    description: Optional[str] = Field(default="", max_length=500)


class Report(BaseModel):
    report_id: str
    target_type: str
    target_id: str
    reason: str
    description: str
    reporter_id: str
    reporter_name: str
    status: str  # "pending" | "reviewed" | "dismissed"
    created_at: datetime


# ============================== Helpers ==============================

def _now():
    return datetime.now(timezone.utc)


def _strip(d: dict) -> dict:
    d.pop("_id", None)
    return d


def _user_from_doc(doc: dict) -> User:
    doc = _strip(dict(doc))
    # `providers` was an unused Firebase-era field; drop if lingering.
    doc.pop("providers", None)
    doc.setdefault("email", None)
    doc.setdefault("name", "")
    doc.setdefault("picture", None)
    doc.setdefault("gender", None)
    doc.setdefault("age", None)
    doc.setdefault("profile_complete", False)
    doc.setdefault("terms_version", None)
    doc.setdefault("terms_accepted_at", None)
    # Multi-provider auth defaults for legacy Google-only rows.
    doc.setdefault("email_verified", True)
    doc.setdefault("auth_providers", ["google"] if doc.get("email") else [])
    # `password_hash`, `apple_sub` are internal — never exposed in the model.
    doc.pop("password_hash", None)
    doc.pop("apple_sub", None)
    return User(**doc)


# NOTE: user creation now happens only via Google Sign-In in
# `POST /api/auth/session`. The legacy device-UUID auto-create helper has
# been removed; there is no anonymous access path anymore.


# User IDs are now generated server-side as `user_{uuid_hex[:12]}` after the
# Google exchange, but we keep this permissive regex for validation of
# report target_ids and admin actions where the value comes from user input.
_USER_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{8,128}$")

_SESSION_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-\.]{16,512}$")

# In-memory guard so a session_id delivered twice by the OS (deep link + auth
# session result on Android) is exchanged only once. Small TTL keeps the set
# bounded — the underlying Emergent session_id is single-use anyway.
_EXCHANGED_SESSION_IDS: dict[str, float] = {}
_EXCHANGE_TTL_SECONDS = 300


def _sweep_exchanged_ids() -> None:
    now = datetime.now(timezone.utc).timestamp()
    stale = [k for k, t in _EXCHANGED_SESSION_IDS.items() if now - t > _EXCHANGE_TTL_SECONDS]
    for k in stale:
        _EXCHANGED_SESSION_IDS.pop(k, None)


async def _lookup_session_user(session_token: str) -> Optional[User]:
    """Given a Bearer session_token, load the corresponding user (or None
    when the session is missing or expired)."""
    sess = await db.user_sessions.find_one(
        {"session_token": session_token}, {"_id": 0}
    )
    if not sess:
        return None
    exp = sess.get("expires_at")
    if exp is not None:
        # Normalize naive datetimes coming from MongoDB before comparison.
        if isinstance(exp, datetime) and exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if isinstance(exp, datetime) and exp < datetime.now(timezone.utc):
            await db.user_sessions.delete_one({"session_token": session_token})
            return None
    doc = await db.users.find_one({"user_id": sess["user_id"]}, {"_id": 0})
    if not doc:
        return None
    return _user_from_doc(doc)


async def get_current_user(authorization: Optional[str] = Header(None)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing session token")
    token = authorization.split(" ", 1)[1].strip()
    if not _SESSION_TOKEN_RE.match(token):
        raise HTTPException(status_code=401, detail="Session token non valido")
    user = await _lookup_session_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Sessione scaduta o non valida")
    return user


async def get_current_user_optional(
    authorization: Optional[str] = Header(None),
) -> Optional[User]:
    """Like get_current_user, but returns None when the caller is anonymous
    or sends an invalid header. Used by endpoints that must remain
    accessible while still tailoring the response to the caller."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    if not _SESSION_TOKEN_RE.match(token):
        return None
    return await _lookup_session_user(token)


# ============================== Age policy ==============================
# Minimum age to use the app is 14. Adults are 18+, minors are 14-17.
# Groups must be strictly age-homogeneous: either fully-adult (min_age >= 18)
# or fully-minor (max_age <= 17). Mixed adult/minor groups are forbidden.

MIN_APP_AGE = 14
ADULT_MIN_AGE = 18

# Terms & liability disclaimer version — keep in sync with the frontend
# constant defined in /app/frontend/src/lib/terms.ts. Bumping this string
# forces every previously-accepting user to re-accept the new revision.
CURRENT_TERMS_VERSION = "2026-06-01"


def _has_accepted_current_terms(user: Optional[User]) -> bool:
    return bool(user and user.terms_version == CURRENT_TERMS_VERSION)


def _require_accepted_terms(user: User) -> None:
    if not _has_accepted_current_terms(user):
        raise HTTPException(
            status_code=403,
            detail=(
                "Devi accettare il regolamento aggiornato di Barrio prima di "
                "continuare."
            ),
        )



def _user_age_bucket(user: Optional[User]) -> Optional[str]:
    """Returns 'adult', 'minor' or None (age not set)."""
    if user is None or user.age is None:
        return None
    if user.age >= ADULT_MIN_AGE:
        return "adult"
    return "minor"


def _group_age_bucket(min_age: int, max_age: int) -> Optional[str]:
    """Returns 'adult' if the range is entirely adult (min>=18), 'minor' if
    entirely minor (max<=17), or None for a forbidden mixed range."""
    if min_age >= ADULT_MIN_AGE:
        return "adult"
    if max_age <= ADULT_MIN_AGE - 1:
        return "minor"
    return None



# ============================== Content moderation ==============================
#
# Strategy: normalize obfuscations (leetspeak, spacing, repetitions) then
# match against BLOCKED STEMS (short prefixes) using a word-boundary rule
# at the STEM start. This catches "drog3", "drog4", "drogaaa", "d r o g a"
# without false-positive on unrelated words that just contain the stem in
# the middle (e.g. "carmine" is not flagged for "armi").

_LEET_MAP = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
    "@": "a", "$": "s", "!": "i",
    "\u00e8": "e", "\u00e9": "e", "\u00e0": "a",
    "\u00ec": "i", "\u00f2": "o", "\u00f9": "u",
})

# Kept in sync with /app/frontend/src/lib/moderation.ts
_BLOCKED_STEMS: List[str] = [
    # Droga
    "drog", "drug", "cocain", "eroin", "cannab", "marij", "weed", "ganja",
    "hashish", "metanfet", "methamph", "ecstasy", "mdma", "lsd", "ketam",
    "spacci", "pusher", "stupefac",
    # Armi / violenza
    "arma", "armi", "pistol", "fucil", "kalash",
    "weapon", "guns", "rifle", "knife",
    "esplos", "bomb", "terror", "attentat",
    "uccider", "ammazz", "omicid", "hitman", "murder",
    "stupr", "rape",
    # Sesso illegale / esplicito
    "orgia", "orgie", "orgy", "pedofil", "pedoph", "minoren",
    "prostit", "escort", "puttana", "zoofil",
    "sesso", "porno",
    # Alcol
    "alcol", "alcool", "alcohol", "ubriac",
    # Odio / auto-lesionismo
    "nazism", "nazist", "razzism", "razzist",
    "suicid", "autolesion",
]

_REPEAT_RE = re.compile(r"(.)\1{2,}")
_NON_ALPHA_RE = re.compile(r"[^a-z\s]")
_WS_RE = re.compile(r"\s+")
_SINGLE_RUN_RE = re.compile(r"(?:^|\s)((?:[a-z]\s+){2,}[a-z])(?=\s|$)")
# Pre-compile one regex that matches any of the stems at a word boundary.
_STEMS_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(s) for s in _BLOCKED_STEMS) + r")",
    re.IGNORECASE,
)


def _normalize_text(text: str) -> str:
    s = text.lower().translate(_LEET_MAP)
    s = _REPEAT_RE.sub(r"\1\1", s)
    s = _NON_ALPHA_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()

    # Glue runs of 2+ single-letter tokens: "d r o g a" -> "droga".
    # Loop until stable; the string strictly shrinks so this terminates.
    prev = None
    while prev != s:
        prev = s
        s = _SINGLE_RUN_RE.sub(lambda m: " " + m.group().replace(" ", "") + " ", s)
        s = _WS_RE.sub(" ", s).strip()
    return s


def _first_forbidden(text: str) -> Optional[str]:
    if not text:
        return None
    m = _STEMS_RE.search(_normalize_text(text))
    return m.group(0) if m else None


def _reject_if_forbidden(*fields: str) -> None:
    for f in fields:
        if _first_forbidden(f):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Contenuto non consentito: sono vietati riferimenti a "
                    "droga, armi, violenza, sesso esplicito, alcol o "
                    "contenuti illegali."
                ),
            )


# ============================== Geocoding & distance ==============================
#
# Convert city/street to lat/lon via OpenStreetMap Nominatim (no API key
# required, must send a proper User-Agent and be polite: 1 req/s). We cache
# in-memory to avoid re-hitting the API for the same address.

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_UA = "Barrio/1.0 (activity-groups mobile app)"
_geocode_cache: dict = {}
_geocode_lock = asyncio.Lock()
_last_geocode_at: float = 0.0
_GEOCODE_MIN_INTERVAL_S = 1.1  # Nominatim usage policy


async def _geocode(city: str, street: str = "") -> Optional[Tuple[float, float]]:
    """Geocode city (+optional street) -> (lat, lon). Returns None on failure."""
    city = (city or "").strip()
    street = (street or "").strip()
    if not city:
        return None
    key = f"{street.lower()}|{city.lower()}"
    if key in _geocode_cache:
        return _geocode_cache[key]

    params = {"format": "json", "limit": "1", "addressdetails": "0"}
    if street:
        params["street"] = street
    params["city"] = city
    params["countrycodes"] = "it"  # bias to Italy; still works for foreign fallback below

    async with _geocode_lock:
        # simple polite throttle (Nominatim: 1 req/sec)
        global _last_geocode_at
        loop = asyncio.get_event_loop()
        wait = _GEOCODE_MIN_INTERVAL_S - (loop.time() - _last_geocode_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_geocode_at = loop.time()

        try:
            async with httpx.AsyncClient(timeout=8.0) as c:
                r = await c.get(
                    _NOMINATIM_URL,
                    params=params,
                    headers={
                        "User-Agent": _NOMINATIM_UA,
                        "Accept-Language": "it,en",
                    },
                )
            if r.status_code == 200 and r.json():
                d = r.json()[0]
                res = (float(d["lat"]), float(d["lon"]))
                _geocode_cache[key] = res
                return res
            # Fallback: retry without country bias if nothing found
            if r.status_code == 200:
                params.pop("countrycodes", None)
                async with httpx.AsyncClient(timeout=8.0) as c:
                    r2 = await c.get(
                        _NOMINATIM_URL,
                        params=params,
                        headers={
                            "User-Agent": _NOMINATIM_UA,
                            "Accept-Language": "it,en",
                        },
                    )
                if r2.status_code == 200 and r2.json():
                    d = r2.json()[0]
                    res = (float(d["lat"]), float(d["lon"]))
                    _geocode_cache[key] = res
                    return res
        except Exception as e:
            try:
                logger.warning(f"geocode error for '{key}': {e}")
            except Exception:
                pass
        return None


_PHOTON_URL = "https://photon.komoot.io/api"


async def _search_cities(q: str, limit: int = 6) -> List[dict]:
    """Autocomplete Italian cities/towns/villages by name prefix.

    Uses the Photon (Komoot) OSM autocomplete service — it supports true
    prefix matching (unlike Nominatim `search`). We only keep results whose
    country code is IT and whose OSM class/value is a human settlement.
    Falls back to Nominatim `search` if Photon returns nothing.
    """
    q = (q or "").strip()
    if len(q) < 2:
        return []
    ck = f"__cities__|{q.lower()}|{limit}"
    if ck in _geocode_cache:
        return _geocode_cache[ck]  # type: ignore

    params_photon = {
        "q": q,
        "limit": str(min(max(limit * 3, 6), 20)),  # over-fetch, we'll filter
        # accept several settlement kinds
        "osm_tag": ["place:city", "place:town", "place:village", "place:hamlet"],
        # restrict to Italy
        "bbox": "6.6273,35.4929,18.8438,47.0921",
    }

    async with _geocode_lock:
        global _last_geocode_at
        loop = asyncio.get_event_loop()
        wait = _GEOCODE_MIN_INTERVAL_S - (loop.time() - _last_geocode_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_geocode_at = loop.time()

        raw_features: list = []
        try:
            async with httpx.AsyncClient(timeout=8.0) as c:
                r = await c.get(
                    _PHOTON_URL,
                    params=params_photon,
                    headers={"User-Agent": _NOMINATIM_UA},
                )
            if r.status_code == 200:
                raw_features = (r.json() or {}).get("features", []) or []
        except Exception as e:
            try:
                logger.warning(f"photon suggest error for '{q}': {e}")
            except Exception:
                pass

    out: List[dict] = []
    seen: set = set()
    for feat in raw_features:
        p = (feat or {}).get("properties") or {}
        geom = (feat or {}).get("geometry") or {}
        if p.get("countrycode") not in ("IT", None):
            # Photon sometimes omits countrycode for admin regions; only skip
            # when we know it's non-IT.
            if p.get("countrycode"):
                continue
        if p.get("osm_key") != "place":
            continue
        if p.get("osm_value") not in ("city", "town", "village", "hamlet"):
            continue
        name = (p.get("name") or "").strip()
        if not name:
            continue
        province = (p.get("county") or p.get("state_district") or "").strip()
        region = (p.get("state") or "").strip()
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        try:
            lon = float(coords[0]); lat = float(coords[1])
        except Exception:
            continue
        key = (name.lower(), province.lower())
        if key in seen:
            continue
        seen.add(key)
        display = name + (f" ({province})" if province else "")
        out.append({
            "name": name,
            "province": province,
            "region": region,
            "lat": lat,
            "lon": lon,
            "display": display,
        })
        if len(out) >= limit:
            break

    _geocode_cache[ck] = out  # type: ignore
    return out


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    x = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(x))


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
    # Only look at groups NOT already marked as expired — avoids reprocessing.
    cursor = db.groups.find(
        {"status": {"$ne": "expired"}},
        {"_id": 0, "group_id": 1, "date": 1, "time": 1},
    )
    async for g in cursor:
        dt = _event_datetime(g.get("date", ""), g.get("time", ""))
        if dt is not None and dt < threshold:
            expired.append(g["group_id"])
    if expired:
        # SOFT-delete: mark the groups as expired instead of erasing them.
        # This preserves historical data for moderation/analytics and is
        # non-destructive on deploy/restart. All feed/list endpoints exclude
        # `status: "expired"` documents.
        now = datetime.now(_APP_TZ)
        await db.groups.update_many(
            {"group_id": {"$in": expired}},
            {"$set": {"status": "expired", "expired_at": now}},
        )
        try:
            logger.info(f"[cleanup] soft-expired {len(expired)} group(s)")
        except Exception:
            pass
    return expired


# ============================== Auth ==============================

EMERGENT_AUTH_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
SESSION_LIFETIME = timedelta(days=7)


@api_router.post("/auth/session", response_model=dict)
async def exchange_google_session(payload: GoogleSessionExchange):
    """Exchange the `session_id` returned by the Emergent Google Auth flow
    for a durable app session token. Also lazily creates/updates the user
    record based on the verified Google identity.

    Returns: `{ session_token, user }` — the client stores the token in
    SecureStore and sends it as `Authorization: Bearer <session_token>` on
    every subsequent API call.
    """
    session_id = (payload.session_id or "").strip()
    if not session_id or len(session_id) < 8:
        raise HTTPException(status_code=400, detail="session_id mancante")

    # Replay guard (session_id is single-use upstream, but the OS may
    # deliver the deep link twice on Android).
    _sweep_exchanged_ids()
    if session_id in _EXCHANGED_SESSION_IDS:
        raise HTTPException(status_code=409, detail="session_id già utilizzato")
    _EXCHANGED_SESSION_IDS[session_id] = datetime.now(timezone.utc).timestamp()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                EMERGENT_AUTH_URL,
                headers={"X-Session-ID": session_id},
            )
    except httpx.HTTPError as exc:
        logger.exception("Emergent auth call failed: %s", exc)
        raise HTTPException(status_code=502, detail="Auth provider non raggiungibile")

    if resp.status_code != 200:
        logger.warning("Emergent auth rejected session_id: %s", resp.text[:200])
        raise HTTPException(status_code=401, detail="Google session non valida o scaduta")

    data = resp.json() or {}
    email = (data.get("email") or "").strip().lower()
    google_name = (data.get("name") or "").strip()
    google_picture = data.get("picture") or None
    session_token = (data.get("session_token") or "").strip()
    if not email or not session_token:
        raise HTTPException(status_code=502, detail="Risposta auth incompleta")
    if not _SESSION_TOKEN_RE.match(session_token):
        raise HTTPException(status_code=502, detail="Formato session_token non valido")

    now = _now()
    # Upsert user keyed by email so a returning user re-uses their user_id
    # (and therefore all their groups/messages/reports).
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        upd: dict = {}
        # Auto-populate name/picture only if empty, to respect user edits.
        if not existing.get("name") and google_name:
            upd["name"] = google_name[:40]
        if not existing.get("picture") and google_picture:
            upd["picture"] = google_picture
        # Ensure google is in the provider list so linked accounts stay consistent
        providers = list(existing.get("auth_providers") or [])
        if "google" not in providers:
            providers.append("google")
            upd["auth_providers"] = providers
        if not existing.get("email_verified"):
            upd["email_verified"] = True
        if upd:
            await db.users.update_one({"user_id": user_id}, {"$set": upd})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one(
            {
                "user_id": user_id,
                "email": email,
                "name": google_name[:40] if google_name else "",
                "picture": google_picture,
                "gender": None,
                "age": None,
                "profile_complete": False,
                "terms_version": None,
                "terms_accepted_at": None,
                "created_at": now,
                "password_hash": None,
                "email_verified": True,
                "auth_providers": ["google"],
            }
        )

    # Store the session (7-day sliding window matches Emergent's default).
    await db.user_sessions.insert_one(
        {
            "session_token": session_token,
            "user_id": user_id,
            "created_at": now,
            "expires_at": now + SESSION_LIFETIME,
        }
    )
    fresh = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    return {"session_token": session_token, "user": _user_from_doc(fresh).model_dump(mode="json")}


@api_router.post("/auth/logout")
async def auth_logout(authorization: Optional[str] = Header(None)):
    """Revoke the current session server-side. Idempotent: returns ok even
    when the token is unknown (already logged out)."""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if _SESSION_TOKEN_RE.match(token):
            await db.user_sessions.delete_one({"session_token": token})
    return {"ok": True}


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


# ==================== Email/Password + Apple Auth (Iteration 19) ====================
#
# Providers unified into the same `users` + `user_sessions` collections used by
# the Emergent Google Auth flow above. The `auth_providers` array tracks which
# provider(s) a given user account has linked; new fields:
#
#   password_hash      Argon2id hash (via pwdlib). Nullable — Google/Apple-only
#                      users have no password.
#   email_verified     True once the user has confirmed the emailed link/code.
#                      Google/Apple flows implicitly set this True because the
#                      IdP already verifies the address; email-password signups
#                      start False and flip True on POST /api/auth/verify-email.
#   auth_providers[]   ["google"], ["password"], ["apple"], or any combination
#                      after account linking.
#   apple_sub          Apple `sub` claim (only when a user has linked Apple).
#
# Reset/verify tokens live in a separate `auth_tokens` collection, storing only
# SHA-256 of the raw token. Tokens are single-use (`used_at`) and TTL-expired.
# Never log the raw token; never return it in an API response.

_JWT_SECRET = os.environ.get("JWT_SECRET_KEY", "")
_JWT_ALG = "HS256"
_RESET_MINUTES = int(os.environ.get("RESET_TOKEN_MINUTES", "30"))
_VERIFY_HOURS = int(os.environ.get("VERIFY_TOKEN_HOURS", "24"))
_PUBLIC_URL = os.environ.get("APP_PUBLIC_URL", "").rstrip("/")
_APPLE_AUDIENCES = [
    a.strip()
    for a in (os.environ.get("APPLE_AUDIENCES") or "").split(",")
    if a.strip()
]

# Password strength: min 8 chars, at least 1 letter and 1 digit.
_PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,128}$")


def _pw_hash(raw: str) -> str:
    if _pwd_hash is None:
        raise HTTPException(status_code=500, detail="Password auth non disponibile")
    return _pwd_hash.hash(raw)


def _pw_verify(raw: str, hashed: Optional[str]) -> bool:
    if _pwd_hash is None:
        return False
    # Always execute Argon2 work so unknown-email requests take the same time
    # as wrong-password requests (mitigates timing enumeration).
    target = hashed if hashed else _DUMMY_PWD_HASH
    try:
        return _pwd_hash.verify(raw, target) and bool(hashed)
    except Exception:
        return False


def _sha256_hex(v: str) -> str:
    return hashlib.sha256(v.encode("utf-8")).hexdigest()


def _issue_session_token() -> str:
    # Long, URL-safe token. Same shape as Emergent's tokens (matches
    # `_SESSION_TOKEN_RE`) so the existing bearer middleware validates it.
    return py_secrets.token_urlsafe(48)


async def _create_session_for(user_id: str) -> str:
    token = _issue_session_token()
    now = _now()
    await db.user_sessions.insert_one(
        {
            "session_token": token,
            "user_id": user_id,
            "created_at": now,
            "expires_at": now + SESSION_LIFETIME,
        }
    )
    return token


# ---- Simple in-memory rate limiter (per process). Good enough for MVP; swap
# to Redis when we scale horizontally.
_RL_BUCKETS: Dict[str, deque] = defaultdict(deque)


def _rate_limit(key: str, limit: int = 10, window_seconds: int = 900) -> bool:
    """Sliding-window limiter. Returns True when the request is allowed."""
    now = time.monotonic()
    q = _RL_BUCKETS[key]
    while q and q[0] <= now - window_seconds:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


# ============================== Email (Emergent Resend) ==============================

EMAIL_BASE_URL = "https://integrations.emergentagent.com"
_EMAIL_KEY = os.environ.get("EMERGENT_EMAIL_KEY", "")
_EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "Barrio")
_EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO")

_SHORTENERS = (
    "bit.ly",
    "tinyurl.com",
    "t.co",
    "is.gd",
    "cutt.ly",
    "goo.gl",
    "rebrand.ly",
)
_CRED_ASK = (
    "reply with your password",
    "reply with the code",
    "send your password",
    "cvv",
    "send us your password",
    "enter your password below",
    "confirm your card number",
    "your full card number",
    "seed phrase",
    "recovery phrase",
    "verify your card",
    "social security number",
    "confirm your bank details",
)
_HOSTISH_RE = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def _email_host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _email_same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: Set[str] = set()
        self.urls: List[str] = []
        self.anchors: List[Tuple[str, str]] = []
        self._href: Optional[str] = None
        self._text: List[str] = []

    def handle_starttag(self, tag: str, attrs):  # type: ignore[override]
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href = None
            self._text = []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan()
    scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Non-https link/asset: {url!r} (G3)")
        parsed = urlparse(low)
        host = parsed.hostname or ""
        if not _email_host_ok(host) or parsed.username is not None:
            raise ValueError(f"Unsafe URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH_RE.finditer(text):
            if not _email_same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text host mismatch: {m.group(1)!r} vs {real!r} (G3)")


async def _send_email(*, to: str, subject: str, html: str, reply_to: Optional[str] = None) -> Optional[str]:
    """Send transactional email via Emergent Resend. Never call from a route
    that receives arbitrary html/subject/recipient from user input (see G4)."""
    _assert_safe_email(subject, html)
    if not _EMAIL_KEY:
        logger.warning("EMERGENT_EMAIL_KEY not configured — skipping send")
        return None
    payload: Dict[str, Any] = {
        "to": [to],
        "subject": subject,
        "html": html,
        "from_name": _EMAIL_FROM_NAME,
    }
    r = reply_to or _EMAIL_REPLY_TO
    if r:
        payload["contact_email"] = r
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{EMAIL_BASE_URL}/api/v1/email/send",
                headers={"X-Email-Key": _EMAIL_KEY},
                json=payload,
            )
        resp.raise_for_status()
        return (resp.json() or {}).get("id")
    except httpx.HTTPStatusError as e:
        logger.error("Email send failed: %s %s", e.response.status_code, e.response.text[:200])
        return None
    except Exception as e:
        logger.error("Email send error: %s", e)
        return None


# ---- Templates. Server-side, never mixed with request input except via escape().

def _reset_email_html(user_name: str, reset_link: str) -> str:
    safe_name = escape(user_name or "there")
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        '<tr><td style="padding:24px;font-family:Arial,sans-serif;color:#111">'
        f'<h2 style="margin:0 0 12px 0">Reimposta la tua password</h2>'
        f'<p>Ciao {safe_name},</p>'
        f'<p>Abbiamo ricevuto una richiesta di reimpostazione della password '
        f'per il tuo account Barrio. Il link è valido per {_RESET_MINUTES} minuti '
        f'e può essere usato una sola volta.</p>'
        f'<p style="margin:24px 0"><a href="{escape(reset_link)}" '
        f'style="background:#FF4747;color:#fff;padding:12px 20px;'
        f'text-decoration:none;border-radius:8px;font-weight:bold">'
        f'Reimposta password</a></p>'
        f'<p style="font-size:14px;color:#444">Se non hai richiesto tu il reset, '
        f'puoi ignorare questa email — la tua password resta invariata.</p>'
        f'<hr style="border:none;border-top:1px solid #eee;margin:24px 0">'
        f'<p style="font-size:12px;color:#888">Inviato da Barrio. '
        f'Non chiediamo mai la tua password o codici via email.</p>'
        '</td></tr></table>'
    )


def _verify_email_html(user_name: str, verify_link: str) -> str:
    safe_name = escape(user_name or "there")
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        '<tr><td style="padding:24px;font-family:Arial,sans-serif;color:#111">'
        f'<h2 style="margin:0 0 12px 0">Benvenuto su Barrio</h2>'
        f'<p>Ciao {safe_name},</p>'
        f'<p>Grazie per esserti registrato! Per completare la registrazione, '
        f'conferma il tuo indirizzo email cliccando sul link qui sotto '
        f'(valido {_VERIFY_HOURS} ore).</p>'
        f'<p style="margin:24px 0"><a href="{escape(verify_link)}" '
        f'style="background:#FF4747;color:#fff;padding:12px 20px;'
        f'text-decoration:none;border-radius:8px;font-weight:bold">'
        f'Verifica email</a></p>'
        f'<hr style="border:none;border-top:1px solid #eee;margin:24px 0">'
        f'<p style="font-size:12px;color:#888">Inviato da Barrio. '
        f'Se non hai creato tu questo account, ignora questa email.</p>'
        '</td></tr></table>'
    )


# ============================== Pydantic models ==============================

class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: Optional[str] = Field(default=None, max_length=40)

    @field_validator("password")
    @classmethod
    def _strong(cls, v: str) -> str:
        if not _PASSWORD_RE.fullmatch(v):
            raise ValueError("Password: minimo 8 caratteri con almeno una lettera e un numero")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RequestResetIn(BaseModel):
    email: EmailStr


class ConfirmResetIn(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _strong(cls, v: str) -> str:
        if not _PASSWORD_RE.fullmatch(v):
            raise ValueError("Password: minimo 8 caratteri con almeno una lettera e un numero")
        return v


class VerifyEmailIn(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class AppleSignInIn(BaseModel):
    identity_token: str = Field(min_length=20, max_length=8192)
    # Provided only on the FIRST sign-in by Apple. Later sign-ins send these as null.
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(default=None, max_length=80)


# ============================== Auth tokens helpers ==============================

async def _issue_auth_token(user_id: str, kind: str, ttl: timedelta) -> str:
    raw = py_secrets.token_urlsafe(48)
    await db.auth_tokens.insert_one(
        {
            "user_id": user_id,
            "kind": kind,
            "token_hash": _sha256_hex(raw),
            "created_at": _now(),
            "expires_at": _now() + ttl,
            "used_at": None,
        }
    )
    return raw


async def _consume_auth_token(kind: str, raw: str) -> Optional[str]:
    """Atomically mark a token used and return its user_id, or None if the
    token is unknown/expired/already used."""
    record = await db.auth_tokens.find_one_and_update(
        {
            "kind": kind,
            "token_hash": _sha256_hex(raw),
            "used_at": None,
            "expires_at": {"$gt": _now()},
        },
        {"$set": {"used_at": _now()}},
        return_document=True,
    )
    if not record:
        return None
    return record.get("user_id")


# ============================== Endpoints ==============================

@api_router.post("/auth/register", response_model=dict, status_code=201)
async def auth_register(payload: RegisterIn, request: Request):
    ip = (request.client.host if request.client else "unknown") or "unknown"
    if not _rate_limit(f"reg:ip:{ip}", limit=10, window_seconds=3600):
        raise HTTPException(status_code=429, detail="Troppi tentativi, riprova tra un'ora")
    email = payload.email.strip().lower()
    name = (payload.name or "").strip()[:40]

    existing = await db.users.find_one({"email": email}, {"_id": 0})
    now = _now()
    if existing:
        # If the user has already linked a password, we can't overwrite it —
        # ask them to log in instead.
        if existing.get("password_hash"):
            raise HTTPException(status_code=409, detail="Account già registrato: accedi con email e password")
        # Google/Apple-only account: attach a password to it so the two
        # providers coexist. Requires the caller to complete verification via
        # the emailed link before we mark auth_providers += ["password"].
        user_id = existing["user_id"]
        await db.users.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "password_hash": _pw_hash(payload.password),
                    "name": existing.get("name") or name,
                },
            },
        )
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one(
            {
                "user_id": user_id,
                "email": email,
                "name": name,
                "picture": None,
                "gender": None,
                "age": None,
                "profile_complete": False,
                "terms_version": None,
                "terms_accepted_at": None,
                "created_at": now,
                "password_hash": _pw_hash(payload.password),
                "email_verified": False,
                "auth_providers": ["password"],
            }
        )

    # Send verification email (fire-and-forget so signup latency stays low).
    verify_token = await _issue_auth_token(user_id, "verify_email", timedelta(hours=_VERIFY_HOURS))
    if _PUBLIC_URL:
        verify_link = f"{_PUBLIC_URL}/verify-email?token={verify_token}"
        try:
            asyncio.create_task(
                _send_email(
                    to=email,
                    subject="Verifica il tuo indirizzo email",
                    html=_verify_email_html(name, verify_link),
                )
            )
        except Exception as exc:
            logger.warning("verify email dispatch failed: %s", exc)

    # Immediately issue a session so signup lands the user in the app; they
    # get a nag banner until email_verified flips True.
    token = await _create_session_for(user_id)
    fresh = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    return {
        "session_token": token,
        "user": _user_from_doc(fresh).model_dump(mode="json"),
        "email_verification_sent": True,
    }


@api_router.post("/auth/login", response_model=dict)
async def auth_login(payload: LoginIn, request: Request):
    ip = (request.client.host if request.client else "unknown") or "unknown"
    email = payload.email.strip().lower()
    if not _rate_limit(f"login:ip:{ip}", limit=15, window_seconds=900):
        raise HTTPException(status_code=429, detail="Troppi tentativi, riprova tra 15 minuti")
    if not _rate_limit(f"login:em:{email}", limit=10, window_seconds=900):
        raise HTTPException(status_code=429, detail="Troppi tentativi, riprova tra 15 minuti")

    user = await db.users.find_one({"email": email}, {"_id": 0})
    hashed = user.get("password_hash") if user else None
    ok = _pw_verify(payload.password, hashed)
    if not user or not ok:
        # Same generic message + timing (dummy hash) to avoid enumeration.
        raise HTTPException(status_code=401, detail="Email o password non corretti")

    token = await _create_session_for(user["user_id"])
    return {
        "session_token": token,
        "user": _user_from_doc(user).model_dump(mode="json"),
    }


@api_router.post("/auth/password/request-reset", response_model=dict)
async def auth_request_reset(payload: RequestResetIn, request: Request):
    ip = (request.client.host if request.client else "unknown") or "unknown"
    if not _rate_limit(f"reset:ip:{ip}", limit=10, window_seconds=3600):
        # Silent — we don't want to reveal that the endpoint is hot.
        return {"message": "Se l'account esiste, riceverai un'email con le istruzioni per il reset."}
    email = payload.email.strip().lower()
    user = await db.users.find_one(
        {"email": email, "password_hash": {"$ne": None}}, {"_id": 0}
    )
    if user:
        raw = await _issue_auth_token(user["user_id"], "reset_password", timedelta(minutes=_RESET_MINUTES))
        if _PUBLIC_URL:
            reset_link = f"{_PUBLIC_URL}/reset-password?token={raw}"
            try:
                asyncio.create_task(
                    _send_email(
                        to=email,
                        subject="Reimposta la tua password Barrio",
                        html=_reset_email_html(user.get("name") or "", reset_link),
                    )
                )
            except Exception as exc:
                logger.warning("reset email dispatch failed: %s", exc)
    # Deliberately identical response whether or not the email exists.
    return {"message": "Se l'account esiste, riceverai un'email con le istruzioni per il reset."}


@api_router.post("/auth/password/confirm-reset", response_model=dict)
async def auth_confirm_reset(payload: ConfirmResetIn):
    user_id = await _consume_auth_token("reset_password", payload.token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Token non valido o scaduto")
    new_hash = _pw_hash(payload.new_password)
    upd: Dict[str, Any] = {"password_hash": new_hash}
    # First time a Google/Apple-only account sets a password → mark provider.
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0}) or {}
    providers = list(user.get("auth_providers") or [])
    if "password" not in providers:
        providers.append("password")
        upd["auth_providers"] = providers
    await db.users.update_one({"user_id": user_id}, {"$set": upd})
    # Invalidate all existing sessions after a password change.
    await db.user_sessions.delete_many({"user_id": user_id})
    return {"ok": True}


@api_router.post("/auth/verify-email", response_model=dict)
async def auth_verify_email(payload: VerifyEmailIn):
    user_id = await _consume_auth_token("verify_email", payload.token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Token non valido o scaduto")
    await db.users.update_one({"user_id": user_id}, {"$set": {"email_verified": True}})
    return {"ok": True}


# ============================== Apple Sign-In ==============================

_APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
_apple_jwks_cache: Dict[str, Any] = {"fetched_at": 0.0, "keys": {}}


async def _apple_jwks_key_for(kid: str) -> Optional[Dict[str, Any]]:
    """Return the JWK matching `kid`, refreshing the cache at most every 60s."""
    now = time.monotonic()
    if now - _apple_jwks_cache["fetched_at"] > 60 and _apple_jwks_cache.get("keys", {}).get(kid) is None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(_APPLE_JWKS_URL)
            resp.raise_for_status()
            keys = (resp.json() or {}).get("keys") or []
            _apple_jwks_cache["keys"] = {k.get("kid"): k for k in keys if k.get("kid")}
            _apple_jwks_cache["fetched_at"] = now
        except Exception as exc:
            logger.warning("Apple JWKS fetch failed: %s", exc)
    return _apple_jwks_cache["keys"].get(kid)


async def _verify_apple_identity_token(identity_token: str) -> Dict[str, Any]:
    if pyjwt is None:
        raise HTTPException(status_code=500, detail="Apple auth non configurato")
    if not _APPLE_AUDIENCES:
        raise HTTPException(status_code=500, detail="APPLE_AUDIENCES non impostato")
    try:
        unverified = pyjwt.get_unverified_header(identity_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Identity token Apple malformato")
    kid = unverified.get("kid")
    if not kid:
        raise HTTPException(status_code=401, detail="Identity token Apple senza kid")
    jwk = await _apple_jwks_key_for(kid)
    if not jwk:
        raise HTTPException(status_code=401, detail="Chiave Apple non trovata")
    try:
        # Try each configured audience — build usually uses the bundle id,
        # Expo Go uses host.exp.Exponent.
        public_key = pyjwt.algorithms.RSAAlgorithm.from_jwk(jwk)
        last_err: Optional[Exception] = None
        for aud in _APPLE_AUDIENCES:
            try:
                claims = pyjwt.decode(
                    identity_token,
                    public_key,
                    algorithms=["RS256"],
                    audience=aud,
                    issuer="https://appleid.apple.com",
                )
                return claims
            except Exception as e:  # pragma: no cover
                last_err = e
        raise last_err or ValueError("audience mismatch")
    except Exception as exc:
        logger.warning("Apple token verify failed: %s", exc)
        raise HTTPException(status_code=401, detail="Identity token Apple non valido")


@api_router.post("/auth/apple", response_model=dict)
async def auth_apple(payload: AppleSignInIn):
    claims = await _verify_apple_identity_token(payload.identity_token)
    apple_sub = str(claims.get("sub") or "").strip()
    if not apple_sub:
        raise HTTPException(status_code=401, detail="Sub Apple mancante")
    # Apple returns `email` on the first sign-in only; on subsequent flows we
    # rely on the value we persisted the first time.
    token_email = (claims.get("email") or "").strip().lower() or None
    first_time_email = (payload.email or "").strip().lower() or None
    email = token_email or first_time_email
    provided_name = (payload.full_name or "").strip()[:40]

    now = _now()
    # Prefer matching by apple_sub (stable). Fall back to email so a user who
    # signed up via email/Google earlier can link Apple to the same account.
    user = await db.users.find_one({"apple_sub": apple_sub}, {"_id": 0})
    if not user and email:
        user = await db.users.find_one({"email": email}, {"_id": 0})

    if user:
        user_id = user["user_id"]
        upd: Dict[str, Any] = {}
        if not user.get("apple_sub"):
            upd["apple_sub"] = apple_sub
        # Apple has verified this email.
        if email and (user.get("email") or "") == "":
            upd["email"] = email
        if email and not user.get("email_verified"):
            upd["email_verified"] = True
        providers = list(user.get("auth_providers") or [])
        if "apple" not in providers:
            providers.append("apple")
            upd["auth_providers"] = providers
        if not user.get("name") and provided_name:
            upd["name"] = provided_name
        if upd:
            await db.users.update_one({"user_id": user_id}, {"$set": upd})
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one(
            {
                "user_id": user_id,
                "email": email,
                "apple_sub": apple_sub,
                "name": provided_name or "",
                "picture": None,
                "gender": None,
                "age": None,
                "profile_complete": False,
                "terms_version": None,
                "terms_accepted_at": None,
                "created_at": now,
                "password_hash": None,
                "email_verified": True,
                "auth_providers": ["apple"],
            }
        )

    token = await _create_session_for(user_id)
    fresh = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    return {
        "session_token": token,
        "user": _user_from_doc(fresh).model_dump(mode="json"),
    }


async def _delete_user_cascade(user_id: str) -> dict:
    """Wipe every trace of a user: their profile, groups they own (with
    chats), their messages everywhere, and their participation in other
    groups. Reports SENT by the user are also removed. Any pending report
    ABOUT the user is marked reviewed. Returns a small summary dict.
    """
    # Groups owned by user + their chats
    owned = await db.groups.find(
        {"owner_id": user_id}, {"_id": 0, "group_id": 1}
    ).to_list(length=1000)
    owned_ids = [g["group_id"] for g in owned]
    if owned_ids:
        await db.groups.delete_many({"group_id": {"$in": owned_ids}})
        await db.messages.delete_many({"group_id": {"$in": owned_ids}})
    # Remove user from any remaining participant list
    await db.groups.update_many(
        {"participants.user_id": user_id},
        {"$pull": {"participants": {"user_id": user_id}}},
    )
    # Delete the user's messages everywhere
    await db.messages.delete_many({"user_id": user_id})
    # Delete reports authored by the user (privacy)
    await db.reports.delete_many({"reporter_id": user_id})
    # Mark pending reports ABOUT this user as reviewed
    await db.reports.update_many(
        {"target_type": "user", "target_id": user_id, "status": "pending"},
        {"$set": {"status": "reviewed"}},
    )
    # Finally, drop the user record itself
    await db.users.delete_one({"user_id": user_id})
    # Revoke any active session
    await db.user_sessions.delete_many({"user_id": user_id})
    return {"ok": True, "deleted_user": user_id, "deleted_groups": owned_ids}


@api_router.delete("/auth/me")
async def delete_my_account(user: User = Depends(get_current_user)):
    """Self-service account deletion. Removes ALL data belonging to the
    caller from the database. Irreversible."""
    return await _delete_user_cascade(user.user_id)


@api_router.post("/auth/accept-terms", response_model=User)
async def accept_terms(
    payload: AcceptTermsIn, user: User = Depends(get_current_user)
):
    """Record that the user accepted the terms/liability disclaimer at the
    given version. The version must match the current server-side revision
    to be considered valid — this lets us force re-acceptance whenever the
    legal text changes."""
    if payload.version != CURRENT_TERMS_VERSION:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Versione regolamento non valida (attesa {CURRENT_TERMS_VERSION})"
            ),
        )
    now = _now()
    await db.users.update_one(
        {"user_id": user.user_id},
        {
            "$set": {
                "terms_version": payload.version,
                "terms_accepted_at": now,
            }
        },
    )
    fresh = await db.users.find_one({"user_id": user.user_id}, {"_id": 0})
    return _user_from_doc(fresh)


@api_router.get("/auth/terms-version")
async def terms_version_info():
    """Public: current terms version. Lets the client detect a bump before
    calling any protected route."""
    return {"version": CURRENT_TERMS_VERSION}


# ============================== Public users ==============================

@api_router.get("/users/{target_id}", response_model=PublicUser)
async def get_public_user(target_id: str, user: User = Depends(get_current_user)):
    """Return the public profile of another user. Access is granted only if
    the caller and the target share at least one group (participant lists
    of any group). Callers can always view their own profile.
    """
    if not _USER_ID_RE.match(target_id):
        raise HTTPException(status_code=400, detail="user_id non valido")
    target = await db.users.find_one({"user_id": target_id}, {"_id": 0})

    if target_id != user.user_id:
        # Return 403 (not 404) both when target doesn't exist and when there is
        # no shared group. This avoids leaking device-id existence to callers.
        if not target:
            raise HTTPException(
                status_code=403,
                detail="Puoi vedere solo profili di utenti con cui condividi un gruppo",
            )
        shared = await db.groups.find_one(
            {"participants.user_id": {"$all": [user.user_id, target_id]}},
            {"_id": 0, "group_id": 1},
        )
        if not shared:
            raise HTTPException(
                status_code=403,
                detail="Puoi vedere solo profili di utenti con cui condividi un gruppo",
            )
    else:
        # target must exist for self-view (it always does because get_current_user auto-creates)
        if not target:
            raise HTTPException(status_code=404, detail="Utente non trovato")

    return PublicUser(
        user_id=target["user_id"],
        name=target.get("name") or "Anonimo",
        picture=target.get("picture"),
        gender=target.get("gender"),
        age=target.get("age"),
        created_at=target["created_at"],
    )


# ============================== Groups ==============================

def _group_doc_to_model(d: dict) -> Group:
    d = _strip(dict(d))
    # Backward-compat: groups created before the gender filter existed
    # default to "any" (everyone welcome).
    d.setdefault("gender_filter", "any")
    return Group(**d)


@api_router.post("/groups", response_model=Group)
async def create_group(payload: GroupCreate, user: User = Depends(get_current_user)):
    _require_accepted_terms(user)
    if not user.name:
        raise HTTPException(status_code=400, detail="Completa il profilo (nome) prima di creare un gruppo")
    if user.age is None:
        raise HTTPException(
            status_code=400,
            detail="Aggiungi la tua età nel profilo prima di creare un gruppo",
        )
    if payload.max_participants < payload.min_participants:
        raise HTTPException(status_code=400, detail="max_participants < min_participants")
    if payload.max_age < payload.min_age:
        raise HTTPException(status_code=400, detail="max_age < min_age")
    # Gender-filter policy: if the creator restricts the group to one gender,
    # their own gender MUST match (otherwise they'd create a group they
    # can't join).
    if payload.gender_filter in ("male", "female"):
        if not user.gender:
            raise HTTPException(
                status_code=400,
                detail="Imposta il tuo sesso nel profilo prima di creare un gruppo con filtro di genere",
            )
        if user.gender != payload.gender_filter:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Non puoi creare un gruppo \"solo donne\" se non sei una donna."
                    if payload.gender_filter == "female"
                    else "Non puoi creare un gruppo \"solo uomini\" se non sei un uomo."
                ),
            )
    # Age-segregation policy: the group must be either fully-adult (min>=18)
    # or fully-minor (max<=17). Mixed ranges are refused, and the group must
    # match the creator's own age bucket.
    g_bucket = _group_age_bucket(payload.min_age, payload.max_age)
    if g_bucket is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "La fascia d'età non può mischiare minorenni e maggiorenni. "
                "Scegli o 14-17 (minorenni) oppure 18+ (maggiorenni)."
            ),
        )
    u_bucket = _user_age_bucket(user)
    if u_bucket != g_bucket:
        if u_bucket == "minor":
            raise HTTPException(
                status_code=400,
                detail="Sei minorenne: puoi creare solo gruppi per minorenni (14-17).",
            )
        raise HTTPException(
            status_code=400,
            detail="Sei maggiorenne: puoi creare solo gruppi per maggiorenni (18+).",
        )
    if not payload.city.strip():
        raise HTTPException(status_code=400, detail="Inserisci la città")
    # Content moderation on every free-text field
    _reject_if_forbidden(
        payload.title,
        payload.description or "",
        payload.location,
        payload.city,
        payload.category_label,
    )
    # Reject events that are already expired (past date + buffer) at creation
    event_dt = _event_datetime(payload.date, payload.time)
    if event_dt is None:
        raise HTTPException(status_code=400, detail="Data/ora non valide")
    now_local = datetime.now(_APP_TZ)
    if event_dt + timedelta(hours=EXPIRED_BUFFER_HOURS) < now_local:
        raise HTTPException(status_code=400, detail="Data del gruppo nel passato")

    # If the client already picked coordinates via the autocomplete, trust
    # them; otherwise geocode the city name. Failure isn't blocking.
    lat, lon = payload.lat, payload.lon
    if lat is None or lon is None:
        coords = await _geocode(payload.city.strip())
        if coords:
            lat, lon = coords

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
        "city": payload.city.strip(),
        "province": (payload.province or "").strip() or None,
        "lat": lat,
        "lon": lon,
        "description": (payload.description or "").strip(),
        "date": payload.date,
        "time": payload.time,
        "min_participants": payload.min_participants,
        "max_participants": payload.max_participants,
        "min_age": payload.min_age,
        "max_age": payload.max_age,
        "gender_filter": payload.gender_filter,
        "owner_id": user.user_id,
        "owner_name": user.name,
        "owner_picture": user.picture,
        "participants": [owner_participant],
        "created_at": _now(),
    }
    # Store a GeoJSON point too so we can query with $geoWithin/$near via
    # the 2dsphere index (the raw lat/lon fields are kept for backward-
    # compatibility with older clients).
    if lat is not None and lon is not None:
        try:
            doc["geo"] = {"type": "Point", "coordinates": [float(lon), float(lat)]}
        except Exception:
            pass
    await db.groups.insert_one(dict(doc))
    return _group_doc_to_model(doc)


# ---- Cursor helpers (opaque URL-safe base64 of ISO datetime) ----

def _encode_cursor(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return base64.urlsafe_b64encode(dt.isoformat().encode("ascii")).decode("ascii").rstrip("=")


def _decode_cursor(cur: Optional[str]) -> Optional[datetime]:
    if not cur:
        return None
    try:
        pad = "=" * (-len(cur) % 4)
        raw = base64.urlsafe_b64decode((cur + pad).encode("ascii")).decode("ascii")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None


@api_router.get("/groups", response_model=GroupPage)
async def list_groups(
    category: Optional[str] = None,
    q: Optional[str] = None,
    lat: Optional[float] = Query(default=None, ge=-90, le=90),
    lon: Optional[float] = Query(default=None, ge=-180, le=180),
    radius_km: Optional[float] = Query(default=None, ge=0.1, le=100),
    limit: int = Query(default=30, ge=1, le=100),
    cursor: Optional[str] = Query(default=None, max_length=256),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """Cursor-paginated feed.

    - `limit`: page size (max 100, default 30).
    - `cursor`: opaque page token returned by the previous call.
    - When `lat/lon/radius_km` are all provided, results are pre-filtered
      server-side via the 2dsphere `$geoWithin` operator; legacy groups
      without a geo point are still surfaced (backward-compat).
    """
    await _purge_expired_groups()

    query: dict = {"status": {"$ne": "expired"}}
    if category and category != "all":
        query["category"] = category
    if q:
        query["title"] = {"$regex": q, "$options": "i"}
    # Age-bucket filter (adults vs minors, see policy above).
    bucket = _user_age_bucket(user)
    if bucket == "adult":
        query["min_age"] = {"$gte": ADULT_MIN_AGE}
    elif bucket == "minor":
        query["max_age"] = {"$lte": ADULT_MIN_AGE - 1}
    # Cursor: continue after this created_at.
    after = _decode_cursor(cursor)
    if after is not None:
        query["created_at"] = {"$lt": after}
    # Geo pre-filter (2dsphere). Only when the caller sent a full triple.
    has_geo = lat is not None and lon is not None and radius_km is not None
    if has_geo:
        radius_meters = float(radius_km) * 1000.0
        geo_filter = {
            "geo": {
                "$geoWithin": {
                    "$centerSphere": [[float(lon), float(lat)], radius_meters / 6378137.0],
                }
            }
        }
        # Include groups without a geo point (legacy) for backward-compat.
        query = {
            "$and": [
                query,
                {"$or": [geo_filter, {"geo": {"$exists": False}}]},
            ]
        }

    # Fetch limit+1 to know if there's another page. Sort by created_at
    # DESC (newest first) — this matches the compound index we create on
    # startup: {status, category, created_at}.
    cursor_docs = (
        db.groups.find(query, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit + 1)
    )
    items = await cursor_docs.to_list(length=limit + 1)

    # If radius_km is set BUT some legacy groups without `geo` slipped in,
    # apply a Haversine fallback filter for those specific docs.
    if has_geo:
        keep: List[dict] = []
        for i in items:
            if i.get("geo"):
                keep.append(i)
                continue
            g_lat, g_lon = i.get("lat"), i.get("lon")
            if g_lat is None or g_lon is None:
                keep.append(i)  # truly legacy — visible
                continue
            if _haversine_km(lat, lon, g_lat, g_lon) <= radius_km:
                keep.append(i)
        items = keep

    next_cursor: Optional[str] = None
    if len(items) > limit:
        # Trim to exactly `limit`; encode the last kept item's created_at
        # as the next cursor.
        items = items[:limit]
        last = items[-1].get("created_at")
        if isinstance(last, datetime):
            next_cursor = _encode_cursor(last)

    return GroupPage(
        items=[Group(**i) for i in items],
        next_cursor=next_cursor,
    )


@api_router.get("/groups/mine", response_model=dict)
async def my_groups(user: User = Depends(get_current_user)):
    await _purge_expired_groups()
    created = await db.groups.find(
        {"owner_id": user.user_id, "status": {"$ne": "expired"}}, {"_id": 0}
    ).sort("created_at", -1).to_list(length=200)
    joined = await db.groups.find(
        {
            "participants.user_id": user.user_id,
            "owner_id": {"$ne": user.user_id},
            "status": {"$ne": "expired"},
        },
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
    _require_accepted_terms(user)
    if not user.name:
        raise HTTPException(status_code=400, detail="Completa il profilo (nome) prima di unirti")
    if user.age is None:
        raise HTTPException(
            status_code=400,
            detail="Aggiungi la tua età nel profilo prima di unirti a un gruppo",
        )
    g = await db.groups.find_one({"group_id": group_id}, {"_id": 0})
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    # Age-segregation check
    g_bucket = _group_age_bucket(g.get("min_age", 0), g.get("max_age", 120))
    u_bucket = _user_age_bucket(user)
    if g_bucket is not None and u_bucket != g_bucket:
        if g_bucket == "adult":
            raise HTTPException(
                status_code=403,
                detail="Questo gruppo è riservato ai maggiorenni (18+).",
            )
        raise HTTPException(
            status_code=403,
            detail="Questo gruppo è riservato ai minorenni (14-17).",
        )
    # Gender-filter check. "any" (or missing on legacy groups) → allow all.
    g_gender = g.get("gender_filter") or "any"
    if g_gender in ("male", "female"):
        if not user.gender:
            raise HTTPException(
                status_code=400,
                detail="Imposta il tuo sesso nel profilo prima di unirti a questo gruppo",
            )
        if user.gender != g_gender:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Questo gruppo è riservato solo alle donne."
                    if g_gender == "female"
                    else "Questo gruppo è riservato solo agli uomini."
                ),
            )
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
    _require_accepted_terms(user)
    if not user.name:
        raise HTTPException(status_code=400, detail="Completa il profilo (nome) prima di scrivere")
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Messaggio vuoto")
    _reject_if_forbidden(text)
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
    result_msg = Message(**_strip(msg))
    # Fan-out to any WebSocket subscriber in the room. Fire-and-forget so
    # the HTTP response is not delayed by slow/dead sockets.
    try:
        asyncio.create_task(
            chat_manager.broadcast(
                group_id,
                {"type": "message", "data": result_msg.model_dump(mode="json")},
            )
        )
    except Exception as exc:
        logger.warning("chat broadcast schedule failed: %s", exc)
    return result_msg


# ============================== Chat WebSocket ==============================
#
# Real-time chat delivery. Each participant of a group opens a single WS
# to /api/ws/groups/{group_id}?token=<session_token>. The server:
#   1. Authenticates the token (query-param, since browsers can't set
#      Authorization headers on native WS).
#   2. Verifies the caller is an actual participant of the group.
#   3. Registers the socket in an in-memory room keyed by group_id.
#   4. Streams NEW messages coming from the HTTP POST endpoint.
#
# Rationale: this pattern lets us push messages to 10k+ concurrent listeners
# without every client polling every 4 seconds (5000 rps -> ~0 rps). Sending
# still goes through POST /messages so every message keeps its content
# moderation, ownership and rate-limit checks — the WS is broadcast-only.
#
# Note: this is a single-process in-memory manager. When we horizontally
# scale to multiple workers we'll swap the manager for a Redis pub/sub
# bridge (broadcast → publish; connections subscribe on connect). The API
# surface for the client will not change.

class _ChatConnectionManager:
    """Per-group set of active WebSocket connections."""

    def __init__(self) -> None:
        # group_id -> set of live WebSockets
        self._rooms: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, group_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._rooms.setdefault(group_id, set()).add(ws)

    async def disconnect(self, group_id: str, ws: WebSocket) -> None:
        async with self._lock:
            room = self._rooms.get(group_id)
            if room is None:
                return
            room.discard(ws)
            if not room:
                self._rooms.pop(group_id, None)

    async def broadcast(self, group_id: str, payload: dict) -> None:
        """Send `payload` (as JSON) to every socket in the room. Any socket
        that raises during send is dropped silently — the client will
        reconnect on its own."""
        # Snapshot the set under the lock, then send outside the lock so a
        # slow client cannot block others.
        async with self._lock:
            sockets = list(self._rooms.get(group_id, set()))
        if not sockets:
            return
        stale: List[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        if stale:
            async with self._lock:
                room = self._rooms.get(group_id)
                if room is not None:
                    for ws in stale:
                        room.discard(ws)
                    if not room:
                        self._rooms.pop(group_id, None)

    def room_size(self, group_id: str) -> int:
        return len(self._rooms.get(group_id, set()))


chat_manager = _ChatConnectionManager()


@app.websocket("/api/ws/groups/{group_id}")
async def chat_socket(websocket: WebSocket, group_id: str, token: Optional[str] = Query(default=None)):
    """Real-time chat channel.

    Query params:
      - token: Bearer session token (same value used in HTTP Authorization)

    Server → Client messages:
      { "type": "connected" }
      { "type": "message", "data": <Message> }
      { "type": "error",   "detail": "..." }        (before close)
      { "type": "pong" }                            (in reply to ping)

    Client → Server:
      { "type": "ping" }   (keep-alive; server replies "pong")
    """
    # Accept first so we can send a structured error before closing on auth
    # failure — this gives the client a clean reason string.
    await websocket.accept()

    async def _fail(code: int, detail: str) -> None:
        try:
            await websocket.send_json({"type": "error", "detail": detail})
        except Exception:
            pass
        # 4401 = auth, 4403 = forbidden, 4404 = not found (custom range)
        await websocket.close(code=code)

    tok = (token or "").strip()
    if not tok or not _SESSION_TOKEN_RE.match(tok):
        await _fail(4401, "Missing or invalid token")
        return
    user = await _lookup_session_user(tok)
    if not user:
        await _fail(4401, "Sessione scaduta o non valida")
        return

    g = await db.groups.find_one(
        {"group_id": group_id},
        {"_id": 0, "participants": 1, "status": 1},
    )
    if not g:
        await _fail(4404, "Group not found")
        return
    if g.get("status") == "expired":
        await _fail(4404, "Gruppo scaduto")
        return
    if not any(p.get("user_id") == user.user_id for p in (g.get("participants") or [])):
        await _fail(4403, "Non sei nel gruppo")
        return

    await chat_manager.connect(group_id, websocket)
    try:
        await websocket.send_json({"type": "connected"})
        # Keep-alive receive loop. We don't accept new-message inputs here
        # (moderation lives in the HTTP endpoint); we only handle "ping".
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {}
            if isinstance(data, dict) and data.get("type") == "ping":
                try:
                    await websocket.send_json({"type": "pong"})
                except Exception:
                    break
            # Any other client frame is ignored — WS is broadcast-only.
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover
        logger.warning("chat socket error group=%s: %s", group_id, exc)
    finally:
        await chat_manager.disconnect(group_id, websocket)


# ============================== Geocode (public) ==============================

@api_router.get("/cities/suggest")
async def cities_suggest(
    q: str = Query(..., min_length=2, max_length=60),
    limit: int = Query(6, ge=1, le=10),
):
    """Autocomplete Italian cities (public endpoint). Returns a list of
    {name, province, region, lat, lon, display} objects."""
    return await _search_cities(q, limit)


@api_router.get("/geocode")
async def geocode(city: str = Query(..., min_length=1, max_length=100), street: str = Query("", max_length=100)):
    """Resolve an address to lat/lon. Used by the client when the user grants
    no GPS permission and enters a reference city manually."""
    coords = await _geocode(city, street)
    if not coords:
        raise HTTPException(status_code=404, detail="Indirizzo non trovato")
    return {"lat": coords[0], "lon": coords[1]}


# ============================== Reports ==============================

async def _target_exists(target_type: str, target_id: str) -> bool:
    """Return True if the reported entity actually exists in the DB."""
    if target_type == "group":
        return await db.groups.find_one({"group_id": target_id}, {"_id": 1}) is not None
    if target_type == "user":
        return await db.users.find_one({"user_id": target_id}, {"_id": 1}) is not None
    if target_type == "message":
        return await db.messages.find_one({"message_id": target_id}, {"_id": 1}) is not None
    return False


@api_router.post("/reports", response_model=Report)
async def create_report(payload: ReportCreate, user: User = Depends(get_current_user)):
    """Create a new user-submitted report. Rate-limits multiple reports of
    the same target by the same user (only one per target per user)."""
    if not await _target_exists(payload.target_type, payload.target_id):
        raise HTTPException(status_code=404, detail="Elemento segnalato non trovato")

    # A user cannot report the same target multiple times.
    existing = await db.reports.find_one({
        "reporter_id": user.user_id,
        "target_type": payload.target_type,
        "target_id": payload.target_id,
    })
    if existing:
        raise HTTPException(status_code=409, detail="Hai già segnalato questo elemento")

    report_id = f"rep_{uuid.uuid4().hex[:12]}"
    doc = {
        "report_id": report_id,
        "target_type": payload.target_type,
        "target_id": payload.target_id,
        "reason": payload.reason,
        "description": (payload.description or "").strip()[:500],
        "reporter_id": user.user_id,
        "reporter_name": user.name or "Utente",
        "status": "pending",
        "created_at": _now(),
    }
    await db.reports.insert_one(dict(doc))

    # Log if this target crosses the alert threshold — an operator can then
    # act on it (out-of-scope for MVP auto take-down).
    try:
        count = await db.reports.count_documents({
            "target_type": payload.target_type,
            "target_id": payload.target_id,
            "status": "pending",
        })
        if count >= REPORT_ALERT_THRESHOLD:
            logger.warning(
                "REPORT_ALERT target=%s id=%s pending=%d",
                payload.target_type, payload.target_id, count,
            )
    except Exception:
        pass

    return Report(**doc)


@api_router.get("/reports/mine", response_model=List[Report])
async def my_reports(user: User = Depends(get_current_user)):
    """List reports created by the currently authenticated user."""
    cursor = db.reports.find(
        {"reporter_id": user.user_id}, {"_id": 0}
    ).sort("created_at", -1).limit(100)
    items = await cursor.to_list(length=100)
    return [Report(**i) for i in items]


# ============================== Admin / Moderation ==============================
# The app owner unlocks a hidden admin panel by entering the shared secret
# (env var ADMIN_SECRET) once inside the app. The client then attaches this
# secret as the `X-Admin-Secret` header on every admin call.

_ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "").strip()


class ReportStatusUpdate(BaseModel):
    status: Literal["pending", "reviewed", "dismissed"]


class AdminReport(Report):
    """Report enriched with a snapshot of the reported target, so the
    admin panel can display context without additional round-trips."""
    target_snapshot: Optional[dict] = None
    target_exists: bool = True


async def require_admin(x_admin_secret: Optional[str] = Header(default=None)) -> bool:
    if not _ADMIN_SECRET:
        # Explicitly refuse admin access when server is misconfigured, rather
        # than silently allowing an empty secret to match.
        raise HTTPException(status_code=503, detail="Admin non configurato sul server")
    if not x_admin_secret or x_admin_secret.strip() != _ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Segreto admin non valido")
    return True


async def _load_target_snapshot(target_type: str, target_id: str) -> Tuple[Optional[dict], bool]:
    """Fetch a compact snapshot of the reported entity for the admin UI."""
    if target_type == "group":
        g = await db.groups.find_one({"group_id": target_id}, {"_id": 0})
        if not g:
            return None, False
        return {
            "title": g.get("title"),
            "category_label": g.get("category_label"),
            "city": g.get("city"),
            "province": g.get("province"),
            "owner_id": g.get("owner_id"),
            "owner_name": g.get("owner_name"),
            "date": g.get("date"),
            "time": g.get("time"),
            "description": g.get("description"),
            "participants_count": len(g.get("participants") or []),
        }, True
    if target_type == "user":
        u = await db.users.find_one({"user_id": target_id}, {"_id": 0})
        if not u:
            return None, False
        return {
            "name": u.get("name"),
            "picture": u.get("picture"),
            "gender": u.get("gender"),
            "age": u.get("age"),
        }, True
    if target_type == "message":
        m = await db.messages.find_one({"message_id": target_id}, {"_id": 0})
        if not m:
            return None, False
        # also pull group title for context
        g_title = None
        g = await db.groups.find_one({"group_id": m.get("group_id")}, {"_id": 0, "title": 1})
        if g:
            g_title = g.get("title")
        return {
            "text": m.get("text"),
            "user_id": m.get("user_id"),
            "user_name": m.get("user_name"),
            "group_id": m.get("group_id"),
            "group_title": g_title,
        }, True
    return None, False


@api_router.get("/admin/verify")
async def admin_verify(_ok: bool = Depends(require_admin)):
    """Cheap endpoint used by the client to check whether the stored secret
    is still valid, before showing the admin panel."""
    return {"ok": True}


@api_router.get("/admin/reports", response_model=List[AdminReport])
async def admin_list_reports(
    status: str = Query(default="pending"),
    _ok: bool = Depends(require_admin),
):
    query: dict = {}
    if status and status != "all":
        query["status"] = status
    cursor = db.reports.find(query, {"_id": 0}).sort("created_at", -1).limit(500)
    items = await cursor.to_list(length=500)
    out: List[AdminReport] = []
    for i in items:
        snap, exists = await _load_target_snapshot(i["target_type"], i["target_id"])
        out.append(AdminReport(
            **i,
            target_snapshot=snap,
            target_exists=exists,
        ))
    return out


@api_router.get("/admin/stats")
async def admin_stats(_ok: bool = Depends(require_admin)):
    """High-level counts used to power the admin dashboard header."""
    pending = await db.reports.count_documents({"status": "pending"})
    reviewed = await db.reports.count_documents({"status": "reviewed"})
    dismissed = await db.reports.count_documents({"status": "dismissed"})
    total_users = await db.users.count_documents({})
    total_groups = await db.groups.count_documents({})
    return {
        "pending": pending,
        "reviewed": reviewed,
        "dismissed": dismissed,
        "users": total_users,
        "groups": total_groups,
    }


@api_router.patch("/admin/reports/{report_id}", response_model=Report)
async def admin_update_report(
    report_id: str,
    payload: ReportStatusUpdate,
    _ok: bool = Depends(require_admin),
):
    r = await db.reports.find_one({"report_id": report_id}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Segnalazione non trovata")
    await db.reports.update_one(
        {"report_id": report_id}, {"$set": {"status": payload.status}}
    )
    r["status"] = payload.status
    return Report(**r)


@api_router.delete("/admin/groups/{group_id}")
async def admin_delete_group(group_id: str, _ok: bool = Depends(require_admin)):
    g = await db.groups.find_one({"group_id": group_id}, {"_id": 0})
    if not g:
        raise HTTPException(status_code=404, detail="Gruppo non trovato")
    await db.groups.delete_one({"group_id": group_id})
    await db.messages.delete_many({"group_id": group_id})
    # Mark related reports as reviewed
    await db.reports.update_many(
        {"target_type": "group", "target_id": group_id, "status": "pending"},
        {"$set": {"status": "reviewed"}},
    )
    return {"ok": True, "deleted_group": group_id}


@api_router.delete("/admin/messages/{message_id}")
async def admin_delete_message(message_id: str, _ok: bool = Depends(require_admin)):
    m = await db.messages.find_one({"message_id": message_id}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Messaggio non trovato")
    await db.messages.delete_one({"message_id": message_id})
    await db.reports.update_many(
        {"target_type": "message", "target_id": message_id, "status": "pending"},
        {"$set": {"status": "reviewed"}},
    )
    return {"ok": True, "deleted_message": message_id}


@api_router.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: str, _ok: bool = Depends(require_admin)):
    """Ban a user: remove their account, their created groups (with chat),
    their participation in other groups, and all their messages. Related
    reports are marked reviewed."""
    if not _USER_ID_RE.match(user_id):
        raise HTTPException(status_code=400, detail="user_id non valido")
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not u:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    return await _delete_user_cascade(user_id)


# ============================== Health ==============================

@api_router.get("/")
async def root():
    return {"message": "Barrio API"}


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
    # ---- Indexes ----
    # Kept idempotent: create_index is a no-op when the target index
    # already matches, so restarts are safe. Each index is wrapped
    # individually so a failure on one doesn't block the others.
    async def _idx(coll, keys, **opts):
        try:
            await coll.create_index(keys, **opts)
        except Exception as exc:
            logger.warning("index %s on %s failed: %s", keys, coll.name, exc)

    # users
    await _idx(db.users, "user_id", unique=True)
    await _idx(db.users, "email", unique=True, sparse=True)
    await _idx(db.users, "apple_sub", unique=True, sparse=True)
    # auth_tokens: single-use email verification and password reset tokens.
    # TTL on `expires_at` auto-purges spent/expired records; the token_hash
    # index makes consume look-ups O(1).
    await _idx(db.auth_tokens, "token_hash", unique=True)
    await _idx(db.auth_tokens, "expires_at", expireAfterSeconds=0)
    await _idx(db.auth_tokens, [("user_id", 1), ("kind", 1)])
    # groups: primary key + feed queries
    await _idx(db.groups, "group_id", unique=True)
    # Compound: default feed sort filters by status + created_at.
    await _idx(db.groups, [("status", 1), ("created_at", -1)])
    # Category-filtered feed
    await _idx(db.groups, [("status", 1), ("category", 1), ("created_at", -1)])
    # Age-bucket lookups
    await _idx(db.groups, [("status", 1), ("min_age", 1)])
    await _idx(db.groups, [("status", 1), ("max_age", 1)])
    # /groups/mine: owned + participant lookups
    await _idx(db.groups, "owner_id")
    await _idx(db.groups, "participants.user_id")
    # Geo: 2dsphere on GeoJSON point. Sparse so groups without a coord
    # (very old ones) don't need a placeholder value.
    await _idx(db.groups, [("geo", "2dsphere")], sparse=True)
    # Chat: per-group history sorted by time
    await _idx(db.messages, [("group_id", 1), ("created_at", 1)])
    await _idx(db.messages, "message_id", unique=True)
    await _idx(db.messages, "user_id")
    # Sessions: unique token + TTL cleanup
    await _idx(db.user_sessions, "session_token", unique=True)
    await _idx(db.user_sessions, "expires_at", expireAfterSeconds=0)
    await _idx(db.user_sessions, "user_id")
    # Reports: admin queue + user-side history + dedup
    await _idx(db.reports, [("status", 1), ("created_at", -1)])
    await _idx(db.reports, [("reporter_id", 1), ("target_type", 1), ("target_id", 1)])
    await _idx(db.reports, [("target_type", 1), ("target_id", 1), ("status", 1)])
    await _idx(db.reports, "report_id", unique=True)

    # ---- One-shot backfill: populate `geo` GeoJSON on legacy groups. ----
    # Runs cheap because the compound index above already exists after this
    # backfill on subsequent restarts.
    try:
        missing = db.groups.find(
            {"lat": {"$ne": None}, "lon": {"$ne": None}, "geo": {"$exists": False}},
            {"_id": 0, "group_id": 1, "lat": 1, "lon": 1},
        )
        bulk = 0
        async for g in missing:
            try:
                await db.groups.update_one(
                    {"group_id": g["group_id"]},
                    {
                        "$set": {
                            "geo": {
                                "type": "Point",
                                "coordinates": [float(g["lon"]), float(g["lat"])],
                            }
                        }
                    },
                )
                bulk += 1
            except Exception:
                continue
        if bulk:
            logger.info("[startup] geo-backfilled %d group(s)", bulk)
    except Exception as exc:
        logger.warning("geo backfill error: %s", exc)

    # Kick off a background loop that purges expired groups every 5 minutes.
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
