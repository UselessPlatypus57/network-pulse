import { timeAgo } from "../format";
import type { HealthSummary } from "../types";

interface Props {
  summary: HealthSummary | undefined;
  error: Error | undefined;
  lastSuccess: Date | undefined;
}

type Mode = "live" | "stale" | "down" | "loading";

function mode({ summary, error }: Props): Mode {
  if (error) return "down";
  if (!summary) return "loading";
  return summary.evaluator.running ? "live" : "stale";
}

/** Header pill: is the *monitor itself* healthy? */
export function MonitorPill(props: Props) {
  const m = mode(props);
  const text = {
    live: `Live · evaluated ${timeAgo(props.summary?.evaluator.last_run_at)}`,
    stale: "Evaluator stalled",
    down: "API unreachable",
    loading: "Connecting…",
  }[m];
  return (
    <span className={`pill ${m}`} role="status">
      <span className="dot" aria-hidden />
      {text}
    </span>
  );
}

/**
 * When the monitoring pipeline is unhealthy, the dashboard must say so loudly:
 * a frozen "all green" screen is worse than no screen at all.
 */
export function MonitorBanner(props: Props) {
  const m = mode(props);
  if (m === "down") {
    return (
      <div className="banner" role="alert">
        <span aria-hidden>✕</span>
        <div>
          <strong>Monitoring API unreachable</strong>
          <span className="muted">
            Showing the last data received ({props.lastSuccess ? timeAgo(props.lastSuccess.toISOString()) : "none yet"}).
            Site statuses below may be out of date. Retrying automatically.
          </span>
        </div>
      </div>
    );
  }
  if (m === "stale") {
    const ev = props.summary!.evaluator;
    return (
      <div className="banner warn" role="alert">
        <span aria-hidden>▲</span>
        <div>
          <strong>Health evaluator is not running</strong>
          <span className="muted">
            Last evaluation {timeAgo(ev.last_run_at)}
            {ev.last_error ? ` — ${ev.last_error}` : ""}. Metrics are still being received, but statuses are frozen.
          </span>
        </div>
      </div>
    );
  }
  return null;
}
