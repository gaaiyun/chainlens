const demo = window.CHAINLENS_DEMO;
const apiUrl = (window.CHAINLENS_API_URL || "").trim().replace(/\/$/, "");
const state = { view: "financing", result: null };
const columnLabels = {
  status: "经营状态",
  enterprise_count: "企业数量",
  industry_code: "行业代码",
  round_name: "融资轮次",
  financing_events: "融资事件数",
  year: "年份",
  bidding_records: "招投标记录数",
  qualification_records: "资质记录数",
  district_code: "地区代码",
  investment_count: "对外投资数",
  capital_range: "注册资本区间",
  econ_kind: "企业经济类型",
  name: "企业名称",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

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
      <div class="finding-title">${escapeHtml(item.title)}</div>
      <div class="finding-body">${escapeHtml(item.body)}</div>
      <span class="finding-evidence">${escapeHtml(item.evidence)}</span>
    </div>`).join("");
  $("#action-list").innerHTML = data.actions.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
}

function renderChart(data) {
  const max = Math.max(...data.chart.values, 1);
  $("#chart-title").textContent = data.chart.label;
  $("#chart-unit").textContent = data.chart.suffix;
  $("#chart").innerHTML = data.chart.labels.map((label, index) => {
    const value = data.chart.values[index];
    const height = Math.max(5, Math.round((value / max) * 100));
    const fullLabel = data.chart.fullLabels?.[index] || label;
    return `<div class="bar-item"><span class="bar-value">${escapeHtml(value)}${escapeHtml(data.chart.suffix)}</span><div class="bar" style="height:${height}%"></div><span class="bar-label" title="${escapeHtml(fullLabel)}">${escapeHtml(label)}</span></div>`;
  }).join("");
}

function renderEvidence(data) {
  $("#evidence-list").innerHTML = data.evidence.map(([id, kernel, claim, value]) => `
    <div class="evidence-item">
      <span class="evidence-id">${escapeHtml(id)}</span>
      <strong>${escapeHtml(claim)}</strong>
      <small>${escapeHtml(kernel)} / ${escapeHtml(value)}</small>
    </div>`).join("");
}

function renderTable(data) {
  $("#result-table thead").innerHTML = `<tr>${data.table.columns.map((column) => `<th>${escapeHtml(columnLabels[column] || column)}</th>`).join("")}</tr>`;
  $("#result-table tbody").innerHTML = data.table.rows.map((row) => `<tr>${row.map((value) => `<td>${escapeHtml(value)}</td>`).join("")}</tr>`).join("");
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
  $("#execution-panel").hidden = true;
  $("#error-panel").hidden = true;
  $("#download-snapshot").childNodes[0].nodeValue = "下载快照 ";
  $("#download-snapshot").disabled = false;
  state.result = data;
}

function renderAskHome() {
  state.view = "ask";
  state.result = null;
  $$(".nav-item").forEach((item) => item.classList.remove("is-active"));
  $("#ask-nav").classList.add("is-active");
  $("#page-title").textContent = "智能制造产业自由问数";
  $("#page-description").textContent = "直接查询企业、融资、招投标、对外投资与资质数据。";
  $(".command-copy .eyebrow").textContent = "AUTONOMOUS / ASK DATA";
  $("#error-panel").hidden = true;
  $("#execution-panel").hidden = true;
  $("#metric-grid").innerHTML = `
    <div class="metric"><div class="metric-value">5</div><div class="metric-label">分析视图</div><div class="metric-note">企业 / 招投标 / 融资 / 投资 / 资质</div></div>
    <div class="metric"><div class="metric-value">SQL</div><div class="metric-label">只读查询</div><div class="metric-note">白名单与行数上限</div></div>
    <div class="metric"><div class="metric-value">WAIT</div><div class="metric-label">等待提问</div><div class="metric-note">结果来自数据库执行</div></div>`;
  renderFindings({
    findings: [{
      title: "受控自由问数",
      body: "问题会被转换为只读 SQL，执行结果进入证据链后再形成结论。",
      evidence: "SAFE SQL GATE",
    }],
    actions: ["输入问题，或选择输入框下方的复合问题。"],
  });
  renderEvidence({
    evidence: [
      ["VIEW-01", "v_enterprise", "企业基本信息与行业", "17,576 家"],
      ["VIEW-02", "v_bidding", "企业招投标记录", "576,690 条"],
      ["VIEW-03", "v_financing", "公开融资事件", "267 条"],
      ["VIEW-04", "v_equity", "企业对外投资", "6,757 条"],
      ["VIEW-05", "v_qualification", "商标与资质", "14,486 条"],
    ],
  });
  $("#chart-title").textContent = "查询结果图表";
  $("#chart-unit").textContent = "";
  $("#chart").innerHTML = `<div class="chart-empty">提交问题后生成与结果字段匹配的图表。</div>`;
  renderTable({ table: { columns: ["状态"], rows: [["等待自由问数查询"]] } });
  $("#data-source").textContent = "znjz / Railway 实时分析引擎";
  $("#download-snapshot").childNodes[0].nodeValue = "等待报告 ";
  $("#download-snapshot").disabled = true;
}

function renderExecution(result) {
  const panel = $("#execution-panel");
  if (!result.safe_sql) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  $("#sql-details").open = false;
  $("#safe-sql").textContent = result.safe_sql || "";
  $("#original-sql").textContent = result.sql || result.safe_sql || "";
  const planner = result.metadata?.planner || result.metadata?.engine || "controlled";
  $("#planner-label").textContent = `${planner} / ${result.metadata?.llm_provider || "deterministic"}`;
  const modifications = result.safety?.modifications || [];
  $("#safety-list").innerHTML = (modifications.length ? modifications : ["SQL 未发生改写"])
    .map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  $("#trace-list").innerHTML = (result.trace || []).map((step) => `
    <li><b>${escapeHtml(step.agent || step.node)}</b> · ${escapeHtml(step.status)}<br><span>${escapeHtml(step.detail || step.error || "")}</span></li>`
  ).join("");
}

function renderErrorState(message) {
  $("#error-panel").hidden = false;
  $("#error-message").textContent = message;
  $("#execution-panel").hidden = true;
  $("#page-title").textContent = "分析未完成";
  $("#page-description").textContent = "系统已停止交付，原因如下。请调整问题后重新运行。";
  $(".command-copy .eyebrow").textContent = "AUTONOMOUS / BLOCKED";
  $("#metric-grid").innerHTML = `
    <div class="metric"><div class="metric-value">STOP</div><div class="metric-label">质量门已阻止</div><div class="metric-note">未返回未经验证的结论</div></div>
    <div class="metric"><div class="metric-value">0</div><div class="metric-label">交付结论</div><div class="metric-note">等待有效查询</div></div>
    <div class="metric"><div class="metric-value">SAFE</div><div class="metric-label">数据状态</div><div class="metric-note">数据库未被修改</div></div>`;
  renderFindings({ findings: [], actions: [] });
  renderEvidence({ evidence: [] });
  renderTable({ table: { columns: ["状态"], rows: [["本次分析失败，未产生结果"]] } });
  $("#chart-title").textContent = "无可交付图表";
  $("#chart-unit").textContent = "";
  $("#chart").innerHTML = `<div class="chart-empty">安全或执行检查未通过。</div>`;
}

function renderApiResult(result) {
  // API 结果保持与静态快照相同的视觉契约；无法识别的列只进入明细表。
  $("#page-title").textContent = result.title;
  $("#page-description").textContent = "最新查询结果已从 ChainLens 确定性分析引擎返回。";
  $(".command-copy .eyebrow").textContent = result.intent === "autonomous" ? "AUTONOMOUS / SAFE SQL" : "EXPERT KERNEL / VERIFIED";
  $("#error-panel").hidden = true;
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
  renderExecution(result);
  $("#data-source").textContent = "znjz / Railway 实时确定性分析引擎";
  $("#download-snapshot").childNodes[0].nodeValue = result.report_markdown ? "下载报告 " : "下载快照 ";
  $("#download-snapshot").disabled = false;
  state.result = result;
}

async function queryApi(question) {
  const response = await fetch(`${apiUrl}/api/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question })
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `API ${response.status}`);
  return payload;
}

