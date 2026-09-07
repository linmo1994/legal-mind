# tests/test_kb_external_hint.py
import os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from kb_external_hint import (
    assess_case_retrieve_miss,
    assess_law_retrieve_miss,
    build_case_external_search_hint,
    build_external_search_hint,
)

class TestKbExternalHint(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(
            assess_law_retrieve_miss("劳动合同法第六十四条", citations=[], laws_text=""),
            "empty",
        )

    def test_hit_no_hint(self):
        cites = [{
            "title": "中华人民共和国劳动合同法",
            "article": "第六十四条",
            "snippet": "第六十四条　被派遣劳动者有权……",
        }]
        self.assertIsNone(
            assess_law_retrieve_miss("帮我检索劳动合同法第64条", citations=cites)
        )

    def test_law_mismatch(self):
        cites = [{
            "title": "中华人民共和国食品安全法",
            "article": "第六十四条",
            "snippet": "第六十四条　食用农产品……",
        }]
        self.assertEqual(
            assess_law_retrieve_miss("帮我检索劳动合同法第64条", citations=cites),
            "law_mismatch",
        )

    def test_article_mismatch(self):
        cites = [{
            "title": "中华人民共和国劳动合同法",
            "article": "第三十八条",
            "snippet": "第三十八条 用人单位有下列情形……",
        }]
        self.assertEqual(
            assess_law_retrieve_miss("帮我检索劳动合同法第64条", citations=cites),
            "article_mismatch",
        )

    def test_build_hint_fields(self):
        h = build_external_search_hint("帮我检索劳动合同法第64条", "article_mismatch")
        self.assertTrue(h["needed"])
        self.assertEqual(h["provider"], "npc_flk")
        self.assertEqual(h["label"], "国家法律法规数据库")
        self.assertIn("flk.npc.gov.cn", h["url"])
        self.assertIn("未自动抓取", h["note"])
        self.assertIn("劳动", h["query"])
        self.assertTrue("64" in h["query"] or "六十四" in h["query"])

    def test_case_miss_empty(self):
        self.assertEqual(
            assess_case_retrieve_miss("食品服务合同", citations=[], cases_text=""),
            "empty",
        )

    def test_case_hit_no_miss(self):
        self.assertIsNone(
            assess_case_retrieve_miss(
                "民间借贷",
                citations=[{"title": "（2025）最高法民再142号"}],
                cases_text="……",
            )
        )

    def test_build_case_hint(self):
        h = build_case_external_search_hint("食品服务合同 十倍赔偿", "empty")
        self.assertTrue(h["needed"])
        self.assertEqual(h["provider"], "court_wenshu")
        self.assertIn("wenshu.court.gov.cn", h["url"])
        self.assertIn("类案", h["note"])
