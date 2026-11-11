# 确定性扫描、证据链与五档报告专项评审

评审日期：2026-11-11。只读评审；未修改产品代码；未连接真实数据库或真实/付费模型。先阅读了 `docs/STATUS.md`、`docs/ARCHITECTURE.md`、`README.md`，将其作为待核对的说明；检查项目和祖先目录，未发现适用的 `AGENTS.md`。

## 结论

五档有真实的章节、确定性分析分支、质量权重和 verifier 检查差异，并非仅换标题。但它们共享同一批目录、文件名、README 和依赖清单事实；没有五种不同的代码理解算法。报告较明确地说明静态边界，但存在会直接影响结论的实现错误：无 README 被写成已具备、标准 Go 测试漏检、自造模型证据被认可、模型摘要绕过引用要求、多库聚合事实挂错证据、同名类被合并。

本专项未发现需要独立定为 P1 的可靠问题。下面将能直接复现的 P2 和较低优先级的 P3 分开，避免把已明确承认的“非运行时调用链”“多库图只用最近地图”等边界当成新缺陷。

## P2 发现

### E1：模型可自造无来源证据，再用它证明自己的发现

- **定位**：`services/api/app/llm/analyzer.py`，`_validate_evidence_items` 149–168、`validate_llm_analysis_output` 227–230；调用链见 `app/engine/langgraph_runner.py` 379–389、`app/engine/llm_merge.py` 8–27、`app/engine/runner.py` 206–225。
- **触发**：模型返回一个新 `llm:*` evidence，字段非空即可，无需 source id、源证据引用、文件位置或派生依据；finding 只引用这条新 evidence。
- **静态事实**：校验将本次模型创建的 refs 并入 allowed refs；持久化给它正常 `EvidenceItem.id`；没有检查其祖先必须是采集证据。`app/verifiers/package.py:335–359` 只检验 finding/risk 是否指向包内 id，`quality.py:19–23` 只看引用列表非空。
- **独立复现**：allowed refs 仅含 `evidence:real`，提交 evidence `llm:made-up`（summary 为“Deployed to production with all tests passing”）及只引用它的“Safe to ship” finding，validator 返回 `accepted=True, messages=[]`；模拟持久化后的对应包通过 `check_evidence_coverage`。
- **影响/推断**：模型错误可以被包装成“确定性校验通过”的已落库证据。后续报告和复核仍可能发现错误，但当前证据结构不保证结论来自采集材料。此处问题是结构允许完全无来源的派生证据，不是要求规则证明任意自然语言断言正确。
- **建议**：模型解释保留为 advisory artifact；如允许派生 evidence，强制非空 `derived_from` 且只能指向已有采集证据，并在持久化和 verifier 中验证来源链，不让仅模型生成的 evidence 单独满足采集覆盖要求。

### E2：智能报告的 executive_summary 完全绕过证据引用要求

- **定位**：`app/reports/llm_generator.py`，`validate_llm_report_sections` 58–70、118–120；`merge_llm_report_markdown` 176–183、186–189。
- **触发**：返回 `{"executive_summary":"Production deployment and all tests have passed.","sections":[]}`。
- **静态事实**：executive summary 只校验字符串和长度，不校验引用；空 sections 被允许；渲染时 summary 使用空 refs 直接插入“执行摘要 / 模型补充解读”。
- **独立复现**：即便 `allowed_evidence_refs=set()`，上述 payload 仍 `accepted=True, messages=[]`，渲染内容包含该断言且没有证据引用。
- **影响**：受证据约束的正文入口存在零引用旁路。这里只指出可结构化拦截的漏洞，不把“有效 id 不一定支持正文”泛化成无法实现的语义校验要求。
- **建议**：为 summary 定义显式 evidence refs 并校验；至少要求非空已验证 section，并由这些 sections 生成摘要，或将不受引用约束的摘要明确排除在受校验证据正文之外。

### E3：缺失 README 的 None 被转成字符串，确定性发现误报“已具备”

