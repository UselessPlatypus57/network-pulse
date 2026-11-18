import { STATUS_ICON, STATUS_LABEL, STATUS_ORDER } from "../format";
import type { HealthSummary, SiteStatus } from "../types";

interface Props {
  summary: HealthSummary | undefined;
  filter: SiteStatus | null;
  onFilter: (s: SiteStatus | null) => void;
}

export function SummaryTiles({ summary, filter, onFilter }: Props) {
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
    </section>
  );
}
