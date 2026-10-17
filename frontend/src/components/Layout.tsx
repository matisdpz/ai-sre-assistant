import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { api } from "../api";
import { AlertIcon, GridIcon, ServerIcon, SparkIcon } from "../icons";
import { usePolling } from "../usePolling";
import { HealthDot } from "./Badges";

async function loadSidebar(signal: AbortSignal) {
  const [services, summary, ai] = await Promise.all([
    api.services(signal),
    api.summary(signal),
    api.aiStatus(signal),
  ]);
  return { services, summary, ai };
}

/** Left navigation, as in Grafana, Datadog or incident.io; collapses to a top bar on phones. */
export function Layout({ children }: { children: ReactNode }) {
  const { data } = usePolling(loadSidebar, 10000);
  const active = data ? data.summary.open + data.summary.acknowledged : 0;

  return (
    <div className="shell">
      <aside className="sidebar">
        <NavLink to="/" className="brand">
          <span className="brand-mark" aria-hidden="true">◆</span> SRE Assistant
        </NavLink>
        <nav aria-label="Main">
          <NavLink to="/" end className="nav-item">
            <GridIcon /> Overview
          </NavLink>
          <NavLink to="/incidents" className="nav-item">
            <AlertIcon /> Incidents
            {active > 0 && <span className="count">{active}</span>}
          </NavLink>
          <div className="nav-section">
            <ServerIcon /> Services
          </div>
          {(data?.services ?? []).map((service) => (
            <NavLink key={service.id} to={`/services/${service.id}`} className="nav-item sub">
              <HealthDot activeIncidents={service.active_incidents} /> {service.id}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="ai-state" title={data?.ai.model ?? undefined}>
            <SparkIcon />
            {data?.ai.enabled ? "AI assistant on" : "AI assistant off"}
          </div>
          <div className="simulated-tag" role="note">
            Simulated data: no real infrastructure is monitored
          </div>
        </div>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}