- **定位**：`app/engine/profile_analysis.py`，`readme_excerpt` 476–477；使用处 70–81、`delivery_present` 414–415、`delivery_missing` 429–430。
- **触发**：扫描一个含 `main.py`、没有 README 的真实目录。扫描器正常返回 `readme_excerpt=None`。
- **静态事实**：辅助函数执行 `str(None)` 得到 `"None"`，后续 `first_text` 将它视为已有文本。
- **独立复现**：`quick_onboarding` 生成“已具备项目说明材料：README 提供了项目用途或启动线索”，且没有缺少 README 的专项风险；`delivery_acceptance` 的“交付完整性快照”包含“README”，且缺失项不含 readme。
- **影响**：同一报告的项目速览/渲染检查可能正确写出缺少 README，而发现列表和证据链却肯定它存在，形成直接矛盾，模型增强也会读到该错误发现。
- **建议**：保留 None 语义，用 `value or ""` 归一化；覆盖 None、缺键、空白字符串及正常 README 四种情况。

### E4：标准 Go 的 *_test.go 测试漏检，二开和验收得出错误“没有自动化测试”

- **定位**：`app/tools/code_scan_tools.py`，`is_test_file` 292–303，扫描写入 536–537；`profile_analysis.py` 185–195。
- **触发**：Go 标准布局，例如 `pkg/hello.go` 和 `pkg/hello_test.go`，没有额外名为 test/tests 的目录。
- **静态事实**：识别规则包含 `_test.py`、`.test.`、`.spec.`，遗漏 `_test.go`。
- **独立复现**：`is_test_file("pkg/hello_test.go") == False`。
- **影响**：扫描的 `test_files` 为空，二开专项写“没有自动化测试，任何改动都只能依赖手工回归”，提高风险和成本；验收检查缺测试，教学报告安排手工验收。Go 是代码显式支持的入口/技术栈，所以这不是未声明语言支持的边界。
- **建议**：识别 Go 的标准后缀；同一分类函数同时用于主语言统计、报告模块筛选与扫描清单，应做跨消费者验证。

### E5：多库/多地图聚合事实统一引用第一份地图，证据链挂错来源

- **定位**：`app/engine/profile_analysis.py` 28–37、119–130；`all_modules` 480–485；`app/engine/analyzer.py` 188–199。
- **触发**：两个地图：m1 仅含 `main.py`，m2 含 `server.js` 和 `package.json`。
- **静态事实**：entrypoints/dependencies/configs/tests/modules 都从全部地图聚合；`codebase_ref=first_ref(refs["codebase"])`；大部分档位 finding/risk 仅使用这个第一 ref。
- **独立复现**：架构发现输出“入口 main.py, server.js 通过 package.json 完成配置与依赖装配”，但 refs 只有 `evidence:codebase:m1`，m1 没有 server.js/package.json。
- **影响**：即使证据 id 有效，追溯到它也看不到支持结论的材料。这与文档已经承认的“多库图只用最近地图”是不同问题：这里是报告发现引用错误；同一 source 的多次历史地图也可触发。
- **建议**：按 source/map 生成发现，或对聚合发现收集全部参与 ref；README/定位也应和实际提供该材料的 snapshot/map 配对。

### E6：UML 类节点只用类名作 id，不同文件同名类被合并

- **定位**：`app/architecture/uml.py`，`build_class_diagram` 94–116；`app/architecture/mermaid.py` 55–69、91–98。
- **触发**：`a.py`、`b.py` 都定义 `class Config`，分别有 alpha/beta 方法。
- **静态事实**：节点 id 为 `_node_id("c", item["name"])`；继承索引 `by_name` 也用短类名；Mermaid renderer 以同一 node.id 映射一个 Mermaid 节点。
- **独立复现**：graph 中出现两个 `c_Config`，渲染结果是同一个 `node_0` 被声明两次，并同时拥有 alpha() 和 beta()。
- **影响**：在常见同名 Config/Base/Client/Result 的代码库，图显示不存在的聚合类，继承边还可能指向另一模块的同名类。Python 虽使用 AST，身份关系仍失真。
- **建议**：使用相对文件路径加限定类名生成稳定唯一 id；继承无法解析完整命名空间时保留未解析关系，不按全局短类名猜测。

## P3 发现

### E7：二开报告把“发现一个测试文件”直接写为低回归成本

