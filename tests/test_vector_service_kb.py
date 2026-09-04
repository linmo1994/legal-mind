# tests/test_vector_service_kb.py
import os
import tempfile
import unittest

from vector_service import VectorService


class TestVectorServiceKb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vs = VectorService(persist_directory=os.path.join(self.tmp.name, "chroma"))
        # 强制哈希向量，避免下载模型
        self.vs.model = None

    def tearDown(self):
        self.tmp.cleanup()

    def test_search_filters_by_doc_type(self):
        self.vs.add_document("d_law", "劳动合同法第五十条 劳动者权利", {
            "doc_type": "law", "title": "劳动合同法", "law_name": "劳动合同法"
        })
        self.vs.add_document("d_case", "劳动合同法第五十条 相关判决事实", {
            "doc_type": "case", "title": "案1", "case_no": "A1"
        })
        laws = self.vs.search("第五十条", n_results=5, boost_keywords=False, where={"doc_type": "law"})
        cases = self.vs.search("第五十条", n_results=5, boost_keywords=False, where={"doc_type": "case"})
        self.assertTrue(all(r["metadata"].get("doc_type") == "law" for r in laws))
        self.assertTrue(all(r["metadata"].get("doc_type") == "case" for r in cases))
        self.assertTrue(any(r["metadata"].get("document_id") == "d_law" for r in laws))
        self.assertTrue(any(r["metadata"].get("document_id") == "d_case" for r in cases))

    def test_count_by_doc_type(self):
        self.vs.add_document("law_a", "劳动合同法第五十条 " * 80, {
            "doc_type": "law", "title": "劳动合同法"
        })
        self.vs.add_document("law_b", "民法典第一千条 " * 80, {
            "doc_type": "law", "title": "民法典"
        })
        self.vs.add_document("case_a", "劳动争议判决事实 " * 80, {
            "doc_type": "case", "title": "案1", "case_no": "A1"
        })
        self.assertEqual(self.vs.count_by_doc_type("law"), 2)
        self.assertEqual(self.vs.count_by_doc_type("case"), 1)
        self.assertEqual(self.vs.count_by_doc_type("unknown"), 0)

    def test_update_document_metadata_merges(self):
        text = "正文一段用于切分测试。" * 60  # >500 chars → multiple chunks
        added = self.vs.add_document("d1", text, {
            "doc_type": "case", "title": "旧", "case_no": "旧号"
        })
        self.assertGreater(added["chunks_count"], 1)
        out = self.vs.update_document_metadata("d1", {
            "title": "新", "case_no": "新号", "court": "北京一中院", "judges": ["张三", "李四"]
        })
        self.assertTrue(out["success"])
        self.assertEqual(out["updated_count"], added["chunks_count"])
        got = self.vs.collection.get(where={"document_id": "d1"}, include=["metadatas"])
        self.assertEqual(len(got["ids"]), added["chunks_count"])
        for meta in got["metadatas"]:
            self.assertEqual(meta["title"], "新")
            self.assertEqual(meta["case_no"], "新号")
            self.assertEqual(meta["court"], "北京一中院")
            self.assertEqual(meta["judges"], "张三; 李四")
            self.assertEqual(meta["doc_type"], "case")
            self.assertIn("chunk_index", meta)
            self.assertEqual(meta["total_chunks"], added["chunks_count"])
