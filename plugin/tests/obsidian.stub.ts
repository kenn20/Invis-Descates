/** Unit boundary only: actual browser and Secret Storage remain manual release gates. */
import { vi } from "vitest";
export class Plugin {
  constructor(public app: unknown, public manifest: unknown) {}
  saveData = vi.fn(async (_: unknown) => {});
}
export class Notice { constructor(_message: string, _duration?: number) {} hide(): void {} }
export class ItemView {}
export class PluginSettingTab {}
export class Modal {}
export class Setting {}
export const requestUrl = vi.fn();
