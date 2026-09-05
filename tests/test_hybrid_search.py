import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))


class TestVectorFtsSync(unittest.TestCase):
    def test_attach_and_upsert_on_add(self):
        # Lightweight stub: avoid loading SentenceTransformer / Chroma
        from vector_service import VectorService

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        chroma_dir = os.path.join(tmp.name, "chroma")
        fts_path = os.path.join(tmp.name, "kb.db")

        vs = VectorService.__new__(VectorService)
        vs.persist_directory = chroma_dir
        vs.collection_name = "legal_documents"
        vs.model = None
        vs.fts = None
        vs.client = MagicMock()
        coll = MagicMock()
        coll.get.return_value = {"ids": ["doc1_chunk_0"]}
        vs.collection = coll
        vs.attach_fts(fts_path)

        vs._split_text = lambda text, **kw: [text]
        vs._generate_embedding = lambda text: [0.1] * 8

        result = VectorService.add_document(
            vs,
            "doc1",
            "劳动合同法第六十四条内容",
            {"doc_type": "law", "title": "劳动合同法"},
        )
        self.assertTrue(result.get("success"))
        hits = vs.fts.search("第六十四条", doc_type="law")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["chunk_id"], "doc1_chunk_0")

        delete_result = VectorService.delete_document(vs, "doc1")
        self.assertTrue(delete_result.get("success"))
        self.assertEqual(vs.fts.search("第六十四条"), [])

    def test_delete_clears_fts_when_chroma_empty(self):
        from vector_service import VectorService

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fts_path = os.path.join(tmp.name, "kb.db")

        vs = VectorService.__new__(VectorService)
        vs.persist_directory = os.path.join(tmp.name, "chroma")
        vs.collection_name = "legal_documents"
        vs.model = None
        vs.fts = None
        vs.client = MagicMock()
        coll = MagicMock()
        coll.get.return_value = {"ids": []}
        vs.collection = coll
        vs.attach_fts(fts_path)

        vs.fts.upsert_chunks(
            [
                {
                    "chunk_id": "orphan_chunk_0",
                    "document_id": "orphan",
                    "doc_type": "law",
                    "body": "残留第六十四条条文",
                }
            ]
        )
        self.assertTrue(vs.fts.search("第六十四条"))

        result = VectorService.delete_document(vs, "orphan")
        self.assertFalse(result.get("success"))  # chroma had no ids
        self.assertEqual(vs.fts.search("第六十四条"), [])

    def test_rebuild_fts_from_chroma(self):
        from vector_service import VectorService

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fts_path = os.path.join(tmp.name, "kb.db")

        vs = VectorService.__new__(VectorService)
        vs.persist_directory = os.path.join(tmp.name, "chroma")
        vs.collection_name = "legal_documents"
        vs.model = None
        vs.fts = None
        vs.client = MagicMock()
        coll = MagicMock()
        coll.get.return_value = {
            "ids": ["doc1_chunk_0", "stale_chunk_0"],
            "documents": [
                "劳动合同法第六十四条 集体合同内容",
                "应被清空的旧条文",
            ],
            "metadatas": [
                {"document_id": "doc1", "doc_type": "law"},
                {"document_id": "stale", "doc_type": "case"},
            ],
        }
        vs.collection = coll
        vs.attach_fts(fts_path)

        # Pre-seed FTS with orphan that must be cleared by rebuild
        vs.fts.upsert_chunks(
            [
                {
                    "chunk_id": "orphan_only",
                    "document_id": "orphan",
                    "doc_type": "law",
                    "body": "孤儿残留条文不应保留",
                }
            ]
        )
        self.assertEqual(vs.fts.count(), 1)

        out = VectorService.rebuild_fts_from_chroma(vs)
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("chunks"), 2)
        coll.get.assert_called_with(include=["documents", "metadatas"])

        hits = vs.fts.search("第六十四条", doc_type="law")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["chunk_id"], "doc1_chunk_0")
        self.assertEqual(vs.fts.search("孤儿残留"), [])
        self.assertEqual(vs.fts.count(), 2)

    def test_rebuild_fts_without_attach(self):
        from vector_service import VectorService

        vs = VectorService.__new__(VectorService)
        vs.fts = None
        vs.collection = MagicMock()
        out = VectorService.rebuild_fts_from_chroma(vs)
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("error"), "fts not attached")

    def test_attach_rebuilds_when_schema_version_stale(self):
        from vector_service import VectorService
        from kb_fts import KbFtsIndex

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fts_path = os.path.join(tmp.name, "kb.db")

        # Simulate legacy index: rows present, schema version 1
        legacy = KbFtsIndex(fts_path)
        legacy.ensure_schema()
        legacy.upsert_chunks(
            [
                {
                    "chunk_id": "old_chunk",
                    "document_id": "old",
                    "doc_type": "law",
                    "body": "旧索引条文第六十四条",
                }
            ]
        )
        legacy.set_schema_version(1)
        self.assertEqual(legacy.get_schema_version(), 1)

        vs = VectorService.__new__(VectorService)
        vs.persist_directory = os.path.join(tmp.name, "chroma")
        vs.collection_name = "legal_documents"
        vs.model = None
        vs.fts = None
        vs.client = MagicMock()
        coll = MagicMock()
        coll.get.return_value = {
            "ids": ["doc1_chunk_0"],
            "documents": ["劳动合同法第六十四条 集体合同"],
            "metadatas": [
                {
                    "document_id": "doc1",
                    "doc_type": "law",
                    "title": "劳动合同法",
                }
            ],
        }
        vs.collection = coll
        vs.attach_fts(fts_path)

        self.assertEqual(vs.fts.get_schema_version(), 3)
        self.assertEqual(vs.fts.search("旧索引条文"), [])
        hits = vs.fts.search("劳动合同法第六十四条", doc_type="law")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["chunk_id"], "doc1_chunk_0")
        self.assertEqual(hits[0].get("title"), "劳动合同法")
        # Title should be searchable via body_idx
        self.assertTrue(vs.fts.search("劳动合同法"))


