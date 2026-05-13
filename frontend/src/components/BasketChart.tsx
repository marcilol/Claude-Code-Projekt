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
  fetchBasketTimeseries,
  fetchBaskets,
  type BasketMeta,
  type BasketTimeseriesResponse,
  type Timeframe,
} from "../api";
import { colorForIndex } from "../theme";
import { TimeframePills } from "./TimeframePills";

const fmtPct = (v: number) => `${(v * 100).toFixed(2)}%`;

const DEFAULT_PICK = 6; // start with 6 baskets visible

export function BasketChart() {
  const [timeframe, setTimeframe] = useState<Timeframe>("1Y");
  const [allBaskets, setAllBaskets] = useState<BasketMeta[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [data, setData] = useState<BasketTimeseriesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Initial load — get full basket list, default-select the first N
  useEffect(() => {
    fetchBaskets()
      .then((r) => {
        setAllBaskets(r.baskets);
        setSelected(r.baskets.slice(0, DEFAULT_PICK).map((b) => b.key));
      })
      .catch((e) => setError(String(e)));
  }, []);

  // Fetch series whenever timeframe or selection changes
  useEffect(() => {
    if (selected.length === 0) {
      setData({ timeframe, baskets: [], rows: [] });
      return;
    }
    setError(null);
    fetchBasketTimeseries(timeframe, selected)
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [timeframe, selected]);

  const toggle = (key: string) => {
    setSelected((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  };

  const colorMap = useMemo(() => {
    const m: Record<string, string> = {};
    selected.forEach((k, i) => (m[k] = colorForIndex(i)));
    return m;
  }, [selected]);

  return (
    <section className="bg-cream-50 border border-cream-300 rounded-xl p-6 shadow-sm">
      <header className="flex items-start justify-between mb-4 flex-wrap gap-3">
        <div>
          <h2 className="text-lg font-semibold text-ink-900">
            Cumulative Basket Returns
          </h2>
          <p className="text-sm text-ink-500 mt-0.5">
            Citrini-style thematic baskets — cap-weighted constant-weight backtest
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
                {data.baskets.map((b) => (
                  <Line
                    key={b.key}
                    type="monotone"
                    dataKey={b.key}
                    name={b.name}
                    stroke={colorMap[b.key] ?? "#1a3d36"}
                    strokeWidth={1.75}
                    dot={false}
                    isAnimationActive={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="mt-4">
            <div className="text-xs text-ink-500 mb-2">
              {selected.length} of {allBaskets.length} baskets shown — click to toggle
            </div>
            <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto pr-2">
              {allBaskets.map((b) => {
                const isOn = selected.includes(b.key);
                const color = colorMap[b.key] ?? "#3d4148";
                return (
                  <button
                    key={b.key}
                    onClick={() => toggle(b.key)}
                    className={`text-xs px-2.5 py-1 rounded-full border transition-opacity ${
                      isOn
                        ? "border-cream-300 bg-cream-50"
                        : "opacity-50 border-cream-300 bg-cream-100 hover:opacity-80"
                    }`}
                    style={{ color: isOn ? color : undefined }}
                    aria-pressed={isOn}
                  >
                    <span
                      className="inline-block w-2 h-2 rounded-full mr-1.5 align-middle"
                      style={{ background: isOn ? color : "#9a8f7d" }}
                    />
                    {b.name}
                  </button>
                );
              })}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
