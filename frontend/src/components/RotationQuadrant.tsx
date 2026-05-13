import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

import {
  fetchQuadrant,
  type QuadrantPoint,
  type QuadrantResponse,
} from "../api";

const QUAD_COLORS: Record<QuadrantPoint["quadrant"], string> = {
  leaders: "#2d8659",
  fading: "#d97c2e",
  recovering: "#4a6b8a",
  laggards: "#c8424a",
};

const QUAD_LABELS: Record<QuadrantPoint["quadrant"], string> = {
  leaders: "Leaders",
  fading: "Fading",
  recovering: "Recovering",
  laggards: "Laggards",
};

const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;

export function RotationQuadrant() {
  const [kind, setKind] = useState<"factor" | "basket">("factor");
  const [data, setData] = useState<QuadrantResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    fetchQuadrant(kind).then(setData).catch((e) => setError(String(e)));
  }, [kind]);

  const counts = useMemo(() => {
    const c = { leaders: 0, fading: 0, recovering: 0, laggards: 0 };
    data?.points.forEach((p) => (c[p.quadrant] = (c[p.quadrant] ?? 0) + 1));
    return c;
  }, [data]);

  return (
    <section className="bg-cream-50 border border-cream-300 rounded-xl p-6 shadow-sm">
      <header className="flex items-start justify-between mb-4 flex-wrap gap-3">
        <div>
          <h2 className="text-lg font-semibold text-ink-900">
            Rotation Quadrant
          </h2>
          <p className="text-sm text-ink-500 mt-0.5">
            5D return (x) vs 21D return (y) — momentum quadrants
          </p>
        </div>
        <div className="inline-flex rounded-full bg-cream-200 p-1 gap-0.5">
          {(["factor", "basket"] as const).map((k) => (
            <button
              key={k}
              onClick={() => setKind(k)}
              className={`px-3 py-1 text-xs font-medium rounded-full capitalize transition-colors ${
                kind === k
                  ? "bg-forest-800 text-cream-50"
                  : "text-ink-700 hover:text-ink-900"
              }`}
            >
              {k}s
            </button>
          ))}
        </div>
      </header>

      <div className="flex flex-wrap gap-3 mb-4">
        {(["leaders", "fading", "recovering", "laggards"] as const).map((q) => (
          <div
            key={q}
            className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-full bg-cream-100 border border-cream-300"
          >
            <span
              className="w-2 h-2 rounded-full"
              style={{ background: QUAD_COLORS[q] }}
            />
            <span className="text-ink-700">{QUAD_LABELS[q]}</span>
            <span className="text-ink-500 tabular-nums">
              {counts[q] ?? 0}
            </span>
          </div>
        ))}
      </div>

      {error && (
        <div className="text-negative text-sm py-8 text-center">
          Failed to load: {error}
        </div>
      )}

      {data && (
        <div className="h-96">
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 20, right: 20, bottom: 30, left: 20 }}>
              <CartesianGrid stroke="#e8ddc9" strokeDasharray="3 3" />
              <XAxis
                type="number"
                dataKey="x"
                name="5D return"
                tickFormatter={fmtPct}
                tick={{ fill: "#6b6b6b", fontSize: 11 }}
                stroke="#d4c4a6"
                label={{
                  value: "5D Return",
                  position: "insideBottom",
                  offset: -10,
                  fill: "#6b6b6b",
                  fontSize: 11,
                }}
              />
              <YAxis
                type="number"
                dataKey="y"
                name="21D return"
                tickFormatter={fmtPct}
                tick={{ fill: "#6b6b6b", fontSize: 11 }}
                stroke="#d4c4a6"
                label={{
                  value: "21D Return",
                  angle: -90,
                  position: "insideLeft",
                  fill: "#6b6b6b",
                  fontSize: 11,
                }}
              />
              <ZAxis range={[80, 80]} />
              <ReferenceLine x={0} stroke="#9a8f7d" strokeDasharray="3 3" />
              <ReferenceLine y={0} stroke="#9a8f7d" strokeDasharray="3 3" />
              <Tooltip
                cursor={{ stroke: "#d4c4a6", strokeDasharray: "3 3" }}
                contentStyle={{
                  background: "#fbf7ee",
                  border: "1px solid #e8ddc9",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                content={({ active, payload }) => {
                  if (!active || !payload?.[0]) return null;
                  const p = payload[0].payload as QuadrantPoint;
                  return (
                    <div className="bg-cream-50 border border-cream-300 rounded-lg p-2 text-xs shadow-sm">
                      <div className="font-semibold text-ink-900 mb-1">
                        {p.name}
                      </div>
                      <div className="text-ink-700">5D: {fmtPct(p.x)}</div>
                      <div className="text-ink-700">21D: {fmtPct(p.y)}</div>
                      <div
                        className="mt-1 capitalize"
                        style={{ color: QUAD_COLORS[p.quadrant] }}
                      >
                        {p.quadrant}
                      </div>
                    </div>
                  );
                }}
              />
              <Scatter data={data.points} fill="#1a3d36">
                {data.points.map((p, i) => (
                  <Cell key={i} fill={QUAD_COLORS[p.quadrant]} />
                ))}
              </Scatter>
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
