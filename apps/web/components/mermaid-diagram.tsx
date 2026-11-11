"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent } from "react";
import { centerDiagram, fitDiagram, resizeViewport, zoomAt } from "@/lib/diagram-viewport";
import type { DiagramPoint, DiagramSize, DiagramTransform } from "@/lib/diagram-viewport";
import "./diagram-viewer.css";

type Props = { source: string; title?: string };
type RenderedDiagram = { source: string; svg: string; size: DiagramSize; error?: never };
type DiagramFailure = { source: string; error: string; svg?: never; size?: never };

const DEFAULT_SIZE = { width: 960, height: 540 };
const MAX_SCALE = 8;
let renderSequence = 0;
let mermaidPromise: Promise<(typeof import("mermaid"))["default"]> | undefined;

function loadMermaid() {
  mermaidPromise ??= import("mermaid").then(({ default: mermaid }) => {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      suppressErrorRendering: true,
      htmlLabels: false,
      theme: "base",
      fontFamily: "inherit",
      themeVariables: {
        darkMode: true,
        background: "transparent",
        primaryColor: "#161b22",
        primaryTextColor: "#e6edf3",
        primaryBorderColor: "#30363d",
        secondaryColor: "#1f6feb",
        tertiaryColor: "#0d1117",
        lineColor: "#8b949e",
        fontSize: "13px",
      },
    });
    return mermaid;
  }).catch((error: unknown) => {
    mermaidPromise = undefined;
    throw error;
  });
  return mermaidPromise;
}

function readSvgSize(svg: string): DiagramSize {
  const element = new DOMParser().parseFromString(svg, "image/svg+xml").documentElement;
  const viewBox = element.getAttribute("viewBox")?.trim().split(/[\s,]+/).map(Number);
  const width = viewBox?.length === 4 ? viewBox[2] : parseFloat(element.getAttribute("width") ?? "");
  const height = viewBox?.length === 4 ? viewBox[3] : parseFloat(element.getAttribute("height") ?? "");
  return Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0
    ? { width, height }
    : DEFAULT_SIZE;
}

function useMermaidSvg(source: string) {
  const id = useId().replace(/[^0-9A-Za-z_-]/g, "");
  const [result, setResult] = useState<RenderedDiagram | DiagramFailure | null>(null);

  useEffect(() => {
    let cancelled = false;
    const renderId = `mermaid-${id}-${++renderSequence}`;
    setResult(null);

    async function renderDiagram() {
      // Keep Mermaid's temporary DOM out of the page and remove it on failures too.
      const host = document.createElement("div");
      host.style.cssText = "position:absolute;left:-100000px;top:0;visibility:hidden;pointer-events:none";
      host.setAttribute("aria-hidden", "true");
      try {
        const mermaid = await loadMermaid();
        if (cancelled) return;
        document.body.append(host);
        const rendered = await mermaid.render(renderId, source, host);
        if (!cancelled) setResult({ source, svg: rendered.svg, size: readSvgSize(rendered.svg) });
      } catch (error) {
        if (!cancelled) {
          setResult({ source, error: error instanceof Error ? error.message : "架构图渲染失败" });
        }
      } finally {
        host.remove();
      }
    }

    void renderDiagram();
    return () => { cancelled = true; };
  }, [id, source]);

  // A changed source must never display the previous source's SVG or error, even before effects run.
  return result?.source === source ? result : null;
}

