# FinAgent 当前验收状态（2026-10-09）

第二阶段工程实现已集成；真实数据闭环为 PARTIAL。所有状态基于源码审查、实际命令输出或指定 GitHub Actions 运行，不以本文件本身证明通过。

| 范围 | 状态 | 实际证据／缺口 |
|---|---|---|
| 原有工程基线、全部原有约束 | PASSED | 原交付98测试及后续15 CI guards原文件完全未改；重新独立运行113通过，基线提交1bcedb6 |
| 当前完整Python离线测试 | PASSED | 主调度实际149 passed in 7.16s；独立复审149 passed in 7.31s；没有跳过测试 |
| 前端类型检查、生产构建、来源检查 | PASSED | npm run check:provenance 与 npm run build（包含tsc --noEmit）退出0；前端源文件未改 |
| PostgreSQL集成及独立API/Worker E2E | PASSED | 本地临时PG16：8并发首启、原生checkpoint、worker重启、12并发领取8唯一任务、旧租约写入拒绝；run d6bc85be-e14f-46d3-ac5e-a31ae9abaa33 |
| SQLite独立进程E2E | PASSED | scripts/e2e_demo.py退出0，10唯一名单/3角色/冻结半年DEMO回测/重启及缺SA处理 |
| 第一阶段Linux Docker/Compose CI | PASSED | 真实既有运行37791876438/37791940279；结果及SHA见CI_RESULT.json；后续基线1bcedb6的push37792833219与PR37792841308亦success |
| 第二阶段新源码Linux Docker/Compose CI | UNVERIFIED | 当前准备独立phase2分支，必须等待该新SHA实际CI verdict成功；旧绿色不能证明新代码 |
| Mac本地Docker | UNVERIFIED | 未安装、未执行；保留本地SQLite/PG运行方式，不需要Docker Desktop |
| NVDA原始发行人财务读取与日期上界校验 | PASSED | 实际原始财报HTTP200、FY2025 GAAP解析；仅保守日期边界，不表示精确时戳／不可变当年档案 |
| 最小真实数据闭环 | PARTIAL | 固定决策2025-02-28纽约23:59:59，原始来源/响应/快照/政策算术/门控/无网络回放已实际执行 |
| 原始SEC 10-K适配、本次读取 | BLOCKED | 缺可识别联系人SEC_USER_AGENT；未伪造身份；本次使用NVIDIA原始公告 |
| 严格历史估值及含公司行动半年总回报 | BLOCKED | Nasdaq历史价格200但0记录，原始可用性及动作完整覆盖缺失；结果UNAVAILABLE/null |
| 历史价格PIT、公司行动完整性、精确发布时间 | UNVERIFIED | Yahoo二级报价仅价格诊断；Nasdaq观察股息不等于完整行动证明；没有升级REAL attestation |
| 可信历史分析师一致预期／全估值法 | BLOCKED | 未取得可信PIT预测；仅明确假设的窄PE算术，不强行DCF |
| 五阶段OpenTelemetry E2E、本地隐私与故障降级 | PASSED | 实际PG research trace 6089cc0da86f41ebd80b16d554edc35f，105 spans；9 SDK测试；源码白名单，不导出prompt/key/原文 |
| Langfuse集成 | PARTIAL | 官方OTLP HTTP exporter及配置已接线，有限队列／fail-open；未提供有效服务凭据 |
| Langfuse在线ingestion/UI、真实LLM指标 | UNVERIFIED | 0真实LLM调用；Token、费用、LLM latency为null；mock验证不能升级在线状态 |
| 串行／有界并行DEMO Benchmark | PASSED | 最终原始JSON/CSV保留，每种策略×冷启动/HTTP幂等复用/真实中断恢复×3；18观测、0失败 |
| 真实LLM性能及真实投资结果 | UNVERIFIED | 当前离线指标不代表LLM加速、成本节省或Alpha；没有可信真实总回报 |

## 可复现证据

- [工程基线及文件哈希](ENGINEERING_BASELINE.json)：真实Git作者Yu，未伪造本地身份；原12个测试文件与22个冻结领域／前端文件均未改。
- [CI配置与运行说明](CI.md)、[既有真实CI证据](CI_RESULT.json)。新提交CI实际结果将独立记录，禁止混用旧SHA。
- [真实数据与PIT报告](REAL_DATA_VALIDATION.md)：执行20261009T025343313311Z，原始响应在artifacts/real-pilot；源URL/时间/hash/重放命令已保存。
- [追踪字段与降级](OBSERVABILITY.md)、[实际PG Worker trace样例](TRACE_SAMPLE.json)：batch_id为父research run ID；backtest拥有自己的run_id；schema v1不变。
- [Benchmark及原始记录](BENCHMARK.md)：披露同输入/模型/环境及源码hash；每次完整观测保留，无可靠并行加速结论。
- [独立复审](agent_reports/phase2_reviewer.md)：复现两个新工具缺陷、交回原责任Agent修复、独立重测；无剩余具体源码阻断项。

## 调度、Git与范围

主调度拆分三个独占模块，最多三个子Agent同时工作；观测模块完成后启动独立Sol High审查。真实数据Agent使用继承配置，观测请求gpt-6.1-sol/medium，Benchmark请求gpt-6-luna/max，审查请求gpt-6.1-sol/high。工具没有独立Fast开关，不能独立证明后端计费路由。实际文件、命令和问题在各角色报告与EXECUTION_LOG中。

基线分支codex/ci-linux-compose仍以draft PR#1等待集成；第二阶段codex/phase2-validation基于其已验证提交。提交使用已认证GitHub API，不修改main、不伪造Git作者。原contracts/data/quant/backtest/api/config和前端未改；仅worker、storage、agents增加观测元数据，新增独立数据pilot与Benchmark工具，没有大型领域重构。首次缺失的CODEX_PARALLEL_START.md由architect生成替代文件，原始缺失事实保留。

DEMO价格、财务、名单、交易日历和收益路径均为SYNTHETIC。缺SA原名单保持UNAVAILABLE；历史LLM知识污染无法证明消除；单NVDA pilot没有补齐另外九只，不等同完整真实Top-10工作流。schema v1为加锁bootstrap，未来结构变动仍需版本迁移；LLM预算是每worker进程。第一阶段全部原始审查/测试记录见agent_reports与EXECUTION_LOG。
