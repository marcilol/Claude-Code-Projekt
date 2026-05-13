import { useEffect, useMemo, useState } from "react";

import {
  fetchZScores,
  type ZScoreResponse,
  type ZScoreRow,
  type ZScoreWindow,
} from "../api";
import { Sparkline } from "./Sparkline";

const WINDOWS: ZScoreWindow[] = [63, 126, 252, 504];
const MODES = ["all", "factor", "basket"] as const;
type Mode = (typeof MODES)[number];

const fmtPct = (v: number) =>
  Number.isFinite(v) ? `${(v * 100).toFixed(2)}%` : "—";
const fmtZ = (v: number) =>
  Number.isFinite(v) ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}σ` : "—";

const deltaClass = (v: number) =>
  !Number.isFinite(v) ? "text-ink-500" : v >= 0 ? "text-positive" : "text-negative";

const zClass = (v: number) => {
  if (!Number.isFinite(v)) return "text-ink-500";
  const a = Math.abs(v);
  if (a >= 2) return v >= 0 ? "text-positive font-semibold" : "text-negative font-semibold";
  if (a >= 1) return v >= 0 ? "text-positive" : "text-negative";
  return "text-ink-700";
};

type SortKey = "name" | "ret_1d" | "ret_5d" | "ret_21d" | "zscore";

export function ZScoreTable() {
  const [windowDays, setWindowDays] = useState<ZScoreWindow>(252);
  const [mode, setMode] = useState<Mode>("all");
  const [data, setData] = useState<ZScoreResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("zscore");
  const [sortDesc, setSortDesc] = useState(true);

  useEffect(() => {
    setError(null);
    fetchZScores(windowDays).then(setData).catch((e) => setError(String(e)));
  }, [windowDays]);

  const rows: ZScoreRow[] = useMemo(() => {
    if (!data) return [];
    let pool: ZScoreRow[] = [];
    if (mode === "all") pool = [...data.factors, ...data.baskets];
    else if (mode === "factor") pool = data.factors;
    else pool = data.baskets;

    const sorted = [...pool].sort((a, b) => {
      const av = a[sortKey] as number | string;
      const bv = b[sortKey] as number | string;
      if (typeof av === "string" && typeof bv === "string") {
        return sortDesc ? bv.localeCompare(av) : av.localeCompare(bv);
      }
      const an = av as number;
      const bn = bv as number;
      const safeA = Number.isFinite(an) ? an : -Infinity;
      const safeB = Number.isFinite(bn) ? bn : -Infinity;
      return sortDesc ? safeB - safeA : safeA - safeB;
    });
    return sorted;
  }, [data, mode, sortKey, sortDesc]);

  const onSort = (k: SortKey) => {
    if (k === sortKey) setSortDesc((d) => !d);
    else {
      setSortKey(k);
      setSortDesc(k !== "name");
    }
  };

  const arrow = (k: SortKey) =>
    sortKey === k ? (sortDesc ? "↓" : "↑") : "";

  return (
    <section className="bg-cream-50 border border-cream-300 rounded-xl p-6 shadow-sm">
      <header className="flex items-start justify-between mb-4 flex-wrap gap-3">
        <div>
          <h2 className="text-lg font-semibold text-ink-900">
            Z-Score Table
          </h2>
          <p className="text-sm text-ink-500 mt-0.5">
            Latest daily move standardized against trailing window — ±2σ ≈ extreme
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="inline-flex rounded-full bg-cream-200 p-1 gap-0.5">
            {MODES.map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-3 py-1 text-xs font-medium rounded-full capitalize transition-colors ${
                  mode === m
                    ? "bg-forest-800 text-cream-50"
                    : "text-ink-700 hover:text-ink-900"
                }`}
              >
                {m === "all" ? "All" : m + "s"}
              </button>
            ))}
          </div>
          <div className="inline-flex rounded-full bg-cream-200 p-1 gap-0.5">
            {WINDOWS.map((w) => (
              <button
                key={w}
                onClick={() => setWindowDays(w)}
                className={`px-3 py-1 text-xs font-medium rounded-full transition-colors ${
                  windowDays === w
                    ? "bg-forest-800 text-cream-50"
                    : "text-ink-700 hover:text-ink-900"
                }`}
              >
                {w}d
              </button>
            ))}
          </div>
        </div>
      </header>

      {error && (
        <div className="text-negative text-sm py-8 text-center">
          Failed to load: {error}
        </div>
      )}

      {!data && !error && (
        <div className="text-ink-500 text-sm py-8 text-center">Loading…</div>
      )}

      {data && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-ink-500 border-b border-cream-300">
                <th
                  className="font-medium pb-2 pr-4 cursor-pointer hover:text-ink-900"
                  onClick={() => onSort("name")}
                >
                  Name {arrow("name")}
                </th>
                <th className="font-medium pb-2 pr-4">Type</th>
                <th
                  className="font-medium pb-2 pr-4 text-right cursor-pointer hover:text-ink-900"
                  onClick={() => onSort("ret_1d")}
                >
                  1D {arrow("ret_1d")}
                </th>
                <th
                  className="font-medium pb-2 pr-4 text-right cursor-pointer hover:text-ink-900"
                  onClick={() => onSort("ret_5d")}
                >
                  5D {arrow("ret_5d")}
                </th>
                <th
                  className="font-medium pb-2 pr-4 text-right cursor-pointer hover:text-ink-900"
                  onClick={() => onSort("ret_21d")}
                >
                  21D {arrow("ret_21d")}
                </th>
                <th
                  className="font-medium pb-2 pr-4 text-right cursor-pointer hover:text-ink-900"
                  onClick={() => onSort("zscore")}
                >
                  Z ({windowDays}d) {arrow("zscore")}
                </th>
                <th className="font-medium pb-2 text-right">Trend</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={`${r.kind}:${r.key}`}
                  className="border-b border-cream-200 last:border-0 hover:bg-cream-100"
                >
                  <td className="py-2 pr-4 text-ink-900">{r.name}</td>
                  <td className="py-2 pr-4 text-ink-500">
                    <span className="text-xs uppercase tracking-wide">
                      {r.kind}
                    </span>
                  </td>
                  <td className={`py-2 pr-4 text-right tabular-nums ${deltaClass(r.ret_1d)}`}>
                    {fmtPct(r.ret_1d)}
                  </td>
                  <td className={`py-2 pr-4 text-right tabular-nums ${deltaClass(r.ret_5d)}`}>
                    {fmtPct(r.ret_5d)}
                  </td>
                  <td className={`py-2 pr-4 text-right tabular-nums ${deltaClass(r.ret_21d)}`}>
                    {fmtPct(r.ret_21d)}
                  </td>
                  <td className={`py-2 pr-4 text-right tabular-nums ${zClass(r.zscore)}`}>
                    {fmtZ(r.zscore)}
                  </td>
                  <td className="py-2 text-right">
                    <div className="inline-block">
                      <Sparkline data={r.sparkline} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
