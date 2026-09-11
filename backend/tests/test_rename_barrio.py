"""Iteration 17 — verify the app rename from GroupUp to Barrio at the
backend API boundary. Only user-visible strings must change; auth, group
CRUD, T&C gate, admin, reports must all keep working."""
import os
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# --- resolve public backend URL from frontend .env
FRONTEND_ENV = Path("/app/frontend/.env")
PUBLIC_URL = None
for line in FRONTEND_ENV.read_text().splitlines():
    for key in ("EXPO_BACKEND_URL=", "EXPO_PUBLIC_BACKEND_URL="):
        if line.startswith(key):
            PUBLIC_URL = line.split("=", 1)[1].strip().strip('"')
            break
BASE_URL = (PUBLIC_URL or "http://localhost:8001").rstrip("/")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]

TERMS_VERSION_CURRENT = "2026-06-01"  # keep in sync with server.CURRENT_TERMS_VERSION


def _seed_user(*, accept_terms: bool, age: int = 25, name: str = "Rename Tester",
               gender: str = "male"):
    """Insert a users doc + a matching user_sessions doc directly in Mongo,
    bypassing the Emergent Google Sign-In flow."""
    uid = f"user_{uuid.uuid4().hex[:12]}"
    tok = f"sess_barriotest_{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    db.users.insert_one({
        "user_id": uid,
        "email": f"TEST_barrio_{uid}@example.com",
        "name": name,
        "picture": "https://x/y.png",
        "gender": gender,
        "age": age,
        "profile_complete": True,
        "terms_version": TERMS_VERSION_CURRENT if accept_terms else None,
        "terms_accepted_at": now if accept_terms else None,
        "created_at": now,
    })
    db.user_sessions.insert_one({
        "session_token": tok,
        "user_id": uid,
        "created_at": now,
        "expires_at": now + timedelta(days=1),
    })
    return uid, tok


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    yield s
    # cleanup
    db.users.delete_many({"email": {"$regex": "^TEST_barrio_"}})
    db.user_sessions.delete_many({"session_token": {"$regex": "^sess_barriotest_"}})
    db.groups.delete_many({"title": {"$regex": "^TEST_BARRIO_"}})


# ============================================================ /api/ health

class TestRootMessageRenamed:
    def test_root_says_barrio_api(self, api):
        r = api.get(f"{BASE_URL}/api/")
        assert r.status_code == 200
        body = r.json()
        assert body == {"message": "Barrio API"}, f"unexpected root payload: {body}"


# ============================================================ T&C error contains 'Barrio'

def _future_date_time():
    dt = datetime.now(timezone.utc) + timedelta(days=10)
    return dt.strftime("%Y-%m-%d"), "18:00"


def _valid_group_payload(title: str):
    date, time_ = _future_date_time()
    return {
        "title": title,
        "category": "basketball",
        "category_label": "Basket",
        "location": "Parco Sempione",
        "city": "Milano",
        "description": "",
        "date": date,
        "time": time_,
        "min_participants": 3,
        "max_participants": 10,
        "min_age": 18,
        "max_age": 40,
        "gender_filter": "any",
    }


class TestTermsGateMentionsBarrio:
    def test_create_group_without_terms_rejects_with_barrio_in_message(self, api):
        uid, tok = _seed_user(accept_terms=False, age=25)
        headers = {"Authorization": f"Bearer {tok}",
                   "Content-Type": "application/json"}
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_valid_group_payload("TEST_BARRIO_no_terms"),
                     headers=headers)
        assert r.status_code == 403, r.text
        detail = (r.json().get("detail") or "").lower()
        assert "barrio" in detail, f"expected 'Barrio' in T&C detail, got: {detail!r}"
        assert "groupup" not in detail, f"legacy name leak: {detail!r}"

    def test_terms_version_endpoint_still_matches(self, api):
        r = api.get(f"{BASE_URL}/api/auth/terms-version")
        assert r.status_code == 200
        assert r.json() == {"version": TERMS_VERSION_CURRENT}


# ============================================================ auth token guard

class TestAuthTokenGuardIntact:
    def test_missing_bearer_401(self, api):
        r = api.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401

    def test_malformed_bearer_401(self, api):
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers={"Authorization": "Bearer !!!"})
        assert r.status_code == 401

    def test_unknown_wellformed_bearer_401(self, api):
        # 32-char hex passes regex but not in db
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers={"Authorization": f"Bearer {uuid.uuid4().hex}"})
        assert r.status_code == 401

    def test_valid_seeded_session_returns_user(self, api):
        uid, tok = _seed_user(accept_terms=True)
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user_id"] == uid
        assert body["terms_version"] == TERMS_VERSION_CURRENT

    def test_google_session_stub_rejects_bad_session_id(self, api):
        # Just make sure the endpoint still exists and validates input.
        r = api.post(f"{BASE_URL}/api/auth/session", json={"session_id": ""})
        assert r.status_code == 400
        r = api.post(f"{BASE_URL}/api/auth/session", json={"session_id": "short"})
        assert r.status_code == 400


# ============================================================ groups still work end-to-end

