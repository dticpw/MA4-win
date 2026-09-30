import { renderMarkdown, escapeHtml } from "/markdown.js";

const $ = (id) => document.getElementById(id);
const state = {
  threads: [],
  approvals: [],
  daemon: {},
  side: {},
  current: null,      // selected thread id
  turn: null,         // in-progress turn id of the selected thread
  tokens: null,
  older: null,        // cursor for older history
  drafts: {},
  seq: 0,
  skills: {},        // cwd -> skills
  override: null,    // {model, effort} chosen with /model for the selected thread
};

// ---------- helpers ----------
const home = "/home/dticpw";
const shortPath = (p) => (p || "").replace(home, "~");
const title = (t) => t.name || t.preview || t.id.slice(0, 8);

function ago(seconds) {
  if (!seconds) return "";
  const d = Date.now() / 1000 - seconds;
  if (d < 60) return "刚刚";
  if (d < 3600) return `${Math.floor(d / 60)} 分钟前`;
  if (d < 86400) return `${Math.floor(d / 3600)} 小时前`;
  return `${Math.floor(d / 86400)} 天前`;
}

const kTokens = (n) => (n >= 1000 ? `${Math.round(n / 1000)}k` : `${n}`);

const STATUS = {
  approval: { label: "等你审批", rank: 0 },
  input: { label: "等你回答", rank: 0 },
  running: { label: "运行中", rank: 1 },
  error: { label: "出错", rank: 2 },
  idle: { label: "空闲", rank: 3 },
  offline: { label: "未载入", rank: 3 },
};

function statusKey(t) {
  if (t.unread && (t.status === "idle" || t.status === "offline")) return "unread";
  return t.status;
}