$$(".nav-item[data-view]").forEach((button) => button.addEventListener("click", () => renderDemo(button.dataset.view)));
$("#ask-nav").addEventListener("click", () => {
  renderAskHome();
  $("#question").focus();
});
$$('.query-examples button').forEach((button) => button.addEventListener("click", () => {
  $("#question").value = button.dataset.question;
  $("#question").focus();
}));

$("#query-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = $("#question").value.trim();
  if (!question) return showToast("请输入一个产业分析问题");
  const button = event.submitter;
  button.disabled = true;
  button.classList.add("is-loading");
  $("#run-label").textContent = "分析中";
  try {
    if (apiUrl) {
      $$(".nav-item").forEach((item) => item.classList.remove("is-active"));
      $("#ask-nav").classList.add("is-active");
      renderApiResult(await queryApi(question));
      showToast("已接入实时分析引擎");
    } else {
      renderDemo(state.view);
      showToast("当前为聚合快照；配置 API 地址后可查询实时数据");
    }
  } catch (error) {
    renderErrorState(error.message || "实时分析失败");
    showToast("分析未完成，已显示具体原因");
  } finally {
    button.disabled = false;
    button.classList.remove("is-loading");
    $("#run-label").textContent = "运行分析";
  }
});

$("#download-snapshot").addEventListener("click", () => {
  const data = state.result || demo.scenarios[state.view];
  if (!data) return showToast("请先运行一次分析");
  const isReport = Boolean(data.report_markdown);
  const content = isReport ? data.report_markdown : JSON.stringify(data, null, 2);
  const blob = new Blob([content], { type: isReport ? "text/markdown;charset=utf-8" : "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = isReport ? `chainlens-${data.intent || state.view}-report.md` : `chainlens-${state.view}-snapshot.json`;
  link.click();
  URL.revokeObjectURL(link.href);
});

renderAskHome();
