import { useEffect, useState } from "react";
import Chart, { Sparkline } from "../components/Chart";
import { api, type Fund, type GrowthResult, type MarketPayload, type Movers } from "../lib/api";
import { fmtMoney, fmtMoneyCompact, pct } from "../lib/format";

const RANGE_DAYS: Record<string, number> = {
  "1D": 5, "1W": 7, "1M": 21, YTD: 0, "1Y": 252, "5Y": 1260, ALL: 20000,
};

export default function Markets({ onPickSymbol }: { onPickSymbol: (s: string) => void }) {
  const [market, setMarket] = useState<MarketPayload | null>(null);
  const [range, setRange] = useState("1Y");
  const [selected, setSelected] = useState("SPY");
  const [series, setSeries] = useState<{ dates: string[]; prices: number[] } | null>(null);
  const [movers, setMovers] = useState<Movers | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<MarketPayload>("/api/market").then(setMarket).catch((e) => setError(e.message));
    api<Movers>("/api/stocks/movers").then(setMovers).catch(() => setMovers(null));
  }, []);

  useEffect(() => {
    let days = RANGE_DAYS[range];
    if (range === "YTD") {
      const jan1 = new Date(new Date().getFullYear(), 0, 1);
      days = Math.max(5, Math.ceil((Date.now() - jan1.getTime()) / 86_400_000));
    }
    setSeries(null);
    api<{ dates: string[]; prices: number[] }>(`/api/prices/${selected}?days=${days}`)
      .then(setSeries)
      .catch(() => setSeries(null));
  }, [selected, range]);

  if (error) return <p className="error">Could not reach the API: {error}</p>;
  if (!market) return <p className="fineprint">Loading markets…</p>;

  const fund = market.funds.find((f) => f.ticker === selected);
  const ret = fund?.returns[range] ?? 0;

  return (
    <>
      <section className="section">
        <div className="section-head">
          <h2>Markets</h2>
          <div className="tabs" role="tablist">
            {market.ranges.map((r) => (
              <button
                key={r}
                type="button"
                className={`tab${r === range ? " active" : ""}`}
                onClick={() => setRange(r)}
              >
                {r}
              </button>
            ))}
          </div>
        </div>

        <div className="fund-grid">
          {market.funds.map((f: Fund) => {
            const r = f.returns[range];
            const up = r >= 0;
            return (
              <button
                key={f.ticker}
                type="button"
                className={`fund-card${f.ticker === selected ? " selected" : ""}`}
                onClick={() => setSelected(f.ticker)}
              >
                <span className="tk">{f.ticker}</span>
                <span className="px">${f.price.toFixed(2)}</span>
                <span className="nm">{f.name}</span>
                <span className="spark"><Sparkline values={f.spark} /></span>
                <span className={`badge ${up ? "up" : "down"}`}>
                  {up ? "+" : ""}{r.toFixed(2)}%
                </span>
              </button>
            );
          })}
        </div>

        <div className="panel chart-panel">
          <div className="chart-head">
            <div>
              <span className="chart-ticker">{selected}</span>
              <span className="chart-name">{fund?.name}</span>
            </div>
            <span className={`chart-change ${ret >= 0 ? "up" : "down"}`}>
              {ret >= 0 ? "+" : ""}{ret.toFixed(2)}% {range}
            </span>
          </div>
          {series ? (
            <Chart
              dates={series.dates}
              values={series.prices}
              color="var(--series-1)"
              area
              fmt={(v) => `$${v.toFixed(2)}`}
              fmtAxis={(v) => `$${v.toFixed(0)}`}
            />
          ) : (
            <p className="fineprint">Loading {range}…</p>
          )}
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>Today's movers</h2>
          <span className="fineprint">S&amp;P 500 · 1-day change</span>
        </div>
        <div className="movers-grid">
          <MoverList title="Top risers" items={movers?.gainers} onPick={onPickSymbol} />
          <MoverList title="Top fallers" items={movers?.losers} onPick={onPickSymbol} />
        </div>
      </section>

      <WhatIf funds={market.funds} />
    </>
  );
}

function MoverList({ title, items, onPick }: {
  title: string; items?: Movers["gainers"]; onPick: (s: string) => void;
}) {
  return (
    <div className="panel">
      <h3>{title}</h3>
      <div className="mover-list">
        {!items ? (
          <span className="fineprint">Loading…</span>
        ) : (
          items.map((q) => {
            const up = q.change_pct >= 0;
            return (
              <div
                key={q.symbol}
                className="mover-row"
                style={{ cursor: "pointer" }}
                onClick={() => onPick(q.symbol)}
              >
                <span className="sym">{q.symbol}</span>
                <span className="nm">{q.name}</span>
                <span className="px">${q.price.toFixed(2)}</span>
                <span className={`badge ${up ? "up" : "down"}`}>
                  {up ? "+" : ""}{q.change_pct.toFixed(2)}%
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function WhatIf({ funds }: { funds: Fund[] }) {
  const [amount, setAmount] = useState(1000);
  const [years, setYears] = useState(10);
  const [ticker, setTicker] = useState("SPY");
  const [result, setResult] = useState<GrowthResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setErr(null);
    const amt = Math.min(100_000_000, Math.max(100, amount || 1000));
    setAmount(amt);
    try {
      setResult(await api<GrowthResult>(`/api/growth?ticker=${ticker}&amount=${amt}&years=${years}`));
    } catch (e) {
      setErr((e as Error).message);
      setResult(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="section">
      <div className="section-head"><h2>What if I had invested…</h2></div>
      <div className="panel">
        <div className="whatif-controls">
          <label>
            Amount
            <div className="amount-wrap">
              $<input
                type="number" min={100} max={100_000_000} step={100} value={amount}
                onChange={(e) => setAmount(Number(e.target.value))}
              />
            </div>
          </label>
          <label>
            Years ago
            <input
              type="range" min={1} max={30} value={years}
              onChange={(e) => setYears(Number(e.target.value))}
            />
            <span className="range-val">{years} yrs</span>
          </label>
          <label>
            Fund
            <select value={ticker} onChange={(e) => setTicker(e.target.value)}>
              {funds.map((f) => (
                <option key={f.ticker} value={f.ticker}>{f.ticker} — {f.name}</option>
              ))}
            </select>
          </label>
          <button className="btn primary" type="button" onClick={run} disabled={busy}>
            {busy ? "Calculating…" : "Calculate"}
          </button>
        </div>

        {err && <p className="error">{err}</p>}

        {result && (
          <div className="wi-result">
            <div className="metrics">
              <Tile
                label="You'd have"
                value={fmtMoney(result.final_value)}
                sub={`from ${fmtMoney(result.amount)} on ${result.start}`}
                cls={result.gain >= 0 ? "pos" : "neg"}
              />
              <Tile
                label="Gain"
                value={`${result.gain >= 0 ? "+" : ""}${fmtMoney(result.gain)}`}
                sub={`${result.multiple}x your money`}
                cls={result.gain >= 0 ? "pos" : "neg"}
              />
              <Tile label="CAGR" value={`${result.cagr}%`} sub="annualized" />
            </div>
            <Chart
              dates={result.curve.dates}
              values={result.curve.values}
              color="var(--series-1)"
              area
              fmt={fmtMoney}
              fmtAxis={fmtMoneyCompact}
            />
            <p className="fineprint">
              Hypothetical historical calculation on adjusted closes. Not a prediction, not advice.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

export function Tile({ label, value, sub, cls = "" }: {
  label: string; value: string | number; sub?: string; cls?: string;
}) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className={`value ${cls}`}>{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export { pct };
