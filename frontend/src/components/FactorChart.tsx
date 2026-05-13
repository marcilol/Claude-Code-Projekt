import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  fetchFactorTimeseries,
  type FactorTimeseriesResponse,
  type Timeframe,
} from "../api";
import { colorForIndex } from "../theme";
import { TimeframePills } from "./TimeframePills";

const fmtPct = (v: number) => `${(v * 100).toFixed(2)}%`;

export function FactorChart() {
  const [timeframe, setTimeframe] = useState<Timeframe>("1Y");
  const [data, setData] = useState<FactorTimeseriesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  useEffect(() => {
    setError(null);
    fetchFactorTimeseries(timeframe)
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [timeframe]);

  const visibleFactors = useMemo(
    () => (data ? data.factors.filter((f) => !hidden.has(f.key)) : []),
    [data, hidden]
  );

  const toggle = (key: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <section className="bg-cream-50 border border-cream-300 rounded-xl p-6 shadow-sm">
      <header className="flex items-start justify-between mb-4 flex-wrap gap-3">
        <div>
          <h2 className="text-lg font-semibold text-ink-900">
            Cumulative Factor Returns
          </h2>
          <p className="text-sm text-ink-500 mt-0.5">
            Style factors only — Russell 3000 universe
          </p>
        </div>
        <TimeframePills value={timeframe} onChange={setTimeframe} />
      </header>

      {error && (
        <div className="text-negative text-sm py-8 text-center">
          Failed to load: {error}
        </div>
      )}

      {!error && !data && (
        <div className="text-ink-500 text-sm py-8 text-center">Loading…</div>
      )}

      {data && (
        <>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data.rows}>
                <CartesianGrid stroke="#e8ddc9" strokeDasharray="3 3" />
                <XAxis
                  dataKey="date"
                  tick={{ fill: "#6b6b6b", fontSize: 11 }}
                  stroke="#d4c4a6"
                  minTickGap={40}
                />
                <YAxis
                  tickFormatter={fmtPct}
                  tick={{ fill: "#6b6b6b", fontSize: 11 }}
                  stroke="#d4c4a6"
                />
                <Tooltip
                  formatter={(v: number) => fmtPct(v)}
                  contentStyle={{
                    background: "#fbf7ee",
                    border: "1px solid #e8ddc9",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  labelStyle={{ color: "#1a1f24", fontWeight: 600 }}
                />
                <Legend
                  verticalAlign="bottom"
                  height={36}
                  iconType="line"
                  wrapperStyle={{ fontSize: 12 }}
                />
                {visibleFactors.map((f) => (
                  <Line
                    key={f.key}
                    type="monotone"
                    dataKey={f.key}
                    name={f.name}
                    stroke={colorForIndex(
                      data.factors.findIndex((x) => x.key === f.key)
                    )}
                    strokeWidth={1.75}
                    dot={false}
                    isAnimationActive={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            {data.factors.map((f, i) => {
              const isHidden = hidden.has(f.key);
              const color = colorForIndex(i);
              return (
                <button
                  key={f.key}
                  onClick={() => toggle(f.key)}
                  className={`text-xs px-2.5 py-1 rounded-full border transition-opacity ${
                    isHidden
                      ? "opacity-40 border-cream-300 bg-cream-100"
                      : "border-cream-300 bg-cream-50"
                  }`}
                  style={{ color }}
                  aria-pressed={!isHidden}
                >
                  <span
                    className="inline-block w-2 h-2 rounded-full mr-1.5 align-middle"
                    style={{ background: color }}
                  />
                  {f.name}
                </button>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}
