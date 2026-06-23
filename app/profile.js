const API_BASE = "";

const nodes = {
  sourceEyebrow: document.querySelector("#sourceEyebrow"),
  profileTitle: document.querySelector("#profileTitle"),
  profileSubtitle: document.querySelector("#profileSubtitle"),
  sourceCard: document.querySelector("#sourceCard"),
  taskPanel: document.querySelector("#taskPanel"),
  progressBar: document.querySelector("#progressBar"),
  taskStatus: document.querySelector("#taskStatus"),
  taskStep: document.querySelector("#taskStep"),
  reportLayout: document.querySelector("#reportLayout"),
  reportSections: document.querySelector("#reportSections"),
  financeTopButton: document.querySelector("#financeTopButton"),
  financeButton: document.querySelector("#financeButton"),
  suggestedQuestions: document.querySelector("#suggestedQuestions"),
  questionInput: document.querySelector("#questionInput"),
  askButton: document.querySelector("#askButton"),
  answerBox: document.querySelector("#answerBox"),
  evidenceDrawer: document.querySelector("#evidenceDrawer"),
  closeEvidenceButton: document.querySelector("#closeEvidenceButton"),
  evidenceBody: document.querySelector("#evidenceBody")
};

const state = {
  task: null,
  report: null
};

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `请求失败：${response.status}`);
  }
  return response.json();
}

async function boot() {
  bindEvents();
  const params = new URLSearchParams(window.location.search);
  const query = (params.get("query") || params.get("ticker") || "").trim();
  const market = (params.get("market") || inferMarket(query)).toUpperCase();
  const documentType = params.get("document_type") || "auto";
  if (!query) {
    setTask({ status: "FAILED_COMPANY_NOT_FOUND", progress: 0, current_step: "请从主页输入公司名或股票代码进入公司画像。" });
    return;
  }
  nodes.profileTitle.textContent = `正在生成 ${query} 的公司画像`;
  try {
    const task = await api("/api/company-profile/reports", {
      method: "POST",
      body: JSON.stringify({ query, market, document_type: documentType, report_style: "plain" })
    });
    state.task = task;
    setTask(task);
    await waitForTask(task.task_id);
  } catch (error) {
    showError(error.message);
  }
}

async function waitForTask(taskId) {
  for (let attempt = 0; attempt < 180; attempt += 1) {
    const task = await api(`/api/company-profile/tasks/${taskId}`);
    state.task = task;
    setTask(task);
    if (task.status === "COMPLETED") {
      await loadReport(task.report_id);
      return;
    }
    if (task.error || task.status === "FAILED_REPORT_GENERATION") {
      showError(task.error?.message || "公司画像生成失败");
      return;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
  }
  showError("生成时间较长，请稍后刷新页面查看任务结果。");
}

function bindEvents() {
  nodes.closeEvidenceButton.addEventListener("click", closeEvidence);
  nodes.financeButton.addEventListener("click", goFinance);
  nodes.financeTopButton.addEventListener("click", goFinance);
  nodes.askButton.addEventListener("click", askQuestion);
  nodes.questionInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") askQuestion();
  });
}

function setTask(task) {
  nodes.progressBar.style.width = `${task.progress || 0}%`;
  nodes.taskStatus.textContent = statusText(task.status);
  nodes.taskStep.textContent = task.current_step || "";
  if (task.error) {
    nodes.taskStep.textContent = task.error.message;
    nodes.taskStep.classList.add("error");
  }
}

async function loadReport(reportId) {
  const report = await api(`/api/company-profile/reports/${reportId}`);
  state.report = report;
  renderReport(report);
}

