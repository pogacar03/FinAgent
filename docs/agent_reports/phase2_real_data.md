# phase2_real_data 实际工作记录

本角色继承主 Agent 模型设置；没有自行手动切换模型。任务为真实 NVDA 单股证据闭环，不写生产 data/quant/backtest/contracts/agents/worker，不改依赖、不提交 Git。

独占新增文件：`backend/finagent/real_pilot.py`、`scripts/real_data_pilot.py`、`tests/test_real_pilot.py`、`docs/REAL_DATA_VALIDATION.md`、本报告。真实原始响应位于 Git 忽略的 `artifacts/real-pilot`。

实现了发行人 GAAP 历史财报解析、结构化发布日期读取、保守日期上界、原始响应 URL/类别/获取时间/内容 SHA-256/代码版本清单、显式 PE 假设政策算术、严格缺失 PIT 与行动覆盖的拒绝门、独立 UNVERIFIED 半年价格诊断和无网络防篡改回放。未伪造另外九只股票、SEC 联系人、当年精确时戳、分析师预测、行动完整性或投资收益。零 LLM 调用。

真实测试命令及结果：

- 首次 test_real_pilot 采集失败 ModuleNotFoundError（TDD RED），实现后 10 passed。
- 回放／失败网络路径新增测试首先 2 failed；实现回放与独立创建执行目录后 12 passed。
- 结构化发布日期和来源身份验证首先 2 failed；修复后 14 passed。
- Sol High reviewer 实际复现可缺字段绕过回放和数组型 JSON 中断；新增回归首先 4 failed / 16 passed。
- 定向修复后 `.venv/bin/python -m pytest tests/test_real_pilot.py -q`：20 passed。
- `.venv/bin/python -m pytest tests/test_real_pilot.py tests/test_quant.py tests/test_backtest.py -q`：55 passed。
- 实际终版 `PYTHONPATH=backend .venv/bin/python scripts/real_data_pilot.py`：退出 0，PARTIAL，执行 20261009T025343313311Z。
- 对同一执行 JSON 的 --replay：实际 PASSED、0 网络调用；不升级 original_chain_status=PARTIAL。

未完成项：精确 SEC 10-K 接受时戳、当年不可变财务页面快照、原始历史市场首次可用证明／修订历史、完整公司行动证明、交易所日历、分析师预测、正式估值、含行动的半年总回报、完整真实 Top-10。当前严格估值和总回报是 UNAVAILABLE/null；不允许在最终状态报告中写真实全链 PASSED。

来源与具体执行细节见 `docs/REAL_DATA_VALIDATION.md`；所有旧核心计算复用原函数，生产98测试由主 Agent独立验收。
