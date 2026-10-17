import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { api } from "../api";
import { usePolling } from "../usePolling";
import { HealthDot } from "./Badges";

async function loadNav(signal: AbortSignal) {
  const [services, summary, ai] = await Promise.all([
    api.services(signal),
    api.summary(signal),
    api.aiStatus(signal),
  ]);
  return { services, summary, ai };
}

/**
 * Top bar: navigation, one health lamp per service, AI state and the simulated-data notice.
 * The incident count lights up while some incident is still unacknowledged.
 */
export function Layout({ children }: { children: ReactNode }) {
  const { data } = usePolling(loadNav, 10000);
  const active = data ? data.summary.open + data.summary.acknowledged : 0;
  const unacknowledged = data?.summary.open ?? 0;

  return (
    <div className="shell">
      <header className="topbar">
        <NavLink to="/" className="brand">
          <span className="brand-mark" aria-hidden="true" />
          SRE Assistant
        </NavLink>
        <nav className="topnav" aria-label="Main">
          <NavLink to="/" end className="nav-item">
            Overview
          </NavLink>
          <NavLink to="/incidents" className="nav-item">
            Incidents
            {active > 0 && (
              <span
                className={`count ${unacknowledged > 0 ? "lit" : ""}`}
                title={`${unacknowledged} not acknowledged`}
              >
                {active}
              </span>
            )}
          </NavLink>
        </nav>
        <nav className="service-nav" aria-label="Services">
          {(data?.services ?? []).map((service) => (
            <NavLink key={service.id} to={`/services/${service.id}`} className="nav-item service-item">
              <HealthDot activeIncidents={service.active_incidents} /> {service.id}
            </NavLink>
          ))}
        </nav>
        <div className="topbar-end">
          <span className={`ai-state ${data?.ai.enabled ? "on" : ""}`} title={data?.ai.model ?? undefined}>
            {data?.ai.enabled ? "AI assistant on" : "AI assistant off"}
          </span>
          <span className="simulated-tag" role="note">
            Simulated data: no real infrastructure is monitored
          </span>
        </div>
      </header>
      <main className="content">{children}</main>
    </div>
  );
}
