import type { SourceFunction, SourceIndex } from "../types/project";

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function lines(value: Record<string, unknown>): boolean {
  return Number.isInteger(value.line_start) && Number.isInteger(value.line_end)
    && Number(value.line_start) >= 1 && Number(value.line_end) >= Number(value.line_start);
}

export function readSourceIndex(value: unknown): SourceIndex | null {
  if (!record(value) || value.version !== 1 || !Array.isArray(value.functions) || !Array.isArray(value.files)
    || !record(value.stats) || !record(value.limits) || !Array.isArray(value.warnings)
    || !value.warnings.every(item => typeof item === "string")) return null;
  for (const fn of value.functions) {
    if (!record(fn) || !lines(fn) || ![fn.id, fn.path, fn.name, fn.qualified_name, fn.docstring].every(x => typeof x === "string")
      || !Array.isArray(fn.parameters) || !fn.parameters.every(x => typeof x === "string")
      || !Array.isArray(fn.statements) || !Array.isArray(fn.calls)) return null;
    for (const item of fn.statements) {
      if (!record(item) || !lines(item) || ![item.kind, item.label, item.excerpt].every(x => typeof x === "string")) return null;
    }
    for (const call of fn.calls) {
      if (!record(call) || typeof call.expression !== "string" || !Number.isInteger(call.line) || Number(call.line) < 1
        || typeof call.reason !== "string" || !Number.isInteger(call.column) || Number(call.column) < 0
        || !["resolved", "unresolved"].includes(String(call.resolution))
        || (call.target_id !== null && typeof call.target_id !== "string")) return null;
    }
    if (fn.entrypoint !== null && (!record(fn.entrypoint)
      || ![fn.entrypoint.kind, fn.entrypoint.label, fn.entrypoint.confidence].every(x => typeof x === "string")
      || !Number.isInteger(fn.entrypoint.line) || Number(fn.entrypoint.line) < 1)) return null;
  }
  if (!value.files.every(file => record(file) && typeof file.path === "string" && typeof file.sha256 === "string"
    && typeof file.language === "string" && Number.isInteger(file.line_count))) return null;
  return value as SourceIndex;
}

export function filterSourceFunctions(functions: SourceFunction[], query: string): SourceFunction[] {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return functions;
  return functions.filter(fn => {
    const content = [fn.path, fn.qualified_name, fn.docstring, fn.id, `L${fn.line_start}`, `L${fn.line_end}`, ...fn.parameters,
      ...fn.statements.map(item => `${item.label} ${item.excerpt}`), ...fn.calls.map(call => call.expression)]
      .join(" ").toLocaleLowerCase();
    return terms.every(term => content.includes(term));
  });
}

export function sourceLineLabel(start: number, end: number): string {
  return start === end ? `L${start}` : `L${start}–L${end}`;
}