- **定位**：`app/reports/renderer.py`，`render_test_config_complexity` 822–837，特别是 834；`render_extension_feasibility` 792。
- **触发**：只要扫描列表有任意测试文件，即便文件为空、没有断言或完全不覆盖改造点。
- **静态事实**：`if tests` 即“回归成本：低（有测试基线）”；同一节后面又说扫描无法判断覆盖率和测试质量。配置数量 <=3 判低成本；技术栈标签数量 <=4 判低依赖成本，这些也没有项目目标或依赖数量依据。
- **性质**：可复现的规则输出；“实际成本可能很高”是推断。本专项不将静态规划建议本身当成错误，只指出被写成结论的成本等级超出实际证据。
- **建议**：改为“存在测试文件；回归成本待确认”，把配置/依赖数量作为观察，给出待验证的复杂度因素；若保留评分，标注明确启发式、不能作为工时结论。

### E8：按策略跳过 .env.example 后，验收报告断言“未发现样例”

- **定位**：`app/tools/path_policy.py` 33–35、79–87；`app/reports/renderer.py` 1101–1105。
- **触发**：仓库存在常规 `.env.example` 或 `.env.sample`。
- **独立复现**：扫描器将 `.env.example` 记录为 `skipped_items=[{"path":".env.example","reason":"sensitive_path"}]`；后续 renderer 只查询 file_tree，必然认为没有环境变量样例。
- **影响**：报告把“未读取内容”写成“资产不存在”，无谓地增加交付缺口。这里不建议读取潜在敏感内容；现有跳过路径足以确认样例路径存在，内容完整性应标为未核验。
- **建议**：缺口计算同时考虑 skipped_items，使用“样例路径存在、内容按敏感策略未采集”，不要将安全过滤变成缺失证据。

## 五种方式的真实差异

共同链路：同一 `scan_codebase` → `build_analysis_context` → `analyze_context` → `build_profile_artifacts`；每档不是再次扫描或调用不同代码分析器。五档都先渲染同一 `build_project_brief`，再走独立章节函数。五档配置唯一后端定义是 `app/research/profiles.py:42–240`。

| 档位 | 确定性分析分支 | 主要独立渲染及定位 | 专项检查 | 真实程度与限度 |
| --- | --- | --- | --- | --- |
| 快速接手 | `profile_analysis.py:58–105`；入口、说明材料、缺 README 风险、30 分钟建议 | `renderer.py:403` 接手指南、435 启动线索、459 架构地图、482 阅读项、504 30 分钟路线、521 后续路径、550 确认事项 | entrypoint、dependency、reading_path | 有真实文件阅读顺序和 README 命令摘录；30 分钟是固定规划建议，没有验证实际启动时间；受 E3 影响 |
| 架构理解 | `profile_analysis.py:107–157`；顶层模块、装配线索、未验证主流程风险 | `renderer.py:590` 定位、635 模块、675 流程、705 外部依赖、728 扩展点、748 缺口 | module_boundaries、entrypoint、architecture_clues | 模块计数和代表文件真实；主流程是固定“入口→装配→模块→输出→测试”骨架，已标注静态推断，不是调用链；多库 refs 受 E5 影响 |
| 二开评估 | `profile_analysis.py:159–220`；候选改造面、测试线索、缺测试高风险、POC 建议 | `renderer.py:772` 改造面、788 可行性、805 风险、822 成本、842 分期、855 证据缺口 | test_clues、risk_register、mitigation | 输出确实不同；可行性基于文件存在性，POC→回归→放量为通用方案；未分析目标差异、修改传播或真实工时；E4/E7 会误判 |
| 教学拆解 | `profile_analysis.py:222–269`；课程主线、代码样例、测试练习 | `renderer.py:876` 目标、892 章节、926 讲解顺序、951 难点、974 练习、1002 材料缺口 | key_files、learning_path、exercises | 模块>80 个文件会下钻子模块，章节可落到代表文件；练习任务有可验证输出，但并未阅读函数实现自动讲解算法；E4 可错误安排手工练习 |
| 交付验收 | `profile_analysis.py:271–341`；交付完整性与 README/入口/依赖/配置缺口 | `renderer.py:1020` 范围、1034 完整性、1065 可启动性、1089 运维、1113 问题、1127 结论；1463 verdict | runbook_clues、open_questions、delivery_readiness_summary | 真正的五类资产清单和通过/有条件通过/不通过分类；只检查资产线索，不构建、部署、执行；报告明示该边界，但 E3/E8 会自相矛盾 |

