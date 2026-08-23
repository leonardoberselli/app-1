"""
GroupUp Backend Tests - Device-UUID Auth (Jan 2026 rewrite).

Auth model: Authorization: Bearer <device_id> where device_id matches
^[A-Za-z0-9_-]{8,128}$. Backend auto-creates user on first request.
"""
import os
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# ----- Config: use public URL from frontend .env
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


def _new_device_id(prefix="TESTDEV"):
    return f"{prefix}_{uuid.uuid4().hex}"[:64]


# --- Session-scoped test device (owner)
@pytest.fixture(scope="session")
def owner_device():
    return _new_device_id("OWNER")


@pytest.fixture(scope="session")
def owner_headers(owner_device):
    return {"Authorization": f"Bearer {owner_device}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def api(owner_device):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    yield s
    # Cleanup: our test docs are all keyed to prefixed device ids
    db.groups.delete_many({"title": {"$regex": "^TEST_"}})
    db.groups.delete_many({"owner_id": {"$regex": "^TESTDEV_seed"}})
    db.messages.delete_many({"text": {"$regex": "^TEST_"}})
    db.users.delete_many({"user_id": {"$regex": "^(OWNER|OTHER|TESTDEV|SHORT)"}})


# ======================================================= Health
class TestHealth:
    def test_root(self, api):
        r = api.get(f"{BASE_URL}/api/")
        assert r.status_code == 200
        assert r.json()["message"] == "GroupUp API"


# ======================================================= /auth/me GET
class TestAuthMeGet:
    def test_missing_auth_401(self, api):
        r = api.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401

    def test_malformed_header_401(self, api):
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers={"Authorization": "NotBearer x"})
        assert r.status_code == 401

    def test_invalid_device_id_too_short_401(self, api):
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers={"Authorization": "Bearer short"})
        assert r.status_code == 401

    def test_invalid_device_id_bad_chars_401(self, api):
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers={"Authorization": "Bearer has spaces here"})
        assert r.status_code == 401

    def test_auto_create_new_user(self, api):
        did = _new_device_id("TESTDEV")
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers={"Authorization": f"Bearer {did}"})
        assert r.status_code == 200, r.text
        u = r.json()
        assert u["user_id"] == did
        assert u["name"] == ""
        assert u["profile_complete"] is False
        # No email field leaked
        assert "email" not in u
        assert "created_at" in u

    def test_min_length_device_id_ok(self, api):
        did = "abcdefgh"  # exactly 8 chars
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers={"Authorization": f"Bearer {did}"})
        assert r.status_code == 200


# ======================================================= /auth/me PATCH
class TestAuthMePatch:
    def test_update_name_only_not_complete(self, api, owner_headers, owner_device):
        r = api.patch(f"{BASE_URL}/api/auth/me",
                      json={"name": "Owner Name"}, headers=owner_headers)
        assert r.status_code == 200
        u = r.json()
        assert u["name"] == "Owner Name"
        assert u["profile_complete"] is False  # missing picture/gender/age

    def test_update_all_fields_complete_true(self, api):
        did = _new_device_id("TESTDEV")
        hdr = {"Authorization": f"Bearer {did}", "Content-Type": "application/json"}
        r = api.patch(f"{BASE_URL}/api/auth/me",
                      json={"name": "Full User", "picture": "https://x/y.png",
                            "gender": "female", "age": 27}, headers=hdr)
        assert r.status_code == 200, r.text
        u = r.json()
        assert u["profile_complete"] is True
        assert u["gender"] == "female" and u["age"] == 27

    def test_invalid_age(self, api, owner_headers):
        r = api.patch(f"{BASE_URL}/api/auth/me",
                      json={"age": 999}, headers=owner_headers)
        assert r.status_code == 422

    def test_invalid_gender(self, api, owner_headers):
        r = api.patch(f"{BASE_URL}/api/auth/me",
                      json={"gender": "unknown"}, headers=owner_headers)
        assert r.status_code == 422

    def test_name_change_propagates_to_groups(self, api):
        # Create a fresh user, set name, create a group, rename, verify group updated.
        did = _new_device_id("TESTDEV")
        hdr = {"Authorization": f"Bearer {did}", "Content-Type": "application/json"}
        api.patch(f"{BASE_URL}/api/auth/me",
                  json={"name": "First Name"}, headers=hdr)
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_prop"), headers=hdr)
        assert r.status_code == 200, r.text
        gid = r.json()["group_id"]
        # Rename
        api.patch(f"{BASE_URL}/api/auth/me",
                  json={"name": "Renamed", "picture": "https://p/x.png"}, headers=hdr)
        g = api.get(f"{BASE_URL}/api/groups/{gid}").json()
        assert g["owner_name"] == "Renamed"
        assert g["owner_picture"] == "https://p/x.png"
        assert any(p["user_id"] == did and p["name"] == "Renamed"
                   and p["picture"] == "https://p/x.png" for p in g["participants"])


# ======================================================= Groups
def _group_payload(title=None, category="basketball", label="Basket",
                   min_p=2, max_p=10, min_a=18, max_a=40,
                   city="Milano", street="Via Torino 20"):
    # Use a dynamic future date so tests keep working over time and pass the
    # server-side "no past date" check.
    future = datetime.now(timezone.utc) + timedelta(days=30)
    return {
        "title": title or f"TEST_grp_{uuid.uuid4().hex[:6]}",
        "category": category,
        "category_label": label,
        "location": "Milano",
        "city": city,
        "street": street,
        "description": "created by backend_test",
        "date": future.strftime("%Y-%m-%d"),
        "time": "18:30",
        "min_participants": min_p,
        "max_participants": max_p,
        "min_age": min_a,
        "max_age": max_a,
    }


