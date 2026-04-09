from __future__ import annotations

import json
import base64
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .agent_runtime import WorkflowAgent
from .models import AlertStatus, CaseContext, RiskLevel


ROLE_AGENT_IDS = {
    "supervisor": "rockburst-supervisor",
    "ingest_intake": "rockburst-ingest-intake",
    "data_quality": "rockburst-data-quality",
    "risk_assessment": "rockburst-risk-assessment",
    "alert_explanation": "rockburst-alert-explanation",
    "action_planning": "rockburst-action-planning",
    "work_order_coordination": "rockburst-work-order-coordination",
    "effectiveness_verification": "rockburst-effectiveness-verification",
    "supervisor_finalize": "rockburst-supervisor-finalize",
}


@dataclass(frozen=True)
class OpenClawDecision:
    action: str
    reason: str


class OpenClawWorkflowClient:
    def __init__(
        self,
        *,
        project_root: Path,
        thinking: str = "off",
        timeout_seconds: int = 180,
        powershell_executable: str = "powershell.exe",
    ) -> None:
        self.project_root = project_root
        self.thinking = thinking
        self.timeout_seconds = timeout_seconds
        self.powershell_executable = powershell_executable
        helper_path = project_root / "scripts" / "openclaw-with-proxy.ps1"
        self.helper_script = _to_windows_path(helper_path)

    def run_agent(self, *, agent_id: str, message: str) -> str:
        command = [
            self.powershell_executable,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            self.helper_script,
            "agent",
            "--local",
            "--agent",
            agent_id,
            "--session-id",
            f"workflow-{agent_id}-{uuid4().hex[:10]}",
            "--message-b64",
            base64.b64encode(message.encode("utf-8")).decode("ascii"),
            "--thinking",
            self.thinking,
            "--json",
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        stdout = _decode_openclaw_output(completed.stdout)
        stderr = _decode_openclaw_output(completed.stderr)
        combined = "\n".join(part for part in [stdout, stderr] if part)
        if completed.returncode != 0:
            raise RuntimeError(f"OpenClaw agent {agent_id} failed: {combined.strip()}")

        envelope_json = _extract_json_text(combined)
        envelope = json.loads(envelope_json)
        payloads = envelope.get("payloads") or []
        if not payloads:
            raise RuntimeError(f"OpenClaw agent {agent_id} returned no payloads: {combined.strip()}")

        text = payloads[0].get("text", "")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError(f"OpenClaw agent {agent_id} returned empty text payload.")
        return text


class OpenClawWorkflowAgent(WorkflowAgent):
    def __init__(
        self,
        *,
        actor: str,
        role_name: str,
        role_id: str,
        client: OpenClawWorkflowClient,
        registry,
        audit_factory,
    ) -> None:
        super().__init__(actor=actor, registry=registry, audit_factory=audit_factory)
        self.role_name = role_name
        self.role_id = role_id
        self.client = client

    def decision_meta(self, decision: OpenClawDecision) -> dict[str, Any]:
        return {
            "role_id": self.role_id,
            "decision_reason": decision.reason,
            "implementation": "openclaw",
        }

    def decide(self, state: CaseContext, *, allowed_actions: list[str], guidance: list[str]) -> OpenClawDecision:
        message = "\n".join(
            [
                f"你是岩爆闭环工作流中的 {self.role_name}。",
                "你的任务是基于当前状态，选择下一步最合适的单个动作。",
                f"只允许从这些动作中选择: {', '.join(allowed_actions)}",
                "必须只返回一个 JSON 对象，不要加代码块、解释、前后缀。",
                '返回格式: {"action":"动作名","reason":"简短中文理由"}',
                "规则:",
                *[f"- {item}" for item in guidance],
                "当前状态(JSON):",
                json.dumps(_state_prompt_payload(state), ensure_ascii=False, indent=2),
            ]
        )
        raw_text = self.client.run_agent(agent_id=self.role_id, message=message)
        decision_payload = json.loads(_extract_json_text(raw_text))
        action = str(decision_payload.get("action", "")).strip()
        reason = str(decision_payload.get("reason", "")).strip()
        if action not in allowed_actions:
            raise RuntimeError(
                f"{self.role_name} 返回了未允许的动作 {action!r}。原始回复: {raw_text}"
            )
        if not reason:
            reason = "依据当前状态执行该动作。"
        return OpenClawDecision(action=action, reason=reason)


class OpenClawSupervisorAgent(OpenClawWorkflowAgent):
    def run(self, state: CaseContext) -> CaseContext:
        decision = self.decide(
            state,
            allowed_actions=["record_workflow_started"],
            guidance=[
                "始终选择 record_workflow_started。",
                "理由应概括当前工作流准备开始处理的模式和区域。",
            ],
        )
        return self.append_audit(
            state,
            entity_type="workflow",
            entity_id=f"{state['mode']}:{state['area_id']}",
            stage="Supervisor",
            action="workflow_started",
            payload={
                "mode": state["mode"],
                "area_id": state["area_id"],
                **self.decision_meta(decision),
            },
        )


class OpenClawIngestIntakeAgent(OpenClawWorkflowAgent):
    def run(self, state: CaseContext) -> CaseContext:
        decision = self.decide(
            state,
            allowed_actions=["order_event_batch", "skip"],
            guidance=[
                "当 mode 是 ingest 且 event_batch 非空时，选择 order_event_batch。",
                "否则选择 skip。",
            ],
        )
        if decision.action == "skip":
            return {}

        next_state, result = self.invoke_tool(state, tool_name="order_event_batch", stage=AlertStatus.OBSERVED.value)
        return self.append_audit(
            next_state,
            entity_type="workflow",
            entity_id=f"ingest:{state['area_id']}",
            stage=AlertStatus.OBSERVED.value,
            action="events_received",
            payload={
                "count": len(next_state.get("event_batch", [])),
                "summary": result.summary,
                **self.decision_meta(decision),
            },
        )


class OpenClawDataQualityAgent(OpenClawWorkflowAgent):
    def run(self, state: CaseContext) -> CaseContext:
        decision = self.decide(
            state,
            allowed_actions=["quality_check_events", "skip"],
            guidance=[
                "当 mode 是 ingest 时，选择 quality_check_events。",
                "否则选择 skip。",
            ],
        )
        if decision.action == "skip":
            return {}

        next_state, result = self.invoke_tool(state, tool_name="quality_check_events", stage=AlertStatus.OBSERVED.value)
        quality_report = next_state["quality_report"]
        payload = quality_report.model_dump(mode="json")
        payload["summary"] = result.summary
        payload.update(self.decision_meta(decision))
        return self.append_audit(
            next_state,
            entity_type="workflow",
            entity_id=f"quality:{state['area_id']}",
            stage=AlertStatus.OBSERVED.value,
            action="quality_checked",
            payload=payload,
        )


class OpenClawRiskAssessmentAgent(OpenClawWorkflowAgent):
    def run(self, state: CaseContext) -> CaseContext:
        decision = self.decide(
            state,
            allowed_actions=["assess_risk_snapshot", "assessment_skipped_no_valid_events", "skip"],
            guidance=[
                "当 mode 不是 ingest 时，选择 skip。",
                "当 mode 是 ingest 且 event_batch 为空时，选择 assessment_skipped_no_valid_events。",
                "当 mode 是 ingest 且 event_batch 非空时，选择 assess_risk_snapshot。",
            ],
        )
        if decision.action == "skip":
            return {}
        if decision.action == "assessment_skipped_no_valid_events":
            return self.append_audit(
                state,
                entity_type="workflow",
                entity_id=f"risk:{state['area_id']}",
                stage=AlertStatus.ASSESSED.value,
                action="assessment_skipped_no_valid_events",
                payload=self.decision_meta(decision),
            )

        next_state, result = self.invoke_tool(state, tool_name="assess_risk_snapshot", stage=AlertStatus.ASSESSED.value)
        snapshot = next_state["risk_snapshot"]
        payload = snapshot.model_dump(mode="json")
        payload["summary"] = result.summary
        payload.update(self.decision_meta(decision))
        return self.append_audit(
            next_state,
            entity_type="risk_snapshot",
            entity_id=snapshot.snapshot_id,
            stage=AlertStatus.ASSESSED.value,
            action="risk_snapshot_created",
            payload=payload,
        )


class OpenClawAlertExplanationAgent(OpenClawWorkflowAgent):
    def run(self, state: CaseContext) -> CaseContext:
        decision = self.decide(
            state,
            allowed_actions=["prepare_alert", "skip"],
            guidance=[
                "当 risk_snapshot 不存在时，选择 skip。",
                "当 risk_snapshot.level 是 L1 时，选择 skip。",
                "当 risk_snapshot.level 是 L2、L3 或 L4 时，选择 prepare_alert。",
            ],
        )
        if decision.action == "skip":
            return {}

        snapshot = state.get("risk_snapshot")
        next_state, result = self.invoke_tool(
            state,
            tool_name="prepare_alert",
            stage=_alert_stage(snapshot.level if snapshot is not None else RiskLevel.L2),
        )
        alert = next_state["alert_state"]
        payload = {
            "message": alert.message,
            "triggered_rules": snapshot.triggered_rules if snapshot is not None else [],
            "summary": result.summary,
            **self.decision_meta(decision),
        }
        return self.append_audit(
            next_state,
            entity_type="alert",
            entity_id=alert.alert_id,
            stage=alert.status.value,
            action="alert_created",
            payload=payload,
        )


class OpenClawActionPlanningAgent(OpenClawWorkflowAgent):
    def run(self, state: CaseContext) -> CaseContext:
        decision = self.decide(
            state,
            allowed_actions=["resolve_and_draft_work_order", "skip"],
            guidance=[
                "当 alert_state 不存在时，选择 skip。",
                "当 alert_state.level 是 L2 时，选择 skip。",
                "当 alert_state.level 是 L3 或 L4 时，选择 resolve_and_draft_work_order。",
            ],
        )
        if decision.action == "skip":
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
        payload.update(self.decision_meta(decision))
        return self.append_audit(
            next_state,
            entity_type="work_order",
            entity_id=work_order.workorder_id,
            stage=AlertStatus.PENDING_APPROVAL.value,
            action="work_order_created",
            payload=payload,
        )


class OpenClawWorkOrderCoordinationAgent(OpenClawWorkflowAgent):
    def run(self, state: CaseContext) -> CaseContext:
        decision = self.decide(
            state,
            allowed_actions=["persist_work_order", "observation_only", "skip"],
            guidance=[
                "当 work_order_state 存在时，优先选择 persist_work_order。",
                "当 mode 是 ingest 且 risk_snapshot.level 是 L1 时，选择 observation_only。",
                "其他情况选择 skip。",
            ],
        )
        if decision.action == "skip":
            return state
        if decision.action == "observation_only":
            snapshot = state["risk_snapshot"]
            return self.append_audit(
                state,
                entity_type="risk_snapshot",
                entity_id=snapshot.snapshot_id,
                stage=AlertStatus.OBSERVED.value,
                action="observation_only",
                payload={
                    "level": snapshot.level.value,
                    **self.decision_meta(decision),
                },
            )

        next_state, _ = self.invoke_tool(
            state,
            tool_name="persist_work_order",
            stage=AlertStatus.PENDING_APPROVAL.value,
        )
        return self.append_audit(
            next_state,
            entity_type="workflow",
            entity_id=f"coordination:{state['mode']}:{state['area_id']}",
            stage=AlertStatus.PENDING_APPROVAL.value,
            action="work_order_persisted",
            payload={
                "workorder_id": next_state["work_order_state"].workorder_id,
                **self.decision_meta(decision),
            },
        )


class OpenClawEffectivenessVerificationAgent(OpenClawWorkflowAgent):
    def run(self, state: CaseContext) -> CaseContext:
        decision = self.decide(
            state,
            allowed_actions=["evaluate_feedback_outcome", "skip"],
            guidance=[
                "当 mode 不是 review 时，选择 skip。",
                "当 execution_feedback 或 alert_state 缺失时，选择 skip。",
                "当 mode 是 review 且 alert_state、execution_feedback 都存在时，选择 evaluate_feedback_outcome。",
            ],
        )
        if decision.action == "skip":
            return {}

        next_state, result = self.invoke_tool(
            state,
            tool_name="evaluate_feedback_outcome",
            stage=AlertStatus.REVIEWED.value,
        )
        review = next_state["loop_review"]
        payload = review.model_dump(mode="json")
        payload["summary"] = result.summary
        payload.update(self.decision_meta(decision))
        return self.append_audit(
            next_state,
            entity_type="loop_review",
            entity_id=review.review_id,
            stage=AlertStatus.REVIEWED.value,
            action="loop_review_created",
            payload=payload,
        )


class OpenClawSupervisorFinalizeAgent(OpenClawWorkflowAgent):
    def run(self, state: CaseContext) -> CaseContext:
        decision = self.decide(
            state,
            allowed_actions=["record_workflow_finished"],
            guidance=[
                "始终选择 record_workflow_finished。",
                "理由应概括当前工作流的产物，例如是否形成告警、工单或复核。",
            ],
        )
        return self.append_audit(
            state,
            entity_type="workflow",
            entity_id=f"{state['mode']}:{state['area_id']}",
            stage="Supervisor",
            action="workflow_finished",
            payload={
                "has_alert": bool(state.get("alert_state")),
                "has_review": bool(state.get("loop_review")),
                **self.decision_meta(decision),
            },
        )


def _state_prompt_payload(state: CaseContext) -> dict[str, Any]:
    event_batch = state.get("event_batch", [])
    quality_report = state.get("quality_report")
    risk_snapshot = state.get("risk_snapshot")
    alert_state = state.get("alert_state")
    work_order_state = state.get("work_order_state")
    execution_feedback = state.get("execution_feedback")
    loop_review = state.get("loop_review")

    return {
        "mode": state.get("mode"),
        "area_id": state.get("area_id"),
        "event_batch": {
            "count": len(event_batch),
            "event_ids": [event.event_id for event in event_batch[:10]],
        },
        "quality_report": quality_report.model_dump(mode="json") if quality_report else None,
        "risk_snapshot": (
            {
                "snapshot_id": risk_snapshot.snapshot_id,
                "level": risk_snapshot.level.value,
                "score": risk_snapshot.score,
                "area_id": risk_snapshot.area_id,
                "triggered_rules": risk_snapshot.triggered_rules,
            }
            if risk_snapshot
            else None
        ),
        "alert_state": (
            {
                "alert_id": alert_state.alert_id,
                "level": alert_state.level.value,
                "status": alert_state.status.value,
                "area_id": alert_state.area_id,
            }
            if alert_state
            else None
        ),
        "work_order_state": (
            {
                "workorder_id": work_order_state.workorder_id,
                "type": work_order_state.type,
                "priority": work_order_state.priority,
                "approval_status": work_order_state.approval_status.value,
                "execution_status": work_order_state.execution_status.value,
                "assignee": work_order_state.assignee,
            }
            if work_order_state
            else None
        ),
        "execution_feedback": execution_feedback.model_dump(mode="json") if execution_feedback else None,
        "loop_review": loop_review.model_dump(mode="json") if loop_review else None,
        "audit_log_count": len(state.get("audit_logs", [])),
    }


def _to_windows_path(path: Path) -> str:
    text = str(path)
    match = re.match(r"^/mnt/([a-zA-Z])/(.*)$", text)
    if match:
        drive = match.group(1).upper()
        rest = match.group(2).replace("/", "\\")
        return f"{drive}:\\{rest}"
    return text


def _extract_json_text(raw_text: str) -> str:
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw_text):
        if char not in "[{":
            continue
        try:
            _, end = decoder.raw_decode(raw_text[index:])
            return raw_text[index:index + end]
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"Could not find JSON payload in OpenClaw output: {raw_text}")


def _alert_stage(level: RiskLevel) -> str:
    return AlertStatus.ALERTED.value if level == RiskLevel.L2 else AlertStatus.PENDING_APPROVAL.value


def _decode_openclaw_output(raw_bytes: bytes) -> str:
    if not raw_bytes:
        return ""

    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")