class TestHybridSearch(unittest.TestCase):
    def _make_vs(self, *, fts=None, query_return=None):
        from vector_service import VectorService

        vs = VectorService.__new__(VectorService)
        vs.model = None
        vs.fts = fts
        vs.client = MagicMock()
        coll = MagicMock()
        coll.count.return_value = 0
        if query_return is None:
            query_return = {
                "ids": [[]],
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
            }
        coll.query.return_value = query_return
        vs.collection = coll
        vs._generate_embedding = lambda q: [0.0] * 8
        return vs

    def test_rrf_prefers_dual_hit(self):
        from vector_service import VectorService

        fts = MagicMock()
        # FTS ranks A first, B second; vector only returns B → B is dual-hit
        fts.search.return_value = [
            {
                "chunk_id": "chunk_a",
                "document_id": "a",
                "doc_type": "law",
                "body": "仅词法命中 第六十四条",
                "fts_rank": 1,
            },
            {
                "chunk_id": "chunk_b",
                "document_id": "b",
                "doc_type": "law",
                "body": "双路命中 第六十四条",
                "fts_rank": 2,
            },
        ]
        vs = self._make_vs(
            fts=fts,
            query_return={
                "ids": [["chunk_b"]],
                "documents": [["向量侧正文 B"]],
                "metadatas": [[{"document_id": "b", "doc_type": "law"}]],
                "distances": [[0.2]],
            },
        )

        results = VectorService.search(
            vs, "第六十四条", n_results=5, boost_keywords=False
        )
        self.assertTrue(results)
        self.assertEqual(results[0]["id"], "chunk_b")
        self.assertIn("rrf_score", results[0])
        self.assertEqual(results[0].get("vector_rank"), 1)
        self.assertEqual(results[0].get("fts_rank"), 2)
        ids = [r["id"] for r in results]
        self.assertIn("chunk_a", ids)
        self.assertLess(ids.index("chunk_b"), ids.index("chunk_a"))

    def test_fts_only_chunk_still_returned(self):
        from vector_service import VectorService
        from kb_fts import KbFtsIndex

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fts = KbFtsIndex(os.path.join(tmp.name, "kb.db"))
        fts.ensure_schema()
        fts.upsert_chunks(
            [
                {
                    "chunk_id": "lex_only_0",
                    "document_id": "lex_only",
                    "doc_type": "law",
                    "title": "劳动合同法",
                    "body": "劳动合同法第六十四条 集体合同内容",
                }
            ]
        )
        vs = self._make_vs(fts=fts)  # vector empty

        results = VectorService.search(
            vs, "第六十四条", n_results=5, boost_keywords=False
        )
        self.assertTrue(results)
        self.assertEqual(results[0]["id"], "lex_only_0")
        self.assertIn("第六十四条", results[0]["document"])
        self.assertIsNone(results[0].get("distance"))
        self.assertEqual(results[0].get("fts_rank"), 1)
        self.assertIsNone(results[0].get("vector_rank"))
        meta = results[0].get("metadata") or {}
        self.assertEqual(meta.get("document_id"), "lex_only")
        self.assertEqual(meta.get("doc_type"), "law")
        self.assertEqual(meta.get("title"), "劳动合同法")

    def test_hybrid_false_skips_fts(self):
        from vector_service import VectorService

        fts = MagicMock()
        fts.search = MagicMock(
            return_value=[
                {
                    "chunk_id": "should_not_appear",
                    "document_id": "x",
                    "doc_type": "law",
                    "body": "不应出现",
                    "fts_rank": 1,
                }
            ]
        )
        vs = self._make_vs(
            fts=fts,
            query_return={
                "ids": [["vec_only"]],
                "documents": [["纯向量结果"]],
                "metadatas": [[{"document_id": "v", "doc_type": "law"}]],
                "distances": [[0.1]],
            },
        )

        results = VectorService.search(
            vs, "第六十四条", n_results=5, boost_keywords=False, hybrid=False
        )
        fts.search.assert_not_called()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "vec_only")
        self.assertNotIn("rrf_score", results[0])

    def test_fts_raise_falls_back_to_vector(self):
        from vector_service import VectorService

        fts = MagicMock()
        fts.search.side_effect = RuntimeError("fts boom")
        vs = self._make_vs(
            fts=fts,
            query_return={
                "ids": [["vec_a", "vec_b"]],
                "documents": [["向量A", "向量B"]],
                "metadatas": [
                    [
                        {"document_id": "a", "doc_type": "law"},
                        {"document_id": "b", "doc_type": "law"},
                    ]
                ],
                "distances": [[0.1, 0.2]],
            },
        )

        results = VectorService.search(
            vs, "第六十四条", n_results=2, boost_keywords=False
        )
        fts.search.assert_called()
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["id"], "vec_a")
        self.assertNotIn("rrf_score", results[0])

    def test_no_fts_truncates_expanded_k_vec(self):
        from vector_service import VectorService

        # hybrid=True but fts is None → vector-only; k_vec expands beyond n_results
        ids = [f"c{i}" for i in range(12)]
        vs = self._make_vs(
            fts=None,
            query_return={
                "ids": [ids],
                "documents": [[f"doc{i}" for i in range(12)]],
                "metadatas": [[{"document_id": f"d{i}", "doc_type": "law"} for i in range(12)]],
                "distances": [[0.01 * i for i in range(12)]],
            },
        )

        results = VectorService.search(
            vs, "查询", n_results=3, boost_keywords=False, hybrid=True
        )
        # collection.query should have been asked for expanded k_vec (>=10)
        kwargs = vs.collection.query.call_args.kwargs
        self.assertGreaterEqual(kwargs["n_results"], 10)
        self.assertEqual(len(results), 3)
        self.assertNotIn("rrf_score", results[0])

    def test_title_boost_prefers_matching_law(self):
        """Same article number, different titles → query with 劳动合同法 ranks it first."""
        from vector_service import VectorService
        from kb_fts import KbFtsIndex

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fts = KbFtsIndex(os.path.join(tmp.name, "kb.db"))
        fts.ensure_schema()
        body = "第六十四条 相关规定内容"
        fts.upsert_chunks(
            [
                {
                    "chunk_id": "food_chunk_0",
                    "document_id": "food",
                    "doc_type": "law",
                    "title": "食品安全法",
                    "body": body,
                },
                {
                    "chunk_id": "labor_chunk_0",
                    "document_id": "labor",
                    "doc_type": "law",
                    "title": "劳动合同法",
                    "body": body,
                },
            ]
        )
        # Vector prefers food safety first (wrong for this query)
        vs = self._make_vs(
            fts=fts,
            query_return={
                "ids": [["food_chunk_0", "labor_chunk_0"]],
                "documents": [[body, body]],
                "metadatas": [
                    [
                        {
                            "document_id": "food",
                            "doc_type": "law",
                            "title": "食品安全法",
                        },
                        {
                            "document_id": "labor",
                            "doc_type": "law",
                            "title": "劳动合同法",
                        },
                    ]
                ],
                "distances": [[0.05, 0.25]],
            },
        )

        results = VectorService.search(
            vs,
            "劳动合同法第六十四条",
            n_results=5,
            boost_keywords=True,
            hybrid=True,
        )
        self.assertTrue(results)
        top_meta = results[0].get("metadata") or {}
        top_title = top_meta.get("title") or top_meta.get("law_name") or ""
        self.assertIn("劳动合同法", top_title)
        self.assertEqual(results[0]["id"], "labor_chunk_0")
        # Hard filter: unrelated statute dropped when matching title exists
        titles = [
            ((r.get("metadata") or {}).get("title") or "")
            for r in results
        ]
        self.assertTrue(all("食品安全" not in t for t in titles))
        self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()