function toast(text, isError = false) {
  const el = $("toast");
  el.textContent = text;
  el.className = "toast" + (isError ? " error" : "");
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, 4000);
}

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-MA4-Request": "1" },
    body: JSON.stringify(body),
  };
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）`);
  return data;
}

// ---------- session list ----------
function sortedThreads() {
  const q = $("search").value.trim().toLowerCase();
  const rows = state.threads.filter((t) => !q
    || title(t).toLowerCase().includes(q) || (t.cwd || "").toLowerCase().includes(q));
  const rank = (t) => {
    if (t.status === "approval" || t.status === "input") return 0;
    if (t.status === "running") return 1;
    if (t.unread) return 2;
    if (t.pinned) return 3;
    return 4;
  };
  return rows.sort((a, b) => rank(a) - rank(b) || b.updatedAt - a.updatedAt);
}

const GROUPS = ["等你处理", "运行中", "新回复", "置顶", "其他"];

function renderThreads() {
  const list = $("thread-list");
  const rows = sortedThreads();
  let lastGroup = null;
  const html = [];
  for (const t of rows) {
    const group = t.status === "approval" || t.status === "input" ? 0
      : t.status === "running" ? 1 : t.unread ? 2 : t.pinned ? 3 : 4;
    if (group !== lastGroup) {
      html.push(`<li class="group">${GROUPS[group]}</li>`);
      lastGroup = group;
    }
    const key = statusKey(t);
    const label = key === "unread" ? "新回复" : STATUS[t.status]?.label || t.status;
    html.push(`<li class="thread ${t.id === state.current ? "selected" : ""}" data-id="${t.id}">
      <span class="dot ${key}" title="${label}"></span>
      <div class="thread-main">
        <div class="thread-title">${t.pinned ? "★ " : ""}${escapeHtml(title(t))}</div>
        <div class="thread-sub">${escapeHtml(shortPath(t.cwd))}</div>
      </div>
      <div class="thread-side">
        <span class="thread-state ${key}">${label}</span>
        <span class="thread-time">${ago(t.updatedAt)}</span>
      </div>
    </li>`);
  }
  list.innerHTML = html.join("") || `<li class="group">没有会话</li>`;
  renderCounters();
  renderHeader();
}

function renderCounters() {
  const waiting = state.threads.filter((t) => t.status === "approval" || t.status === "input").length
    + state.approvals.filter((a) => !state.threads.some((t) => t.id === a.threadId && t.status === "approval")).length;
  const running = state.threads.filter((t) => t.status === "running").length;
  const unread = state.threads.filter((t) => t.unread).length;
  $("count-waiting").textContent = waiting;
  $("count-running").textContent = running;
  $("count-unread").textContent = unread;
  const attention = waiting + unread;
  document.title = attention ? `(${attention}) MA4` : "MA4";
  const cwds = [...new Set(state.threads.map((t) => t.cwd).filter(Boolean))];
  $("cwd-options").innerHTML = cwds.map((c) => `<option value="${escapeHtml(c)}">`).join("");
}

// ---------- conversation ----------
const currentThread = () => state.threads.find((t) => t.id === state.current);

function renderHeader() {
  const t = currentThread();
  if (!t) return;
  $("rename").textContent = title(t);
  const chips = [];
  if (t.model) chips.push(`<span class="chip model">${escapeHtml(t.model)}</span>`);
  if (t.effort) chips.push(`<span class="chip">思考 ${escapeHtml(t.effort)}</span>`);
  const next = state.override;
  if (next && (next.model !== t.model || (next.effort && next.effort !== t.effort))) {
    chips.push(`<span class="chip pending" title="用 /model 选的，从下一轮开始生效">下一轮 → ${escapeHtml(next.model)}${next.effort ? " · " + escapeHtml(next.effort) : ""}</span>`);
  }
  if (t.branch) chips.push(`<span class="chip">⎇ ${escapeHtml(t.branch)}</span>`);
  if (state.tokens && state.tokens.used) {
    chips.push(`<span class="chip">上下文 ${kTokens(state.tokens.used)}${state.tokens.window ? " / " + kTokens(state.tokens.window) : ""}</span>`);
  }
  $("chat-meta").innerHTML = `<span>${escapeHtml(shortPath(t.cwd))} · ${STATUS[t.status]?.label || t.status}</span>${chips.join("")}`;
  $("pin").textContent = t.pinned ? "取消置顶" : "置顶";
  const running = t.status === "running" || t.status === "approval" || t.status === "input";
  $("interrupt").hidden = !running;
  $("send").textContent = running ? "插话" : "发送";
  $("composer-hint").textContent = t.status === "offline"
    ? "这个会话未载入，发送时会先载入（不会重复启动）" : running ? "Agent 正在工作，消息会插入当前回合" : "";
  const live = $("live-status");
  live.hidden = !running;
  live.textContent = t.status === "approval" ? "等你审批（见右侧）" : t.status === "input" ? "Agent 在等你回答" : "运行中…";
}

function itemHtml(item) {
  const id = escapeHtml(item.id || "");
  switch (item.type) {
    case "userMessage":
      return `<div class="msg user" data-item="${id}"><div class="bubble">${escapeHtml(item.text || "").replace(/\n/g, "<br>")}</div></div>`;
    case "agentMessage":
      return `<div class="msg agent" data-item="${id}"><div class="md">${renderMarkdown(item.text || "")}</div></div>`;
    case "reasoning":
      if (!item.text) return "";
      return `<details class="tool muted" data-item="${id}"><summary>思考</summary><pre>${escapeHtml(item.text)}</pre></details>`;
    case "commandExecution": {
      const failed = item.exitCode !== null && item.exitCode !== undefined && item.exitCode !== 0;
      const state = item.status === "inProgress" ? "运行中" : failed ? `退出码 ${item.exitCode}` : "";
      return `<details class="tool ${failed ? "failed" : ""}" data-item="${id}"><summary><span class="tool-kind">命令</span><code>${escapeHtml(item.command || "")}</code><span class="tool-state">${state}</span></summary><pre>${escapeHtml(item.output || "（无输出）")}</pre></details>`;
    }
    case "fileChange": {
      const paths = (item.changes || []).map((c) => shortPath(c.path)).join("、");
      const diffs = (item.changes || []).map((c) => `# ${c.path}\n${c.diff || ""}`).join("\n\n");
      return `<details class="tool" data-item="${id}"><summary><span class="tool-kind">改文件</span>${escapeHtml(paths)}</summary><pre class="diff">${escapeHtml(diffs)}</pre></details>`;
    }
    case "mcpToolCall":
    case "dynamicToolCall":
    case "collabAgentToolCall":
    case "subAgentActivity":
      return `<div class="tool line" data-item="${id}"><span class="tool-kind">工具</span>${escapeHtml(item.tool || item.type)}${item.error ? ` · <span class="failed">${escapeHtml(item.error)}</span>` : ""}</div>`;
    case "webSearch":
      return `<div class="tool line" data-item="${id}"><span class="tool-kind">搜索</span>${escapeHtml(item.query || "")}</div>`;
    case "plan":
      return `<details class="tool" data-item="${id}"><summary><span class="tool-kind">计划</span></summary><pre>${escapeHtml(item.text || "")}</pre></details>`;
    case "contextCompaction":
      return `<div class="tool line muted" data-item="${id}">上下文已压缩</div>`;
    case "imageView":
    case "imageGeneration":
      return `<div class="tool line" data-item="${id}"><span class="tool-kind">图片</span>${escapeHtml(shortPath(item.path || ""))}</div>`;
    default:
      return item.type ? `<div class="tool line muted" data-item="${id}">${escapeHtml(item.type)}</div>` : "";
  }
}

