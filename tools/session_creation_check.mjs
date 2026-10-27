import { chromium, executablePath } from "./browser.mjs";
// Exercise the real page with delayed/omitted thread metadata. All API calls
// are intercepted: no real threads, messages, model calls or state writes.
import assert from "node:assert/strict";
import { readdirSync, existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";


const browser = await chromium.launch({ executablePath, headless: true });
try {
  for (const width of [1440, 1024, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 }, reducedMotion: "reduce" });
    const errors = [], calls = [];
    const fresh = { id: "fresh-empty-thread", cwd: width === 1024 ? "C:/Users/测试 用户/codex" : "/home/dticpw/codex", status: "idle", name: "", updatedAt: 1 };
    const runtime = { home: fresh.cwd.slice(0, -6), defaultCwd: fresh.cwd };
    const fixture = { threads: [], approvals: [], daemon: { connected: true }, side: { runtime }, seq: 0,
      controllers: { tasks: [], recovering: false } };
    let releaseOpen;
    const openReady = new Promise((resolve) => { releaseOpen = resolve; });
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
    await page.addInitScript(() => {
      window.EventSource = class { constructor() { window.fixtureEvents = this; } addEventListener() {} };
    });
    const publish = (threads) => page.evaluate((threads) => {
      window.fixtureEvents.onmessage({ data: JSON.stringify({ kind: "threads", threads }) });
    }, threads);
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      const body = route.request().postDataJSON();
      calls.push({ path, body });
      let result;
      if (path === "/api/state") result = fixture; // empty new thread omitted
      else if (path === "/api/side") result = { runtime };
      else if (path === "/api/new") result = { threadId: fresh.id };
      else if (path === "/api/history") result = { turns: [], older: null };
      else if (path === "/api/open") {
        await openReady;
        result = { thread: fresh, turn: null, tokens: null, override: null };
      } else if (path === "/api/rename" || path === "/api/command") {
        fresh.name = body.name === "rename" ? body.arg : body.name;
        result = { renamed: true };
      } else if (path === "/api/send") result = { turnId: "fixture-turn" };
      else { errors.push("Unexpected API request: " + path); result = {}; }
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(result) });
    });
    const submit = async (text) => {
      await page.locator("#input").fill(text);
      await page.locator("#composer").evaluate((form) => form.requestSubmit());
    };
    await page.goto(process.env.MA4_URL || "http://127.0.0.1:8764");
    await page.waitForFunction(() => window.fixtureEvents);
    await page.locator("#new-thread").click();
    assert.equal(await page.locator("#new-cwd").inputValue(), fresh.cwd);
    await page.locator("#new-submit").click();
    await page.waitForFunction(() => location.hash === "#fresh-empty-thread");
    // A command before /open resolves must give a useful error and retain input.
    await submit("/rename ");
    await page.waitForFunction(() => document.getElementById("toast").textContent.includes("尚未载入"));
    assert.equal(await page.locator("#input").inputValue(), "/rename ");
    assert.equal(calls.some((c) => c.path === "/api/command"), false);
    releaseOpen();
    await page.waitForFunction(() => document.getElementById("turns").textContent.includes("还没有对话"));
    // Repeated list events may arrive before the created thread enters the list.
    for (let i = 0; i < 3; i++) await publish([]);
    assert.equal(await page.locator("#rename").innerText(), "fresh-em");
    await submit("/status ");
    await page.waitForFunction((cwd) => document.querySelector(".note")?.textContent.includes(cwd), fresh.cwd);
    // Bare /rename opens the same name dialog as clicking the title.
    page.once("dialog", (dialog) => dialog.accept("空白会话改名"));
    await submit("/rename ");
    await page.waitForFunction(() => document.getElementById("input").value === "");
    assert.deepEqual(calls.find((c) => c.path === "/api/rename").body,
      { id: fresh.id, name: "空白会话改名" });
    await publish([fresh]);
    await publish([]);
    assert.equal(await page.locator("#rename").innerText(), "空白会话改名");
    await submit("/rename 带参数改名");
    await page.waitForFunction(() => document.getElementById("input").value === "");
    assert.deepEqual(calls.find((c) => c.path === "/api/command").body,
      { id: fresh.id, name: "rename", arg: "带参数改名" });
    await submit("第一条消息");
    await page.waitForFunction(() => document.getElementById("input").value === "");
    const sent = calls.filter((c) => c.path === "/api/send");
    assert.equal(sent.length, 1);
    assert.equal(sent[0].body.id, fresh.id);
    assert.equal(sent[0].body.text, "第一条消息");
    assert.ok(sent[0].body.request_id);
    // Catch-up after a deferred subscription reloads history without losing a draft.
    await page.locator("#input").fill("尚未发送的草稿");
    await page.evaluate(() => window.fixtureEvents.onmessage({ data: JSON.stringify({
      kind: "history", threadId: "fresh-empty-thread",
    }) }));
    await page.waitForFunction(() => document.getElementById("turns").textContent.includes("还没有对话"));
    assert.equal(calls.filter((c) => c.path === "/api/open").length, 2);
    assert.equal(await page.locator("#input").inputValue(), "尚未发送的草稿");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    await page.close();
    console.log(`${width}px: create, delayed metadata, refresh, rename, status and send passed`);
  }
} finally { await browser.close(); }
