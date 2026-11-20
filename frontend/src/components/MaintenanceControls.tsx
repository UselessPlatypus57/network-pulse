import { useState } from "react";
import { api } from "../api";
import { duration, fmt } from "../format";
import type { Site } from "../types";

interface Props {
  site: Site;
  onChange: () => void;
}

const WINDOWS = [
  { minutes: 30, label: "30 min" },
  { minutes: 60, label: "1 hour" },
  { minutes: 120, label: "2 hours" },
  { minutes: 240, label: "4 hours" },
];

export function MaintenanceControls({ site, onChange }: Props) {
  const [minutes, setMinutes] = useState(60);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  const until = site.maintenance_until ? new Date(site.maintenance_until) : null;
  const active = until !== null && until.getTime() > Date.now();

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(undefined);
    try {
      await fn();
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`maint ${active ? "active" : ""}`}>
      <div className="chaos-head">
        <span className="fact-label">Planned maintenance</span>
        {!active && (
          <label className="muted chaos-duration">
            for{" "}
            <select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} aria-label="Maintenance length">
              {WINDOWS.map((w) => (
                <option key={w.minutes} value={w.minutes}>
                  {w.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <div className="chaos-buttons">
        {active ? (
          <button className="chaos-btn" disabled={busy} onClick={() => act(() => api.endMaintenance(site.id))}>
            End maintenance now
          </button>
        ) : (
          <button className="chaos-btn" disabled={busy} onClick={() => act(() => api.startMaintenance(site.id, minutes))}>
            Start maintenance
          </button>
        )}
      </div>
      <p className="chaos-status" role="status">
        {active && until ? (
          <>
            <strong>In maintenance until {fmt.clock(until.toISOString())}</strong> ({duration(new Date().toISOString(), site.maintenance_until)}{" "}
            left). Alerts are suppressed and this time doesn't count against uptime. When it ends, the site is
            re-checked from scratch, so if the work broke something it alerts right away.
          </>
        ) : (
          <span className="muted">
            For planned work: the site won't alert or count as down while the window is open.
          </span>
        )}
      </p>
      {error && <p className="chaos-error">Couldn't update maintenance: {error}</p>}
    </div>
  );
}
