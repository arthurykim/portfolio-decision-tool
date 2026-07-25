import { useEffect, useMemo, useRef, useState } from "react";
import Chart from "../components/Chart";
import {
  api, post, type CatalogEntry, type NewsItem, type Quote, type StockHistory,
} from "../lib/api";
import { avatarHue } from "../lib/format";

const PAGE_SIZE = 50;

interface Props {
  user: { username: string; is_admin: boolean } | null;
  watchlist: string[];
  setWatchlist: (s: string[]) => void;
  requireSignIn: () => void;
  focusSymbol: string | null;
  onFocusHandled: () => void;
}

export default function Stocks({
  user, watchlist, setWatchlist, requireSignIn, focusSymbol, onFocusHandled,
}: Props) {
  const [sp500, setSp500] = useState<CatalogEntry[]>([]);
  const [ipos, setIpos] = useState<(CatalogEntry & { ipo: string })[]>([]);
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [detail, setDetail] = useState<string | null>(null);

  useEffect(() => {
    api<{ stocks: CatalogEntry[] }>("/data/sp500.json").then((d) => setSp500(d.stocks));
    api<{ stocks: (CatalogEntry & { ipo: string })[] }>("/data/ipos.json")
      .then((d) => {
        setIpos(d.stocks);
        fetchQuotes(d.stocks.map((s) => s.symbol));
      });
  }, []);

  useEffect(() => {
    if (focusSymbol) {
      setDetail(focusSymbol);
      onFocusHandled();
    }
  }, [focusSymbol, onFocusHandled]);

  async function fetchQuotes(symbols: string[]) {
    const need = symbols.filter((s) => !(s in quotes)).slice(0, 30);
    if (!need.length) return;
    try {
      const got = await api<Quote[]>(`/api/stocks/quotes?symbols=${need.join(",")}`);
      setQuotes((q) => ({ ...q, ...Object.fromEntries(got.map((x) => [x.symbol, x])) }));
    } catch { /* quotes are best-effort */ }
  }

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q
      ? sp500.filter((s) =>
          s.symbol.toLowerCase().includes(q) || s.name.toLowerCase().includes(q))
      : sp500;
  }, [sp500, query]);

  const totalPages = Math.max(1, Math.ceil(matches.length / PAGE_SIZE));
  const current = Math.min(page, totalPages);
  const shown = matches.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);

  // Load quotes for whatever rows are visible, debounced while typing.
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      for (let i = 0; i < shown.length; i += 30) {
        fetchQuotes(shown.slice(i, i + 30).map((s) => s.symbol));
      }
    }, query ? 350 : 0);
    return () => window.clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown.map((s) => s.symbol).join(","), query]);

  async function togglePin(symbol: string) {
    if (!user) return requireSignIn();
    try {
      const r = watchlist.includes(symbol)
        ? await api<{ symbols: string[] }>(`/api/watchlist/${symbol}`, { method: "DELETE" })
        : await post<{ symbols: string[] }>("/api/watchlist", { symbol });
      setWatchlist(r.symbols);
    } catch (e) {
      alert((e as Error).message);
    }
  }

  const names: Record<string, string> = useMemo(
    () => Object.fromEntries([...sp500, ...ipos].map((s) => [s.symbol, s.name])),
    [sp500, ipos],
  );

  return (
    <section className="section">
      <div className="section-head">
        <h2>Stocks</h2>
        <input
          className="search" type="search" placeholder="Search 500+ companies…"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setPage(1); }}
        />
      </div>

      {user && watchlist.length > 0 && (
        <>
          <h3 className="subhead">Pinned</h3>
          <div className="watch-strip">
            {watchlist.map((sym) => (
              <MiniCard
                key={sym} symbol={sym} name={names[sym] ?? quotes[sym]?.name ?? ""}
                quote={quotes[sym]} onOpen={() => setDetail(sym)}
                onUnpin={() => togglePin(sym)}
              />
            ))}
          </div>
        </>
      )}

      <h3 className="subhead">Recent tech IPOs</h3>
      <div className="ipo-strip">
        {ipos.map((s) => (
          <MiniCard
            key={s.symbol} symbol={s.symbol} name={`${s.name} · ${s.sector}`}
            quote={quotes[s.symbol]} sub={`IPO ${s.ipo}`} onOpen={() => setDetail(s.symbol)}
          />
        ))}
      </div>

      {detail && <StockDetail symbol={detail} onClose={() => setDetail(null)} />}

      <h3 className="subhead">{query ? `Search: “${query}”` : "S&P 500"}</h3>
      <div className="panel table-panel">
        <table className="stock-table">
          <thead>
            <tr>
              <th></th><th>Symbol</th><th>Company</th><th>Sector</th>
              <th className="num">Price</th><th className="num">1D</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((s) => {
              const q = quotes[s.symbol];
              const up = (q?.change_pct ?? 0) >= 0;
              return (
                <tr key={s.symbol} onClick={() => setDetail(s.symbol)}>
                  <td>
                    <button
                      className={`pin-btn${watchlist.includes(s.symbol) ? " pinned" : ""}`}
                      title={`${watchlist.includes(s.symbol) ? "Unpin" : "Pin"} ${s.symbol}`}
                      onClick={(e) => { e.stopPropagation(); togglePin(s.symbol); }}
                    >
                      {watchlist.includes(s.symbol) ? "★" : "☆"}
                    </button>
                  </td>
                  <td className="sym">{s.symbol}</td>
                  <td>{s.name}</td>
                  <td className="sector">{s.sector}</td>
                  <td className="num">{q ? `$${q.price.toFixed(2)}` : "—"}</td>
                  <td className={`num chg ${up ? "up" : "down"}`}>
                    {q ? `${up ? "+" : ""}${q.change_pct.toFixed(2)}%` : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {totalPages > 1 && (
          <div className="pager">
            {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
              <button
                key={p} type="button"
                className={`page-btn${p === current ? " active" : ""}`}
                onClick={() => setPage(p)}
              >
                {p}
              </button>
            ))}
          </div>
        )}
        <p className="fineprint">
          {matches.length}{query ? " matches" : " companies"} · page {current} of {totalPages}
        </p>
      </div>
    </section>
  );
}

