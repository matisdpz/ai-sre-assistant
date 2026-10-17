import { Fragment, type CSSProperties } from "react";
import { Link } from "react-router-dom";

import { TYPE_LABELS } from "../format";
import type { Incident, IncidentType, MetricPoint, Rule, Service } from "../types";
import { Sparkline } from "./Sparkline";

/**
 * Annunciator panel, as in a cockpit: one lamp per detection rule and service. A lamp is
 * dark while the rule is quiet and lights up while an incident for it is unresolved.
 * Filled = not acknowledged; outlined = acknowledged. Recovered metrics add a note only:
 * the incident stays on the board until a person resolves it.
 *
 * Items are emitted column by column (rule labels, then one column per service) so the
 * grid can flow by columns on wide screens and stack per service on phones.
 */

const RULES: IncidentType[] = ["high_error_rate", "high_latency", "high_cpu", "service_down"];

type MetricRule = Exclude<IncidentType, "service_down">;
const READING: Record<MetricRule, { pick: (p: MetricPoint) => number; unit: string }> = {
  high_error_rate: { pick: (p) => p.error_rate, unit: "%" },
  high_latency: { pick: (p) => p.latency_p95_ms, unit: "ms" },
  high_cpu: { pick: (p) => p.cpu_pct, unit: "%" },
};

function ruleDescription(rule: Rule | undefined): string | null {
  if (!rule) return null;
  if (rule.type === "service_down") return `down for ${rule.breach_samples} samples`;
  const levels = rule.warning === null ? `${rule.critical}` : `${rule.warning} / ${rule.critical}`;
  return `≥ ${levels} ${rule.unit}, ${rule.breach_samples} samples`;
}

function latestReading(points: MetricPoint[], type: IncidentType): string {
  const last = points[points.length - 1];
  if (!last) return "no data";
  if (type === "service_down") return last.up ? "Up" : "Down";
  const up = [...points].reverse().find((p) => p.up);
  const { pick, unit } = READING[type];
  return up ? `${pick(up).toFixed(1)} ${unit}` : "down";
}


/** Samples as thin bars: a gap in availability reads at a glance. */
function UptimeBar({ points, label }: { points: MetricPoint[]; label: string }) {
  if (points.length === 0) return <svg className="uptime" aria-label={`${label}: no data`} />;
  return (
    <svg
      className="uptime"
      viewBox={`0 0 ${points.length} 1`}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
    >
      {points.map((p, i) => (
        <rect key={p.ts} x={i} width={1} height={1} className={p.up ? "up" : "down"} />
      ))}
    </svg>
  );
}

function Lamp({
  service,
  type,
  incident,
  points,
  rule,
  index,
}: {
  service: Service;
  type: IncidentType;
  incident: Incident | undefined;
  points: MetricPoint[];
  rule: Rule | undefined;
  index: number;
}) {
  const label = TYPE_LABELS[type];
  const className = incident
    ? `lamp sev-${incident.severity} status-${incident.status}${incident.recovered_at ? " is-recovered" : ""}`
    : "lamp is-off";
  const trend =
    type === "service_down" ? (
      <UptimeBar points={points} label={`${service.id} availability, last 15 minutes`} />
    ) : (
      <Sparkline
        label={`${service.id} ${label.toLowerCase()}, last 15 minutes`}
        values={points.map((p) => (p.up ? READING[type].pick(p) : null))}
        threshold={rule?.warning}
      />
    );

  return (
    <Link
      to={incident ? `/incidents/${incident.id}` : `/services/${service.id}`}
      className={className}
      style={{ "--i": index } as CSSProperties}
    >
      <span className="lamp-rule">{label}</span>
      <span className="sr-only"> on {service.id}: </span>
      <span className="lamp-head">
        <span className="lamp-state">
          {incident ? (incident.severity === "critical" ? "Critical" : "Warning") : "Normal"}
        </span>
        <span className="lamp-reading">{latestReading(points, type)}</span>
      </span>
      {incident && (
        <span className="lamp-status">
          {incident.status === "open" ? "Not acknowledged" : "Acknowledged"}
        </span>
      )}
      {incident?.recovered_at && <span className="lamp-recovered">Metrics recovered</span>}
      {trend}
    </Link>
  );
}

export function Annunciator({
  services,
  metrics,
  rules,
  active,
}: {
  services: Service[];
  metrics: MetricPoint[][];
  rules: Rule[];
  active: Incident[];
}) {
  return (
    <div className="annunciator" style={{ "--services": services.length } as CSSProperties}>
      <div className="ann-corner" aria-hidden="true" />
      {RULES.map((type) => (
        <div key={type} className="ann-rule">
          <strong>{TYPE_LABELS[type]}</strong>
          <span className="muted small">{ruleDescription(rules.find((r) => r.type === type))}</span>
        </div>
      ))}
      {services.map((service, col) => (
        <Fragment key={service.id}>
          <div className="ann-service">
            <Link to={`/services/${service.id}`} className="ann-service-name">
              {service.name}
            </Link>
            <span className={`ann-service-state ${service.active_incidents ? "bad" : "ok"}`}>
              {service.active_incidents
                ? `${service.active_incidents} active incident${service.active_incidents > 1 ? "s" : ""}`
                : "Operational"}
            </span>
          </div>
          {RULES.map((type, row) => (
            <Lamp
              key={type}
              service={service}
              type={type}
              incident={active.find((i) => i.service_id === service.id && i.type === type)}
              points={metrics[col] ?? []}
              rule={rules.find((r) => r.type === type)}
              index={col * RULES.length + row}
            />
          ))}
        </Fragment>
      ))}
    </div>
  );
}
