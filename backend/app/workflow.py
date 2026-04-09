from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph

from .agent_tools import WorkflowServices, build_tool_registry
from .config import AppSettings, get_settings
from .database import Database
from .models import (
    Alert,
    AlertStatus,
    AuditLog,
    CaseContext,
    ExecutionFeedback,
    MicroseismicEvent,
    ReplayStatus,
    RiskLevel,
    WorkOrder,
)
from .openclaw_workflow_agents import (
    OpenClawActionPlanningAgent,
    OpenClawAlertExplanationAgent,
    OpenClawDataQualityAgent,
    OpenClawEffectivenessVerificationAgent,
    OpenClawIngestIntakeAgent,
    OpenClawRiskAssessmentAgent,
    OpenClawSupervisorAgent,
    OpenClawSupervisorFinalizeAgent,
    OpenClawWorkOrderCoordinationAgent,
    OpenClawWorkflowClient,
)
from .risk_engine import RiskEngine
from .time_utils import utc_now
from .workflow_agents import (
    ActionPlanningAgent,
    AlertExplanationAgent,
    DataQualityAgent,
    EffectivenessVerificationAgent,
    IngestIntakeAgent,
    RiskAssessmentAgent,
    SupervisorAgent,
    SupervisorFinalizeAgent,
    WorkOrderCoordinationAgent,
)


AGENT_ORDER = [
    "supervisor",
    "ingest_intake",
    "data_quality",
    "risk_assessment",
    "alert_explanation",
    "action_planning",
    "work_order_coordination",
    "effectiveness_verification",
    "supervisor_finalize",
]

ROLE_STEP_INDEX = {role_key: index for index, role_key in enumerate(AGENT_ORDER, start=1)}


@dataclass
class WorkflowExecutionError(RuntimeError):
    message: str
    role_key: str
    role_id: str
    mode: str
    area_id: str
    decision_stage: str
    audit_logs: list[AuditLog]

    def __str__(self) -> str:
        return self.message


