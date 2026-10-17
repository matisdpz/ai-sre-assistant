import { useSearchParams } from "react-router-dom";

import { api } from "../api";
import { IncidentList } from "../components/IncidentList";
import { PageHeader } from "../components/PageHeader";
import { TYPE_LABELS } from "../format";
import type { IncidentStatus } from "../types";
import { usePolling } from "../usePolling";

const TABS: { key: IncidentStatus | "all"; label: string }[] = [
  { key: "open", label: "Triggered" },
  { key: "acknowledged", label: "Acknowledged" },
  { key: "resolved", label: "Resolved" },
  { key: "all", label: "All" },
];

/** Incident queue with status tabs and filters kept in the URL, so a view can be shared. */
export function Incidents() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("status") ?? "open") as IncidentStatus | "all";
  const service = params.get("service") ?? "";
  const search = params.get("q") ?? "";

  const { data, error, updatedAt, refresh } = usePolling(
    async (signal) => {
      const [incidents, summary, services] = await Promise.all([
        api.incidents(
          { status: tab === "all" ? undefined : tab, serviceId: service || undefined, limit: 200 },
          signal,
        ),
        api.summary(signal),
        api.services(signal),
      ]);
      return { incidents, summary, services };
    },
    5000,
    [tab, service],
  );

  function update(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  const counts: Record<string, number | undefined> = {
    open: data?.summary.open,
    acknowledged: data?.summary.acknowledged,
    resolved: data?.summary.resolved,
    all: data ? data.summary.open + data.summary.acknowledged + data.summary.resolved : undefined,
  };
  const needle = search.trim().toLowerCase();
  const shown = (data?.incidents ?? []).filter(
    (i) =>
      !needle ||
      `${TYPE_LABELS[i.type]} ${i.service_id} ${i.summary}`.toLowerCase().includes(needle),
  );

  return (
    <>
      <PageHeader title="Incidents" updatedAt={updatedAt} />
      <div className="tabs" role="tablist" aria-label="Incident status">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            className={`tab ${tab === t.key ? "active" : ""}`}
            onClick={() => update("status", t.key)}
          >
            {t.label}
            {counts[t.key] !== undefined && <span className="count">{counts[t.key]}</span>}
          </button>
        ))}
      </div>
      <div className="filters">
        <input
          type="search"
          placeholder="Search incidents…"
          aria-label="Search incidents"
          value={search}
          onChange={(e) => update("q", e.target.value)}
        />
        <select aria-label="Service" value={service} onChange={(e) => update("service", e.target.value)}>
          <option value="">All services</option>
          {(data?.services ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.id}
            </option>
          ))}
        </select>
      </div>
      {error && <div className="alert">{error}</div>}
      <section className="card">
        <IncidentList incidents={shown} empty="No incident matches." onChange={refresh} />
      </section>
    </>
  );
}
