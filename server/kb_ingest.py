"""Upload ingest pipeline: text → LLM meta → kb row → chroma chunks."""

from __future__ import annotations

import uuid
from typing import Any, Callable, Optional

from kb_meta_extract import extract_metadata
from kb_store import DOC_TYPES


def new_document_id(doc_type: str) -> str:
    return f"kb_{doc_type}_{uuid.uuid4().hex[:12]}"


def title_from_meta(doc_type: str, meta: dict, fallback: str = "") -> str:
    meta = meta or {}
    if doc_type == "law":
        name = (meta.get("law_name") or "").strip()
        return name or fallback
    if doc_type == "case":
        case_no = (meta.get("case_no") or "").strip()
        if case_no:
            return case_no
        cause = (meta.get("cause_of_action") or "").strip()
        return cause or fallback
    return fallback


def _to_scalar(value: Any):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return "; ".join(str(x) for x in value if x is not None)
    return str(value)


def chunk_metadata(
    doc_type: str,
    document_id: str,
    file_id: str | None,
    title: str,
    meta: dict,
) -> dict:
    out: dict[str, Any] = {
        "document_id": document_id,
        "doc_type": doc_type,
        "title": title,
        "source": "kb",
    }
    if file_id is not None:
        out["file_id"] = file_id
    for key, value in (meta or {}).items():
        scalar = _to_scalar(value)
        if scalar is None:
            continue
        out[key] = scalar
    return out


def ingest_uploaded_file(
    *,
    doc_type: str,
    file_id: str,
    created_by: str | None,
    kb_store,
    file_service,
    vector_service,
    complete_fn: Optional[Callable[[str, str], str]] = None,
) -> dict:
    if doc_type not in DOC_TYPES:
        raise ValueError(f"invalid doc_type: {doc_type}")

    text = file_service.get_file_text(file_id)
    document_id = new_document_id(doc_type)

    if not (text or "").strip():
        return kb_store.create_document(
            id=document_id,
            doc_type=doc_type,
            file_id=file_id,
            title=file_id or "",
            status="extract_failed",
            meta={},
            created_by=created_by,
        )

    kb_store.create_document(
        id=document_id,
        doc_type=doc_type,
        file_id=file_id,
        title=file_id or "",
        status="processing",
        meta={},
        created_by=created_by,
    )

    meta, meta_status = extract_metadata(doc_type, text, complete_fn=complete_fn)
    title = title_from_meta(doc_type, meta, fallback=file_id or "")
    metadata = chunk_metadata(doc_type, document_id, file_id, title, meta)

    result = vector_service.add_document(document_id, text, metadata)
    if result.get("success"):
        status = "meta_failed" if meta_status == "meta_failed" else "ready"
    else:
        status = "vector_failed"

    kb_store.update_document(document_id, title=title, status=status, meta=meta)
    doc = kb_store.get_document(document_id)
    assert doc is not None
    return doc
