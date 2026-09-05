import os
import sys
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from http_api_extra import (  # noqa: E402
    format_kb_hits,
    hits_to_citations,
    make_kb_retrieve_fn,
)


class TestKbRetrieve(unittest.TestCase):
    def test_format_kb_hits(self):
        text = format_kb_hits(
            [
                {
                    "document": "第一条 ……",
                    "metadata": {"title": "劳动合同法", "doc_type": "law"},
                    "similarity": 0.9,
                }
            ],
            limit=3,
        )
        self.assertIn("劳动合同法", text)
        self.assertIn("第一条", text)

    def test_hits_to_citations_fields(self):
        hits = [
            {
                "id": "doc1_chunk_0",
                "document": "第六十四条 集体合同……" + ("x" * 500),
                "metadata": {
                    "doc_type": "law",
                    "document_id": "doc1",
                    "file_id": "f-law-1",
                    "title": "劳动合同法",
                },
                "rrf_score": 0.032,
            }
        ]
        cites = hits_to_citations(hits, "检索劳动合同法第六十四条")
        self.assertEqual(len(cites), 1)
        c = cites[0]
        self.assertEqual(c["id"], "doc1_chunk_0")
        self.assertEqual(c["doc_type"], "law")
        self.assertEqual(c["document_id"], "doc1")
        self.assertEqual(c["file_id"], "f-law-1")
        self.assertEqual(c["title"], "劳动合同法")
        self.assertEqual(c["article"], "第六十四条")
        self.assertEqual(len(c["snippet"]), 400)
        self.assertAlmostEqual(c["rrf_score"], 0.032)

    def test_hits_to_citations_dedupes_same_file_article(self):
        hits = [
            {
                "id": "doc1_chunk_0",
                "document": "第六十四条 段一",
                "metadata": {
                    "doc_type": "law",
                    "document_id": "doc1",
                    "file_id": "f-law-1",
                    "title": "劳动合同法",
                },
            },
            {
                "id": "doc1_chunk_1",
                "document": "第六十四条 段二",
                "metadata": {
                    "doc_type": "law",
                    "document_id": "doc1",
                    "file_id": "f-law-1",
                    "title": "劳动合同法",
                },
            },
        ]
        cites = hits_to_citations(hits, "劳动合同法第六十四条")
        self.assertEqual(len(cites), 1)
        self.assertEqual(cites[0]["file_id"], "f-law-1")

    def test_retrieve_scopes_call_vector_with_doc_type(self):
        vs = MagicMock()
        vs.search.side_effect = [
            [
                {
                    "id": "law0",
                    "document": "法条A 第六十四条",
                    "metadata": {
                        "title": "X法",
                        "doc_type": "law",
                        "document_id": "d-law",
                        "file_id": "f1",
                    },
                    "rrf_score": 0.01,
                    "similarity": 0.8,
                }
            ],
            [
                {
                    "id": "case0",
                    "document": "判决要旨",
                    "metadata": {
                        "title": "案号1",
                        "doc_type": "case",
                        "document_id": "d-case",
                        "file_id": "f2",
                    },
                    "similarity": 0.7,
                }
            ],
        ]
        server = MagicMock()
        server.vector_service = vs
        retrieve = make_kb_retrieve_fn(server)
        out = retrieve("民间借贷第六十四条", scopes=["law", "case"])
        self.assertIn("法条A", out["laws"])
        self.assertIn("判决要旨", out["cases"])
        self.assertEqual(vs.search.call_args_list[0].kwargs.get("where"), {"doc_type": "law"})
        self.assertEqual(vs.search.call_args_list[1].kwargs.get("where"), {"doc_type": "case"})
        self.assertEqual(len(out["law_citations"]), 1)
        self.assertEqual(out["law_citations"][0]["file_id"], "f1")
        self.assertEqual(out["law_citations"][0]["title"], "X法")
        self.assertEqual(out["law_citations"][0]["article"], "第六十四条")
        self.assertEqual(len(out["case_citations"]), 1)
        self.assertEqual(out["case_citations"][0]["file_id"], "f2")

    def test_retrieve_law_only(self):
        vs = MagicMock()
        vs.search.return_value = []
        server = MagicMock()
        server.vector_service = vs
        retrieve = make_kb_retrieve_fn(server)
        out = retrieve("劳动合同法", scopes=["law"])
        self.assertEqual(out["laws"], "")
        self.assertEqual(out["cases"], "")
        self.assertEqual(out["law_citations"], [])
        self.assertEqual(out["case_citations"], [])
        vs.search.assert_called_once()
        self.assertEqual(vs.search.call_args.kwargs.get("where"), {"doc_type": "law"})

    def test_orchestrate_legal_retrieval_exposes_citations(self):
        from agents.orchestrator import run_orchestrate

        def retrieve(query, scopes=None):
            return {
                "laws": "《劳动合同法》\n第六十四条",
                "cases": "",
                "law_citations": [
                    {
                        "id": "c0",
                        "doc_type": "law",
                        "document_id": "d1",
                        "file_id": "f1",
                        "title": "劳动合同法",
                        "article": "第六十四条",
                        "snippet": "第六十四条",
                        "rrf_score": 0.02,
                    }
                ],
                "case_citations": [],
            }

        result = run_orchestrate(
            user_text="检索劳动合同法第六十四条",
            messages=[],
            llm=None,
            retrieve_fn=retrieve,
            file_service=None,
            skills=[],
        )
        self.assertEqual(result.get("agent"), "legal_retrieval")
        cites = result.get("citations") or []
        self.assertEqual(len(cites), 1)
        self.assertEqual(cites[0]["file_id"], "f1")
        self.assertEqual(cites[0]["title"], "劳动合同法")


if __name__ == "__main__":
    unittest.main()
