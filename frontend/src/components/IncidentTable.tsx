import { Link } from "react-router-dom";

import { formatAgo, TYPE_LABELS } from "../format";
import type { Incident } from "../types";
import { SeverityBadge, StatusBadge } from "./Badges";

export function IncidentTable({ incidents, empty }: { incidents: Incident[]; empty: string }) {
  if (incidents.length === 0) return <p className="empty">{empty}</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Incident</th>
            <th>Service</th>
            <th>Severity</th>
            <th>Status</th>
            <th>Detected</th>
          </tr>
        </thead>
        <tbody>
          {incidents.map((incident) => (
            <tr key={incident.id}>
              <td>
                <Link to={`/incidents/${incident.id}`}>{TYPE_LABELS[incident.type]}</Link>
                <div className="muted">{incident.summary}</div>
                {incident.recovered_at && !incident.resolved_at && (
                  <div className="secondary">Metrics recovered, awaiting resolution</div>
                )}
              </td>
              <td>{incident.service_id}</td>
              <td>
                <SeverityBadge severity={incident.severity} />
              </td>
              <td>
                <StatusBadge status={incident.status} />
              </td>
              <td className="num" title={incident.detected_at}>
                {formatAgo(incident.detected_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
