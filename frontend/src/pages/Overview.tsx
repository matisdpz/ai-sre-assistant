import { Link } from "react-router-dom";

import { api } from "../api";
import { HealthBadge } from "../components/Badges";
import { IncidentTable } from "../components/IncidentTable";
import { usePolling } from "../usePolling";

const REFRESH_MS = 5000;

async function loadOverview(signal: AbortSignal) {
  const [services, open, acknowledged, resolved] = await Promise.all([
    api.services(signal),
    api.incidents({ status: "open" }, signal),
    api.incidents({ status: "acknowledged" }, signal),
    api.incidents({ status: "resolved", limit: 10 }, signal),
  ]);
  const active = [...open, ...acknowledged].sort((a, b) =>
    b.detected_at.localeCompare(a.detected_at),
  );
  return { services, active, resolved };
}

export function Overview() {
  const { data, error, loading } = usePolling(loadOverview, REFRESH_MS);

  return (
    <>
      <h1>Overview</h1>
      <p className="muted">Refreshes every {REFRESH_MS / 1000} s.</p>
      {error && <div className="alert">{error}</div>}
      {loading && !data && <p className="empty">Loading…</p>}
      {data && (
        <>
          <section>
            <h2>Services</h2>
            <div className="grid">
              {data.services.map((service) => (
                <Link key={service.id} to={`/services/${service.id}`} className="card service-card">
                  <strong>{service.name}</strong>
                  <span className="muted">{service.description}</span>
                  <HealthBadge activeIncidents={service.active_incidents} />
                </Link>
              ))}
            </div>
          </section>
          <section className="card">
            <h2>Active incidents</h2>
            <IncidentTable incidents={data.active} empty="No active incident." />
          </section>
          <section className="card">
            <h2>Recently resolved</h2>
            <IncidentTable incidents={data.resolved} empty="Nothing resolved yet." />
          </section>
        </>
      )}
    </>
  );
}
