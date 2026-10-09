# NVDA 真实数据验证记录（第二阶段）

整体 **PARTIAL**。2026-10-09 已实际请求网络、保存原始响应、解析发行人财务、执行时点门控与估值政策算术，并运行半年价格诊断。严格历史估值及含公司行动的总回报仍为 `UNAVAILABLE`，不能宣称真实 Top-10 E2E 已通过。

本次决策时点固定为 `2025-02-28T23:59:59-05:00`，财务期末为 2025-01-26。只研究 NVDA；没有添加虚构的另外九只股票，没有创建或放宽 `FrozenSignal`。未调用 LLM，没有模型生成的财务事实或投资结论。

| 验收项 | 工程状态 | 实际证据／限制 |
|---|---|---|
| 原始发行人财务读取、GAAP 表格解析、日期边界校验 | PASSED | HTTP 200；财务模型仅标识下述保守日期边界政策 |
| 精确原始发布时间及当年不可变页面档案 | UNVERIFIED | 发行人页面只提供日期；当前下载内容不是 2025 年当时的存档 |
| 原始 SEC 10-K 自动读取 | BLOCKED | 本次未配置可识别联系人的 SEC_USER_AGENT；未伪造身份，采用发行人原始财报公告 |
| Nasdaq 原始历史价格 | BLOCKED | HTTP 200 但 `totalRecords=0`、rows=null；不会把 HTTP 成功当作数据完整 |
| 发行人历史价格页面 | PARTIAL | 实际终版请求 HTTP 200；仅取得动态页面壳，没有拿到当年完整报价档案；前期探测另有 403 |
| 历史价格 PIT、原始未调整价格口径、交易所日历证明 | UNVERIFIED | Yahoo 二级接口返回报价，但没有历史首次可用、修订档案及完整口径证明 |
| 公司行动完整覆盖 | UNVERIFIED | Nasdaq 两条已观察股息，不证明所有拆股、股息以及历史首次可用性；coverage_verified=false |
| 正式历史估值与半年总回报 | BLOCKED | API 风格结果为 UNAVAILABLE，目标、入场价及总回报为 null |
| 无网络快照回放与防篡改测试 | PASSED | 每个原始响应 SHA-256、来源类别与 HTTP 状态检查；从 bytes 无条件重算全部领域字段 |

## 观测、假设及诊断的边界

[NVIDIA 原始财报公告](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-fourth-quarter-and-fiscal-2025) 标注发布日 2025-02-26。程序读取 FY25 **GAAP** 单元格：收入 130,497 百万美元、净利润 72,880 百万美元、摊薄 EPS 2.94 USD/share。FY24 收入 60,922 百万美元用于确定性计算收入增长率；利润率也从已报告数值计算。没有使用当前 company-facts、当今行情、模型记忆或 Non-GAAP EPS 填补缺失。EPS 口径是公告中 2024 拆股后单位。

发布日期只精确到天。程序使用发行人 Pacific 时区该日结束后的午夜作为**可用时间上界** `2025-02-27T08:00:00Z`，明确字段 `publication_precision=DATE_ONLY`、`availability_policy=DATE_BOUND_NEXT_PACIFIC_MIDNIGHT_NOT_EXACT_RELEASE_TIMESTAMP`。这个上界早于本次决策。财务 snapshot 的 PIT_VERIFIED 限于此保守日期边界，绝不表示知道精确 SEC 接受时间或拥有不可变当年档案；决策早于上界必须拒绝。

窄 PE 政策计算复用现有 `quant.target_from_assumptions`：已报告 EPS × (1 + 截断到 30% 的收入增长) 得到假设 EPS 3.822，再乘**假设** PE 20，算术结果 76.44，20% 安全边际阈值 61.152。两项均保存 `kind=ASSUMPTION` 和来源哈希；没有可信历史分析师预测，因此不是一致预期，不强行做 DCF。它只在 `unvalidated_policy_calculation` 中显示；正式 `valuation.target_12m/entry_price` 仍为 null。