function turnHtml(turn) {
  const items = turn.items.map(itemHtml).join("");
  const note = turn.status === "interrupted" ? `<div class="turn-note">已中断</div>`
    : turn.status === "failed" ? `<div class="turn-note failed">出错：${escapeHtml(turn.error || "")}</div>` : "";
  return `<div class="turn" data-turn="${escapeHtml(turn.id)}">${items}${note}</div>`;
}

function nearBottom() {
  const box = $("messages");
  return box.scrollHeight - box.scrollTop - box.clientHeight < 120;
}

function scrollBottom() {
  const box = $("messages");
  box.scrollTop = box.scrollHeight;
}

async function openThread(id) {
  if (state.current) state.drafts[state.current] = $("input").value;
  state.current = id;
  window.history.replaceState(null, "", "#" + id);
  state.turn = null;
  state.tokens = null;
  state.override = null;
  $("empty").hidden = true;
  $("conversation").hidden = false;
  $("turns").innerHTML = `<div class="loading">读取中…</div>`;
  $("older").hidden = true;
  $("input").value = state.drafts[id] || "";
  renderThreads();
  try {
    const [opened, history] = await Promise.all([api("/api/open", { id }), api(`/api/history?id=${id}`)]);
    if (state.current !== id) return;
    state.turn = opened.turn;
    state.tokens = opened.tokens;
    state.override = opened.override;
    state.older = history.older;
    $("turns").innerHTML = history.turns.map(turnHtml).join("") || `<div class="loading">还没有对话</div>`;
    $("older").hidden = !history.older;
    renderHeader();
    scrollBottom();
  } catch (error) {
    $("turns").innerHTML = `<div class="loading failed">${escapeHtml(error.message)}</div>`;
  }
}

async function loadOlder() {
  const id = state.current;
  const box = $("messages");
  const before = box.scrollHeight;
  const history = await api(`/api/history?id=${id}&cursor=${encodeURIComponent(state.older)}`);
  if (state.current !== id) return;
  $("turns").insertAdjacentHTML("afterbegin", history.turns.map(turnHtml).join(""));
  state.older = history.older;
  $("older").hidden = !history.older;
  box.scrollTop = box.scrollHeight - before;
}

function turnElement(turnId) {
  let el = document.querySelector(`[data-turn="${CSS.escape(turnId)}"]`);
  if (!el) {
    $("turns").querySelector(".loading")?.remove();
    $("turns").insertAdjacentHTML("beforeend", `<div class="turn" data-turn="${escapeHtml(turnId)}"></div>`);
    el = $("turns").lastElementChild;
  }
  return el;
}

function upsertItem(turnId, item) {
  const follow = nearBottom();
  const html = itemHtml(item);
  if (item.type === "userMessage") document.querySelector(".msg.user.pending")?.remove();
  const existing = document.querySelector(`[data-item="${CSS.escape(item.id || "")}"]`);
  if (existing) {
    const wasOpen = existing.open;
    existing.outerHTML = html;
    const replaced = document.querySelector(`[data-item="${CSS.escape(item.id || "")}"]`);
    if (replaced && wasOpen) replaced.open = true;
  } else if (html) {
    turnElement(turnId).insertAdjacentHTML("beforeend", html);
  }
  if (follow) scrollBottom();
}

function appendDelta(itemId, delta) {
  const follow = nearBottom();
  let el = document.querySelector(`[data-item="${CSS.escape(itemId)}"]`);
  if (!el) {
    turnElement(state.turn || "live").insertAdjacentHTML("beforeend",
      `<div class="msg agent" data-item="${escapeHtml(itemId)}"><div class="md"></div></div>`);
    el = document.querySelector(`[data-item="${CSS.escape(itemId)}"]`);
  }
  el.dataset.raw = (el.dataset.raw || "") + delta;
  el.querySelector(".md").innerHTML = renderMarkdown(el.dataset.raw);
  if (follow) scrollBottom();
}

