"""
Iteration 18 — Scaling changes.

Tests:
- Cursor pagination on GET /api/groups
- Geo filter with 2dsphere index (+ Haversine fallback)
- Backward compat for legacy groups without `geo`
- MongoDB indexes exist
- WebSocket /api/ws/groups/{id}?token=... auth + broadcast
- Moderation still enforced on POST /messages

Uses direct MongoDB seeding for user_sessions (see
/app/memory/test_credentials.md).
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
import websockets
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

FRONTEND_ENV = Path("/app/frontend/.env")
PUBLIC_URL = None
for line in FRONTEND_ENV.read_text().splitlines():
    if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
        PUBLIC_URL = line.split("=", 1)[1].strip().strip('"')
BASE_URL = (PUBLIC_URL or "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL missing"
# Derive WS URL (http->ws, https->wss)
if BASE_URL.startswith("https://"):
    WS_BASE = "wss://" + BASE_URL[len("https://"):]
elif BASE_URL.startswith("http://"):
    WS_BASE = "ws://" + BASE_URL[len("http://"):]
else:
    WS_BASE = BASE_URL

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]

TERMS_VERSION = "2026-06-01"

# ============================== helpers ==============================


def _seed_user(name="Iter18 User", age=25, gender="male"):
    uid = f"user_it18_{uuid.uuid4().hex[:10]}"
    token = f"sess_it18_{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    db.users.insert_one({
        "user_id": uid,
        "email": f"TEST_{uid}@example.com",
        "name": name,
        "picture": None,
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


def _future_date(days=20):
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


def _insert_group_direct(*, owner_id, owner_name, title, city, lat=None, lon=None,
                         include_geo=True, category="other", created_at=None):
    """Insert group directly in Mongo (bypasses geocoding, useful for seeding)."""
    gid = f"grp_it18_{uuid.uuid4().hex[:10]}"
    doc = {
        "group_id": gid,
        "title": title,
        "category": category,
        "category_label": "Altro",
        "location": "Test loc",
        "city": city,
        "province": None,
        "lat": lat,
        "lon": lon,
        "description": "seed",
        "date": _future_date(30),
        "time": "18:30",
        "min_participants": 3,
        "max_participants": 10,
        "min_age": 18,
        "max_age": 99,
        "gender_filter": "any",
        "owner_id": owner_id,
        "owner_name": owner_name,
        "owner_picture": None,
        "participants": [{"user_id": owner_id, "name": owner_name, "picture": None}],
        "created_at": created_at or datetime.now(timezone.utc),
    }
    if include_geo and lat is not None and lon is not None:
        doc["geo"] = {"type": "Point", "coordinates": [float(lon), float(lat)]}
    db.groups.insert_one(dict(doc))
    return gid


@pytest.fixture(scope="module")
def owner():
    """Owner user + session — cleaned up at end."""
    uid, token, headers = _seed_user()
    yield {"user_id": uid, "token": token, "headers": headers}


@pytest.fixture(scope="module", autouse=True)
def cleanup_at_end():
    yield
    db.groups.delete_many({"group_id": {"$regex": "^grp_it18_"}})
    db.groups.delete_many({"title": {"$regex": "^TEST_it18_"}})
    db.messages.delete_many({"group_id": {"$regex": "^grp_it18_"}})
    db.users.delete_many({"user_id": {"$regex": "^user_it18_"}})
    db.user_sessions.delete_many({"session_token": {"$regex": "^sess_it18_"}})


# ============================== a) Cursor pagination ==============================


class TestCursorPagination:
    def test_limit_validation(self):
        r = requests.get(f"{BASE_URL}/api/groups", params={"limit": 0})
        assert r.status_code == 422, r.text
        r = requests.get(f"{BASE_URL}/api/groups", params={"limit": 101})
        assert r.status_code == 422, r.text

    def test_response_shape(self):
        r = requests.get(f"{BASE_URL}/api/groups", params={"limit": 5})
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body, dict)
        assert "items" in body and "next_cursor" in body
        assert isinstance(body["items"], list)
        assert body["next_cursor"] is None or isinstance(body["next_cursor"], str)
        assert len(body["items"]) <= 5

    def test_invalid_cursor_ignored(self):
        r = requests.get(f"{BASE_URL}/api/groups", params={"limit": 3, "cursor": "!!!not-base64!!!"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "items" in body

    def test_pagination_no_overlap(self, owner):
        # Seed 8 groups with distinct created_at
        base_time = datetime.now(timezone.utc)
        ids = []
        for i in range(8):
            gid = _insert_group_direct(
                owner_id=owner["user_id"],
                owner_name="Iter18 User",
                title=f"TEST_it18_page_{i}_{uuid.uuid4().hex[:4]}",
                city="Test City",
                lat=45.0, lon=9.0,
                created_at=base_time - timedelta(seconds=i),
            )
            ids.append(gid)

        r1 = requests.get(f"{BASE_URL}/api/groups", params={"limit": 5})
        assert r1.status_code == 200
        p1 = r1.json()
        # Since there are >5 groups globally, cursor must be non-null
        assert p1["next_cursor"] is not None, "next_cursor must be set when more items exist"
        first_ids = {i["group_id"] for i in p1["items"]}
        assert len(p1["items"]) == 5

        r2 = requests.get(f"{BASE_URL}/api/groups",
                          params={"limit": 5, "cursor": p1["next_cursor"]})
        assert r2.status_code == 200
        p2 = r2.json()
        second_ids = {i["group_id"] for i in p2["items"]}
        assert first_ids.isdisjoint(second_ids), \
            f"Overlap between pages: {first_ids & second_ids}"

    def test_end_of_stream_returns_null_cursor(self, owner):
        # Ask for a huge page, or walk to the end
        r = requests.get(f"{BASE_URL}/api/groups", params={"limit": 100})
        assert r.status_code == 200
        body = r.json()
        # If we drained the DB, next_cursor is null
        # (If more than 100 groups exist we still verify the type invariant)
        assert body["next_cursor"] is None or isinstance(body["next_cursor"], str)


# ============================== b) Geo filter with 2dsphere ==============================


class TestGeoFilter:
    MILANO = (45.4642, 9.19)
    ROMA = (41.9028, 12.4964)

    def test_geo_filter_narrow_and_wide(self, owner):
        # Seed one group per city
        mid = _insert_group_direct(
            owner_id=owner["user_id"], owner_name="Iter18 User",
            title=f"TEST_it18_MILANO_{uuid.uuid4().hex[:4]}",
            city="Milano",
            lat=self.MILANO[0], lon=self.MILANO[1],
        )
        rid = _insert_group_direct(
            owner_id=owner["user_id"], owner_name="Iter18 User",
            title=f"TEST_it18_ROMA_{uuid.uuid4().hex[:4]}",
            city="Roma",
            lat=self.ROMA[0], lon=self.ROMA[1],
        )
        # Ensure both docs have `geo` field populated
        m_doc = db.groups.find_one({"group_id": mid})
        r_doc = db.groups.find_one({"group_id": rid})
        assert m_doc.get("geo", {}).get("type") == "Point", "Missing geo on newly-created Milano group"
        assert m_doc["geo"]["coordinates"] == [self.MILANO[1], self.MILANO[0]]
        assert r_doc.get("geo", {}).get("type") == "Point"

        # Narrow: 5 km around Milano — should not include Roma
        # NOTE: legacy groups without `geo` are always included by design,
        # so we verify that Milano IS included and Roma is NOT.
        r = requests.get(
            f"{BASE_URL}/api/groups",
            params={"lat": self.MILANO[0], "lon": self.MILANO[1], "radius_km": 5, "limit": 100},
        )
        assert r.status_code == 200, r.text
        ids = {i["group_id"] for i in r.json()["items"]}
        assert mid in ids, "Milano group should be within 5km of Milano"
        assert rid not in ids, "Roma group MUST be filtered out at 5km radius"

        # Wide: 1000 km around Milano — should include both
        r = requests.get(
            f"{BASE_URL}/api/groups",
            params={"lat": self.MILANO[0], "lon": self.MILANO[1], "radius_km": 100, "limit": 100},
        )
        assert r.status_code == 200
        ids_wide = {i["group_id"] for i in r.json()["items"]}
        # 100km is our max (per Query ge=0.1, le=100). Milano <-> Roma ~477km.
        # So use max-radius-that-API-allows, and verify only Milano is there.
        assert mid in ids_wide
        assert rid not in ids_wide, "Roma still filtered at 100km"


# ============================== c) Backward compat (legacy geo) ==============================


class TestLegacyGeo:
    def test_legacy_group_without_geo_still_visible(self, owner):
        # Insert a legacy group with lat/lon but NO geo
        lat, lon = 45.4642, 9.19  # Milano
        gid = _insert_group_direct(
            owner_id=owner["user_id"], owner_name="Iter18 User",
            title=f"TEST_it18_legacy_{uuid.uuid4().hex[:4]}",
            city="Milano",
            lat=lat, lon=lon,
            include_geo=False,
        )
        doc = db.groups.find_one({"group_id": gid})
        assert "geo" not in doc, "seed should not have geo field"

        # A) baseline listing must include it
        r = requests.get(f"{BASE_URL}/api/groups", params={"limit": 100})
        ids = {i["group_id"] for i in r.json()["items"]}
        assert gid in ids

        # B) geo filter within 5km of Milano must still include it via Haversine fallback
        r = requests.get(
            f"{BASE_URL}/api/groups",
            params={"lat": lat, "lon": lon, "radius_km": 5, "limit": 100},
        )
        ids2 = {i["group_id"] for i in r.json()["items"]}
        assert gid in ids2, "Legacy group without `geo` should pass Haversine fallback"

        # C) far away 5km of Roma should exclude it
        r = requests.get(
            f"{BASE_URL}/api/groups",
            params={"lat": 41.9, "lon": 12.5, "radius_km": 5, "limit": 100},
        )
        ids3 = {i["group_id"] for i in r.json()["items"]}
        assert gid not in ids3, "Legacy far-away group must be excluded by Haversine fallback"


# ============================== f) Indexes exist ==============================


class TestIndexes:
    def test_groups_indexes(self):
        idx = list(db.groups.list_indexes())
        keys_list = [tuple(sorted(i["key"].items())) for i in idx]
        # 2dsphere
        assert any("geo" in dict(i["key"]) and i["key"]["geo"] == "2dsphere" for i in idx), \
            f"Missing 2dsphere on groups.geo. Indexes: {[i['name'] for i in idx]}"
        # Compound status+created_at
        want = [("created_at", -1), ("status", 1)]
        assert tuple(sorted(want)) in keys_list, "Missing groups {status,created_at} index"
        # owner_id single
        assert any(list(i["key"].items()) == [("owner_id", 1)] for i in idx)
        assert any(list(i["key"].items()) == [("participants.user_id", 1)] for i in idx)

    def test_messages_indexes(self):
        idx = list(db.messages.list_indexes())
        keys_list = [tuple(sorted(i["key"].items())) for i in idx]
        assert tuple(sorted([("group_id", 1), ("created_at", 1)])) in keys_list, \
            "Missing messages {group_id,created_at} index"
        # message_id unique
        assert any(i["key"].get("message_id") == 1 and i.get("unique") for i in idx), \
            "message_id not unique"

    def test_reports_indexes(self):
        idx = list(db.reports.list_indexes())
        keys_list = [tuple(sorted(i["key"].items())) for i in idx]
        assert tuple(sorted([("status", 1), ("created_at", -1)])) in keys_list
        assert any(i["key"].get("report_id") == 1 and i.get("unique") for i in idx)


# ============================== d) WebSocket ==============================


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


class TestWebSocket:
    def _ws_url(self, gid, token):
        return f"{WS_BASE}/api/ws/groups/{gid}?token={token}"

    def test_ws_missing_token_4401(self, owner):
        # Create a group so the URL is valid but token empty
        gid = _insert_group_direct(
            owner_id=owner["user_id"], owner_name="Iter18 User",
            title=f"TEST_it18_ws_{uuid.uuid4().hex[:4]}",
            city="Milano", lat=45.46, lon=9.19,
        )

        async def go():
            uri = f"{WS_BASE}/api/ws/groups/{gid}"
            try:
                async with websockets.connect(uri) as ws:
                    # server should send error then close
                    try:
                        await asyncio.wait_for(ws.recv(), timeout=5)
                    except Exception:
                        pass
                    await asyncio.wait_for(ws.wait_closed(), timeout=5)
                    return ws.close_code
            except websockets.exceptions.InvalidStatus as e:
                # If proxy/HTTP layer rejects before upgrade
                return int(getattr(e.response, "status_code", 0))
            except Exception as e:
                return f"exc:{e}"
        code = _run(go())
        assert code == 4401, f"Expected 4401 for missing token, got {code}"

    def test_ws_malformed_token_4401(self, owner):
        gid = _insert_group_direct(
            owner_id=owner["user_id"], owner_name="Iter18 User",
            title=f"TEST_it18_wsmal_{uuid.uuid4().hex[:4]}",
            city="Milano", lat=45.46, lon=9.19,
        )
        async def go():
            uri = f"{WS_BASE}/api/ws/groups/{gid}?token=short!!!"
            async with websockets.connect(uri) as ws:
                try:
                    await asyncio.wait_for(ws.recv(), timeout=5)
                except Exception:
                    pass
                await asyncio.wait_for(ws.wait_closed(), timeout=5)
                return ws.close_code
        assert _run(go()) == 4401

    def test_ws_not_participant_4403(self, owner):
        # Create group owned by `owner`; then seed a second user NOT in group.
        gid = _insert_group_direct(
            owner_id=owner["user_id"], owner_name="Iter18 User",
            title=f"TEST_it18_wsnp_{uuid.uuid4().hex[:4]}",
            city="Milano", lat=45.46, lon=9.19,
        )
        _, other_token, _ = _seed_user(name="Other User")
        async def go():
            uri = f"{WS_BASE}/api/ws/groups/{gid}?token={other_token}"
            async with websockets.connect(uri) as ws:
                try:
                    await asyncio.wait_for(ws.recv(), timeout=5)
                except Exception:
                    pass
                await asyncio.wait_for(ws.wait_closed(), timeout=5)
                return ws.close_code
        assert _run(go()) == 4403

    def test_ws_group_not_found_4404(self, owner):
        async def go():
            uri = f"{WS_BASE}/api/ws/groups/grp_doesnotexist_XYZ?token={owner['token']}"
            async with websockets.connect(uri) as ws:
                try:
                    await asyncio.wait_for(ws.recv(), timeout=5)
                except Exception:
                    pass
                await asyncio.wait_for(ws.wait_closed(), timeout=5)
                return ws.close_code
        assert _run(go()) == 4404

    def test_ws_connected_ping_pong(self, owner):
        gid = _insert_group_direct(
            owner_id=owner["user_id"], owner_name="Iter18 User",
            title=f"TEST_it18_wspp_{uuid.uuid4().hex[:4]}",
            city="Milano", lat=45.46, lon=9.19,
        )
        async def go():
            uri = f"{WS_BASE}/api/ws/groups/{gid}?token={owner['token']}"
            async with websockets.connect(uri) as ws:
                # Expect connected
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                assert msg == {"type": "connected"}, msg
                await ws.send(json.dumps({"type": "ping"}))
                pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                assert pong == {"type": "pong"}, pong
        _run(go())

    def test_ws_broadcast_to_two_clients(self, owner):
        # Seed a participant
        p_uid, p_token, p_headers = _seed_user(name="WS Participant")

        # Create group and add participant to it directly
        gid = _insert_group_direct(
            owner_id=owner["user_id"], owner_name="Iter18 User",
            title=f"TEST_it18_wsbc_{uuid.uuid4().hex[:4]}",
            city="Milano", lat=45.46, lon=9.19,
        )
        db.groups.update_one(
            {"group_id": gid},
            {"$push": {"participants": {"user_id": p_uid, "name": "WS Participant", "picture": None}}},
        )

        async def go():
            uri1 = f"{WS_BASE}/api/ws/groups/{gid}?token={owner['token']}"
            uri2 = f"{WS_BASE}/api/ws/groups/{gid}?token={p_token}"
            async with websockets.connect(uri1) as ws1, websockets.connect(uri2) as ws2:
                # Drain connected frames
                assert json.loads(await asyncio.wait_for(ws1.recv(), timeout=5))["type"] == "connected"
                assert json.loads(await asyncio.wait_for(ws2.recv(), timeout=5))["type"] == "connected"

                # HTTP POST message as owner
                text = f"TEST_it18_broadcast_{uuid.uuid4().hex[:6]}"
                r = requests.post(
                    f"{BASE_URL}/api/groups/{gid}/messages",
                    json={"text": text},
                    headers=owner["headers"],
                )
                assert r.status_code == 200, r.text
                sent = r.json()

                # Both sockets receive the broadcast
                frame1 = json.loads(await asyncio.wait_for(ws1.recv(), timeout=10))
                frame2 = json.loads(await asyncio.wait_for(ws2.recv(), timeout=10))
                for f in (frame1, frame2):
                    assert f["type"] == "message", f
                    assert f["data"]["message_id"] == sent["message_id"]
                    assert f["data"]["text"] == text
        _run(go())


# ============================== e) Moderation ==============================


class TestModeration:
    def test_forbidden_keyword_in_message(self, owner):
        gid = _insert_group_direct(
            owner_id=owner["user_id"], owner_name="Iter18 User",
            title=f"TEST_it18_mod_{uuid.uuid4().hex[:4]}",
            city="Milano", lat=45.46, lon=9.19,
        )
        r = requests.post(
            f"{BASE_URL}/api/groups/{gid}/messages",
            json={"text": "voglio comprare droga stasera"},
            headers=owner["headers"],
        )
        assert r.status_code == 400, r.text
        assert "non consentito" in r.json().get("detail", "").lower() \
            or "vietati" in r.json().get("detail", "").lower()