[Nasdaq 股息原始接口](https://api.nasdaq.com/api/quote/NVDA/dividends?assetclass=stocks) 返回 2025-03-12、2025-06-11 两个 ex-date，各 0.01 USD/share。程序明确区分除息日、公告日和支付日，不把仅有股息列表当作完整公司行动证明。2025-09-11 的下一次股息在本次退出之后。

[Yahoo chart 二级响应](https://query1.finance.yahoo.com/v8/finance/chart/NVDA?period1=1740700800&period2=1757116800&interval=1d&events=div%2Csplits) 的原始 quote.open 支持独立价格诊断：2025-03-03 开盘 123.51000213623047，2025-09-03 开盘 171.05999755859375。实际 `_holding` 算术给出价格变动 0.3849890259892963，标为 **UNVERIFIED / PRICE_ONLY_CHANGE**，不含股息、未认证拆股完整性，不能视作持仓总回报、FinAgent 投资收益或 Alpha。直接忽略 adjclose，绝不把调整价和 raw-action 口径混用；当前接口口径仍未认证。实际 total_return=null。报价的 available_at 保存为本次获取时间，不能伪装成 2025 年收盘时就有的已认证快照。

## 实际终版执行

- 执行 ID：`20261009T025343313311Z`（2026-10-09 10:53:43 Asia/Shanghai）。
- Snapshot ID：`real-pilot:0a092eec4516ce585a9512d0d789dbb858bae74e2bc8b615c45aa9ff40b112b6`。
- 记录：`artifacts/real-pilot/20261009T025343313311Z/execution.json`，五份原始响应均保存为内容哈希命名 `.raw`，目录由 Git 忽略。
- 每个来源保存 source_url、resolved_url、source_class、fetched_at、http_status、content_sha256、snapshot_id、raw_file、服务器 Last-Modified（可能缺失）。版本记录 Python、平台、实际 Git HEAD（无提交则 null）与本模块/量化/回测/契约源文件 SHA-256。
- 财务原始响应 SHA-256：`7e80228d2e31817b9cd86de3faa21c95dff2e61c4c4520c63e06e8b3b72218c5`。
- Nasdaq 价格 SHA-256：`ca76c37333145328887f83c79e594b23ffbe4fa37aed1c30bd2efb0662ce4a60`。
- Nasdaq 股息 SHA-256：`51fe8e28b753bd25aca7092f373d79114f58371b2742f4b7fbc14ee62e5a18ef`。
- Yahoo 二级报价 SHA-256：`525b59d32998c77ad723089d70c93e27ad14462ca3fb4aa932c2d1bf2351637c`。

这些哈希证明本次保存与回放数据一致，不是发行人签名，也不证明当年网页未经修订。把响应拷贝到其他机器时，应保留清单并调整原始文件的本地定位；来源身份、哈希与领域结果不能改动。

## 运行及真实测试结果

在项目根目录运行；当前本地运行方式不依赖 Docker。现场采集需要网络，不进入离线 CI 单元测试。

```sh
PYTHONPATH=backend .venv/bin/python scripts/real_data_pilot.py
PYTHONPATH=backend .venv/bin/python scripts/real_data_pilot.py --replay artifacts/real-pilot/20261009T025343313311Z/execution.json
.venv/bin/python -m pytest tests/test_real_pilot.py tests/test_quant.py tests/test_backtest.py -q
```

实际结果：采集命令退出 0、输出 PARTIAL（仅表示财务读取成功；绝不等同全链通过）；回放退出 0、PASSED、network_calls=0、original_chain_status=PARTIAL；合并针对性测试 **55 passed**，其中新增 pilot 测试 **20 passed**。

复审实际复现了新工具的 P1：删除财务事实字段可绕过旧 replay 的条件校验；P2：HTTP 200 且 JSON 数组让价格处理 AttributeError 中断。均先写失败回归，再定向修复。现在获取与回放共享纯 `analyze_snapshot_data`，回放从原始 bytes 无条件重算并完整比较财务 schema/PIT、顶层状态、null 估值/总回报与诊断字段。篡改收入、财务状态、删除事实后伪造收益、升级顶层或诊断状态都会拒绝。畸形提供商响应转为来源 UNAVAILABLE，其他可用证据继续保存。

下一步需要：有原始发布时间／修订历史的历史 OHLCV 服务、完整拆股股息覆盖与日历的原始数据证明，以及有效 SEC 联系 User-Agent（若使用 SEC）。取得这些证据前，维持上述 BLOCKED/UNVERIFIED，不将二级响应自动升级为生产 REAL bundle attestation。
