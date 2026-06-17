const API_BASE = "";

const fallbackCompany = {
  id: "US-AAPL",
  cik: "0000320193",
  ticker: "AAPL",
  name: "Apple Inc.",
  market: "US",
  industry: "科技",
  source: "Fallback Demo"
};

let TOP_COMPANIES = [
  { id: "US-AAPL", ticker: "AAPL", name: "Apple Inc.", market: "US", industry: "科技" },
  { id: "US-MSFT", ticker: "MSFT", name: "Microsoft", market: "US", industry: "科技" },
  { id: "US-NVDA", ticker: "NVDA", name: "NVIDIA", market: "US", industry: "科技" },
  { id: "US-GOOGL", ticker: "GOOGL", name: "Alphabet", market: "US", industry: "科技" },
  { id: "US-META", ticker: "META", name: "Meta Platforms", market: "US", industry: "科技" },
  { id: "US-BIDU", ticker: "BIDU", name: "Baidu, Inc.", market: "US", industry: "互联网" },
  { id: "US-TSLA", ticker: "TSLA", name: "Tesla", market: "US", industry: "汽车" },
  { id: "US-AMZN", ticker: "AMZN", name: "Amazon", market: "US", industry: "互联网零售" },
  { id: "US-JPM", ticker: "JPM", name: "JPMorgan Chase", market: "US", industry: "金融" },
  { id: "CN-SZSE-000001", ticker: "000001", name: "平安银行", market: "CN", industry: "金融" },
  { id: "CN-SZSE-000333", ticker: "000333", name: "美的集团", market: "CN", industry: "家电" },
  { id: "CN-SZSE-000651", ticker: "000651", name: "格力电器", market: "CN", industry: "家电" },
  { id: "CN-SSE-600519", ticker: "600519", name: "贵州茅台", market: "CN", industry: "白酒" },
  { id: "CN-SZSE-300750", ticker: "300750", name: "宁德时代", market: "CN", industry: "动力电池" },
  { id: "CN-SZSE-000858", ticker: "000858", name: "五粮液", market: "CN", industry: "白酒" },
  { id: "CN-SZSE-002594", ticker: "002594", name: "比亚迪", market: "CN", industry: "新能源汽车" },
  { id: "CN-SSE-600036", ticker: "600036", name: "招商银行", market: "CN", industry: "金融" },
  { id: "CN-SSE-601318", ticker: "601318", name: "中国平安", market: "CN", industry: "金融" },
  { id: "CN-SSE-688981", ticker: "688981", name: "中芯国际", market: "CN", industry: "半导体" }
];

const state = {
  backendReady: false,
  market: "ALL",
  launchTicker: "AAPL",
  launchMarket: "US",
  company: fallbackCompany,
  companies: [],
  periodType: "annual",
  periods: { annual: [], quarterly: [], reports: [] },
  analysis: null,
  metricDictionary: {},
  periodChangeTimer: null
};

const nodes = {};
[
  "sidebarCompanyName",
  "sidebarCompanyMeta",
  "backendStatus",
  "annualButton",
  "quarterlyButton",
  "periodSelect",
  "onlineAnalyzeButton",
  "watchButton",
  "reportPeriod",
  "companyTitle",
  "stanceBadge",
  "oneLineSummary",
  "healthScore",
  "metricsGrid",
  "sourceTag",
  "reportCard",
  "riskRadar",
  "periodCompare",
  "chatLog",
  "questionInput",
  "askButton",
  "industryAnalyzeButton",
  "industryInsight",
  "industryCompare",
  "refreshReportsButton",
  "reportList",
  "metricDictionary",
  "refreshWatchlistButton",
  "addAlertButton",
  "watchlist",
  "alertList"
].forEach((id) => {
  nodes[id] = document.querySelector(`#${id}`);
});

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
  const launch = getLaunchCompany();
  state.launchTicker = launch.ticker;
  state.launchMarket = launch.market;
  state.market = launch.market;
  bindEvents();
  renderSelectedCompany({ ticker: launch.ticker, market: launch.market, name: "正在载入公司" });
  try {
    await api("/api/health");
    state.backendReady = true;
    setStatus("后端已连接", "ok");
    await loadMetricDictionary();
    await loadCompany(launch.ticker, launch.market);
    await refreshWatchlist();
  } catch (error) {
    state.backendReady = false;
    setStatus("后端未运行，显示本地 Demo", "error");
    state.analysis = fallbackAnalysis();
    renderSelectedCompany(fallbackCompany);
    renderPeriodOptions(["2021-FY", "2022-FY", "2023-FY"]);
    render();
    resetChat();
  }
}

