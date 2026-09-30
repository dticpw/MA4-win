// Visual check of the running MA4 page with the system Chrome.
// Uses the playwright-core that the Playwright MCP already cached under ~/.npm/_npx
// (no browser download). Usage: node tools/ui_check.mjs [thread-id] [out-dir]
import { readdirSync, existsSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const cache = join(homedir(), ".npm/_npx");
const found = readdirSync(cache).map((d) => join(cache, d, "node_modules/playwright-core/index.mjs")).find(existsSync);
if (!found) throw new Error("playwright-core not found under ~/.npm/_npx; run the Playwright MCP once");
const { chromium } = await import(found);

const [id = "", out = ".agent-tmp/ui-check"] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true });
const problems = [];
for (const [w, h, scheme] of [[1440, 900, "light"], [1024, 800, "dark"], [390, 844, "light"]]) {
  const page = await browser.newPage({ viewport: { width: w, height: h }, colorScheme: scheme });
  page.on("pageerror", (e) => problems.push(`${w}: ${e.message}`));
  page.on("console", (m) => m.type() === "error" && problems.push(`${w}: ${m.text()}`));
  await page.goto(`http://127.0.0.1:8764/${id ? "#" + id : ""}`);
  await page.waitForSelector(id ? ".turn" : ".thread", { timeout: 15000 }).catch(() => problems.push(`${w}: nothing rendered`));
  await page.waitForTimeout(800);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  if (overflow > 0) problems.push(`${w}: horizontal overflow ${overflow}px`);
  await page.screenshot({ path: join(out, `w${w}.png`) });
  await page.close();
}
await browser.close();
console.log(problems.length ? problems.join("\n") : `ok · screenshots in ${out}`);
