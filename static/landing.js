/* Landing hero: the real /api/growth endpoint, running live on the front page.
 * No mock data — if the API is down, the page says so rather than faking a curve.
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const NS = "http://www.w3.org/2000/svg";

  const els = {
    amount: $("lp-amount"), ticker: $("lp-ticker"), years: $("lp-years"),
    final: $("lp-final"), gain: $("lp-gain"), multiple: $("lp-multiple"),
    cagr: $("lp-cagr"), chart: $("lp-chart"), caption: $("lp-caption"),
    error: $("lp-error"),
  };

  const usd0 = new Intl.NumberFormat("en-US",
    { style: "currency", currency: "USD", maximumFractionDigits: 0 });

  const PREFERRED = ["VOO", "SPY", "QQQ", "VTI"];

  // ------------------------------------------------------------ hero number
  let countTimer = null;

  function countUp(el, to) {
    if (countTimer) cancelAnimationFrame(countTimer);
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const from = Number(el.dataset.value || 0);
    if (reduce || !from) {
      el.textContent = usd0.format(to);
      el.dataset.value = String(to);
      return;
    }
    const start = performance.now(), dur = 520;
    const tick = (now) => {
      const t = Math.min(1, (now - start) / dur);
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = usd0.format(from + (to - from) * eased);
      if (t < 1) countTimer = requestAnimationFrame(tick);
      else { el.dataset.value = String(to); countTimer = null; }
    };
    countTimer = requestAnimationFrame(tick);
  }

  /** Round gridline values inside [lo, hi] — never the raw data extremes. */
  function niceTicks(lo, hi, count = 3) {
    const raw = (hi - lo) / count || 1;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].find((m) => m * mag >= raw) * mag;
    const ticks = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(v);
    return ticks;
  }

  // ------------------------------------------------------------ the chart
  // One series, so no legend — the caption names it (dataviz: single series).
  function drawCurve(dates, values, animate) {
    els.chart.innerHTML = "";
    const box = els.chart.getBoundingClientRect();
    const W = Math.max(box.width, 280), H = Math.max(box.height, 150);
    const pad = { t: 10, r: 52, b: 20, l: 8 };
    const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;

    const lo = Math.min(...values), hi = Math.max(...values);
    const span = hi - lo || 1;
    const x = (i) => pad.l + (i / (values.length - 1)) * iw;
    const y = (v) => pad.t + ih - ((v - lo) / span) * ih;

    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label",
      `Growth of ${usd0.format(values[0])} to ${usd0.format(values[values.length - 1])} ` +
      `between ${dates[0]} and ${dates[dates.length - 1]}.`);

    const defs = document.createElementNS(NS, "defs");
    defs.innerHTML =
      `<linearGradient id="lp-fade" x1="0" y1="0" x2="0" y2="1">
         <stop offset="0%" stop-color="var(--series-1)" stop-opacity="0.20"/>
         <stop offset="100%" stop-color="var(--series-1)" stop-opacity="0"/>
       </linearGradient>`;
    svg.appendChild(defs);

    // Recessive gridlines at round values + right-hand value ticks.
    for (const v of niceTicks(lo, hi)) {
      const gy = y(v);
      const line = document.createElementNS(NS, "line");
      line.setAttribute("x1", pad.l); line.setAttribute("x2", pad.l + iw);
      line.setAttribute("y1", gy); line.setAttribute("y2", gy);
      line.setAttribute("class", "lp-gridline");
      svg.appendChild(line);

      const t = document.createElementNS(NS, "text");
      t.setAttribute("x", pad.l + iw + 8); t.setAttribute("y", gy + 4);
      t.setAttribute("class", "lp-tick");
      t.textContent = usd0.format(v);
      svg.appendChild(t);
    }

    // Baseline.
    const axis = document.createElementNS(NS, "line");
    axis.setAttribute("x1", pad.l); axis.setAttribute("x2", pad.l + iw);
    axis.setAttribute("y1", pad.t + ih); axis.setAttribute("y2", pad.t + ih);
    axis.setAttribute("class", "lp-axis");
    svg.appendChild(axis);

    // Date endpoints, so the window is readable off the chart itself.
    for (const [i, anchor] of [[0, "start"], [dates.length - 1, "end"]]) {
      const t = document.createElementNS(NS, "text");
      t.setAttribute("x", x(i)); t.setAttribute("y", pad.t + ih + 15);
      t.setAttribute("class", "lp-tick");
      t.setAttribute("text-anchor", anchor === "start" ? "start" : "end");
      t.textContent = dates[i].slice(0, 7);
      svg.appendChild(t);
    }

    const pts = values.map((v, i) => `${x(i).toFixed(2)},${y(v).toFixed(2)}`);

    const base = (pad.t + ih).toFixed(2);
    const area = document.createElementNS(NS, "path");
    area.setAttribute("class", "lp-area");
    area.setAttribute("d",
      `M${pts.join("L")}` +
      `L${x(values.length - 1).toFixed(2)},${base}` +
      `L${x(0).toFixed(2)},${base}Z`);
    svg.appendChild(area);

    const line = document.createElementNS(NS, "path");
    line.setAttribute("class", "lp-line");
    line.setAttribute("d", `M${pts.join("L")}`);
    svg.appendChild(line);

    // Hover layer: crosshair + dot + tooltip.
    const cross = document.createElementNS(NS, "line");
    cross.setAttribute("class", "lp-cross");
    cross.setAttribute("y1", pad.t); cross.setAttribute("y2", pad.t + ih);
    cross.setAttribute("visibility", "hidden");
    svg.appendChild(cross);

    const dot = document.createElementNS(NS, "circle");
    dot.setAttribute("class", "lp-dot"); dot.setAttribute("r", 5);
    dot.setAttribute("visibility", "hidden");
    svg.appendChild(dot);

    const hit = document.createElementNS(NS, "rect");
    hit.setAttribute("class", "lp-hit");
    hit.setAttribute("x", 0); hit.setAttribute("y", 0);
    hit.setAttribute("width", W); hit.setAttribute("height", H);
    svg.appendChild(hit);

    const tip = document.createElement("div");
    tip.className = "lp-tip"; tip.hidden = true;
    els.chart.appendChild(tip);

    const scaleX = () => W / els.chart.getBoundingClientRect().width;
    hit.addEventListener("pointermove", (e) => {
      const r = els.chart.getBoundingClientRect();
      const px = (e.clientX - r.left) * scaleX();
      const i = Math.max(0, Math.min(values.length - 1,
        Math.round(((px - pad.l) / iw) * (values.length - 1))));
      const cx = x(i), cy = y(values[i]);
      cross.setAttribute("x1", cx); cross.setAttribute("x2", cx);
      cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", cx); dot.setAttribute("cy", cy);
      dot.setAttribute("visibility", "visible");
      tip.hidden = false;
      tip.innerHTML = `<b>${usd0.format(values[i])}</b> <span>${dates[i]}</span>`;
      tip.style.left = `${cx / scaleX()}px`;
      tip.style.top = `${cy / scaleX() - 10}px`;
    });
    hit.addEventListener("pointerleave", () => {
      cross.setAttribute("visibility", "hidden");
      dot.setAttribute("visibility", "hidden");
      tip.hidden = true;
    });

    els.chart.appendChild(svg);

    if (animate) {
      const len = line.getTotalLength();
      line.style.setProperty("--len", len);
      line.style.strokeDasharray = len;
      line.style.strokeDashoffset = len;
      line.classList.add("draw");
    }
  }

  // ------------------------------------------------------------ data
  let seq = 0;

  async function refresh(animate) {
    const mine = ++seq;
    const amount = Number(els.amount.value);
    const ticker = els.ticker.value;
    const years = Number(els.years.value);
    if (!ticker || !(amount >= 100)) return;

    try {
      const res = await fetch(
        `/api/growth?ticker=${encodeURIComponent(ticker)}&amount=${amount}&years=${years}`);
      const body = await res.json();
      if (mine !== seq) return;                 // a newer request already won
      if (!res.ok) throw new Error(body.detail || "Could not run that scenario.");

      els.error.hidden = true;
      countUp(els.final, body.final_value);

      const up = body.gain >= 0;
      els.gain.textContent = `${up ? "+" : "−"}${usd0.format(Math.abs(body.gain))}`;
      els.gain.className = up ? "up" : "down";
      els.multiple.textContent = `${body.multiple.toFixed(2)}×`;
      els.cagr.textContent = `${body.cagr.toFixed(1)}%`;
      els.cagr.className = body.cagr >= 0 ? "up" : "down";

      const name = els.ticker.selectedOptions[0]?.dataset.name || ticker;
      els.caption.textContent =
        `${ticker} — ${name} · ${body.start} to ${body.end} · adjusted closes, dividends included`;
      drawCurve(body.curve.dates, body.curve.values, animate);
    } catch (err) {
      if (mine !== seq) return;
      els.error.textContent = err.message || "Could not reach the API.";
      els.error.hidden = false;
      els.caption.textContent = "";
      els.chart.innerHTML = "";
    }
  }

  const debounce = (fn, ms) => {
    let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  };
  const refreshSoon = debounce(() => refresh(false), 320);

  // ------------------------------------------------------------ news
  // SPY's feed is the broad-market one — index moves, ETF flows, big movers.
  // The section stays hidden unless real headlines come back, so a dead feed
  // leaves no empty shell on the page.
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  const STEPS = [["day", 86400], ["hour", 3600], ["minute", 60]];

  function ago(iso) {
    const t = Date.parse(iso);
    if (!Number.isFinite(t)) return "";
    const secs = (t - Date.now()) / 1000;
    for (const [unit, size] of STEPS) {
      if (Math.abs(secs) >= size) return rtf.format(Math.round(secs / size), unit);
    }
    return "just now";
  }

  async function loadNews() {
    const section = $("lp-news"), list = $("lp-news-list");
    try {
      const res = await fetch("/api/stocks/SPY/news?limit=6");
      if (!res.ok) return;
      const { items } = await res.json();
      if (!items?.length) return;

      for (const n of items) {
        // Feed content is third-party. Build nodes and assign textContent —
        // never innerHTML — so a headline can't inject markup.
        const a = document.createElement("a");
        a.href = n.url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";

        const title = document.createElement("span");
        title.className = "lp-news-title";
        title.textContent = n.title;

        const meta = document.createElement("span");
        meta.className = "lp-news-meta";
        const when = ago(n.published);
        meta.textContent = n.publisher + (when ? ` · ${when}` : "");

        a.append(title, meta);
        const li = document.createElement("li");
        li.appendChild(a);
        list.appendChild(li);
      }
      $("lp-news-stamp").textContent = `Updated ${ago(new Date().toISOString())}`;
      section.hidden = false;
    } catch {
      /* Headlines are a bonus, not the product — stay quiet and stay hidden. */
    }
  }

  // ------------------------------------------------------------ auth
  // Same endpoints and same session cookie as the app — signing in here means
  // you are already signed in when you land on /markets.
  let authMode = "login";
  let user = null;

  const modal = () => $("lp-auth-modal");

  function renderAuth() {
    const box = $("lp-auth");
    box.innerHTML = "";
    if (user) {
      const chip = document.createElement("span");
      chip.className = "lp-user-chip";
      chip.textContent = user.username;
      const out = document.createElement("button");
      out.className = "lp-btn lp-btn-ghost";
      out.type = "button";
      out.textContent = "Sign out";
      out.addEventListener("click", async () => {
        await fetch("/api/auth/logout", { method: "POST" });
        user = null;
        renderAuth();
      });
      box.append(chip, out);
    } else {
      const btn = document.createElement("button");
      btn.className = "lp-btn lp-btn-ghost";
      btn.type = "button";
      btn.textContent = "Sign in";
      btn.addEventListener("click", () => openAuth("login"));
      box.appendChild(btn);
    }
  }

  function setAuthMode(mode) {
    authMode = mode;
    const login = mode === "login";
    $("lp-auth-title").textContent = login ? "Sign in" : "Create an account";
    $("lp-auth-submit").textContent = login ? "Sign in" : "Create account";
    $("lp-auth-switch").textContent = login
      ? "New here? Create an account"
      : "Already have an account? Sign in";
    $("lp-auth-password").autocomplete = login ? "current-password" : "new-password";
    $("lp-auth-error").hidden = true;
  }

  function openAuth(mode) {
    setAuthMode(mode);
    modal().showModal();
    $("lp-auth-username").focus();
  }

  async function submitAuth(e) {
    e.preventDefault();
    const err = $("lp-auth-error");
    err.hidden = true;
    const body = JSON.stringify({
      username: $("lp-auth-username").value.trim(),
      password: $("lp-auth-password").value,
    });
    try {
      const res = await fetch(`/api/auth/${authMode}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Something went wrong.");
      user = data;
      $("lp-auth-password").value = "";
      modal().close();
      renderAuth();
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
    }
  }

  function initAuth() {
    $("lp-auth-form").addEventListener("submit", submitAuth);
    $("lp-auth-close").addEventListener("click", () => modal().close());
    $("lp-auth-switch").addEventListener("click", () =>
      setAuthMode(authMode === "login" ? "register" : "login"));
    $("lp-final-signin").addEventListener("click", () => openAuth("register"));

    fetch("/api/auth/me")
      .then((r) => r.json())
      .then((r) => {
        user = r.user;
        renderAuth();
        // Deep link: /?signin or /?signup opens the dialog directly.
        if (!user) {
          const q = new URLSearchParams(location.search);
          if (q.has("signup")) openAuth("register");
          else if (q.has("signin")) openAuth("login");
        }
      })
      .catch(renderAuth);
  }

  // ------------------------------------------------------------ init
  async function init() {
    initAuth();
    loadNews();   // deliberately not awaited — the hero must not wait on headlines
    try {
      const res = await fetch("/api/market?period=1Y");
      if (!res.ok) throw new Error();
      const { funds } = await res.json();
      for (const f of funds) {
        const o = document.createElement("option");
        o.value = f.ticker;
        o.dataset.name = f.name;
        o.textContent = `${f.ticker} — ${f.name}`;
        els.ticker.appendChild(o);
      }
      const pick = PREFERRED.find((t) => funds.some((f) => f.ticker === t));
      if (pick) els.ticker.value = pick;
    } catch {
      els.error.textContent = "Could not reach the API — is the server running?";
      els.error.hidden = false;
      els.caption.textContent = "";
      return;
    }

    els.amount.addEventListener("input", refreshSoon);
    els.ticker.addEventListener("change", () => refresh(true));
    els.years.addEventListener("change", () => refresh(true));

    let w = window.innerWidth;
    window.addEventListener("resize", debounce(() => {
      if (window.innerWidth !== w) { w = window.innerWidth; refresh(false); }
    }, 180));

    refresh(true);
  }

  init();
})();
