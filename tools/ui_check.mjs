// System Chrome + existing Playwright cache. Mutations require the owning fixture.
import { chromium, executablePath } from "./browser.mjs";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { SessionActions, DEFAULT_ACTIONS, MOCK_REPLY } from "./session_actions.mjs";
const [id = "", out = ".agent-tmp/ui-check", base = "http://127.0.0.1:8764", exercise] = process.argv.slice(2);
assert(["127.0.0.1", "localhost", "[::1]"].includes(new URL(base).hostname), "localhost only");
mkdirSync(out, { recursive: true });
const problems = [], checks = [], journeys = [];
let browser, page, actions;
let compatibility = null;
const identity = JSON.parse(process.env.MA4_VERIFY_INSTANCE || "null");
async function defaultCompatibility() {
  compatibility = { result: "running", checks: [], modelTurns: 1 };
  actions.step++;
  await actions.doctor();
  await page.locator("#new-thread").click();
  await page.locator("#new-cwd").fill(identity.cwd);
  await page.keyboard.press("Escape");
  assert.equal(await page.locator("#new-dialog").isVisible(), false, "Escape must close new dialog");
  compatibility.checks.push("new-dialog Escape closed");
  const before = await actions.doctor(), message = "默认兼容检查：创建时带首条消息";
  await page.locator("#new-thread").click();
  await page.locator("#new-cwd").fill(identity.cwd);
  await page.locator("#new-text").fill(message);
  await actions.doctor();
  const pending = page.waitForResponse(r => r.url() === base + "/api/new" && r.request().method() === "POST");
  await page.locator("#new-submit").click();
  const response = await pending, result = await response.json();
  assert(response.ok()); assert(result.threadId && !before.threads.some(t => t.id === result.threadId));
  const session = { id: result.threadId, sends: [], baseline: null };
  actions.owned.set("compat", session);
  await page.waitForFunction(id => location.hash === "#" + id, session.id);
  await page.locator(".turn").waitFor();
  const history = await actions.readHistory("compat", false);
  assert.equal(history.turnCount, 1, "creation with first message starts exactly one turn");
  session.sends.push({ message, turnId: history.summary[0].id, source: "new-dialog first message" });
  compatibility.threadId = session.id;
  compatibility.history = await actions.wait("compat");
  compatibility.checks.push("create with first message", "completed reply");
  assert.equal(await page.locator("#input").getAttribute("aria-label"), "消息正文");
  compatibility.checks.push("composer aria-label");
  const pinBefore = await page.locator("#pin").innerText();
  await actions.doctor();
  await page.locator("#pin").click();
  await page.waitForFunction(before => document.querySelector("#pin").innerText !== before, pinBefore);
  assert((await actions.doctor()).threads.find(t => t.id === session.id).pinned);
  compatibility.checks.push("pin UI and persisted state");
  await page.locator("#input").fill("/help");
  await actions.doctor();
  await page.locator("#send").click();
  await page.getByText("可用命令：", { exact: false }).waitFor({ state: "visible" });
  compatibility.checks.push("/help visible");
  compatibility.screenshot = await actions.screenshot("compatibility-help");
  await page.locator("#home").click();
  await page.locator("#welcome-recent .cards").waitFor();
  compatibility.checks.push("home recent cards");
  await actions.open("compat");
  await actions.readHistory("compat");
  compatibility.result = "passed";
}
try {
  browser = await chromium.launch({ executablePath, headless: true });
  page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  if (exercise === "--exercise") {
    assert(!id, "exercise cannot accept an external thread ID");
    actions = new SessionActions(page, { base, identity, out });
    await actions.start();
    const plan = JSON.parse(process.env.MA4_SESSION_PLAN || JSON.stringify(DEFAULT_ACTIONS));
    await actions.run(plan, process.env.MA4_SESSION_MESSAGE || "第三轮浏览器有限动作验证");
    journeys.push({ feature: "sessions", result: "passed", steps: actions.steps,
      sessions: [...actions.owned].map(([alias, s]) => ({ alias, threadId: s.id, sends: s.sends })) });
    if (!process.env.MA4_SESSION_PLAN) await defaultCompatibility();
  } else {
    page.on("pageerror", e => problems.push(e.message));
    page.on("console", m => { if (m.type() === "error") problems.push(m.text()); });
    page.on("response", r => { if (r.url().startsWith(base + "/") && r.status() >= 400) problems.push("HTTP " + r.status() + " " + r.url()); });
    await page.goto(base + "/" + (id ? "#" + id : ""));
    await page.locator(id ? ".turn" : ".thread, .project-group, #thread-list > .group").first().waitFor();
    if (id) assert.equal(await page.locator("#input").getAttribute("aria-label"), "消息正文");
  }
  for (const [w, h, scheme] of [[1440, 900, "light"], [1024, 800, "dark"], [390, 844, "light"]]) {
    await page.setViewportSize({ width: w, height: h }); await page.emulateMedia({ colorScheme: scheme });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    assert.equal(overflow, 0, "horizontal overflow at " + w);
    assert.equal(await page.getByRole("searchbox", { name: "搜索会话或目录" }).count(), 1);
    await page.screenshot({ path: join(out, "w" + w + ".png"), fullPage: true });
    checks.push(w + "x" + h + " " + scheme + ": rendered, no horizontal overflow");
  }
  if (actions) { await actions.doctor(); await Promise.all(actions.pending); assert(!actions.diagnostics.some(d => !d.expected), "unexpected diagnostic"); }
} catch (error) {
  problems.push(error.stack || String(error));
  if (page) { try { await page.screenshot({ path: join(out, "failure.png"), fullPage: true }); } catch {} }
} finally {
  // Record errors before closing the browser deliberately aborts the persistent SSE.
  if (actions) await Promise.allSettled(actions.pending);
  const report = { result: problems.length ? "failed" : "passed", identity, checks, journeys,
    compatibility, steps: actions?.steps || [], diagnostics: actions?.diagnostics || [], requests: actions?.requests || [], problems };
  writeFileSync(join(out, "report.json"), JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify(report, null, 2));
  if (browser) await browser.close();
}
if (problems.length) process.exitCode = 1;
