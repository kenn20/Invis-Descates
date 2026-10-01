import { expect, it, vi } from "vitest";
import { App, PluginManifest } from "obsidian";
import Plugin from "../src/main";

function setup() {
  const secrets = new Map<string, string>();
  const save = vi.fn(async (_: unknown) => {});
  const app = { secretStorage: { getSecret: (key: string) => secrets.get(key), setSecret: (key: string, value: string) => secrets.set(key, value) } } as unknown as App;
  const plugin = new Plugin(app, {} as PluginManifest);
  plugin.saveData = save;
  return { plugin, secrets, save, app };
}

it("keeps credentials out of saved settings and isolates installations", () => {
  const { plugin, secrets, app } = setup();
  plugin.storePairedToken("credential-a-sentinel");
  const other = new Plugin(app, {} as PluginManifest); other.storePairedToken("credential-b-sentinel");
  expect(secrets.size).toBe(2);
  expect(JSON.stringify(plugin.settings)).not.toContain("credential-a-sentinel");
});

it("clears credentials on server change and blocks connection until reload", async () => {
  const { plugin, secrets, save } = setup();
  const installation = plugin.settings.installationId;
  plugin.storePairedToken("credential-sentinel");
  await plugin.updateSettings({ serverUrl: "https://companion.example" });
  expect([...secrets.values()]).not.toContain("credential-sentinel");
  expect(plugin.settings.installationId).not.toBe(installation);
  plugin.storePairedToken("new-credential"); expect([...secrets.values()]).not.toContain("new-credential");
  expect(JSON.stringify(save.mock.calls)).not.toContain("credential-sentinel");
  await expect(plugin.updateSettings({ serverUrl: "http://evil.example" })).rejects.toThrow();
  expect(plugin.settings.serverUrl).toBe("https://companion.example");
});
