import { Notice, Plugin, requestUrl } from "obsidian";
import { HttpTransport } from "./transport";
import { NUDGE_VIEW, NudgeView } from "./nudge-ui";
import { CompanionSettings, CompanionSettingsTab, defaults } from "./settings";
import { ConsentScope, NoteIds } from "./scope";
import { EvaluationController } from "./controller";
import { NudgeDecision } from "./protocol";
import { getNudgeView } from "./nudge-ui";
import { LOCAL_ORIGIN, MemoryClient, PairingClient, serverOrigin, localInstallationId } from "./cloud";
import { MemorySync } from "./memory-sync";
import { MemoryModal } from "./memory-modal";

export default class InvisibleCompanionPlugin extends Plugin {
  settings: CompanionSettings = defaults();
  private scope = new ConsentScope();
  private get tokenKey(): string { return `invisible-ai-companion:${this.settings.installationId}`; }
  private latestDecision?: Extract<NudgeDecision, { decision: "show" }>;
  private controller?: EvaluationController;
  private noteIds = new NoteIds();
  private memory?: MemoryClient;
  private memorySync?: MemorySync;
  private pairingGeneration = 0;
  private needsReload = false;
  connectionStatus = "Not connected";
  private get token(): string | undefined { return this.app.secretStorage.getSecret(this.tokenKey) || undefined; }
  async onload(): Promise<void> {
    this.settings = { ...defaults(), ...(await this.loadData() as Partial<CompanionSettings> | null) };
    this.settings.serverUrl = serverOrigin(this.settings.serverUrl);
    this.settings.installationId = localInstallationId(this.settings.vaultId, this.app.secretStorage);
    this.restoreScope();
    this.noteIds = new NoteIds(this.settings.noteIds, ids => { this.settings.noteIds = ids; void this.saveData(this.settings); });
    this.registerView(NUDGE_VIEW, leaf => new NudgeView(leaf));
    this.addSettingTab(new CompanionSettingsTab(this.app, this));
    // app.secretStorage (Obsidian 1.11.4) keeps the bearer token outside plugin data and notes.
    const http = new HttpTransport(requestUrl, () => this.settings.serverUrl + "/v1/nudges:evaluate", () => this.token);
    this.memory = new MemoryClient(requestUrl, () => this.settings.serverUrl, () => this.token);
    this.connectionStatus = this.token ? "Device token configured" : "Not connected";
    const transport = http;
    this.memorySync = new MemorySync(this.scope, this.noteIds,
      () => !this.needsReload && this.settings.enabled && !this.settings.paused && this.settings.memoryEnabled && this.settings.serverUrl !== LOCAL_ORIGIN && !!this.token,
      { installationId: this.settings.installationId, vaultId: this.settings.vaultId }, request => this.memory!.upload(request));
    const status = this.addStatusBarItem(); status.setText("Companion idle");
    const showLatest = async (): Promise<void> => { if (this.latestDecision) await (await getNudgeView(this.app)).showDecision(this.latestDecision); };
    status.setAttribute("role", "button"); status.tabIndex = 0; status.setAttribute("aria-label", "Open companion nudge");
    status.addEventListener("click", () => { void showLatest(); });
    status.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); void showLatest(); } });
    this.controller = new EvaluationController(this.scope, transport, this.settings, decision => {
      this.latestDecision = decision; status.setText("Companion nudge available");
      new Notice("Companion nudge available. Click the status item or run ‘Show companion nudge’.");
    }, this.noteIds);
    this.controller.setPaused(this.settings.paused || !this.settings.enabled);
    this.registerEvent(this.app.workspace.on("editor-change", editor => {
      const file = this.app.workspace.getActiveFile(); if (file) { this.controller?.schedule(file.path, editor.getValue()); this.memorySync?.schedule(file.path, editor.getValue()); }
    }));
    this.registerEvent(this.app.vault.on("rename", (file, oldPath) => { this.memorySync?.cancel(); this.noteIds.rename(oldPath, file.path); }));
    this.registerEvent(this.app.vault.on("delete", file => {
      this.memorySync?.cancel();
      const id = this.noteIds.existing(file.path);
      if (id) {
        this.settings.pendingDeletes = [...new Set([...this.settings.pendingDeletes, id])];
        this.noteIds.remove(file.path); void this.flushDeletes();
      }
    }));
    void this.flushDeletes();
    this.addCommand({ id: "sign-in-google", name: "Sign in with Google", callback: () => this.signIn() });
    this.addCommand({ id: "ask-memories", name: "Ask your memories", callback: () => {
      if (!this.settings.memoryEnabled || !this.token || this.settings.serverUrl === LOCAL_ORIGIN || this.needsReload) { this.connectionNotice("Enable central memories and sign in first."); return; }
      new MemoryModal(this.app, query => this.memory!.answer(this.settings.installationId, this.settings.vaultId, query)).open();
    } });
    this.addCommand({ id: "show-companion-nudge", name: "Show companion nudge", callback: async () => {
      await showLatest();
    } });
  }
  async updateSettings(change: Partial<CompanionSettings>): Promise<void> {
    this.memorySync?.cancel();
    if (change.serverUrl !== undefined) change.serverUrl = serverOrigin(change.serverUrl);
    if (change.serverUrl !== undefined && change.serverUrl !== this.settings.serverUrl) {
      this.pairingGeneration++; this.app.secretStorage.setSecret(this.tokenKey, "");
      this.connectionStatus = "Server changed; reload and sign in again";
      change = { ...change, noteIds: {}, pendingDeletes: [], vaultId: crypto.randomUUID(), installationId: crypto.randomUUID() };
      this.needsReload = true; this.controller?.setPaused(true);
      this.settings = { ...this.settings, ...change }; await this.saveData(this.settings);
      this.connectionNotice("Server saved. Reload the plugin before connecting."); return;
    }
    this.settings = { ...this.settings, ...change }; this.restoreScope(); await this.saveData(this.settings);
    this.controller?.setPaused(this.needsReload || this.settings.paused || !this.settings.enabled);
  }
  /** Pairing flow calls this after the user explicitly accepts the companion's pairing code. */
  storePairedToken(token: string): void { if (!this.needsReload) { this.app.secretStorage.setSecret(this.tokenKey, token); this.connectionStatus = "Device token configured"; } }
  connectionNotice(message: string): void { new Notice(message); }
  async signIn(): Promise<void> {
    if (this.needsReload) { this.connectionNotice("Reload the plugin first."); return; }
    const generation = ++this.pairingGeneration;
    let notice: Notice | undefined;
    try {
      const client = new PairingClient(requestUrl, this.settings.serverUrl);
      const pairing = await client.start(this.settings.installationId, this.settings.vaultId);
      if (generation !== this.pairingGeneration) return;
      this.connectionStatus = "Waiting for browser approval";
      notice = new Notice(`Confirm this code in your browser: ${pairing.userCode}`, 0);
      window.open(pairing.verificationUrl, "_blank", "noopener,noreferrer");
      while (generation === this.pairingGeneration) {
        await new Promise(resolve => window.setTimeout(resolve, pairing.interval * 1000));
        if (generation !== this.pairingGeneration) return;
        const token = await client.poll(pairing);
        if (generation !== this.pairingGeneration) return;
        if (token) { this.storePairedToken(token); this.connectionStatus = "Connected"; this.connectionNotice("Google sign-in complete."); void this.flushDeletes(); return; }
      }
    } catch { if (generation === this.pairingGeneration) { this.connectionStatus = "Sign-in failed or expired"; this.connectionNotice(this.connectionStatus); } }
    finally { notice?.hide(); }
  }
  async signOut(): Promise<void> {
    const generation = ++this.pairingGeneration;
    try { await this.memory?.revoke(); }
    catch { this.connectionNotice("Could not revoke the token on the server. Retry when connected."); return; }
    if (generation !== this.pairingGeneration) return;
    this.app.secretStorage.setSecret(this.tokenKey, ""); this.connectionStatus = "Disconnected";
    this.connectionNotice("This device token was revoked.");
  }
  private async flushDeletes(): Promise<void> {
    if (!this.token || this.settings.serverUrl === LOCAL_ORIGIN || this.needsReload) return;
    for (const noteId of [...this.settings.pendingDeletes]) {
      try { await this.memory?.remove(this.settings.installationId, this.settings.vaultId, noteId); }
      catch { return; }
      this.settings.pendingDeletes = this.settings.pendingDeletes.filter(id => id !== noteId); await this.saveData(this.settings);
    }
  }
  onunload(): void { this.memorySync?.cancel(); this.pairingGeneration++; this.controller?.setPaused(true); }
  private restoreScope(): void { this.scope.clear(); for (const folder of this.settings.allowedFolders) this.scope.allow(folder); }
}
