from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from .database import Database
from .models import MicroseismicEvent, ReplayStartRequest, ReplayStatus, ScenarioMetadata
from .time_utils import utc_now


class ReplayController:
    def __init__(
        self,
        scenario_dir: Path,
        db: Database,
        ingest_batch: Callable[[list[MicroseismicEvent]], Awaitable[Any]],
    ) -> None:
        self.scenario_dir = scenario_dir
        self.db = db
        self.ingest_batch = ingest_batch
        self._task: asyncio.Task[None] | None = None

    def list_scenarios(self) -> list[ScenarioMetadata]:
        scenarios: list[ScenarioMetadata] = []
        for path in sorted(self.scenario_dir.glob("*.json")):
            payload = self._load_raw(path.stem)
            areas = sorted({event["area_id"] for batch in payload["batches"] for event in batch["events"]})
            scenarios.append(
                ScenarioMetadata(
                    name=payload["name"],
                    description=payload["description"],
                    batches=len(payload["batches"]),
                    areas=areas,
                )
            )
        return scenarios

    async def start(self, request: ReplayStartRequest) -> dict[str, object]:
        if self._task and not self._task.done():
            raise RuntimeError("Replay already running")

        payload = self._load_raw(request.scenario_name)
        started_at = utc_now().isoformat()
        self.db.set_replay_state(
            status=ReplayStatus.RUNNING,
            scenario_name=request.scenario_name,
            progress=0,
            total_batches=len(payload["batches"]),
            loop_enabled=request.loop,
            started_at=started_at,
            last_error=None,
        )
        self._task = asyncio.create_task(self._run(payload, request))
        return self.db.get_replay_state()

    async def stop(self) -> dict[str, object]:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        current = self.db.get_replay_state()
        self.db.set_replay_state(
            status=ReplayStatus.STOPPED,
            scenario_name=current["scenario_name"],
            progress=current["progress"],
            total_batches=current["total_batches"],
            loop_enabled=current["loop_enabled"],
            started_at=current["started_at"],
            last_error=None,
        )
        return self.db.get_replay_state()

    def status(self) -> dict[str, object]:
        return self.db.get_replay_state()

    def _load_raw(self, scenario_name: str) -> dict[str, object]:
        path = self.scenario_dir / f"{scenario_name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Scenario {scenario_name} not found")
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    async def _run(self, payload: dict[str, object], request: ReplayStartRequest) -> None:
        batches = payload["batches"]
        try:
            while True:
                for index, batch in enumerate(batches, start=1):
                    await asyncio.sleep((batch.get("wait_ms") or request.interval_ms) / 1000)
                    events = [MicroseismicEvent.model_validate(item) for item in batch["events"]]
                    await self.ingest_batch(events)
                    self.db.set_replay_state(
                        status=ReplayStatus.RUNNING,
                        scenario_name=request.scenario_name,
                        progress=index,
                        total_batches=len(batches),
                        loop_enabled=request.loop,
                        started_at=self.db.get_replay_state()["started_at"],
                        last_error=None,
                    )
                if not request.loop:
                    break
            self.db.set_replay_state(
                status=ReplayStatus.STOPPED,
                scenario_name=request.scenario_name,
                progress=len(batches),
                total_batches=len(batches),
                loop_enabled=request.loop,
                started_at=self.db.get_replay_state()["started_at"],
                last_error=None,
            )
        except asyncio.CancelledError:
            self.db.set_replay_state(
                status=ReplayStatus.STOPPED,
                scenario_name=request.scenario_name,
                progress=self.db.get_replay_state()["progress"],
                total_batches=len(batches),
                loop_enabled=request.loop,
                started_at=self.db.get_replay_state()["started_at"],
                last_error=None,
            )
            raise
        except Exception as exc:
            current = self.db.get_replay_state()
            self.db.set_replay_state(
                status=ReplayStatus.FAILED,
                scenario_name=request.scenario_name,
                progress=current["progress"],
                total_batches=len(batches),
                loop_enabled=request.loop,
                started_at=current["started_at"],
                last_error=str(exc),
            )
