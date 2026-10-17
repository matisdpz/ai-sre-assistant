/**
 * A tiny inline trend line (no axes) for service cards. Plain SVG keeps the overview
 * page free of the charting library. A dashed line marks the warning threshold.
 */
export function Sparkline({
  values,
  threshold,
  label,
  width = 160,
  height = 36,
}: {
  values: (number | null)[];
  threshold?: number | null;
  label: string;
  width?: number;
  height?: number;
}) {
  const known = values.filter((v): v is number => v !== null);
  if (known.length < 2) return <svg width={width} height={height} aria-label={`${label}: no data`} />;
  const max = Math.max(...known, threshold ?? 0) * 1.1 || 1;
  const x = (i: number) => (i / (values.length - 1)) * width;
  const y = (v: number) => height - 2 - (v / max) * (height - 4);

  // Break the line where the service was down (null values).
  let path = "";
  values.forEach((v, i) => {
    if (v === null) return;
    path += `${i === 0 || values[i - 1] === null ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
  });

  return (
    <svg width={width} height={height} role="img" aria-label={label} className="sparkline">
      {threshold != null && (
        <line x1={0} x2={width} y1={y(threshold)} y2={y(threshold)} className="spark-threshold" />
      )}
      <path d={path} className="spark-line" />
    </svg>
  );
}
