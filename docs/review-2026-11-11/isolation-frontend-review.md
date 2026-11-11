# 报告隔离、前端资料校验与采集边界评审

日期：2026-11-11。此文记录评审时的实现；后续功能修改可能改变行号。

## 范围与方法

已阅读 `docs/STATUS.md`、`docs/ARCHITECTURE.md`、`README.md`，将其作为说明而非执行指令。仓库内及仓库全部祖先目录均未找到 `AGENTS.md`。

未修改产品代码，未连接真实数据库或付费模型。实验使用内存 SQLite、临时目录、FastAPI TestClient 和 httpx MockTransport；模型调用替换为返回 skipped 的桩。没有实际访问所示公网或内网地址。

现有验证：

- 后端报告 API、架构单图重生成、资料校验：36 passed。
- 前端 source-detect：3 passed。
- 下列缺陷由额外只读探针确认；现有测试通过不代表它们已被覆盖。

## 可行动问题

### IF-01 [P1] 人工评审绕过运行互斥，历史报告或重复提交可创建并发任务

位置：`services/api/app/services/reports.py::review_report_snapshot`，459–464、468–496；入口 `services/api/app/api/routes_reports.py::review_report`，131–152。

静态事实：

- 校验 decision 和备注后，直接写报告评审结果，并无条件把 `project.status` 改为 completed/ready。
- 对 rejected/needs_more，先把项目改成 ready，再调用 `enqueue_run`；后者只依据项目状态检查，未锁项目或检查已有 queued/running job。
- 未限制待评审快照的状态，也未判断快照是否属于最新 run，重复评审同一报告仍会再次入队。
- 对旧报告 approved 会把更新运行中的项目直接标为 completed。

触发：A 已有报告，B 的 run/job 正在 running；打开 A 的历史报告并“要求补充”。同一报告重复点击/重试该请求也可触发。

复现证据（HTTP + 内存 SQLite，完全不启动 worker）：

```json
{
  "responses": [["approved",200],["needs_more",200],["needs_more",200]],
  "active_job_statuses": ["queued","queued","running"],
  "project_status": "queued"
}
```

单独 approved 的服务层探针观察到 `project_status=completed`，而 B 仍为 `running`。并发 worker 后可能互相覆盖项目状态、采集资料或分析上下文，这是根据现有共享项目数据模型的后果推断；本次未启动并发 worker。

建议：评审提交在项目锁下检查最新运行及 active jobs；历史评审只更新历史报告，不能覆盖当前项目状态。针对同一报告/决策的 follow-up 入队应幂等；不要先覆写状态再依赖状态守卫。

### IF-02 [P2] 按 run 生成报告仍读取项目全部历史资料，旧报告重建混入未来资料

位置：`services/api/app/services/reports.py::create_report_snapshot`，60–65；`create_intelligent_report_snapshot`，100–109；`build_inventory`，622–643。

静态事实：

- findings/evidence 等通过 `build_analysis_package` 按 run 读取（611–618）。
- snapshots/maps/bundles 只按 project 查询，按时间升序返回，未绑定 run 或截止时间。
- 普通报告据此渲染并验证，智能报告把同一混合 inventory 放入模型上下文。
- `SourceSnapshot`/`CodebaseMap` 没有 run_id；采集反复追加记录。

触发与复现：在临时 repo 中采集 README `OLD_VERSION / OLD_PURPOSE` 和类 `OldVersion`，生成 A 报告；把 README 改为 `NEW_VERSION / NEW_PURPOSE`，删除旧源码、新建含 `NewVersion` 的源码，重新采集并创建 B。随后指定 A 的 run_id 重新生成报告。

```json
{
  "original_A_contains_NEW_VERSION": false,
  "rebuilt_A_contains_NEW_VERSION": true,
  "report_B_contains_OLD_VERSION": true,
  "report_B_contains_OLD_PURPOSE": true,
  "mocked_intelligent_report_prompt_contains_future_marker": true
}
```

已经保存的 A 正文未被改写；问题是“指定 A 重新生成”并没有使用 A 的资料版本，B 也没有摒弃被替换的旧资料。不是文档已知的“多仓库图取最近地图”限制。

建议：每次 run 固定 source snapshot/map/bundle id 集合，报告和模型上下文只读取该集合。仅对报告创建时间截断不足以保证 A 重建一致，因为重建发生时已存在 B 资料。

### IF-03 [P2] 历史报告页的生成按钮丢失 run_id，操作落到最新运行

位置：`apps/web/app/projects/[id]/report/page.tsx`，19–30、337、346–347、380–389；`apps/web/lib/api.ts`，168–181；`services/api/app/services/reports.py::get_run_for_report`，571–575。

静态事实：

