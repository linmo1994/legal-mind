"""Plan-and-Execute orchestration loop with limited replan."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from agents.pe_tools import TOOL_NAMES, run_tool
from agents.workflow import emit_step

MAX_PLAN_STEPS = 8
MAX_REPLANS = 5
MAX_TOOL_CALLS = 15

_NO_CASE_GUIDANCE = (
    "无案件时不要假设能读取卷宗证据；缺当事人信息应 ask_user，请用户选择案件、「全选」或粘贴当事人信息。"
    "用户已表示不绑定案件并要求占位起草时，可用 draft_doc/reason，缺失项标注【待补充】。"
)

_RETRIEVE_GUIDANCE = (
    "用户咨询实体法律问题（如能否胜诉、责任分析、纠纷怎么办、是否合法等）且未限定只要法规或只要类案时，"
    "计划须同时包含法规检索（retrieve_law）与类案检索（retrieve_case），再综合分析。"
    "用户明确要求查找/检索类案、案例、判例时，只安排 retrieve_case，不要安排 retrieve_law；"
    "明确只要法条/法规/某法第×条时，只安排 retrieve_law，不要安排 retrieve_case。"
    "纯闲聊或仅收集当事人信息、不给出实体法结论时可不检索。"
    "最终答复应写明所依据的法规名称与条款（及类案标识），与检索结果一致；"
    "用户只要类案而本地无相关类案时，如实说明未命中，不要改用无关法条凑答；勿编造案例。"
)

PLANNER_SYSTEM = (
    "你是法律任务规划助手（planner）。根据用户目标产出可执行的步骤列表。"
    "只输出 JSON：{\"plan\":[\"步骤1\", ...]}，步骤为自然语言，长度 1–8。"
    + _NO_CASE_GUIDANCE
    + _RETRIEVE_GUIDANCE
)

EXECUTOR_SYSTEM = (
    "你是法律步骤执行器（executor）。根据当前步骤选一个工具并给出参数。"
    f"可用工具：{', '.join(TOOL_NAMES)}。"
    "只输出 JSON：{\"tool\":\"工具名\",\"args\":{...}}。"
    "若当前步骤是检索法规，选择 retrieve_law；检索类案则 retrieve_case；"
    "用户目标若是查找案例/类案，不要选择 retrieve_law；若是查找法条/某法第×条，不要选择 retrieve_case。"
    "args.query 尽量保留用户提到的法名、条款、案由关键词。"
    "若目标是生成起诉状/文书且用户已给出原告与被告（或明确要求占位起草），"
    "在无法读卷宗时优先选择 draft_doc，不要反复选择 read_evidence。"
)

# Avoid planner keywords「规划」「步骤列表」and English substring "planner".
REPLAN_SYSTEM = (
    "你是法律任务收口助手。根据目标、已执行步骤与剩余待办，"
    "在三种动作中选其一，只输出 JSON：\n"
    "- {\"action\":\"continue\",\"plan\":[\"尚未做的步骤\",...]}\n"
    "- {\"action\":\"response\",\"response\":\"最终答复\"}\n"
    "- {\"action\":\"ask_user\",\"question\":\"向用户追问\"}\n"
    + _NO_CASE_GUIDANCE
    + _RETRIEVE_GUIDANCE
    + "若用户明确只要类案而尚未检索类案，优先 continue 并补上类案检索；不要改去检索法规凑答。"
    + "若仍需法源而过去步骤尚未检索成功，优先 continue 并补上检索步骤，再 response。"
    + "若用户要生成起诉状/导出文书且已提供原告与被告（或要求占位起草），"
    "应 continue 并安排 draft_doc，或在已起草后 response；不要在能起草时仅 ask_user。"
)

WRAP_SYSTEM = (
    "请根据已执行步骤给出阶段性结论作为最终答复。"
    "优先输出 JSON：{\"action\":\"response\",\"response\":\"...\"}；"
    "若无法结构化，直接输出答复正文。"
)

_DOC_INTENT_KEYS = (
    "起诉状",
    "生成文书",
    "起草",
    "导出文书",
    "答辩状",
    "申请书",
    "判决书",
    "协议书",
    "要素式",
    "写一份",
)


def _wants_legal_doc(text: str) -> bool:
    t = text or ""
    return any(k in t for k in _DOC_INTENT_KEYS)


def _has_party_or_placeholder_signal(text: str) -> bool:
    t = text or ""
    if any(k in t for k in ("占位", "先按", "不绑定案件", "无需案件")):
        return True
    return ("原告" in t and "被告" in t)


def _already_drafted(past_steps: Optional[List[Dict[str, Any]]]) -> bool:
    return any((p or {}).get("tool") == "draft_doc" for p in (past_steps or []))


_LAW_RETRIEVE_STEP = "检索相关法规并整理可引用条文"
_CASE_RETRIEVE_STEP = "检索相关类案并整理可引用案例"

# Entity-law consultation → default dual retrieve (law + case)
_LEGAL_ADVICE_KEYS = (
    "胜诉",
    "败诉",
    "能否胜",
    "分析",
    "能不能告",
    "能否起诉",
    "可否起诉",
    "风险",
    "维权",
    "纠纷",
    "责任",
    "合法",
    "违法",
    "应否",
    "是否构成",
    "怎么办",
    "如何处理",
    "怎么打",
    "有没有戏",
    "把握",
)

_CASE_LOOKUP_KEYS = ("类案", "案例", "判例", "检索案", "相似案例")
_CASE_FIND_KEYS = ("查找", "检索", "搜索", "找")
_LAW_LOOKUP_KEYS = ("法条", "法规", "法律依据", "检索法")


def _wants_legal_advice_retrieve(text: str) -> bool:
    t = text or ""
    return any(k in t for k in _LEGAL_ADVICE_KEYS)


def _has_case_lookup_signal(text: str) -> bool:
    t = text or ""
    return any(k in t for k in _CASE_LOOKUP_KEYS)


def _has_law_lookup_signal(text: str) -> bool:
    t = text or ""
    if any(k in t for k in _LAW_LOOKUP_KEYS):
        return True
    if "第" in t and "条" in t:
        return True
    if any(k in t for k in ("依据", "引用")) and any(
        k in t for k in ("法", "条例", "规定")
    ):
        return True
    return False


def _wants_case_only(text: str) -> bool:
    """User is explicitly looking up cases, not asking for dual legal advice."""
    t = text or ""
    if not _has_case_lookup_signal(t):
        return False
    if _has_law_lookup_signal(t):
        return False
    # 「查找/检索…案例」→ case-only even if text also contains 纠纷/违约等 advice-ish words
    if any(k in t for k in _CASE_FIND_KEYS):
        return True
    # bare「只要类案/给我案例」without advice dual intent
    if not _wants_legal_advice_retrieve(t):
        return True
    return False


def _wants_law_only(text: str) -> bool:
    """User is explicitly looking up statutes, not cases."""
    t = text or ""
    if not _has_law_lookup_signal(t):
        return False
    if _has_case_lookup_signal(t):
        return False
    if any(k in t for k in _CASE_FIND_KEYS) and any(
        k in t for k in ("法", "条", "法规", "条例")
    ):
        return True
    if not _wants_legal_advice_retrieve(t):
        return True
    return False


def _wants_law_retrieve(text: str) -> bool:
    t = text or ""
    if _wants_case_only(t):
        return False
    if _wants_legal_advice_retrieve(t):
        return True
    return _has_law_lookup_signal(t)


def _wants_case_retrieve(text: str) -> bool:
    t = text or ""
    if _wants_law_only(t):
        return False
    if _wants_legal_advice_retrieve(t):
        return True
    return _has_case_lookup_signal(t)


def _looks_like_law_retrieve_step(step: str) -> bool:
    s = step or ""
    if s == _LAW_RETRIEVE_STEP or "整理可引用条文" in s:
        return True
    return ("检索" in s) and any(k in s for k in ("法规", "法条")) and not any(
        k in s for k in ("类案", "案例", "判例")
    )


def _looks_like_case_retrieve_step(step: str) -> bool:
    s = step or ""
    if s == _CASE_RETRIEVE_STEP or "整理可引用案例" in s:
        return True
    return any(k in s for k in ("类案", "案例", "判例"))


def _past_has_tool(past_steps, name: str) -> bool:
    return any((p or {}).get("tool") == name for p in (past_steps or []))


def _plan_mentions_law_retrieve(plan: list) -> bool:
    blob = "\n".join(plan or [])
    if any(k in blob for k in ("检索相关法规", "整理可引用条文")):
        return True
    has_retrieve = "检索" in blob
    has_law = any(k in blob for k in ("法规", "法条"))
    return has_retrieve and has_law


def _plan_mentions_case_retrieve(plan: list) -> bool:
    blob = "\n".join(plan or [])
    return any(k in blob for k in ("类案", "案例", "判例"))


def _ensure_retrieve_steps(
    objective: str,
    plan: list,
    past_steps=None,
    *,
    max_steps: int = MAX_PLAN_STEPS,
) -> list:
    steps = [s for s in (plan or []) if isinstance(s, str) and s.strip()]
    # Drop planner steps that conflict with exclusive lookup intent
    if _wants_case_only(objective):
        steps = [s for s in steps if not _looks_like_law_retrieve_step(s)]
    if _wants_law_only(objective):
        steps = [s for s in steps if not _looks_like_case_retrieve_step(s)]
    inject: list = []
    if (
        _wants_law_retrieve(objective)
        and not _past_has_tool(past_steps, "retrieve_law")
        and not _plan_mentions_law_retrieve(steps)
    ):
        inject.append(_LAW_RETRIEVE_STEP)
    if (
        _wants_case_retrieve(objective)
        and not _past_has_tool(past_steps, "retrieve_case")
        and not _plan_mentions_case_retrieve(steps)
    ):
        inject.append(_CASE_RETRIEVE_STEP)
    if not inject:
        return steps[:max_steps]
    merged = inject + [s for s in steps if s not in inject]
    return merged[:max_steps]


def _should_auto_draft_doc(
    objective: str,
    past_steps: Optional[List[Dict[str, Any]]],
    last_artifact: Optional[Dict[str, Any]],
    user_supplement: str = "",
) -> bool:
    """When doc intent + parties/placeholder/export are clear, don't stop without draft_doc."""
    if last_artifact or _already_drafted(past_steps):
        return False
    blob = f"{objective or ''}\n{user_supplement or ''}"
    if not _wants_legal_doc(blob):
        return False
    # 导出 = classic product expectation: draft with 【待补充】 rather than stop at ask_user
    if "导出" in blob:
        return True
    return _has_party_or_placeholder_signal(blob)


