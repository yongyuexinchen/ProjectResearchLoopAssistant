"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { statusLabel } from "@/lib/labels";
import { mergeRunEvents, parseSseFrame, runEventStreamUrl, streamTerminalState, type StreamEvent } from "@/lib/run-events";

const EVENT_LABELS: Record<string, string> = {
  run_queued: "任务已排队", run_retry_queued: "重试已排队", run_started: "开始处理",
  node_completed: "分析步骤完成", run_completed: "本轮分析结束", run_failed: "运行失败", run_cancelled: "任务已取消",
  workflow_stage_started: "开始处理", workflow_stage_completed: "阶段完成", workflow_stage_failed: "阶段失败",
  workflow_stage_skipped: "阶段已跳过", workflow_completed: "结果已就绪", workflow_paused: "等待补充信息",
  workflow_stage_running: "阶段处理中", run_resume_queued: "已排队继续处理",
};
const NODE_LABELS: Record<string, string> = {
  load_state: "读取调研配置", build_context: "整理资料上下文", analyze_sources: "分析工程与资料",
  update_analysis: "保存发现与证据", verify_package: "检查结果质量", decide_next_state: "判断调研是否完成", persist_state: "保存分析结果",
};

export function RunStreamPanel({ projectId, runId, runStatus }: { projectId: string; runId: string | null; runStatus?: string }) {
  const router = useRouter();
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connection, setConnection] = useState("正在连接");
  const [retryKey, setRetryKey] = useState(0);
  const sequence = useRef(0);

  useEffect(() => { sequence.current = 0; setEvents([]); }, [runId]);

  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    let stopped = false;

    async function connect() {
      if (controller.signal.aborted) return;
      setConnection(attempts ? "连接中断，正在恢复…" : "正在连接…");
      let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
      try {
        const response = await fetch(runEventStreamUrl(projectId, runId!, sequence.current, window.location.origin), {
          headers: { Accept: "text/event-stream" }, signal: controller.signal, cache: "no-store",
        });
        if (!response.ok || !response.body) throw new Error(`连接失败（${response.status}）`);
        reader = response.body.getReader();
        setConnection("实时更新中");
        attempts = 0;
        const decoder = new TextDecoder();
        let buffer = "";
        const pushFrame = (frame: string) => {
          const parsed = parseSseFrame(frame);
          if (!parsed) return;
          if (typeof parsed.data.sequence === "number") sequence.current = Math.max(sequence.current, parsed.data.sequence);
          const item: StreamEvent = { ...parsed, id: parsed.data.id ?? parsed.id ?? `${parsed.event}-${sequence.current}` };
          setEvents(current => mergeRunEvents(current, [item]));
          stopped = streamTerminalState(stopped, parsed.event);
          if (["run_queued", "run_retry_queued", "run_resume_queued", "run_started"].includes(parsed.event)) setConnection("实时更新中");
          if (["run_completed", "run_failed", "run_cancelled", "workflow_completed"].includes(parsed.event)) {
            setConnection("已同步最新结果");
            router.refresh();
          }
        };
        while (!controller.signal.aborted) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split(/\r?\n\r?\n/);
          buffer = frames.pop() ?? "";
          frames.forEach(pushFrame);
        }
        buffer += decoder.decode();
        if (buffer.trim()) pushFrame(buffer);
        if (["completed", "ready_for_review", "ready_for_review_with_risks", "failed", "cancelled", "paused_for_input"].includes(runStatus ?? "")) {
          stopped = true;
          setConnection("已同步最新结果");
        }
      } catch {
        if (!controller.signal.aborted) setConnection("连接中断，正在恢复…");
      } finally {
        reader?.releaseLock();
        if (!controller.signal.aborted && !stopped) {
          attempts += 1;
          reconnectTimer = setTimeout(() => void connect(), Math.min(10000, 1000 * 2 ** Math.min(attempts, 3)));
        }
      }
    }
    void connect();
    return () => { controller.abort(); if (reconnectTimer) clearTimeout(reconnectTimer); };
  }, [projectId, runId, runStatus, retryKey, router]);

  return (
    <details className="panel stack">
      <summary>运行明细 <span className="muted">· {runId ? connection : "启动后自动更新"}</span></summary>
      {runId ? <button className="button button-secondary" type="button" onClick={() => setRetryKey(key => key + 1)}>重新连接</button> : null}
      <div className="stream-events" role="log" aria-label="调研事件">
        {events.map(event => (
          <div className="stream-event" key={event.id}>
            <span className="stream-event__type">{EVENT_LABELS[event.event] ?? "任务更新"}</span>
            <strong>{event.data.node_name ? NODE_LABELS[event.data.node_name] ?? "分析步骤" : String(event.data.label ?? event.data.detail ?? event.data.message ?? EVENT_LABELS[event.event] ?? "处理中")}</strong>
            <span className="meta">{event.data.status ? statusLabel(event.data.status) : `事件 ${event.data.sequence ?? ""}`}</span>
          </div>
        ))}
        {!events.length ? <p className="muted">{runId ? "正在读取已保存的运行记录…" : "还没有运行记录。"}</p> : null}
      </div>
    </details>
  );
}
