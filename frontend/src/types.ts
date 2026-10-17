// Mirrors the backend response schemas (backend/app/schemas.py).

export type Severity = "warning" | "critical";
export type IncidentStatus = "open" | "acknowledged" | "resolved";
export type IncidentType = "high_error_rate" | "high_latency" | "high_cpu" | "service_down";
export type EventKind = "detected" | "escalated" | "recovered" | "retriggered" | "status_changed";

export interface Service {
  id: string;
  name: string;
  description: string;
  active_incidents: number;
}

export interface MetricPoint {
  ts: string;
  request_rate: number;
  error_rate: number;
  latency_p95_ms: number;
  cpu_pct: number;
  mem_pct: number;
  up: boolean;
  source: string;
}

export interface Incident {
  id: string;
  service_id: string;
  type: IncidentType;
  severity: Severity;
  status: IncidentStatus;
  summary: string;
  threshold: number;
  peak_value: number;
  started_at: string;
  detected_at: string;
  recovered_at: string | null;
  resolved_at: string | null;
  updated_at: string;
}

export interface IncidentEvent {
  id: number;
  kind: EventKind;
  actor: "system" | "user";
  from_status: IncidentStatus | null;
  to_status: IncidentStatus | null;
  note: string | null;
  created_at: string;
}

export interface IncidentDetail extends Incident {
  evidence: { ts: string; value: number; up: boolean }[];
  events: IncidentEvent[];
}

export interface Rule {
  type: IncidentType;
  label: string;
  metric: keyof MetricPoint;
  unit: string;
  warning: number | null;
  critical: number;
  breach_samples: number;
  recovery_samples: number;
}
