import { Notice, Plugin, requestUrl } from "obsidian";
import { HttpTransport } from "./transport";
import { NUDGE_VIEW, NudgeView } from "./nudge-ui";
import { CompanionSettings, CompanionSettingsTab, defaults } from "./settings";
import { ConsentScope } from "./scope";
import { EvaluationController } from "./controller";
import { NudgeDecision } from "./protocol";
import { getNudgeView } from "./nudge-ui";

export default class InvisibleCompanionPlugin extends Plugin {
  settings: CompanionSettings = defaults();
  private scope = new ConsentScope();
  private readonly tokenKey = "invisible-ai-companion-token";
  private latestDecision?: Extract<NudgeDecision, { decision: "show" }>;
  private controller?: EvaluationController;
  async onload(): Promise<void> {
    this.settings = { ...defaults(), ...(await this.loadData() as Partial<CompanionSettings> | null) };
    this.restoreScope();
    this.registerView(NUDGE_VIEW, leaf => new NudgeView(leaf));
    this.addSettingTab(new CompanionSettingsTab(this.app, this));
    // app.secretStorage (Obsidian 1.11.4) keeps the bearer token outside plugin data and notes.
    const transport = new HttpTransport(requestUrl, "http://127.0.0.1:27123/v1/nudges:evaluate", () => this.app.secretStorage.getSecret(this.tokenKey) ?? undefined);
    const status = this.addStatusBarItem(); status.setText("Companion idle");
    const showLatest = async (): Promise<void> => { if (this.latestDecision) await (await getNudgeView(this.app)).showDecision(this.latestDecision); };
    status.setAttribute("role", "button"); status.tabIndex = 0; status.setAttribute("aria-label", "Open companion nudge");
    status.addEventListener("click", () => { void showLatest(); });
    status.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); void showLatest(); } });
    this.controller = new EvaluationController(this.scope, transport, this.settings, decision => {
      this.latestDecision = decision; status.setText("Companion nudge available");
      new Notice("Companion nudge available. Click the status item or run ‘Show companion nudge’.");
    });
    this.controller.setPaused(this.settings.paused || !this.settings.enabled);
    this.registerEvent(this.app.workspace.on("editor-change", editor => {
      const file = this.app.workspace.getActiveFile(); if (file) this.controller?.schedule(file.path, editor.getValue());
    }));
    this.addCommand({ id: "show-companion-nudge", name: "Show companion nudge", callback: async () => {
      await showLatest();
    } });
  }
  async updateSettings(change: Partial<CompanionSettings>): Promise<void> {
    this.settings = { ...this.settings, ...change }; this.restoreScope(); await this.saveData(this.settings);
    this.controller?.setPaused(this.settings.paused || !this.settings.enabled);
  }
  /** Pairing flow calls this after the user explicitly accepts the companion's pairing code. */
  storePairedToken(token: string): void { this.app.secretStorage.setSecret(this.tokenKey, token); }
  private restoreScope(): void { this.scope.clear(); for (const folder of this.settings.allowedFolders) this.scope.allow(folder); }
}