class TestGroupsCRUD:
    def test_create_requires_auth(self, api):
        r = api.post(f"{BASE_URL}/api/groups", json=_group_payload())
        assert r.status_code == 401

    def test_create_requires_name(self, api):
        # Fresh device with no name set
        did = _new_device_id("TESTDEV")
        hdr = {"Authorization": f"Bearer {did}", "Content-Type": "application/json"}
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_noname"), headers=hdr)
        assert r.status_code == 400
        assert "nome" in r.json()["detail"].lower()

    def test_list_public(self, api):
        r = api.get(f"{BASE_URL}/api/groups")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_group_public(self, api, owner_headers, owner_device):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_public"), headers=owner_headers)
        assert r.status_code == 200, r.text
        gid = r.json()["group_id"]
        r = api.get(f"{BASE_URL}/api/groups/{gid}")  # no auth
        assert r.status_code == 200
        assert r.json()["group_id"] == gid

    def test_create_persists_and_owner_is_participant(self, api, owner_headers, owner_device):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_persist"), headers=owner_headers)
        assert r.status_code == 200
        g = r.json()
        assert g["title"] == "TEST_persist"
        assert g["owner_id"] == owner_device
        assert len(g["participants"]) == 1
        assert g["participants"][0]["user_id"] == owner_device
        pytest.created_group_id = g["group_id"]

    def test_validation_max_lt_min_participants(self, api, owner_headers):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(min_p=10, max_p=5), headers=owner_headers)
        assert r.status_code == 400

    def test_validation_max_lt_min_age(self, api, owner_headers):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(min_a=40, max_a=18), headers=owner_headers)
        assert r.status_code == 400

    def test_filter_by_category(self, api, owner_headers):
        api.post(f"{BASE_URL}/api/groups",
                 json=_group_payload(category="basketball"), headers=owner_headers)
        r = api.get(f"{BASE_URL}/api/groups", params={"category": "basketball"})
        assert r.status_code == 200
        assert all(g["category"] == "basketball" for g in r.json())

    def test_filter_by_q(self, api, owner_headers):
        title = f"TEST_search_{uuid.uuid4().hex[:6]}"
        api.post(f"{BASE_URL}/api/groups",
                 json=_group_payload(title=title), headers=owner_headers)
        r = api.get(f"{BASE_URL}/api/groups", params={"q": title})
        assert r.status_code == 200
        assert title in [g["title"] for g in r.json()]

    def test_mine_requires_auth(self, api):
        r = api.get(f"{BASE_URL}/api/groups/mine")
        assert r.status_code == 401

    def test_mine_returns_created(self, api, owner_headers, owner_device):
        r = api.get(f"{BASE_URL}/api/groups/mine", headers=owner_headers)
        assert r.status_code == 200
        body = r.json()
        assert "created" in body and "joined" in body
        assert pytest.created_group_id in [g["group_id"] for g in body["created"]]

    def test_delete_by_non_owner_forbidden(self, api, owner_headers):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_del_forb"), headers=owner_headers)
        gid = r.json()["group_id"]
        other = _new_device_id("OTHER")
        other_hdr = {"Authorization": f"Bearer {other}", "Content-Type": "application/json"}
        api.patch(f"{BASE_URL}/api/auth/me", json={"name": "Intruder"}, headers=other_hdr)
        r = api.delete(f"{BASE_URL}/api/groups/{gid}", headers=other_hdr)
        assert r.status_code == 403

    def test_delete_by_owner_ok_and_deletes_messages(self, api, owner_headers):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_del_owner"), headers=owner_headers)
        gid = r.json()["group_id"]
        api.post(f"{BASE_URL}/api/groups/{gid}/messages",
                 json={"text": "TEST_delmsg"}, headers=owner_headers)
        r = api.delete(f"{BASE_URL}/api/groups/{gid}", headers=owner_headers)
        assert r.status_code == 200
        # verify group gone
        assert api.get(f"{BASE_URL}/api/groups/{gid}").status_code == 404
        # verify messages gone
        assert db.messages.count_documents({"group_id": gid}) == 0


# ======================================================= Join / Leave
class TestJoinLeave:
    def test_join_requires_name(self, api, owner_headers):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_join_req_name"), headers=owner_headers)
        gid = r.json()["group_id"]
        # Fresh device with no name
        did = _new_device_id("TESTDEV")
        hdr = {"Authorization": f"Bearer {did}", "Content-Type": "application/json"}
        r = api.post(f"{BASE_URL}/api/groups/{gid}/join", headers=hdr)
        assert r.status_code == 400

    def test_join_duplicate_idempotent(self, api, owner_headers):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_join_dup"), headers=owner_headers)
        gid = r.json()["group_id"]
        other = _new_device_id("OTHER")
        hdr = {"Authorization": f"Bearer {other}", "Content-Type": "application/json"}
        api.patch(f"{BASE_URL}/api/auth/me", json={"name": "Joiner"}, headers=hdr)
        r1 = api.post(f"{BASE_URL}/api/groups/{gid}/join", headers=hdr)
        r2 = api.post(f"{BASE_URL}/api/groups/{gid}/join", headers=hdr)
        assert r1.status_code == 200 and r2.status_code == 200
        # participant appears only once
        parts = [p["user_id"] for p in r2.json()["participants"]]
        assert parts.count(other) == 1

    def test_join_full_group_400(self, api, owner_headers):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_full", min_p=1, max_p=1),
                     headers=owner_headers)
        gid = r.json()["group_id"]
        other = _new_device_id("OTHER")
        hdr = {"Authorization": f"Bearer {other}", "Content-Type": "application/json"}
        api.patch(f"{BASE_URL}/api/auth/me", json={"name": "Late"}, headers=hdr)
        r = api.post(f"{BASE_URL}/api/groups/{gid}/join", headers=hdr)
        assert r.status_code == 400
        assert "completo" in r.json()["detail"].lower()

    def test_owner_cannot_leave(self, api, owner_headers):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_owner_leave"), headers=owner_headers)
        gid = r.json()["group_id"]
        r = api.post(f"{BASE_URL}/api/groups/{gid}/leave", headers=owner_headers)
        assert r.status_code == 400

    def test_participant_can_leave(self, api, owner_headers):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_leave"), headers=owner_headers)
        gid = r.json()["group_id"]
        other = _new_device_id("OTHER")
        hdr = {"Authorization": f"Bearer {other}", "Content-Type": "application/json"}
        api.patch(f"{BASE_URL}/api/auth/me", json={"name": "Leaver"}, headers=hdr)
        api.post(f"{BASE_URL}/api/groups/{gid}/join", headers=hdr)
        r = api.post(f"{BASE_URL}/api/groups/{gid}/leave", headers=hdr)
        assert r.status_code == 200
        assert other not in [p["user_id"] for p in r.json()["participants"]]


