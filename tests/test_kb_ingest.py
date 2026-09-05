import os, tempfile, unittest
from kb_store import KbStore
from kb_ingest import ingest_uploaded_file, title_from_meta
from vector_service import VectorService


class FakeFileService:
    def __init__(self, mapping, names=None):
        self.mapping = mapping
        self.names = names or {}

    def get_file_text(self, file_id):
        return self.mapping.get(file_id)

    def get_file(self, file_id):
        if file_id not in self.mapping and file_id not in self.names:
            return None
        return {"original_name": self.names.get(file_id, file_id)}


class TestKbIngest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kb = KbStore(os.path.join(self.tmp.name, "kb.db"))
        self.kb.ensure_schema()
        self.vs = VectorService(persist_directory=os.path.join(self.tmp.name, "chroma"))
        self.vs.model = None
        self.files = FakeFileService({"f1": "中华人民共和国劳动合同法 第一条 …" * 5})

    def tearDown(self):
        self.tmp.cleanup()

    def test_title_from_meta(self):
        self.assertEqual(title_from_meta("law", {"law_name": "民法典"}, "x"), "民法典")
        self.assertEqual(title_from_meta("case", {"case_no": "", "cause_of_action": "劳动争议"}, "x"), "劳动争议")
        self.assertEqual(
            title_from_meta("template", {"template_name": "民事起诉状"}, "x"),
            "民事起诉状",
        )

    def test_ingest_template_uses_full_filename_as_name(self):
        files = FakeFileService(
            {"f_tpl": "要素式起诉状模板正文 …" * 5},
            names={"f_tpl": "民间借贷纠纷起诉状.docx"},
        )

        def fake(system, user):
            self.assertIn("民间借贷纠纷起诉状", user)
            return '{"template_name":"起诉状","document_type":"起诉状","case_category":"民事"}'

        doc = ingest_uploaded_file(
            doc_type="template",
            file_id="f_tpl",
            created_by="u1",
            kb_store=self.kb,
            file_service=files,
            vector_service=self.vs,
            complete_fn=fake,
        )
        self.assertEqual(doc["status"], "ready")
        self.assertEqual(doc["meta"]["template_name"], "民间借贷纠纷起诉状")
        self.assertEqual(doc["title"], "民间借贷纠纷起诉状")

    def test_ingest_happy_path(self):
        def fake(system, user):
            return '{"law_name":"劳动合同法","effect_level":"法律","issuing_authority":"全国人大常委会","document_number":"","effective_date":"2008-01-01"}'
        doc = ingest_uploaded_file(
            doc_type="law",
            file_id="f1",
            created_by="u1",
            kb_store=self.kb,
            file_service=self.files,
            vector_service=self.vs,
            complete_fn=fake,
        )
        self.assertEqual(doc["status"], "ready")
        self.assertEqual(doc["meta"]["law_name"], "劳动合同法")
        hits = self.vs.search("劳动合同法", n_results=3, boost_keywords=False, where={"doc_type": "law"})
        self.assertTrue(any(h["metadata"]["document_id"] == doc["id"] for h in hits))

    def test_ingest_empty_text(self):
        files = FakeFileService({"f2": None})
        doc = ingest_uploaded_file(
            doc_type="case",
            file_id="f2",
            created_by=None,
            kb_store=self.kb,
            file_service=files,
            vector_service=self.vs,
            complete_fn=lambda s, u: "{}",
        )
        self.assertEqual(doc["status"], "extract_failed")

    def test_ingest_llm_transport_error_still_vectorizes(self):
        def boom(system, user):
            raise OSError("timeout")

        doc = ingest_uploaded_file(
            doc_type="law",
            file_id="f1",
            created_by="u1",
            kb_store=self.kb,
            file_service=self.files,
            vector_service=self.vs,
            complete_fn=boom,
        )
        self.assertEqual(doc["status"], "meta_failed")
        self.assertEqual(doc["meta"].get("law_name"), "")
        hits = self.vs.search(
            "劳动合同法", n_results=3, boost_keywords=False, where={"doc_type": "law"}
        )
        self.assertTrue(any(h["metadata"]["document_id"] == doc["id"] for h in hits))


if __name__ == "__main__":
    unittest.main()
