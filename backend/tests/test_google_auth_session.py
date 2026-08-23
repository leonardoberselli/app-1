"""
Iteration 14 — Emergent Managed Google Sign-In session-token auth.

Because we cannot complete the real Google OAuth flow from an automated
test, we seed valid `users` + `user_sessions` rows directly in MongoDB
and exercise the protected endpoints with `Authorization: Bearer <session_token>`.

Covers:
- Auth guard (401 no header / malformed / unknown)
- Happy path with seeded session (GET /auth/me, POST /groups, POST /auth/logout revokes)
- Expired session -> 401
- POST /auth/session input validation (empty / too-short session_id)
- POST /auth/session with random string reaches Emergent and gets 401
- Age/T&C gate: user without terms_version cannot create group
"""
import os
import re
import uuid
import secrets
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# ---- Config
FRONTEND_ENV = Path("/app/frontend/.env")
PUBLIC_URL = None
for line in FRONTEND_ENV.read_text().splitlines():
    if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
        PUBLIC_URL = line.split("=", 1)[1].strip().strip('"')
BASE_URL = (PUBLIC_URL or "http://localhost:8001").rstrip("/")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]

TERMS_VERSION = "2026-06-01"  # must match server.CURRENT_TERMS_VERSION


def _hex32() -> str:
    return secrets.token_hex(16)  # 32 hex chars — valid session_token


def _now():
    return datetime.now(timezone.utc)


def _seed_user(**overrides) -> str:
    uid = overrides.pop("user_id", f"user_{uuid.uuid4().hex[:12]}")
    doc = {
        "user_id": uid,
        "email": overrides.pop("email", f"TEST_{uid}@example.com"),
        "name": "Test User",
        "age": 25,
        "gender": "male",
        "picture": None,
        "profile_complete": True,
        "terms_version": TERMS_VERSION,
        "terms_accepted_at": _now(),
        "created_at": _now(),
        **overrides,
    }
    db.users.insert_one(doc)
    return uid


def _seed_session(user_id: str, expires_in: timedelta = timedelta(days=7)) -> str:
    token = f"sess_test_{_hex32()}"  # 42 chars, matches ^[A-Za-z0-9_\-\.]{16,512}$
    db.user_sessions.insert_one({
        "session_token": token,
        "user_id": user_id,
        "created_at": _now(),
        "expires_at": _now() + expires_in,
    })
    return token


def _cleanup():
    # Delete all test seeded users + their sessions + groups
    users = list(db.users.find({"email": {"$regex": "^TEST_"}}, {"user_id": 1}))
    uids = [u["user_id"] for u in users]
    if uids:
        db.user_sessions.delete_many({"user_id": {"$in": uids}})
        db.groups.delete_many({"owner_id": {"$in": uids}})
        db.messages.delete_many({"user_id": {"$in": uids}})
        db.users.delete_many({"user_id": {"$in": uids}})


@pytest.fixture(scope="module", autouse=True)
def cleanup_module():
    _cleanup()
    yield
    _cleanup()


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _future_date():
    return (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")


def _group_payload(title=None):
    return {
        "title": title or f"TEST_grp_{uuid.uuid4().hex[:6]}",
        "category": "basketball",
        "category_label": "Basket",
        "location": "Milano",
        "city": "Milano",
        "description": "created by google-auth test",
        "date": _future_date(),
        "time": "18:30",
        "min_participants": 3,
        "max_participants": 10,
        "min_age": 18,
        "max_age": 40,
    }


# ============================== 1. Auth guard behaviour
class TestAuthGuard:
    def test_no_authorization_header_401(self, api):
        r = api.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401

    def test_wrong_scheme_401(self, api):
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers={"Authorization": "Basic abc"})
        assert r.status_code == 401

    def test_malformed_short_bearer_401(self, api):
        # "short" is < 16 chars → regex fails
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers={"Authorization": "Bearer short"})
        assert r.status_code == 401
        assert "non valido" in r.json()["detail"].lower()

    def test_bearer_with_bad_chars_401(self, api):
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers={"Authorization": "Bearer has spaces here bad!!"})
        assert r.status_code == 401

    def test_unknown_but_well_formed_session_token_401(self, api):
        token = f"sess_unknown_{_hex32()}"
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401
        assert r.json()["detail"] == "Sessione scaduta o non valida"


