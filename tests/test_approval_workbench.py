import os
import tempfile
import unittest

from approval_store import ApprovalStore
from rbac_store import RbacStore


class TestApprovalWorkbench(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rbac = RbacStore(os.path.join(self.tmp.name, "rbac.db"))
        self.rbac.ensure_schema()
        self.rbac.seed_defaults()

        self.partner = self.rbac.create_user("p1", "hash", "Partner")
        self.lead = self.rbac.create_user("l1", "hash", "Lead")
        self.assistant = self.rbac.create_user("a1", "hash", "Assistant")
        self.other_assistant = self.rbac.create_user("a2", "hash", "Other")

        self.case = self.rbac.create_case("2026民0001", "测试案")
        self.rbac.add_case_member(self.case["id"], self.partner["id"], "partner")
        self.rbac.add_case_member(self.case["id"], self.lead["id"], "lead_lawyer")
        self.rbac.add_case_member(self.case["id"], self.assistant["id"], "assistant")
        self.rbac.add_case_member(self.case["id"], self.other_assistant["id"], "assistant")

        self.store = ApprovalStore(
            os.path.join(self.tmp.name, "approval.db"),
            rbac_store=self.rbac,
        )
        self.store.ensure_schema()

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_artifact_stores_session_id(self):
        art = self.store.create_artifact(
            case_id=self.case["id"],
            file_id="f-sess",
            title="起诉状",
            doc_type="起诉状",
            created_by=self.assistant["id"],
            source="ai_draft_doc",
            session_id="sess_from_chat",
        )
        self.assertEqual(art["session_id"], "sess_from_chat")
        again = self.store.get_artifact(art["id"])
        self.assertEqual(again["session_id"], "sess_from_chat")

    def _create_and_reject(self, *, created_by, file_id, comment="格式不对"):
        art = self.store.create_artifact(
            case_id=self.case["id"],
            file_id=file_id,
            title="起诉状",
            doc_type="起诉状",
            created_by=created_by,
            source="ai_draft_doc",
            session_id="sess_reject_src",
        )
        self.store.submit_for_review(
            art["id"],
            actor_user_id=created_by,
            actor_case_role="assistant",
        )
        tasks = self.store.list_open_tasks_for_user(self.lead["id"])
        self.store.decide(
            tasks[0]["id"],
            actor_user_id=self.lead["id"],
            decision="reject",
            comment=comment,
        )
        return art

    def test_list_rejected_for_creator_only_own_drafts_with_comment(self):
        rejected = self._create_and_reject(
            created_by=self.assistant["id"],
            file_id="f-rej-1",
            comment="请修改标题",
        )
        self._create_and_reject(
            created_by=self.other_assistant["id"],
            file_id="f-rej-2",
            comment="内容不完整",
        )

        draft_no_comment = self.store.create_artifact(
            case_id=self.case["id"],
            file_id="f-draft",
            title="草稿",
            doc_type="起诉状",
            created_by=self.assistant["id"],
            source="ai_draft_doc",
        )

        mine = self.store.list_rejected_for_creator(self.assistant["id"])
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["id"], rejected["id"])
        self.assertEqual(mine[0]["reject_comment"], "请修改标题")
        self.assertNotIn(draft_no_comment["id"], [a["id"] for a in mine])

    def test_is_rejection_acked_and_ack_rejection(self):
        rejected = self._create_and_reject(
            created_by=self.assistant["id"],
            file_id="f-ack-1",
        )
        artifact_id = rejected["id"]
        user_id = self.assistant["id"]

        self.assertFalse(self.store.is_rejection_acked(user_id, artifact_id))

        self.store.ack_rejection(user_id, artifact_id)
        self.assertTrue(self.store.is_rejection_acked(user_id, artifact_id))

    def test_clear_rejection_acks_for_artifact(self):
        rejected = self._create_and_reject(
            created_by=self.assistant["id"],
            file_id="f-clear-1",
        )
        artifact_id = rejected["id"]
        user_id = self.assistant["id"]

        self.store.ack_rejection(user_id, artifact_id)
        self.assertTrue(self.store.is_rejection_acked(user_id, artifact_id))

        self.store.clear_rejection_acks_for_artifact(artifact_id)
        self.assertFalse(self.store.is_rejection_acked(user_id, artifact_id))

    def test_decide_reject_clears_rejection_acks(self):
        rejected = self._create_and_reject(
            created_by=self.assistant["id"],
            file_id="f-reject-clear",
            comment="第一次驳回",
        )
        artifact_id = rejected["id"]
        user_id = self.assistant["id"]

        self.store.ack_rejection(user_id, artifact_id)
        self.assertTrue(self.store.is_rejection_acked(user_id, artifact_id))

        self.store.submit_for_review(
            artifact_id,
            actor_user_id=user_id,
            actor_case_role="assistant",
        )
        tasks = self.store.list_open_tasks_for_user(self.lead["id"])
        self.store.decide(
            tasks[0]["id"],
            actor_user_id=self.lead["id"],
            decision="reject",
            comment="第二次驳回",
        )

        self.assertFalse(self.store.is_rejection_acked(user_id, artifact_id))

        rejected_again = self.store.get_artifact(artifact_id)
        self.assertEqual(rejected_again["reject_comment"], "第二次驳回")
        self.assertEqual(rejected_again["approval_status"], "draft")


if __name__ == "__main__":
    unittest.main()
