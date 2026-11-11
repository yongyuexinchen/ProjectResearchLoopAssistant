# 报告源码图集成实施记录

日期：2026-11-11。对应已批准方案和 Task 3；未提交或推送。

## 实现

- `services/api/app/reports/architecture.py` 按 project + 精确 `stats_json.run_id` 复制 ArchitectureDiagram 的 Mermaid、graph/details 和来源元数据。完整 JSON 副本保存在 `verifier_result_json.architecture_diagrams`；不存在匹配图时保存空列表，明确写资料缺口。
- 普通报告追加“源码流程与架构图”章，携带 Mermaid、节点、文件 hash、函数定义位置、分类语句位置、静态调用点和可读目标位置。源码文本做 Markdown/HTML 转义。智能增强拆出该章，在文字合并后原样放回，不能改写确定性图。
- Markdown/PDF 导航最多展示 120 函数、1200 语句/调用、每函数 24 项、80 文件；超限写明展示数/总数和完整索引仍在在线报告中可搜索。完整图索引未被截掉。
- 在线报告新增 `ReportArchitectureSection`，直接用保存的 Mermaid 渲染画布，并复用 SourceNavigator 搜索完整的本次图索引；不查询最新架构，也不提供修改旧报告图的操作。
- PDF 直接用 ReportLab 绘制保存的节点卡片和真实连接箭头，显示调用行号；自动换行、分页和页码。跳过对应 Markdown Mermaid 章的文本源码，改绘矢量图及有预算的导航；不请求网络渲染服务。只规范化图标签的 `<br/>`，源码摘录仍按原样文本输出。
- 修复 IF-03：普通/智能生成 action 绑定当前显示报告的 run_id；成功后跳至新快照 report_id。

## 验证证据

- 先写 6 个后端测试，确认全部因缺少报告图集成而失败，再实现到通过。
- 给历史报告两种生成动作写真实页面/API-helper 边界测试；原实现二者都失败（run_id undefined），修复后二者通过。
- 增加已解析目标可读性断言，先失败、再改为函数名 + 文件/定义行。
- 增加导航预算与 graph `<br/>`/源码字面值分离两项测试，先失败、实现后通过。
- 最后相关后端：`test_report_architecture.py`、`test_report_export.py`、`test_reports_api.py`、`test_llm_report_generator.py`、`test_report_renderer.py`、`test_report_diff.py`，**35 passed**。
- 最后前端：`npm test`，**19 passed**；`npx tsc --noEmit`，**exit 0**。
- 曾按要求运行全后端：**348 passed / 19 failed / 2 skipped**；19 个失败全部属于另一个并行实现尚未落地的 source_flow/parser/integration（模块缺失或 graph None），已向主线程报告。主线程将在解析器落地后统一最终运行，未把本次范围测试当作全仓库通过。
- 所有测试使用内存 SQLite/临时资料；模型增强测试替换 LLMRouter.chat，不使用真实数据库、付费模型或真实网络。

## PDF 样例

`.tmp/report-qa/sample-report.pdf`，6 页；第 6 页包含矢量节点、连接箭头及源码行号导航。主线程首次 Poppler 检查确认基本可读，并指出标题贴近上方图框；现已将节点/连接框后的留白分别增加至 18/20pt，重新生成同路径样例。此调整后架构报告/导出 10 项测试通过，等待主线程视觉复核；不将文本提取通过等同于布局检查通过。

## 本次未扩展

未修复原评审 IF-01、IF-02、IF-04、IF-05、IF-06；未改变 worker、源码解析器、架构页、通用图类型或 SourceNavigator。报告图快照实现不宣称解决其他旧资料的 run 隔离缺陷。
