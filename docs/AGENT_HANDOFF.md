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

### 2026-07-26 · Railway API 与 GitHub Pages 实时链路上线

- Railway CLI 已授权并链接到
  `perceptive-stillness / production / chainlens`，真实变量只保存在
  Railway Variables，没有进入仓库或文档。
- 公网地址：
  - 前端：`https://gaaiyun.github.io/chainlens/`
  - API：`https://chainlens-production.up.railway.app`
  - 健康检查：`https://chainlens-production.up.railway.app/health`
- 首次 Railway 失败的根因是未配置 DB Variables，服务回退查找不存在的
  `/app/data/warehouse/chainlens.duckdb`。配置变量后部署成功。
- 首次公网查询返回 500 的根因是 Starlette 严格 JSON 编码拒绝结果表中的
  `NaN`。`0dcb72d` 在 API 输出边界把非有限浮点数转换为 `null`，没有修改
  指标计算。
- `2c2312f` 将 GitHub Pages 接到 Railway API，并按 API `ChartSpec` 和结果
  表渲染实时柱图；`f1f69e3` 修复移动端区县长标签重叠。
- 最终 Railway deployment：
  `1d5d9257-aff6-479f-b4bf-a91e8c5853ee`，状态 `SUCCESS`，commit
  `f1f69e3`。
- 最终 Pages workflow：`30201175165`，状态 `success`。
- 公网 API 四场景实测：
  - financing：2 条结论、5 条证据、2 个图表规格；
  - qualification：2 条结论、4 条证据、1 个图表规格；
  - network：2 条结论、3 条证据、1 个图表规格，约 18 秒；
  - region：2 条结论、3 条证据、1 个图表规格。
- 公网 Playwright 验收通过：桌面融资查询和手机区域查询均进入 LIVE 状态，
  CORS 正常，浏览器控制台无错误，图表、证据和结果明细均非空。
- 验收截图：
  `data/outputs/public_acceptance_20260726/desktop-live-final.png`、
  `data/outputs/public_acceptance_20260726/mobile-live-final.png`。
- 最后一次本地验证：
  - `python -m pytest -q` -> `21 passed`
  - `python scripts/check_security.py` -> `[OK] security scan passed`
  - `scripts/test_frontend.py` -> `[OK] frontend smoke passed`
- 运营风险：Railway 当前为试用额度；竞赛正式开放前检查额度。公网 API
  当前是固定四类确定性分析、只读数据和受限 CORS，但还没有用户账号、持久化
  限流和监控告警，若大规模开放需补 API 网关或服务端限流。

### 2026-07-28 · 受控自主分析完成，本地与真实 MySQL 十问通过

- 修复公开输入框“问题变化但返回固定 overview”的根因。专家路由现在只匹配
  融资盲区、资质续期、产业协作网络和区域体检四类高特异性问题，其余进入
  `AutonomousAnalysisAgent`。
- 新增 LangGraph 自主分析状态图：加载 Schema、生成 SQL、安全校验、执行、
  最多两次修复、结果剖析和报告组装。模型只规划 SQL；结论、图表、证据和
  报告数字全部消费数据库执行结果。
- 新增十类已审查 SQL 模板，覆盖经营状态、行业 Top、融资轮次、招投标年度、
  资质年份、地区分布、成立趋势、投资 Top、注册资本区间和企业详情。标准问题
  不调用 LLM；长尾问题使用火山方舟，DeepSeek 只作故障切换。
- 自主 SQL 只允许五个脱敏视图、单条 `SELECT/WITH`、显式字段，统一限制到
  500 行；危险 SQL 和白名单外对象无法执行。空结果明确说明未命中，不生成
  延伸结论。
- API 增加顶层 `sql`、`safe_sql`、`safety` 和结构化错误。缺少长尾问题模型
  配置返回 `503`；SQL 连续修复失败返回 `422`。
- GitHub Pages 前端新增可展开的 SQL、安全改写和 Agent trace，实时结果可下载
  Markdown 报告；错误状态会清空旧结果并说明失败原因。桌面和 390px 手机
  Playwright 回归均通过。
- 新增 `scripts/run_autonomous_acceptance.py`，每题保存完整 JSON、Markdown、
  HTML、PDF 和 PNG。验收产物位于：
  - 本地 DuckDB：`data/outputs/autonomous_acceptance_20260728_local`
  - 真实 MySQL：`data/outputs/autonomous_acceptance_20260728_mysql`
- 真实 MySQL 十问输出：10/10 通过；各题返回行数依次为
  `10, 10, 18, 25, 20, 10, 46, 10, 5, 1`。