function DiagramCanvas({ source, title, onExpand, onClose }: Props & { onExpand?: () => void; onClose?: () => void }) {
  const diagram = useMermaidSvg(source);
  const svg = diagram?.svg;
  const size = diagram?.size ?? DEFAULT_SIZE;
  const viewportRef = useRef<HTMLDivElement>(null);
  const viewportSize = useRef<DiagramSize>({ width: 0, height: 0 });
  const transformRef = useRef<DiagramTransform>({ scale: 1, x: 0, y: 0 });
  const pointers = useRef(new Map<number, DiagramPoint>());
  const fitted = useRef(true);
  const [transform, setTransform] = useState(transformRef.current);
  const [dragging, setDragging] = useState(false);
  const hintId = useId();

  const applyTransform = useCallback((next: DiagramTransform) => {
    transformRef.current = next;
    setTransform(next);
  }, []);

  const fit = useCallback(() => {
    fitted.current = true;
    applyTransform(fitDiagram(size, viewportSize.current));
  }, [applyTransform, size]);

  const constrainScale = useCallback((scale: number) => {
    const minimum = Math.min(0.1, fitDiagram(size, viewportSize.current).scale);
    return Math.min(MAX_SCALE, Math.max(minimum, scale));
  }, [size]);

  const zoom = useCallback((scale: number, anchor?: DiagramPoint) => {
    fitted.current = false;
    applyTransform(zoomAt(transformRef.current, constrainScale(scale), anchor ?? {
      x: viewportSize.current.width / 2,
      y: viewportSize.current.height / 2,
    }));
  }, [applyTransform, constrainScale]);

  const reset = useCallback(() => {
    fitted.current = false;
    applyTransform(centerDiagram(size, viewportSize.current, 1));
  }, [applyTransform, size]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || !svg) return;
    pointers.current.clear();
    setDragging(false);
    fitted.current = true;

    function measure() {
      if (!viewport) return;
      const next = { width: viewport.clientWidth, height: viewport.clientHeight };
      if (!next.width || !next.height) return;
      const previous = viewportSize.current;
      viewportSize.current = next;
      applyTransform(fitted.current || !previous.width
        ? fitDiagram(size, next)
        : resizeViewport(transformRef.current, previous, next));
    }

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [applyTransform, size, svg]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || !svg) return;
    function onWheel(event: WheelEvent) {
      if (!viewport) return;
      event.preventDefault();
      const rect = viewport.getBoundingClientRect();
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewport.clientHeight : 1;
      const delta = Math.max(-300, Math.min(300, event.deltaY * unit));
      zoom(transformRef.current.scale * Math.exp(-delta * 0.002), {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      });
    }
    // React's delegated wheel listener can be passive; this canvas must prevent page scrolling.
    viewport.addEventListener("wheel", onWheel, { passive: false });
    return () => viewport.removeEventListener("wheel", onWheel);
  }, [svg, zoom]);

  function pointerPosition(event: PointerEvent<HTMLDivElement>): DiagramPoint {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (!svg || (event.pointerType === "mouse" && event.button !== 0)) return;
    event.preventDefault();
    event.currentTarget.focus({ preventScroll: true });
    event.currentTarget.setPointerCapture(event.pointerId);
    pointers.current.set(event.pointerId, pointerPosition(event));
    setDragging(true);
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    const previous = pointers.current.get(event.pointerId);
    if (!previous) return;
    const before = [...pointers.current.values()];
    const point = pointerPosition(event);
    pointers.current.set(event.pointerId, point);
    const after = [...pointers.current.values()];
    fitted.current = false;
    const current = transformRef.current;

    if (after.length === 1) {
      applyTransform({ ...current, x: current.x + point.x - previous.x, y: current.y + point.y - previous.y });
    } else {
      const middle = (points: DiagramPoint[]) => ({ x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 });
      const distance = (points: DiagramPoint[]) => Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
      const oldMiddle = middle(before);
      const nextMiddle = middle(after);
      const oldDistance = distance(before);
      const nextScale = oldDistance > 0 ? current.scale * distance(after) / oldDistance : current.scale;
      const next = zoomAt(current, constrainScale(nextScale), oldMiddle);
      applyTransform({ ...next, x: next.x + nextMiddle.x - oldMiddle.x, y: next.y + nextMiddle.y - oldMiddle.y });
    }
  }

  function onPointerEnd(event: PointerEvent<HTMLDivElement>) {
    pointers.current.delete(event.pointerId);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    setDragging(pointers.current.size > 0);
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!svg || event.target !== event.currentTarget || event.ctrlKey || event.metaKey || event.altKey) return;
    const current = transformRef.current;
    if (event.key === "+" || event.key === "=") zoom(current.scale * 1.25);
    else if (event.key === "-" || event.key === "_") zoom(current.scale / 1.25);
    else if (event.key === "0") fit();
    else if (event.key === "1") reset();
    else if (event.key.startsWith("Arrow")) {
      const delta = { ArrowLeft: [40, 0], ArrowRight: [-40, 0], ArrowUp: [0, 40], ArrowDown: [0, -40] }[event.key];
      if (!delta) return;
      fitted.current = false;
      applyTransform({ ...current, x: current.x + delta[0], y: current.y + delta[1] });
    } else return;
    event.preventDefault();
  }

  return (
    <div className={`architecture-diagram${onClose ? " architecture-diagram--fullscreen" : ""}`}>
      <div className="architecture-diagram__toolbar">
        <strong>{title ?? "架构图"}</strong>
        <div className="architecture-diagram__actions" role="group" aria-label="架构图查看工具">
          <button type="button" disabled={!svg} onClick={() => zoom(transformRef.current.scale / 1.25)} aria-label="缩小架构图" title="缩小">−</button>
          <output className="architecture-diagram__zoom" aria-label="当前缩放比例">{Math.round(transform.scale * 1000) / 10}%</output>
          <button type="button" disabled={!svg} onClick={() => zoom(transformRef.current.scale * 1.25)} aria-label="放大架构图" title="放大">＋</button>
          <button type="button" disabled={!svg} onClick={fit} title="完整显示架构图（快捷键 0）">适应画布</button>
          <button type="button" disabled={!svg} onClick={reset} aria-label="按原始大小居中显示架构图" title="原始大小（快捷键 1）">1:1</button>
          {onExpand ? <button type="button" disabled={!svg} onClick={onExpand} aria-label="全屏查看架构图">全屏查看</button> : null}
          {onClose ? <button type="button" onClick={onClose} data-diagram-close aria-label="关闭全屏架构图">关闭 <span aria-hidden="true">Esc</span></button> : null}
        </div>
      </div>
      <div
        ref={viewportRef}
        className={`architecture-diagram__viewport${dragging ? " is-dragging" : ""}`}
        role="region"
        aria-label={`${title ?? "架构图"}，可拖动和缩放的画布`}
        aria-describedby={hintId}
        aria-busy={!diagram}
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerEnd}
        onPointerCancel={onPointerEnd}
        onLostPointerCapture={onPointerEnd}
        onKeyDown={onKeyDown}
      >
        {svg ? <div
          className="architecture-diagram__svg"
          style={{ width: size.width, height: size.height, transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})` }}
          dangerouslySetInnerHTML={{ __html: svg }}
        /> : diagram?.error ? <div className="architecture-diagram__message" role="alert">
          <p className="error-text">架构图暂时无法显示，可点击上方“重新生成此图”重试。</p>
          <details><summary>查看错误与源码</summary><p>{diagram.error}</p><pre>{source}</pre></details>
        </div> : <p className="architecture-diagram__message muted" role="status">架构图加载中…</p>}
      </div>
      <p id={hintId} className="architecture-diagram__hint">拖动整张图 · 滚轮 / 双指缩放 · + / − 缩放 · 方向键平移 · 0 适应画布 · 1 原始大小</p>
    </div>
  );
}

export function MermaidDiagram({ source, title }: Props) {
  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => { setOpen(false); }, [source]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!open || !dialog) return;
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    dialog.showModal();
    document.body.style.overflow = "hidden";
    dialog.querySelector<HTMLButtonElement>("[data-diagram-close]")?.focus();
    return () => {
      dialog.close();
      document.body.style.overflow = previousOverflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, [open]);

  return <div className="stack">
    <DiagramCanvas source={source} title={title} onExpand={() => setOpen(true)} />
    <dialog
      ref={dialogRef}
      className="architecture-diagram-dialog"
      aria-label={`${title ?? "架构图"}全屏查看`}
      onCancel={(event) => { event.preventDefault(); setOpen(false); }}
      onClose={() => setOpen(false)}
    >
      {open ? <DiagramCanvas source={source} title={title} onClose={() => setOpen(false)} /> : null}
    </dialog>
  </div>;
}
