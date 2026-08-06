"""
GroupUp - Backend Auth & Groups tests
Covers: signup, login, verify-email, request-password-reset, confirm-reset,
GET/POST /api/auth/me, /api/auth/session (invalid), /api/auth/apple (invalid),
groups list (unauthenticated), groups create (unauthorized), indexes.
"""
import os
import time
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv
from pathlib import Path

# Load backend env for direct mongo access
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = "http://localhost:8001"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]


def _now():
    return datetime.now(timezone.utc)


def _rand_email():
    return f"TEST_{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    yield s
    # Cleanup: remove test users, their sessions, tokens
    users = list(db.users.find({"email": {"$regex": "^test_"}}))
    for u in users:
        db.user_sessions.delete_many({"user_id": u["user_id"]})
        db.auth_tokens.delete_many({"user_id": u["user_id"]})
    db.users.delete_many({"email": {"$regex": "^test_"}})


# ---------------------------------------------------------------- Health
class TestHealth:
    def test_root(self, api):
        r = api.get(f"{BASE_URL}/api/")
        assert r.status_code == 200
        assert r.json()["message"] == "GroupUp API"


# ---------------------------------------------------------------- Signup
class TestSignup:
    def test_signup_happy(self, api):
        email = _rand_email()
        r = api.post(f"{BASE_URL}/api/auth/signup",
                     json={"email": email, "password": "StrongP@ss1", "name": "Tester"})
        assert r.status_code == 200, r.text
        assert "Registrazione" in r.json().get("message", "")
        # verify persistence
        u = db.users.find_one({"email": email.lower()})
        assert u is not None
        assert u["email_verified"] is False
        assert u.get("password_hash")
        assert "password" in u["providers"]
        # verify email verification token was written
        tok = db.auth_tokens.find_one({"user_id": u["user_id"], "kind": "verify_email"})
        assert tok is not None

    def test_signup_duplicate(self, api):
        email = _rand_email()
        r1 = api.post(f"{BASE_URL}/api/auth/signup",
                      json={"email": email, "password": "StrongP@ss1", "name": "Dup"})
        assert r1.status_code == 200
        r2 = api.post(f"{BASE_URL}/api/auth/signup",
                      json={"email": email, "password": "StrongP@ss1", "name": "Dup"})
        assert r2.status_code == 409
        assert "già registrata" in r2.json()["detail"].lower() or "gia registrata" in r2.json()["detail"].lower()

    def test_signup_password_too_short(self, api):
        r = api.post(f"{BASE_URL}/api/auth/signup",
                     json={"email": _rand_email(), "password": "short", "name": "X"})
        assert r.status_code == 422


# ---------------------------------------------------------------- Login (pre-verify)
class TestLoginPreVerify:
    @pytest.fixture(scope="class")
    def unverified(self, api):
        email = _rand_email()
        api.post(f"{BASE_URL}/api/auth/signup",
                 json={"email": email, "password": "StrongP@ss1", "name": "Unverified"})
        return email

    def test_login_unverified_403(self, api, unverified):
        r = api.post(f"{BASE_URL}/api/auth/login",
                     json={"email": unverified, "password": "StrongP@ss1"})
        assert r.status_code == 403
        assert "Verifica" in r.json()["detail"]

    def test_login_wrong_password(self, api, unverified):
        r = api.post(f"{BASE_URL}/api/auth/login",
                     json={"email": unverified, "password": "WrongPassw0rd"})
        assert r.status_code == 401
        assert r.json()["detail"] == "Email o password non validi"

    def test_login_nonexistent(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login",
                     json={"email": _rand_email(), "password": "AnyPassw0rd"})
        assert r.status_code == 401
        assert r.json()["detail"] == "Email o password non validi"


# ---------------------------------------------------------------- Verify email
class TestVerifyEmail:
    def test_invalid_token(self, api):
        r = api.post(f"{BASE_URL}/api/auth/verify-email",
                     json={"token": "not-a-real-token-abc123"})
        assert r.status_code == 400
        assert "Link non valido" in r.json()["detail"]

    def test_valid_token_returns_session_and_verifies(self, api):
        email = _rand_email()
        api.post(f"{BASE_URL}/api/auth/signup",
                 json={"email": email, "password": "StrongP@ss1", "name": "Verifier"})
        user = db.users.find_one({"email": email.lower()})
        raw = "test-verify-token-" + uuid.uuid4().hex
        db.auth_tokens.insert_one({
            "user_id": user["user_id"],
            "token_hash": hashlib.sha256(raw.encode()).hexdigest(),
            "kind": "verify_email",
            "expires_at": _now() + timedelta(hours=1),
            "used_at": None,
            "created_at": _now(),
        })
        r = api.post(f"{BASE_URL}/api/auth/verify-email", json={"token": raw})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "session_token" in body and body["session_token"].startswith("gu_")
        assert body["user"]["email_verified"] is True
        assert body["user"]["email"] == email.lower()
        # DB state
        u = db.users.find_one({"user_id": user["user_id"]})
        assert u["email_verified"] is True
        # Store for downstream tests
        pytest.verified_email = email
        pytest.verified_password = "StrongP@ss1"
        pytest.verified_session = body["session_token"]
        pytest.verified_user_id = user["user_id"]