class RockburstWorkflow:
    def __init__(
        self,
        db: Database,
        risk_engine: RiskEngine,
        min_confidence: float,
        *,
        settings: AppSettings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.db = db
        self.risk_engine = risk_engine
        self.min_confidence = min_confidence
        self.services = WorkflowServices(db=db, risk_engine=risk_engine, min_confidence=min_confidence)
        self.tool_registry = build_tool_registry(self.services)
        self.agents = self._build_agents()
        self.graph = self._build_graph()

    def _build_agents(self) -> dict[str, Any]:
        shared = {"registry": self.tool_registry, "audit_factory": self._audit}
        runtime = self.settings.workflow_runtime
        if runtime == "python":
            return {
                "supervisor": SupervisorAgent(actor="SupervisorAgent", **shared),
                "ingest_intake": IngestIntakeAgent(actor="IntakeAgent", **shared),
                "data_quality": DataQualityAgent(actor="QualityAgent", **shared),
                "risk_assessment": RiskAssessmentAgent(actor="RiskAssessmentAgent", **shared),
                "alert_explanation": AlertExplanationAgent(actor="AlertExplanationAgent", **shared),
                "action_planning": ActionPlanningAgent(actor="ActionPlanningAgent", **shared),
                "work_order_coordination": WorkOrderCoordinationAgent(actor="WorkOrderCoordinationAgent", **shared),
                "effectiveness_verification": EffectivenessVerificationAgent(actor="EffectivenessVerificationAgent", **shared),
                "supervisor_finalize": SupervisorFinalizeAgent(actor="SupervisorAgent", **shared),
            }

        if runtime == "openclaw":
            client = OpenClawWorkflowClient(
                project_root=self.settings.project_root,
                thinking=self.settings.openclaw_thinking,
                timeout_seconds=self.settings.openclaw_timeout_seconds,
            )
            return {
                "supervisor": OpenClawSupervisorAgent(
                    actor="SupervisorAgent",
                    role_name="监督编排智能体",
                    role_id="rockburst-supervisor",
                    client=client,
                    **shared,
                ),
                "ingest_intake": OpenClawIngestIntakeAgent(
                    actor="IntakeAgent",
                    role_name="采集接入智能体",
                    role_id="rockburst-ingest-intake",
                    client=client,
                    **shared,
                ),
                "data_quality": OpenClawDataQualityAgent(
                    actor="QualityAgent",
                    role_name="数据质检智能体",
                    role_id="rockburst-data-quality",
                    client=client,
                    **shared,
                ),
                "risk_assessment": OpenClawRiskAssessmentAgent(
                    actor="RiskAssessmentAgent",
                    role_name="风险评估智能体",
                    role_id="rockburst-risk-assessment",
                    client=client,
                    **shared,
                ),
                "alert_explanation": OpenClawAlertExplanationAgent(
                    actor="AlertExplanationAgent",
                    role_name="告警解释智能体",
                    role_id="rockburst-alert-explanation",
                    client=client,
                    **shared,
                ),
                "action_planning": OpenClawActionPlanningAgent(
                    actor="ActionPlanningAgent",
                    role_name="处置规划智能体",
                    role_id="rockburst-action-planning",
                    client=client,
                    **shared,
                ),
                "work_order_coordination": OpenClawWorkOrderCoordinationAgent(
                    actor="WorkOrderCoordinationAgent",
                    role_name="工单协调智能体",
                    role_id="rockburst-work-order-coordination",
                    client=client,
                    **shared,
                ),
                "effectiveness_verification": OpenClawEffectivenessVerificationAgent(
                    actor="EffectivenessVerificationAgent",
                    role_name="效果验证智能体",
                    role_id="rockburst-effectiveness-verification",
                    client=client,
                    **shared,
                ),
                "supervisor_finalize": OpenClawSupervisorFinalizeAgent(
                    actor="SupervisorAgent",
                    role_name="监督收尾智能体",
                    role_id="rockburst-supervisor-finalize",
                    client=client,
                    **shared,
                ),
            }

        raise ValueError(f"Unsupported workflow runtime: {runtime}")

    def _build_graph(self):
        graph = StateGraph(CaseContext)
        for role_key in AGENT_ORDER:
            graph.add_node(role_key, lambda state, current_role=role_key: self._run_agent_step(current_role, state))

        graph.add_edge(START, AGENT_ORDER[0])
        for current_role, next_role in zip(AGENT_ORDER, AGENT_ORDER[1:]):
            graph.add_edge(current_role, next_role)
        graph.add_edge(AGENT_ORDER[-1], END)
        return graph.compile()

    def run_ingest_case(
        self,
        area_id: str,
        events: list[MicroseismicEvent],
        *,
        replay_context: dict[str, Any] | None = None,
    ) -> CaseContext:
        initial_state: CaseContext = {
            "mode": "ingest",
            "area_id": area_id,
            "event_batch": events,
            "operator_decisions": {},
            "audit_logs": [],
            "replay_progress": replay_context,
        }
        return self.graph.invoke(initial_state)

    def run_review_case(self, alert: Alert, work_order: WorkOrder, feedback: ExecutionFeedback) -> CaseContext:
        initial_state: CaseContext = {
            "mode": "review",
            "area_id": alert.area_id,
            "event_batch": [],
            "alert_state": alert,
            "work_order_state": work_order,
            "execution_feedback": feedback,
            "operator_decisions": {},
            "audit_logs": [],
            "replay_progress": None,
        }
        return self.graph.invoke(initial_state)

    def _run_agent_step(self, role_key: str, state: CaseContext) -> CaseContext:
        agent = self.agents[role_key]
        self._update_replay_role_state(role_key=role_key, state=state, phase="running_role", completed_offset=1)
        try:
            next_state = agent.run(state)
            self._update_replay_role_state(role_key=role_key, state=state, phase="role_completed", completed_offset=0)
            return next_state
        except WorkflowExecutionError:
            raise
        except Exception as exc:
            decision_stage = self._decision_stage(role_key, state)
            role_id = getattr(agent, "role_id", role_key)
            runtime = self.settings.workflow_runtime
            base_payload = {
                "role_id": role_id,
                "decision_stage": decision_stage,
                "error": str(exc),
                "implementation": runtime,
            }
            failed_logs = [
                self._audit(
                    entity_type="workflow",
                    entity_id=f"{state['mode']}:{state['area_id']}",
                    stage=decision_stage,
                    actor=getattr(agent, "actor", "WorkflowAgent"),
                    action="agent_decision_failed",
                    payload=base_payload,
                ),
                self._audit(
                    entity_type="workflow",
                    entity_id=f"{state['mode']}:{state['area_id']}",
                    stage="Supervisor",
                    actor="SupervisorAgent",
                    action="workflow_failed",
                    payload=base_payload,
                ),
            ]
            self._mark_replay_failed(role_key=role_key, role_id=role_id, state=state, error_message=str(exc))
            raise WorkflowExecutionError(
                message=(
                    f"Workflow failed in {role_id} for {state['mode']} case "
                    f"{state['area_id']}: {exc}"
                ),
                role_key=role_key,
                role_id=role_id,
                mode=state["mode"],
                area_id=state["area_id"],
                decision_stage=decision_stage,
                audit_logs=[*state.get("audit_logs", []), *failed_logs],
            ) from exc

    def _update_replay_role_state(
        self,
        *,
        role_key: str,
        state: CaseContext,
        phase: str,
        completed_offset: int,
    ) -> None:
        replay_context = state.get("replay_progress")
        if not replay_context:
            return
        role_step = ROLE_STEP_INDEX[role_key]
        completed_role_steps = max(role_step - completed_offset, 0)
        role_id = getattr(self.agents[role_key], "role_id", role_key)
        self.db.update_replay_state(
            current_batch=replay_context.get("batch_index", 0),
            current_area_id=state["area_id"],
            current_mode=state["mode"],
            current_phase=phase,
            current_role_key=role_key,
            current_role_id=role_id,
            current_role_step=role_step,
            total_role_steps=len(AGENT_ORDER),
            completed_role_steps=completed_role_steps,
            current_summary=f"{state['area_id']}:{role_key}",
        )

    def _mark_replay_failed(
        self,
        *,
        role_key: str,
        role_id: str,
        state: CaseContext,
        error_message: str,
    ) -> None:
        replay_context = state.get("replay_progress")
        if not replay_context:
            return
        role_step = ROLE_STEP_INDEX[role_key]
        self.db.update_replay_state(
            status=ReplayStatus.FAILED,
            current_batch=replay_context.get("batch_index", 0),
            current_area_id=state["area_id"],
            current_mode=state["mode"],
            current_phase="failed",
            current_role_key=role_key,
            current_role_id=role_id,
            current_role_step=role_step,
            total_role_steps=len(AGENT_ORDER),
            completed_role_steps=max(role_step - 1, 0),
            current_summary=f"{state['area_id']}:{role_key}",
            last_error=error_message,
        )

    def _decision_stage(self, role_key: str, state: CaseContext) -> str:
        if role_key in {"supervisor", "supervisor_finalize"}:
            return "Supervisor"
        if role_key in {"ingest_intake", "data_quality"}:
            return AlertStatus.OBSERVED.value
        if role_key == "risk_assessment":
            return AlertStatus.ASSESSED.value
        if role_key == "alert_explanation":
            snapshot = state.get("risk_snapshot")
            level = snapshot.level if snapshot is not None else RiskLevel.L2
            return AlertStatus.ALERTED.value if level == RiskLevel.L2 else AlertStatus.PENDING_APPROVAL.value
        if role_key in {"action_planning", "work_order_coordination"}:
            return AlertStatus.PENDING_APPROVAL.value
        if role_key == "effectiveness_verification":
            return AlertStatus.REVIEWED.value
        return "Supervisor"

    def _audit(
        self,
        *,
        entity_type: str,
        entity_id: str,
        stage: str,
        actor: str,
        action: str,
        payload: dict[str, Any],
    ) -> AuditLog:
        return AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            stage=stage,
            actor=actor,
            action=action,
            payload=payload,
            ts=utc_now(),
        )
