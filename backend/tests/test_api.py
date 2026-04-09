from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings, PROJECT_ROOT
from app.main import create_app


@pytest.fixture()
def client(tmp_path: Path):
    data_dir = tmp_path / "data"
    scenario_dir = data_dir / "scenarios"
    uploads_dir = data_dir / "uploads"
    configs_dir = tmp_path / "configs"
    data_dir.mkdir(parents=True, exist_ok=True)
    scenario_dir.mkdir(parents=True, exist_ok=True)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    configs_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy(PROJECT_ROOT / "backend" / "configs" / "rules.yaml", configs_dir / "rules.yaml")
    for file_path in (PROJECT_ROOT / "backend" / "data" / "scenarios").glob("*.json"):
        shutil.copy(file_path, scenario_dir / file_path.name)

    settings = AppSettings(
        project_root=PROJECT_ROOT,
        data_dir=data_dir,
        db_path=data_dir / "rockburst-test.db",
        rules_path=configs_dir / "rules.yaml",
        scenario_dir=scenario_dir,
        uploads_dir=uploads_dir,
        cors_origins=("http://localhost:5173",),
    )

    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def test_ingest_filters_low_confidence_and_duplicates(client: TestClient):
    response = client.post(
        "/ingest/microseismic-events",
        json={
            "events": [
                {
                    "event_id": "dup-1",
                    "ts": "2026-04-08T09:00:00",
                    "area_id": "N-101",
                    "energy": 3200,
                    "magnitude": 0.95,
                    "x": 12.0,
                    "y": 5.0,
                    "z": -321.0,
                    "confidence": 0.91,
                    "source": "pytest",
                },
                {
                    "event_id": "dup-1",
                    "ts": "2026-04-08T09:00:01",
                    "area_id": "N-101",
                    "energy": 3200,
                    "magnitude": 0.95,
                    "x": 12.0,
                    "y": 5.0,
                    "z": -321.0,
                    "confidence": 0.91,
                    "source": "pytest",
                },
                {
                    "event_id": "low-confidence",
                    "ts": "2026-04-08T09:00:02",
                    "area_id": "N-101",
                    "energy": 6000,
                    "magnitude": 1.2,
                    "x": 12.8,
                    "y": 5.5,
                    "z": -320.3,
                    "confidence": 0.45,
                    "source": "pytest",
                },
                {
                    "event_id": "ok-2",
                    "ts": "2026-04-08T09:00:04",
                    "area_id": "N-101",
                    "energy": 7200,
                    "magnitude": 1.3,
                    "x": 13.2,
                    "y": 5.7,
                    "z": -319.9,
                    "confidence": 0.94,
                    "source": "pytest",
                },
            ]
        },
    )

    assert response.status_code == 200
    case = response.json()["cases"][0]
    assert case["quality_report"]["received"] == 4
    assert case["quality_report"]["accepted"] == 2
    assert case["quality_report"]["dropped"] == 2
    assert case["risk_snapshot"]["level"] in {"L1", "L2", "L3", "L4"}


def test_alert_to_loop_close_flow(client: TestClient):
    ingest = client.post(
        "/ingest/microseismic-events",
        json={
            "events": [
                {
                    "event_id": "flow-1",
                    "ts": "2026-04-08T10:00:00",
                    "area_id": "N-205",
                    "energy": 9500,
                    "magnitude": 1.7,
                    "x": 25.2,
                    "y": 12.1,
                    "z": -286.0,
                    "confidence": 0.95,
                    "source": "pytest",
                },
                {
                    "event_id": "flow-2",
                    "ts": "2026-04-08T10:00:05",
                    "area_id": "N-205",
                    "energy": 10200,
                    "magnitude": 1.8,
                    "x": 25.4,
                    "y": 12.3,
                    "z": -285.8,
                    "confidence": 0.96,
                    "source": "pytest",
                },
                {
                    "event_id": "flow-3",
                    "ts": "2026-04-08T10:00:10",
                    "area_id": "N-205",
                    "energy": 11000,
                    "magnitude": 1.95,
                    "x": 25.6,
                    "y": 12.5,
                    "z": -285.4,
                    "confidence": 0.97,
                    "source": "pytest",
                },
                {
                    "event_id": "flow-4",
                    "ts": "2026-04-08T10:00:15",
                    "area_id": "N-205",
                    "energy": 11800,
                    "magnitude": 2.1,
                    "x": 25.8,
                    "y": 12.7,
                    "z": -285.1,
                    "confidence": 0.95,
                    "source": "pytest",
                },
            ]
        },
    )

    assert ingest.status_code == 200
    case = ingest.json()["cases"][0]
    assert case["alert"] is not None
    assert case["work_order"] is not None

    alert_id = case["alert"]["alert_id"]
    workorder_id = case["work_order"]["workorder_id"]

    approve = client.post(f"/alerts/{alert_id}/approve", json={"actor": "pytest", "note": "approved for execution"})
    assert approve.status_code == 200
    assert approve.json()["alert"]["status"] == "Approved"

    dispatch = client.post(
        f"/work-orders/{workorder_id}/dispatch",
        json={"actor": "pytest", "assignee": "emergency-inspection-team", "dispatch_note": "move to site immediately"},
    )
    assert dispatch.status_code == 200
    assert dispatch.json()["work_order"]["execution_status"] == "dispatched"

    feedback = client.post(
        f"/work-orders/{workorder_id}/feedback",
        json={"actor": "pytest", "result": "risk_not_reduced", "notes": "risk stays high after action", "attachments": []},
    )
    assert feedback.status_code == 200
    review = feedback.json()["loop_review"]
    assert review is not None
    assert review["status"] == "open"

    close = client.post(
        f"/loop-reviews/{review['review_id']}/close",
        json={"actor": "pytest", "closure_note": "secondary mitigation accepted and loop closed"},
    )
    assert close.status_code == 200
    assert close.json()["alert"]["status"] == "Closed"


