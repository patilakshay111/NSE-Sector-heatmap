const state = {
  view: "dashboard",
  status: null,
  theme: document.documentElement.dataset.theme === "dark" ? "dark" : "light",
};

function q(selector) {
  return document.querySelector(selector);
}

function applyTheme(theme) {
  state.theme = theme === "dark" ? "dark" : "light";
  if (state.theme === "dark") {
    document.documentElement.dataset.theme = "dark";
  } else {
    delete document.documentElement.dataset.theme;
  }
  localStorage.setItem("theme", state.theme);

  const toggle = q("#theme-toggle");
  const isDark = state.theme === "dark";
  toggle.textContent = isDark ? "Light Mode" : "Dark Mode";
  toggle.setAttribute("aria-pressed", String(isDark));
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json();
}

function fmt(value, digits = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return n.toLocaleString("en-IN", { maximumFractionDigits: digits });
}

function pct(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return `${n >= 0 ? "+" : ""}${fmt(n, 2)}%`;
}

function safe(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#039;");
}

function changeClass(value) {
  const n = Number(value || 0);
  if (n > 0) return "good";
  if (n < 0) return "bad";
  return "warn";
}

function heatColor(value) {
  const n = Number(value || 0);
  if (n > 0) return "var(--heat-good)";
  if (n < 0) return "var(--heat-bad)";
  return "var(--heat-flat)";
}

function titleForView(view) {
  return String(view || "")
    .split("-")
    .map((part) => part ? part[0].toUpperCase() + part.slice(1) : "")
    .join(" ");
}

function setView(view) {
  state.view = view;
  document.querySelectorAll(".nav").forEach((btn) => btn.classList.toggle("active", btn.dataset.view === view));
  document.querySelectorAll(".view").forEach((panel) => panel.classList.toggle("active", panel.id === view));
  q("#page-title").textContent = titleForView(view);
}

function leaderDetail(row) {
  if (!row) return "Waiting for NSE data.";
  const parts = [
    `LTP ${fmt(row.last)}`,
    `change ${fmt(row.change)}`,
    `Adv ${row.advances || 0}`,
    `Dec ${row.declines || 0}`,
  ];
  return parts.join(" / ");
}

function renderLeaders(status) {
  const gain = status.max_gainer;
  const loss = status.max_loser;
  q("#max-gain-name").textContent = gain?.symbol || "-";
  q("#max-gain-change").textContent = pct(gain?.percentChange);
  q("#max-gain-detail").textContent = leaderDetail(gain);
  q("#max-loss-name").textContent = loss?.symbol || "-";
  q("#max-loss-change").textContent = pct(loss?.percentChange);
  q("#max-loss-detail").textContent = leaderDetail(loss);
}

function renderMomentum(rows) {
  const target = q("#momentum-list");
  if (!rows.length) {
    target.innerHTML = "<div class=\"empty-state\">No sectoral index data returned yet.</div>";
    return;
  }
  const maxAbs = Math.max(0.1, ...rows.map((row) => Math.abs(Number(row.percentChange || 0))));
  target.innerHTML = rows.map((row) => {
    const width = Math.max(2, (Math.abs(Number(row.percentChange || 0)) / maxAbs) * 100);
    return `
      <div class="momentum-row">
        <div class="momentum-name">${row.symbol}</div>
        <div class="momentum-track">
          <div class="momentum-bar" style="width:${width}%; background:${heatColor(row.percentChange)}"></div>
        </div>
        <strong class="${changeClass(row.percentChange)}">${pct(row.percentChange)}</strong>
      </div>
    `;
  }).join("");
}

function renderHeatmap(rows) {
  const target = q("#sector-heatmap");
  if (!rows.length) {
    target.innerHTML = "<div class=\"empty-state\">Start streaming to load sector tiles.</div>";
    return;
  }
  target.innerHTML = rows.map((row) => `
    <article class="sector-tile" style="--tile-color:${heatColor(row.percentChange)}">
      <strong>${row.symbol}</strong>
      <div class="tile-change">${pct(row.percentChange)}</div>
      <span>LTP ${fmt(row.last)} / ${fmt(row.change)} pts</span>
      <span>Adv ${row.advances || 0} / Dec ${row.declines || 0}</span>
    </article>
  `).join("");
}

function renderTable(rows) {
  const body = q("#indices-body");
  if (!rows.length) {
    body.innerHTML = "<tr><td colspan=\"10\" class=\"empty-state\">No sectors found in the latest NSE response.</td></tr>";
    return;
  }
  body.innerHTML = rows.map((row) => `
    <tr>
      <td>${row.symbol}</td>
      <td>${fmt(row.last)}</td>
      <td class="${changeClass(row.change)}">${fmt(row.change)}</td>
      <td class="${changeClass(row.percentChange)}">${pct(row.percentChange)}</td>
      <td>${fmt(row.open)}</td>
      <td>${fmt(row.high)}</td>
      <td>${fmt(row.low)}</td>
      <td>${row.advances || 0}</td>
      <td>${row.declines || 0}</td>
      <td class="${changeClass(row.breadth)}">${fmt(row.breadth, 3)}</td>
    </tr>
  `).join("");
}

