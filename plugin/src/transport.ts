import { CompanionTransport, emptyMetrics, EvaluateRequest, NudgeDecision, TransportMetrics } from "./protocol";

/** Obsidian's supported requestUrl is injected to retain a unit-testable transport boundary. */
export type RequestUrl = (options: { url: string; method: "POST"; headers: Record<string, string>; body: string; throw: false }) => Promise<{ status: number; json: unknown }>;

export class HttpTransport implements CompanionTransport {
  readonly metrics: TransportMetrics = emptyMetrics();
  constructor(private readonly requestUrl: RequestUrl, private readonly endpoint: string | (() => string), private readonly token: () => string | undefined) {}
  async evaluate(request: EvaluateRequest): Promise<NudgeDecision | undefined> {
    const started = performance.now(); this.metrics.sent++;
    const token = this.token();
    if (!token) { this.metrics.unauthorized++; return undefined; }
    try {
      const response = await this.requestUrl({ url: typeof this.endpoint === "string" ? this.endpoint : this.endpoint(), method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(request), throw: false });
      if (response.status === 401) { this.metrics.unauthorized++; return undefined; }
      if (response.status < 200 || response.status >= 300 || !isDecision(response.json)) { this.metrics.failures++; return undefined; }
      this.metrics.received++; this.metrics.latenciesMs.push(performance.now() - started);
      return response.json;
    } catch { this.metrics.failures++; return undefined; }
  }
}

export const isDecision = (value: unknown): value is NudgeDecision => {
  if (!value || typeof value !== "object") return false;
  const decision = value as Partial<NudgeDecision>;
  return decision.schemaVersion === 1 && typeof decision.requestId === "string" && typeof decision.noteId === "string" && typeof decision.revision === "number" && ["show", "silent", "blocked"].includes(decision.decision as string);
};

/** Render boundary: latest request + revision must match before any UI receives a result. */
export class CurrentDecisionGate {
  private latest = new Map<string, { requestId: string; revision: number }>();
  begin(request: EvaluateRequest): void { this.latest.set(request.noteId, { requestId: request.requestId, revision: request.revision }); }
  accept(decision: NudgeDecision): boolean {
    const current = this.latest.get(decision.noteId);
    return !!current && current.requestId === decision.requestId && current.revision === decision.revision;
  }
  invalidate(noteId: string): void { this.latest.delete(noteId); }
}