function renderReport(report) {
  const company = report.company;
  const documentMeta = report.source_document;
  nodes.sourceEyebrow.textContent = `${company.stock_code} · ${company.market} · ${company.exchange || "交易所待识别"}`;
  nodes.profileTitle.textContent = report.title;
  nodes.profileSubtitle.textContent = report.disclaimer;
  nodes.sourceCard.innerHTML = `
    <div><span>资料类型</span><strong>${escapeHtml(documentTypeLabel(documentMeta.document_type))}</strong></div>
    <div><span>使用资料</span><strong>${escapeHtml(documentMeta.document_title)}</strong></div>
    <div><span>报告期</span><strong>${escapeHtml(documentMeta.report_period)}</strong></div>
    <div><span>披露日期</span><strong>${escapeHtml(documentMeta.disclosure_date || "待识别")}</strong></div>
    <div><span>来源</span><a href="${safeUrl(documentMeta.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(documentMeta.source_platform)}</a></div>
  `;
  nodes.reportLayout.classList.remove("hidden");
  nodes.reportSections.innerHTML = report.sections.map(renderSection).join("");
  nodes.reportSections.querySelectorAll("[data-evidence]").forEach((button) => {
    button.addEventListener("click", () => openEvidence(button.dataset.evidence));
  });
  nodes.suggestedQuestions.innerHTML = (report.suggested_questions || [])
    .map((question) => `<button type="button" data-question="${escapeAttr(question)}">${question}</button>`)
    .join("");
  nodes.suggestedQuestions.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      nodes.questionInput.value = button.dataset.question;
      askQuestion();
    });
  });
}

function renderSection(section) {
  return `
    <article class="section-card">
      <h2>${section.title}</h2>
      ${section.content_blocks.map(renderBlock).join("")}
      ${renderEvidenceButtons(section.evidence_refs || [])}
    </article>
  `;
}

