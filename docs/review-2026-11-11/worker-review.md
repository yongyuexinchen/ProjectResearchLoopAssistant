# Worker / LangGraph 只读评审（2026-11-11）

评审基线 HEAD：`6b66b51c357fc893bb52c4d22d34777d09af4125`。以下行号均相对于此版本仓库根目录。实际加载依赖为 LangGraph 1.2.7、langgraph-checkpoint 4.1.1、SQLAlchemy 2.0.51。

先阅读了 `docs/STATUS.md`、`docs/ARCHITECTURE.md`、`README.md`；它们仅作为参考。仓库及项目目录至盘符根目录的所有父目录均未找到 `AGENTS.md`。未修改产品代码、未连接真实 MySQL、未调用模型服务。所有动态实验显式设置 `DATABASE_URL=sqlite+pysqlite:///:memory:`，并将 `LLMRouter.chat` 替换为离线返回；两项涉及独立事务的实验另建系统临时目录内的 SQLite 文件，结束后删除。

## 结论与验证范围

确认 4 项 P2、1 项 P3，未发现足以确认为 P1 的问题。每项将静态事实、实验观察和后果推断分开。报告没有把文档已承认的静态扫描边界重新列为缺陷。

现有针对性测试：

```text
python -m pytest -q tests/test_worker_leases.py tests/test_worker_recovery.py tests/test_interrupt_resume.py tests/test_workflow_api.py tests/test_mysql_checkpointer.py
32 passed, 1 warning in 7.43s
```

这些通过结果不覆盖下列确定性注入的时序窗口。

## P2-1：已完成 analysis 的重试分支在检查取消前重新提交运行状态

- **定位**：`services/api/app/workers/run_worker.py`，`execute_workflow` 第 221–226 行；相关 `reuse_stage` 第 159–165 行、`run_one_job` 第 86–87 行。
- **触发条件**：自动工作流 analysis 已完成、后续 report 等阶段失败；用户重试，然后在 collection 复用检查通过至 analysis 复用写状态之间取消。
- **静态事实**：复用 analysis 分支先无条件设置 `run.status = "ready_for_review_with_risks"`、设置项目状态并 `session.commit()`，之后才由 `reuse_stage("analysis")` 调用 `guard()`。取消将 job 改为 cancelled，后一个 guard 会退出 Worker，却不会撤销前一次已提交的状态覆盖。
- **复现方法**：离线创建自动工作流；注入 report 生成失败；POST retry；仅用包装器在 `stage_event(... collection ..., detail.startswith("已检查"))` 的原函数调用前执行真实 cancel API。这是 `reuse_stage` 的 guard 已返回、尚未写事件的确定性调度点。调用原 `stage_event` 并继续原 Worker。
- **动态证据**：在内存 SQLite 和独立会话的临时文件 SQLite 上均观察到：

```text
cancel_http=200
status_after_cancel=cancelled
final_run_status=ready_for_review_with_risks
final_workflow_status=running
report_exists=False
jobs=[('start','failed'), ('retry','cancelled')]
```

- **风险推断**：页面显示仍在运行，但没有 active job；retry 只接受 failed/cancelled、resume 只接受 paused，因此用户不能通过这两个恢复入口继续该 run。这一后果直接由已观察到的最终状态与接口状态约束推出。
- **建议**：让复用 analysis 的状态恢复也受取消/owner 检查保护，且把检查与该状态更新放进同一有效的数据库临界区；不要在 `reuse_stage` 检查之前提交状态。补充上述取消调度点的文件数据库回归测试。

## P2-2：普通分析 run 的 resume 绕过队列和取消检查

- **定位**：`services/api/app/api/routes_runs.py`，`resume_existing_run` 第 172–188 行；`services/api/app/engine/runner.py`，`resume_run` 第 119–146 行；`services/api/app/engine/langgraph_runner.py`，`resume_run_graph` 第 75–92 行、`commit_graph_step` 第 231–237 行。
- **触发条件**：通过受支持的 `POST /projects/{id}/runs` 创建普通分析 run，因缺少目标而暂停；回答问题后调用 resume，同时取消该恢复中的运行。
- **静态事实**：`workflow_job` 只认 payload 中 workflow=true 的 job。普通后台 run 即使有 start job，也落入直接 `resume_run(...)` 的同步 HTTP 分支。该分支不创建新 job；`resume_run_graph` 仅设置 `_GRAPH_SESSION`，未设置 `_GRAPH_GUARD`，后续节点的提交不检查取消或租约。Worker 第 57–60 行的非 workflow resume 分支也直接调用同一个无 guard 函数，但目前常规 API 不会创建这种 resume job。
- **复现方法**：用既有 `create_collected_project(..., analysis_goal=None)` 创建普通 run 并由 Worker 执行到暂停；回答问题；在恢复阶段的 `analyze_context` 包装器内调用真实 cancel API，再返回原分析结果；不改变图及其节点持久化代码。
- **动态证据**：

