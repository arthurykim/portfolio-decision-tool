/* Portfolio Decision Tool — frontend logic. No dependencies. */
"use strict";

const $ = (id) => document.getElementById(id);

const PRESETS = {
  "60/40": { SPY: 60, AGG: 40 },
  "Three-Fund": { VTI: 50, VXUS: 30, AGG: 20 },
  "All Weather": { SPY: 30, TLT: 40, IEF: 15, GLD: 7.5, BIL: 7.5 },
  "Golden Butterfly": { VTI: 20, SPY: 20, TLT: 20, BIL: 20, GLD: 20 },
  "100% S&P": { SPY: 100 },
};

let TICKER_LIST = [];

// ---------------------------------------------------------------- utilities
async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail
        : Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join("; ")
        : JSON.stringify(body.detail);
    } catch { /* keep statusText */ }
    throw new Error(detail);
  }
  return res.json();
}

const fmtPct = (x, dp = 1) => `${(x * 100).toFixed(dp)}%`;

// ---------------------------------------------------------------- quotes
async function loadQuotes() {
  const el = $("quotes");
  try {
    const quotes = await api("/api/quotes");
    el.innerHTML = "";
    for (const q of quotes) {
      const up = q.change_pct >= 0;
      const card = document.createElement("div");
      card.className = "quote-card";
      card.title = q.name;
      card.innerHTML =
        `<div class="qt">${q.ticker}</div>` +
        `<div class="qp">$${q.price.toFixed(2)}</div>` +
        `<div class="qc ${up ? "up" : "down"}">${up ? "▲" : "▼"} ${Math.abs(q.change_pct).toFixed(2)}%</div>`;
      el.appendChild(card);
    }
    if (quotes.length) {
      const note = document.createElement("span");
      note.className = "note";
      note.textContent = `as of ${quotes[0].as_of} (delayed)`;
      el.appendChild(note);
    }
  } catch {
    el.innerHTML = `<span class="note">Live quotes unavailable right now.</span>`;
  }
}

// ---------------------------------------------------------------- builder
function renderBuilder() {
  const rows = $("alloc-rows");
  rows.innerHTML = "";
  for (const t of TICKER_LIST) {
    const row = document.createElement("div");
    row.className = "alloc-row";
    row.innerHTML =
      `<span class="tk">${t.ticker}</span>` +
      `<span class="nm">${t.name}</span>` +
      `<input type="number" min="0" max="100" step="0.5" value="0" ` +
      `data-ticker="${t.ticker}" aria-label="${t.ticker} weight %" />`;
    rows.appendChild(row);
  }
  rows.addEventListener("input", updateTotal);

  const presets = $("presets");
  for (const name of Object.keys(PRESETS)) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.textContent = name;
    b.addEventListener("click", () => applyPreset(name));
    presets.appendChild(b);
  }
}

function weightInputs() {
  return [...document.querySelectorAll("#alloc-rows input")];
}

function applyPreset(name) {
  const preset = PRESETS[name];
  for (const input of weightInputs()) {
    input.value = preset[input.dataset.ticker] ?? 0;
  }
  updateTotal();
}

function currentAllocation() {
  const alloc = {};
  for (const input of weightInputs()) {
    const w = parseFloat(input.value) || 0;
    if (w > 0) alloc[input.dataset.ticker] = w / 100;
  }
  return alloc;
}

function totalPct() {
  return weightInputs().reduce((s, i) => s + (parseFloat(i.value) || 0), 0);
}

function updateTotal() {
  const total = totalPct();
  const el = $("alloc-total");
  el.textContent = `Total: ${total.toFixed(1)}%`;
  el.className = "alloc-total " + (Math.abs(total - 100) < 0.1 ? "ok" : "bad");
}

function normalize() {
  const total = totalPct();
  if (total <= 0) return;
  for (const input of weightInputs()) {
    const w = parseFloat(input.value) || 0;
    input.value = w > 0 ? +(100 * w / total).toFixed(2) : 0;
  }
  updateTotal();
}

