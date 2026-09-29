import { cp, mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const vault = process.env.OBSIDIAN_VAULT;
if (!vault) throw new Error("Set OBSIDIAN_VAULT to the vault directory; deployment target is intentionally explicit.");
const target = resolve(vault, ".obsidian/plugins/invisible-ai-companion");
await mkdir(target, { recursive: true });
for (const file of ["main.js", "main.js.map", "manifest.json", "styles.css"]) await cp(file, resolve(target, file));
console.log(`Deployed plugin files to ${target}`);
