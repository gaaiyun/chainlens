# ChainLens 链见 · 交接活文档

> 这是一份**活文档**。任何影响架构、数据、算法口径、部署或验收的变化，都直接追加到本文档底部的「追加日志」，不要另起新稿。
> 姊妹项目 `text2sql-analysis` 的交接文档在 `G:\text2sql-analysis\docs\AGENT_HANDOFF.md`，两边互为上下游，改动要互相同步。

---

## 0. 一句话说清这是什么

**ChainLens（链见）是一个面向"数据要素×工业制造"赛道的多智能体产业数据协同平台。**

它把智能制造产业链上分散的工商登记、招投标、股权、融资、资质五类公开数据，融合加工成三个可复用的**数据要素产品**，
用于解决一个具体的社会问题：**大量有真实经营能力的中小制造企业，在金融和政策视角下是"数据黑户"，看不见、评不了、扶不到。**

数据事实（本库 17,576 家智能制造企业）：

| 维度 | 有记录企业数 | 覆盖率 | 含义 |
| --- | --- | --- | --- |
| 融资记录 | 124 | **0.7%** | 99.3% 的企业在资本视角完全隐形 |
| 资质/荣誉记录 | 1,401 | **8.0%** | 92% 的企业在政策视角没有可识别标签 |
| 招投标记录 | 3,679 | **20.9%** | 只有两成企业的真实交易能力被记录 |
| 股权关联 | 2,289 | 13.0% | 产业协作关系高度稀疏 |

> 这些数字来自 `data/warehouse/chainlens.duckdb`，由 `scripts/build_warehouse.py` 可复现，不是估算。
> 最新实测值见 `docs/DATA_FACTS.md`（由 `scripts/profile_facts.py` 自动生成）。

**立意**：不是再做一个"数据库问答机器人"，而是把公共数据加工成**增信凭证**，让沉默的中小企业被看见。

---

## 1. 与 text2sql-analysis 的关系（必读）

| 项 | text2sql-analysis | chainlens |
| --- | --- | --- |
| 定位 | Text2SQL 查询工具，一问一答 | 产业数据要素平台，一问一份可执行决策 |
| 数据访问 | 远程 MySQL `znjz`（需密钥、需公网放行） | 本地 DuckDB，离线可复现，零密钥 |
| 结论来源 | LLM 生成 SQL → LLM 解读 | **确定性算法内核算结论，LLM 只负责表达** |
| 智能体 | 单一 AgentRuntime 线性流程 | 8 个专职 Agent + 编排器 + 证据链 |
| 交付物 | 表格 / 图表 / 分析文本 | 决策简报 + 行动清单 + 证据链 + 数据产品 |
| 复用关系 | — | 复用其 SQL 安全层思想与 `znjz` 口径知识 |

**不要把 chainlens 当成 text2sql-analysis 的重写。** 前者是查询工具，后者是场景应用；两个仓库都保留。
text2sql-analysis 里已验证的 `znjz` 字段口径（哪些字段不存在、行业只能用 `industry_code` 等）在 chainlens 里依然成立，见 `docs/METHODOLOGY.md`。

---

## 2. 当前仓库状态

- 仓库根目录：`G:\chainlens`
- GitHub：`gaaiyun/chainlens`（**待创建 / 待首推**）
- 原始数据目录：`G:\text2sql_0705`（6 个 Excel，不入库、已在 `.gitignore`）
- 本地数据底座：`data/warehouse/chainlens.duckdb`（由 ETL 生成，不入库）
- Python：3.13.5，依赖见 `requirements.txt`

---

## 3. 目录结构与职责

```text
G:\chainlens\
├── README.md                       # 对外说明（竞赛/GitHub 首页）
├── docs\
│   ├── AGENT_HANDOFF.md            # ← 本文档，唯一交接入口
│   ├── COMPETITION_BRIEF.md        # 竞赛方案书：问题 / 立意 / 社会价值 / 创新点
│   ├── ARCHITECTURE.md             # 多智能体架构与数据流
│   ├── METHODOLOGY.md              # 指标口径与算法（OCS 信用分等）
│   ├── DATA_PRODUCTS.md            # 三个数据要素产品说明书
│   ├── DATA_FACTS.md               # 自动生成的数据实测事实
│   └── COMPLIANCE.md               # 数据安全、脱敏与合规边界
├── src\chainlens\
│   ├── warehouse\                  # 数据底座：ETL、schema、只读安全访问
│   ├── kernels\                    # 确定性分析内核（无 LLM 参与）
│   ├── agents\                     # 多智能体角色
│   ├── evidence.py                 # 证据链数据结构
│   ├── orchestrator.py             # 智能体 DAG 编排
│   └── llm.py                      # LLM Provider（可缺省，退化为模板表达）
├── app\streamlit_app.py            # 演示前端
├── scripts\                        # 可复现命令
└── tests\                          # 口径与安全测试
```

---

## 4. 核心设计原则（改代码前必须理解）

1. **结论与表达分离。** 所有数字、排名、分数由 `src/chainlens/kernels/` 的纯 Python/SQL 算出；LLM 只把结构化结论写成人话。
   → 好处：断网、无 Key 也能跑出完整结论；政府/金融场景可审计。**不要把任何指标计算搬进 prompt。**
