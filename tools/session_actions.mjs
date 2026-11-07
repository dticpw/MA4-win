// Finite browser actions for an owned, disposable MA4 fixture. No business logic.
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export const MOCK_REPLY = "本机模拟回复：Windows 共享会话连接成功。";
export const DEFAULT_ACTIONS = ["fail-create", "create", "send", "wait", "reopen", "refresh", "history"];
const OPS = new Set([...DEFAULT_ACTIONS, "open"]);

export function validatePlan(plan) {
  assert(Array.isArray(plan) && plan.length > 0 && plan.length <= 40, "plan must contain 1..40 actions");
  const known = new Set(), active = new Set();
  const actions = plan.map(raw => {
    const action = typeof raw === "string" ? { op: raw } : raw;
    assert(action && OPS.has(action.op), "unknown action");
    assert(Object.keys(action).every(k => ["op", "session", "message"].includes(k)), "unsupported action field (thread IDs/cwd/code are not accepted)");
    const session = action.session ?? "main";
    assert(/^[a-z][a-z0-9_-]{0,31}$/.test(session), "invalid session alias");
    assert(action.message === undefined || (action.op === "send" && typeof action.message === "string" && action.message.trim() && !action.message.startsWith("/") && action.message.length <= 10000), "invalid message");
    if (action.op === "create") {
      assert(!known.has(session), "duplicate session alias");
      known.add(session);
    } else if (action.op !== "fail-create") assert(known.has(session), "action requires a session created by this plan");
    if (action.op === "send") { assert(!active.has(session), "wait for completion before another send"); active.add(session); }
    if (action.op === "wait") { assert(active.has(session), "wait requires an explicit send"); active.delete(session); }
    return { ...action, session };
  });
  assert.equal(active.size, 0, "every send requires a matching wait before plan end; no automatic wait is added");
  return actions;
}

export function validateIdentity(base, expected, state) {
  const url = new URL(base);
  assert(url.protocol === "http:" && url.hostname === "127.0.0.1" && url.port && url.port !== "8764" && url.pathname === "/" && !url.search && !url.hash && !url.username && !url.password, "only random local fixture ports are allowed; 8764 is forbidden");
  assert.equal(base, expected?.url, "unexpected verification URL");
  const v = expected?.verification;
  assert(v && /^[a-f0-9]{32}$/.test(v.instance) && Number.isInteger(v.ownerPid) && v.ownerPid > 0 && Number.isInteger(v.backendPid) && v.backendPid > 0, "complete fixture identity required");
  assert(typeof expected.cwd === "string" && expected.cwd.replaceAll("\\", "/").includes("/.agent-tmp/"), "isolated fixture workspace required");
  const norm = p => p?.replaceAll("\\", "/");
  assert.equal(norm(v.codexHome), norm(expected.cwd) + "/codex-home");
  assert.equal(norm(v.dataDir), norm(expected.cwd) + "/state");
  const endpoint = new URL(v.endpoint);
  assert(endpoint.protocol === "ws:" && endpoint.hostname === "127.0.0.1" && endpoint.port && endpoint.port !== "8764", "invalid backend endpoint");
  assert(expected.backendVersion, "backend version required");
  if (state) {
    assert.deepEqual(state.side?.runtime?.verification, v, "instance identity mismatch");
    assert.equal(state.side.runtime.defaultCwd, expected.cwd, "workspace changed");
    assert.equal(state.daemon?.connected, true, "backend disconnected");
    assert.equal(state.daemon.version, expected.backendVersion, "backend version changed");
  }
  return expected;
}

export function historySummary(history) {
  assert(Array.isArray(history.turns), "history turns missing");
  return history.turns.map(t => ({ id: t.id, status: t.status,
    items: t.items.map(i => ({ id: i.id, type: i.type, text: i.text })) }));
}

