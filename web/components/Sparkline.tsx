/**
 * Hand-rolled SVG sparkline. No chart library: fourteen points do not earn a
 * dependency. The line is the accent; the area fill is a whisper of it.
 */
export function Sparkline({
  values,
  label,
  width = 120,
  height = 32,
}: {
  values: number[];
  label: string;
  width?: number;
  height?: number;
}) {
  if (!values.length) return null;

  const max = Math.max(...values, 0.000001);
  const stepX = values.length > 1 ? width / (values.length - 1) : width;
  const points = values.map((value, index) => {
    const x = index * stepX;
    const y = height - 2 - (value / max) * (height - 4);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const line = points.join(" ");
  const area = `0,${height} ${line} ${width},${height}`;

  return (
    <svg
      role="img"
      aria-label={label}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="block"
    >
      <polygon points={area} className="fill-accent/10" />
      <polyline
        points={line}
        fill="none"
        className="stroke-accent/80"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
