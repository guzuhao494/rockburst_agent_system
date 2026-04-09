from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from .database import Database
from .models import AgentMonitorStatus, AlertStatus, ApprovalStatus, AuditLog, ExecutionStatus, ReviewStatus
from .openclaw_workflow_agents import OpenClawWorkflowClient, _extract_json_text
from .time_utils import utc_now


@dataclass(frozen=True)
class MonitorTrigger:
    signature: str
    reason: str


@dataclass(frozen=True)
class MonitorBriefing:
    headline: str
    summary: str
    priority: str


class RockburstAgentMonitor:
    def __init__(
        self,
        *,
        db: Database,
        client: OpenClawWorkflowClient,
        enabled: bool,
        interval_seconds: int,
        session_id: str = "rockburst-monitor",
    ) -> None:
        self.db = db
        self.client = client
        self.enabled = enabled
        self.interval_seconds = interval_seconds
        self.session_id = session_id
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        status = AgentMonitorStatus.MONITORING if self.enabled else AgentMonitorStatus.IDLE
        self.db.set_agent_monitor_state(
            enabled=self.enabled,
            status=status,
            session_id=self.session_id,
            poll_interval_seconds=self.interval_seconds,
            last_checked_at=None,
            last_briefing_at=self.db.get_agent_monitor_state()["last_briefing_at"],
            latest_headline=self.db.get_agent_monitor_state()["latest_headline"],
            latest_summary=self.db.get_agent_monitor_state()["latest_summary"],
            latest_priority=self.db.get_agent_monitor_state()["latest_priority"],
            last_trigger_signature=self.db.get_agent_monitor_state()["last_trigger_signature"],
            last_error=None,
        )
        if self.enabled and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._run_loop(), name="rockburst-agent-monitor")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        current = self.db.get_agent_monitor_state()
        self.db.set_agent_monitor_state(
            enabled=current["enabled"],
            status=AgentMonitorStatus.IDLE,
            session_id=current["session_id"],
            poll_interval_seconds=current["poll_interval_seconds"],
            last_checked_at=current["last_checked_at"],
            last_briefing_at=current["last_briefing_at"],
            latest_headline=current["latest_headline"],
            latest_summary=current["latest_summary"],
            latest_priority=current["latest_priority"],
            last_trigger_signature=current["last_trigger_signature"],
            last_error=current["last_error"],
        )

    def status(self) -> dict[str, Any]:
        return self.db.get_agent_monitor_state()

    async def _run_loop(self) -> None:
        while True:
            checked_at = utc_now().isoformat()
            try:
                self.db.update_agent_monitor_state(
                    status=AgentMonitorStatus.MONITORING,
                    last_checked_at=checked_at,
                    last_error=None,
                )
                trigger = self._detect_trigger()
                if trigger is None:
                    self.db.update_agent_monitor_state(
                        status=AgentMonitorStatus.MONITORING,
                        last_trigger_signature=None,
                        last_error=None,
                    )
                else:
                    current = self.db.get_agent_monitor_state()
                    if current["last_trigger_signature"] != trigger.signature:
                        self.db.update_agent_monitor_state(
                            status=AgentMonitorStatus.ATTENTION,
                            last_checked_at=checked_at,
                            last_error=None,
                        )
                        briefing = await asyncio.to_thread(self._generate_briefing, trigger)
                        self.db.update_agent_monitor_state(
                            status=AgentMonitorStatus.ATTENTION,
                            last_briefing_at=checked_at,
                            latest_headline=briefing.headline,
                            latest_summary=briefing.summary,
                            latest_priority=briefing.priority,
                            last_trigger_signature=trigger.signature,
                            last_error=None,
                        )
                        self.db.create_audit_log(
                            AuditLog(
                                entity_type="agent_monitor",
                                entity_id=self.session_id,
                                stage="Supervisor",
                                actor="rockburst",
                                action="auto_briefing_published",
                                payload={
                                    "headline": briefing.headline,
                                    "summary": briefing.summary,
                                    "priority": briefing.priority,
                                    "trigger_reason": trigger.reason,
                                    "session_id": self.session_id,
                                },
                                ts=utc_now(),
                            )
                        )
                    else:
                        self.db.update_agent_monitor_state(
                            status=AgentMonitorStatus.ATTENTION,
                            last_error=None,
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.db.update_agent_monitor_state(
                    status=AgentMonitorStatus.ERROR,
                    last_checked_at=checked_at,
                    last_error=str(exc),
                )
            await asyncio.sleep(self.interval_seconds)

    def _detect_trigger(self) -> MonitorTrigger | None:
        alerts = self.db.list_alert_envelopes()
        work_orders = self.db.list_work_order_envelopes()
        replay_state = self.db.get_replay_state()

        pending_alerts = sorted(
            (item for item in alerts if item.alert.status == AlertStatus.PENDING_APPROVAL),
            key=lambda item: item.alert.level.value,
            reverse=True,
        )
        ready_orders = [
            item
            for item in work_orders
            if item.work_order.approval_status == ApprovalStatus.APPROVED
            and item.work_order.execution_status == ExecutionStatus.READY
        ]
        open_reviews = [item for item in alerts if item.loop_review and item.loop_review.status == ReviewStatus.OPEN]

        if not pending_alerts and not ready_orders and not open_reviews and replay_state["status"] != "failed":
            return None

        top_pending = pending_alerts[0] if pending_alerts else None
        top_ready = ready_orders[0] if ready_orders else None
        top_review = open_reviews[0] if open_reviews else None
        signature = json.dumps(
            {
                "pending_alert_ids": [item.alert.alert_id for item in pending_alerts[:3]],
                "ready_work_order_ids": [item.work_order.workorder_id for item in ready_orders[:3]],
                "open_review_ids": [item.loop_review.review_id for item in open_reviews[:3] if item.loop_review],
                "replay_status": replay_state["status"],
                "replay_error": replay_state["last_error"],
                "current_role_key": replay_state["current_role_key"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        reasons: list[str] = []
        if top_pending is not None:
            reasons.append(
                f"存在待审批告警，最高等级为 {top_pending.alert.level.value}，区域 {top_pending.alert.area_id}"
            )
        if top_ready is not None:
            reasons.append(f"存在待派发工单，区域 {top_ready.alert.area_id}")
        if top_review is not None and top_review.loop_review is not None:
            reasons.append(f"存在待关环复核，告警 {top_review.alert.alert_id}")
        if replay_state["status"] == "failed":
            reasons.append(f"回放失败: {replay_state['last_error']}")
        return MonitorTrigger(signature=signature, reason="；".join(reasons))

    def _generate_briefing(self, trigger: MonitorTrigger) -> MonitorBriefing:
        message = "\n".join(
            [
                "你是岩爆系统的外层值守智能体 rockburst。",
                "先调用 rockburst_agent_briefing 获取当前系统简报；必要时再调用其他只读工具补充上下文。",
                "只返回一个 JSON 对象，不要加代码块或额外解释。",
                '格式: {"headline":"...","summary":"...","priority":"normal|high|critical"}',
                f"当前触发原因: {trigger.reason}",
                "要求:",
                "- headline 用一句中文点明当前最关键事项。",
                "- summary 用 1 到 3 句中文说明为什么值得关注，以及建议先做什么。",
                "- priority 只能从 normal、high、critical 三者中选择。",
            ]
        )
        raw_text = self.client.run_agent(
            agent_id="rockburst",
            message=message,
            session_id=self.session_id,
        )
        payload = json.loads(_extract_json_text(raw_text))
        headline = str(payload.get("headline", "")).strip()
        summary = str(payload.get("summary", "")).strip()
        priority = str(payload.get("priority", "high")).strip().lower() or "high"
        if priority not in {"normal", "high", "critical"}:
            raise RuntimeError(f"Unexpected briefing priority: {priority}")
        if not headline:
            raise RuntimeError("OpenClaw monitor returned an empty headline.")
        if not summary:
            summary = headline
        return MonitorBriefing(headline=headline, summary=summary, priority=priority)
