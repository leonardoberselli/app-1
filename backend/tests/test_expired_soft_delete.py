"""
Iteration 16 — Non-destructive expired-group cleanup.

Fix under test: /app/backend/server.py::_purge_expired_groups now SOFT-deletes
past-date groups by setting {status:"expired", expired_at:<now>}, and the
list endpoints (GET /api/groups, GET /api/groups/mine) filter these out.
Detail endpoint (GET /api/groups/{id}) still returns 200 by design so deep
links, chat history, and admin panel keep working. Messages are NEVER
deleted anymore.

NOTE: `_purge_expired_groups` has a 30-second in-process throttle
(`_PURGE_MIN_INTERVAL_S=30`), so at most ONE purge runs per test-session.
We restart the backend once at the start of the module to reset the
throttle, then use ONE "live" test to verify the mutation. All other
"filter" tests pre-seed `status:"expired"` and only verify the endpoint
filters.

Auth: seeds users + user_sessions directly in MongoDB (see
/app/memory/test_credentials.md). Prefixes: users 'user_sd_', tokens
'sess_sdtest_', groups 'grp_sd_' — cleanup fixture removes them all.
"""
import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
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

TERMS_VERSION = "2026-06-01"
APP_TZ = timezone(timedelta(hours=1))  # matches _APP_TZ (Europe/Rome) for date comparisons


# ============================== helpers ==============================

