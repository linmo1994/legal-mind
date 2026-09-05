# tests/test_kb_query_parse.py
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from kb_query_parse import (  # noqa: E402
    build_fts_match,
    extract_articles,
    extract_law_name_hint,
    normalize_article_forms,
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

    def test_and_when_law_and_article(self):
        m = build_fts_match("检索劳动合同法第六十四条")
        self.assertIn(" AND ", m)
        # Main join is AND; OR may appear inside law/article variant groups
        self.assertTrue("第六十四条" in m or "第64条" in m)
        self.assertTrue("劳动" in m or "劳动合同法" in m)

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


if __name__ == "__main__":
    unittest.main()