质量权重也不同：`quality.py:113` 用当前 profile 的六维权重计算总分。例：二开将风险透明度权重设为 0.24，教学将建议可信度设为 0.22；这些是不同加权，不能等同于不同的实际分析深度。专项 verifier 缺失均为 warning（`package.py:116–139`）；它们并不证明各档的核心问题已经被深入回答。

## “证据链”实际语义

1. `analyzer.py:27–49` 从每个 snapshot 创建 source_snapshot evidence，摘要是采集文本或通用“已采集”语句；置信度固定 85。
2. `analyzer.py:105–123` 从每个 map 创建 codebase_map evidence；摘要只说明技术栈，metadata 保存依赖/入口/测试路径，置信度固定 90。
3. Finding/risk 先引用 draft client_ref，`runner.py:197–260` 持久化后替换为数据库 evidence id。
4. `package.py:335–359` 证明引用命中“本分析包中的 id”，没有证明文本蕴含关系、源码行号、运行行为或派生链；目前只需一个有效 ref 命中。
5. `renderer.py:1249–1280` 生成“发现→证据标题/摘要”的展示。这是引用索引，不是编译级数据流或运行证据追踪。E1/E5 是可具体修复的来源漏洞。
6. snapshot 状态不会在 `analyzer.py:27–49` 过滤；failed/skipped 也被命名为“已采集输入源”。`context/builder.py:15–27` 与 `services/reports.py:622–635` 读取项目所有历史 snapshots/maps，未按 source 选择最新或绑定 run；历史污染/报告隔离由主评审另行统一分析，避免重复计项。

## 大仓库性能与图形能力：已证实范围

- 全量采集 `scan_codebase:477–567` 使用 os.walk，过滤目录和超单文件体积，但没有文件总数、总耗时、总 JSON 体积上限；file_tree 和 skipped_items 全部保留。复杂度随目录树增长，不应将“单文件限额”等同于“整个超大仓库有硬预算”。
- `file_tools.py:8–11` 先 read_text 完整读取再切 excerpt；普通扫描会先受 1MB 默认单文件限额约束，不是流式读取；没有观察到无限单文件读取的正常扫描路径。
- import 图限制为 240 个文件、每个 128KB（`graph_builder.py:14–20,208–265`）；类图 120 个文件/36 类（`uml.py:20–23,55–123`）。这些是图源码采样预算，不是全量采集预算。
- 模块图来自 file_tree（`graph_builder.py:127`）；跨一级模块 import 图用正则（208/363/371），Python/JS 支持有限。Go/Java 虽能进入候选，提取仍走 JS 正则，不能称为相应语言完整依赖图。
- data_flow 是目录角色分类与 import 边，缺 import 时人为按层顺序相连，并在 notes 说明示意（268–327）。
- UML component 复用 import 图；Python class 用 AST，JS/TS class 用正则；sequence 根据 import 权重生成阅读骨架，notes 已承认静态近似。E6 超出这些已知边界，属于明确身份错误。
- 单图 regenerate 仅从 graph_json 重渲染，不会重扫或调用模型（`architecture/service.py:31–38`），文档这项描述属实。
- 未做真实超大仓库耗时/峰值内存基准，因此不报告未经实测的具体吞吐或“性能合格”。以上未当作新 P2，供能力说明使用。

## 真实函数链与细架构图定位

所有路径以下均相对 `services/api`；箭头表示实际调用或顺序，分支为注明的启发式/可选步骤。

### 采集与扫描

`workers/run_worker.execute_workflow:140`
→ collection 阶段 `:184–198`
→ `services/collection.collect_project_sources:37`（每源异常转 failed snapshot）
→ `collect_one_source:125`
→ local_directory `:145` / github_repo clone `:159` 后
→ `tools/code_scan_tools.scan_codebase:477`
→ `path_policy.should_skip_path:53`
→ `extract_manifest:392` → `file_tools.read_text_excerpt:8`
→ `detect_stack:276`, `is_test_file:292`, `infer_entrypoints:169`
→ 持久化 SourceSnapshot `collection.py:63`、CodebaseMap `:77`。

### 分析、模型与证据持久化

