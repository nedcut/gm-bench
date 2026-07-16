const state = {
  agents: [],
  dashboard: null,
  latestResult: null,
};

const modeHelp = {
  run: "Single-agent benchmark across the selected seeds.",
  compare: "Runs every built-in agent across the same seeds.",
  evaluate: "Scores one candidate against the remaining baseline panel.",
};

const els = {
  dbPath: document.querySelector("#dbPath"),
  mode: document.querySelector("#mode"),
  modeHelp: document.querySelector("#modeHelp"),
  agent: document.querySelector("#agent"),
  seeds: document.querySelector("#seeds"),
  seasons: document.querySelector("#seasons"),
  runForm: document.querySelector("#runForm"),
  runButton: document.querySelector("#runButton"),
  runStatus: document.querySelector("#runStatus"),
  refreshButton: document.querySelector("#refreshButton"),
  resultPanel: document.querySelector("#resultPanel"),
  resultTitle: document.querySelector("#resultTitle"),
  resultBody: document.querySelector("#resultBody"),
  resultStats: document.querySelector("#resultStats"),
  insightCards: document.querySelector("#insightCards"),
  scoreChart: document.querySelector("#scoreChart"),
  metricRuns: document.querySelector("#metricRuns"),
  metricEpisodes: document.querySelector("#metricEpisodes"),
  metricBest: document.querySelector("#metricBest"),
  metricIllegal: document.querySelector("#metricIllegal"),
  standingsRows: document.querySelector("#standingsRows"),
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
  setStatus("Refreshing dashboard...", "loading");
  const dashboard = await fetchJson("/api/dashboard");
  state.dashboard = dashboard;
  state.agents = dashboard.agents;
  renderAgentOptions();
  renderDashboard(dashboard);
  setStatus("Ready", "ready");
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
  renderInsights(dashboard.insights || []);
  renderScoreChart(dashboard.score_history || []);
  renderStandings(dashboard.agent_standings || []);
  renderLeaderboard(dashboard.leaderboard);
  renderRuns(dashboard.runs);
  renderTransactions(dashboard.transactions);
}

function renderInsights(insights) {
  if (!insights.length) {
    els.insightCards.innerHTML = `<div class="empty-state">Run a benchmark to generate database signals.</div>`;
    return;
  }
  els.insightCards.innerHTML = insights.map((item) => `
    <article class="insight-card ${escapeHtml(item.tone || "neutral")}">
      <strong>${escapeHtml(item.title)}</strong>
      <p>${escapeHtml(item.detail)}</p>
    </article>
  `).join("");
}

function renderScoreChart(points) {
  if (!points.length) {
    els.scoreChart.innerHTML = `<div class="empty-state">No score history yet.</div>`;
    return;
  }
  const maxScore = Math.max(...points.map((point) => Number(point.final_score)), 1);
  els.scoreChart.innerHTML = points.map((point) => {
    const height = Math.max(10, Math.round((Number(point.final_score) / maxScore) * 100));
    return `
      <div class="score-bar" title="${escapeHtml(point.agent)} seed ${point.seed}: ${Number(point.final_score).toFixed(3)}">
        <span style="height: ${height}%"></span>
        <small>${escapeHtml(point.agent.slice(0, 3))}</small>
      </div>
    `;
  }).join("");
}

function renderStandings(rows) {
  if (!rows.length) {
    els.standingsRows.innerHTML = `<tr><td colspan="9">No logged agent standings yet.</td></tr>`;
    return;
  }
  els.standingsRows.innerHTML = rows.map((row, index) => `
    <tr>
      <td>${index + 1}</td>
      <td><strong>${escapeHtml(row.agent)}</strong></td>
      <td>${row.episodes}</td>
      <td class="score">${Number(row.mean_score).toFixed(3)}</td>
      <td>${Number(row.best_score).toFixed(3)}</td>
      <td>${Number(row.range).toFixed(3)}</td>
      <td>${Number(row.mean_wins).toFixed(2)}</td>
      <td>${row.titles}</td>
      <td class="${row.illegal_actions ? "bad" : ""}">${row.illegal_actions}</td>
    </tr>
  `).join("");
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
  els.runsList.innerHTML = runs.map((run) => {
    const summary = runSummaryLine(run);
    return `
      <button class="run-row" type="button" data-run-id="${escapeHtml(run.id)}">
        <header><span>${escapeHtml(run.command)} · ${escapeHtml(run.agent || "multiple")}</span><code>${run.id.slice(0, 8)}</code></header>
        <p>${escapeHtml(summary)}</p>
        <p>seeds ${escapeHtml(JSON.stringify(run.seeds))} · ${run.seasons || "-"} seasons · ${formatDate(run.created_at)}</p>
      </button>
    `;
  }).join("");
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
  els.resultPanel.classList.add("is-running");
  setStatus("Running benchmark...", "loading");
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
    state.latestResult = payload.result;
    renderDashboard(payload.dashboard);
    renderLatestResult(mode, payload.result, payload.run_id);
    setStatus(`Logged run ${payload.run_id}`, "ready");
  } catch (error) {
    setStatus(error.message, "error");
    els.resultTitle.textContent = "Run failed";
    els.resultBody.textContent = error.message;
    els.resultStats.innerHTML = "";
  } finally {
    els.runButton.disabled = false;
    els.resultPanel.classList.remove("is-running");
  }
}

