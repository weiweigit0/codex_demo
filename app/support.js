const API_BASE = window.location.protocol === "file:" ? "http://localhost:8765" : "";

const nodes = {
  coverageGrid: document.querySelector("#coverageGrid"),
  marketFilter: document.querySelector("#marketFilter"),
  supportSearch: document.querySelector("#supportSearch"),
  supportSearchButton: document.querySelector("#supportSearchButton"),
  resultMeta: document.querySelector("#resultMeta"),
  supportTable: document.querySelector("#supportTable")
};

async function api(path) {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `请求失败：${response.status}`);
  }
  return response.json();
}

async function boot() {
  bindEvents();
  await Promise.allSettled([loadCoverage(), loadCompanies()]);
}

function bindEvents() {
  nodes.supportSearchButton.addEventListener("click", loadCompanies);
  nodes.marketFilter.addEventListener("change", loadCompanies);
  nodes.supportSearch.addEventListener("keydown", (event) => {
    if (event.key === "Enter") loadCompanies();
  });
}

async function loadCoverage() {
  try {
    const data = await api("/support-api/coverage");
    nodes.coverageGrid.innerHTML = Object.entries(data)
      .map(
        ([market, item]) => `
          <article class="coverage-card">
            <h2>${market} · ${item.status} · ${item.count} 家</h2>
            <p>${item.source}</p>
            <p>${item.note}</p>
          </article>
        `
      )
      .join("");
  } catch (error) {
    nodes.coverageGrid.innerHTML = `<article class="coverage-card"><h2>覆盖范围暂不可用</h2><p>${error.message}</p></article>`;
  }
}

async function loadCompanies() {
  const q = nodes.supportSearch.value.trim();
  const market = nodes.marketFilter.value;
  nodes.resultMeta.textContent = "正在查询支持列表...";
  try {
    const data = await api(`/support-api/companies?q=${encodeURIComponent(q)}&market=${market}&limit=300`);
    renderCompanies(data.items || []);
    nodes.resultMeta.textContent = `匹配 ${data.total_matched} 家，当前展示 ${data.total_returned} 家。`;
  } catch (error) {
    nodes.supportTable.innerHTML = "";
    nodes.resultMeta.textContent = error.message;
  }
}

function renderCompanies(items) {
  if (!items.length) {
    nodes.supportTable.innerHTML = `
      <tr>
        <td colspan="7">没有匹配到支持公司。可以尝试输入美股 ticker，例如 AAPL / MSFT / NVDA。</td>
      </tr>
    `;
    return;
  }
  nodes.supportTable.innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>${item.market}</td>
          <td><strong>${item.ticker}</strong></td>
          <td>${item.name}</td>
          <td>${item.industry || "待识别行业"}</td>
          <td>${statusTag(item.status)}</td>
          <td>
            <div class="abilities">
              ${(item.abilities || []).map((ability) => `<span class="ability">${ability}</span>`).join("")}
            </div>
          </td>
          <td>${item.note || ""}</td>
        </tr>
      `
    )
    .join("");
}

function statusTag(status) {
  const cls = status === "支持" ? "full" : "partial";
  return `<span class="status ${cls}">${status}</span>`;
}

boot();
