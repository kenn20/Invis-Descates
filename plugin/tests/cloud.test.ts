import { describe, expect, it, vi } from "vitest";
import { LOCAL_ORIGIN, MemoryClient, PairingClient, serverOrigin } from "../src/cloud";
import { NoteIds, ConsentScope } from "../src/scope";
import { EvaluationController } from "../src/controller";
import { emptyMetrics } from "../src/protocol";

const session = () => ({ pairingSecret: "s".repeat(43), userCode: "ABCDEF0123", verificationUrl: "https://companion.example/auth/google?code=ABCDEF0123", expiresIn: 300, interval: 3 });
describe("Google pairing", () => {
  it("rejects insecure servers, credentials in URLs, paths, and cross-origin approval redirects", async () => {
    expect(serverOrigin("https://companion.example/")).toBe("https://companion.example");
    expect(serverOrigin(LOCAL_ORIGIN)).toBe(LOCAL_ORIGIN);
    for (const origin of ["http://companion.example", "https://name:secret@companion.example", "https://companion.example/path", "https://companion.example?token=secret"]) expect(() => serverOrigin(origin)).toThrow();
    const client = new PairingClient(async () => ({ status: 200, json: { ...session(), verificationUrl: "https://evil.example/auth/google?code=ABCDEF0123" } }), "https://companion.example");
    await expect(client.start(crypto.randomUUID(), crypto.randomUUID())).rejects.toThrow("Invalid sign-in URL");
  });
  it("keeps credentials in POST bodies and polls pending/limited/approved states", async () => {
    const request = vi.fn().mockResolvedValueOnce({ status: 200, json: session() }).mockResolvedValueOnce({ status: 202, json: {} }).mockResolvedValueOnce({ status: 429, json: {} }).mockResolvedValueOnce({ status: 200, json: { token: "t".repeat(43) } });
    const client = new PairingClient(request, "https://companion.example");
    const pairing = await client.start(crypto.randomUUID(), crypto.randomUUID());
    expect(await client.poll(pairing)).toBeUndefined(); expect(await client.poll(pairing)).toBeUndefined();
    expect(await client.poll(pairing)).toBe("t".repeat(43));
    for (const [options] of request.mock.calls) { expect(options.url).not.toContain(pairing.pairingSecret); expect(options.headers.Authorization).toBeUndefined(); }
    await expect(client.poll({ ...pairing, startedAt: Date.now() - 301000 })).rejects.toThrow("expired");
    expect(request).toHaveBeenCalledTimes(4);
  });
});

it("requires a token before memory access and keeps tokens out of request bodies", async () => {
  const request = vi.fn().mockResolvedValue({ status: 200, json: { answer: "Your own memory" } });
  let token: string | undefined;
  const client = new MemoryClient(request, () => "https://companion.example", () => token);
  await expect(client.answer("installation", "vault", "question")).rejects.toThrow("Sign in first");
  expect(request).not.toHaveBeenCalled(); token = "private-token";
  expect(await client.answer("installation", "vault", "question")).toBe("Your own memory");
  expect(request.mock.calls[0][0].headers.Authorization).toBe("Bearer private-token");
  expect(request.mock.calls[0][0].body).not.toContain(token);
  request.mockResolvedValue({ status: 401, json: {} }); await expect(client.revoke()).rejects.toThrow("revoked");
});

it("restores opaque note identities without storing credentials", () => {
  let saved: Record<string, string> = {};
  const ids = new NoteIds({}, value => { saved = value; });
  const first = ids.idFor("allowed/note.md");
  expect(new NoteIds(saved).idFor("allowed/note.md")).toBe(first);
  ids.rename("allowed/note.md", "allowed/renamed.md"); expect(saved["allowed/renamed.md"]).toBe(first);
  ids.remove("allowed/renamed.md"); expect(saved).toEqual({});
});

it("rechecks folder consent before a queued transmission", async () => {
  vi.useFakeTimers();
  const scope = new ConsentScope(); scope.allow("allowed");
  const evaluate = vi.fn();
  const controller = new EvaluationController(scope, { metrics: emptyMetrics(), evaluate }, { installationId: crypto.randomUUID(), vaultId: crypto.randomUUID() }, () => {});
  controller.schedule("allowed/note.md", "private"); scope.remove("allowed");
  await vi.advanceTimersByTimeAsync(1200); expect(evaluate).not.toHaveBeenCalled();
  vi.useRealTimers();
});

it("indexes independently of nudge limits, with bounds and revocable consent", async () => {
  const { MemorySync } = await import("../src/memory-sync");
  vi.useFakeTimers();
  const scope = new ConsentScope(); scope.allow("allowed");
  const upload = vi.fn().mockResolvedValue(undefined); let enabled = true;
  const sync = new MemorySync(scope, new NoteIds(), () => enabled, { installationId: "installation", vaultId: "vault" }, upload);
  sync.schedule("excluded/a.md", "secret"); await vi.advanceTimersByTimeAsync(1200); expect(upload).not.toHaveBeenCalled();
  sync.schedule("allowed/a.md", "🙂".repeat(3000)); await vi.advanceTimersByTimeAsync(1200);
  expect(upload).toHaveBeenCalledTimes(1); expect(new TextEncoder().encode(upload.mock.calls[0][0].excerpt).length).toBeLessThanOrEqual(8192);
  sync.schedule("allowed/a.md", "private"); enabled = false; await vi.advanceTimersByTimeAsync(1200); expect(upload).toHaveBeenCalledTimes(1);
  enabled = true; sync.schedule("allowed/a.md", "private"); sync.cancel(); await vi.advanceTimersByTimeAsync(1200); expect(upload).toHaveBeenCalledTimes(1);
  vi.useRealTimers();
});

it("keeps installation identity local when vault settings are synced", async () => {
  const { localInstallationId } = await import("../src/cloud");
  const device = () => { const values = new Map<string, string>(); return { getSecret: (key: string) => values.get(key), setSecret: (key: string, value: string) => values.set(key, value) }; };
  const a = device(), b = device(), vault = crypto.randomUUID();
  const first = localInstallationId(vault, a);
  expect(localInstallationId(vault, a)).toBe(first);
  expect(localInstallationId(vault, b)).not.toBe(first);
});