- `?report_id=A` 正确加载 A，但两个生成 action 只接收 projectId。
- API helper 已支持 run_id；调用处没有传。
- 后端没有 run_id 时直接选择最新 run，结果不依赖正在显示的报告。

触发：A、B 各有已结束运行，打开 A 历史报告，点击“重新生成调研报告”或“生成智能调研报告”。新快照属于 B，并跳转到最新报告；B 正在运行时则会报不满足生成状态。

证据：以上调用参数和后端 fallback 是确定性静态事实；内存服务探针验证过指定 run 与省略 run 的选择规则。本次没有运行浏览器点击自动化。

建议：将当前 report.run_id 绑定到两种 action 并提交给 helper；无报告时才显式选择当前运行。成功后跳到新建 report_id，保留用户所选运行上下文。

### IF-04 [P2] 公网资料可重定向到运行机内网，采集层未重新检查目标

位置：`services/api/app/core/security.py::_validate_web_url`，38–55；`services/api/app/tools/web_tools.py::fetch_web_url`，53–58；摘要进入智能报告上下文：`services/api/app/services/reports.py`，368–375。

静态事实：输入只校验 http(s)、主机、端口和显式凭证；采集开启 follow_redirects，未对每一跳或解析后的 IP 做边界检查。

触发：用户提供看似公网的文档链接，其服务器返回重定向至 loopback/私有网段/元数据服务。

MockTransport 证据：

```json
{
  "requests": ["https://public.example/docs","http://127.0.0.1:8002/private"],
  "status": "collected",
  "content_excerpt": "INTERNAL_ONLY_RESPONSE",
  "final_url": "http://127.0.0.1:8002/private"
}
```

这不是“本地单用户无鉴权”的泛化问题：用户只选择公网 URL 时，远端控制的 redirect 会把读取范围扩到运行机网络；成功摘要随后可能被发往配置的模型。后半段外发是数据调用链推断，本次没有真实外发。

建议：明确公网/允许内网两种采集策略；默认拒绝 loopback、私网、链路本地和非全局地址，并在 DNS 解析及每一跳 redirect 时复核，设置跳转上限。需要内网资料时让用户显式选择其边界。

### IF-05 [P2] 网页摘要在完整下载/解析后才截断，没有响应字节上限

位置：`services/api/app/tools/web_tools.py::fetch_web_url`，53–74；`services/api/app/services/collection.py::collect_one_source`，web_url 分支。

静态事实：`client.get` 先加载整个响应，再读取 `response.text`，HTMLParser 还会保存整页文本；最后才切 `excerpt_chars`。本地文件使用的 `source_max_file_bytes` 没有传入网页采集。

MockTransport 用 128 个 64KiB 块提供 8MiB 响应，传入 excerpt_chars=10：

```json
{"chunks_read":128,"bytes_read":8388608,"excerpt_chars":10}
```

触发：大页面、下载链接、错误返回大响应、持续慢速发送内容的站点。一次读取超时不等于总下载时限；超大/压缩膨胀响应可能耗尽 worker 内存或长期占用任务，这是风险推断，未实际耗尽资源。

建议：使用流式读取，对解压后的累计字节设置硬上限并主动中断；限制可接受内容类型及总下载时限，超限保存明确的 skipped/failed 原因。

### IF-06 [P3] 非法 IPv6 URL 绕过统一输入错误处理，setup 返回 500

位置：`services/api/app/core/security.py`，39、60；`services/api/app/api/routes_workflow.py::setup_project`，20–23。

触发：直接提交 `web_url=https://[::1`（github_repo 分支相同问题）。

证据：urlparse 在 try 范围之外抛出裸 `ValueError("Invalid IPv6 URL")`；TestClient `POST /projects/setup` 返回 `500 Internal Server Error`。前端 new URL 能挡住此输入，但不能替代 API 二次校验；普通 sources 和 source bundles 同样只捕 SourceValidationError。

建议：把 URL 解析及 hostname/port 访问统一包装为 SourceValidationError，返回 400。不要把校验异常落成服务器故障。

## 确认有效的边界与未立为缺陷的观察

