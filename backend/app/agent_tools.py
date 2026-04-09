from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import uuid4

from .agent_runtime import ToolRegistry, ToolResult
from .database import Database
from .models import (
    Alert,
    AlertStatus,
    ApprovalStatus,
    CaseContext,
    ExecutionStatus,
    LoopReview,
    MicroseismicEvent,
    QualityReport,
    QualityStatus,
    ReviewStatus,
    RiskLevel,
    WorkOrder,
)
from .risk_engine import RiskEngine
from .time_utils import utc_now


@dataclass(frozen=True)
class WorkflowServices:
    db: Database
    risk_engine: RiskEngine
    min_confidence: float


def build_tool_registry(services: WorkflowServices) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register("order_event_batch", lambda state: order_event_batch(state))
    registry.register("quality_check_events", lambda state: quality_check_events(state, services=services))
    registry.register("assess_risk_snapshot", lambda state: assess_risk_snapshot(state, services=services))
    registry.register("prepare_alert", lambda state: prepare_alert(state, services=services))
    registry.register("resolve_work_order_template", lambda state: resolve_work_order_template(state, services=services))
    registry.register("draft_work_order", lambda state: draft_work_order(state))
    registry.register("persist_work_order", lambda state: persist_work_order(state, services=services))
    registry.register("evaluate_feedback_outcome", lambda state: evaluate_feedback_outcome(state, services=services))
    return registry


def order_event_batch(state: CaseContext) -> ToolResult:
    ordered = sorted(state.get("event_batch", []), key=lambda event: event.ts)
    return ToolResult(
        updates={"event_batch": ordered},
        summary=f"按时间顺序整理了 {len(ordered)} 条事件。",
        payload={"event_count": len(ordered)},
    )


def quality_check_events(state: CaseContext, *, services: WorkflowServices) -> ToolResult:
    seen_event_ids: set[str] = set()
    valid_events: list[MicroseismicEvent] = []
    dropped: list[str] = []
    reasons: list[str] = []

    for event in state.get("event_batch", []):
        if event.event_id in seen_event_ids:
            dropped.append(event.event_id)
            reasons.append(f"{event.event_id} 因重复事件被剔除")
            continue

        seen_event_ids.add(event.event_id)
        if event.confidence < services.min_confidence:
            dropped.append(event.event_id)
            reasons.append(f"{event.event_id} 因置信度 {event.confidence:.2f} 低于阈值被剔除")
            continue

        services.db.upsert_event(event.model_dump(mode="json"), QualityStatus.ACCEPTED.value)
        valid_events.append(event)

    quality_report = QualityReport(
        area_id=state["area_id"],
        received=len(state.get("event_batch", [])),
        accepted=len(valid_events),
        dropped=len(dropped),
        dropped_event_ids=dropped,
        reasons=reasons,
    )
    return ToolResult(
        updates={"event_batch": valid_events, "quality_report": quality_report},
        summary=f"完成数据质检，保留 {len(valid_events)} 条，剔除 {len(dropped)} 条。",
        payload=quality_report.model_dump(mode="json"),
    )


def assess_risk_snapshot(state: CaseContext, *, services: WorkflowServices) -> ToolResult:
    events = state.get("event_batch", [])
    snapshot = services.risk_engine.assess(state["area_id"], events)
    services.db.create_risk_snapshot(snapshot)
    return ToolResult(
        updates={"risk_snapshot": snapshot},
        summary=f"生成 {snapshot.level.value} 风险快照，综合评分 {snapshot.score:.1f}。",
        payload={
            "snapshot_id": snapshot.snapshot_id,
            "level": snapshot.level.value,
            "score": snapshot.score,
        },
    )


def prepare_alert(state: CaseContext, *, services: WorkflowServices) -> ToolResult:
    snapshot = state["risk_snapshot"]
    message = (
        f"区域 {snapshot.area_id} 触发 {snapshot.level.value} 级风险告警，"
        f"综合评分为 {snapshot.score:.1f}。请确认下一步处置动作。"
    )
    alert_status = AlertStatus.ALERTED if snapshot.level == RiskLevel.L2 else AlertStatus.PENDING_APPROVAL
    now = utc_now()
    alert = Alert(
        alert_id=f"alert-{uuid4().hex[:12]}",
        risk_snapshot_id=snapshot.snapshot_id,
        area_id=snapshot.area_id,
        level=snapshot.level,
        status=alert_status,
        message=message,
        suggested_actions=services.risk_engine.suggested_actions(snapshot.level),
        created_at=now,
        updated_at=now,
    )
    services.db.create_alert(alert)
    return ToolResult(
        updates={"alert_state": alert},
        summary=f"生成 {alert.level.value} 告警并写入数据库。",
        payload={"alert_id": alert.alert_id, "status": alert.status.value, "level": alert.level.value},
    )


