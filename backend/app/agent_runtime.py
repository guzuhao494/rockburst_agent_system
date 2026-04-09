from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

from .models import AuditLog, CaseContext


@dataclass
class ToolResult:
    updates: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


ToolHandler = Callable[..., ToolResult]
AuditFactory = Callable[..., AuditLog]


class ToolRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, name: str, handler: ToolHandler) -> None:
        self._handlers[name] = handler

    def invoke(self, name: str, state: CaseContext, **kwargs: Any) -> ToolResult:
        if name not in self._handlers:
            raise KeyError(f"Tool {name} is not registered")
        return self._handlers[name](state=state, **kwargs)


class WorkflowAgent:
    def __init__(self, *, actor: str, registry: ToolRegistry, audit_factory: AuditFactory) -> None:
        self.actor = actor
        self.registry = registry
        self.audit_factory = audit_factory

    def append_audit(
        self,
        state: CaseContext,
        *,
        entity_type: str,
        entity_id: str,
        stage: str,
        action: str,
        payload: dict[str, Any],
    ) -> CaseContext:
        log = self.audit_factory(
            entity_type=entity_type,
            entity_id=entity_id,
            stage=stage,
            actor=self.actor,
            action=action,
            payload=payload,
        )
        return merge_case_state(state, {"audit_logs": [*state.get("audit_logs", []), log]})

    def invoke_tool(self, state: CaseContext, *, tool_name: str, stage: str, **kwargs: Any) -> tuple[CaseContext, ToolResult]:
        result = self.registry.invoke(tool_name, state=state, **kwargs)
        tool_log = self.audit_factory(
            entity_type="tool",
            entity_id=f"tool-{uuid4().hex[:12]}",
            stage=stage,
            actor=self.actor,
            action="tool_completed",
            payload={
                "tool_name": tool_name,
                "summary": result.summary,
                **result.payload,
            },
        )
        next_state = merge_case_state(state, result.updates)
        next_state["audit_logs"] = [*state.get("audit_logs", []), tool_log]
        return next_state, result


def merge_case_state(state: CaseContext, updates: dict[str, Any]) -> CaseContext:
    merged = dict(state)
    merged.update(updates)
    return merged  # type: ignore[return-value]
