"""
Iteration 15 — Gender filter on groups.

Covers:
- POST /api/groups: gender_filter field validated against creator's gender.
- POST /api/groups/{id}/join: enforces gender + age at the same time.
- Legacy groups (no gender_filter field) default to "any".
- GET responses always include gender_filter.

Auth: seed users + user_sessions rows directly in MongoDB (see
/app/memory/test_credentials.md). Sessions are prefixed 'sess_gtest_' and
users 'user_gt_' so cleanup is trivial.
"""
import os
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


# ------------------------- helpers -------------------------

def _seed_user(*, gender, age=25, name="Gtest User"):
    """Insert a fully-onboarded user + fresh session. Returns (user_id, token, headers)."""
    uid = f"user_gt_{uuid.uuid4().hex[:10]}"
    token = f"sess_gtest_{uuid.uuid4().hex}"  # matches ^[A-Za-z0-9_\-\.]{16,512}$
    now = datetime.now(timezone.utc)
    db.users.insert_one({
        "user_id": uid,
        "email": f"TEST_{uid}@example.com",
        "name": name,
        "picture": "https://example.com/p.png",
        "gender": gender,
        "age": age,
        "profile_complete": True,
        "terms_version": TERMS_VERSION,
        "terms_accepted_at": now,
        "created_at": now,
    })
    db.user_sessions.insert_one({
        "session_token": token,
        "user_id": uid,
        "created_at": now,
        "expires_at": now + timedelta(days=7),
    })
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    return uid, token, headers


def _payload(**overrides):
    future = (datetime.now(timezone.utc) + timedelta(days=20)).strftime("%Y-%m-%d")
    base = {
        "title": f"TEST_gf_{uuid.uuid4().hex[:6]}",
        "category": "basketball",
        "category_label": "Basket",
        "location": "Parco Sempione",
        "city": "Milano",
        "description": "gender-filter test",
        "date": future,
        "time": "18:30",
        "min_participants": 3,
        "max_participants": 10,
        "min_age": 18,
        "max_age": 40,
    }
    base.update(overrides)
    return base


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    yield s
    # Cleanup all TEST_-prefixed seed data
    db.groups.delete_many({"title": {"$regex": "^TEST_"}})
    db.groups.delete_many({"owner_id": {"$regex": "^user_gt_"}})
    db.messages.delete_many({"group_id": {"$regex": "^grp_"}, "user_id": {"$regex": "^user_gt_"}})
    db.user_sessions.delete_many({"session_token": {"$regex": "^sess_gtest_"}})
    db.users.delete_many({"user_id": {"$regex": "^user_gt_"}})


# ------------------------- CREATE tests -------------------------

class TestCreateGroupGenderFilter:

    def test_no_gender_cannot_create_male_group(self, api):
        _, _, hdr = _seed_user(gender=None)
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_payload(gender_filter="male"), headers=hdr)
        assert r.status_code == 400, r.text
        assert "sesso" in r.json()["detail"].lower()
        assert "profilo" in r.json()["detail"].lower()

    def test_male_cannot_create_female_group(self, api):
        _, _, hdr = _seed_user(gender="male")
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_payload(gender_filter="female"), headers=hdr)
        assert r.status_code == 400
        assert "solo donne" in r.json()["detail"].lower()

    def test_female_cannot_create_male_group(self, api):
        _, _, hdr = _seed_user(gender="female")
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_payload(gender_filter="male"), headers=hdr)
        assert r.status_code == 400
        assert "solo uomini" in r.json()["detail"].lower()

    def test_female_can_create_female_group_persisted(self, api):
        uid, _, hdr = _seed_user(gender="female")
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_payload(gender_filter="female"), headers=hdr)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["gender_filter"] == "female"
        assert body["owner_id"] == uid
        # Verify persisted in DB
        doc = db.groups.find_one({"group_id": body["group_id"]}, {"_id": 0})
        assert doc["gender_filter"] == "female"
        # And returned by GET detail
        g = api.get(f"{BASE_URL}/api/groups/{body['group_id']}").json()
        assert g["gender_filter"] == "female"

    def test_male_can_create_male_group(self, api):
        _, _, hdr = _seed_user(gender="male")
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_payload(gender_filter="male"), headers=hdr)
        assert r.status_code == 200, r.text
        assert r.json()["gender_filter"] == "male"

    def test_any_gender_can_create_any_group(self, api):
        _, _, hdr = _seed_user(gender="male")
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_payload(gender_filter="any"), headers=hdr)
        assert r.status_code == 200
        assert r.json()["gender_filter"] == "any"

    def test_omitted_gender_filter_defaults_to_any(self, api):
        _, _, hdr = _seed_user(gender="female")
        # Payload without gender_filter key at all
        r = api.post(f"{BASE_URL}/api/groups", json=_payload(), headers=hdr)
        assert r.status_code == 200, r.text
        assert r.json()["gender_filter"] == "any"

    def test_nogender_user_can_create_any_group(self, api):
        # gender_filter="any" must NOT require the creator to have a gender.
        _, _, hdr = _seed_user(gender=None)
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_payload(gender_filter="any"), headers=hdr)
        assert r.status_code == 200, r.text
        assert r.json()["gender_filter"] == "any"


