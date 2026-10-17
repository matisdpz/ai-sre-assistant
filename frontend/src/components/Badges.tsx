import type { Hypothesis, IncidentStatus, Severity } from "../types";

// Status colors always come with a text label: color never carries meaning alone.

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`badge sev-${severity}`}>
      <span className="dot" aria-hidden="true" />
      {severity === "critical" ? "Critical" : "Warning"}
    </span>
  );
}

const STATUS_LABEL: Record<IncidentStatus, string> = {
  open: "Triggered",
  acknowledged: "Acknowledged",
  resolved: "Resolved",
};

export function StatusBadge({ status }: { status: IncidentStatus }) {
  return <span className={`pill status-${status}`}>{STATUS_LABEL[status]}</span>;
}

export function HealthDot({ activeIncidents }: { activeIncidents: number }) {
  const healthy = activeIncidents === 0;
  return (
    <span
      className={`health-dot ${healthy ? "ok" : "bad"}`}
      title={healthy ? "Healthy" : `${activeIncidents} active incident(s)`}
      aria-label={healthy ? "Healthy" : `${activeIncidents} active incidents`}
    />
  );
}

export function ConfidenceBadge({ confidence }: { confidence: Hypothesis["confidence"] }) {
  return <span className={`pill confidence-${confidence}`}>{confidence} confidence</span>;
}
