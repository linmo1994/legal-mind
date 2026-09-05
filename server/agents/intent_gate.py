"""Single-shot LLM legal/non-legal intent gate."""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

LEGAL_INTENTS = (
    "law_search",
    "case_search",
    "doc_writing",
    "contract_review",
    "legal_analysis",
)

NON_LEGAL_CLOSING = (
    "另外说明：我更擅长解答法律法规、类案检索与法律文书相关问题，有这类需求随时问我。"
)

CLASSIFY_SYSTEM = """你是意图分类器。只输出一个 JSON 对象，不要其它文字。
非法律问题：{"domain":"non_legal"}
法律相关（法规/类案/文书/合同审查/案情分析）：{"domain":"legal","intent":"<枚举>"}
intent 只能是：law_search, case_search, doc_writing, contract_review, legal_analysis。"""


def parse_gate_payload(raw: str) -> Optional[dict]:
    """Extract first JSON object; validate domain/intent; return None if invalid."""
    if not raw or not isinstance(raw, str):
        return None
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    domain = data.get("domain")
    if domain == "non_legal":
        return {"domain": "non_legal"}
    if domain == "legal":
        intent = data.get("intent")
        if intent not in LEGAL_INTENTS:
            return None
        return {"domain": "legal", "intent": intent}
    return None


def classify_domain_intent(
    llm_fn: Callable[..., str],
    user_text: str,
    messages: Optional[Any] = None,
) -> Optional[dict]:
    """
    Call llm_fn once for domain/intent classification.

    llm_fn(system, user, hist=None) -> str
    Returns {"domain":"non_legal"} or {"domain":"legal","intent":"..."}, or None on failure.
    """
    if llm_fn is None:
        return None
    try:
        raw = llm_fn(CLASSIFY_SYSTEM, user_text or "", messages)
    except Exception:
        return None
    return parse_gate_payload(raw if isinstance(raw, str) else None)
