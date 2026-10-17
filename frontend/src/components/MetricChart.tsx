import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatTime } from "../format";
import type { MetricPoint } from "../types";

export interface Threshold {
  warning: number | null;
  critical: number;
}

interface Props {
  title: string;
  unit: string;
  points: MetricPoint[];
  value: (point: MetricPoint) => number;
  threshold?: Threshold;
  domainMax?: number; // fixed top of the y-axis, e.g. 100 for a percentage
}

/** Contiguous runs of samples where the service was down, to shade them. */
function downRanges(points: MetricPoint[]): [string, string][] {
  const ranges: [string, string][] = [];
  let start: string | null = null;
  points.forEach((point, i) => {
    if (!point.up && start === null) start = point.ts;
    const endOfRun = start !== null && (point.up || i === points.length - 1);
    if (endOfRun) {
      ranges.push([start as string, point.ts]);
      start = null;
    }
  });
  return ranges;
}

/** Round up to 1, 2 or 5 times a power of ten, so the top tick is a readable number. */
export function niceCeil(value: number): number {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 5, 10].find((m) => m * power >= value) ?? 10;
  return step * power;
}

/** One metric over time: a single line, threshold lines, outages shaded. One y-axis. */
export function MetricChart({ title, unit, points, value, threshold, domainMax }: Props) {
  const data = points.map((p) => ({ ts: p.ts, value: p.up ? value(p) : null }));
  const latest = [...points].reverse().find((p) => p.up);
  const suffix = unit ? ` ${unit}` : "";
  const dataMax = Math.max(0, ...data.map((d) => d.value ?? 0));
  // Bounded metrics (CPU %) use their fixed maximum; others leave room above the critical line.
  const top = domainMax ?? niceCeil(Math.max(dataMax, (threshold?.critical ?? 0) * 1.15));

  return (
    <div className="card">
      <div className="chart-title">
        <h3>{title}</h3>
        <span className="secondary">
          {latest ? `now ${value(latest).toFixed(1)}${suffix}` : "no data"}
        </span>
      </div>
      <div style={{ height: 200 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 56, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis
              dataKey="ts"
              tickFormatter={formatTime}
              stroke="var(--axis)"
              tick={{ fill: "var(--muted)", fontSize: 11 }}
              minTickGap={48}
            />
            <YAxis
              width={44}
              domain={[0, top]}
              stroke="var(--axis)"
              tick={{ fill: "var(--muted)", fontSize: 11 }}
            />
            {downRanges(points).map(([x1, x2]) => (
              <ReferenceArea key={x1} x1={x1} x2={x2} fill="var(--down-fill)" ifOverflow="hidden" />
            ))}
            {threshold?.warning != null && (
              <ReferenceLine
                y={threshold.warning}
                stroke="var(--warning)"
                strokeDasharray="4 4"
                label={{ value: "warning", position: "right", fill: "var(--ink-2)", fontSize: 11 }}
              />
            )}
            {threshold && (
              <ReferenceLine
                y={threshold.critical}
                stroke="var(--critical)"
                strokeDasharray="4 4"
                label={{ value: "critical", position: "right", fill: "var(--ink-2)", fontSize: 11 }}
              />
            )}
            <Tooltip
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                const v = payload[0].value;
                return (
                  <div className="chart-tooltip">
                    <div className="muted">{formatTime(String(label))}</div>
                    <div>{v == null ? "service down" : `${Number(v).toFixed(1)}${suffix}`}</div>
                  </div>
                );
              }}
              cursor={{ stroke: "var(--axis)" }}
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke="var(--series-1)"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }}
              isAnimationActive={false}
              connectNulls={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
