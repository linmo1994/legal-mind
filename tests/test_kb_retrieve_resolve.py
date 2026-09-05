import os
import sys
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from kb_retrieve_resolve import (  # noqa: E402
    empty_law_message,
    format_kb_hit_texts,
    resolve_law_regulation_text,
    resolve_similar_cases_text,
)


class TestKbRetrieveResolve(unittest.TestCase):
    def test_format_hits(self):
        text = format_kb_hit_texts(
            [
                {
                    "document": "第六十四条 ……",
                    "metadata": {"title": "劳动合同法", "doc_type": "law"},
                }
            ]
        )
        self.assertIn("劳动合同法", text)
        self.assertIn("第六十四条", text)

    def test_resolve_law_uses_doc_type_filter(self):
        vs = MagicMock()
        vs.search.return_value = [
            {
                "document": "法条正文",
                "metadata": {"title": "劳动合同法", "doc_type": "law"},
            }
        ]
        out = resolve_law_regulation_text(vs, "劳动合同法第64条")
        self.assertIn("劳动合同法", out)
        self.assertEqual(vs.search.call_args.kwargs.get("where"), {"doc_type": "law"})

    def test_resolve_case_uses_doc_type_filter(self):
        vs = MagicMock()
        vs.search.return_value = [
            {
                "document": "裁判要旨",
                "metadata": {"title": "（2023）民终1号", "doc_type": "case"},
            }
        ]
        out = resolve_similar_cases_text(vs, "民间借贷")
        self.assertIn("裁判要旨", out)
        self.assertEqual(vs.search.call_args.kwargs.get("where"), {"doc_type": "case"})

    def test_empty_when_no_vector(self):
        self.assertEqual(resolve_law_regulation_text(None, "x"), "")
        self.assertIn("法规库", empty_law_message("x"))


if __name__ == "__main__":
    unittest.main()
