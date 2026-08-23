from fastapi import FastAPI, APIRouter, HTTPException, Header, Depends, Query
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import re
import math
import asyncio
import logging
import uuid
import httpx
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Tuple
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
    min_age: int = Field(ge=0, le=120)
    max_age: int = Field(ge=0, le=120)


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
_NOMINATIM_UA = "GroupUp/1.0 (activity-groups mobile app)"
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


# ============================== Public users ==============================

@api_router.get("/users/{target_id}", response_model=PublicUser)
async def get_public_user(target_id: str, user: User = Depends(get_current_user)):
    """Return the public profile of another user. Access is granted only if
    the caller and the target share at least one group (participant lists
    of any group). Callers can always view their own profile.
    """
    if not _DEVICE_ID_RE.match(target_id):
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
    return Group(**d)


@api_router.post("/groups", response_model=Group)
async def create_group(payload: GroupCreate, user: User = Depends(get_current_user)):
    if not user.name:
        raise HTTPException(status_code=400, detail="Completa il profilo (nome) prima di creare un gruppo")
    if payload.max_participants < payload.min_participants:
        raise HTTPException(status_code=400, detail="max_participants < min_participants")
    if payload.max_age < payload.min_age:
        raise HTTPException(status_code=400, detail="max_age < min_age")
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
        "owner_id": user.user_id,
        "owner_name": user.name,
        "owner_picture": user.picture,
        "participants": [owner_participant],
        "created_at": _now(),
    }
    await db.groups.insert_one(dict(doc))
    return _group_doc_to_model(doc)


@api_router.get("/groups", response_model=List[Group])
async def list_groups(
    category: Optional[str] = None,
    q: Optional[str] = None,
    lat: Optional[float] = Query(default=None, ge=-90, le=90),
    lon: Optional[float] = Query(default=None, ge=-180, le=180),
    radius_km: Optional[float] = Query(default=None, ge=0.1, le=100),
):
    await _purge_expired_groups()
    query: dict = {}
    if category and category != "all":
        query["category"] = category
    if q:
        query["title"] = {"$regex": q, "$options": "i"}
    cursor = db.groups.find(query, {"_id": 0}).sort("created_at", -1).limit(500)
    items = await cursor.to_list(length=500)

    # Distance filter: only apply if the caller sent a full triple. Groups
    # without lat/lon are INCLUDED (backward-compat with pre-geocoding data).
    if lat is not None and lon is not None and radius_km is not None:
        filtered = []
        for i in items:
            g_lat, g_lon = i.get("lat"), i.get("lon")
            if g_lat is None or g_lon is None:
                filtered.append(i)  # keep legacy groups visible
                continue
            if _haversine_km(lat, lon, g_lat, g_lon) <= radius_km:
                filtered.append(i)
        items = filtered

    return [Group(**i) for i in items[:200]]


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
    return Message(**_strip(msg))


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
    if not _DEVICE_ID_RE.match(user_id):
        raise HTTPException(status_code=400, detail="user_id non valido")
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not u:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    # Delete groups owned by the user + their chats
    owned = await db.groups.find(
        {"owner_id": user_id}, {"_id": 0, "group_id": 1}
    ).to_list(length=1000)
    owned_ids = [g["group_id"] for g in owned]
    if owned_ids:
        await db.groups.delete_many({"group_id": {"$in": owned_ids}})
        await db.messages.delete_many({"group_id": {"$in": owned_ids}})

    # Remove the user from any remaining participant list
    await db.groups.update_many(
        {"participants.user_id": user_id},
        {"$pull": {"participants": {"user_id": user_id}}},
    )
    # Delete the user's messages everywhere
    await db.messages.delete_many({"user_id": user_id})
    # Finally, delete the user profile itself
    await db.users.delete_one({"user_id": user_id})
    # Mark related reports as reviewed
    await db.reports.update_many(
        {"target_type": "user", "target_id": user_id, "status": "pending"},
        {"$set": {"status": "reviewed"}},
    )
    return {
        "ok": True,
        "deleted_user": user_id,
        "deleted_groups": owned_ids,
    }


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
