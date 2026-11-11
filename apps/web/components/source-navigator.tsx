"use client";

import { useMemo, useState } from "react";
import { filterSourceFunctions, readSourceIndex, sourceLineLabel } from "@/lib/source-navigation";
import "./source-navigator.css";

export function SourceNavigator({ details }: { details: unknown }) {
  const index = useMemo(() => readSourceIndex(details), [details]);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [visibleCount, setVisibleCount] = useState(100);
  const matches = useMemo(() => filterSourceFunctions(index?.functions ?? [], query), [index, query]);
  if (!index) return null;
  const current = matches.find(fn => fn.id === selectedId) ?? matches[0];
  const file = index.files.find(item => item.path === current?.path);
  const selectFunction = (id: string) => { setQuery(""); setSelectedId(id); };
  const byId = new Map(index.functions.map(fn => [fn.id, fn]));

  return <details className="source-navigator" open>
    <summary>源码逐段导航 · {index.files.length} 个文件 / {index.functions.length} 个函数</summary>
    <p className="meta">行号来自本次解析的源码快照。已解析表示可定位的静态调用引用；分支是否执行、真实数据流和动态分派仍需运行验证。用途说明来自语法分类和源码注释。</p>
    {index.warnings.length ? <ul className="compact-list">{index.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul> : null}
    <label className="stack">查找文件、函数、说明或调用
      <input className="input" value={query} onChange={event => { setQuery(event.target.value); setVisibleCount(100); }} placeholder="例如 api chat / process_message / L120" />
    </label>
    <div className="source-navigator__grid">
      <nav aria-label="源码函数列表" className="source-navigator__list">
        <p className="meta">找到 {matches.length} 个函数{matches.length > visibleCount ? `，显示前 ${visibleCount} 个` : ""}</p>
        {matches.slice(0, visibleCount).map(fn => <button key={fn.id} type="button"
          className={fn.id === current?.id ? "source-navigator__function is-selected" : "source-navigator__function"}
          onClick={() => setSelectedId(fn.id)} aria-pressed={fn.id === current?.id}>
          <strong>{fn.qualified_name}</strong>
          <span>{fn.path}:{fn.line_start}–{fn.line_end}</span>
          {fn.entrypoint ? <span>{fn.entrypoint.confidence === "syntax" ? "入口注册语法" : "入口候选"} · {fn.entrypoint.label}</span> : null}
        </button>)}
        {matches.length > visibleCount ? <button className="button button-secondary" type="button" onClick={() => setVisibleCount(count => count + 100)}>继续显示 100 个函数</button> : null}
      </nav>
      {current ? <article className="source-navigator__body" aria-label="函数内部源码导航">
        <h3>{current.qualified_name}({current.parameters.join(", ")})</h3>
        <p><code>{current.path}:{current.line_start}–{current.line_end}</code></p>
        {current.docstring ? <pre className="source-navigator__comment">{current.docstring}</pre> : <p className="meta">此函数没有可提取的说明注释；下方用途仅说明语法作用。</p>}
        {file ? <div className="meta source-navigator__hash">
          <div>当前文件：{file.path} · {file.description || "未提取到文件说明"}</div>
          <div>源码 SHA-256：{file.sha256}</div>
        </div> : null}
        <h4>函数内部：每段在哪里、做什么</h4>
        {current.statements.length ? <ol className="source-navigator__statements">
          {current.statements.map((item, i) => <li key={`${item.line_start}-${i}`}>
            <div><span className="badge">{sourceLineLabel(item.line_start, item.line_end)}</span> <strong>{item.label}</strong> <span className="meta">{item.kind}</span></div>
            <pre><code>{item.excerpt}</code></pre>
          </li>)}
        </ol> : <p className="meta">没有已保存的语句明细；请查看扫描限制。</p>}
        <h4>从此函数调用到哪里</h4>
        {current.calls.length ? <ul className="compact-list">{current.calls.map((call, i) => {
          const target = call.target_id ? byId.get(call.target_id) : undefined;
          return <li key={`${call.line}-${i}`}>
            <code>L{call.line} {call.expression}</code>{" → "}
            {target ? <button className="source-navigator__link" type="button" onClick={() => selectFunction(target.id)}>
              {target.path}:{target.line_start} · {target.qualified_name}
            </button> : <span>未解析 · {call.reason || "无法静态确定目标"}</span>}
          </li>;
        })}</ul> : <p className="meta">没有已保存的调用表达式。</p>}
      </article> : <p className="meta">没有匹配的函数。</p>}
    </div>
  </details>;
}
