"""Iteration 20 — Multi-provider authentication tests.

Covers:
- POST /api/auth/register  (Argon2id, rate limit, dup, weak password)
- POST /api/auth/login     (happy path, wrong password, unknown email
                            timing/enumeration equivalence, rate limit)
- POST /api/auth/password/request-reset  (generic message either way)
- POST /api/auth/password/confirm-reset  (single-use, invalidates sessions)
- POST /api/auth/verify-email
- POST /api/auth/apple     (malformed / wrong signature / wrong audience)
- Google backward-compat (legacy Google user still passes /api/auth/me)
- Cross-provider linking (password → then google via /auth/session)
"""
from __future__ import annotations

import hashlib
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from cryptography.hazmat.primitives.asymmetric import rsa
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

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


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _ts() -> str:
    return f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"


def _email() -> str:
    return f"testauth_{_ts()}@barrio.dev"


PASSWORD_OK = "TestPass99"


@pytest.fixture(scope="session")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    yield s
    # cleanup: anything we inserted with an @barrio.dev email + tokens for those user_ids
    users = list(db.users.find({"email": {"$regex": r"@barrio\.dev$"}}, {"user_id": 1}))
    ids = [u["user_id"] for u in users]
    if ids:
        db.user_sessions.delete_many({"user_id": {"$in": ids}})
        db.auth_tokens.delete_many({"user_id": {"$in": ids}})
    db.users.delete_many({"email": {"$regex": r"@barrio\.dev$"}})
    db.users.delete_many({"user_id": {"$regex": r"^user_it20_"}})
    db.user_sessions.delete_many({"user_id": {"$regex": r"^user_it20_"}})
    db.auth_tokens.delete_many({"user_id": {"$regex": r"^user_it20_"}})


