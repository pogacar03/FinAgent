# FinAgent 实际交付状态

验收日期：2026-10-08，Asia/Shanghai。项目：`/Users/yu/Desktop/FinAgent/finagent_codex_starter`。

**离线 DEMO MVP 已实现并通过本地应用、数据库、浏览器与测试验收。REAL 的输入验证和执行链路通过离线测试；真实市场/模型调用、真实业绩以及 Docker 启动未验证。** 每项状态来自实际代码与执行结果，不能把未执行项视为通过。

## 实际实现

| 模块 | 实现与证据 | 状态 |
|---|---|---|
| 架构与 Schema | 深度不可变 Pydantic contracts、哈希、时间/证据/名单约束；14 contract tests | 已实现 |
| 后端 API | 提交/查询/历史/个股/审计/回测/核验榜单；OpenAPI；请求冲突409、畸形导入422 | 已实现 |
| 持久化 worker | 独立进程、PostgreSQL SKIP LOCKED、随机租约 fencing、心跳、过期接管、有限重试、不可变工件 | 已实现并验证 |
| 首次启动 | PG 同连接事务 advisory lock；8个同时初始化无DDL竞态；SQLite串行 bootstrap | 已验证 |
| 数据与 PIT | DEMO显式SYNTHETIC；REAL sealed bundle、原始来源、可用时点、用户核验声明；无依赖时不可用 | 已实现；真实覆盖待提供 |
| 量化筛选 | 明确缺项、最少有效因子、至多30、确定性排名、行业上限、十只等权、不足不填充 | 已实现并验证 |
| Multi-Agent | 实际 LangGraph fan-out/fan-in，三个私有上下文、只读证据、结构化汇总、最多一轮复核 | 已实现并验证 |
| 消融 | quant_only / single_agent_skills / multi_persona / multi_persona_debate | 已实现并验证 |
| 模型访问 | OpenAI-compatible HTTP结构化预测、Python计算估值、匿名证据、有限重试、跨股票共享并发/频率预算 | 离线模拟已验证；真实调用待密钥 |
| 估值与入场 | FACT与Assumption分开，EPS×PE及受限DCF，50/30/20，安全边际；NVDA199/159.20合成例 | 已实现并验证 |
| 原生检查点 | SQLite/PostgreSQL官方异步 saver，分支恢复、已完成个股复用、模型/版本/输入身份固定 | 已实现并验证 |
| 半年回测 | 下一合格NY开盘，六日历月，同一窗口，拆股/分红/现金/成本/滑点；未成熟PENDING | 已实现并验证 |
| 限价次实验 | 等待期拆股调整，包括晚SA公布前动作；未成交现金与同信号机会成本 | 已实现并验证 |
| 回测数据版本 | 每次评估固定执行bundle；允许未来新增记录，拒绝改写原决策Universe/入选股票输入；不重做LLM | 已实现并验证 |
| SA榜单 | Bearer导入、来源/发布时间/10只验证、单独核验声明、追加修订、回测固定版本、缺失为null/UNAVAILABLE | 已实现；原始榜单未提供 |
| 跨期汇总 | Python聚合有效/缺失期、胜率、超额百分点、观察窗口NAV和期末回撤，混合/重叠/重复拒绝 | 已实现并单测；未提供真实跨期样本 |
| 中文前端 | 提交/进度/历史、Top10、角色报告/证据/假设、图表、PIT/合成标签、固定SA来源、审计 | 实际浏览器验收通过 |
| 审计 | 带ID/时间的Plan/Tools/State/Evidence/Output与实际checkpoint身份；不保存原始提示/密钥 | 已实现并E2E验证 |

## 最新验收结果

以下命令均从项目目录运行，前端命令从 `frontend/` 运行。

| 命令/检查 | 实际结果 |
|---|---|
| `.venv/bin/python -m pytest -q` | **98 passed in 4.95s**，无失败/跳过 |
| `npm ci` | exit0，锁定依赖安装成功 |
| `npm run check:provenance` | 固定SA、显式无榜单、旧缺字段/缺payload案例通过 |
| `npm run build` | TypeScript `--noEmit` + Vite8.3.4生产构建通过 |
| `npm audit` | **0 vulnerabilities** |
| `.venv/bin/python scripts/e2e_demo.py` | SQLite：独立HTTP/worker、真实图、10只、3角色、worker重启、半年合成回测、SA不可用；exit0 |
| `.venv/bin/python scripts/postgres_smoke.py` | 独立PG16临时集群：8并发首次启动、原生checkpoint、HTTP/worker重启、12竞争worker唯一领取8任务、旧租约写入拒绝；exit0 |
| `.venv/bin/python -m compileall -q backend scripts tests` | exit0 |
| Compose YAML解析/环境合并/容器数据路径 | 静态验证通过；未运行容器 |
| `git diff --check` | exit0 |
| 实际浏览器 | 点击提交→完成→10只→NVDA三报告→回测；520/1280视口检查；最新代码重启后恢复结果与固定来源提示 |

SQLite E2E run：`c0c74fac-af67-4215-a621-42cbe6c65751`；PG E2E run：`f5654ecb-f75f-415a-8a81-27b46d927aa5`。DEMO样例仅验证工程链路，不代表投资优势。最终截图：`artifacts/finagent-final.jpg`；E2E JSON：`artifacts/e2e_report.json`（每次脚本执行覆盖）。

