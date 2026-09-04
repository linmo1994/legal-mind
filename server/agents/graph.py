"""Orchestration graph: allowed specialist edges, depth and cycle checks."""

ALLOWED_EDGES = {
    "orchestrator": {"text_analysis", "legal_retrieval", "doc_writing"},
    "text_analysis": {"legal_retrieval"},
    "doc_writing": {"text_analysis", "legal_retrieval"},
    "legal_retrieval": set(),
}

MAX_AGENT_DEPTH = 2  # orchestrator=0, first specialist=1, nested=2


class OrchestrationError(ValueError):
    """Invalid routing, depth, or cycle."""


def validate_subcall(caller: str, callee: str, depth: int, visited: set) -> None:
    """Raise OrchestrationError if this edge is not allowed from the current stack.

    ``depth`` is the caller's depth. A subcall is only allowed when the callee
    would run at depth <= MAX_AGENT_DEPTH, i.e. caller depth < MAX_AGENT_DEPTH.
    """
    if callee == "orchestrator":
        raise OrchestrationError("specialists cannot call the orchestrator")
    if depth >= MAX_AGENT_DEPTH:
        raise OrchestrationError("任务编排失败：超过最大调用深度")
    allowed = ALLOWED_EDGES.get(caller)
    if allowed is None:
        raise OrchestrationError(f"unknown caller agent: {caller}")
    if callee not in allowed:
        raise OrchestrationError(f"任务编排失败：不允许 {caller} 调用 {callee}")
    if callee in visited:
        raise OrchestrationError("任务编排失败：检测到循环调用")
