# CI-only 独立复审

日期：2026-10-08。按父任务指定的 Sol High 设置执行；工具未独立暴露模型/计费元数据。复审只写本报告，没有改核心逻辑、Docker 配置、依赖或 Git 设置，也没有安装 Docker。

## 结论

**规格符合性：通过代码与本地护栏复审。** 已有 Linux GitHub Actions Python 测试、独立进程 SQLite E2E、前端检查/构建，以及真实 Docker build / Compose API-worker-PostgreSQL 集成入口。失败返回非零并尝试保留日志；下游未执行或失败不会生成 VERIFIED 总结。

**代码质量：通过本轮 CI 范围复审。** 未发现需要阻塞提交的 P0/P1/P2 具体缺陷。

**容器功能状态：UNVERIFIED。Actions 实际执行状态：UNVERIFIED。** 本机没有 Docker；仓库 `git remote -v` 无输出，因此本轮没有触发远端工作流。mock Docker 测试、YAML/bash 检查和此前非容器 PostgreSQL 运行，都不能替代 Linux 容器验收。发布到 GitHub 并取得这次提交的真实成功工作流前，不得改成容器已验证。

## 检查范围与执行链

检查 `.github/workflows/ci.yml`、`scripts/ci/docker_check.sh`、`scripts/ci/compose_smoke.py`、`tests/test_ci.py`；读取 Compose/Dockerfile、锁定依赖、前端入口与现有 E2E 脚本确认接线。当前工作流上传 Action 已固定完整 SHA。

- Python job 使用 Python3.11 与 requirements.lock，运行 pytest/JUnit 和既有独立进程 E2E。
- 前端 job 使用 Node22.22.2、npm ci、来源护栏和 TypeScript/Vite 构建。
- Docker job 依赖两项成功，使用 Ubuntu24.04 执行既有 API/worker/frontend 镜像构建，启动四服务 Compose，并从 PostgreSQL 容器实际调用 pg_isready/psql。
- 冒烟程序不启动替代的本地 API/worker。验证 API 使用 PostgreSQL、Nginx 页面/API 代理、真实 worker 容器状态；停止 worker 时提交并核验 QUEUED，启动后核验十只唯一标的、三角色、SYNTHETIC 与五阶段审计/检查点，再重启 worker 完成相同冻结信号的成熟回测。
- SQL 查询核验 research_jobs、agent_reports、universe artifact、原生 checkpoints 与 audit_events；UUID 在进入 SQL 前验证。缺表/查询错误使用 ON_ERROR_STOP=1 和 subprocess check=True，不能静默成功。
- `set -Eeuo pipefail` 与 EXIT/INT/TERM trap 覆盖正常命令失败；退出前采集 compose 状态/日志并清理本次唯一项目的 volume。保留初始失败码，原始成功而 cleanup 失败也返回非零。镜像构建输出留在 Actions 步骤日志；Compose/cleanup 文件由 always 上传步骤保存。
- 最终 verdict 使用 always()，只有三个依赖 job 全部 success 才输出 VERIFIED (Linux CI)；failed/skipped/cancelled 均为 UNVERIFIED 且 verdict 非零。integration.json 只在全部实际冒烟检查完成后写入。

## 实际复审命令与结果

在 `/Users/yu/Desktop/FinAgent/finagent_codex_starter` 执行：

1. `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_ci.py -q`：**12 passed in5.30s**。这些是轮询失败/超时、Compose JSON 状态、UUID 防注入及真实 bash trap 的 mock Docker 护栏，不是容器验证。
2. `bash -n scripts/ci/docker_check.sh`：退出0。
3. 使用已安装 PyYAML BaseLoader 检查触发器、四项 job、needs、always 上传与 verdict：`CI_YAML_CHECK ... PASS`。这是结构检查，不宣称 GitHub runner 已解析执行。
4. `git remote -v`：无输出。
5. 只读上游引用检查：setup-python 的 v5/v5.6.0 与所用 SHA 一致；checkout/setup-node 的 git ls-remote 请求连接失败，随后通过官方 GitHub commit 页面确认引用存在。[checkout](https://github.com/actions/checkout/commit/11d5960a326750d5838078e36cf38b85af677262)、[setup-node](https://github.com/actions/setup-node/commit/49933ea5288caeca8642d1e84afbd3f7d6820020)、[upload-artifact](https://github.com/actions/upload-artifact/commit/ea165f8d65b6e75b540449e92b4886f43607fa02)。这些引用检查不是 Actions 执行证据。

父任务报告全套 **110 passed**；本复审没有重复运行稳定全套，也不将其记为复审者独立执行结果。

## 验证边界

CI 当前覆盖成功的请求→排队→容器 worker→原生 PostgreSQL 检查点→冻结信号→worker 重启→成熟回测。它不等同于中途强杀后的选择性图恢复测试、浏览器交互测试或真实行情/LLM/SA 历史验收；这些原有验收与数据边界仍单独适用。当前存在的配置、脚本、护栏均可交付，真正 Docker/Linux 执行结果继续保留 UNVERIFIED，不因本机缺 Docker 阻塞或安装新服务。
