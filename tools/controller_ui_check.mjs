import { chromium, executablePath } from "./browser.mjs";
// Exercise the real local UI with disposable, idle controllers (no model turns).
import assert from "node:assert/strict";
import { readdirSync, existsSync, mkdirSync, rmdirSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";

const origin = process.env.MA4_URL || "http://127.0.0.1:8764";
const out = resolve(process.argv[2] || ".agent-tmp/controller-upgrade/ui-interactions");
mkdirSync(out, { recursive: true });
const project = join(out, "fixture-project");
mkdirSync(project, { recursive: true });

const browser = await chromium.launch({ executablePath, headless: true });
const created = [], problems = [], tag = Date.now();
async function api(path, body) {
  const response = await fetch(origin + path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json", "X-MA4-Request": "1" }, body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}
async function tasks() { return (await api("/api/state")).controllers.tasks; }
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
  page.on("pageerror", (e) => problems.push(e.message));
  await page.goto(origin);
  await page.waitForSelector(".project-group");
  for (const suffix of ["<A>", "B"]) {
    await page.locator("#new-controller").click();
    await page.locator("#task-cwd").fill(project);
    await page.locator("#task-form-name").fill(`UI 验证 ${suffix} ${tag}`);
    await page.locator("#task-form-target").fill("只验证界面，不启动模型；验收标准：分组、编辑、交接可用。");
    assert.equal(await page.locator("#task-duration").inputValue(), "120");
    assert.equal(await page.locator("#task-tokens").inputValue(), "");
    assert.equal(await page.locator("#task-money").inputValue(), "");
    await page.locator("#task-save").click();
    await page.waitForFunction(() => !document.getElementById("task-dialog").open);
    const task = (await tasks()).find((t) => t.name === `UI 验证 ${suffix} ${tag}`);
    assert(task); created.push(task.id);
    assert.deepEqual(task.budget, { durationMinutes: 120, currency: "CNY" });
    await page.locator(`[data-task="${task.id}"]`).click();
    await page.waitForFunction((name) => document.getElementById("task-name").textContent === name, task.name);
  }
  const [a, b] = await Promise.all(created.map(async (id) => (await tasks()).find((t) => t.id === id)));
  assert.equal(a.cwd, b.cwd);
  assert.notEqual(a.host, b.host);
  await page.locator(`[data-task="${a.id}"]`).click();
  await page.locator("#task-edit").click();
  await page.locator("#task-form-target").fill("用户明确修改的目标，保存后暂停。");
  await page.locator("#task-save").click();
  await page.waitForFunction(() => !document.getElementById("task-dialog").open);
  let current = (await tasks()).find((t) => t.id === a.id);
  assert.equal(current.status, "paused");
  assert.equal(current.target, "用户明确修改的目标，保存后暂停。");
  assert.equal(current.budget.durationMinutes, 120);
  await page.locator("#task-handoff").click();
  await page.locator("#handoff-summary").fill("只有界面验证，无执行产物；保持用户目标和预算。");
  await page.locator("#handoff-submit").click();
  await page.waitForFunction(() => !document.getElementById("handoff-dialog").open);
  current = (await tasks()).find((t) => t.id === a.id);
  assert.notEqual(current.host, a.host);
  assert(current.formerHosts.includes(a.host));
  assert.equal(await page.locator("#input").isDisabled(), true);
  await page.locator("#task-back-host").click();
  await page.waitForFunction(() => !document.getElementById("input").disabled);
  await page.locator("#task-artifacts").click();
  await page.waitForSelector("#artifacts-dialog[open]");
  assert.match(await page.locator("#artifacts-list").innerText(), /没有待处理/);
  await page.locator('[data-close-dialog="artifacts-dialog"]').click();
  for (const [width, height, scheme] of [[1440, 1000, "light"], [1024, 900, "dark"], [390, 844, "light"]]) {
    await page.setViewportSize({ width, height });
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    await page.evaluate(() => document.documentElement.removeAttribute("data-theme"));
    await page.waitForTimeout(200);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `overflow at ${width}`);
    await page.screenshot({ path: join(out, `w${width}.png`), fullPage: true });
    await page.locator("#new-controller").click();
    assert.equal(await page.locator("#task-duration").inputValue(), "120");
    const dialog = await page.locator("#task-dialog").boundingBox();
    assert(dialog.x >= 0 && dialog.x + dialog.width <= width, `dialog overflow at ${width}`);
    await page.screenshot({ path: join(out, `defaults-w${width}.png`), fullPage: true });
    await page.locator("#task-advanced-budget > summary").click();
    await page.locator("#task-deadline").fill("2030-01-01T12:00");
    assert.equal(await page.locator("#task-duration").isDisabled(), true);
    await page.locator("#task-deadline").fill("");
    assert.equal(await page.locator("#task-duration").isDisabled(), false);
    await page.locator('[data-close-dialog="task-dialog"]').click();
  }
  assert.deepEqual(problems, []);
  console.log("OK: default 120 minutes with no money/token cap; create/edit/grouping/handoff/dialogs; 1440/1024/390; no model turns");
} finally {
  await browser.close();
  const failures = [];
  for (const id of created) {
    try { await api("/api/tasks/remove", { task_id: id }); }
    catch (e) { failures.push(`${id}: ${e.message}`); }
  }
  if (!failures.length) rmdirSync(project);
  else throw new Error("Disposable task cleanup failed: " + failures.join("; "));
}
