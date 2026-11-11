export type StreamPayload = Record<string, unknown> & {
  id?: string;
  sequence?: number;
  node_name?: string;
  status?: string;
  message?: string;
  stage?: string;
  detail?: string;
};

export type StreamEvent = { id: string; event: string; data: StreamPayload };

export function streamTerminalState(previous: boolean, event: string): boolean {
  if (["run_queued", "run_retry_queued", "run_resume_queued", "run_started"].includes(event)) return false;
  if (["run_completed", "run_failed", "run_cancelled", "workflow_completed"].includes(event)) return true;
  return previous;
}

export function runEventStreamUrl(projectId: string, runId: string, afterSequence: number, origin: string): string {
  const url = new URL(`/api/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/events/stream`, origin);
  url.searchParams.set("after_sequence", String(afterSequence));
  return url.toString();
}

export function parseSseFrame(frame: string): { id?: string; event: string; data: StreamPayload } | null {
  let id: string | undefined;
  let event = "";
  const data: string[] = [];
  for (const line of frame.replace(/\r\n/g, "\n").split("\n")) {
    if (line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    if (colon < 0) continue;
    const name = line.slice(0, colon);
    const value = line.slice(colon + 1).replace(/^ /, "");
    if (name === "id") id = value;
    if (name === "event") event = value;
    if (name === "data") data.push(value);
  }
  if (!event || !data.length) return null;
  try {
    const parsed: unknown = JSON.parse(data.join("\n"));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    return { id, event, data: parsed as StreamPayload };
  } catch { return null; }
}

export function mergeRunEvents(current: StreamEvent[], incoming: StreamEvent[]): StreamEvent[] {
  const events = new Map(current.map(event => [event.id, event]));
  incoming.forEach(event => events.set(event.id, event));
  return [...events.values()].sort((a, b) => (a.data.sequence ?? 0) - (b.data.sequence ?? 0)).slice(-80);
}