function MiniCard({ symbol, name, quote, sub, onOpen, onUnpin }: {
  symbol: string; name: string; quote?: Quote; sub?: string;
  onOpen: () => void; onUnpin?: () => void;
}) {
  const up = (quote?.change_pct ?? 0) >= 0;
  return (
    <div className="mini-card" style={{ cursor: "pointer" }} onClick={onOpen}>
      {onUnpin && (
        <button
          className="unpin" title={`Unpin ${symbol}`}
          onClick={(e) => { e.stopPropagation(); onUnpin(); }}
        >
          ✕
        </button>
      )}
      <span className="avatar" style={{ ["--h" as string]: avatarHue(symbol) }}>
        {symbol.slice(0, 2)}
      </span>
      <span className="tk">{symbol}</span>
      <span className="nm">{name}</span>
      {quote ? (
        <>
          <div className="px">${quote.price.toFixed(2)}</div>
          <span className={`chg ${up ? "up" : "down"}`}>
            {up ? "+" : ""}{quote.change_pct.toFixed(2)}%
          </span>
        </>
      ) : (
        <div className="px">{sub ?? ""}</div>
      )}
    </div>
  );
}

function StockDetail({ symbol, onClose }: { symbol: string; onClose: () => void }) {
  const [range, setRange] = useState("1Y");
  const [data, setData] = useState<StockHistory | null>(null);
  const [news, setNews] = useState<NewsItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    setData(null);
    setErr(null);
    const refresh = nonce > 0 ? "&refresh=true" : "";
    api<StockHistory>(`/api/stocks/${symbol}/history?range=${range}${refresh}`)
      .then(setData)
      .catch((e) => setErr(e.message));
  }, [symbol, range, nonce]);

  useEffect(() => {
    setNews(null);
    api<{ items: NewsItem[] }>(`/api/stocks/${symbol}/news?limit=6`)
      .then((r) => setNews(r.items))
      .catch(() => setNews([]));
  }, [symbol]);

  const up = (data?.stats.change ?? 0) >= 0;

  return (
    <div className="panel detail-panel">
      <div className="detail-head">
        <div className="detail-id">
          <span className="detail-symbol">{symbol}</span>
          <span className="detail-name">{data?.name}</span>
          {data?.sector && <span className="detail-sector">{data.sector}</span>}
        </div>
        <div className="detail-actions">
          <button className="btn ghost" type="button" onClick={() => setNonce((n) => n + 1)}>
            ↻ Refresh
          </button>
          <button className="btn ghost" type="button" onClick={onClose}>✕ Close</button>
        </div>
      </div>

      {data && (
        <div className="detail-price">
          <span className="detail-last">${data.stats.price.toFixed(2)}</span>
          <span className={`detail-change ${up ? "up" : "down"}`}>
            {up ? "+" : ""}{data.stats.change.toFixed(2)} ({up ? "+" : ""}
            {data.stats.change_pct.toFixed(2)}%) {data.range}
          </span>
          <span className="fineprint">
            as of {data.fetched_at.replace("T", " ")} · {data.interval} bars
          </span>
        </div>
      )}

      <div className="tabs" role="tablist">
        {(data?.ranges ?? ["1D", "1W", "1M", "6M", "YTD", "1Y", "5Y", "MAX"]).map((r) => (
          <button
            key={r} type="button"
            className={`tab${r === range ? " active" : ""}`}
            onClick={() => setRange(r)}
          >
            {r}
          </button>
        ))}
      </div>

      {err ? (
        <p className="error">Couldn't load {symbol}: {err}</p>
      ) : data ? (
        <Chart
          dates={data.points.map((p) => p.t.slice(0, 10))}
          values={data.points.map((p) => p.c)}
          color={up ? "var(--delta-up)" : "var(--series-8)"}
          area
          fmt={(v) => `$${v.toFixed(2)}`}
        />
      ) : (
        <p className="fineprint">Loading {range}…</p>
      )}

      {data && (
        <div className="detail-stats">
          {[
            ["Open", `$${data.stats.open.toFixed(2)}`],
            ["High", `$${data.stats.high.toFixed(2)}`],
            ["Low", `$${data.stats.low.toFixed(2)}`],
            ["Volume", data.stats.volume
              ? data.stats.volume.toLocaleString("en-US", { notation: "compact" })
              : "—"],
            ["Points", String(data.stats.points)],
          ].map(([k, v]) => (
            <div className="s" key={k}>
              <span className="k">{k}</span>
              <span className="v">{v}</span>
            </div>
          ))}
        </div>
      )}

      <div className="detail-news">
        <h4>Latest news</h4>
        {news === null ? (
          <p className="fineprint">Loading…</p>
        ) : news.length === 0 ? (
          <p className="fineprint">No recent headlines.</p>
        ) : (
          <>
            {news.map((n) => (
              <a
                key={n.url} className="news-item" href={n.url}
                target="_blank" rel="noopener noreferrer"
              >
                <span className="news-title">{n.title}</span>
                <span className="news-meta">
                  {n.publisher}
                  {n.published ? ` · ${new Date(n.published).toLocaleDateString()}` : ""}
                </span>
              </a>
            ))}
            <p className="fineprint">
              Headlines and links via Yahoo Finance; articles open at the publisher.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
