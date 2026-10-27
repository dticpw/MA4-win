import { chromium, executablePath } from "./browser.mjs";
// Uses synthetic activity and intercepted APIs; never joins a table or calls a model.
import assert from "node:assert/strict";
import { readdirSync, existsSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";


const out = resolve(process.argv[2] || ".agent-tmp/service-activity/ui");
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath, headless: true });
try {
  for (const [width, height, scheme] of [[1440, 1000, "light"], [1024, 900, "dark"], [390, 844, "light"]]) {
    const page = await browser.newPage({ viewport: { width, height }, colorScheme: scheme, reducedMotion: "reduce" });
    const errors = [], now = Date.now() / 1000;
    let activity = [
      { key: "texas", label: "德州扑克", metric: "在线玩家", count: 3, stale: false, fetched_at: now },
      { key: "ace21", label: "王牌21点", metric: "在线玩家", count: 0, stale: false, fetched_at: now },
      { key: "chat", label: "Chat / 代理", metric: "近 5 分钟活跃 IP", count: 2, stale: false, fetched_at: now,
        visitors: [{ ip: "192.0.2.1", city: "Hangzhou", region: "Zhejiang", country: "CN", last_seen: now - 30, requests: 4 },
          { ip: "2001:db8:1234:5678:1234:5678:1234:5678", city: "", country: "<img src=x onerror=alert(1)>", last_seen: now - 60, requests: 1 }] },
    ];
    await page.addInitScript(() => {
      window.EventSource = class { addEventListener() {} };
      const original = window.setInterval;
      window.setInterval = (fn, ms, ...args) => ms === 15000 ? (window.refreshActivity = fn, 123) : original(fn, ms, ...args);
    });
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      let result;
      if (path === "/api/state") result = { threads: [], approvals: [], controllers: { tasks: [] }, daemon: { connected: true }, side: { activity }, seq: 0 };
      else if (path === "/api/side") result = { activity };
      else { errors.push("Unexpected API: " + path); result = {}; }
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(result) });
    });
    await page.goto(process.env.MA4_URL || "http://127.0.0.1:8764");
    await page.locator("#activity-card").waitFor({ state: "visible" });
    assert.equal(await page.locator("#service-activity button").count(), 1, "Games must not expose details");
    assert.deepEqual(await page.locator(".activity-value").allTextContents(), ["3", "0", "2›"]);
    await page.locator("#activity-card").scrollIntoViewIfNeeded();
    await page.screenshot({ path: join(out, `card-${width}.png`) });
    await page.locator("[data-activity='chat']").focus();
    await page.keyboard.press("Enter");
    assert.equal(await page.locator("#activity-dialog").isVisible(), true);
    assert.match(await page.locator("#activity-visitors").innerText(), /城市未记录/);
    assert.equal(await page.locator("#activity-visitors img").count(), 0);
    assert.equal(await page.locator("#activity-visitors").evaluate((el) => el.scrollWidth > el.clientWidth), false);
    await page.screenshot({ path: join(out, `details-${width}.png`) });
    activity[2] = { ...activity[2], count: 0, visitors: [], fetched_at: now + 15 };
    await page.evaluate(() => window.refreshActivity());
    await page.waitForFunction(() => document.getElementById("activity-visitors").textContent.includes("没有调用记录"));
    assert.equal(await page.locator("#activity-dialog").isVisible(), true);
    activity = activity.map((row) => ({ ...row, count: null, stale: true, error: "查询失败，暂无法确认" }));
    await page.evaluate(() => window.refreshActivity());
    await page.waitForFunction(() => document.querySelector("[data-activity='chat']").disabled);
    assert.equal(await page.locator("#activity-visitors").innerText(), "");
    assert.match(await page.locator("#activity-detail-status").innerText(), /暂无法确认/);
    await page.keyboard.press("Escape");
    assert.deepEqual(await page.locator(".activity-value").allTextContents(), ["—", "—", "—›"]);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    await page.close();
    console.log(`${width}px ${scheme}: counts, keyboard details, location fallback, escaping, live refresh and failure states passed`);
  }
} finally { await browser.close(); }
