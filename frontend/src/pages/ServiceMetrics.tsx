import { Link, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api";
import { HealthDot } from "../components/Badges";
import { IncidentList } from "../components/IncidentList";
import { MetricChart, type Threshold } from "../components/MetricChart";
import { PageHeader } from "../components/PageHeader";
import { TYPE_LABELS } from "../format";
import type { IncidentType, Rule } from "../types";
import { usePolling } from "../usePolling";

const RANGES = [
  { key: "15m", label: "15m", samples: 90 },
  { key: "1h", label: "1h", samples: 360 },
  { key: "3h", label: "3h", samples: 1080 },
];

function thresholdOf(rules: Rule[], type: IncidentType): Threshold | undefined {
  const rule = rules.find((r) => r.type === type);
  return rule ? { warning: rule.warning, critical: rule.critical } : undefined;
}

/** A Grafana-like service dashboard: range picker, one chart per metric, incident markers. */
export function ServiceMetrics() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const range = RANGES.find((r) => r.key === params.get("range")) ?? RANGES[0];

  const { data, error, updatedAt, refresh } = usePolling(
    async (signal) => {
      const [points, rules, incidents, services] = await Promise.all([
        api.metrics(id, { limit: range.samples }, signal),
        api.rules(signal),
        api.incidents({ serviceId: id, limit: 20 }, signal),
        api.services(signal),
      ]);
      return { points, rules, incidents, service: services.find((s) => s.id === id) };
    },
    5000,
    [id, range.samples],
  );

  const markers = (data?.incidents ?? []).map((i) => ({ ts: i.started_at, label: TYPE_LABELS[i.type] }));

  return (
    <>
      <PageHeader
        title={
          <span className="title-with-dot">
            {data?.service && <HealthDot activeIncidents={data.service.active_incidents} />}
            {data?.service?.name ?? id}
          </span>
        }
        subtitle={data?.service?.description}
        updatedAt={updatedAt}
      >
        <div className="segmented" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button
              key={r.key}
              type="button"
              className={r.key === range.key ? "active" : ""}
              aria-pressed={r.key === range.key}
              onClick={() => setParams({ range: r.key }, { replace: true })}
            >
              {r.label}
            </button>
          ))}
        </div>
      </PageHeader>
      <p className="muted small legend">
        Simulated metrics, one sample every 10 s. <span className="legend-swatch down" /> service down
        <span className="legend-swatch marker" /> incident start
      </p>
      {error && <div className="alert">{error}</div>}
      {data && data.points.length === 0 && (
        <p className="empty">No samples yet. Is the simulator running?</p>
      )}
      {data && data.points.length > 0 && (
        <div className="charts">
          <MetricChart
            title="Error rate"
            unit="%"
            points={data.points}
            value={(p) => p.error_rate}
            threshold={thresholdOf(data.rules, "high_error_rate")}
            markers={markers}
          />
          <MetricChart
            title="p95 latency"
            unit="ms"
            points={data.points}
            value={(p) => p.latency_p95_ms}
            threshold={thresholdOf(data.rules, "high_latency")}
            markers={markers}
          />
          <MetricChart
            title="CPU"
            unit="%"
            points={data.points}
            value={(p) => p.cpu_pct}
            threshold={thresholdOf(data.rules, "high_cpu")}
            domainMax={100}
            markers={markers}
          />
          <MetricChart title="Request rate" unit="req/s" points={data.points} value={(p) => p.request_rate} markers={markers} />
        </div>
      )}
      {data && (
        <section className="card">
          <div className="card-header">
            <h2>Recent incidents</h2>
            <Link to={`/incidents?status=all&service=${id}`}>View all →</Link>
          </div>
          <IncidentList incidents={data.incidents.slice(0, 8)} empty="No incident on this service." onChange={refresh} />
        </section>
      )}
    </>
  );
}
