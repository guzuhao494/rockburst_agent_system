from __future__ import annotations

from uuid import uuid4

from .config import RuleConfig
from .models import MicroseismicEvent, RiskLevel, RiskSnapshot


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


class RiskEngine:
    def __init__(self, rule_config: RuleConfig) -> None:
        self.rule_config = rule_config

    def assess(self, area_id: str, events: list[MicroseismicEvent]) -> RiskSnapshot:
        if not events:
            raise ValueError("风险评估至少需要一条事件数据")

        thresholds = self.rule_config.thresholds_for(area_id)
        energy_sum = sum(event.energy for event in events)
        peak_energy = max(event.energy for event in events)
        max_magnitude = max(event.magnitude for event in events)
        event_count = len(events)
        avg_confidence = sum(event.confidence for event in events) / event_count
        latest_ts = max(event.ts for event in events)

        weights = self.rule_config.weights
        contributions = {
            "energy_sum": clamp(energy_sum / thresholds.energy_sum.L4, 0.0, 1.2) * weights["energy_sum"] * 100,
            "peak_energy": clamp(peak_energy / thresholds.peak_energy.L4, 0.0, 1.2) * weights["peak_energy"] * 100,
            "event_count": clamp(event_count / thresholds.event_count.L4, 0.0, 1.2) * weights["event_count"] * 100,
            "magnitude": clamp(max_magnitude / thresholds.magnitude.L4, 0.0, 1.2) * weights["magnitude"] * 100,
        }
        confidence_penalty = max(0.0, self.rule_config.min_confidence - avg_confidence) * weights["confidence_penalty"] * 100
        score = clamp(sum(contributions.values()) - confidence_penalty, 0.0, 100.0)

        triggered_rules: list[str] = []
        highest_trigger_rank = 1
        metrics = {
            "energy_sum": (energy_sum, thresholds.energy_sum),
            "peak_energy": (peak_energy, thresholds.peak_energy),
            "event_count": (event_count, thresholds.event_count),
            "magnitude": (max_magnitude, thresholds.magnitude),
        }
        for label, (value, band) in metrics.items():
            if value >= band.L4:
                highest_trigger_rank = max(highest_trigger_rank, 4)
                triggered_rules.append(f"{label} 达到 L4 阈值（{value:.2f}）")
            elif value >= band.L3:
                highest_trigger_rank = max(highest_trigger_rank, 3)
                triggered_rules.append(f"{label} 达到 L3 阈值（{value:.2f}）")
            elif value >= band.L2:
                highest_trigger_rank = max(highest_trigger_rank, 2)
                triggered_rules.append(f"{label} 达到 L2 阈值（{value:.2f}）")

        level = self._score_to_level(score)
        if highest_trigger_rank > self._level_rank(level):
            level = {2: RiskLevel.L2, 3: RiskLevel.L3, 4: RiskLevel.L4}.get(highest_trigger_rank, RiskLevel.L1)

        explanation = (
            f"区域 {area_id} 本批次处理了 {event_count} 条有效微震事件，"
            f"累计能量 {energy_sum:.0f} J，峰值能量 {peak_energy:.0f} J，"
            f"最大震级 {max_magnitude:.2f}，平均置信度 {avg_confidence:.2f}。"
        )
        if triggered_rules:
            explanation += f"触发规则：{'；'.join(triggered_rules)}。"
        else:
            explanation += "本批次未触发显著阈值规则。"
        explanation += f"综合评分 {score:.1f}，判定等级为 {level.value}。"

        return RiskSnapshot(
            snapshot_id=f"risk-{uuid4().hex[:12]}",
            area_id=area_id,
            ts=latest_ts,
            score=round(score, 2),
            level=level,
            triggered_rules=triggered_rules,
            explanation=explanation,
            contributing_factors={name: round(value, 2) for name, value in contributions.items()},
        )

    def suggested_actions(self, level: RiskLevel) -> list[str]:
        return list(self.rule_config.action_templates.get(level.value, []))

    def work_order_template(self, level: RiskLevel) -> dict[str, object] | None:
        template = self.rule_config.work_order_templates.get(level.value)
        return template.model_dump() if template else None

    def _score_to_level(self, score: float) -> RiskLevel:
        boundaries = self.rule_config.level_boundaries
        if score >= boundaries["L4"]:
            return RiskLevel.L4
        if score >= boundaries["L3"]:
            return RiskLevel.L3
        if score >= boundaries["L2"]:
            return RiskLevel.L2
        return RiskLevel.L1

    def _level_rank(self, level: RiskLevel) -> int:
        return {"L1": 1, "L2": 2, "L3": 3, "L4": 4}[level.value]
