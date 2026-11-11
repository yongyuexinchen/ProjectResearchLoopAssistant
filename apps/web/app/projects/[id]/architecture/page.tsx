import { redirect } from "next/navigation";
import Link from "next/link";
import { DiagramRegenerator } from "@/components/diagram-regenerator";
import { WorkbenchNav } from "@/components/workbench-nav";
import { generateArchitectureDiagrams, getProject, listArchitectureDiagrams } from "@/lib/api";
import type { ArchitectureDiagram } from "@/types/project";

const BASIS_LABELS: Record<string, string> = {
  "deterministic:file_tree": "确定性 · 目录树",
  "deterministic:import_scan": "确定性 · import 扫描",
  "deterministic:ast + regex": "确定性 · AST + 正则",
  "heuristic:import_order": "启发式 · 依赖顺序",
  "heuristic:directory_naming": "启发式 · 目录命名",
};

const DIAGRAM_HINTS: Record<string, string> = {
  module_map: "UML 包结构视角：目录层级与体量分布，判断哪些目录是主战场。",
  uml_component: "UML 组件图：一级模块当作构件，虚线箭头是 import 依赖。",
  uml_class: "UML 类图：真实类与主要方法，实线三角箭头表示继承。",
  uml_sequence: "UML 时序图：从入口模块展开的主链路骨架，用来看阅读顺序。",
  data_flow: "分层视角：按角色看数据经过哪些层，属于启发式归类。",
};

async function generateAction(projectId: string) {
  "use server";

  let failed = false;
  try {
    await generateArchitectureDiagrams(projectId);
  } catch {
    failed = true;
  }
  redirect(failed ? `/projects/${projectId}/architecture?error=1` : `/projects/${projectId}/architecture`);
}

function BasisBadge({ basis }: { basis: string }) {
  const label = BASIS_LABELS[basis] ?? basis;
  const className = basis.startsWith("deterministic") ? "badge badge-ok" : "badge badge-warning";
  return <span className={className}>{label}</span>;
}

function DiagramCard({ diagram }: { diagram: ArchitectureDiagram }) {
  const nodes = diagram.graph_json?.nodes ?? [];
  const edges = diagram.graph_json?.edges ?? [];
  const notes = diagram.graph_json?.notes ?? [];

  return (
    <section className="panel stack">
      <div className="toolbar">
        <div>
          <h2>{diagram.title || diagram.diagram_type}</h2>
          <p className="meta">{DIAGRAM_HINTS[diagram.diagram_type] ?? ""}</p>
          {diagram.stats_json.root_label ? <p className="meta">来源工程：{diagram.stats_json.root_label}</p> : null}
        </div>
        <div className="toolbar-actions">
          <span className="badge">{nodes.length} 节点</span>
          <span className="badge">{edges.length} 边</span>
          <BasisBadge basis={diagram.basis} />
        </div>
      </div>

      <DiagramRegenerator diagram={diagram} />

      {notes.length ? (
        <ul className="compact-list">
          {notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}

      <details>
        <summary className="muted">查看节点与依赖明细（{nodes.length} 节点 / {edges.length} 边）</summary>
        <div className="inventory-grid">
          <div>
            <h3>节点</h3>
            <ul className="compact-list">
              {nodes.slice(0, 40).map((node) => (
                <li key={node.id}>
                  {node.kind} · {node.path || "（根）"} · {node.file_count} 文件
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3>依赖边</h3>
            <ul className="compact-list">
              {edges.slice(0, 40).map((edge) => (
                <li key={`${edge.source}->${edge.target}`}>
                  {edge.source} → {edge.target}
                  {edge.weight ? ` · ${edge.weight} 次` : ""}
                </li>
              ))}
            </ul>
          </div>
        </div>
        {nodes.length > 40 || edges.length > 40 ? (
          <p className="muted">只展示前 40 条，完整数据保存在 architecture_diagrams 表。</p>
        ) : null}
      </details>
    </section>
  );
}

export default async function ProjectArchitecturePage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ error?: string; run_id?: string }>;
}) {
  const { id } = await params;
  const { error, run_id } = await searchParams;
  const [project, diagrams] = await Promise.all([getProject(id), listArchitectureDiagrams(id, run_id)]);
  const generate = generateAction.bind(null, id);

  return (
    <div className="stack">
      <div className="toolbar">
        <div>
          <h1>架构图</h1>
          <p className="muted">{project.name}</p>
          {run_id ? <p className="meta">正在查看所选调研任务保存的架构图。</p> : null}
          <p className="meta">拖动画布平移，滚轮缩放查看细节，也可以全屏查看。架构图由已采集的工程结构生成。</p>
        </div>
        <div className="toolbar-actions">
          {run_id ? <Link className="button button-secondary" href={`/projects/${id}/run?run_id=${encodeURIComponent(run_id)}`}>返回本次调研结果</Link> : <form action={generate}>
            <button className="button" type="submit">
              {diagrams.length ? "重新生成架构图" : "生成架构图"}
            </button>
          </form>}
        </div>
      </div>
      <WorkbenchNav projectId={id} active="architecture" />

      {error ? (
        <section className="panel stack">
          <p className="error-text">生成失败：请先在「输入源」页采集本地目录或 GitHub 仓库，再回来生成架构图。</p>
        </section>
      ) : null}

      {diagrams.length ? (
        diagrams.map((diagram) => <DiagramCard diagram={diagram} key={diagram.id} />)
      ) : (
        <section className="panel stack">
          <h2>{run_id ? "本次调研没有保存架构图" : "还没有架构图"}</h2>
          <p className="muted">
            {run_id ? "可能尚未完成架构阶段，或本次资料仅包含文档。请返回本次调研查看具体状态。" : "添加并采集本地目录或 GitHub 仓库后，自动调研会生成结构图、组件图、类图与数据流图。也可以通过右上角按钮手动生成。"}
          </p>
        </section>
      )}
    </div>
  );
}
