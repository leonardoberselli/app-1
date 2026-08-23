"""
Iteration 12 tests: /api/cities/suggest (Photon) and street-removal in /api/groups.
"""
import os
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

SUGGEST_SLEEP = 1.2  # be polite to Photon
NOMINATIM_SLEEP = 1.3


def _new_device_id(prefix="TESTDEV"):
    return f"{prefix}_{uuid.uuid4().hex}"[:64]


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    yield s
    # cleanup groups seeded by these tests
    db.groups.delete_many({"title": {"$regex": "^TEST_it12_"}})
    db.users.delete_many({"user_id": {"$regex": "^(OWNERIT12_|TESTDEV_it12)"}})


@pytest.fixture(scope="module")
def owner_headers(api):
    did = _new_device_id("OWNERIT12")
    hdr = {"Authorization": f"Bearer {did}", "Content-Type": "application/json"}
    api.patch(f"{BASE_URL}/api/auth/me", json={"name": "Owner It12"}, headers=hdr)
    return hdr


def _group_payload(**over):
    future = datetime.now(timezone.utc) + timedelta(days=30)
    base = {
        "title": f"TEST_it12_{uuid.uuid4().hex[:6]}",
        "category": "basketball",
        "category_label": "Basket",
        "location": "Bar Rita",
        "city": "Milano",
        "province": "Milano",
        "lat": 45.4641,
        "lon": 9.1896,
        "description": "test iter12",
        "date": future.strftime("%Y-%m-%d"),
        "time": "18:30",
        "min_participants": 2,
        "max_participants": 10,
        "min_age": 18,
        "max_age": 40,
    }
    base.update(over)
    return base


# ================== /api/cities/suggest ==================