2. **每个结论必须挂证据。** 任何进入报告的数字都要携带 `Evidence(sql, params, row_count, computed_at, kernel, confidence)`。
   没有证据的结论由 `CriticAgent` 直接拦掉。
3. **只读、白名单、可解释。** 数据访问层只允许 `SELECT`，只允许白名单视图，自动补 `LIMIT`。
4. **离线优先。** 默认数据源是本地 DuckDB。远程 MySQL 是可选项，不是前提。
5. **口径写在文档里，不写在脑子里。** 新增/修改任何指标，同步更新 `docs/METHODOLOGY.md`。

---

## 5. 数据底座

### 源表映射

| DuckDB 表 | 源文件 | 行数量级 | 说明 |
| --- | --- | --- | --- |
| `enterprise` | `znjz_gzldata_step1.xls` | 17,576 | 工商登记主档 |
| `enterprise_industry` | `znjz_gzldata_step2.xlsx` | 17,576 | 行业代码（GB/T 4754） |
| `financing` | `znjz_gzldata_step3.xlsx` | 17,719 | 融资事件（98% 为空行） |
| `equity` | `znjz_gzldata_step4.xlsx` | 21,980 | 股权投资关系 |
| `bidding` | `znjz_gzldata_step5.xlsx` | 590,523 | 招投标记录（核心资产） |
| `qualification` | `znjz_gzldata_step6.xlsx` | 30,588 | 商标与资质 |

### 派生视图（分析层只允许访问这些）

`v_enterprise` / `v_bidding` / `v_financing` / `v_equity` / `v_qualification`

定义在 `src/chainlens/warehouse/etl.py` 的 `DERIVED_VIEWS` 常量里。

### 重建命令

```powershell
cd G:\chainlens
python scripts\build_warehouse.py            # 复用已有 parquet，秒级
python scripts\build_warehouse.py --force    # 重新解析 Excel，约 3-6 分钟
```

---

## 6. 常用命令

```powershell
cd G:\chainlens
python -m pip install -r requirements.txt

python scripts\build_warehouse.py      # 建数据底座
python scripts\profile_facts.py        # 刷新 docs/DATA_FACTS.md 实测数字
python scripts\run_pipeline.py --demo  # 跑一遍多智能体流水线，产出决策简报
python scripts\check_security.py       # 提交前敏感信息扫描
python -m pytest -q                    # 口径与安全测试

streamlit run app\streamlit_app.py     # 演示前端
```

---

## 7. 历史恢复路径