- Railway 已通过 stdin 配齐 8 个模型变量，真实值未进入仓库或命令输出；数据库
  5 个变量仍然有效。
- 本轮提交：
  - `3e6d9d7 docs(agent): 定义受控自主分析设计`
  - `4acc6ff feat(agent): 实现受控自主分析运行时`
  - `4d1bf57 feat(web): 展示自主查询与安全轨迹`
- 最新本地验证：
  - `python -m pytest -q` -> `39 passed in 19.76s`；
  - 专项回归：自主 Agent `13 passed`，API `9 passed`；
  - `python scripts/check_security.py` -> `[OK] security scan passed`；
  - `python -m compileall -q app src scripts api_server.py` -> exit 0；
  - `git diff --check` -> exit 0；
  - `scripts/test_frontend.py` -> `[OK] frontend smoke passed`。
- 写入本条时尚未 push 和执行公网最终回归。接手时先看 `git status`、GitHub
  Actions 和 Railway deployment；完成后必须把部署 ID、公网十问和截图结果
  继续追加在本节之后，不另建交接文件。

### 2026-07-28 · Railway 首次自主分析部署失败与就绪检查修复

- `6ba0716` 推送后 GitHub Pages workflow `30358249195` 成功；Railway
  deployment `197eee96-3ad4-48b9-a9e8-4a176fe021e5` 失败。
- Railway 构建完全成功，失败点是 300 秒健康检查超时。部署日志只有
  `Starting Container`，没有 Python 异常；根因是 `api_server.py` 在模块导入
  阶段同步构造 `ChainLensOrchestrator`，远程 MySQL 物化完成前 Uvicorn 端口
  无法打开。旧成功实例 `f8bc99f7-5e5b-4216-81d6-757739d75237` 仍在线。
- 修复为 liveness/readiness 分离：FastAPI lifespan 在工作线程初始化仓库；
  `/health` 立即返回 `pending/initializing/ready/error`，`/ready` 只有数据完全
  可查询才返回 200；查询未就绪时返回结构化 503。
- `railway.toml` 改用 `/ready`，窗口从 300 秒调整为 900 秒。Railway 会让旧
  实例继续服务，直到新实例真正 ready，避免用“假健康”接管公网流量。
- `src/chainlens/warehouse/mysql.py` 新增逐个视图的无敏感信息进度日志，便于
  区分数据库慢、进程崩溃和具体物化阶段。
- 新增生命周期回归测试，验证慢初始化期间 `/health` 在 0.5 秒内响应；API
  专项 `11 passed`，MySQL 适配专项 `6 passed`，全量 `41 passed in 25.04s`，
  安全扫描、编译、diff check 和本次文件 Ruff 均通过。
- 使用 Railway 真实变量的额外初始化测试在 240 秒超时，说明当时 MySQL 链路
  存在明显波动。没有因此删减字段或放宽 readiness；下一步重新部署并观察
  900 秒内逐表进度。

### 2026-07-28 · 自主分析公网验收通过

- 修复后的 Railway deployment
  `630bcb3b-bf6b-4bb1-b7d8-3ac49f886680` 状态 `SUCCESS`，commit `901ba93`。
  `/health` 和 `/ready` 均返回 `status=ready`、`database=mysql`、
  `engine=controlled-agent-runtime`。
- GitHub Pages workflow `30359516030` 成功，commit `901ba93`。
- 新增 `scripts/run_public_acceptance.py`，对生产 API 保存完整响应和 Markdown
  报告。公网 11/11 通过：
  - 十个确定性模板问题均约 0.8–1.2 秒；
  - 长尾“按企业经济类型统计企业数量”真实使用 LLM，7.01 秒返回 40 行；
  - 全部响应均有 safe SQL、安全报告、非空结果、结论、图表、证据、trace
    和 Markdown 报告。
- 公网 API 产物：`data/outputs/public_autonomous_acceptance_20260728`。
- 新增 `scripts/test_public_frontend.py`，真实验证 GitHub Pages -> Railway CORS
  链路。桌面注册资本区间和 390px 手机经济类型查询均通过；SQL 可展开、报告
  可下载、图表/表格/证据非空、浏览器控制台无错误。
- 公网截图和下载报告：`data/outputs/public_frontend_20260728`。
- 截图复核后继续完善表达：常用字段映射为业务中文；折线趋势改为报告首期、
  末期和确定性差值，不再只报告最高点。对应新增单元测试。
