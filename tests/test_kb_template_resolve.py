import os
import tempfile
import unittest

from kb_store import KbStore
from kb_template_resolve import (
    find_template_doc,
    list_template_names,
    resolve_template_text,
)


class FakeFiles:
    def __init__(self, texts):
        self.texts = texts

    def get_file_text(self, file_id):
        return self.texts.get(file_id)


class TestKbTemplateResolve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kb = KbStore(os.path.join(self.tmp.name, "kb.db"))
        self.kb.ensure_schema()
        self.kb.create_document(
            id="kb_template_1",
            doc_type="template",
            file_id="f1",
            title="民间借贷纠纷起诉状",
            status="ready",
            meta={
                "template_name": "民间借贷纠纷起诉状",
                "document_type": "起诉状",
                "case_category": "民事",
                "validity": "有效",
            },
            created_by="u",
        )
        self.kb.create_document(
            id="kb_template_2",
            doc_type="template",
            file_id="f2",
            title="离婚纠纷答辩状",
            status="ready",
            meta={
                "template_name": "离婚纠纷答辩状",
                "document_type": "答辩状",
                "case_category": "民事",
                "validity": "失效",
            },
            created_by="u",
        )
        self.files = FakeFiles({"f1": "【要素式】民间借贷纠纷起诉状正文……"})

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_skips_invalid(self):
        names = list_template_names(self.kb)
        self.assertEqual(names, ["民间借贷纠纷起诉状"])

    def test_find_and_resolve(self):
        doc = find_template_doc(self.kb, "民间借贷起诉状")
        self.assertIsNotNone(doc)
        self.assertEqual(doc["id"], "kb_template_1")
        text, matched, available = resolve_template_text(
            "民间借贷纠纷起诉状",
            kb_store=self.kb,
            file_service=self.files,
        )
        self.assertEqual(matched, "民间借贷纠纷起诉状")
        self.assertIn("要素式", text)
        self.assertEqual(available, ["民间借贷纠纷起诉状"])

    def test_not_found(self):
        text, matched, available = resolve_template_text(
            "不存在的模板xyz",
            kb_store=self.kb,
            file_service=self.files,
        )
        self.assertIsNone(text)
        self.assertIsNone(matched)
        self.assertEqual(available, ["民间借贷纠纷起诉状"])


if __name__ == "__main__":
    unittest.main()
