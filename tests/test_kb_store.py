import os
import tempfile
import unittest

from kb_store import KbStore


class TestKbStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = KbStore(os.path.join(self.tmp.name, "kb.db"))
        self.store.ensure_schema()

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_and_list_by_type(self):
        self.store.create_document(
            id="kb_law_1",
            doc_type="law",
            file_id="f1",
            title="劳动合同法",
            status="ready",
            meta={"law_name": "劳动合同法", "effect_level": "法律"},
            created_by="u1",
        )
        self.store.create_document(
            id="kb_case_1",
            doc_type="case",
            file_id="f2",
            title="(2020)京01民终1号",
            status="ready",
            meta={"case_no": "(2020)京01民终1号", "case_kind": "ordinary"},
            created_by="u1",
        )
        laws = self.store.list_documents(doc_type="law")
        self.assertEqual(len(laws), 1)
        self.assertEqual(laws[0]["meta"]["law_name"], "劳动合同法")
        self.assertEqual(self.store.count_documents(doc_type="law"), 1)
        self.assertEqual(self.store.count_documents(doc_type="case"), 1)

    def test_soft_delete_hides_from_list(self):
        self.store.create_document(
            id="kb_x",
            doc_type="law",
            file_id=None,
            title="x",
            status="ready",
            meta={},
            created_by=None,
        )
        self.assertTrue(self.store.soft_delete("kb_x"))
        self.assertEqual(self.store.list_documents(doc_type="law"), [])
        self.assertIsNone(self.store.get_document("kb_x"))
        self.assertIsNotNone(self.store.get_document("kb_x", include_deleted=True))

    def test_update_meta_and_status(self):
        self.store.create_document(
            id="kb_u",
            doc_type="case",
            file_id="f",
            title="旧",
            status="meta_failed",
            meta={},
            created_by=None,
        )
        row = self.store.update_document(
            "kb_u",
            title="新案号",
            status="ready",
            meta={"case_no": "新案号", "case_kind": "guiding"},
        )
        self.assertEqual(row["title"], "新案号")
        self.assertEqual(row["status"], "ready")
        self.assertEqual(row["meta"]["case_kind"], "guiding")


if __name__ == "__main__":
    unittest.main()
