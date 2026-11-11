"use client";

import { useEffect, useState } from "react";

import { MermaidDiagram } from "@/components/mermaid-diagram";
import { SourceNavigator } from "@/components/source-navigator";

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

export function ReportArchitectureSection({ verifier, projectId, reportId }: {
  verifier: unknown;
  projectId: string;
  reportId: string;
}) {
  const saved = record(verifier)?.architecture_diagrams;
  const [detailsById, setDetailsById] = useState<Record<string, unknown>>({});
  const [sourceRequested, setSourceRequested] = useState(false);
  const [sourceLoaded, setSourceLoaded] = useState(false);
  const [sourceError, setSourceError] = useState("");

  useEffect(() => {
    if (!sourceRequested || !Array.isArray(saved) || !saved.length) return;
    const controller = new AbortController();
    async function loadSourceIndex() {
      try {
        const response = await fetch(
          `/api/projects/${encodeURIComponent(projectId)}/reports/${encodeURIComponent(reportId)}/source-index`,
          { cache: "no-store", signal: controller.signal },
        );
        if (!response.ok) throw new Error("source index request failed");
        const body: unknown = await response.json();
        const rows = record(body)?.diagrams;
        if (!Array.isArray(rows)) throw new Error("source index format invalid");
        const next: Record<string, unknown> = {};
        for (const row of rows) {
          const item = record(row);
          if (item && typeof item.id === "string" && record(item.details)) next[item.id] = item.details;
        }
        setDetailsById(next);
        setSourceLoaded(true);
      } catch {
        if (!controller.signal.aborted) {
          setSourceLoaded(true);
          setSourceError("源码明细加载失败；图和静态位置仍来自本报告快照。");
        }
      }
    }
    void loadSourceIndex();
    return () => controller.abort();
  }, [projectId, reportId, saved, sourceRequested]);

  // Legacy reports do not carry diagram snapshots. Reading them must never fetch current diagrams.
  if (!Array.isArray(saved)) return null;
  const diagrams = saved.flatMap((value, index) => {
    const diagram = record(value);
    const graph = record(diagram?.graph_json);
    if (!diagram || !graph || typeof diagram.mermaid_source !== "string") return [];
    return [{
      id: typeof diagram.id === "string" ? diagram.id : String(index),
      title: typeof diagram.title === "string" ? diagram.title : "架构图",
      basis: typeof diagram.basis === "string" ? diagram.basis : "依据未记录",
      source: diagram.mermaid_source,
      graph,
      root: record(diagram.stats_json)?.root_label,
    }];
  });

  return (
    <section className="panel stack" aria-label="报告保存的源码流程与架构图">
      <div>
        <h2>源码流程与架构图</h2>
        <p className="muted">图和源码位置随本报告保存。之后重新画图或修改源码，不会改变这份报告。</p>
        <p className="meta">图表示静态源码引用，不证明实际运行顺序或真实数据流；动态调用保留为未解析。</p>
        {sourceRequested ? null : (
          <button className="button button-secondary" type="button" onClick={() => setSourceRequested(true)}>
            按需加载源码逐段导航
          </button>
        )}
        {sourceRequested && !sourceLoaded ? <p className="meta">正在加载本次报告的源码索引…</p> : null}
        {sourceRequested && sourceLoaded && !Object.keys(detailsById).length && !sourceError ? <p className="meta">本次报告没有保存可加载的源码明细。</p> : null}
        {sourceError ? <p className="meta">{sourceError}</p> : null}
      </div>
      {diagrams.length ? diagrams.map(diagram => (
        <article className="stack" key={diagram.id}>
          <div className="toolbar">
            <h3>{diagram.title}</h3>
            <span className={diagram.basis.startsWith("deterministic") || diagram.basis.startsWith("static:") ? "badge badge-ok" : "badge badge-warning"}>
              {diagram.basis.startsWith("static:") ? "静态源码依据" : diagram.basis.startsWith("deterministic") ? "静态结构依据" : "启发式/已保存依据"}
            </span>
          </div>
          {typeof diagram.root === "string" ? <p className="meta">来源工程：{diagram.root}</p> : null}
          <MermaidDiagram source={diagram.source} title={diagram.title} />
          {Array.isArray(diagram.graph.notes) ? <ul className="compact-list">{diagram.graph.notes.filter((note): note is string => typeof note === "string").map((note, index) => <li key={index}>{note}</li>)}</ul> : null}
          {sourceRequested ? <SourceNavigator details={detailsById[diagram.id]} /> : null}
        </article>
      )) : <p className="muted">本次运行没有保存架构图；未借用其他运行的图。纯文档资料可能没有源码图。</p>}
    </section>
  );
}
