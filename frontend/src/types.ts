// Mirrors the FastAPI response schemas (backend/app/schemas.py & routers).

export type SiteStatus = "unknown" | "healthy" | "degraded" | "offline";
export type AlertSeverity = "warning" | "critical";
export type AlertState = "open" | "resolved";
export type FaultKind = "latency" | "packet_loss" | "outage" | "flap";

export interface Site {
  id: string;
  name: string;
  region: string;
  technology: string;
  latitude: number;
  longitude: number;
  status: SiteStatus;
  status_since: string;
  reasons: string[];
  pending_status: SiteStatus | null;
  pending_count: number;
  last_seen_at: string | null;
  window_latency_ms: number | null;
  window_packet_loss_pct: number | null;
  window_availability_pct: number | null;
}

export interface EvaluatorStatus {
  running: boolean;
  last_run_at: string | null;
  last_duration_ms: number | null;
  last_error: string | null;
  interval_s: number;
}

export interface HealthSummary {
  total: number;
  counts: Record<SiteStatus, number>;
  open_alerts: number;
  evaluator: EvaluatorStatus;
  generated_at: string;
}

export interface MetricPoint {
  ts: string;
  latency_ms: number;
  packet_loss_pct: number;
  availability_pct: number;
}

export interface Alert {
  id: number;
  site_id: string;
  site_name: string;
  severity: AlertSeverity;
  state: AlertState;
  reason: string;
  opened_at: string;
  updated_at: string;
  resolved_at: string | null;
}

export interface Fault {
  site_id: string;
  fault: FaultKind;
  started_at: string;
  expires_at: string;
}

export interface DetectionConfig {
  latency_degraded_ms: number;
  packet_loss_degraded_pct: number;
  availability_degraded_pct: number;
  packet_loss_offline_pct: number;
  availability_offline_pct: number;
  window_s: number;
  min_samples: number;
  trip_count: number;
  clear_count: number;
  stale_after_s: number;
  evaluation_interval_s: number;
}
