from fastapi import APIRouter

from app.detection import RULES
from app.schemas import RuleOut

router = APIRouter(prefix="/api/v1/rules", tags=["rules"])

# Field of the metric sample that each rule reads (service_down reads `up`).
_METRIC = {
    "high_error_rate": "error_rate",
    "high_latency": "latency_p95_ms",
    "high_cpu": "cpu_pct",
    "service_down": "up",
}


@router.get("", response_model=list[RuleOut])
def list_rules() -> list[RuleOut]:
    """Detection thresholds, so the dashboard draws the same lines the engine uses."""
    return [
        RuleOut(
            type=rule.incident_type,
            label=rule.label,
            metric=_METRIC[rule.incident_type.value],
            unit=rule.unit,
            warning=rule.warning,
            critical=rule.critical,
            breach_samples=rule.breach_samples,
            recovery_samples=rule.recovery_samples,
        )
        for rule in RULES
    ]
