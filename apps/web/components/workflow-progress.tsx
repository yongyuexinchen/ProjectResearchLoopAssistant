"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { getProjectWorkflow, reportMarkdownUrl, reportPdfUrl } from "@/lib/api";
import type { WorkflowState } from "@/types/project";
import "./workflow-progress.css";

const ACTIVE = new Set(["queued", "running", "resuming"]);
const STATUS: Record<string, string> = {
  idle: "准备开始", queued: "任务排队中", running: "正在自动调研", resuming: "正在继续调研",
  paused_for_input: "需要补充信息", completed: "调研结果已就绪", failed: "本次调研未完成", cancelled: "本次调研已取消",
};
const STAGE_STATUS: Record<string, string> = { pending: "等待处理", running: "处理中", completed: "已完成", skipped: "已跳过", failed: "失败" };

async function performAction(path: string): Promise<{ run?: { id: string } }> {
  const response = await fetch(path, { method: "POST", signal: AbortSignal.timeout(20000) });
  if (response.ok) return response.json();
  const body = await response.json().catch(() => null);
  throw new Error(typeof body?.detail === "string" ? body.detail : "操作未成功，请稍后重试。");
}

export function WorkflowProgress({ projectId, runId }: { projectId: string; runId?: string | null }) {
  const router = useRouter();
  const [state, setState] = useState<WorkflowState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const lastStatus = useRef<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    lastStatus.current = null;
    setState(null);
    async function update() {
      let nextDelay = 2500;
      try {
        const next = await getProjectWorkflow(projectId, runId, AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]));
        if (controller.signal.aborted) return;
        setState(next);
        setError(null);
        if (lastStatus.current !== next.status && !ACTIVE.has(next.status) && next.status !== "idle") router.refresh();
        lastStatus.current = next.status;
        if (!ACTIVE.has(next.status)) nextDelay = 12000;
      } catch {
        if (!controller.signal.aborted) setError("暂时无法读取进度，正在自动重连。后台任务会继续执行。");
        nextDelay = 5000;
      }
      if (!controller.signal.aborted) timer = setTimeout(() => void update(), nextDelay);
    }
    void update();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [projectId, runId, revision, router]);

  async function act(action: "start" | "cancel" | "retry" | "resume") {
    if (busy) return;
    const currentRun = state?.run;
    if (action !== "start" && !currentRun) return;
    setBusy(true);
    setError(null);
    try {
      const base = `/api/projects/${encodeURIComponent(projectId)}`;
      const result = await performAction(action === "start" ? `${base}/workflow` : `${base}/runs/${encodeURIComponent(currentRun!.id)}/${action}`);
      if (action === "start" && result.run) router.push(`/projects/${projectId}/run?run_id=${encodeURIComponent(result.run.id)}`);
      setRevision(value => value + 1);
      router.refresh();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "操作失败，请重试。"); }
    finally { setBusy(false); }
  }

  const status = state?.status ?? "idle";
  const active = ACTIVE.has(status);
  const ready = status === "completed" && Boolean(state?.report);
  const stages = state?.stages.length ? state.stages : [
    { key: "collection", label: "采集资料", status: "pending", detail: "读取目录、代码与文档" },
    { key: "analysis", label: "智能分析", status: "pending", detail: "梳理模块、证据与风险" },
    { key: "architecture", label: "生成架构图", status: "pending", detail: "生成可拖动查看的架构图" },
    { key: "report", label: "生成报告", status: "pending", detail: "汇总结果并检查质量" },
  ];
  return (
    <section className={`panel workflow-progress workflow-progress--${status}`} aria-label="自动调研进度">
      <div className="toolbar">
        <div>
          <p className="workflow-progress__eyebrow">AUTOMATIC RESEARCH</p>
          <h2 aria-live="polite">{state ? STATUS[status] ?? status : "正在读取任务状态…"}</h2>
          <p className="muted">{ready ? "报告已保存，可以查看调研结论、风险与架构图。" : active ? "后台会依次完成以下步骤。你可以离开此页面，稍后回来查看。" : "资料配置好后，启动一次即可自动完成调研和结果整理。"}</p>
        </div>
        <div className="workflow-progress__number">{state?.progress ?? 0}<span>%</span></div>
      </div>
      <progress className="workflow-progress__bar" max={100} value={state?.progress ?? 0} aria-label="调研完成进度" />
      <ol className="workflow-stages">
        {stages.map((stage, index) => (
          <li className={`workflow-stage workflow-stage--${stage.status}`} key={stage.key} aria-current={stage.status === "running" ? "step" : undefined}>
            <span className="workflow-stage__number">{stage.status === "completed" ? "✓" : index + 1}</span>
            <strong>{stage.label}</strong>
            <span className="workflow-stage__status">{STAGE_STATUS[stage.status] ?? stage.status}</span>
            {stage.detail ? <p className="muted">{stage.detail}</p> : null}
          </li>
        ))}
      </ol>
      {status === "queued" ? <p className="muted">等待后台处理。若长时间没有变化，请确认后台 Worker 已启动。</p> : null}
      {status === "paused_for_input" ? <p className="workflow-notice">有影响结论的问题需要你补充。请在下方“问题”中保存回答，再点击继续调研。</p> : null}
      {state?.error ? <p className="error-text" role="alert">{state.error}</p> : null}
      {state?.warnings.map((warning, index) => <p className="workflow-notice" key={`${index}-${warning}`}>{warning}</p>)}
      {error ? <p className="error-text" role="alert">{error}</p> : null}
      <div className="toolbar-actions workflow-progress__actions">
        {ready && state?.report ? <>
          <Link className="button" href={`/projects/${projectId}/report?report_id=${encodeURIComponent(state.report.id)}`}>查看调研报告 →</Link>
          {state.architecture_count > 0 ? <Link className="button button-secondary" href={`/projects/${projectId}/architecture?run_id=${encodeURIComponent(state.run?.id ?? "")}`}>查看架构图 · {state.architecture_count} 张</Link> : null}
          <a className="button button-secondary" href={reportMarkdownUrl(projectId, state.report.id)}>下载 Markdown</a>
          <a className="button button-secondary" href={reportPdfUrl(projectId, state.report.id)}>下载 PDF</a>
          <p className="muted">自动任务已完成，报告仍可在详情页人工评审。</p>
        </> : null}
        {state && status === "idle" ? <>
          <button className="button" disabled={busy} type="button" onClick={() => void act("start")}>{busy ? "正在启动…" : "开始自动调研 →"}</button>
          <Link className="button button-secondary" href={`/projects/${projectId}/sources`}>检查输入资料</Link>
        </> : null}
        {active ? <button className="button button-secondary" disabled={busy} type="button" onClick={() => void act("cancel")}>{busy ? "正在处理…" : "取消任务"}</button> : null}
        {status === "failed" || status === "cancelled" ? <button className="button" disabled={busy} type="button" onClick={() => void act("retry")}>{busy ? "正在重试…" : "重试自动调研"}</button> : null}
        {status === "paused_for_input" ? <>
          <Link className="button button-secondary" href={`/projects/${projectId}/run?run_id=${encodeURIComponent(state?.run?.id ?? "")}#questions`}>查看待补充问题</Link>
          <button className="button" disabled={busy} type="button" onClick={() => void act("resume")}>{busy ? "正在继续…" : "已补充，继续调研"}</button>
        </> : null}
      </div>
      <p className="meta">进度依据实际完成阶段更新，单个阶段耗时取决于资料量与模型响应。</p>
    </section>
  );
}
