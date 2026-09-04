"""HTTP handlers for knowledge-base admin APIs (testable without socket server)."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from auth_service import AuthService
from http_rbac_api import StatusPayload, _deny, _ok, extract_bearer
from kb_ingest import ingest_uploaded_file
from kb_store import DOC_TYPES, KbStore
from rbac_service import RbacService

# Action: (name, doc_id|None). name in list|create|search|get|patch|delete|update|None
KbRoute = Tuple[Optional[str], Optional[str]]


def parse_kb_path(path: str, method: str) -> KbRoute:
    """Parse /api/admin/kb routes. Path should already be stripped of query string.

    /api/admin/kb/documents/{id} splits to 6 parts (index 5 = id).
    /api/admin/kb/documents/{id}/update splits to 7 parts (parts[6] == "update").
    """
    path = (path or "").split("?", 1)[0].rstrip("/") or "/"
    method = (method or "").upper()

    if path == "/api/admin/kb/documents" and method == "GET":
        return ("list", None)
    if path == "/api/admin/kb/documents" and method == "POST":
        return ("create", None)
    if path == "/api/admin/kb/search" and method == "POST":
        return ("search", None)

    if not path.startswith("/api/admin/kb/documents/"):
        return (None, None)

    parts = path.split("/")
    # "", "api", "admin", "kb", "documents", "{id}" [, "update"]
    if len(parts) == 7 and parts[6] == "update" and method == "POST":
        return ("update", parts[5])
    if len(parts) == 6 and method == "GET":
        return ("get", parts[5])
    if len(parts) == 6 and method == "PATCH":
        return ("patch", parts[5])
    if len(parts) == 6 and method == "DELETE":
        return ("delete", parts[5])
    return (None, None)


class KbHttpApi:
    def __init__(
        self,
        store: KbStore,
        auth: AuthService,
        rbac: RbacService,
        *,
        file_service,
        vector_service,
        complete_fn: Optional[Callable[[str, str], str]] = None,
    ):
        self.store = store
        self.auth = auth
        self.rbac = rbac
        self.file_service = file_service
        self.vector_service = vector_service
        self.complete_fn = complete_fn

    def current_user(self, authorization: Optional[str]) -> Optional[Dict[str, Any]]:
        token = extract_bearer(authorization)
        if not token:
            return None
        return self.auth.resolve_token(token)

    def require_user(self, authorization: Optional[str]) -> StatusPayload:
        user = self.current_user(authorization)
        if not user:
            return _deny(401, "未登录或登录已过期")
        return _ok({"user": user})

    def require_perm(
        self,
        authorization: Optional[str],
        perm: str,
        case_id: Optional[int] = None,
    ) -> StatusPayload:
        gated = self.require_user(authorization)
        if gated[0] != 200:
            return gated
        user = gated[1]["user"]
        if not self.rbac.require(user["id"], perm, case_id):
            return _deny(403, f"无权限：{perm}")
        return _ok({"user": user})

    def _require_vectorize(self, authorization: Optional[str]) -> StatusPayload:
        return self.require_perm(authorization, "cap.vectorize")

    def _require_vector_service(self) -> Optional[StatusPayload]:
        if not self.vector_service:
            return _deny(503, "向量服务未就绪")
        return None

    def create_from_file(
        self, authorization: Optional[str], body: dict
    ) -> StatusPayload:
        gated = self._require_vectorize(authorization)
        if gated[0] != 200:
            return gated
        missing = self._require_vector_service()
        if missing:
            return missing
        if not self.file_service:
            return _deny(503, "文件服务未就绪")

        body = body or {}
        doc_type = (body.get("doc_type") or "").strip()
        file_id = (body.get("file_id") or "").strip()
        if not doc_type or not file_id:
            return _deny(400, "请提供 doc_type 和 file_id")
        if doc_type not in DOC_TYPES:
            return _deny(400, f"无效 doc_type: {doc_type}")

        user = gated[1]["user"]
        created_by = str(user.get("id") or user.get("username") or "")
        try:
            doc = ingest_uploaded_file(
                doc_type=doc_type,
                file_id=file_id,
                created_by=created_by or None,
                kb_store=self.store,
                file_service=self.file_service,
                vector_service=self.vector_service,
                complete_fn=self.complete_fn,
            )
        except ValueError as e:
            return _deny(400, str(e))
        except Exception as e:
            return _deny(500, str(e))
        return _ok(doc)

    def list_documents(
        self,
        authorization: Optional[str],
        doc_type: str,
        limit: int = 50,
        offset: int = 0,
    ) -> StatusPayload:
        gated = self._require_vectorize(authorization)
        if gated[0] != 200:
            return gated
        doc_type = (doc_type or "").strip()
        if doc_type not in DOC_TYPES:
            return _deny(400, f"无效 doc_type: {doc_type}")
        try:
            limit = max(1, min(int(limit), 200))
            offset = max(0, int(offset))
        except (TypeError, ValueError):
            return _deny(400, "limit/offset 无效")
        items = self.store.list_documents(
            doc_type=doc_type, limit=limit, offset=offset
        )
        total = self.store.count_documents(doc_type=doc_type)
        return _ok({"items": items, "total": total})

    def get_document(
        self, authorization: Optional[str], doc_id: str
    ) -> StatusPayload:
        gated = self._require_vectorize(authorization)
        if gated[0] != 200:
            return gated
        doc = self.store.get_document(doc_id)
        if not doc:
            return _deny(404, "文档不存在")
        return _ok(doc)

    def patch_document(
        self, authorization: Optional[str], doc_id: str, body: dict
    ) -> StatusPayload:
        gated = self._require_vectorize(authorization)
        if gated[0] != 200:
            return gated
        missing = self._require_vector_service()
        if missing:
            return missing

        existing = self.store.get_document(doc_id)
        if not existing:
            return _deny(404, "文档不存在")

        body = body or {}
        title = body.get("title")
        meta = body.get("meta")
        if title is None and meta is None:
            return _deny(400, "请提供 title 或 meta")

        kwargs: Dict[str, Any] = {}
        if title is not None:
            kwargs["title"] = str(title)
        if meta is not None:
            if not isinstance(meta, dict):
                return _deny(400, "meta 必须为对象")
            kwargs["meta"] = meta

        updated = self.store.update_document(doc_id, **kwargs)
        if not updated:
            return _deny(404, "文档不存在")

        chroma_meta: Dict[str, Any] = dict(updated.get("meta") or {})
        chroma_meta["title"] = updated.get("title") or ""
        chroma_meta["doc_type"] = updated.get("doc_type")
        try:
            self.vector_service.update_document_metadata(doc_id, chroma_meta)
        except Exception as e:
            return _deny(500, f"向量元数据更新失败: {e}")
        return _ok(updated)

    def delete_document(
        self, authorization: Optional[str], doc_id: str
    ) -> StatusPayload:
        gated = self._require_vectorize(authorization)
        if gated[0] != 200:
            return gated
        missing = self._require_vector_service()
        if missing:
            return missing

        existing = self.store.get_document(doc_id)
        if not existing:
            return _deny(404, "文档不存在")

        # Chroma first, then soft-delete — avoids soft-deleted rows left when Chroma fails.
        try:
            self.vector_service.delete_document(doc_id)
        except Exception as e:
            return _deny(500, f"向量删除失败: {e}")
        ok = self.store.soft_delete(doc_id)
        if not ok:
            return _deny(404, "文档不存在")
        return _ok({"ok": True, "id": doc_id})

    def search(self, authorization: Optional[str], body: dict) -> StatusPayload:
        gated = self._require_vectorize(authorization)
        if gated[0] != 200:
            return gated
        missing = self._require_vector_service()
        if missing:
            return missing

        body = body or {}
        doc_type = (body.get("doc_type") or "").strip()
        query = (body.get("query") or "").strip()
        if not doc_type or not query:
            return _deny(400, "请提供 doc_type 和 query")
        if doc_type not in DOC_TYPES:
            return _deny(400, f"无效 doc_type: {doc_type}")
        n_results = body.get("n_results", 5)
        try:
            n_results = max(1, min(int(n_results), 50))
        except (TypeError, ValueError):
            return _deny(400, "n_results 无效")

        try:
            results = self.vector_service.search(
                query,
                n_results=n_results,
                where={"doc_type": doc_type},
            )
        except Exception as e:
            return _deny(500, str(e))
        return _ok({"results": results or []})
