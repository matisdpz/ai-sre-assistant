import { Link } from "react-router-dom";

import { api, ApiError } from "../api";
import { formatAgo, formatDuration, secondsBetween, TYPE_LABELS } from "../format";
import { useToast } from "../toast";
import type { Incident } from "../types";
import { SeverityBadge, StatusBadge } from "./Badges";

/**
 * Incident rows: severity band, what and where, how long, and
 * one-click acknowledge / resolve without leaving the list.
 */
export function IncidentList({
  incidents,
  empty,
  onChange,
  showActions = true,
}: {
  incidents: Incident[];
  empty: string;
  onChange?: () => void;
  showActions?: boolean;
}) {
  const toast = useToast();

  async function act(incident: Incident, action: "acknowledge" | "resolve") {
    try {
      await api.changeStatus(incident.id, action, null);
      toast("success", `${TYPE_LABELS[incident.type]} on ${incident.service_id} ${action === "resolve" ? "resolved" : "acknowledged"}.`);
    } catch (error) {
      toast("error", error instanceof ApiError ? error.message : "Action failed.");
    } finally {
      onChange?.();
    }
  }

  if (incidents.length === 0) return <p className="empty">{empty}</p>;
  return (
    <ul className="incident-list">
      {incidents.map((incident) => {
        const ongoing = incident.status !== "resolved";
        const duration = secondsBetween(incident.started_at, incident.resolved_at ?? incident.recovered_at);
        return (
          <li key={incident.id} className={`incident-row sev-${incident.severity} ${ongoing ? "" : "is-resolved"}`}>
            <div className="incident-main">
              <div className="incident-title">
                <Link to={`/incidents/${incident.id}`}>{TYPE_LABELS[incident.type]}</Link>
                <span className="muted">on</span>
                <Link to={`/services/${incident.service_id}`} className="service-link">
                  {incident.service_id}
                </Link>
              </div>
              <div className="muted small">{incident.summary}</div>
            </div>
            <div className="incident-meta">
              <SeverityBadge severity={incident.severity} />
              <StatusBadge status={incident.status} />
              <span className="small muted" title={incident.detected_at}>
                {ongoing && !incident.recovered_at
                  ? `ongoing for ${formatDuration(duration)}`
                  : `${incident.recovered_at && ongoing ? "metrics recovered, " : ""}detected ${formatAgo(incident.detected_at)}`}
              </span>
            </div>
            {showActions && ongoing && (
              <div className="incident-actions">
                {incident.status === "open" && (
                  <button type="button" className="btn small" onClick={() => act(incident, "acknowledge")}>
                    Acknowledge
                  </button>
                )}
                <button type="button" className="btn small" onClick={() => act(incident, "resolve")}>
                  Resolve
                </button>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
