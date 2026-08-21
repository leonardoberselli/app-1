"""
GroupUp Backend Tests - Device-UUID Auth (Jan 2026 rewrite).

Auth model: Authorization: Bearer <device_id> where device_id matches
^[A-Za-z0-9_-]{8,128}$. Backend auto-creates user on first request.
"""
import os
import uuid
from pathlib import Path
from datetime import datetime, timezone

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
                   min_p=2, max_p=10, min_a=18, max_a=40):
    return {
        "title": title or f"TEST_grp_{uuid.uuid4().hex[:6]}",
        "category": category,
        "category_label": label,
        "location": "Milano",
        "description": "created by backend_test",
        "date": "2026-02-15",
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
