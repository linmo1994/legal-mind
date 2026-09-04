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
        st, body = self.api.check_orchestrate_access(self.hdr, {"user_text": "hi"})
        self.assertEqual(st, 400)
        self.assertIn("case_id", body["error"])

    def test_director_ok(self):
        case = self.store.create_case("B-1", "案", created_by=1)
        st, body = self.api.check_orchestrate_access(
            self.hdr, {"case_id": case["id"], "user_text": "你好"}
        )
        self.assertEqual(st, 200)
        self.assertEqual(body["case_id"], case["id"])


if __name__ == "__main__":
    unittest.main()
