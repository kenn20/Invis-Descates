/** Pairing secrets live only in memory; browser callbacks never carry credentials. */
export type CloudRequest = (options: { url: string; method: string; headers: Record<string, string>; body?: string; throw: false }) => Promise<{ status: number; json: unknown }>;
export const LOCAL_ORIGIN = "http://127.0.0.1:27123";
export function serverOrigin(value: string): string {
  const url = new URL(value);
  if ((url.protocol !== "https:" && url.origin !== LOCAL_ORIGIN) || url.username || url.password || url.search || url.hash || url.pathname !== "/") throw new Error("Use an HTTPS server origin");
  return url.origin;
}
export interface PairingSession { pairingSecret: string; userCode: string; verificationUrl: string; expiresIn: number; interval: number; startedAt: number }
const object = (value: unknown): Record<string, unknown> => value && typeof value === "object" ? value as Record<string, unknown> : {};
export class PairingClient {
  constructor(private readonly request: CloudRequest, readonly origin: string) { if (serverOrigin(origin) !== origin || origin === LOCAL_ORIGIN) throw new Error("Google sign-in requires an HTTPS server"); }
  async start(installationId: string, vaultId: string): Promise<PairingSession> {
    const response = await this.request({ url: this.origin + "/auth/pairing/start", method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ installationId, vaultId, deviceName: "Obsidian" }), throw: false });
    const data = object(response.json);
    if (response.status !== 200 || typeof data.pairingSecret !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(data.pairingSecret) || typeof data.userCode !== "string" || !/^[A-F0-9]{10}$/.test(data.userCode) || typeof data.verificationUrl !== "string" || data.expiresIn !== 300 || data.interval !== 3) throw new Error("Could not start sign-in");
    const verification = new URL(data.verificationUrl);
    if (verification.origin !== this.origin || verification.pathname !== "/auth/google" || verification.search !== "?code=" + data.userCode || verification.hash || verification.username || verification.password) throw new Error("Invalid sign-in URL");
    return { pairingSecret: data.pairingSecret, userCode: data.userCode, verificationUrl: data.verificationUrl, expiresIn: 300, interval: 3, startedAt: Date.now() };
  }
  async poll(session: PairingSession): Promise<string | undefined> {
    if (Date.now() >= session.startedAt + session.expiresIn * 1000) throw new Error("Sign-in expired");
    const response = await this.request({ url: this.origin + "/auth/pairing/poll", method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pairingSecret: session.pairingSecret }), throw: false });
    if (response.status === 202 || response.status === 429) return undefined;
    const token = object(response.json).token;
    if (response.status !== 200 || typeof token !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(token)) throw new Error("Sign-in failed or expired");
    return token;
  }
}
export class MemoryClient {
  constructor(private readonly request: CloudRequest, private readonly origin: () => string, private readonly token: () => string | undefined) {}
  private async send(path: string, method: string, payload?: unknown): Promise<unknown> {
    const token = this.token(); if (!token) throw new Error("Sign in first");
    const response = await this.request({ url: serverOrigin(this.origin()) + path, method, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: payload === undefined ? undefined : JSON.stringify(payload), throw: false });
    if (response.status === 401) throw new Error("Sign-in expired or revoked");
    if (response.status < 200 || response.status >= 300) throw new Error("Service unavailable");
    return response.json;
  }
  async upload(request: { installationId: string; vaultId: string; noteId: string; revision: number; excerpt: string }): Promise<void> {
    const { installationId, vaultId, noteId, revision, excerpt } = request;
    await this.send("/v1/memories", "PUT", { installationId, vaultId, noteId, revision, content: excerpt });
  }
  async remove(installationId: string, vaultId: string, noteId: string): Promise<void> { await this.send("/v1/memories", "DELETE", { installationId, vaultId, noteId }); }
  async revoke(): Promise<void> { await this.send("/v1/pairing", "DELETE"); }
  async answer(installationId: string, vaultId: string, query: string): Promise<string> {
    const result = object(await this.send("/v1/rag:answer", "POST", { installationId, vaultId, query, topK: 5 }));
    if (typeof result.answer !== "string" || result.answer.length > 8000) throw new Error("Invalid answer");
    return result.answer;
  }
}
