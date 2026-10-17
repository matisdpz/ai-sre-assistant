import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { IncidentDetail } from "../pages/IncidentDetail";
import { incident, mockFetch } from "./helpers";

afterEach(() => vi.unstubAllGlobals());

function renderIncident() {
  return render(
    <MemoryRouter initialEntries={["/incidents/inc-1"]}>
      <Routes>
        <Route path="/incidents/:id" element={<IncidentDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("incident detail", () => {
  it("offers acknowledge and resolve on an open incident", async () => {
    mockFetch(() => ({ body: incident() }));
    renderIncident();

    expect(await screen.findByRole("button", { name: "Acknowledge" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resolve" })).toBeInTheDocument();
    expect(screen.getByText("Detected", { selector: ".timeline strong" })).toBeInTheDocument();
  });

  it("offers only resolve once acknowledged, and nothing once resolved", async () => {
    mockFetch(() => ({ body: incident({ status: "acknowledged" }) }));
    const { unmount } = renderIncident();
    expect(await screen.findByRole("button", { name: "Resolve" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Acknowledge" })).not.toBeInTheDocument();
    unmount();

    mockFetch(() => ({ body: incident({ status: "resolved", resolved_at: "2026-01-01T13:00:00Z" }) }));
    renderIncident();
    expect(await screen.findByText("Resolved", { selector: ".badge" })).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("sends the note and shows a 409 conflict clearly", async () => {
    const fetchMock = mockFetch((_url, init) => {
      if (init?.method === "POST") {
        return { status: 409, body: { detail: "cannot change status from resolved to resolved" } };
      }
      return { body: incident() };
    });
    renderIncident();

    await userEvent.type(await screen.findByLabelText("Note (optional)"), "rolled back deploy");
    await userEvent.click(screen.getByRole("button", { name: "Resolve" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("cannot change status");
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(post?.[1]?.body).toBe(JSON.stringify({ note: "rolled back deploy" }));
  });
});

describe("overview", () => {
  it("shows the simulated-data banner, service health and active incidents", async () => {
    mockFetch((url) => {
      if (url === "/api/v1/services") {
        return {
          body: [
            { id: "api-gateway", name: "API Gateway", description: "", active_incidents: 0 },
            { id: "payment-service", name: "Payment Service", description: "", active_incidents: 1 },
          ],
        };
      }
      if (url.includes("status=open")) return { body: [incident()] };
      if (url.includes("status=")) return { body: [] };
      return undefined;
    });
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByRole("note")).toHaveTextContent("Simulated data");
    expect(await screen.findByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText("1 active incident")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "High error rate" })).toHaveAttribute("href", "/incidents/inc-1");
    await waitFor(() => expect(screen.getByText("Nothing resolved yet.")).toBeInTheDocument());
  });
});