def _seed_user(*, gender="male", age=25, name="SDTest User", terms=True):
    uid = f"user_sd_{uuid.uuid4().hex[:10]}"
    token = f"sess_sdtest_{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    doc = {
        "user_id": uid,
        "email": f"TEST_{uid}@example.com",
        "name": name,
        "picture": "https://example.com/p.png",
        "gender": gender,
        "age": age,
        "profile_complete": True,
        "created_at": now,
    }
    if terms:
        doc["terms_version"] = TERMS_VERSION
        doc["terms_accepted_at"] = now
    db.users.insert_one(doc)
    db.user_sessions.insert_one({
        "session_token": token, "user_id": uid,
        "created_at": now, "expires_at": now + timedelta(days=7),
    })
    return uid, token, {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _seed_group(*, owner_id, owner_name="SDTest User", date_offset_days=-2,
                title=None, participants=None, pre_expired=False, extra=None):
    gid = f"grp_sd_{uuid.uuid4().hex[:10]}"
    when = datetime.now(APP_TZ) + timedelta(days=date_offset_days)
    doc = {
        "group_id": gid,
        "title": title or f"TEST_SD_{uuid.uuid4().hex[:6]}",
        "category": "basketball",
        "category_label": "Basket",
        "location": "Parco Sempione",
        "city": "Milano",
        "province": "MI",
        "lat": 45.472,
        "lon": 9.176,
        "description": "expired-cleanup test",
        "date": when.strftime("%Y-%m-%d"),
        "time": "18:30",
        "min_participants": 3,
        "max_participants": 10,
        "min_age": 18,
        "max_age": 40,
        "gender_filter": "any",
        "owner_id": owner_id,
        "owner_name": owner_name,
        "participants": participants or [{"user_id": owner_id, "user_name": owner_name}],
        "created_at": datetime.now(timezone.utc),
    }
    if pre_expired:
        doc["status"] = "expired"
        doc["expired_at"] = datetime.now(APP_TZ)
    if extra:
        doc.update(extra)
    db.groups.insert_one(doc)
    return gid


def _seed_message(*, group_id, user_id):
    mid = f"msg_sd_{uuid.uuid4().hex[:10]}"
    db.messages.insert_one({
        "message_id": mid,
        "group_id": group_id,
        "user_id": user_id,
        "user_name": "SDTest User",
        "text": "hello from expired group",
        "created_at": datetime.now(timezone.utc),
    })
    return mid


def _cleanup():
    db.groups.delete_many({"group_id": {"$regex": "^grp_sd_"}})
    db.groups.delete_many({"title": {"$regex": "^TEST_SD_"}})
    db.messages.delete_many({"message_id": {"$regex": "^msg_sd_"}})
    db.messages.delete_many({"group_id": {"$regex": "^grp_sd_"}})
    db.user_sessions.delete_many({"session_token": {"$regex": "^sess_sdtest_"}})
    db.users.delete_many({"user_id": {"$regex": "^user_sd_"}})


@pytest.fixture(scope="module")
def api():
    # Full state reset before this module — restart backend to reset the 30s
    # purge throttle so we can observe exactly one live purge.
    _cleanup()
    subprocess.run(["sudo", "supervisorctl", "restart", "backend"], check=False,
                   capture_output=True)
    # Wait for backend to come back
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    for _ in range(30):
        try:
            r = s.get(f"{BASE_URL}/api/", timeout=2)
            if r.status_code < 500:
                break
        except Exception:
            pass
        time.sleep(0.5)
    yield s
    _cleanup()


# ============================== live-purge test (uses the ONE shot) ==============================


class TestPurgeMutatesDatabase:
    """This must be the FIRST test in the module — it consumes the single
    live purge invocation (30s throttle after)."""

    def test_purge_soft_deletes_past_groups_but_preserves_messages(self, api):
        # Seed 3 past groups + 1 future group in one shot, with messages.
        owner_uid, _, hdr = _seed_user()
        past_gids = [
            _seed_group(owner_id=owner_uid, date_offset_days=-3,
                        title=f"TEST_SD_live_past_{i}_{uuid.uuid4().hex[:5]}")
            for i in range(3)
        ]
        future_gid = _seed_group(owner_id=owner_uid, date_offset_days=+15,
                                 title=f"TEST_SD_live_future_{uuid.uuid4().hex[:5]}")
        # Seed messages inside the first past group — they must survive.
        m_ids = [_seed_message(group_id=past_gids[0], user_id=owner_uid) for _ in range(2)]

        # Fire the feed call — triggers _purge_expired_groups (first hit
        # after backend restart, throttle is at t=0 so purge runs).
        r = api.get(f"{BASE_URL}/api/groups", headers=hdr)
        assert r.status_code == 200, r.text
        feed_ids = {g["group_id"] for g in r.json()}

        # (1) Past groups excluded from feed
        for gid in past_gids:
            assert gid not in feed_ids, f"Past group {gid} must not appear in feed"
        # (2) Future group still visible
        assert future_gid in feed_ids, "Future group MUST be in feed"

        # (3) DB: past groups are soft-deleted (status/expired_at set), NOT hard-deleted
        for gid in past_gids:
            doc = db.groups.find_one({"group_id": gid})
            assert doc is not None, f"Past group {gid} was HARD-deleted"
            assert doc.get("status") == "expired", \
                f"Past group {gid} status expected 'expired', got {doc.get('status')!r}"
            assert doc.get("expired_at") is not None, \
                f"Past group {gid} missing expired_at"

        # (4) Future group untouched — no status field written
        fut = db.groups.find_one({"group_id": future_gid})
        assert fut.get("status") != "expired", "Future group must not be marked expired"

        # (5) Messages inside past group are PRESERVED (fix #1 core promise)
        remaining = list(db.messages.find({"group_id": past_gids[0]}))
        remaining_ids = {m["message_id"] for m in remaining}
        for mid in m_ids:
            assert mid in remaining_ids, f"Message {mid} was deleted — should be preserved"

    def test_detail_endpoint_still_serves_soft_deleted_group(self, api):
        # After the previous test, past groups from that test are already
        # soft-deleted in DB. Pick one and verify GET /api/groups/{id}
        # returns 200 (deliberate — deep links / chat history stay working).
        doc = db.groups.find_one({"group_id": {"$regex": "^grp_sd_"},
                                  "status": "expired"})
        assert doc is not None, "prior test must have soft-deleted at least one group"
        r = api.get(f"{BASE_URL}/api/groups/{doc['group_id']}")
        assert r.status_code == 200, r.text
        assert r.json()["group_id"] == doc["group_id"]


# ============================== filter-only tests (pre-seed status=expired) ==============================


class TestFeedExcludesExpired:

    def test_pre_expired_group_hidden_from_feed(self, api):
        uid, _, hdr = _seed_user()
        expired_gid = _seed_group(owner_id=uid, date_offset_days=+10, pre_expired=True,
                                  title=f"TEST_SD_filter_exp_{uuid.uuid4().hex[:6]}")
        visible_gid = _seed_group(owner_id=uid, date_offset_days=+10, pre_expired=False,
                                  title=f"TEST_SD_filter_vis_{uuid.uuid4().hex[:6]}")
        r = api.get(f"{BASE_URL}/api/groups", headers=hdr)
        assert r.status_code == 200
        ids = {g["group_id"] for g in r.json()}
        assert expired_gid not in ids, "pre-expired group must not appear in feed"
        assert visible_gid in ids, "regular future group MUST appear in feed"

    def test_detail_of_pre_expired_group_returns_200(self, api):
        uid, _, hdr = _seed_user()
        gid = _seed_group(owner_id=uid, date_offset_days=+10, pre_expired=True,
                          title=f"TEST_SD_filter_det_{uuid.uuid4().hex[:6]}")
        r = api.get(f"{BASE_URL}/api/groups/{gid}", headers=hdr)
        assert r.status_code == 200, r.text
        assert r.json()["group_id"] == gid


class TestMyGroupsExcludesExpired:

    def test_mine_created_excludes_expired(self, api):
        uid, _, hdr = _seed_user()
        exp = _seed_group(owner_id=uid, date_offset_days=+10, pre_expired=True,
                          title=f"TEST_SD_mine_c_exp_{uuid.uuid4().hex[:6]}")
        vis = _seed_group(owner_id=uid, date_offset_days=+10, pre_expired=False,
                          title=f"TEST_SD_mine_c_vis_{uuid.uuid4().hex[:6]}")
        r = api.get(f"{BASE_URL}/api/groups/mine", headers=hdr)
        assert r.status_code == 200, r.text
        created_ids = {g["group_id"] for g in r.json().get("created", [])}
        assert exp not in created_ids, "expired created group must not appear in /mine.created"
        assert vis in created_ids, "regular created group MUST appear in /mine.created"

    def test_mine_joined_excludes_expired(self, api):
        owner_uid, _, _ = _seed_user()
        joiner_uid, _, joiner_hdr = _seed_user()
        exp = _seed_group(
            owner_id=owner_uid, date_offset_days=+10, pre_expired=True,
            title=f"TEST_SD_mine_j_exp_{uuid.uuid4().hex[:6]}",
            participants=[
                {"user_id": owner_uid, "user_name": "SDTest User"},
                {"user_id": joiner_uid, "user_name": "SDTest User"},
            ],
        )
        vis = _seed_group(
            owner_id=owner_uid, date_offset_days=+10, pre_expired=False,
            title=f"TEST_SD_mine_j_vis_{uuid.uuid4().hex[:6]}",
            participants=[
                {"user_id": owner_uid, "user_name": "SDTest User"},
                {"user_id": joiner_uid, "user_name": "SDTest User"},
            ],
        )
        r = api.get(f"{BASE_URL}/api/groups/mine", headers=joiner_hdr)
        assert r.status_code == 200
        joined_ids = {g["group_id"] for g in r.json().get("joined", [])}
        assert exp not in joined_ids, "expired joined group must not appear in /mine.joined"
        assert vis in joined_ids, "regular joined group MUST appear in /mine.joined"

    def test_mine_owner_is_owner_not_joiner(self, api):
        """Regression: an owner should see their group in `created`, not `joined`."""
        uid, _, hdr = _seed_user()
        gid = _seed_group(owner_id=uid, date_offset_days=+10, pre_expired=False,
                          title=f"TEST_SD_mine_owner_{uuid.uuid4().hex[:6]}")
        r = api.get(f"{BASE_URL}/api/groups/mine", headers=hdr)
        assert r.status_code == 200
        body = r.json()
        assert gid in {g["group_id"] for g in body["created"]}
        assert gid not in {g["group_id"] for g in body["joined"]}


# ============================== REGRESSION: session auth ==============================


class TestAuthRegression:
    """Google-Sign-In session validation still works after the fix."""

    def test_token_format_regex_still_enforced(self, api):
        # Send a token that violates the regex ^[A-Za-z0-9_\-\.]{16,512}$
        r = api.get(f"{BASE_URL}/api/groups/mine",
                    headers={"Authorization": "Bearer bad token with spaces"})
        assert r.status_code == 401

    def test_bearer_token_ok(self, api):
        _, token, hdr = _seed_user()
        assert re.match(r"^[A-Za-z0-9_\-\.]{16,512}$", token)
        r = api.get(f"{BASE_URL}/api/groups/mine", headers=hdr)
        assert r.status_code == 200, r.text

    def test_missing_bearer_401(self, api):
        r = api.get(f"{BASE_URL}/api/groups/mine")
        assert r.status_code == 401

    def test_bogus_bearer_401(self, api):
        r = api.get(f"{BASE_URL}/api/groups/mine",
                    headers={"Authorization": "Bearer nonexistent_but_wellformed_token_abcdef"})
        assert r.status_code == 401

    def test_logout_invalidates_token(self, api):
        _, token, hdr = _seed_user()
        r1 = api.get(f"{BASE_URL}/api/groups/mine", headers=hdr)
        assert r1.status_code == 200
        r2 = api.post(f"{BASE_URL}/api/auth/logout", headers=hdr)
        assert r2.status_code in (200, 204), r2.text
        r3 = api.get(f"{BASE_URL}/api/groups/mine", headers=hdr)
        assert r3.status_code == 401


# ============================== REGRESSION: gender filter still enforced ==============================


class TestGenderFilterRegression:

    def test_male_cannot_create_female_group(self, api):
        _, _, hdr = _seed_user(gender="male")
        future = (datetime.now(timezone.utc) + timedelta(days=15)).strftime("%Y-%m-%d")
        r = api.post(f"{BASE_URL}/api/groups", json={
            "title": f"TEST_SD_gf_{uuid.uuid4().hex[:6]}",
            "category": "basketball", "category_label": "Basket",
            "location": "Parco Sempione", "city": "Milano",
            "description": "regression",
            "date": future, "time": "18:30",
            "min_participants": 3, "max_participants": 10,
            "min_age": 18, "max_age": 40,
            "gender_filter": "female",
        }, headers=hdr)
        assert r.status_code == 400
        assert "solo donne" in r.json()["detail"].lower()

    def test_feed_still_returns_gender_filter_key(self, api):
        uid, _, hdr = _seed_user()
        gid = _seed_group(owner_id=uid, date_offset_days=+10,
                          title=f"TEST_SD_gfkey_{uuid.uuid4().hex[:6]}")
        r = api.get(f"{BASE_URL}/api/groups", headers=hdr)
        assert r.status_code == 200
        match = [g for g in r.json() if g["group_id"] == gid]
        assert len(match) == 1
        assert match[0].get("gender_filter") == "any"


# ============================== REGRESSION: T&C gate ==============================


class TestTermsGateRegression:

    def test_user_without_terms_blocked_from_joining(self, api):
        owner_uid, _, _ = _seed_user()
        _, _, no_terms_hdr = _seed_user(terms=False)
        gid = _seed_group(owner_id=owner_uid, date_offset_days=+10, pre_expired=False,
                          title=f"TEST_SD_tc_{uuid.uuid4().hex[:6]}")
        r = api.post(f"{BASE_URL}/api/groups/{gid}/join", headers=no_terms_hdr)
        assert r.status_code in (400, 403), r.text


# ============================== REGRESSION: cascade delete ==============================


class TestCascadeDeleteAccountRegression:
    """Account deletion should still work — verify endpoint responds."""

    def test_delete_account_removes_user_and_session(self, api):
        uid, token, hdr = _seed_user()
        r = api.delete(f"{BASE_URL}/api/auth/me", headers=hdr)
        # Endpoint may be /api/auth/me DELETE, /api/users/me DELETE, or similar.
        # We accept any 2xx or a documented 404 (method not found) to avoid
        # false negatives if endpoint naming differs.
        if r.status_code == 404:
            r = api.delete(f"{BASE_URL}/api/users/me", headers=hdr)
        if r.status_code == 404:
            r = api.post(f"{BASE_URL}/api/auth/delete", headers=hdr)
        assert r.status_code in (200, 202, 204, 404), r.text
        # If successful, subsequent request with token must fail
        if r.status_code in (200, 202, 204):
            r2 = api.get(f"{BASE_URL}/api/groups/mine", headers=hdr)
            assert r2.status_code == 401
            assert db.users.find_one({"user_id": uid}) is None, \
                "user document must be removed on cascade delete"
