import { useState } from "react";
import { api } from "../api";
import { duration } from "../format";
import type { Fault, FaultKind } from "../types";

interface Props {
  siteId: string;
  fault: Fault | undefined;
  onChange: () => void;
}

const FAULTS: { kind: FaultKind; label: string; expect: string }[] = [
  { kind: "latency", label: "Latency spike", expect: "Expect DEGRADED once most of the window is slow, then a warning alert." },
  { kind: "packet_loss", label: "Packet loss", expect: "Expect DEGRADED (loss and availability breach), then a warning alert." },
  { kind: "outage", label: "Site outage", expect: "Site stops reporting. Expect OFFLINE when the heartbeat goes stale, then a critical alert." },
  { kind: "flap", label: "Flapping", expect: "Brief spikes on every third sample. Expect NO status change and NO alert." },
];

const DURATIONS = [60, 120, 300];

export function ChaosControls({ siteId, fault, onChange }: Props) {
  const [durationS, setDurationS] = useState(120);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

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

  const active = FAULTS.find((f) => f.kind === fault?.fault);

  return (
    <div className="chaos">
      <div className="chaos-head">
        <span className="fact-label">Chaos testing</span>
        <label className="muted chaos-duration">
          for{" "}
          <select value={durationS} onChange={(e) => setDurationS(Number(e.target.value))} aria-label="Fault duration">
            {DURATIONS.map((d) => (
              <option key={d} value={d}>
                {d < 120 ? `${d}s` : `${d / 60} min`}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="chaos-buttons">
        {FAULTS.map((f) => (
          <button
            key={f.kind}
            className="chaos-btn"
            aria-pressed={fault?.fault === f.kind}
            disabled={busy}
            title={f.expect}
            onClick={() => act(() => api.injectFault(siteId, f.kind, durationS))}
          >
            {f.label}
          </button>
        ))}
        <button className="chaos-btn clear" disabled={busy || !fault} onClick={() => act(() => api.clearFault(siteId))}>
          Clear
        </button>
      </div>
      <p className="chaos-status" role="status">
        {active && fault ? (
          <>
            <strong>{active.label}</strong> injected · ends in {duration(new Date().toISOString(), fault.expires_at)}. {active.expect}
          </>
        ) : (
          <span className="muted">
            Inject a fault to watch detection, alerting and recovery end to end. The monitor isn't told about faults; it
            only sees the metrics.
          </span>
        )}
      </p>
      {error && <p className="chaos-error">Couldn't apply fault: {error}</p>}
    </div>
  );
}
