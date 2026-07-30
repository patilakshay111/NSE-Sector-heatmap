const state = {
  view: "dashboard",
  status: null,
  pnlDate: null,
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
  const validGroups = groups.filter((group) => !group.noSetup);
  const stockCount = groups.reduce((count, group) => count + (group.stocks || []).length, 0);
  q("#stock-sector-count").textContent = groups.length ? String(validGroups.length) : "-";
  q("#stock-count").textContent = groups.length ? String(stockCount) : "-";

  if (!groups.length) {
    target.innerHTML = "<div class=\"empty-state\">Start streaming to select valid buy and sell sectors.</div>";
    return;
  }

  target.innerHTML = groups.map((group) => {
    const stocks = group.stocks || [];
    const tone = group.direction === "gain" ? "gain" : "loss";
    const groupTitle = group.direction === "gain" ? "Buy setup sector" : "Sell setup sector";
    if (group.noSetup) {
      return `
        <article class="stock-group ${tone} no-setup">
          <div class="panel-head">
            <div>
              <h2>No valid setup</h2>
              <span>${groupTitle}</span>
            </div>
            <strong>-</strong>
          </div>
          <div class="empty-state">${safe(group.reason || "No valid setup for this side.")}</div>
        </article>
      `;
    }
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

function renderSectorSelectionRule(rule) {
  const target = q("#stock-selection-rule");
  if (!target) return;
  if (rule?.label) {
    target.textContent = rule.label;
    return;
  }
  target.textContent = "-";
}

function tradeSideClass(side) {
  return side === "BUY" ? "good" : "bad";
}

function renderPaperTrading(paper) {
  const data = paper || {};
  const ideas = data.ideas || [];
  const activeTrades = data.openTrades || data.activeTrades || [];
  const closedTrades = data.closedTrades || [];

  q("#p-initial").textContent = fmt(data.initialCapital, 0);
  q("#p-available").textContent = fmt(data.availableCapital, 0);
  q("#p-allocated").textContent = fmt(data.allocatedCapital, 0);
  q("#p-unrealized").textContent = fmt(data.unrealizedPnl);
  q("#p-unrealized").className = changeClass(data.unrealizedPnl);
  q("#p-realized").textContent = fmt(data.realizedPnl);
  q("#p-realized").className = changeClass(data.realizedPnl);
  q("#p-active-count").textContent = data.activeCount ?? "-";
  q("#p-total-trades").textContent = data.totalTrades ?? "-";
  q("#p-win-rate").textContent = Number.isFinite(Number(data.winRate)) ? pct(data.winRate) : "-";
  q("#p-profit-factor").textContent = data.profitFactorLabel || (Number.isFinite(Number(data.profitFactor)) ? fmt(data.profitFactor, 2) : "-");
  q("#p-saved").textContent = data.persistenceError ? "Save error" : data.lastSavedAt || "-";
  q("#p-saved").className = data.persistenceError ? "bad" : "";
  q("#p-idea-count").textContent = data.sessionOpen ? `${ideas.length} ideas` : data.sessionStatus || "Waiting for session";
  q("#p-closed-count").textContent = `${data.closedCount || 0} closed`;

  q("#paper-ideas-body").innerHTML = data.persistenceError ? `<tr><td colspan="11" class="empty-state bad">${safe(data.persistenceError)}</td></tr>` : ideas.length ? ideas.map((idea) => `
    <tr class="${idea.ready ? "ready-row" : ""}">
      <td>
        <strong>${safe(idea.symbol)}</strong>
        <span>${safe(idea.sector)}</span>
      </td>
      <td class="${tradeSideClass(idea.side)}">${safe(idea.side)}</td>
      <td>
        <strong>${safe(idea.thesis)}</strong>
        <span>${safe(idea.m5?.startedAt || "-")} / O ${fmt(idea.m5?.open)} C ${fmt(idea.m5?.close)}</span>
      </td>
      <td>${fmt(idea.quantity, 0)}</td>
      <td>${fmt(idea.entry)}</td>
      <td>${fmt(idea.stopLoss)}</td>
      <td>${fmt(idea.target)}</td>
      <td>${fmt(idea.rr)}</td>
      <td class="bad">${fmt(idea.lossIfSl)}</td>
      <td class="good">${fmt(idea.profitIfTp)}</td>
      <td><span class="status-pill ${idea.ready ? "ready" : ""}">${safe(idea.status)}</span></td>
    </tr>
  `).join("") : `<tr><td colspan="11" class="empty-state">${safe(data.sessionStatus || "Waiting for selected stocks and M5 candles.")}</td></tr>`;

  q("#active-trades-body").innerHTML = activeTrades.length ? activeTrades.map((trade) => `
    <tr>
      <td>
        <strong>${safe(trade.id)}</strong>
        <span>${safe(trade.entryTime || trade.openedAt)}</span>
      </td>
      <td>${safe(trade.symbol)}</td>
      <td class="${tradeSideClass(trade.side)}">${safe(trade.side)}</td>
      <td>${safe(trade.thesis)}</td>
      <td>${fmt(trade.quantity, 0)}</td>
      <td>${safe(trade.entryTime || trade.openedAt)}</td>
      <td>${fmt(trade.entry)}</td>
      <td>${fmt(trade.currentPrice)}</td>
      <td>${fmt(trade.stopLoss)}</td>
      <td>${fmt(trade.target)}</td>
      <td>${fmt(trade.currentRr ?? trade.rr)}</td>
      <td class="${changeClass(trade.unrealizedPnl)}">${fmt(trade.unrealizedPnl)}</td>
      <td>
        <strong>${trade.stopMovedToBe ? "BE+" : "Initial"}</strong>
        <span>${safe(trade.stopMoveReason || "Waiting for RR trigger")}</span>
      </td>
      <td><button class="close-trade-btn danger" type="button" data-trade-id="${safe(trade.id)}">Close</button></td>
    </tr>
  `).join("") : "<tr><td colspan=\"14\" class=\"empty-state\">No active paper trades yet.</td></tr>";

  q("#closed-trades-body").innerHTML = closedTrades.length ? closedTrades.map((trade) => `
    <tr>
      <td>${safe(trade.id)}</td>
      <td>${safe(trade.symbol)}</td>
      <td class="${tradeSideClass(trade.side)}">${safe(trade.side)}</td>
      <td>${safe(trade.exitReason)}</td>
      <td>${fmt(trade.quantity, 0)}</td>
      <td>${safe(trade.entryTime || trade.openedAt)}</td>
      <td>${safe(trade.exitTime || trade.closedAt)}</td>
      <td>${fmt(trade.entry)}</td>
      <td>${fmt(trade.exitPrice)}</td>
      <td class="${changeClass(trade.realizedPnl)}">${fmt(trade.realizedPnl)}</td>
    </tr>
  `).join("") : "<tr><td colspan=\"10\" class=\"empty-state\">No closed paper trades yet.</td></tr>";
}

function reportPnlRows(rows, emptyText, colspan = 8) {
  if (!rows.length) {
    return `<tr><td colspan="${colspan}" class="empty-state">${emptyText}</td></tr>`;
  }
  return rows.map((row) => `
    <tr>
      <td>${safe(row.name)}</td>
      <td class="${changeClass(row.totalPnl)}">${fmt(row.totalPnl)}</td>
      <td class="${changeClass(row.realizedPnl)}">${fmt(row.realizedPnl)}</td>
      <td class="${changeClass(row.unrealizedPnl)}">${fmt(row.unrealizedPnl)}</td>
      <td>${fmt(row.totalTrades, 0)} <span>${fmt(row.closedTrades, 0)} closed / ${fmt(row.openTrades, 0)} open</span></td>
      <td>${Number.isFinite(Number(row.winRate)) ? pct(row.winRate) : "-"}</td>
      <td>${safe(row.profitFactorLabel || "-")}</td>
      <td>${fmt(row.winningTrades, 0)} / ${fmt(row.losingTrades, 0)}</td>
    </tr>
  `).join("");
}

function syncPnlDateControl(report) {
  const input = q("#paper-pnl-date");
  if (!input || !report?.date) return;
  if (report.today) {
    input.max = report.today;
  } else {
    input.removeAttribute("max");
  }
  input.value = report.date;
  state.pnlDate = report.date;
}

function renderPaperReport(report, options = {}) {
  report = report || {};
  if (options.syncDate !== false) {
    syncPnlDateControl(report);
  }
  q("#r-date").textContent = report.date || "-";
  q("#r-total-pnl").textContent = fmt(report.totalPnl);
  q("#r-total-pnl").className = changeClass(report.totalPnl);
  q("#r-realized-pnl").textContent = fmt(report.realizedPnl);
  q("#r-realized-pnl").className = changeClass(report.realizedPnl);
  q("#r-open-pnl").textContent = fmt(report.unrealizedPnl);
  q("#r-open-pnl").className = changeClass(report.unrealizedPnl);
  q("#r-total-trades").textContent = report.totalTrades ?? "-";
  q("#r-win-rate").textContent = Number.isFinite(Number(report.winRate)) ? pct(report.winRate) : "-";
  q("#r-profit-factor").textContent = report.profitFactorLabel || "-";

  const emptySuffix = report.date ? `for ${report.date}` : "for this day";
  q("#stock-pnl-body").innerHTML = reportPnlRows(report.stockRows || [], `No stock P/L ${emptySuffix}.`);
  q("#thesis-pnl-body").innerHTML = reportPnlRows(report.thesisRows || [], `No thesis P/L ${emptySuffix}.`);
  const exitRows = report.exitRows || [];
  q("#exit-pnl-body").innerHTML = exitRows.length ? exitRows.map((row) => `
    <tr>
      <td>${safe(row.name)}</td>
      <td class="${changeClass(row.realizedPnl)}">${fmt(row.realizedPnl)}</td>
      <td>${fmt(row.closedTrades, 0)}</td>
      <td>${Number.isFinite(Number(row.winRate)) ? pct(row.winRate) : "-"}</td>
      <td>${safe(row.profitFactorLabel || "-")}</td>
      <td>${fmt(row.winningTrades, 0)} / ${fmt(row.losingTrades, 0)}</td>
    </tr>
  `).join("") : `<tr><td colspan="6" class="empty-state">No exits ${emptySuffix}.</td></tr>`;
}

async function loadPaperReport(dateKey) {
  const query = dateKey ? `?date=${encodeURIComponent(dateKey)}` : "";
  const result = await api(`/api/paper-pnl${query}`);
  renderPaperReport(result.dailyReport || {}, { syncDate: true });
}

function renderSettings(status) {
  const source = q("#source-url");
  source.textContent = status.source_url || "-";
  source.href = status.source_url || "#";
  q("#api-url").textContent = status.api_url || "-";
  q("#stock-api-url").textContent = status.stock_api_url || "-";
  q("#holiday-api-url").textContent = status.holiday_api_url || "-";
  q("#market-status-api-url").textContent = status.market_status_api_url || "-";
  q("#poll-interval").textContent = `${status.poll_seconds || 0}s`;
  const clock = status.market_clock || {};
  const nextHoliday = clock.nextHoliday || null;
  q("#market-clock").textContent = `${clock.shouldStream ? "Open" : "Sleeping"} / ${clock.reason || "-"}`;
  q("#market-clock").className = clock.shouldStream ? "good" : "warn";
  q("#next-open-at").textContent = clock.nextOpenAt || "-";
  q("#today-holiday").textContent = clock.isHoliday ? clock.holidayName || "Trading holiday" : "No";
  q("#today-holiday").className = clock.isHoliday ? "warn" : "good";
  q("#next-holiday").textContent = nextHoliday ? `${nextHoliday.date} / ${nextHoliday.description}` : "-";
  const provenance = status.data_provenance || {};
  q("#mock-prices").textContent = provenance.mockPricesAllowed ? "Allowed" : "Blocked";
  q("#mock-prices").className = provenance.mockPricesAllowed ? "bad" : "good";
  q("#paper-data-policy").textContent = status.paper_trading?.dataPolicy?.lookAheadBiasGuard || provenance.paperLogic || "-";
  const stopConfig = status.paper_trading?.stopManagement || {};
  q("#paper-be-enabled").textContent = stopConfig.moveSlToBreakEven ? "On" : "Off";
  q("#paper-be-enabled").className = stopConfig.moveSlToBreakEven ? "good" : "warn";
  q("#paper-be-trigger").textContent = `${fmt(stopConfig.breakEvenTriggerRr, 2)}R`;
  q("#paper-be-lock").textContent = `${fmt(stopConfig.profitLockRr, 2)}R`;
  q("#last-error").textContent = status.last_error || "-";
  q("#last-error").className = status.last_error ? "bad" : "";
}

function renderStatus(status) {
  state.status = status;
  const rows = status.sector_rows || [];
  const ok = status.running && !status.last_error;
  const clock = status.market_clock || {};
  q("#status-line").textContent = status.last_error
    ? `NSE stream warning: ${status.last_error}`
    : `${status.streaming_label} / ${clock.reason || "Market clock"} / ${status.snapshot_time || clock.nextOpenAt || "waiting for NSE tick"}`;
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
  renderSectorSelectionRule(status.sector_selection_rule);
  renderStockGroups(status.sector_stock_groups || []);
  renderPaperTrading(status.paper_trading || {});
  const liveReport = status.paper_trading?.dailyReport || {};
  if (!state.pnlDate || state.pnlDate === liveReport.date) {
    renderPaperReport(liveReport);
  }
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

async function closePaperTrade(tradeId) {
  const result = await api("/api/paper-trades/close", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ trade_id: tradeId }),
  });
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
q("#paper-pnl-date").addEventListener("change", (event) => {
  const selectedDate = event.target.value;
  state.pnlDate = selectedDate;
  loadPaperReport(selectedDate).catch((err) => {
    q("#status-line").textContent = err.message;
  });
});
q("#paper-pnl-today").addEventListener("click", () => {
  const today = state.status?.paper_trading?.dailyReport?.date || "";
  state.pnlDate = today || null;
  if (today) {
    renderPaperReport(state.status.paper_trading.dailyReport);
  } else {
    loadPaperReport("").catch((err) => {
      q("#status-line").textContent = err.message;
    });
  }
});

document.addEventListener("click", (event) => {
  const button = event.target?.closest?.(".close-trade-btn");
  if (!button) return;
  const tradeId = button.dataset.tradeId;
  button.disabled = true;
  button.textContent = "Closing...";
  closePaperTrade(tradeId).catch((err) => {
    q("#status-line").textContent = err.message;
    button.disabled = false;
    button.textContent = "Close";
  });
});

refresh().catch((err) => {
  q("#status-line").textContent = err.message;
});
setInterval(() => refresh().catch(() => {}), 5000);
