// Single place that knows how to talk to the FastAPI backend.
// In dev, Vite proxies /api to localhost:8000 (same origin, no CORS).
// In production VITE_API_BASE points at the deployed API.
const BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { credentials: "include", ...init });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail =
        typeof body.detail === "string"
          ? body.detail
          : Array.isArray(body.detail)
            ? body.detail.map((d: { msg: string }) => d.msg).join("; ")
            : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(detail);
  }
  return res.json() as Promise<T>;
}

export const post = <T,>(path: string, body: unknown) =>
  api<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

// ---------------------------------------------------------------- types
export interface Fund {
  ticker: string;
  name: string;
  price: number;
  returns: Record<string, number>;
  since: string;
  spark: number[];
}

export interface MarketPayload {
  ranges: string[];
  as_of: string;
  funds: Fund[];
}

export interface Quote {
  symbol: string;
  price: number;
  change_pct: number;
  name?: string;
}

export interface Movers {
  gainers: Quote[];
  losers: Quote[];
}

export interface Metrics {
  start: string;
  end: string;
  total_return: number;
  cagr: number;
  real_cagr: number;
  volatility: number;
  sharpe: number;
  sortino: number;
  calmar: number;
  max_drawdown: number;
  longest_drawdown_days: number;
  risk_free_rate: number;
  inflation_rate: number;
}

export interface Series {
  dates: string[];
  values: number[];
}

export interface BacktestResult {
  metrics: Metrics;
  benchmark: { ticker: string; name: string; metrics: Metrics; equity_curve: Series } | null;
  inflation_estimated: boolean;
  equity_curve: Series;
  drawdown: Series;
}

export interface GrowthResult {
  ticker: string;
  amount: number;
  start: string;
  end: string;
  final_value: number;
  gain: number;
  multiple: number;
  cagr: number;
  curve: { dates: string[]; values: number[] };
}

export interface StockHistory {
  symbol: string;
  name: string;
  sector: string;
  range: string;
  interval: string;
  ranges: string[];
  fetched_at: string;
  points: { t: string; c: number }[];
  stats: {
    price: number;
    change: number;
    change_pct: number;
    high: number;
    low: number;
    open: number;
    volume: number | null;
    points: number;
  };
}

export interface NewsItem {
  title: string;
  publisher: string;
  published: string;
  url: string;
}

export interface ChatReply {
  answer: string;
  sources: { source: string; heading: string }[];
  mode: "gemini" | "extractive";
}

export interface User {
  username: string;
  is_admin: boolean;
}

export interface LearnArticle {
  slug: string;
  title: string;
  teaser: string;
  image: string;
  content?: string;
}

export interface CatalogEntry {
  symbol: string;
  name: string;
  sector: string;
}
