# Research Workflow Implementation Plan

> Agentic workers: execute independent tasks in the current session, verify behavior before claiming completion.

**Goal:** 可逐步配置、自动完成调研、持续显示进度，并方便拖动查看架构图。

**Architecture:** 复用现有后台 RunJob，使用 payload 标记自动流程，通过持久事件推导阶段。独立前端组件处理配置、进度与图交互。

**Tech Stack:** Next.js / React / TypeScript / Mermaid / FastAPI / SQLAlchemy / LangGraph。

**Spec:** ../specs/2026-11-11-research-workflow-design.md

## Global Constraints

在原项目目录修改；不读取或输出密钥；不调用付费模型验证；不新增不必要依赖；保留原工具页。

## Review Focus

刷新与断线重连；取消或重试的旧事件；缺失模型配置与文本资料；长时间阶段续租；向导错误后的表单恢复。

### Task 1: 后台自动流程

- [x] 为原子配置、阶段完成/失败、取消/重试、报告绑定和文本资料添加失败测试。
- [x] 增加 schemas/workflow.py、api/routes_workflow.py 与 services/workflow.py；复用 run job。
- [x] 在 worker 中接入采集、分析、架构图、报告，保留重试标志并维护租约。
- [x] 运行新增测试和全部后端回归。

### Task 2: 配置向导

- [x] 替换 projects/new 页面，增加 project-setup-wizard.tsx 与专属样式。
- [x] 分步验证、返回保留、多资料、模型就绪提示、确认页与提交防重。
- [x] 提交 POST /api/projects/setup，跳转指定 run_id 的运行页。

### Task 3: 进度、事件和入口

- [x] 新增工作流类型、API 和 workflow-progress 组件。
- [x] 自动读取持久工作流状态与事件，取消卸载连接，恢复与重试时重新订阅。
- [x] 运行页与概览展示主路径；修复相对 URL 构造错误，区分服务端和浏览器 API 地址。
- [x] 为 SSE 帧解析和关键状态行为添加回归检查。

### Task 4: 架构图

- [x] 为缩放中心与适应屏幕几何添加失败测试。
- [x] 实现 inline/fullscreen 拖动、滚轮缩放、重置与键盘操作。
- [x] 严格 Mermaid 渲染、独立 SVG ID、处理源变更与过期渲染。

### Task 5: 集成验证

- [x] 独立审查最终实现并修复影响主流程的问题。
- [x] 完成后端测试、前端类型检查和生产构建。
- [x] 本机浏览器检验并记录已验证范围与任何环境限制。

## Execution record

并行职责：backend_audit 负责后端与测试，configuration_wizard 负责向导，diagram_interaction 负责架构图；主代理负责进度、事件、入口、文档和集成。当前目录不属于 Git 仓库，无法创建 worktree 或提交，保留本地修改。

完成记录：所有任务已实现并验证。独立审查发现并修复历史任务重试并发、回答跳转、架构图串版本与旧失败事件影响重连；浏览器验收另修复扁平目录空白图和 UTF-8 BOM 的 AST/import 扫描。后端最终 295 通过、1 跳过；前端 12 通过；生产构建通过。浏览器离线完整验收覆盖四步向导、100% 结果、报告内容、全屏拖动和鼠标缩放、适应画布与 Esc 焦点返回。

现有 API/Worker 进程没有热重载。停止现有服务的动作被自动审批拒绝（仅给出 blocked by policy），没有尝试通过其他方式终止这些服务。已准备 restart-all.ps1，完成 PowerShell 语法检查与 -WhatIf 预览，供用户明确执行重启。页面已展示本机 /projects/new 的新向导。

后续修复：用户反馈启动 405，已确认旧进程未加载新接口；新增 BackendOnly 模式并成功重启 API/Worker，保留前端页面。启动检查同时确认配置与工作流接口。

单图重生成：新增每图独立按钮与 POST /projects/{id}/architecture/{diagram_id}/regenerate，只按保存的图快照更新该图 Mermaid 源码。修复 actor/end 等标识符冲突，保留可读标签并转义语法字符。新接口支持历史图，异常快照不会覆盖原图。独立审查未发现重要问题；后端最终 312 通过、1 跳过，前端 12 通过、类型检查和生产构建通过。已在用户真实“监控大屏调研”的原报错时序图上点击按钮验证：正常显示 SVG、无错误，其他四张图数据库记录及查看缩放位置保持不变，目标图的 ID/graph_json/run 元数据保持不变。没有模型调用或重新调研。
