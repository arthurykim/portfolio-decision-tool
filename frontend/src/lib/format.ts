export const pct = (x: number, dp = 1) => `${(x * 100).toFixed(dp)}%`;

export const fmtMoney = (x: number) =>
  x.toLocaleString("en-US", { style: "currency", currency: "USD" });

export const fmtMoneyCompact = (x: number) =>
  x.toLocaleString("en-US", {
    style: "currency", currency: "USD",
    notation: "compact", maximumFractionDigits: 1,
  });

export const fmtYears = (days: number) => {
  const years = days / 365.25;
  return years >= 1 ? `${years.toFixed(1)} years` : `${Math.round(days / 30.4)} months`;
};

/** Colored-initials avatar hue, derived from the ticker. No trademarked logos. */
export const avatarHue = (symbol: string) =>
  [...symbol].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 0);

/** Minimal Markdown: headings, bullets, bold, paragraphs. */
export function renderMarkdown(md: string): string {
  const esc = (s: string) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (s: string) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  return md.trim().split(/\n{2,}/).map((b) => {
    if (b.startsWith("### ")) return `<h3>${inline(b.slice(4))}</h3>`;
    if (b.startsWith("## ")) return `<h2>${inline(b.slice(3))}</h2>`;
    if (b.startsWith("# ")) return `<h1>${inline(b.slice(2))}</h1>`;
    const lines = b.split("\n");
    if (lines.every((l) => l.startsWith("- ")))
      return `<ul>${lines.map((l) => `<li>${inline(l.slice(2))}</li>`).join("")}</ul>`;
    return `<p>${inline(b).replace(/\n/g, " ")}</p>`;
  }).join("");
}
