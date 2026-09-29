import { App, PluginSettingTab, Setting } from "obsidian";
import InvisibleCompanionPlugin from "./main";

export interface CompanionSettings {
  enabled: boolean;
  paused: boolean;
  allowedFolders: string[];
  installationId: string;
  vaultId: string;
}

export const defaults = (): CompanionSettings => ({ enabled: false, paused: false, allowedFolders: [], installationId: crypto.randomUUID(), vaultId: crypto.randomUUID() });

/** Consent starts empty and is persisted as plugin configuration, never in a note. */
export class CompanionSettingsTab extends PluginSettingTab {
  private pendingToken = "";
  constructor(app: App, private readonly companion: InvisibleCompanionPlugin) { super(app, companion); }
  display(): void {
    const { containerEl } = this; containerEl.empty();
    new Setting(containerEl).setName("Enable companion").setDesc("No note content is sent until a folder is explicitly allowed.")
      .addToggle(toggle => toggle.setValue(this.companion.settings.enabled).onChange(async enabled => this.companion.updateSettings({ enabled })));
    new Setting(containerEl).setName("Pause nudges").setDesc("Writing and local settings remain available while paused.")
      .addToggle(toggle => toggle.setValue(this.companion.settings.paused).onChange(async paused => this.companion.updateSettings({ paused })));
    new Setting(containerEl).setName("Allowed folders").setDesc("One vault-relative folder per line. Empty means no content leaves Obsidian.")
      .addTextArea(input => input.setValue(this.companion.settings.allowedFolders.join("\n")).onChange(async value => this.companion.updateSettings({ allowedFolders: value.split("\n").map(folder => folder.trim()).filter(Boolean) })));
    new Setting(containerEl).setName("Development pairing token").setDesc("For the local proof only. It is saved in Obsidian Secret Storage, not plugin settings or a note.")
      .addText(input => { input.inputEl.type = "password"; input.onChange(value => { this.pendingToken = value; }); })
      .addButton(button => button.setButtonText("Store token").setCta().onClick(() => { if (this.pendingToken) { this.companion.storePairedToken(this.pendingToken); this.pendingToken = ""; this.display(); } }));
  }
}