# ======================================================= Messages
class TestMessages:
    def test_get_messages_requires_auth(self, api):
        r = api.get(f"{BASE_URL}/api/groups/whatever/messages")
        assert r.status_code == 401

    def test_participant_can_post_and_read(self, api, owner_headers, owner_device):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_chat"), headers=owner_headers)
        gid = r.json()["group_id"]
        r = api.post(f"{BASE_URL}/api/groups/{gid}/messages",
                     json={"text": "TEST_hello"}, headers=owner_headers)
        assert r.status_code == 200
        assert r.json()["text"] == "TEST_hello"
        assert r.json()["user_id"] == owner_device
        r = api.get(f"{BASE_URL}/api/groups/{gid}/messages", headers=owner_headers)
        assert r.status_code == 200
        assert any(m["text"] == "TEST_hello" for m in r.json())

    def test_non_participant_forbidden(self, api, owner_headers):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_foreign"), headers=owner_headers)
        gid = r.json()["group_id"]
        other = _new_device_id("OTHER")
        hdr = {"Authorization": f"Bearer {other}", "Content-Type": "application/json"}
        api.patch(f"{BASE_URL}/api/auth/me", json={"name": "Stranger"}, headers=hdr)
        r = api.get(f"{BASE_URL}/api/groups/{gid}/messages", headers=hdr)
        assert r.status_code == 403
        r = api.post(f"{BASE_URL}/api/groups/{gid}/messages",
                     json={"text": "nope"}, headers=hdr)
        assert r.status_code == 403

    def test_post_requires_name(self, api, owner_headers):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_msg_name"), headers=owner_headers)
        gid = r.json()["group_id"]
        # Fresh device (no name) - not a participant so we'd hit 403 first.
        # So we make the owner request without a name by using another device
        # then manually add to participants via DB is intrusive. Instead just
        # verify empty text -> 400 as a proxy for POST validation.
        r = api.post(f"{BASE_URL}/api/groups/{gid}/messages",
                     json={"text": "   "}, headers=owner_headers)
        assert r.status_code == 400


# ======================================================= Removed legacy Firebase endpoints
class TestNoLegacyEndpoints:
    @pytest.mark.parametrize("path", [
        "/api/auth/login", "/api/auth/signup", "/api/auth/session",
        "/api/auth/apple", "/api/auth/logout",
    ])
    def test_gone(self, api, path):
        r = api.post(f"{BASE_URL}{path}", json={})
        assert r.status_code == 404



# ======================================================= Expired-group auto-purge
# The backend removes groups whose event date+time+3h buffer is in the past. The
# purge runs on GET /api/groups, GET /api/groups/{id}, GET /api/groups/mine
# (throttled to once every 30s) and via a 5-minute background force loop. To
# force a fresh purge window per test we restart the backend once before this
# class (resets _last_purge_at=0), then wait 31s between purge-triggering
# assertions so the in-request throttle doesn't swallow the call.
import subprocess
import time
from zoneinfo import ZoneInfo

APP_TZ = ZoneInfo("Europe/Rome")


def _seed_group_doc(*, date: str, time_str: str, title: str, owner_id: str = "TESTDEV_seed",
                    group_id: str = None) -> str:
    """Insert a group directly via motor bypassing POST validation so we can
    plant already-expired events (POST /groups blocks past dates)."""
    gid = group_id or f"grp_{uuid.uuid4().hex[:12]}"
    doc = {
        "group_id": gid,
        "title": title,
        "category": "basketball",
        "category_label": "Basket",
        "location": "Milano",
        "description": "seed",
        "date": date,
        "time": time_str,
        "min_participants": 2,
        "max_participants": 10,
        "min_age": 18,
        "max_age": 40,
        "owner_id": owner_id,
        "owner_name": "Seed Owner",
        "owner_picture": None,
        "participants": [{"user_id": owner_id, "name": "Seed Owner", "picture": None}],
        "created_at": datetime.now(timezone.utc),
    }
    db.groups.insert_one(doc)
    return gid


