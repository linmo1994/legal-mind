#!/usr/bin/env python3
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from session_service import SessionService  # noqa: E402


class TestSessionArtifact(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.svc = SessionService(os.path.join(self.tmp, "sessions.db"))

    def test_roundtrip_artifact(self):
        self.svc.create_session("s1", title="t")
        self.svc.add_message("s1", "user", "生成起诉状")
        art = {"file_id": "f1", "filename": "民事起诉状.docx"}
        self.svc.add_message("s1", "assistant", "已起草", extra={"artifact": art})
        msgs = self.svc.get_session_messages("s1")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[1]["artifact"]["file_id"], "f1")
        self.assertEqual(msgs[1]["content"], "已起草")

    def test_roundtrip_capabilities(self):
        self.svc.create_session("s2", title="t")
        caps = {
            "skills": [{"kind": "skill", "id": "judge-work", "name": "法官断案指南"}],
            "mcp": [{"kind": "mcp", "id": "legal://law_regulation", "name": "法律法规"}],
        }
        self.svc.add_message("s2", "assistant", "分析完成", extra={"capabilities": caps})
        msgs = self.svc.get_session_messages("s2")
        self.assertEqual(msgs[0]["capabilities"]["skills"][0]["id"], "judge-work")
        self.assertEqual(msgs[0]["capabilities"]["mcp"][0]["id"], "legal://law_regulation")


if __name__ == "__main__":
    unittest.main()
