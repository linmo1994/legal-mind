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
    "validity",
)

CASE_META_KEYS = (
    "cause_of_action",
    "court",
    "procedure",
    "case_no",
    "judges",
    "case_kind",
    "validity",
)

TEMPLATE_META_KEYS = (
    "template_name",
    "document_type",
    "case_category",
    "validity",
)

TEMPLATE_DOCUMENT_TYPES = ("起诉状", "答辩状", "申请书")
TEMPLATE_CASE_CATEGORIES = ("民事", "刑事", "行政")
VALIDITY_VALUES = ("有效", "失效")
DEFAULT_VALIDITY = "有效"

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

TEMPLATE_SYSTEM_PROMPT = """你是最高人民法院要素式法律文书模板元数据抽取助手。根据用户提供的模板正文（可能含文件名），只输出一个 JSON 对象，不要输出任何其他文字或 markdown 代码块。

字段含义：
- template_name：文书全称，必须包含案由（或具体事项）+ 文书种类，例如「民间借贷纠纷起诉状」「离婚纠纷答辩状」「强制执行申请书」。禁止只填「起诉状」「答辩状」「申请书」或仅「民事起诉状」这类过短名称；未知填 ""
- document_type：文书类型，仅允许 "起诉状"、"答辩状"、"申请书" 三者之一；无法判断时填 ""
- case_category：案件类型，仅允许 "民事"、"刑事"、"行政" 三者之一；无法判断时填 ""
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


def _apply_validity(meta: dict, raw: dict | None = None) -> dict:
    raw = raw or {}
    val = raw.get("validity", meta.get("validity"))
    if val is None:
        val = ""
    val = str(val).strip()
    # Accept common aliases from LLM / older UI.
    aliases = {
        "valid": DEFAULT_VALIDITY,
        "active": DEFAULT_VALIDITY,
        "invalid": "失效",
        "inactive": "失效",
        "expired": "失效",
    }
    val = aliases.get(val.lower(), val) if val else val
    meta["validity"] = val if val in VALIDITY_VALUES else DEFAULT_VALIDITY
    return meta


def normalize_law_meta(raw: dict) -> dict:
    meta = _empty_meta(LAW_META_KEYS)
    for key in LAW_META_KEYS:
        if key == "validity":
            continue
        val = raw.get(key)
        if val is None:
            continue
        meta[key] = str(val).strip()
    return _apply_validity(meta, raw)


def normalize_case_meta(raw: dict) -> dict:
    meta = _empty_meta(CASE_META_KEYS)
    for key in CASE_META_KEYS:
        if key == "validity":
            continue
        val = raw.get(key)
        if val is None:
            continue
        if key == "judges" and isinstance(val, list):
            meta[key] = "; ".join(str(v).strip() for v in val if str(v).strip())
        else:
            meta[key] = str(val).strip()
    if meta["case_kind"] not in ("ordinary", "guiding"):
        meta["case_kind"] = "ordinary"
    return _apply_validity(meta, raw)


def normalize_template_meta(raw: dict) -> dict:
    meta = _empty_meta(TEMPLATE_META_KEYS)
    for key in TEMPLATE_META_KEYS:
        if key == "validity":
            continue
        val = raw.get(key)
        if val is None:
            continue
        meta[key] = str(val).strip()
    if meta["document_type"] not in TEMPLATE_DOCUMENT_TYPES:
        meta["document_type"] = ""
    if meta["case_category"] not in TEMPLATE_CASE_CATEGORIES:
        meta["case_category"] = ""
    return _apply_validity(meta, raw)


def template_name_from_filename(filename: str | None) -> str:
    """Strip path/extension; e.g. 民间借贷纠纷起诉状.docx → 民间借贷纠纷起诉状."""
    if not filename:
        return ""
    base = str(filename).replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not base:
        return ""
    if "." in base:
        base = base.rsplit(".", 1)[0].strip()
    return base


def is_bare_template_name(name: str | None) -> bool:
    """True when name is empty or lacks 案由 (too generic)."""
    n = (name or "").strip()
    if not n:
        return True
    if n in TEMPLATE_DOCUMENT_TYPES:
        return True
    for cat in TEMPLATE_CASE_CATEGORIES:
        for dt in TEMPLATE_DOCUMENT_TYPES:
            if n == f"{cat}{dt}":
                return True
    return False


def refine_template_meta(meta: dict, source_filename: str | None = None) -> dict:
    """Prefer a full name from the upload filename when LLM name is bare/empty."""
    out = dict(meta or {})
    stem = template_name_from_filename(source_filename)
    current = (out.get("template_name") or "").strip()
    if stem and is_bare_template_name(current):
        out["template_name"] = stem
    elif stem and current and stem != current and current in stem:
        # LLM returned a suffix of the filename (e.g. 起诉状 vs 民间借贷纠纷起诉状)
        out["template_name"] = stem
    elif not current and stem:
        out["template_name"] = stem
    return normalize_template_meta(out)


def extract_metadata(
    doc_type: str,
    text: str,
    *,
    complete_fn: Optional[Callable[[str, str], str]] = None,
    source_filename: Optional[str] = None,
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
    elif doc_type == "template":
        system = TEMPLATE_SYSTEM_PROMPT
        normalize = normalize_template_meta
        stem = template_name_from_filename(source_filename)
        if stem:
            body = f"文件名：{stem}\n\n{body}"
    else:
        raise ValueError(f"invalid doc_type: {doc_type}")

    try:
        response = complete_fn(system, body)
        raw = parse_json_object(response)
        meta = normalize(raw)
    except Exception:
        # Transport / HTTP / OS errors (and parse failures) degrade to empty meta.
        meta = normalize({})
        if doc_type == "template":
            return refine_template_meta(meta, source_filename), "meta_failed"
        return meta, "meta_failed"

    if doc_type == "template":
        meta = refine_template_meta(meta, source_filename)
    return meta, "ready"
