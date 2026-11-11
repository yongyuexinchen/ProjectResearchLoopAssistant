# Project Research Loop Assistant

[![CI](https://github.com/yongyuexinchen/ProjectResearchLoopAssistant/actions/workflows/ci.yml/badge.svg)](https://github.com/yongyuexinchen/ProjectResearchLoopAssistant/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Project Research Loop Assistant / 工程调研 Loop 助手，是一个用于理解陌生工程和新代码库的 Loop Engineering 示例项目。系统围绕一个可验证目标持续采集资料、分析项目、记录证据、运行验证器并生成 Project Research Package / 项目调研包。

文档入口：

- [项目现状与评审说明](docs/STATUS.md)：当前能力、验证基线、已知边界和外部评审建议。
- [架构说明](docs/ARCHITECTURE.md)：运行时流程、数据模型、扫描/报告/校验架构。

项目使用：

- FastAPI 提供 REST / SSE API。
- LangGraph `StateGraph` 编排可恢复 Agent Loop。
- MySQL 保存项目、输入源、运行、证据、报告、LLM 调用、运行事件和 graph checkpoint。
- 后台 worker 执行长任务，HTTP 请求只负责排队。
- Next.js 提供中文优先的工程调研工作台。
- OpenAI-compatible LLM provider 接入 DeepSeek、Qwen/DashScope 或自部署 vLLM。

## 能力边界

本项目只做只读工程调研，不修改被分析代码，不执行被分析项目脚本，不创建 commit、issue 或 PR。LLM 只作为增强能力，最终产物必须经过结构化解析、证据引用校验、确定性 verifier 和人工评审。

Project Research Package 包含：

```text
Executive Brief
Research Profile
Source Bundle Summary
Engineering Onboarding Guide
Source Inventory
Codebase Map
Architecture Map
Runbook
Findings
Risk Register
Open Questions
Reading Path
Evidence Index
Verifier Result
Run Timeline
LLM Call Summary
Report Snapshot
```

## 本地依赖

建议环境：

- uv 0.11+
- Python 3.11+
- Node.js 20+
- MySQL 8+

安装 uv：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv --version
```

## 配置环境变量

在仓库根目录复制配置文件：

```powershell
Copy-Item .env.example .env
```

按本机情况修改 `.env`：

```env
DATABASE_URL=mysql+pymysql://root:<local-password>@localhost:3306/loop_engineering
WORKSPACE_ROOT=D:/loop-workspace/projects
NEXT_PUBLIC_API_BASE_URL=http://localhost:8002

LLM_PROVIDER=deepseek
LLM_API_KEY=<your-api-key>
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
LLM_API_KEY_REQUIRED=true
LLM_TIMEOUT_SECONDS=30
```

Provider 示例：

```env
# Qwen / DashScope OpenAI-compatible mode
LLM_PROVIDER=qwen
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
LLM_API_KEY_REQUIRED=true

# Self-hosted vLLM OpenAI-compatible server
LLM_PROVIDER=vllm
LLM_BASE_URL=http://127.0.0.1:8001/v1
LLM_MODEL=<served-model-name>
LLM_API_KEY_REQUIRED=false
```

`.env` 不要提交到 Git。数据库和 LLM 密钥只放本机。

## 开源与安全

- 仓库不会提交 `.env`、`.env.*`、`workspace/projects/`、`.tmp/`、虚拟环境和依赖目录。
- 新环境从 `.env.example` 复制出 `.env`，只在本机填写真实密码和 API Key。
- 提交前建议执行：

  ```powershell
  git status --short --ignored
  git diff --cached
  ```

- 如果密钥曾经进入 Git 历史，应立即轮换密钥，并使用 `git filter-repo` 或重新初始化仓库清理历史；仅删除当前文件不足以移除历史记录。

## 创建数据库

```powershell
mysql -uroot -p -e "CREATE DATABASE IF NOT EXISTS loop_engineering CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

## 启动后端 API

```powershell
Set-Location services/api
uv python install 3.11
uv sync --extra dev
uv run alembic upgrade head
uv run python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8002
```

后端依赖由 `services/api/pyproject.toml` 声明，由 `services/api/uv.lock` 锁定。`uv sync --extra dev` 会创建并同步本地 `.venv`，不需要手动激活虚拟环境。

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8002/health
```

## 启动后台 Worker

另开一个 PowerShell 终端：

```powershell
Set-Location services/api
$env:PYTHONPATH='.'
uv run python -m app.workers.worker_service --queue default --poll-interval 2
```

worker 会轮询 queued run job，使用 lease/heartbeat 防止重复领取，并把运行过程写入 durable run events。

## 启动前端

另开一个 PowerShell 终端，在仓库根目录执行：

```powershell
npm --prefix apps/web install
npm --prefix apps/web run dev -- --hostname 127.0.0.1 --port 3000
```

浏览器打开：

```text
http://127.0.0.1:3000/projects
```

## 推荐体验路径

更新代码后，在项目根目录运行 `powershell -ExecutionPolicy Bypass -File .\restart-all.ps1`，重启本项目的 API、Worker 与前端。脚本按项目路径识别进程，日志保存在 `.tmp/service-logs/`；可先加 `-WhatIf` 预览匹配结果。此脚本不重启 MySQL。

`start-all.ps1` 在 MySQL 未运行时可以代为启动，但不会写死本机 MySQL 路径。需要时设置 `LOOP_MYSQLD_PATH`（mysqld 可执行文件完整路径），可选设置 `LOOP_MYSQL_INI_PATH`（my.ini 路径）。

若配置页面提交出现 `Method Not Allowed`，通常是旧 API 尚未加载新版接口。运行 `powershell -ExecutionPolicy Bypass -File .\restart-all.ps1 -BackendOnly` 只重启 API 与 Worker，保留浏览器表单；完成后直接再次点击启动。启动检查会同时确认新配置接口和工作流接口，不再仅依据端口占用或健康检查判断就绪。

1. 打开 `/projects/new`，按“项目目标 → 输入资料 → 调研偏好 → 确认启动”逐步配置。
2. 点击最后一步的启动按钮，后台自动完成资料采集、分析验证、架构图和调研报告。前提是 API 和 Worker 均已启动；浏览器关闭不影响后台任务。
3. 运行页自动显示四阶段进度和事件，无需手动订阅。进度按已完成阶段推进，报告保存后才显示 100%。可取消，失败后可重试；需要补充信息时保存回答并继续。
4. 完成后直接查看报告、架构图，或下载 Markdown/PDF。纯文档资料会明确提示跳过架构图。
5. 架构图支持鼠标拖动画布、滚轮围绕鼠标缩放、全屏、适应屏幕和 1:1 重置；画布聚焦后可用方向键平移、+/- 缩放、0 适应屏幕、Esc 退出全屏。
6. 报告仍保留人工评审。原有输入源、采集、证据和工具页放在“资料与分析工具”中，便于深入检查。
7. 在 `/evaluations` 运行调研档位 benchmark，确认核心能力没有退化。

自动流程接口：`POST /projects/setup` 原子保存配置并排队；`POST /projects/:id/workflow` 启动现有项目；`GET /projects/:id/workflow?run_id=...` 查询指定任务进度。

自动生成的架构图按运行保存，查看旧任务时不会切换到新任务的图。多个代码库资料同时存在时，架构图当前基于最近采集的代码库地图生成，图卡会标注来源工程。

每张架构图都有“重新生成此图”按钮，报错时可单独重试。重生成使用该图保存的结构快照，不重新运行调研、不调用模型，也不会替换其他图。历史任务同样可用。对应接口为 `POST /projects/:id/architecture/:diagram_id/regenerate`。

浏览器统一访问同源 `/api/*`；服务端优先使用 `LOOP_API_ORIGIN`，其次使用 `NEXT_PUBLIC_API_BASE_URL`。项目自带启动脚本和默认代理使用后端端口 `8002`；如果手动改到其他后端端口，请同时设置 `LOOP_API_ORIGIN` 和 `NEXT_PUBLIC_API_BASE_URL`。

## 常用命令

后端测试：

```powershell
Set-Location services/api
uv run --extra dev python -m pytest tests -q
```

数据库迁移状态：

```powershell
Set-Location services/api
uv run python -m alembic -c alembic.ini current
```

前端构建：

```powershell
npm --prefix apps/web run build
```

前端交互计算与事件回归测试（需要 Node.js 22.6+，本次使用 Node.js 24）：

```powershell
npm --prefix apps/web test
```

运行评估：

```powershell
Invoke-RestMethod -Method POST http://127.0.0.1:8002/evaluations/run
```

## 主要页面

```text
/projects
/projects/new
/projects/:id
/projects/:id/sources
/projects/:id/inventory
/projects/:id/run
/projects/:id/findings
/projects/:id/codebase
/projects/:id/risks
/projects/:id/report
/settings/llm
/evaluations
```

## 参与贡献与安全

- 贡献说明见 [CONTRIBUTING.md](CONTRIBUTING.md)。
- 安全问题请遵循 [SECURITY.md](SECURITY.md)，不要公开提交密钥或私有代码。

## License

本项目以 MIT License 开源，详见 [LICENSE](LICENSE)。
