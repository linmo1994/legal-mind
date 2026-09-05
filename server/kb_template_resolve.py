"""Resolve document templates from the knowledge base (doc_type=template)."""

from __future__ import annotations

from typing import Any, List, Optional, Tuple


def _display_name(doc: dict) -> str:
    meta = doc.get("meta") or {}
    return (meta.get("template_name") or doc.get("title") or "").strip()


def _is_usable(doc: dict) -> bool:
    if (doc.get("status") or "") == "deleted":
        return False
    meta = doc.get("meta") or {}
    if meta.get("validity") == "失效":
        return False
    return True


def list_template_names(kb_store, *, limit: int = 200) -> List[str]:
    if kb_store is None:
        return []
    docs = kb_store.list_documents(doc_type="template", limit=limit, offset=0)
    names: List[str] = []
    seen = set()
    for doc in docs:
        if not _is_usable(doc):
            continue
        name = _display_name(doc)
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _score_match(query: str, name: str) -> int:
    q = (query or "").strip()
    n = (name or "").strip()
    if not q or not n:
        return 0
    if q == n:
        return 100
    if q in n:
        return 80
    if n in q:
        return 70
    score = 0
    # Prefer longer shared substrings (案由片段)
    for size in (6, 4, 3, 2):
        seen = set()
        for i in range(0, max(0, len(q) - size + 1)):
            piece = q[i : i + size]
            if piece in seen:
                continue
            seen.add(piece)
            if piece in n:
                score += size
    return score


def find_template_doc(kb_store, template_name: str) -> Optional[dict]:
    if kb_store is None:
        return None
    query = (template_name or "").strip()
    docs = [
        d
        for d in kb_store.list_documents(doc_type="template", limit=200, offset=0)
        if _is_usable(d)
    ]
    if not docs:
        return None
    if not query:
        return docs[0]

    best = None
    best_score = 0
    for doc in docs:
        name = _display_name(doc)
        score = _score_match(query, name)
        if score > best_score:
            best_score = score
            best = doc
    # Exact/containment scores are >=70; fuzzy substring overlap needs a lower bar.
    if best_score < 12:
        return None
    return best


def _text_from_file(file_service, file_id: Optional[str]) -> str:
    if not file_service or not file_id:
        return ""
    get_text = getattr(file_service, "get_file_text", None)
    if not callable(get_text):
        return ""
    text = get_text(file_id) or ""
    return str(text).strip()


def _text_from_vector(vector_service, document_id: str) -> str:
    if not vector_service or not document_id:
        return ""
    collection = getattr(vector_service, "collection", None)
    if collection is None:
        return ""
    try:
        results = collection.get(
            where={"document_id": document_id},
            include=["documents", "metadatas"],
        )
    except Exception:
        return ""
    docs = results.get("documents") or []
    metas = results.get("metadatas") or []
    if not docs:
        return ""
    paired: List[Tuple[int, str]] = []
    for i, text in enumerate(docs):
        meta = metas[i] if i < len(metas) and isinstance(metas[i], dict) else {}
        idx = meta.get("chunk_index", i)
        try:
            idx_i = int(idx)
        except (TypeError, ValueError):
            idx_i = i
        paired.append((idx_i, text or ""))
    paired.sort(key=lambda x: x[0])
    return "\n".join(p[1] for p in paired if p[1]).strip()


def resolve_template_text(
    template_name: str,
    *,
    kb_store,
    file_service=None,
    vector_service=None,
) -> Tuple[Optional[str], Optional[str], List[str]]:
    """
    Returns (text, matched_name, available_names).
    text is None when not found.
    """
    available = list_template_names(kb_store)
    doc = find_template_doc(kb_store, template_name)
    if not doc:
        return None, None, available

    matched = _display_name(doc) or (template_name or "").strip()
    text = _text_from_file(file_service, doc.get("file_id"))
    if not text:
        text = _text_from_vector(vector_service, doc.get("id") or "")
    if not text:
        return None, matched, available
    return text, matched, available
