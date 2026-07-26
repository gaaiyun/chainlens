const demo = window.CHAINLENS_DEMO;
const apiUrl = (window.CHAINLENS_API_URL || "").trim().replace(/\/$/, "");
const state = { view: "financing", result: null };

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("is-visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("is-visible"), 3200);
}

function renderMetrics(data) {
  $("#metric-grid").innerHTML = data.metrics.map((item) => `
    <div class="metric">
      <div class="metric-value">${item.value}</div>
      <div class="metric-label">${item.label}</div>
      <div class="metric-note">${item.note}</div>
    </div>`).join("");
}

function renderFindings(data) {
  $("#finding-list").innerHTML = data.findings.map((item) => `
    <div class="finding">
      <div class="finding-title">${item.title}</div>
      <div class="finding-body">${item.body}</div>
      <span class="finding-evidence">${item.evidence}</span>
    </div>`).join("");
  $("#action-list").innerHTML = data.actions.map((item) => `<li>${item}</li>`).join("");
}

function renderChart(data) {
  const max = Math.max(...data.chart.values, 1);
  $("#chart-title").textContent = data.chart.label;
  $("#chart-unit").textContent = data.chart.suffix;
  $("#chart").innerHTML = data.chart.labels.map((label, index) => {
    const value = data.chart.values[index];
    const height = Math.max(5, Math.round((value / max) * 100));
    const fullLabel = data.chart.fullLabels?.[index] || label;
    return `<div class="bar-item"><span class="bar-value">${value}${data.chart.suffix}</span><div class="bar" style="height:${height}%"></div><span class="bar-label" title="${fullLabel}">${label}</span></div>`;
  }).join("");
}

function renderEvidence(data) {
  $("#evidence-list").innerHTML = data.evidence.map(([id, kernel, claim, value]) => `
    <div class="evidence-item">
      <span class="evidence-id">${id}</span>
      <strong>${claim}</strong>
      <small>${kernel} / ${value}</small>
    </div>`).join("");
}

function renderTable(data) {
  $("#result-table thead").innerHTML = `<tr>${data.table.columns.map((column) => `<th>${column}</th>`).join("")}</tr>`;
  $("#result-table tbody").innerHTML = data.table.rows.map((row) => `<tr>${row.map((value) => `<td>${value}</td>`).join("")}</tr>`).join("");
  $("#table-status").textContent = `${data.table.rows.length} 行聚合预览`;
}

function renderApiChart(result) {
  const spec = result.charts?.[0];
  const rows = spec ? result.tables?.[spec.data_key] || [] : [];
  const isMobile = window.innerWidth < 640;
  const pointLimit = isMobile ? 5 : 12;
  const points = rows
    .map((row) => ({ label: row[spec.x], value: Number(row[spec.y]) }))
    .filter((point) => point.label !== null && point.label !== undefined && Number.isFinite(point.value))
    .slice(0, pointLimit);

  if (!spec || !points.length) {
    $("#chart-title").textContent = "实时图表";
    $("#chart-unit").textContent = "";
    $("#chart").innerHTML = `<div class="chart-empty">当前结果没有可绘制的数值序列，请查看明细表和证据链。</div>`;
    return;
  }

  const suffix = String(spec.y).includes("%") ? "%" : "";
  const labels = points.map((point) => {
    const full = String(point.label);
    if (!isMobile) return full;
    const district = full.includes("市") ? full.slice(full.lastIndexOf("市") + 1) : full;
    const compact = district || full;
    return compact.length > 4 ? `${compact.slice(0, 3)}…` : compact;
  });
  renderChart({
    chart: {
      label: spec.title,
      labels,
      fullLabels: points.map((point) => String(point.label)),
      values: points.map((point) => point.value),
      suffix,
    },
  });
}

function renderDemo(view = state.view) {
  state.view = view;
  const data = demo.scenarios[view];
  $(".nav-item.is-active")?.classList.remove("is-active");
  document.querySelector(`[data-view="${view}"]`)?.classList.add("is-active");
  $("#page-title").textContent = data.title;
  $("#page-description").textContent = data.description;
  $(".eyebrow").textContent = data.kicker;
  renderMetrics(data);
  renderFindings(data);
  renderChart(data);
  renderEvidence(data);
  renderTable(data);
  $("#data-source").textContent = `${demo.source} / ${demo.updated}`;
  state.result = data;
}

function renderApiResult(result) {
  // API 结果保持与静态快照相同的视觉契约；无法识别的列只进入明细表。
  $("#page-title").textContent = result.title;
  $("#page-description").textContent = "最新查询结果已从 ChainLens 确定性分析引擎返回。";
  renderFindings({
    findings: result.findings.map((item) => ({ title: "可核验结论", body: item.text, evidence: item.evidence_id })),
    actions: result.actions
  });
  renderEvidence({
    evidence: result.evidence.slice(0, 6).map((item) => [item.evidence_id, item.kernel, item.claim, `${item.value ?? ""}${item.unit ?? ""}`])
  });
  const table = Object.values(result.tables)[0] || [];
  const columns = table.length ? Object.keys(table[0]) : ["状态"];
  const rows = table.length ? table.slice(0, 12).map((item) => columns.map((column) => item[column] ?? "")) : [["无匹配记录"]];
  renderTable({ table: { columns, rows } });
  $("#metric-grid").innerHTML = `
    <div class="metric"><div class="metric-value">${result.findings.length}</div><div class="metric-label">可核验结论</div><div class="metric-note">来自 API 返回</div></div>
    <div class="metric"><div class="metric-value">${result.evidence.length}</div><div class="metric-label">证据记录</div><div class="metric-note">Evidence Ledger</div></div>
    <div class="metric"><div class="metric-value">LIVE</div><div class="metric-label">数据状态</div><div class="metric-note">确定性计算引擎</div></div>`;
  renderApiChart(result);
  $("#data-source").textContent = "znjz / Railway 实时确定性分析引擎";
  state.result = result;
}

async function queryApi(question) {
  const response = await fetch(`${apiUrl}/api/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question })
  });
  if (!response.ok) throw new Error(`API ${response.status}`);
  return response.json();
}

$$(".nav-item").forEach((button) => button.addEventListener("click", () => renderDemo(button.dataset.view)));

$("#query-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = $("#question").value.trim();
  if (!question) return showToast("请输入一个产业分析问题");
  const button = event.submitter;
  button.disabled = true;
  button.classList.add("is-loading");
  try {
    if (apiUrl) {
      renderApiResult(await queryApi(question));
      showToast("已接入实时分析引擎");
    } else {
      renderDemo(state.view);
      showToast("当前为聚合快照；配置 API 地址后可查询实时数据");
    }
  } catch (error) {
    showToast("实时接口暂不可用，已保留当前快照");
    console.error(error);
  } finally {
    button.disabled = false;
    button.classList.remove("is-loading");
  }
});

$("#download-snapshot").addEventListener("click", () => {
  const data = state.result || demo.scenarios[state.view];
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `chainlens-${state.view}-snapshot.json`;
  link.click();
  URL.revokeObjectURL(link.href);
});

renderDemo();
