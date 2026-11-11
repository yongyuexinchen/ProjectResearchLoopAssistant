"use client";

import { useEffect, useRef, useState } from "react";
import { MermaidDiagram } from "@/components/mermaid-diagram";
import { regenerateArchitectureDiagram } from "@/lib/api";
import type { ArchitectureDiagram } from "@/types/project";

function errorMessage(caught: unknown): string {
  if (caught instanceof DOMException && caught.name === "TimeoutError") return "重新生成超时，请稍后重试。";
  if (!(caught instanceof Error)) return "重新生成失败，请稍后重试。";
  try {
    const body: unknown = JSON.parse(caught.message);
    if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") return body.detail;
  } catch { /* A network error may not contain JSON. */ }
  return caught instanceof TypeError ? "暂时无法连接后台，请稍后重试。" : caught.message;
}

export function DiagramRegenerator({ diagram }: { diagram: ArchitectureDiagram }) {
  const [source, setSource] = useState(diagram.mermaid_source);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);

  useEffect(() => {
    setSource(diagram.mermaid_source);
    setRevision(0);
    setBusy(false);
    setError(null);
    setNotice(null);
    return () => { requestRef.current?.abort(); requestRef.current = null; };
  }, [diagram.id, diagram.mermaid_source]);

  async function regenerate() {
    if (requestRef.current) return;
    const controller = new AbortController();
    requestRef.current = controller;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await regenerateArchitectureDiagram(diagram.project_id, diagram.id,
        AbortSignal.any([controller.signal, AbortSignal.timeout(20000)]));
      if (controller.signal.aborted) return;
      if (updated.id !== diagram.id || updated.project_id !== diagram.project_id || !updated.mermaid_source?.trim()) {
        throw new Error("后台返回的图信息不完整，请重试。");
      }
      setSource(updated.mermaid_source);
      // The saved source can be unchanged. A new canvas still retries a failed browser render.
      setRevision(current => current + 1);
      setNotice("已重新生成此图。");
    } catch (caught) {
      if (!controller.signal.aborted) setError(errorMessage(caught));
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return (
    <div className="stack" data-diagram-id={diagram.id}>
      <div className="toolbar">
        <p className="meta">可根据本次调研保存的结构，单独重新生成这张图。</p>
        <button className="button button-secondary" type="button" disabled={busy}
          aria-label={`重新生成${diagram.title || "此图"}`}
          onClick={() => void regenerate()}>{busy ? "正在重新生成…" : "重新生成此图"}</button>
      </div>
      {error ? <p className="error-text" role="alert">{error}</p> : null}
      {notice ? <p className="muted" role="status">{notice}</p> : null}
      <MermaidDiagram key={`${diagram.id}-${revision}`} source={source} title={diagram.title || "架构图"} />
    </div>
  );
}
