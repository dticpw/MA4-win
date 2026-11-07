import { chromium, executablePath } from "./browser.mjs";
// Render deterministic API fixtures through the real page; never calls a model
// or writes to MA4 state. Uses the existing system Chrome and Playwright cache.
import assert from "node:assert/strict";
import { readdirSync, existsSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";

const origin = process.env.MA4_URL || "http://127.0.0.1:8764";
const out = resolve(process.argv[2] || ".agent-tmp/controller-refinement/ui");

const usage = { totalTokens: 1600, inputTokens: 1500, cachedInputTokens: 1200, outputTokens: 100 };
const task = { id: "fixture-task", name: "统计与派工详情 · 界面验证", cwd: "/example/project", host: "fixture-host", formerHosts: [],
  workers: { "fixture-worker": { name: "Skill 评估", state: "idle", access: "read", scope: [] } },
  hostBusy: false, status: "stopped", target: "只验证渲染，不调用模型。", budget: {}, usageTotal: usage, summary: "整体目标未达标", evidence: "测试数据",
  completion: { outcome: "unmet", usageTotal: usage, turnDurationMs: 65000, settling: false },
  statistics: { roles: [{ role: "host", usage, durationMs: 65000, turnCount: 2 }, { role: "worker", usage: {}, durationMs: 0, turnCount: 0 }],
    sessions: [{ threadId: "fixture-host", name: "当前中控", usage, durationMs: 65000, unattributedTokens: 100,
      turns: [{ id: "fixture-turn-1", status: "completed", usage, durationMs: 65000 }, { id: "fixture-turn-2", status: "failed", usage: null }] }] } };
const controllers = { tasks: [task], error: null, recovering: false };
const state = { controllers, seq: 0, daemon: { connected: true }, approvals: [], side: { runtime: { home: "/home/dticpw", defaultCwd: "/home/dticpw/codex" }, folds: [
  { name: "RPGO3dPixel · 旧普通会话", cwd_prefix: task.cwd, include_active: true },
  { name: "MA3 · 旧执行会话", cwd_prefix: "/example/ma3/" },
] }, threads: [
  { id: task.host, name: task.name, cwd: task.cwd, status: "idle", updatedAt: 1,
    sandbox: "dangerFullAccess", approval: "never" },
  { id: "fixture-worker", name: "Skill 评估", cwd: task.cwd, status: "idle", updatedAt: 1 },
  { id: "normal", name: "日常讨论", cwd: "/home/dticpw/codex", status: "idle", updatedAt: 1 },
  { id: "ma4", name: "MA4 接续", cwd: "/home/dticpw/PG_linux/MA4", status: "idle", updatedAt: 1 },
  { id: "legacy", name: "旧 RPG 讨论", cwd: task.cwd, status: "idle", updatedAt: 1 },
  { id: "old-worker", name: "旧 MA3 执行", cwd: "/example/ma3/work", status: "idle", updatedAt: 1 },
] };
const history = { older: null, turns: [{ id: "fixture-turn-1", status: "completed", items: [
  { id: "dispatch", type: "dynamicToolCall", tool: "ma4_dispatch", status: "completed", success: false,
    arguments: JSON.stringify({ instruction: "先核对预览 <img src=x onerror=alert(1)>，成果放在项目内。", write_scope: ["/absolute/path"] }, null, 2),
    output: '{"error":"写入范围必须是项目相对路径，如 src/ui"}' },
  { id: "success", type: "dynamicToolCall", tool: "ma4_control", status: "completed", success: true,
    arguments: '{"action":"finish","outcome":"unmet"}', output: '{"status":"stopped"}' },
  { id: "running", type: "dynamicToolCall", tool: "ma4_artifacts", status: "inProgress", arguments: '{"action":"list"}' },
] }] };
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath, headless: true });
const problems = [];
try {
  for (const [width, height, scheme] of [[1440, 1000, "light"], [1024, 900, "dark"], [390, 844, "light"]]) {
    const page = await browser.newPage({ viewport: { width, height }, colorScheme: scheme, reducedMotion: "reduce" });
    page.on("pageerror", (e) => problems.push(e.message));
    page.on("console", (m) => { if (m.type() === "error") problems.push(m.text()); });
    // No actual state, history, open, send or event requests reach the server.
    await page.addInitScript(() => { window.EventSource = class { constructor() { window.fixtureEvents = this; } addEventListener() {} }; });
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      const result = { "/api/state": state, "/api/history": history, "/api/open": {}, "/api/side": {} }[path];
      if (result === undefined) problems.push("Unexpected API request: " + path);
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(result || {}) });
    });
    await page.goto(origin + "#" + task.host);
    await page.waitForSelector('[data-item="dispatch"]');
    assert.match(await page.locator("#chat-meta").innerText(), /完全访问 · 从不审批/);
    assert.equal(await page.locator("#task-reports").isVisible(), false);
    const pending = structuredClone(controllers);
    pending.tasks[0].status = "review";
    pending.tasks[0].hostBusy = true;
    pending.tasks[0].reportDelivery = { count: 2, state: "host_busy", reason: "中控正在处理当前回合，结束后再回传",
      reports: [{ name: "静态屋瓦铺石与贴地返修 · Skill 评估", threadId: "fixture-worker" },
        { name: "Godot-Blender 归档页面制作", threadId: "fixture-archive" }] };
    await page.evaluate((value) => window.fixtureEvents.onmessage({ data: JSON.stringify({ kind: "controllers", controllers: value }) }), pending);
    assert.match(await page.locator("#task-reports").innerText(), /2 份执行报告待回传/);
    assert.match(await page.locator("#task-reports").innerText(), /当前回合/);
    const reportButton = page.locator('[data-report-thread="fixture-worker"]');
    await reportButton.focus();
    await page.evaluate((value) => window.fixtureEvents.onmessage({ data: JSON.stringify({ kind: "controllers", controllers: value }) }), pending);
    assert.equal(await reportButton.evaluate((el) => document.activeElement === el), true);
    await page.screenshot({ path: join(out, `reports-w${width}.png`), fullPage: true });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    pending.tasks[0].reportDelivery.reason = "任务未自动运行，报告保留；普通聊天不会恢复任务";
    pending.tasks[0].reportDelivery.state = "retained";
    pending.tasks[0].status = "paused";
    pending.tasks[0].hostBusy = false;
    await page.evaluate((value) => window.fixtureEvents.onmessage({ data: JSON.stringify({ kind: "controllers", controllers: value }) }), pending);
    assert.match(await page.locator("#task-reports").innerText(), /不会恢复/);
    await page.locator('[data-report-thread="fixture-worker"]').focus();
    await page.keyboard.press("Enter");
    await page.waitForURL("**/#fixture-worker");
    assert.equal(await page.locator("#input").isDisabled(), true);
    await page.locator("#task-back-host").click();
    await page.waitForURL("**/#fixture-host");
    await page.evaluate((value) => window.fixtureEvents.onmessage({ data: JSON.stringify({ kind: "controllers", controllers: value }) }), controllers);
    assert.equal(await page.locator("#task-reports").isVisible(), false);
    await page.locator("#task-statistics-details > summary").focus();
    await page.keyboard.press("Enter");
    await page.locator('[data-session-stats="fixture-host"] > summary').click();
    assert.match(await page.locator("#task-statistics").innerText(), /缓存输入/);
    assert.match(await page.locator("#task-statistics").innerText(), /100 tokens 尚未归属/);
    assert.match(await page.locator("#task-statistics").innerText(), /未取得轮次用量/);
    // A live usage update preserves expansion of the selected session.
    await page.evaluate((controllers) => {
      controllers.tasks[0].usageTotal.totalTokens += 1;
      window.fixtureEvents.onmessage({ data: JSON.stringify({ kind: "controllers", controllers }) });
    }, structuredClone(controllers));
    assert.equal(await page.locator('[data-session-stats="fixture-host"]').evaluate((el) => el.open), true);
    await page.locator('[data-session-stats="fixture-host"] table').scrollIntoViewIfNeeded();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `stats overflow at ${width}`);
    await page.screenshot({ path: join(out, `stats-w${width}.png`), fullPage: true });
    await page.locator("#task-statistics-details > summary").click();
    const detail = page.locator('[data-item="dispatch"]');
    await detail.locator("summary").focus();
    await page.keyboard.press("Enter");
    assert.match(await detail.innerText(), /派工内容与参数/);
    assert.match(await detail.innerText(), /必须是项目相对路径/);
    assert.equal(await detail.locator("img").count(), 0);
    assert.match(await page.locator('[data-item="success"] summary').innerText(), /成功/);
    assert.match(await page.locator('[data-item="running"] summary').innerText(), /运行中/);
    await detail.locator("pre").last().scrollIntoViewIfNeeded();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `overflow at ${width}`);
    await page.screenshot({ path: join(out, `tools-w${width}.png`), fullPage: true });
    // Managed and ordinary threads with the same cwd must never mix.
    assert.equal(await page.locator('[data-id="legacy"]').count(), 0);
    assert.equal(await page.locator('[data-id="normal"]').count(), 0);
    await page.locator("#tab-sessions").click();
    assert.equal(await page.locator('#thread-list [data-task="fixture-task"]').count(), 0);
    assert.equal(await page.locator('[data-id="normal"]').count(), 1);
    assert.equal(await page.locator('[data-id="ma4"]').count(), 1);
    assert.equal(await page.locator('[data-id="legacy"]').count(), 0);
    const legacy = page.locator('[data-project="sessions:/example/project"]');
    await legacy.click();
    await page.locator('[data-id="legacy"]').waitFor();
    assert.equal(await page.locator('[data-id="legacy"]').count(), 1);
    await page.locator("#search").fill("旧 RPG");
    assert.equal(await page.locator('[data-id="legacy"]').count(), 1);
    assert.equal(await page.locator('[data-id="normal"]').count(), 0);
    await page.locator("#search").fill("");
    await page.locator("#new-thread").click();
    assert.equal(await page.locator("#new-cwd").inputValue(), "/home/dticpw/codex");
    await page.keyboard.press("Escape");
    await page.locator("#tab-sessions").focus();
    await page.keyboard.press("ArrowLeft");
    assert.equal(await page.locator("#tab-tasks").getAttribute("aria-selected"), "true");
    assert.equal(await page.locator('[data-id="legacy"]').count(), 0);
    await page.evaluate((controllers) => {
      controllers.tasks[0].status = "closing";
      controllers.tasks[0].note = "时限已到，等待当前工作安全收尾，再由中控汇总。";
      window.fixtureEvents.onmessage({ data: JSON.stringify({ kind: "controllers", controllers }) });
    }, structuredClone(controllers));
    assert.equal(await page.locator("#task-state").innerText(), "到期收尾中");
    assert.equal(await page.locator("#task-pause").innerText(), "立即停止");
    assert.equal(await page.locator("#task-resume").isVisible(), false);
    assert.equal(await page.locator("#task-handoff").isDisabled(), true);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: join(out, `closing-w${width}.png`), fullPage: true });
    // Formerly all idle/attention tasks said "prepare a draft". Exercise an
    // expired, already handed-off task, without sending or renewing anything.
    const diagnosed = structuredClone(controllers), dt = diagnosed.tasks[0];
    dt.status = "attention";
    dt.budget = { deadline: 1000 };
    delete dt.completion;
    dt.summary = dt.evidence = "";
    dt.diagnosis = { code: "budget", title: "预算已到，需确认后继续", reason: "已到截止时间，不能按当前预算启动新工作。",
      nextStep: "你：打开“查看并确认后继续”，核对目标与目录，明确调整预算后再启动；仅聊天不会恢复自动推进。",
      facts: ["接任中控已创建，交接说明尚未发送；下一次消息会附带说明。"],
      work: { host: false, running: 0, sending: 0, queued: 0, idle: 7, reports: 0 },
      confirmBlocker: null, handoffBlocker: null, canPause: false };
    const push = async () => page.evaluate(value => window.fixtureEvents.onmessage({ data: JSON.stringify({ kind: "controllers", controllers: value }) }), diagnosed);
    await push();
    assert.equal(await page.locator("#task-phase").isVisible(), false);
    assert.match(await page.locator("#task-diagnosis").innerText(), /预算已到/);
    assert.match(await page.locator("#task-diagnosis").innerText(), /空闲 7/);
    await page.locator("[data-diagnosis-evidence] > summary").focus();
    await page.keyboard.press("Enter");
    assert.match(await page.locator("#task-diagnosis").innerText(), /交接说明尚未发送/);
    await push();
    assert.equal(await page.locator("[data-diagnosis-evidence] > summary").evaluate(el => document.activeElement === el), true);
    dt.diagnosis.work.reports = 1;
    await push();
    assert.equal(await page.locator("[data-diagnosis-evidence]").evaluate(el => el.open), true);
    assert.equal(await page.locator("[data-diagnosis-evidence] > summary").evaluate(el => document.activeElement === el), true);
    dt.diagnosis.work.reports = 0;
    await push();
    await page.keyboard.press("Enter");
    await page.locator("#task-context").evaluate(el => { el.scrollTop = 0; });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.equal(await page.locator("#task-pause").isVisible(), false);
    await page.screenshot({ path: join(out, `diagnosis-w${width}.png`), fullPage: true });
    await page.locator("#task-resume").focus();
    await page.keyboard.press("Enter");
    assert.equal(await page.locator("#task-dialog").evaluate(el => el.open), true);
    assert.equal(await page.locator("#task-duration").inputValue(), ""); // no automatic extension
    assert.equal(await page.locator("#task-save").isDisabled(), false);
    await page.locator("#task-duration").fill("30");
    const originalGoal = await page.locator("#task-form-target").inputValue();
    Object.assign(dt.diagnosis, { code: "sending", title: "消息发送结果待确认", reason: "尚未取得确认", nextStep: "MA4：按消息标记核对。",
      confirmBlocker: "还有回合或发送操作未结束，请等它们返回后再确认目标", handoffBlocker: "任务已结束或有发送状态未确认" });
    await push();
    assert.equal(await page.locator("#task-save").isDisabled(), true);
    assert.equal(await page.locator("#task-confirm-only").isDisabled(), true);
    assert.match(await page.locator("#task-confirm-hint").innerText(), /发送操作未结束/);
    assert.equal(await page.locator("#task-duration").inputValue(), "30");
    assert.equal(await page.locator("#task-form-target").inputValue(), originalGoal);
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#task-handoff").isDisabled(), true);
    Object.assign(dt.diagnosis, { code: "pausing", title: "自动推进已停，仍有回合未结束", canPause: true });
    dt.status = "paused";
    dt.diagnosis.work.running = 1;
    await push();
    assert.equal(await page.locator("#task-pause").innerText(), "停止在途回合");
    dt.status = "waiting";
    dt.budget = { deadline: Date.now() / 1000 + 3600 };
    Object.assign(dt.diagnosis, { code: "workers_busy", title: "执行者仍在工作", reason: "中控当前空闲，不代表整个任务已经停住。",
      nextStep: "执行者：完成工作并报告；MA4 在中控空闲且条件允许时自动回传。", facts: [],
      confirmBlocker: "还有回合或发送操作未结束，请等它们返回后再确认目标", handoffBlocker: null });
    await push();
    assert.match(await page.locator("#task-diagnosis").innerText(), /执行者仍在工作/);
    assert.match(await page.locator("#task-diagnosis").innerText(), /执行中 1/);
    assert.equal(await page.locator("#task-resume").isVisible(), false);
    assert.equal(await page.locator("#task-handoff").isDisabled(), false);
    await page.locator("#task-context").evaluate(el => { el.scrollTop = 0; });
    await page.screenshot({ path: join(out, `diagnosis-active-w${width}.png`), fullPage: true });
    await page.locator("#tab-sessions").click();
    await page.screenshot({ path: join(out, `ordinary-w${width}.png`), fullPage: true });
    await page.close();
  }
  assert.deepEqual(problems, []);
  console.log("OK: pending reports, statistics, tool details, sidebar tabs, closing; diagnosis, expired handoff, in-flight pause, uncertain-send blockers, preserved form inputs, keyboard/live update, 1440/1024/390; no model or state writes");
} finally {
  await browser.close();
}
