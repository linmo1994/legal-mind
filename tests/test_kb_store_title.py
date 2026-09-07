import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from kb_store import KbStore


class TestKbStoreTitle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = KbStore(self.tmp.name)
        self.store.ensure_schema()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_find_by_exact_title_prefers_newer(self):
        self.store.create_document(
            id="old",
            doc_type="law",
            file_id="f-old",
            title="中华人民共和国劳动合同法",
            status="ready",
            meta={},
            created_by=None,
        )
        import time
        time.sleep(0.02)
        self.store.create_document(
            id="new",
            doc_type="law",
            file_id="f-new",
            title="中华人民共和国劳动合同法",
            status="ready",
            meta={},
            created_by=None,
        )
        rows = self.store.find_documents_by_title(
            doc_type="law", title="中华人民共和国劳动合同法"
        )
        self.assertEqual(rows[0]["id"], "new")
        self.assertEqual(rows[0]["file_id"], "f-new")

    def test_exact_match_survives_limit_among_newer_partials(self):
        exact_title = "中华人民共和国劳动合同法"
        self.store.create_document(
            id="exact-old",
            doc_type="law",
            file_id="f-exact",
            title=exact_title,
            status="ready",
            meta={},
            created_by=None,
        )
        import time

        for i in range(12):
            time.sleep(0.01)
            self.store.create_document(
                id=f"partial-{i}",
                doc_type="law",
                file_id=f"f-partial-{i}",
                title=f"关于{exact_title}的实施细则第{i}号",
                status="ready",
                meta={},
                created_by=None,
            )
        rows = self.store.find_documents_by_title(
            doc_type="law", title=exact_title, limit=5
        )
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "exact-old")
        self.assertEqual(rows[0]["file_id"], "f-exact")

    def test_skips_deleted(self):
        self.store.create_document(
            id="d1",
            doc_type="law",
            file_id="f1",
            title="X法",
            status="deleted",
            meta={},
            created_by=None,
        )
        self.assertEqual(
            self.store.find_documents_by_title(doc_type="law", title="X法"), []
        )


if __name__ == "__main__":
    unittest.main()