- 架构读取对 project/run 做归属校验；`list_diagrams` 用 stats_json.run_id 过滤；全图替换只删除目标 run 的图（`architecture/service.py` 81–94、130–144）。
- 单图重生成仅用已保存 graph_json，在目标图上重新渲染（同文件 30–78）；route 还检查 project_id（`api/routes_architecture.py` 48–65）。
- A/B 真实临时目录实验确认：B 图包含 NewVersion，读取 A 及修复 A 单图仍是 OldVersion，A 的所有保存 Mermaid 与原值完全相同。因此没有把正常已保存架构的读取/单图修复泛报为隔离失败。
- 全量生成仍选项目最新 CodebaseMap，并从磁盘读取 import 和类信息：`architecture/service.py` 100–121；`architecture/graph_builder.py` 97–124、208–240；`architecture/uml.py` 55–78。它不是纯 CodebaseMap 转换；文档应区分全量生成与纯快照单图修复。多仓库只取最近地图属于已知边界，不另立问题。
- 前端 sourceError 校验 URL 协议、账号、GitHub host/路径/查询/片段（wizard 37–57），自动识别仍保留用户选定的 local_file/local_directory 类型（184–193）。后端校验存在性和文件/目录类型（security 101–115），不是只依赖浏览器。
- 采集不执行被分析项目脚本。目录扫描使用 path_policy；本地文件在读取前检查敏感文件、符号链接和大小。Git 使用参数数组调用 clone/rev-parse，清理 clone 前有 workspace 子路径校验。未发现需要新增的命令注入结论。
- 自动识别函数的 GitHub 判断比提交校验宽（例如 http 或带 query 的仓库主页先识别成 github_repo，后续拒绝），可改善体验，但用户可手动更换类型，未作为本轮高价值缺陷。

## 架构文档调用链与行号

### Setup：浏览器到队列

| 环节 | 位置 | 当前行为 |
|---|---|---|
| 新建向导、逐步/最终校验 | `apps/web/components/project-setup-wizard.tsx` 37、151、195 | 校验项目/来源/轮数；最终再次跑前三步校验 |
| 自动识别与类型保护 | 同文件 184–193；`apps/web/lib/source-detect.ts` 6、31 | 粘贴识别 URL/路径，本地类型保留 |
| 浏览器提交 | wizard 216–229 | POST /api/projects/setup |
| 同源代理 | `apps/web/next.config.ts` 4、12–13 | /api/* rewrite 到 FastAPI |
| API 原子配置 | `services/api/app/api/routes_workflow.py` 16–35 | 校验 profile/source；建 Project/Source；enqueue；commit |
| 二次输入检查与防重复 | `services/api/app/services/workflow.py::enqueue_workflow` 17–33 | 项目行锁、active job 检查、重验各来源 |
| durable 入队 | `services/api/app/engine/runner.py::enqueue_run` 90–116 | AnalysisRun + RunJob + run_queued event |
| worker 工作流 | `services/api/app/workers/run_worker.py::execute_workflow` 140、184–248 | collection → graph analysis → architecture → report |

注意：以上 active job 互斥在 workflow 入口；人工评审使用直接 enqueue_run，存在 IF-01。

### 报告：自动、手动、智能、评审与导出

| 环节 | 位置 |
|---|---|
| 自动报告 | `services/api/app/workers/run_worker.py` 242–248 |
| 手动/智能 API | `services/api/app/api/routes_reports.py` 30–63 |
| 报告选择 run、状态检查、渲染快照 | `services/api/app/services/reports.py::create_report_snapshot` 44–82 |
| run 选择 | 同文件 `get_run_for_report` 564–578 |
| 按 run 取分析包 | 同文件 `build_analysis_package` 581–619 |
| project 级资料查询 | 同文件 `build_inventory` 622–660（IF-02） |
| 确定性 Markdown | `services/api/app/reports/renderer.py::render_report_markdown` 75–123 |
| 项目速览 | `services/api/app/reports/project_brief.py::build_project_brief` 172 |
| 智能增强、router 调用 | `services/api/app/services/reports.py` 85–234；上下文构造 294–438 |
| LLM 引用校验和合并 | 同文件 159–219；`services/api/app/reports/llm_generator.py` 的 validate_llm_report_sections / merge_llm_report_markdown |
| 人工评审 | report/page.tsx 33–45 → lib/api.ts 212–220 → routes_reports.py 131–152 → services/reports.py 448–510 |
| 原文读取与导出 | routes_reports.py 75–108；PDF 由 app/reports/pdf.py 渲染已保存 markdown |
| 前端读取所选报告 | `apps/web/app/projects/[id]/report/page.tsx` 332–348 |
| 历史对比截止 | `services/api/app/reports/diff.py::build_report_package_snapshot` 35–48；仅过滤后写入分析项，不解决 IF-02 |

### 架构图

`apps/web/app/projects/[id]/architecture/page.tsx:114`
→ `apps/web/lib/api.ts:283`
→ `services/api/app/api/routes_architecture.py:14–19`
→ `services/api/app/architecture/service.py:81–94`（按 run 读取）。

`apps/web/components/diagram-regenerator.tsx:35–43`
→ `apps/web/lib/api.ts:293`
→ `services/api/app/api/routes_architecture.py:48–65`
→ `services/api/app/architecture/service.py:30–78`（纯保存快照重绘）。

自动全图生成：`run_worker.py:228–238`
→ `architecture/service.py:97–154`
→ CodebaseMap + 磁盘 import/class 读取
→ graph_json/Mermaid + stats_json.run_id 保存。
