# 项目现状与评审说明

> 面向代码评审 / 外部模型审核。最后更新：2026-11-11。
>
> 仓库：<https://github.com/yongyuexinchen/ProjectResearchLoopAssistant>

## 1. 项目定位

Project Research Loop Assistant 是一个只读的工程调研工作台：输入项目目录、GitHub 仓库或文档，系统自动采集资料、分析代码库、记录证据、运行确定性校验，并生成带证据引用的调研报告和架构图。

技术栈：

- 前端：Next.js 15、React 19、TypeScript、Mermaid
- 后端：FastAPI、LangGraph、SQLAlchemy、Alembic、MySQL
- 运行方式：API + 独立后台 Worker；HTTP 请求只负责入队
- 模型：OpenAI-compatible provider（DeepSeek / Qwen / vLLM 等），模型只做增强，不替代确定性证据校验

## 2. 当前能力

### 配置与自动运行

- 四步配置：项目目标 → 添加资料 → 调研方式 → 确认并启动
- 资料类型：本地目录、本地文档、网页链接、GitHub 仓库
- 中文界面；粘贴 URL 会自动识别为 GitHub 仓库或网页，粘贴本地路径会自动识别为本地目录
- 提交前统一校验；失败保留输入
- 后台自动完成：采集 → 分析与验证 → 架构图 → 报告

### 五种调研方式

五种方式共享证据、校验和运行隔离，但使用不同的报告结构：

| key | 名称 | 核心章节 |
| --- | --- | --- |
| `quick_onboarding` | 快速接手 | 接手指南、启动线索、架构地图、阅读路线、30 分钟路线、确认事项 |
| `architecture_understanding` | 架构理解 | 系统边界、模块边界、主流程、外部依赖、扩展点、验证缺口 |
| `extension_evaluation` | 二开评估 | 改造面、可行性、风险、测试与配置复杂度、分期方案 |
| `teaching_breakdown` | 教学拆解 | 教学目标、章节、代码讲解顺序、难点、练习、材料缺口 |
| `delivery_acceptance` | 交付验收 | 范围、完整性、可启动性、文档运维缺口、验收问题与结论 |

所有报告都以「项目速览」开头：项目定位、背景与目标、主要能力、工程特点、技术形态、资料缺口和依据来源。

### 进展与结果

- 进度来自持久化 run events，不依赖前端临时状态
- 支持断线重连、取消、失败重试、暂停后回答问题继续
- 报告保存后才到 100%；人工评审仍保留
- 评审会区分当前报告和历史报告：历史报告不能覆盖当前项目状态或启动新任务；同一报告重复提交同一 follow-up 决策是幂等的
- 报告导出 Markdown / PDF，文件名绑定项目、调研方式和日期
- 架构图按运行保存，支持整图拖动、鼠标位置缩放、全屏、适应画布、1:1、键盘操作
- 单张架构图可重新生成；只更新选中图，不重新扫描仓库、不调用模型
- 新增源码函数/调用位置图：Python AST 与 JS/TS/TSX Tree-sitter 静态索引，保存函数、语句分类、调用行号、源码 hash；报告在线/Markdown/PDF 使用同一份 run 快照

### 证据与安全边界

- 采集是只读的：不修改被分析代码、不执行被分析项目脚本、不创建 commit/issue/PR
- 扫描过滤敏感文件（`.env`、key、pem 等）、vendor、构建产物、缓存和大型生成文件
- 采集快照、代码库地图和资料包绑定到本次 run；历史报告不会读取后续 run 的新资料（旧版无 run_id 的数据有受控兼容回退）
- 网页采集默认只允许公网 IP，逐跳复核 redirect；有响应字节上限；内网资料需要显式开启 `WEB_ALLOW_PRIVATE_HOSTS`
- 发现和风险必须引用已落库证据
- LLM 输出必须通过结构校验和 evidence id 校验；失败时回退到确定性报告
- LLM 补充问题降级为 advisory，不单独阻塞自动任务；确定性高影响问题仍会暂停

## 3. 当前实现结构

### 前端

- `apps/web/app/projects/new`：四步向导
- `apps/web/app/projects/[id]`：项目概览、工作流进度、报告入口
- `apps/web/app/projects/[id]/report`：报告查看、人工评审、导出
- `apps/web/app/projects/[id]/architecture`：架构图查看和单图重生成
- `apps/web/lib/source-detect.ts`：资料类型自动识别
- `apps/web/lib/research-templates.ts`：五种调研方式的前端展示

### 后端