function renderStockGroups(groups) {
  const target = q("#stock-groups");
  const stockCount = groups.reduce((count, group) => count + (group.stocks || []).length, 0);
  q("#stock-sector-count").textContent = groups.length || "-";
  q("#stock-count").textContent = stockCount || "-";

  if (!groups.length) {
    target.innerHTML = "<div class=\"empty-state\">Start streaming to select top and losing sectors.</div>";
    return;
  }

  target.innerHTML = groups.map((group) => {
    const stocks = group.stocks || [];
    const tone = group.direction === "gain" ? "gain" : "loss";
    const groupTitle = group.direction === "gain" ? "Top gain sector" : "Top losing sector";
    const rows = stocks.length ? stocks.map((stock) => `
      <tr>
        <td>
          <strong>${safe(stock.symbol)}</strong>
          ${stock.name ? `<span>${safe(stock.name)}</span>` : ""}
        </td>
        <td>${fmt(stock.open)}</td>
        <td>${fmt(stock.current)}</td>
        <td>${fmt(stock.vwap)}</td>
        <td class="${changeClass(stock.change)}">${fmt(stock.change)}</td>
        <td class="${changeClass(stock.percentChange)}">${pct(stock.percentChange)}</td>
        <td>${fmt(stock.low)} - ${fmt(stock.high)}</td>
        <td>${fmt(stock.volume, 0)}</td>
      </tr>
    `).join("") : "<tr><td colspan=\"8\" class=\"empty-state\">No stock rows returned for this sector.</td></tr>";
    return `
      <article class="stock-group ${tone}">
        <div class="panel-head">
          <div>
            <h2>${safe(group.sector)}</h2>
            <span>${groupTitle}</span>
          </div>
          <strong class="${changeClass(group.sectorPercentChange)}">${pct(group.sectorPercentChange)}</strong>
        </div>
        ${group.error ? `<div class="empty-state bad">${safe(group.error)}</div>` : `
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Stock</th><th>Day Open</th><th>Current</th><th>VWAP</th><th>Today Gain</th><th>% Today</th><th>Day Range</th><th>Volume</th>
                </tr>
              </thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        `}
      </article>
    `;
  }).join("");
}

function renderSettings(status) {
  const source = q("#source-url");
  source.textContent = status.source_url || "-";
  source.href = status.source_url || "#";
  q("#api-url").textContent = status.api_url || "-";
  q("#stock-api-url").textContent = status.stock_api_url || "-";
  q("#poll-interval").textContent = `${status.poll_seconds || 0}s`;
  q("#last-error").textContent = status.last_error || "-";
  q("#last-error").className = status.last_error ? "bad" : "";
}

function renderStatus(status) {
  state.status = status;
  const rows = status.sector_rows || [];
  const ok = status.running && !status.last_error;
  q("#status-line").textContent = status.last_error
    ? `NSE stream warning: ${status.last_error}`
    : `${status.streaming_label} / ${status.snapshot_time || "waiting for NSE tick"}`;
  q("#status-line").className = status.last_error ? "bad" : "";
  q("#m-streaming").textContent = status.streaming_label || "-";
  q("#m-streaming").className = ok ? "good" : status.running ? "warn" : "bad";
  q("#m-snapshot").textContent = status.snapshot_time || "-";
  q("#m-success").textContent = status.last_success_at || "-";
  q("#m-count").textContent = status.fetch_count || 0;
  q("#m-sectors").textContent = rows.length;
  q("#m-speed").textContent = `${status.poll_seconds || 0}s`;
  q("#heatmap-note").textContent = status.streaming_label === "On" ? "Streaming on" : "Streaming off";

  renderLeaders(status);
  renderMomentum(rows);
  renderHeatmap(rows);
  renderTable(rows);
  renderStockGroups(status.sector_stock_groups || []);
  renderSettings(status);
}

async function refresh() {
  const status = await api("/api/status");
  renderStatus(status);
}

async function command(path) {
  const result = await api(path, { method: "POST" });
  renderStatus(result.status);
}

document.querySelectorAll(".nav").forEach((btn) => {
  btn.addEventListener("click", () => setView(btn.dataset.view));
});

applyTheme(state.theme);
q("#theme-toggle").addEventListener("click", () => {
  applyTheme(state.theme === "dark" ? "light" : "dark");
});
q("#start-btn").addEventListener("click", () => command("/api/start").catch((err) => {
  q("#status-line").textContent = err.message;
}));
q("#stop-btn").addEventListener("click", () => command("/api/stop").catch((err) => {
  q("#status-line").textContent = err.message;
}));
q("#refresh-btn").addEventListener("click", () => command("/api/refresh").catch((err) => {
  q("#status-line").textContent = err.message;
}));

refresh().catch((err) => {
  q("#status-line").textContent = err.message;
});
setInterval(() => refresh().catch(() => {}), 5000);
