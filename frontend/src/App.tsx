import { useCallback, useEffect, useRef, useState } from "react";
import { api, post, type LearnArticle, type User } from "./lib/api";
import About from "./views/About";
import Assistant from "./views/Assistant";
import Backtest from "./views/Backtest";
import Learn from "./views/Learn";
import Markets from "./views/Markets";
import Stocks from "./views/Stocks";

const VIEWS = ["markets", "stocks", "backtest", "learn", "assistant", "about"] as const;
type View = (typeof VIEWS)[number];

function parseHash(): { view: View; arg: string | null } {
  const [name, arg] = window.location.hash.slice(1).split("/");
  return {
    view: (VIEWS as readonly string[]).includes(name) ? (name as View) : "markets",
    arg: arg || null,
  };
}

export default function App() {
  const [{ view, arg }, setRoute] = useState(parseHash);
  const [user, setUser] = useState<User | null>(null);
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [articles, setArticles] = useState<LearnArticle[]>([]);
  const [authOpen, setAuthOpen] = useState(false);
  const [focusSymbol, setFocusSymbol] = useState<string | null>(null);

  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    api<{ user: User | null }>("/api/auth/me").then((r) => setUser(r.user)).catch(() => setUser(null));
    api<LearnArticle[]>("/api/learn").then(setArticles).catch(() => setArticles([]));
  }, []);

  useEffect(() => {
    if (!user) { setWatchlist([]); return; }
    api<{ symbols: string[] }>("/api/watchlist").then((r) => setWatchlist(r.symbols)).catch(() => {});
  }, [user]);

  const go = (v: string) => { window.location.hash = v; };

  // Clicking a mover jumps to Stocks with that symbol already open.
  const pickSymbol = useCallback((symbol: string) => {
    setFocusSymbol(symbol);
    window.location.hash = "stocks";
  }, []);

  async function signOut() {
    await post("/api/auth/logout", {});
    setUser(null);
  }

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <h1>Portfolio Decision Tool</h1>
            <span className="as-of">educational · not investment advice</span>
          </div>

          <nav className="nav">
            <a href="#markets" className={view === "markets" ? "active" : ""}>Markets</a>
            <a href="#stocks" className={view === "stocks" ? "active" : ""}>Stocks</a>
            <a href="#backtest" className={view === "backtest" ? "active" : ""}>Backtest</a>
            <div className="nav-drop">
              <a href="#learn" className={view === "learn" ? "active" : ""}>Learn ▾</a>
              <div className="drop-menu">
                {articles.map((a) => (
                  <a key={a.slug} href={`#learn/${a.slug}`}>{a.title}</a>
                ))}
                <a href="#learn">All topics</a>
              </div>
            </div>
            <a href="#assistant" className={view === "assistant" ? "active" : ""}>Assistant</a>
            <a href="#about" className={view === "about" ? "active" : ""}>About</a>
          </nav>

          <div className="auth-box">
            {user ? (
              <>
                <span className="user-chip">
                  {user.username}
                  {user.is_admin && <span className="admin-tag">admin</span>}
                </span>
                <button className="btn ghost" type="button" onClick={signOut}>Sign out</button>
              </>
            ) : (
              <button className="btn ghost" type="button" onClick={() => setAuthOpen(true)}>
                Sign in
              </button>
            )}
          </div>
        </div>
      </header>

      <main className="page">
        {view === "markets" && <Markets onPickSymbol={pickSymbol} />}
        {view === "stocks" && (
          <Stocks
            user={user}
            watchlist={watchlist}
            setWatchlist={setWatchlist}
            requireSignIn={() => setAuthOpen(true)}
            focusSymbol={focusSymbol}
            onFocusHandled={() => setFocusSymbol(null)}
          />
        )}
        {view === "backtest" && <Backtest />}
        {view === "learn" && <Learn slug={arg} onOpen={(s) => go(s ? `learn/${s}` : "learn")} />}
        {view === "assistant" && <Assistant />}
        {view === "about" && <About user={user} />}

        {(view === "markets" || view === "backtest") && <Glossary />}
      </main>

      <footer className="disclaimer">
        Educational tool only. Historical performance does not predict future results.
        Nothing here is investment advice. Market data via Yahoo Finance, delayed.
      </footer>

      {authOpen && <AuthModal onClose={() => setAuthOpen(false)} onSignedIn={setUser} />}
    </>
  );
}

function AuthModal({ onClose, onSignedIn }: {
  onClose: () => void; onSignedIn: (u: User) => void;
}) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => { dialogRef.current?.showModal(); }, []);

  async function submit() {
    setErr(null);
    try {
      const user = await post<User>(`/api/auth/${mode}`, { username, password });
      onSignedIn(user);
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <dialog className="auth-modal" ref={dialogRef} onClose={onClose}>
      <form className="auth-form" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <h3>{mode === "login" ? "Sign in" : "Create account"}</h3>
        <label>
          Username
          <input
            type="text" minLength={3} maxLength={32} autoComplete="username" required
            value={username} onChange={(e) => setUsername(e.target.value)}
          />
        </label>
        <label>
          Password
          <input
            type="password" minLength={8} maxLength={128} autoComplete="current-password" required
            value={password} onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {err && <p className="error">{err}</p>}
        <div className="editor-actions">
          <button className="btn primary" type="submit">
            {mode === "login" ? "Sign in" : "Create account"}
          </button>
          <button className="btn ghost" type="button" onClick={onClose}>Close</button>
        </div>
        <button
          className="linklike" type="button"
          onClick={() => setMode(mode === "login" ? "register" : "login")}
        >
          {mode === "login" ? "New here? Create an account" : "Have an account? Sign in"}
        </button>
      </form>
    </dialog>
  );
}

const GLOSSARY: [string, string][] = [
  ["CAGR", "Compound annual growth rate — the steady yearly return that gets from the start value to the end value. Lets you compare periods of different lengths."],
  ["Real CAGR", "Growth after inflation — what the money is actually worth in today's dollars. A 9% return in a 6% inflation year is only about 3% of real progress."],
  ["Volatility", "How much daily returns swing, annualized. Stocks run ~15–20%, bonds ~4–6%. Higher volatility means a bumpier ride."],
  ["Sharpe ratio", "Return per unit of risk: return above the risk-free T-bill rate, divided by volatility. Above ~0.5 is decent for a passive portfolio."],
  ["Sortino ratio", "Like Sharpe, but it only counts downside volatility — so it better reflects the losses investors actually mind."],
  ["Calmar ratio", "Annual return divided by the worst drawdown. How much growth did I get for the deepest loss I had to sit through?"],
  ["Max drawdown", "The worst peak-to-trough loss in the period — what you'd have lost buying at the worst top."],
  ["Longest recovery", "The longest time spent below a previous peak. How many years you wait to break even often decides whether people stick with a strategy."],
];

function Glossary() {
  return (
    <section className="section glossary">
      <div className="section-head"><h2>What the numbers mean</h2></div>
      <div className="glossary-grid">
        {GLOSSARY.map(([term, blurb]) => (
          <div className="panel gloss" key={term}>
            <h3>{term}</h3>
            <p>{blurb}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
