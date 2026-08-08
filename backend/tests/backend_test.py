"""
GroupUp Backend Tests — Firebase Auth migration (Jan 2026).

Covers:
- Health
- /api/auth/me GET & PATCH (Firebase ID token)
- Missing/invalid/malformed tokens -> 401
- Removed legacy endpoints -> 404
- Groups CRUD (create/list/detail/join/leave/delete/mine) with owner semantics
- Group validation (max_participants < min_participants; max_age < min_age)
- Group filters (?category=..., ?q=...)
- Messages: participant-only GET/POST (403 for non-participants)
"""
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# ----- Config
FRONTEND_ENV = Path("/app/frontend/.env")
PUBLIC_URL = None
for line in FRONTEND_ENV.read_text().splitlines():
    if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
        PUBLIC_URL = line.split("=", 1)[1].strip().strip('"')
BASE_URL = (PUBLIC_URL or "http://localhost:8001").rstrip("/")

FIREBASE_API_KEY = "AIzaSyCfHWq1CR3bcuXgn0I44kkgvjHZiOjsY-o"
TEST_EMAIL = "testuser@groupup.test"
TEST_PASSWORD = "TestPass1234!"
TEST_UID = "nXSxqsjwtGU3kEPFNkF9CgWR5tb2"

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]


def _get_id_token():
    r = requests.post(
        f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD, "returnSecureToken": True},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["idToken"]


@pytest.fixture(scope="session")
def id_token():
    return _get_id_token()


