// Use installed Chrome and the existing MCP cache on either operating system.
import { readdirSync, existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const cache = process.platform === "win32"
  ? join(process.env.LOCALAPPDATA, "npm-cache", "_npx") : join(homedir(), ".npm", "_npx");
const found = readdirSync(cache).map(d => join(cache, d, "node_modules/playwright-core/index.mjs")).find(existsSync);
if (!found) throw new Error("Existing Playwright MCP cache required; no browser is downloaded");
export const { chromium } = await import(pathToFileURL(found).href);
export const executablePath = process.env.MA4_CHROME || (process.platform === "win32"
  ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : "/usr/bin/google-chrome");
