import "leaflet/dist/leaflet.css";
import type { LatLngBoundsExpression } from "leaflet";
import { useEffect, useMemo, useRef } from "react";
import { CircleMarker, MapContainer, TileLayer, Tooltip, useMap } from "react-leaflet";
import { STATUS_ICON, STATUS_LABEL, STATUS_ORDER, fmt } from "../format";
import { cssVar, useColorScheme } from "../hooks/useColorScheme";
import type { Site, SiteStatus } from "../types";

interface Props {
  sites: Site[] | undefined;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

// Draw healthy first so problems always sit on top of the stack.
const Z: Record<SiteStatus, number> = { unknown: 0, healthy: 1, maintenance: 2, degraded: 3, offline: 4 };

// Standard OSM tiles (no API key). Dark mode re-inks them with a CSS filter on
// the tile pane (see .map.dark in styles.css) rather than a second provider.
const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

function FitOnce({ bounds }: { bounds: LatLngBoundsExpression | null }) {
  const map = useMap();
  const done = useRef(false);
  useEffect(() => {
    if (bounds && !done.current) {
      map.fitBounds(bounds, { padding: [24, 24] });
      done.current = true;
    }
  }, [bounds, map]);
  return null;
}

function FollowSelection({ site }: { site: Site | undefined }) {
  const map = useMap();
  useEffect(() => {
    if (site && !map.getBounds().pad(-0.1).contains([site.latitude, site.longitude])) {
      map.panTo([site.latitude, site.longitude]);
    }
  }, [site?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

export function SiteMap({ sites, selectedId, onSelect }: Props) {
  const scheme = useColorScheme();
  const colors = useMemo(
    () => ({
      healthy: cssVar("--status-healthy"),
      degraded: cssVar("--status-degraded"),
      offline: cssVar("--status-offline"),
      unknown: cssVar("--status-unknown"),
      maintenance: cssVar("--status-maintenance"),
      ring: cssVar("--surface-1"),
      accent: cssVar("--accent"),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [scheme],
  );

  const bounds = useMemo<LatLngBoundsExpression | null>(() => {
    if (!sites?.length) return null;
    const lats = sites.map((s) => s.latitude);
    const lons = sites.map((s) => s.longitude);
    return [
      [Math.min(...lats), Math.min(...lons)],
      [Math.max(...lats), Math.max(...lons)],
    ];
  }, [sites?.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const ordered = useMemo(
    () => [...(sites ?? [])].sort((a, b) => Z[a.status] - Z[b.status] || Number(a.id === selectedId) - Number(b.id === selectedId)),
    [sites, selectedId],
  );
  const counts = useMemo(() => {
    const c: Record<SiteStatus, number> = { healthy: 0, degraded: 0, offline: 0, unknown: 0, maintenance: 0 };
    sites?.forEach((s) => c[s.status]++);
    return c;
  }, [sites]);

  return (
    <section className="card map-card" aria-label="Site map">
      <div className="card-header">
        <h2 className="card-title">Coverage map · Houston metro</h2>
        <span className="muted">Scroll to zoom · drag to pan · click a site for details</span>
      </div>
      <div className="map-wrap">
        {/* Scroll-wheel zoom in half-level steps so a trackpad or mouse wheel feels smooth, not jumpy. */}
        <MapContainer
          center={[29.76, -95.37]}
          zoom={10}
          scrollWheelZoom
          zoomSnap={0.5}
          zoomDelta={0.5}
          wheelPxPerZoomLevel={120}
          className={`map ${scheme}`}
          attributionControl
        >
          <TileLayer url={TILE_URL} attribution={ATTRIBUTION} maxZoom={19} />
          <FitOnce bounds={bounds} />
          <FollowSelection site={sites?.find((s) => s.id === selectedId)} />
          {ordered.map((s) => {
            const selected = s.id === selectedId;
            return (
              <CircleMarker
                key={s.id}
                center={[s.latitude, s.longitude]}
                radius={selected ? 11 : s.status === "healthy" ? 7 : 9}
                pathOptions={{
                  color: selected ? colors.accent : colors.ring,
                  weight: selected ? 3 : 2,
                  fillColor: colors[s.status],
                  fillOpacity: 0.95,
                  className: `site-marker ${s.status}`,
                }}
                eventHandlers={{ click: () => onSelect(s.id) }}
              >
                <Tooltip direction="top" offset={[0, -8]} opacity={1}>
                  <div className="map-tip">
                    <strong>{s.id}</strong> · {s.name}
                    <div>
                      {STATUS_ICON[s.status]} {STATUS_LABEL[s.status]}
                      {s.status !== "unknown" && ` · ${fmt.ms(s.window_latency_ms)} · ${fmt.pct(s.window_packet_loss_pct, 1)} loss`}
                    </div>
                    {s.reasons.length > 0 && <div className="map-tip-reason">{s.reasons.join("; ")}</div>}
                  </div>
                </Tooltip>
              </CircleMarker>
            );
          })}
        </MapContainer>
        <div className="map-legend" aria-label="Legend">
          {STATUS_ORDER.map((s) => (
            <span key={s} className={`status ${s}`}>
              <span className="icon" aria-hidden>
                {STATUS_ICON[s]}
              </span>
              {STATUS_LABEL[s]} <span className="muted num">{counts[s]}</span>
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}
