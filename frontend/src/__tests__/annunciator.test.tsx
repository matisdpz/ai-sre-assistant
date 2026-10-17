import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { Annunciator } from "../components/Annunciator";
import type { MetricPoint, Service } from "../types";
import { incident } from "./helpers";

const SERVICES: Service[] = [
  { id: "api-gateway", name: "API Gateway", description: "", active_incidents: 0 },
  { id: "payment-service", name: "Payment Service", description: "", active_incidents: 1 },
];

function point(overrides: Partial<MetricPoint> = {}): MetricPoint {
  return {
    ts: "2026-01-01T12:00:00Z",
    request_rate: 80,
    error_rate: 0.5,
    latency_p95_ms: 120,
    cpu_pct: 40,
    mem_pct: 50,
    up: true,
    source: "simulator",
    ...overrides,
  };
}

function renderPanel(active = [incident()], metrics: MetricPoint[][] = [[point()], [point()]]) {
  return render(
    <MemoryRouter>
      <Annunciator services={SERVICES} metrics={metrics} rules={[]} active={active} />
    </MemoryRouter>,
  );
}

const lamp = (rule: string, service: string) =>
  screen.getAllByRole("link").find((a) => a.textContent?.startsWith(`${rule} on ${service}`))!;

describe("annunciator", () => {
  it("draws one lamp per rule and service", () => {
    renderPanel();
    // 2 service names + 4 rules x 2 services.
    expect(screen.getAllByRole("link")).toHaveLength(2 + 8);
  });

  it("lights the lamp of an unresolved incident and links to it", () => {
    renderPanel();
    const lit = lamp("High error rate", "payment-service");
    expect(lit).toHaveAttribute("href", "/incidents/inc-1");
    expect(lit).toHaveClass("status-open", "sev-warning");
    expect(lit).toHaveTextContent("Not acknowledged");
  });

  it("keeps quiet lamps dark and links them to the service", () => {
    renderPanel();
    const off = lamp("High error rate", "api-gateway");
    expect(off).toHaveClass("is-off");
    expect(off).toHaveAttribute("href", "/services/api-gateway");
    expect(off).toHaveTextContent("0.5 %");
  });

  it("marks acknowledged and recovered incidents apart from new ones", () => {
    renderPanel([
      incident({ status: "acknowledged" }),
      incident({ id: "inc-2", type: "high_cpu", recovered_at: "2026-01-01T12:05:00Z" }),
    ]);
    expect(lamp("High error rate", "payment-service")).toHaveTextContent("Acknowledged");
    expect(lamp("High CPU", "payment-service")).toHaveClass("is-recovered");
    expect(lamp("High CPU", "payment-service")).toHaveTextContent("Not acknowledged");
    expect(lamp("High CPU", "payment-service")).toHaveTextContent("Metrics recovered");
  });

  it("shows a down service in the service-down row", () => {
    renderPanel([], [[point({ up: false })], [point()]]);
    expect(lamp("Service down", "api-gateway")).toHaveTextContent("Down");
    expect(lamp("High latency", "api-gateway")).toHaveTextContent("down");
  });
});
