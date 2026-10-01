import { canEvaluate, LocalPolicy, recordNudge } from "./policy";
import { EvaluateRequest, NudgeDecision, CompanionTransport } from "./protocol";
import { ConsentScope, excerptAtMost, NoteIds } from "./scope";
import { CurrentDecisionGate } from "./transport";

/** Debounced local coordinator. Only its injected source supplies note text. */
export class EvaluationController {
  private readonly revisions = new Map<string, number>();
  private timer?: ReturnType<typeof setTimeout>;
  private policy: LocalPolicy = { paused: false, cooldownUntil: 0, dailyNudges: 0 };
  private readonly gate = new CurrentDecisionGate();
  constructor(private readonly scope: ConsentScope, private readonly transport: CompanionTransport, private readonly identity: { installationId: string; vaultId: string }, private readonly onDecision: (decision: Extract<NudgeDecision, { decision: "show" }>) => void, private readonly ids = new NoteIds()) {}
  setPaused(paused: boolean): void { this.policy = { ...this.policy, paused }; }
  schedule(path: string, text: string, trigger: "idle" | "save" = "idle"): void {
    if (!this.scope.permits(path) || !canEvaluate(this.policy, Date.now())) return;
    const noteId = this.ids.idFor(path); const revision = Math.max(Date.now(), (this.revisions.get(noteId) ?? 0) + 1); this.revisions.set(noteId, revision);
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.send(path, noteId, revision, text, trigger), trigger === "save" ? 0 : 1200);
  }
  private async send(path: string, noteId: string, revision: number, text: string, trigger: "idle" | "save"): Promise<void> {
    if (!this.scope.permits(path) || !canEvaluate(this.policy, Date.now()) || this.revisions.get(noteId) !== revision) return;
    const request: EvaluateRequest = { schemaVersion: 1, requestId: crypto.randomUUID(), installationId: this.identity.installationId, vaultId: this.identity.vaultId, noteId, revision, createdAt: new Date().toISOString(), trigger, excerpt: excerptAtMost(text), signals: { challengeScore: 0.8, reflectionDepth: 0.2, daysSinceUpdate: 0, idleMs: trigger === "idle" ? 1200 : 0 } };
    this.gate.begin(request); const decision = await this.transport.evaluate(request);
    if (this.policy.paused || !this.scope.permits(path) || !decision || !this.gate.accept(decision) || decision.decision !== "show") return;
    this.policy = recordNudge(this.policy, Date.now()); this.onDecision(decision);
  }
}
