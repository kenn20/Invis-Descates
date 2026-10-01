import { ConsentScope, excerptAtMost, NoteIds } from "./scope";
import { EvaluateRequest } from "./protocol";

/** Indexing is independent of the nudge budget, and rechecks consent at send time. */
export class MemorySync {
  private timer?: ReturnType<typeof setTimeout>;
  private revision = 0;
  constructor(private readonly scope: ConsentScope, private readonly ids: NoteIds,
    private readonly enabled: () => boolean,
    private readonly identity: { installationId: string; vaultId: string },
    private readonly upload: (request: Pick<EvaluateRequest, "installationId" | "vaultId" | "noteId" | "revision" | "excerpt">) => Promise<void>) {}
  schedule(path: string, text: string): void {
    this.cancel();
    if (!this.enabled() || !this.scope.permits(path) || !text.trim()) return;
    this.timer = setTimeout(() => {
      this.timer = undefined;
      if (!this.enabled() || !this.scope.permits(path)) return;
      this.revision = Math.max(Date.now(), this.revision + 1);
      void this.upload({ ...this.identity, noteId: this.ids.idFor(path), revision: this.revision, excerpt: excerptAtMost(text) }).catch(() => {});
    }, 1200);
  }
  cancel(): void { if (this.timer) clearTimeout(this.timer); this.timer = undefined; }
}
