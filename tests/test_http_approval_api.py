import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from approval_store import ApprovalStore
from auth_service import AuthService
from http_approval_api import ApprovalHttpApi, parse_approval_path
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
        self.rbac_api = RbacHttpApi(
            self.store,
            self.auth,
            RbacService(self.store),
            approval_store=self.approval,
        )
        self.api = ApprovalHttpApi(
            self.store,
            self.auth,
            RbacService(self.store),
            self.approval,
        )
        self._users = {}
        self._case_id = None
        self._setup_case()

    def tearDown(self):
        self.tmp.cleanup()

    def _auth_header(self, token: str) -> str:
        return f"Bearer {token}"

    def _login(self, username: str) -> str:
        login = self.rbac_api.login({"username": username, "password": "pass12345"})[1]
        return self._auth_header(login["token"])

    def _setup_case(self):
        director_hdr = self._auth_header(
            self.rbac_api.login({"username": "director", "password": "ChangeMe123!"})[1]["token"]
        )
        for name in ("p_appr", "l_appr", "a_appr"):
            st, created = self.rbac_api.create_user(
                director_hdr,
                {
                    "username": name,
                    "password": "pass12345",
                    "display_name": name,
                    "roles": [],
                    "must_change_password": False,
                },
            )
            self.assertEqual(st, 201)
            self._users[name] = created["user"]["id"]
        st, case_body = self.rbac_api.create_case(
            director_hdr,
            {
                "case_type": "civil",
                "title": "审批流测试",
                "partner_user_id": self._users["p_appr"],
                "lead_lawyer_user_id": self._users["l_appr"],
                "assistant_user_id": self._users["a_appr"],
            },
        )
        self.assertEqual(st, 201)
        self._case_id = case_body["case"]["id"]

    def test_advance_case_stage_adjacent_only(self):
        login = self.rbac_api.login({"username": "director", "password": "ChangeMe123!"})[1]
        hdr = self._auth_header(login["token"])
        created_users = []
        for name in ("p_stage", "l_stage"):
            st, created = self.rbac_api.create_user(
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
        st, case_body = self.rbac_api.create_case(
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

        lead_login = self.rbac_api.login({"username": "l_stage", "password": "pass12345"})[1]
        lead_hdr = self._auth_header(lead_login["token"])

        st, advanced = self.rbac_api.advance_case_stage(
            lead_hdr, case_id, {"to": "materials_ready"}
        )
        self.assertEqual(st, 200)
        self.assertEqual(advanced["case"]["stage"], "materials_ready")
        self.assertEqual(advanced["case"]["status"], "materials_ready")

        st2, bad = self.rbac_api.advance_case_stage(lead_hdr, case_id, {"to": "closed"})
        self.assertEqual(st2, 400)

        audit = self.approval.list_audit(case_id=case_id)
        self.assertTrue(any(e["action"] == "case_stage_advance" for e in audit))

    def test_assistant_cannot_decide_partner_task(self):
        assistant_hdr = self._login("a_appr")
        st, created = self.api.create_artifact(
            assistant_hdr,
            {
                "case_id": self._case_id,
                "file_id": "f-assist-deny",
                "title": "起诉状",
                "doc_type": "起诉状",
            },
        )
        self.assertEqual(st, 201)
        artifact_id = created["artifact"]["id"]

        st, submitted = self.api.submit_artifact(assistant_hdr, artifact_id)
        self.assertEqual(st, 200)
        self.assertEqual(submitted["artifact"]["approval_status"], "pending_lead")

        lead_hdr = self._login("l_appr")
        inbox = self.api.inbox(lead_hdr)[1]["tasks"]
        self.assertEqual(len(inbox), 1)
        lead_task_id = inbox[0]["id"]

        st, after_lead = self.api.decide(
            lead_hdr, lead_task_id, {"decision": "approve"}
        )
        self.assertEqual(st, 200)
        self.assertEqual(after_lead["artifact"]["approval_status"], "pending_partner")

        partner_inbox = self.api.inbox(self._login("p_appr"))[1]["tasks"]
        self.assertEqual(len(partner_inbox), 1)
        partner_task_id = partner_inbox[0]["id"]

        st, denied = self.api.decide(
            assistant_hdr, partner_task_id, {"decision": "approve"}
        )
        self.assertEqual(st, 403)

    def test_decide_idempotent(self):
        assistant_hdr = self._login("a_appr")
        st, created = self.api.create_artifact(
            assistant_hdr,
            {
                "case_id": self._case_id,
                "file_id": "f-idempotent",
                "title": "起诉状",
                "doc_type": "起诉状",
            },
        )
        self.assertEqual(st, 201)
        artifact_id = created["artifact"]["id"]
        self.api.submit_artifact(assistant_hdr, artifact_id)

        lead_hdr = self._login("l_appr")
        lead_task_id = self.api.inbox(lead_hdr)[1]["tasks"][0]["id"]
        st1, first = self.api.decide(lead_hdr, lead_task_id, {"decision": "approve"})
        self.assertEqual(st1, 200)
        self.assertEqual(first["artifact"]["approval_status"], "pending_partner")

        st2, second = self.api.decide(lead_hdr, lead_task_id, {"decision": "approve"})
        self.assertEqual(st2, 200)
        self.assertEqual(second["artifact"]["approval_status"], "pending_partner")

    def test_happy_path_submit_lead_partner_approved(self):
        assistant_hdr = self._login("a_appr")
        st, created = self.api.create_artifact(
            assistant_hdr,
            {
                "case_id": self._case_id,
                "file_id": "f-happy",
                "title": "起诉状",
                "doc_type": "起诉状",
            },
        )
        self.assertEqual(st, 201)
        artifact_id = created["artifact"]["id"]

        st, submitted = self.api.submit_artifact(assistant_hdr, artifact_id)
        self.assertEqual(st, 200)
        self.assertEqual(submitted["artifact"]["approval_status"], "pending_lead")

        lead_hdr = self._login("l_appr")
        lead_task_id = self.api.inbox(lead_hdr)[1]["tasks"][0]["id"]
        st, after_lead = self.api.decide(
            lead_hdr, lead_task_id, {"decision": "approve", "comment": "可以"}
        )
        self.assertEqual(st, 200)
        self.assertEqual(after_lead["artifact"]["approval_status"], "pending_partner")

        partner_hdr = self._login("p_appr")
        partner_task_id = self.api.inbox(partner_hdr)[1]["tasks"][0]["id"]
        st, approved = self.api.decide(
            partner_hdr, partner_task_id, {"decision": "approve", "comment": "定稿"}
        )
        self.assertEqual(st, 200)
        self.assertEqual(approved["artifact"]["approval_status"], "approved")

        st, detail = self.api.get_artifact(partner_hdr, artifact_id)
        self.assertEqual(st, 200)
        self.assertEqual(detail["artifact"]["approval_status"], "approved")

        director_hdr = self._auth_header(
            self.rbac_api.login({"username": "director", "password": "ChangeMe123!"})[1]["token"]
        )
        st, audit = self.api.list_audit(director_hdr, self._case_id)
        self.assertEqual(st, 200)
        actions = {e["action"] for e in audit["events"]}
        self.assertIn("artifact_created", actions)
        self.assertIn("artifact_submit", actions)
        self.assertIn("approval_approve", actions)

    def test_workbench_badge_and_ack(self):
        assistant_hdr = self._login("a_appr")
        lead_hdr = self._login("l_appr")

        st, created = self.api.create_artifact(
            assistant_hdr,
            {
                "case_id": self._case_id,
                "file_id": "f-workbench",
                "title": "起诉状",
                "doc_type": "起诉状",
            },
        )
        self.assertEqual(st, 201)
        artifact_id = created["artifact"]["id"]

        st, submitted = self.api.submit_artifact(assistant_hdr, artifact_id)
        self.assertEqual(st, 200)
        self.assertEqual(submitted["artifact"]["approval_status"], "pending_lead")

        lead_task_id = self.api.inbox(lead_hdr)[1]["tasks"][0]["id"]
        st, rejected = self.api.decide(
            lead_hdr, lead_task_id, {"decision": "reject", "comment": "格式不对"}
        )
        self.assertEqual(st, 200)
        self.assertEqual(rejected["artifact"]["approval_status"], "draft")

        st, wb = self.api.workbench(assistant_hdr)
        self.assertEqual(st, 200)
        self.assertGreaterEqual(len(wb["rejected_mine"]), 1)
        self.assertFalse(wb["rejected_mine"][0]["ack"])
        self.assertGreaterEqual(wb["badge_count"], 1)
        self.assertTrue(any(c["id"] == self._case_id for c in wb["my_cases"]))
        badge_before_ack = wb["badge_count"]

        aid = wb["rejected_mine"][0]["artifact_id"]
        st, ack_body = self.api.ack_reject(assistant_hdr, aid)
        self.assertEqual(st, 200)
        self.assertTrue(ack_body["ok"])

        st, wb2 = self.api.workbench(assistant_hdr)
        self.assertEqual(st, 200)
        item = next(x for x in wb2["rejected_mine"] if x["artifact_id"] == aid)
        self.assertTrue(item["ack"])
        self.assertEqual(wb2["badge_count"], badge_before_ack - 1)

    def test_workbench_badge_only(self):
        assistant_hdr = self._login("a_appr")
        lead_hdr = self._login("l_appr")

        st, created = self.api.create_artifact(
            assistant_hdr,
            {
                "case_id": self._case_id,
                "file_id": "f-badge-only",
                "title": "起诉状",
                "doc_type": "起诉状",
            },
        )
        self.assertEqual(st, 201)
        artifact_id = created["artifact"]["id"]
        self.api.submit_artifact(assistant_hdr, artifact_id)
        lead_task_id = self.api.inbox(lead_hdr)[1]["tasks"][0]["id"]
        self.api.decide(lead_hdr, lead_task_id, {"decision": "reject", "comment": "需修改"})

        st, wb = self.api.workbench(assistant_hdr, badge_only=True)
        self.assertEqual(st, 200)
        self.assertEqual(set(wb.keys()), {"badge_count"})
        self.assertGreaterEqual(wb["badge_count"], 1)

    def test_parse_approval_path_workbench_routes(self):
        self.assertEqual(
            parse_approval_path("/api/approvals/workbench", "GET"),
            ("workbench", None),
        )
        self.assertEqual(
            parse_approval_path("/api/approvals/rejects/42/ack", "POST"),
            ("ack_reject", "42"),
        )


if __name__ == "__main__":
    unittest.main()