def _run_forced_draft_doc(
    *,
    write_llm,
    tool_ctx: Dict[str, Any],
    objective: str,
    user_supplement: str,
    past_steps: List[Dict[str, Any]],
    tool_calls_used: int,
) -> tuple:
    """Execute one draft_doc; returns (past_steps, tool_calls_used, artifact, observation)."""
    prompt = (user_supplement or objective or "").strip() or str(objective or "")
    step = "按已有信息起草文书并导出 Word"
    emit_step("plan_step", "draft_doc", step, status="running")
    emit_step("tool", "draft_doc", "文书起草", status="running")
    tool_out = run_tool("draft_doc", {"prompt": prompt}, tool_ctx)
    obs = str(tool_out.get("observation") or "")
    artifact = None
    if isinstance(tool_out.get("artifact"), dict) and tool_out["artifact"].get("file_id"):
        artifact = tool_out["artifact"]
    emit_step(
        "tool",
        "draft_doc",
        "文书起草",
        status="done",
        detail={"tool": "draft_doc", "observation": obs[:400], "has_artifact": bool(artifact)},
    )
    emit_step(
        "plan_step",
        "draft_doc",
        step,
        status="done",
        detail={"tool": "draft_doc", "observation": obs[:500]},
    )
    past_steps = list(past_steps) + [
        {
            "step": step,
            "observation": obs,
            "tool": "draft_doc",
            "channel": "tool",
        }
    ]
    return past_steps, tool_calls_used + 1, artifact, obs