```text
cancel_http=200
status_after_cancel=cancelled
active_jobs_during_resume=0
resume_http=200
final_status=ready_for_review_with_risks
turns_after_cancel=['analyze_sources','llm_analyze_sources','update_analysis',
                    'verify_package','llm_verify_package','decide_next_state','persist_state']
```

- **风险推断**：用户确认取消后仍继续分析和落库，并覆盖 cancelled。因为恢复阶段无 durable active job，API 进程退出也没有可由 stale-job 恢复的 resume 任务。没有实际终止 API 进程，后一项属于基于缺少 job 的风险推断。
- **建议**：普通 run 与自动 workflow 使用一致的 resume 入队路径，恢复执行统一从带 guard 的 `stream_run_graph_events(..., resume_payload=...)` 进入；若继续保留同步兼容入口，也必须接入取消检查并明确其执行模式。

## P2-3：旧 Worker 的错误收尾可覆盖已由新 Worker 接管的 job

- **定位**：`services/api/app/workers/run_worker.py`，`run_one_job` 异常收尾第 89–100 行；同类成功收尾第 70–84 行；`require_job` 第 287–291 行。相关 `services/api/app/services/run_jobs.py`，`mark_job_failed` 第 158–161 行、`mark_job_succeeded` 第 152–155 行。
- **触发条件**：旧 Worker 在错误收尾事务读到自己仍是 owner 后被暂停/数据库调用延迟；租约过期并由另一 Worker 恢复领取；旧 Worker 随后继续提交错误。
- **静态事实**：owner 校验使用普通 `session.get` 取得的 ORM 快照，没有 `FOR UPDATE`，也没有 `UPDATE ... WHERE status='running' AND locked_by=...` 的条件更新。校验和提交之间 owner 可以改变；`mark_job_failed` 无条件更新 status、清空 owner，run/project 的 failed 更新同样没有 fencing 条件。
- **复现方法及范围**：使用两个独立会话的临时文件 SQLite，按异常收尾原语句顺序执行时序实验，而不是声称已经在真实 MySQL 或完整 daemon 上造成故障。A 读取 running/worker-a 并通过原 `ensure_loaded_job_still_owned`；B 将租约推进到过期，调用原 `recover_stale_jobs`、原 `claim_next_job(worker-b)` 并提交；A 按原异常块写 run/project failed、调用原 `mark_job_failed` 并提交。
- **动态证据**：

```text
before_old_error_commit={status:'running',locked_by:'worker-b',attempt_count:2}
after_old_error_commit ={status:'failed', locked_by:None,      attempt_count:2,run_status:'failed'}
```

- **风险推断**：新 Worker 在下一次 guard/heartbeat 时看到自己失去所有权而退出；job 已被旧 Worker 标成 failed，不再由 stale-job recovery 自动领取。这是从已观察到的状态与 guard/recovery 条件推出，未做真实 InnoDB 并发压力实验。
- **建议**：成功/失败终结使用基于当前 owner 和 attempt/fencing token 的数据库原子条件更新，只有更新成功才在同一事务内修改 run/project、写终结事件。也可在短收尾事务对 job 加排他锁并重新检查；锁顺序应与取消、stale recovery 一并设计。

## P2-4：checkpointer 的 pending write 索引让失败/中断后的成功输出被静默丢弃

- **定位**：`services/api/app/engine/checkpointer.py`，`SqlAlchemyCheckpointSaver.put_writes` 第 150–165 行。
- **触发条件**：同一 checkpoint/task 先写 `__error__` 或 `__interrupt__`，重试/恢复后再写普通输出；这些批次的第一个元素都使用 enumerate index=0。
- **静态事实**：本实现所有 channel 都直接使用 enumerate index，已存在就跳过。实际安装的 `langgraph/checkpoint/base/__init__.py:795` 定义 `WRITES_IDX_MAP = {ERROR:-1,SCHEDULED:-2,INTERRUPT:-3,RESUME:-4}`；同依赖的 `langgraph/checkpoint/memory/__init__.py:499–509` 对特殊 channel 使用保留负索引，并允许特殊项更新。项目实现忽略了这两个规则。
- **最小复现**：给同一 `config` 与 `task_id='same-task'` 依次调用：

```python
saver.put_writes(config, [('__error__', 'old failed attempt')], 'same-task')
saver.put_writes(config, [('score', {'overall_score': 93})], 'same-task')
print(saver.get_tuple(config).pending_writes)
```

- **动态证据**：相同 checkpoint 与操作，使用临时 SQLite 的项目 saver 和依赖自带 `InMemorySaver` 对照：

