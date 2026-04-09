from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class AppSettings:
    project_root: Path
    data_dir: Path
    db_path: Path
    rules_path: Path
    scenario_dir: Path
    uploads_dir: Path
    cors_origins: tuple[str, ...]
    workflow_runtime: str
    openclaw_thinking: str
    openclaw_timeout_seconds: int

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.scenario_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


def get_settings() -> AppSettings:
    data_dir = Path(os.getenv("APP_DATA_DIR", PROJECT_ROOT / "backend" / "data"))
    db_path = Path(os.getenv("APP_DB_PATH", data_dir / "rockburst.db"))
    rules_path = Path(os.getenv("APP_RULES_PATH", PROJECT_ROOT / "backend" / "configs" / "rules.yaml"))
    scenario_dir = Path(os.getenv("APP_SCENARIO_DIR", data_dir / "scenarios"))
    uploads_dir = Path(os.getenv("APP_UPLOADS_DIR", data_dir / "uploads"))
    cors_origins = tuple(
        origin.strip()
        for origin in os.getenv(
            "APP_CORS_ORIGINS",
            "http://localhost:5173,http://localhost:4173,http://127.0.0.1:5173,http://127.0.0.1:4173",
        ).split(",")
        if origin.strip()
    )
    workflow_runtime = os.getenv("APP_WORKFLOW_RUNTIME", "openclaw").strip().lower() or "openclaw"
    openclaw_thinking = os.getenv("APP_OPENCLAW_THINKING", "off").strip().lower() or "off"
    openclaw_timeout_seconds = int(os.getenv("APP_OPENCLAW_TIMEOUT_SECONDS", "180"))
    settings = AppSettings(
        project_root=PROJECT_ROOT,
        data_dir=data_dir,
        db_path=db_path,
        rules_path=rules_path,
        scenario_dir=scenario_dir,
        uploads_dir=uploads_dir,
        cors_origins=cors_origins,
        workflow_runtime=workflow_runtime,
        openclaw_thinking=openclaw_thinking,
        openclaw_timeout_seconds=openclaw_timeout_seconds,
    )
    settings.ensure_directories()
    return settings


class ThresholdBand(BaseModel):
    L2: float
    L3: float
    L4: float


class AreaThresholds(BaseModel):
    energy_sum: ThresholdBand
    peak_energy: ThresholdBand
    event_count: ThresholdBand
    magnitude: ThresholdBand


class WorkOrderTemplate(BaseModel):
    type: str
    priority: str
    due_in_hours: int
    checklist: list[str] = Field(default_factory=list)


class RuleConfig(BaseModel):
    min_confidence: float
    level_boundaries: dict[str, float]
    weights: dict[str, float]
    thresholds: dict[str, AreaThresholds]
    action_templates: dict[str, list[str]]
    work_order_templates: dict[str, WorkOrderTemplate]
    escalation_sla_minutes: dict[str, int]

    def thresholds_for(self, area_id: str) -> AreaThresholds:
        return self.thresholds.get(area_id, self.thresholds["default"])


def load_rule_config(path: Path) -> RuleConfig:
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    return RuleConfig.model_validate(raw)
