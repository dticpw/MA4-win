import { test } from "node:test";
import assert from "node:assert/strict";
import { dynamicToolHtml, statisticsHtml, ordinarySessionGroups, messagePresentation, userMessageHtml, workspaceHtml, reportDeliveryHtml, diagnosisHtml, sessionActivityAt, mergeThreadTimes } from "./web/controllers.js";

test("diagnosis preserves work counts and escapes reasons, instructions and blockers", () => {
  assert.equal(diagnosisHtml(undefined), "");
  const html = diagnosisHtml({ title: "<script>bad</script>", reason: "结果 <待核对>", nextStep: '你：检查 <img src=x onerror="bad()">',
    facts: ["交接 <事实>"], confirmBlocker: "发送 <未确认>", handoffBlocker: "连接 <中断>",
    work: { host: false, running: 1, sending: 2, queued: 3, idle: 7, reports: 4 } });
  assert.match(html, /中控空闲 · 执行中 1 · 发送中 2 · 排队 3 · 空闲 7 · 待回传 4/);
  assert.match(html, /暂不能确认：发送 &lt;未确认&gt;/);
  assert.match(html, /交接 &lt;事实&gt;/);
  assert(!html.includes("<script>"));
  assert(!html.includes("<img"));
  assert(!html.includes("<details open"));
});

test("session dates use only that session's trustworthy activity, including former hosts", () => {
  const task = { updatedAt: 9000, host: "host", formerHosts: ["former"], statistics: { sessions: [
    { threadId: "host", turns: [{ startedAt: 200, completedAt: 250 }] },
    { threadId: "worker", updatedAt: 800 },
    { threadId: "former", turns: [{ startedAt: 100 }] },
    { threadId: "estimated", turns: [{ completedAt: 1000, timeEstimated: true }] },
  ] } };
  assert.equal(sessionActivityAt(task, "host"), 250);
  assert.equal(sessionActivityAt(task, "worker"), 800);
  assert.equal(sessionActivityAt(task, "former"), 100);
  assert.equal(sessionActivityAt(task, "missing"), null);
  assert.equal(sessionActivityAt(task, "estimated"), null);
});

test("old lists and reconnects cannot regress dates or mix normal/managed sessions", () => {
  const before = [{ id: "host", updatedAt: 400 }, { id: "normal", updatedAt: 700 }];
  const rows = [{ id: "host", updatedAt: 100, status: "idle" }, { id: "normal", updatedAt: 800 }, { id: "new", updatedAt: null }];
  assert.deepEqual(mergeThreadTimes(rows, before).map(row => row.updatedAt), [400, 800, null]);
  assert.equal(mergeThreadTimes(rows, before)[0].status, "idle");
  for (const updatedAt of [null, undefined, 0, -1, true, "100", NaN, Infinity])
    assert.equal(mergeThreadTimes([{ id: "unknown", updatedAt }], before)[0].updatedAt, null);
  assert.deepEqual(rows.map(row => row.updatedAt), [100, 800, null]);
});

test("program envelopes distinguish user, automatic and worker-report messages", () => {
  for (const [source, label] of [["user", "你的消息"], ["automatic", "MA4 自动通知"], ["worker_report", "执行者回报"]]) {
    const raw = `[MA4 message:abc]\n[MA4 source:${source}]\n目标与预算\n[MA4 content]\n实际正文`;
    assert.deepEqual(messagePresentation(raw), { source, context: "目标与预算", text: "实际正文" });
    const html = userMessageHtml({ id: "i", text: raw });
    assert.match(html, new RegExp(label));
    assert.match(html, /<details class="message-context">/);
    assert(!html.includes("<details open"));
    assert(!html.includes("[MA4 message:"));
  }
});

test("legacy unknown sources remain honest and ordinary user text is not guessed", () => {
  assert.equal(messagePresentation("MA4 任务：test\n[MA4 message:old]\n随意插话").source, "legacy");
  assert.equal(messagePresentation("MA4 任务：test\n[MA4 message:old]\n以下是执行者的未独立验证报告。...").source, "worker_report");
  assert.equal(messagePresentation("MA4 任务：test\n[MA4 message:old]\n用户启动/恢复本任务。").source, "automatic");
  assert.equal(messagePresentation("用户启动/恢复本任务。").source, "user");
  assert.equal(messagePresentation("解释这个标记：[MA4 message:old]\n以下是执行者的未独立验证报告。").source, "user");
});

test("message labels and folded context safely escape user-controlled content", () => {
  const raw = '[MA4 message:id]\n[MA4 source:user]\n<script>context</script>\n[MA4 content]\n<img src=x onerror=alert(1)>';
  const html = userMessageHtml({ id: '\" onclick=\"alert(1)', text: raw });
  assert(!html.includes("<script>"));
  assert(!html.includes("<img "));
  assert(!html.includes('data-item="" onclick='));
  assert.match(html, /&lt;script&gt;/);
});

