import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "../api";
import { niceCeil } from "../components/MetricChart";
import { formatAgo } from "../format";
import { mockFetch } from "./helpers";

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("surfaces the backend detail message of an error", async () => {
    mockFetch(() => ({ status: 409, body: { detail: "cannot change status from resolved to resolved" } }));

    const error = await api.changeStatus("inc-1", "resolve", null).catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(409);
    expect(error.message).toBe("cannot change status from resolved to resolved");
  });

  it("explains when the API is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(api.services()).rejects.toThrow("The API is unreachable");
  });

  it("sends the note and builds query strings", async () => {
    const fetchMock = mockFetch(() => ({ body: [] }));

    await api.incidents({ status: "open" });
    await api.changeStatus("inc-1", "acknowledge", "on it");

    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/v1/incidents?status=open&limit=50");
    const [url, init] = fetchMock.mock.calls[1];
    expect(url).toBe("/api/v1/incidents/inc-1/acknowledge");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify({ note: "on it" }));
  });
});

describe("formatAgo", () => {
  const now = Date.parse("2026-01-01T12:00:00Z");
  it.each([
    ["2026-01-01T11:59:30Z", "30s ago"],
    ["2026-01-01T11:55:00Z", "5 min ago"],
    ["2026-01-01T09:00:00Z", "3 h ago"],
    ["2025-12-25T12:00:00Z", "7 d ago"],
  ])("%s -> %s", (iso, expected) => {
    expect(formatAgo(iso, now)).toBe(expected);
  });
});

describe("niceCeil", () => {
  it.each([
    [0, 1],
    [0.7, 1],
    [11.5, 20],
    [16, 20],
    [87, 100],
    [110, 200],
    [1338, 2000],
    [100, 100],
  ])("%s -> %s", (value, expected) => {
    expect(niceCeil(value)).toBe(expected);
  });
});
