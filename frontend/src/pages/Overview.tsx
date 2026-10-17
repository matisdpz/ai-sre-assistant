import { Link } from "react-router-dom";

import { api } from "../api";
import { HealthDot } from "../components/Badges";
import { IncidentList } from "../components/IncidentList";
import { KpiTile } from "../components/KpiTile";
import { PageHeader } from "../components/PageHeader";
import { Sparkline } from "../components/Sparkline";
import { formatDuration } from "../format";
import type { MetricPoint, Rule } from "../types";
import { usePolling } from "../usePolling";

const SPARK_SAMPLES = 90; // 15 minutes at one sample per 10 s

async function loadOverview(signal: AbortSignal) {
  const [services, summary, open, acknowledged, rules] = await Promise.all([
    api.services(signal),
    api.summary(signal),
    api.incidents({ status: "open", limit: 200 }, signal),
    api.incidents({ status: "acknowledged", limit: 200 }, signal),
    api.rules(signal),
  ]);
  const metrics = await Promise.all(
    services.map((s) => api.metrics(s.id, { limit: SPARK_SAMPLES }, signal)),
  );
  const active = [...open, ...acknowledged].sort(
    (a, b) =>
      // Critical first, then newest first.
      Number(b.severity === "critical") - Number(a.severity === "critical") ||
      b.detected_at.localeCompare(a.detected_at),
  );
  return { services, summary, active, rules, metrics };
}

function warningOf(rules: Rule[], type: Rule["type"]) {
  return rules.find((r) => r.type === type)?.warning ?? null;
}

function latest(points: MetricPoint[], pick: (p: MetricPoint) => number, unit: string) {
  const last = [...points].reverse().find((p) => p.up);
  return last ? `${pick(last).toFixed(1)} ${unit}` : "down";
}

export function Overview() {
  const { data, error, loading, updatedAt, refresh } = usePolling(loadOverview, 5000);
  const summary = data?.summary;
  const critical = data?.active.filter((i) => i.severity === "critical").length ?? 0;
  const healthy = data?.services.filter((s) => s.active_incidents === 0).length ?? 0;

  return (
    <>
      <PageHeader title="Overview" subtitle="Simulated system · 3 services" updatedAt={updatedAt} />
      {error && <div className="alert">{error}</div>}
      {loading && !data && <p className="empty">Loading…</p>}
      {data && summary && (
        <>
          <div className="kpis">
            <KpiTile
              label="Active incidents"
              value={summary.open + summary.acknowledged}
              hint={critical ? `${critical} critical` : "none critical"}
              tone={critical ? "bad" : summary.open + summary.acknowledged ? "warn" : "good"}
            />
            <KpiTile
              label="Unacknowledged"
              value={summary.open}
              hint="waiting for someone"
              tone={summary.open ? "bad" : "good"}
            />
            <KpiTile
              label="MTTA"
              value={summary.mtta_seconds === null ? "-" : formatDuration(summary.mtta_seconds)}
              hint="mean time to acknowledge"
            />
            <KpiTile
              label="MTTR"
              value={summary.mttr_seconds === null ? "-" : formatDuration(summary.mttr_seconds)}
              hint="mean time to resolve"
            />
            <KpiTile
              label="Healthy services"
              value={`${healthy}/${data.services.length}`}
              tone={healthy === data.services.length ? "good" : "warn"}
            />
          </div>

          <section>
            <h2 className="section-title">Services</h2>
            <div className="service-grid">
              {data.services.map((service, i) => {
                const points = data.metrics[i];
                return (
                  <Link key={service.id} to={`/services/${service.id}`} className="card service-card">
                    <div className="service-head">
                      <HealthDot activeIncidents={service.active_incidents} />
                      <strong>{service.name}</strong>
                      <span className="muted small">{service.id}</span>
                    </div>
                    <div className={`service-state ${service.active_incidents ? "bad" : "ok"}`}>
                      {service.active_incidents
                        ? `${service.active_incidents} active incident${service.active_incidents > 1 ? "s" : ""}`
                        : "Operational"}
                    </div>
                    <div className="spark-row">
                      <div>
                        <div className="muted small">Error rate · {latest(points, (p) => p.error_rate, "%")}</div>
                        <Sparkline
                          label={`${service.id} error rate, last 15 minutes`}
                          values={points.map((p) => (p.up ? p.error_rate : null))}
                          threshold={warningOf(data.rules, "high_error_rate")}
                        />
                      </div>
                      <div>
                        <div className="muted small">p95 latency · {latest(points, (p) => p.latency_p95_ms, "ms")}</div>
                        <Sparkline
                          label={`${service.id} p95 latency, last 15 minutes`}
                          values={points.map((p) => (p.up ? p.latency_p95_ms : null))}
                          threshold={warningOf(data.rules, "high_latency")}
                        />
                      </div>
                    </div>
                  </Link>
                );
              })}
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <h2>Active incidents</h2>
              <Link to="/incidents">View all →</Link>
            </div>
            <IncidentList incidents={data.active} empty="No active incident. All quiet." onChange={refresh} />
          </section>
        </>
      )}
    </>
  );
}
