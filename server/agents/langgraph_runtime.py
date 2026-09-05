"""LangGraph runtime: orchestrator + three specialists with a local call trace."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from langgraph.graph import END, START, StateGraph

from agents.graph import validate_subcall
from agents.orchestrator import (
    RetrievalCache,
    cap_agent,
    flatten_capabilities,
    merge_capability_items,
    run_specialist,
)


def _append_unique(trace: List[Dict[str, str]], item: Dict[str, str]) -> None:
    key = (item.get("kind"), item.get("id"))
    for existing in trace:
        if (existing.get("kind"), existing.get("id")) == key:
            return
    if item.get("id"):
        trace.append(item)


def _trace_from_result(agent: str, result: Dict[str, Any]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = [cap_agent(agent)]
    for sub in result.get("subcalls_used") or []:
        items.append(cap_agent(sub))
    items.extend(flatten_capabilities(result.get("capabilities")))
    ordered: List[Dict[str, str]] = []
    for item in items:
        _append_unique(ordered, item)
    return ordered


def run_langgraph(
    user_text: str,
    messages: Optional[List[Dict]] = None,
    plan: Optional[Dict[str, Any]] = None,
    retrieve_fn: Optional[Callable] = None,
    file_service=None,
    skills: Optional[List[Dict]] = None,
    session_id: Optional[str] = None,
    write_llm=None,
    template_fn=None,
    cache: Optional[RetrievalCache] = None,
    case_id=None,
    case_store=None,
) -> Dict[str, Any]:
    messages = messages or []
    skills = skills or []
    cache = cache or RetrievalCache()
    if not plan:
        raise ValueError("plan is required")

    def specialist_node(agent_name: str):
        def node(state: Dict[str, Any]) -> Dict[str, Any]:
            steps = (state.get("plan") or {}).get("steps") or []
            index = int(state.get("step_index") or 0)
            step = steps[index] if index < len(steps) else {"agent": agent_name, "allow_subcalls": []}
            allow = step.get("allow_subcalls") or []
            validate_subcall("orchestrator", agent_name, depth=0, visited=set())
            last = run_specialist(
                agent_name,
                state.get("user_text") or "",
                state.get("messages") or [],
                allow,
                depth=1,
                visited={agent_name},
                retrieve_fn=retrieve_fn,
                cache=cache,
                file_service=file_service,
                session_id=session_id,
                skills=state.get("skills") or [],
                write_llm=write_llm,
                template_fn=template_fn,
                retrieval_scopes=(state.get("plan") or {}).get("retrieval_scopes"),
                intent=(state.get("plan") or {}).get("intent"),
                case_id=case_id,
                case_store=case_store,
            )
            trace = list(state.get("trace") or [])
            for item in _trace_from_result(agent_name, last):
                _append_unique(trace, item)
            return {
                "last": last,
                "step_index": index + 1,
                "trace": trace,
            }

        return node

    def finish(state: Dict[str, Any]) -> Dict[str, Any]:
        last = dict(state.get("last") or {})
        last["plan"] = state.get("plan") or plan
        last.setdefault("visible_text", "")
        last.setdefault("agent", "orchestrator")
        trace = list(state.get("trace") or [])
        caps = merge_capability_items(flatten_capabilities(last.get("capabilities")), trace)
        caps["trace"] = trace
        last["capabilities"] = caps
        last["runtime"] = "langgraph"
        return {"result": last}

    def route_next(state: Dict[str, Any]) -> str:
        steps = (state.get("plan") or {}).get("steps") or []
        index = int(state.get("step_index") or 0)
        if index >= len(steps):
            return "finish"
        agent = (steps[index] or {}).get("agent")
        if agent in ("text_analysis", "legal_retrieval", "doc_writing"):
            return agent
        return "finish"

    builder = StateGraph(dict)
    builder.add_node("text_analysis", specialist_node("text_analysis"))
    builder.add_node("legal_retrieval", specialist_node("legal_retrieval"))
    builder.add_node("doc_writing", specialist_node("doc_writing"))
    builder.add_node("finish", finish)
    routes = {
        "text_analysis": "text_analysis",
        "legal_retrieval": "legal_retrieval",
        "doc_writing": "doc_writing",
        "finish": "finish",
    }
    builder.add_conditional_edges(START, route_next, routes)
    for name in ("text_analysis", "legal_retrieval", "doc_writing"):
        builder.add_conditional_edges(name, route_next, routes)
    builder.add_edge("finish", END)
    compiled = builder.compile()
    initial = {
        "user_text": user_text,
        "messages": messages,
        "skills": skills,
        "plan": plan,
        "step_index": 0,
        "trace": [cap_agent("orchestrator")],
        "last": {},
    }
    out = compiled.invoke(initial)
    result = out.get("result") if isinstance(out, dict) else None
    if not isinstance(result, dict):
        raise RuntimeError("LangGraph 未返回编排结果")
    return result