function bindEvents() {
  nodes.annualButton.addEventListener("click", () => setPeriodType("annual"));
  nodes.quarterlyButton.addEventListener("click", () => setPeriodType("quarterly"));
  nodes.periodSelect.addEventListener("change", scheduleAnalysis);
  nodes.onlineAnalyzeButton.addEventListener("click", analyzeOnline);
  nodes.watchButton.addEventListener("click", addCurrentToWatchlist);
  nodes.askButton.addEventListener("click", askQuestion);
  nodes.questionInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") askQuestion();
  });
  nodes.industryAnalyzeButton.addEventListener("click", analyzeIndustry);
  nodes.refreshReportsButton.addEventListener("click", refreshReports);
  nodes.refreshWatchlistButton.addEventListener("click", refreshWatchlist);
  nodes.addAlertButton.addEventListener("click", addDefaultAlert);
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => setView(tab.dataset.view));
  });
}

function setView(view) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.view === view));
  ["industry", "reports", "learning", "watchlist"].forEach((name) => {
    document.querySelector(`#${name}View`).classList.toggle("hidden", view !== name);
  });
}

function setStatus(text, type) {
  nodes.backendStatus.textContent = text;
  nodes.backendStatus.className = type === "ok" ? "status-ok" : "status-error";
}