- Claude 会话可读归档：`G:\ClaudeCode\readable\`
- Claude 原始归档：`G:\ClaudeCode\archive\`
- Claude 项目存储：`G:\ClaudeCode\_projects-store\`
- Codex 记忆：`G:\codex-home\memories\MEMORY.md`、`G:\codex-home\memories\rollout_summaries\`
- 上游项目交接文档：`G:\text2sql-analysis\docs\AGENT_HANDOFF.md`

恢复顺序：本文档 → `docs/COMPETITION_BRIEF.md` → `docs/ARCHITECTURE.md` → `docs/METHODOLOGY.md` → 代码。

---

## 8. 维护规则

- 不另起新交接文档，只往「追加日志」追加。
- 追加时写清：日期、做了什么、动了哪些文件、验证了什么、留了什么坑。
- 不把真实 Key、密码、数据库地址、cookie 写进任何文件。
- 改指标口径必须同步改 `docs/METHODOLOGY.md` 和对应测试。
- 声称"完成/通过"前必须先跑验证命令并贴出输出。

---

## 9. 追加日志

### 2026-07-26 · 项目创建

- 从 `text2sql-analysis` 分出新仓库 `G:\chainlens`，定位改为「数据要素竞赛场景应用」而非查询工具。
- 确定核心立意：用公共数据给中小制造企业增信，解决"数据黑户"问题。
- 完成数据事实盘点：融资覆盖率 0.7%、资质覆盖率 8.0%、招投标覆盖率 20.9%，资质过期率约 81%。
- 建立本地 DuckDB 数据底座方案（`src/chainlens/warehouse/etl.py`），彻底摆脱远程 MySQL 依赖。
- 动了哪些文件：新建仓库全部骨架 + 本文档。
- 未完成：分析内核、多智能体层、前端、GitHub 首推。

### 2026-07-26 · 接手恢复与 Agent 层完成

- 先在上游 `G:\text2sql-analysis` 提交了交接文档、schema 导出脚本和测试：`86dc194 docs(handoff): 补充交接文档和schema导出工具`。
- 从中断会话恢复四个确定性内核：`credit`、`qualification`、`graph`、`region`。修复后的代码已通过真实 DuckDB 集成测试。
- 新增 `src/chainlens/agents/contracts.py`、`reporting.py`、`orchestrator.py`：
  - `IntentAgent` 用显式规则把中文问题路由到融资、资质、网络、区域四类场景；
  - `KernelAgent` 只调用确定性内核；
  - `CriticAgent` 拦截没有证据或不可核查的报告；
  - `ReportAgent` 和 `ArtifactAgent` 从同一份结构化结果生成 Markdown、HTML、PDF 和 PNG；
  - 当前 `metadata["llm_used"] = False`，没有把关键数字交给模型猜测。
- 新增 `app/streamlit_app.py`，页面只调用 `ChainLensOrchestrator`，支持四个场景、表格、证据链、图表和报告下载。
- 新增 `api_server.py` 和 `web/` 静态前端：
  - FastAPI `GET /health`、`POST /api/query` 返回同一份 Agent 结果；
  - GitHub Pages / Cloudflare Pages 可直接部署 `web/`；
  - 静态页面默认展示脱敏聚合快照，配置 `web/config.js` 的 API 地址后切换实时查询；
  - `scripts/test_frontend.py` 已用 Playwright 验证桌面、移动端、场景切换和 JSON 快照下载。
- 前端设计方向已固定为“工业编辑室”：石墨侧栏、暖白数据工作区、信号橙/青绿色强调、证据链作为主视觉，不使用通用聊天窗口布局。
- 新增 `scripts/run_pipeline.py`、`scripts/check_security.py`、`requirements.txt`、`pyproject.toml`，使源码布局可以在干净 shell 直接运行。
- 新增竞赛和方法文档：`README.md`、`docs/ARCHITECTURE.md`、`docs/METHODOLOGY.md`、`docs/DATA_PRODUCTS.md`、`docs/COMPETITION_BRIEF.md`、`docs/COMPLIANCE.md`、`docs/DATA_FACTS.md`。
- 测试输出：
  - `python -m pytest -q` -> `9 passed in 18.43s`
  - `python scripts/check_security.py` -> `[OK] security scan passed`
- `python scripts/run_pipeline.py --output-dir G:\chainlens\data\outputs\acceptance_20260726` -> 4 个场景全部 `[ok]`
- `scripts/test_frontend.py` -> `[OK] frontend smoke passed`，截图和下载快照在 `G:\chainlens\data\outputs\frontend_smoke`
- 实际产物已保存到 `G:\chainlens\data\outputs\acceptance_20260726`，每个场景有 Markdown、HTML、PDF 和图表，另有 `summary.json`。
- 当前仍未完成：实时 API 公网部署、Cloudflare/自定义域名配置、远程 MySQL 接入；本地离线主线和 GitHub Pages 静态前端已可复现。

### 2026-07-26 · GitHub Pages 已上线

- 已创建并推送 GitHub 仓库：`https://github.com/gaaiyun/chainlens`
- 已通过 GitHub API 启用 Pages 的 workflow 构建模式。
- workflow `Deploy static frontend` 已成功完成，公网前端：
  - `https://gaaiyun.github.io/chainlens/`
- 公网检查结果：HTTP `200`，返回 `text/html`，页面首屏可访问。
- API 仍未公网部署。原因是当前机器只有 GitHub 授权，没有宝塔 SSH 凭据、Render/Railway/Cloudflare API 授权或其他可运行 Python/DuckDB 的公网主机授权。
- API 代码入口仍是 `api_server.py`，本地启动方式：

```powershell
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

- 要完成 API 公网部署，需要补充一种明确的运行环境：宝塔服务器 SSH 用户名/端口/密钥，或已登录的 Render/Railway/Cloudflare 等平台。

### 2026-07-26 · Railway 部署准备

- 用户询问 Railway 是否适合部署。结论：适合承载 FastAPI API，GitHub Pages
  继续承载静态前端；不需要在 Railway Developer/OAuth 页面创建 OAuth App。
- 新增仓库根目录 `railway.toml`，固定 Nixpacks 构建、`uvicorn` 启动命令、
  `/health` 健康检查和失败重启策略。
- `api_server.py` 新增 `CHAINLENS_ALLOWED_ORIGINS` 环境变量解析，生产环境
  可以只允许 `https://gaaiyun.github.io`，本地未配置时仍允许开发调试。
- 新增 `docs/RAILWAY_DEPLOY.md`，记录控制台步骤、变量规则、数据底座进入
  Railway 的方案、上线验收和常见误区。
- 新增 API CORS 配置测试；尚未创建 Railway 项目或公网 API 域名。
- 远程数据方案已确定为已有 `znjz` MySQL：连接时用 DuckDB MySQL 扩展只读
  附加，随后把 `v_enterprise`、`v_bidding`、`v_financing`、`v_equity`、
  `v_qualification` 五个白名单视图物化到内存 DuckDB，内核只查询缓存。
- 实连验证结果：MySQL 端口可达；五个视图分别返回 `17,576`、`576,690`、
  `267`、`6,757`、`14,486` 行；完整 financing、qualification、network、
  region 四场景均通过，启动缓存约 6.5 秒。
- 新增 `src/chainlens/warehouse/mysql.py`，远程数据适配和视图契约集中在
  仓库层，不把 MySQL 连接逻辑散落到 API 或内核。
- 原来的“必须上传 DuckDB”判断已作废。Railway 只需配置五个 DB Variables；
  本地 DuckDB 继续作为离线复现路径。
