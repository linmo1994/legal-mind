import os
import tempfile
import unittest

from approval_store import ApprovalStore
from auth_service import AuthService
from http_rbac_api import RbacHttpApi
from rbac_service import RbacService
from rbac_store import RbacStore


class TestHttpApprovalApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RbacStore(os.path.join(self.tmp.name, "rbac.db"))
        self.store.ensure_schema()
        self.store.seed_defaults()
        self.auth = AuthService(self.store)
        self.auth.ensure_seed_director("ChangeMe123!")
        self.approval = ApprovalStore(
            os.path.join(self.tmp.name, "approval.db"),
            rbac_store=self.store,
        )
        self.approval.ensure_schema()
        self.api = RbacHttpApi(
            self.store,
            self.auth,
            RbacService(self.store),
            approval_store=self.approval,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _auth_header(self, token: str) -> str:
        return f"Bearer {token}"

    def test_advance_case_stage_adjacent_only(self):
        login = self.api.login({"username": "director", "password": "ChangeMe123!"})[1]
        hdr = self._auth_header(login["token"])
        created_users = []
        for name in ("p_stage", "l_stage"):
            st, created = self.api.create_user(
                hdr,
                {
                    "username": name,
                    "password": "pass12345",
                    "display_name": name,
                    "roles": [],
                    "must_change_password": False,
                },
            )
            self.assertEqual(st, 201)
            created_users.append(created["user"]["id"])
        st, case_body = self.api.create_case(
            hdr,
            {
                "case_type": "civil",
                "title": "阶段推进测试",
                "partner_user_id": created_users[0],
                "lead_lawyer_user_id": created_users[1],
            },
        )
        self.assertEqual(st, 201)
        case_id = case_body["case"]["id"]
        self.assertEqual(case_body["case"]["stage"], "intake")

        lead_login = self.api.login({"username": "l_stage", "password": "pass12345"})[1]
        lead_hdr = self._auth_header(lead_login["token"])

        st, advanced = self.api.advance_case_stage(
            lead_hdr, case_id, {"to": "materials_ready"}
        )
        self.assertEqual(st, 200)
        self.assertEqual(advanced["case"]["stage"], "materials_ready")
        self.assertEqual(advanced["case"]["status"], "materials_ready")

        st2, bad = self.api.advance_case_stage(lead_hdr, case_id, {"to": "closed"})
        self.assertEqual(st2, 400)

        audit = self.approval.list_audit(case_id=case_id)
        self.assertTrue(any(e["action"] == "case_stage_advance" for e in audit))