async function send(event) {
  event.preventDefault();
  if (palette.open) return;
  let text = $("input").value;
  if (!text.trim() || !state.current) return;
  if (text.startsWith("//")) {
    text = text.slice(1); // "//x" sends the literal text "/x"
  } else if (/^\/\S/.test(text)) {
    await runCommand(text.trim());
    return;
  }
  const id = state.current;
  const requestId = crypto.randomUUID();
  $("send").disabled = true;
  $("turns").insertAdjacentHTML("beforeend",
    `<div class="msg user pending"><div class="bubble">${escapeHtml(text).replace(/\n/g, "<br>")}</div></div>`);
  scrollBottom();
  try {
    const result = await api("/api/send", { id, text, request_id: requestId });
    if (state.current === id && result.turnId) state.turn = result.turnId;
    $("input").value = "";
    state.drafts[id] = "";
  } catch (error) {
    document.querySelector(".msg.user.pending")?.remove();
    toast("发送失败：" + error.message, true);
  } finally {
    $("send").disabled = false;
  }
}

// ---------- slash commands & $skills ----------
const COMMANDS = [
  { name: "rename", args: "名称", text: "改会话名称" },
  { name: "compact", args: "", text: "压缩上下文" },
  { name: "model", args: "[模型] [思考深度]", text: "查看或切换模型与思考深度（下一轮起）" },
  { name: "review", args: "[分支]", text: "审查未提交的改动，或与某分支的差异" },
  { name: "stop", args: "", text: "中断当前回合" },
  { name: "new", args: "[目录]", text: "新建会话（默认同目录）" },
  { name: "status", args: "", text: "显示会话信息" },
  { name: "skills", args: "", text: "列出可用 Skill（输入 $ 也能选）" },
  { name: "help", args: "", text: "列出所有命令" },
];

function note(html) {
  $("turns").insertAdjacentHTML("beforeend", `<div class="note">${html}</div>`);
  scrollBottom();
}

async function listSkills() {
  const t = currentThread();
  if (!t) return [];
  if (!state.skills[t.cwd]) state.skills[t.cwd] = (await api(`/api/skills?id=${t.id}`)).skills;
  return state.skills[t.cwd];
}

async function runCommand(line) {
  const [, name, arg = ""] = line.match(/^\/(\S+)\s*([\s\S]*)$/);
  const t = currentThread();
  const clear = () => { $("input").value = ""; state.drafts[t.id] = ""; };
  const known = COMMANDS.find((c) => c.name === name);
  if (!known) {
    toast(`不认识 /${name}。要当普通文字发出去，请在开头多打一个 /`, true);
    return;
  }
  try {
    if (name === "help") {
      note("可用命令：<br>" + COMMANDS.map((c) => `<code>/${c.name}${c.args ? " " + c.args : ""}</code> ${c.text}`).join("<br>")
        + "<br>以 <code>//</code> 开头会把 / 当普通文字发送。");
    } else if (name === "status") {
      const tokens = state.tokens?.used ? `${kTokens(state.tokens.used)} / ${kTokens(state.tokens.window || 0)}` : "本页还没收到用量";
      note([`会话：${escapeHtml(title(t))}（<code>${t.id}</code>）`, `目录：${escapeHtml(t.cwd)}`,
        `模型：${escapeHtml(t.model || "默认")} · 思考 ${escapeHtml(t.effort || "默认")}`
          + (state.override ? `（下一轮 → ${escapeHtml(state.override.model)}${state.override.effort ? " · " + escapeHtml(state.override.effort) : ""}）` : ""),
        `状态：${STATUS[t.status]?.label || t.status}`, t.branch ? `Git 分支：${escapeHtml(t.branch)}` : "",
        `上下文：${tokens}`].filter(Boolean).join("<br>"));
    } else if (name === "skills") {
      const skills = await listSkills();
      note(`这个目录可用的 Skill（发送时写 <code>$名称</code> 会作为 Skill 调用）：<br>`
        + skills.map((k) => `<code>$${escapeHtml(k.name)}</code> ${escapeHtml(k.description.slice(0, 60))}`).join("<br>"));
    } else if (name === "new") {
      $("new-error").textContent = "";
      $("new-cwd").value = arg.trim() || t.cwd;
      $("new-dialog").showModal();
    } else if (name === "model" && !arg.trim()) {
      const { models } = await api("/api/models");
      note(`当前：${escapeHtml(t.model || "默认")} · 思考 ${escapeHtml(t.effort || "默认")}。可选：<br>`
        + models.map((m) => `<code>${escapeHtml(m.id)}</code>${m.default ? "（默认）" : ""}`
          + (m.efforts.length ? ` 思考：${m.efforts.map(escapeHtml).join(" / ")}` : "")).join("<br>")
        + "<br>用 <code>/model 模型名 [思考深度]</code> 切换，从下一轮开始生效。");
    } else {
      const result = await api("/api/command", { id: t.id, name, arg });
      if (result.override) { state.override = result.override; renderHeader(); }
      toast(result.message || `/${name} 已完成`);
    }
    clear();
  } catch (error) {
    toast(error.message, true);
  }
}

