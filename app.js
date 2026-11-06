(function () {
  const $ = (id) => document.getElementById(id);
  let token = "";
  let dataPath = "";
  let state = null;
  let tab = "home";
  let openMint = null;
  const POLL_MS = 15000;

  function readFragment() {
    const raw = (location.hash || "").replace(/^#/, "");
    const found = {};
    if (raw) {
      raw.split("&").forEach((part) => {
        const i = part.indexOf("=");
        if (i <= 0) return;
        const key = part.slice(0, i);
        if (key !== "t" && key !== "d") return;
        let val = part.slice(i + 1);
        try { val = decodeURIComponent(val.replace(/\+/g, "%2B")); } catch (e) {}
        found[key] = val;
      });
    }
    try {
      if (found.t) localStorage.setItem("app_token", found.t);
      if (found.d) localStorage.setItem("data_path", found.d);
      token = found.t || localStorage.getItem("app_token") || "";
      dataPath = found.d || localStorage.getItem("data_path") || "";
    } catch (e) {
      token = found.t || "";
      dataPath = found.d || "";
    }
    if (!dataPath || /[\\/]/.test(dataPath) || dataPath.indexOf("..") !== -1) {
      if (dataPath) dataPath = "";
    }
    if (found.t || found.d) {
      try { history.replaceState(null, "", location.pathname + location.search); } catch (e) {}
    }
  }

  function dataUrl(parts) {
    const segs = [encodeURIComponent(dataPath)].concat(parts.map((p) => encodeURIComponent(p)));
    return "./d/" + segs.join("/") + "?t=" + Date.now();
  }

  async function getJson(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  }

  function show(el, on) { if (el) el.classList.toggle("hidden", !on); }

  function fmtUsd(n) {
    const v = Number(n || 0);
    return (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function setOdometer(n) {
    const el = $("odometer");
    el.textContent = fmtUsd(n);
  }

  function setModeBadge(mode) {
    const el = $("modeBadge");
    const paper = String(mode || "PAPER").toUpperCase() !== "LIVE";
    el.textContent = paper ? "PAPER" : "LIVE";
    el.className = "badge " + (paper ? "paper" : "live");
  }

  function goTab(name) {
    tab = name;
    openMint = null;
    ["home", "agents", "activity", "account"].forEach((t) => {
      show($("tab-" + t), t === name);
    });
    show($("screen-coin"), false);
    show($("screen-auditor"), false);
    document.querySelectorAll(".tabs button").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === name);
    });
  }

  function openCoin(mint) {
    if (!mint) return;
    openMint = mint;
    ["home", "agents", "activity", "account"].forEach((t) => show($("tab-" + t), false));
    show($("screen-auditor"), false);
    show($("screen-coin"), true);
    loadCoin(mint);
  }

  function openAuditor(mint) {
    openMint = null;
    show($("screen-coin"), false);
    ["home", "agents", "activity", "account"].forEach((t) => show($("tab-" + t), false));
    show($("screen-auditor"), true);
    renderAuditor((state && state.agents && state.agents.auditor) || {}, mint);
  }

  function goBack() {
    openMint = null;
    show($("screen-coin"), false);
    show($("screen-auditor"), false);
    goTab(tab);
  }

  function renderHome(s) {
    setModeBadge(s.mode);
    setOdometer(s.balance);
    const t = s.ticket || {};
    $("balanceSub").textContent = t.warning || (s.paper ? "Paper stack" : "Live stack");
    const pts = (s.chart || []).map((p) => ({ t: p.ts, y: p.balance }));
    const drew = window.DeskChart.drawLine($("balanceChart"), pts);
    show($("chartEmpty"), !drew);
    const box = $("positions");
    const opens = s.positions || [];
    box.innerHTML = opens.map((p) => {
      return `<div class="pos" data-mint="${esc(p.mint)}">
        <div><div class="name">${esc(p.name || p.symbol || (p.mint ? p.mint.slice(0, 6) : ""))}</div>
        <div class="meta">${fmtUsd(p.size_usd)} · stop -${p.stop_pct}%</div></div>
        <a class="link" href="${esc(p.link)}" target="_blank" rel="noopener">Sell on FOMO</a>
      </div>`;
    }).join("");
    show($("positionsEmpty"), opens.length === 0);
    box.querySelectorAll(".pos").forEach((el) => el.addEventListener("click", (e) => {
      if (e.target.closest("a")) return;
      openCoin(el.dataset.mint);
    }));
    $("homeActivity").innerHTML = renderFeed((s.activity || []).slice(0, 6));
    bindFeed($("homeActivity"));
  }

  function renderAgents(s) {
    const a = s.agents || {};
    const paused = new Set(s.paused || []);
    const set = s.settings || {};
    const scanner = a.scanner || {};
    const auditor = a.auditor || {};
    const analyst = a.analyst || {};
    const executor = a.executor || {};
    const risk = a.risk || {};
    const score = analyst.last_score;
    const deg = Math.max(0, Math.min(100, Number(score || 0))) * 3.6;
    const ringGood = score != null && score >= (set["analyst.min_score"] || 70);
    $("agents").innerHTML = `
      <p class="muted" style="margin:0 0 12px">Pause and resume from Telegram. This page is read-only.</p>
      ${agentCard("Scanner", scanner.status || "idle", `${scanner.pools || 0} pools`,
        `${scanner.passed || 0} passed · ${scanner.killed || 0} killed`, "scanner", paused.has("scanner"), scanner.detail)}
      ${agentCard("Auditor", auditor.status || "idle", `${auditor.taken || 0} taken apart`,
        auditor.detail || `${auditor.rejected || 0} rejected`, "auditor", paused.has("auditor"), "", auditorLayers(auditor))}
      <div class="card agent">
        <div class="top"><h3>Analyst</h3>${pauseLabel(paused.has("analyst"))}</div>
        <div class="ring ${ringGood ? "good" : ""}" style="--deg:${deg}deg"><span>${score == null ? "—" : score}</span></div>
        <div class="stat">${esc(analyst.status || "Scoring")} · ${esc(analyst.detail || "")}</div>
      </div>
      <div class="card agent">
        <div class="top"><h3>Executor</h3>${pauseLabel(paused.has("executor"))}</div>
        <div class="stat">${executor.trades || 0} trades · ${fmtUsd(set["executor.min_ticket_usd"] || 47.5)} · ${set["executor.stack_pct"] || 8}% of stack</div>
        <div class="bar"><span style="width:${executor.progress || 0}%"></span></div>
        <div class="stat">${esc(executor.detail || executor.status || "")}</div>
      </div>
      <div class="card agent">
        <div class="top"><h3>Risk</h3>${pauseLabel(paused.has("risk"))}</div>
        <div class="stat">${risk.guarding ? "Guarding" : (risk.last_exit || "flat")}</div>
        <div class="pills">
          <span class="pill stop">stop -${set["risk.stop_pct"] || 6}%</span>
          <span class="pill trail">trail ${set["risk.trail_pct"] || 12}%</span>
        </div>
      </div>`;
    const disc = $("agents").querySelector("[data-open-auditor]");
    if (disc) disc.addEventListener("click", () => openAuditor());
  }

  function auditorLayers(auditor) {
    const live = auditor.live_layers || [];
    if (!live.length) return `<div class="layer-grid">${[1,2,3,4,5,6,7,8].map((n) =>
      `<div class="layer grey">L${n}<div>not checked</div></div>`).join("")}</div>`;
    const by = {};
    live.forEach((l) => { by[l.n] = l; });
    return `<div class="layer-grid" data-open-auditor>${[1,2,3,4,5,6,7,8].map((n) => {
      const l = by[n];
      if (!l) return `<div class="layer grey">L${n}<div>not checked</div></div>`;
      const cls = l.pass ? "ok" : "red";
      return `<div class="layer ${cls}">${esc(l.name)}<div>${esc(l.value)}</div></div>`;
    }).join("")}</div>`;
  }

  function agentCard(title, status, stat, extra, name, isPaused, detail, extraHtml) {
    return `<div class="card agent">
      <div class="top"><h3>${title}</h3>${pauseLabel(isPaused)}</div>
      <div class="stat">${esc(stat)}</div>
      <div class="stat">${esc(extra || detail || status)}</div>
      ${extraHtml || ""}
    </div>`;
  }

  function pauseLabel(isPaused) {
    return `<span class="muted">${isPaused ? "Paused" : "Running"}</span>`;
  }

  function renderActivity(s) {
    const items = s.activity || [];
    $("activity").innerHTML = renderFeed(items);
    show($("activityEmpty"), items.length === 0);
    bindFeed($("activity"));
  }

  function renderFeed(items) {
    return `<div class="feed">${(items || []).map((a) => {
      const kill = a.kind === "scan_kill";
      const name = a.name || (a.mint ? a.mint.slice(0, 6) : "");
      return `<div class="feed-row ${kill ? "kill" : ""}" data-mint="${esc(a.mint || "")}">
        <div class="name">${esc(a.title || name)}</div>
        <div class="right">${esc(a.detail || "")}</div>
        <div class="sub">${esc(a.subtitle || "")}${a.link ? ` · <a class="link" href="${esc(a.link)}" target="_blank" rel="noopener">FOMO</a>` : ""}</div>
      </div>`;
    }).join("")}</div>`;
  }

  function bindFeed(root) {
    root.querySelectorAll(".feed-row").forEach((el) => {
      if (!el.dataset.mint) return;
      el.addEventListener("click", (e) => {
        if (e.target.closest("a")) return;
        openCoin(el.dataset.mint);
      });
    });
  }

  function renderAccount(s) {
    setModeBadge(s.mode);
    const warn = s.ticket && s.ticket.warning ? s.ticket.warning : "";
    $("modeNote").textContent = warn
      ? warn + " Mode, pause, and settings are read-only here — change them in Telegram."
      : "Mode, pause, and settings are read-only here. Change them in Telegram.";
    $("fomoHandle").textContent = s.fomo_handle ? "@" + s.fomo_handle : "";
    const inv = $("inviteLink");
    inv.href = s.signup || "#";
    inv.textContent = s.signup || "invite";
    renderSettings(s.settings || {});
  }

  function renderSettings(settings) {
    const box = $("settings");
    const groups = {};
    Object.keys(settings).sort().forEach((key) => {
      const g = key.split(".")[0];
      (groups[g] = groups[g] || []).push(key);
    });
    const names = Object.keys(groups);
    if (!names.length) {
      box.innerHTML = `<div class="empty">No settings in this snapshot.</div>`;
      return;
    }
    box.innerHTML = names.map((g) => {
      const rows = groups[g].map((key) => {
        const v = settings[key];
        const shown = typeof v === "boolean" ? (v ? "on" : "off") : (v == null ? "" : String(v));
        return `<div class="setting"><label>${esc(key)}<span>${esc(shown)}</span></label></div>`;
      }).join("");
      return `<h3 style="margin:16px 0 6px;font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">${esc(g)}</h3>${rows}`;
    }).join("");
  }

  async function loadCoin(mint, quiet) {
    if (!quiet) $("coinHead").innerHTML = `<div class="muted">Loading…</div>`;
    try {
      const c = await getJson(dataUrl(["coin", mint + ".json"]));
      if (openMint !== mint) return;
      const coin = c.coin || c;
      const name = coin.name || coin.symbol || mint.slice(0, 6);
      const link = c.link || coin.link || "";
      $("coinHead").innerHTML = `<h2>${esc(name)}</h2>
        <div class="muted">${esc(coin.symbol || "")} · ${esc(mint.slice(0, 6))}…</div>
        <p><a class="link" href="${esc(link)}" target="_blank" rel="noopener">Open on FOMO</a></p>`;
      $("coinActions").innerHTML = `
        <a class="btn" href="${esc(link)}" target="_blank" rel="noopener">Buy on FOMO</a>
        ${c.position ? `<a class="btn ghost" href="${esc(link)}" target="_blank" rel="noopener">Sell on FOMO</a>` : ""}`;
      const pts = (c.prices || []).map((p) => ({ t: p.ts, y: p.price_usd }));
      const dash = c.position && c.position.trail_active ? c.position.trail_line
        : (c.position ? c.position.stop_line : null);
      const drew = window.DeskChart.drawCandles($("coinChart"), pts, { dash });
      show($("coinChartEmpty"), !drew);
      const layers = c.layers || [];
      $("coinAudit").innerHTML = `<div class="card-head"><h2>Auditor</h2></div>` +
        `<div class="layer-grid">${[1,2,3,4,5,6,7,8].map((n) => {
          const l = layers.find((x) => x.n === n);
          if (!l) return `<div class="layer grey">L${n}<div>not checked</div></div>`;
          return `<div class="layer ${l.pass ? "ok" : "red"}">${esc(l.name)}<div>${esc(l.value)}</div></div>`;
        }).join("")}</div>`;
    } catch (err) {
      if (openMint !== mint) return;
      $("coinHead").innerHTML = `<div class="empty">Unknown coin.</div>`;
      $("coinActions").innerHTML = "";
    }
  }

  function renderAuditor(auditor) {
    $("auditorStatus").textContent = auditor.detail || auditor.status || "";
    $("layerGrid").innerHTML = [1,2,3,4,5,6,7,8].map((n) => {
      const live = (auditor.live_layers || []).find((l) => l.n === n);
      if (!live) return `<div class="layer grey">L${n}<div>not checked</div></div>`;
      return `<div class="layer ${live.pass ? "ok" : "red"} ${n === (auditor.live_layers || []).length ? "on" : ""}">${esc(live.name)}<div>${esc(live.value)}</div></div>`;
    }).join("");
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function applySnapshots(st, chartDoc, activityDoc) {
    state = st || {};
    if (chartDoc) {
      const pts = Array.isArray(chartDoc) ? chartDoc : (chartDoc.points || chartDoc.chart || null);
      if (Array.isArray(pts)) state.chart = pts;
    }
    if (activityDoc) {
      const items = Array.isArray(activityDoc) ? activityDoc : (activityDoc.items || activityDoc.activity || null);
      if (Array.isArray(items)) state.activity = items;
    }
  }

  async function refresh() {
    if (!dataPath) throw new Error("no data");
    const st = await getJson(dataUrl(["state.json"]));
    const chartDoc = await getJson(dataUrl(["chart.json"])).catch(() => null);
    const activityDoc = await getJson(dataUrl(["activity.json"])).catch(() => null);
    applySnapshots(st, chartDoc, activityDoc);
    renderHome(state);
    renderAgents(state);
    renderActivity(state);
    renderAccount(state);
    const coinVisible = $("screen-coin") && !$("screen-coin").classList.contains("hidden");
    if (coinVisible && openMint) await loadCoin(openMint, true);
    return state;
  }

  document.querySelectorAll(".tabs button").forEach((b) => {
    b.addEventListener("click", () => goTab(b.dataset.tab));
  });
  document.querySelectorAll("[data-back]").forEach((b) => b.addEventListener("click", goBack));
  document.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => goTab(b.dataset.go)));
  $("retryBtn").addEventListener("click", boot);

  async function boot() {
    readFragment();
    show($("error"), false);
    show($("loading"), true);
    show($("main"), false);
    if (!dataPath) {
      show($("loading"), false);
      $("error").querySelector("p").textContent = "Open the desk from your link to load data.";
      show($("error"), true);
      return;
    }
    try {
      await refresh();
      show($("loading"), false);
      show($("main"), true);
      if (navigator.serviceWorker) navigator.serviceWorker.register("sw.js").catch(() => {});
    } catch (e) {
      show($("loading"), false);
      $("error").querySelector("p").textContent = "Can't reach the desk.";
      show($("error"), true);
    }
  }

  boot();
  setInterval(() => { if (dataPath) refresh().catch(() => {}); }, POLL_MS);
})();