- `railway.toml` 增加后端 `watchPatterns`。后续只改 `README.md`、`docs/` 或
  `web/` 不再触发 Railway 数据重载。
- 最终本地质量门：`42 passed in 26.30s`；安全扫描、编译、diff check、
  本次文件 Ruff 和本地 Playwright 均退出 0。

### 2026-07-28 · 最终版本交付状态

- 最终代码 commit：`34919c1`；Railway deployment
  `7b11edfe-0aba-4772-9142-2a7fee39b6c3` 为 `SUCCESS`，builder 为
  `RAILPACK`，`/ready`、900 秒窗口和 5 条 `watchPatterns` 均已实际生效。
- 最终 Railway 日志按顺序显示 `v_enterprise`、`v_bidding`、`v_financing`、
  `v_equity`、`v_qualification` 物化完成，之后 `/ready` 才从 503 转为 200。
- 最终 GitHub Pages workflow `30360700284` 成功，head SHA 为 `34919c1`。
- 最终公网 API 11/11 再次通过：十个模板问题 0.76–1.15 秒；长尾经济类型
  问题使用火山方舟、无修复、7.10 秒返回 41 行。产物：
  `data/outputs/public_autonomous_acceptance_20260728_final`。
- 最终公网桌面/手机 Playwright 再次通过，CORS、SQL 展开、trace、图表、
  12 行移动端预览和 Markdown 下载均正常，控制台无错误。产物：
  `data/outputs/public_frontend_20260728_final`。
- 成立趋势最终线上结论示例：1978 年 1 家到 2026 年 737 家，首末变化 736；
  文案明确说明这不表示期间持续增长或因果关系。该数字来自最终 safe SQL
  结果，不来自 LLM。
- 当前公网入口：`https://gaaiyun.github.io/chainlens/`；API：
  `https://chainlens-production.up.railway.app`。写入本条时功能已可交付。

### 2026-07-29 · 自由问数复合问题审计与首页入口完善

- 用户明确目标是“可以自由问数的 Agent”，因此不能只用十个模板问题验收。
  本轮先对四个未预设复合问题做公网审计，发现并修复三类问题：
  - `Top 20` 被模型遗漏，最终安全门现在强制写入用户要求的 `LIMIT 20`；
  - “成立年份 + 招投标企业数”被成立趋势模板吞掉，跨视图问题现在绕过单域模板；
  - “有融资但没有招投标”被“融资 + 没有”关键词误路由，已改为只匹配明确的无融资短语。
- Railway 真实变量本地复测四个复合问题均成功：40 行多指标聚合、20 行 Top N、
  46 行成立与招投标 JOIN、20 行融资但无招投标 `NOT EXISTS`。
- 前端默认首页已改为“智能制造产业自由问数”，新增 `00 自由问数` 导航和三个
  可点击复合问题示例；固定融资、资质、网络、区域场景仍保留。
- 本节之后需要继续追加全量测试、公网复合问题最终回归、GitHub Pages 与 Railway
  部署结果，不另起交接文件。

### 2026-07-29 · 自由问数最终公网交付

- 后端、前端和文档 commits：
  - `968ddaf fix(agent): 修复复合问数路由与结果上限`
  - `e31cc9c feat(web): 增加自由问数默认工作台`
  - `881df3b docs(ask): 完善自由问数说明与验收`
- Railway deployment `3fcb24ed-2831-448e-b286-2060a381c6ad` 为 `SUCCESS`，
  commit `881df3b`；五个视图物化完成后 `/ready` 返回 200。
- GitHub Pages workflow `30381939123` 为 `success`，commit `881df3b`。
- 最终公网 API 验收 `15/15`：十个模板、一个普通长尾和四个复合自由问数均通过。
  复合问题覆盖多指标平均值、显式 Top 20、成立年份与招投标跨表统计、融资但无
  招投标的 `NOT EXISTS`。产物：
  `data/outputs/public_freeform_acceptance_20260729_final`。
- 模型可能使用 `year/start_year`、`latest_finance_year/latest_financing_year` 等
  等价别名；验收器检查语义列组和 SQL 必备片段，不把正确 SQL 误判为失败。
- 公网自由问数页面桌面和 390px 手机 Playwright 通过：默认标题、`00 自由问数`、
  三个示例按钮、真实 API、CORS、SQL trace、图表、表格和 Markdown 下载均正常，
  浏览器控制台无错误。产物：`data/outputs/public_freeform_frontend_20260729`。
- 本轮最终本地质量门：`44 passed in 19.13s`；全仓 Ruff、安全扫描、编译、
  diff check 和本地 Playwright 均通过。
