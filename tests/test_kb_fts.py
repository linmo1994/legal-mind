# tests/test_kb_fts.py
import os
import tempfile
import unittest
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from kb_fts import KbFtsIndex, normalize_fts_query, rrf_fuse  # noqa: E402


class TestKbFts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.idx = KbFtsIndex(os.path.join(self.tmp.name, "kb.db"))
        self.idx.ensure_schema()

    def tearDown(self):
        self.tmp.cleanup()

    def test_upsert_and_search_article(self):
        body = "劳动合同法第六十四条 集体合同……"
        self.idx.upsert_chunks([
            {
                "chunk_id": "d1_chunk_0",
                "document_id": "d1",
                "doc_type": "law",
                "body": body,
            },
            {
                "chunk_id": "d2_chunk_0",
                "document_id": "d2",
                "doc_type": "case",
                "body": "某民间借贷纠纷判决要旨……",
            },
        ])
        hits = self.idx.search("第六十四条", doc_type="law", limit=5)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["chunk_id"], "d1_chunk_0")
        self.assertEqual(hits[0]["fts_rank"], 1)
        # Returned body must be original (no index-time spacing)
        self.assertEqual(hits[0]["body"], body)
        self.assertIn("劳动合同法第六十四条", hits[0]["body"])

    def test_law_plus_article_prefers_matching_title(self):
        """Same article number in two laws → query naming 劳动合同法 must rank that title first."""
        self.idx.upsert_chunks(
            [
                {
                    "chunk_id": "food_64",
                    "document_id": "food",
                    "doc_type": "law",
                    "title": "中华人民共和国食品安全法",
                    "body": "第六十四条　食用农产品批发市场违反本法规定的……",
                },
                {
                    "chunk_id": "labor_64",
                    "document_id": "labor",
                    "doc_type": "law",
                    "title": "中华人民共和国劳动合同法",
                    "body": "第六十四条　被派遣劳动者有权在劳务派遣单位或者用工单位依法参加或者组织工会……",
                },
            ]
        )
        hits = self.idx.search("帮我检索劳动合同法第64条", doc_type="law", limit=5)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["chunk_id"], "labor_64")
        self.assertIn("劳动合同法", hits[0].get("title") or "")

    def test_delete_by_document(self):
        self.idx.upsert_chunks([{
            "chunk_id": "d1_chunk_0",
            "document_id": "d1",
            "doc_type": "law",
            "body": "测试条文",
        }])
        self.assertEqual(self.idx.delete_by_document_id("d1"), 1)
        self.assertEqual(self.idx.search("测试条文"), [])

    def test_count_and_document_id_filter(self):
        self.idx.upsert_chunks([
            {
                "chunk_id": "d1_chunk_0",
                "document_id": "d1",
                "doc_type": "law",
                "body": "劳动合同法第六十四条 甲",
            },
            {
                "chunk_id": "d1_chunk_1",
                "document_id": "d1",
                "doc_type": "law",
                "body": "劳动合同法第六十四条 乙",
            },
            {
                "chunk_id": "d2_chunk_0",
                "document_id": "d2",
                "doc_type": "law",
                "body": "劳动合同法第六十四条 丙",
            },
        ])
        self.assertEqual(self.idx.count(), 3)
        hits = self.idx.search("第六十四条", document_id="d1", limit=10)
        self.assertEqual(len(hits), 2)
        self.assertTrue(all(h["document_id"] == "d1" for h in hits))

    def test_rrf_fuse(self):
        fused = rrf_fuse([["a", "b"], ["b", "c"]], rrf_k=60)
        ids = [x[0] for x in fused]
        self.assertEqual(ids[0], "b")  # 两路皆命中

    def test_normalize_keeps_article(self):
        q = normalize_fts_query("检索劳动合同法第六十四条")
        self.assertIn("第六十四条", q)

    def test_upsert_title_in_body_idx_not_body(self):
        """Optional title is indexed in body_idx; returned body stays raw."""
        import sqlite3

        body = "第六十四条 集体合同内容"
        self.idx.upsert_chunks(
            [
                {
                    "chunk_id": "d1_chunk_0",
                    "document_id": "d1",
                    "doc_type": "law",
                    "title": "劳动合同法",
                    "body": body,
                }
            ]
        )
        hits = self.idx.search("劳动合同法第六十四条", doc_type="law", limit=5)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["body"], body)

        with sqlite3.connect(self.idx.db_path) as conn:
            row = conn.execute(
                "SELECT body, body_idx FROM kb_chunks_fts WHERE chunk_id = ?",
                ("d1_chunk_0",),
            ).fetchone()
        self.assertEqual(row[0], body)
        self.assertTrue(row[1].startswith("劳动合同法"))
        self.assertIn("第六十四条", row[1])
        self.assertEqual(hits[0].get("title"), "劳动合同法")

        with sqlite3.connect(self.idx.db_path) as conn:
            row2 = conn.execute(
                "SELECT title FROM kb_chunks_fts WHERE chunk_id = ?",
                ("d1_chunk_0",),
            ).fetchone()
        self.assertEqual(row2[0], "劳动合同法")

    def test_schema_version_meta(self):
        self.assertEqual(self.idx.get_schema_version(), 3)


if __name__ == "__main__":
    unittest.main()