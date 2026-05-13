import { useEffect, useMemo, useState } from "react";
import {
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

import { fetchPortfolio, type PortfolioResponse } from "../api";

const SECTOR_COLORS = [
  "#1a3d36",
  "#2d8659",
  "#4a6b8a",
  "#d97c2e",
  "#8b4789",
  "#b89324",
  "#5a7a3a",
  "#a04545",
  "#3a6b7a",
  "#c8424a",
  "#6b6b6b",
];

const fmtPct = (v: number) => `${v.toFixed(1)}%`;
const fmt$ = (v: number) =>
  v.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });

interface KpiProps {
  label: string;
  value: string;
  sub?: string;
  accent?: "default" | "positive" | "negative";
}

function Kpi({ label, value, sub, accent = "default" }: KpiProps) {
  const valueClass =
    accent === "positive"
      ? "text-positive"
      : accent === "negative"
      ? "text-negative"
      : "text-ink-900";
  return (
    <div className="bg-cream-50 border border-cream-300 rounded-xl p-5 shadow-sm">
      <div className="text-xs uppercase tracking-wide text-ink-500 mb-1.5">
        {label}
      </div>
      <div className={`text-2xl font-semibold tabular-nums ${valueClass}`}>
        {value}
      </div>
      {sub && <div className="text-xs text-ink-500 mt-1">{sub}</div>}
    </div>
  );
}

