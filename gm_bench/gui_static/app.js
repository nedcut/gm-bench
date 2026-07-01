const state = {
  agents: [],
  dashboard: null,
};

const els = {
  dbPath: document.querySelector("#dbPath"),
  mode: document.querySelector("#mode"),
  agent: document.querySelector("#agent"),
  seeds: document.querySelector("#seeds"),
  seasons: document.querySelector("#seasons"),
  runForm: document.querySelector("#runForm"),
  runButton: document.querySelector("#runButton"),
  runStatus: document.querySelector("#runStatus"),
  refreshButton: document.querySelector("#refreshButton"),
  metricRuns: document.querySelector("#metricRuns"),
  metricEpisodes: document.querySelector("#metricEpisodes"),
  metricBest: document.querySelector("#metricBest"),
  metricIllegal: document.querySelector("#metricIllegal"),
  leaderboardRows: document.querySelector("#leaderboardRows"),
  runsList: document.querySelector("#runsList"),
  transactionList: document.querySelector("#transactionList"),
};

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed: ${response.status}`);
  return payload;
}

async function loadDashboard() {
  const dashboard = await fetchJson("/api/dashboard");
  state.dashboard = dashboard;
  state.agents = dashboard.agents;
  renderAgentOptions();
  renderDashboard(dashboard);
}

function renderAgentOptions() {
  const current = els.agent.value || "value";
  els.agent.innerHTML = state.agents.map((agent) => `<option value="${agent}">${agent}</option>`).join("");
  els.agent.value = state.agents.includes(current) ? current : "value";
}

function renderDashboard(dashboard) {
  els.dbPath.textContent = dashboard.db_path;
  els.metricRuns.textContent = dashboard.metrics.runs.toLocaleString();
  els.metricEpisodes.textContent = dashboard.metrics.episodes.toLocaleString();
  els.metricBest.textContent = Number(dashboard.metrics.best_score).toFixed(3);
  els.metricIllegal.textContent = `${Number(dashboard.metrics.illegal_action_rate).toFixed(2)}%`;
  renderLeaderboard(dashboard.leaderboard);
  renderRuns(dashboard.runs);
  renderTransactions(dashboard.transactions);
}

function renderLeaderboard(rows) {
  if (!rows.length) {
    els.leaderboardRows.innerHTML = `<tr><td colspan="7">No logged episodes yet.</td></tr>`;
    return;
  }
  els.leaderboardRows.innerHTML = rows.map((row, index) => `
    <tr>
      <td>${index + 1}</td>
      <td><strong>${escapeHtml(row.agent)}</strong></td>
      <td><code>${row.seed}</code></td>
      <td class="score">${Number(row.final_score).toFixed(3)}</td>
      <td>${row.wins}</td>
      <td>${row.championships}</td>
      <td class="${row.illegal_actions ? "bad" : ""}">${row.illegal_actions}</td>
    </tr>
  `).join("");
}

function renderRuns(runs) {
  if (!runs.length) {
    els.runsList.innerHTML = `<div class="run-row"><p>No runs logged yet.</p></div>`;
    return;
  }
  els.runsList.innerHTML = runs.map((run) => `
    <div class="run-row">
      <header><span>${escapeHtml(run.command)} · ${escapeHtml(run.agent || "multiple")}</span><code>${run.id.slice(0, 8)}</code></header>
      <p>seeds ${escapeHtml(JSON.stringify(run.seeds))} · ${run.seasons || "—"} seasons · ${formatDate(run.created_at)}</p>
    </div>
  `).join("");
}

function renderTransactions(transactions) {
  if (!transactions.length) {
    els.transactionList.innerHTML = `<div class="transaction-row"><p>No transaction traces yet.</p></div>`;
    return;
  }
  els.transactionList.innerHTML = transactions.map((item) => `
    <div class="transaction-row">
      <header>
        <span class="${item.accepted ? "status-ok" : "status-bad"}">${item.accepted ? "ACCEPTED" : "ILLEGAL"} · ${escapeHtml(item.phase)}</span>
        <code>${item.run_id.slice(0, 8)}</code>
      </header>
      <p>${escapeHtml(item.agent)} seed ${item.seed}: ${escapeHtml(item.message)}</p>
      <p><code>${escapeHtml(actionSummary(item.action))}</code></p>
    </div>
  `).join("");
}

async function runBenchmark(event) {
  event.preventDefault();
  els.runButton.disabled = true;
  els.runStatus.textContent = "Running benchmark...";
  try {
    const mode = els.mode.value;
    const body = {
      mode,
      agent: els.agent.value,
      seeds: els.seeds.value,
      seasons: Number(els.seasons.value),
    };
    if (mode === "compare") body.agents = state.agents;
    if (mode === "evaluate") body.baselines = state.agents.filter((agent) => agent !== body.agent);
    const payload = await fetchJson("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    renderDashboard(payload.dashboard);
    els.runStatus.textContent = `Logged run ${payload.run_id}`;
  } catch (error) {
    els.runStatus.textContent = error.message;
  } finally {
    els.runButton.disabled = false;
  }
}

function setMode(mode) {
  els.mode.value = mode;
  document.querySelector("#run-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

function actionSummary(action) {
  const copy = { ...action };
  delete copy.model_error;
  return JSON.stringify(copy);
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

els.runForm.addEventListener("submit", runBenchmark);
els.refreshButton.addEventListener("click", loadDashboard);
document.querySelectorAll("[data-mode]").forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});
document.querySelectorAll("[data-jump]").forEach((button) => {
  button.addEventListener("click", () => document.querySelector(`#${button.dataset.jump}`).scrollIntoView({ behavior: "smooth", block: "start" }));
});

loadDashboard().catch((error) => {
  els.runStatus.textContent = error.message;
});

