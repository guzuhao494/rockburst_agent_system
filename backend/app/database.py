from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .models import (
    AgentMonitorStatus,
    Alert,
    AlertEnvelope,
    AuditLog,
    ExecutionFeedback,
    ExecutionStatus,
    LoopReview,
    ReplayStatus,
    ReviewStatus,
    RiskSnapshot,
    WorkOrder,
    WorkOrderEnvelope,
)
from .time_utils import utc_now


def _utcnow() -> datetime:
    return utc_now()


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _from_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS microseismic_events (
                    event_id TEXT PRIMARY KEY,
                    ts TEXT NOT NULL,
                    area_id TEXT NOT NULL,
                    energy REAL NOT NULL,
                    magnitude REAL NOT NULL,
                    x REAL NOT NULL,
                    y REAL NOT NULL,
                    z REAL NOT NULL,
                    confidence REAL NOT NULL,
                    source TEXT NOT NULL,
                    quality_status TEXT NOT NULL,
                    quality_notes TEXT
                );

                CREATE TABLE IF NOT EXISTS risk_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    area_id TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    score REAL NOT NULL,
                    level TEXT NOT NULL,
                    triggered_rules TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    contributing_factors TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id TEXT PRIMARY KEY,
                    risk_snapshot_id TEXT NOT NULL,
                    area_id TEXT NOT NULL,
                    level TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    suggested_actions TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(risk_snapshot_id) REFERENCES risk_snapshots(snapshot_id)
                );

                CREATE TABLE IF NOT EXISTS work_orders (
                    workorder_id TEXT PRIMARY KEY,
                    alert_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    assignee TEXT,
                    priority TEXT NOT NULL,
                    approval_status TEXT NOT NULL,
                    execution_status TEXT NOT NULL,
                    due_at TEXT,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(alert_id) REFERENCES alerts(alert_id)
                );

                CREATE TABLE IF NOT EXISTS execution_feedbacks (
                    feedback_id TEXT PRIMARY KEY,
                    workorder_id TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    result TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    attachments TEXT NOT NULL,
                    FOREIGN KEY(workorder_id) REFERENCES work_orders(workorder_id)
                );

                CREATE TABLE IF NOT EXISTS loop_reviews (
                    review_id TEXT PRIMARY KEY,
                    alert_id TEXT NOT NULL,
                    effectiveness TEXT NOT NULL,
                    residual_risk TEXT NOT NULL,
                    followup_action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    closed_at TEXT,
                    closure_note TEXT,
                    FOREIGN KEY(alert_id) REFERENCES alerts(alert_id)
                );

                CREATE TABLE IF NOT EXISTS audit_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    ts TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS replay_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    scenario_name TEXT,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    total_batches INTEGER NOT NULL,
                    loop_enabled INTEGER NOT NULL,
                    started_at TEXT,
                    last_error TEXT,
                    current_batch INTEGER NOT NULL DEFAULT 0,
                    current_area_id TEXT,
                    current_mode TEXT,
                    current_phase TEXT NOT NULL DEFAULT 'idle',
                    current_role_key TEXT,
                    current_role_id TEXT,
                    current_role_step INTEGER NOT NULL DEFAULT 0,
                    total_role_steps INTEGER NOT NULL DEFAULT 0,
                    completed_role_steps INTEGER NOT NULL DEFAULT 0,
                    current_summary TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_monitor_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    enabled INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    poll_interval_seconds INTEGER NOT NULL,
                    last_checked_at TEXT,
                    last_briefing_at TEXT,
                    latest_headline TEXT,
                    latest_summary TEXT,
                    latest_priority TEXT,
                    last_trigger_signature TEXT,
                    last_error TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )
            replay_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(replay_state)").fetchall()
            }
            replay_migrations = {
                "last_error": "ALTER TABLE replay_state ADD COLUMN last_error TEXT",
                "current_batch": "ALTER TABLE replay_state ADD COLUMN current_batch INTEGER NOT NULL DEFAULT 0",
                "current_area_id": "ALTER TABLE replay_state ADD COLUMN current_area_id TEXT",
                "current_mode": "ALTER TABLE replay_state ADD COLUMN current_mode TEXT",
                "current_phase": "ALTER TABLE replay_state ADD COLUMN current_phase TEXT NOT NULL DEFAULT 'idle'",
                "current_role_key": "ALTER TABLE replay_state ADD COLUMN current_role_key TEXT",
                "current_role_id": "ALTER TABLE replay_state ADD COLUMN current_role_id TEXT",
                "current_role_step": "ALTER TABLE replay_state ADD COLUMN current_role_step INTEGER NOT NULL DEFAULT 0",
                "total_role_steps": "ALTER TABLE replay_state ADD COLUMN total_role_steps INTEGER NOT NULL DEFAULT 0",
                "completed_role_steps": "ALTER TABLE replay_state ADD COLUMN completed_role_steps INTEGER NOT NULL DEFAULT 0",
                "current_summary": "ALTER TABLE replay_state ADD COLUMN current_summary TEXT",
            }
            for column_name, statement in replay_migrations.items():
                if column_name not in replay_columns:
                    conn.execute(statement)
            conn.execute(
                """
                INSERT INTO replay_state (
                    id, scenario_name, status, progress, total_batches, loop_enabled, started_at, last_error,
                    current_batch, current_area_id, current_mode, current_phase, current_role_key, current_role_id,
                    current_role_step, total_role_steps, completed_role_steps, current_summary, updated_at
                )
                VALUES (1, NULL, ?, 0, 0, 0, NULL, NULL, 0, NULL, NULL, 'idle', NULL, NULL, 0, 0, 0, NULL, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (ReplayStatus.IDLE.value, _utcnow().isoformat()),
            )
            conn.execute(
                """
                INSERT INTO agent_monitor_state (
                    id, enabled, status, session_id, poll_interval_seconds, last_checked_at, last_briefing_at,
                    latest_headline, latest_summary, latest_priority, last_trigger_signature, last_error, updated_at
                )
                VALUES (1, 0, ?, 'rockburst-monitor', 20, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (AgentMonitorStatus.IDLE.value, _utcnow().isoformat()),
            )

    def upsert_event(self, event: dict[str, Any], quality_status: str, quality_notes: str = "") -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO microseismic_events (
                    event_id, ts, area_id, energy, magnitude, x, y, z, confidence, source, quality_status, quality_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    event["ts"],
                    event["area_id"],
                    event["energy"],
                    event["magnitude"],
                    event["x"],
                    event["y"],
                    event["z"],
                    event["confidence"],
                    event["source"],
                    quality_status,
                    quality_notes,
                ),
            )

    def create_risk_snapshot(self, snapshot: RiskSnapshot) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO risk_snapshots (
                    snapshot_id, area_id, ts, score, level, triggered_rules, explanation, contributing_factors
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.area_id,
                    snapshot.ts.isoformat(),
                    snapshot.score,
                    snapshot.level.value,
                    _to_json(snapshot.triggered_rules),
                    snapshot.explanation,
                    _to_json(snapshot.contributing_factors),
                ),
            )

    def create_alert(self, alert: Alert) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO alerts (
                    alert_id, risk_snapshot_id, area_id, level, status, message, suggested_actions, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert.alert_id,
                    alert.risk_snapshot_id,
                    alert.area_id,
                    alert.level.value,
                    alert.status.value,
                    alert.message,
                    _to_json(alert.suggested_actions),
                    alert.created_at.isoformat(),
                    alert.updated_at.isoformat(),
                ),
            )

    def update_alert_status(self, alert_id: str, status: str, message: str | None = None) -> Alert:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()
            if row is None:
                raise KeyError(f"Alert {alert_id} not found")
            conn.execute(
                "UPDATE alerts SET status = ?, message = ?, updated_at = ? WHERE alert_id = ?",
                (status, message or row["message"], _utcnow().isoformat(), alert_id),
            )
        return self.get_alert(alert_id)

    def get_alert(self, alert_id: str) -> Alert:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()
            if row is None:
                raise KeyError(f"Alert {alert_id} not found")
            return self._row_to_alert(row)

    def create_work_order(self, work_order: WorkOrder) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO work_orders (
                    workorder_id, alert_id, type, assignee, priority, approval_status, execution_status, due_at, details, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    work_order.workorder_id,
                    work_order.alert_id,
                    work_order.type,
                    work_order.assignee,
                    work_order.priority,
                    work_order.approval_status.value,
                    work_order.execution_status.value,
                    work_order.due_at.isoformat() if work_order.due_at else None,
                    _to_json(work_order.details),
                    work_order.created_at.isoformat(),
                    work_order.updated_at.isoformat(),
                ),
            )

    def get_work_order(self, workorder_id: str) -> WorkOrder:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM work_orders WHERE workorder_id = ?", (workorder_id,)).fetchone()
            if row is None:
                raise KeyError(f"Work order {workorder_id} not found")
            return self._row_to_work_order(row)

    def find_work_order_by_alert(self, alert_id: str) -> WorkOrder | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM work_orders WHERE alert_id = ?", (alert_id,)).fetchone()
            return self._row_to_work_order(row) if row else None

    def update_work_order_approval(self, workorder_id: str, approval_status: str) -> WorkOrder:
        with self.connection() as conn:
            conn.execute(
                "UPDATE work_orders SET approval_status = ?, updated_at = ? WHERE workorder_id = ?",
                (approval_status, _utcnow().isoformat(), workorder_id),
            )
        return self.get_work_order(workorder_id)

    def dispatch_work_order(self, workorder_id: str, assignee: str, due_at: datetime | None) -> WorkOrder:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE work_orders
                SET assignee = ?, due_at = ?, execution_status = ?, updated_at = ?
                WHERE workorder_id = ?
                """,
                (
                    assignee,
                    due_at.isoformat() if due_at else None,
                    ExecutionStatus.DISPATCHED.value,
                    _utcnow().isoformat(),
                    workorder_id,
                ),
            )
        return self.get_work_order(workorder_id)

    def mark_work_order_execution(self, workorder_id: str, status: str) -> WorkOrder:
        with self.connection() as conn:
            conn.execute(
                "UPDATE work_orders SET execution_status = ?, updated_at = ? WHERE workorder_id = ?",
                (status, _utcnow().isoformat(), workorder_id),
            )
        return self.get_work_order(workorder_id)

    def add_feedback(self, feedback: ExecutionFeedback) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO execution_feedbacks (feedback_id, workorder_id, ts, result, notes, attachments)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback.feedback_id,
                    feedback.workorder_id,
                    feedback.ts.isoformat(),
                    feedback.result,
                    feedback.notes,
                    _to_json(feedback.attachments),
                ),
            )

    def list_feedbacks(self, workorder_id: str) -> list[ExecutionFeedback]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM execution_feedbacks WHERE workorder_id = ? ORDER BY ts DESC", (workorder_id,)
            ).fetchall()
            return [self._row_to_feedback(row) for row in rows]

    def latest_feedback(self, workorder_id: str) -> ExecutionFeedback | None:
        feedbacks = self.list_feedbacks(workorder_id)
        return feedbacks[0] if feedbacks else None

    def create_loop_review(self, review: LoopReview) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO loop_reviews (
                    review_id, alert_id, effectiveness, residual_risk, followup_action, status, created_at, closed_at, closure_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review.review_id,
                    review.alert_id,
                    review.effectiveness,
                    review.residual_risk,
                    review.followup_action,
                    review.status.value,
                    review.created_at.isoformat(),
                    review.closed_at.isoformat() if review.closed_at else None,
                    review.closure_note,
                ),
            )

    def get_loop_review(self, review_id: str) -> LoopReview:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM loop_reviews WHERE review_id = ?", (review_id,)).fetchone()
            if row is None:
                raise KeyError(f"Loop review {review_id} not found")
            return self._row_to_loop_review(row)

    def find_loop_review_by_alert(self, alert_id: str) -> LoopReview | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM loop_reviews WHERE alert_id = ? ORDER BY created_at DESC", (alert_id,)).fetchone()
            return self._row_to_loop_review(row) if row else None

    def close_loop_review(self, review_id: str, closure_note: str) -> LoopReview:
        with self.connection() as conn:
            conn.execute(
                "UPDATE loop_reviews SET status = ?, closed_at = ?, closure_note = ? WHERE review_id = ?",
                (ReviewStatus.CLOSED.value, _utcnow().isoformat(), closure_note, review_id),
            )
        return self.get_loop_review(review_id)

    def create_audit_log(self, log: AuditLog) -> AuditLog:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_logs (entity_type, entity_id, stage, actor, action, payload, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log.entity_type,
                    log.entity_id,
                    log.stage,
                    log.actor,
                    log.action,
                    _to_json(log.payload),
                    log.ts.isoformat(),
                ),
            )
            log_id = int(cursor.lastrowid)
        payload = log.model_dump()
        payload["log_id"] = log_id
        return AuditLog(**payload)

    def list_audit_logs(self, entity_type: str | None = None, entity_id: str | None = None, limit: int = 50) -> list[AuditLog]:
        clauses: list[str] = []
        params: list[Any] = []
        if entity_type:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if entity_id:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM audit_logs {where} ORDER BY ts DESC, log_id DESC LIMIT ?"
        params.append(limit)
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_audit_log(row) for row in rows]

    def list_latest_risk_snapshots(self) -> list[RiskSnapshot]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT rs.*
                FROM risk_snapshots rs
                INNER JOIN (
                    SELECT area_id, MAX(ts) AS max_ts
                    FROM risk_snapshots
                    GROUP BY area_id
                ) latest
                ON latest.area_id = rs.area_id AND latest.max_ts = rs.ts
                ORDER BY rs.score DESC, rs.area_id
                """
            ).fetchall()
            return [self._row_to_risk_snapshot(row) for row in rows]

    def list_alert_envelopes(self) -> list[AlertEnvelope]:
        with self.connection() as conn:
            alert_rows = conn.execute("SELECT * FROM alerts ORDER BY updated_at DESC").fetchall()
        envelopes: list[AlertEnvelope] = []
        for row in alert_rows:
            alert = self._row_to_alert(row)
            snapshot = self.get_risk_snapshot(alert.risk_snapshot_id)
            work_order = self.find_work_order_by_alert(alert.alert_id)
            latest_feedback = self.latest_feedback(work_order.workorder_id) if work_order else None
            loop_review = self.find_loop_review_by_alert(alert.alert_id)
            audit_logs = self.list_audit_logs(entity_type="alert", entity_id=alert.alert_id, limit=10)
            envelopes.append(
                AlertEnvelope(
                    alert=alert,
                    risk_snapshot=snapshot,
                    work_order=work_order,
                    latest_feedback=latest_feedback,
                    loop_review=loop_review,
                    audit_logs=audit_logs,
                )
            )
        return envelopes

    def list_work_order_envelopes(self) -> list[WorkOrderEnvelope]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM work_orders ORDER BY updated_at DESC").fetchall()
        envelopes: list[WorkOrderEnvelope] = []
        for row in rows:
            work_order = self._row_to_work_order(row)
            alert = self.get_alert(work_order.alert_id)
            snapshot = self.get_risk_snapshot(alert.risk_snapshot_id)
            feedbacks = self.list_feedbacks(work_order.workorder_id)
            loop_review = self.find_loop_review_by_alert(alert.alert_id)
            envelopes.append(
                WorkOrderEnvelope(
                    work_order=work_order,
                    alert=alert,
                    risk_snapshot=snapshot,
                    feedbacks=feedbacks,
                    loop_review=loop_review,
                )
            )
        return envelopes

    def get_risk_snapshot(self, snapshot_id: str) -> RiskSnapshot:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM risk_snapshots WHERE snapshot_id = ?", (snapshot_id,)).fetchone()
            if row is None:
                raise KeyError(f"Risk snapshot {snapshot_id} not found")
            return self._row_to_risk_snapshot(row)

    def set_replay_state(
        self,
        *,
        status: ReplayStatus,
        scenario_name: str | None,
        progress: int,
        total_batches: int,
        loop_enabled: bool,
        started_at: str | None,
        current_batch: int = 0,
        current_area_id: str | None = None,
        current_mode: str | None = None,
        current_phase: str = "idle",
        current_role_key: str | None = None,
        current_role_id: str | None = None,
        current_role_step: int = 0,
        total_role_steps: int = 0,
        completed_role_steps: int = 0,
        current_summary: str | None = None,
        last_error: str | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE replay_state
                SET scenario_name = ?, status = ?, progress = ?, total_batches = ?, loop_enabled = ?, started_at = ?, last_error = ?,
                    current_batch = ?, current_area_id = ?, current_mode = ?, current_phase = ?, current_role_key = ?,
                    current_role_id = ?, current_role_step = ?, total_role_steps = ?, completed_role_steps = ?,
                    current_summary = ?, updated_at = ?
                WHERE id = 1
                """,
                (
                    scenario_name,
                    status.value,
                    progress,
                    total_batches,
                    1 if loop_enabled else 0,
                    started_at,
                    last_error,
                    current_batch,
                    current_area_id,
                    current_mode,
                    current_phase,
                    current_role_key,
                    current_role_id,
                    current_role_step,
                    total_role_steps,
                    completed_role_steps,
                    current_summary,
                    _utcnow().isoformat(),
                ),
            )

    def update_replay_state(self, **updates: Any) -> None:
        current = self.get_replay_state()
        status_value = updates.pop("status", current["status"])
        status = status_value if isinstance(status_value, ReplayStatus) else ReplayStatus(status_value)
        merged = {
            "scenario_name": updates.pop("scenario_name", current["scenario_name"]),
            "progress": updates.pop("progress", current["progress"]),
            "total_batches": updates.pop("total_batches", current["total_batches"]),
            "loop_enabled": updates.pop("loop_enabled", current["loop_enabled"]),
            "started_at": updates.pop("started_at", current["started_at"]),
            "current_batch": updates.pop("current_batch", current["current_batch"]),
            "current_area_id": updates.pop("current_area_id", current["current_area_id"]),
            "current_mode": updates.pop("current_mode", current["current_mode"]),
            "current_phase": updates.pop("current_phase", current["current_phase"]),
            "current_role_key": updates.pop("current_role_key", current["current_role_key"]),
            "current_role_id": updates.pop("current_role_id", current["current_role_id"]),
            "current_role_step": updates.pop("current_role_step", current["current_role_step"]),
            "total_role_steps": updates.pop("total_role_steps", current["total_role_steps"]),
            "completed_role_steps": updates.pop("completed_role_steps", current["completed_role_steps"]),
            "current_summary": updates.pop("current_summary", current["current_summary"]),
            "last_error": updates.pop("last_error", current["last_error"]),
        }
        if updates:
            unknown = ", ".join(sorted(updates))
            raise KeyError(f"Unknown replay state update fields: {unknown}")
        self.set_replay_state(status=status, **merged)

    def get_replay_state(self) -> dict[str, Any]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM replay_state WHERE id = 1").fetchone()
            assert row is not None
            return {
                "scenario_name": row["scenario_name"],
                "status": row["status"],
                "progress": row["progress"],
                "total_batches": row["total_batches"],
                "loop_enabled": bool(row["loop_enabled"]),
                "started_at": row["started_at"],
                "last_error": row["last_error"],
                "current_batch": row["current_batch"],
                "current_area_id": row["current_area_id"],
                "current_mode": row["current_mode"],
                "current_phase": row["current_phase"],
                "current_role_key": row["current_role_key"],
                "current_role_id": row["current_role_id"],
                "current_role_step": row["current_role_step"],
                "total_role_steps": row["total_role_steps"],
                "completed_role_steps": row["completed_role_steps"],
                "current_summary": row["current_summary"],
                "updated_at": row["updated_at"],
            }

    def set_agent_monitor_state(
        self,
        *,
        enabled: bool,
        status: AgentMonitorStatus,
        session_id: str,
        poll_interval_seconds: int,
        last_checked_at: str | None = None,
        last_briefing_at: str | None = None,
        latest_headline: str | None = None,
        latest_summary: str | None = None,
        latest_priority: str | None = None,
        last_trigger_signature: str | None = None,
        last_error: str | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE agent_monitor_state
                SET enabled = ?, status = ?, session_id = ?, poll_interval_seconds = ?, last_checked_at = ?,
                    last_briefing_at = ?, latest_headline = ?, latest_summary = ?, latest_priority = ?,
                    last_trigger_signature = ?, last_error = ?, updated_at = ?
                WHERE id = 1
                """,
                (
                    1 if enabled else 0,
                    status.value,
                    session_id,
                    poll_interval_seconds,
                    last_checked_at,
                    last_briefing_at,
                    latest_headline,
                    latest_summary,
                    latest_priority,
                    last_trigger_signature,
                    last_error,
                    _utcnow().isoformat(),
                ),
            )

    def update_agent_monitor_state(self, **updates: Any) -> None:
        current = self.get_agent_monitor_state()
        status_value = updates.pop("status", current["status"])
        status = status_value if isinstance(status_value, AgentMonitorStatus) else AgentMonitorStatus(status_value)
        merged = {
            "enabled": updates.pop("enabled", current["enabled"]),
            "session_id": updates.pop("session_id", current["session_id"]),
            "poll_interval_seconds": updates.pop("poll_interval_seconds", current["poll_interval_seconds"]),
            "last_checked_at": updates.pop("last_checked_at", current["last_checked_at"]),
            "last_briefing_at": updates.pop("last_briefing_at", current["last_briefing_at"]),
            "latest_headline": updates.pop("latest_headline", current["latest_headline"]),
            "latest_summary": updates.pop("latest_summary", current["latest_summary"]),
            "latest_priority": updates.pop("latest_priority", current["latest_priority"]),
            "last_trigger_signature": updates.pop("last_trigger_signature", current["last_trigger_signature"]),
            "last_error": updates.pop("last_error", current["last_error"]),
        }
        if updates:
            unknown = ", ".join(sorted(updates))
            raise KeyError(f"Unknown agent monitor state update fields: {unknown}")
        self.set_agent_monitor_state(status=status, **merged)

    def get_agent_monitor_state(self) -> dict[str, Any]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM agent_monitor_state WHERE id = 1").fetchone()
            assert row is not None
            return {
                "enabled": bool(row["enabled"]),
                "status": row["status"],
                "session_id": row["session_id"],
                "poll_interval_seconds": row["poll_interval_seconds"],
                "last_checked_at": row["last_checked_at"],
                "last_briefing_at": row["last_briefing_at"],
                "latest_headline": row["latest_headline"],
                "latest_summary": row["latest_summary"],
                "latest_priority": row["latest_priority"],
                "last_trigger_signature": row["last_trigger_signature"],
                "last_error": row["last_error"],
                "updated_at": row["updated_at"],
            }

    def _row_to_risk_snapshot(self, row: sqlite3.Row) -> RiskSnapshot:
        return RiskSnapshot(
            snapshot_id=row["snapshot_id"],
            area_id=row["area_id"],
            ts=datetime.fromisoformat(row["ts"]),
            score=row["score"],
            level=row["level"],
            triggered_rules=_from_json(row["triggered_rules"], []),
            explanation=row["explanation"],
            contributing_factors=_from_json(row["contributing_factors"], {}),
        )

    def _row_to_alert(self, row: sqlite3.Row) -> Alert:
        return Alert(
            alert_id=row["alert_id"],
            risk_snapshot_id=row["risk_snapshot_id"],
            area_id=row["area_id"],
            level=row["level"],
            status=row["status"],
            message=row["message"],
            suggested_actions=_from_json(row["suggested_actions"], []),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _row_to_work_order(self, row: sqlite3.Row) -> WorkOrder:
        return WorkOrder(
            workorder_id=row["workorder_id"],
            alert_id=row["alert_id"],
            type=row["type"],
            assignee=row["assignee"],
            priority=row["priority"],
            approval_status=row["approval_status"],
            execution_status=row["execution_status"],
            due_at=datetime.fromisoformat(row["due_at"]) if row["due_at"] else None,
            details=_from_json(row["details"], {}),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _row_to_feedback(self, row: sqlite3.Row) -> ExecutionFeedback:
        return ExecutionFeedback(
            feedback_id=row["feedback_id"],
            workorder_id=row["workorder_id"],
            ts=datetime.fromisoformat(row["ts"]),
            result=row["result"],
            notes=row["notes"],
            attachments=_from_json(row["attachments"], []),
        )

    def _row_to_loop_review(self, row: sqlite3.Row) -> LoopReview:
        return LoopReview(
            review_id=row["review_id"],
            alert_id=row["alert_id"],
            effectiveness=row["effectiveness"],
            residual_risk=row["residual_risk"],
            followup_action=row["followup_action"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            closed_at=datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else None,
            closure_note=row["closure_note"],
        )

    def _row_to_audit_log(self, row: sqlite3.Row) -> AuditLog:
        return AuditLog(
            log_id=row["log_id"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            stage=row["stage"],
            actor=row["actor"],
            action=row["action"],
            payload=_from_json(row["payload"], {}),
            ts=datetime.fromisoformat(row["ts"]),
        )
