"""Resolve law/case texts from the knowledge-base vector index (not MCP mocks)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def format_kb_hit_texts(hits: Optional[List[Dict[str, Any]]], *, limit: int = 5) -> str:
    parts: List[str] = []
    for hit in (hits or [])[:limit]:
        if not isinstance(hit, dict):
            continue
        meta = hit.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        title = (
            meta.get("title") or meta.get("law_name") or meta.get("case_no") or ""
        ).strip()
        doc = (hit.get("document") or hit.get("text") or "").strip()
        if not doc and not title:
            continue
        head = f"《{title}》" if title else "（未命名片段）"
        snippet = doc[:800] + ("…" if len(doc) > 800 else "")
        parts.append(f"{head}\n{snippet}")
    return "\n\n".join(parts)


def _search(vector_service, query: str, *, doc_type: str, n_results: int = 5) -> List[Dict[str, Any]]:
    if not vector_service:
        return []
    q = (query or "").strip() or ("法律" if doc_type == "law" else "案例")
    try:
        return (
            vector_service.search(
                q,
                n_results=n_results,
                boost_keywords=True,
                where={"doc_type": doc_type},
            )
            or []
        )
    except Exception as exc:
        print(f"[kb_retrieve_resolve] {doc_type} search failed: {exc}")
        return []


def resolve_law_regulation_text(
    vector_service, query: str, *, n_results: int = 5
) -> str:
    """Return formatted law snippets from KB, or empty string if none."""
    hits = _search(vector_service, query, doc_type="law", n_results=n_results)
    return format_kb_hit_texts(hits, limit=n_results)


def resolve_similar_cases_text(
    vector_service, query: str, *, n_results: int = 5
) -> str:
    """Return formatted case snippets from KB, or empty string if none."""
    hits = _search(vector_service, query, doc_type="case", n_results=n_results)
    return format_kb_hit_texts(hits, limit=n_results)


def empty_law_message(query: str) -> str:
    q = (query or "").strip() or "（未指定）"
    return (
        f"未在知识库法规库中找到与「{q}」相关的条文。\n"
        "请先在管理端「知识库 · 法规库」上传并向量化相关法律法规。"
    )


def empty_case_message(query: str) -> str:
    q = (query or "").strip() or "（未指定）"
    return (
        f"未在知识库裁判案例库中找到与「{q}」相关的类案。\n"
        "请先在管理端「知识库 · 裁判案例库」上传并向量化相关裁判文书。"
    )
