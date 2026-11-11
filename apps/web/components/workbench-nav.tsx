import Link from "next/link";

const NAV_ITEMS = [
  { key: "overview", label: "概览", href: "" },
  { key: "sources", label: "输入源", href: "sources" },
  { key: "inventory", label: "采集", href: "inventory" },
  { key: "run", label: "自动调研", href: "run" },
  { key: "tools", label: "工具", href: "tools" },
  { key: "findings", label: "发现", href: "findings" },
  { key: "codebase", label: "工程结构", href: "codebase" },
  { key: "architecture", label: "架构图", href: "architecture" },
  { key: "risks", label: "风险", href: "risks" },
  { key: "report", label: "调研报告", href: "report" },
];

export function WorkbenchNav({ projectId, active }: { projectId: string; active: string }) {
  const primary = new Set(["overview", "run", "architecture", "report"]);
  function itemLink(item: typeof NAV_ITEMS[number]) {
    const href = item.href ? `/projects/${projectId}/${item.href}` : `/projects/${projectId}`;
    const className = item.key === active ? "workbench-link workbench-link-active" : "workbench-link";
    return <Link className={className} href={href} key={item.key} aria-current={item.key === active ? "page" : undefined}>{item.label}</Link>;
  }
  return (
    <div className="stack">
      <nav className="workbench-nav" aria-label="项目工作台">{NAV_ITEMS.filter(item => primary.has(item.key)).map(itemLink)}</nav>
      <details open={!primary.has(active)}>
        <summary className="muted">资料与分析工具</summary>
        <nav className="workbench-nav" aria-label="资料与分析工具">{NAV_ITEMS.filter(item => !primary.has(item.key)).map(itemLink)}</nav>
      </details>
    </div>
  );
}