@pytest.fixture(scope="session")
def auth_headers(id_token):
    return {"Authorization": f"Bearer {id_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    yield s
    # Cleanup groups/messages created by our test UID
    db.messages.delete_many({"user_id": TEST_UID, "text": {"$regex": "^TEST_"}})
    db.groups.delete_many({"owner_id": TEST_UID, "title": {"$regex": "^TEST_"}})


# --------------------------------------------------------------- Health
class TestHealth:
    def test_root(self, api):
        r = api.get(f"{BASE_URL}/api/")
        assert r.status_code == 200
        assert r.json()["message"] == "GroupUp API"


# --------------------------------------------------------------- /auth/me
class TestAuthMe:
    def test_me_ok(self, api, auth_headers):
        r = api.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert r.status_code == 200, r.text
        u = r.json()
        assert u["user_id"] == TEST_UID
        assert u["email"] == TEST_EMAIL
        assert u["email_verified"] is True
        # required fields
        for k in ("name", "profile_complete", "providers", "created_at"):
            assert k in u

    def test_me_missing_token(self, api):
        r = api.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401

    def test_me_malformed_header(self, api):
        r = api.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": "NotBearer x"})
        assert r.status_code == 401

    def test_me_invalid_token(self, api):
        r = api.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": "Bearer bogus.jwt.token"})
        assert r.status_code == 401

    def test_patch_me_updates_and_completes(self, api, auth_headers):
        payload = {
            "name": "Test User",
            "picture": "https://example.com/avatar.png",
            "gender": "other",
            "age": 30,
        }
        r = api.patch(f"{BASE_URL}/api/auth/me", json=payload, headers=auth_headers)
        assert r.status_code == 200, r.text
        u = r.json()
        assert u["name"] == "Test User"
        assert u["picture"] == "https://example.com/avatar.png"
        assert u["gender"] == "other"
        assert u["age"] == 30
        assert u["profile_complete"] is True
        # Persistence
        r2 = api.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert r2.json()["profile_complete"] is True

    def test_patch_me_invalid_age(self, api, auth_headers):
        r = api.patch(f"{BASE_URL}/api/auth/me", json={"age": 999}, headers=auth_headers)
        assert r.status_code == 422

    def test_patch_me_invalid_gender(self, api, auth_headers):
        r = api.patch(f"{BASE_URL}/api/auth/me", json={"gender": "unknown"}, headers=auth_headers)
        assert r.status_code == 422


# --------------------------------------------------------------- Removed legacy endpoints
class TestRemovedEndpoints:
    @pytest.mark.parametrize("path,method,body", [
        ("/api/auth/login", "POST", {"email": "x@x.com", "password": "x"}),
        ("/api/auth/signup", "POST", {"email": "x@x.com", "password": "xxxxxx", "name": "x"}),
        ("/api/auth/session", "POST", {"session_id": "x"}),
        ("/api/auth/apple", "POST", {"identity_token": "x"}),
        ("/api/auth/verify-email", "POST", {"token": "x"}),
        ("/api/auth/request-password-reset", "POST", {"email": "x@x.com"}),
        ("/api/auth/confirm-reset", "POST", {"token": "x", "new_password": "xxxxxx"}),
        ("/api/auth/logout", "POST", {}),
    ])
    def test_removed(self, api, path, method, body):
        r = api.request(method, f"{BASE_URL}{path}", json=body)
        assert r.status_code == 404, f"{path} should be removed but returned {r.status_code}"


# --------------------------------------------------------------- Groups
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

    def test_list_public(self, api):
        r = api.get(f"{BASE_URL}/api/groups")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_and_persist(self, api, auth_headers):
        payload = _group_payload(title="TEST_persist")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=auth_headers)
        assert r.status_code == 200, r.text
        g = r.json()
        assert g["title"] == "TEST_persist"
        assert g["owner_id"] == TEST_UID
        assert len(g["participants"]) == 1
        assert g["participants"][0]["user_id"] == TEST_UID
        # GET verifies persistence
        r2 = api.get(f"{BASE_URL}/api/groups/{g['group_id']}")
        assert r2.status_code == 200
        assert r2.json()["group_id"] == g["group_id"]
        pytest.created_group_id = g["group_id"]

    def test_validation_max_lt_min_participants(self, api, auth_headers):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(min_p=10, max_p=5), headers=auth_headers)
        assert r.status_code == 400
        assert "participants" in r.json()["detail"].lower()

    def test_validation_max_lt_min_age(self, api, auth_headers):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(min_a=40, max_a=18), headers=auth_headers)
        assert r.status_code == 400
        assert "age" in r.json()["detail"].lower()

    def test_filter_by_category(self, api, auth_headers):
        # Ensure at least one exists
        api.post(f"{BASE_URL}/api/groups",
                 json=_group_payload(category="basketball"), headers=auth_headers)
        r = api.get(f"{BASE_URL}/api/groups", params={"category": "basketball"})
        assert r.status_code == 200
        data = r.json()
        assert all(g["category"] == "basketball" for g in data)
        assert len(data) >= 1

    def test_filter_by_q(self, api, auth_headers):
        title = f"TEST_search_{uuid.uuid4().hex[:6]}"
        api.post(f"{BASE_URL}/api/groups",
                 json=_group_payload(title=title), headers=auth_headers)
        r = api.get(f"{BASE_URL}/api/groups", params={"q": title})
        assert r.status_code == 200
        titles = [g["title"] for g in r.json()]
        assert title in titles

    def test_mine_endpoint(self, api, auth_headers):
        r = api.get(f"{BASE_URL}/api/groups/mine", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert "created" in body and "joined" in body
        created_ids = [g["group_id"] for g in body["created"]]
        assert pytest.created_group_id in created_ids

    def test_delete_requires_owner_and_works(self, api, auth_headers):
        # Create then delete
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_del"), headers=auth_headers)
        gid = r.json()["group_id"]
        r = api.delete(f"{BASE_URL}/api/groups/{gid}", headers=auth_headers)
        assert r.status_code == 200
        r = api.get(f"{BASE_URL}/api/groups/{gid}")
        assert r.status_code == 404


# --------------------------------------------------------------- Messages
class TestMessages:
    def test_participant_can_post_and_read(self, api, auth_headers):
        # Owner is automatically a participant
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_chat"), headers=auth_headers)
        gid = r.json()["group_id"]
        # Post message
        r = api.post(f"{BASE_URL}/api/groups/{gid}/messages",
                     json={"text": "TEST_hello"}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["text"] == "TEST_hello"
        assert r.json()["user_id"] == TEST_UID
        # Read
        r = api.get(f"{BASE_URL}/api/groups/{gid}/messages", headers=auth_headers)
        assert r.status_code == 200
        assert any(m["text"] == "TEST_hello" for m in r.json())

    def test_non_participant_forbidden(self, api, auth_headers):
        # Create a group owned by test user, then remove test user from participants
        # to simulate a non-participant. (Can't leave as owner; instead, insert a
        # synthetic group not containing our uid.)
        fake_gid = f"grp_{uuid.uuid4().hex[:12]}"
        db.groups.insert_one({
            "group_id": fake_gid,
            "title": "TEST_foreign",
            "category": "basketball",
            "category_label": "Basket",
            "location": "Milano",
            "description": "",
            "date": "2026-02-15",
            "time": "18:30",
            "min_participants": 2,
            "max_participants": 10,
            "min_age": 18,
            "max_age": 40,
            "owner_id": "someone_else_uid",
            "owner_name": "Other",
            "owner_picture": None,
            "participants": [{"user_id": "someone_else_uid", "name": "Other", "picture": None}],
            "created_at": __import__("datetime").datetime.utcnow(),
        })
        try:
            r = api.get(f"{BASE_URL}/api/groups/{fake_gid}/messages", headers=auth_headers)
            assert r.status_code == 403
            r = api.post(f"{BASE_URL}/api/groups/{fake_gid}/messages",
                         json={"text": "should fail"}, headers=auth_headers)
            assert r.status_code == 403
        finally:
            db.groups.delete_one({"group_id": fake_gid})

    def test_messages_missing_auth(self, api):
        r = api.get(f"{BASE_URL}/api/groups/any/messages")
        assert r.status_code == 401


# --------------------------------------------------------------- Join / Leave
class TestJoinLeave:
    def test_join_leave_flow_with_second_user(self, api, auth_headers):
        # Create a foreign group and join it as our test user
        fake_gid = f"grp_{uuid.uuid4().hex[:12]}"
        db.groups.insert_one({
            "group_id": fake_gid,
            "title": "TEST_join",
            "category": "basketball",
            "category_label": "Basket",
            "location": "Milano",
            "description": "",
            "date": "2026-02-15",
            "time": "18:30",
            "min_participants": 2,
            "max_participants": 10,
            "min_age": 18,
            "max_age": 40,
            "owner_id": "other_uid",
            "owner_name": "Other",
            "owner_picture": None,
            "participants": [{"user_id": "other_uid", "name": "Other", "picture": None}],
            "created_at": __import__("datetime").datetime.utcnow(),
        })
        try:
            r = api.post(f"{BASE_URL}/api/groups/{fake_gid}/join", headers=auth_headers)
            assert r.status_code == 200
            uids = [p["user_id"] for p in r.json()["participants"]]
            assert TEST_UID in uids
            # /mine.joined should now show it
            r = api.get(f"{BASE_URL}/api/groups/mine", headers=auth_headers)
            joined_ids = [g["group_id"] for g in r.json()["joined"]]
            assert fake_gid in joined_ids
            # Leave
            r = api.post(f"{BASE_URL}/api/groups/{fake_gid}/leave", headers=auth_headers)
            assert r.status_code == 200
            uids = [p["user_id"] for p in r.json()["participants"]]
            assert TEST_UID not in uids
        finally:
            db.groups.delete_one({"group_id": fake_gid})
            db.messages.delete_many({"group_id": fake_gid})

    def test_owner_cannot_leave(self, api, auth_headers):
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_owner_leave"), headers=auth_headers)
        gid = r.json()["group_id"]
        try:
            r = api.post(f"{BASE_URL}/api/groups/{gid}/leave", headers=auth_headers)
            assert r.status_code == 400
        finally:
            api.delete(f"{BASE_URL}/api/groups/{gid}", headers=auth_headers)
