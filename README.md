# FinAgent

半年度美股 Top10 可审计研究原型。中文界面，独立 asyncio worker，真实 LangGraph 三角色编排，冻结名单后执行确定性半年回测。

**DEMO 的股票价格、财务数据、预测假设和收益路径全部是 SYNTHETIC，不能当作真实历史业绩。** 无 Seeking Alpha 原始核验榜单时仅显示不可用。REAL 不会自动替换为演示数据。

## 本地运行

需要 Python 3.11+、uv、Node 22.12+ 与 npm。下面的本地路径使用 SQLite，适合开发与离线验收。生产配置使用 PostgreSQL。

```bash
cd /Users/yu/Desktop/FinAgent/finagent_codex_starter
uv venv --python python3.11 .venv
uv pip install --python .venv/bin/python -r requirements.lock
cd frontend
npm ci
cd ..
```

分别在三个终端中运行：

```bash
PYTHONPATH=backend .venv/bin/python -m uvicorn finagent.api:app --host 127.0.0.1 --port 8000
```

```bash
PYTHONPATH=backend .venv/bin/python -m finagent.worker
```

```bash
cd frontend
npm run dev -- --host 127.0.0.1
```

打开 [界面](http://127.0.0.1:5173)，选择 2025-H2、DEMO，提交研究，等待完成，点开个股证据，再执行半年回测。[OpenAPI](http://127.0.0.1:8000/docs) 提供交互式请求 Schema。HTTP 进程不执行后台研究；只有 worker 开启时排队任务才会推进。

无密钥离线演示脚本会启动独立 HTTP 和 worker 子进程、提交研究、重启 worker、回测并核验结果，然后关闭自己的子进程：

```bash
.venv/bin/python scripts/e2e_demo.py
```

## Docker / PostgreSQL

Mac 开发继续使用上面的本地运行方式，不需要安装 Docker Desktop。容器构建与 Compose 集成由 GitHub Actions Linux Runner 验证，详见 [CI 运行说明](docs/CI.md)。Linux CI已实际通过首次容器构建/集成验收，证据见 [CI_RESULT](docs/CI_RESULT.json)。Mac本地容器仍为 **UNVERIFIED / 未执行**；后续提交以其实际CI结果为准。

已有 Docker 的 Linux/其他环境可在项目目录运行：

```bash
docker compose up --build
```

Compose 定义 postgres、api、worker、frontend 四个服务。前端端口 5173，API 8000。服务首次启动会执行幂等 schema v1 bootstrap；未来结构变更须添加显式版本迁移。PostgreSQL 数据使用命名 volume。LLM HTTP 请求共享 `LLM_CONCURRENCY` 并发上限与 `LLM_MIN_INTERVAL_SECONDS` 最短发起间隔，重试也遵守预算。检查点采用官方 PostgreSQL saver，SQLite 检查点仅用于本地开发。

`.env.example` 列出配置项；不要把密钥贴到聊天或提交到 Git。本地运行通过环境变量配置，可使用 `uvicorn --env-file .env` 或 shell 导出；worker 可在启动前导出相同变量。Compose 会读取 `.env`。本地示例 PostgreSQL 密码只能用于隔离演示。

## 接口

- `POST /api/runs`：`{"period":"2025-H2","mode":"DEMO","research_mode":"multi_persona"}`。
- `GET /api/runs` 与 `GET /api/runs/{id}`：历史任务、持久化状态、进度。
- `GET /api/runs/{id}/picks`：冻结 Top10 或不足原因。
- `GET /api/stocks/{ticker}/research?run_id=...`：角色观点、假设、证据与估值。
- `GET /api/runs/{id}/audit`：Plan / Tools / State / Evidence / Output 审计。
- `POST /api/backtests`：`{"run_id":"...","policy":"PRIMARY"}`。
- `GET /api/backtests/{id}`：任务状态及独立回测结果状态。
- `GET /api/benchmarks/sa/{period}`：榜单可用性。
- `POST /api/benchmarks/sa`：设置 `BENCHMARK_IMPORT_TOKEN` 后以 Bearer token 导入本地核验榜单。导入不自动证明来源真实性。普通 BenchmarkList 会保留为未核验；核验导入使用 `{"list": {...}, "verification_evidence": {"verified_by": "...", "verified_at": "2026-10-08T10:00:00Z", "evidence_uri": "https://...", "notes": "原文与发布时间核对记录"}}`。修订追加为不可变版本，回测提交时固定所选版本。

相同研究请求与版本配置自动复用任务；回测的默认 as_of 在提交时解析，因此新的当前评估可生成新任务，显式相同 as_of/榜单版本保持幂等。任务保存不含密钥的执行版本、模型与数据 bundle 指纹；worker 配置漂移时拒绝执行，恢复时重载已保存输入。显式回测 idempotency_key 的相同请求会复用首次解析的评估时间、榜单和数据版本；不同请求返回 409。REAL 回测可绑定追加未来行情的独立执行数据版本，但必须保持原始决策时点的 Universe 和入选股票研究输入一致；改写历史输入会被拒绝。数据库租约带随机 token、过期回收和心跳；旧 worker 无法提交新结果。已完成个股研究和冻结信号不可覆盖。

## 数据与研究边界

Compose 中 `./data` 挂载为 `/data`：将 bundle 放在 `data/real/bundle.json`，或设置 `REAL_DATA_PATH_CONTAINER=/data/你自己的文件.json`。本地 `REAL_DATA_PATH` 使用主机上的 JSON 文件路径。

REAL 的输入配置与验证格式见 [PROVIDERS](docs/PROVIDERS.md)。需要原始来源、可用时间、截止时点、PIT 核验、币种、拆股口径、公司行动覆盖。缺少这些依赖时返回 UNAVAILABLE/验证失败，不产生虚构 REAL 价格和业绩。公开 SEC 原始申报获取与结构化财务研究分开；今天的公司概览不能冒充历史数据。

DEMO 使用合成日期与交易会话，只验证工程链路、信息可用性约束和账本规则。真实会话及退市覆盖需由真实数据 bundle 提供。PIT 校验不能保证消除大模型的训练记忆污染；历史 LLM 研究不能据此宣称已证明投资优势。

缺 EPS 修正不补零伪装五因子；财务无效可弃权；不足十只或行业约束不足时不生成完整信号。主要实验为十只等权、冻结后下一个可交易开盘、六个日历月、同起止窗口与公司行动口径。限价建仓实验独立核算未成交资金与现金拖累。

NVDA 示例中的三角色 190/240/160、目标 199、20% 安全边际下入场阈值 159.20 都是虚构测试数字。

## 测试与交付记录

```bash
.venv/bin/python -m pytest -q
cd frontend && npm run check:provenance && npm run build && npm audit
cd ..
.venv/bin/python scripts/e2e_demo.py
# 已安装 PostgreSQL 16 时；否则通过 PG_BIN 指定 bin 目录
.venv/bin/python scripts/postgres_smoke.py
```

实际通过/失败、环境限制和未完成项见 [STATUS](docs/STATUS.md)。每个子 Agent 的模型请求、文件、测试命令与问题清单在 [agent_reports](docs/agent_reports/)，调度记录见 [EXECUTION_LOG](docs/EXECUTION_LOG.md)。

[架构与接口](docs/ARCHITECTURE_FROZEN.md)、[并行文件归属](CODEX_PARALLEL_START.md)、[量化政策](docs/QUANT_POLICY.md)、[Agent 运行时](docs/AGENT_RUNTIME.md)、[版本与许可证](docs/REUSE_REGISTER.md)。未复制第三方框架仓库，未使用 vectorbt 或交易执行系统。Langfuse 外部追踪尚非必需依赖；本地数据库始终保存审计事件。

## 可测量的工程指标

用同一数据/模式/硬件重复运行，记录整体耗时、每 ticker graph 延迟、P95、重试和失败数、恢复时复用数量、DB claim 时间与覆盖股票数。LLM 成本与 tokens 仅使用供应商返回的实际统计；不从假定价格或估计 token 编造改进率。投资比较要公开有效期数、缺失期数和原始来源，不把缺期资金曲线称为连续五年结果。
