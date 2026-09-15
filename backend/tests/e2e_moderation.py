"""E2E test for the new moderation features:
  1. Group owner kicks a participant (participant is banned, cannot re-join,
     their messages are wiped from the group).
  2. Admin suspends a user (temporary + permanent), and the user cannot log
     in or use their existing session until the suspension is lifted.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

BASE = os.environ.get("BARRIO_TEST_BASE", "http://127.0.0.1:8001/api")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
ADMIN_SECRET = os.environ.get("BARRIO_ADMIN_SECRET", "BaNaN@381")

GREEN, RED, CYAN, BOLD, RESET = "\033[92m", "\033[91m", "\033[96m", "\033[1m", "\033[0m"


def step(n, t):
    print(f"\n{BOLD}{CYAN}── Step {n}: {t}{RESET}")


def ok(m):
    print(f"  {GREEN}✓{RESET} {m}")


def fail(m):
    print(f"  {RED}✗{RESET} {m}")
    sys.exit(1)


async def register_and_login(api, email, password, name):
    r = await api.post(
        "/auth/register", json={"email": email, "password": password, "name": name}
    )
    if r.status_code != 201:
        fail(f"register {email} failed: {r.status_code} {r.text}")
    return r.json()  # {session_token, user}


async def main():
    unique = uuid.uuid4().hex[:8]
    owner_email = f"owner_{unique}@barriotest.example.com"
    mem_email = f"mem_{unique}@barriotest.example.com"
    admin_email = f"adm_{unique}@barriotest.example.com"

    mongo = AsyncIOMotorClient(MONGO_URL)
    db = mongo[DB_NAME]

    async with httpx.AsyncClient(base_url=BASE, timeout=15.0) as api:
        # -------- Part A: kick from group ---------------------------------
        step(1, "Register owner + one member")
        owner = await register_and_login(api, owner_email, "Owner-Pass-1", "Owner")
        mem = await register_and_login(api, mem_email, "Mem-Pass-1", "Mem")
        # Complete onboarding fields directly in DB.
        for uid in (owner["user"]["user_id"], mem["user"]["user_id"]):
            await db.users.update_one(
                {"user_id": uid},
                {"$set": {"age": 30, "email_verified": True, "terms_version": "2026-06-01",
                          "terms_accepted_at": datetime.now(timezone.utc)}},
            )
        ok(f"owner={owner['user']['user_id']}  mem={mem['user']['user_id']}")

        step(2, "Owner creates a group; member joins")
        r = await api.post(
            "/groups",
            headers={"Authorization": f"Bearer {owner['session_token']}"},
            json={
                "title": "Kick test",
                "category": "altro",
                "category_label": "Altro",
                "city": "Milano",
                "location": "Piazza Duomo, Milano",
                "date": "2027-01-15",
                "time": "20:00",
                "max_participants": 5,
                "min_participants": 3,
                "min_age": 18,
                "max_age": 60,
                "description": "",
            },
        )
        if r.status_code != 200:
            fail(f"group create: {r.status_code} {r.text}")
        gid = r.json()["group_id"]
        r = await api.post(
            f"/groups/{gid}/join",
            headers={"Authorization": f"Bearer {mem['session_token']}"},
        )
        if r.status_code != 200:
            fail(f"member join: {r.status_code} {r.text}")
        assert any(p["user_id"] == mem["user"]["user_id"] for p in r.json()["participants"])
        ok(f"group={gid} · member joined")

        step(3, "Member posts a chat message")
        r = await api.post(
            f"/groups/{gid}/messages",
            headers={"Authorization": f"Bearer {mem['session_token']}"},
            json={"text": "ciao a tutti"},
        )
        if r.status_code != 200:
            fail(f"post msg: {r.status_code} {r.text}")
        ok("member message posted")

        step(4, "Non-owner cannot kick (403)")
        r = await api.post(
            f"/groups/{gid}/kick",
            headers={"Authorization": f"Bearer {mem['session_token']}"},
            json={"user_id": mem["user"]["user_id"]},
        )
        if r.status_code != 403:
            fail(f"expected 403, got {r.status_code} {r.text}")
        ok("403 as expected (only owner can kick)")

        step(5, "Owner cannot kick themselves (400)")
        r = await api.post(
            f"/groups/{gid}/kick",
            headers={"Authorization": f"Bearer {owner['session_token']}"},
            json={"user_id": owner["user"]["user_id"]},
        )
        if r.status_code != 400:
            fail(f"expected 400, got {r.status_code}")
        ok("owner self-kick correctly rejected")

        step(6, "Owner kicks member with a reason")
        r = await api.post(
            f"/groups/{gid}/kick",
            headers={"Authorization": f"Bearer {owner['session_token']}"},
            json={"user_id": mem["user"]["user_id"], "reason": "bullismo in chat"},
        )
        if r.status_code != 200:
            fail(f"kick: {r.status_code} {r.text}")
        body = r.json()
        assert not any(p["user_id"] == mem["user"]["user_id"] for p in body["participants"])
        assert mem["user"]["user_id"] in (body.get("banned_user_ids") or [])
        ok("member removed + added to banned_user_ids")

        # Verify member's messages were purged from this group
        cnt = await db.messages.count_documents(
            {"group_id": gid, "user_id": mem["user"]["user_id"]}
        )
        if cnt != 0:
            fail(f"messages not purged: {cnt} left")
        ok("member's chat messages purged from this group")

        # System message announced the kick
        sys_msgs = await db.messages.count_documents(
            {"group_id": gid, "user_id": "system__"}
        )
        if sys_msgs < 1:
            fail("no system announcement message")
        ok("system announcement inserted in chat")

        step(7, "Kicked member cannot re-join (403)")
        r = await api.post(
            f"/groups/{gid}/join",
            headers={"Authorization": f"Bearer {mem['session_token']}"},
        )
        if r.status_code != 403:
            fail(f"expected 403 for kicked user rejoin, got {r.status_code}")
        ok("re-join blocked as expected")

        # -------- Part B: admin suspend user ------------------------------
        step(8, "Register a fresh user to suspend")
        target = await register_and_login(api, admin_email, "Target-Pass-1", "Target")
        target_id = target["user"]["user_id"]
        await db.users.update_one(
            {"user_id": target_id},
            {"$set": {"age": 30, "email_verified": True, "terms_version": "2026-06-01",
                      "terms_accepted_at": datetime.now(timezone.utc)}},
        )

        step(9, "Admin suspends target for 3 days")
        r = await api.post(
            f"/admin/users/{target_id}/suspend",
            headers={"X-Admin-Secret": ADMIN_SECRET},
            json={"days": 3, "reason": "molestie ripetute"},
        )
        if r.status_code != 200:
            fail(f"admin suspend: {r.status_code} {r.text}")
        sus = r.json()["suspension"]
        assert sus["until"] is not None
        ok(f"suspended until {sus['until']} · reason={sus['reason']!r}")

        step(10, "Existing session of suspended user returns 403")
        r = await api.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {target['session_token']}"},
        )
        if r.status_code != 403:
            fail(f"expected 403 for suspended session, got {r.status_code}")
        det = r.json().get("detail") or {}
        assert det.get("suspended") is True and det.get("until"), det
        ok(f"/auth/me → 403 · detail.suspended=True · message={det.get('message')!r}")

        # Sessions purged
        left = await db.user_sessions.count_documents({"user_id": target_id})
        if left != 0:
            fail(f"sessions not purged: {left}")
        ok("all sessions revoked server-side")

        step(11, "Login attempt with correct password → 403 (not 401)")
        r = await api.post(
            "/auth/login",
            json={"email": admin_email, "password": "Target-Pass-1"},
        )
        if r.status_code != 403:
            fail(f"expected 403 during login of suspended user, got {r.status_code}")
        assert (r.json().get("detail") or {}).get("suspended") is True
        ok("login blocked with structured suspension detail")

        step(12, "Admin unsuspends → user can log in again")
        r = await api.post(
            f"/admin/users/{target_id}/unsuspend",
            headers={"X-Admin-Secret": ADMIN_SECRET},
        )
        if r.status_code != 200:
            fail(f"unsuspend: {r.status_code} {r.text}")
        r = await api.post(
            "/auth/login",
            json={"email": admin_email, "password": "Target-Pass-1"},
        )
        if r.status_code != 200:
            fail(f"login after unsuspend: {r.status_code} {r.text}")
        ok("login OK after unsuspend")

        step(13, "Permanent ban: days=None")
        r = await api.post(
            f"/admin/users/{target_id}/suspend",
            headers={"X-Admin-Secret": ADMIN_SECRET},
            json={"days": None, "reason": "recidivo"},
        )
        if r.status_code != 200:
            fail(f"permanent suspend: {r.status_code} {r.text}")
        assert r.json()["suspension"]["until"] is None
        ok("permanent suspension recorded (until=null)")

        r = await api.post(
            "/auth/login",
            json={"email": admin_email, "password": "Target-Pass-1"},
        )
        det = (r.json() or {}).get("detail") or {}
        if r.status_code != 403 or det.get("until") is not None:
            fail(f"expected 403 with until=null, got {r.status_code} {r.text}")
        ok("login still blocked with permanent ban message")

        step(14, "adminGetUser returns full suspension record")
        r = await api.get(
            f"/admin/users/{target_id}",
            headers={"X-Admin-Secret": ADMIN_SECRET},
        )
        if r.status_code != 200:
            fail(f"admin_get_user: {r.status_code} {r.text}")
        j = r.json()
        assert j["suspension_active"] is True
        assert j["suspension"]["until"] is None
        assert "recidivo" in (j["suspension"]["reason"] or "")
        ok("admin_get_user reports active permanent ban")

        # -------- Cleanup -------------------------------------------------
        step(15, "Cleanup test users + group")
        for e in (owner_email, mem_email, admin_email):
            u = await db.users.find_one({"email": e})
            if u:
                uid = u["user_id"]
                await db.users.delete_one({"user_id": uid})
                await db.user_sessions.delete_many({"user_id": uid})
                await db.auth_tokens.delete_many({"user_id": uid})
        await db.groups.delete_one({"group_id": gid})
        await db.messages.delete_many({"group_id": gid})
        ok("cleaned")

    print(f"\n{BOLD}{GREEN}ALL 15 STEPS PASSED — kick + suspend flows work.{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
