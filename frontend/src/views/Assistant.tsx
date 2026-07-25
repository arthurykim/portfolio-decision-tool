import { useRef, useState } from "react";
import { post, type ChatReply } from "../lib/api";

interface Msg { role: "user" | "assistant"; content: string; sources?: ChatReply["sources"] }

export default function Assistant() {
  const [log, setLog] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const message = input.trim();
    if (!message || busy) return;
    setInput("");
    setBusy(true);
    const history = log.slice(-6).map(({ role, content }) => ({ role, content }));
    setLog((l) => [...l, { role: "user", content: message }]);
    try {
      const r = await post<ChatReply>("/api/chat", { message, history });
      setLog((l) => [...l, { role: "assistant", content: r.answer, sources: r.sources }]);
    } catch (err) {
      setLog((l) => [...l, { role: "assistant", content: `Sorry — ${(err as Error).message}` }]);
    } finally {
      setBusy(false);
      requestAnimationFrame(() => boxRef.current?.scrollTo({ top: 1e6 }));
    }
  }

  return (
    <section className="section">
      <div className="section-head"><h2>Ask the assistant</h2></div>
      <div className="panel">
        <p className="chat-hint">
          Ask about metrics, asset classes, or strategies — e.g. “What is max drawdown?”
          or “How does the All Weather portfolio work?”
        </p>
        <div className="chat-log" aria-live="polite" ref={boxRef}>
          {log.map((m, i) => (
            <div key={i} className={`chat-msg ${m.role}`}>
              {m.content}
              {m.sources && m.sources.length > 0 && (
                <span className="src">
                  Sources: {[...new Set(m.sources.map((s) => `${s.source} › ${s.heading}`))].slice(0, 3).join(" · ")}
                </span>
              )}
            </div>
          ))}
          {busy && <div className="chat-msg assistant pending">Thinking…</div>}
        </div>
        <form className="chat-form" onSubmit={send}>
          <input
            type="text" maxLength={2000} autoComplete="off" value={input}
            placeholder="Ask a question about investing concepts…"
            onChange={(e) => setInput(e.target.value)}
          />
          <button className="btn primary chat-send" type="submit" disabled={busy}>Send</button>
        </form>
      </div>
    </section>
  );
}
