import type {
  AIStatus,
  Diagnosis,
  Incident,
  IncidentDetail,
  IncidentStatus,
  IncidentSummary,
  MetricPoint,
  Rule,
  Service,
} from "./types";

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

export interface IncidentQuery {
  status?: IncidentStatus;
  serviceId?: string;
  limit?: number;
}

export const api = {
  services: (signal?: AbortSignal) => request<Service[]>("/api/v1/services", { signal }),
  rules: (signal?: AbortSignal) => request<Rule[]>("/api/v1/rules", { signal }),
  metrics: (
    serviceId: string,
    window: { limit: number; since?: string; until?: string },
    signal?: AbortSignal,
  ) => {
    const params = new URLSearchParams({ limit: String(window.limit) });
    if (window.since) params.set("since", window.since);
    if (window.until) params.set("until", window.until);
    return request<MetricPoint[]>(
      `/api/v1/services/${encodeURIComponent(serviceId)}/metrics?${params}`,
      { signal },
    );
  },
  incidents: (query: IncidentQuery, signal?: AbortSignal) => {
    const params = new URLSearchParams();
    if (query.status) params.set("status", query.status);
    if (query.serviceId) params.set("service_id", query.serviceId);
    params.set("limit", String(query.limit ?? 50));
    return request<Incident[]>(`/api/v1/incidents?${params}`, { signal });
  },
  summary: (signal?: AbortSignal) =>
    request<IncidentSummary>("/api/v1/incidents/summary", { signal }),
  incident: (id: string, signal?: AbortSignal) =>
    request<IncidentDetail>(`/api/v1/incidents/${encodeURIComponent(id)}`, { signal }),
  changeStatus: (id: string, action: "acknowledge" | "resolve", note: string | null) =>
    request<IncidentDetail>(`/api/v1/incidents/${encodeURIComponent(id)}/${action}`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  aiStatus: (signal?: AbortSignal) => request<AIStatus>("/api/v1/ai/status", { signal }),
  /** The stored diagnosis, or null when none was requested yet. Never calls the AI. */
  diagnosis: async (id: string, signal?: AbortSignal): Promise<Diagnosis | null> => {
    try {
      return await request<Diagnosis>(`/api/v1/incidents/${encodeURIComponent(id)}/diagnosis`, {
        signal,
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  },
  /** Asks the AI provider (uses quota): only on an explicit click. */
  requestDiagnosis: (id: string) =>
    request<Diagnosis>(`/api/v1/incidents/${encodeURIComponent(id)}/diagnosis`, {
      method: "POST",
    }),
};
