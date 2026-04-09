from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .agent_monitor import RockburstAgentMonitor
from .config import AppSettings, get_settings, load_rule_config
from .database import Database
from .models import (
    AlertEnvelope,
    AlertStatus,
    AgentBriefing,
    ApprovalStatus,
    AuditLog,
    DashboardSummary,
    DecisionRequest,
    DispatchRequest,
    ExecutionFeedback,
    ExecutionFeedbackCreate,
    ExecutionStatus,
    IngestCaseResult,
    IngestRequest,
    LoopReviewCloseRequest,
    ReplayStartRequest,
    RecommendedAction,
    ReviewStatus,
    RiskCurrentResponse,
    WorkOrderEnvelope,
)
from .openclaw_workflow_agents import OpenClawWorkflowClient
from .replay import ReplayController
from .risk_engine import RiskEngine
from .time_utils import utc_now
from .workflow import RockburstWorkflow, WorkflowExecutionError


def create_app(settings: AppSettings | None = None) -> FastAPI:
    settings = settings or get_settings()
    rule_config = load_rule_config(settings.rules_path)
    db = Database(settings.db_path)
    db.initialize()
    risk_engine = RiskEngine(rule_config)
    workflow = RockburstWorkflow(db, risk_engine, rule_config.min_confidence, settings=settings)

    app = FastAPI(title="Rockburst Closed-Loop Multi-Agent MVP", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def ingest_events(
        events: list[Any],
        replay_context: dict[str, Any] | None = None,
    ) -> list[IngestCaseResult]:
        grouped: dict[str, list[Any]] = defaultdict(list)
        for event in events:
            grouped[event.area_id].append(event)

        results: list[IngestCaseResult] = []
        for area_id, area_events in grouped.items():
            if replay_context:
                db.update_replay_state(
                    current_batch=replay_context.get("batch_index", 0),
                    current_area_id=area_id,
                    current_mode="ingest",
                    current_phase="dispatching_case",
                    current_summary=f"{area_id} 正在进入工作流",
                )
            try:
                state = await asyncio.to_thread(
                    workflow.run_ingest_case,
                    area_id,
                    area_events,
                    replay_context=replay_context,
                )
            except WorkflowExecutionError as exc:
                _persist_audit_logs(db, exc.audit_logs)
                raise
            _persist_audit_logs(db, state.get("audit_logs", []))
            results.append(
                IngestCaseResult(
                    area_id=area_id,
                    quality_report=state["quality_report"],
                    risk_snapshot=state.get("risk_snapshot"),
                    alert=state.get("alert_state"),
                    work_order=state.get("work_order_state"),
                )
            )
        return results

    replay = ReplayController(settings.scenario_dir, db, ingest_events)
    agent_monitor = RockburstAgentMonitor(
        db=db,
        client=OpenClawWorkflowClient(
            project_root=settings.project_root,
            thinking=settings.openclaw_thinking,
            timeout_seconds=settings.openclaw_timeout_seconds,
        ),
        enabled=settings.agent_monitor_enabled,
        interval_seconds=settings.agent_monitor_interval_seconds,
    )

    app.state.settings = settings
    app.state.rule_config = rule_config
    app.state.db = db
    app.state.workflow = workflow
    app.state.replay = replay
    app.state.agent_monitor = agent_monitor

    @app.on_event("startup")
    async def startup_agent_monitor() -> None:
        await agent_monitor.start()

    @app.on_event("shutdown")
    async def shutdown_agent_monitor() -> None:
        await agent_monitor.stop()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/ingest/microseismic-events")
    async def ingest_microseismic_events(request: IngestRequest) -> dict[str, Any]:
        try:
            cases = await ingest_events(request.events)
        except WorkflowExecutionError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"received": len(request.events), "cases": [case.model_dump(mode="json") for case in cases]}

    @app.post("/replay/start")
    async def start_replay(request: ReplayStartRequest) -> dict[str, Any]:
        try:
            return await replay.start(request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/replay/stop")
    async def stop_replay() -> dict[str, Any]:
        return await replay.stop()

    @app.get("/replay/status")
    async def replay_status() -> dict[str, Any]:
        return replay.status()

    @app.get("/agent/monitor/status")
    async def agent_monitor_status() -> dict[str, Any]:
        return agent_monitor.status()

    @app.get("/replay/scenarios")
    async def replay_scenarios() -> list[dict[str, Any]]:
        return [scenario.model_dump(mode="json") for scenario in replay.list_scenarios()]

    @app.get("/risk/current", response_model=RiskCurrentResponse)
    async def get_current_risk() -> RiskCurrentResponse:
        return RiskCurrentResponse(generated_at=utc_now(), snapshots=db.list_latest_risk_snapshots())

    @app.get("/alerts", response_model=list[AlertEnvelope])
    async def get_alerts() -> list[AlertEnvelope]:
        return db.list_alert_envelopes()

    @app.get("/work-orders", response_model=list[WorkOrderEnvelope])
    async def get_work_orders() -> list[WorkOrderEnvelope]:
        return db.list_work_order_envelopes()

    @app.get("/config/rules")
    async def get_rules() -> dict[str, Any]:
        return rule_config.model_dump(mode="json")

    @app.get("/dashboard/summary", response_model=DashboardSummary)
    async def dashboard_summary() -> DashboardSummary:
        alerts = db.list_alert_envelopes()
        work_orders = db.list_work_order_envelopes()
        latest_risk = db.list_latest_risk_snapshots()
        counts = {
            "areas": len(latest_risk),
            "active_alerts": sum(1 for item in alerts if item.alert.status not in {AlertStatus.CLOSED, AlertStatus.REJECTED}),
            "pending_approval": sum(1 for item in alerts if item.alert.status == AlertStatus.PENDING_APPROVAL),
            "open_work_orders": sum(1 for item in work_orders if item.work_order.execution_status != ExecutionStatus.CLOSED),
            "closed_loops": sum(1 for item in alerts if item.loop_review and item.loop_review.status == ReviewStatus.CLOSED),
        }
        return DashboardSummary(
            generated_at=utc_now(),
            counts=counts,
            risk_by_area=latest_risk,
            recent_audit=db.list_audit_logs(limit=20),
            replay_status=replay.status(),
            agent_monitor=agent_monitor.status(),
        )

    @app.get("/agent/briefing", response_model=AgentBriefing)
    async def agent_briefing() -> AgentBriefing:
        alerts = db.list_alert_envelopes()
        work_orders = db.list_work_order_envelopes()
        latest_risk = db.list_latest_risk_snapshots()
        counts = {
            "areas": len(latest_risk),
            "active_alerts": sum(1 for item in alerts if item.alert.status not in {AlertStatus.CLOSED, AlertStatus.REJECTED}),
            "pending_approval": sum(1 for item in alerts if item.alert.status == AlertStatus.PENDING_APPROVAL),
            "open_work_orders": sum(1 for item in work_orders if item.work_order.execution_status != ExecutionStatus.CLOSED),
            "closed_loops": sum(1 for item in alerts if item.loop_review and item.loop_review.status == ReviewStatus.CLOSED),
        }
        return _build_agent_briefing(
            alerts=alerts,
            work_orders=work_orders,
            counts=counts,
            replay_state=replay.status(),
            agent_monitor_state=agent_monitor.status(),
        )

    @app.post("/alerts/{alert_id}/approve", response_model=AlertEnvelope)
    async def approve_alert(alert_id: str, request: DecisionRequest) -> AlertEnvelope:
        try:
            alert = db.update_alert_status(alert_id, AlertStatus.APPROVED.value)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        work_order = db.find_work_order_by_alert(alert_id)
        if work_order:
            db.update_work_order_approval(work_order.workorder_id, ApprovalStatus.APPROVED.value)
        db.create_audit_log(
            AuditLog(
                entity_type="alert",
                entity_id=alert_id,
                stage=AlertStatus.APPROVED.value,
                actor=request.actor,
                action="alert_approved",
                payload={"note": request.note},
                ts=utc_now(),
            )
        )
        return _get_alert_envelope(db, alert_id)

    @app.post("/alerts/{alert_id}/reject", response_model=AlertEnvelope)
    async def reject_alert(alert_id: str, request: DecisionRequest) -> AlertEnvelope:
        try:
            alert = db.update_alert_status(alert_id, AlertStatus.REJECTED.value, message=request.note or None)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        work_order = db.find_work_order_by_alert(alert_id)
        if work_order:
            db.update_work_order_approval(work_order.workorder_id, ApprovalStatus.REJECTED.value)
            db.mark_work_order_execution(work_order.workorder_id, ExecutionStatus.CLOSED.value)
        db.create_audit_log(
            AuditLog(
                entity_type="alert",
                entity_id=alert.alert_id,
                stage=AlertStatus.REJECTED.value,
                actor=request.actor,
                action="alert_rejected",
                payload={"note": request.note},
                ts=utc_now(),
            )
        )
        return _get_alert_envelope(db, alert_id)

    @app.post("/work-orders/{workorder_id}/dispatch", response_model=WorkOrderEnvelope)
    async def dispatch_work_order(workorder_id: str, request: DispatchRequest) -> WorkOrderEnvelope:
        try:
            work_order = db.get_work_order(workorder_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if work_order.approval_status != ApprovalStatus.APPROVED:
            raise HTTPException(status_code=409, detail="Work order must be approved before dispatch")
        updated = db.dispatch_work_order(workorder_id, request.assignee, request.due_at)
        db.update_alert_status(updated.alert_id, AlertStatus.DISPATCHED.value)
        db.create_audit_log(
            AuditLog(
                entity_type="work_order",
                entity_id=workorder_id,
                stage=AlertStatus.DISPATCHED.value,
                actor=request.actor,
                action="work_order_dispatched",
                payload={"assignee": request.assignee, "dispatch_note": request.dispatch_note},
                ts=utc_now(),
            )
        )
        return _get_work_order_envelope(db, workorder_id)

    @app.post("/work-orders/{workorder_id}/feedback", response_model=WorkOrderEnvelope)
    async def submit_feedback(workorder_id: str, request: ExecutionFeedbackCreate) -> WorkOrderEnvelope:
        try:
            work_order = db.get_work_order(workorder_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        feedback = ExecutionFeedback(
            feedback_id=f"fb-{uuid4().hex[:12]}",
            workorder_id=workorder_id,
            ts=utc_now(),
            result=request.result,
            notes=request.notes,
            attachments=request.attachments,
        )
        db.add_feedback(feedback)
        execution_status = _feedback_result_to_status(request.result)
        updated_work_order = db.mark_work_order_execution(workorder_id, execution_status.value)
        alert = db.update_alert_status(updated_work_order.alert_id, AlertStatus.EXECUTED.value)
        try:
            state = await asyncio.to_thread(workflow.run_review_case, alert, updated_work_order, feedback)
        except WorkflowExecutionError as exc:
            _persist_audit_logs(db, exc.audit_logs)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        _persist_audit_logs(db, state.get("audit_logs", []))
        db.create_audit_log(
            AuditLog(
                entity_type="work_order",
                entity_id=workorder_id,
                stage=AlertStatus.EXECUTED.value,
                actor=request.actor,
                action="execution_feedback_submitted",
                payload={"result": request.result, "notes": request.notes},
                ts=utc_now(),
            )
        )
        return _get_work_order_envelope(db, workorder_id)

    @app.post("/loop-reviews/{review_id}/close", response_model=AlertEnvelope)
    async def close_loop_review(review_id: str, request: LoopReviewCloseRequest) -> AlertEnvelope:
        try:
            review = db.close_loop_review(review_id, request.closure_note)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        alert = db.get_alert(review.alert_id)
        db.update_alert_status(alert.alert_id, AlertStatus.REVIEWED.value)
        db.create_audit_log(
            AuditLog(
                entity_type="alert",
                entity_id=alert.alert_id,
                stage=AlertStatus.REVIEWED.value,
                actor=request.actor,
                action="loop_review_completed",
                payload={"closure_note": request.closure_note},
                ts=utc_now(),
            )
        )
        db.update_alert_status(alert.alert_id, AlertStatus.CLOSED.value)
        work_order = db.find_work_order_by_alert(alert.alert_id)
        if work_order:
            db.mark_work_order_execution(work_order.workorder_id, ExecutionStatus.CLOSED.value)
        db.create_audit_log(
            AuditLog(
                entity_type="loop_review",
                entity_id=review.review_id,
                stage=AlertStatus.CLOSED.value,
                actor=request.actor,
                action="loop_closed",
                payload={"closure_note": request.closure_note},
                ts=utc_now(),
            )
        )
        return _get_alert_envelope(db, alert.alert_id)

    return app


def _persist_audit_logs(db: Database, logs: list[AuditLog]) -> None:
    for log in logs:
        db.create_audit_log(log)


def _feedback_result_to_status(result: str) -> ExecutionStatus:
    mapping = {
        "completed": ExecutionStatus.EXECUTED,
        "risk_not_reduced": ExecutionStatus.EXECUTED,
        "timed_out": ExecutionStatus.TIMED_OUT,
        "blocked": ExecutionStatus.BLOCKED,
    }
    return mapping[result]


def _get_alert_envelope(db: Database, alert_id: str) -> AlertEnvelope:
    for item in db.list_alert_envelopes():
        if item.alert.alert_id == alert_id:
            return item
    raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")


def _get_work_order_envelope(db: Database, workorder_id: str) -> WorkOrderEnvelope:
    for item in db.list_work_order_envelopes():
        if item.work_order.workorder_id == workorder_id:
            return item
    raise HTTPException(status_code=404, detail=f"Work order {workorder_id} not found")


def _build_agent_briefing(
    *,
    alerts: list[AlertEnvelope],
    work_orders: list[WorkOrderEnvelope],
    counts: dict[str, int],
    replay_state: dict[str, Any],
    agent_monitor_state: dict[str, Any],
) -> AgentBriefing:
    priorities: list[str] = []
    recommended_actions: list[RecommendedAction] = []

    pending_alerts = sorted(
        (item for item in alerts if item.alert.status == AlertStatus.PENDING_APPROVAL),
        key=lambda item: item.alert.level.value,
        reverse=True,
    )
    approved_ready_orders = [
        item
        for item in work_orders
        if item.work_order.approval_status == ApprovalStatus.APPROVED
        and item.work_order.execution_status == ExecutionStatus.READY
    ]
    open_reviews = [item for item in alerts if item.loop_review and item.loop_review.status == ReviewStatus.OPEN]
    active_high_risk = [item for item in alerts if item.alert.level.value in {"L3", "L4"} and item.alert.status != AlertStatus.CLOSED]

    if pending_alerts:
        top_pending = pending_alerts[0]
        priorities.append(
            f"存在 {len(pending_alerts)} 条待审批告警，最高等级为 {top_pending.alert.level.value}，区域 {top_pending.alert.area_id}。"
        )
        recommended_actions.append(
            RecommendedAction(
                action_type="review_alert",
                target_type="alert",
                target_id=top_pending.alert.alert_id,
                reason="高等级告警仍待人工审批，闭环尚未继续推进。",
                requires_confirmation=True,
            )
        )

    if approved_ready_orders:
        next_work_order = approved_ready_orders[0]
        priorities.append(f"存在 {len(approved_ready_orders)} 张已批准但未派发工单。")
        recommended_actions.append(
            RecommendedAction(
                action_type="dispatch_work_order",
                target_type="work_order",
                target_id=next_work_order.work_order.workorder_id,
                reason="工单已获批准，但尚未派发到执行人。",
                requires_confirmation=True,
            )
        )

    if open_reviews:
        next_review = open_reviews[0]
        priorities.append(f"存在 {len(open_reviews)} 条执行后待关环复核事项。")
        if next_review.loop_review is not None:
            recommended_actions.append(
                RecommendedAction(
                    action_type="close_review",
                    target_type="loop_review",
                    target_id=next_review.loop_review.review_id,
                    reason="执行反馈已形成复核结果，等待最终关环确认。",
                    requires_confirmation=True,
                )
            )

    if replay_state.get("status") == "idle" and not active_high_risk:
        priorities.append("当前没有高等级活动告警，可启动模拟回放或注入一批演示事件。")
        recommended_actions.append(
            RecommendedAction(
                action_type="start_demo_replay",
                target_type="replay",
                reason="系统处于空闲态，适合演示默认风险升级流程。",
                requires_confirmation=False,
            )
        )

    current_role_key = replay_state.get("current_role_key")
    current_area_id = replay_state.get("current_area_id")
    if replay_state.get("status") == "running" and current_role_key and current_area_id:
        priorities.append(
            f"回放正在区域 {current_area_id} 执行角色 {current_role_key}，角色进度 {replay_state.get('completed_role_steps', 0)}/{replay_state.get('total_role_steps', 0)}。"
        )

    if not priorities:
        priorities.append("当前系统运行平稳，没有待审批、待派发或待关环的关键事项。")

    return AgentBriefing(
        generated_at=utc_now(),
        headline=priorities[0],
        priorities=priorities,
        recommended_actions=recommended_actions,
        counts=counts,
        replay_status=replay_state,
        agent_monitor=agent_monitor_state,
    )


app = create_app()
