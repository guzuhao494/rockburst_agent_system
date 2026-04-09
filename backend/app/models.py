from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class AlertStatus(str, Enum):
    OBSERVED = "Observed"
    ASSESSED = "Assessed"
    ALERTED = "Alerted"
    PENDING_APPROVAL = "PendingApproval"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    DISPATCHED = "Dispatched"
    EXECUTED = "Executed"
    REVIEWED = "Reviewed"
    CLOSED = "Closed"


class ApprovalStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ExecutionStatus(str, Enum):
    NOT_CREATED = "not_created"
    READY = "ready"
    DISPATCHED = "dispatched"
    EXECUTED = "executed"
    TIMED_OUT = "timed_out"
    BLOCKED = "blocked"
    CLOSED = "closed"


class ReviewStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class QualityStatus(str, Enum):
    ACCEPTED = "accepted"
    DROPPED = "dropped"


class ReplayStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


class MicroseismicEvent(BaseModel):
    event_id: str
    ts: datetime
    area_id: str
    energy: float
    magnitude: float
    x: float
    y: float
    z: float
    confidence: float = Field(ge=0.0, le=1.0)
    source: str


class RiskSnapshot(BaseModel):
    snapshot_id: str
    area_id: str
    ts: datetime
    score: float
    level: RiskLevel
    triggered_rules: list[str]
    explanation: str
    contributing_factors: dict[str, float] = Field(default_factory=dict)


class Alert(BaseModel):
    alert_id: str
    risk_snapshot_id: str
    area_id: str
    level: RiskLevel
    status: AlertStatus
    message: str
    suggested_actions: list[str]
    created_at: datetime
    updated_at: datetime


class WorkOrder(BaseModel):
    workorder_id: str
    alert_id: str
    type: str
    assignee: str | None = None
    priority: str
    approval_status: ApprovalStatus
    execution_status: ExecutionStatus
    due_at: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ExecutionFeedback(BaseModel):
    feedback_id: str
    workorder_id: str
    ts: datetime
    result: str
    notes: str
    attachments: list[str] = Field(default_factory=list)


class LoopReview(BaseModel):
    review_id: str
    alert_id: str
    effectiveness: str
    residual_risk: str
    followup_action: str
    status: ReviewStatus = ReviewStatus.OPEN
    created_at: datetime
    closed_at: datetime | None = None
    closure_note: str | None = None


class AuditLog(BaseModel):
    log_id: int | None = None
    entity_type: str
    entity_id: str
    stage: str
    actor: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: datetime


class IngestRequest(BaseModel):
    events: list[MicroseismicEvent]


class ReplayStartRequest(BaseModel):
    scenario_name: str
    interval_ms: int = Field(default=800, ge=100, le=10_000)
    loop: bool = False


class DecisionRequest(BaseModel):
    actor: str
    note: str = ""


class DispatchRequest(BaseModel):
    actor: str
    assignee: str
    due_at: datetime | None = None
    dispatch_note: str = ""


class ExecutionFeedbackCreate(BaseModel):
    actor: str
    result: Literal["completed", "timed_out", "blocked", "risk_not_reduced"]
    notes: str
    attachments: list[str] = Field(default_factory=list)


class LoopReviewCloseRequest(BaseModel):
    actor: str
    closure_note: str


class AlertEnvelope(BaseModel):
    alert: Alert
    risk_snapshot: RiskSnapshot
    work_order: WorkOrder | None = None
    latest_feedback: ExecutionFeedback | None = None
    loop_review: LoopReview | None = None
    audit_logs: list[AuditLog] = Field(default_factory=list)


class WorkOrderEnvelope(BaseModel):
    work_order: WorkOrder
    alert: Alert
    risk_snapshot: RiskSnapshot | None = None
    feedbacks: list[ExecutionFeedback] = Field(default_factory=list)
    loop_review: LoopReview | None = None


class DashboardSummary(BaseModel):
    generated_at: datetime
    counts: dict[str, int]
    risk_by_area: list[RiskSnapshot]
    recent_audit: list[AuditLog]
    replay_status: dict[str, Any]


class RecommendedAction(BaseModel):
    action_type: str
    target_type: str
    target_id: str | None = None
    reason: str
    requires_confirmation: bool = True


class AgentBriefing(BaseModel):
    generated_at: datetime
    headline: str
    priorities: list[str] = Field(default_factory=list)
    recommended_actions: list[RecommendedAction] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    replay_status: dict[str, Any] = Field(default_factory=dict)


class ScenarioMetadata(BaseModel):
    name: str
    description: str
    batches: int
    areas: list[str]


class QualityReport(BaseModel):
    area_id: str
    received: int
    accepted: int
    dropped: int
    dropped_event_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class IngestCaseResult(BaseModel):
    area_id: str
    quality_report: QualityReport
    risk_snapshot: RiskSnapshot | None = None
    alert: Alert | None = None
    work_order: WorkOrder | None = None


class RiskCurrentResponse(BaseModel):
    generated_at: datetime
    snapshots: list[RiskSnapshot]


class CaseContext(TypedDict, total=False):
    mode: str
    area_id: str
    event_batch: list[MicroseismicEvent]
    quality_report: QualityReport
    risk_snapshot: RiskSnapshot | None
    alert_state: Alert | None
    work_order_state: WorkOrder | None
    resolved_work_order_template: dict[str, Any]
    operator_decisions: dict[str, Any]
    execution_feedback: ExecutionFeedback | None
    loop_review: LoopReview | None
    audit_logs: list[AuditLog]
