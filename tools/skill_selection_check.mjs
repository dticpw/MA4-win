import { chromium, executablePath } from "./browser.mjs";
// Composer skill selection with intercepted APIs; never starts a real model turn.
import assert from "node:assert/strict";
import { readdirSync, existsSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";


const out = resolve(process.argv[2] || ".agent-tmp/skill-selection/ui");
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath, headless: true });
const choice = { name: "godot-tech", path: "/skills/godot-tech/SKILL.md" };
try {
  for (const [width, scheme] of [[1440, "light"], [1024, "dark"], [390, "light"]]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 }, colorScheme: scheme, reducedMotion: "reduce" });
    const errors = [], sends = [];
    let fail = false, holdSend = false, releaseSend, releaseSkills;
    const task = { id: "task", host: "host", cwd: "/example/project", name: "Skill 选择检查", target: "",
      status: "draft", hostBusy: false, budget: {}, formerHosts: [], workers: { worker: { name: "执行者", state: "idle" } } };
    const threads = ["host", "other", "worker", "race"].map((id) => ({ id, name: id, cwd: `/example/${id}`, status: "idle", updatedAt: 1 }));
    const state = { threads, approvals: [], daemon: { connected: true }, side: {}, seq: 0,
      controllers: { tasks: [task], recovering: false } };
    const history = { older: null, turns: [{ id: "old", status: "completed", items: [
      { id: "historical", type: "userMessage", text: "旧消息原文：先使用 $godot-tech", attachments: [{ type: "skill", ...choice }] },
    ] }] };
    page.on("pageerror", (e) => errors.push(e.message));
    await page.addInitScript(() => {
      window.EventSource = class { constructor() { window.fixtureEvents = this; } addEventListener() {} };
    });
    await page.route("**/api/**", async (route) => {
      const url = new URL(route.request().url()), path = url.pathname, body = route.request().postDataJSON();
      let result;
      if (path === "/api/state") result = state;
      else if (path === "/api/side") result = {};
      else if (path === "/api/history") result = history;
      else if (path === "/api/open") result = { thread: threads.find((t) => t.id === body.id) };
      else if (path === "/api/skills") {
        if (url.searchParams.get("id") === "race") await new Promise((resolve) => { releaseSkills = resolve; });
        result = { skills: [{ ...choice, description: "测试用技能，不访问真实技能文件" },
          ...Array.from({ length: 14 }, (_, i) => ({ name: `sample-${i}`, path: `/skills/${i}/SKILL.md`, description: "测试条目" }))] };
      } else if (path === "/api/send") {
        sends.push(body);
        if (holdSend) await new Promise((resolve) => { releaseSend = resolve; });
        if (fail) { await route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ error: "测试发送失败" }) }); return; }
        result = { mode: "start", turnId: "sent" };
      } else { errors.push("Unexpected API: " + path); result = {}; }
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(result) });
    });
    const input = page.locator("#input"), menu = page.locator("#palette"), selected = page.locator("#composer-skills");
    const ready = () => page.waitForFunction(() => document.getElementById("send").dataset.pending !== "true");
    const open = async (id) => {
      await page.locator(id === "host" || id === "worker" ? "#tab-tasks" : "#tab-sessions").click();
      await page.locator(`[data-id="${id}"]`).click();
      await page.waitForFunction((id) => location.hash === `#${id}` && Boolean(document.querySelector('[data-item="historical"]')), id);
    };
    const choose = async () => {
      await page.locator("#choose-skill").click();
      await menu.locator('[data-index="0"]').click();
      assert.match(await selected.innerText(), /godot-tech/);
    };
    await page.goto((process.env.MA4_URL || "http://127.0.0.1:8764") + "/#host");
    await page.waitForSelector('[data-item="historical"]');
    assert.equal(await page.locator(".message-body").innerText(), "旧消息原文：先使用 $godot-tech");
    assert.equal(await page.locator(".message-attachments").innerText(), "Skill 附件：godot-tech");

    // Pasted and typed names, including Enter with the menu visible, remain text.
    await input.fill("复制的模板：先使用 $godot-tech");
    await menu.waitFor({ state: "visible" });
    await input.press("Enter"); await ready();
    assert.equal(sends.at(-1).text, "复制的模板：先使用 $godot-tech");
    assert.deepEqual(sends.at(-1).skills, []);
    await input.pressSequentially("$godot-tech");
    await menu.waitFor({ state: "visible" });
    await input.press("Shift+Tab");
    assert.equal(await selected.isVisible(), false);
    await input.focus();
    await input.press("Enter"); await ready();
    assert.equal(sends.at(-1).text, "$godot-tech");
    assert.deepEqual(sends.at(-1).skills, []);

    // Button selection leaves text untouched, every enabled skill is reachable.
    await input.fill("正文不含技能名");
    await page.locator("#choose-skill").click();
    await menu.waitFor({ state: "visible" });
    assert.equal(await menu.locator("[data-index]").count(), 15);
    await page.screenshot({ path: join(out, `menu-${width}.png`) });
    await menu.locator('[data-index="0"]').click();
    assert.equal(await input.inputValue(), "正文不含技能名");
    await page.screenshot({ path: join(out, `selected-${width}.png`) });
    await selected.getByRole("button", { name: "移除 Skill godot-tech" }).focus();
    await page.keyboard.press("Enter");
    assert.equal(await selected.isVisible(), false);
    await input.press("Enter"); await ready();
    assert.deepEqual(sends.at(-1).skills, []);

    await input.fill("键盘打开附件菜单");
    await page.locator("#choose-skill").focus(); await page.keyboard.press("Enter");
    await menu.waitFor({ state: "visible" });
    await input.press("ArrowDown"); await input.press("Enter");
    assert.equal(await input.inputValue(), "键盘打开附件菜单");
    await input.press("Enter"); await ready();
    assert.deepEqual(sends.at(-1).skills, [choice]);

    // An explicit keyboard choice removes only the typed search token.
    await input.fill("检查当前实现 $god");
    await menu.waitFor({ state: "visible" });
    await input.press("ArrowDown"); await input.press("Enter");
    assert.equal(await input.inputValue(), "检查当前实现 ");
    assert.match(await selected.innerText(), /godot-tech/);
    await input.press("Enter"); await ready();
    assert.deepEqual(sends.at(-1).skills, [choice]);
    assert.equal(await selected.isVisible(), false);
    await input.fill("后续普通问题"); await input.press("Enter"); await ready();
    assert.deepEqual(sends.at(-1).skills, []);

    // Failed sends retain text and choices; each thread has its own draft.
    await input.fill("发送失败保留"); await choose(); fail = true;
    await input.press("Enter"); await ready();
    assert.equal(await input.inputValue(), "发送失败保留");
    assert.match(await selected.innerText(), /godot-tech/);
    fail = false;
    await open("other");
    assert.equal(await selected.isVisible(), false);
    await input.fill("另一个会话的草稿");
    await open("host");
    assert.equal(await input.inputValue(), "发送失败保留");
    assert.match(await selected.innerText(), /godot-tech/);

    // A late send response must not clear the newly selected thread's draft.
    holdSend = true;
    await input.press("Enter");
    await page.waitForFunction(() => document.getElementById("send").dataset.pending === "true");
    await open("other"); await choose();
    assert.ok(releaseSend); releaseSend(); await ready(); holdSend = false;
    assert.equal(await input.inputValue(), "另一个会话的草稿");
    assert.match(await selected.innerText(), /godot-tech/);
    await input.press("Enter"); await ready();
    assert.equal(sends.at(-1).id, "other");
    assert.deepEqual(sends.at(-1).skills, [choice]);
    await open("host");
    assert.equal(await input.inputValue(), "");
    assert.equal(await selected.isVisible(), false);

    // Stale skill loading cannot open a menu or attach to a different session.
    await open("race");
    const skillRequest = page.waitForRequest((r) => r.url().includes("/api/skills?id=race"));
    await input.fill("$god"); await skillRequest;
    await open("host");
    assert.ok(releaseSkills); releaseSkills();
    await page.waitForTimeout(200);
    assert.equal(await menu.isVisible(), false);
    assert.equal(await selected.isVisible(), false);
    await open("worker");
    assert.equal(await input.isDisabled(), true);
    assert.equal(await page.locator("#choose-skill").isDisabled(), true);
    await open("host");
    assert.equal(await input.isDisabled(), false);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    console.log(`${width} ${scheme}: text-only, selection/removal, keyboard, failure, session isolation and history passed`);
    await page.close();
  }
} finally { await browser.close(); }