# ============================== 2. Happy path via DB seed
class TestSessionHappyPath:
    def test_me_returns_seeded_user(self, api):
        uid = _seed_user(name="Alice Seeded", age=28)
        token = _seed_session(uid)
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user_id"] == uid
        assert body["name"] == "Alice Seeded"
        assert body["age"] == 28
        assert body["profile_complete"] is True

    def test_create_group_with_seeded_session(self, api):
        uid = _seed_user(name="Group Owner", age=30)
        token = _seed_session(uid)
        hdr = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title=f"TEST_google_{uuid.uuid4().hex[:6]}"),
                     headers=hdr)
        assert r.status_code == 200, r.text
        g = r.json()
        assert g["owner_id"] == uid
        assert g["owner_name"] == "Group Owner"
        # participant = owner
        assert any(p["user_id"] == uid for p in g["participants"])
        # verify persisted
        r2 = api.get(f"{BASE_URL}/api/groups/{g['group_id']}")
        assert r2.status_code == 200
        assert r2.json()["group_id"] == g["group_id"]

    def test_logout_revokes_session(self, api):
        uid = _seed_user(name="Loggin Out", age=26)
        token = _seed_session(uid)
        hdr = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        # pre-check: session valid
        assert api.get(f"{BASE_URL}/api/auth/me", headers=hdr).status_code == 200
        # logout
        r = api.post(f"{BASE_URL}/api/auth/logout", headers=hdr)
        assert r.status_code == 200
        assert r.json().get("ok") is True
        # DB row removed
        assert db.user_sessions.count_documents({"session_token": token}) == 0
        # /auth/me now 401
        r = api.get(f"{BASE_URL}/api/auth/me", headers=hdr)
        assert r.status_code == 401

    def test_logout_is_idempotent(self, api):
        # Second call on the same (now-unknown) token still returns 200
        token = f"sess_gone_{_hex32()}"
        r = api.post(f"{BASE_URL}/api/auth/logout",
                     headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200


# ============================== 3. Expired session
class TestExpiredSession:
    def test_expired_session_401_and_row_cleaned(self, api):
        uid = _seed_user(name="Expired Sess", age=22)
        token = _seed_session(uid, expires_in=timedelta(minutes=-5))  # already past
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401
        # Backend deletes expired sessions on lookup
        assert db.user_sessions.count_documents({"session_token": token}) == 0


# ============================== 4-5. POST /auth/session validation
class TestSessionExchangeValidation:
    def test_empty_session_id_400(self, api):
        # Pydantic may reject with 422 (min_length=1) or app-level 400.
        r = api.post(f"{BASE_URL}/api/auth/session", json={"session_id": ""})
        assert r.status_code in (400, 422), r.text

    def test_missing_session_id_key_422(self, api):
        r = api.post(f"{BASE_URL}/api/auth/session", json={})
        assert r.status_code == 422

    def test_too_short_session_id_400(self, api):
        # 5 chars, well below the 8-char server-side minimum
        r = api.post(f"{BASE_URL}/api/auth/session", json={"session_id": "short"})
        assert r.status_code in (400, 422), r.text

    def test_random_session_id_rejected_by_emergent_401(self, api):
        # Well-formed length but random → Emergent will 401
        r = api.post(f"{BASE_URL}/api/auth/session",
                     json={"session_id": _hex32()})
        # Accepted values: 401 (Emergent rejects) OR 502 (upstream unreachable
        # from sandbox). Both mean the backend correctly relayed and did not
        # create a user.
        assert r.status_code in (401, 502), r.text
        if r.status_code == 401:
            assert "google" in r.json()["detail"].lower() or "session" in r.json()["detail"].lower()


# ============================== 7. Age/T&C gate for group creation
class TestTermsGate:
    def test_no_terms_accepted_group_create_gate(self, api):
        uid = _seed_user(
            name="No Terms User",
            age=25,
            terms_version=None,
            terms_accepted_at=None,
        )
        token = _seed_session(uid)
        hdr = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title=f"TEST_gate_{uuid.uuid4().hex[:6]}"),
                     headers=hdr)
        # Server should refuse — either 400 (business gate) or 403.
        assert r.status_code in (400, 403), r.text
        detail = (r.json().get("detail") or "").lower()
        # Italian gate message referencing regolamento / condizioni / termini
        assert any(
            kw in detail
            for kw in ("regolamento", "condizioni", "termini", "accetta", "responsabilit")
        ), f"expected T&C gate message, got: {detail!r}"


# ============================== 6. Duplicate exchange guard (best effort)
class TestReplayGuard:
    def test_same_session_id_second_time_409_or_401(self, api):
        # We can't produce a real Emergent-valid session_id, but we CAN verify
        # that the same random id is either 401 (Emergent said no) or 409
        # (backend replay guard kicked in). Either is acceptable.
        sid = _hex32()
        r1 = api.post(f"{BASE_URL}/api/auth/session", json={"session_id": sid})
        r2 = api.post(f"{BASE_URL}/api/auth/session", json={"session_id": sid})
        assert r1.status_code in (401, 502)
        # Second call: 409 (replay-guard) preferred, or 401 (Emergent still rejects, tolerated)
        assert r2.status_code in (401, 409, 502)
