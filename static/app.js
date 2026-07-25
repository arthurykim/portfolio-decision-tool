"use strict";

const $ = (id) => document.getElementById(id);

const PRESETS = {
  "60/40": { SPY: 60, AGG: 40 },
  "Three-Fund": { VTI: 50, VXUS: 30, AGG: 20 },
  "All Weather": { SPY: 30, TLT: 40, IEF: 15, GLD: 7.5, BIL: 7.5 },
  "Golden Butterfly": { VTI: 20, SPY: 20, TLT: 20, BIL: 20, GLD: 20 },
  "100% S&P": { SPY: 100 },
};

// Days of history to chart for each range tab.
const RANGE_DAYS = { "1D": 5, "1W": 7, "1M": 21, YTD: 0, "1Y": 252, "5Y": 1260, ALL: 20000 };

const state = {
  funds: [], range: "1Y", selected: "SPY",
  user: null, watchlist: [], sp500: [], ipos: [], quotes: {},
};

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
const fmtMoney = (x) => x.toLocaleString("en-US", { style: "currency", currency: "USD" });
const fmtMoneyCompact = (x) =>
  x.toLocaleString("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 });
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// ---------------------------------------------------------------- charts
function sparkline(values, { width = 90, height = 28 } = {}) {
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  const pts = values.map((v, i) =>
    `${((i / (values.length - 1)) * width).toFixed(1)},${(height - 2 - ((v - min) / range) * (height - 4)).toFixed(1)}`);
  const up = values[values.length - 1] >= values[0];
  const color = up ? cssVar("--delta-up") : cssVar("--delta-down");
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">` +
    `<path d="M ${pts.join(" L ")}" fill="none" stroke="${color}" stroke-width="1.5"></path></svg>`;
}

function drawChart(containerId, dates, values, { color, area = false, fmt, fmtAxis = fmt }) {
  const container = $(containerId);
  container.innerHTML = "";

  const W = 900, H = 300;
  const pad = { top: 12, right: 16, bottom: 26, left: 60 };
  const iw = W - pad.left - pad.right;
  const ih = H - pad.top - pad.bottom;

  let min = Math.min(...values), max = Math.max(...values);
  if (min === max) { min -= 1; max += 1; }
  const spread = max - min;
  min -= spread * 0.05; max += spread * 0.05;

  const x = (i) => pad.left + (i / (values.length - 1)) * iw;
  const y = (v) => pad.top + (1 - (v - min) / (max - min)) * ih;

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

  for (let k = 0; k <= 3; k++) {
    const v = min + ((max - min) * k) / 3;
    const gy = y(v);
    svg.innerHTML +=
      `<line class="gridline" x1="${pad.left}" x2="${W - pad.right}" y1="${gy}" y2="${gy}"></line>` +
      `<text class="axis-label" x="${pad.left - 8}" y="${gy + 4}" text-anchor="end">${fmtAxis(v)}</text>`;
  }
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

// ---------------------------------------------------------------- market dashboard
function renderTabs(ranges) {
  const tabs = $("range-tabs");
  tabs.innerHTML = "";
  for (const r of ranges) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "tab" + (r === state.range ? " active" : "");
    b.textContent = r;
    b.addEventListener("click", () => {
      state.range = r;
      renderTabs(ranges);
      renderFundGrid();
      renderMainChart();
    });
    tabs.appendChild(b);
  }
}

function renderFundGrid() {
  const grid = $("fund-grid");
  grid.innerHTML = "";
  for (const f of state.funds) {
    const ret = f.returns[state.range];
    const up = ret >= 0;
    const card = document.createElement("button");
    card.type = "button";
    card.className = "fund-card" + (f.ticker === state.selected ? " selected" : "");
    card.innerHTML =
      `<span class="tk">${f.ticker}</span>` +
      `<span class="px">$${f.price.toFixed(2)}</span>` +
      `<span class="nm">${f.name}</span>` +
      `<span class="spark">${sparkline(f.spark)}</span>` +
      `<span class="badge ${up ? "up" : "down"}">${up ? "+" : ""}${ret.toFixed(2)}%</span>`;
    card.addEventListener("click", () => {
      state.selected = f.ticker;
      renderFundGrid();
      renderMainChart();
    });
    grid.appendChild(card);
  }
}

async function renderMainChart() {
  const fund = state.funds.find((f) => f.ticker === state.selected);
  if (!fund) return;
  $("chart-ticker").textContent = fund.ticker;
  $("chart-name").textContent = fund.name;
  const ret = fund.returns[state.range];
  const el = $("chart-change");
  el.textContent = `${ret >= 0 ? "+" : ""}${ret.toFixed(2)}% ${state.range}`;
  el.className = "chart-change " + (ret >= 0 ? "up" : "down");

  let days = RANGE_DAYS[state.range];
  if (state.range === "YTD") {
    const jan1 = new Date(new Date().getFullYear(), 0, 1);
    days = Math.max(5, Math.ceil((Date.now() - jan1) / 86400000));
  }
  const r = await api(`/api/prices/${fund.ticker}?days=${days}`);
  drawChart("main-chart", r.dates, r.prices,
    { color: cssVar("--series-1"), area: true, fmt: (v) => `$${v.toFixed(0)}` });
}

async function loadMarket() {
  const m = await api("/api/market");
  state.funds = m.funds;
  renderTabs(m.ranges);
  renderFundGrid();
  renderMainChart();
  $("as-of").textContent = `data through ${m.as_of} · refreshed hourly`;
}

// ---------------------------------------------------------------- what-if
function renderWhatIfControls() {
  const sel = $("wi-ticker");
  sel.innerHTML = "";
  for (const f of state.funds) {
    const opt = document.createElement("option");
    opt.value = f.ticker;
    opt.textContent = `${f.ticker} — ${f.name}`;
    sel.appendChild(opt);
  }
  $("wi-years").addEventListener("input", () => {
    $("wi-years-label").textContent = `${$("wi-years").value} yrs`;
  });
  $("wi-run").addEventListener("click", runWhatIf);
}

async function runWhatIf() {
  const btn = $("wi-run");
  const amount = Math.min(100_000_000, Math.max(100, parseFloat($("wi-amount").value) || 1000));
  $("wi-amount").value = amount;
  const years = $("wi-years").value;
  const ticker = $("wi-ticker").value;
  btn.disabled = true;
  try {
    const g = await api(`/api/growth?ticker=${ticker}&amount=${amount}&years=${years}`);
    $("wi-result").hidden = false;
    const gainPos = g.gain >= 0;
    $("wi-metrics").innerHTML = [
      ["You'd have", fmtMoney(g.final_value), `from ${fmtMoney(g.amount)} on ${g.start}`, gainPos ? "pos" : "neg"],
      ["Gain", `${gainPos ? "+" : ""}${fmtMoney(g.gain)}`, `${g.multiple}x your money`, gainPos ? "pos" : "neg"],
      ["CAGR", `${g.cagr}%`, "annualized", ""],
    ].map(([label, value, sub, cls]) =>
      `<div class="tile"><div class="label">${label}</div>` +
      `<div class="value ${cls}">${value}</div><div class="sub">${sub}</div></div>`
    ).join("");
    drawChart("wi-chart", g.curve.dates, g.curve.values,
      { color: cssVar("--series-1"), area: true, fmt: fmtMoney, fmtAxis: fmtMoneyCompact });
  } catch (e) {
    $("wi-result").hidden = false;
    $("wi-metrics").innerHTML = `<p class="error">${e.message}</p>`;
    $("wi-chart").innerHTML = "";
  } finally {
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------- backtest builder
function renderBuilder() {
  const rows = $("alloc-rows");
  rows.innerHTML = "";
  for (const f of state.funds) {
    const row = document.createElement("div");
    row.className = "alloc-row";
    row.innerHTML =
      `<span class="tk">${f.ticker}</span>` +
      `<span class="nm">${f.name}</span>` +
      `<input type="number" min="0" max="100" step="0.5" value="0" ` +
      `data-ticker="${f.ticker}" aria-label="${f.ticker} weight %" />`;
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

const weightInputs = () => [...document.querySelectorAll("#alloc-rows input")];

function applyPreset(name) {
  const preset = PRESETS[name];
  for (const input of weightInputs()) input.value = preset[input.dataset.ticker] ?? 0;
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

const totalPct = () => weightInputs().reduce((s, i) => s + (parseFloat(i.value) || 0), 0);

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

  const total = totalPct();
  if (Math.abs(total - 100) > 0.1) {
    errEl.textContent = `Weights must total 100% (currently ${total.toFixed(1)}%). Use "Normalize".`;
    errEl.hidden = false;
    return;
  }

  btn.disabled = true;
  btn.textContent = "Running…";
  try {
    const body = { allocation: currentAllocation() };
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
      { color: cssVar("--series-1"), fmt: (v) => `$${v.toFixed(2)}` });
    drawChart("drawdown-chart", r.drawdown.dates, r.drawdown.values,
      { color: cssVar("--series-8"), area: true, fmt: (v) => fmtPct(v) });
  } catch (e) {
    errEl.textContent = e.message || "Backtest failed.";
    errEl.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = "Run backtest";
  }
}

// ---------------------------------------------------------------- router
const VIEWS = ["markets", "stocks", "backtest", "assistant", "about"];

function route() {
  const view = VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "markets";
  for (const el of document.querySelectorAll(".view")) el.hidden = el.dataset.view !== view;
  for (const a of document.querySelectorAll(".nav a")) a.classList.toggle("active", a.dataset.view === view);
  if (view === "stocks") loadStocksView();
  if (view === "about") loadAbout();
}

// ---------------------------------------------------------------- auth
function renderAuthBox() {
  const box = $("auth-box");
  box.innerHTML = "";
  if (state.user) {
    const chip = document.createElement("span");
    chip.className = "user-chip";
    chip.textContent = state.user.username;
    if (state.user.is_admin) {
      const tag = document.createElement("span");
      tag.className = "admin-tag";
      tag.textContent = "admin";
      chip.appendChild(tag);
    }
    const out = document.createElement("button");
    out.className = "btn ghost";
    out.type = "button";
    out.textContent = "Sign out";
    out.addEventListener("click", async () => {
      await api("/api/auth/logout", { method: "POST" });
      state.user = null;
      state.watchlist = [];
      renderAuthBox();
      renderWatchStrip();
      renderStockTable();
      $("about-edit").hidden = true;
    });
    box.append(chip, out);
  } else {
    const btn = document.createElement("button");
    btn.className = "btn ghost";
    btn.type = "button";
    btn.textContent = "Sign in";
    btn.addEventListener("click", () => $("auth-modal").showModal());
    box.appendChild(btn);
  }
}

let authMode = "login";

function setAuthMode(mode) {
  authMode = mode;
  $("auth-title").textContent = mode === "login" ? "Sign in" : "Create account";
  $("auth-submit").textContent = mode === "login" ? "Sign in" : "Create account";
  $("auth-switch").textContent = mode === "login"
    ? "New here? Create an account" : "Have an account? Sign in";
  $("auth-error").hidden = true;
}

async function submitAuth() {
  const username = $("auth-username").value.trim();
  const password = $("auth-password").value;
  const errEl = $("auth-error");
  errEl.hidden = true;
  try {
    const user = await api(`/api/auth/${authMode === "login" ? "login" : "register"}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    state.user = user;
    $("auth-modal").close();
    $("auth-password").value = "";
    renderAuthBox();
    await refreshWatchlist();
    renderStockTable();
    $("about-edit").hidden = !user.is_admin;
  } catch (e) {
    errEl.textContent = e.message;
    errEl.hidden = false;
  }
}

function initAuth() {
  $("auth-submit").addEventListener("click", submitAuth);
  $("auth-close").addEventListener("click", () => $("auth-modal").close());
  $("auth-switch").addEventListener("click", () =>
    setAuthMode(authMode === "login" ? "register" : "login"));
  $("auth-form").addEventListener("submit", (e) => e.preventDefault());
  $("auth-password").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); submitAuth(); }
  });
}

// ---------------------------------------------------------------- stocks view
let stocksLoaded = false;

async function loadStocksView() {
  if (!stocksLoaded) {
    stocksLoaded = true;
    const [sp, ipos] = await Promise.all([
      api("/data/sp500.json"), api("/data/ipos.json"),
    ]);
    state.sp500 = sp.stocks;
    state.ipos = ipos.stocks;
    $("stock-search").addEventListener("input", () => {
      tablePage = 1;
      renderStockTable();
    });
    renderIpoStrip();
    fetchQuotes(state.ipos.map((s) => s.symbol)).then(renderIpoStrip);
  }
  renderStockTable();
  renderWatchStrip();
}

async function fetchQuotes(symbols) {
  const need = symbols.filter((s) => !(s in state.quotes));
  if (!need.length) return;
  try {
    const quotes = await api(`/api/stocks/quotes?symbols=${need.slice(0, 30).join(",")}`);
    for (const q of quotes) state.quotes[q.symbol] = q;
  } catch { /* quotes are best-effort */ }
}

function quoteCells(symbol) {
  const q = state.quotes[symbol];
  if (!q) return `<td class="num">—</td><td class="num">—</td>`;
  const up = q.change_pct >= 0;
  return `<td class="num">$${q.price.toFixed(2)}</td>` +
    `<td class="num chg ${up ? "up" : "down"}">${up ? "+" : ""}${q.change_pct.toFixed(2)}%</td>`;
}

function pinButton(symbol) {
  const pinned = state.watchlist.includes(symbol);
  const label = pinned ? "Unpin" : "Pin";
  return `<button class="pin-btn ${pinned ? "pinned" : ""}" data-symbol="${symbol}" ` +
    `title="${label} ${symbol}" aria-label="${label} ${symbol}">${pinned ? "★" : "☆"}</button>`;
}

async function togglePin(symbol) {
  if (!state.user) { $("auth-modal").showModal(); return; }
  const pinned = state.watchlist.includes(symbol);
  try {
    const r = pinned
      ? await api(`/api/watchlist/${symbol}`, { method: "DELETE" })
      : await api("/api/watchlist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ symbol }),
        });
    state.watchlist = r.symbols;
    renderWatchStrip();
    renderStockTable();
    renderIpoStrip();
  } catch (e) {
    alert(e.message);
  }
}

function bindPinButtons(container) {
  for (const btn of container.querySelectorAll(".pin-btn")) {
    btn.addEventListener("click", () => togglePin(btn.dataset.symbol));
  }
}

let tableRenderSeq = 0;
let quoteTimer = null;
let tablePage = 1;
const PAGE_SIZE = 50;

function renderPager(totalPages) {
  const pager = $("stock-pager");
  pager.innerHTML = "";
  if (totalPages <= 1) return;
  for (let p = 1; p <= totalPages; p++) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "page-btn" + (p === tablePage ? " active" : "");
    b.textContent = p;
    b.addEventListener("click", () => {
      tablePage = p;
      renderStockTable();
    });
    pager.appendChild(b);
  }
}

function renderStockTable() {
  if (!state.sp500.length) return;
  const seq = ++tableRenderSeq;
  const q = $("stock-search").value.trim().toLowerCase();
  const matches = q
    ? state.sp500.filter((s) =>
        s.symbol.toLowerCase().includes(q) || s.name.toLowerCase().includes(q))
    : state.sp500;
  const totalPages = Math.max(1, Math.ceil(matches.length / PAGE_SIZE));
  tablePage = Math.min(tablePage, totalPages);
  const startIdx = (tablePage - 1) * PAGE_SIZE;
  const shown = matches.slice(startIdx, startIdx + PAGE_SIZE);
  $("table-title").textContent = q ? `Search: “${$("stock-search").value.trim()}”` : "S&P 500";
  renderPager(totalPages);
  $("table-note").textContent =
    `${matches.length}${q ? " matches" : " companies"} · page ${tablePage} of ${totalPages}`;

  $("stock-rows").innerHTML = shown.map((s) =>
    `<tr><td>${pinButton(s.symbol)}</td><td class="sym">${s.symbol}</td>` +
    `<td>${s.name}</td><td class="sector">${s.sector}</td>${quoteCells(s.symbol)}</tr>`
  ).join("");
  bindPinButtons($("stock-rows"));

  // Load prices for the visible rows, debounced so typing doesn't spam fetches.
  clearTimeout(quoteTimer);
  quoteTimer = setTimeout(async () => {
    const symbols = shown.map((s) => s.symbol);
    for (let i = 0; i < symbols.length; i += 30) {
      await fetchQuotes(symbols.slice(i, i + 30));
    }
    if (seq !== tableRenderSeq) return;  // a newer render owns the table now
    const rows = $("stock-rows").rows;
    shown.forEach((s, i) => {
      if (!rows[i]) return;
      const tmp = document.createElement("tr");
      tmp.innerHTML = quoteCells(s.symbol);
      const [priceCell, chgCell] = [...tmp.children];
      const cells = rows[i].querySelectorAll(".num");
      cells[0].replaceWith(priceCell);
      cells[1].replaceWith(chgCell);
    });
  }, q ? 350 : 0);
}

function miniCard(symbol, name, sub, withUnpin) {
  const q = state.quotes[symbol];
  const up = q && q.change_pct >= 0;
  return `<div class="mini-card">` +
    (withUnpin ? `<button class="unpin" data-symbol="${symbol}" title="Unpin ${symbol}">✕</button>` : "") +
    `<span class="tk">${symbol}</span><span class="nm">${name}</span>` +
    (q ? `<div class="px">$${q.price.toFixed(2)}</div>` +
         `<span class="chg ${up ? "up" : "down"}">${up ? "+" : ""}${q.change_pct.toFixed(2)}%</span>`
       : `<div class="px">${sub}</div>`) +
    `</div>`;
}

function renderIpoStrip() {
  $("ipo-strip").innerHTML = state.ipos.map((s) =>
    miniCard(s.symbol, `${s.name} · ${s.sector}`, `IPO ${s.ipo}`, false)).join("");
}

async function renderWatchStrip() {
  const section = $("watch-section");
  if (!state.user || !state.watchlist.length) { section.hidden = true; return; }
  section.hidden = false;
  await fetchQuotes(state.watchlist);
  const names = {};
  for (const s of [...state.sp500, ...state.ipos]) names[s.symbol] = s.name;
  $("watch-strip").innerHTML = state.watchlist.map((sym) =>
    miniCard(sym, names[sym] || (state.quotes[sym] && state.quotes[sym].name) || "", "", true)).join("");
  for (const btn of $("watch-strip").querySelectorAll(".unpin")) {
    btn.addEventListener("click", () => togglePin(btn.dataset.symbol));
  }
}

async function refreshWatchlist() {
  if (!state.user) return;
  try {
    const r = await api("/api/watchlist");
    state.watchlist = r.symbols;
    for (const q of r.quotes) state.quotes[q.symbol] = q;
    renderWatchStrip();
  } catch { /* signed out */ }
}

// ---------------------------------------------------------------- about
let aboutLoaded = false;

function renderMarkdown(md) {
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  const blocks = md.trim().split(/\n{2,}/);
  return blocks.map((b) => {
    if (b.startsWith("### ")) return `<h3>${inline(b.slice(4))}</h3>`;
    if (b.startsWith("## ")) return `<h2>${inline(b.slice(3))}</h2>`;
    if (b.startsWith("# ")) return `<h1>${inline(b.slice(2))}</h1>`;
    const lines = b.split("\n");
    if (lines.every((l) => l.startsWith("- ")))
      return `<ul>${lines.map((l) => `<li>${inline(l.slice(2))}</li>`).join("")}</ul>`;
    return `<p>${inline(b).replace(/\n/g, "<br>")}</p>`;
  }).join("");
}

async function loadAbout() {
  if (aboutLoaded) return;
  aboutLoaded = true;
  const r = await api("/api/about");
  $("about-content").innerHTML = renderMarkdown(r.content);
  $("about-edit").hidden = !(state.user && state.user.is_admin);

  $("about-edit").addEventListener("click", async () => {
    const current = await api("/api/about");
    $("about-textarea").value = current.content;
    $("about-editor").hidden = false;
    $("about-content").hidden = true;
  });
  $("about-cancel").addEventListener("click", () => {
    $("about-editor").hidden = true;
    $("about-content").hidden = false;
  });
  $("about-save").addEventListener("click", async () => {
    try {
      const r2 = await api("/api/about", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: $("about-textarea").value }),
      });
      $("about-content").innerHTML = renderMarkdown(r2.content);
      $("about-editor").hidden = true;
      $("about-content").hidden = false;
    } catch (e) {
      alert(e.message);
    }
  });
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
  window.addEventListener("hashchange", route);
  initAuth();
  route();

  api("/api/auth/me").then(async (r) => {
    state.user = r.user;
    renderAuthBox();
    if (r.user) await refreshWatchlist();
  }).catch(renderAuthBox);

  try {
    await loadMarket();
  } catch {
    $("fund-grid").innerHTML = `<p class="error">Could not reach the API.</p>`;
    return;
  }
  renderWhatIfControls();
  renderBuilder();
  applyPreset("60/40");
  setInterval(loadMarket, 60 * 60 * 1000);
}

init();
