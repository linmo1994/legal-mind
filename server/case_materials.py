"""Assemble case contract/evidence context for LLM prompts."""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

EVIDENCE_BRIEF_MAX = 200
CONTRACT_TEXT_MAX = 20000
EVIDENCE_TEXT_MAX = 15000
TOOL_NAME = "get_case_evidence_file"

WriteLlm = Callable[..., str]


def allow_case_material_access(
    authorization: Optional[str],
    case_id: Any,
    rbac_api: Any,
) -> bool:
    """Gate case materials inject / evidence tool round behind cap.chat.

    - No case_id → False (nothing to inject).
    - No rbac_api → True (match orchestrate when RBAC not wired).
    - Otherwise require check_orchestrate_access status 200; on deny/error, False.
    """
    if case_id in (None, ""):
        return False
    if rbac_api is None:
        return True
    try:
        status, payload = rbac_api.check_orchestrate_access(
            authorization, {"case_id": case_id, "user_text": ""}
        )
        if status != 200:
            err = ""
            if isinstance(payload, dict):
                err = payload.get("error") or payload.get("detail") or ""
            print(
                f"[case_materials] skip inject/tool: case_id={case_id} "
                f"status={status} {err}"
            )
            return False
        return True
    except Exception as exc:
        print(f"[case_materials] access check failed case_id={case_id}: {exc}")
        return False


def truncate_chars(text: str, limit: int) -> str:
    t = text or ""
    if len(t) <= limit:
        return t
    return t[:limit] + "…[已截断]"


def cap_evidence_brief(text: str) -> str:
    """Return evidence brief with length <= EVIDENCE_BRIEF_MAX."""
    t = truncate_chars(text or "", EVIDENCE_BRIEF_MAX).replace("…[已截断]", "…")
    if len(t) <= EVIDENCE_BRIEF_MAX:
        return t
    return t[: EVIDENCE_BRIEF_MAX - 1] + "…"


def _meta(case: Dict[str, Any]) -> Dict[str, Any]:
    return dict(case.get("meta") or {})


def _heuristic_brief(text: str) -> str:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if not compact:
        return "暂无摘要"
    return cap_evidence_brief(compact)


def generate_evidence_brief(text: str, write_llm: Optional[WriteLlm] = None) -> str:
    body = (text or "").strip()
    if not body:
        return "暂无摘要"
    if write_llm:
        try:
            raw = write_llm(
                "你是法律助理。根据证据材料正文写中文说明，不超过200字，只输出说明本身。",
                truncate_chars(body, 6000),
            )
            brief = re.sub(r"\s+", " ", (raw or "").strip())
            if brief:
                return cap_evidence_brief(brief)
        except Exception as exc:
            print(f"[case_materials] brief llm failed: {exc}")
    return _heuristic_brief(body)


def ensure_evidence_briefs(
    file_service,
    file_ids: List[str],
    write_llm: Optional[WriteLlm] = None,
) -> None:
    for fid in file_ids or []:
        info = file_service.get_file(fid)
        if not info:
            continue
        meta = dict(info.get("metadata") or {})
        if (meta.get("evidence_brief") or "").strip():
            continue
        text = info.get("text_content")
        if text is None and hasattr(file_service, "get_file_text"):
            text = file_service.get_file_text(fid)
        brief = generate_evidence_brief(text or "", write_llm=write_llm)
        file_service.update_file_metadata(fid, {"evidence_brief": brief})


def build_case_material_context(
    case_id: int,
    store,
    file_service,
    write_llm: Optional[WriteLlm] = None,
) -> str:
    case = store.get_case(int(case_id))
    if not case:
        return ""
    meta = _meta(case)
    evidence_ids = list(meta.get("evidence_file_ids") or [])
    ensure_evidence_briefs(file_service, evidence_ids, write_llm=write_llm)

    lines = ["【当前案件】"]
    lines.append(
        f"案号：{case.get('case_no') or '-'}｜标题：{case.get('title') or '-'}｜"
        f"类型：{meta.get('case_type') or '-'}"
    )
    lines.append("")
    lines.append("【委托合同】")
    contract_ids = list(meta.get("contract_file_ids") or [])
    if not contract_ids:
        lines.append("未上传委托合同。")
    else:
        for fid in contract_ids:
            info = file_service.get_file(fid) or {}
            name = info.get("original_name") or fid
            text = info.get("text_content")
            if text is None and hasattr(file_service, "get_file_text"):
                text = file_service.get_file_text(fid)
            lines.append(f"文件名：{name}（file_id={fid}）")
            lines.append(truncate_chars(text or "（无解析正文）", CONTRACT_TEXT_MAX))
    lines.append("")
    lines.append("【证据材料】")
    if not evidence_ids:
        lines.append("未上传证据材料。")
    else:
        for i, fid in enumerate(evidence_ids, 1):
            info = file_service.get_file(fid) or {}
            meta_f = dict(info.get("metadata") or {})
            brief = (meta_f.get("evidence_brief") or "").strip() or "暂无摘要"
            lines.append(
                f"{i}. file_id={fid}｜文件名={info.get('original_name') or fid}｜"
                f"类型={info.get('file_type') or '-'}｜说明={brief}"
            )
        lines.append(
            f"如需某份证据全文，请单独回复一行 JSON："
            f'{{"tool":"{TOOL_NAME}","file_id":"<id>"}}'
        )
    return "\n".join(lines).strip()


def resolve_cases_for_file_id(file_id: str, case_ids: List[int], store) -> List[int]:
    fid = str(file_id or "").strip()
    hits: List[int] = []
    if not fid or not store:
        return hits
    for cid in case_ids or []:
        try:
            case = store.get_case(int(cid))
        except Exception:
            continue
        if not case:
            continue
        meta = dict(case.get("meta") or {})
        bag = set(str(x) for x in (meta.get("evidence_file_ids") or []))
        if fid in bag:
            hits.append(int(cid))
    return hits


def get_case_evidence_text(
    case_id: int,
    file_id: str,
    store,
    file_service,
) -> str:
    case = store.get_case(int(case_id))
    if not case:
        raise ValueError("案件不存在")
    allowed = set(_meta(case).get("evidence_file_ids") or [])
    if file_id not in allowed:
        raise ValueError("该文件不属于本案证据材料")
    info = file_service.get_file(file_id)
    if not info:
        raise ValueError("文件不存在")
    text = info.get("text_content")
    if text is None and hasattr(file_service, "get_file_text"):
        text = file_service.get_file_text(file_id)
    name = info.get("original_name") or file_id
    body = truncate_chars(text or "（无解析正文）", EVIDENCE_TEXT_MAX)
    return f"【证据全文】{name}（file_id={file_id}）\n{body}"


def parse_evidence_tool_call(reply: str) -> Optional[str]:
    if not reply:
        return None
    for line in (reply or "").splitlines():
        s = line.strip()
        if not (s.startswith("{") and s.endswith("}")):
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        if obj.get("tool") == TOOL_NAME and obj.get("file_id"):
            return str(obj["file_id"]).strip()
    # 全文仅含一个 JSON 对象时
    m = re.search(
        r'\{\s*"tool"\s*:\s*"' + re.escape(TOOL_NAME) + r'"\s*,\s*"file_id"\s*:\s*"([^"]+)"\s*\}',
        reply,
    )
    return m.group(1) if m else None
