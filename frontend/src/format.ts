import type { SiteStatus } from "./types";

export const STATUS_LABEL: Record<SiteStatus, string> = {
  healthy: "Healthy",
  degraded: "Degraded",
  offline: "Offline",
  unknown: "Unknown",
};

// Status is never carried by color alone: every use pairs it with this glyph + label.
export const STATUS_ICON: Record<SiteStatus, string> = {
  healthy: "●",
  degraded: "▲",
  offline: "✕",
  unknown: "○",
};

export const STATUS_ORDER: SiteStatus[] = ["offline", "degraded", "healthy", "unknown"];

export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const secs = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ${mins % 60}m ago`;
}

export function duration(fromIso: string, toIso?: string | null): string {
  const ms = (toIso ? new Date(toIso).getTime() : Date.now()) - new Date(fromIso).getTime();
  const secs = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(secs / 60);
  const h = Math.floor(m / 60);
  if (h) return `${h}h ${m % 60}m`;
  if (m) return `${m}m ${secs % 60}s`;
  return `${secs}s`;
}

/** Seconds -> "3m 10s" / "1h 05m" / "42s". */
export function secs(s: number | null | undefined): string {
  if (s == null) return "—";
  const total = Math.round(s);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  if (h) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m) return `${m}m ${String(total % 60).padStart(2, "0")}s`;
  return `${total}s`;
}

export const fmt = {
  /** Truncate (never round up), so 99.996% shows as 99.99%, not a misleading 100.00%. */
  uptime: (v: number | null | undefined) => (v == null ? "—" : v >= 100 ? "100%" : `${(Math.floor(v * 100) / 100).toFixed(2)}%`),
  ms: (v: number | null) => (v == null ? "—" : `${Math.round(v)} ms`),
  pct: (v: number | null, digits = 2) => (v == null ? "—" : `${v.toFixed(digits)}%`),
  clock: (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
};