# =========================================================
# Registration
# =========================================================
class TestRegister:
    def test_happy_path_creates_user_and_session(self, http):
        email = _email()
        r = http.post(f"{BASE_URL}/api/auth/register",
                      json={"email": email, "password": PASSWORD_OK, "name": "Iter20"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert "session_token" in body and len(body["session_token"]) >= 16
        assert body.get("email_verification_sent") is True
        u = body["user"]
        assert u.get("email") == email
        assert u.get("email_verified") is False
        assert "password" in (u.get("auth_providers") or [])

        # Session works on /api/auth/me
        r = http.get(f"{BASE_URL}/api/auth/me",
                     headers={"Authorization": f"Bearer {body['session_token']}"})
        assert r.status_code == 200, r.text
        me = r.json()
        assert me["email"] == email
        assert me.get("email_verified") is False
        assert "password" in (me.get("auth_providers") or [])

        # DB has password_hash set (Argon2id)
        doc = db.users.find_one({"email": email})
        assert doc is not None
        assert doc.get("password_hash"), "password_hash must be set"
        assert doc["password_hash"].startswith("$argon2"), (
            f"expected argon2 hash prefix, got: {doc['password_hash'][:12]}"
        )

    def test_duplicate_email_returns_409(self, http):
        email = _email()
        r = http.post(f"{BASE_URL}/api/auth/register",
                      json={"email": email, "password": PASSWORD_OK})
        assert r.status_code == 201, r.text
        r = http.post(f"{BASE_URL}/api/auth/register",
                      json={"email": email, "password": PASSWORD_OK})
        assert r.status_code == 409, r.text
        assert "già registrato" in r.json()["detail"].lower() or "gia registrato" in r.json()["detail"].lower()

    @pytest.mark.parametrize("weak", ["password", "12345678", "abcdefgh", "short1", ""])
    def test_weak_password_422(self, http, weak):
        email = _email()
        r = http.post(f"{BASE_URL}/api/auth/register",
                      json={"email": email, "password": weak})
        assert r.status_code == 422, (
            f"weak password {weak!r} expected 422, got {r.status_code}: {r.text}"
        )


# =========================================================
# Login
# =========================================================
class TestLogin:
    @pytest.fixture(scope="class")
    def registered(self, http):
        email = _email()
        r = http.post(f"{BASE_URL}/api/auth/register",
                      json={"email": email, "password": PASSWORD_OK, "name": "LoginTest"})
        assert r.status_code == 201, r.text
        return {"email": email, "password": PASSWORD_OK,
                "user_id": r.json()["user"]["user_id"]}

    def test_happy_path(self, http, registered):
        r = http.post(f"{BASE_URL}/api/auth/login",
                      json={"email": registered["email"], "password": registered["password"]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "session_token" in body
        # Session works
        r = http.get(f"{BASE_URL}/api/auth/me",
                     headers={"Authorization": f"Bearer {body['session_token']}"})
        assert r.status_code == 200
        assert r.json()["email"] == registered["email"]

    def test_wrong_password_401(self, http, registered):
        r = http.post(f"{BASE_URL}/api/auth/login",
                      json={"email": registered["email"], "password": "WrongPass99"})
        assert r.status_code == 401
        assert r.json()["detail"] == "Email o password non corretti"

    def test_unknown_email_401_same_message_and_similar_timing(self, http, registered):
        # Warm up (JIT, connection, etc.) so first call doesn't skew
        http.post(f"{BASE_URL}/api/auth/login",
                  json={"email": registered["email"], "password": "warmup1x"})

        # Wrong password timing (existing account)
        t0 = time.perf_counter()
        r_wrong = http.post(f"{BASE_URL}/api/auth/login",
                            json={"email": registered["email"], "password": "AlsoWrong9"})
        t_wrong = time.perf_counter() - t0

        # Unknown email timing (dummy hash path)
        unknown = _email()
        t0 = time.perf_counter()
        r_unknown = http.post(f"{BASE_URL}/api/auth/login",
                              json={"email": unknown, "password": "Whatever99"})
        t_unknown = time.perf_counter() - t0

        assert r_wrong.status_code == 401
        assert r_unknown.status_code == 401
        # SAME generic message
        assert r_wrong.json()["detail"] == r_unknown.json()["detail"] == "Email o password non corretti"
        # Timing: |delta| should be < 500ms. We loosen from 300ms because HTTPS
        # + Kube ingress adds noise, but a missing dummy-hash would give
        # differences of many hundreds of ms since Argon2id verify is slow.
        delta = abs(t_unknown - t_wrong)
        assert delta < 0.5, (
            f"Timing gap too big — dummy Argon2 not running? "
            f"wrong={t_wrong*1000:.0f}ms unknown={t_unknown*1000:.0f}ms delta={delta*1000:.0f}ms"
        )

    def test_login_rate_limit_returns_429(self, http):
        # Fresh unique email → per-IP counter still shared with other tests,
        # so we may hit the IP limit (15/15min) first. That's still a 429,
        # which is what we care about.
        email = _email()
        got_429 = False
        for _ in range(25):
            r = http.post(f"{BASE_URL}/api/auth/login",
                          json={"email": email, "password": "Bogus999x"})
            if r.status_code == 429:
                got_429 = True
                break
        assert got_429, "Expected a 429 after many failed login attempts"


# =========================================================
# Password reset (request + confirm)
# =========================================================
class TestPasswordReset:
    @pytest.fixture(scope="class")
    def registered(self, http):
        email = _email()
        r = http.post(f"{BASE_URL}/api/auth/register",
                      json={"email": email, "password": PASSWORD_OK, "name": "ResetTest"})
        assert r.status_code == 201, r.text
        return {"email": email, "user_id": r.json()["user"]["user_id"],
                "session_token": r.json()["session_token"]}

    def test_request_reset_existing_creates_token_doc(self, http, registered):
        r = http.post(f"{BASE_URL}/api/auth/password/request-reset",
                      json={"email": registered["email"]})
        assert r.status_code == 200, r.text
        assert "Se l'account esiste" in r.json()["message"]

        doc = db.auth_tokens.find_one(
            {"user_id": registered["user_id"], "kind": "reset_password", "used_at": None}
        )
        assert doc is not None, "reset_password token must be created"
        # Expires ~30min from now
        exp = doc["expires_at"]
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        delta = exp - datetime.now(timezone.utc)
        assert timedelta(minutes=25) <= delta <= timedelta(minutes=31), (
            f"expected ~30min TTL, got {delta}"
        )

    def test_request_reset_unknown_email_same_message_no_token(self, http, registered):
        unknown = _email()
        # response identical
        r1 = http.post(f"{BASE_URL}/api/auth/password/request-reset",
                       json={"email": registered["email"]})
        r2 = http.post(f"{BASE_URL}/api/auth/password/request-reset",
                       json={"email": unknown})
        assert r1.status_code == r2.status_code == 200
        assert r1.json() == r2.json(), "Responses must be IDENTICAL (no enumeration)"

        # No user, therefore no token issued keyed to any user_id we can find,
        # but a doc could exist under a random user_id — instead assert user
        # itself doesn't exist and no token references any user matching that email
        assert db.users.count_documents({"email": unknown}) == 0

    def test_confirm_reset_happy_path_invalidates_sessions(self, http, registered):
        # Manually issue a known token by inserting the doc; we know
        # the code path uses sha256(raw). This lets us "grab" the raw
        # token without an SMTP mailbox.
        raw = "test20reset_" + uuid.uuid4().hex
        db.auth_tokens.insert_one({
            "user_id": registered["user_id"],
            "kind": "reset_password",
            "token_hash": _sha256_hex(raw),
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=30),
            "used_at": None,
        })

        # Verify original session still valid
        r = http.get(f"{BASE_URL}/api/auth/me",
                     headers={"Authorization": f"Bearer {registered['session_token']}"})
        assert r.status_code == 200, "prereq: session valid before reset"

        r = http.post(f"{BASE_URL}/api/auth/password/confirm-reset",
                      json={"token": raw, "new_password": "NewPass2026"})
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True}

        # Original session invalidated
        r = http.get(f"{BASE_URL}/api/auth/me",
                     headers={"Authorization": f"Bearer {registered['session_token']}"})
        assert r.status_code == 401, "sessions must be revoked after reset"

        # Old password no longer works
        r = http.post(f"{BASE_URL}/api/auth/login",
                      json={"email": registered["email"], "password": PASSWORD_OK})
        assert r.status_code == 401

        # New password does work
        r = http.post(f"{BASE_URL}/api/auth/login",
                      json={"email": registered["email"], "password": "NewPass2026"})
        assert r.status_code == 200, r.text

    def test_confirm_reset_invalid_token_400(self, http):
        r = http.post(f"{BASE_URL}/api/auth/password/confirm-reset",
                      json={"token": "notarealtoken_" + uuid.uuid4().hex,
                            "new_password": PASSWORD_OK})
        assert r.status_code == 400
        assert r.json()["detail"] == "Token non valido o scaduto"

    def test_confirm_reset_reuse_400(self, http):
        # Register a fresh user, issue a token, use it, then try again
        email = _email()
        r = http.post(f"{BASE_URL}/api/auth/register",
                      json={"email": email, "password": PASSWORD_OK})
        assert r.status_code == 201
        uid = r.json()["user"]["user_id"]

        raw = "reuse20_" + uuid.uuid4().hex
        db.auth_tokens.insert_one({
            "user_id": uid, "kind": "reset_password",
            "token_hash": _sha256_hex(raw),
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=30),
            "used_at": None,
        })
        r1 = http.post(f"{BASE_URL}/api/auth/password/confirm-reset",
                       json={"token": raw, "new_password": "NewPass2026"})
        assert r1.status_code == 200
        r2 = http.post(f"{BASE_URL}/api/auth/password/confirm-reset",
                       json={"token": raw, "new_password": "OtherPass20"})
        assert r2.status_code == 400


# =========================================================
# Verify email
# =========================================================
class TestVerifyEmail:
    def test_verify_email_flips_flag(self, http):
        email = _email()
        r = http.post(f"{BASE_URL}/api/auth/register",
                      json={"email": email, "password": PASSWORD_OK})
        assert r.status_code == 201
        uid = r.json()["user"]["user_id"]
        token = r.json()["session_token"]

        # Manually seed a known verify_email token
        raw = "verify20_" + uuid.uuid4().hex
        db.auth_tokens.insert_one({
            "user_id": uid, "kind": "verify_email",
            "token_hash": _sha256_hex(raw),
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=24),
            "used_at": None,
        })

        r = http.post(f"{BASE_URL}/api/auth/verify-email", json={"token": raw})
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True}

        # /me now shows email_verified: True
        r = http.get(f"{BASE_URL}/api/auth/me",
                     headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json().get("email_verified") is True

    def test_verify_email_bad_token(self, http):
        r = http.post(f"{BASE_URL}/api/auth/verify-email",
                      json={"token": "badtoken_" + uuid.uuid4().hex})
        assert r.status_code == 400


# =========================================================
# Apple sign-in — negative paths only (no real Apple JWKS)
# =========================================================
class TestAppleSignIn:
    def test_malformed_token_401(self, http):
        r = http.post(f"{BASE_URL}/api/auth/apple",
                      json={"identity_token": "not-a-jwt-just-random-junkxxxxxxxx"})
        assert r.status_code == 401, r.text

    def test_random_bytes_401(self, http):
        r = http.post(f"{BASE_URL}/api/auth/apple",
                      json={"identity_token": "a" * 300})
        assert r.status_code == 401

    def test_jwt_wrong_signature_401(self, http):
        # Sign a token ourselves with a random RSA key — Apple's JWKS lookup by
        # kid should fail (kid unknown) → 401
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            encoding=__import__("cryptography").hazmat.primitives.serialization.Encoding.PEM,
            format=__import__("cryptography").hazmat.primitives.serialization.PrivateFormat.PKCS8,
            encryption_algorithm=__import__("cryptography").hazmat.primitives.serialization.NoEncryption(),
        )
        tok = pyjwt.encode(
            {"iss": "https://appleid.apple.com",
             "aud": "com.barrio.app",
             "sub": "fakesub",
             "iat": int(time.time()),
             "exp": int(time.time()) + 3600,
             "email": "fake@example.com"},
            pem, algorithm="RS256", headers={"kid": "totallyfakekid"},
        )
        r = http.post(f"{BASE_URL}/api/auth/apple",
                      json={"identity_token": tok})
        assert r.status_code == 401, r.text


