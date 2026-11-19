import { STATUS_ICON, STATUS_LABEL, STATUS_ORDER, fmt, secs } from "../format";
import type { FleetUptime, HealthSummary, SiteStatus } from "../types";

interface Props {
  summary: HealthSummary | undefined;
  uptime: FleetUptime | undefined;
  filter: SiteStatus | null;
  onFilter: (s: SiteStatus | null) => void;
}

export function SummaryTiles({ summary, uptime, filter, onFilter }: Props) {
  const total = summary?.total ?? 0;
  return (
    <section className="tiles" aria-label="Fleet health summary">
      {STATUS_ORDER.map((s) => {
        const n = summary?.counts[s] ?? 0;
        const share = total ? Math.round((n / total) * 100) : 0;
        return (
          <button
            key={s}
            className="tile"
            aria-pressed={filter === s}
            onClick={() => onFilter(filter === s ? null : s)}
            title={`Show only ${STATUS_LABEL[s].toLowerCase()} sites`}
          >
            <span className={`label status ${s}`}>
              <span className="icon" aria-hidden>
                {STATUS_ICON[s]}
              </span>
              {STATUS_LABEL[s]}
            </span>
            <span className="value num">{summary ? n : "–"}</span>
            <span className="sub">{summary ? `${share}% of ${total} sites` : " "}</span>
          </button>
        );
      })}
      <div className="tile static">
        <span className="label">Open alerts</span>
        <span className="value num">{summary ? summary.open_alerts : "–"}</span>
        <span className="sub">one per affected site</span>
      </div>
      <div className="tile static" title="Share of observed time not offline, across all sites, last 24 hours">
        <span className="label">24h availability</span>
        <span className="value num">{fmt.uptime(uptime?.available_pct)}</span>
        <span className="sub">
          {uptime ? `${uptime.incidents} incident${uptime.incidents === 1 ? "" : "s"} · MTTR ${secs(uptime.mttr_s)}` : " "}
        </span>
      </div>
    </section>
  );
}