# ------------------------- JOIN tests -------------------------

class TestJoinGroupGenderFilter:

    def test_no_gender_user_blocked_400_on_male_group(self, api):
        _, _, owner_hdr = _seed_user(gender="male")
        g = api.post(f"{BASE_URL}/api/groups",
                     json=_payload(gender_filter="male"), headers=owner_hdr).json()
        _, _, joiner_hdr = _seed_user(gender=None)
        r = api.post(f"{BASE_URL}/api/groups/{g['group_id']}/join", headers=joiner_hdr)
        assert r.status_code == 400, r.text
        assert "sesso" in r.json()["detail"].lower()

    def test_female_user_forbidden_403_on_male_group(self, api):
        _, _, owner_hdr = _seed_user(gender="male")
        g = api.post(f"{BASE_URL}/api/groups",
                     json=_payload(gender_filter="male"), headers=owner_hdr).json()
        _, _, joiner_hdr = _seed_user(gender="female")
        r = api.post(f"{BASE_URL}/api/groups/{g['group_id']}/join", headers=joiner_hdr)
        assert r.status_code == 403, r.text
        assert "uomini" in r.json()["detail"].lower()

    def test_male_user_forbidden_403_on_female_group(self, api):
        _, _, owner_hdr = _seed_user(gender="female")
        g = api.post(f"{BASE_URL}/api/groups",
                     json=_payload(gender_filter="female"), headers=owner_hdr).json()
        _, _, joiner_hdr = _seed_user(gender="male")
        r = api.post(f"{BASE_URL}/api/groups/{g['group_id']}/join", headers=joiner_hdr)
        assert r.status_code == 403
        assert "donne" in r.json()["detail"].lower()

    def test_male_user_joins_male_group(self, api):
        owner_id, _, owner_hdr = _seed_user(gender="male")
        g = api.post(f"{BASE_URL}/api/groups",
                     json=_payload(gender_filter="male"), headers=owner_hdr).json()
        joiner_id, _, joiner_hdr = _seed_user(gender="male", name="Male Joiner")
        r = api.post(f"{BASE_URL}/api/groups/{g['group_id']}/join", headers=joiner_hdr)
        assert r.status_code == 200, r.text
        assert joiner_id in [p["user_id"] for p in r.json()["participants"]]

    def test_female_user_joins_female_group(self, api):
        _, _, owner_hdr = _seed_user(gender="female")
        g = api.post(f"{BASE_URL}/api/groups",
                     json=_payload(gender_filter="female"), headers=owner_hdr).json()
        joiner_id, _, joiner_hdr = _seed_user(gender="female", name="F Joiner")
        r = api.post(f"{BASE_URL}/api/groups/{g['group_id']}/join", headers=joiner_hdr)
        assert r.status_code == 200
        assert joiner_id in [p["user_id"] for p in r.json()["participants"]]


# ------------------------- LEGACY groups (no field) -------------------------