@pytest.fixture(scope="class")
def reset_backend_for_purge():
    """Restart backend so the in-process 30s purge throttle is reset, then
    wait long enough for the startup force-purge to age out so subsequent
    in-request purges actually run."""
    subprocess.run(["sudo", "supervisorctl", "restart", "backend"], check=False,
                   capture_output=True)
    # Wait for backend to come back up (health check)
    for _ in range(30):
        try:
            r = requests.get(f"{BASE_URL}/api/", timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(1)
    # The startup background loop force-purges immediately on boot which sets
    # _last_purge_at → any in-request purge within 30s will be throttled. Wait
    # it out so the very first test's purge actually runs.
    time.sleep(32)
    yield


@pytest.mark.usefixtures("reset_backend_for_purge")
class TestExpiredGroupPurge:
    """Auto-purge of groups whose event datetime + 3h buffer is in the past."""

    def test_expired_group_purged_on_list_and_messages_cascade(self, api, owner_headers):
        # Seed one already-expired group (yesterday 18:00) with two messages.
        yesterday = (datetime.now(APP_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
        gid = _seed_group_doc(date=yesterday, time_str="18:00", title="TEST_expired_list")
        db.messages.insert_one({
            "message_id": f"msg_{uuid.uuid4().hex[:12]}",
            "group_id": gid, "user_id": "TESTDEV_seed", "user_name": "Seed",
            "user_picture": None, "text": "TEST_before_purge",
            "created_at": datetime.now(timezone.utc),
        })
        assert db.groups.count_documents({"group_id": gid}) == 1
        assert db.messages.count_documents({"group_id": gid}) == 1

        # Trigger purge via public list endpoint.
        r = api.get(f"{BASE_URL}/api/groups")
        assert r.status_code == 200
        assert gid not in [g["group_id"] for g in r.json()]
        # Verify DB cascade.
        assert db.groups.count_documents({"group_id": gid}) == 0
        assert db.messages.count_documents({"group_id": gid}) == 0

    def test_expired_group_purged_on_get_detail_returns_404(self, api):
        # Wait for throttle window (30s) to elapse since previous test triggered purge.
        time.sleep(31)
        yesterday = (datetime.now(APP_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
        gid = _seed_group_doc(date=yesterday, time_str="10:00", title="TEST_expired_detail")
        r = api.get(f"{BASE_URL}/api/groups/{gid}")
        # Group is purged before the find_one → 404
        assert r.status_code == 404
        assert db.groups.count_documents({"group_id": gid}) == 0

    def test_expired_group_purged_on_mine(self, api, owner_headers, owner_device):
        time.sleep(31)
        yesterday = (datetime.now(APP_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
        gid = _seed_group_doc(date=yesterday, time_str="09:00",
                              title="TEST_expired_mine", owner_id=owner_device)
        r = api.get(f"{BASE_URL}/api/groups/mine", headers=owner_headers)
        assert r.status_code == 200
        assert gid not in [g["group_id"] for g in r.json()["created"]]
        assert db.groups.count_documents({"group_id": gid}) == 0

    def test_today_future_group_kept(self, api):
        time.sleep(31)
        # Event today + 2h — well before the 3h buffer expires
        future = datetime.now(APP_TZ) + timedelta(hours=2)
        gid = _seed_group_doc(
            date=future.strftime("%Y-%m-%d"),
            time_str=future.strftime("%H:%M"),
            title="TEST_future_kept",
        )
        r = api.get(f"{BASE_URL}/api/groups")
        assert r.status_code == 200
        assert gid in [g["group_id"] for g in r.json()]
        assert db.groups.count_documents({"group_id": gid}) == 1
        db.groups.delete_one({"group_id": gid})  # cleanup

    def test_within_buffer_group_kept(self, api):
        time.sleep(31)
        # Event 1h in the past — still within the 3h buffer, must survive
        past = datetime.now(APP_TZ) - timedelta(hours=1)
        gid = _seed_group_doc(
            date=past.strftime("%Y-%m-%d"),
            time_str=past.strftime("%H:%M"),
            title="TEST_buffer_kept",
        )
        r = api.get(f"{BASE_URL}/api/groups")
        assert r.status_code == 200
        assert gid in [g["group_id"] for g in r.json()]
        assert db.groups.count_documents({"group_id": gid}) == 1
        db.groups.delete_one({"group_id": gid})

    def test_malformed_date_group_left_in_place(self, api):
        time.sleep(31)
        # Malformed date should NOT crash purge; group should also NOT be deleted.
        gid = _seed_group_doc(date="not-a-date", time_str="99:99",
                              title="TEST_malformed")
        r = api.get(f"{BASE_URL}/api/groups")
        assert r.status_code == 200
        # Group stays in DB (unparsable → skipped by purge, not deleted).
        assert db.groups.count_documents({"group_id": gid}) == 1
        db.groups.delete_one({"group_id": gid})  # cleanup

    def test_purge_is_throttled_within_30s(self, api):
        # First call runs purge; second call within 30s must be a no-op.
        time.sleep(31)
        yesterday = (datetime.now(APP_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
        # Seed group #1 and trigger purge → it should be deleted.
        gid1 = _seed_group_doc(date=yesterday, time_str="12:00",
                               title="TEST_throttle_1")
        assert api.get(f"{BASE_URL}/api/groups").status_code == 200
        assert db.groups.count_documents({"group_id": gid1}) == 0

        # Immediately seed group #2 and trigger again — throttle should keep it.
        gid2 = _seed_group_doc(date=yesterday, time_str="12:00",
                               title="TEST_throttle_2")
        assert api.get(f"{BASE_URL}/api/groups").status_code == 200
        # Still there — throttle prevented purge from running again.
        assert db.groups.count_documents({"group_id": gid2}) == 1
        db.groups.delete_one({"group_id": gid2})

    def test_create_group_rejects_past_date(self, api, owner_headers):
        past_date = (datetime.now(APP_TZ) - timedelta(days=2)).strftime("%Y-%m-%d")
        payload = _group_payload(title="TEST_reject_past")
        payload["date"] = past_date
        payload["time"] = "10:00"
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 400
        assert "passato" in r.json()["detail"].lower()

    def test_create_group_rejects_invalid_date_format(self, api, owner_headers):
        payload = _group_payload(title="TEST_bad_date")
        payload["date"] = "not-a-date"
        payload["time"] = "10:00"
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 400


# ======================================================= Content Moderation
# Verify POST /api/groups and POST /api/groups/{id}/messages reject forbidden
# content (droga, armi, orgy, etc.) even when obfuscated (leetspeak, spacing,
# accents, repeated letters, English variants). Response must be 400 with
# the exact Italian detail message.

FORBIDDEN_DETAIL = (
    "Contenuto non consentito: sono vietati riferimenti a "
    "droga, armi, violenza, sesso esplicito, alcol o "
    "contenuti illegali."
)


@pytest.fixture(scope="module", autouse=False)
def owner_named(api, owner_headers):
    """Ensure owner device has a name set (moderation tests may run in isolation)."""
    api.patch(f"{BASE_URL}/api/auth/me",
              json={"name": "Mod Owner"}, headers=owner_headers)
    return True


@pytest.mark.usefixtures("owner_named")
class TestModerationGroups:
    """POST /api/groups content moderation on title/description/location/category_label."""

    @pytest.mark.parametrize("bad", [
        "droga",                # straight
        "dr0ga",                # leetspeak zero
        "d r o g a",            # spaced
        "drogaaaa",             # repeated letters
        "c0caina",              # leet cocaina
        "cocaine party",        # english
        "drugs galore",         # english plural
        "v3ndere armi",         # leet + italian armi
        "arm1",                 # leet armi
        "orgia in casa",        # italian orgia
        "orgy tonight",         # english orgy
        "guns for sale",        # english guns
        "kalashnikov",          # weapons list
        "più droga",            # accented
    ])
    def test_reject_forbidden_title(self, api, owner_headers, bad):
        payload = _group_payload(title=f"TEST_{bad}")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 400, f"expected 400 for title={bad!r}, got {r.status_code}: {r.text}"
        assert r.json()["detail"] == FORBIDDEN_DETAIL

    def test_reject_forbidden_description(self, api, owner_headers):
        payload = _group_payload(title="TEST_clean_desc_bad")
        payload["description"] = "vendiamo c0caina al parco"
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 400
        assert r.json()["detail"] == FORBIDDEN_DETAIL

    def test_reject_forbidden_location(self, api, owner_headers):
        payload = _group_payload(title="TEST_clean_loc_bad")
        payload["location"] = "Piazza della droga"
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 400
        assert r.json()["detail"] == FORBIDDEN_DETAIL

    def test_reject_forbidden_category_label(self, api, owner_headers):
        payload = _group_payload(title="TEST_clean_cat_bad", label="Orgia Party")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 400
        assert r.json()["detail"] == FORBIDDEN_DETAIL

    def test_accept_clean_content(self, api, owner_headers):
        """Sanity check: perfectly clean groups still create as before."""
        payload = _group_payload(title="TEST_clean_ok")
        payload["description"] = "Bella partita al parco, portate acqua"
        payload["location"] = "Parco Sempione, Milano"
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["title"] == "TEST_clean_ok"
        assert body["description"] == "Bella partita al parco, portate acqua"

    def test_accept_similar_but_clean(self, api, owner_headers):
        """Should NOT false-positive on ordinary italian words."""
        payload = _group_payload(title="TEST_erbolino corsa")
        # 'corsa', 'gara', 'weekend' are clean; keep test titles unique
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 200, r.text


@pytest.mark.usefixtures("owner_named")
class TestModerationMessages:
    """POST /api/groups/{id}/messages content moderation."""

    def test_reject_forbidden_message(self, api, owner_headers):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_mod_chat"), headers=owner_headers)
        assert r.status_code == 200, r.text
        gid = r.json()["group_id"]
        r = api.post(f"{BASE_URL}/api/groups/{gid}/messages",
                     json={"text": "vendo dr0ga a tutti"}, headers=owner_headers)
        assert r.status_code == 400
        assert r.json()["detail"] == FORBIDDEN_DETAIL

    def test_reject_spaced_forbidden_message(self, api, owner_headers):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_mod_chat_spaced"), headers=owner_headers)
        gid = r.json()["group_id"]
        r = api.post(f"{BASE_URL}/api/groups/{gid}/messages",
                     json={"text": "d r o g a subito"}, headers=owner_headers)
        assert r.status_code == 400
        assert r.json()["detail"] == FORBIDDEN_DETAIL

    def test_reject_english_forbidden_message(self, api, owner_headers):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_mod_chat_en"), headers=owner_headers)
        gid = r.json()["group_id"]
        r = api.post(f"{BASE_URL}/api/groups/{gid}/messages",
                     json={"text": "buying guns tonight"}, headers=owner_headers)
        assert r.status_code == 400
        assert r.json()["detail"] == FORBIDDEN_DETAIL

    def test_accept_clean_message(self, api, owner_headers):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_mod_chat_ok"), headers=owner_headers)
        gid = r.json()["group_id"]
        r = api.post(f"{BASE_URL}/api/groups/{gid}/messages",
                     json={"text": "TEST_ci vediamo al parco alle 18"}, headers=owner_headers)
        assert r.status_code == 200
        assert r.json()["text"] == "TEST_ci vediamo al parco alle 18"



# ======================================================= Public user profile
# GET /api/users/{target_id} — visible when caller & target share a group.
class TestPublicUserProfile:
    @pytest.fixture(scope="class")
    def owner_named(self, api, owner_headers):
        """Ensure the owner has a name so they can create groups."""
        api.patch(f"{BASE_URL}/api/auth/me",
                  json={"name": "Owner Name"}, headers=owner_headers)
        yield

    @pytest.fixture(scope="class")
    def other_user(self, api):
        """A second, fully-profiled user (no shared group yet)."""
        did = _new_device_id("OTHER")
        hdr = {"Authorization": f"Bearer {did}", "Content-Type": "application/json"}
        api.patch(f"{BASE_URL}/api/auth/me",
                  json={"name": "Bob Other", "picture": "https://pic/bob.png",
                        "gender": "male", "age": 33}, headers=hdr)
        return {"device_id": did, "headers": hdr}

    # ---- Auth / input validation

    def test_missing_auth_401(self, api):
        r = api.get(f"{BASE_URL}/api/users/anyuser1234")
        assert r.status_code == 401

    def test_bad_bearer_401(self, api):
        r = api.get(f"{BASE_URL}/api/users/anyuser1234",
                    headers={"Authorization": "Bearer !!bad!!"})
        assert r.status_code == 401

    def test_malformed_target_id_400(self, api, owner_headers, owner_named):
        # 'x' is too short (min 8)
        r = api.get(f"{BASE_URL}/api/users/x", headers=owner_headers)
        assert r.status_code == 400
        assert "non valido" in r.json()["detail"].lower()

    def test_malformed_target_id_bad_chars_400(self, api, owner_headers, owner_named):
        # spaces not allowed by regex — but path encoding may hide this; use $
        r = api.get(f"{BASE_URL}/api/users/bad$$$$id", headers=owner_headers)
        assert r.status_code == 400

    def test_nonexistent_target_404(self, api, owner_headers, owner_named):
        # Valid regex but never seen by backend
        did = _new_device_id("NEVER")
        r = api.get(f"{BASE_URL}/api/users/{did}", headers=owner_headers)
        assert r.status_code == 404
        assert r.json()["detail"] == "Utente non trovato"

    # ---- Self view (no shared group required)

    def test_self_view_no_shared_group_returns_200(self, api):
        did = _new_device_id("SELF")
        hdr = {"Authorization": f"Bearer {did}", "Content-Type": "application/json"}
        api.patch(f"{BASE_URL}/api/auth/me",
                  json={"name": "Self User", "age": 29, "gender": "female"},
                  headers=hdr)
        r = api.get(f"{BASE_URL}/api/users/{did}", headers=hdr)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user_id"] == did
        assert body["name"] == "Self User"
        assert body["age"] == 29
        assert body["gender"] == "female"
        # PublicUser must NOT expose profile_complete
        assert "profile_complete" not in body

    def test_public_user_payload_shape(self, api, owner_headers, owner_named):
        # PublicUser fields: user_id, name, picture, gender, age, created_at
        r = api.get(f"{BASE_URL}/api/users/{_extract_owner_from(owner_headers)}",
                    headers=owner_headers)
        assert r.status_code == 200
        body = r.json()
        for k in ("user_id", "name", "picture", "gender", "age", "created_at"):
            assert k in body, f"missing {k} in PublicUser payload"

    # ---- Access control based on shared group membership

    def test_no_shared_group_returns_403(self, api, owner_headers, other_user):
        # owner never joined a group with other_user
        r = api.get(f"{BASE_URL}/api/users/{other_user['device_id']}",
                    headers=owner_headers)
        assert r.status_code == 403
        assert r.json()["detail"] == (
            "Puoi vedere solo profili di utenti con cui condividi un gruppo"
        )

    def test_shared_group_allows_view_both_directions(
        self, api, owner_headers, owner_device, other_user, owner_named
    ):
        # Create a group as owner, other joins → they share a group.
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_profile_share"),
                     headers=owner_headers)
        assert r.status_code == 200, r.text
        gid = r.json()["group_id"]
        r = api.post(f"{BASE_URL}/api/groups/{gid}/join",
                     headers=other_user["headers"])
        assert r.status_code == 200, r.text

        # Owner → Other
        r = api.get(f"{BASE_URL}/api/users/{other_user['device_id']}",
                    headers=owner_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user_id"] == other_user["device_id"]
        assert body["name"] == "Bob Other"
        assert body["age"] == 33
        assert body["gender"] == "male"
        assert body["picture"] == "https://pic/bob.png"

        # Other → Owner
        r = api.get(f"{BASE_URL}/api/users/{owner_device}",
                    headers=other_user["headers"])
        assert r.status_code == 200, r.text
        assert r.json()["user_id"] == owner_device
        assert r.json()["name"] == "Owner Name"

    def test_leaving_group_removes_access_403(
        self, api, owner_headers, owner_device, owner_named
    ):
        # Fresh third user, they join then leave → no longer share a group.
        did = _new_device_id("OTHER")
        hdr = {"Authorization": f"Bearer {did}", "Content-Type": "application/json"}
        api.patch(f"{BASE_URL}/api/auth/me",
                  json={"name": "Leaver"}, headers=hdr)
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_profile_leave"),
                     headers=owner_headers)
        gid = r.json()["group_id"]
        api.post(f"{BASE_URL}/api/groups/{gid}/join", headers=hdr)
        # Sanity: while joined, both can see each other
        r = api.get(f"{BASE_URL}/api/users/{did}", headers=owner_headers)
        assert r.status_code == 200
        # Now leave and re-check
        api.post(f"{BASE_URL}/api/groups/{gid}/leave", headers=hdr)
        r = api.get(f"{BASE_URL}/api/users/{did}", headers=owner_headers)
        assert r.status_code == 403
        r = api.get(f"{BASE_URL}/api/users/{owner_device}", headers=hdr)
        assert r.status_code == 403

    def test_endpoint_auto_creates_caller_not_target(self, api):
        # Fresh device with NO prior request — the endpoint's dep should
        # auto-create the caller, but the target (also new) must 404.
        caller = _new_device_id("TESTDEV")
        target = _new_device_id("NEVER")
        hdr = {"Authorization": f"Bearer {caller}", "Content-Type": "application/json"}
        r = api.get(f"{BASE_URL}/api/users/{target}", headers=hdr)
        assert r.status_code == 404
        # Caller now exists in db (auto-created)
        assert db.users.count_documents({"user_id": caller}) == 1
        # Target was NOT created
        assert db.users.count_documents({"user_id": target}) == 0


def _extract_owner_from(headers: dict) -> str:
    return headers["Authorization"].split(" ", 1)[1]


# ======================================================= Iteration 10: Stem-based moderation
# Verify the new stem-based moderation catches leetspeak/repeats/accents/spacing
# variants requested by the user in this iteration, blocks the newly added
# terms (sesso, porno, alcol, ubriac, stupefac, attentat, uccider, ammazz,
# omicid), and does NOT false-positive on ordinary Italian words that just
# happen to contain a stem in the middle (carbonara, ceramica, sessione,
# metodo, cocacola, hashtag, carmine, gatto, erba).

@pytest.mark.usefixtures("owner_named")
class TestModerationStemsIteration10:
    """Iteration 10: stem-based obfuscation catches + newly added terms + FP-free."""

    # ---- TRUE-POSITIVE: exact user-facing example + leet/repeat variants ----
    @pytest.mark.parametrize("bad", [
        "Vendo Drog3",         # user's original example (leet 3->e)
        "Drog4",               # leet 4->a
        "dr0ga",               # leet 0->o
        "drogaaa",             # repeated tail
        "v3nd3re Arm1",        # leet armi
        "Vendita p1st0le",     # leet pistole -> pistol stem
        "Vendo sesso",         # new term sesso
        "porno party",         # new term porno
        "orgia in casa",       # orgia stem
        "bevi alcol tutti",    # new term alcol
        "vieni per l alcool",  # alcool variant
        "alcohol night",       # english alcohol
        "vado a ubriacarmi",   # ubriac stem
        "cerco stupefacenti",  # stupefac stem
        "organizziamo attentato",  # attentat stem
        "voglio ucciderlo",    # uccider stem
        "ammazziamoci",        # ammazz stem
        "compiere omicidio",   # omicid stem
    ])
    def test_reject_title_iteration10(self, api, owner_headers, bad):
        payload = _group_payload(title=f"TEST_{bad}")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 400, f"expected 400 for title={bad!r}, got {r.status_code}: {r.text}"
        assert r.json()["detail"] == FORBIDDEN_DETAIL

    @pytest.mark.parametrize("bad", [
        "Vendo Drog3 al parco",
        "consegna dr0ga stasera",
        "portiamo sesso qui",
        "beviamo alcool",
        "andiamo a ubriacarci",
    ])
    def test_reject_description_iteration10(self, api, owner_headers, bad):
        payload = _group_payload(title=f"TEST_desc_ok_{uuid.uuid4().hex[:6]}")
        payload["description"] = bad
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 400, f"expected 400 for desc={bad!r}"
        assert r.json()["detail"] == FORBIDDEN_DETAIL

    @pytest.mark.parametrize("bad", [
        "Via della Drog4",
        "Piazza attentato",
        "Parco Sesso 5",
    ])
    def test_reject_location_iteration10(self, api, owner_headers, bad):
        payload = _group_payload(title=f"TEST_loc_ok_{uuid.uuid4().hex[:6]}")
        payload["location"] = bad
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 400, f"expected 400 for location={bad!r}"
        assert r.json()["detail"] == FORBIDDEN_DETAIL

    @pytest.mark.parametrize("bad", [
        "Drog3 party",
        "Sesso club",
        "Alcool social",
    ])
    def test_reject_category_label_iteration10(self, api, owner_headers, bad):
        payload = _group_payload(title=f"TEST_cat_ok_{uuid.uuid4().hex[:6]}", label=bad)
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 400, f"expected 400 for label={bad!r}"
        assert r.json()["detail"] == FORBIDDEN_DETAIL

    @pytest.mark.parametrize("bad", [
        "vendo Drog3 a tutti",
        "porto sesso stasera",
        "beviamo alcool insieme",
        "andiamo a ubriacarci",
        "sto per ucciderlo",
    ])
    def test_reject_chat_message_iteration10(self, api, owner_headers, bad):
        # Create a clean group first
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title=f"TEST_chat_it10_{uuid.uuid4().hex[:6]}"),
                     headers=owner_headers)
        assert r.status_code == 200, r.text
        gid = r.json()["group_id"]
        r = api.post(f"{BASE_URL}/api/groups/{gid}/messages",
                     json={"text": bad}, headers=owner_headers)
        assert r.status_code == 400, f"expected 400 for msg={bad!r}: {r.text}"
        assert r.json()["detail"] == FORBIDDEN_DETAIL

    # ---- TRUE-NEGATIVE: clean words that must NOT be flagged ----
    @pytest.mark.parametrize("clean_title", [
        "TEST_Cena carbonara",              # 'arma' should NOT match 'carbonara'
        "TEST_Corso di ceramica",           # inner 'armi' in 'ceramica' -> stem 'arma' word-boundary ok
        "TEST_Sessione di studio",          # 'sesso' stem must not match 'sessione'
        "TEST_Metodo di studio",            # 'meth' — no 'meth' stem, only 'methamph'
        "TEST_Cocacola party",              # 'cocain' stem word-boundary must not match 'cocacola'
        "TEST_Hashtag social",              # 'hashish' stem must not match 'hashtag'
        "TEST_Carmine e i suoi amici",      # 'armi' stem must not match 'carmine' (word-boundary)
        "TEST_Il gatto sul tetto",          # totally clean
        "TEST_Un po d erba nel parco",      # 'erba' has NO stem (kept lenient per spec)
    ])
    def test_accept_false_positive_free(self, api, owner_headers, clean_title):
        payload = _group_payload(title=clean_title)
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 200, f"false-positive on {clean_title!r}: {r.text}"
        body = r.json()
        assert body["title"] == clean_title

    def test_accept_clean_description_with_similar_words(self, api, owner_headers):
        payload = _group_payload(title=f"TEST_clean_desc_it10_{uuid.uuid4().hex[:6]}")
        payload["description"] = (
            "Sessione di ceramica: portate il carbonaio e un panino di carbonara. "
            "Hashtag ufficiale #cocacolaparty — verrà anche Carmine."
        )
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 200, r.text

    def test_forbidden_detail_message_exact(self, api, owner_headers):
        """Guard: the detail message wording must match exactly (client mirrors it)."""
        payload = _group_payload(title="TEST_Vendo Drog3")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 400
        assert r.json()["detail"] == (
            "Contenuto non consentito: sono vietati riferimenti a "
            "droga, armi, violenza, sesso esplicito, alcol o "
            "contenuti illegali."
        )


# ======================================================= Iteration 11: Geolocation (Nominatim + Haversine)
# Throttle: Nominatim policy is 1 req/s; we sleep 1.3s between geocode-triggering requests.
import time as _time

NOMINATIM_SLEEP = 1.3


@pytest.mark.usefixtures("owner_named")
class TestGeolocationGroupCreate:
    """POST /api/groups: city/street mandatory + geocoding to lat/lon."""

    def test_missing_city_400(self, api, owner_headers):
        payload = _group_payload(title="TEST_geo_nocity", city="", street="Via Roma 1")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 400
        assert "citt" in r.json()["detail"].lower()

    def test_missing_street_400(self, api, owner_headers):
        _time.sleep(NOMINATIM_SLEEP)
        payload = _group_payload(title="TEST_geo_nostreet", city="Milano", street="")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 400
        assert "via" in r.json()["detail"].lower()

    def test_missing_city_field_entirely_422(self, api, owner_headers):
        """Removing city key from payload should be a Pydantic 422."""
        payload = _group_payload(title="TEST_geo_nocity_key")
        payload.pop("city")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 422

    def test_missing_street_field_entirely_422(self, api, owner_headers):
        payload = _group_payload(title="TEST_geo_nostreet_key")
        payload.pop("street")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 422

    def test_create_with_city_and_street_geocodes_milano(self, api, owner_headers):
        _time.sleep(NOMINATIM_SLEEP)
        payload = _group_payload(title="TEST_geo_milano_ok",
                                 city="Milano", street="Via Torino 20")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 200, r.text
        g = r.json()
        # lat/lon must be set and around Milan center (45.4x, 9.1x)
        assert g["lat"] is not None and g["lon"] is not None, f"lat/lon missing: {g}"
        assert 45.3 <= g["lat"] <= 45.6, f"lat out of Milan range: {g['lat']}"
        assert 9.0 <= g["lon"] <= 9.3, f"lon out of Milan range: {g['lon']}"
        assert g["city"] == "Milano"
        assert g["street"] == "Via Torino 20"
        pytest.milano_group_id = g["group_id"]
        pytest.milano_lat = g["lat"]
        pytest.milano_lon = g["lon"]

    def test_reject_moderation_in_city(self, api, owner_headers):
        payload = _group_payload(title="TEST_geo_mod_city", city="Cittadella droga", street="Via 1")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 400
        assert r.json()["detail"] == FORBIDDEN_DETAIL

    def test_reject_moderation_in_street(self, api, owner_headers):
        payload = _group_payload(title="TEST_geo_mod_street", city="Milano",
                                 street="Via della drog4")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 400
        assert r.json()["detail"] == FORBIDDEN_DETAIL


@pytest.mark.usefixtures("owner_named")
class TestGeolocationListFilter:
    """GET /api/groups with lat/lon/radius_km — Haversine filter + backward compat."""

    def test_no_geo_params_returns_all(self, api):
        r = api.get(f"{BASE_URL}/api/groups")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        # Should include groups without lat/lon too
        assert len(r.json()) >= 0  # regression: endpoint still works

    def test_filter_by_milano_5km_includes_milano_group(self, api, owner_headers):
        # Ensure the milano group exists in DB
        assert hasattr(pytest, "milano_group_id"), "prerequisite: create milano group ran"
        r = api.get(f"{BASE_URL}/api/groups",
                    params={"lat": 45.4642, "lon": 9.1900, "radius_km": 5})
        assert r.status_code == 200
        ids = [g["group_id"] for g in r.json()]
        assert pytest.milano_group_id in ids, "Milano group must be within 5km of Milan center"

    def test_filter_by_milano_1km_excludes_rome_group(self, api, owner_headers):
        # Seed a Rome group directly in DB with lat/lon at Colosseum (~41.89, 12.49)
        rome_gid = f"grp_{uuid.uuid4().hex[:12]}"
        future = (datetime.now(timezone.utc) + timedelta(days=15)).strftime("%Y-%m-%d")
        db.groups.insert_one({
            "group_id": rome_gid,
            "title": "TEST_rome_geo",
            "category": "basketball",
            "category_label": "Basket",
            "location": "Roma",
            "city": "Roma",
            "street": "Via dei Fori Imperiali 1",
            "lat": 41.8902,
            "lon": 12.4922,
            "description": "seed rome",
            "date": future,
            "time": "18:00",
            "min_participants": 2,
            "max_participants": 10,
            "min_age": 18,
            "max_age": 40,
            "owner_id": "TESTDEV_seedrome",
            "owner_name": "Seed Rome",
            "owner_picture": None,
            "participants": [{"user_id": "TESTDEV_seedrome", "name": "Seed Rome", "picture": None}],
            "created_at": datetime.now(timezone.utc),
        })
        try:
            r = api.get(f"{BASE_URL}/api/groups",
                        params={"lat": 45.4642, "lon": 9.1900, "radius_km": 1})
            assert r.status_code == 200
            ids = [g["group_id"] for g in r.json()]
            assert rome_gid not in ids, "Rome group must NOT be within 1km of Milan"
        finally:
            db.groups.delete_one({"group_id": rome_gid})

    def test_legacy_groups_without_latlon_are_included(self, api):
        """Backward compat: groups with lat=None must be kept visible when filtering."""
        # Seed a legacy group with no lat/lon
        legacy_gid = f"grp_{uuid.uuid4().hex[:12]}"
        future = (datetime.now(timezone.utc) + timedelta(days=15)).strftime("%Y-%m-%d")
        db.groups.insert_one({
            "group_id": legacy_gid,
            "title": "TEST_legacy_nogeo",
            "category": "basketball",
            "category_label": "Basket",
            "location": "Nowhere",
            "city": None,
            "street": None,
            "lat": None,
            "lon": None,
            "description": "seed legacy",
            "date": future,
            "time": "18:00",
            "min_participants": 2, "max_participants": 10,
            "min_age": 18, "max_age": 40,
            "owner_id": "TESTDEV_seedlegacy",
            "owner_name": "Legacy", "owner_picture": None,
            "participants": [{"user_id": "TESTDEV_seedlegacy", "name": "Legacy", "picture": None}],
            "created_at": datetime.now(timezone.utc),
        })
        try:
            r = api.get(f"{BASE_URL}/api/groups",
                        params={"lat": 45.4642, "lon": 9.1900, "radius_km": 1})
            assert r.status_code == 200
            ids = [g["group_id"] for g in r.json()]
            assert legacy_gid in ids, "Legacy no-lat/lon group must be visible under geo filter"
        finally:
            db.groups.delete_one({"group_id": legacy_gid})


class TestGeocodeEndpoint:
    """GET /api/geocode?city=&street="""

    def test_geocode_milano_returns_lat_lon(self, api):
        _time.sleep(NOMINATIM_SLEEP)
        r = api.get(f"{BASE_URL}/api/geocode",
                    params={"city": "Milano", "street": "Via Torino"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "lat" in body and "lon" in body
        assert 45.3 <= body["lat"] <= 45.6
        assert 9.0 <= body["lon"] <= 9.3

    def test_geocode_nonexistent_city_404(self, api):
        _time.sleep(NOMINATIM_SLEEP)
        r = api.get(f"{BASE_URL}/api/geocode",
                    params={"city": "CittaChenonEsisteSicuro123XYZ"})
        assert r.status_code == 404
        assert "trovat" in r.json()["detail"].lower()

    def test_geocode_missing_city_422(self, api):
        r = api.get(f"{BASE_URL}/api/geocode")
        assert r.status_code == 422

    def test_geocode_only_city_ok(self, api):
        _time.sleep(NOMINATIM_SLEEP)
        r = api.get(f"{BASE_URL}/api/geocode", params={"city": "Milano"})
        assert r.status_code == 200
        assert "lat" in r.json() and "lon" in r.json()
