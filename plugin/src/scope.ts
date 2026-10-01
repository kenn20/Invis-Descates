/** Local-only scope and opaque-note identity. This module never reads a vault. */
export const excerptAtMost = (text: string, maxBytes = 8 * 1024): string => {
  const encoder = new TextEncoder();
  if (encoder.encode(text).byteLength <= maxBytes) return text;
  let end = text.length;
  while (encoder.encode(text.slice(0, end)).byteLength > maxBytes) end--;
  return text.slice(0, end);
};

export class ConsentScope {
  private allowed = new Set<string>();
  clear(): void { this.allowed.clear(); }
  allow(folder: string): void { this.allowed.add(this.canonical(folder)); }
  remove(folder: string): void { this.allowed.delete(this.canonical(folder)); }
  permits(notePath: string): boolean {
    if (notePath.startsWith("/") || notePath.split("/").includes("..")) return false;
    const path = this.canonical(notePath);
    return [...this.allowed].some(folder => path === folder || path.startsWith(`${folder}/`));
  }
  private canonical(path: string): string {
    const parts = path.split("/").filter(Boolean);
    if (parts.some(part => part === "." || part === "..")) throw new Error("invalid vault-relative path");
    return parts.join("/");
  }
}

export class NoteIds {
  private readonly ids: Map<string, string>;
  constructor(initial: Record<string, string> = {}, private readonly changed: (ids: Record<string, string>) => void = () => {}) { this.ids = new Map(Object.entries(initial)); }
  existing(path: string): string | undefined { return this.ids.get(path); }
  private persist(): void { this.changed(Object.fromEntries(this.ids)); }
  idFor(path: string): string { return this.ids.get(path) ?? this.create(path); }
  rename(from: string, to: string): void { const id = this.ids.get(from); if (id) { this.ids.delete(from); this.ids.set(to, id); this.persist(); } }
  remove(path: string): void { this.ids.delete(path); this.persist(); }
  private create(path: string): string { const id = crypto.randomUUID(); this.ids.set(path, id); this.persist(); return id; }
}
