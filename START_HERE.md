# FinAgent: Codex 一次性开发包

这个包提供架构约束、源码复用地图、旧版设计参考和一个完整的一次性开发 Prompt。**包内没有应用实现代码**。

## 最简单的使用方法
1. 在你的 Mac 上创建/进入本地 `finagent` Git 仓库，把这个包内所有文件原样放到仓库根目录（覆盖前检查已有内容）。
2. 在该仓库目录启动 Codex CLI（或者 Codex IDE 插件）。
3. 将 `CODEX_ONE_SHOT_PROMPT.md` 全文交给 Codex；如支持文件引用，直接要求它“执行 @CODEX_ONE_SHOT_PROMPT.md”。
4. 赋予它工作区文件读写、命令运行与依赖安装权限。**不要把 API 密钥粘贴给 Codex 聊天**；需要时在本机 `.env` 文件中设置。
5. 要求它把测试报告、未完成项与运行命令写到 `docs/STATUS.md`。

## 极简启动消息（可以直接粘贴）
```
请读取仓库根目录的 AGENTS.md、docs/IMPLEMENTATION_DECISIONS_V2.md、docs/REUSE_MAP.md 和 CODEX_ONE_SHOT_PROMPT.md；现在严格按 CODEX_ONE_SHOT_PROMPT.md 一次性实现 FinAgent。不要只给计划，不要停在骨架；自行编码、安装依赖、运行测试、修复问题、启动 E2E 演示，最后输出真实验收报告。缺少 API Key / Seeking Alpha 历史原始榜单时继续完成明确标注的离线 DEMO，绝不伪造真实回测成绩。
```

## 使用现实预期
“一个 Prompt”指尽量让 Codex **自主连续执行**，不代表可以保证一次模型调用就无故障实现复杂系统。可能需要你批准命令、登录服务、提供本地环境配置。历史 Seeking Alpha 列表与可验证 PIT 财务历史数据是客观外部依赖。
