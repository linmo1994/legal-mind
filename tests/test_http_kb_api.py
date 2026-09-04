import os, tempfile, unittest
from auth_service import AuthService
from rbac_service import RbacService
from rbac_store import RbacStore
from kb_store import KbStore
from http_kb_api import KbHttpApi, parse_kb_path
from vector_service import VectorService


class FakeFiles:
    def get_file_text(self, file_id):
        return "法规正文测试内容 " * 10


class TestParseKbPath(unittest.TestCase):
    """Router path parsing — by-id routes must not regress to 404."""

    def test_by_id_get_patch_delete(self):
        doc_id = "abc-123"
        base = f"/api/admin/kb/documents/{doc_id}"
        self.assertEqual(parse_kb_path(base, "GET"), ("get", doc_id))
        self.assertEqual(parse_kb_path(base, "PATCH"), ("patch", doc_id))
        self.assertEqual(parse_kb_path(base, "DELETE"), ("delete", doc_id))
        self.assertEqual(
            parse_kb_path(f"{base}/update", "POST"), ("update", doc_id)
        )
        # Trailing slash / query must not break index math
        self.assertEqual(parse_kb_path(base + "/", "GET"), ("get", doc_id))
        self.assertEqual(parse_kb_path(base + "?x=1", "GET"), ("get", doc_id))

    def test_collection_and_unknown(self):
        self.assertEqual(parse_kb_path("/api/admin/kb/documents", "GET"), ("list", None))
        self.assertEqual(parse_kb_path("/api/admin/kb/documents", "POST"), ("create", None))
        self.assertEqual(parse_kb_path("/api/admin/kb/search", "POST"), ("search", None))
        self.assertEqual(parse_kb_path("/api/admin/kb/documents/x", "POST"), (None, None))
        self.assertEqual(parse_kb_path("/api/admin/kb/other", "GET"), (None, None))


class TestHttpKbApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        rbac_path = os.path.join(self.tmp.name, "rbac.db")
        self.rbac_store = RbacStore(rbac_path)
        self.rbac_store.ensure_schema()
        self.rbac_store.seed_defaults()
        self.auth = AuthService(self.rbac_store)
        self.auth.ensure_seed_director("ChangeMe123!")
        login = self.auth.login("director", "ChangeMe123!")
        self.token = login["token"]
        self.authz = f"Bearer {self.token}"
        self.kb = KbStore(os.path.join(self.tmp.name, "kb.db"))
        self.kb.ensure_schema()
        self.vs = VectorService(persist_directory=os.path.join(self.tmp.name, "chroma"))
        self.vs.model = None
        self.api = KbHttpApi(
            self.kb, self.auth, RbacService(self.rbac_store),
            file_service=FakeFiles(), vector_service=self.vs,
            complete_fn=lambda s, u: '{"law_name":"测试法","effect_level":"法律","issuing_authority":"","document_number":"","effective_date":""}',
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_ingest_list_search_patch_delete(self):
        st, body = self.api.create_from_file(self.authz, {"doc_type": "law", "file_id": "f1"})
        self.assertEqual(st, 200, body)
        doc_id = body["id"]
        st, listed = self.api.list_documents(self.authz, "law")
        self.assertEqual(st, 200)
        self.assertEqual(len(listed["items"]), 1)
        st, search = self.api.search(self.authz, {"doc_type": "law", "query": "测试法", "n_results": 3})
        self.assertEqual(st, 200)
        self.assertTrue(len(search["results"]) >= 1)
        st, patched = self.api.patch_document(self.authz, doc_id, {
            "meta": {**body["meta"], "effect_level": "行政法规"}
        })
        self.assertEqual(st, 200)
        self.assertEqual(patched["meta"]["effect_level"], "行政法规")
        st, _ = self.api.delete_document(self.authz, doc_id)
        self.assertEqual(st, 200)
        st, listed2 = self.api.list_documents(self.authz, "law")
        self.assertEqual(listed2["items"], [])
        st, search2 = self.api.search(self.authz, {"doc_type": "law", "query": "测试法", "n_results": 3})
        self.assertEqual(st, 200)
        self.assertEqual(search2["results"], [])

    def test_delete_chroma_hard_failure_skips_soft_delete(self):
        st, body = self.api.create_from_file(self.authz, {"doc_type": "law", "file_id": "f1"})
        self.assertEqual(st, 200, body)
        doc_id = body["id"]

        def fail_delete(_doc_id):
            return {"success": False, "message": "chroma unavailable"}

        self.api.vector_service.delete_document = fail_delete
        st, err = self.api.delete_document(self.authz, doc_id)
        self.assertEqual(st, 500, err)
        still = self.kb.get_document(doc_id)
        self.assertIsNotNone(still)
        self.assertNotEqual(still["status"], "deleted")

    def test_delete_chroma_not_found_still_soft_deletes(self):
        doc = self.kb.create_document(
            id="kb_law_noforce",
            doc_type="law",
            file_id="f-empty",
            title="extract failed row",
            status="extract_failed",
            meta={},
            created_by="u1",
        )
        st, out = self.api.delete_document(self.authz, doc["id"])
        self.assertEqual(st, 200, out)
        self.assertIsNone(self.kb.get_document(doc["id"]))

    def test_patch_chroma_hard_failure_leaves_store_unchanged(self):
        st, body = self.api.create_from_file(self.authz, {"doc_type": "law", "file_id": "f1"})
        self.assertEqual(st, 200, body)
        doc_id = body["id"]
        before = self.kb.get_document(doc_id)

        def fail_update(_doc_id, _meta):
            return {"success": False, "message": "chroma write error"}

        self.api.vector_service.update_document_metadata = fail_update
        st, err = self.api.patch_document(
            self.authz, doc_id, {"meta": {**body["meta"], "effect_level": "行政法规"}}
        )
        self.assertEqual(st, 500, err)
        after = self.kb.get_document(doc_id)
        self.assertEqual(after["meta"]["effect_level"], before["meta"]["effect_level"])


if __name__ == "__main__":
    unittest.main()
