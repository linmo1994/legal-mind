import os
import tempfile
import unittest

from approval_store import ApprovalStore
from rbac_store import RbacStore


class TestApprovalStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rbac = RbacStore(os.path.join(self.tmp.name, "rbac.db"))
        self.rbac.ensure_schema()
        self.rbac.seed_defaults()

        self.partner = self.rbac.create_user("p1", "hash", "Partner")
        self.lead = self.rbac.create_user("l1", "hash", "Lead")
        self.assistant = self.rbac.create_user("a1", "hash", "Assistant")

        self.case = self.rbac.create_case("2026民0001", "测试案")
        self.rbac.add_case_member(self.case["id"], self.partner["id"], "partner")
        self.rbac.add_case_member(self.case["id"], self.lead["id"], "lead_lawyer")
        self.rbac.add_case_member(self.case["id"], self.assistant["id"], "assistant")

        self.store = ApprovalStore(
            os.path.join(self.tmp.name, "approval.db"),
            rbac_store=self.rbac,
        )
        self.store.ensure_schema()

    def tearDown(self):
        self.tmp.cleanup()

    def test_submit_by_assistant_creates_lead_task(self):
        art = self.store.create_artifact(
            case_id=self.case["id"],
            file_id="f1",
            title="起诉状",
            doc_type="起诉状",
            created_by=self.assistant["id"],
            source="ai_draft_doc",
        )
        out = self.store.submit_for_review(
            art["id"],
            actor_user_id=self.assistant["id"],
            actor_case_role="assistant",
        )
        self.assertEqual(out["approval_status"], "pending_lead")

        tasks = self.store.list_open_tasks_for_user(self.lead["id"])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["step"], "lead")
        self.assertEqual(tasks[0]["artifact_id"], art["id"])

        audit = self.store.list_audit(case_id=self.case["id"])
        self.assertTrue(any(e["action"] == "artifact_submit" for e in audit))

    def test_lead_self_submit_skips_to_partner(self):
        art = self.store.create_artifact(
            case_id=self.case["id"],
            file_id="f2",
            title="起诉状",
            doc_type="起诉状",
            created_by=self.lead["id"],
            source="ai_draft_doc",
        )
        out = self.store.submit_for_review(
            art["id"],
            actor_user_id=self.lead["id"],
            actor_case_role="lead_lawyer",
        )
        self.assertEqual(out["approval_status"], "pending_partner")

        lead_tasks = self.store.list_open_tasks_for_user(self.lead["id"])
        self.assertEqual(len(lead_tasks), 0)

        partner_tasks = self.store.list_open_tasks_for_user(self.partner["id"])
        self.assertEqual(len(partner_tasks), 1)
        self.assertEqual(partner_tasks[0]["step"], "partner")

    def test_reject_returns_draft_and_cancels_open(self):
        art = self.store.create_artifact(
            case_id=self.case["id"],
            file_id="f3",
            title="起诉状",
            doc_type="起诉状",
            created_by=self.assistant["id"],
            source="ai_draft_doc",
        )
        submitted = self.store.submit_for_review(
            art["id"],
            actor_user_id=self.assistant["id"],
            actor_case_role="assistant",
        )
        self.assertEqual(submitted["approval_status"], "pending_lead")

        tasks = self.store.list_open_tasks_for_user(self.lead["id"])
        self.assertEqual(len(tasks), 1)

        rejected = self.store.decide(
            tasks[0]["id"],
            actor_user_id=self.lead["id"],
            decision="reject",
            comment="格式不对",
        )
        self.assertEqual(rejected["approval_status"], "draft")
        self.assertEqual(rejected["reject_comment"], "格式不对")

        open_tasks = self.store.list_open_tasks_for_user(self.lead["id"])
        self.assertEqual(len(open_tasks), 0)

        audit = self.store.list_audit(case_id=self.case["id"])
        self.assertTrue(any(e["action"] == "approval_reject" for e in audit))

    def test_partner_approve_sets_approved(self):
        art = self.store.create_artifact(
            case_id=self.case["id"],
            file_id="f4",
            title="起诉状",
            doc_type="起诉状",
            created_by=self.assistant["id"],
            source="ai_draft_doc",
        )
        self.store.submit_for_review(
            art["id"],
            actor_user_id=self.assistant["id"],
            actor_case_role="assistant",
        )
        lead_tasks = self.store.list_open_tasks_for_user(self.lead["id"])
        after_lead = self.store.decide(
            lead_tasks[0]["id"],
            actor_user_id=self.lead["id"],
            decision="approve",
        )
        self.assertEqual(after_lead["approval_status"], "pending_partner")

        partner_tasks = self.store.list_open_tasks_for_user(self.partner["id"])
        self.assertEqual(len(partner_tasks), 1)

        approved = self.store.decide(
            partner_tasks[0]["id"],
            actor_user_id=self.partner["id"],
            decision="approve",
        )
        self.assertEqual(approved["approval_status"], "approved")

        open_tasks = self.store.list_open_tasks_for_user(self.partner["id"])
        self.assertEqual(len(open_tasks), 0)

        audit = self.store.list_audit(case_id=self.case["id"])
        actions = {e["action"] for e in audit}
        self.assertIn("artifact_submit", actions)
        self.assertIn("approval_approve", actions)


if __name__ == "__main__":
    unittest.main()