`execute_workflow:205`
→ `engine/langgraph_runner.stream_run_graph_events:95`
→ `build_loop_graph:166`：`load_state_node:255`
→ `build_context_node:271` → `context/builder.build_analysis_context:8`
→ `analyze_sources_node:288` → `engine/analyzer.analyze_context:10`
→ `reports/project_brief.build_project_brief:172`（parse_readme 246、resolve_tech_stack 564）
→ `engine/profile_analysis.build_profile_artifacts:15`
→ 可选 `llm_analyze_sources_node:308`
→ `build_llm_analyzer_prompt:524`（compact_context 493 / compact_analysis 443）
→ `LLMRouter.chat` → `llm/analyzer.validate_llm_analysis_output:215`
→ `engine/llm_merge.merge_llm_analysis:8`
→ `update_analysis_node:607`
→ `engine/runner.persist_analysis_artifacts:197`：EvidenceItem → ref_map → Finding/Risk/Question/Recommendation。

### 质量评分与报告校验要分成两层

`langgraph_runner.verify_package_node:624` 的实际动作是
→ `verifiers/quality.score_analysis_package:77`
→ QualityScore 落库 `:648`
→ 可选 `llm_verify_package_node:670`
→ `decide_next_state_node:813` → `persist_state_node:871`。

真正调用确定性 package verifier 的位置在报告层：
`services/reports.create_report_snapshot:44`
→ `build_analysis_package:581` + `build_inventory:622`
→ `verifiers/package.verify_analysis_package:9`
→ structure 318、evidence 335、codebase 363、risk 401、question 417、quality 437、profile 116
→ report.status=draft/blocked `:69`。

### 五档报告与智能增强

`execute_workflow:244`
→ `services/reports.create_intelligent_report_snapshot:85`
→ `create_report_snapshot:44`
→ `reports/renderer.render_report_markdown:75`
→ `resolve_profile:121`、`build_project_brief:172`
→ `render_project_brief:205`
→ `render_profile_report_sections:300` 遍历 `ResearchProfile.section_plan`
→ `profile_section_body:322` 分发五档专属函数
→ `render_conclusion:1145` / `profile_verdict:1175`
→ `render_evidence_chain:1249` + 索引/校验/附录
→ ReportSnapshot。
可选增强：
`build_llm_report_messages:294` → `LLMRouter.chat`
→ `reports/llm_generator.validate_llm_report_sections:46`
→ `merge_llm_report_markdown:129`
→ `services/reports.py:221` 更新当前 report.markdown_content。

### 图生成与重生成

`execute_workflow:235`
→ `architecture/service.generate_architecture:97`（选最近 CodebaseMap）
→ `graph_builder.codebase_map_payload:83`、`resolve_source_root:97`
→ `build_module_map:127`
→ `build_dependency_flow:208` → `_select_scan_files:330` / `_extract_imports:363` / `_resolve_import_module:371`
→ `uml.build_component_diagram:29`、`build_class_diagram:55`、`build_sequence_diagram:126`
→ `graph_builder.build_data_flow:268`
→ `mermaid.render_mermaid:13`：flowchart 23 / classDiagram 55 / sequenceDiagram 80
→ ArchitectureDiagram（graph_json + mermaid_source + run_id stats）`service.py:136–149`。
单图：`api/routes_architecture.regenerate_architecture_diagram:49`
→ `service.regenerate_diagram:31` → `_graph_from_snapshot:41` → `render_mermaid:13`。

## 验证记录

执行现有定向回归：
`test_readonly_scanners.py`、`test_scan_and_brief_quality.py`、`test_profile_specific_analysis.py`、`test_profile_report_content.py`、`test_profile_report_merge.py`、`test_llm_analyzer.py`、`test_llm_report_generator.py`、`test_architecture_module_map.py`、`test_architecture_mermaid.py`。

结果：**83 passed, 1 skipped in 1.05s**。跳过的是本机 Windows 符号链接权限相关测试。LLM 相关测试的服务调用均 monkeypatch，数据库使用测试内存 SQLite；未使用真实业务 DB。

额外用系统临时目录及纯函数独立实验确认 E1–E6、E8；目录自动清理，未新增测试文件、未改变产品文件。现有测试通过只证明已有用例覆盖到的行为，不能覆盖本报告新增反例。