// ---------------------------------------------------------------- charts
// Minimal SVG line/area chart with crosshair + tooltip.
function drawChart(containerId, dates, values, { color, area = false, fmt }) {
  const container = $(containerId);
  container.innerHTML = "";

  const W = 900, H = 300;
  const pad = { top: 12, right: 16, bottom: 26, left: 56 };
  const iw = W - pad.left - pad.right;
  const ih = H - pad.top - pad.bottom;

  let min = Math.min(...values), max = Math.max(...values);
  if (min === max) { min -= 1; max += 1; }
  const range = max - min;
  min -= range * 0.05; max += range * 0.05;

  const x = (i) => pad.left + (i / (values.length - 1)) * iw;
  const y = (v) => pad.top + (1 - (v - min) / (max - min)) * ih;

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

  // horizontal gridlines + y labels (4 ticks)
  for (let k = 0; k <= 3; k++) {
    const v = min + ((max - min) * k) / 3;
    const gy = y(v);
    svg.innerHTML +=
      `<line class="gridline" x1="${pad.left}" x2="${W - pad.right}" y1="${gy}" y2="${gy}"></line>` +
      `<text class="axis-label" x="${pad.left - 8}" y="${gy + 4}" text-anchor="end">${fmt(v)}</text>`;
  }
  // x labels: first / middle / last
  for (const i of [0, Math.floor(values.length / 2), values.length - 1]) {
    const anchor = i === 0 ? "start" : i === values.length - 1 ? "end" : "middle";
    svg.innerHTML += `<text class="axis-label" x="${x(i)}" y="${H - 6}" text-anchor="${anchor}">${dates[i]}</text>`;
  }

  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  if (area) {
    const base = y(Math.min(max, Math.max(min, 0)));
    svg.innerHTML +=
      `<path d="M ${pts.join(" L ")} L ${x(values.length - 1).toFixed(1)},${base} L ${x(0).toFixed(1)},${base} Z"` +
      ` fill="${color}" opacity="0.15"></path>`;
  }
  svg.innerHTML +=
    `<path d="M ${pts.join(" L ")}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"></path>` +
    `<line class="crosshair baseline" y1="${pad.top}" y2="${H - pad.bottom}" x1="-10" x2="-10" style="display:none"></line>` +
    `<circle class="dot" r="4" fill="${color}" stroke="var(--surface-1)" stroke-width="2" style="display:none"></circle>`;

  container.appendChild(svg);

  const tooltip = document.createElement("div");
  tooltip.className = "tooltip";
  container.appendChild(tooltip);

  const crosshair = svg.querySelector(".crosshair");
  const dot = svg.querySelector(".dot");

  svg.addEventListener("mousemove", (e) => {
    const rect = svg.getBoundingClientRect();
    const mx = ((e.clientX - rect.left) / rect.width) * W;
    const i = Math.max(0, Math.min(values.length - 1,
      Math.round(((mx - pad.left) / iw) * (values.length - 1))));
    const cx = x(i), cy = y(values[i]);
    crosshair.style.display = "";
    crosshair.setAttribute("x1", cx); crosshair.setAttribute("x2", cx);
    dot.style.display = "";
    dot.setAttribute("cx", cx); dot.setAttribute("cy", cy);
    tooltip.style.display = "block";
    tooltip.innerHTML = `<div class="tt-date">${dates[i]}</div><div class="tt-val">${fmt(values[i])}</div>`;
    const left = (cx / W) * rect.width;
    tooltip.style.left = `${Math.min(left + 12, rect.width - tooltip.offsetWidth - 4)}px`;
    tooltip.style.top = `${(cy / H) * rect.height - 40}px`;
  });
  svg.addEventListener("mouseleave", () => {
    crosshair.style.display = "none";
    dot.style.display = "none";
    tooltip.style.display = "none";
  });
}

// ---------------------------------------------------------------- backtest
const seriesColor = () => getComputedStyle(document.documentElement).getPropertyValue("--series-1").trim();
const drawdownColor = () => getComputedStyle(document.documentElement).getPropertyValue("--series-8").trim();