// Popup above the composer: "/" at the start lists commands, "$word" lists skills.
const palette = { open: false, items: [], index: 0, start: 0 };

async function updatePalette() {
  const input = $("input");
  const before = input.value.slice(0, input.selectionStart);
  let items = [];
  const command = before.match(/^\/(\S*)$/);
  const skill = before.match(/(?:^|\s)\$([\w:-]*)$/);
  if (command) {
    palette.start = 0;
    items = COMMANDS.filter((c) => c.name.startsWith(command[1]))
      .map((c) => ({ insert: `/${c.name}${c.args ? " " : ""}`, label: `/${c.name}`, hint: `${c.args} ${c.text}`.trim() }));
  } else if (skill) {
    palette.start = before.length - skill[1].length - 1;
    const q = skill[1].toLowerCase();
    items = (await listSkills().catch(() => []))
      .filter((k) => k.name.toLowerCase().includes(q))
      .map((k) => ({ insert: `$${k.name} `, label: `$${k.name}`, hint: k.description.slice(0, 50) }));
  }
  palette.items = items.slice(0, 12);
  palette.index = 0;
  palette.open = palette.items.length > 0;
  renderPalette();
}

function renderPalette() {
  const box = $("palette");
  box.hidden = !palette.open;
  box.innerHTML = palette.items.map((item, i) =>
    `<li class="${i === palette.index ? "active" : ""}" data-index="${i}"><b>${escapeHtml(item.label)}</b><span>${escapeHtml(item.hint)}</span></li>`).join("");
  box.querySelector(".active")?.scrollIntoView({ block: "nearest" });
}

function choosePalette(i) {
  const item = palette.items[i];
  const input = $("input");
  const after = input.value.slice(input.selectionStart);
  input.value = input.value.slice(0, palette.start) + item.insert + after;
  const caret = palette.start + item.insert.length;
  input.setSelectionRange(caret, caret);
  palette.open = false;
  renderPalette();
  input.focus();
}

function paletteKeys(e) {
  if (!palette.open) return false;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    const step = e.key === "ArrowDown" ? 1 : -1;
    palette.index = (palette.index + step + palette.items.length) % palette.items.length;
    renderPalette();
  } else if (e.key === "Enter" && !e.isComposing
      && palette.items[palette.index].insert.trim() === $("input").value.trim()) {
    // Already fully typed (e.g. "/compact"): run it instead of re-inserting.
    palette.open = false;
    renderPalette();
    $("composer").requestSubmit();
  } else if (e.key === "Tab" || (e.key === "Enter" && !e.isComposing)) {
    choosePalette(palette.index);
  } else if (e.key === "Escape") {
    palette.open = false;
    renderPalette();
  } else {
    return false;
  }
  e.preventDefault();
  return true;
}

// ---------- side panel ----------
function renderApprovals() {
  const card = $("approvals-card");
  card.hidden = !state.approvals.length;
  $("approvals").innerHTML = state.approvals.map((a) => {
    const t = state.threads.find((x) => x.id === a.threadId);
    const what = a.kind === "command" ? `<code>${escapeHtml(a.command || "")}</code>`
      : a.kind === "file" ? escapeHtml((a.paths || []).map(shortPath).join("、") || "修改文件")
        : "这类请求需要在终端里处理";
    const buttons = a.kind === "other" ? "" : `
      <button class="primary small" data-decide="accept" data-key="${a.key}">允许</button>
      <button class="ghost small" data-decide="acceptForSession" data-key="${a.key}">本会话都允许</button>
      <button class="ghost small" data-decide="decline" data-key="${a.key}">拒绝</button>`;
    return `<div class="approval">
      <div class="approval-thread" data-open="${a.threadId || ""}">${escapeHtml(t ? title(t) : "会话")}</div>
      <div class="approval-what">${what}</div>
      ${a.reason ? `<div class="approval-reason">${escapeHtml(a.reason)}</div>` : ""}
      <div class="approval-actions">${buttons}</div>
    </div>`;
  }).join("");
  renderCounters();
}

