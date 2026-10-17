import type { Incident, IncidentDetail, IncidentStatus, MetricPoint, Rule, Service } from "./types";

/** An HTTP error from the API, with the backend's `detail` message when there is one. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "The API is unreachable. Is the backend running?");
  }
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // Not JSON: keep the generic message.
    }
    throw new ApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  services: (signal?: AbortSignal) => request<Service[]>("/api/v1/services", { signal }),
  rules: (signal?: AbortSignal) => request<Rule[]>("/api/v1/rules", { signal }),
  metrics: (serviceId: string, limit: number, signal?: AbortSignal) =>
    request<MetricPoint[]>(
      `/api/v1/services/${encodeURIComponent(serviceId)}/metrics?limit=${limit}`,
      { signal },
    ),
  incidents: (params: { status?: IncidentStatus; limit?: number }, signal?: AbortSignal) => {
    const query = new URLSearchParams();
    if (params.status) query.set("status", params.status);
    query.set("limit", String(params.limit ?? 50));
    return request<Incident[]>(`/api/v1/incidents?${query}`, { signal });
  },
  incident: (id: string, signal?: AbortSignal) =>
    request<IncidentDetail>(`/api/v1/incidents/${encodeURIComponent(id)}`, { signal }),
  changeStatus: (id: string, action: "acknowledge" | "resolve", note: string | null) =>
    request<IncidentDetail>(`/api/v1/incidents/${encodeURIComponent(id)}/${action}`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
};
