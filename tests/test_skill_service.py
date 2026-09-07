#!/usr/bin/env python3
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from skill_service import SkillService, parse_skill_markdown  # noqa: E402


SAMPLE = """---
name: 案情拆解
description: 当用户需要梳理事实、争议焦点或证据缺口时使用
applies_to:
  - text_analysis
  - orchestrator
---

# 案情拆解

1. 列出当事人
2. 不要编造法条
"""


class TestSkillService(unittest.TestCase):
    def test_parse_front_matter(self):
        meta, body = parse_skill_markdown(SAMPLE)
        self.assertEqual(meta["name"], "案情拆解")
        self.assertIn("text_analysis", meta["applies_to"])
        self.assertIn("列出当事人", body)

    def test_crud_roundtrip(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        svc = SkillService(tmp)
        created = svc.create({
            "id": "case-split",
            "name": "案情拆解",
            "description": "梳理事实",
            "applies_to": ["text_analysis"],
            "body": "列出当事人",
        })
        self.assertEqual(created["id"], "case-split")
        listed = svc.list_skills()
        self.assertEqual(len(listed), 1)
        one = svc.get("case-split")
        self.assertIn("列出当事人", one["body"])
        svc.update("case-split", {"body": "列出证据"})
        self.assertIn("列出证据", svc.get("case-split")["body"])
        svc.delete("case-split")
        self.assertEqual(svc.list_skills(), [])

    def test_update_persists_all_critical_fields(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        svc = SkillService(tmp)
        svc.create({
            "id": "persist-me",
            "name": "旧名",
            "description": "旧描述",
            "applies_to": ["text_analysis"],
            "body": "旧正文第一行\n第二行",
        })
        updated = svc.update("persist-me", {
            "name": "新名称",
            "description": "新描述 含:冒号",
            "applies_to": ["doc_writing", "orchestrator"],
            "body": "新正文\n含 --- 分隔线\n第三行 <tag>",
        })
        self.assertEqual(updated["name"], "新名称")
        self.assertEqual(updated["description"], "新描述 含:冒号")
        self.assertEqual(updated["applies_to"], ["doc_writing", "orchestrator"])
        self.assertIn("新正文", updated["body"])
        self.assertIn("---", updated["body"])
        self.assertIn("<tag>", updated["body"])
        again = svc.get("persist-me")
        self.assertEqual(again["body"], updated["body"])
        self.assertEqual(again["name"], "新名称")

    def test_update_allows_clearing_body_and_applies(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        svc = SkillService(tmp)
        svc.create({
            "id": "clear-me",
            "name": "X",
            "description": "D",
            "applies_to": ["text_analysis"],
            "body": "keep?",
        })
        svc.update("clear-me", {"body": "", "applies_to": [], "description": ""})
        got = svc.get("clear-me")
        self.assertEqual(got["body"], "")
        self.assertEqual(got["applies_to"], [])
        self.assertEqual(got["description"], "")

    def test_multiline_description_normalized(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        svc = SkillService(tmp)
        svc.create({"id": "ml", "name": "N", "description": "a", "applies_to": [], "body": "B1"})
        svc.update("ml", {"description": "line1\nline2", "body": "B2"})
        got = svc.get("ml")
        self.assertEqual(got["description"], "line1 line2")
        self.assertEqual(got["body"], "B2")
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        svc = SkillService(tmp)
        svc.create({
            "id": "case-split",
            "name": "案情拆解",
            "description": "争议焦点 证据缺口",
            "applies_to": ["text_analysis"],
            "body": "x",
        })
        hits = svc.match("请帮我看争议焦点", limit=3)
        self.assertEqual(hits[0]["id"], "case-split")

    def test_skill_priority_instruction_prefers_skill_over_mcp(self):
        from skill_service import SKILL_PRIORITY_MARKER, ensure_skill_priority_in_prompt
        prompt = ensure_skill_priority_in_prompt(
            "你是助手。先调用提示词模版。",
            [{"id": "judge-work", "name": "法官断案指南", "description": "法官断案"}],
        )
        self.assertIn(SKILL_PRIORITY_MARKER, prompt)
        self.assertIn("必须优先使用 Skill", prompt)
        self.assertIn("judge-work", prompt)
        self.assertTrue(prompt.index(SKILL_PRIORITY_MARKER) > prompt.index("你是助手"))
        again = ensure_skill_priority_in_prompt(prompt, [{"id": "x", "name": "X", "description": "y"}])
        self.assertEqual(again.count(SKILL_PRIORITY_MARKER), 1)
        self.assertIn("（x）", again)


if __name__ == "__main__":
    unittest.main()
