const AUTH_TOKEN_KEY = "financial_mining_token";
const AUTH_USER_KEY = "financial_mining_user";
const API_BASE = window.location.protocol === "file:" ? "http://localhost:8765" : "";
const PAGE_BASE = window.location.protocol === "file:" ? "http://localhost:8765" : "";
const token = localStorage.getItem(AUTH_TOKEN_KEY);
const userLabel = document.querySelector("#userLabel");
const logoutButton = document.querySelector("#logoutButton");
const marketButtons = document.querySelectorAll("[data-market]");
const tickerInput = document.querySelector("#homeTickerInput");
const analyzeButton = document.querySelector("#homeAnalyzeButton");
const profileAnalyzeButton = document.querySelector("#profileAnalyzeButton");
const documentTypeSelect = document.querySelector("#documentTypeSelect");
const searchMessage = document.querySelector("#homeSearchMessage");
const quickCompanies = document.querySelector("#homeQuickCompanies");
const focusSearchButtons = document.querySelectorAll("[data-focus-search]");

let selectedMarket = "US";
let topCompanies = [
  { ticker: "AAPL", name: "Apple", market: "US" },
  { ticker: "MSFT", name: "Microsoft", market: "US" },
  { ticker: "NVDA", name: "NVIDIA", market: "US" },
  { ticker: "000333", name: "美的集团", market: "CN" },
  { ticker: "002594", name: "比亚迪", market: "CN" },
  { ticker: "600519", name: "贵州茅台", market: "CN" }
];

if (!token) {
  window.location.href = `${PAGE_BASE}/login.html`;
}

async function loadCurrentUser() {
  const response = await fetch(`${API_BASE}/api/auth/me`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_USER_KEY);
    window.location.href = `${PAGE_BASE}/login.html`;
    return;
  }
  const data = await response.json();
  localStorage.setItem(AUTH_USER_KEY, JSON.stringify(data.user));
  userLabel.textContent = data.user.username;
}

async function logout() {
  await fetch(`${API_BASE}/api/auth/logout`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` }
  }).catch(() => {});
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(AUTH_USER_KEY);
  window.location.href = `${PAGE_BASE}/login.html`;
}

function startService() {
  startFinancialService();
}

function startFinancialService() {
  const raw = tickerInput.value.trim();
  if (!ensureTicker(raw)) return;
  const market = inferMarket(raw, selectedMarket);
  const params = new URLSearchParams({ ticker: raw, market });
  window.location.href = `${PAGE_BASE}/index.html?${params.toString()}`;
}

function startProfileService() {
  const raw = tickerInput.value.trim();
  if (!ensureTicker(raw)) return;
  const market = inferMarket(raw, selectedMarket);
  const params = new URLSearchParams({ query: raw, market, document_type: documentTypeSelect?.value || "auto" });
  window.location.href = `${PAGE_BASE}/profile.html?${params.toString()}`;
}

function ensureTicker(raw) {
  if (raw) return true;
  searchMessage.textContent = "请先输入股票代码或公司名。";
  searchMessage.classList.add("error");
  tickerInput.focus();
  return false;
}

logoutButton.addEventListener("click", logout);
analyzeButton.addEventListener("click", startFinancialService);
profileAnalyzeButton.addEventListener("click", startProfileService);
tickerInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") startService();
});
marketButtons.forEach((button) => {
  button.addEventListener("click", () => {
    selectedMarket = button.dataset.market;
    renderMarket();
    renderQuickCompanies();
  });
});
focusSearchButtons.forEach((button) => {
  button.addEventListener("click", () => {
    tickerInput.focus();
    tickerInput.scrollIntoView({ behavior: "smooth", block: "center" });
  });
});

async function loadTopCompanies() {
  try {
    const response = await fetch(`${API_BASE}/api/companies/top?market=ALL`);
    if (!response.ok) return;
    const data = await response.json();
    if (data.items?.length) topCompanies = data.items;
  } catch (error) {
    // Use the local fallback above.
  } finally {
    renderQuickCompanies();
  }
}

function renderMarket() {
  marketButtons.forEach((button) => button.classList.toggle("active", button.dataset.market === selectedMarket));
  tickerInput.placeholder = selectedMarket === "CN" ? "例如 000333 / 比亚迪 / 600519" : "例如 AAPL / MSFT / NVDA";
  searchMessage.textContent = selectedMarket === "CN"
    ? "将自动从巨潮资讯获取公告和财报 PDF。"
    : "将自动从 SEC 获取结构化财务数据。";
  searchMessage.classList.remove("error");
}

function renderQuickCompanies() {
  const items = topCompanies.filter((item) => item.market === selectedMarket).slice(0, 6);
  quickCompanies.innerHTML = items
    .map((item) => `<button type="button" data-ticker="${item.ticker}" data-market="${item.market}">${item.ticker} · ${item.name}</button>`)
    .join("");
  quickCompanies.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      selectedMarket = button.dataset.market;
      tickerInput.value = button.dataset.ticker;
      renderMarket();
      startService();
    });
  });
}

function inferMarket(value, fallback) {
  return /^\d{6}$/.test(value.trim()) ? "CN" : fallback;
}

renderMarket();
renderQuickCompanies();
loadCurrentUser();
loadTopCompanies();
