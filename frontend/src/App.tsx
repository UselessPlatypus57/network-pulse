import { useState } from "react";
import { api } from "./api";
import { MonitorBanner, MonitorPill } from "./components/MonitorStatus";
import { SiteList } from "./components/SiteList";
import { SiteMap } from "./components/SiteMap";
import { SummaryTiles } from "./components/SummaryTiles";
import { usePolling } from "./hooks/usePolling";
import type { SiteStatus } from "./types";

const POLL_MS = 3000;

export default function App() {
  const summary = usePolling(api.summary, POLL_MS);
  const sites = usePolling(api.sites, POLL_MS);
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
        <MonitorPill summary={summary.data} error={summary.error} lastSuccess={summary.lastSuccess} />
      </header>

      <MonitorBanner summary={summary.data} error={summary.error} lastSuccess={summary.lastSuccess} />

      <SummaryTiles summary={summary.data} filter={filter} onFilter={setFilter} />

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
    </div>
  );
}
