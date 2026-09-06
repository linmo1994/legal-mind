"""Local law-retrieve miss detection + NPC FLK external search hint (no scraping)."""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from kb_query_parse import (
    doc_has_article,
    extract_articles,
    extract_law_name_hint,
    normalize_article_forms,
)

NPC_FLK_HOME = "https://flk.npc.gov.cn/"
NOTE = "本地知识库未命中；未自动抓取外网正文，请打开官网核对。"


def title_matches_law_hint(title: str, hint: str) -> bool:
    """Same soft rules as VectorService._title_matches_hint."""
    t = (title or "").strip()
    h = (hint or "").strip()
    if not t or not h:
        return False
    if h in t or t in h:
        return True
    for suffix in ("条例", "规定", "办法", "法"):
        if h.endswith(suffix) and len(h) > len(suffix):
            stem = h[: -len(suffix)]
            if stem and stem in t:
                return True
    return False


def _title_from_meta(meta: Any) -> str:
    if not isinstance(meta, dict):
        return ""
    return (meta.get("law_name") or meta.get("title") or "").strip()


def _docs_from(
    citations: Any,
    hits: Any,
    laws_text: str,
) -> List[Dict[str, str]]:
    """Normalize to {title, text} from citations, hits, or laws_text alone."""
    docs: List[Dict[str, str]] = []

    for c in citations or []:
        if not isinstance(c, dict):
            continue
        title = (c.get("title") or "").strip()
        text = (c.get("snippet") or c.get("text") or c.get("document") or "").strip()
        if title or text:
            docs.append({"title": title, "text": text})

    for h in hits or []:
        if not isinstance(h, dict):
            continue
        meta = h.get("metadata") or {}
        title = (
            (h.get("title") or "").strip()
            or _title_from_meta(meta)
        )
        text = (h.get("document") or h.get("text") or h.get("snippet") or "").strip()
        if title or text:
            docs.append({"title": title, "text": text})

    if not docs and (laws_text or "").strip():
        docs.append({"title": "", "text": (laws_text or "").strip()})

    return docs


def assess_law_retrieve_miss(
    query: str,
    *,
    citations: list = None,
    hits: list = None,
    laws_text: str = "",
) -> Optional[str]:
    docs = _docs_from(citations, hits, laws_text)
    if not docs and not (laws_text or "").strip():
        return "empty"
    hint = extract_law_name_hint(query)
    arts = extract_articles(query)
    if hint:
        titled = [d for d in docs if title_matches_law_hint(d.get("title") or "", hint)]
        if not titled:
            return "law_mismatch"
        pool = titled
    else:
        pool = docs
    if arts:
        if not any(
            any(doc_has_article(d.get("text") or "", a) for a in arts)
            for d in pool
        ):
            return "article_mismatch"
    return None


def build_suggest_query(query: str) -> str:
    hint = extract_law_name_hint(query) or ""
    arts = extract_articles(query)
    art = ""
    if arts:
        forms = normalize_article_forms(arts[0])
        art = (
            next(
                (f for f in forms if "六" in f or not f[1:-1].isdigit()),
                forms[0],
            )
            if forms
            else arts[0]
        )
    return " ".join(x for x in (hint, art) if x).strip() or (query or "").strip()


def build_external_search_hint(query: str, reason: str) -> Dict[str, Any]:
    sq = build_suggest_query(query)
    url = NPC_FLK_HOME
    return {
        "needed": True,
        "reason": reason,
        "query": sq,
        "provider": "npc_flk",
        "label": "国家法律法规数据库",
        "url": url,
        "note": NOTE + (f" 建议检索词：{sq}" if sq else ""),
    }
