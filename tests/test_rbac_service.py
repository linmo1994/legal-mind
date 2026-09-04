import os
import tempfile
import unittest

from auth_service import AuthService
from rbac_service import RbacService
from rbac_store import RbacStore


class TestRbacService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RbacStore(os.path.join(self.tmp.name, "rbac.db"))
        self.store.ensure_schema()
        self.store.seed_defaults()
        self.auth = AuthService(self.store)
        self.auth.ensure_seed_director("ChangeMe123!")
        self.rbac = RbacService(self.store)
        lawyer = self.store.create_user(
            "lawyer1",
            self.auth.hash_password("pass12345"),
            display_name="主办一号",
            must_change_password=False,
        )
        self.lawyer_id = lawyer["id"]
        director = self.store.get_user_by_username("director")
        self.director_id = director["id"]
        self.case = self.store.create_case(
            case_no="(2026)测民初1号",
            title="测试民间借贷案",
            created_by=self.director_id,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_case_member_gets_judge(self):
        self.store.add_case_member(
            self.case["id"], self.lawyer_id, "lead_lawyer", assigned_by=self.director_id
        )
        with_case = self.rbac.effective_permissions(self.lawyer_id, self.case["id"])
        without = self.rbac.effective_permissions(self.lawyer_id, None)
        self.assertIn("cap.judge", with_case)
        self.assertNotIn("cap.judge", without)

    def test_reject_director_as_case_member(self):
        with self.assertRaises(ValueError):
            self.store.add_case_member(
                self.case["id"],
                self.director_id,
                "lead_lawyer",
                assigned_by=self.director_id,
            )

    def test_director_firm_has_judge(self):
        perms = self.rbac.effective_permissions(self.director_id, self.case["id"])
        self.assertIn("cap.judge", perms)
        self.assertIn("cap.user_manage", perms)


if __name__ == "__main__":
    unittest.main()