function renderBlock(block) {
  if (block.type === "paragraph" || block.type === "notice") {
    return `<p>${escapeHtml(block.text)}</p>`;
  }
  if (block.type === "kv") {
    return `<div class="kv-grid">${Object.entries(block.items || {})
      .filter(([, value]) => typeof value !== "object")
      .map(([key, value]) => `<div class="kv-item"><span>${escapeHtml(label(key))}</span><strong>${escapeHtml(value || "文件未披露")}</strong></div>`)
      .join("")}</div>`;
  }
  if (block.type === "table") {
    const rows = block.rows || [];
    return rows.length ? `
      <table class="plain-table">
        <thead><tr><th>业务板块</th><th>核心产品 / 服务</th><th>普通人解释</th></tr></thead>
        <tbody>${rows.map((row) => `<tr><td>${escapeHtml(row.name || "主营业务")}</td><td>${escapeHtml((row.core_products_or_services || []).join("、") || "待识别")}</td><td>${escapeHtml(row.plain_explanation || "")}</td></tr>`).join("")}</tbody>
      </table>
    ` : "";
  }
  if (block.type === "cards") {
    return `<div class="people-grid">${(block.items || []).map((item) => `
      <div class="person-card"><strong>${escapeHtml(item.name)}</strong><p>${escapeHtml(item.role || "")}</p><p>${escapeHtml(item.importance_reason || item.background || "")}</p></div>
    `).join("")}</div>`;
  }
  if (block.type === "risk_cards") {
    return `<div class="risk-grid">${(block.items || []).map((item) => `
      <div class="risk-card"><strong>${escapeHtml(item.risk_name)}</strong><p>严重程度：${escapeHtml(severityText(item.severity))}</p><p>${escapeHtml(item.plain_explanation)}</p></div>
    `).join("")}</div>`;
  }
  if (block.type === "risk_facts") {
    if (!block.items?.length) return `<p>未从披露文件中提取到可核验的风险事实。</p>`;
    return `<div class="risk-grid">${block.items.map((item) => `<div class="risk-card"><strong>${escapeHtml(item.risk_name)}</strong><p>${escapeHtml(item.description)}</p><p>趋势：${escapeHtml(item.trend)}</p></div>`).join("")}</div>`;
  }
  if (block.type === "risk_assessments") {
    if (!block.items?.length) return `<p>暂无可评估的需关注程度。</p>`;
    return `<div class="risk-grid">${block.items.map((item) => `<div class="risk-card"><strong>${escapeHtml(item.risk_category)} · 需关注程度：${escapeHtml(severityText(item.attention_level))}</strong><p>${escapeHtml(item.assessment_reason)}</p><p>${escapeHtml((item.uncertainties || []).join("；"))}</p></div>`).join("")}</div>`;
  }
  if (block.type === "questions") {
    return `<ul>${(block.items || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
  }
  return "";
}

function renderEvidenceButtons(refs) {
  if (!refs.length) return "";
  return `<div class="evidence-buttons">${refs.slice(0, 4).map((id) => `<button type="button" data-evidence="${escapeAttr(id)}">查看依据</button>`).join("")}</div>`;
}

async function openEvidence(evidenceId) {
  try {
    const evidence = await api(`/api/company-profile/evidence/${evidenceId}`);
    nodes.evidenceBody.innerHTML = `
      <div><strong>结论</strong><p>${escapeHtml(evidence.claim)}</p></div>
      <div><strong>来源文件</strong><p>${escapeHtml(evidence.source.document_title)}</p></div>
      <div><strong>位置</strong><p>第 ${escapeHtml(evidence.location.page)} 页 · ${escapeHtml(evidence.location.section_title || "相关章节")}</p></div>
      <div><strong>原文片段</strong><p>${escapeHtml(evidence.original_text)}</p></div>
      <div><strong>置信度</strong><p>${escapeHtml(evidence.confidence)}</p></div>
    `;
    nodes.evidenceDrawer.classList.add("open");
    nodes.evidenceDrawer.setAttribute("aria-hidden", "false");
  } catch (error) {
    nodes.evidenceBody.textContent = error.message;
    nodes.evidenceDrawer.classList.add("open");
  }
}

function closeEvidence() {
  nodes.evidenceDrawer.classList.remove("open");
  nodes.evidenceDrawer.setAttribute("aria-hidden", "true");
}

async function askQuestion() {
  const question = nodes.questionInput.value.trim();
  if (!question || !state.report) return;
  nodes.answerBox.textContent = "正在回答...";
  try {
    const data = await api(`/api/company-profile/reports/${state.report.report_id}/qa`, {
      method: "POST",
      body: JSON.stringify({ question })
    });
    nodes.answerBox.innerHTML = `
      <p>${escapeHtml(data.answer)}</p>
      ${data.answer_type === "finance_handoff" ? '<button type="button" id="inlineFinanceButton">进入财报掘金</button>' : ""}
    `;
    const inline = document.querySelector("#inlineFinanceButton");
    if (inline) inline.addEventListener("click", goFinance);
  } catch (error) {
    nodes.answerBox.textContent = error.message;
  }
}

function goFinance() {
  if (!state.report) {
    window.location.href = "./index.html";
    return;
  }
  const entry = state.report.finance_agent_entry;
  window.location.href = entry?.target_url || `./index.html?ticker=${state.report.company.stock_code}&market=CN`;
}

function showError(message) {
  setTask({ status: "FAILED_REPORT_GENERATION", progress: 100, current_step: message });
  nodes.profileTitle.textContent = "公司画像生成失败";
  nodes.profileSubtitle.textContent = message;
}

function inferMarket(query) {
  return /^\d{6}$/.test(query) ? "CN" : "auto";
}

function statusText(status) {
  return {
    RESOLVING_COMPANY: "识别公司",
    RETRIEVING_DOCUMENT: "检索披露文件",
    PARSING_DOCUMENT: "解析文件",
    EXTRACTING_INFORMATION: "抽取画像",
    COMPLETED: "已完成",
    FAILED_REPORT_GENERATION: "生成失败"
  }[status] || status || "处理中";
}

function severityText(value) {
  return { high: "高", medium: "中", low: "低" }[value] || "未知";
}

function documentTypeLabel(value) {
  return {
    annual_report: "年度报告",
    prospectus: "招股说明书"
  }[value] || value || "公开披露文件";
}

function label(key) {
  return {
    full_name: "公司全称",
    short_name: "公司简称",
    stock_code: "股票代码",
    market: "上市地",
    exchange: "交易所",
    industry: "所属行业",
    main_business: "主营业务",
    controlling_shareholder: "控股股东",
    actual_controller: "实际控制人",
    control_type: "控制权类型",
    plain_explanation: "普通人解释",
    business_concentration_note: "业务集中说明",
    company_position: "公司位置",
    bargaining_power_note: "议价说明",
    risk_note: "风险提示",
    summary: "总结"
  }[key] || key;
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
}

function safeUrl(value) {
  try {
    const url = new URL(value, window.location.origin);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "#";
  } catch (_) {
    return "#";
  }
}

boot();