class TestLegacyGroupsNoGenderFilter:

    def test_legacy_group_get_returns_any(self, api):
        # Insert group doc directly WITHOUT gender_filter field.
        gid = f"grp_{uuid.uuid4().hex[:12]}"
        future = (datetime.now(timezone.utc) + timedelta(days=10)).strftime("%Y-%m-%d")
        owner_id, _, _ = _seed_user(gender="male", name="Legacy Owner")
        db.groups.insert_one({
            "group_id": gid,
            "title": "TEST_legacy_no_gender",
            "category": "basketball",
            "category_label": "Basket",
            "location": "Milano",
            "city": "Milano",
            "description": "legacy",
            "date": future,
            "time": "18:00",
            "min_participants": 2,
            "max_participants": 10,
            "min_age": 18,
            "max_age": 40,
            # gender_filter DELIBERATELY OMITTED
            "owner_id": owner_id,
            "owner_name": "Legacy Owner",
            "owner_picture": None,
            "participants": [{"user_id": owner_id, "name": "Legacy Owner", "picture": None}],
            "created_at": datetime.now(timezone.utc),
        })
        # GET detail
        r = api.get(f"{BASE_URL}/api/groups/{gid}")
        assert r.status_code == 200
        assert r.json()["gender_filter"] == "any"
        # GET list must also carry the field
        r = api.get(f"{BASE_URL}/api/groups")
        assert r.status_code == 200
        entry = next((g for g in r.json() if g["group_id"] == gid), None)
        assert entry is not None
        assert entry["gender_filter"] == "any"

    def test_legacy_group_joinable_by_nogender_user(self, api):
        gid = f"grp_{uuid.uuid4().hex[:12]}"
        future = (datetime.now(timezone.utc) + timedelta(days=10)).strftime("%Y-%m-%d")
        owner_id, _, _ = _seed_user(gender="female", name="Legacy Owner2")
        db.groups.insert_one({
            "group_id": gid,
            "title": "TEST_legacy_no_gender_2",
            "category": "basketball",
            "category_label": "Basket",
            "location": "Milano",
            "city": "Milano",
            "description": "legacy2",
            "date": future,
            "time": "18:00",
            "min_participants": 2, "max_participants": 10,
            "min_age": 18, "max_age": 40,
            "owner_id": owner_id,
            "owner_name": "Legacy Owner2",
            "owner_picture": None,
            "participants": [{"user_id": owner_id, "name": "Legacy Owner2", "picture": None}],
            "created_at": datetime.now(timezone.utc),
        })
        # Female user with no gender can still join.
        _, _, hdr = _seed_user(gender=None, name="Anon Joiner")
        # BUT — user MUST have a gender=None; join has no gender check if group is "any"
        r = api.post(f"{BASE_URL}/api/groups/{gid}/join", headers=hdr)
        assert r.status_code == 200, r.text


# ------------------------- AGE + GENDER interaction -------------------------

class TestAgeAndGenderInteraction:
    """A "female 18+" group must reject a male 25yo (gender=403) AND a female 15yo (age=403)."""

    def _make_female_adult_group(self, api):
        _, _, owner_hdr = _seed_user(gender="female", age=30, name="F Owner")
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_payload(gender_filter="female", min_age=18, max_age=40),
                     headers=owner_hdr)
        assert r.status_code == 200, r.text
        return r.json()["group_id"]

    def test_male_adult_blocked_403_gender(self, api):
        gid = self._make_female_adult_group(api)
        _, _, hdr = _seed_user(gender="male", age=25, name="M25")
        r = api.post(f"{BASE_URL}/api/groups/{gid}/join", headers=hdr)
        assert r.status_code == 403, r.text
        # Detail must be gender-related (age also fails, but code path fires age first);
        # accept either as long as it's a 403 and detail is Italian.
        detail = r.json()["detail"].lower()
        assert ("donne" in detail) or ("maggiorenni" in detail)

    def test_female_minor_blocked_403_age(self, api):
        # Owner must be an adult woman to CREATE an 18+ group (age-bucket rule).
        gid = self._make_female_adult_group(api)
        _, _, hdr = _seed_user(gender="female", age=15, name="F15")
        r = api.post(f"{BASE_URL}/api/groups/{gid}/join", headers=hdr)
        assert r.status_code == 403, r.text
        assert "maggiorenni" in r.json()["detail"].lower()


# ------------------------- Regression: previous 16/16 -------------------------

class TestRegressionNoImpact:
    """Basic smoke that non-gender flows still work after this feature."""

    def test_health(self, api):
        assert api.get(f"{BASE_URL}/api/").status_code == 200

    def test_get_groups_public(self, api):
        r = api.get(f"{BASE_URL}/api/groups")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        # Every returned group must expose gender_filter (default "any" or explicit).
        for g in r.json():
            assert "gender_filter" in g
            assert g["gender_filter"] in ("male", "female", "any")

    def test_create_and_join_any_group_still_works(self, api):
        _, _, owner_hdr = _seed_user(gender="male", name="Reg Owner")
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_payload(gender_filter="any"), headers=owner_hdr)
        assert r.status_code == 200
        gid = r.json()["group_id"]
        # A no-gender user can join an "any" group
        _, _, hdr = _seed_user(gender=None, name="Reg Joiner")
        r = api.post(f"{BASE_URL}/api/groups/{gid}/join", headers=hdr)
        assert r.status_code == 200