def resolve_work_order_template(state: CaseContext, *, services: WorkflowServices) -> ToolResult:
    alert = state["alert_state"]
    template = services.risk_engine.work_order_template(alert.level)
    resolved_template = template or {
        "type": "现场检查",
        "priority": "high",
        "due_in_hours": 4,
        "checklist": [],
    }
    return ToolResult(
        updates={"resolved_work_order_template": resolved_template},
        summary=f"已解析 {alert.level.value} 级工单模板。",
        payload={
            "type": resolved_template["type"],
            "priority": resolved_template["priority"],
            "due_in_hours": resolved_template["due_in_hours"],
        },
    )


def draft_work_order(state: CaseContext) -> ToolResult:
    alert = state["alert_state"]
    template = state.get("resolved_work_order_template") or {
        "type": "现场检查",
        "priority": "high",
        "due_in_hours": 4,
        "checklist": [],
    }
    now = utc_now()
    due_at = now + timedelta(hours=int(template["due_in_hours"]))
    work_order = WorkOrder(
        workorder_id=f"wo-{uuid4().hex[:12]}",
        alert_id=alert.alert_id,
        type=str(template["type"]),
        priority=str(template["priority"]),
        approval_status=ApprovalStatus.PENDING,
        execution_status=ExecutionStatus.READY,
        due_at=due_at,
        details={
            "checklist": list(template.get("checklist", [])),
            "suggested_actions": alert.suggested_actions,
        },
        created_at=now,
        updated_at=now,
    )
    return ToolResult(
        updates={"work_order_state": work_order},
        summary=f"已起草工单 {work_order.type}，要求 {template['due_in_hours']} 小时内完成。",
        payload={"workorder_id": work_order.workorder_id, "type": work_order.type, "priority": work_order.priority},
    )


def persist_work_order(state: CaseContext, *, services: WorkflowServices) -> ToolResult:
    work_order = state.get("work_order_state")
    if work_order is None:
        return ToolResult(summary="当前没有需要持久化的工单。")

    services.db.create_work_order(work_order)
    return ToolResult(
        updates={"work_order_state": work_order},
        summary=f"工单 {work_order.workorder_id} 已持久化。",
        payload={"workorder_id": work_order.workorder_id},
    )


def evaluate_feedback_outcome(state: CaseContext, *, services: WorkflowServices) -> ToolResult:
    alert = state["alert_state"]
    feedback = state["execution_feedback"]

    if feedback.result == "completed":
        effectiveness = "effective"
        residual_risk = "medium-low"
        followup_action = "继续开展高频巡查，并持续观察未来两小时的微震变化趋势。"
    elif feedback.result == "timed_out":
        effectiveness = "not_completed"
        residual_risk = "high"
        followup_action = "升级至当班负责人，并以更严格的到场时限重新派发。"
    elif feedback.result == "blocked":
        effectiveness = "blocked"
        residual_risk = "high"
        followup_action = "先恢复现场资源和通道条件，再重新执行任务，同时保持区域限行。"
    else:
        effectiveness = "risk_not_reduced"
        residual_risk = "high"
        followup_action = "生成第二轮处置建议，补充支护复核与卸压解危评估。"

    review = LoopReview(
        review_id=f"review-{uuid4().hex[:12]}",
        alert_id=alert.alert_id,
        effectiveness=effectiveness,
        residual_risk=residual_risk,
        followup_action=followup_action,
        status=ReviewStatus.OPEN,
        created_at=utc_now(),
    )
    services.db.create_loop_review(review)
    return ToolResult(
        updates={"loop_review": review},
        summary=f"已完成执行效果评估，复核状态为 {review.status.value}。",
        payload={"review_id": review.review_id, "effectiveness": review.effectiveness, "residual_risk": review.residual_risk},
    )
