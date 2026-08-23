"""
Iteration 13 - Reports & Admin Moderation panel.

Covers:
  - POST /api/reports (auth, target existence, dedupe, happy path per target_type)
  - GET  /api/admin/verify (auth via X-Admin-Secret)
  - GET  /api/admin/stats
  - GET  /api/admin/reports?status=...
  - PATCH /api/admin/reports/{id}
  - DELETE /api/admin/groups/{id}       (+ cascade messages, mark reports reviewed)
  - DELETE /api/admin/messages/{id}      (+ mark related message-reports reviewed)
  - DELETE /api/admin/users/{id}         (+ cascade owned groups, participants, msgs)
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

FRONTEND_ENV = Path("/app/frontend/.env")
PUBLIC_URL = None
for _line in FRONTEND_ENV.read_text().splitlines():
    if _line.startswith("EXPO_PUBLIC_BACKEND_URL="):
        PUBLIC_URL = _line.split("=", 1)[1].strip().strip('"')
BASE_URL = (PUBLIC_URL or "http://localhost:8001").rstrip("/")

ADMIN_SECRET = os.environ["ADMIN_SECRET"]

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]


# --------------------------- Helpers ---------------------------

def _new_device(prefix="TESTREP"):
    return f"{prefix}_{uuid.uuid4().hex}"[:64]


def _headers(did):
    return {"Authorization": f"Bearer {did}", "Content-Type": "application/json"}


def _future_date():
    d = datetime.now(timezone.utc) + timedelta(days=30)
    return d.strftime("%Y-%m-%d")


def _group_payload(title=None):
    return {
        "title": title or f"TEST_rep_grp_{uuid.uuid4().hex[:6]}",
        "category": "basketball",
        "category_label": "Basket",
        "location": "Parco",
        "city": "Milano",
        "description": "TEST reports iteration",
        "date": _future_date(),
        "time": "18:30",
        "min_participants": 3,
        "max_participants": 10,
        "min_age": 18,
        "max_age": 40,
    }


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    yield s
    # cleanup any residual TESTREP data
    db.reports.delete_many({"reporter_id": {"$regex": "^TESTREP"}})
    db.reports.delete_many({"target_id": {"$regex": "^(TESTREP|grp_)"}})
    db.groups.delete_many({"title": {"$regex": "^TEST_rep_"}})
    db.messages.delete_many({"text": {"$regex": "^TEST_rep_"}})
    db.users.delete_many({"user_id": {"$regex": "^TESTREP"}})


@pytest.fixture(scope="module")
def alice(api):
    """Group owner + first user."""
    did = _new_device("TESTREP_ALICE")
    api.patch(f"{BASE_URL}/api/auth/me",
              json={"name": "Alice Owner"}, headers=_headers(did))
    return did


@pytest.fixture(scope="module")
def bob(api):
    """Group joiner + reporter."""
    did = _new_device("TESTREP_BOB")
    api.patch(f"{BASE_URL}/api/auth/me",
              json={"name": "Bob Reporter"}, headers=_headers(did))
    return did


@pytest.fixture(scope="module")
def group(api, alice, bob):
    r = api.post(f"{BASE_URL}/api/groups",
                 json=_group_payload(), headers=_headers(alice))
    assert r.status_code == 200, r.text
    gid = r.json()["group_id"]
    # bob joins
    r = api.post(f"{BASE_URL}/api/groups/{gid}/join", headers=_headers(bob))
    assert r.status_code == 200
    return gid


@pytest.fixture(scope="module")
def alice_message(api, alice, group):
    r = api.post(f"{BASE_URL}/api/groups/{group}/messages",
                 json={"text": "TEST_rep_hi_from_alice"},
                 headers=_headers(alice))
    assert r.status_code == 200, r.text
    return r.json()["message_id"]


ADMIN_HEADERS = {"X-Admin-Secret": ADMIN_SECRET, "Content-Type": "application/json"}


# =========================================================
# POST /api/reports
# =========================================================
class TestReportsCreate:
    def test_missing_auth_401(self, api):
        r = api.post(f"{BASE_URL}/api/reports",
                     json={"target_type": "group", "target_id": "grp_x",
                           "reason": "spam"})
        assert r.status_code == 401

    def test_target_not_found_404(self, api, bob):
        r = api.post(f"{BASE_URL}/api/reports",
                     json={"target_type": "group",
                           "target_id": "grp_doesnotexist",
                           "reason": "spam"},
                     headers=_headers(bob))
        assert r.status_code == 404

    def test_invalid_reason_422(self, api, bob, group):
        r = api.post(f"{BASE_URL}/api/reports",
                     json={"target_type": "group", "target_id": group,
                           "reason": "banana"},
                     headers=_headers(bob))
        assert r.status_code == 422

    def test_invalid_target_type_422(self, api, bob, group):
        r = api.post(f"{BASE_URL}/api/reports",
                     json={"target_type": "planet", "target_id": group,
                           "reason": "spam"},
                     headers=_headers(bob))
        assert r.status_code == 422

    def test_report_group_ok(self, api, bob, group):
        r = api.post(f"{BASE_URL}/api/reports",
                     json={"target_type": "group", "target_id": group,
                           "reason": "spam", "description": "test-desc"},
                     headers=_headers(bob))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["target_type"] == "group"
        assert body["target_id"] == group
        assert body["reason"] == "spam"
        assert body["status"] == "pending"
        assert body["reporter_id"] == bob
        assert body["reporter_name"] == "Bob Reporter"
        assert body["report_id"].startswith("rep_")
        pytest.rep_group_id = body["report_id"]

    def test_duplicate_report_conflict_409(self, api, bob, group):
        r = api.post(f"{BASE_URL}/api/reports",
                     json={"target_type": "group", "target_id": group,
                           "reason": "spam"},
                     headers=_headers(bob))
        assert r.status_code == 409
        assert "già segnalato" in r.json()["detail"].lower()

    def test_report_user_ok(self, api, bob, alice):
        r = api.post(f"{BASE_URL}/api/reports",
                     json={"target_type": "user", "target_id": alice,
                           "reason": "harassment"},
                     headers=_headers(bob))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["target_type"] == "user" and body["target_id"] == alice
        assert body["status"] == "pending"
        pytest.rep_user_id = body["report_id"]

    def test_report_message_ok(self, api, bob, alice_message):
        r = api.post(f"{BASE_URL}/api/reports",
                     json={"target_type": "message",
                           "target_id": alice_message,
                           "reason": "harassment",
                           "description": "cattivo"},
                     headers=_headers(bob))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["target_type"] == "message"
        assert body["target_id"] == alice_message
        pytest.rep_msg_id = body["report_id"]

    def test_report_user_not_found_404(self, api, bob):
        r = api.post(f"{BASE_URL}/api/reports",
                     json={"target_type": "user",
                           "target_id": "TESTREP_neverexisted999",
                           "reason": "spam"},
                     headers=_headers(bob))
        assert r.status_code == 404

    def test_report_persisted_via_mine(self, api, bob):
        r = api.get(f"{BASE_URL}/api/reports/mine", headers=_headers(bob))
        assert r.status_code == 200
        ids = [x["report_id"] for x in r.json()]
        assert pytest.rep_group_id in ids
        assert pytest.rep_user_id in ids
        assert pytest.rep_msg_id in ids


# =========================================================
# Admin auth
# =========================================================
class TestAdminAuth:
    def test_verify_missing_header_401(self, api):
        r = api.get(f"{BASE_URL}/api/admin/verify")
        assert r.status_code == 401

    def test_verify_wrong_secret_401(self, api):
        r = api.get(f"{BASE_URL}/api/admin/verify",
                    headers={"X-Admin-Secret": "not-the-secret"})
        assert r.status_code == 401

    def test_verify_correct_secret_200(self, api):
        r = api.get(f"{BASE_URL}/api/admin/verify", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_stats_wrong_secret_401(self, api):
        r = api.get(f"{BASE_URL}/api/admin/stats",
                    headers={"X-Admin-Secret": "wrong"})
        assert r.status_code == 401

    def test_stats_ok(self, api):
        r = api.get(f"{BASE_URL}/api/admin/stats", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        body = r.json()
        for k in ("pending", "reviewed", "dismissed", "users", "groups"):
            assert k in body
            assert isinstance(body[k], int)


# =========================================================
# Admin list reports + snapshot
# =========================================================
class TestAdminListReports:
    def test_list_pending_wrong_secret_401(self, api):
        r = api.get(f"{BASE_URL}/api/admin/reports?status=pending",
                    headers={"X-Admin-Secret": "nope"})
        assert r.status_code == 401

    def test_list_pending_contains_our_reports(self, api):
        r = api.get(f"{BASE_URL}/api/admin/reports?status=pending",
                    headers=ADMIN_HEADERS)
        assert r.status_code == 200, r.text
        items = r.json()
        ids = [i["report_id"] for i in items]
        assert pytest.rep_group_id in ids
        assert pytest.rep_user_id in ids
        assert pytest.rep_msg_id in ids

    def test_snapshot_group(self, api, group):
        r = api.get(f"{BASE_URL}/api/admin/reports?status=pending",
                    headers=ADMIN_HEADERS)
        assert r.status_code == 200
        rep = next(i for i in r.json() if i["report_id"] == pytest.rep_group_id)
        assert rep["target_exists"] is True
        snap = rep["target_snapshot"]
        assert snap is not None
        assert snap["city"] == "Milano"
        assert snap["title"].startswith("TEST_rep_grp_")
        assert snap["participants_count"] >= 2

    def test_snapshot_user(self, api, alice):
        r = api.get(f"{BASE_URL}/api/admin/reports?status=pending",
                    headers=ADMIN_HEADERS)
        rep = next(i for i in r.json() if i["report_id"] == pytest.rep_user_id)
        assert rep["target_exists"] is True
        assert rep["target_snapshot"]["name"] == "Alice Owner"

    def test_snapshot_message(self, api, group):
        r = api.get(f"{BASE_URL}/api/admin/reports?status=pending",
                    headers=ADMIN_HEADERS)
        rep = next(i for i in r.json() if i["report_id"] == pytest.rep_msg_id)
        assert rep["target_exists"] is True
        snap = rep["target_snapshot"]
        assert snap["text"] == "TEST_rep_hi_from_alice"
        assert snap["group_id"] == group

    def test_list_all_returns_all_statuses(self, api):
        r = api.get(f"{BASE_URL}/api/admin/reports?status=all",
                    headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert len(r.json()) >= 3


# =========================================================
# PATCH /api/admin/reports/{id}
# =========================================================
class TestAdminPatchReport:
    def test_wrong_secret_401(self, api):
        r = api.patch(f"{BASE_URL}/api/admin/reports/rep_none",
                      json={"status": "dismissed"},
                      headers={"X-Admin-Secret": "nope"})
        assert r.status_code == 401

    def test_report_not_found_404(self, api):
        r = api.patch(f"{BASE_URL}/api/admin/reports/rep_notthere",
                      json={"status": "reviewed"},
                      headers=ADMIN_HEADERS)
        assert r.status_code == 404

    def test_invalid_status_422(self, api):
        r = api.patch(
            f"{BASE_URL}/api/admin/reports/{pytest.rep_user_id}",
            json={"status": "banned"},
            headers=ADMIN_HEADERS,
        )
        assert r.status_code == 422

    def test_dismiss_user_report(self, api):
        r = api.patch(
            f"{BASE_URL}/api/admin/reports/{pytest.rep_user_id}",
            json={"status": "dismissed"},
            headers=ADMIN_HEADERS,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "dismissed"

        # verify via list filter
        r = api.get(f"{BASE_URL}/api/admin/reports?status=dismissed",
                    headers=ADMIN_HEADERS)
        assert pytest.rep_user_id in [x["report_id"] for x in r.json()]

        # and no longer under pending
        r = api.get(f"{BASE_URL}/api/admin/reports?status=pending",
                    headers=ADMIN_HEADERS)
        assert pytest.rep_user_id not in [x["report_id"] for x in r.json()]


# =========================================================
# DELETE /api/admin/messages/{id}
# =========================================================
class TestAdminDeleteMessage:
    def test_wrong_secret_401(self, api, alice_message):
        r = api.delete(f"{BASE_URL}/api/admin/messages/{alice_message}",
                       headers={"X-Admin-Secret": "nope"})
        assert r.status_code == 401

    def test_message_not_found_404(self, api):
        r = api.delete(f"{BASE_URL}/api/admin/messages/msg_none",
                       headers=ADMIN_HEADERS)
        assert r.status_code == 404

    def test_delete_message_and_mark_reports_reviewed(self, api, alice_message):
        # confirm message + pending report exist
        assert db.messages.count_documents({"message_id": alice_message}) == 1
        rep = db.reports.find_one({"report_id": pytest.rep_msg_id})
        assert rep and rep["status"] == "pending"

        r = api.delete(f"{BASE_URL}/api/admin/messages/{alice_message}",
                       headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["deleted_message"] == alice_message

        # DB verifications
        assert db.messages.count_documents({"message_id": alice_message}) == 0
        rep_after = db.reports.find_one({"report_id": pytest.rep_msg_id})
        assert rep_after["status"] == "reviewed"


# =========================================================
# DELETE /api/admin/groups/{id}
# =========================================================
class TestAdminDeleteGroup:
    def test_wrong_secret_401(self, api):
        r = api.delete(f"{BASE_URL}/api/admin/groups/grp_x",
                       headers={"X-Admin-Secret": "nope"})
        assert r.status_code == 401

    def test_not_found_404(self, api):
        r = api.delete(f"{BASE_URL}/api/admin/groups/grp_none",
                       headers=ADMIN_HEADERS)
        assert r.status_code == 404

    def test_delete_group_cascade(self, api, alice, bob, group):
        # add another message to verify cascade
        r = api.post(f"{BASE_URL}/api/groups/{group}/messages",
                     json={"text": "TEST_rep_second_msg"},
                     headers=_headers(bob))
        assert r.status_code == 200
        m2 = r.json()["message_id"]

        # sanity: pending report for group exists
        rep = db.reports.find_one({"report_id": pytest.rep_group_id})
        assert rep and rep["status"] == "pending"

        r = api.delete(f"{BASE_URL}/api/admin/groups/{group}",
                       headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["deleted_group"] == group

        # Group gone
        assert db.groups.count_documents({"group_id": group}) == 0
        # Messages gone
        assert db.messages.count_documents({"group_id": group}) == 0
        assert db.messages.count_documents({"message_id": m2}) == 0
        # Related group-report is now reviewed
        rep_after = db.reports.find_one({"report_id": pytest.rep_group_id})
        assert rep_after["status"] == "reviewed"


# =========================================================
# DELETE /api/admin/users/{id}  (ban)
# =========================================================
class TestAdminDeleteUser:
    def test_wrong_secret_401(self, api):
        r = api.delete(f"{BASE_URL}/api/admin/users/TESTREP_none12345",
                       headers={"X-Admin-Secret": "nope"})
        assert r.status_code == 401

    def test_invalid_id_400(self, api):
        r = api.delete(f"{BASE_URL}/api/admin/users/x",
                       headers=ADMIN_HEADERS)
        assert r.status_code == 400

    def test_not_found_404(self, api):
        r = api.delete(f"{BASE_URL}/api/admin/users/TESTREP_nobodyhere",
                       headers=ADMIN_HEADERS)
        assert r.status_code == 404

    def test_delete_user_cascade(self, api):
        # Build a self-contained scenario: two users, one group, messages, one pending user-report.
        u_owner = _new_device("TESTREP_BANOWN")
        u_other = _new_device("TESTREP_BANOTH")
        u_reporter = _new_device("TESTREP_BANRPT")
        api.patch(f"{BASE_URL}/api/auth/me",
                  json={"name": "Ban Owner"}, headers=_headers(u_owner))
        api.patch(f"{BASE_URL}/api/auth/me",
                  json={"name": "Ban Other"}, headers=_headers(u_other))
        api.patch(f"{BASE_URL}/api/auth/me",
                  json={"name": "Reporter"}, headers=_headers(u_reporter))

        # Group owned by u_owner, u_other joins
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_rep_ban_owned"),
                     headers=_headers(u_owner))
        gid_owned = r.json()["group_id"]
        api.post(f"{BASE_URL}/api/groups/{gid_owned}/join",
                 headers=_headers(u_other))

        # Group owned by u_other, u_owner joins (so u_owner shows in participants of other's group)
        r = api.post(f"{BASE_URL}/api/groups",
                     json=_group_payload(title="TEST_rep_ban_joined"),
                     headers=_headers(u_other))
        gid_joined = r.json()["group_id"]
        api.post(f"{BASE_URL}/api/groups/{gid_joined}/join",
                 headers=_headers(u_owner))
        # u_owner posts a message in u_other's group
        r = api.post(f"{BASE_URL}/api/groups/{gid_joined}/messages",
                     json={"text": "TEST_rep_owner_says_hi"},
                     headers=_headers(u_owner))
        mid_owner_msg = r.json()["message_id"]

        # u_reporter joins u_owner's group so they can report
        api.post(f"{BASE_URL}/api/groups/{gid_owned}/join",
                 headers=_headers(u_reporter))
        # Reporter reports u_owner (user report)
        r = api.post(f"{BASE_URL}/api/reports",
                     json={"target_type": "user", "target_id": u_owner,
                           "reason": "harassment"},
                     headers=_headers(u_reporter))
        assert r.status_code == 200, r.text
        rep_ban_id = r.json()["report_id"]
        assert db.reports.find_one({"report_id": rep_ban_id})["status"] == "pending"

        # ---- act: delete u_owner via admin
        r = api.delete(f"{BASE_URL}/api/admin/users/{u_owner}",
                       headers=ADMIN_HEADERS)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["deleted_user"] == u_owner
        assert gid_owned in body["deleted_groups"]

        # ---- assertions
        # user gone
        assert db.users.count_documents({"user_id": u_owner}) == 0
        # owned group gone + its messages gone
        assert db.groups.count_documents({"group_id": gid_owned}) == 0
        assert db.messages.count_documents({"group_id": gid_owned}) == 0
        # joined group still exists, but u_owner removed from participants
        g_joined_doc = db.groups.find_one({"group_id": gid_joined})
        assert g_joined_doc is not None
        assert all(p["user_id"] != u_owner
                   for p in g_joined_doc.get("participants", []))
        # u_owner's message in joined group also gone
        assert db.messages.count_documents({"message_id": mid_owner_msg}) == 0
        # pending user-report on u_owner marked reviewed
        rep_after = db.reports.find_one({"report_id": rep_ban_id})
        assert rep_after["status"] == "reviewed"
