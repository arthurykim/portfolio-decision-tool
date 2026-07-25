import { useEffect, useState } from "react";
import Chart from "../components/Chart";
import { api, post, type BacktestResult } from "../lib/api";
import { fmtMoney, fmtYears, pct } from "../lib/format";
import { Tile } from "./Markets";

const PRESETS: Record<string, Record<string, number>> = {
  "60/40": { SPY: 60, AGG: 40 },
  "Three-Fund": { VTI: 50, VXUS: 30, AGG: 20 },
  "All Weather": { SPY: 30, TLT: 40, IEF: 15, GLD: 7.5, BIL: 7.5 },
  "Golden Butterfly": { VTI: 20, SPY: 20, TLT: 20, BIL: 20, GLD: 20 },
  "100% S&P": { SPY: 100 },
};

export default function Backtest() {
  const [tickers, setTickers] = useState<{ ticker: string; name: string }[]>([]);
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ ticker: string; name: string }[]>("/api/tickers").then((t) => {
      setTickers(t);
      setWeights(Object.fromEntries(t.map((x) => [x.ticker, PRESETS["60/40"][x.ticker] ?? 0])));
    });
  }, []);

  const total = Object.values(weights).reduce((s, w) => s + (w || 0), 0);

  function applyPreset(name: string) {
    setWeights(Object.fromEntries(tickers.map((t) => [t.ticker, PRESETS[name][t.ticker] ?? 0])));
  }

  function normalize() {
    if (total <= 0) return;
    setWeights((w) =>
      Object.fromEntries(Object.entries(w).map(([k, v]) => [k, v > 0 ? +((100 * v) / total).toFixed(2) : 0])));
  }

  async function run() {
    if (Math.abs(total - 100) > 0.1) {
      setErr(`Weights must total 100% (currently ${total.toFixed(1)}%). Use "Normalize".`);
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const allocation = Object.fromEntries(
        Object.entries(weights).filter(([, w]) => w > 0).map(([k, w]) => [k, w / 100]));
      const body: Record<string, unknown> = { allocation };
      if (start) body.start = start;
      if (end) body.end = end;
      setResult(await post<BacktestResult>("/api/backtest", body));
    } catch (e) {
      setErr((e as Error).message);
      setResult(null);
    } finally {
      setBusy(false);
    }
  }

  const m = result?.metrics;

  return (
    <section className="section">
      <div className="section-head"><h2>Backtest an allocation</h2></div>
      <div className="layout">
        <aside className="panel builder">
          <h3>Allocation</h3>
          <div className="presets">
            {Object.keys(PRESETS).map((name) => (
              <button key={name} type="button" className="chip" onClick={() => applyPreset(name)}>
                {name}
              </button>
            ))}
          </div>

          <div className="alloc-rows">
            {tickers.map((t) => (
              <div className="alloc-row" key={t.ticker}>
                <span className="tk">{t.ticker}</span>
                <span className="nm">{t.name}</span>
                <input
                  type="number" min={0} max={100} step={0.5}
                  aria-label={`${t.ticker} weight %`}
                  value={weights[t.ticker] ?? 0}
                  onChange={(e) =>
                    setWeights((w) => ({ ...w, [t.ticker]: Number(e.target.value) }))}
                />
              </div>
            ))}
          </div>

          <div className="alloc-footer">
            <span className={`alloc-total ${Math.abs(total - 100) < 0.1 ? "ok" : "bad"}`}>
              Total: {total.toFixed(1)}%
            </span>
            <button className="btn ghost" type="button" onClick={normalize}>
              Normalize to 100%
            </button>
          </div>

          <h3>Date range</h3>
          <div className="dates">
            <label>Start <input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></label>
            <label>End <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></label>
          </div>

          <button className="btn primary" type="button" onClick={run} disabled={busy}>
            {busy ? "Running…" : "Run backtest"}
          </button>
          {err && <p className="error">{err}</p>}
        </aside>

        <div className="results">
          {!result ? (
            <div className="panel empty-state">
              <p>Pick an allocation (or a preset), then run a backtest.</p>
            </div>
          ) : (
            <>
              <PlainSummary r={result} />
              <div className="metrics">
                <Tile label="CAGR" value={pct(m!.cagr)} sub={`${m!.start} → ${m!.end}`} cls={m!.cagr < 0 ? "neg" : ""} />
                <Tile label="Real CAGR" value={pct(m!.real_cagr)} sub="after inflation" cls={m!.real_cagr < 0 ? "neg" : ""} />
                <Tile label="Total return" value={pct(m!.total_return)} cls={m!.total_return < 0 ? "neg" : ""} />
                <Tile label="Volatility" value={pct(m!.volatility)} sub="annualized" />
                <Tile label="Sharpe" value={m!.sharpe.toFixed(2)} sub={`rf = ${pct(m!.risk_free_rate)}`} />
                <Tile label="Sortino" value={m!.sortino.toFixed(2)} sub="downside risk only" />
                <Tile label="Calmar" value={m!.calmar.toFixed(2)} sub="return vs drawdown" />
                <Tile label="Max drawdown" value={pct(m!.max_drawdown)} sub="peak to trough" cls="neg" />
                <Tile label="Longest recovery" value={fmtYears(m!.longest_drawdown_days)} sub="below a prior peak" />
                {result.benchmark && (
                  <Tile
                    label="vs S&P 500"
                    value={`${m!.cagr - result.benchmark.metrics.cagr >= 0 ? "+" : ""}${pct(m!.cagr - result.benchmark.metrics.cagr)}`}
                    sub={`benchmark ${pct(result.benchmark.metrics.cagr)} CAGR`}
                    cls={m!.cagr - result.benchmark.metrics.cagr >= 0 ? "pos" : "neg"}
                  />
                )}
              </div>

              <div className="panel chart-panel">
                <div className="chart-head">
                  <h3>Growth of $1</h3>
                  {result.benchmark && (
                    <div className="legend">
                      <span className="key"><i className="swatch port" />Your allocation</span>
                      <span className="key"><i className="swatch bench" />S&amp;P 500</span>
                    </div>
                  )}
                </div>
                <Chart
                  dates={result.equity_curve.dates}
                  values={result.equity_curve.values}
                  color="var(--series-1)"
                  fmt={(v) => `$${v.toFixed(2)}`}
                  overlay={result.benchmark
                    ? { values: result.benchmark.equity_curve.values, color: "var(--muted)" }
                    : null}
                />
              </div>

              <div className="panel chart-panel">
                <h3>Drawdown from peak</h3>
                <Chart
                  dates={result.drawdown.dates}
                  values={result.drawdown.values}
                  color="var(--series-8)"
                  area
                  fmt={(v) => pct(v)}
                />
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function PlainSummary({ r }: { r: BacktestResult }) {
  const m = r.metrics;
  const grown = 10000 * (1 + m.total_return);
  const years = (new Date(m.end).getTime() - new Date(m.start).getTime()) / 31_557_600_000;
  const real = 10000 * Math.pow(1 + m.real_cagr, years);
  const diff = r.benchmark ? m.cagr - r.benchmark.metrics.cagr : 0;

  return (
    <div className="panel plain-summary">
      <p>
        <strong>$10,000</strong> invested on {m.start} would have become{" "}
        <strong>{fmtMoney(grown)}</strong> by {m.end} — about{" "}
        <strong>{fmtMoney(real)}</strong> in today's money once inflation
        ({pct(m.inflation_rate)}/yr) is taken out.
      </p>
      <p>
        The worst stretch was a <strong>{pct(Math.abs(m.max_drawdown))}</strong> fall, and it
        took <strong>{fmtYears(m.longest_drawdown_days)}</strong> to climb back to the
        previous high.
      </p>
      {r.benchmark && (
        <p>
          {diff >= 0 ? (
            <>It grew <strong>{pct(Math.abs(diff))}/yr faster</strong> than simply buying the S&amp;P 500.</>
          ) : (
            <>Simply buying the S&amp;P 500 would have grown <strong>{pct(Math.abs(diff))}/yr faster</strong>, though usually with bigger swings.</>
          )}
        </p>
      )}
      {r.inflation_estimated && (
        <p><span className="est-note">Inflation for the most recent period is estimated — see data/cpi.json.</span></p>
      )}
    </div>
  );
}
