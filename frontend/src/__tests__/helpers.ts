import { vi } from "vitest";

import type { IncidentDetail } from "../types";

type Route = (url: string, init?: RequestInit) => { status?: number; body: unknown } | undefined;

/** Replace fetch with a router of canned JSON responses; returns the mock for assertions. */
export function mockFetch(route: Route) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const reply = route(url, init);
    if (!reply) throw new Error(`unexpected request: ${init?.method ?? "GET"} ${url}`);
    return new Response(JSON.stringify(reply.body), {
      status: reply.status ?? 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", mock);
  return mock;
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
