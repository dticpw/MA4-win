import { chromium, executablePath } from "./browser.mjs";
// Full discussion/confirmation UI flow with intercepted APIs; no real model calls.
import assert from "node:assert/strict";
import { readdirSync, existsSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";


const out = resolve(process.argv[2] || ".agent-tmp/controller-discussion/ui");
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath, headless: true });
const envelope = (source, content) => `[MA4 message:fixture-${source}]\n[MA4 source:${source}]\n任务信息：完整目标与预算\n[MA4 content]\n${content}`;
try {
  for (const [width, scheme] of [[1440, "light"], [1024, "dark"], [390, "light"]]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 }, colorScheme: scheme, reducedMotion: "reduce" });
    const calls = [], errors = [];
    let task;
    const state = { threads: [], approvals: [], daemon: { connected: true }, side: {}, seq: 0,
      controllers: { tasks: [], recovering: false } };
    const history = { older: null, turns: [{ id: "discussion", status: "completed", items: [
      { id: "user", type: "userMessage", text: envelope("user", "先商量人物比例") },
      { id: "automatic", type: "userMessage", text: envelope("automatic", "用户已确认目标与预算") },
      { id: "report", type: "userMessage", text: envelope("worker_report", "执行者：代表动作已制作，请独立验收。") },
    ] }] };
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    await page.addInitScript(() => {
      window.EventSource = class { constructor() { window.fixtureEvents = this; } addEventListener() {} };
    });
    const publish = () => page.evaluate((controllers) => window.fixtureEvents.onmessage({
      data: JSON.stringify({ kind: "controllers", controllers }),
    }), state.controllers);
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname, body = route.request().postDataJSON();
      calls.push({ path, body });
      let result;
      if (path === "/api/state") result = state;
      else if (path === "/api/side") result = {};
      else if (path === "/api/history") result = history;
      else if (path === "/api/open") result = { thread: state.threads[0] };
      else if (path === "/api/tasks/create") {
        assert.equal(body.target, undefined);
        assert.deepEqual(body.budget, { durationMinutes: 480 });
        assert.equal(body.start, undefined);
        assert.equal(body.idea, "先商量人物比例");
        task = { id: "task", host: "host", cwd: body.cwd, name: body.name, idea: body.idea,
          target: "", goalConfirmed: false, draftRevision: 1, draft: { target: "", budget: body.budget },
          budget: body.budget, status: "draft", hostBusy: false, workers: {}, formerHosts: [] };
        state.controllers.tasks = [task];
        state.threads = [{ id: "host", name: task.name, cwd: task.cwd, status: "idle", updatedAt: 1 }];
        result = { taskId: task.id, threadId: task.host };
      } else if (path === "/api/tasks/update") {
        assert.equal(body.draft_revision, task.draftRevision);
        task.draft = { target: body.target, budget: body.budget, workspaces: body.workspaces };
        task.draftRevision++;
        result = { draftSaved: true };
      } else if (path === "/api/tasks/confirm") {
        assert.equal(body.draft_revision, task.draftRevision);
        task.target = body.target; task.budget = body.budget; task.workspaces = body.workspaces; task.draft = null; task.draftRevision++;
        task.goalConfirmed = true; task.status = body.start ? "running" : "paused";
        result = body.start ? { resumed: true } : { confirmed: true };
      } else if (path === "/api/send") result = { mode: "start", turnId: "chat-only" };
      else { errors.push("Unexpected API: " + path); result = {}; }
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(result) });
    });
    const ready = async () => page.waitForFunction(() => !document.getElementById("task-dialog").open);
    await page.goto(process.env.MA4_URL || "http://127.0.0.1:8764");
    await page.waitForFunction(() => window.fixtureEvents);
    await page.locator("#new-controller").click();
    assert.equal(await page.locator("#task-review-fields").isVisible(), false);
    await page.locator("#task-cwd").fill("/example/project");
    await page.locator("#task-form-name").fill("美术方向讨论");
    await page.locator("#task-form-idea").fill("先商量人物比例");
    assert.equal(await page.getByLabel("启动后时限（min）", { exact: true }).isVisible(), true);
    assert.equal(await page.locator("#task-duration").inputValue(), "");
    await page.locator("#task-save").click();
    assert.equal(calls.filter((c) => c.path === "/api/tasks/create").length, 0);
    await page.locator("#task-advanced-budget summary").click();
    assert.equal(await page.locator("#task-money").inputValue(), "");
    assert.equal(await page.locator("#task-tokens").inputValue(), "");
    await page.locator("#task-deadline").fill("2030-10-13T18:00");
    assert.equal(await page.locator("#task-duration").isDisabled(), true);
    assert.equal(await page.locator("#task-form").evaluate((form) => form.checkValidity()), true);
    await page.locator("#task-deadline").fill("");
    assert.equal(await page.locator("#task-duration").isEnabled(), true);
    await page.locator("#task-advanced-budget summary").click();
    for (const value of ["0", "0.5"]) {
      await page.locator("#task-duration").fill(value);
      assert.equal(await page.locator("#task-form").evaluate((form) => form.checkValidity()), false);
    }
    await page.locator("#task-duration").fill("480");
    assert.equal(await page.locator("#task-form").evaluate((form) => form.checkValidity()), true);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: join(out, `create-${width}.png`) });
    await page.locator("#task-save").click();
    await ready();
    await page.waitForSelector('[data-item="report"]');
    assert.match(await page.locator("#task-phase").innerText(), /仅讨论/);
    assert.match(await page.locator("#task-target").textContent(), /尚未确认/);
    assert.equal(await page.locator(".message-source").allTextContents().then((a) => a.join("|")), "你的消息|MA4 自动通知|执行者回报");
    assert.equal(await page.locator(".message-context[open]").count(), 0);
    await page.locator('[data-item="automatic"] summary').focus();
    await page.keyboard.press("Enter");
    assert.match(await page.locator('[data-item="automatic"] pre').innerText(), /完整目标/);
    task.draft = { target: "目标：比例协调\n范围：代表角色\n验收：实机对照", budget: task.budget };
    task.draftRevision++; task.hostBusy = true;
    await publish();
    await page.locator("#task-resume").focus();
    await page.keyboard.press("Enter");
    assert.equal(await page.locator("#task-save").isDisabled(), true);
    task.hostBusy = false; await publish();
    assert.equal(await page.locator("#task-save").isEnabled(), true);
    await page.locator("#task-form-target").fill(task.draft.target + "；由用户看整体效果");
    assert.equal(await page.locator(".workspace-row").count(), 1);
    assert.equal(await page.locator(".workspace-row input").getAttribute("readonly"), "");
    await page.locator("#task-add-workspace").click();
    await page.locator(".workspace-row").last().locator("input").fill("/mnt/c/Users/DTICPW/agent-workflows");
    await page.locator(".workspace-row").last().locator("textarea").fill("skills/godot-tech");
    await page.locator("#task-add-workspace").click();
    await page.locator(".workspace-row").last().locator("[data-remove-workspace]").click();
    assert.equal(await page.locator(".workspace-row").count(), 2);
    assert.match(await page.locator("#task-workspace-note").innerText(), /将发生变更/);
    assert.equal(await page.locator("#task-duration").inputValue(), "480");
    await page.locator("#task-save-draft").click();
    await ready();
    assert.equal(task.target, "");
    assert.equal(task.workspaces, undefined);
    assert.deepEqual(task.draft.workspaces, [
      { cwd: "/example/project", write_scope: [] },
      { cwd: "/mnt/c/Users/DTICPW/agent-workflows", write_scope: ["skills/godot-tech"] },
    ]);
    assert.equal(task.status, "draft");
    await page.locator("#task-resume").click();
    assert.equal(await page.locator("#task-duration").inputValue(), "480");
    await page.screenshot({ path: join(out, `review-${width}.png`) });
    await page.locator("#task-confirm-only").click();
    await ready();
    assert.equal(task.status, "paused");
    assert.equal(task.workspaces.length, 2);
    task.workers = { worker: { name: "Skill 维护", cwd: "/mnt/c/Users/DTICPW/agent-workflows", access: "write", scope: ["skills/godot-tech"], state: "idle" } };
    await publish();
    await page.locator("#task-workspace-summary").locator("..").locator("summary").click();
    assert.match(await page.locator("#task-workspace-summary").innerText(), /Skill 维护/);
    assert.match(await page.locator("#task-workspace-summary").innerText(), /skills\/godot-tech/);
    assert.match(task.target, /由用户看整体效果/);
    await page.locator("#input").fill("补充讨论，不启动任务");
    await page.locator("#composer").evaluate((form) => form.requestSubmit());
    await page.waitForFunction(() => document.getElementById("input").value === "");
    assert.equal(task.status, "paused");
    assert.equal(calls.filter((c) => c.path === "/api/tasks/resume").length, 0);
    task.draft = { target: "目标：场景协调\n范围：一段场景\n验收：游玩镜头", budget: task.budget,
      workspaces: [{ cwd: task.cwd, write_scope: [] }] };
    task.draftRevision++; await publish();
    await page.locator("#task-resume").click();
    assert.match(await page.locator("#task-current-target").innerText(), /比例协调/);
    assert.match(await page.locator("#task-change-note").innerText(), /目标将发生变更/);
    assert.match(await page.locator("#task-current-workspace-text").innerText(), /agent-workflows/);
    assert.equal(await page.locator(".workspace-row").count(), 1);
    assert.match(await page.locator("#task-workspace-note").innerText(), /将发生变更/);
    task.draft.target += "，补查遮挡"; task.draftRevision++; await publish();
    assert.equal(await page.locator("#task-save").isDisabled(), true);
    assert.match(await page.locator("#task-confirm-hint").innerText(), /草案刚刚更新/);
    await page.locator('[data-close-dialog="task-dialog"]').click();
    await page.locator("#task-resume").click();
    assert.match(await page.locator("#task-form-target").inputValue(), /补查遮挡/);
    await page.screenshot({ path: join(out, `change-${width}.png`) });
    await page.locator("#task-save").click();
    await ready();
    assert.equal(task.status, "running");
    assert.match(task.target, /补查遮挡/);
    assert.equal(task.budget.durationMinutes, 480);
    assert.deepEqual(task.workspaces, [{ cwd: task.cwd, write_scope: [] }]);
    assert.equal(calls.filter((c) => c.path === "/api/tasks/confirm" && c.body.start).length, 1);

    // Editing permissions must preserve the exact deadline, including seconds.
    const otherLimits = { tokenLimit: 1000000, moneyLimit: 20, currency: "CNY", rates: { input: 1, cached: 0.1, output: 5 } };
    const originalDeadline = new Date("2030-10-13T18:00:37.125").getTime() / 1000;
    task.status = "paused"; task.budget = { ...otherLimits, deadline: originalDeadline };
    await publish();
    await page.locator("#task-edit").click();
    assert.equal(await page.getByLabel("从现在起的时限（min）", { exact: true }).isEnabled(), true);
    assert.equal(await page.locator("#task-duration").inputValue(), "");
    assert.match(await page.locator("#task-duration-hint").innerText(), /不是在旧截止时间上追加/);
    await page.locator(".workspace-row textarea").fill("assets");
    await page.locator("#task-confirm-only").click(); await ready();
    assert.deepEqual(task.budget, { ...otherLimits, deadline: originalDeadline });
    assert.deepEqual(task.workspaces[0].write_scope, ["assets"]);

    await page.locator("#task-edit").click();
    for (const value of ["0", "-1", "0.5", "1e20"]) {
      await page.locator("#task-duration").fill(value);
      assert.equal(await page.locator("#task-form").evaluate((form) => form.checkValidity()), false);
    }
    await page.locator("#task-duration").fill("");
    assert.equal(await page.locator("#task-form").evaluate((form) => form.checkValidity()), true);
    assert.equal(await page.locator("#task-deadline").isEnabled(), true);
    // The deadline uses the click time, even if the form was open for minutes.
    const enteredAt = new Date("2030-10-13T12:00:00Z").getTime(), clickedAt = enteredAt + 120000;
    await page.evaluate((now) => { Date.now = () => now; }, enteredAt);
    await page.locator("#task-duration").focus();
    await page.keyboard.type("30");
    assert.equal(await page.locator("#task-deadline").isDisabled(), true);
    assert.equal(await page.locator("#task-form").evaluate((form) => form.checkValidity()), true);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.locator("#task-duration-label").evaluate((el) => el.scrollIntoView({ block: "start" }));
    assert.equal(await page.locator("#task-dialog").evaluate((el) => el.scrollWidth > el.clientWidth), false);
    await page.screenshot({ path: join(out, `minutes-${width}.png`) });
    await page.evaluate((now) => { Date.now = () => now; }, clickedAt);
    await page.locator("#task-save").click(); await ready();
    const relativeDeadline = clickedAt / 1000 + 30 * 60;
    assert.deepEqual(task.budget, { ...otherLimits, deadline: relativeDeadline });
    assert.equal(task.status, "running");

    task.status = "paused"; await publish();
    await page.locator("#task-edit").click();
    assert.equal(await page.locator("#task-duration").inputValue(), "");
    await page.locator("#task-duration").fill("60");
    await page.locator('[data-close-dialog="task-dialog"]').click();
    await page.locator("#task-edit").click();
    assert.equal(await page.locator("#task-duration").inputValue(), "");
    assert.equal(await page.locator("#task-deadline").isEnabled(), true);
    assert.equal(task.budget.deadline, relativeDeadline);
    // A draft stores a fixed cutoff, but does not change the active budget.
    await page.locator("#task-duration").fill("15");
    await page.locator("#task-save-draft").click(); await ready();
    const draftDeadline = clickedAt / 1000 + 15 * 60;
    assert.equal(task.budget.deadline, relativeDeadline);
    assert.equal(task.draft.budget.deadline, draftDeadline);
    await page.evaluate((now) => { Date.now = () => now; }, clickedAt + 60000);
    await page.locator("#task-edit").click();
    assert.equal(await page.locator("#task-duration").inputValue(), "");
    await page.locator("#task-confirm-only").click(); await ready();
    assert.deepEqual(task.budget, { ...otherLimits, deadline: draftDeadline });

    // Clearing a relative entry restores manual calendar input.
    await page.locator("#task-edit").click();
    await page.locator("#task-duration").fill("30");
    await page.locator("#task-duration").fill("");
    await page.locator("#task-deadline").fill("2030-10-14T09:45");
    await page.locator("#task-confirm-only").click(); await ready();
    assert.equal(task.budget.deadline, new Date("2030-10-14T09:45").getTime() / 1000);

    // Token/money-only tasks can also add a deadline in minutes.
    task.budget = { ...otherLimits }; await publish();
    await page.locator("#task-edit").click();
    assert.equal(await page.getByLabel("从现在起的时限（min）", { exact: true }).isEnabled(), true);
    await page.locator("#task-confirm-only").click(); await ready();
    assert.deepEqual(task.budget, otherLimits);
    await page.locator("#task-edit").click();
    await page.locator("#task-duration").fill("30");
    await page.locator("#task-confirm-only").click(); await ready();
    assert.equal(task.budget.deadline, (clickedAt + 60000) / 1000 + 30 * 60);
    await page.locator("#new-controller").click();
    assert.equal(await page.getByLabel("启动后时限（min）", { exact: true }).isEnabled(), true);
    assert.equal(await page.locator("#task-duration").inputValue(), "");
    assert.equal(await page.locator("#task-duration-hint").isVisible(), false);
    assert.equal(await page.locator("#task-deadline").isEnabled(), true);
    await page.locator('[data-close-dialog="task-dialog"]').click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    await page.close();
    console.log(`${width}px ${scheme}: discussion flow, permission/time confirmation, relative minutes, fixed deadlines and stale-confirmation guard passed`);
  }
} finally { await browser.close(); }
