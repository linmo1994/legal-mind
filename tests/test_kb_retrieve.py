import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from http_api_extra import (  # noqa: E402
    format_kb_hits,
    hits_to_citations,
    make_kb_retrieve_fn,
    make_resolve_doc_from_store,
    prefer_hits_matching_articles,
    prefer_hits_matching_case_query,
    resolve_kb_file_id,
)
from kb_store import KbStore  # noqa: E402


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

    def test_hits_to_citations_does_not_stamp_query_article_on_wrong_chunk(self):
        """Query asks for 第64条 but hit text is 第38条 — do not label as 第六十四条."""
        hits = [
            {
                "id": "chunk_38",
                "document": "第三十八条 用人单位有下列情形之一的……第四十条 ……",
                "metadata": {
                    "doc_type": "law",
                    "document_id": "doc1",
                    "file_id": "f-law-1",
                    "title": "中华人民共和国劳动合同法",
                },
            }
        ]
        cites = hits_to_citations(hits, "帮我检索劳动合同法第64条")
        self.assertEqual(len(cites), 1)
        # Must reflect content, not the query stamp
        self.assertNotIn(cites[0].get("article") or "", ("第六十四条", "第64条"))
        self.assertIn("三十八", cites[0].get("article") or "")

    def test_prefer_hits_matching_query_article(self):
        hits = [
            {
                "id": "a",
                "document": "第三十八条 ……",
                "metadata": {"title": "劳动合同法"},
            },
            {
                "id": "b",
                "document": "第六十四条 非全日制用工……",
                "metadata": {"title": "劳动合同法"},
            },
        ]
        ordered = prefer_hits_matching_articles(hits, "检索劳动合同法第六十四条")
        self.assertEqual(ordered[0]["id"], "b")

    def test_prefer_hits_hard_filters_non_matching_articles(self):
        """有明确条文时，禁止用同法其它条凑结果。"""
        hits = [
            {
                "id": "a65",
                "document": "第六十五条 ……",
                "metadata": {"title": "劳动合同法"},
            },
            {
                "id": "a66",
                "document": "第六十六条 ……",
                "metadata": {"title": "劳动合同法"},
            },
            {
                "id": "a21",
                "document": "第二十一条 ……",
                "metadata": {"title": "劳动合同法"},
            },
        ]
        for q in ("劳动合同法64条", "检索劳动合同法第六十四条"):
            out = prefer_hits_matching_articles(hits, q)
            self.assertEqual(out, [], msg=f"expected empty for {q!r}, got {[h['id'] for h in out]}")

        hits_ok = hits + [
            {
                "id": "a64",
                "document": "第六十四条 非全日制用工……",
                "metadata": {"title": "劳动合同法"},
            }
        ]
        out = prefer_hits_matching_articles(hits_ok, "劳动合同法64条")
        self.assertEqual([h["id"] for h in out], ["a64"])

    def test_prefer_hits_matching_case_query_drops_unrelated(self):
        hits = [
            {
                "id": "loan",
                "document": "民间借贷担保纠纷……保证责任……",
                "metadata": {
                    "doc_type": "case",
                    "title": "（2025）最高法民再142号",
                },
            }
        ]
        kept = prefer_hits_matching_case_query(hits, "食品服务合同 十倍赔偿")
        self.assertEqual(kept, [])

    def test_prefer_hits_matching_case_query_keeps_keyword_overlap(self):
        hits = [
            {
                "id": "loan",
                "document": "民间借贷担保纠纷……保证责任……",
                "metadata": {
                    "doc_type": "case",
                    "title": "（2025）最高法民再142号",
                },
            }
        ]
        kept = prefer_hits_matching_case_query(hits, "检索民间借贷担保类案")
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["id"], "loan")

    def test_prefer_hits_matching_case_query_keeps_food_drops_loan(self):
        """餐饮/十倍赔偿 query must not surface 民间借贷再审案."""
        q = "查找餐饮服务合同违约10倍赔偿的案例"
        hits = [
            {
                "id": "food",
                "document": "餐饮服务合同纠纷，消费者主张十倍赔偿……",
                "metadata": {
                    "doc_type": "case",
                    "title": "（2023）粤2071民初27790号",
                },
            },
            {
                "id": "loan",
                "document": "民间借贷担保纠纷……保证责任……合同……",
                "metadata": {
                    "doc_type": "case",
                    "title": "（2025）最高法民再142号",
                },
            },
        ]
        kept = prefer_hits_matching_case_query(hits, q)
        self.assertEqual([h["id"] for h in kept], ["food"])

    def test_retrieve_case_scope_filters_unrelated_neighbors(self):
        vs = MagicMock()
        vs.fts = object()
        vs.search.return_value = [
            {
                "id": "c0",
                "document": "民间借贷担保纠纷……",
                "metadata": {
                    "doc_type": "case",
                    "document_id": "kb_case_1",
                    "file_id": "f1",
                    "title": "（2025）最高法民再142号",
                },
            }
        ]
        server = MagicMock()
        server.vector_service = vs
        server.kb_store = None
        retrieve = make_kb_retrieve_fn(server)
        out = retrieve("食品服务合同 十倍赔偿", scopes=["case"])
        self.assertEqual(out["cases"], "")
        self.assertEqual(out["case_citations"], [])

    def test_hits_to_citations_resolves_file_id_by_document_id(self):
        hits = [
            {
                "id": "kb_law_abc_chunk_0",
                "document": "第六十四条 非全日制用工……",
                "metadata": {
                    "doc_type": "law",
                    "document_id": "kb_law_abc",
                    "title": "中华人民共和国劳动合同法",
                    # no file_id
                },
            }
        ]

        def resolve_doc(document_id, title, doc_type):
            if document_id == "kb_law_abc":
                return {
                    "file_id": "file-uuid-1",
                    "title": "中华人民共和国劳动合同法",
                    "doc_type": "law",
                    "document_id": "kb_law_abc",
                }
            return None

        cites = hits_to_citations(hits, "劳动合同法第64条", resolve_doc=resolve_doc)
        self.assertEqual(cites[0]["file_id"], "file-uuid-1")

    def test_resolve_doc_from_store_integration(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            store = KbStore(tmp.name)
            store.ensure_schema()
            store.create_document(
                id="kb_law_int",
                doc_type="law",
                file_id="file-int-1",
                title="中华人民共和国劳动合同法",
                status="ready",
                meta={},
                created_by=None,
            )
            resolve_doc = make_resolve_doc_from_store(store)
            hits = [
                {
                    "id": "kb_law_int_chunk_0",
                    "document": "第六十四条 非全日制用工……",
                    "metadata": {
                        "doc_type": "law",
                        "document_id": "kb_law_int",
                        # no file_id
                    },
                }
            ]
            cites = hits_to_citations(hits, "劳动合同法第64条", resolve_doc=resolve_doc)
            self.assertEqual(cites[0]["file_id"], "file-int-1")
            self.assertEqual(cites[0]["title"], "中华人民共和国劳动合同法")
        finally:
            os.unlink(tmp.name)

    def test_resolve_doc_from_store_legacy_title_only_document_id(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            store = KbStore(tmp.name)
            store.ensure_schema()
            title = "中华人民共和国劳动合同法"
            store.create_document(
                id="kb_law_real",
                doc_type="law",
                file_id="file-legacy-1",
                title=title,
                status="ready",
                meta={},
                created_by=None,
            )
            resolve_doc = make_resolve_doc_from_store(store)
            hits = [
                {
                    "id": "legacy_0",
                    "document": "第六十四条 ……",
                    "metadata": {
                        "document_id": title,
                        # no title, no file_id, no doc_type
                    },
                }
            ]
            cites = hits_to_citations(hits, "劳动合同法第六十四条", resolve_doc=resolve_doc)
            self.assertEqual(cites[0]["file_id"], "file-legacy-1")
            self.assertEqual(cites[0]["title"], title)
            self.assertEqual(cites[0]["doc_type"], "law")
        finally:
            os.unlink(tmp.name)

    def test_resolve_kb_file_id_backfills_title_without_file_id(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            store = KbStore(tmp.name)
            store.ensure_schema()
            store.create_document(
                id="kb_no_fid",
                doc_type="law",
                file_id=None,
                title="劳动合同法",
                status="ready",
                meta={},
                created_by=None,
            )
            fid, row = resolve_kb_file_id(store, document_id="kb_no_fid")
            self.assertIsNone(fid)
            self.assertIsNotNone(row)
            resolve_doc = make_resolve_doc_from_store(store)
            resolved = resolve_doc("kb_no_fid", "", "")
            self.assertIsNone(resolved.get("file_id"))
            self.assertEqual(resolved.get("title"), "劳动合同法")
            self.assertEqual(resolved.get("doc_type"), "law")
            self.assertEqual(resolved.get("document_id"), "kb_no_fid")
        finally:
            os.unlink(tmp.name)

    def test_hits_to_citations_resolves_file_id_by_title_when_legacy_id(self):
        hits = [
            {
                "id": "legacy_0",
                "document": "第六十四条 ……",
                "metadata": {
                    "document_id": "中华人民共和国劳动合同法",
                    # no title, no file_id, no doc_type
                },
            }
        ]

        def resolve_doc(document_id, title, doc_type):
            key = title or document_id
            if key == "中华人民共和国劳动合同法":
                return {
                    "file_id": "file-uuid-2",
                    "title": "中华人民共和国劳动合同法",
                    "doc_type": "law",
                    "document_id": "kb_law_real",
                }
            return None

        cites = hits_to_citations(hits, "劳动合同法第六十四条", resolve_doc=resolve_doc)
        self.assertEqual(cites[0]["file_id"], "file-uuid-2")
        self.assertEqual(cites[0]["title"], "中华人民共和国劳动合同法")

    def test_hits_to_citations_keeps_missing_file_id_when_unresolved(self):
        hits = [
            {
                "id": "x",
                "document": "第一条",
                "metadata": {"title": "未知法", "doc_type": "law"},
            }
        ]
        cites = hits_to_citations(hits, "未知法", resolve_doc=lambda *a, **k: None)
        self.assertTrue(cites[0]["file_id"] in (None, ""))

    def test_retrieve_promotes_vector_and_attaches_fts(self):
        """Background VectorService may sit on _vector_service_instance without FTS."""
        vs = MagicMock()
        vs.fts = None
        vs.search.return_value = []
        server = MagicMock()
        server.vector_service = None
        server.kb_store = None
        server._vector_service_instance = [vs]
        attached = {"n": 0}

        def _attach():
            attached["n"] += 1
            vs.fts = object()

        server._attach_fts_if_ready = _attach
        retrieve = make_kb_retrieve_fn(server)
        retrieve("劳动合同法第64条", scopes=["law"])
        self.assertIs(server.vector_service, vs)
        self.assertEqual(attached["n"], 1)
        self.assertIsNotNone(vs.fts)

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

    def test_hits_to_citations_case_dedupes_without_statute_articles(self):
        """Case chunks often quote 第×条 of laws — must not split one case into many cites."""
        case_no = "(2025)最高法民再142号"
        hits = [
            {
                "id": "c0",
                "document": "本院认为……依照《民法典》第二百一十八条……",
                "metadata": {
                    "doc_type": "case",
                    "document_id": "kb_case_1",
                    "file_id": "f-case-1",
                    "title": case_no,
                    "case_no": case_no,
                },
            },
            {
                "id": "c1",
                "document": "……第六十四条……",
                "metadata": {
                    "doc_type": "case",
                    "document_id": "kb_case_1",
                    "file_id": "f-case-1",
                    "title": case_no,
                },
            },
            {
                "id": "c2",
                "document": "……第一条……",
                "metadata": {
                    "doc_type": "case",
                    "document_id": "kb_case_1",
                    "file_id": "f-case-1",
                    "title": case_no,
                },
            },
        ]
        cites = hits_to_citations(hits, "检索类案")
        self.assertEqual(len(cites), 1)
        self.assertEqual(cites[0]["title"], case_no)
        self.assertEqual(cites[0]["file_id"], "f-case-1")
        self.assertTrue(cites[0].get("article") in (None, ""))

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
                    "document": "民间借贷纠纷判决要旨",
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
        # Article in query → expand recall pool before prefer/truncate
        self.assertEqual(vs.search.call_args_list[0].kwargs.get("n_results"), 20)
        self.assertEqual(vs.search.call_args_list[1].kwargs.get("n_results"), 20)
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
