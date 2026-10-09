# Phase 2 Agent E2E Observability

2026-10-09。实现使用实际 OpenTelemetry SDK 1.45.1；不通过自行生成随机 trace ID 冒充 SDK span。默认独立本地 JSONL 出口；Langfuse 通过官方 OTLP HTTP/protobuf exporter 接入。

## 接线 API

```python
from finagent.observability import trace_scope, record_event, flush, shutdown

with trace_scope('Task Planning', batch_id=run_id, run_id=run_id):
    with trace_scope('Tool Calling', ticker='NVDA', snapshot_id=snapshot_id):
        # 执行真实业务操作；with 可以直接用于 async 函数。
        result = await operation()
        ids = record_event('Evidence Verification', {
            'status': 'PIT_VERIFIED', 'checkpoint_id': checkpoint_id,
        })
flush(timeout_millis=3000)
shutdown()
```

`trace_scope(stage, **metadata)` 返回真实 `trace_id`（32 位十六进制）、`span_id`（16 位十六进制）与继承的关联 ID。`record_event(stage, metadata)` 创建实际短子 span 并返回相同关联结构；用于已有业务审计事件。`current_correlation()` 提供只读字典副本。ContextVar 与 OTel 当前 span 上下文支持 asyncio 多 ticker 隔离及 `asyncio.to_thread` 继承；子任务应在 ticker scope 内创建。

阶段统一为 Task Planning、Tool Calling、State Management、Evidence Verification、Result Expression。兼容现有 `Plan/Tools/State/Evidence/Output` 和 `Planning/Tool Execution/Result Synthesis`。未知阶段归入 State Management，未知原文不落盘。

业务操作必须包在 scope 内才能测量实际执行持续时间；从 checkpoint 重放的审计事件是短 span，其持续时间不是历史 LLM 请求持续时间。历史真实请求延迟由 `llm_latency_ms` 字段提供，不能把审计重放 span 的 duration 当 LLM 性能。

## 字段与隐私边界

| 字段 | 来源/语义 |
|---|---|
| `batch_id`, `run_id` | 持久批次/作业 ID；子 span 继承 |
| `ticker`, `snapshot_id`, `checkpoint_id` | 股票、不可变数据快照、原生 LangGraph checkpoint ID |
| `trace_id`, `span_id`, `parent_span_id` | SDK 生成与父子关系；不是业务 ID 或 hash |
| `start_time_unix_ns`, `end_time_unix_ns`, `duration_ms` | 实际 SDK 观测墙钟时间；非模拟延迟 |
| `prompt_tokens`, `completion_tokens`, `total_tokens` | 只由 provider usage 返回；缺失时不估计，本地 `llm_metrics` 为 null |
| `llm_latency_ms`, `latency_ms`, `budget_wait_ms` | 实测 LLM 请求、工具耗时、预算等待；不得从 DEMO token 推导 |
| `usage_source`, `llm_called` | `PROVIDER` / `NOT_CALLED` 等明确来源；DEMO 无 LLM 调用 |
| `retry_count`, `attempt`, `attempts` | 实际工具重试与任务尝试次数；调用方提供 |
| `cache_hit`, `resumed`, `recovery_result` | 缓存实际命中、checkpoint 实际恢复与受控结果码 |
| `cost_usd` | 仅 provider 已返回费用；无返回则 null，不自行估算 |

仅白名单类型化字段被接收；不支持任意字典、自由文本、HTTP header、URL、原始 prompt、完整财务文档或 provider exception body。字符串仅允许短受控标识符；明显密钥/授权串拒绝。数值要求有限、非负；token 必须整数；bool 不被误认为 token。异常 span 仅记录 ERROR 状态，不启用 SDK 自动 exception message/stacktrace。Resource 不从 `OTEL_RESOURCE_ATTRIBUTES` 导入任意环境字段。文件新建权限为 0600，`artifacts/` 已被 Git 忽略。

关联 ID 同时映射 `langfuse.trace.metadata.*`，run_id 映射 `langfuse.session.id`，每个子 span 都重复受控关联字段，满足 Langfuse 查询所需传播。Provider generation 使用 `gen_ai.usage.input_tokens/output_tokens` 与 `langfuse.observation.type=generation`；未设置输入/输出内容属性。

## 配置与降级

默认 `FINAGENT_TRACE_PATH=artifacts/traces/worker.jsonl`。Langfuse 仅当 `FINAGENT_LANGFUSE_ENABLED=true` 且 `LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY` 均存在时启用。`LANGFUSE_BASE_URL` 默认 EU `https://cloud.langfuse.com`；自部署可配置 base URL。认证只进入 HTTP 请求头；不写入 trace。OTLP endpoint 是 `/api/public/otel/v1/traces`，启用 `x-langfuse-ingestion-version: 4`。

本地 SimpleSpanProcessor 与独立远端 BatchSpanProcessor 同时接收 span；远端队列 256、每批最多 32、HTTP 超时 2 秒，无业务等待远端上传。远端 HTTP/认证失败或无密钥不抛入业务；本地文件写失败也不抛入业务。`local.failures` / `remote.failures` 保存进程内实际导出失败计数，远端状态 `CONFIGURED_UNVERIFIED` 仅表示配置成功。Langfuse 导出是 best effort：进程终止、队列溢出会丢远端 span，持久业务审计仍应保留在数据库中。`flush` 成功不证明服务器 ingestion 或 UI 可见；业务结束应显式 flush/shutdown。

## 实际验收证据

执行 `.venv/bin/python -m pytest tests/test_observability.py -q`：**9 passed in 0.91s**。覆盖五阶段真实 SDK span/父子关联、async 两股票隔离与线程继承、严格字段过滤、缺失 token null、异常正文不落盘、SDK/provider 初始化故障 fail open 且业务异常保留、本地写故障 fail open、实际 HTTP 连接 `127.0.0.1:1` 不可达时远端 fail open、本地仍导出、无凭据降级。

本地 SDK 烟测已实际执行，文件 `artifacts/traces/sdk-smoke.jsonl` 含 6 span。trace_id `34b64d6b92ee0a337721c9d0d637c4eb`；run_id `434a1245-f7b5-448e-9f5c-f28693928ea0`；root span_id `75be73f056c6649a`。其 snapshot/checkpoint 明确标为 `SDK-SMOKE-DEMO` / `SDK-SMOKE-NOT-WORKFLOW`，仅用于 SDK 出口验收，**不是完整真实数据工作流或 Langfuse 在线 Trace**。所有 LLM 指标为 null。完整 Worker trace 应以主 Agent 实際运行产物为准。

状态：本地 SDK 单元验收 **PASSED**；Langfuse 网络不可达降级 **PASSED**；Langfuse 真实服务 ingestion/UI **UNVERIFIED**，本次未使用有效服务凭据；真实 LLM token/费用及 latency 验收 **UNVERIFIED**，测试中的 provider usage 数字为测试 fixture。

## 官方资料

- [OpenTelemetry Python instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/)：SDK TracerProvider / span / processor 使用方式。
- [Langfuse OTLP 接口及字段映射](https://langfuse.com/integrations/native/opentelemetry)：HTTP endpoint、Basic Auth、v4 ingestion header、trace metadata 与 GenAI usage；查阅日期 2026-10-09。