# ---------------------------------------------------------------- Login (post-verify) + /me
class TestLoginPostVerifyAndMe:
    def test_login_after_verify(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login",
                     json={"email": pytest.verified_email, "password": pytest.verified_password})
        assert r.status_code == 200, r.text
        assert r.json()["session_token"].startswith("gu_")
        pytest.login_session = r.json()["session_token"]

    def test_me_with_bearer(self, api):
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers={"Authorization": f"Bearer {pytest.login_session}"})
        assert r.status_code == 200
        u = r.json()
        assert u["email"] == pytest.verified_email.lower()
        assert u["email_verified"] is True

    def test_me_without_bearer(self, api):
        r = api.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401


# ---------------------------------------------------------------- Password reset
class TestPasswordReset:
    def test_request_reset_existing_returns_generic(self, api):
        r = api.post(f"{BASE_URL}/api/auth/request-password-reset",
                     json={"email": pytest.verified_email})
        assert r.status_code == 200
        assert "istruzioni" in r.json()["message"].lower()

    def test_request_reset_unknown_returns_same(self, api):
        r = api.post(f"{BASE_URL}/api/auth/request-password-reset",
                     json={"email": _rand_email()})
        assert r.status_code == 200
        assert "istruzioni" in r.json()["message"].lower()

    def test_confirm_reset_invalid_token(self, api):
        r = api.post(f"{BASE_URL}/api/auth/confirm-reset",
                     json={"token": "bogus-token-xyz", "new_password": "NewStrongP@ss1"})
        assert r.status_code == 400

    def test_confirm_reset_valid_and_login(self, api):
        raw = "test-reset-" + uuid.uuid4().hex
        db.auth_tokens.insert_one({
            "user_id": pytest.verified_user_id,
            "token_hash": hashlib.sha256(raw.encode()).hexdigest(),
            "kind": "password_reset",
            "expires_at": _now() + timedelta(minutes=30),
            "used_at": None,
            "created_at": _now(),
        })
        new_pw = "BrandNewP@ss99"
        r = api.post(f"{BASE_URL}/api/auth/confirm-reset",
                     json={"token": raw, "new_password": new_pw})
        assert r.status_code == 200, r.text
        assert r.json()["message"] == "Password aggiornata"
        # Old sessions should be revoked
        r_me = api.get(f"{BASE_URL}/api/auth/me",
                       headers={"Authorization": f"Bearer {pytest.login_session}"})
        assert r_me.status_code == 401
        # Login with new password works
        r_login = api.post(f"{BASE_URL}/api/auth/login",
                           json={"email": pytest.verified_email, "password": new_pw})
        assert r_login.status_code == 200, r_login.text
        pytest.verified_password = new_pw


# ---------------------------------------------------------------- Google session (invalid)
class TestGoogleSession:
    def test_invalid_session_id(self, api):
        r = api.post(f"{BASE_URL}/api/auth/session",
                     json={"session_id": "definitely-not-real-" + uuid.uuid4().hex})
        assert r.status_code == 401
        assert "Invalid session_id" in r.json()["detail"]


# ---------------------------------------------------------------- Apple
class TestApple:
    def test_missing_identity_token(self, api):
        r = api.post(f"{BASE_URL}/api/auth/apple", json={})
        assert r.status_code == 422

    def test_bogus_identity_token(self, api):
        r = api.post(f"{BASE_URL}/api/auth/apple",
                     json={"identity_token": "not.a.jwt"})
        assert r.status_code == 401
        assert "Invalid Apple token" in r.json()["detail"]


# ---------------------------------------------------------------- Groups access
class TestGroupsAccess:
    def test_list_groups_unauth(self, api):
        r = api.get(f"{BASE_URL}/api/groups")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_group_unauth(self, api):
        payload = {
            "title": "TEST_group", "category": "basket", "category_label": "Basket",
            "location": "Milano", "description": "", "date": "2026-02-01", "time": "18:00",
            "min_participants": 2, "max_participants": 10, "min_age": 18, "max_age": 40
        }
        r = api.post(f"{BASE_URL}/api/groups", json=payload)
        assert r.status_code == 401


# ---------------------------------------------------------------- Indexes
class TestIndexes:
    def test_users_email_unique(self):
        idx = db.users.index_information()
        assert any(v.get("unique") and v["key"] == [("email", 1)] for v in idx.values())

    def test_users_apple_sub_sparse_unique(self):
        idx = db.users.index_information()
        found = False
        for v in idx.values():
            if v["key"] == [("apple_sub", 1)] and v.get("unique") and v.get("sparse"):
                found = True
        assert found

    def test_user_sessions_expires_at_ttl(self):
        idx = db.user_sessions.index_information()
        found = False
        for v in idx.values():
            if v["key"] == [("expires_at", 1)] and v.get("expireAfterSeconds") == 0:
                found = True
        assert found

    def test_auth_tokens_expires_at_ttl(self):
        idx = db.auth_tokens.index_information()
        found = False
        for v in idx.values():
            if v["key"] == [("expires_at", 1)] and v.get("expireAfterSeconds") == 0:
                found = True
        assert found
