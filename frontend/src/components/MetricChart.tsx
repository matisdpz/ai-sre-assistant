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

/** A period to shade (the incident) and point annotations (incident starts). */
export interface Highlight {
  from: string;
  to: string | null; // null: still ongoing
}
export interface Marker {
  ts: string;
  label: string;
}

interface Props {
  title: string;
  unit: string;
  points: MetricPoint[];
  value: (point: MetricPoint) => number;
  threshold?: Threshold;
  domainMax?: number; // fixed top of the y-axis, e.g. 100 for a percentage
  highlight?: Highlight;
  markers?: Marker[];
  height?: number;
}

/** Round up to 1, 2 or 5 times a power of ten, so the top tick is a readable number. */
export function niceCeil(value: number): number {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 5, 10].find((m) => m * power >= value) ?? 10;
  return step * power;
}

/** Contiguous runs of samples where the service was down, as [start, end] times in ms. */
export function downRanges(points: MetricPoint[]): [number, number][] {
  const ranges: [number, number][] = [];
  let start: number | null = null;
  points.forEach((point, i) => {
    const t = Date.parse(point.ts);
    if (!point.up && start === null) start = t;
    if (start !== null && (point.up || i === points.length - 1)) {
      ranges.push([start, t]);
      start = null;
    }
  });
  return ranges;
}

/** One metric over time: one line, threshold lines, outages and incidents shaded. One y-axis. */
export function MetricChart({
  title,
  unit,
  points,
  value,
  threshold,
  domainMax,
  highlight,
  markers = [],
  height = 200,
}: Props) {
  const data = points.map((p) => ({ t: Date.parse(p.ts), value: p.up ? value(p) : null }));
  const latest = [...points].reverse().find((p) => p.up);
  const suffix = unit ? ` ${unit}` : "";
  const dataMax = Math.max(0, ...data.map((d) => d.value ?? 0));
  // Bounded metrics (CPU %) use their fixed maximum; others leave room above the critical line.
  const top = domainMax ?? niceCeil(Math.max(dataMax, (threshold?.critical ?? 0) * 1.15));
  const first = data[0]?.t ?? 0;
  const last = data[data.length - 1]?.t ?? 0;
  const clamp = (t: number) => Math.min(Math.max(t, first), last);

  return (
    <div className="card chart-card">
      <div className="chart-title">
        <h3>{title}</h3>
        <span className="chart-now">
          {latest ? `${value(latest).toFixed(1)}${suffix}` : "no data"}
        </span>
      </div>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 56, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={[first, last]}
              tickFormatter={(t: number) => formatTime(new Date(t).toISOString())}
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
            {highlight && (
              <ReferenceArea
                x1={clamp(Date.parse(highlight.from))}
                x2={clamp(highlight.to ? Date.parse(highlight.to) : last)}
                fill="var(--incident-fill)"
                ifOverflow="hidden"
              />
            )}
            {downRanges(points).map(([x1, x2]) => (
              <ReferenceArea key={x1} x1={x1} x2={x2} fill="var(--down-fill)" ifOverflow="hidden" />
            ))}
            {markers
              .filter((m) => Date.parse(m.ts) >= first && Date.parse(m.ts) <= last)
              .map((m) => (
                <ReferenceLine
                  key={m.ts + m.label}
                  x={Date.parse(m.ts)}
                  stroke="var(--marker)"
                  strokeDasharray="2 3"
                  label={{ value: m.label, position: "insideTopLeft", fill: "var(--ink-2)", fontSize: 10 }}
                />
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
                    <div className="muted">{formatTime(new Date(Number(label)).toISOString())}</div>
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
