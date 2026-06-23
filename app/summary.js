const params = new URLSearchParams(window.location.search);
const ticker = (params.get("ticker") || "AAPL").trim();
const market = (params.get("market") || (/^\d{6}$/.test(ticker) ? "CN" : "US")).toUpperCase();
const existingSummaryId = params.get("summary_id");
const nodes = Object.fromEntries(["summaryTitle","summarySubline","periodTypeSelect","totalScore","scoreHint","summaryStatus","summaryContent","oneLineSummary","threeMinuteText","scoreCards","keyPoints","risks","watchItems","questionLog","questionForm","questionInput","videoButton","enrichButton","disclaimer","financialLink","profileLink"].map((id) => [id, document.querySelector(`#${id}`)]));
let periodType = params.get("period_type") === "quarterly" ? "quarterly" : "annual";
let summary = null;

async function api(path, options = {}) {
  const response = await fetch(path, {headers: {"Content-Type": "application/json", ...(options.headers || {})}, ...options});
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || `请求失败：${response.status}`); }
  return response.json();
}

async function boot() {
  nodes.periodTypeSelect.value = periodType;
  nodes.financialLink.href = `./index.html?ticker=${encodeURIComponent(ticker)}&market=${market}`;
  nodes.profileLink.href = `./profile.html?query=${encodeURIComponent(ticker)}&market=${market}&document_type=auto`;
  try {
    if (existingSummaryId) {
      summary = await api(`/api/three-minute-summaries/${encodeURIComponent(existingSummaryId)}`);
      nodes.periodTypeSelect.value = summary.period_type;
      nodes.periodTypeSelect.disabled = true;
      render();
      nodes.financialLink.href = `./index.html?ticker=${encodeURIComponent(summary.company.ticker)}&market=${summary.company.market}`;
      nodes.profileLink.href = `./profile.html?query=${encodeURIComponent(summary.company.ticker)}&market=${summary.company.market}&document_type=auto`;
      return;
    }
    await createSummary(false);
  } catch (error) { nodes.summaryStatus.textContent = error.message; nodes.summaryStatus.className = "status error"; }
}

async function createSummary(allowWebEnrichment) {
    nodes.summaryStatus.textContent = allowWebEnrichment ? "正在检查可用的公开补充资料" : "正在生成三分钟总结";
    const task = await api("/api/three-minute-summaries", {method: "POST", body: JSON.stringify({ticker, market, period_type: periodType, allow_web_enrichment: allowWebEnrichment})});
    const result = await waitTask(task.task_id);
    summary = await api(`/api/three-minute-summaries/${encodeURIComponent(result.summary_id)}`);
    render();
}

async function waitTask(taskId) {
  while (true) {
    const task = await api(`/api/three-minute-summaries/tasks/${encodeURIComponent(taskId)}`);
    nodes.summaryStatus.textContent = task.current_step || "正在生成";
    if (task.status === "COMPLETED") return task;
    if (task.status === "FAILED") throw new Error(task.error?.message || "总结生成失败");
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
}

function render() {
  nodes.summaryTitle.textContent = `${summary.company.name}，3分钟看懂 ${summary.period}`;
  nodes.summarySubline.textContent = summary.status === "completed" ? (summary.external_sources?.length ? `结论以披露为主，并补充了 ${summary.external_sources.map((item) => item.source_type).join("、")} 背景资料。` : "结论由已验证财务事实与披露证据生成。") : "当前无法形成完整总结。";
  nodes.totalScore.textContent = summary.total_score ?? "--";
  nodes.scoreHint.textContent = summary.status === "completed" ? "经营理解分 / 100" : "资料或模型暂不可用";
  nodes.oneLineSummary.textContent = summary.one_line_summary;
  nodes.threeMinuteText.textContent = summary.three_minute_summary;
  nodes.scoreCards.innerHTML = (summary.score_cards || []).map((card) => `<article class="score-item"><div><span>${escapeHtml(card.dimension)}</span><strong>${card.score}<em>/${card.max_score}</em></strong></div><p>${escapeHtml(card.reason)}</p><small>${card.confidence === "high" ? "证据充分" : card.confidence === "medium" ? "证据一般" : "谨慎解读"} · ${card.evidence_block_ids.length} 条依据</small></article>`).join("") || "<p class='empty'>暂未形成可引用评分。</p>";
  nodes.keyPoints.innerHTML = renderItems(summary.key_points, "暂无重点结论。");
  nodes.risks.innerHTML = renderItems(summary.risks, "暂未形成可引用风险结论。");
  nodes.watchItems.innerHTML = (summary.watch_items || []).map((item) => `<span>${escapeHtml(item)}</span>`).join("");
  nodes.disclaimer.textContent = summary.disclaimer;
  nodes.summaryStatus.textContent = summary.generation_meta?.cache_status === "HIT" ? "已加载本地缓存总结" : "总结已生成";
  nodes.summaryContent.classList.remove("hidden");
}

function renderItems(items, empty) { return (items || []).map((item) => `<article><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.text)}</p><small>披露依据 ${item.evidence_block_ids.length} 条</small></article>`).join("") || `<p class="empty">${empty}</p>`; }
function escapeHtml(value) { const div = document.createElement("div"); div.textContent = value || ""; return div.innerHTML; }

nodes.questionForm.addEventListener("submit", async (event) => { event.preventDefault(); if (!summary || !nodes.questionInput.value.trim()) return; const question = nodes.questionInput.value.trim(); nodes.questionInput.value = ""; nodes.questionLog.insertAdjacentHTML("beforeend", `<article class="question user">${escapeHtml(question)}</article>`); try { const result = await api(`/api/three-minute-summaries/${summary.summary_id}/questions`, {method: "POST", body: JSON.stringify({question})}); nodes.questionLog.insertAdjacentHTML("beforeend", `<article class="question agent">${escapeHtml(result.answer)}<small>${result.citations?.length || 0} 条披露依据</small></article>`); } catch (error) { nodes.questionLog.insertAdjacentHTML("beforeend", `<article class="question agent">${escapeHtml(error.message)}</article>`); } });
nodes.videoButton.addEventListener("click", () => { if (summary) window.location.href = `./summary-video.html?summary_id=${encodeURIComponent(summary.summary_id)}`; });
nodes.enrichButton.addEventListener("click", async () => { try { await createSummary(true); } catch (error) { nodes.summaryStatus.textContent = error.message; nodes.summaryStatus.className = "status error"; } });
nodes.periodTypeSelect.addEventListener("change", async () => { if (existingSummaryId) return; periodType = nodes.periodTypeSelect.value; try { await createSummary(false); } catch (error) { nodes.summaryStatus.textContent = error.message; nodes.summaryStatus.className = "status error"; } });
boot();
