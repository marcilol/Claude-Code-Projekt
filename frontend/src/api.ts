export type Timeframe = "1D" | "1W" | "1M" | "3M" | "6M" | "1Y";
export type ZScoreWindow = 63 | 126 | 252 | 504;

export interface FactorMeta {
  key: string;
  name: string;
}

export interface FactorTimeseriesResponse {
  timeframe: Timeframe;
  factors: FactorMeta[];
  rows: Array<{ date: string } & Record<string, number>>;
}

export interface BasketMeta {
  key: string;
  name: string;
  coverage?: number;
  size?: number;
}

export interface BasketTimeseriesResponse {
  timeframe: Timeframe;
  baskets: BasketMeta[];
  rows: Array<{ date: string } & Record<string, number>>;
}

export interface ZScoreRow {
  key: string;
  name: string;
  kind: "factor" | "basket";
  ret_1d: number;
  ret_5d: number;
  ret_21d: number;
  zscore: number;
  sparkline: number[];
}

export interface ZScoreResponse {
  window: ZScoreWindow;
  factors: ZScoreRow[];
  baskets: ZScoreRow[];
}

export interface QuadrantPoint {
  key: string;
  name: string;
  x: number; // 5D return
  y: number; // 21D return
  quadrant: "leaders" | "fading" | "recovering" | "laggards";
}

export interface QuadrantResponse {
  kind: "factor" | "basket";
  points: QuadrantPoint[];
}

export interface PortfolioDecomposition {
  factor_var_annual: number;
  idio_var_annual: number;
  total_var_annual: number;
  factor_vol_annual_pct: number;
  total_vol_annual_pct: number;
  pct_factor: number;
  pct_idio: number;
}

export interface MCFRRow {
  factor: string;
  display: string;
  kind: "country" | "industry" | "style";
  exposure: number;
  mcfr_pct: number;
}

export interface MCFRMatrixRow {
  ticker: string;
  weight: number;
  stock_total: number;
  by_factor: Record<string, number>;
}

export interface SectorSlice {
  sector: string;
  weight: number;
}

export interface PortfolioResponse {
  portfolio_path: string;
  as_of: string;
  n_positions: number;
  skipped_not_in_universe: string[];
  total_value: number;
  decomposition: PortfolioDecomposition;
  mcfr: MCFRRow[];
  mcfr_matrix: { style_factors: string[]; rows: MCFRMatrixRow[] };
  sector_pie: SectorSlice[];
}

async function jget<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status} on ${url}`);
  return r.json();
}

export const fetchFactorTimeseries = (timeframe: Timeframe) =>
  jget<FactorTimeseriesResponse>(`/api/factors/timeseries?timeframe=${timeframe}`);

export const fetchBaskets = () =>
  jget<{ baskets: BasketMeta[] }>(`/api/baskets`);

export const fetchBasketTimeseries = (timeframe: Timeframe, keys?: string[]) => {
  const q = new URLSearchParams({ timeframe });
  (keys ?? []).forEach((k) => q.append("keys", k));
  return jget<BasketTimeseriesResponse>(`/api/baskets/timeseries?${q}`);
};

export const fetchZScores = (window: ZScoreWindow) =>
  jget<ZScoreResponse>(`/api/zscores?window=${window}`);

export const fetchQuadrant = (kind: "factor" | "basket") =>
  jget<QuadrantResponse>(`/api/quadrant?kind=${kind}`);

export const fetchPortfolio = () => jget<PortfolioResponse>(`/api/portfolio`);
