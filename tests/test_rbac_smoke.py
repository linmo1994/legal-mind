import os
import tempfile
import unittest

from auth_service import AuthService
from http_rbac_api import RbacHttpApi
from rbac_service import RbacService
from rbac_store import RbacStore


class TestRbacSmoke(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RbacStore(os.path.join(self.tmp.name, "rbac.db"))
        self.store.ensure_schema()
        self.store.seed_defaults()
        self.auth = AuthService(self.store)
        self.auth.ensure_seed_director("ChangeMe123!")
        self.api = RbacHttpApi(self.store, self.auth, RbacService(self.store))
        self.director = self.api.login({"username": "director", "password": "ChangeMe123!"})[1]
        self.dh = "Bearer " + self.director["token"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_officer_assign_lead_can_judge(self):
        st, officer = self.api.create_user(
            self.dh,
            {
                "username": "officer1",
                "password": "pass12345",
                "roles": ["admin_officer"],
                "must_change_password": False,
            },
        )
        self.assertEqual(st, 201)
        st, lead = self.api.create_user(
            self.dh,
            {
                "username": "lead1",
                "password": "pass12345",
                "roles": [],
                "must_change_password": False,
            },
        )
        self.assertEqual(st, 201)
        oh = "Bearer " + self.api.login({"username": "officer1", "password": "pass12345"})[1]["token"]
        st, case_body = self.api.create_case(oh, {"case_no": "SMOKE-1", "title": "冒烟案"})
        self.assertEqual(st, 201)
        case_id = case_body["case"]["id"]
        st, _ = self.api.add_member(
            oh, case_id, {"user_id": lead["user"]["id"], "role_code": "lead_lawyer"}
        )
        self.assertEqual(st, 201)
        lh = "Bearer " + self.api.login({"username": "lead1", "password": "pass12345"})[1]["token"]
        st, ok = self.api.check_orchestrate_access(
            lh, {"case_id": case_id, "user_text": "请帮我断案"}
        )
        self.assertEqual(st, 200)
        st, denied = self.api.check_orchestrate_access(
            oh, {"case_id": case_id, "user_text": "请帮我断案"}
        )
        self.assertEqual(st, 403)
        self.assertTrue(
            "cap.judge" in denied["error"] or "cap.chat" in denied["error"],
            denied["error"],
        )


if __name__ == "__main__":
    unittest.main()
