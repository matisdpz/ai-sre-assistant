import type { IncidentStatus, Severity } from "../types";

// Status colors always come with a text label: color never carries meaning alone.

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`badge ${severity}`}>
      <span className="dot" aria-hidden="true" />
      {severity === "critical" ? "Critical" : "Warning"}
    </span>
  );
}

const STATUS_LABEL: Record<IncidentStatus, string> = {
  open: "Open",
  acknowledged: "Acknowledged",
  resolved: "Resolved",
};

export function StatusBadge({ status }: { status: IncidentStatus }) {
  return (
    <span className={`badge ${status === "resolved" ? "good" : "neutral"}`}>
      <span className="dot" aria-hidden="true" />
      {STATUS_LABEL[status]}
    </span>
  );
}

export function HealthBadge({ activeIncidents }: { activeIncidents: number }) {
  return activeIncidents === 0 ? (
    <span className="badge good">
      <span className="dot" aria-hidden="true" />
      Healthy
    </span>
  ) : (
    <span className="badge critical">
      <span className="dot" aria-hidden="true" />
      {activeIncidents} active {activeIncidents === 1 ? "incident" : "incidents"}
    </span>
  );
}
