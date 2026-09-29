import { App, ItemView, WorkspaceLeaf } from "obsidian";
import { NudgeDecision } from "./protocol";

export const NUDGE_VIEW = "invisible-ai-nudge";

/** A passive side panel; it is only opened by an explicit command or click. */
export class NudgeView extends ItemView {
  private decision?: Extract<NudgeDecision, { decision: "show" }>;
  constructor(leaf: WorkspaceLeaf) { super(leaf); }
  getViewType(): string { return NUDGE_VIEW; }
  getDisplayText(): string { return "Companion nudge"; }
  async showDecision(decision: Extract<NudgeDecision, { decision: "show" }>): Promise<void> {
    this.decision = decision; await this.render();
  }
  async onOpen(): Promise<void> { await this.render(); }
  private async render(): Promise<void> {
    const el = this.contentEl; el.empty();
    if (!this.decision) { el.createEl("p", { text: "No current nudge." }); return; }
    el.createEl("p", { text: this.decision.hint, attr: { "aria-live": "polite" } });
    const dismiss = el.createEl("button", { text: "Dismiss", attr: { "aria-label": "Dismiss companion nudge" } });
    dismiss.onclick = () => { this.decision = undefined; void this.render(); };
  }
}

export const getNudgeView = async (app: App): Promise<NudgeView> => {
  let leaf = app.workspace.getLeavesOfType(NUDGE_VIEW)[0];
  if (!leaf) leaf = app.workspace.getRightLeaf(false)!;
  await leaf.setViewState({ type: NUDGE_VIEW, active: false });
  return leaf.view as NudgeView;
};
