# ChainLens Autonomous Analysis Implementation Plan

> 按任务顺序实施；每项先写失败测试，再写最小实现，并在提交前完成对应验证。

**Goal:** 为 ChainLens 增加可交付的受控自主分析，让任意合规产业问题生成安全 SQL、真实结果、确定性结论、图表、证据和报告。

**Architecture:** 保留四个专家内核，并把其他问题路由到 LangGraph 自主分析图。LLM 只生成 SQL 计划；Warehouse 安全门执行白名单只读查询，Profiler 从结果确定性生成统一 `AnalysisResult`。

**Tech Stack:** Python 3.12、FastAPI、LangGraph、OpenAI-compatible SDK、DuckDB、MySQL、原生 HTML/CSS/JavaScript、Playwright。

---

## 文件结构

- 新建 `src/chainlens/agents/llm.py`：Provider 配置和 OpenAI-compatible 调用。
- 新建 `src/chainlens/agents/schema_context.py`：五个视图 Schema 与提示词。
- 新建 `src/chainlens/agents/autonomous.py`：LangGraph、自主 SQL、修复和确定性结果组装。
- 修改 `src/chainlens/agents/orchestrator.py`：精确专家路由和 autonomous fallback。
- 修改 `src/chainlens/agents/contracts.py`：在结果元数据中稳定暴露 SQL 安全信息。
- 修改 `api_server.py`：API 输出 SQL、安全报告和结构化错误。
- 修改 `web/index.html`、`web/app.js`、`web/styles.css`：展示 SQL、trace、错误和报告下载。
- 修改 `requirements.txt`、`pyproject.toml`：加入 `openai`、`langgraph`、`sqlparse`。
- 新建 `tests/test_autonomous_agent.py`：自主图单元和真实 Warehouse 集成测试。
- 修改 `tests/test_api_server.py`、`scripts/test_frontend.py`：API 与 UI 回归。

### Task 1: Provider、Schema 与安全计划合同

**Files:**
- Create: `src/chainlens/agents/llm.py`
- Create: `src/chainlens/agents/schema_context.py`
- Create: `tests/test_autonomous_agent.py`
- Modify: `requirements.txt`
- Modify: `pyproject.toml`

- [ ] **Step 1: 写 Provider 和结构化计划解析的失败测试**

测试 `LLMSettings.from_environment()`、缺 Key、代码围栏 JSON、非法 JSON 和计划必填字段。

- [ ] **Step 2: 运行测试并确认因模块缺失失败**

Run: `python -m pytest tests/test_autonomous_agent.py -q`

Expected: `ModuleNotFoundError: chainlens.agents.autonomous`。

- [ ] **Step 3: 实现最小 Provider、Schema Context 和 `SQLPlan`**

Provider 使用 `OpenAI(base_url=..., api_key=...)`；`SQLPlan` 只接受 `title/sql/chart`，解析时剥离 Markdown 围栏并拒绝额外自然语言。

- [ ] **Step 4: 运行目标测试**

Run: `python -m pytest tests/test_autonomous_agent.py -q`

Expected: Provider/计划解析测试通过。

- [ ] **Step 5: 提交**

```powershell
git add requirements.txt pyproject.toml src/chainlens/agents/llm.py src/chainlens/agents/schema_context.py tests/test_autonomous_agent.py
git commit -m "feat(agent): 建立自主分析Provider和Schema合同"
```

### Task 2: LangGraph 自主分析与确定性证据

**Files:**
- Create: `src/chainlens/agents/autonomous.py`
- Modify: `src/chainlens/agents/orchestrator.py`
- Test: `tests/test_autonomous_agent.py`

- [ ] **Step 1: 写成立趋势、经营状态、注册资本区间、空结果和 SQL 修复测试**

用可编排 Fake LLM 返回计划，使用真实测试 Warehouse 执行；断言 `intent=autonomous`、`safe_sql` 存在、Finding 数字来自结果、Evidence SQL 等于安全 SQL。

- [ ] **Step 2: 运行并确认 autonomous fallback 尚不存在**

Run: `python -m pytest tests/test_autonomous_agent.py -q`

Expected: 路由仍为 `overview` 或类不存在。

- [ ] **Step 3: 实现 LangGraph 节点与最多两次修复**

节点固定为 `retrieve_schema/generate_sql/validate_sql/execute_sql/repair_sql/profile_result/compose_result`；安全拒绝和执行异常进入 repair，超过次数抛出 `AutonomousAnalysisError`。

