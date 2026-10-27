// Check MA4 with system Chrome and existing playwright-core; no browser download.
// node tools/ui_check.mjs [thread-id] [out-dir] [base-url] [--exercise]
import { readdirSync, existsSync, mkdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const cache = process.platform === "win32"
  ? join(process.env.LOCALAPPDATA, "npm-cache", "_npx") : join(homedir(), ".npm", "_npx");
const found = existsSync(cache) && readdirSync(cache)
  .map(d => join(cache, d, "node_modules", "playwright-core", "index.mjs")).find(existsSync);
if (!found) throw new Error("No cached playwright-core; use the existing Playwright MCP first");
const { chromium } = await import(pathToFileURL(found).href);
const [id = "", out = ".agent-tmp/ui-check", base = "http://127.0.0.1:8764", exercise] = process.argv.slice(2);
if (!["127.0.0.1", "localhost", "[::1]"].includes(new URL(base).hostname))
  throw new Error("UI check is limited to localhost");
mkdirSync(out, { recursive: true });
const executablePath = process.env.MA4_CHROME || (process.platform === "win32"
  ? "C:/Program Files/Google/Chrome/Application/chrome.exe" : "/usr/bin/google-chrome");
const browser = await chromium.launch({ executablePath, headless: true });
const problems = [], checks = [];
try {
  for (const [w, h, scheme] of [[1440, 900, "light"], [1024, 800, "dark"], [390, 844, "light"]]) {
    const page = await browser.newPage({
      viewport: { width: w, height: h }, colorScheme: scheme, reducedMotion: "reduce"
    });
    page.on("pageerror", e => problems.push(w + ": " + e.message));
    page.on("console", m => m.type() === "error" && problems.push(w + ": " + m.text()));
    page.on("response", r => {
      if (r.url().startsWith(base) && r.status() >= 400) problems.push(w + ": HTTP " + r.status() + " " + r.url());
    });
    await page.goto(base + "/" + (id ? "#" + id : ""));
    await page.waitForSelector(id ? ".turn" : ".thread", { timeout: 15000 });
    await page.waitForTimeout(300);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (overflow > 0) problems.push(w + ": horizontal overflow " + overflow + "px");
    await page.getByRole("searchbox", { name: "搜索会话或目录" }).count().then(n => {
      if (n !== 1) problems.push(w + ": search label missing");
    });
    if (id && await page.locator("#input").getAttribute("aria-label") !== "发送消息")
      problems.push(w + ": composer label missing");
    await page.screenshot({ path: join(out, "w" + w + ".png"), fullPage: true });
    checks.push(w + "x" + h + " " + scheme + ": rendered, no horizontal overflow");
    if (exercise === "--exercise" && w === 1440) {
      const response = await page.request.get(base + "/api/state");
      const state = await response.json();
      const cwd = state.side.runtime.defaultCwd;
      // Mutation tests only against our disposable, explicitly mocked smoke fixture.
      if (!cwd.replaceAll("\\", "/").includes("/.agent-tmp/smoke-"))
        throw new Error("--exercise requires an isolated smoke-test workspace");
      await page.locator("#new-thread").click();
      await page.locator("#new-cwd").fill(cwd);
      await page.keyboard.press("Escape");
      if (await page.locator("#new-dialog").isVisible()) problems.push("Escape did not close dialog");
      await page.locator("#new-thread").click();
      await page.locator("#new-cwd").fill(cwd);
      const beforeHash = await page.evaluate(() => location.hash);
      const message = "浏览器发送验证 " + Date.now().toString(36);
      await page.locator("#new-text").fill(message);
      await page.locator("#new-submit").click();
      await page.waitForFunction(before => location.hash !== before, beforeHash);
      await page.getByText(message, { exact: true }).last().waitFor();
      await page.waitForFunction(async () => {
        const response = await fetch("/api/history?id=" + location.hash.slice(1));
        const history = await response.json();
        return history.turns?.at(-1)?.status === "completed";
      });
      await page.getByText("本机模拟回复：Windows 共享会话连接成功。", { exact: true }).last().waitFor();
      const pinBefore = await page.locator("#pin").innerText();
      await page.locator("#pin").click();
      await page.waitForFunction(before => document.querySelector("#pin").innerText !== before, pinBefore);
      await page.locator("#input").fill("/help");
      await page.locator("#send").click();
      await page.getByText("可用命令：", { exact: false }).waitFor({ state: "visible" });
      await page.locator("#home").click();
      await page.locator("#welcome-recent .cards").waitFor();
      checks.push("new dialog / Escape / create+send / streamed reply / pin / help / overview");
    }
    await page.close();
  }
} finally {
  await browser.close();
}
const report = { result: problems.length ? "failed" : "passed", checks, problems };
writeFileSync(join(out, "report.json"), JSON.stringify(report, null, 2) + "\n", "utf8");
console.log(JSON.stringify(report, null, 2));
if (problems.length) process.exitCode = 1;
