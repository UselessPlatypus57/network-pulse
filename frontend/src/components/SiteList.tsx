import { useMemo, useState } from "react";
import { STATUS_LABEL, STATUS_ORDER, duration, fmt } from "../format";
import type { Site, SiteStatus } from "../types";
import { StatusBadge } from "./StatusBadge";

interface Props {
  sites: Site[] | undefined;
  filter: SiteStatus | null;
  onFilter: (s: SiteStatus | null) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

const rank = (s: SiteStatus) => STATUS_ORDER.indexOf(s);

export function SiteList({ sites, filter, onFilter, selectedId, onSelect }: Props) {
  const [query, setQuery] = useState("");

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (sites ?? [])
      .filter((s) => !filter || s.status === filter)
      .filter((s) => !q || `${s.id} ${s.name} ${s.region}`.toLowerCase().includes(q))
      // Worst first, then longest in that state, then by id.
      .sort((a, b) => rank(a.status) - rank(b.status) || a.status_since.localeCompare(b.status_since) || a.id.localeCompare(b.id));
  }, [sites, filter, query]);

  return (
    <section className="card" aria-label="Cell sites">
      <div className="card-header">
        <h2 className="card-title">Sites</h2>
        <span className="muted num">
          {rows.length} / {sites?.length ?? 0}
        </span>
      </div>
      <div className="card-body toolbar">
        <input
          className="search"
          type="search"
          placeholder="Search id, name, region…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search sites"
        />
        <button className="chip" aria-pressed={filter === null} onClick={() => onFilter(null)}>
          All
        </button>
        {STATUS_ORDER.map((s) => (
          <button key={s} className="chip" aria-pressed={filter === s} onClick={() => onFilter(filter === s ? null : s)}>
            {STATUS_LABEL[s]}
          </button>
        ))}
      </div>
      <div className="table-wrap">
        <table className="sites">
          <thead>
            <tr>
              <th>Site</th>
              <th>Status</th>
              <th className="r">Latency</th>
              <th className="r">Loss</th>
              <th className="r">Avail.</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id} aria-selected={s.id === selectedId} onClick={() => onSelect(s.id)}>
                <td>
                  <div className="site-id">{s.id}</div>
                  <div className="site-name">
                    {s.name} · {s.technology}
                  </div>
                </td>
                <td>
                  <StatusBadge status={s.status} />
                  <div className="pending">
                    {s.pending_status
                      ? `→ ${STATUS_LABEL[s.pending_status].toLowerCase()}? (${s.pending_count} checks)`
                      : `for ${duration(s.status_since)}`}
                  </div>
                </td>
                <td className="r num">{fmt.ms(s.window_latency_ms)}</td>
                <td className="r num">{fmt.pct(s.window_packet_loss_pct, 1)}</td>
                <td className="r num">{fmt.pct(s.window_availability_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {sites && rows.length === 0 && <div className="empty">No sites match.</div>}
        {!sites && <div className="empty">Loading sites…</div>}
      </div>
    </section>
  );
}
