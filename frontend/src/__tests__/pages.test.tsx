import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { LiveProvider } from "../live";
import { IncidentDetail } from "../pages/IncidentDetail";
import { Incidents } from "../pages/Incidents";
import { ToastProvider } from "../toast";
import { DIAGNOSIS, incident, mockFetch } from "./helpers";

afterEach(() => vi.unstubAllGlobals());

function renderAt(path: string, element: React.ReactNode, pattern = path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <LiveProvider>
        <ToastProvider>
          <Routes>
            <Route path={pattern} element={element} />
          </Routes>
        </ToastProvider>
      </LiveProvider>
    </MemoryRouter>,
  );
}

const renderIncident = () => renderAt("/incidents/inc-1", <IncidentDetail />, "/incidents/:id");

describe("incident detail", () => {
  it("offers acknowledge and resolve on a triggered incident", async () => {
    mockFetch((url) => (url === "/api/v1/incidents/inc-1" ? { body: incident() } : undefined));
    renderIncident();

    expect(await screen.findByRole("button", { name: "Acknowledge" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resolve" })).toBeInTheDocument();
    expect(screen.getByText("Detected", { selector: ".timeline strong" })).toBeInTheDocument();
  });

  it("offers only resolve once acknowledged, and no action once resolved", async () => {
    mockFetch((url) =>
      url === "/api/v1/incidents/inc-1" ? { body: incident({ status: "acknowledged" }) } : undefined,
    );
    const { unmount } = renderIncident();
    expect(await screen.findByRole("button", { name: "Resolve" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Acknowledge" })).not.toBeInTheDocument();
    unmount();

    mockFetch((url) =>
      url === "/api/v1/incidents/inc-1"
        ? { body: incident({ status: "resolved", resolved_at: "2026-01-01T13:00:00Z" }) }
        : undefined,
    );
    renderIncident();
    expect(await screen.findByText("Resolved", { selector: ".pill" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Acknowledge|Resolve/ })).not.toBeInTheDocument();
  });

  it("sends the note and shows a 409 conflict clearly", async () => {
    const fetchMock = mockFetch((url, init) => {
      if (init?.method === "POST") {
        return { status: 409, body: { detail: "cannot change status from resolved to resolved" } };
      }
      return url === "/api/v1/incidents/inc-1" ? { body: incident() } : undefined;
    });
    renderIncident();

    await userEvent.type(await screen.findByLabelText(/Saved with your next action/), "rolled back deploy");
    await userEvent.click(screen.getByRole("button", { name: "Resolve" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("cannot change status");
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(post?.[1]?.body).toBe(JSON.stringify({ note: "rolled back deploy" }));
  });
});

describe("AI assistant", () => {
  it("explains that AI is off when no key is configured", async () => {
    mockFetch((url) => (url === "/api/v1/incidents/inc-1" ? { body: incident() } : undefined));
    renderIncident();

    expect(await screen.findByText(/AI diagnosis is off/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Analyze with AI" })).not.toBeInTheDocument();
  });

  it("calls the AI only on click and keeps facts apart from hypotheses", async () => {
    const fetchMock = mockFetch((url, init) => {
      if (url === "/api/v1/incidents/inc-1") return { body: incident() };
      if (url === "/api/v1/ai/status") {
        return { body: { enabled: true, provider: "gemini", model: "gemini-3.5-flash-lite" } };
      }
      if (url.endsWith("/diagnosis") && init?.method === "POST") return { status: 201, body: DIAGNOSIS };
      return undefined;
    });
    renderIncident();

    const button = await screen.findByRole("button", { name: "Analyze with AI" });
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    await userEvent.click(button);

    const facts = (await screen.findByText("Observed facts")).closest(".ai-block") as HTMLElement;
    expect(within(facts).getByText(/Average p95 latency/)).toBeInTheDocument();
    const generated = screen.getByText("Hypotheses").closest(".ai-block") as HTMLElement;
    expect(within(generated).getByText("AI-generated · not confirmed")).toBeInTheDocument();
    expect(within(generated).getByText("Database dependency degraded")).toBeInTheDocument();
    expect(screen.getByText(/Not a confirmed root cause/)).toBeInTheDocument();
  });

  it("shows the quota message and keeps the page usable", async () => {
    mockFetch((url, init) => {
      if (url === "/api/v1/incidents/inc-1") return { body: incident() };
      if (url === "/api/v1/ai/status") return { body: { enabled: true, provider: "gemini", model: "m" } };
      if (url.endsWith("/diagnosis") && init?.method === "POST") {
        return { status: 429, body: { detail: "Gemini quota or rate limit reached (free tier limits apply)." } };
      }
      return undefined;
    });
    renderIncident();

    await userEvent.click(await screen.findByRole("button", { name: "Analyze with AI" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("quota");
    expect(screen.getByRole("button", { name: "Resolve" })).toBeEnabled();
  });
});

describe("overview", () => {
  it("shows KPIs, service health, active incidents and acknowledges in one click", async () => {
    const fetchMock = mockFetch((url, init) => {
      if (url.includes("status=open")) return { body: [incident()] };
      if (init?.method === "POST") return { body: incident({ status: "acknowledged" }) };
      return undefined;
    });
    render(
      <MemoryRouter>
        <LiveProvider>
          <ToastProvider>
            <App />
          </ToastProvider>
        </LiveProvider>
      </MemoryRouter>,
    );

    expect(screen.getByRole("note")).toHaveTextContent("Simulated data");
    expect(await screen.findByText("Operational")).toBeInTheDocument();
    expect(screen.getByText("1 active incident")).toBeInTheDocument();
    expect(screen.getByText("1m 35s")).toBeInTheDocument(); // MTTA from the summary
    expect(screen.getByRole("link", { name: "High error rate" })).toHaveAttribute("href", "/incidents/inc-1");

    await userEvent.click(screen.getByRole("button", { name: "Acknowledge" }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => url === "/api/v1/incidents/inc-1/acknowledge" && init?.method === "POST",
        ),
      ).toBe(true),
    );
    expect(await screen.findByText(/acknowledged\./)).toBeInTheDocument(); // toast
  });
});

describe("incidents page", () => {
  it("shows status tabs with counts and switches the query", async () => {
    const fetchMock = mockFetch(() => undefined);
    renderAt("/incidents", <Incidents />);

    const resolvedTab = await screen.findByRole("tab", { name: /Resolved/ });
    await waitFor(() => expect(resolvedTab).toHaveTextContent("2"));
    expect(screen.getByRole("tab", { name: /Triggered/ })).toHaveAttribute("aria-selected", "true");

    await userEvent.click(resolvedTab);

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("status=resolved"))).toBe(true),
    );
    expect(resolvedTab).toHaveAttribute("aria-selected", "true");
  });
});
