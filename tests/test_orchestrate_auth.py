import os
import tempfile
import unittest

from auth_service import AuthService
from http_rbac_api import RbacHttpApi
from rbac_service import RbacService
from rbac_store import RbacStore


class TestOrchestrateAuth(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RbacStore(os.path.join(self.tmp.name, "rbac.db"))
        self.store.ensure_schema()
        self.store.seed_defaults()
        self.auth = AuthService(self.store)
        self.auth.ensure_seed_director("ChangeMe123!")
        self.api = RbacHttpApi(self.store, self.auth, RbacService(self.store))
        self.token = self.auth.login("director", "ChangeMe123!")["token"]
        self.hdr = f"Bearer {self.token}"

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_token(self):
        st, _ = self.api.check_orchestrate_access(None, {"case_id": 1, "user_text": "hi"})
        self.assertEqual(st, 401)

    def test_no_case_id(self):
        # 案件可选：有律所级 cap.chat 即可编排
        st, body = self.api.check_orchestrate_access(self.hdr, {"user_text": "hi"})
        self.assertEqual(st, 200)
        self.assertIsNone(body.get("case_id"))

    def test_invalid_case_id(self):
        st, body = self.api.check_orchestrate_access(
            self.hdr, {"case_id": 999999, "user_text": "hi"}
        )
        self.assertEqual(st, 404)

    def test_director_ok(self):
        case = self.store.create_case("B-1", "案", created_by=1)
        st, body = self.api.check_orchestrate_access(
            self.hdr, {"case_id": case["id"], "user_text": "你好"}
        )
        self.assertEqual(st, 200)
        self.assertEqual(body["case_id"], case["id"])

    def test_case_id_all_permitted_sentinel(self):
        st, body = self.api.check_orchestrate_access(
            self.hdr, {"case_id": "*", "user_text": "hi"}
        )
        self.assertEqual(st, 200)
        self.assertEqual(body.get("case_id"), "*")
        self.assertEqual(body.get("case_scope"), "all_permitted")

    def test_case_id_garbage_still_400(self):
        st, body = self.api.check_orchestrate_access(
            self.hdr, {"case_id": "abc", "user_text": "hi"}
        )
        self.assertEqual(st, 400)


if __name__ == "__main__":
    unittest.main()