function renderMetrics(m) {
  const negClass = (x) => (x < 0 ? " neg" : "");
  $("metrics").innerHTML = [
    ["CAGR", fmtPct(m.cagr), `${m.start} → ${m.end}`, negClass(m.cagr)],
    ["Total return", fmtPct(m.total_return), "", negClass(m.total_return)],
    ["Volatility", fmtPct(m.volatility), "annualized", ""],
    ["Sharpe", m.sharpe.toFixed(2), "rf = 0", ""],
    ["Max drawdown", fmtPct(m.max_drawdown), "peak to trough", " neg"],
  ].map(([label, value, sub, cls]) =>
    `<div class="tile"><div class="label">${label}</div>` +
    `<div class="value${cls}">${value}</div>` +
    (sub ? `<div class="sub">${sub}</div>` : "") + `</div>`
  ).join("");
  $("metrics").hidden = false;
}

async function runBacktest() {
  const btn = $("run");
  const errEl = $("error");
  errEl.hidden = true;

  const alloc = currentAllocation();
  const total = totalPct();
  if (Math.abs(total - 100) > 0.1) {
    errEl.textContent = `Weights must total 100% (currently ${total.toFixed(1)}%). Use "Normalize".`;
    errEl.hidden = false;
    return;
  }

  btn.disabled = true;
  btn.textContent = "Running…";
  try {
    const body = { allocation: alloc };
    if ($("start-date").value) body.start = $("start-date").value;
    if ($("end-date").value) body.end = $("end-date").value;

    const r = await api("/api/backtest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    $("empty-state").hidden = true;
    renderMetrics(r.metrics);
    $("equity-panel").hidden = false;
    $("drawdown-panel").hidden = false;
    drawChart("equity-chart", r.equity_curve.dates, r.equity_curve.values,
      { color: seriesColor(), fmt: (v) => `$${v.toFixed(2)}` });
    drawChart("drawdown-chart", r.drawdown.dates, r.drawdown.values,
      { color: drawdownColor(), area: true, fmt: (v) => fmtPct(v) });
  } catch (e) {
    errEl.textContent = e.message || "Backtest failed.";
    errEl.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = "Run backtest";
  }
}

// ---------------------------------------------------------------- chat
const chatHistory = [];

function addChatMsg(role, text, sources) {
  const log = $("chat-log");
  const div = document.createElement("div");
  div.className = `chat-msg ${role}`;
  div.textContent = text;
  if (sources && sources.length) {
    const src = document.createElement("span");
    src.className = "src";
    const names = [...new Set(sources.map((s) => `${s.source} › ${s.heading}`))];
    src.textContent = `Sources: ${names.slice(0, 3).join(" · ")}`;
    div.appendChild(src);
  }
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

async function sendChat(e) {
  e.preventDefault();
  const input = $("chat-input");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  addChatMsg("user", message);
  const pending = addChatMsg("assistant", "Thinking…");
  pending.classList.add("pending");
  try {
    const r = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history: chatHistory.slice(-6) }),
    });
    pending.remove();
    addChatMsg("assistant", r.answer, r.sources);
    chatHistory.push({ role: "user", content: message },
                     { role: "assistant", content: r.answer });
  } catch (err) {
    pending.remove();
    addChatMsg("assistant", `Sorry — ${err.message || "the assistant is unavailable."}`);
  }
}

// ---------------------------------------------------------------- init
async function init() {
  $("normalize").addEventListener("click", normalize);
  $("run").addEventListener("click", runBacktest);
  $("chat-form").addEventListener("submit", sendChat);

  try {
    TICKER_LIST = await api("/api/tickers");
  } catch {
    $("error").textContent = "Could not reach the API.";
    $("error").hidden = false;
    return;
  }
  renderBuilder();
  applyPreset("60/40");
  loadQuotes();
  setInterval(loadQuotes, 5 * 60 * 1000);
}

init();