```text
SqlAlchemyCheckpointSaver:
  [('same-task','__error__','old failed attempt')]
LangGraph InMemorySaver:
  [('same-task','__error__','old failed attempt'),
   ('same-task','score',{'overall_score':93})]
```

- **风险推断**：成功输出没有进入 pending writes。若完整后继 checkpoint 落库之前再次崩溃，恢复端不能从 pending writes 取得该输出，可能重复执行已提交节点。这里证明的是 saver 数据丢失及其与依赖实现的偏差；没有声称正常的所有 resume 都失败（现有 resume 测试通过）。
- **建议**：遵守当前 LangGraph `WRITES_IDX_MAP` 的索引及特殊 channel 覆盖语义；为 error→成功、interrupt→resume、重复特殊写建立契约测试，并在完整 checkpoint 前注入崩溃检查恢复效果。

## P3-1：业务提交早于 checkpoint，恢复会重复持久化评分和节点轨迹

- **定位**：`services/api/app/engine/langgraph_runner.py`，`verify_package_node` 第 624–667 行、`commit_graph_step` 第 231–237 行；`services/api/app/engine/checkpointer.py`，`from_session_bind` 第 50–57 行、`_write_session` 第 191–194 行；`services/api/app/engine/runner.py`，`append_turn` 第 36–58 行、`latest_previous_score` 第 168–174 行。
- **触发条件**：节点已提交业务事实，但尚未把返回值/pending writes/checkpoint 持久化时进程终止。
- **静态事实**：节点自身 commit，checkpointer 另开事务 commit；`durability='sync'` 不会把两个数据库事务变成一个。`verify_package_node` 每次都新增 `QualityScore` 和 turn，且下一次读同 run 最近评分作为 previous_score，没有以 checkpoint/task 为键的幂等控制。
- **复现方法**：包装原 `verify_package_node`，先调用原函数（包括原业务 commit），在返回给 LangGraph 之前抛 `KeyboardInterrupt` 模拟退出；异常绕过 `run_one_job` 的 `except Exception`，job 保持 running；将租约置为过期、调用原 stale recovery，再由另一 Worker 执行原图。
- **动态证据**：

```text
scores_before_recovery=1
scores_after_recovery=2
verify_turns=2
score_deltas=[93,0]
run_status=ready_for_review_with_risks
```

- **风险推断与定级**：最终包可完成，但一次逻辑校验产生两条已完成轨迹，恢复后的 delta 也被自己的重复记录改变。因此列 P3，而非声称任务或报告丢失。LLM 节点存在同类事务窗口，但未调用付费模型验证重复计费，不能把计费损失作为本项已证事实。
- **建议**：为节点副作用引入稳定执行键并复用已提交输出，或统一业务事实与 checkpoint 的提交策略；至少在评分/turn 重放时去重并保留第一次的基准分。

## 可用于架构文档的真实调用链

以下是运行时代码路径；函数名与行号来自上述基线，不把 Mermaid 中的启发式箭头当作源码调用。

### 自动工作流建立、领取、执行

1. `routes_workflow.setup_project:17–35` 校验输入并创建 Project/Source，调用 `services.workflow.enqueue_workflow:17–32`；已有项目走 `routes_workflow.start_workflow:46–55`。
2. `enqueue_workflow:19–25` 锁项目并检查 active job，`32` 调 `engine.runner.enqueue_run:90–116`；后者通过 `run_jobs.create_run_job:22–44` 持久化 queued job，`run_events.record_run_event:29–63` 写 queued 事件；HTTP 最后提交。
3. 独立进程 `workers.worker_service.main:23–31` → `run_worker_loop:12–20`；循环先 `recover_stale_jobs:86–133` 并提交，再 `run_one_job:21–101`。
4. `run_one_job:31–50` → `claim_next_job:47–73`（队列/时间过滤、FOR UPDATE SKIP LOCKED、attempt+1），保存 running/resuming 与 started 事件并提交。
5. `run_one_job:53–56` → `maintain_job_lease:105–137`（后台线程调用 `heartbeat_current_job:270–284` → `heartbeat_job:76–83`）→ `execute_workflow:140–250`。
6. collection：`execute_workflow:184–198` → `collect_project_sources:37–122` → `collect_one_source:125+`。每源后提交，全部完成后保存 collection completed 事件。
7. analysis：`execute_workflow:203–220` → `langgraph_runner.stream_run_graph_events:95–163`。依次执行：`load_state_node:255` → `build_context_node:271`（`context.builder.build_analysis_context:8`）→ `analyze_sources_node:288`（`engine.analyzer.analyze_context:10`）→ `llm_analyze_sources_node:308` → `update_analysis_node:607`（`runner.persist_analysis_artifacts:197`）→ `verify_package_node:624`（`verifiers.quality.score_analysis_package:77`）→ `llm_verify_package_node:670` → `decide_next_state_node:813` → `persist_state_node:871`。
8. architecture：`execute_workflow:228–238` → `architecture.service.generate_architecture:97–154`，无代码库则保存 skipped 事件。
9. report：`execute_workflow:242–248` → `services.reports.create_intelligent_report_snapshot:85` → `create_report_snapshot:44` → `reports.renderer.render_report_markdown`，可选 `LLMRouter.chat` 增强后与 report completed 事件一起由 Worker 提交。
10. 收尾：`run_one_job:70–84` 将 job succeeded 并写 paused/completed 事件。工作流 UI 的 completed 并非 run 持久化成 completed：`services.workflow.workflow_state:47+` 根据 report、阶段事件和 run 状态派生展示状态。

