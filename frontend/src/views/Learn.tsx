import { useEffect, useState } from "react";
import { api, type LearnArticle } from "../lib/api";
import { renderMarkdown } from "../lib/format";

const BROKERAGES = [
  ["Fidelity", "https://www.fidelity.com", "Full-service brokerage with no-minimum index funds and retirement accounts.", "fidelity.com"],
  ["Vanguard", "https://investor.vanguard.com", "The company that invented the index fund; runs VOO, VTI, and VXUS.", "vanguard.com"],
  ["Charles Schwab", "https://www.schwab.com", "Broad brokerage with strong research tools and banking integration.", "schwab.com"],
  ["SoFi Invest", "https://www.sofi.com/invest/", "App-first investing alongside banking and student-loan products.", "sofi.com"],
  ["Ally Invest", "https://www.ally.com/invest/", "Online bank with simple self-directed and automated investing.", "ally.com"],
  ["Marcus by Goldman Sachs", "https://www.marcus.com", "High-yield savings and CDs — the cash side of a portfolio.", "marcus.com"],
  ["Credit Karma", "https://www.creditkarma.com", "Free credit monitoring — a common first stop before investing.", "creditkarma.com"],
];

export default function Learn({ slug, onOpen }: { slug: string | null; onOpen: (s: string | null) => void }) {
  const [list, setList] = useState<LearnArticle[]>([]);
  const [article, setArticle] = useState<LearnArticle | null>(null);

  useEffect(() => { api<LearnArticle[]>("/api/learn").then(setList); }, []);

  useEffect(() => {
    if (!slug) { setArticle(null); return; }
    setArticle(null);
    api<LearnArticle>(`/api/learn/${slug}`).then(setArticle).catch(() => onOpen(null));
    window.scrollTo({ top: 0 });
  }, [slug, onOpen]);

  if (slug) {
    return (
      <section className="section">
        <div className="section-head">
          <h2>{article?.title ?? "Loading…"}</h2>
          <button className="btn ghost" type="button" onClick={() => onOpen(null)}>← All topics</button>
        </div>
        <div className="panel about-content">
          {article ? (
            <>
              <img className="article-hero" src={article.image} alt={`Diagram illustrating ${article.title}`} />
              <div dangerouslySetInnerHTML={{
                __html: renderMarkdown((article.content ?? "").split("\n").slice(1).join("\n")),
              }} />
            </>
          ) : <p className="fineprint">Loading…</p>}
        </div>
      </section>
    );
  }

  return (
    <section className="section">
      <div className="section-head"><h2>Learn</h2></div>
      <div className="learn-grid">
        {list.map((a) => (
          <button key={a.slug} type="button" className="learn-tile" onClick={() => onOpen(a.slug)}>
            <img className="tile-thumb" src={a.image} alt="" loading="lazy" />
            <h3>{a.title}</h3>
            <p>{a.teaser}</p>
            <span className="read">Read →</span>
          </button>
        ))}
      </div>

      <h3 className="subhead">Where to start (external links)</h3>
      <div className="learn-grid">
        {BROKERAGES.map(([name, url, blurb, host]) => (
          <a key={name} className="learn-tile" href={url} target="_blank" rel="noopener noreferrer">
            <h3>{name}</h3><p>{blurb}</p><span className="read">{host} →</span>
          </a>
        ))}
      </div>
      <p className="fineprint">
        Independent educational links — not endorsements, not advice, and this site has no
        affiliation with or compensation from any of them.
      </p>
    </section>
  );
}