test("skill attachments are labelled separately without inventing user text", () => {
  const html = userMessageHtml({ text: "我的正文 @godot-tech", attachments: [
    { type: "skill", name: '<godot-tech>', path: "/skills/godot-tech/SKILL.md" },
    { type: "mention", name: "README" },
  ] });
  assert.match(html, /<div class="message-body">我的正文 @godot-tech<\/div>/);
  assert.match(html, /Skill 附件：<b>&lt;godot-tech&gt;<\/b>/);
  assert.match(html, /引用附件：<b>README<\/b>/);
  assert(!html.includes("@&lt;godot-tech&gt;"));
  assert(!userMessageHtml({ text: "普通文字" }).includes("message-attachments"));
});

test("ordinary sessions are separated by task membership, not shared cwd", () => {
  const tasks = [{ host: "host", formerHosts: ["old-host"], workers: { worker: {} } }];
  const rows = ["host", "old-host", "worker", "legacy"].map(id => ({ id, cwd: "/project/rpg", status: "idle" }));
  rows.push({ id: "normal", cwd: "/home/dticpw/codex" }, { id: "ma4", cwd: "/home/dticpw/PG_linux/MA4" });
  const folds = [{ name: "RPG 旧会话", cwd_prefix: "/project/rpg", include_active: true }];
  const groups = ordinarySessionGroups(tasks, rows, folds);
  assert.deepEqual(groups.map(g => g.rows.map(r => r.id)), [["normal", "ma4"], ["legacy"]]);
  assert.equal(groups[1].folded, true);
  assert.deepEqual(ordinarySessionGroups(tasks, rows, folds, "search").flatMap(g => g.rows.map(r => r.id)), ["legacy", "normal", "ma4"]);
});

test("folder matching respects path boundaries and preserves important old sessions", () => {
  const rows = [
    { id: "outside", cwd: "/project/rpg2" },
    { id: "pinned", cwd: "/project/rpg", pinned: true },
    { id: "waiting", cwd: "/project/rpg", status: "input" },
    { id: "inside", cwd: "/project/rpg/child", status: "idle" },
  ];
  assert.deepEqual(ordinarySessionGroups([], rows, [{ name: "旧会话", cwd_prefix: "/project/rpg" }]).map(g => g.rows.map(r => r.id)), [["outside", "pinned", "waiting"], ["inside"]]);
});

test("dispatch details expose failure and escape task content", () => {
  const html = dynamicToolHtml({ id: 'x" onclick="bad', tool: "ma4_dispatch", status: "completed", success: false,
    arguments: '{"instruction":"<script>bad()</script>","write_scope":["/tmp"]}', output: '{"error":"必须是项目相对路径"}' });
  assert.match(html, /派工内容与参数/);
  assert.match(html, /失败原因/);
  assert.match(html, /必须是项目相对路径/);
  assert(!html.includes("<script>"));
  assert(!html.includes('data-item="x" onclick='));
});

test("running and missing tool returns do not claim success", () => {
  assert.match(dynamicToolHtml({ status: "inProgress" }), /等待返回/);
  assert.match(dynamicToolHtml({ status: "completed" }), /无返回值记录/);
  assert(!dynamicToolHtml({ status: "completed" }).includes("成功"));
});

test("statistics separate cached input, missing attribution, and unknown time", () => {
  const usage = { totalTokens: 1600, inputTokens: 1500, cachedInputTokens: 1200, outputTokens: 100 };
  const html = statisticsHtml({ statistics: { roles: [{ role: "host", usage, durationMs: 1500, turnCount: 1 }],
    sessions: [{ threadId: "host", name: "<旧中控>", usage, durationMs: 1500, unattributedTokens: 1600,
      turns: [{ id: "t1", status: "failed", usage: null }] }] } });
  assert.match(html, /<td>300<\/td><td>1,200<\/td><td>100<\/td>/);
  assert.match(html, /尚未归属到轮次/);
  assert.match(html, /未取得轮次用量/);
  assert.match(html, /<td>—<\/td>/);
  assert(!html.includes("<旧中控>"));
});

test("workspace display includes actual worker locations, legacy roots and escaped scopes", () => {
  const old = workspaceHtml({ cwd: "/main", workers: { old: { name: "旧执行者", access: "write", scope: [] } } });
  assert.match(old, /\/main/);
  assert.match(old, /整个目录/);
  const html = workspaceHtml({ cwd: "/main", workspaces: [{ cwd: "/shared", write_scope: ["skills/<tag>"] }],
    workers: { worker: { name: "<script>", cwd: "/shared", access: "write", scope: ["skills/<tag>"] } } });
  assert.match(html, /\/shared/);
  assert(!html.includes("<script>"));
  assert(!html.includes("<tag>"));
  assert.match(html, /skills\/&lt;tag&gt;/);
});

test("pending report display preserves source links, reasons and escapes content", () => {
  assert.equal(reportDeliveryHtml(undefined), "");
  assert.equal(reportDeliveryHtml({ count: 0 }), "");
  const html = reportDeliveryHtml({ count: 2, reason: "中控正在处理 <当前回合>",
    reports: [{ name: "评估 <script>", threadId: 'id" onclick="bad()' }, { name: "旧报告" }] });
  assert.match(html, /2 份执行报告待回传/);
  assert.match(html, /中控正在处理 &lt;当前回合&gt;/);
  assert(!html.includes("<script>"));
  assert(!html.includes('onclick="bad()'));
  assert.match(html, /查看执行会话/);
  assert.match(html, /旧报告/);
});
