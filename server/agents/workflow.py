"""Real workflow events emitted at the actual call site (not a preview)."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Callable, Dict, List, Optional

_NOOP_SENTINEL = object()
_current: ContextVar[Any] = ContextVar("legalmind_workflow", default=None)


class WorkflowTracer:
    def __init__(self, on_event: Optional[Callable[[Dict[str, str]], None]] = None):
        self.events: List[Dict[str, str]] = []
        self.on_event = on_event

    def emit(self, kind: str, ident: str, name: str, status: str = "done") -> Dict[str, str]:
        item = {
            "kind": str(kind),
            "id": str(ident or ""),
            "name": str(name or ident or ""),
            "status": status,
        }
        if not item["id"]:
            return item
        self.events.append(item)
        if self.on_event:
            try:
                self.on_event(dict(item))
            except Exception as exc:
                print(f"[workflow] on_event failed: {exc}")
        return item


class _NoopTracer:
    events: List[Dict[str, str]] = []

    def emit(self, *args, **kwargs) -> Dict[str, str]:
        return {}


_NOOP = _NoopTracer()


def bind_workflow(tracer: WorkflowTracer):
    return _current.set(tracer)


def reset_workflow(token) -> None:
    _current.reset(token)


def get_workflow() -> Any:
    return _current.get() or _NOOP


def emit_step(kind: str, ident: str, name: str, status: str = "done") -> None:
    get_workflow().emit(kind, ident, name, status)
