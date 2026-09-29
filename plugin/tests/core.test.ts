import { describe, expect, it, vi } from "vitest";
import { ConsentScope, excerptAtMost, NoteIds } from "../src/scope";
import { CurrentDecisionGate, HttpTransport } from "../src/transport";
import { EvaluateRequest } from "../src/protocol";
import { canEvaluate, recordNudge } from "../src/policy";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { EvaluationController } from "../src/controller";
import { CompanionTransport, emptyMetrics } from "../src/protocol";

const request = (revision = 1): EvaluateRequest => ({
  schemaVersion: 1, requestId: crypto.randomUUID(), installationId: crypto.randomUUID(), vaultId: crypto.randomUUID(), noteId: crypto.randomUUID(), revision,
  createdAt: new Date().toISOString(), trigger: "idle", excerpt: "blocked", signals: { challengeScore: .9, reflectionDepth: .2, daysSinceUpdate: 0, idleMs: 1200 },
});

describe("local consent boundary", () => {
  it("allows only explicit folder children and rejects traversal, absolute, and sibling-prefix paths", () => {
    const scope = new ConsentScope(); scope.allow("journal");
    expect(scope.permits("journal/today.md")).toBe(true);
    expect(scope.permits("journal-old/today.md")).toBe(false);
    expect(scope.permits("../journal/today.md")).toBe(false);
    expect(scope.permits("/journal/today.md")).toBe(false);
    scope.remove("journal"); expect(scope.permits("journal/today.md")).toBe(false);
  });
  it("truncates excerpts on UTF-8 boundaries and preserves opaque IDs across renames", () => {
    const excerpt = excerptAtMost("🙂".repeat(3000));
    expect(new TextEncoder().encode(excerpt).byteLength).toBeLessThanOrEqual(8192);
    const ids = new NoteIds(); const first = ids.idFor("journal/a.md"); ids.rename("journal/a.md", "journal/b.md");
    expect(ids.idFor("journal/b.md")).toBe(first); ids.remove("journal/b.md"); expect(ids.idFor("journal/b.md")).not.toBe(first);
  });
});

describe("local policy and response freshness", () => {
  it("enforces cooldown and daily budget", () => {
    const at = 100; const policy = recordNudge({ paused: false, cooldownUntil: 0, dailyNudges: 0 }, at);
    expect(canEvaluate(policy, at + 1)).toBe(false); expect(canEvaluate(policy, at + 20 * 60_000)).toBe(true);
    expect(canEvaluate({ ...policy, cooldownUntil: 0, dailyNudges: 3 }, at)).toBe(false);
  });
  it("accepts only the latest request and note revision", () => {
    const gate = new CurrentDecisionGate(); const old = request(1); const newest = { ...request(2), noteId: old.noteId };
    gate.begin(old); gate.begin(newest);
    expect(gate.accept({ ...old, decision: "silent", reason: "no_value" })).toBe(false);
    expect(gate.accept({ ...newest, decision: "silent", reason: "no_value" })).toBe(true);
  });
  it("does not submit without a token and treats transport errors as silence", async () => {
    const transport = new HttpTransport(async () => { throw new Error("offline"); }, "http://127.0.0.1", () => undefined);
    expect(await transport.evaluate(request())).toBeUndefined(); expect(transport.metrics.unauthorized).toBe(1);
  });
});

it("keeps the plugin on the read-only side of the vault boundary", () => {
  const source = readFileSync(resolve(import.meta.dirname, "../src/main.ts"), "utf8");
  expect(source).not.toMatch(/vault\.(create|modify|delete|rename|trash)\s*\(/);
});

it("sends one bounded update only from an allowed, unpaused note and renders only its current decision", async () => {
  vi.useFakeTimers();
  const scope = new ConsentScope(); scope.allow("allowed");
  const seen: EvaluateRequest[] = []; let shown = 0;
  const transport: CompanionTransport = { metrics: emptyMetrics(), evaluate: async value => { seen.push(value); return { schemaVersion: 1, requestId: value.requestId, noteId: value.noteId, revision: value.revision, decision: "show", mode: "reflection", displayMode: "inline", hint: "Question", range: { from: 0, to: 1 }, expiresAt: new Date().toISOString() }; } };
  const controller = new EvaluationController(scope, transport, { installationId: crypto.randomUUID(), vaultId: crypto.randomUUID() }, () => shown++);
  controller.schedule("excluded/a.md", "secret"); controller.schedule("allowed/a.md", "🙂".repeat(3000));
  await vi.advanceTimersByTimeAsync(1200);
  expect(seen).toHaveLength(1); expect(new TextEncoder().encode(seen[0].excerpt).byteLength).toBeLessThanOrEqual(8192); expect(shown).toBe(1);
  controller.setPaused(true); controller.schedule("allowed/a.md", "later"); await vi.advanceTimersByTimeAsync(1200); expect(seen).toHaveLength(1);
  vi.useRealTimers();
});
