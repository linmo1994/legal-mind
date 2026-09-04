import os
import tempfile
import unittest

from auth_service import AuthService
from rbac_store import RbacStore


class TestAuth(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RbacStore(os.path.join(self.tmp.name, "rbac.db"))
        self.store.ensure_schema()
        self.store.seed_defaults()
        self.auth = AuthService(self.store)
        self.auth.ensure_seed_director("ChangeMe123!")

    def tearDown(self):
        self.tmp.cleanup()

    def test_login_ok(self):
        out = self.auth.login("director", "ChangeMe123!")
        self.assertIsNotNone(out)
        self.assertIn("token", out)
        self.assertIn("cap.user_manage", out["firm_permissions"])

    def test_login_bad_password(self):
        self.assertIsNone(self.auth.login("director", "wrong"))

    def test_resolve_token(self):
        out = self.auth.login("director", "ChangeMe123!")
        user = self.auth.resolve_token(out["token"])
        self.assertEqual(user["username"], "director")


if __name__ == "__main__":
    unittest.main()
