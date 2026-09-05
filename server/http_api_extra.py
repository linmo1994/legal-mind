"""Extra REST routes: orchestrate, skills, MCP admin config."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Tuple

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


def hits_to_citations(hits: list, query: str = "") -> list:
    """Convert vector/FTS search hits into structured citation dicts.

    Dedupes by (file_id|document_id|title) + article so one law+article
    yields a single link even when multiple chunks match.
    """
    try:
        from kb_query_parse import extract_articles
    except Exception:
        extract_articles = None  # type: ignore

    query_articles = extract_articles(query) if extract_articles else []
    query_article = query_articles[0] if query_articles else None
    out = []
    seen = set()
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        meta = hit.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        doc = (hit.get("document") or hit.get("text") or "").strip()
        title = (
            meta.get("title") or meta.get("law_name") or meta.get("case_no") or ""
        ).strip()
        article = query_article
        if not article and extract_articles and doc:
            found = extract_articles(doc)
            article = found[0] if found else None
        file_id = meta.get("file_id") or None
        document_id = meta.get("document_id") or ""
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
                "doc_type": meta.get("doc_type") or "",
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

    def _vector():
        vs = getattr(mcp_server, "vector_service", None)
        if vs:
            return vs
        inst = getattr(mcp_server, "_vector_service_instance", None)
        if isinstance(inst, (list, tuple)) and inst and inst[0]:
            mcp_server.vector_service = inst[0]
            return inst[0]
        return None

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
            try:
                hits = vs.search(q, n_results=5, boost_keywords=True, where={"doc_type": "law"})
            except Exception as exc:
                hits = []
                print(f"[kb_retrieve] law search failed: {exc}")
            out["laws"] = format_kb_hits(hits)
            out["law_citations"] = hits_to_citations(hits, q)
        if "case" in scopes:
            try:
                hits = vs.search(q, n_results=5, boost_keywords=True, where={"doc_type": "case"})
            except Exception as exc:
                hits = []
                print(f"[kb_retrieve] case search failed: {exc}")
            out["cases"] = format_kb_hits(hits)
            out["case_citations"] = hits_to_citations(hits, q)
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

    case_id = body.get("case_id")
    case_ctx = ""
    store = getattr(getattr(mcp_server, "rbac_api", None), "store", None) or getattr(
        mcp_server, "rbac_store", None
    )
    parsed_case_id = None
    if case_id not in (None, ""):
        try:
            parsed_case_id = int(case_id)
        except (TypeError, ValueError):
            print(f"[orchestrate] invalid case_id={case_id!r}")
    if parsed_case_id is not None and store and file_service:
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
            extra = {}
            if result.get("artifact"):
                extra["artifact"] = result["artifact"]
            if result.get("capabilities"):
                extra["capabilities"] = result["capabilities"]
            session_service.add_message(
                session_id,
                "assistant",
                result.get("visible_text") or "",
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
