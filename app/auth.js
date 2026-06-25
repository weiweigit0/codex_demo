const AUTH_TOKEN_KEY = "financial_mining_token";
const AUTH_USER_KEY = "financial_mining_user";
const API_BASE = window.location.protocol === "file:" ? "http://localhost:8765" : "";
const PAGE_BASE = window.location.protocol === "file:" ? "http://localhost:8765" : "";

const form = document.querySelector("[data-auth-form]");
const message = document.querySelector("#formMessage");
const snapshotNodes = {
  eyebrow: document.querySelector("#authSnapshotEyebrow"),
  title: document.querySelector("#authSnapshotTitle"),
  meta: document.querySelector("#authSnapshotMeta"),
  score: document.querySelector("#authSnapshotScore"),
  summary: document.querySelector("#authSnapshotSummary"),
  metrics: document.querySelector("#authSnapshotMetrics"),
  bars: document.querySelector("#authSnapshotBars"),
  refresh: document.querySelector("#authSnapshotRefresh")
};

function setMessage(text, ok = false) {
  message.textContent = text || "";
  message.classList.toggle("ok", ok);
}

async function api(path, payload) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "请求失败，请稍后重试");
  }
  return data;
}

async function loadAuthSnapshot(refresh = false) {
  if (!snapshotNodes.title) return;
  renderAuthSnapshotLoading(refresh ? "正在换一家真实公司..." : "正在读取真实财报...");
  try {
    const market = refresh ? randomMarket() : "US";
    const response = await fetch(`${API_BASE}/api/home/financial-snapshot?market=${market}${refresh ? "&refresh=true" : ""}`);
    if (!response.ok) throw new Error("snapshot unavailable");
    const snapshot = await response.json();
    renderAuthSnapshot(snapshot, Boolean(snapshot.is_demo));
  } catch (error) {
    renderAuthSnapshot(authFallbackSnapshot(), true);
  }
}

function renderAuthSnapshotLoading(text) {
  snapshotNodes.eyebrow.textContent = "随机真实财报快照";
  snapshotNodes.title.textContent = text;
  snapshotNodes.meta.textContent = "公开披露数据预览";
  snapshotNodes.score.textContent = "--";
  snapshotNodes.summary.textContent = "正在读取一家公司的真实财报快照...";
  snapshotNodes.metrics.innerHTML = Array.from({ length: 4 }, () => "<article class=\"loading\"></article>").join("");
  snapshotNodes.bars.innerHTML = [38, 52, 66, 80].map((height) => `<i style="height: ${height}%"></i>`).join("");
}

function renderAuthSnapshot(snapshot, isFallback) {
  const company = snapshot.company || {};
  const metrics = (snapshot.metrics || []).slice(0, 4);
  const trend = snapshot.trend?.length ? snapshot.trend : [38, 52, 66, 80];
  snapshotNodes.eyebrow.textContent = isFallback ? "示例财报快照" : "随机真实财报快照";
  snapshotNodes.title.textContent = `${company.name || "Apple Inc."} · ${company.ticker || "AAPL"}`;
  snapshotNodes.meta.textContent = `${marketLabel(company.market)} · ${snapshot.period || "2025-FY"} · 公开披露数据`;
  snapshotNodes.score.textContent = snapshot.score ? `${snapshot.health_label || "中性"} ${snapshot.score}分` : (snapshot.health_label || "中性");
  snapshotNodes.summary.textContent = snapshot.summary || "公开财报数据已接入，注册后可查看完整财报掘金分析。";
  snapshotNodes.metrics.innerHTML = metrics.map((item) => `
    <article>
      <span>${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.value)}</strong>
      <small class="${String(item.change || "").includes("-") ? "down" : ""}">${escapeHtml(item.change || "同比待补充")}</small>
    </article>
  `).join("");
  snapshotNodes.bars.innerHTML = trend.map((height) => `<i style="height: ${Number(height) || 42}%"></i>`).join("");
}

function authFallbackSnapshot() {
  return {
    company: { ticker: "AAPL", name: "Apple Inc.", market: "US" },
    period: "2025-FY",
    health_label: "中性",
    score: null,
    is_demo: true,
    summary: "示例快照：收入、利润和现金流指标会在后端可用时自动替换为真实随机公司数据。",
    metrics: [
      { label: "营业收入", value: "416.16B USD", change: "同比 +6.43%" },
      { label: "净利润", value: "112.01B USD", change: "同比 +19.5%" },
      { label: "毛利率", value: "46.91%", change: "同比待补充" },
      { label: "经营现金流", value: "111.48B USD", change: "同比 -5.73%" }
    ],
    trend: [38, 48, 62, 76]
  };
}

function randomMarket() {
  return Math.random() > 0.5 ? "US" : "CN";
}

function marketLabel(market) {
  return market === "CN" ? "A股" : market === "US" ? "美股" : "市场";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[char]);
}

function saveSession(data) {
  localStorage.setItem(AUTH_TOKEN_KEY, data.token);
  localStorage.setItem(AUTH_USER_KEY, JSON.stringify(data.user));
}

function readValues() {
  const values = {};
  form.querySelectorAll("input[name]").forEach((input) => {
    values[input.name] = input.value.trim();
  });
  return values;
}

function validateLogin(values) {
  if (!values.username || !values.password) return "请输入用户名和密码";
  return "";
}

function validateRegister(values) {
  if (!values.username || values.username.length < 3) return "用户名至少需要 3 位";
  if (!/^1[3-9]\d{9}$/.test(values.phone || "")) return "请输入正确的手机号";
  if (!values.password || values.password.length < 6) return "密码至少需要 6 位";
  if (values.password !== values.confirmPassword) return "两次输入的密码不一致";
  return "";
}

async function handleSubmit(event) {
  event.preventDefault();
  const mode = form.dataset.authForm;
  const values = readValues();
  const error = mode === "register" ? validateRegister(values) : validateLogin(values);
  if (error) {
    setMessage(error);
    return;
  }

  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  setMessage(mode === "register" ? "正在创建账号..." : "正在登录...", true);
  try {
    const path = mode === "register" ? "/api/auth/register" : "/api/auth/login";
    const payload =
      mode === "register"
        ? { username: values.username, password: values.password, phone: values.phone }
        : { username: values.username, password: values.password };
    const data = await api(path, payload);
    saveSession(data);
    window.location.href = `${PAGE_BASE}/home.html`;
  } catch (error) {
    setMessage(error.message);
  } finally {
    button.disabled = false;
  }
}

form.addEventListener("submit", handleSubmit);
snapshotNodes.refresh?.addEventListener("click", () => loadAuthSnapshot(true));
loadAuthSnapshot();