- [ ] **Step 4: 实现精确专家路由**

只把 OCS/融资盲区、资质续期、产业网络、产业健康等高特异性问题送入专家内核，其他问题送入自主分析。

- [ ] **Step 5: 跑自主与原内核测试**

Run: `python -m pytest tests/test_autonomous_agent.py tests/test_agent_orchestrator.py tests/test_kernels_integration.py -q`

Expected: 全部通过。

- [ ] **Step 6: 提交**

```powershell
git add src/chainlens/agents/autonomous.py src/chainlens/agents/orchestrator.py tests/test_autonomous_agent.py
git commit -m "feat(agent): 增加LangGraph受控自主分析"
```

### Task 3: API 与前端可观察性

**Files:**
- Modify: `api_server.py`
- Modify: `tests/test_api_server.py`
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/styles.css`
- Modify: `scripts/test_frontend.py`

- [ ] **Step 1: 写 API SQL 合同和结构化错误测试**

断言 autonomous 响应含 `sql/safe_sql/safety/trace/report_markdown`；模型配置缺失时返回 503 JSON，不返回 HTML 500。

- [ ] **Step 2: 运行并确认合同缺失**

Run: `python -m pytest tests/test_api_server.py -q`

Expected: 顶层 SQL 字段断言失败。

- [ ] **Step 3: 实现 API 输出与错误映射**

在统一响应中透传元数据；`AutonomousAnalysisError` 映射为 422，Provider/上游不可达映射为 503。

- [ ] **Step 4: 写前端 SQL/trace/错误状态失败测试**

Playwright mock autonomous 响应，要求 SQL 折叠区可展开、SQL 文本可见、图表和报告下载有效；mock 错误响应要求显示具体错误。

- [ ] **Step 5: 实现前端 SQL 与报告交付**

新增不嵌套卡片的 `<details>` SQL 区，显示 safe SQL、安全修改和 trace；下载按钮在实时模式导出 Markdown 报告。

- [ ] **Step 6: 跑 API 与桌面/手机 Playwright**

Run: `python -m pytest tests/test_api_server.py -q`

Run: `python scripts/test_frontend.py`

Expected: API 与前端烟测通过，无控制台错误或文字重叠。

- [ ] **Step 7: 提交**

```powershell
git add api_server.py tests/test_api_server.py web/index.html web/app.js web/styles.css scripts/test_frontend.py
git commit -m "feat(web): 展示自主SQL执行轨迹和报告"
```

### Task 4: 真实模型、Railway 与十问验收

**Files:**
- Create: `scripts/run_autonomous_acceptance.py`
- Modify: `docs/AGENT_HANDOFF.md`
- Modify: `docs/RAILWAY_DEPLOY.md`
- Modify: `README.md`

- [ ] **Step 1: 编写十问验收脚本**

问题覆盖经营状态、行业 Top、融资轮次、招投标年度、资质年份、地区分布、成立趋势、投资 Top、注册资本区间和企业详情；保存问题、SQL、安全报告、结果、图表、报告和 trace。

- [ ] **Step 2: 用真实 MySQL + 火山方舟运行十问**

Run: `python scripts/run_autonomous_acceptance.py --output-dir data/outputs/autonomous_acceptance_20260728`

Expected: 10/10 成功，SQL 全部安全，报告不为空。

- [ ] **Step 3: 跑全量质量门**

Run: `python -m pytest -q`

Run: `python scripts/check_security.py`

Run: `python -m compileall -q app src scripts api_server.py`

Expected: 全部退出 0。

- [ ] **Step 4: 配置 Railway LLM Variables 并发布**

Key 通过 `railway variable set ... --stdin` 写入，不出现在命令输出、Git 或文档。等待 Railway deployment `SUCCESS`。

- [ ] **Step 5: 公网十问与 Playwright 验收**

验证 GitHub Pages 任意问题返回匹配 SQL、图表、证据和报告；桌面与 390px 手机无控制台错误、重叠或截断。

- [ ] **Step 6: 更新同一份交接活文档并提交**

记录 commits、deployment、十问结果、截图、限制和恢复路径，不写任何真实密钥。

```powershell
git add README.md docs/AGENT_HANDOFF.md docs/RAILWAY_DEPLOY.md scripts/run_autonomous_acceptance.py
git commit -m "docs(agent): 记录自主分析公网验收"
git push origin main
```
