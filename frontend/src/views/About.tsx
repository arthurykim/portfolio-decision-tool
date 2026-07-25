import { useEffect, useState } from "react";
import { api, type User } from "../lib/api";
import { renderMarkdown } from "../lib/format";

export default function About({ user }: { user: User | null }) {
  const [content, setContent] = useState("");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    api<{ content: string }>("/api/about").then((r) => setContent(r.content));
  }, []);

  async function save() {
    try {
      const r = await api<{ content: string }>("/api/about", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: draft }),
      });
      setContent(r.content);
      setEditing(false);
    } catch (e) {
      alert((e as Error).message);
    }
  }

  return (
    <section className="section">
      <div className="section-head">
        <h2>About</h2>
        {user?.is_admin && !editing && (
          <button className="btn ghost" type="button" onClick={() => { setDraft(content); setEditing(true); }}>
            Edit
          </button>
        )}
      </div>
      <div className="panel">
        {editing ? (
          <>
            <textarea rows={14} value={draft} onChange={(e) => setDraft(e.target.value)} />
            <div className="editor-actions">
              <button className="btn primary" type="button" onClick={save}>Save</button>
              <button className="btn ghost" type="button" onClick={() => setEditing(false)}>Cancel</button>
            </div>
          </>
        ) : (
          <div className="about-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }} />
        )}
      </div>
    </section>
  );
}