### 中断、回答、恢复、重试、取消

- 中断：`decide_next_state_node:833–862` 先保存 paused/interrupt turn，再调用 LangGraph `interrupt`；`stream_run_graph_events:151–163` 将更新暴露给 Worker；`execute_workflow:213–216` 保存 analysis pending 并返回；job 成功结束以释放执行槽。
- 回答：`routes_runs.answer_question:192–216` 将 Question answered；缺少 analysis_goal 的问题会补 Project.analysis_goal。
- 自动工作流恢复：`routes_runs.resume_existing_run:168–182` 创建 resume job；Worker `execute_workflow:205–207` 把 payload 传为 `resume_payload`；`stream_run_graph_events:108` 构造 `Command(resume=...)`；重入中断节点后 `route_after_decision:206–211` 返回 build_context；`build_context_node:285` 清理 pending_interrupt 并重新分析。
- 普通 run 恢复：`routes_runs:183–188` → `runner.resume_run:119–146` → `resume_run_graph:75–92`，目前在请求线程内执行，区别见 P2-2。
- 用户重试：`routes_runs.retry_run:115–132` 复用 run/thread，创建 retry job；`execute_workflow:154–157` 从旧事件计算已完成阶段，复用阶段或继续图；`stream_run_graph_events:109–131` 使用已完成图 decision 或 `graph_input=None` 继续待执行节点。
- 过期恢复：`worker_service.run_worker_loop:16–18` → `run_jobs.recover_stale_jobs:86–133`；未耗尽重试次数转 queued，耗尽则写 job/run/project failed 与 run_failed 事件。
- 取消：`routes_runs.cancel_run:93–111` → `run_jobs.cancel_run_jobs:176–186`，清锁并保存 cancelled；后台图通过 `_GRAPH_GUARD` → `commit_graph_step:234–237` 检查所有权，Worker 外层通过 `JobLeaseLost` 返回。上述 P2-1、P2-2 是这条保护链的具体缺口。
- 断线重连：`routes_runs.stream_run_events:147–164` → `run_events.stream_run_events_live:118+`；按 sequence 补读持久事件，新 session 轮询 active job，无 active job 且历史已读完才结束，不靠浏览器保持图执行。

## 真实 MySQL 验证盲区（覆盖说明，不另算缺陷）

- `tests/test_mysql_checkpointer.py:10–13` 实际调用 `tests/test_runs_api.build_client:28–43`，数据库是 SQLite StaticPool，不是真实 MySQL。
- `test_worker_leases.py` 的两次 claim 在同一 session 顺序调用，未验证两个 InnoDB 事务的 SKIP LOCKED、锁等待或接管交错；长操作 lease 测试为文件 SQLite。
- `_GRAPH_GUARD` 在 SQLite StaticPool 走 `run_worker.py:123–128` 的特殊分支，生产 MySQL 走 `129` 及 `ensure_job_still_owned:260–262` 的另一会话；内存测试通过不能证明生产分支的取消/事务可见性。
- `.github/workflows/ci.yml:12–24` 只安装依赖并运行 pytest，无 MySQL service、migration-upgrade 或连接级 isolation 验证。尚未验证 InnoDB 的外键锁顺序、默认隔离级别下的 sequence 冲突重试和 checkpoint JSON 真实往返。
- 尤其 `run_events.record_run_event:42–61` 与 `audit.record_event:22–43` 在冲突后只回滚 savepoint，再读 MAX(sequence)，应放进真实 MySQL 独立事务测试验证读视图是否刷新；本评审没有连接真实数据库，故未将其定性为已复现缺陷。

建议下一轮在一次性 MySQL 实例运行两个连接的领取/接管/取消交错、特殊 pending writes、迁移空库升级及“业务 commit 后进程终止”实验。不要使用用户现有数据库作为这类故障注入目标。
