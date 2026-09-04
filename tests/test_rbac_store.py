import os
import tempfile
import unittest

from rbac_store import RbacStore


class TestRbacStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RbacStore(os.path.join(self.tmp.name, "rbac.db"))
        self.store.ensure_schema()
        self.store.seed_defaults()

    def tearDown(self):
        self.tmp.cleanup()

    def test_seeds_five_system_roles(self):
        codes = {r["code"] for r in self.store.list_roles()}
        self.assertEqual(
            codes,
            {"director", "admin_officer", "partner", "lead_lawyer", "assistant"},
        )

    def test_director_has_user_manage(self):
        perms = self.store.permissions_for_role_codes(["director"])
        self.assertIn("cap.user_manage", perms)
        self.assertIn("cap.case_assign", perms)

    def test_admin_officer_no_judge(self):
        perms = self.store.permissions_for_role_codes(["admin_officer"])
        self.assertIn("cap.case_assign", perms)
        self.assertNotIn("cap.judge", perms)

    def test_seed_director_user(self):
        u = self.store.get_user_by_username("director")
        self.assertIsNotNone(u)
        self.assertTrue(u["must_change_password"])


if __name__ == "__main__":
    unittest.main()
