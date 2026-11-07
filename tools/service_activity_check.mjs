// Synthetic aggregates only. Installed Chrome; no live tasks, credentials or model calls.
import { chromium, executablePath } from "./browser.mjs";
import assert from "node:assert/strict";
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const out = resolve(process.argv[2] || ".agent-tmp/service-activity/ui");
const cache = join(out, "browser-cache");
mkdirSync(cache, { recursive: true });
process.env.TMP = process.env.TEMP = process.env.TMPDIR = cache;
const root = fileURLToPath(new URL("../", import.meta.url));
const assets = { "/": "web/index.html", "/style.css": "web/style.css", "/app.js": "web/app.js",
  "/controllers.js": "web/controllers.js", "/markdown.js": "web/markdown.js", "/paths.js": "web/paths.js",
  "/favicon.ico": "deploy/ma4-icon.ico", "/ma4-icon.svg": "deploy/ma4-icon.svg" };
const types = { html: "text/html", css: "text/css", js: "text/javascript", ico: "image/x-icon", svg: "image/svg+xml" };
const server = createServer((req, res) => {
  const file = assets[new URL(req.url, "http://localhost").pathname];
  if (!file) { res.writeHead(404).end(); return; }
  res.writeHead(200, { "Content-Type": types[file.split(".").at(-1)] });
  res.end(readFileSync(join(root, file)));
});
let base = process.env.MA4_URL;
if (base) {
  const url = new URL(base);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || url.port === "8764")
    throw new Error("Panel previews require an isolated local port, not 8764");
  base = url.origin;
} else {
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}`;
}
let browser;
const checks = [], screenshots = [], problems = [];
const deferred = process.env.MA4_PANEL_DEFERRED === "1"; // Explicit regression fixture; never the default panel.
try {
  browser = await chromium.launch({ executablePath, headless: true });
  const layouts = [1440, 1024, 390].flatMap(width => ["light", "dark"].map(scheme => [width, width === 1440 ? 1100 : 900, scheme]))
    .filter(([width, , scheme]) => !process.env.MA4_PANEL_LAYOUT || process.env.MA4_PANEL_LAYOUT === `${width}-${scheme}`);
  assert(layouts.length, "Unknown MA4_PANEL_LAYOUT");
  for (const [width, height, scheme] of layouts) {
    const page = await browser.newPage({ viewport: { width, height }, colorScheme: scheme, reducedMotion: "reduce", timezoneId: "Asia/Shanghai" });
    const errors = [], requests = [], now = Date.now() / 1000;
    let controllers = { tasks: [{ id: "date-task", name: "面板与会话日期 · 模拟", cwd: "/example/MA4", host: "date-host",
      hostBusy: true, status: "running", updatedAt: now, target: "隔离模拟数据，不触及用户任务。", budget: {},
      formerHosts: ["date-former"], workers: { "date-worker": { name: "模拟执行者", state: "idle", access: "read", cwd: "/example/MA4" } },
      statistics: { roles: [], sessions: [{ threadId: "date-host", name: "模拟中控", turns: [{ id: "mock-turn", startedAt: now - 180 }] },
        { threadId: "date-worker", name: "模拟执行者", updatedAt: now - 3600, turns: [] }, { threadId: "date-former", name: "前任中控", turns: [] }].map(row => ({ ...row, usage: { totalTokens: 0 } })) },
    }] };
    let threads = [{ id: "date-host", name: "模拟中控", cwd: "/example/MA4", status: "running", updatedAt: now - 86400,
      sandbox: "dangerFullAccess", approval: "never" },
      { id: "date-normal", name: "普通会话 · 模拟", cwd: "/example/normal", status: "idle", updatedAt: now - 7200 },
      { id: "date-unknown", name: "缺少时间 · 模拟", cwd: "/example/normal", status: "offline", updatedAt: null }];
    const makeSide = () => ({
      quota: { families: [{ label: "Codex · 模拟额度", windows: [{ label: "5 小时", used: 24, reset_at: now + 3600 }] }] },
      links: [{ name: "muQ", url: "https://muq.koa-ol.com" }],
      health: [{ name: "OVH VPS", type: "tcp", host: "51.79.241.161", port: 22, ok: true, ms: 152, at: now },
        { name: "muQ 首页", type: "http", url: "https://muq.koa-ol.com", ok: true, ms: 110, code: 200, at: now },
        { name: "21点联机服务", url: "https://koa-ol.com/ace21-api/health", ok: true, ms: 156, code: 200, at: now }].filter(row => deferred || row.type !== "tcp"),
      activity: [
        { key: "texas", label: "德州扑克", metric: "在线玩家", count: 3 },
        { key: "ace21", label: "王牌21点", metric: "在线玩家", count: 0 },
        { key: "xiangqi", label: "中象大厅", metric: "在线玩家", count: 2 },
        { key: "xiangqi-assist", label: "中象辅助", metric: "近 5 分钟活跃浏览器", count: 8, complete_window: true },
        { key: "chat", label: "Chat / 代理", metric: "近 5 分钟活跃 IP", count: 2,
          visitors: [{ ip: "192.0.2.1", city: "Hangzhou", region: "Zhejiang", country: "CN", last_seen: now - 30, requests: 4 },
            { ip: "2001:db8:1234:5678:1234:5678:1234:5678", city: "", country: "<img src=x onerror=alert(1)>", last_seen: now - 60, requests: 1 }] },
      ].filter(row => deferred || row.key !== "xiangqi").map(row => ({ ...row, stale: false, status: "ok", fetched_at: now })),
    });
    let side = makeSide();
    side.health = side.health.map(({ at, ok, ms, ...row }) => row);
    side.activity = side.activity.map(row => ({ ...row, fetched_at: undefined, count: null, status: "pending", stale: true }));
    await page.addInitScript(() => {
      window.EventSource = class { constructor() { window.fixtureEvents = this; } addEventListener() {} };
      const original = window.setInterval;
      window.setInterval = (fn, ms, ...args) => ms === 15000 ? (window.refreshActivity = fn, 123) : original(fn, ms, ...args);
    });
    page.on("pageerror", e => errors.push(e.message));
    page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
    page.on("response", r => { if (r.status() >= 400) errors.push(`HTTP ${r.status()}: ${r.url()}`); });
    await page.route("**/*", async route => {
      const url = new URL(route.request().url());
      if (url.origin !== base) { errors.push(`Unexpected remote request: ${url.origin}`); return route.abort(); }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      requests.push({ path: url.pathname, method: route.request().method() });
      let result;
      if (url.pathname === "/api/state") result = { threads, approvals: [], controllers, daemon: { connected: true }, side, seq: 0 };
      else if (url.pathname === "/api/side") result = side;
      else if (url.pathname === "/api/open") result = { thread: threads.find(row => row.id === "date-host") };
      else if (url.pathname === "/api/history") result = { turns: [], older: null };
      else { errors.push("Unexpected API: " + url.pathname); result = {}; }
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(result) });
    });
    await page.goto(base);
    await page.locator("#activity-card").waitFor({ state: "visible" });
    const assist = page.locator('[data-service="xiangqi-assist"]'), xiangqi = page.locator('[data-service="xiangqi"]');
    assert.match(await assist.innerText(), /未知[\s\S]*查询中/);
    if (deferred) assert.match(await page.locator(".health-tcp").innerText(), /检查中[\s\S]*尚无记录/);
    if (width === 390 && scheme === "dark") {
      await page.locator("#activity-card").screenshot({ path: join(out, "390-dark-pending.png") });
      if (deferred) await page.locator(".health-tcp").screenshot({ path: join(out, "390-dark-tcp-pending.png") });
    }
    const refresh = async () => {
      await page.evaluate(() => window.refreshActivity());
      // The interval callback returns the API/render promise; evaluate awaits it.
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      assert.equal(await page.locator(".side").evaluate(el => el.scrollWidth > el.clientWidth), false);
    };
    const capture = async (name, locator = page) => {
      const file = `${width}-${scheme}-${name}.png`;
      await locator.screenshot({ path: join(out, file), ...(locator === page ? { fullPage: true } : {}) });
      screenshots.push(file);
    };
    side = makeSide();
    await refresh();
    assert.deepEqual(await page.locator(".activity-value").allTextContents(), deferred ? ["3", "0", "2", "8", "2›"] : ["3", "0", "8", "2›"]);
    assert.equal(await page.locator("#service-activity button").count(), 1);
    assert.equal(await page.locator(".health-tcp a").count(), 0);
    assert.equal(await page.locator("#health a").count(), 2);
    if (deferred) assert.match(await page.locator(".health-tcp").innerText(), /可达[\s\S]*TCP 连接耗时：152 ms[\s\S]*最近检查/);
    else {
      assert.equal(await page.locator(".health-tcp").count(), 0);
      assert.equal(await xiangqi.count(), 0);
    }
    assert.match(await assist.innerText(), /浏览器标识[\s\S]*非精准人数/);
    assert(requests.every(r => r.method === "GET" && ["/api/state", "/api/side"].includes(r.path)));
    assert.equal(requests.filter(r => r.path === "/api/side").length, 1);
    // Session time is own turn evidence, never the task edit time or another worker.
    const host = page.locator('#thread-list [data-id="date-host"]');
    const worker = page.locator('#thread-list [data-id="date-worker"]');
    await page.locator('[data-task-expand="date-task"]').focus();
    await page.keyboard.press("Enter");
    assert.equal(await host.locator(".thread-time").innerText(), "3 分钟前");
    assert.equal(await worker.locator(".thread-time").innerText(), "1 小时前");
    assert.match(await host.locator(".thread-time").getAttribute("title"), /最近活动：\d{4}\/\d{1,2}\/\d{1,2}/);
    await page.locator(".former-hosts summary").click();
    assert.equal(await page.locator('#thread-list [data-id="date-former"] .thread-time').innerText(), "时间未知");
    await host.focus();
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => location.hash === "#date-host");
    assert.match(await page.locator("#chat-meta").innerText(), /完全访问 · 从不审批/);
    assert.equal(await host.evaluate(el => el.classList.contains("selected")), true);
    // Ordinary sessions keep their own date and an explicit unknown label.
    await page.locator('[data-sidebar-view="sessions"]').click();
    assert.equal(await page.locator('#thread-list [data-id="date-normal"] .thread-time').innerText(), "2 小时前");
    assert.equal(await page.locator('#thread-list [data-id="date-unknown"] .thread-time').innerText(), "时间未知");
    await page.locator('[data-sidebar-view="tasks"]').click();
    await host.focus();
    threads[0] = { ...threads[0], updatedAt: now - 60 };
    await page.evaluate(rows => window.fixtureEvents.onmessage({ data: JSON.stringify({ kind: "threads", threads: rows }) }), threads);
    assert.equal(await host.evaluate(el => document.activeElement === el), true);
    assert.equal(await host.locator(".thread-time").innerText(), "1 分钟前");
    threads[0].updatedAt = now - 86400;
    controllers.tasks[0].statistics.sessions[0].turns[0].startedAt = now - 86400;
    await page.evaluate(rows => window.fixtureEvents.onmessage({ data: JSON.stringify({ kind: "threads", threads: rows }) }), threads);
    await page.evaluate(() => { window.fixtureEvents.onerror(); window.fixtureEvents.onopen(); });
    await page.waitForFunction(() => document.getElementById("daemon").textContent === "守护进程已连接");
    assert.equal(await host.locator(".thread-time").innerText(), "1 分钟前");
    await page.locator("#activity-card").scrollIntoViewIfNeeded();
    await capture("normal"); // same current evidence filename, before any failure scenarios
    await page.locator("#health a").first().focus();
    await page.keyboard.press("Tab");
    assert.equal(await page.locator("#health a").nth(1).evaluate(el => el === document.activeElement), true);
    await page.locator("[data-activity='chat']").focus();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Shift+Tab");
    assert.equal(await page.locator("[data-activity='chat']").evaluate(el => getComputedStyle(el).outlineStyle), "solid");
    await refresh();
    assert.equal(await page.locator("[data-activity='chat']").evaluate(el => el === document.activeElement), true);
    await page.keyboard.press("Enter");
    assert.equal(await page.locator("#activity-dialog").isVisible(), true);
    assert.match(await page.locator("#activity-visitors").innerText(), /城市未记录/);
    assert.equal(await page.locator("#activity-visitors img").count(), 0);
    assert.equal(await page.locator("#activity-visitors").evaluate(el => el.scrollWidth > el.clientWidth), false);
    const row = key => side.activity.find(value => value.key === key);
    Object.assign(row("chat"), { count: 0, visitors: [], fetched_at: now + 15 });
    await refresh();
    assert.match(await page.locator("#activity-visitors").innerText(), /没有调用记录/);
    await page.keyboard.press("Escape");
    row("xiangqi-assist").count = 0;
    if (deferred) row("xiangqi").count = 0;
    await refresh();
    assert.equal(await assist.locator(".activity-value").innerText(), "0");
    if (deferred) assert.equal(await xiangqi.locator(".activity-value").innerText(), "0");
    Object.assign(row("xiangqi-assist"), { count: 4, status: "collecting", complete_window: false });
    await refresh();
    assert.match(await assist.innerText(), /积累中[\s\S]*不足 5 分钟/);
    if (width === 390) await capture("collecting", page.locator("#activity-card"));
    for (const reason of ["查询失败，暂无法确认", "数据非法或缺失，暂无法确认", "查询超时，暂无法确认", ""]) {
      Object.assign(row("xiangqi-assist"), { count: null, status: "unknown", stale: true, error: reason });
      await refresh();
      assert.equal(await assist.locator(".activity-value").innerText(), "未知");
      assert.match(await assist.innerText(), reason ? /暂无法确认/ : /数据已过期/);
    }
    if (deferred) {
    side.health[0] = { ...side.health[0], ok: false, ms: null, error: "TCP 连接失败或超时" };
    await refresh();
    assert.match(await page.locator(".health-tcp").innerText(), /不可达[\s\S]*耗时：未知/);
    side.health[0].stale = true;
    await refresh();
    assert.match(await page.locator(".health-tcp").innerText(), /未知 · 数据已过期/);
    }
    if (width === 390) await capture("expired", page.locator("#activity-card"));
    if (deferred && width === 390 && scheme === "dark") await capture("tcp-expired", page.locator(".health-tcp"));
    side.activity = side.activity.map(row => ({ ...row, count: null, stale: true, status: "unknown", error: "查询失败，暂无法确认" }));
    await refresh();
    assert.equal(await page.locator("[data-activity='chat']").isDisabled(), true);
    assert.deepEqual(await page.locator(".activity-value").allTextContents(), deferred ? ["未知", "未知", "未知", "未知", "未知›"] : ["未知", "未知", "未知", "未知›"]);
    if (width === 390 && scheme === "dark") await capture("failure", page.locator("#activity-card"));
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.equal(await page.locator(".side").evaluate(el => el.scrollWidth > el.clientWidth), false);
    await page.evaluate(() => window.fixtureEvents.onerror());
    assert.match(await page.locator("#daemon").innerText(), /未连接/);
    await page.evaluate(() => window.fixtureEvents.onopen());
    await page.waitForFunction(() => document.getElementById("daemon").textContent === "守护进程已连接");
    assert.deepEqual(errors, []);
    side = makeSide();
    await refresh();
    assert.equal(await assist.locator(".activity-value").innerText(), "8");
    checks.push({ width, scheme, deferred, sessionDates: "own activity, stale list, reconnect, unknown, former host, ordinary, keyboard",
      states: ["pending", "normal", "zero", "collecting", "failure", "bad-data", "timeout", "expired", "recovered"],
      keyboard: true, overflow: false, resourceErrors: 0, scriptErrors: 0, remoteRequests: 0 });
    console.log(`${width}px ${scheme}: 9 activity states, session dates, defaults, quota/health, keyboard, Chat, reconnect and resources passed`);
    await page.close();
  }
} catch (error) {
  problems.push(String(error.stack || error));
  process.exitCode = 1;
} finally {
  await browser?.close();
  if (server.listening) await new Promise(resolve => server.close(resolve));
  const report = process.env.MA4_PANEL_LAYOUT ? `report-${process.env.MA4_PANEL_LAYOUT}.json` : "report.json";
  writeFileSync(join(out, report), JSON.stringify({ result: problems.length ? "failed" : "passed", base, executablePath, checks, screenshots, problems }, null, 2) + "\n");
}
if (problems.length) console.error(problems.join("\n"));