async function searchCompany() {
  const query = state.launchTicker;
  if (!query) return;
  if (!state.backendReady) {
    state.companies = [fallbackCompany];
    renderSelectedCompany(fallbackCompany);
    return;
  }
  setStatus("搜索中", "ok");
  try {
    const data = await api(`/api/companies/search?q=${encodeURIComponent(query)}&market=${state.market}`);
    state.companies = data.items;
    const exact = data.items.find((item) => item.ticker?.toLowerCase() === query.toLowerCase());
    if (exact || data.items.length) {
      setStatus("已匹配公司，正在加载财报", "ok");
      await selectCompany(exact || data.items[0]);
      return;
    }
    setStatus("未找到公司，请返回主页确认股票代码", "error");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function selectCompany(company) {
  state.company = company;
  renderSelectedCompany(company);
  await loadPeriods(company.ticker, company.market);
  await refreshReports();
  await analyzeOnline();
}

async function loadCompany(ticker, market) {
  state.launchTicker = ticker;
  state.launchMarket = market;
  state.market = market;
  await searchCompany();
}

async function loadPeriods(ticker, market) {
  if (!state.backendReady) return;
  setStatus("获取报告期", "ok");
  try {
    const data = await api(`/api/reports/options?ticker=${encodeURIComponent(ticker)}&market=${market || "US"}`);
    state.company = data.company;
    state.periods = data.periods;
    renderPeriodOptions(state.periods[state.periodType] || []);
    renderReports(state.periods.reports || []);
    setStatus("报告期已加载", "ok");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function analyzeOnline() {
  if (!state.backendReady) {
    state.analysis = fallbackAnalysis();
    render();
    return;
  }
  const selected = Array.from(nodes.periodSelect.selectedOptions).map((option) => option.value);
  const originalButtonText = nodes.onlineAnalyzeButton.textContent;
  setStatus("联网分析中，首次解析巨潮 PDF 可能需要几十秒", "ok");
  nodes.onlineAnalyzeButton.textContent = "解析中...";
  nodes.onlineAnalyzeButton.disabled = true;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 120000);
  try {
    const data = await api("/api/analysis/report-card", {
      method: "POST",
      signal: controller.signal,
      body: JSON.stringify({
        ticker: state.company.ticker || state.launchTicker,
        market: state.company.market || "US",
        period_type: state.periodType,
        periods: selected
      })
    });
    state.analysis = data;
    state.company = data.company;
    setStatus("分析完成", "ok");
    render();
    resetChat();
  } catch (error) {
    const message = error.name === "AbortError"
      ? "解析超时，请减少选择的报告期或稍后重试"
      : error.message;
    setStatus(message, "error");
  } finally {
    window.clearTimeout(timeout);
    nodes.onlineAnalyzeButton.textContent = originalButtonText;
    nodes.onlineAnalyzeButton.disabled = false;
  }
}

async function analyzeIndustry() {
  if (!state.backendReady) return;
  nodes.industryInsight.textContent = "正在生成行业对比...";
  try {
    const data = await api("/api/analysis/industry-comparison", {
      method: "POST",
      body: JSON.stringify({
        ticker: state.company.ticker,
        market: state.company.market || "US",
        period: state.analysis?.latest_period
      })
    });
    nodes.industryInsight.textContent = data.insight;
    renderIndustryTable(data.rows || []);
  } catch (error) {
    nodes.industryInsight.textContent = error.message;
  }
}

async function refreshReports() {
  if (!state.backendReady) return;
  try {
    const data = await api(`/api/reports/list?ticker=${encodeURIComponent(state.company.ticker)}&market=${state.company.market || "US"}`);
    renderReports(data.reports || []);
  } catch (error) {
    nodes.reportList.innerHTML = `<div class="source-item"><strong>资料列表暂不可用</strong><p>${error.message}</p></div>`;
  }
}

async function loadMetricDictionary() {
  if (!state.backendReady) return;
  const data = await api("/api/metrics/dictionary");
  state.metricDictionary = data.items;
  renderMetricDictionary();
}

async function addCurrentToWatchlist() {
  if (!state.backendReady) return;
  try {
    await api("/api/watchlists", {
      method: "POST",
      body: JSON.stringify({ company: state.company })
    });
    setStatus("已加入自选", "ok");
    await refreshWatchlist();
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function refreshWatchlist() {
  if (!state.backendReady) return;
  const data = await api("/api/watchlists");
  nodes.watchlist.innerHTML = (data.items || [])
    .map((item) => {
      const company = item.company;
      return `
        <div class="source-item">
          <strong>${company.name} (${company.ticker})</strong>
          <small>${company.market} · ${company.industry || "待识别行业"}</small>
        </div>
      `;
    })
    .join("") || '<div class="source-item"><strong>暂无自选</strong><p>可将当前公司加入自选，后续用于财报更新和风险变化提醒。</p></div>';
  const alerts = await api("/api/watchlists/alerts");
  nodes.alertList.innerHTML = (alerts.items || [])
    .map(
      (item) => `
        <div class="source-item">
          <strong>提醒：${item.metric}</strong>
          <small>${item.company_id} · ${item.condition} ${item.threshold ?? ""}</small>
        </div>
      `
    )
    .join("");
}

async function addDefaultAlert() {
  if (!state.backendReady || !state.company) return;
  try {
    await api("/api/watchlists/alerts", {
      method: "POST",
      body: JSON.stringify({
        company_id: state.company.id,
        metric: "风险雷达",
        condition: "出现黄色或红色风险时提醒",
        threshold: null
      })
    });
    setStatus("提醒已创建", "ok");
    await refreshWatchlist();
  } catch (error) {
    setStatus(error.message, "error");
  }
}

function renderPeriodOptions(periods) {
  const selected = periods.slice(0, Math.min(4, periods.length));
  nodes.periodSelect.innerHTML = periods
    .map((period) => `<option value="${period}" ${selected.includes(period) ? "selected" : ""}>${period}</option>`)
    .join("");
}

function setPeriodType(type) {
  state.periodType = type;
  nodes.annualButton.classList.toggle("active", type === "annual");
  nodes.quarterlyButton.classList.toggle("active", type === "quarterly");
  renderPeriodOptions(state.periods[type] || []);
  scheduleAnalysis();
}

function scheduleAnalysis() {
  window.clearTimeout(state.periodChangeTimer);
  state.periodChangeTimer = window.setTimeout(() => {
    analyzeOnline();
  }, 350);
}

function render() {
  const analysis = state.analysis || fallbackAnalysis();
  const company = state.company || analysis.company;
  nodes.reportPeriod.textContent = analysis.latest_period || "多期分析";
  nodes.companyTitle.textContent = `${company.name} ${company.ticker ? `(${company.ticker})` : ""}`;
  nodes.oneLineSummary.textContent = analysis.summary;
  nodes.healthScore.textContent = analysis.score;
  nodes.sourceTag.textContent = company.source || "财报数据";
  renderStance(analysis.stance);
  renderMetrics(analysis.metrics || {});
  renderReportCard(company, analysis);
  renderRisks(analysis.risks || []);
  renderComparison(analysis.comparison?.rows || []);
}

function renderStance(stance) {
  const labels = { positive: "偏积极", neutral: "中性", cautious: "偏谨慎" };
  nodes.stanceBadge.className = `stance-badge ${stance || "neutral"}`;
  nodes.stanceBadge.textContent = labels[stance] || "中性";
}

function renderMetrics(metrics) {
  const visible = ["revenue", "net_profit", "gross_margin", "operating_cashflow", "receivables", "inventory", "net_margin", "debt_ratio"];
  nodes.metricsGrid.innerHTML = visible
    .map((key) => {
      const metric = metrics[key] || { label: labelForMetric(key), display: "待补充", yoy: null };
      return `
        <article class="metric-card" data-metric="${key}">
          <span>${metric.label || labelForMetric(key)}</span>
          <strong>${metric.display || "待补充"}</strong>
          <small>${metric.yoy === null || metric.yoy === undefined ? "同比待补充" : `同比${pctText(metric.yoy)}`}</small>
        </article>
      `;
    })
    .join("");
  nodes.metricsGrid.querySelectorAll("[data-metric]").forEach((card) => {
    card.addEventListener("click", () => explainMetricInChat(card.dataset.metric));
  });
}

function renderReportCard(company, analysis) {
  const sources = analysis.sources || [];
  const sourceText = sources.length
    ? sources.map((item) => item.url
      ? `<a href="${item.url}" target="_blank" rel="noreferrer">${item.form} ${item.filing_date || ""}</a>`
      : `${item.form} ${item.filing_date || ""}`
    ).join(" · ")
    : "当前分析来自结构化财务数据或 Demo 数据。";
  const factOpinion = analysis.fact_opinion || { facts: [], inferences: [] };
  const rows = [
    ["公司靠什么赚钱", analysis.business_model || "待补充业务模式文本。"],
    ["本期表现", analysis.summary],
    ["最大亮点", (analysis.highlights || []).join(" ")],
    ["最大风险", (analysis.risks || []).filter((risk) => risk.level !== "green").map((risk) => risk.reason).join(" ") || "暂未识别到突出风险。"],
    ["事实依据", (factOpinion.facts || []).join("；") || "待补充"],
    ["后续关注", (analysis.watch_metrics || []).join("、") || "收入、利润、现金流"],
    ["信息来源", sourceText]
  ];
  nodes.reportCard.innerHTML = rows
    .map(([label, value]) => `<div class="card-row"><strong>${label}</strong><div>${value}</div></div>`)
    .join("");
}

function renderRisks(risks) {
  nodes.riskRadar.innerHTML = risks
    .map(
      (risk) => `
        <div class="risk-item ${risk.level}">
          <span class="risk-dot"></span>
          <div>
            <h3>${risk.name}</h3>
            <p>${risk.reason}</p>
          </div>
        </div>
      `
    )
    .join("");
}

function renderComparison(rows) {
  if (!rows.length) {
    nodes.periodCompare.innerHTML = "请选择多个年份或季度后点击联网分析。";
    return;
  }
  nodes.periodCompare.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>报告期</th><th>收入</th><th>收入同比</th><th>净利润</th><th>净利同比</th>
          <th>毛利率</th><th>净利率</th><th>ROE</th><th>经营现金流</th><th>负债率</th>
        </tr>
      </thead>
      <tbody>
        ${rows
          .map(
            (row) => `
              <tr>
                <td>${row.period}</td><td>${row.revenue}</td>
                <td>${valueOrPct(row.revenue_yoy)}</td><td>${row.net_profit}</td>
                <td>${valueOrPct(row.net_profit_yoy)}</td><td>${row.gross_margin}</td>
                <td>${row.net_margin || "待补充"}</td><td>${row.roe || "待补充"}</td>
                <td>${row.operating_cashflow}</td><td>${row.debt_ratio}</td>
              </tr>
            `
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderIndustryTable(rows) {
  if (!rows.length) {
    nodes.industryCompare.innerHTML = "暂无同行样本。";
    return;
  }
  nodes.industryCompare.innerHTML = `
    <table>
      <thead><tr><th>公司</th><th>报告期</th><th>收入</th><th>收入同比</th><th>净利润</th><th>毛利率</th><th>ROE</th><th>负债率</th></tr></thead>
      <tbody>
        ${rows
          .map(
            (row) => `
              <tr>
                <td>${row.name}</td><td>${row.period}</td><td>${row.revenue}</td><td>${valueOrPct(row.revenue_yoy)}</td>
                <td>${row.net_profit}</td><td>${row.gross_margin ?? "待补充"}%</td><td>${row.roe ?? "待补充"}%</td><td>${row.debt_ratio ?? "待补充"}%</td>
              </tr>
            `
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderReports(reports) {
  nodes.reportList.innerHTML = (reports || [])
    .slice(0, 24)
    .map(
      (report) => `
        <div class="source-item">
          <strong>${report.period} · ${report.report_type}</strong>
          <small>${report.parse_status || "pending"} ${report.publish_date || ""}</small>
          <p>${report.source_url ? `<a href="${report.source_url}" target="_blank" rel="noreferrer">查看来源</a>` : "来源链接待补充或来自结构化接口。"}</p>
        </div>
      `
    )
    .join("") || '<div class="source-item"><strong>暂无报告列表</strong><p>可先通过联网分析生成资料来源。</p></div>';
}

function renderMetricDictionary() {
  const entries = Object.entries(state.metricDictionary || {});
  nodes.metricDictionary.innerHTML = entries
    .map(
      ([key, item]) => `
        <div class="dictionary-card" data-metric="${key}">
          <h3>${item.name}</h3>
          <p>${item.plain}</p>
        </div>
      `
    )
    .join("");
}

async function explainMetricInChat(metricKey) {
  const meta = state.metricDictionary[metricKey] || { name: labelForMetric(metricKey), plain: "暂无解释。", how_to_read: "" };
  appendMessage(`解释一下${meta.name}`, "user");
  appendMessage(`先说结论：${meta.name}是${meta.plain}${meta.how_to_read ? ` 怎么看：${meta.how_to_read}` : ""}<small>依据：指标解释库。本内容仅用于财报理解，不构成投资建议。</small>`, "agent");
}

async function askQuestion() {
  const question = nodes.questionInput.value.trim();
  if (!question) return;
  appendMessage(question, "user");
  nodes.questionInput.value = "";
  if (!state.backendReady) {
    appendMessage(`${state.analysis?.summary || ""}<small>本内容仅用于财报理解，不构成投资建议。</small>`, "agent");
    return;
  }
  try {
    const data = await api("/api/qa", {
      method: "POST",
      body: JSON.stringify({ question, analysis: state.analysis })
    });
    const citations = (data.citations || []).map((item) => item.title).join("、");
    appendMessage(`${data.answer}<small>依据：${citations || "当前分析结果"}。${data.disclaimer}</small>`, "agent");
  } catch (error) {
    appendMessage(`问答服务暂时不可用：${error.message}`, "agent");
  }
}

function resetChat() {
  nodes.chatLog.innerHTML = "";
  appendMessage("我已经准备好。你可以问：现金流怎么样、风险在哪里、行业里强不强、毛利率是什么意思。", "agent");
}

function appendMessage(content, role) {
  const item = document.createElement("div");
  item.className = `message ${role}`;
  item.innerHTML = content;
  nodes.chatLog.appendChild(item);
  nodes.chatLog.scrollTop = nodes.chatLog.scrollHeight;
}

function fallbackAnalysis() {
  return {
    company: fallbackCompany,
    period_type: "annual",
    latest_period: "2023-FY",
    selected_periods: ["2021-FY", "2022-FY", "2023-FY"],
    score: 82,
    stance: "positive",
    summary: "Apple Inc. 在 2023-FY 收入和利润保持较大规模，经营现金流为正，但仍需要关注增长放缓和产品周期变化。",
    business_model: "公司主要通过硬件产品、服务订阅和生态系统变现。",
    highlights: ["经营现金流为正，利润质量较好。"],
    watch_metrics: ["营业收入", "净利润", "经营现金流", "毛利率"],
    metrics: {
      revenue: { label: "营业收入", display: "383.29B USD", yoy: -2.8 },
      net_profit: { label: "净利润", display: "97.00B USD", yoy: -2.8 },
      gross_margin: { label: "毛利率", display: "44.1%" },
      operating_cashflow: { label: "经营现金流", display: "110.54B USD" },
      receivables: { label: "应收账款", display: "待补充", yoy: null },
      inventory: { label: "存货", display: "待补充", yoy: null },
      net_margin: { label: "净利率", display: "25.3%" },
      debt_ratio: { label: "资产负债率", display: "82.4%" }
    },
    risks: [{ name: "收入增长", level: "yellow", reason: "收入同比下降，增长动能需要观察。" }],
    comparison: { rows: [] },
    sources: [],
    rag_chunks: [],
    disclaimer: "本内容仅用于财报信息理解和研究辅助，不构成任何投资建议。"
  };
}

function valueOrPct(value) {
  return value === null || value === undefined ? "待补充" : pctText(value);
}

function pctText(value) {
  return `${value >= 0 ? "增长" : "下降"}${Math.abs(value)}%`;
}

function labelForMetric(key) {
  return {
    revenue: "营业收入",
    net_profit: "净利润",
    gross_margin: "毛利率",
    operating_cashflow: "经营现金流",
    receivables: "应收账款",
    inventory: "存货",
    net_margin: "净利率",
    debt_ratio: "资产负债率"
  }[key] || key;
}

function getLaunchCompany() {
  const params = new URLSearchParams(window.location.search);
  const ticker = (params.get("ticker") || "AAPL").trim();
  const market = (params.get("market") || inferMarket(ticker)).trim().toUpperCase();
  return { ticker, market: market === "A" ? "CN" : market };
}

function inferMarket(ticker) {
  return /^\d{6}$/.test(ticker) ? "CN" : "US";
}

function renderSelectedCompany(company) {
  nodes.sidebarCompanyName.textContent = company.name || company.ticker || "等待载入";
  nodes.sidebarCompanyMeta.textContent = `${company.ticker || state.launchTicker} · ${company.market || state.launchMarket} · ${company.industry || "待识别行业"}`;
}

boot();
