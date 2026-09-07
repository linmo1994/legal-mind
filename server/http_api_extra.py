"""Extra REST routes: orchestrate, skills, MCP admin config."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from agents.graph import OrchestrationError
from agents.orchestrator import run_orchestrate
from config_admin import (
    create_profile,
    delete_profile,
    ensure_profiles,
    list_public_profiles,
    public_profile,
    redact_llm_config,
    update_profile,
    validate_mcp_config_update,
)
from skill_service import SkillService


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def config_path() -> str:
    return os.path.join(project_root(), "config.json")


def skill_service() -> SkillService:
    return SkillService(os.path.join(project_root(), "skills"))


def _contents_text(resp: Dict[str, Any]) -> str:
    contents = ((resp or {}).get("result") or {}).get("contents") or []
    return "\n".join(c.get("text") or "" for c in contents if isinstance(c, dict))


def format_kb_hits(hits: list, *, limit: int = 5) -> str:
    parts = []
    for hit in (hits or [])[:limit]:
        meta = hit.get("metadata") or {}
        title = (meta.get("title") or meta.get("law_name") or meta.get("case_no") or "").strip()
        doc = (hit.get("document") or hit.get("text") or "").strip()
        if not doc and not title:
            continue
        head = f"《{title}》" if title else "（未命名片段）"
        snippet = doc[:800] + ("…" if len(doc) > 800 else "")
        parts.append(f"{head}\n{snippet}")
    return "\n\n".join(parts)


def prefer_hits_matching_articles(hits: list, query: str = "") -> list:
    """Keep only chunks that contain the queried article when one is specified.

    Soft reorder is not enough: returning same-law neighbors (65/66/21) looks like a miss.
    If the query names an article but no hit contains it, return [].
    """
    try:
        from kb_query_parse import doc_has_article, extract_articles
    except Exception:
        return list(hits or [])

    articles = extract_articles(query or "")
    if not articles or not hits:
        return list(hits or [])

    matched: List[Any] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        doc = hit.get("document") or hit.get("text") or ""
        if any(doc_has_article(doc, a) for a in articles):
            matched.append(hit)
    return matched


_CASE_QUERY_STOPWORDS = frozenset(
    {
        "检索",
        "类案",
        "案例",
        "判例",
        "相关",
        "帮我",
        "请",
        "一下",
        "看看",
        "有没有",
        "是否",
        "查找",
        "搜索",
        "本地",
        "知识库",
        "回答",
        "分析",
        "说明",
        "要点",
    }
)

# Too generic alone — must not keep an unrelated judgment.
_CASE_WEAK_KEYWORDS = frozenset(
    {
        "合同",
        "违约",
        "纠纷",
        "赔偿",
        "服务",
        "诉讼",
        "原告",
        "被告",
        "法院",
        "判决",
        "裁定",
        "借款",
        "担保",
        "保证",
        "责任",
        "相关",
        "问题",
        "情况",
    }
)


def case_query_keywords(query: str) -> List[str]:
    """Content tokens from a case-search query (drop retrieval boilerplate)."""
    import re

    text = (query or "").strip()
    if not text:
        return []
    text = re.sub(r"第[一二三四五六七八九十百千零〇\d]+条", " ", text)
    text = re.sub(r"(?<![A-Za-z0-9])[一二三四五六七八九十百千零〇\d]{1,8}条", " ", text)
    for sw in sorted(_CASE_QUERY_STOPWORDS, key=len, reverse=True):
        if sw in text:
            text = text.replace(sw, " ")
    text = re.sub(r"\s+", " ", text).strip()
    raw = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9][A-Za-z0-9\-]{1,}", text)
    out: List[str] = []
    seen = set()

    def _add(tok: str) -> None:
        t = (tok or "").strip().rstrip("的了吗呢啊呀")
        if not t or t.isdigit() or t in _CASE_QUERY_STOPWORDS:
            return
        if t in seen:
            return
        seen.add(t)
        out.append(t)

    for tok in raw:
        _add(tok)
        # Long CJK runs → 3/4-char windows so「餐饮服务合同违约」可命中「餐饮服务」
        if len(tok) > 4 and re.fullmatch(r"[\u4e00-\u9fff]+", tok or ""):
            for n in (4, 3):
                for i in range(0, len(tok) - n + 1):
                    piece = tok[i : i + n]
                    if piece in _CASE_WEAK_KEYWORDS:
                        continue
                    _add(piece)
    return out


def _case_hit_match_score(blob: str, keywords: List[str]) -> int:
    """Higher = more relevant. Digits/weak unigrams do not count."""
    score = 0
    for kw in keywords or []:
        if not kw or kw.isdigit() or kw in _CASE_WEAK_KEYWORDS:
            continue
        if kw not in blob:
            continue
        score += 2 if len(kw) >= 4 else 1
    return score


def prefer_hits_matching_case_query(hits: list, query: str = "") -> list:
    """Keep only case chunks with meaningful keyword overlap.

    Vector Top-K always returns neighbors when the case collection is small;
    weak overlap (e.g. bare「合同」) must not keep unrelated judgments in
    citations or the model context.
    """
    keywords = case_query_keywords(query)
    if not keywords:
        # No usable stems → treat as miss (do not dump entire case KB).
        return []
    matched: List[Any] = []
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        meta = hit.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        blob = " ".join(
            [
                str(meta.get("title") or ""),
                str(meta.get("case_no") or ""),
                str(hit.get("document") or hit.get("text") or ""),
            ]
        )
        # Need a real topical stem (len>=4) or two shorter non-weak stems.
        if _case_hit_match_score(blob, keywords) >= 2:
            matched.append(hit)
    return matched


def resolve_kb_file_id(store, *, document_id: str = "", title: str = "", doc_type: str = ""):
    """Look up kb_documents for file_id. Returns (file_id|None, row|None).

    When get_document finds a row without file_id, returns that row for
    title/doc_type backfill and still tries title search for file_id.
    """
    if store is None:
        return None, None
    doc_id = (document_id or "").strip()
    id_row = None
    if doc_id:
        try:
            id_row = store.get_document(doc_id)
        except Exception:
            id_row = None
        if id_row and id_row.get("file_id"):
            return id_row.get("file_id"), id_row
    title_q = (title or "").strip()
    if not title_q and id_row:
        title_q = (id_row.get("title") or "").strip()
    if not title_q:
        title_q = doc_id
    if not title_q and not id_row:
        return None, None
    dt_hint = doc_type or (id_row or {}).get("doc_type") or ""
    if dt_hint in ("law", "case"):
        types = [dt_hint]
    else:
        types = ["law", "case"]
    for dt in types:
        try:
            rows = store.find_documents_by_title(doc_type=dt, title=title_q, limit=5)
        except Exception:
            rows = []
        for row in rows or []:
            if row.get("file_id"):
                if id_row:
                    merged = dict(row)
                    merged["id"] = id_row.get("id") or merged.get("id")
                    merged["title"] = id_row.get("title") or merged.get("title")
                    merged["doc_type"] = id_row.get("doc_type") or merged.get("doc_type")
                    return merged.get("file_id"), merged
                return row.get("file_id"), row
    if id_row:
        return None, id_row
    return None, None


def make_resolve_doc_from_store(store):
    def resolve_doc(document_id, title, doc_type):
        fid, row = resolve_kb_file_id(
            store,
            document_id=document_id or "",
            title=title or "",
            doc_type=doc_type or "",
        )
        if not row and not fid:
            return None
        out = {
            "file_id": fid or (row or {}).get("file_id") or None,
            "title": (row or {}).get("title") or title,
            "doc_type": (row or {}).get("doc_type") or doc_type,
            "document_id": (row or {}).get("id") or document_id,
        }
        if out.get("file_id") or row:
            return out
        return None

    return resolve_doc


def hits_to_citations(hits: list, query: str = "", *, resolve_doc=None) -> list:
    """Convert vector/FTS search hits into structured citation dicts.

    Laws dedupe by (file_id|document_id|title) + article so one law+article
    yields a single link even when multiple chunks match.
    Cases dedupe by case identity only — judgment text often cites statutes
    (「第×条」); those must not become case "articles" or duplicate links.
    """
    try:
        from kb_query_parse import resolve_hit_article
    except Exception:
        resolve_hit_article = None  # type: ignore

    out = []
    seen = set()
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        meta = hit.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        doc = (hit.get("document") or hit.get("text") or "").strip()
        file_id = meta.get("file_id") or None
        document_id = meta.get("document_id") or ""
        title = (
            meta.get("title") or meta.get("law_name") or meta.get("case_no") or ""
        ).strip()
        doc_type = meta.get("doc_type") or ""
        if (not file_id or not title or not doc_type) and callable(resolve_doc):
            try:
                resolved = resolve_doc(document_id, title, doc_type)
            except Exception:
                resolved = None
            if isinstance(resolved, dict):
                file_id = file_id or resolved.get("file_id") or None
                title = title or (resolved.get("title") or "").strip()
                doc_type = doc_type or resolved.get("doc_type") or ""
                if resolved.get("document_id") and (
                    not document_id or document_id == title
                ):
                    document_id = resolved.get("document_id") or document_id
        # Cases are not statutes: never attach 「第×条」 from chunk/query text.
        if doc_type == "case":
            article = None
        elif resolve_hit_article:
            article = resolve_hit_article(doc, query)
        else:
            article = None
        if doc_type == "case":
            dedupe_key = f"case|{file_id or ''}|{document_id}|{title}"
        else:
            dedupe_key = (
                f"{file_id or ''}|{document_id}|{title}|{article or ''}"
            )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        rrf = hit.get("rrf_score")
        try:
            rrf_score = float(rrf) if rrf is not None else None
        except (TypeError, ValueError):
            rrf_score = None
        out.append(
            {
                "id": hit.get("id") or "",
                "doc_type": doc_type,
                "document_id": document_id,
                "file_id": file_id,
                "title": title,
                "article": article,
                "snippet": doc[:400],
                "rrf_score": rrf_score,
            }
        )
    return out


def make_kb_retrieve_fn(mcp_server):
    """Retrieve from knowledge-base vectors with doc_type scopes (law/case)."""
    store = getattr(mcp_server, "kb_store", None)
    resolve_doc = make_resolve_doc_from_store(store) if store else None

    def _ensure_fts(vs) -> None:
        """Background VectorService promote often skips FTS; attach before hybrid search."""
        if vs is None or getattr(vs, "fts", None):
            return
        if getattr(mcp_server, "vector_service", None) is not vs:
            mcp_server.vector_service = vs
        attach = getattr(mcp_server, "_attach_fts_if_ready", None)
        if callable(attach):
            try:
                attach()
            except Exception as exc:
                print(f"[kb_retrieve] FTS attach failed: {exc}")

    def _vector():
        vs = getattr(mcp_server, "vector_service", None)
        if not vs:
            inst = getattr(mcp_server, "_vector_service_instance", None)
            if isinstance(inst, (list, tuple)) and inst and inst[0]:
                mcp_server.vector_service = inst[0]
                vs = inst[0]
        if vs:
            _ensure_fts(vs)
        return vs

    def _search_scoped(vs, q: str, doc_type: str) -> list:
        pool = 5
        try:
            from kb_query_parse import extract_articles

            if extract_articles(q):
                # Article queries often lose the exact chunk in Top-5 RRF; expand then prefer.
                pool = 20
        except Exception:
            pass
        try:
            hits = vs.search(
                q, n_results=pool, boost_keywords=True, where={"doc_type": doc_type}
            )
        except Exception as exc:
            print(f"[kb_retrieve] {doc_type} search failed: {exc}")
            return []
        hits = list(hits or [])
        if doc_type == "law":
            hits = prefer_hits_matching_articles(hits, q)
        elif doc_type == "case":
            hits = prefer_hits_matching_case_query(hits, q)
        return hits[:5]

    def retrieve(query: str, scopes=None) -> Dict[str, Any]:
        scopes = [s for s in (scopes or ["law", "case"]) if s in ("law", "case")]
        if not scopes:
            scopes = ["law", "case"]
        out: Dict[str, Any] = {
            "laws": "",
            "cases": "",
            "law_citations": [],
            "case_citations": [],
        }
        vs = _vector()
        if not vs:
            return out
        q = (query or "").strip() or "法律"
        if "law" in scopes:
            hits = _search_scoped(vs, q, "law")
            out["laws"] = format_kb_hits(hits)
            out["law_citations"] = hits_to_citations(hits, q, resolve_doc=resolve_doc)
        if "case" in scopes:
            hits = _search_scoped(vs, q, "case")
            out["cases"] = format_kb_hits(hits)
            out["case_citations"] = hits_to_citations(hits, q, resolve_doc=resolve_doc)
        return out

    return retrieve


def make_retrieve_fn(mcp_server):
    """Prefer knowledge-base vector retrieval; keep mock resources as unused fallback API."""
    return make_kb_retrieve_fn(mcp_server)


def load_full_config() -> Dict[str, Any]:
    path = config_path()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_full_config(cfg: Dict[str, Any]) -> None:
    path = config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")


def public_mcp_config() -> Dict[str, Any]:
    cfg = load_full_config()
    return {
        "mcp_server": cfg.get("mcp_server") or {},
        "llm": redact_llm_config(cfg.get("llm") or {}),
    }


def apply_mcp_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    patch = validate_mcp_config_update(payload)
    cfg = ensure_profiles(load_full_config())
    if "mcp_server" in patch:
        cfg.setdefault("mcp_server", {}).update(patch["mcp_server"])
        for item in cfg.get("mcp_profiles") or []:
            if item.get("active"):
                item["host"] = cfg["mcp_server"]["host"]
                item["port"] = cfg["mcp_server"]["port"]
                break
    if "llm" in patch:
        llm_patch = dict(patch["llm"])
        key = llm_patch.pop("api_key", None)
        cfg.setdefault("llm", {}).update(llm_patch)
        if key:
            cfg["llm"]["api_key"] = key
        for item in cfg.get("llm_profiles") or []:
            if item.get("active"):
                for field, value in llm_patch.items():
                    item[field] = value
                if key:
                    item["api_key"] = key
                break
    save_full_config(cfg)
    return public_mcp_config()


def public_profiles() -> Dict[str, Any]:
    return list_public_profiles(load_full_config())


def handle_profile_create(body: Dict[str, Any]) -> Dict[str, Any]:
    cfg, item = create_profile(load_full_config(), body)
    save_full_config(cfg)
    return item


def handle_profile_update(kind: str, pid: str, body: Dict[str, Any]) -> Dict[str, Any]:
    cfg, item = update_profile(load_full_config(), kind, pid, body)
    save_full_config(cfg)
    return item


def handle_profile_delete(kind: str, pid: str) -> Dict[str, Any]:
    cfg = delete_profile(load_full_config(), kind, pid)
    save_full_config(cfg)
    return {"ok": True}


def handle_profile_get(kind: str, pid: str) -> Dict[str, Any]:
    cfg = ensure_profiles(load_full_config())
    key = "mcp_profiles" if kind == "mcp" else "llm_profiles"
    for item in cfg.get(key) or []:
        if item.get("id") == pid:
            return public_profile(kind, item, cfg.get("llm"))
    raise FileNotFoundError(pid)


def profile_path_parts(path: str) -> Optional[Tuple[str, str]]:
    prefix = "/api/admin/profiles/"
    if not path.startswith(prefix):
        return None
    rest = path[len(prefix):].strip("/")
    parts = rest.split("/")
    if len(parts) != 2 or parts[0] not in ("mcp", "llm") or not parts[1]:
        return None
    return parts[0], parts[1]


def handle_orchestrate(mcp_server, body: Dict[str, Any], on_event=None) -> Dict[str, Any]:
    from agents.workflow import WorkflowTracer, bind_workflow, reset_workflow
    user_text = body.get("user_text") or body.get("message") or ""
    messages = body.get("messages") or []
    session_id = body.get("session_id")
    skills = skill_service().match(user_text, limit=3)
    retrieve_fn = make_retrieve_fn(mcp_server)
    file_service = getattr(mcp_server, "file_service", None)
    tracer = WorkflowTracer(on_event=on_event)
    token = bind_workflow(tracer)

    def template_fn(template_name: str) -> str:
        resp = mcp_server._handle_resource_read(0, {
            "uri": "legal://doc_template",
            "arguments": {"template_name": template_name},
        })
        return _contents_text(resp)

    def write_llm(system: str, user: str, hist=None) -> str:
        from llm_complete import complete_chat
        return complete_chat(system, user, extra_messages=hist)

    raw_case = body.get("case_id")
    case_ctx = ""
    store = getattr(getattr(mcp_server, "rbac_api", None), "store", None) or getattr(
        mcp_server, "rbac_store", None
    )
    parsed_case_id = None
    case_scope = "none"
    permitted_case_ids: list = []
    if raw_case == "*":
        case_scope = "all_permitted"
        rbac_api = getattr(mcp_server, "rbac_api", None)
        uid = body.get("_auth_user_id")
        if store and uid is not None and rbac_api:
            try:
                can_all = rbac_api.rbac.require(int(uid), "cap.case_manage")
                cases = store.list_cases_for_user(int(uid), all_cases=bool(can_all))
                permitted_case_ids = [
                    int(c["id"]) for c in (cases or []) if c.get("id") is not None
                ]
            except Exception as exc:
                print(f"[orchestrate] permitted cases failed: {exc}")
    elif raw_case not in (None, ""):
        try:
            parsed_case_id = int(raw_case)
            case_scope = "single"
        except (TypeError, ValueError):
            print(f"[orchestrate] invalid case_id={raw_case!r}")
    if case_scope == "single" and parsed_case_id is not None and store and file_service:
        try:
            from case_materials import build_case_material_context

            case_ctx = build_case_material_context(
                parsed_case_id, store, file_service, write_llm=write_llm
            )
        except Exception as exc:
            print(f"[orchestrate] case materials failed: {exc}")
    enriched = user_text
    if case_ctx:
        enriched = case_ctx + "\n\n" + (user_text or "")

    try:
        result = run_orchestrate(
            user_text=enriched,
            messages=messages,
            llm=None,
            retrieve_fn=retrieve_fn,
            file_service=file_service,
            skills=skills,
            session_id=session_id,
            write_llm=write_llm,
            template_fn=template_fn,
            case_id=parsed_case_id,
            case_store=store,
            case_scope=case_scope,
            permitted_case_ids=permitted_case_ids,
            resume_state=body.get("resume_state"),
        )
    finally:
        reset_workflow(token)
    saved = False
    session_service = getattr(mcp_server, "session_service", None)
    if session_id and session_service and not result.get("legacy"):
        try:
            if not session_service.get_session(session_id):
                session_service.create_session(session_id)
            # Persist original user_text only — do not store materials block in history.
            session_service.add_message(session_id, "user", user_text)
            assistant_text = result.get("visible_text") or ""
            if result.get("status") == "awaiting_user":
                assistant_text = result.get("pending_question") or assistant_text
            extra = {}
            if result.get("artifact"):
                extra["artifact"] = result["artifact"]
            if result.get("capabilities"):
                extra["capabilities"] = result["capabilities"]
            if result.get("resume_state"):
                extra["resume_state"] = result["resume_state"]
            if result.get("plan") is not None:
                extra["plan"] = result["plan"]
            if result.get("past_steps"):
                extra["past_steps"] = result["past_steps"]
            if result.get("status"):
                extra["status"] = result["status"]
            session_service.add_message(
                session_id,
                "assistant",
                assistant_text,
                extra=extra or None,
            )
            saved = True
        except Exception as exc:
            print(f"[orchestrate] persist session messages failed: {exc}")
    result["saved_to_session"] = saved
    return result


def admin_overview_stats(mcp_server) -> Dict[str, Any]:
    skills = skill_service().list_skills()
    cfg = ensure_profiles(load_full_config())
    mcp_profiles = cfg.get("mcp_profiles") or []
    mcp_service_count = len(mcp_profiles)
    vector = getattr(mcp_server, "vector_service", None) if mcp_server else None
    document_count = 0
    chunk_count = 0
    vector_error = None
    if vector is None:
        # 后台线程可能仍在初始化（list/tuple 容器，避免 MagicMock 误判）
        inst = getattr(mcp_server, "_vector_service_instance", None) if mcp_server else None
        if isinstance(inst, (list, tuple)) and len(inst) > 0 and inst[0]:
            vector = inst[0]
            mcp_server.vector_service = vector
        else:
            vector_error = "向量服务未就绪"
    if vector is not None:
        try:
            counts = vector.count_documents()
            document_count = int(counts.get("document_count") or 0)
            chunk_count = int(counts.get("chunk_count") or 0)
            if counts.get("error"):
                vector_error = str(counts["error"])
            else:
                vector_error = None
        except Exception as e:
            vector_error = str(e)

    user_count = 0
    case_count = 0
    client_count = 0
    role_count = 0
    permission_count = 0
    rbac = getattr(mcp_server, "rbac_store", None) if mcp_server else None
    if rbac is not None:
        try:
            user_count = len(rbac.list_users())
            case_count = len(rbac.list_cases())
            client_count = len(rbac.list_clients())
            role_count = len(rbac.list_roles())
            permission_count = len(rbac.list_permissions())
        except Exception:
            pass

    return {
        "skill_count": len(skills),
        "mcp_service_count": mcp_service_count,
        "document_count": document_count,
        "chunk_count": chunk_count,
        "vector_error": vector_error,
        "user_count": user_count,
        "case_count": case_count,
        "client_count": client_count,
        "role_count": role_count,
        "permission_count": permission_count,
    }


def skill_id_from_path(path: str) -> Optional[str]:
    prefix = "/api/skills/"
    if path.startswith(prefix) and len(path) > len(prefix):
        return path[len(prefix):].strip("/")
    return None