class TestCitiesSuggest:
    def test_suggest_mila_returns_milano(self, api):
        time.sleep(SUGGEST_SLEEP)
        r = api.get(f"{BASE_URL}/api/cities/suggest", params={"q": "mila"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list)
        assert len(data) > 0, f"expected suggestions for 'mila', got empty: {data}"
        # Milano expected in the list
        names = [d["name"] for d in data]
        assert any("Milano" == n for n in names), f"Milano not in {names}"
        milano = next(d for d in data if d["name"] == "Milano")
        assert milano["province"].lower().startswith("milan"), milano
        assert milano["region"] == "Lombardia", milano
        assert 45.0 <= milano["lat"] <= 46.0
        assert 8.5 <= milano["lon"] <= 9.6
        assert "display" in milano

    def test_suggest_correg_returns_correggio(self, api):
        time.sleep(SUGGEST_SLEEP)
        r = api.get(f"{BASE_URL}/api/cities/suggest", params={"q": "correg"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list) and len(data) > 0, data
        # At least one entry starts with "Correggio"
        assert any(d["name"].lower().startswith("correg") for d in data), data

    def test_suggest_rom_returns_roma(self, api):
        time.sleep(SUGGEST_SLEEP)
        r = api.get(f"{BASE_URL}/api/cities/suggest", params={"q": "rom"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data) > 0
        assert any(d["name"] == "Roma" for d in data), [d["name"] for d in data]

    def test_suggest_too_short_422(self, api):
        r = api.get(f"{BASE_URL}/api/cities/suggest", params={"q": "a"})
        assert r.status_code == 422

    def test_suggest_unknown_returns_empty(self, api):
        time.sleep(SUGGEST_SLEEP)
        r = api.get(f"{BASE_URL}/api/cities/suggest", params={"q": "zzzzz"})
        assert r.status_code == 200
        assert r.json() == []

    def test_suggest_missing_q_422(self, api):
        r = api.get(f"{BASE_URL}/api/cities/suggest")
        assert r.status_code == 422


# ================== POST /api/groups (street removed) ==================

class TestCreateGroupNoStreet:
    def test_create_without_street_ok(self, api, owner_headers):
        payload = _group_payload()
        # explicitly ensure no street key
        payload.pop("street", None)
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 200, r.text
        g = r.json()
        assert "street" not in g, f"street should not appear in response: {g}"
        assert g["city"] == "Milano"
        assert g["province"] == "Milano"
        assert g["lat"] is not None and g["lon"] is not None
        assert 45.3 <= g["lat"] <= 45.6
        assert 9.0 <= g["lon"] <= 9.3

    def test_create_with_client_provided_coords_no_geocode(self, api, owner_headers):
        payload = _group_payload(
            title=f"TEST_it12_coords_{uuid.uuid4().hex[:6]}",
            city="Milano", province="Milano",
            lat=45.4641, lon=9.1896,
        )
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 200, r.text
        g = r.json()
        assert g["lat"] == 45.4641
        assert g["lon"] == 9.1896
        assert g["province"] == "Milano"
        assert "street" not in g

    def test_create_without_city_400(self, api, owner_headers):
        payload = _group_payload(city="")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 400
        assert "citt" in r.json()["detail"].lower()

    def test_create_city_only_backend_geocodes(self, api, owner_headers):
        # No lat/lon supplied by client -> backend geocodes via Nominatim
        time.sleep(NOMINATIM_SLEEP)
        payload = _group_payload(
            title=f"TEST_it12_geo_{uuid.uuid4().hex[:6]}",
            city="Milano",
        )
        payload.pop("lat", None)
        payload.pop("lon", None)
        payload.pop("province", None)
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 200, r.text
        g = r.json()
        # Geocoding may fail transiently; when Nominatim works, we should
        # see coords in the Milan range.
        if g["lat"] is not None:
            assert 45.3 <= g["lat"] <= 45.6, g
            assert 9.0 <= g["lon"] <= 9.3, g

    def test_reject_moderation_in_city(self, api, owner_headers):
        payload = _group_payload(city="Cittadella droga")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 400
        assert "consentito" in r.json()["detail"].lower()

    def test_list_groups_geo_filter_includes_milano(self, api, owner_headers):
        # Ensure a milano group exists
        payload = _group_payload(
            title=f"TEST_it12_listmilano_{uuid.uuid4().hex[:6]}",
            city="Milano", province="Milano",
            lat=45.4641, lon=9.1896,
        )
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 200
        gid = r.json()["group_id"]
        # Query with geo filter around Milan
        r = api.get(f"{BASE_URL}/api/groups",
                    params={"lat": 45.464, "lon": 9.19, "radius_km": 5})
        assert r.status_code == 200
        ids = [g["group_id"] for g in r.json()]
        assert gid in ids


# ================== Regression: existing endpoints ==================

class TestRegression:
    def test_auth_me_still_works(self, api, owner_headers):
        r = api.get(f"{BASE_URL}/api/auth/me", headers=owner_headers)
        assert r.status_code == 200
        assert r.json()["name"] == "Owner It12"

    def test_get_group_by_id_still_works(self, api, owner_headers):
        payload = _group_payload(title=f"TEST_it12_reg_{uuid.uuid4().hex[:6]}")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        assert r.status_code == 200
        gid = r.json()["group_id"]
        r = api.get(f"{BASE_URL}/api/groups/{gid}")
        assert r.status_code == 200
        assert r.json()["group_id"] == gid

    def test_join_group_still_works(self, api, owner_headers):
        payload = _group_payload(title=f"TEST_it12_join_{uuid.uuid4().hex[:6]}")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        gid = r.json()["group_id"]
        other = _new_device_id("TESTDEV_it12")
        hdr = {"Authorization": f"Bearer {other}", "Content-Type": "application/json"}
        api.patch(f"{BASE_URL}/api/auth/me", json={"name": "Joiner12"}, headers=hdr)
        r = api.post(f"{BASE_URL}/api/groups/{gid}/join", headers=hdr)
        assert r.status_code == 200
        assert any(p["user_id"] == other for p in r.json()["participants"])

    def test_messages_still_work(self, api, owner_headers):
        payload = _group_payload(title=f"TEST_it12_msg_{uuid.uuid4().hex[:6]}")
        r = api.post(f"{BASE_URL}/api/groups", json=payload, headers=owner_headers)
        gid = r.json()["group_id"]
        r = api.post(f"{BASE_URL}/api/groups/{gid}/messages",
                     json={"text": "TEST_it12_hello"}, headers=owner_headers)
        assert r.status_code == 200
        assert r.json()["text"] == "TEST_it12_hello"

    def test_geocode_endpoint_still_works(self, api):
        time.sleep(NOMINATIM_SLEEP)
        r = api.get(f"{BASE_URL}/api/geocode", params={"city": "Milano"})
        assert r.status_code == 200
        body = r.json()
        assert "lat" in body and "lon" in body
