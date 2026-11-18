import { useState } from "react";
import { duration, fmt } from "../format";
import type { Alert } from "../types";

interface Props {
  alerts: Alert[] | undefined;
  onSelectSite: (id: string) => void;
}

const SEVERITY = {
  critical: { icon: "✕", label: "Critical" },
  warning: { icon: "▲", label: "Warning" },
} as const;

export function AlertFeed({ alerts, onSelectSite }: Props) {
  const [showResolved, setShowResolved] = useState(true);
  const open = alerts?.filter((a) => a.state === "open") ?? [];
  const resolved = alerts?.filter((a) => a.state === "resolved") ?? [];
  const rows = showResolved ? [...open, ...resolved] : open;

  return (
    <section className="card" aria-label="Alerts">
      <div className="card-header">
        <h2 className="card-title">
          Alerts <span className="muted num">· {open.length} open</span>
        </h2>
        <div className="toolbar">
          <button className="chip" aria-pressed={!showResolved} onClick={() => setShowResolved(false)}>
            Open
          </button>
          <button className="chip" aria-pressed={showResolved} onClick={() => setShowResolved(true)}>
            All
          </button>
        </div>
      </div>
      <ol className="alert-list">
        {rows.map((a) => {
          const sev = SEVERITY[a.severity];
          return (
            <li key={a.id} className={`alert ${a.state} ${a.severity}`}>
              <button className="alert-btn" onClick={() => onSelectSite(a.site_id)}>
                <span className={`status ${a.severity === "critical" ? "offline" : "degraded"}`}>
                  <span className="icon" aria-hidden>
                    {a.state === "resolved" ? "✓" : sev.icon}
                  </span>
                  {a.state === "resolved" ? "Resolved" : sev.label}
                </span>
                <span className="alert-site">
                  <strong>{a.site_id}</strong> <span className="muted">{a.site_name}</span>
                </span>
                <span className="alert-time muted num">
                  {fmt.clock(a.opened_at)} · {a.state === "open" ? `open ${duration(a.opened_at)}` : `lasted ${duration(a.opened_at, a.resolved_at)}`}
                </span>
                <span className="alert-reason">{a.reason || "threshold breached"}</span>
              </button>
            </li>
          );
        })}
      </ol>
      {alerts && rows.length === 0 && <div className="empty">{showResolved ? "No alerts yet." : "No open alerts. All quiet."}</div>}
      {!alerts && <div className="empty">Loading alerts…</div>}
    </section>
  );
}
