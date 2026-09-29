export type Trigger = "idle" | "save" | "manual";

export interface EvaluateRequest {
  schemaVersion: 1;
  requestId: string;
  installationId: string;
  vaultId: string;
  noteId: string;
  revision: number;
  createdAt: string;
  trigger: Trigger;
  excerpt: string;
  signals: { challengeScore: number; reflectionDepth: number; daysSinceUpdate: number; idleMs: number };
}

type DecisionBase = Pick<EvaluateRequest, "schemaVersion" | "requestId" | "noteId" | "revision">;
export type NudgeDecision =
  | (DecisionBase & { decision: "show"; mode: "reflection" | "changelog"; displayMode: "inline" | "panel"; hint: string; range: { from: number; to: number }; expiresAt: string })
  | (DecisionBase & { decision: "silent"; reason: "low_confidence" | "no_value" })
  | (DecisionBase & { decision: "blocked"; reason: "security_policy" | "security_unavailable" | "generation_unavailable" | "invalid_generation" });

export interface TransportMetrics {
  sent: number; received: number; failures: number; unauthorized: number; stale: number; duplicates: number;
  latenciesMs: number[]; queueHighWater: number; reconnectFailures: number;
}

export interface CompanionTransport {
  evaluate(request: EvaluateRequest, signal?: AbortSignal): Promise<NudgeDecision | undefined>;
  readonly metrics: TransportMetrics;
}

export const emptyMetrics = (): TransportMetrics => ({ sent: 0, received: 0, failures: 0, unauthorized: 0, stale: 0, duplicates: 0, latenciesMs: [], queueHighWater: 0, reconnectFailures: 0 });
