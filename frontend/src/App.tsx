import { useEffect, useState } from "react";
import { api } from "./api";
import { AlertFeed } from "./components/AlertFeed";
import { MonitorBanner, MonitorPill } from "./components/MonitorStatus";
import { SiteDetail } from "./components/SiteDetail";
import { SiteList } from "./components/SiteList";
import { SiteMap } from "./components/SiteMap";
import { SummaryTiles } from "./components/SummaryTiles";
import { usePolling } from "./hooks/usePolling";
import type { HealthSummary, SiteStatus } from "./types";

const POLL_MS = 3000;

/**
 * Mirror fleet health in the browser tab, so a dashboard left in a background
 * tab still shows trouble: "(3) Network Pulse" with 3 unhealthy sites, or a
 * warning when the monitor itself is unreachable or stalled.
 */
function tabTitle(summary: HealthSummary | undefined, error: Error | undefined): string {
  if (error) return "⚠ Monitor unreachable · Network Pulse";
  if (!summary) return "Network Pulse";
  if (!summary.evaluator.running) return "⚠ Evaluator stalled · Network Pulse";
  const unhealthy = summary.counts.offline + summary.counts.degraded;
  return unhealthy ? `(${unhealthy}) Network Pulse` : "Network Pulse";
}

export default function App() {
  // Keeps polling in a background tab (one cheap GROUP BY) so the tab title stays live.
  const summary = usePolling(api.summary, POLL_MS, [], { background: true });
  const sites = usePolling(api.sites, POLL_MS);
  const alerts = usePolling(api.alerts, POLL_MS);
  const config = usePolling(api.config, 60_000);
  const faults = usePolling(api.faults, POLL_MS);
  const uptime = usePolling(() => api.fleetUptime(24), 15_000);
  const [filter, setFilter] = useState<SiteStatus | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const title = tabTitle(summary.data, summary.error);
  useEffect(() => {
    document.title = title;
  }, [title]);

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <img src="/favicon.svg" width={28} height={28} alt="" />
          <h1>Network Pulse</h1>
          <span className="tag">Cell-site health monitor</span>
        </div>
        <div className="toolbar">
          {!!faults.data?.length && (
            <span className="pill chaos-pill" title={faults.data.map((f) => `${f.site_id}: ${f.fault}`).join(", ")}>
              ⚡ {faults.data.length} fault{faults.data.length > 1 ? "s" : ""} injected
            </span>
          )}
          <MonitorPill summary={summary.data} error={summary.error} lastSuccess={summary.lastSuccess} />
        </div>
      </header>

      <MonitorBanner summary={summary.data} error={summary.error} lastSuccess={summary.lastSuccess} />

      <SummaryTiles summary={summary.data} uptime={uptime.data} filter={filter} onFilter={setFilter} />

      <div className="main-grid">
        <SiteMap sites={sites.data} selectedId={selectedId} onSelect={setSelectedId} />
        <div className="side-col">
          <SiteList
            sites={sites.data}
            filter={filter}
            onFilter={setFilter}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </div>
      </div>

      <div className="main-grid">
        <SiteDetail
          site={sites.data?.find((s) => s.id === selectedId)}
          config={config.data}
          fault={faults.data?.find((f) => f.site_id === selectedId)}
          onFaultsChanged={faults.refresh}
          onSiteChanged={() => {
            sites.refresh();
            summary.refresh();
          }}
          onClose={() => setSelectedId(null)}
        />
        <AlertFeed alerts={alerts.data} onSelectSite={setSelectedId} />
      </div>
    </div>
  );
}
