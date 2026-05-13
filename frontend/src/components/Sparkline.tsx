interface Props {
  data: number[];
  width?: number;
  height?: number;
  stroke?: string;
}

export function Sparkline({
  data,
  width = 80,
  height = 24,
  stroke,
}: Props) {
  if (!data || data.length === 0) {
    return <div style={{ width, height }} />;
  }

  const min = Math.min(...data, 0);
  const max = Math.max(...data, 0);
  const range = max - min || 1;
  const last = data[data.length - 1];

  const color = stroke ?? (last >= 0 ? "#2d8659" : "#c8424a");

  const stepX = width / Math.max(1, data.length - 1);
  const points = data
    .map((v, i) => {
      const x = i * stepX;
      const y = height - ((v - min) / range) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  // Zero-line position
  const zeroY = height - ((0 - min) / range) * height;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <line
        x1={0}
        x2={width}
        y1={zeroY}
        y2={zeroY}
        stroke="#e8ddc9"
        strokeDasharray="2 2"
        strokeWidth={0.75}
      />
      <polyline
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        points={points}
      />
    </svg>
  );
}