function renderSide() {
  const q = state.side.quota || {};
  let quota = "暂无数据";
  if (Number.isFinite(q.used)) {
    const left = q.reset_at ? Math.max(0, q.reset_at - Date.now() / 1000) : null;
    const reset = left === null ? "重置时间未知"
      : `${Math.floor(left / 86400)} 天 ${Math.floor((left % 86400) / 3600)} 小时后重置`;
    quota = `<div class="bar"><span style="width:${q.used}%"></span></div>
      <div class="quota-text">7 日已用 <b>${q.used}%</b> · ${reset}</div>`;
  }
  if (q.error || q.stale) quota += `<div class="hint">${escapeHtml(q.error || "数据可能过期")}</div>`;
  $("quota").innerHTML = quota;
  $("health").innerHTML = (state.side.health || []).map((h) => {
    const cls = h.at === undefined ? "unknown" : h.ok ? "ok" : "bad";
    const detail = h.at === undefined ? "检查中" : h.ok ? `${h.ms} ms` : (h.code ? `HTTP ${h.code}` : h.error || "不可达");
    return `<li><span class="dot ${cls}"></span><a href="${escapeHtml(h.url)}" target="_blank" rel="noopener">${escapeHtml(h.name)}</a><span class="hint">${escapeHtml(detail)}</span></li>`;
  }).join("");
  $("links").innerHTML = (state.side.links || []).map((l) =>
    `<a class="link-chip" href="${escapeHtml(l.url)}" target="_blank" rel="noopener">${escapeHtml(l.name)} ↗</a>`).join("");
}

function renderDaemon() {
  const el = $("daemon");
  const ok = state.daemon.connected;
  el.className = "daemon " + (ok ? "ok" : "bad");
  el.textContent = ok ? "守护进程已连接" : "守护进程未连接";
  el.title = state.daemon.error || state.daemon.version || "";
}

// ---------- desktop notifications ----------
function notifyUser(t, text) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  if (!document.hidden && t.id === state.current) return;
  const n = new Notification(`MA4 · ${title(t)}`, { body: text, tag: t.id });
  n.onclick = () => { window.focus(); openThread(t.id); };
}

function setupNotifyToggle() {
  const button = $("notify-toggle");
  const sync = () => {
    button.hidden = !("Notification" in window) || Notification.permission === "granted";
  };
  button.addEventListener("click", async () => { await Notification.requestPermission(); sync(); });
  sync();
}

function applyThreads(threads) {
  const before = new Map(state.threads.map((t) => [t.id, t]));
  state.threads = threads;
  for (const t of threads) {
    const old = before.get(t.id);
    if (!old) continue;
    if (old.status !== t.status && (t.status === "approval" || t.status === "input")) {
      notifyUser(t, t.status === "approval" ? "等你审批" : "等你回答");
    } else if (old.status === "running" && t.status === "idle") {
      notifyUser(t, "这一轮做完了");
    }
  }
  renderThreads();
}

// ---------- events ----------
function handle(event) {
  switch (event.kind) {
    case "threads":
      applyThreads(event.threads);
      break;
    case "approvals":
      state.approvals = event.approvals;
      renderApprovals();
      break;
    case "daemon":
      state.daemon = event.daemon;
      renderDaemon();
      break;
    case "tokens":
      if (event.threadId === state.current) { state.tokens = event.tokens; renderHeader(); }
      break;
    case "turn":
      if (event.threadId !== state.current) break;
      state.turn = event.state === "started" ? event.turnId : null;
      if (event.state === "started") turnElement(event.turnId);
      if (event.state === "failed" && event.error) toast("这一轮出错：" + event.error, true);
      renderHeader();
      break;
    case "item":
      if (event.threadId === state.current) upsertItem(event.turnId, event.item);
      break;
    case "delta":
      if (event.threadId === state.current) appendDelta(event.itemId, event.delta);
      break;
    default:
      break;
  }
}

