# tests/test_kb_query_parse.py
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from kb_query_parse import (  # noqa: E402
    build_fts_match,
    doc_has_article,
    extract_articles,
    extract_law_name_hint,
    normalize_article_forms,
    resolve_hit_article,
)


class TestKbQueryParse(unittest.TestCase):
    def test_extract_article_and_law(self):
        arts_cn = extract_articles("检索劳动合同法第六十四条")
        arts_ar = extract_articles("检索劳动合同法第64条")
        self.assertTrue(
            "第六十四条" in arts_cn or "第64条" in arts_ar or "第64条" in arts_cn
        )
        hint = extract_law_name_hint("检索劳动合同法第64条")
        self.assertTrue(hint)
        self.assertIn("劳动", hint)

    def test_law_hint_strips_stacked_search_verbs(self):
        """「帮我检索…」 must not glue 检索 into the law name (breaks FTS / title filter)."""
        hint = extract_law_name_hint("帮我检索劳动合同法第64条")
        self.assertEqual(hint, "劳动合同法")
        hint2 = extract_law_name_hint("请帮我查找中华人民共和国劳动合同法第六十四条")
        self.assertTrue(hint2)
        self.assertTrue(hint2.endswith("劳动合同法") or hint2 == "中华人民共和国劳动合同法")
        self.assertNotIn("检索", hint2 or "")
        self.assertNotIn("查找", hint2 or "")

    def test_law_and_article_fts_match_is_article_focused(self):
        """Law name is filtered via title column; MATCH must not AND a polluted law phrase."""
        m = build_fts_match("帮我检索劳动合同法第64条")
        self.assertNotIn("检索劳动合同法", m)
        self.assertTrue("第六十四条" in m or "第64条" in m)
        # Must not require the law phrase inside body_idx (unicode61 keeps full title as one token)
        self.assertNotIn(" AND ", m)

    def test_and_when_law_and_article(self):
        # Legacy name kept: law+article queries still include article forms
        m = build_fts_match("检索劳动合同法第六十四条")
        self.assertTrue("第六十四条" in m or "第64条" in m)
        self.assertNotIn("检索劳动合同法", m)

    def test_or_fallback_without_law(self):
        m = build_fts_match("第六十四条")
        self.assertIn("第六十四条", m)
        # No law hint → OR-style fallback (single token may have no OR)
        self.assertNotIn(" AND ", m)

    def test_article_forms(self):
        forms = normalize_article_forms("第64条")
        self.assertTrue(any("六十四" in f or f == "第64条" for f in forms))
        forms2 = normalize_article_forms("第六十四条")
        self.assertTrue(any("64" in f or f == "第六十四条" for f in forms2))

    def test_article_forms_110_legal_chinese(self):
        forms = normalize_article_forms("第110条")
        self.assertIn("第一百一十条", forms)

    def test_doc_has_article_and_resolve(self):
        doc = "第三十八条 用人单位……第四十条 ……"
        self.assertFalse(doc_has_article(doc, "第64条"))
        self.assertTrue(doc_has_article(doc, "第38条"))
        self.assertEqual(
            resolve_hit_article(doc, "帮我检索劳动合同法第64条"),
            "第三十八条",
        )
        doc64 = "第六十四条 非全日制用工……"
        self.assertEqual(
            resolve_hit_article(doc64, "帮我检索劳动合同法第64条"),
            "第六十四条",
        )


if __name__ == "__main__":
    unittest.main()
