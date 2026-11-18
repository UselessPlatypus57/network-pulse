import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmt } from "../format";
import type { MetricPoint } from "../types";

type Key = "latency_ms" | "packet_loss_pct" | "availability_pct";

interface Props {
  title: string;
  data: MetricPoint[];
  dataKey: Key;
  unit: string;
  format: (v: number) => string;
  threshold: number;
  thresholdLabel: string;
  /** Lower is worse (availability) - pins the y-domain top at 100. */
  lowerIsWorse?: boolean;
}

/** Round up to 1, 2 or 5 x 10^n so axis ticks land on readable values. */
function niceCeil(x: number): number {
  if (x <= 0) return 1;
  const mag = 10 ** Math.floor(Math.log10(x));
  return ([1, 2, 5, 10].find((m) => m * mag >= x) ?? 10) * mag;
}

function domain(values: number[], threshold: number, lowerIsWorse: boolean): [number, number] {
  if (lowerIsWorse) {
    const lo = Math.min(threshold, ...values);
    return [Math.max(0, Math.floor(lo - (100 - lo) * 0.25)), 100];
  }
  const hi = Math.max(threshold, ...values);
  return [0, niceCeil(hi * 1.1)];
}

/**
 * One metric, one axis. Latency, loss and availability live on different
 * scales, so they are three small charts rather than one dual-axis chart.
 */
export function MetricChart({ title, data, dataKey, unit, format, threshold, thresholdLabel, lowerIsWorse = false }: Props) {
  const values = data.map((d) => d[dataKey]);
  const latest = values.at(-1);
  const rows = data.map((d) => ({ t: new Date(d.ts).getTime(), v: d[dataKey] }));

  return (
    <figure className="metric-chart">
      <figcaption>
        <span className="metric-title">{title}</span>
        <span className="metric-latest num">{latest == null ? "—" : format(latest)}</span>
      </figcaption>
      <div className="metric-plot">
        {rows.length === 0 ? (
          <div className="empty">No samples in range</div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--grid)" strokeWidth={1} />
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(t: number) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                tick={{ fill: "var(--text-muted)", fontSize: 11 }}
                stroke="var(--axis)"
                minTickGap={40}
              />
              <YAxis
                domain={domain(values, threshold, lowerIsWorse)}
                tick={{ fill: "var(--text-muted)", fontSize: 11 }}
                stroke="var(--axis)"
                width={44}
                tickFormatter={(v: number) => `${+v.toFixed(2)}`}
                allowDecimals
              />
              <ReferenceLine
                y={threshold}
                stroke="var(--status-degraded)"
                strokeDasharray="4 4"
                strokeWidth={1}
                label={{ value: thresholdLabel, position: "insideTopRight", fill: "var(--text-muted)", fontSize: 11 }}
              />
              <Tooltip
                cursor={{ stroke: "var(--text-muted)", strokeWidth: 1 }}
                isAnimationActive={false}
                content={({ active, payload }) =>
                  active && payload?.length ? (
                    <div className="chart-tip">
                      <div className="muted">{fmt.clock(new Date(payload[0].payload.t).toISOString())}</div>
                      <strong className="num">{format(payload[0].payload.v)}</strong>
                    </div>
                  ) : null
                }
              />
              <Line
                type="monotone"
                dataKey="v"
                name={unit}
                stroke="var(--accent)"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, stroke: "var(--surface-1)", strokeWidth: 2 }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </figure>
  );
}