async function loadState() {
  const data = await api("/api/state");
  state.seq = data.seq;
  state.approvals = data.approvals;
  state.daemon = data.daemon;
  state.side = data.side;
  state.threads = data.threads;
  renderThreads();
  renderApprovals();
  renderDaemon();
  renderSide();
}

function connectEvents() {
  const source = new EventSource(`/api/events?since=${state.seq}`);
  source.onmessage = (message) => {
    state.seq = Number(message.lastEventId) || state.seq;
    handle(JSON.parse(message.data));
  };
  source.addEventListener("resync", () => loadState().catch(() => {}));
  source.onerror = () => {
    // EventSource reconnects by itself and resends Last-Event-ID.
    state.daemon = { connected: false, error: "与 MA4 后台的连接中断，正在重连" };
    renderDaemon();
  };
}

// ---------- wiring ----------
function wire() {
  $("search").addEventListener("input", renderThreads);
  $("thread-list").addEventListener("click", (e) => {
    const row = e.target.closest(".thread");
    if (row) openThread(row.dataset.id);
  });
  $("composer").addEventListener("submit", send);
  $("input").addEventListener("input", () => updatePalette());
  $("input").addEventListener("blur", () => setTimeout(() => { palette.open = false; renderPalette(); }, 150));
  $("palette").addEventListener("mousedown", (e) => {
    const row = e.target.closest("li");
    if (row) { e.preventDefault(); choosePalette(Number(row.dataset.index)); }
  });
  $("input").addEventListener("keydown", (e) => {
    if (paletteKeys(e)) return;
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      $("composer").requestSubmit();
    }
  });
  $("older").addEventListener("click", () => loadOlder().catch((e) => toast(e.message, true)));
  $("rename").addEventListener("click", async () => {
    const t = currentThread();
    const name = prompt("会话名称", title(t));
    if (name && name.trim()) await api("/api/rename", { id: t.id, name }).catch((e) => toast(e.message, true));
  });
  $("pin").addEventListener("click", () => {
    const t = currentThread();
    api("/api/pin", { id: t.id, pinned: !t.pinned }).catch((e) => toast(e.message, true));
  });
  $("terminal").addEventListener("click", () =>
    api("/api/terminal", { id: state.current }).then(() => toast("已在终端打开")).catch((e) => toast(e.message, true)));
  $("interrupt").addEventListener("click", () =>
    api("/api/interrupt", { id: state.current }).catch((e) => toast(e.message, true)));
  $("approvals").addEventListener("click", (e) => {
    const button = e.target.closest("[data-decide]");
    if (button) {
      api("/api/approval", { key: button.dataset.key, decision: button.dataset.decide })
        .catch((err) => toast(err.message, true));
      return;
    }
    const open = e.target.closest("[data-open]");
    if (open && open.dataset.open) openThread(open.dataset.open);
  });
  $("messages").addEventListener("click", (e) => {
    const copy = e.target.closest(".copy");
    if (!copy) return;
    navigator.clipboard.writeText(copy.nextElementSibling.textContent)
      .then(() => { copy.textContent = "已复制"; setTimeout(() => { copy.textContent = "复制"; }, 1200); })
      .catch(() => toast("复制失败，请手动选择", true));
  });
  $("new-thread").addEventListener("click", () => {
    $("new-error").textContent = "";
    $("new-cwd").value = currentThread()?.cwd || "";
    $("new-dialog").showModal();
  });
  $("new-submit").addEventListener("click", async () => {
    const cwd = $("new-cwd").value.trim();
    if (!cwd) return;
    $("new-submit").disabled = true;
    try {
      const result = await api("/api/new", { cwd, text: $("new-text").value });
      $("new-dialog").close();
      $("new-text").value = "";
      await loadState();
      openThread(result.threadId);
    } catch (error) {
      $("new-error").textContent = error.message;
    } finally {
      $("new-submit").disabled = false;
    }
  });
  setInterval(() => api("/api/side").then((side) => { state.side = side; renderSide(); }).catch(() => {}), 60000);
  setInterval(renderThreads, 60000); // keep "n 分钟前" fresh
}

setupNotifyToggle();
wire();
loadState()
  .then(() => {
    connectEvents();
    const wanted = location.hash.slice(1);
    if (wanted && state.threads.some((t) => t.id === wanted)) openThread(wanted);
  })
  .catch((e) => toast("读取失败：" + e.message, true));