def _finish_ask_or_response(
    *,
    action: str,
    decision: Dict[str, Any],
    write_llm,
    tool_ctx: Dict[str, Any],
    objective: str,
    user_supplement: str,
    past_steps: List[Dict[str, Any]],
    tool_calls_used: int,
    replan_count: int,
    plan: List[str],
    citations: List[Any],
    external_search: Any,
    last_artifact: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Handle ask_user/response; auto-force draft_doc when intent+parties are clear."""
    if action not in ("ask_user", "response"):
        return None

    if _should_auto_draft_doc(
        objective, past_steps, last_artifact, user_supplement=user_supplement
    ):
        past_steps, tool_calls_used, art, obs = _run_forced_draft_doc(
            write_llm=write_llm,
            tool_ctx=tool_ctx,
            objective=objective,
            user_supplement=user_supplement,
            past_steps=past_steps,
            tool_calls_used=tool_calls_used,
        )
        if art:
            last_artifact = art
        title = (last_artifact or {}).get("title") or "法律文书"
        if last_artifact and obs:
            visible = (
                f"已起草《{title}》。请在下方卡片中下载 Word 核阅后使用。\n\n{obs}"
            )
        elif action == "response":
            visible = str(decision.get("response") or "") or obs
        else:
            visible = obs or str(decision.get("question") or "")
        return _result(
            status="complete",
            visible_text=visible,
            plan=plan,
            past_steps=past_steps,
            citations=citations,
            resume_state=_snapshot_resume(
                objective,
                plan,
                past_steps,
                tool_calls_used,
                replan_count,
                external_search=external_search,
            ),
            tool_calls_used=tool_calls_used,
            replan_count=replan_count,
            external_search=external_search,
            artifact=last_artifact,
        )

    if action == "ask_user":
        return _result(
            status="awaiting_user",
            pending_question=str(decision.get("question") or ""),
            plan=plan,
            past_steps=past_steps,
            citations=citations,
            resume_state=_snapshot_resume(
                objective,
                plan,
                past_steps,
                tool_calls_used,
                replan_count,
                external_search=external_search,
            ),
            tool_calls_used=tool_calls_used,
            replan_count=replan_count,
            external_search=external_search,
            artifact=last_artifact,
        )
    visible = str(decision.get("response") or "")
    if last_artifact:
        title = last_artifact.get("title") or "法律文书"
        hint = f"已起草《{title}》。请在下方卡片中下载 Word 核阅后使用。"
        visible = f"{hint}\n\n{visible}".strip() if visible else hint
    return _result(
        status="complete",
        visible_text=visible,
        plan=plan,
        past_steps=past_steps,
        citations=citations,
        resume_state=_snapshot_resume(
            objective,
            plan,
            past_steps,
            tool_calls_used,
            replan_count,
            external_search=external_search,
        ),
        tool_calls_used=tool_calls_used,
        replan_count=replan_count,
        external_search=external_search,
        artifact=last_artifact,
    )


def _complete_with_optional_auto_draft(
    *,
    write_llm,
    tool_ctx: Dict[str, Any],
    objective: str,
    user_supplement: str,
    past_steps: List[Dict[str, Any]],
    tool_calls_used: int,
    replan_count: int,
    plan: List[str],
    citations: List[Any],
    external_search: Any,
    last_artifact: Optional[Dict[str, Any]],
    messages,
    status: str = "complete",
) -> Dict[str, Any]:
    """Budget/empty-plan wrap; force draft_doc first when doc export is owed."""
    if _should_auto_draft_doc(
        objective, past_steps, last_artifact, user_supplement=user_supplement
    ):
        past_steps, tool_calls_used, art, obs = _run_forced_draft_doc(
            write_llm=write_llm,
            tool_ctx=tool_ctx,
            objective=objective,
            user_supplement=user_supplement,
            past_steps=past_steps,
            tool_calls_used=tool_calls_used,
        )
        if art:
            last_artifact = art
        title = (last_artifact or {}).get("title") or "法律文书"
        text = (
            f"已起草《{title}》。请在下方卡片中下载 Word 核阅后使用。\n\n{obs}"
            if last_artifact and obs
            else (obs or _force_wrap_response(write_llm, objective, past_steps, messages))
        )
    else:
        text = _force_wrap_response(write_llm, objective, past_steps, messages)
    return _result(
        status=status,
        visible_text=text,
        plan=plan,
        past_steps=past_steps,
        citations=citations,
        resume_state=_snapshot_resume(
            objective,
            plan,
            past_steps,
            tool_calls_used,
            replan_count,
            external_search=external_search,
        ),
        tool_calls_used=tool_calls_used,
        replan_count=replan_count,
        external_search=external_search,
        artifact=last_artifact,
    )


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first JSON object `{...}` from model output."""
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                chunk = text[start : i + 1]
                try:
                    data = json.loads(chunk)
                except json.JSONDecodeError:
                    return None
                return data if isinstance(data, dict) else None
    return None


def _call_llm(write_llm: Optional[Callable], system: str, user: str, hist=None) -> str:
    if not write_llm:
        return ""
    try:
        return write_llm(system, user, hist) or ""
    except Exception as exc:
        return f"(llm error: {exc})"


def _llm_json(
    write_llm: Optional[Callable],
    system: str,
    user: str,
    hist=None,
) -> Optional[Dict[str, Any]]:
    """Parse JSON from LLM; retry once on failure."""
    raw = _call_llm(write_llm, system, user, hist)
    data = _extract_json(raw)
    if data is not None:
        return data
    raw2 = _call_llm(write_llm, system, user + "\n请严格只输出一个 JSON 对象。", hist)
    return _extract_json(raw2)


def _normalize_plan(raw: Any, max_steps: int) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for item in raw:
        s = str(item or "").strip()
        if s:
            out.append(s)
        if len(out) >= max_steps:
            break
    return out


def _plan_llm(
    write_llm: Optional[Callable],
    objective: str,
    messages,
    max_plan_steps: int,
) -> List[str]:
    user = f"目标：{objective}"
    data = _llm_json(write_llm, PLANNER_SYSTEM, user, messages)
    plan = _normalize_plan((data or {}).get("plan"), max_plan_steps)
    if plan:
        return plan
    # heuristic short plan
    return ["检索相关法规并分析后给出结论"][:max_plan_steps]


def _exec_llm(
    write_llm: Optional[Callable],
    step: str,
    objective: str,
    messages,
) -> Dict[str, Any]:
    user = f"目标：{objective}\n当前步骤：{step}\n请选择恰好一个工具。"
    data = _llm_json(write_llm, EXECUTOR_SYSTEM, user, messages)
    if data and data.get("tool"):
        args = data.get("args") if isinstance(data.get("args"), dict) else {}
        return {"tool": str(data.get("tool")), "args": args}
    # heuristic
    return {"tool": "reason", "args": {"prompt": step or objective}}


def _replan_llm(
    write_llm: Optional[Callable],
    objective: str,
    past_steps: List[Dict[str, Any]],
    plan: List[str],
    messages,
    tool_calls_used: int,
    replan_count: int,
    max_tool_calls: int,
    max_replans: int,
    max_plan_steps: int,
    user_supplement: str = "",
) -> Dict[str, Any]:
    past_txt = json.dumps(past_steps, ensure_ascii=False)[:4000]
    user = (
        f"目标：{objective}\n"
        f"{'用户补充：' + user_supplement + chr(10) if user_supplement else ''}"
        f"已执行：{past_txt}\n"
        f"剩余计划：{plan}\n"
        f"预算：tool {tool_calls_used}/{max_tool_calls}，replan {replan_count}/{max_replans}\n"
        "请选择 continue / response / ask_user。"
    )
    data = _llm_json(write_llm, REPLAN_SYSTEM, user, messages)
    if not data or not data.get("action"):
        # heuristic: if we have past steps, respond; else continue with reason
        if past_steps:
            obs = past_steps[-1].get("observation") or ""
            return {
                "action": "response",
                "response": str(obs)[:2000] or "已根据已有步骤给出结论。",
            }
        return {"action": "continue", "plan": ["综合分析并给出结论"]}

    action = str(data.get("action") or "").strip().lower()
    if action == "ask_user":
        q = str(data.get("question") or data.get("pending_question") or "").strip()
        return {"action": "ask_user", "question": q or "请补充关键事实信息。"}
    if action == "response":
        return {
            "action": "response",
            "response": str(data.get("response") or "").strip() or "（空答复）",
        }
    # continue
    new_plan = _normalize_plan(data.get("plan"), max_plan_steps)
    if not new_plan:
        new_plan = list(plan) if plan else ["综合分析并给出结论"]
    return {"action": "continue", "plan": new_plan}


def _force_wrap_response(
    write_llm: Optional[Callable],
    objective: str,
    past_steps: List[Dict[str, Any]],
    messages,
) -> str:
    past_txt = json.dumps(past_steps, ensure_ascii=False)[:4000]
    user = f"目标：{objective}\n已执行步骤：{past_txt}\n请给出最终答复。"
    raw = _call_llm(write_llm, WRAP_SYSTEM, user, messages)
    data = _extract_json(raw) or {}
    if data.get("action") == "response" or data.get("response"):
        text = str(data.get("response") or "").strip()
        if text:
            return text
    # If model returned continue/ask_user JSON or empty, fall back to past observations
    if raw and not (raw.strip().startswith("{") and _extract_json(raw)):
        return raw.strip()
    bits = []
    for step in past_steps:
        obs = str(step.get("observation") or "").strip()
        if obs:
            bits.append(obs)
    if bits:
        return "\n".join(bits)[:3000]
    return "已达到执行预算，基于现有信息给出阶段性结论。"


def _snapshot_resume(
    objective: str,
    plan: List[str],
    past_steps: List[Dict[str, Any]],
    tool_calls_used: int,
    replan_count: int,
    external_search: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "objective": objective,
        "plan": list(plan),
        "past_steps": list(past_steps),
        "tool_calls_used": tool_calls_used,
        "replan_count": replan_count,
    }
    if external_search:
        out["external_search"] = external_search
    return out


def _result(
    *,
    status: str,
    visible_text: str = "",
    plan: Optional[List[str]] = None,
    past_steps: Optional[List[Dict[str, Any]]] = None,
    pending_question: str = "",
    citations: Optional[List[Dict[str, Any]]] = None,
    resume_state: Optional[Dict[str, Any]] = None,
    tool_calls_used: int = 0,
    replan_count: int = 0,
    external_search: Optional[Dict[str, Any]] = None,
    artifact: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    out = {
        "visible_text": visible_text or "",
        "plan": list(plan or []),
        "past_steps": list(past_steps or []),
        "pending_question": pending_question or "",
        "citations": list(citations or []),
        "orchestration_mode": "plan_execute",
        "resume_state": resume_state,
        "status": status,
        "tool_calls_used": tool_calls_used,
        "replan_count": replan_count,
    }
    if external_search:
        out["external_search"] = external_search
    if artifact:
        out["artifact"] = artifact
    return out


def run_plan_execute(
    objective: str,
    messages=None,
    write_llm=None,
    retrieve_fn=None,
    file_service=None,
    case_id=None,
    case_store=None,
    case_scope=None,
    permitted_case_ids=None,
    skills=None,
    session_id=None,
    resume_state=None,
    max_plan_steps: int = MAX_PLAN_STEPS,
    max_replans: int = MAX_REPLANS,
    max_tool_calls: int = MAX_TOOL_CALLS,
) -> Dict[str, Any]:
    """Run Plan → Execute(one tool) → Replan loop until response / ask_user / budget."""
    messages = messages or []
    citations: List[Dict[str, Any]] = []
    user_supplement = ""
    external_search = None
    last_artifact: Optional[Dict[str, Any]] = None

    # Tool-internal LLM calls (e.g. reason) must not be mistaken for replanner by
    # scripted fakes that key off non-planner/non-executor system prompts.
    def _tool_write_llm(system, user, hist=None):
        tagged = (system or "") + "\n（选一个工具已选定，请直接完成该工具所需输出）"
        return _call_llm(write_llm, tagged, user, hist)

    resolved_scope = case_scope or ("single" if case_id is not None else "none")
    tool_ctx = {
        "retrieve_fn": retrieve_fn,
        "write_llm": _tool_write_llm if write_llm else None,
        "file_service": file_service,
        "case_id": case_id,
        "case_scope": resolved_scope,
        "permitted_case_ids": list(permitted_case_ids or []),
        "case_store": case_store,
        "messages": messages,
        "objective": objective,
        "skills": skills,
        "session_id": session_id,
    }

    if resume_state:
        base_objective = str(resume_state.get("objective") or objective or "")
        plan = list(resume_state.get("plan") or [])
        past_steps: List[Dict[str, Any]] = list(resume_state.get("past_steps") or [])
        tool_calls_used = int(resume_state.get("tool_calls_used") or 0)
        replan_count = int(resume_state.get("replan_count") or 0)
        external_search = resume_state.get("external_search")
        user_supplement = str(objective or "")
        objective = base_objective
        tool_ctx["objective"] = objective
        # Budget already exhausted — wrap without another replan (avoids unbounded ask_user cycles)
        if tool_calls_used >= max_tool_calls or replan_count >= max_replans:
            return _complete_with_optional_auto_draft(
                write_llm=write_llm,
                tool_ctx=tool_ctx,
                objective=objective,
                user_supplement=user_supplement,
                past_steps=past_steps,
                tool_calls_used=tool_calls_used,
                replan_count=replan_count,
                plan=plan,
                citations=citations,
                external_search=external_search,
                last_artifact=last_artifact,
                messages=messages,
            )
        # Skip planner; replan immediately with user supplement
        decision = _replan_llm(
            write_llm,
            objective,
            past_steps,
            plan,
            messages,
            tool_calls_used,
            replan_count,
            max_tool_calls,
            max_replans,
            max_plan_steps,
            user_supplement=user_supplement,
        )
        replan_count += 1
        action = decision.get("action")
        finished = _finish_ask_or_response(
            action=str(action or ""),
            decision=decision,
            write_llm=write_llm,
            tool_ctx=tool_ctx,
            objective=objective,
            user_supplement=user_supplement,
            past_steps=past_steps,
            tool_calls_used=tool_calls_used,
            replan_count=replan_count,
            plan=plan,
            citations=citations,
            external_search=external_search,
            last_artifact=last_artifact,
        )
        if finished is not None:
            return finished
        plan = list(decision.get("plan") or [])
        plan = _ensure_retrieve_steps(
            f"{objective}\n{user_supplement}",
            plan,
            past_steps,
            max_steps=max_plan_steps,
        )
        emit_step("plan", "plan", "执行计划", detail={"steps": list(plan)})
    else:
        past_steps = []
        tool_calls_used = 0
        replan_count = 0
        plan = _plan_llm(write_llm, objective, messages, max_plan_steps)
        plan = _ensure_retrieve_steps(
            objective, plan, past_steps, max_steps=max_plan_steps
        )
        emit_step("plan", "plan", "执行计划", detail={"steps": list(plan)})

    safety = max_tool_calls + max_replans + 8
    for _ in range(safety):
        if tool_calls_used >= max_tool_calls or replan_count >= max_replans:
            return _complete_with_optional_auto_draft(
                write_llm=write_llm,
                tool_ctx=tool_ctx,
                objective=objective,
                user_supplement=user_supplement,
                past_steps=past_steps,
                tool_calls_used=tool_calls_used,
                replan_count=replan_count,
                plan=plan,
                citations=citations,
                external_search=external_search,
                last_artifact=last_artifact,
                messages=messages,
            )

        if not plan:
            return _complete_with_optional_auto_draft(
                write_llm=write_llm,
                tool_ctx=tool_ctx,
                objective=objective,
                user_supplement=user_supplement,
                past_steps=past_steps,
                tool_calls_used=tool_calls_used,
                replan_count=replan_count,
                plan=plan,
                citations=citations,
                external_search=external_search,
                last_artifact=last_artifact,
                messages=messages,
            )

        step = plan[0]
        choice = _exec_llm(write_llm, step, objective, messages)
        tool_name = str(choice.get("tool") or "reason")
        tool_args = choice.get("args") if isinstance(choice.get("args"), dict) else {}
        step_id = tool_name or str(tool_calls_used)
        # Human-visible call-site kinds for the workbench (KB ≠ Skill ≠ MCP).
        _TOOL_FLOW = {
            "retrieve_law": ("kb", "kb_law", "本地知识库 · 法规检索"),
            "retrieve_case": ("kb", "kb_case", "本地知识库 · 类案检索"),
            "read_evidence": ("kb", "kb_evidence", "案件材料 · 证据阅读"),
            "draft_doc": ("tool", "draft_doc", "文书起草"),
            "reason": ("tool", "reason", "推理综合"),
        }
        flow_kind, flow_id, flow_name = _TOOL_FLOW.get(
            tool_name, ("tool", tool_name, tool_name)
        )
        emit_step("plan_step", step_id, step, status="running")
        emit_step(flow_kind, flow_id, flow_name, status="running")
        tool_out = run_tool(tool_name, tool_args, tool_ctx)
        obs = str(tool_out.get("observation") or "")
        if isinstance(tool_out.get("artifact"), dict) and tool_out["artifact"].get("file_id"):
            last_artifact = tool_out["artifact"]
        for c in tool_out.get("citations") or []:
            if isinstance(c, dict):
                citations.append(c)
        cite_n = len(tool_out.get("citations") or [])
        emit_step(
            flow_kind,
            flow_id,
            flow_name,
            status="done",
            detail={
                "tool": tool_name,
                "channel": "local_kb" if flow_kind == "kb" else "tool",
                "citations": cite_n,
                "observation": obs[:400],
            },
        )
        if tool_out.get("external_search"):
            external_search = tool_out["external_search"]
            emit_step(
                "external",
                "npc_flk",
                "国家法律法规数据库（未自动抓取）",
                status="done",
                detail={
                    "reason": external_search.get("reason"),
                    "query": external_search.get("query"),
                    "url": external_search.get("url"),
                },
            )
        emit_step(
            "plan_step",
            step_id,
            step,
            status="done",
            detail={"tool": tool_name, "observation": obs[:500]},
        )

        past_steps.append(
            {
                "step": step,
                "observation": obs,
                "tool": tool_name,
                "channel": "local_kb" if flow_kind == "kb" else "tool",
            }
        )
        plan = plan[1:]
        tool_calls_used += 1

        decision = _replan_llm(
            write_llm,
            objective,
            past_steps,
            plan,
            messages,
            tool_calls_used,
            replan_count,
            max_tool_calls,
            max_replans,
            max_plan_steps,
            user_supplement=user_supplement,
        )
        replan_count += 1
        action = decision.get("action")

        finished = _finish_ask_or_response(
            action=str(action or ""),
            decision=decision,
            write_llm=write_llm,
            tool_ctx=tool_ctx,
            objective=objective,
            user_supplement=user_supplement,
            past_steps=past_steps,
            tool_calls_used=tool_calls_used,
            replan_count=replan_count,
            plan=plan,
            citations=citations,
            external_search=external_search,
            last_artifact=last_artifact,
        )
        if finished is not None:
            return finished
        # continue
        plan = list(decision.get("plan") or [])
        plan = _ensure_retrieve_steps(
            f"{objective}\n{user_supplement}",
            plan,
            past_steps,
            max_steps=max_plan_steps,
        )
        emit_step("plan", "plan", "执行计划", detail={"steps": list(plan)})

    return _complete_with_optional_auto_draft(
        write_llm=write_llm,
        tool_ctx=tool_ctx,
        objective=objective,
        user_supplement=user_supplement,
        past_steps=past_steps,
        tool_calls_used=tool_calls_used,
        replan_count=replan_count,
        plan=plan,
        citations=citations,
        external_search=external_search,
        last_artifact=last_artifact,
        messages=messages,
        status="error",
    )