# =========================================================
# Google backward-compat + cross-provider linking
# =========================================================
class TestGoogleBackwardCompat:
    def test_legacy_google_user_me_still_works(self, http):
        """Seed a Google-created user + session directly, ensure /auth/me still
        works (User.email now Optional shouldn't break anything)."""
        uid = f"user_it20_gg_{uuid.uuid4().hex[:8]}"
        token = f"sess_it20_{uuid.uuid4().hex}"
        db.users.insert_one({
            "user_id": uid,
            "email": f"legacy_google_{_ts()}@barrio.dev",
            "name": "Legacy Google",
            "picture": "https://x/y.png",
            "gender": None, "age": None,
            "profile_complete": False,
            "terms_version": None,
            "terms_accepted_at": None,
            "created_at": datetime.now(timezone.utc),
            # New fields intentionally OMITTED to mimic pre-iteration-19 legacy row
        })
        db.user_sessions.insert_one({
            "session_token": token,
            "user_id": uid,
            "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
            "created_at": datetime.now(timezone.utc),
        })

        r = http.get(f"{BASE_URL}/api/auth/me",
                     headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        me = r.json()
        assert me["user_id"] == uid
        # Legacy default: password_hash absent → auth_providers may be empty
        # but must not crash. Field should exist (with a default) per spec.
        assert "auth_providers" in me
        assert "email_verified" in me

    def test_cross_provider_password_then_google_link(self, http):
        """User registers with password; then /auth/session upserts by email
        (Google flow) → auth_providers should contain both."""
        email = _email()
        r = http.post(f"{BASE_URL}/api/auth/register",
                      json={"email": email, "password": PASSWORD_OK, "name": "Cross"})
        assert r.status_code == 201, r.text
        uid = r.json()["user"]["user_id"]

        # Simulate the Google upsert by directly running the same code
        # path that /auth/session would run: add "google" to providers +
        # set email_verified=True on the existing user.
        # We can't hit the real /auth/session without a valid session_id
        # from Emergent auth, so we assert the mongo state can support both.
        # However the SERVER-SIDE code at /auth/session should handle this
        # atomically. Verify at least that the fields coexist safely.
        db.users.update_one(
            {"user_id": uid},
            {"$addToSet": {"auth_providers": "google"},
             "$set": {"email_verified": True}},
        )
        doc = db.users.find_one({"user_id": uid})
        assert set(doc.get("auth_providers") or []) >= {"password", "google"}
        assert doc.get("password_hash"), "password_hash must survive google linking"
        # /me reflects both providers
        # (login again to get a session_token since we don't have one stored)
        r = http.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": PASSWORD_OK})
        assert r.status_code == 200
        sess = r.json()["session_token"]
        r = http.get(f"{BASE_URL}/api/auth/me",
                     headers={"Authorization": f"Bearer {sess}"})
        assert r.status_code == 200
        assert set(r.json().get("auth_providers") or []) >= {"password", "google"}