def test_workflow_records_tool_calls(client: TestClient):
    ingest = client.post(
        "/ingest/microseismic-events",
        json={
            "events": [
                {
                    "event_id": "tool-1",
                    "ts": "2026-04-08T11:00:00",
                    "area_id": "N-101",
                    "energy": 4200,
                    "magnitude": 1.05,
                    "x": 12.1,
                    "y": 5.2,
                    "z": -320.8,
                    "confidence": 0.93,
                    "source": "pytest",
                },
                {
                    "event_id": "tool-2",
                    "ts": "2026-04-08T11:00:05",
                    "area_id": "N-101",
                    "energy": 4600,
                    "magnitude": 1.12,
                    "x": 12.4,
                    "y": 5.4,
                    "z": -320.5,
                    "confidence": 0.94,
                    "source": "pytest",
                },
            ]
        },
    )

    assert ingest.status_code == 200

    summary = client.get("/dashboard/summary")
    assert summary.status_code == 200
    tool_logs = [item for item in summary.json()["recent_audit"] if item["entity_type"] == "tool"]
    assert tool_logs
    assert tool_logs[0]["action"] == "tool_completed"
    assert "tool_name" in tool_logs[0]["payload"]


def test_agent_briefing_prioritizes_pending_approval(client: TestClient):
    ingest = client.post(
        "/ingest/microseismic-events",
        json={
            "events": [
                {
                    "event_id": "briefing-1",
                    "ts": "2026-04-08T12:00:00",
                    "area_id": "N-205",
                    "energy": 9800,
                    "magnitude": 1.7,
                    "x": 25.2,
                    "y": 12.1,
                    "z": -286.0,
                    "confidence": 0.95,
                    "source": "pytest",
                },
                {
                    "event_id": "briefing-2",
                    "ts": "2026-04-08T12:00:05",
                    "area_id": "N-205",
                    "energy": 10400,
                    "magnitude": 1.85,
                    "x": 25.4,
                    "y": 12.3,
                    "z": -285.8,
                    "confidence": 0.96,
                    "source": "pytest",
                },
                {
                    "event_id": "briefing-3",
                    "ts": "2026-04-08T12:00:10",
                    "area_id": "N-205",
                    "energy": 11100,
                    "magnitude": 1.95,
                    "x": 25.6,
                    "y": 12.5,
                    "z": -285.4,
                    "confidence": 0.97,
                    "source": "pytest",
                },
                {
                    "event_id": "briefing-4",
                    "ts": "2026-04-08T12:00:15",
                    "area_id": "N-205",
                    "energy": 12000,
                    "magnitude": 2.1,
                    "x": 25.8,
                    "y": 12.7,
                    "z": -285.1,
                    "confidence": 0.95,
                    "source": "pytest",
                },
            ]
        },
    )

    assert ingest.status_code == 200

    briefing = client.get("/agent/briefing")
    assert briefing.status_code == 200
    payload = briefing.json()
    assert payload["headline"]
    assert payload["priorities"]
    assert payload["recommended_actions"]
    assert payload["recommended_actions"][0]["action_type"] == "review_alert"
