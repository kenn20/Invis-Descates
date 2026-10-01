import { App, Modal, Setting } from "obsidian";
export class MemoryModal extends Modal {
  constructor(app: App, private readonly ask: (query: string) => Promise<string>) { super(app); }
  onOpen(): void {
    this.contentEl.createEl("h2", { text: "Ask your memories" });
    let query = "";
    new Setting(this.contentEl).setName("Question").addTextArea(input => input.onChange(value => { query = value; }));
    const output = this.contentEl.createEl("p"); output.setAttribute("role", "status");
    new Setting(this.contentEl).addButton(button => button.setButtonText("Ask").setCta().onClick(async () => {
      if (!query.trim()) return;
      button.setDisabled(true); output.setText("Searching your memories…");
      try { output.setText(await this.ask(query)); }
      catch { output.setText("Unable to retrieve memories. Check your connection and sign-in."); }
      finally { button.setDisabled(false); }
    }));
  }
  onClose(): void { this.contentEl.empty(); }
}
