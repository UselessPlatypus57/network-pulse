import type {
  Alert,
  DetectionConfig,
  Fault,
  FaultKind,
  FleetUptime,
  HealthSummary,
  MetricPoint,
  Site,
  UptimeReport,
} from "./types";

// Same-origin by default (Vite proxy in dev, nginx in Docker).
const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  summary: () => request<HealthSummary>("/api/v1/health/summary"),
  config: () => request<DetectionConfig>("/api/v1/health/config"),
  sites: () => request<Site[]>("/api/v1/sites"),
  siteMetrics: (id: string, minutes = 15) =>
    request<MetricPoint[]>(`/api/v1/sites/${encodeURIComponent(id)}/metrics?minutes=${minutes}`),
  siteUptime: (id: string, hours = 24) =>
    request<UptimeReport>(`/api/v1/sites/${encodeURIComponent(id)}/uptime?hours=${hours}`),
  fleetUptime: (hours = 24) => request<FleetUptime>(`/api/v1/health/uptime?hours=${hours}`),
  startMaintenance: (siteId: string, minutes: number) =>
    request<Site>(`/api/v1/sites/${encodeURIComponent(siteId)}/maintenance`, {
      method: "PUT",
      body: JSON.stringify({ minutes }),
    }),
  endMaintenance: (siteId: string) =>
    request<Site>(`/api/v1/sites/${encodeURIComponent(siteId)}/maintenance`, { method: "DELETE" }),
  alerts: (limit = 50) => request<Alert[]>(`/api/v1/alerts?limit=${limit}`),
  faults: () => request<Fault[]>("/api/v1/chaos"),
  injectFault: (siteId: string, fault: FaultKind, durationS: number) =>
    request<Fault>(`/api/v1/chaos/${encodeURIComponent(siteId)}`, {
      method: "PUT",
      body: JSON.stringify({ fault, duration_s: durationS }),
    }),
  clearFault: (siteId: string) =>
    request<void>(`/api/v1/chaos/${encodeURIComponent(siteId)}`, { method: "DELETE" }),
};