export function PortfolioPage() {
  const [data, setData] = useState<PortfolioResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPortfolio().then(setData).catch((e) => setError(String(e)));
  }, []);

  const styleFactors = data?.mcfr_matrix.style_factors ?? [];

  const matrixMaxAbs = useMemo(() => {
    if (!data) return 1;
    let m = 0;
    for (const row of data.mcfr_matrix.rows) {
      for (const f of styleFactors) {
        m = Math.max(m, Math.abs(row.by_factor[f] ?? 0));
      }
    }
    return m || 1;
  }, [data, styleFactors]);

  const cellColor = (v: number) => {
    if (!Number.isFinite(v) || v === 0) return "transparent";
    const a = Math.min(1, Math.abs(v) / matrixMaxAbs);
    return v > 0
      ? `rgba(45, 134, 89, ${a * 0.55 + 0.05})`
      : `rgba(200, 66, 74, ${a * 0.55 + 0.05})`;
  };

  if (error) {
    return (
      <div className="bg-cream-50 border border-negative/30 rounded-xl p-6 text-negative">
        Failed to load portfolio: {error}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-cream-50 border border-cream-300 rounded-xl p-6 text-ink-500">
        Loading portfolio analysis…
      </div>
    );
  }

  const d = data.decomposition;

  return (
    <div className="space-y-6">
      {/* Header */}
      <section className="bg-cream-50 border border-cream-300 rounded-xl p-6 shadow-sm">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold text-ink-900">
              {data.portfolio_path}
            </h2>
            <p className="text-sm text-ink-500 mt-0.5">
              {data.n_positions} positions priced &middot; as of {data.as_of} &middot; total {fmt$(data.total_value)}
            </p>
          </div>
          {data.skipped_not_in_universe.length > 0 && (
            <div className="text-xs text-ink-500">
              Skipped (not in Russell 3000):{" "}
              <span className="text-ink-700">
                {data.skipped_not_in_universe.join(", ")}
              </span>
            </div>
          )}
        </div>
      </section>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Kpi
          label="Annualized Vol"
          value={fmtPct(d.total_vol_annual_pct)}
          sub="total portfolio vol"
        />
        <Kpi
          label="Factor Variance"
          value={fmtPct(d.pct_factor)}
          sub={`${fmtPct(d.factor_vol_annual_pct)} factor vol`}
          accent={d.pct_factor > 50 ? "negative" : "default"}
        />
        <Kpi
          label="Idio Variance"
          value={fmtPct(d.pct_idio)}
          sub="stock-specific risk"
          accent={d.pct_idio > 50 ? "positive" : "default"}
        />
        <Kpi
          label="Positions"
          value={String(data.n_positions)}
          sub={`${data.skipped_not_in_universe.length} skipped`}
        />
      </div>

      {/* Returns explained banner */}
      <section className="bg-cream-50 border border-cream-300 rounded-xl p-6 shadow-sm">
        <h3 className="text-base font-semibold text-ink-900 mb-2">
          Returns Explained by Factors
        </h3>
        <p className="text-sm text-ink-500 mb-4">
          Of the portfolio's annualized variance, {fmtPct(d.pct_factor)} comes from systematic factor exposures and {fmtPct(d.pct_idio)} from stock-specific (idiosyncratic) risk.
        </p>
        <div className="h-3 bg-cream-200 rounded-full overflow-hidden flex">
          <div
            className="bg-forest-800"
            style={{ width: `${d.pct_factor}%` }}
            title={`Factor: ${fmtPct(d.pct_factor)}`}
          />
          <div
            className="bg-positive"
            style={{ width: `${d.pct_idio}%` }}
            title={`Idio: ${fmtPct(d.pct_idio)}`}
          />
        </div>
        <div className="flex justify-between text-xs mt-2">
          <span className="text-forest-800 font-medium">
            Factor {fmtPct(d.pct_factor)}
          </span>
          <span className="text-positive font-medium">
            Idiosyncratic {fmtPct(d.pct_idio)}
          </span>
        </div>
      </section>

      {/* MCFR by factor */}
      <section className="bg-cream-50 border border-cream-300 rounded-xl p-6 shadow-sm">
        <h3 className="text-base font-semibold text-ink-900 mb-1">
          Marginal Contribution to Factor Risk
        </h3>
        <p className="text-sm text-ink-500 mb-4">
          % of factor variance attributable to each factor — sorted by absolute contribution
        </p>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-ink-500 border-b border-cream-300">
              <th className="font-medium pb-2 pr-4">Factor</th>
              <th className="font-medium pb-2 pr-4">Type</th>
              <th className="font-medium pb-2 pr-4 text-right">Exposure</th>
              <th className="font-medium pb-2 text-right">MCFR %</th>
            </tr>
          </thead>
          <tbody>
            {data.mcfr.slice(0, 15).map((r) => (
              <tr
                key={r.factor}
                className="border-b border-cream-200 last:border-0 hover:bg-cream-100"
              >
                <td className="py-2 pr-4 text-ink-900">{r.display}</td>
                <td className="py-2 pr-4 text-ink-500 text-xs uppercase tracking-wide">
                  {r.kind}
                </td>
                <td
                  className={`py-2 pr-4 text-right tabular-nums ${
                    r.exposure >= 0 ? "text-ink-700" : "text-negative"
                  }`}
                >
                  {r.exposure >= 0 ? "+" : ""}
                  {r.exposure.toFixed(3)}
                </td>
                <td
                  className={`py-2 text-right tabular-nums font-medium ${
                    r.mcfr_pct >= 0 ? "text-positive" : "text-negative"
                  }`}
                >
                  {r.mcfr_pct >= 0 ? "+" : ""}
                  {r.mcfr_pct.toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* Stock × Factor MCFR matrix */}
      <section className="bg-cream-50 border border-cream-300 rounded-xl p-6 shadow-sm overflow-x-auto">
        <h3 className="text-base font-semibold text-ink-900 mb-1">
          Joint Stock × Factor MCFR
        </h3>
        <p className="text-sm text-ink-500 mb-4">
          Per-stock contribution to each style factor's annualized vol — green = adds risk, red = hedges
        </p>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-ink-500 border-b border-cream-300">
              <th className="font-medium pb-2 pr-3 sticky left-0 bg-cream-50 z-10">Ticker</th>
              <th className="font-medium pb-2 pr-3 text-right">Weight</th>
              {styleFactors.map((f) => (
                <th key={f} className="font-medium pb-2 px-2 text-right whitespace-nowrap">
                  {f}
                </th>
              ))}
              <th className="font-medium pb-2 pl-3 text-right border-l border-cream-300">
                Stock Total
              </th>
            </tr>
          </thead>
          <tbody>
            {data.mcfr_matrix.rows.map((row) => (
              <tr
                key={row.ticker}
                className="border-b border-cream-200 last:border-0"
              >
                <td className="py-1.5 pr-3 font-medium text-ink-900 sticky left-0 bg-cream-50 z-10">
                  {row.ticker}
                </td>
                <td className="py-1.5 pr-3 text-right tabular-nums text-ink-700">
                  {(row.weight * 100).toFixed(1)}%
                </td>
                {styleFactors.map((f) => {
                  const v = row.by_factor[f] ?? 0;
                  return (
                    <td
                      key={f}
                      className="py-1.5 px-2 text-right tabular-nums"
                      style={{ background: cellColor(v) }}
                    >
                      {v === 0 || !Number.isFinite(v)
                        ? "—"
                        : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}`}
                    </td>
                  );
                })}
                <td
                  className={`py-1.5 pl-3 text-right tabular-nums font-medium border-l border-cream-300 ${
                    row.stock_total >= 0 ? "text-positive" : "text-negative"
                  }`}
                >
                  {row.stock_total >= 0 ? "+" : ""}
                  {(row.stock_total * 100).toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-xs text-ink-500 mt-3">
          Values are annualized %. Sum across all stocks for one factor = that factor's MCFR.
        </p>
      </section>

      {/* Sector pie */}
      <section className="bg-cream-50 border border-cream-300 rounded-xl p-6 shadow-sm">
        <h3 className="text-base font-semibold text-ink-900 mb-1">
          Sector Exposure
        </h3>
        <p className="text-sm text-ink-500 mb-4">
          Portfolio dollar weight by GICS sector
        </p>
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data.sector_pie}
                dataKey="weight"
                nameKey="sector"
                cx="50%"
                cy="50%"
                outerRadius={110}
                innerRadius={55}
                paddingAngle={1}
                stroke="#fbf7ee"
                strokeWidth={2}
                labelLine={false}
              >
                {data.sector_pie.map((_, i) => (
                  <Cell key={i} fill={SECTOR_COLORS[i % SECTOR_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                formatter={(v: number) => `${(v * 100).toFixed(1)}%`}
                contentStyle={{
                  background: "#fbf7ee",
                  border: "1px solid #e8ddc9",
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Legend
                layout="vertical"
                align="right"
                verticalAlign="middle"
                iconType="square"
                wrapperStyle={{ fontSize: 12 }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </section>
    </div>
  );
}
