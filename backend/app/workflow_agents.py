from __future__ import annotations

from typing import Any

from .agent_runtime import WorkflowAgent
from .models import AlertStatus, CaseContext, RiskLevel


class SupervisorAgent(WorkflowAgent):
    def run(self, state: CaseContext) -> CaseContext:
        return self.append_audit(
            state,
            entity_type="workflow",
            entity_id=f"{state['mode']}:{state['area_id']}",
            stage="Supervisor",
            action="workflow_started",
            payload={"mode": state["mode"], "area_id": state["area_id"]},
        )


class IngestIntakeAgent(WorkflowAgent):
    def run(self, state: CaseContext) -> CaseContext:
        if state["mode"] != "ingest":
            return {}

        next_state, result = self.invoke_tool(state, tool_name="order_event_batch", stage=AlertStatus.OBSERVED.value)
        return self.append_audit(
            next_state,
            entity_type="workflow",
            entity_id=f"ingest:{state['area_id']}",
            stage=AlertStatus.OBSERVED.value,
            action="events_received",
            payload={"count": len(next_state.get("event_batch", [])), "summary": result.summary},
        )


class DataQualityAgent(WorkflowAgent):
    def run(self, state: CaseContext) -> CaseContext:
        if state["mode"] != "ingest":
            return {}

        next_state, result = self.invoke_tool(state, tool_name="quality_check_events", stage=AlertStatus.OBSERVED.value)
        quality_report = next_state["quality_report"]
        payload = quality_report.model_dump(mode="json")
        payload["summary"] = result.summary
        return self.append_audit(
            next_state,
            entity_type="workflow",
            entity_id=f"quality:{state['area_id']}",
            stage=AlertStatus.OBSERVED.value,
            action="quality_checked",
            payload=payload,
        )


class RiskAssessmentAgent(WorkflowAgent):
    def run(self, state: CaseContext) -> CaseContext:
        if state["mode"] != "ingest":
            return {}

        if not state.get("event_batch"):
            return self.append_audit(
                state,
                entity_type="workflow",
                entity_id=f"risk:{state['area_id']}",
                stage=AlertStatus.ASSESSED.value,
                action="assessment_skipped_no_valid_events",
                payload={},
            )

        next_state, result = self.invoke_tool(state, tool_name="assess_risk_snapshot", stage=AlertStatus.ASSESSED.value)
        snapshot = next_state["risk_snapshot"]
        payload = snapshot.model_dump(mode="json")
        payload["summary"] = result.summary
        return self.append_audit(
            next_state,
            entity_type="risk_snapshot",
            entity_id=snapshot.snapshot_id,
            stage=AlertStatus.ASSESSED.value,
            action="risk_snapshot_created",
            payload=payload,
        )


class AlertExplanationAgent(WorkflowAgent):
    def run(self, state: CaseContext) -> CaseContext:
        snapshot = state.get("risk_snapshot")
        if snapshot is None or snapshot.level == RiskLevel.L1:
            return {}

        next_state, result = self.invoke_tool(state, tool_name="prepare_alert", stage=_alert_stage(snapshot.level))
        alert = next_state["alert_state"]
        return self.append_audit(
            next_state,
            entity_type="alert",
            entity_id=alert.alert_id,
            stage=alert.status.value,
            action="alert_created",
            payload={
                "message": alert.message,
                "triggered_rules": snapshot.triggered_rules,
                "summary": result.summary,
            },
        )


class ActionPlanningAgent(WorkflowAgent):
    def run(self, state: CaseContext) -> CaseContext:
        alert = state.get("alert_state")
        if alert is None or alert.level == RiskLevel.L2:
            return {}

        next_state, _ = self.invoke_tool(
            state,
            tool_name="resolve_work_order_template",
            stage=AlertStatus.PENDING_APPROVAL.value,
        )
        next_state, result = self.invoke_tool(
            next_state,
            tool_name="draft_work_order",
            stage=AlertStatus.PENDING_APPROVAL.value,
        )
        work_order = next_state["work_order_state"]
        payload = work_order.model_dump(mode="json")
        payload["summary"] = result.summary
        return self.append_audit(
            next_state,
            entity_type="work_order",
            entity_id=work_order.workorder_id,
            stage=AlertStatus.PENDING_APPROVAL.value,
            action="work_order_created",
            payload=payload,
        )


class WorkOrderCoordinationAgent(WorkflowAgent):
    def run(self, state: CaseContext) -> CaseContext:
        next_state = state
        work_order = state.get("work_order_state")
        if work_order:
            next_state, _ = self.invoke_tool(
                state,
                tool_name="persist_work_order",
                stage=AlertStatus.PENDING_APPROVAL.value,
            )

        if state.get("mode") == "ingest" and state.get("risk_snapshot") and state["risk_snapshot"].level == RiskLevel.L1:
            return self.append_audit(
                next_state,
                entity_type="risk_snapshot",
                entity_id=state["risk_snapshot"].snapshot_id,
                stage=AlertStatus.OBSERVED.value,
                action="observation_only",
                payload={"level": state["risk_snapshot"].level.value},
            )

        return next_state


class EffectivenessVerificationAgent(WorkflowAgent):
    def run(self, state: CaseContext) -> CaseContext:
        if state["mode"] != "review":
            return {}

        alert = state.get("alert_state")
        feedback = state.get("execution_feedback")
        if alert is None or feedback is None:
            return {}

        next_state, result = self.invoke_tool(
            state,
            tool_name="evaluate_feedback_outcome",
            stage=AlertStatus.REVIEWED.value,
        )
        review = next_state["loop_review"]
        payload = review.model_dump(mode="json")
        payload["summary"] = result.summary
        return self.append_audit(
            next_state,
            entity_type="loop_review",
            entity_id=review.review_id,
            stage=AlertStatus.REVIEWED.value,
            action="loop_review_created",
            payload=payload,
        )


class SupervisorFinalizeAgent(WorkflowAgent):
    def run(self, state: CaseContext) -> CaseContext:
        return self.append_audit(
            state,
            entity_type="workflow",
            entity_id=f"{state['mode']}:{state['area_id']}",
            stage="Supervisor",
            action="workflow_finished",
            payload={"has_alert": bool(state.get("alert_state")), "has_review": bool(state.get("loop_review"))},
        )


def _alert_stage(level: RiskLevel) -> str:
    return AlertStatus.ALERTED.value if level == RiskLevel.L2 else AlertStatus.PENDING_APPROVAL.value
