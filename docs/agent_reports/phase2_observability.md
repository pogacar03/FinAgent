# Phase 2 observability execution report

所有权：新增 `backend/finagent/observability.py`、`tests/test_observability.py`、`docs/OBSERVABILITY.md`、本报告；未修改既有核心、依赖、`.env`、Compose；依赖安装由主 Agent 完成。未提交 Git。

已读 AGENTS.md、V2 绑定决策以及 agents.py、worker.py、storage.py 实际实现。现状发现：旧 audit 事件已有部分 provider usage 与工具累计延迟，缺少实际 SDK span；Worker checkpoint 重放事件必须区分真实操作耗时和审计复制耗时。已向主 Agent 冻结接线 API，由主 Agent负责 Worker / Store.event 集成。

实现：实际 OpenTelemetry SDK 1.45.1；本地 JSONL SDK exporter；可选官方 OTLP HTTP/protobuf Langfuse exporter；五阶段标准化；ContextVar 关联；父子 SDK IDs；严格字段白名单；禁原始 prompt、key、doc、provider 异常；异常不自动记录正文/stack；本地/远端独立 fail open；远端有界队列。

实际执行：

- `.venv/bin/python -m pytest tests/test_observability.py -q`：9 passed in 0.91s。
- `PYTHONPATH=backend .venv/bin/python` 调用实际 SDK：6 span 导出到 `artifacts/traces/sdk-smoke.jsonl`，trace `34b64d6b92ee0a337721c9d0d637c4eb`。这是 SDK 烟测 DEMO，非完整研究工作流，指标 null。
- 实际 HTTP localhost:1 不可达测试：业务完成，本地 span 保存，远端 failures=1。

PASSED：SDK local spans / stage / privacy / async correlation / exporter failure fallback。

PARTIAL：工作流集成由主 Agent 负责；本报告不能代替完整 Worker E2E 验收。

UNVERIFIED：Langfuse live ingestion/UI，无有效凭据；真实 LLM 指标，无实际外部 LLM 请求。无伪造 Trace URL、token、节省或加速声明。

注意：JSONL 同步写入会计入工作流性能；必须由相同 instrumentation/config 的 Benchmark 比较。远端 best effort，进程硬终止/队列溢出可能丢 span，数据库审计仍需保留。flush 返回 true 不能证明 Langfuse 接收/展示成功。更多字段与配置见 `docs/OBSERVABILITY.md`。
