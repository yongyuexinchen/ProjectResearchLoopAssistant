export type DiagramSize = { width: number; height: number };
export type DiagramPoint = { x: number; y: number };
export type DiagramTransform = DiagramPoint & { scale: number };

export function centerDiagram(size: DiagramSize, viewport: DiagramSize, scale: number): DiagramTransform {
  return {
    scale,
    x: (viewport.width - size.width * scale) / 2,
    y: (viewport.height - size.height * scale) / 2,
  };
}

export function fitDiagram(size: DiagramSize, viewport: DiagramSize, padding = 24): DiagramTransform {
  // A fixed minimum would crop large graphs; fit must be allowed below the usual zoom range.
  const scale = Math.min(
    1,
    Math.max(1, viewport.width - padding * 2) / size.width,
    Math.max(1, viewport.height - padding * 2) / size.height,
  );
  return centerDiagram(size, viewport, scale);
}

export function zoomAt(current: DiagramTransform, scale: number, anchor: DiagramPoint): DiagramTransform {
  const ratio = scale / current.scale;
  return {
    scale,
    x: anchor.x - (anchor.x - current.x) * ratio,
    y: anchor.y - (anchor.y - current.y) * ratio,
  };
}

export function resizeViewport(
  current: DiagramTransform,
  previous: DiagramSize,
  next: DiagramSize,
): DiagramTransform {
  return {
    ...current,
    x: current.x + (next.width - previous.width) / 2,
    y: current.y + (next.height - previous.height) / 2,
  };
}
