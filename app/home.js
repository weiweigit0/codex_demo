const AUTH_TOKEN_KEY = "financial_mining_token";
const AUTH_USER_KEY = "financial_mining_user";
const API_BASE = window.location.protocol === "file:" ? "http://localhost:8765" : "";
const PAGE_BASE = window.location.protocol === "file:" ? "http://localhost:8765" : "";
const UI = window.FinancialMiningUI || {};

const userLabel = document.querySelector("#userLabel");
const tickerInput = document.querySelector("#homeTickerInput");
const analyzeButton = document.querySelector("#homeAnalyzeButton");
const searchMessage = document.querySelector("#homeSearchMessage");
const hotCompaniesNode = document.querySelector("#homeHotCompanies");
const snapshotContent = document.querySelector("#snapshotContent");
const moreHotButton = document.querySelector("#moreHotButton");

const fallbackHotCompanies = [
  { ticker: "AAPL", name: "Apple Inc.", market: "US", industry: "消费电子", price: "可分析", change: "" },
  { ticker: "600519", name: "贵州茅台", market: "CN", industry: "食品饮料", price: "可分析", change: "" },
  { ticker: "300750", name: "宁德时代", market: "CN", industry: "电力设备", price: "可分析", change: "" }
];

function boot() {
  loadCurrentUser();
  bindEvents();
  renderHotCompanies(fallbackHotCompanies);
  loadHotCompanies();
  loadFinancialSnapshot();
}

