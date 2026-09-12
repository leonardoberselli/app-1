"""E2E live verification of the Email/Password auth flow.

Simulates the full journey:
  register -> (inject verify token) -> verify-email -> login ->
  request-password-reset -> (inject reset token) -> confirm-reset ->
  login with NEW password -> confirm old session invalidated

Because verification/reset raw tokens are only delivered via email (only the
sha256 lives in the DB), we inject known tokens directly into
`auth_tokens` — this is the officially documented test-mode escape hatch
described in /app/memory/test_credentials.md.

Usage:
    python /app/backend/tests/e2e_email_password_flow.py

Exits with non-zero if any step fails.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

# Backend runs on 127.0.0.1:8001 inside the container; /api is the ingress prefix.
BASE_URL = os.environ.get("BARRIO_TEST_BASE", "http://127.0.0.1:8001/api")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


# ---------- pretty printing ------------------------------------------------
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def step(n: int, title: str) -> None:
    print(f"\n{BOLD}{CYAN}── Step {n}: {title}{RESET}")


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")
    sys.exit(1)


def info(msg: str) -> None:
    print(f"  {YELLOW}·{RESET} {msg}")


# ---------- helpers --------------------------------------------------------
def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def inject_token(db, user_id: str, kind: str, ttl: timedelta) -> str:
    """Insert a fresh auth token for `user_id` and return its RAW value."""
    raw = uuid.uuid4().hex + uuid.uuid4().hex  # 64 chars, matches server format
    await db.auth_tokens.insert_one(
        {
            "user_id": user_id,
            "kind": kind,
            "token_hash": sha256_hex(raw),
            "created_at": now_utc(),
            "expires_at": now_utc() + ttl,
            "used_at": None,
        }
    )
    return raw


async def main() -> None:
    # Unique email so re-runs don't collide with rate limits or existing rows.
    unique = uuid.uuid4().hex[:10]
    email = f"e2e_{unique}@barriotest.example.com"
    password_v1 = "Correct-Horse-1"
    password_v2 = "Battery-Staple-2"

    mongo = AsyncIOMotorClient(MONGO_URL)
    db = mongo[DB_NAME]

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as api:
        # ------------------------------------------------------------------
        step(1, "POST /auth/register creates the user + issues a session")
        r = await api.post(
            "/auth/register",
            json={"email": email, "password": password_v1, "name": "E2E Rider"},
        )
        if r.status_code != 201:
            fail(f"expected 201, got {r.status_code}: {r.text}")
        body = r.json()
        assert body.get("email_verification_sent") is True, body
        first_session = body["session_token"]
        user_id = body["user"]["user_id"]
        assert body["user"]["email"] == email
        assert body["user"]["email_verified"] is False
        ok(f"user_id={user_id}  session={first_session[:12]}…  email_verified=False")

        # ------------------------------------------------------------------
        step(2, "POST /auth/register with the SAME email must 409")
        r = await api.post(
            "/auth/register",
            json={"email": email, "password": password_v1, "name": "duplicate"},
        )
        if r.status_code != 409:
            fail(f"expected 409, got {r.status_code}: {r.text}")
        assert "già registrato" in r.json().get("detail", "").lower()
        ok("duplicate registration correctly rejected with 409")

        # ------------------------------------------------------------------
        step(3, "POST /auth/register with weak password must 422")
        r = await api.post(
            "/auth/register",
            json={"email": f"weak_{unique}@x.io", "password": "onlyletters"},
        )
        if r.status_code != 422:
            fail(f"expected 422, got {r.status_code}: {r.text}")
        ok("weak password rejected by RegisterIn validator")

        # ------------------------------------------------------------------
        step(4, "Inject verify-email token in DB (raw token only lives in email)")
        verify_raw = await inject_token(db, user_id, "verify_email", timedelta(hours=1))
        info(f"raw token = {verify_raw[:10]}…{verify_raw[-6:]}  (len={len(verify_raw)})")
        ok("token inserted in auth_tokens")

        # ------------------------------------------------------------------
        step(5, "POST /auth/verify-email flips email_verified to True")
        r = await api.post("/auth/verify-email", json={"token": verify_raw})
        if r.status_code != 200 or r.json().get("ok") is not True:
            fail(f"verify-email failed: {r.status_code} {r.text}")
        ok("verify-email 200 OK")

        # Re-using the same token must fail (single-use enforcement).
        r = await api.post("/auth/verify-email", json={"token": verify_raw})
        if r.status_code != 400:
            fail(f"reusing token expected 400, got {r.status_code}")
        ok("second use of the same token correctly rejected (single-use)")

        # Confirm DB state
        u = await db.users.find_one({"user_id": user_id}, {"_id": 0})
        if not u or u.get("email_verified") is not True:
            fail(f"users.email_verified not True: {u!r}")
        ok("users.email_verified = True in MongoDB")

        # ------------------------------------------------------------------
        step(6, "POST /auth/login with correct password returns a session")
        r = await api.post(
            "/auth/login", json={"email": email, "password": password_v1}
        )
        if r.status_code != 200:
            fail(f"login failed: {r.status_code} {r.text}")
        second_session = r.json()["session_token"]
        assert r.json()["user"]["email_verified"] is True
        ok(f"login OK  session={second_session[:12]}…")

        # ------------------------------------------------------------------
        step(7, "POST /auth/login with WRONG password returns 401")
        r = await api.post(
            "/auth/login", json={"email": email, "password": "wrong-Password-9"}
        )
        if r.status_code != 401:
            fail(f"expected 401, got {r.status_code}: {r.text}")
        assert "non corretti" in r.json().get("detail", "").lower()
        ok("wrong password → 401 with generic error (no enumeration leak)")

        # ------------------------------------------------------------------
        step(8, "POST /auth/password/request-reset returns generic message")
        r = await api.post(
            "/auth/password/request-reset", json={"email": email}
        )
        if r.status_code != 200:
            fail(f"request-reset failed: {r.status_code} {r.text}")
        ok(f"200 OK · {r.json().get('message')!r}")

        # Same generic response even for unknown emails
        r = await api.post(
            "/auth/password/request-reset",
            json={"email": f"unknown_{unique}@barriotest.example.com"},
        )
        if r.status_code != 200:
            fail(f"request-reset unknown email failed: {r.status_code}")
        ok("unknown email → same 200 (no user-enumeration)")

        # ------------------------------------------------------------------
        step(9, "Inject reset-password token in DB")
        reset_raw = await inject_token(
            db, user_id, "reset_password", timedelta(minutes=15)
        )
        info(f"raw token = {reset_raw[:10]}…{reset_raw[-6:]}")
        ok("token inserted")

        # ------------------------------------------------------------------
        step(10, "POST /auth/password/confirm-reset with new password")
        r = await api.post(
            "/auth/password/confirm-reset",
            json={"token": reset_raw, "new_password": password_v2},
        )
        if r.status_code != 200 or r.json().get("ok") is not True:
            fail(f"confirm-reset failed: {r.status_code} {r.text}")
        ok("confirm-reset 200 OK")

        # ------------------------------------------------------------------
        step(11, "OLD session tokens are invalidated after password reset")
        sessions_left = await db.user_sessions.count_documents({"user_id": user_id})
        if sessions_left != 0:
            fail(f"expected 0 sessions after reset, got {sessions_left}")
        ok(f"user_sessions for {user_id} = 0 (all pre-reset tokens revoked)")

        # Verify by hitting a protected endpoint with the old session
        r = await api.get(
            "/auth/me", headers={"Authorization": f"Bearer {second_session}"}
        )
        if r.status_code not in (401, 403, 404):
            fail(f"expected 401/403/404 with old session, got {r.status_code}: {r.text}")
        ok(f"GET /auth/me with old session → {r.status_code} (revoked, as expected)")

        # ------------------------------------------------------------------
        step(12, "Login with the OLD password must now fail (401)")
        r = await api.post(
            "/auth/login", json={"email": email, "password": password_v1}
        )
        if r.status_code != 401:
            fail(f"expected 401 for old password, got {r.status_code}: {r.text}")
        ok("old password → 401 (correctly rotated)")

        # ------------------------------------------------------------------
        step(13, "Login with the NEW password succeeds")
        r = await api.post(
            "/auth/login", json={"email": email, "password": password_v2}
        )
        if r.status_code != 200:
            fail(f"expected 200 with new password, got {r.status_code}: {r.text}")
        third_session = r.json()["session_token"]
        ok(f"new password login OK  session={third_session[:12]}…")

        # ------------------------------------------------------------------
        step(14, "Second use of the reset token must fail (single-use)")
        r = await api.post(
            "/auth/password/confirm-reset",
            json={"token": reset_raw, "new_password": "AnotherPass-9"},
        )
        if r.status_code != 400:
            fail(f"expected 400 for reused reset token, got {r.status_code}")
        ok("second use of reset token → 400 (single-use enforced)")

        # ------------------------------------------------------------------
        # Cleanup — remove the test user + their sessions/tokens so repeated
        # runs stay isolated.
        step(15, "Cleanup (remove test user + tokens + sessions)")
        await db.users.delete_one({"user_id": user_id})
        await db.user_sessions.delete_many({"user_id": user_id})
        await db.auth_tokens.delete_many({"user_id": user_id})
        # also drop the "weak" user if it slipped through
        await db.users.delete_one({"email": f"weak_{unique}@x.io"})
        ok("test artifacts removed")

    print(f"\n{BOLD}{GREEN}ALL 15 STEPS PASSED — Email/Password flow is production-ready.{RESET}\n")


if __name__ == "__main__":
    t0 = time.time()
    try:
        asyncio.run(main())
    except AssertionError as e:
        print(f"{RED}ASSERTION FAILED:{RESET} {e}")
        sys.exit(1)
    print(f"[{time.time() - t0:.2f}s total]")
