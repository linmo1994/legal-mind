import os
import tempfile
import unittest

from auth_service import AuthService
from http_rbac_api import RbacHttpApi
from rbac_service import RbacService
from rbac_store import RbacStore


class TestHttpRbacApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RbacStore(os.path.join(self.tmp.name, "rbac.db"))
        self.store.ensure_schema()
        self.store.seed_defaults()
        self.auth = AuthService(self.store)
        self.auth.ensure_seed_director("ChangeMe123!")
        self.api = RbacHttpApi(self.store, self.auth, RbacService(self.store))

    def tearDown(self):
        self.tmp.cleanup()

    def _auth_header(self, token: str) -> str:
        return f"Bearer {token}"

    def test_login_ok_and_bad(self):
        status, body = self.api.login({"username": "director", "password": "ChangeMe123!"})
        self.assertEqual(status, 200)
        self.assertIn("token", body)
        status2, _ = self.api.login({"username": "director", "password": "nope"})
        self.assertEqual(status2, 401)

    def test_users_require_cap(self):
        status, _ = self.api.list_users(None)
        self.assertEqual(status, 401)
        login = self.api.login({"username": "director", "password": "ChangeMe123!"})[1]
        status, body = self.api.list_users(self._auth_header(login["token"]))
        self.assertEqual(status, 200)
        self.assertTrue(any(u["username"] == "director" for u in body["users"]))

    def test_assign_case_member(self):
        login = self.api.login({"username": "director", "password": "ChangeMe123!"})[1]
        hdr = self._auth_header(login["token"])
        st, created = self.api.create_user(
            hdr,
            {
                "username": "lead1",
                "password": "pass12345",
                "display_name": "主办",
                "roles": [],
                "must_change_password": False,
            },
        )
        self.assertEqual(st, 201)
        st, case_body = self.api.create_case(
            hdr, {"case_no": "A-1", "title": "测试案"}
        )
        self.assertEqual(st, 201)
        st, mem = self.api.add_member(
            hdr,
            case_body["case"]["id"],
            {"user_id": created["user"]["id"], "role_code": "lead_lawyer"},
        )
        self.assertEqual(st, 201)
        self.assertEqual(mem["member"]["role_code"], "lead_lawyer")


if __name__ == "__main__":
    unittest.main()
