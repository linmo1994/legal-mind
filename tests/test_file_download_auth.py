"""Tests for file download/preview authorization and session user binding."""

import os
import shutil
import sys
import tempfile
import unittest
import json
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from approval_store import ApprovalStore
from auth_service import AuthService
from file_service import FileService
from http_rbac_api import RbacHttpApi
from rbac_service import RbacService
from rbac_store import RbacStore
from session_service import SessionService


class TestFileDownloadAuth(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.store = RbacStore(os.path.join(self.tmp, "rbac.db"))
        self.store.ensure_schema()
        self.store.seed_defaults()
        self.auth = AuthService(self.store)
        self.auth.ensure_seed_director("ChangeMe123!")
        self.approval = ApprovalStore(
            os.path.join(self.tmp, "approval.db"),
            rbac_store=self.store,
        )
        self.approval.ensure_schema()
        self.files = FileService(
            os.path.join(self.tmp, "files.db"),
            os.path.join(self.tmp, "uploads"),
        )
        self.sessions = SessionService(os.path.join(self.tmp, "sessions.db"))
        self.api = RbacHttpApi(
            self.store,
            self.auth,
            RbacService(self.store),
            file_service=self.files,
            approval_store=self.approval,
        )
        self._users: dict = {}
        self._case_id: int = 0
        self._setup_users_and_case()

    def _hdr(self, username: str) -> str:
        if username not in self._users:
            password = "ChangeMe123!" if username == "director" else "pass12345"
            login = self.auth.login(username, password)
            self.assertIsNotNone(login, f"login failed for {username}")
            self._users[username] = login["token"]
        return f"Bearer {self._users[username]}"

    def _setup_users_and_case(self):
        director_hdr = self._hdr("director")
        user_ids = {}
        for name in ("p_dl", "l_dl", "a_dl", "outsider"):
            st, created = self.api.create_user(
                director_hdr,
                {
                    "username": name,
                    "password": "pass12345",
                    "display_name": name,
                    "roles": [],
                    "must_change_password": False,
                },
            )
            self.assertEqual(st, 201, created)
            user_ids[name] = created["user"]["id"]
            self._users[name] = self.auth.login(name, "pass12345")["token"]
        st, case_body = self.api.create_case(
            director_hdr,
            {
                "case_type": "civil",
                "title": "下载鉴权测试",
                "partner_user_id": user_ids["p_dl"],
                "lead_lawyer_user_id": user_ids["l_dl"],
                "assistant_user_id": user_ids["a_dl"],
            },
        )
        self.assertEqual(st, 201, case_body)
        self._case_id = case_body["case"]["id"]

    def _save_file(self, data: bytes, name: str, session_id: Optional[str] = None) -> str:
        info = self.files.save_file(data, name, session_id=session_id)
        return info["file_id"]

    def _check(self, authz, file_id):
        info = self.files.get_file(file_id)
        return self.api.check_file_download_access(
            authz, file_id, info, session_service=self.sessions
        )

    def test_unauthenticated_returns_401(self):
        fid = self._save_file(b"secret", "doc.txt")
        st, _ = self._check(None, fid)
        self.assertEqual(st, 401)

    def test_artifact_case_member_allowed(self):
        fid = self._save_file(b"artifact", "起诉状.docx")
        self.approval.create_artifact(
            case_id=self._case_id,
            file_id=fid,
            title="起诉状",
            doc_type="起诉状",
            created_by=self.store.get_user_by_username("a_dl")["id"],
        )
        st, _ = self._check(self._hdr("a_dl"), fid)
        self.assertEqual(st, 200)

    def test_artifact_non_member_denied(self):
        fid = self._save_file(b"artifact", "起诉状.docx")
        self.approval.create_artifact(
            case_id=self._case_id,
            file_id=fid,
            title="起诉状",
            doc_type="起诉状",
        )
        st, body = self._check(self._hdr("outsider"), fid)
        self.assertEqual(st, 403, body)

    def test_artifact_director_allowed(self):
        fid = self._save_file(b"artifact", "起诉状.docx")
        self.approval.create_artifact(
            case_id=self._case_id,
            file_id=fid,
            title="起诉状",
            doc_type="起诉状",
        )
        st, _ = self._check(self._hdr("director"), fid)
        self.assertEqual(st, 200)

    def test_uploader_via_session_allowed(self):
        uid = self.store.get_user_by_username("l_dl")["id"]
        sid = "sess-uploader"
        self.sessions.create_session(sid, user_id=uid)
        fid = self._save_file(b"my upload", "note.txt", session_id=sid)
        st, _ = self._check(self._hdr("l_dl"), fid)
        self.assertEqual(st, 200)

    def test_unknown_ownership_non_director_denied(self):
        fid = self._save_file(b"orphan", "orphan.txt")
        st, body = self._check(self._hdr("l_dl"), fid)
        self.assertEqual(st, 403, body)

    def test_unknown_ownership_director_allowed(self):
        fid = self._save_file(b"orphan", "orphan.txt")
        st, _ = self._check(self._hdr("director"), fid)
        self.assertEqual(st, 200)

    def test_case_meta_file_member_allowed(self):
        fid = self._save_file(b"contract", "contract.pdf")
        case = self.store.get_case(self._case_id)
        meta = dict(case.get("meta") or {})
        meta["contract_file_ids"] = [fid]
        self.store.update_case(self._case_id, meta_json=json.dumps(meta))
        st, _ = self._check(self._hdr("p_dl"), fid)
        self.assertEqual(st, 200)


class TestSessionUserBinding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.svc = SessionService(os.path.join(self.tmp, "sessions.db"))

    def test_create_session_stores_user_id(self):
        self.svc.create_session("s1", title="t", user_id=42)
        sess = self.svc.get_session("s1")
        self.assertEqual(sess["user_id"], 42)

    def test_list_sessions_filters_by_user(self):
        self.svc.create_session("u1-a", user_id=1)
        self.svc.add_message("u1-a", "user", "hello")
        self.svc.create_session("u1-b", user_id=1)
        self.svc.add_message("u1-b", "user", "world")
        self.svc.create_session("u2-a", user_id=2)
        self.svc.add_message("u2-a", "user", "other")
        listed = self.svc.list_sessions(user_id=1)
        ids = {s["session_id"] for s in listed}
        self.assertEqual(ids, {"u1-a", "u1-b"})
        self.assertEqual(len(self.svc.list_sessions(user_id=2)), 1)


if __name__ == "__main__":
    unittest.main()
