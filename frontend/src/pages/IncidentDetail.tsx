import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, ApiError } from "../api";
import { SeverityBadge, StatusBadge } from "../components/Badges";
import { formatDateTime, TYPE_LABELS } from "../format";
import type { IncidentDetail as Detail, IncidentEvent } from "../types";
import { usePolling } from "../usePolling";

const EVENT_LABEL: Record<IncidentEvent["kind"], string> = {
  detected: "Detected",
  escalated: "Escalated to critical",
  recovered: "Metrics recovered",
  retriggered: "Breached again",
  status_changed: "Status changed",
};

function describe(event: IncidentEvent): string {
  if (event.kind === "status_changed") return `${event.from_status} → ${event.to_status}`;
  return EVENT_LABEL[event.kind];
}

export function IncidentDetail() {
  const { id = "" } = useParams();
  const { data, error, refresh } = usePolling((signal) => api.incident(id, signal), 5000, [id]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  async function act(action: "acknowledge" | "resolve") {
    setBusy(true);
    setActionError(null);
    try {
      await api.changeStatus(id, action, note.trim() || null);
      setNote("");
    } catch (reason) {
      // 409: someone else changed it first, or the action is not allowed in this state.
      setActionError(reason instanceof ApiError ? reason.message : "Action failed.");
    } finally {
      setBusy(false);
      refresh();
    }
  }

  if (!data) {
    return error ? <div className="alert">{error}</div> : <p className="empty">Loading…</p>;
  }
  const incident: Detail = data;

  return (
    <>
      <p>
        <Link to="/">← Overview</Link>
      </p>
      <h1>
        {TYPE_LABELS[incident.type]} on{" "}
        <Link to={`/services/${incident.service_id}`}>{incident.service_id}</Link>
      </h1>
      <p className="buttons">
        <SeverityBadge severity={incident.severity} />
        <StatusBadge status={incident.status} />
      </p>
      <p className="secondary">{incident.summary}</p>
      {error && <div className="alert">{error}</div>}

      <section className="card">
        <dl className="facts">
          <div><dt>Started</dt><dd>{formatDateTime(incident.started_at)}</dd></div>
          <div><dt>Detected</dt><dd>{formatDateTime(incident.detected_at)}</dd></div>
          <div><dt>Recovered</dt><dd>{incident.recovered_at ? formatDateTime(incident.recovered_at) : "-"}</dd></div>
          <div><dt>Resolved</dt><dd>{incident.resolved_at ? formatDateTime(incident.resolved_at) : "-"}</dd></div>
          <div><dt>Threshold</dt><dd>{incident.threshold}</dd></div>
          <div><dt>Peak value</dt><dd>{incident.peak_value}</dd></div>
        </dl>
      </section>

      {incident.status !== "resolved" && (
        <section className="card actions">
          <h2>Actions</h2>
          {actionError && <div className="alert" role="alert">{actionError}</div>}
          <label htmlFor="note" className="muted">Note (optional)</label>
          <textarea id="note" value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
          <div className="buttons">
            {incident.status === "open" && (
              <button disabled={busy} onClick={() => act("acknowledge")}>Acknowledge</button>
            )}
            <button className="primary" disabled={busy} onClick={() => act("resolve")}>Resolve</button>
          </div>
        </section>
      )}

      <section className="card">
        <h2>Evidence</h2>
        <p className="muted">Observed samples behind the latest detection decision (simulated).</p>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Time</th><th>Value</th><th>Service up</th></tr></thead>
            <tbody>
              {incident.evidence.map((e) => (
                <tr key={e.ts}>
                  <td className="num">{formatDateTime(e.ts)}</td>
                  <td className="num">{e.value}</td>
                  <td>{e.up ? "yes" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <h2>Timeline</h2>
        <ol className="timeline">
          {incident.events.map((event) => (
            <li key={event.id} className={event.actor}>
              <strong>{describe(event)}</strong>{" "}
              <span className="muted">
                by {event.actor} · {formatDateTime(event.created_at)}
              </span>
              {event.note && <div className="secondary">{event.note}</div>}
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}
