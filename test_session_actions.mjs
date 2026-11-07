import test from "node:test";
import assert from "node:assert/strict";
import { validatePlan, validateIdentity, historySummary, SessionActions } from "./tools/session_actions.mjs";
import { parseArgs, checkedOutput } from "./tools/session_cli.mjs";

function identity() {
  const cwd = "E:/project/.agent-tmp/task/smoke-test";
  return { url: "http://127.0.0.1:43210", cwd, backendVersion: "test",
    verification: { instance: "a".repeat(32), ownerPid: 1, backendPid: 2, endpoint: "ws://127.0.0.1:43211", codexHome: cwd + "/codex-home", dataDir: cwd + "/state" } };
}
test("full identity is required and each identity component must match", () => {
  const e = identity();
  const state = { side: { runtime: { verification: { ...e.verification }, defaultCwd: e.cwd } }, daemon: { connected: true, version: "test" } };
  assert.equal(validateIdentity(e.url, e, state), e);
  for (const key of Object.keys(e.verification)) {
    const wrong = structuredClone(state); wrong.side.runtime.verification[key] = "other";
    assert.throws(() => validateIdentity(e.url, e, wrong));
    const missing = structuredClone(e); delete missing.verification[key];
    assert.throws(() => validateIdentity(e.url, missing, state));
  }
});
test("live port, remote URLs and disconnected backends are refused", () => {
  for (const url of ["http://127.0.0.1:8764", "http://example.com:43210", "https://127.0.0.1:43210", "http://127.0.0.1:43210/path"]) {
    const e = identity(); e.url = url; assert.throws(() => validateIdentity(url, e));
  }
  const e = identity();
  assert.throws(() => validateIdentity(e.url, e, { side: { runtime: { verification: e.verification, defaultCwd: e.cwd } }, daemon: { connected: false, version: "test" } }));
});
test("plans use local aliases and reject arbitrary IDs, cwd, code and unknown actions", () => {
  for (const plan of [["send"], ["create", "wait"], ["create", "send", "send"], [{ op: "create", threadId: "foreign" }], [{ op: "create", cwd: "E:/" }], [{ op: "create", code: "x" }], ["eval"], ["create", "create"], ["create", { op: "send", message: "/help" }]])
    assert.throws(() => validatePlan(plan));
  assert.equal(validatePlan([{ op: "create", session: "second" }, { op: "open", session: "second" }, { op: "send", session: "second", message: "different" }, { op: "wait", session: "second" }]).length, 4);
});
test("unowned session fails before any page access", () => {
  const object = Object.create(SessionActions.prototype); object.owned = new Map();
  assert.throws(() => object.ownedSession("foreign"));
});
test("unexpected action failure stops later actions and does not retry", async () => {
  const object = Object.create(SessionActions.prototype); object.steps = []; object.step = 0;
  let count = 0; object.create = async () => { count++; throw new Error("backend failure"); };
  await assert.rejects(object.run(["create", "send", "wait"], "hello"), /backend failure/);
  assert.equal(count, 1); assert.equal(object.steps.length, 1); assert.equal(object.steps[0].status, "failed");
});
test("unpaired send is rejected before the CLI can create output or fixture", () => {
  assert.throws(() => parseArgs(["--output", ".agent-tmp/task/not-created", "--actions", "create,send"]), /matching wait/);
  assert.throws(() => validatePlan(["create", "send", "history"]), /matching wait/);
});
test("repeated text is checked separately by both turn ID and item ID", async () => {
  const object = Object.create(SessionActions.prototype), seen = [];
  object.page = { locator(selector) { seen.push(selector); return { waitFor: async () => {}, count: async () => 1, getByText: (text, opts) => { assert.equal(text, "repeat"); assert(opts.exact); return { waitFor: async () => {} }; } }; } };
  await object.historyVisible([{ id: "t1", items: [{ id: "i1", type: "userMessage", text: "repeat" }] }, { id: "t2", items: [{ id: "i2", type: "userMessage", text: "repeat" }] }]);
  assert.deepEqual(seen, ['#turns [data-turn="t1"] [data-item="i1"]', '#turns [data-turn="t2"] [data-item="i2"]']);
});
test("history summary preserves item IDs and detects duplicate turns", () => {
  const turn = { id: "t1", status: "completed", items: [{ id: "i1", type: "userMessage", text: "hello" }] };
  assert.notDeepEqual(historySummary({ turns: [turn] }), historySummary({ turns: [turn, turn] }));
  assert.notDeepEqual(historySummary({ turns: [turn] }), historySummary({ turns: [{ ...turn, items: [{ ...turn.items[0], id: "i2" }] }] }));
});
test("CLI parses different compositions and rejects unknown flags/messages", () => {
  const parsed = parseArgs(["--output", ".agent-tmp/task/new", "--actions", "create,open,history,send,wait,refresh", "--message", "another message"]);
  assert.equal(parsed.actions.length, 6); assert.equal(parsed.message, "another message");
  for (const args of [["--url", "http://127.0.0.1:8764"], ["--output"], ["--output", "x", "--message", "/help"], ["--output", "x", "--plan", "[\"send\"]"]]) assert.throws(() => parseArgs(args));
});
test("CLI output refuses project root, existing files and escaping paths", () => {
  for (const path of [".", ".agent-tmp", "tools/session_cli.mjs", ".agent-tmp/../outside"]) assert.throws(() => checkedOutput(path));
});
test("direct open reloads the target even when another composer stays visible", async () => {
  const object = Object.create(SessionActions.prototype), calls = [];
  object.base = "http://127.0.0.1:12345";
  object.ownedSession = () => ({ id: "alpha" }); object.doctor = async () => {};
  object.beforeNavigation = () => calls.push("guard navigation");
  object.page = { goto: async url => calls.push(url), reload: async () => calls.push("reload"),
    waitForFunction: async (_fn, id) => assert.equal(id, "alpha"),
    locator: () => ({ isVisible: async () => true, waitFor: async () => {} }) };
  object.readHistory = async alias => { assert.equal(alias, "alpha"); calls.push("history"); return {}; };
  await object.open("alpha");
  assert.deepEqual(calls, ["guard navigation", object.base + "/#alpha", "guard navigation", "reload", "history"]);
});
