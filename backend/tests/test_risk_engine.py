from datetime import datetime, timedelta

from app.config import PROJECT_ROOT, load_rule_config
from app.models import MicroseismicEvent, RiskLevel
from app.risk_engine import RiskEngine


def test_risk_engine_escalates_on_high_energy_batch():
    config = load_rule_config(PROJECT_ROOT / "backend" / "configs" / "rules.yaml")
    engine = RiskEngine(config)
    base = datetime(2026, 4, 8, 10, 0, 0)
    events = [
        MicroseismicEvent(
            event_id=f"e-{index}",
            ts=base + timedelta(seconds=index * 5),
            area_id="N-205",
            energy=9000 + index * 1200,
            magnitude=1.7 + index * 0.15,
            x=20.0 + index,
            y=10.0,
            z=-280.0,
            confidence=0.95,
            source="pytest",
        )
        for index in range(4)
    ]

    snapshot = engine.assess("N-205", events)

    assert snapshot.level in {RiskLevel.L3, RiskLevel.L4}
    assert snapshot.score >= 65
    assert snapshot.triggered_rules
    assert snapshot.explanation
    assert "N-205" in snapshot.explanation
