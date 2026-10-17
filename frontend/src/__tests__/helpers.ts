import { vi } from "vitest";

import type { Diagnosis, IncidentDetail } from "../types";

export type Reply = { status?: number; body: unknown } | undefined;
type Route = (url: string, init?: RequestInit) => Reply;

/** Replace fetch with a router of canned JSON responses; returns the mock for assertions. */
export function mockFetch(route: Route) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const reply = route(url, init) ?? defaults(url);
    if (!reply) throw new Error(`unexpected request: ${init?.method ?? "GET"} ${url}`);
    return new Response(JSON.stringify(reply.body), {
      status: reply.status ?? 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

/** Answers for the calls every page makes (sidebar, rules...), unless a test overrides them. */
function defaults(url: string): Reply {
  if (url === "/api/v1/services") {
    return {
      body: [
        { id: "api-gateway", name: "API Gateway", description: "", active_incidents: 0 },
        { id: "payment-service", name: "Payment Service", description: "", active_incidents: 1 },
      ],
    };
  }
  if (url === "/api/v1/incidents/summary") {
    return { body: { open: 1, acknowledged: 0, resolved: 2, mtta_seconds: 95, mttr_seconds: 600 } };
  }
  if (url === "/api/v1/ai/status") return { body: { enabled: false, provider: null, model: null } };
  if (url === "/api/v1/rules") return { body: [] };
  if (url.includes("/metrics")) return { body: [] };
  if (url.endsWith("/diagnosis")) return { status: 404, body: { detail: "no diagnosis yet" } };
  if (url.startsWith("/api/v1/incidents?")) return { body: [] };
  return undefined;
}

export function incident(overrides: Partial<IncidentDetail> = {}): IncidentDetail {
  return {
    id: "inc-1",
    service_id: "payment-service",
    type: "high_error_rate",
    severity: "warning",
    status: "open",
    summary: "error rate >= 5 % (warning) for 3 consecutive samples, peak 8 %",
    threshold: 5,
    peak_value: 8,
    started_at: "2026-01-01T12:00:10Z",
    detected_at: "2026-01-01T12:00:30Z",
    recovered_at: null,
    resolved_at: null,
    updated_at: "2026-01-01T12:00:30Z",
    evidence: [
      { ts: "2026-01-01T12:00:10Z", value: 6, up: true },
      { ts: "2026-01-01T12:00:20Z", value: 7, up: true },
      { ts: "2026-01-01T12:00:30Z", value: 8, up: true },
    ],
    events: [
      {
        id: 1,
        kind: "detected",
        actor: "system",
        from_status: null,
        to_status: null,
        note: null,
        created_at: "2026-01-01T12:00:30Z",
      },
    ],
    ...overrides,
  };
}

export const DIAGNOSIS: Diagnosis = {
  id: "diag-1",
  incident_id: "inc-1",
  provider: "gemini",
  model: "gemini-3.5-flash-lite",
  created_at: "2026-01-01T12:05:00Z",
  facts: ["Average p95 latency: 180.0 ms before the incident, 1300.0 ms during it (+622%)."],
  summary: "Errors and latency rose together.",
  hypotheses: [
    {
      title: "Database dependency degraded",
      reasoning: "Latency and errors increased at the same time.",
      confidence: "medium",
      supporting_facts: [],
    },
  ],
  suggested_checks: ["Check database-service metrics for the same period."],
  disclaimer: "AI-generated hypotheses from simulated data. Not a confirmed root cause: verify before acting.",
};