原先审查的八项问题和最终复审的六项问题均已定向修复，详见 [最终审查报告](agent_reports/final_reviewer.md)。关键修复均有先失败后通过的回归证据：幂等重试、未来执行数据、PG首启、动作PIT、等待期限价拆股、共享HTTP预算。

## 实际子 Agent 调度

| 角色 | 实际工具请求模型 / effort | 任务与提交 |
|---|---|---|
| architect | gpt-6.1-sol / high | 冻结接口、数据库/状态机/验收；真实contracts+14测试+文档 |
| data_engineer | gpt-6-luna / max | provider代码、PIT/动作/榜单、测试、问题清单；随后定向修复 |
| agent_engineer | gpt-6.1-sol / medium | 原生graph、隔离/复核/恢复、共享预算、测试、问题清单 |
| frontend_engineer | gpt-6-luna / max | 中文UI、API、来源、依赖修复、构建/审计、问题清单 |
| quant_engineer | gpt-6.1-sol / high | 筛选/估值/冻结/回测、拆股等待修复、测试、问题清单 |
| backend_reviewer | gpt-6.1-sol / high | 独立源码审查、真实复现、定向复测和最终审查报告 |
| 主调度 root | 当前会话模型，由宿主配置 | 管理依赖/文件所有权、API/DB/worker、集成、故障注入、PG/浏览器/E2E、文档 |

架构先完成，再按依赖分批编码；最多同时三个子Agent，所有文件按归属编辑。没有独立Fast开关，未声称设置Fast；工具请求模型不等于可独立核验的后台计费路由。详见 [执行日志](EXECUTION_LOG.md) 和 [各角色报告](agent_reports/)。

## 可运行入口与交付位置

当前保留最新本地API8000、worker、前端5173，打开 <http://127.0.0.1:5173>。完整安装/三终端/Compose命令见 [README](../README.md)。重启和复验不需要聊天上下文。代码在本地feature分支 `codex/finagent-parallel` 工作树；本机Git作者身份未配置，未伪造身份或声称提交。

原始包未包含 `CODEX_PARALLEL_START.md`，在项目/Desktop搜索后由architect依据用户指令及V2生成明确标注的替代文件；无法声称执行未提供的原始内容。

## 未执行、缺失与范围限制

- **Docker验收门槛尚未验证**：本机未安装Docker，未执行 `docker compose up --build`。四服务文件已交付并静态解析；其等价本地PostgreSQL/HTTP/worker路径实际运行。不能据此宣称容器启动门槛已满足。
- 未提供真实行情/历史Universe/财务原文/公司行动、模型密钥或可核验SA原始名单。REAL接口以用户sealed bundle及声明为入口，不独立认证声明；离线REAL测试使用明确虚构fixture，无真实收益结论。
- SEC原始申报元数据适配器已实现并离线测；实时获取未执行。历史财务取值需要原始PIT输入，今天Company Facts不替代历史。
- DEMO会话为工作日合成日历（包括可能真实休市的日期）。REAL依赖输入SPY会话、原始价格及完整动作覆盖；系统不独立认证交易所/退市覆盖。动量使用原始价格代理并披露口径；不可冒充正式已验证SA Quant评级。
- 历史LLM训练记忆污染无法证明消除，回放冻结时间是模型决策时点，实际执行时间在审计记录中；不得宣称真实前瞻收益。
- 汇总回撤仅观察期末，缺期不可称连续五年净值；当前前端显示单期比较，跨期函数未扩展成五年仪表盘。
- Langfuse/外部OpenTelemetry导出、Redis缓存、真实供应商成本与吞吐基线未实现/未测；本地持久审计可用。不存在凭空性能提升百分比。
- schema v1为加锁bootstrap，后续结构变更仍需显式版本迁移。预算是每worker进程；多进程需分配供应商总配额。

## 后续基线测量流程

同一输入bundle/模型/策略/硬件下，每种消融至少运行三次，保留任务ID、墙钟总时间、每股票graph延迟、供应商返回tokens、重试/失败、checkpoint复用数、DB claim延迟、有效股票/周期覆盖；分别报告冷启动与恢复结果。没有真实调用时只报告离线工程时间，不推算实际LLM成本或投资提升。版本/许可证选择见 [REUSE_REGISTER](REUSE_REGISTER.md)。

## CI-only 后续交付（2026-10-08）

新增 `.github/workflows/ci.yml`、`scripts/ci/docker_check.sh`、`scripts/ci/compose_smoke.py`、`tests/test_ci.py` 和 [CI运行说明](CI.md)。工作流覆盖Python测试、前端构建、Linux Docker镜像与Compose/API/Worker/PostgreSQL集成；失败收集日志、上传证据、返回非零。聚合CI verdict只在全部真实job成功时认定该SHA的Linux容器VERIFIED。此前本地开发命令继续可用，无需安装Docker Desktop。

CI执行状态：**UNVERIFIED / NOT_RUN**。本地没有Docker且仓库没有GitHub remote，未提供实际Actions run URL；尚未触发远端CI。脚本mock测试/本地E2E不能改变此状态。核心业务源码、前端源码、现有Dockerfiles/Compose/Makefile未改，按本轮开始前后SHA256比较确认。最新追加测试证据和复审见执行日志；上文98项是原交付时的历史测试结果。
