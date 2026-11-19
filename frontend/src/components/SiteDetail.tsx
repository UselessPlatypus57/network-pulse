import { useState } from "react";
import { api } from "../api";
import { STATUS_LABEL, duration, fmt, secs, timeAgo } from "../format";
import { usePolling } from "../hooks/usePolling";
import type { DetectionConfig, Fault, Site } from "../types";
import { ChaosControls } from "./ChaosControls";
import { MetricChart } from "./MetricChart";
import { StatusBadge } from "./StatusBadge";

interface Props {
  site: Site | undefined;
  config: DetectionConfig | undefined;
  fault: Fault | undefined;
  onFaultsChanged: () => void;
  onClose: () => void;
}

const RANGES = [15, 60] as const;

export function SiteDetail({ site, config, fault, onFaultsChanged, onClose }: Props) {
  const [minutes, setMinutes] = useState<(typeof RANGES)[number]>(15);
  const metrics = usePolling(
    () => (site ? api.siteMetrics(site.id, minutes) : Promise.resolve([])),
    5000,
    [site?.id, minutes],
  );
  const uptime = usePolling(
    () => (site ? api.siteUptime(site.id, 24) : Promise.resolve(undefined)),
    15000,
    [site?.id],
  );

  if (!site) {
    return (
      <section className="card detail-card" aria-label="Site detail">
        <div className="card-header">
          <h2 className="card-title">Site detail</h2>
        </div>
        <div className="empty">Select a site on the map or in the list to see its metrics.</div>
      </section>
    );
  }

  const data = metrics.data ?? [];

  return (
    <section className="card detail-card" aria-label={`Details for ${site.id}`}>
      <div className="card-header">
        <div className="detail-title">
          <h2>
            {site.id} <span className="muted">· {site.name}</span>
          </h2>
          <span className="muted">
            {site.region} · {site.technology} · {site.latitude.toFixed(3)}, {site.longitude.toFixed(3)}
          </span>
        </div>
        <div className="toolbar">
          {RANGES.map((r) => (
            <button key={r} className="chip" aria-pressed={minutes === r} onClick={() => setMinutes(r)}>
              {r}m
            </button>
          ))}
          <button className="chip" onClick={onClose} aria-label="Close site detail">
            ✕
          </button>
        </div>
      </div>

      <div className="card-body detail-facts">
        <div>
          <span className="fact-label">Status</span>
          <StatusBadge status={site.status} />
        </div>
        <div>
          <span className="fact-label">In state for</span>
          <span className="num">{duration(site.status_since)}</span>
        </div>
        <div>
          <span className="fact-label">Last report</span>
          <span className="num">{timeAgo(site.last_seen_at)}</span>
        </div>
        <div>
          <span className="fact-label">Trend</span>
          <span>
            {site.pending_status
              ? `→ ${STATUS_LABEL[site.pending_status]} (${site.pending_count}/${
                  site.pending_status === "healthy" ? config?.clear_count ?? "?" : config?.trip_count ?? "?"
                } checks)`
              : "Stable"}
          </span>
        </div>
      </div>

      <div className="card-body detail-facts uptime-facts" aria-label="Last 24 hours">
        <div>
          <span className="fact-label">24h availability</span>
          <span className="num">{fmt.uptime(uptime.data?.available_pct)}</span>
        </div>
        <div>
          <span className="fact-label">24h healthy</span>
          <span className="num">{fmt.uptime(uptime.data?.healthy_pct)}</span>
        </div>
        <div>
          <span className="fact-label">Incidents</span>
          <span className="num">
            {uptime.data ? uptime.data.incidents : "—"}
            {uptime.data?.ongoing_incident_s != null && (
              <span className="muted"> · 1 ongoing ({secs(uptime.data.ongoing_incident_s)})</span>
            )}
          </span>
        </div>
        <div>
          <span className="fact-label">MTTR</span>
          <span className="num" title="Mean time to recovery for incidents resolved in the last 24h">
            {uptime.data ? secs(uptime.data.mttr_s) : "—"}
          </span>
        </div>
      </div>

      {site.reasons.length > 0 && (
        <ul className="reasons">
          {site.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}

      <div className="charts">
        <MetricChart
          title="Latency"
          data={data}
          dataKey="latency_ms"
          unit="ms"
          format={(v) => fmt.ms(v)}
          threshold={config?.latency_degraded_ms ?? 150}
          thresholdLabel={`degraded > ${config?.latency_degraded_ms ?? 150} ms`}
        />
        <MetricChart
          title="Packet loss"
          data={data}
          dataKey="packet_loss_pct"
          unit="%"
          format={(v) => fmt.pct(v, 1)}
          threshold={config?.packet_loss_degraded_pct ?? 2}
          thresholdLabel={`degraded > ${config?.packet_loss_degraded_pct ?? 2}%`}
        />
        <MetricChart
          title="Availability"
          data={data}
          dataKey="availability_pct"
          unit="%"
          format={(v) => fmt.pct(v)}
          threshold={config?.availability_degraded_pct ?? 99}
          thresholdLabel={`degraded < ${config?.availability_degraded_pct ?? 99}%`}
          lowerIsWorse
        />
      </div>
      <ChaosControls siteId={site.id} fault={fault} onChange={onFaultsChanged} />

      {config && (
        <p className="detail-note muted">
          Status uses the median of the last {config.window_s}s (min {config.min_samples} samples). A change needs{" "}
          {config.trip_count} consecutive bad checks to escalate and {config.clear_count} good ones to clear; no data
          for {config.stale_after_s}s marks the site offline.
        </p>
      )}
    </section>
  );
}
