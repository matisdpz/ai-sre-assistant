import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api";
import { MetricChart, type Threshold } from "../components/MetricChart";
import type { IncidentType, Rule } from "../types";
import { usePolling } from "../usePolling";

const RANGES = [
  { label: "Last 15 min", samples: 90 },
  { label: "Last hour", samples: 360 },
  { label: "Last 3 hours", samples: 1080 },
];

function thresholdOf(rules: Rule[], type: IncidentType): Threshold | undefined {
  const rule = rules.find((r) => r.type === type);
  return rule ? { warning: rule.warning, critical: rule.critical } : undefined;
}

export function ServiceMetrics() {
  const { id = "" } = useParams();
  const [samples, setSamples] = useState(90);
  const { data, error } = usePolling(
    async (signal) => {
      const [points, rules] = await Promise.all([api.metrics(id, samples, signal), api.rules(signal)]);
      return { points, rules };
    },
    5000,
    [id, samples],
  );

  return (
    <>
      <p>
        <Link to="/">← Overview</Link>
      </p>
      <div className="toolbar">
        <div>
          <h1>{id}</h1>
          <p className="muted">Simulated metrics, one sample every 10 s. Red bands: service down.</p>
        </div>
        <label>
          <span className="muted">Range </span>
          <select value={samples} onChange={(e) => setSamples(Number(e.target.value))}>
            {RANGES.map((r) => (
              <option key={r.samples} value={r.samples}>{r.label}</option>
            ))}
          </select>
        </label>
      </div>
      {error && <div className="alert">{error}</div>}
      {data && data.points.length === 0 && <p className="empty">No samples yet. Is the simulator running?</p>}
      {data && data.points.length > 0 && (
        <div className="charts">
          <MetricChart
            title="Error rate"
            unit="%"
            points={data.points}
            value={(p) => p.error_rate}
            threshold={thresholdOf(data.rules, "high_error_rate")}
          />
          <MetricChart
            title="p95 latency"
            unit="ms"
            points={data.points}
            value={(p) => p.latency_p95_ms}
            threshold={thresholdOf(data.rules, "high_latency")}
          />
          <MetricChart
            title="CPU"
            unit="%"
            points={data.points}
            value={(p) => p.cpu_pct}
            threshold={thresholdOf(data.rules, "high_cpu")}
            domainMax={100}
          />
          <MetricChart title="Request rate" unit="req/s" points={data.points} value={(p) => p.request_rate} />
        </div>
      )}
    </>
  );
}