- `app/api/routes_*`：HTTP 接口
- `app/services/workflow.py`：自动流程阶段与进度状态
- `app/services/reports.py`：报告快照、智能报告、评审、导出数据
- `app/engine/langgraph_runner.py`：LangGraph 节点与暂停/恢复
- `app/engine/analyzer.py`：确定性分析入口
- `app/engine/profile_analysis.py`：按调研方式补充发现/风险/建议
- `app/tools/code_scan_tools.py`：代码库扫描、入口识别、主语言判断
- `app/reports/project_brief.py`：README/依赖/目录的「项目速览」提取
- `app/reports/renderer.py`：按调研方式渲染 Markdown 报告
- `app/reports/llm_generator.py`：LLM 报告增强校验与章节合并
- `app/verifiers/`：确定性校验与质量评分
- `app/research/profiles.py`：五种调研方式的唯一后端定义

## 4. 验证基线

最后一轮本地验证：

- 后端：`411 passed, 2 skipped`
- 前端：19 项测试通过
- TypeScript：`npx tsc --noEmit` 通过
- 生产构建：`npm run build` 通过
- PowerShell 启动脚本语法解析通过
- 真实模型端到端验证过：教学拆解、架构理解、智能报告增强与自动完成流程
- 真实仓库验证：OSIRIS 生成 500 文件、2400 函数、8613 个调用点的源码索引，报告 117KB，PDF 42 页
- 报告页初始 HTML：约 6.1MB → 559KB；完整源码索引点击“按需加载源码逐段导航”后再请求

CI 只运行确定性测试和类型检查，不配置真实数据库、模型密钥或付费模型调用：

```text
.github/workflows/ci.yml
  backend:  uv sync --extra dev && uv run pytest -q
  frontend: npm ci && npm test && npx tsc --noEmit
```

## 5. 已知边界与风险

这些是当前实现刻意保留的边界，不是“已完成”：

1. **架构图以静态扫描为主**
   - 模块边界来自目录、配置、依赖和文件树，不是完整编译依赖图。
   - 源码函数图支持 Python、JavaScript、TypeScript、TSX；Go/Java 等语言暂不做精细解析，会明确提示。
   - 源码图只证明语法上的声明和可解析调用引用，不证明运行顺序、动态分派或真实数据血缘；路径别名、CommonJS `require`、构造调用等未解析项会保留为未解析。
   - 解析有文件数、单文件字节数、总字节数、函数/语句/调用/画布节点预算；超限会在图和报告中写明，并保留有界可搜索明细。
   - 完整源码索引随报告快照保存在服务端；报告 API 不内嵌明细，前端点击“按需加载源码逐段导航”才请求 `/source-index`，避免初始报告页达到数 MB。
   - 目前没有 Go import graph / Java 类依赖图 / 完整调用链。
   - 主流程和时序图是阅读骨架，不是真实运行调用链。

2. **多代码库支持有限**
   - 多个代码目录同时输入时，架构图目前基于最近采集的代码库地图。
   - 尚未实现跨仓库统一架构图或按资料选择架构图。

3. **报告质量依赖资料**
   - README、依赖清单和源码目录越完整，项目速览越可靠。
   - 资料缺失时会明确写“资料缺口”，不会编造动机或功能。
   - 旧报告不会自动重写；需要重新生成报告或重跑分析。

4. **LLM 是增强层**
   - 没有可用模型时使用确定性回退，报告会明确提示。
   - 模型可能提出错误问题或与旧 run 的复核意见不一致；正文以确定性证据为准。
   - 自动测试不调用付费模型，真实模型行为需要单独验收。

5. **安全**
   - `.env`、本地克隆目录、日志、虚拟环境和依赖目录均被 `.gitignore` 排除。
   - 仓库只包含 `.env.example`；如密钥曾进入历史，仍需轮换并清理历史。

## 6. 建议外部评审重点关注

1. `app/tools/code_scan_tools.py`：入口识别、主语言判断、vendor/生成文件过滤是否会误判。
2. `app/reports/project_brief.py`：README 解析、表格解析、证据来源是否可追溯。
3. `app/reports/renderer.py`：五种方式章节是否真正有差异，是否存在没有证据的断言。
4. `app/engine/profile_analysis.py`：档位特定的发现/风险是否过度推断。
5. `app/engine/langgraph_runner.py` + `app/workers/run_worker.py`：暂停/恢复、lease、重试和断线是否可能丢任务或重复执行。
6. `app/services/reports.py`：报告快照、智能报告、人工评审和 run 的隔离。
7. `apps/web/components/project-setup-wizard.tsx`：资料类型与 URI 的校验、自动切换是否覆盖边界情况。
8. 测试盲区：真实 MySQL、Worker 崩溃恢复、付费模型失败回退、超大仓库扫描性能。
