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


def make_retrieve_fn(mcp_server):
    def retrieve(query: str) -> Dict[str, Any]:
        law = mcp_server._handle_resource_read(0, {
            "uri": "legal://law_regulation",
            "arguments": {"query": query},
        })
        case = mcp_server._handle_resource_read(0, {
            "uri": "legal://similar_cases",
            "arguments": {"case_description": query, "query": query},
        })
        return {"laws": _contents_text(law), "cases": _contents_text(case)}
    return retrieve


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

    try:
        result = run_orchestrate(
            user_text=user_text,
            messages=messages,
            llm=None,
            retrieve_fn=retrieve_fn,
            file_service=file_service,
            skills=skills,
            session_id=session_id,
            write_llm=write_llm,
            template_fn=template_fn,
        )
    finally:
        reset_workflow(token)
    saved = False
    session_service = getattr(mcp_server, "session_service", None)
    if session_id and session_service and not result.get("legacy"):
        try:
            if not session_service.get_session(session_id):
                session_service.create_session(session_id)
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