export class SessionActions {
  constructor(page, { base, identity, out }) {
    validateIdentity(base, identity);
    this.page = page; this.base = base; this.identity = identity; this.out = out;
    this.owned = new Map(); this.steps = []; this.diagnostics = []; this.requests = [];
    this.expectedFailure = null; this.pending = []; this.step = 0;
    this.eventRequests = new Set(); this.navigationAborts = new WeakSet();
    mkdirSync(out, { recursive: true });
    page.on("pageerror", error => this.diagnostics.push({ kind: "pageerror", step: this.step, text: error.message, expected: false }));
    page.on("console", message => {
      if (message.type() !== "error") return;
      // Chrome's generic resource error is expected only for the exact failed POST URL.
      const loc = message.location();
      const expected = !!this.expectedFailure && loc.url === base + "/api/new" && /400/.test(message.text());
      this.diagnostics.push({ kind: "console", step: this.step, text: message.text(), location: loc, expected });
    });
    page.on("requestfailed", req => {
      const text = req.failure()?.errorText;
      const expected = this.navigationAborts.has(req) && text === "net::ERR_ABORTED";
      this.diagnostics.push({ kind: "requestfailed", step: this.step, url: req.url(), method: req.method(), text, expected, reason: expected ? "own navigation closed prior SSE" : undefined });
      this.eventRequests.delete(req);
    });
    page.on("requestfinished", req => this.eventRequests.delete(req));
    page.on("response", response => {
      const req = response.request();
      if (!response.url().startsWith(base + "/api/")) return;
      const item = { step: this.step, url: response.url(), method: req.method(), status: response.status() };
      if (req.method() === "POST") this.requests.push(item);
      if (response.status() >= 400) {
        const expected = this.expectedFailure?.request === req && response.status() === 400;
        const entry = { ...item, kind: "http", expected };
        this.diagnostics.push(entry);
        this.pending.push(response.text().then(body => { entry.body = body; }));
      }
    });
    page.on("request", req => {
      if (req.method() === "GET" && req.url().startsWith(base + "/api/events?")) this.eventRequests.add(req);
      if (this.expectedFailure && !this.expectedFailure.request && req.method() === "POST" && req.url() === base + "/api/new" && req.postDataJSON()?.cwd === this.expectedFailure.cwd)
        this.expectedFailure.request = req;
    });
  }
  async doctor() {
    validateIdentity(this.base, this.identity);
    const response = await this.page.request.get(this.base + "/api/state", { timeout: 5000 });
    assert(response.ok(), "fixture state unavailable");
    const state = await response.json();
    validateIdentity(this.base, this.identity, state);
    for (const owned of this.owned.values()) {
      const thread = state.threads.find(t => t.id === owned.id);
      assert(thread && thread.cwd === this.identity.cwd, "owned session missing or workspace mismatch");
    }
    return state;
  }
  ownedSession(alias) { const s = this.owned.get(alias); assert(s, "session not created by this action runner"); return s; }
  async screenshot(name) {
    const file = String(this.step).padStart(2, "0") + "-" + name + ".png";
    await this.page.screenshot({ path: join(this.out, file), fullPage: true }); return file;
  }
  beforeNavigation() { for (const request of this.eventRequests) this.navigationAborts.add(request); }
  async start() {
    await this.doctor();
    await this.page.goto(this.base);
    await this.page.locator("#new-thread").waitFor();
  }
  async create(alias, fail = false) {
    assert(fail || !this.owned.has(alias), "session already owned");
    const before = await this.doctor();
    const previousExpectedErrors = this.diagnostics.filter(d => d.kind === "http" && d.expected).length;
    const cwd = fail ? this.identity.cwd + "/nonexistent-" + this.identity.verification.instance : this.identity.cwd;
    await this.page.locator("#new-thread").click();
    await this.page.locator("#new-cwd").fill(cwd);
    await this.page.locator("#new-text").fill("");
    await this.doctor();
    if (fail) this.expectedFailure = { cwd };
    const responsePromise = this.page.waitForResponse(r => r.url() === this.base + "/api/new" && r.request().method() === "POST");
    await this.page.locator("#new-submit").click();
    const response = await responsePromise;
    const body = await response.json();
    if (fail) {
      assert.equal(response.status(), 400, "nonexistent cwd must really fail");
      assert.match(body.error, /工作目录不存在/);
      await this.page.locator("#new-error").filter({ hasText: body.error }).waitFor();
      assert(await this.page.locator("#new-dialog").isVisible());
      const screenshot = await this.screenshot("controlled-failure");
      assert.deepEqual((await this.doctor()).threads.map(t => t.id).sort(), before.threads.map(t => t.id).sort(), "failed create must not create a session");
      await Promise.all(this.pending);
      const expected = this.diagnostics.filter(d => d.kind === "http" && d.expected);
      assert.equal(expected.length, previousExpectedErrors + 1, "exactly one expected HTTP error per failed create");
      this.expectedFailure = null;
      await this.page.keyboard.press("Escape");
      return { status: 400, error: body.error, screenshot, injection: false, retry: false };
    }
    assert(response.ok(), JSON.stringify(body));
    assert(body.threadId && !before.threads.some(t => t.id === body.threadId), "new session identity required");
    this.owned.set(alias, { id: body.threadId, sends: [], baseline: null });
    await this.page.waitForFunction(id => location.hash === "#" + id, body.threadId);
    await this.page.locator("#input").waitFor();
    await this.doctor();
    return { threadId: body.threadId };
  }
  async open(alias, list = false) {
    const session = this.ownedSession(alias); await this.doctor();
    if (list) {
      await this.page.locator("#home").click();
      await this.page.locator(`#thread-list [data-id="${session.id}"]`).click();
    } else {
      this.beforeNavigation(); await this.page.goto(this.base + "/#" + session.id);
      // A hash-only goto can keep another session's visible composer. Always
      // load the target document; visibility is not evidence of session identity.
      this.beforeNavigation(); await this.page.reload();
    }
    await this.page.waitForFunction(id => location.hash === "#" + id, session.id);
    await this.page.locator("#input").waitFor();
    return this.readHistory(alias, true);
  }
  async send(alias, message) {
    const session = this.ownedSession(alias);
    assert.equal(await this.page.evaluate(() => location.hash), "#" + session.id, "open the owned session before sending");
    assert(message?.trim() && !message.startsWith("/"), "non-command message required");
    await this.page.locator("#input").fill(message);
    const screenshot = await this.screenshot("before-send-" + (session.sends.length + 1));
    await this.doctor();
    const responsePromise = this.page.waitForResponse(r => r.url() === this.base + "/api/send" && r.request().method() === "POST");
    await this.page.locator("#send").click();
    const response = await responsePromise; const result = await response.json();
    assert(response.ok(), JSON.stringify(result));
    assert.equal(result.mode, "start", "send must start a new idle turn");
    assert(result.turnId, "turn ID required");
    session.sends.push({ message, turnId: result.turnId, requestId: response.request().postDataJSON().request_id });
    return { ...session.sends.at(-1), screenshot };
  }
  async wait(alias) {
    const session = this.ownedSession(alias); assert(session.sends.length, "nothing sent");
    const turnId = session.sends.at(-1).turnId;
    const deadline = Date.now() + 30000;
    let history;
    while (Date.now() < deadline) {
      history = await this.readHistory(alias, false);
      const turn = history.summary.find(t => t.id === turnId);
      assert(!["failed", "interrupted"].includes(turn?.status), "turn did not complete successfully");
      if (turn?.status === "completed") break;
      await this.page.waitForTimeout(100);
    }
    assert.equal(history.summary.find(t => t.id === turnId)?.status, "completed", "completion timeout; not resent");
    assert.equal(history.summary.length, session.sends.length, "one persisted turn per explicit send");
    for (const sent of session.sends) {
      const t = history.summary.find(t => t.id === sent.turnId);
      assert(t.items.some(i => i.type === "userMessage" && i.text === sent.message));
      assert(t.items.some(i => i.type === "agentMessage" && i.text === MOCK_REPLY));
    }
    await this.historyVisible(history.summary);
    session.baseline = history.summary;
    return { ...history, screenshot: await this.screenshot("reply") };
  }
  async historyVisible(summary) {
    for (const turn of summary) for (const item of turn.items) {
      if (!["userMessage", "agentMessage"].includes(item.type)) continue;
      assert(turn.id && item.id, "persisted turn and message IDs required for UI matching");
      const scope = this.page.locator(`#turns [data-turn=${JSON.stringify(turn.id)}] [data-item=${JSON.stringify(item.id)}]`);
      await scope.waitFor();
      assert.equal(await scope.count(), 1, "one UI element per persisted message ID");
      await scope.getByText(item.text, { exact: true }).waitFor();
    }
  }
  async readHistory(alias, compare = true) {
    const session = this.ownedSession(alias); await this.doctor();
    const response = await this.page.request.get(this.base + "/api/history?id=" + encodeURIComponent(session.id));
    assert(response.ok(), "history request failed");
    const history = await response.json(); const summary = historySummary(history);
    if (compare && session.baseline) {
      assert.deepEqual(summary, session.baseline, "history IDs/count/content changed without a send");
      await this.historyVisible(summary);
    }
    writeFileSync(join(this.out, "history-" + alias + ".json"), JSON.stringify(history, null, 2) + "\n");
    return { threadId: session.id, turnCount: summary.length, itemCount: summary.reduce((n,t) => n + t.items.length, 0), summary };
  }
  async refresh(alias) {
    const session = this.ownedSession(alias); await this.doctor();
    assert.equal(await this.page.evaluate(() => location.hash), "#" + session.id);
    this.beforeNavigation(); await this.page.reload(); await this.page.locator("#input").waitFor();
    return { ...await this.readHistory(alias), screenshot: await this.screenshot("refreshed") };
  }
  async run(plan, message) {
    const actions = validatePlan(plan);
    for (const action of actions) {
      const step = { index: ++this.step, action, startedAt: new Date().toISOString() }; this.steps.push(step);
      try {
        const s = action.session;
        switch (action.op) {
          case "fail-create": step.result = await this.create(s, true); break;
          case "create": step.result = await this.create(s); break;
          case "open": step.result = await this.open(s); break;
          case "send": step.result = await this.send(s, action.message ?? message); break;
          case "wait": step.result = await this.wait(s); break;
          case "reopen": step.result = { ...await this.open(s, true), screenshot: await this.screenshot("reopened") }; break;
          case "refresh": step.result = await this.refresh(s); break;
          case "history": step.result = await this.readHistory(s); break;
        }
        step.status = "passed";
      } catch (error) { step.status = "failed"; step.error = error.message; throw error; }
    }
    await Promise.all(this.pending);
    assert.equal(this.diagnostics.filter(d => !d.expected).length, 0, "unexpected browser/network errors (see diagnostics)");
    return this.steps;
  }
}
