import { Link } from "react-router-dom";

import { api } from "../api";
import { Annunciator } from "../components/Annunciator";
import { IncidentList } from "../components/IncidentList";
import { PageHeader } from "../components/PageHeader";
import { formatDuration } from "../format";
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

export function Overview() {
  const { data, error, loading, updatedAt, refresh } = usePolling(loadOverview, 5000);
  const summary = data?.summary;
  const critical = data?.active.filter((i) => i.severity === "critical").length ?? 0;
  const healthy = data?.services.filter((s) => s.active_incidents === 0).length ?? 0;

  return (
    <>
      <PageHeader title="Overview" subtitle="Simulated system, live detection" updatedAt={updatedAt} />
      {error && <div className="alert">{error}</div>}
      {loading && !data && <p className="empty">Loading…</p>}
      {data && summary && (
        <>
          <section className="panel annunciator-panel" aria-labelledby="ann-title">
            <div className="panel-head">
              <h2 id="ann-title">Detection status</h2>
              <p className="muted small">
                One lamp per rule and service. A lit lamp is an unresolved incident; filled means nobody has acknowledged it yet.
              </p>
            </div>
            <Annunciator
              services={data.services}
              metrics={data.metrics}
              rules={data.rules}
              active={data.active}
            />
            <dl className="readouts">
              <div className={critical ? "bad" : ""}>
                <dt>Active incidents</dt>
                <dd>
                  {summary.open + summary.acknowledged}
                  <span className="muted small">{critical ? `${critical} critical` : "none critical"}</span>
                </dd>
              </div>
              <div className={summary.open ? "bad" : ""}>
                <dt>Not acknowledged</dt>
                <dd>{summary.open}</dd>
              </div>
              <div>
                <dt title="Mean time to acknowledge">MTTA</dt>
                <dd>{summary.mtta_seconds === null ? "-" : formatDuration(summary.mtta_seconds)}</dd>
              </div>
              <div>
                <dt title="Mean time to resolve">MTTR</dt>
                <dd>{summary.mttr_seconds === null ? "-" : formatDuration(summary.mttr_seconds)}</dd>
              </div>
              <div>
                <dt>Healthy services</dt>
                <dd>
                  {healthy}/{data.services.length}
                </dd>
              </div>
            </dl>
          </section>

          <section className="panel">
            <div className="panel-head row">
              <h2>Active incidents</h2>
              <Link to="/incidents">View all incidents</Link>
            </div>
            <IncidentList incidents={data.active} empty="No active incident. All lamps are dark." onChange={refresh} />
          </section>
        </>
      )}
    </>
  );
}
