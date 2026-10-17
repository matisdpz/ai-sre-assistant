import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, ApiError } from "../api";
import { SeverityBadge, StatusBadge } from "../components/Badges";
import { DiagnosisPanel } from "../components/DiagnosisPanel";
import { MetricChart } from "../components/MetricChart";
import { PageHeader } from "../components/PageHeader";
import { formatDateTime, formatDuration, secondsBetween, TYPE_LABELS } from "../format";
import { useToast } from "../toast";
import type { IncidentEvent, IncidentType, MetricPoint } from "../types";
import { usePolling } from "../usePolling";

const EVENT_LABEL: Record<IncidentEvent["kind"], string> = {
  detected: "Detected",
  escalated: "Escalated to critical",
  recovered: "Metrics recovered",
  retriggered: "Breached again",
  status_changed: "Status changed",
};

function describe(event: IncidentEvent): string {
  if (event.kind === "status_changed") {
    return event.to_status === "acknowledged" ? "Acknowledged" : "Resolved";
  }
  return EVENT_LABEL[event.kind];
}

const CHART_TITLE: Record<IncidentType, string> = {
  high_error_rate: "Error rate",
  high_latency: "p95 latency",
  high_cpu: "CPU",
  service_down: "Request rate (gaps: service down)",
};

const CONTEXT_MS = 10 * 60 * 1000; // chart window: 10 minutes before and after

async function loadIncident(id: string, signal: AbortSignal) {
  const incident = await api.incident(id, signal);
  const start = Date.parse(incident.started_at) - CONTEXT_MS;
  const endRef = incident.resolved_at ?? incident.recovered_at;
  const until = endRef ? new Date(Date.parse(endRef) + CONTEXT_MS).toISOString() : undefined;
  const [points, rules, ai] = await Promise.all([
    api.metrics(incident.service_id, { since: new Date(start).toISOString(), until, limit: 2000 }, signal),
    api.rules(signal),
    api.aiStatus(signal),
  ]);
  return { incident, points, rules, ai };
}

export function IncidentDetail() {
  const { id = "" } = useParams();
  const { data, error, updatedAt, refresh } = usePolling((signal) => loadIncident(id, signal), 5000, [id]);
  const toast = useToast();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  async function act(action: "acknowledge" | "resolve") {
    setBusy(true);
    setActionError(null);
    try {
      await api.changeStatus(id, action, note.trim() || null);
      setNote("");
      toast("success", action === "resolve" ? "Incident resolved." : "Incident acknowledged.");
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
  const { incident, points, rules, ai } = data;
  const rule = rules.find((r) => r.type === incident.type);
  const metric = rule?.metric;
  const value =
    metric && metric !== "up"
      ? (p: MetricPoint) => Number(p[metric])
      : (p: MetricPoint) => p.request_rate; // service_down: show traffic, gaps mark the outage
  const ongoing = incident.status !== "resolved";
  const duration = secondsBetween(incident.started_at, incident.resolved_at ?? incident.recovered_at);

  return (
    <>
      <p className="breadcrumb">
        <Link to="/incidents">Incidents</Link> / <span className="muted">{incident.id.slice(0, 8)}</span>
      </p>
      <PageHeader
        title={
          <>
            {TYPE_LABELS[incident.type]} on{" "}
            <Link to={`/services/${incident.service_id}`}>{incident.service_id}</Link>
          </>
        }
        subtitle={
          <span className="header-badges">
            <SeverityBadge severity={incident.severity} />
            <StatusBadge status={incident.status} />
            <span>{incident.summary}</span>
          </span>
        }
        updatedAt={updatedAt}
      >
        {ongoing && incident.status === "open" && (
          <button type="button" className="btn" disabled={busy} onClick={() => act("acknowledge")}>
            Acknowledge
          </button>
        )}
        {ongoing && (
          <button type="button" className="btn primary" disabled={busy} onClick={() => act("resolve")}>
            Resolve
          </button>
        )}
      </PageHeader>
      {actionError && (
        <div className="alert" role="alert">
          {actionError}
        </div>
      )}
      {error && <div className="alert">{error}</div>}

      <div className="detail-layout">
        <div className="detail-main">
          {points.length > 0 ? (
            <MetricChart
              title={CHART_TITLE[incident.type]}
              unit={rule && metric !== "up" ? rule.unit : "req/s"}
              points={points}
              value={value}
              threshold={rule && metric !== "up" ? { warning: rule.warning, critical: rule.critical } : undefined}
              domainMax={incident.type === "high_cpu" ? 100 : undefined}
              highlight={{ from: incident.started_at, to: incident.recovered_at ?? incident.resolved_at }}
              markers={[{ ts: incident.detected_at, label: "detected" }]}
              height={240}
            />
          ) : (
            <p className="empty">No stored samples around this incident.</p>
          )}

          <DiagnosisPanel incidentId={incident.id} ai={ai} />

          <section className="card">
            <h2>Evidence</h2>
            <p className="muted small">Observed samples behind the latest detection decision (simulated).</p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Value</th>
                    <th>Service up</th>
                  </tr>
                </thead>
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
        </div>

        <aside className="detail-side">
          <section className="card">
            <h2>Properties</h2>
            <dl className="props">
              <dt>Service</dt>
              <dd><Link to={`/services/${incident.service_id}`}>{incident.service_id}</Link></dd>
              <dt>Started</dt>
              <dd>{formatDateTime(incident.started_at)}</dd>
              <dt>Detected</dt>
              <dd>{formatDateTime(incident.detected_at)}</dd>
              <dt>{incident.recovered_at || incident.resolved_at ? "Duration" : "Ongoing for"}</dt>
              <dd>{formatDuration(duration)}</dd>
              <dt>Recovered</dt>
              <dd>{incident.recovered_at ? formatDateTime(incident.recovered_at) : "-"}</dd>
              <dt>Resolved</dt>
              <dd>{incident.resolved_at ? formatDateTime(incident.resolved_at) : "-"}</dd>
              {incident.type !== "service_down" && (
                <>
                  <dt>Threshold</dt>
                  <dd>{incident.threshold} {rule?.unit}</dd>
                  <dt>Peak</dt>
                  <dd>{incident.peak_value} {rule?.unit}</dd>
                </>
              )}
            </dl>
          </section>

          {ongoing && (
            <section className="card">
              <h2>Note</h2>
              <label htmlFor="note" className="muted small">
                Saved with your next action (optional)
              </label>
              <textarea id="note" value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
            </section>
          )}

          <section className="card">
            <h2>Timeline</h2>
            <ol className="timeline">
              {[...incident.events].reverse().map((event) => (
                <li key={event.id} className={`${event.actor} kind-${event.kind}`}>
                  <strong>{describe(event)}</strong>
                  <div className="muted small">
                    {event.actor === "user" ? "by a person" : "by detection"} · {formatDateTime(event.created_at)}
                  </div>
                  {event.note && <div className="note">{event.note}</div>}
                </li>
              ))}
            </ol>
          </section>
        </aside>
      </div>
    </>
  );
}
