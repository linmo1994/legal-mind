"""LLM-based metadata extraction for knowledge-base documents."""

from __future__ import annotations

import json
import re
from typing import Callable, Optional

LAW_META_KEYS = (
    "law_name",
    "effect_level",
    "issuing_authority",
    "document_number",
    "effective_date",
)

CASE_META_KEYS = (
    "cause_of_action",
    "court",
    "procedure",
    "case_no",
    "judges",
    "case_kind",
)

LAW_SYSTEM_PROMPT = """你是法律文献元数据抽取助手。根据用户提供的法规正文，只输出一个 JSON 对象，不要输出任何其他文字或 markdown 代码块。

字段含义（未知或无法识别时填 ""）：
- law_name：法律名称
- effect_level：效力级别（如法律、行政法规、部门规章等）
- issuing_authority：发布机关
- document_number：文号
- effective_date：施行日期（YYYY-MM-DD 或原文表述）"""

CASE_SYSTEM_PROMPT = """你是裁判文书元数据抽取助手。根据用户提供的案例正文，只输出一个 JSON 对象，不要输出任何其他文字或 markdown 代码块。

字段含义（未知或无法识别时填 ""）：
- cause_of_action：案由
- court：审判法院
- procedure：审理程序（如一审、二审、再审等）
- case_no：案号
- judges：审判人员（多人用分号分隔的字符串）
- case_kind：案例类型，仅允许 "ordinary"（普通案例）或 "guiding"（指导案例），无法判断时用 "ordinary"
"""

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL | re.IGNORECASE)


def parse_json_object(text: str) -> dict:
    stripped = (text or "").strip()
    match = _FENCE_RE.match(stripped)
    if match:
        stripped = match.group(1).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("JSON root must be an object")
    return parsed


def _empty_meta(keys: tuple[str, ...]) -> dict:
    return {k: "" for k in keys}


def normalize_law_meta(raw: dict) -> dict:
    meta = _empty_meta(LAW_META_KEYS)
    for key in LAW_META_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        meta[key] = str(val).strip()
    return meta


def normalize_case_meta(raw: dict) -> dict:
    meta = _empty_meta(CASE_META_KEYS)
    for key in CASE_META_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        if key == "judges" and isinstance(val, list):
            meta[key] = "; ".join(str(v).strip() for v in val if str(v).strip())
        else:
            meta[key] = str(val).strip()
    if meta["case_kind"] not in ("ordinary", "guiding"):
        meta["case_kind"] = "ordinary"
    return meta


def extract_metadata(
    doc_type: str,
    text: str,
    *,
    complete_fn: Optional[Callable[[str, str], str]] = None,
) -> tuple[dict, str]:
    if complete_fn is None:
        from llm_complete import complete_chat

        complete_fn = complete_chat

    body = (text or "")[:12000]

    if doc_type == "law":
        system = LAW_SYSTEM_PROMPT
        normalize = normalize_law_meta
    elif doc_type == "case":
        system = CASE_SYSTEM_PROMPT
        normalize = normalize_case_meta
    else:
        raise ValueError(f"invalid doc_type: {doc_type}")

    try:
        response = complete_fn(system, body)
        raw = parse_json_object(response)
        return normalize(raw), "ready"
    except Exception:
        # Transport / HTTP / OS errors (and parse failures) degrade to empty meta.
        return normalize({}), "meta_failed"
