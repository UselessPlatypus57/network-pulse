import { useState } from "react";
import { api } from "./api";
import { AlertFeed } from "./components/AlertFeed";
import { MonitorBanner, MonitorPill } from "./components/MonitorStatus";
import { SiteDetail } from "./components/SiteDetail";
import { SiteList } from "./components/SiteList";
import { SiteMap } from "./components/SiteMap";
import { SummaryTiles } from "./components/SummaryTiles";
import { usePolling } from "./hooks/usePolling";
import type { SiteStatus } from "./types";

const POLL_MS = 3000;

export default function App() {
  const summary = usePolling(api.summary, POLL_MS);
  const sites = usePolling(api.sites, POLL_MS);
  const alerts = usePolling(api.alerts, POLL_MS);
  const config = usePolling(api.config, 60_000);
  const faults = usePolling(api.faults, POLL_MS);
  const uptime = usePolling(() => api.fleetUptime(24), 15_000);
  const [filter, setFilter] = useState<SiteStatus | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

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
          onClose={() => setSelectedId(null)}
        />
        <AlertFeed alerts={alerts.data} onSelectSite={setSelectedId} />
      </div>
    </div>
  );
}