async function loadCurrentUser() {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  if (!token) {
    enterDemoMode();
    return;
  }
  try {
    const response = await fetch(`${API_BASE}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!response.ok) {
      enterDemoMode();
      return;
    }
    const data = await response.json();
    userLabel.textContent = data.user?.username || "演示模式";
  } catch (error) {
    enterDemoMode();
  }
}

function enterDemoMode() {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(AUTH_USER_KEY);
  userLabel.textContent = "演示模式";
}

function bindEvents() {
  analyzeButton.addEventListener("click", startFinancialAnalysis);
  tickerInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") startFinancialAnalysis();
  });
  moreHotButton.addEventListener("click", () => {
    window.location.href = `${PAGE_BASE}/support.html?source=home_hot`;
  });
  document.querySelectorAll("[data-scroll-target]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelector(`#${button.dataset.scrollTarget}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
  document.querySelector("[data-nav-action='financial']")?.addEventListener("click", () => {
    if (tickerInput.value.trim()) {
      startFinancialAnalysis();
      return;
    }
    focusSearch("请输入股票代码或公司名后开始财报洞察。");
  });
}

function startFinancialAnalysis() {
  const raw = tickerInput.value.trim();
  if (!raw) {
    focusSearch("请输入股票代码或公司名。");
    return;
  }
  const market = inferMarket(raw);
  window.location.href = toFinancialUrl(raw, market);
}

function focusSearch(message) {
  searchMessage.textContent = message;
  searchMessage.classList.add("error");
  tickerInput.focus();
  tickerInput.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function loadHotCompanies() {
  try {
    const response = await fetch(`${API_BASE}/api/companies/top?market=ALL`);
    if (!response.ok) throw new Error("top companies unavailable");
    const data = await response.json();
    const items = normalizeHotCompanies(data.items || []);
    renderHotCompanies(items.length ? items.slice(0, 3) : fallbackHotCompanies);
  } catch (error) {
    renderHotCompanies(fallbackHotCompanies);
  }
}

function normalizeHotCompanies(items) {
  const preferred = ["AAPL", "600519", "300750", "NVDA", "BIDU", "000001"];
  const ranked = [...items].sort((a, b) => {
    const ai = preferred.indexOf(a.ticker);
    const bi = preferred.indexOf(b.ticker);
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });
  return ranked.map((item) => ({
    ticker: item.ticker,
    name: item.name || item.short_name || item.ticker,
    market: item.market || inferMarket(item.ticker),
    industry: item.industry || "待识别行业",
    price: "可分析",
    change: ""
  }));
}

function renderHotCompanies(items) {
  hotCompaniesNode.innerHTML = items.slice(0, 3).map((item) => `
    <article class="hot-company-card" data-ticker="${escapeHtml(item.ticker)}" data-market="${escapeHtml(item.market)}">
      <div class="company-avatar">${escapeHtml(avatarText(item.name))}</div>
      <div>
        <h3>${escapeHtml(item.name)}</h3>
        <p>${escapeHtml(item.ticker)} · ${escapeHtml(marketLabel(item.market))} · ${escapeHtml(item.industry)}</p>
      </div>
      <div class="hot-card-meta">
        <strong>${escapeHtml(item.price || "可分析")}</strong>
        ${item.change ? `<span class="${String(item.change).includes("-") ? "down" : ""}">${escapeHtml(item.change)}</span>` : ""}
      </div>
      <button type="button">查看分析 →</button>
    </article>
  `).join("");
  hotCompaniesNode.querySelectorAll(".hot-company-card").forEach((card) => {
    card.addEventListener("click", () => {
      window.location.href = toFinancialUrl(card.dataset.ticker, card.dataset.market);
    });
  });
}

async function loadFinancialSnapshot() {
  renderSnapshotLoading();
  try {
    const response = await fetch(`${API_BASE}/api/home/financial-snapshot?market=US`);
    if (!response.ok) throw new Error("snapshot unavailable");
    const snapshot = await response.json();
    renderInsightPreview(snapshot, Boolean(snapshot.is_demo));
  } catch (error) {
    renderInsightPreview(fallbackSnapshot(), true);
  }
}

function renderSnapshotLoading() {
  snapshotContent.className = "insight-preview-content loading";
  snapshotContent.innerHTML = `
    <p class="snapshot-eyebrow">财报洞察</p>
    <h2>正在读取一家公司的财报摘要...</h2>
    <div class="snapshot-skeleton"></div>
  `;
}

function renderInsightPreview(snapshot, isFallback) {
  const company = snapshot.company || {};
  const metrics = normalizeSnapshotMetrics(snapshot.metrics || []);
  const targetUrl = snapshot.target_url || toFinancialUrl(company.ticker || "AAPL", company.market || "US");
  const watchUrl = appendIntent(targetUrl, "watch");
  snapshotContent.className = `insight-preview-content${isFallback ? " fallback" : ""}`;
  snapshotContent.innerHTML = `
    <div class="insight-preview-head">
      <div>
        <p class="snapshot-eyebrow">财报洞察</p>
        <h2>${escapeHtml(company.name || "Apple Inc.")}</h2>
        <span>${escapeHtml(company.ticker || "AAPL")} · ${escapeHtml(marketLabel(company.market))} · ${escapeHtml(company.industry || "待识别行业")} · ${escapeHtml(snapshot.period || "最近报告期")}</span>
      </div>
      <button type="button" data-watch-company>☆ 关注</button>
    </div>
    <div class="preview-metrics">
      ${metrics.map((item) => `
        <article>
          <span>${escapeHtml(item.label)}</span>
          <strong>${escapeHtml(item.value)}</strong>
          <small class="${String(item.change || "").includes("-") ? "down" : ""}">${escapeHtml(item.change || "同比待补充")}</small>
        </article>
      `).join("")}
    </div>
    <button class="preview-report-link" type="button" data-open-report>查看完整报告 →</button>
  `;
  snapshotContent.querySelector("[data-open-report]")?.addEventListener("click", () => {
    window.location.href = targetUrl.startsWith("/") ? `${PAGE_BASE}${targetUrl}` : targetUrl;
  });
  snapshotContent.querySelector("[data-watch-company]")?.addEventListener("click", () => {
    window.location.href = watchUrl.startsWith("/") ? `${PAGE_BASE}${watchUrl}` : watchUrl;
  });
}

function normalizeSnapshotMetrics(metrics) {
  const preferred = ["revenue", "net_profit", "gross_margin", "operating_cashflow"];
  const byKey = new Map(metrics.map((item) => [item.key, item]));
  const fallback = {
    revenue: { label: "营业收入", value: "待补充", change: "同比待补充" },
    net_profit: { label: "净利润", value: "待补充", change: "同比待补充" },
    gross_margin: { label: "毛利率", value: "待补充", change: "同比待补充" },
    operating_cashflow: { label: "经营现金流", value: "待补充", change: "同比待补充" }
  };
  return preferred.map((key) => {
    const item = byKey.get(key) || fallback[key];
    return {
      label: item.label || fallback[key].label,
      value: item.value || "待补充",
      change: item.change || "同比待补充"
    };
  });
}

function fallbackSnapshot() {
  return {
    company: { ticker: "AAPL", name: "Apple Inc.", market: "US", industry: "消费电子" },
    period: "2025-FY",
    is_demo: true,
    metrics: [
      { key: "revenue", label: "营业收入", value: "416.16B USD", change: "同比 +6.43%" },
      { key: "net_profit", label: "净利润", value: "112.01B USD", change: "同比 +19.5%" },
      { key: "gross_margin", label: "毛利率", value: "46.91%", change: "同比待补充" },
      { key: "operating_cashflow", label: "经营现金流", value: "111.48B USD", change: "同比 -5.73%" }
    ],
    target_url: "/index.html?ticker=AAPL&market=US"
  };
}

function appendIntent(url, intent) {
  const absolute = url.startsWith("http") ? new URL(url) : new URL(url, window.location.origin);
  absolute.searchParams.set("intent", intent);
  return url.startsWith("http") ? absolute.toString() : `${absolute.pathname}${absolute.search}`;
}

function toFinancialUrl(ticker, market) {
  if (UI.toFinancialUrl) return UI.toFinancialUrl(ticker, market);
  return `${PAGE_BASE}/index.html?${new URLSearchParams({ ticker, market }).toString()}`;
}

function inferMarket(value) {
  if (UI.inferMarket) return UI.inferMarket(value, "US");
  return /^\d{6}$/.test(String(value || "").trim()) ? "CN" : "US";
}

function marketLabel(market) {
  return market === "CN" ? "A股" : market === "US" ? "美股" : market || "市场";
}

function avatarText(name) {
  return String(name || "财").trim().slice(0, 1).toUpperCase();
}

function escapeHtml(value) {
  if (UI.escapeHtml) return UI.escapeHtml(value);
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[char]);
}

boot();
