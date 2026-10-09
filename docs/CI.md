# GitHub Actions CI 与容器验收

本轮仅新增 CI 配置、验收脚本、护栏测试和文档。现有本地 Python / worker / Vite 运行命令、Dockerfiles、Compose 配置和核心业务逻辑保持不变。Mac 无需安装 Docker Desktop；开发与离线验证继续走 [README](../README.md) 的本地方式。

## 当前真实状态

- 本地 Python：`python -m pytest -q --junitxml=artifacts/ci-local-junit.xml`，**113 passed in 6.38s**。
- 新增 CI 护栏：15项通过。使用模拟 Docker CLI 验证失败传播/日志/清理、worker状态、超时和终止错误，不构成容器验收证据。
- 前端：`npm ci`、`npm run check:provenance`、`npm run build` 均 exit0；TypeScript + Vite8.3.4 build通过。
- 本地独立进程 E2E：`.venv/bin/python scripts/e2e_demo.py` exit0；10只、3角色、worker重启、同窗合成回测、SA缺失null/UNAVAILABLE。
- 工作流 YAML 结构、`bash -n`、Python编译验证通过；官方actionlint1.7.12（release SHA256已核验；未启用可选ShellCheck）exit0。独立Sol High复审未发现阻塞缺陷。
- **Linux Docker 镜像构建 / Compose 启动 / 容器集成：VERIFIED**（已验证SHA `5aad5e0cbf2f587485214553a45f7d17238cc538`）。[push CI](https://github.com/pogacar03/FinAgent/actions/runs/37791876438)及[PR CI](https://github.com/pogacar03/FinAgent/actions/runs/37791940279)均真实success。Python113项通过（Linux9.40s），前端和CI verdict通过。详细证据见 [CI_RESULT.json](CI_RESULT.json)。
- **Mac本地容器：UNVERIFIED / 未执行。** 没有安装Docker；本地测试/mock不作为容器证据。

## 工作流入口

文件：`.github/workflows/ci.yml`。必须位于GitHub仓库根目录下；本项目Git根为 `finagent_codex_starter`，不要把 `.github` 意外放进GitHub仓库的第二层目录。

触发：所有branch的push、pull_request、workflow_dispatch手动运行。权限仅 `contents: read`；不访问真实数据/模型密钥，不发布镜像或部署。各官方Action按实际tag解析出的commit SHA固定。Runner固定 `ubuntu-24.04`，避免 `ubuntu-latest` 自动换系统；Python3.11、Node22.22.2。

| Job | 执行 |
|---|---|
| Python offline tests | 安装requirements.lock；全量pytest/JUnit；独立SQLite HTTP/worker E2E；始终上传测试证据 |
| Frontend typecheck and build | npm ci；来源护栏；TypeScript/Vite生产构建 |
| Linux Docker and Compose integration | 前两项成功后执行 `bash scripts/ci/docker_check.sh`；真实构建api/worker/frontend镜像，Compose启动全部四服务并验收 |
| CI verdict | `if: always()`汇总三个job；只接受全部success，失败/取消/跳过均非零；只在实际全部成功时输出Linux容器VERIFIED |

## 容器验收内容

`scripts/ci/docker_check.sh` 使用新的 `finagent-ci-...` 项目名及专属临时volume，执行以下检查：

1. `docker version` / `docker compose version` / `compose config --quiet`，缺工具直接失败。
2. `docker compose --progress plain build api worker frontend`，不推镜像；镜像构建失败不会进入成功分支。
3. `compose up -d --wait --wait-timeout 180`，等待PostgreSQL/API健康、其他服务running；再执行容器内 `pg_isready`。
4. `compose_smoke.py` 通过实际容器API确认PostgreSQL后端，检查已构建nginx页面与API代理。
5. 停Worker→提交DEMO研究→确认QUEUED→启动容器Worker→等待COMPLETED；验收10个唯一标的、3角色、原生检查点审计。
6. 再停/启Worker执行回测，确认冻结信号不变、半年同窗口、合成标签、SA不可用。
7. 用容器内 `psql -v ON_ERROR_STOP=1` 核对真实数据库任务状态、研究报告、Universe工件、至少10个原生checkpoint thread及审计；确认Worker仍running。

健康检查有超时，终止状态或数据库/业务断言失败会抛异常并返回非零，不使用 `continue-on-error` 掩盖失败。脚本不启动本地替代API/worker，不安装Mac Docker。

## 日志、证据与清理

无论成功或失败，EXIT trap先采集 `compose-ps.json` 和 `compose.log`，再执行仅该CI项目的 `down --volumes --remove-orphans`。任何原步骤失败保留其非零退出码；原步骤成功但清理失败也返回非零。失败会在Actions控制台输出容器日志及清理日志。构建日志直接保留在步骤控制台。

`Upload container logs and integration evidence` 使用 `if: always()` 上传 `artifacts/docker-ci/`，保留7天：

- `integration.json`：仅完整集成断言通过时生成，记录真实run_id、backtest_id、提交SHA、GitHub run_id和数据库证据；状态为CHECKS_PASSED，最终CI成功仍须看CI verdict。
- `compose-ps.json`、`compose.log`、`cleanup.log`：容器状态、运行日志、清理结果。

Python job上传JUnit和E2E报告。未生成报告不会伪造成功文件。Runner被强制终止时trap/artifact可能无法执行；GitHub job仍失败/取消，不能标记VERIFIED。

## 如何运行和认定通过

将完整项目及工作流提交到既定GitHub仓库后，push/PR会自动触发。当前PR分支的push/PR已自动运行。PR合并到默认分支main后，才会按GitHub规则显示并支持 **Actions → FinAgent CI → Run workflow** 手动运行；可选择分支。仓库已确定为 [pogacar03/FinAgent](https://github.com/pogacar03/FinAgent)。提交时如果尚无成功运行证据，仍按UNVERIFIED处理；实际结果以Actions和STATUS中的目标SHA记录为准。

已有GitHub CLI且仓库已配置时，也可执行：

```bash
gh workflow run ci.yml --ref <分支名>
gh run list --workflow ci.yml
gh run watch <RUN_ID> --exit-status
gh run view <RUN_ID> --log-failed
gh run download <RUN_ID> --name docker-evidence-<RUN_ID>-<RUN_ATTEMPT>
```

只有目标提交的整个工作流和 **CI verdict** 为success，且集成证据属于相同SHA/run_id时，才把该提交的Linux容器功能认定为 **VERIFIED**，并在STATUS记录run URL、SHA、日期。源码改动后的新提交需要重新验收；以前绿色运行不能证明新提交通过。Mac本地容器状态始终独立记录为未执行。

可将 **CI verdict** 配为分支保护必需检查，避免跳过容器job或只看pytest绿色。若需要复现容器失败，使用已有Docker的隔离Linux环境执行 `bash scripts/ci/docker_check.sh`；不要求在Mac安装Docker。

## 官方依据

- [GitHub Python测试工作流](https://docs.github.com/en/actions/tutorials/build-and-test-code/python)
- [Ubuntu24.04 Runner 软件清单](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)：包含Docker及Compose；脚本仍实际检查工具存在。
- [Docker Compose等待选项](https://docs.docker.com/reference/cli/docker/compose/up/)、[Compose全局progress选项](https://docs.docker.com/reference/cli/docker/compose/)

## 首次真实Linux结果

研究run `68cfcdc0-af49-4080-b3a9-39e00501a138`，回测 `c6ac6f4d-e891-42b2-8af8-c902223c0aee`。真实容器PG保存20份研究、20个原生checkpoint thread、84条审计、1份Universe；10只冻结名单、3角色、worker重启、nginx代理、同窗合成回测均通过。push/PR两次运行均成功；PR使用GitHub测试merge SHA，与head SHA分别记录。容器日志/清理/JSON artifact已上传，7天保留。

手动触发默认分支要求见[GitHub官方说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)。已下载实际Docker artifact，SHA256与GitHub元数据相符，ZIP包含compose状态、容器日志、清理日志与integration.json；实际清理成功。