function renderLatestResult(mode, result, runId) {
  const summary = summarizeResult(mode, result);
  els.resultTitle.textContent = summary.title;
  els.resultBody.textContent = summary.body;
  els.resultStats.innerHTML = summary.stats.map((item) => `
    <span><strong>${escapeHtml(item.value)}</strong>${escapeHtml(item.label)}</span>
  `).join("");
  els.resultPanel.dataset.runId = runId;
}

function summarizeResult(mode, result) {
  if (mode === "evaluate") {
    const normalized = result.normalized;
    const lift = Number(normalized.score_lift);
    const liftPct = Number(normalized.score_lift_pct);
    return {
      title: `${result.agent} ${lift >= 0 ? "beats" : "trails"} panel by ${Math.abs(lift).toFixed(3)}`,
      body: `Candidate mean ${normalized.candidate_mean_score.toFixed(3)} vs baseline panel ${normalized.baseline_panel_mean_score.toFixed(3)} across seeds ${result.seeds.join(", ")}.`,
      stats: [
        { label: "candidate", value: normalized.candidate_mean_score.toFixed(3) },
        { label: "baseline", value: normalized.baseline_panel_mean_score.toFixed(3) },
        { label: "lift", value: `${lift >= 0 ? "+" : ""}${liftPct.toFixed(2)}%` },
        { label: "illegal", value: String(normalized.candidate_illegal_actions) },
      ],
    };
  }
  if (mode === "compare") {
    const ranked = [...result].sort((a, b) => b.summary.mean_score - a.summary.mean_score);
    const winner = ranked[0];
    const runnerUp = ranked[1];
    const spread = runnerUp ? winner.summary.mean_score - runnerUp.summary.mean_score : 0;
    return {
      title: `${winner.agent} wins the comparison`,
      body: runnerUp
        ? `${winner.agent} finished ${spread.toFixed(3)} points ahead of ${runnerUp.agent} on mean score.`
        : `${winner.agent} was the only compared agent.`,
      stats: [
        { label: "mean score", value: winner.summary.mean_score.toFixed(3) },
        { label: "mean wins", value: winner.summary.mean_total_wins.toFixed(2) },
        { label: "titles", value: String(winner.summary.championships) },
        { label: "illegal", value: String(winner.summary.illegal_actions) },
      ],
    };
  }
  return {
    title: `${result.agent} mean score ${result.summary.mean_score.toFixed(3)}`,
    body: `${result.summary.mean_total_wins.toFixed(2)} average wins, ${result.summary.championships} titles, and ${result.summary.illegal_actions} rejected actions across seeds ${result.seeds.join(", ")}.`,
    stats: [
      { label: "stddev", value: result.summary.score_stddev.toFixed(3) },
      { label: "episodes", value: String(result.episodes.length) },
      { label: "seasons", value: String(result.seasons) },
      { label: "illegal", value: String(result.summary.illegal_actions) },
    ],
  };
}

function setMode(mode) {
  els.mode.value = mode;
  updateModeHelp();
  setActiveRail(mode === "compare" || mode === "evaluate" ? mode : "run-panel");
  document.querySelector("#run-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

function updateModeHelp() {
  els.modeHelp.textContent = modeHelp[els.mode.value] || modeHelp.run;
}

function setActiveRail(target) {
  document.querySelectorAll(".rail-item").forEach((button) => {
    const key = button.dataset.mode || button.dataset.jump;
    button.classList.toggle("active", key === target);
  });
}

function setStatus(message, tone) {
  els.runStatus.textContent = message;
  els.runStatus.dataset.tone = tone;
}

function runSummaryLine(run) {
  const summary = run.summary || {};
  if ("score_lift" in summary) {
    const lift = Number(summary.score_lift);
    return `lift ${lift >= 0 ? "+" : ""}${lift.toFixed(3)} · candidate ${Number(summary.candidate_mean_score).toFixed(3)}`;
  }
  if ("mean_score" in summary) {
    return `mean ${Number(summary.mean_score).toFixed(3)} · wins ${Number(summary.mean_total_wins).toFixed(2)} · illegal ${summary.illegal_actions}`;
  }
  if (Array.isArray(summary.agents)) {
    return `${summary.agents.length} agents compared`;
  }
  return "saved benchmark run";
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
  // Minimal HTML-entity escaper for the local-only GUI; this function is the sanitizer.
  // nosemgrep
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

els.runForm.addEventListener("submit", runBenchmark);
els.mode.addEventListener("change", updateModeHelp);
els.refreshButton.addEventListener("click", loadDashboard);
document.querySelectorAll("[data-mode]").forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});
document.querySelectorAll("[data-jump]").forEach((button) => {
  button.addEventListener("click", () => {
    setActiveRail(button.dataset.jump);
    document.querySelector(`#${button.dataset.jump}`).scrollIntoView({ behavior: "smooth", block: "start" });
  });
});

updateModeHelp();
loadDashboard().catch((error) => {
  setStatus(error.message, "error");
});