class TestGroupsHappyPath:
    def test_create_join_leave_cycle(self, api):
        owner_uid, owner_tok = _seed_user(accept_terms=True, age=28,
                                          name="Owner Barrio", gender="male")
        other_uid, other_tok = _seed_user(accept_terms=True, age=30,
                                          name="Joiner Barrio", gender="female")
        owner_h = {"Authorization": f"Bearer {owner_tok}",
                   "Content-Type": "application/json"}
        other_h = {"Authorization": f"Bearer {other_tok}",
                   "Content-Type": "application/json"}

        # create
        payload = _valid_group_payload("TEST_BARRIO_cycle")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_h)
        assert r.status_code == 200, r.text
        gid = r.json()["group_id"]
        assert r.json()["owner_id"] == owner_uid

        # join
        r = api.post(f"{BASE_URL}/api/groups/{gid}/join", headers=other_h)
        assert r.status_code == 200
        parts = [p["user_id"] for p in r.json()["participants"]]
        assert owner_uid in parts and other_uid in parts

        # leave (non-owner)
        r = api.post(f"{BASE_URL}/api/groups/{gid}/leave", headers=other_h)
        assert r.status_code == 200
        parts = [p["user_id"] for p in r.json()["participants"]]
        assert other_uid not in parts

        # delete by owner
        r = api.delete(f"{BASE_URL}/api/groups/{gid}", headers=owner_h)
        assert r.status_code == 200
        r = api.get(f"{BASE_URL}/api/groups/{gid}")
        assert r.status_code == 404

    def test_gender_filter_rejects_wrong_gender(self, api):
        # Owner female creates a female-only group; a male tries to join.
        owner_uid, owner_tok = _seed_user(accept_terms=True, gender="female",
                                          name="FOwner", age=26)
        male_uid, male_tok = _seed_user(accept_terms=True, gender="male",
                                        name="MJoin", age=27)
        owner_h = {"Authorization": f"Bearer {owner_tok}",
                   "Content-Type": "application/json"}
        payload = _valid_group_payload("TEST_BARRIO_female_only")
        payload["gender_filter"] = "female"
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_h)
        assert r.status_code == 200, r.text
        gid = r.json()["group_id"]

        r = api.post(f"{BASE_URL}/api/groups/{gid}/join",
                     headers={"Authorization": f"Bearer {male_tok}"})
        assert r.status_code == 403
        assert "donne" in r.json()["detail"].lower()

    def test_age_gate_rejects_minor_from_adult_group(self, api):
        adult_uid, adult_tok = _seed_user(accept_terms=True, age=28)
        minor_uid, minor_tok = _seed_user(accept_terms=True, age=15)
        adult_h = {"Authorization": f"Bearer {adult_tok}",
                   "Content-Type": "application/json"}
        payload = _valid_group_payload("TEST_BARRIO_adult_only")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=adult_h)
        assert r.status_code == 200
        gid = r.json()["group_id"]

        r = api.post(f"{BASE_URL}/api/groups/{gid}/join",
                     headers={"Authorization": f"Bearer {minor_tok}"})
        assert r.status_code == 403
        assert "maggiorenn" in r.json()["detail"].lower()


# ============================================================ admin still works

class TestAdmin:
    def test_admin_verify_requires_secret(self, api):
        r = api.get(f"{BASE_URL}/api/admin/verify")
        # No secret → 401 or 503 (if unset); both are acceptable "denied".
        assert r.status_code in (401, 503)

    def test_admin_verify_with_secret(self, api):
        secret = os.environ.get("ADMIN_SECRET", "").strip()
        if not secret:
            pytest.skip("ADMIN_SECRET not set on server")
        r = api.get(f"{BASE_URL}/api/admin/verify",
                    headers={"X-Admin-Secret": secret})
        assert r.status_code == 200
        assert r.json() == {"ok": True}


# ============================================================ reports still work

class TestReports:
    def test_report_group_and_dedupe(self, api):
        # owner creates a group, reporter reports it
        owner_uid, owner_tok = _seed_user(accept_terms=True, age=30)
        rep_uid, rep_tok = _seed_user(accept_terms=True, age=30,
                                      name="Reporter")
        owner_h = {"Authorization": f"Bearer {owner_tok}",
                   "Content-Type": "application/json"}
        rep_h = {"Authorization": f"Bearer {rep_tok}",
                 "Content-Type": "application/json"}
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_valid_group_payload("TEST_BARRIO_report"),
                     headers=owner_h)
        assert r.status_code == 200
        gid = r.json()["group_id"]

        r = api.post(f"{BASE_URL}/api/reports", headers=rep_h, json={
            "target_type": "group",
            "target_id": gid,
            "reason": "spam",
            "description": "TEST barrio report",
        })
        assert r.status_code == 200, r.text
        # dedupe
        r2 = api.post(f"{BASE_URL}/api/reports", headers=rep_h, json={
            "target_type": "group",
            "target_id": gid,
            "reason": "spam",
            "description": "",
        })
        assert r2.status_code == 409
        # cleanup
        db.reports.delete_many({"target_id": gid})
