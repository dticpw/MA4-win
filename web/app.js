import { isWithin, shortPath as compactPath } from "/paths.js";
import { renderMarkdown, escapeHtml } from "/markdown.js";
import { createControllers, dynamicToolHtml, userMessageHtml, activityTimestamp, mergeThreadTimes } from "/controllers.js";

const $ = (id) => document.getElementById(id);
const state = {
  threads: [],
  approvals: [],
  daemon: {},
  side: {},
  current: null,      // selected thread id
  openedThread: null, // metadata from /api/open, independent of list/SSE delivery order
  turn: null,         // in-progress turn id of the selected thread
  tokens: null,
  older: null,        // cursor for older history
  drafts: {},
  skillDrafts: {},   // thread id -> attachments explicitly chosen for this draft
  seq: 0,
  skills: {},        // cwd -> skills
  override: null,    // {model, effort} chosen with /model for the selected thread
  filter: null,      // "waiting" | "running" | "unread" from the top counters
  flash: new Set(),  // thread ids whose status just changed
  counts: {},
  sidebarView: "tasks",
  openFolds: new Set(), // fold groups the user expanded
  quotaSignature: null, // last rendered quota figures
};

const controllers = createControllers({ api, openThread, toast, refresh: loadState, current: () => state.current, home: () => state.side.runtime?.home || "" });

// ---------- helpers ----------
const shortPath = (p) => compactPath(p, state.side.runtime?.home || "");
const defaultCwd = () => state.side.runtime?.defaultCwd || "";
const title = (t) => t.name || t.preview || t.id.slice(0, 8);

function ago(seconds) {
  if (!activityTimestamp(seconds)) return "时间未知";
  const d = Date.now() / 1000 - seconds;
  if (d < 60) return "刚刚";
  if (d < 3600) return `${Math.floor(d / 60)} 分钟前`;
  if (d < 86400) return `${Math.floor(d / 3600)} 小时前`;
  return `${Math.floor(d / 86400)} 天前`;
}

function duration(seconds) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} 秒`;
  if (s < 3600) return `${Math.floor(s / 60)} 分 ${s % 60} 秒`;
  return `${Math.floor(s / 3600)} 时 ${Math.floor((s % 3600) / 60)} 分`;
}

const clock = (seconds) => new Date(seconds * 1000).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
const elapsed = (run) => (run && run.startedAt ? duration(Date.now() / 1000 - run.startedAt) : "");

const SANDBOX = { dangerFullAccess: "完全访问", workspaceWrite: "工作区可写", readOnly: "只读", externalSandbox: "外部沙箱" };
const APPROVAL = { never: "从不审批", "on-request": "按需审批", untrusted: "不可信命令需审批", "on-failure": "失败时审批", granular: "细粒度审批" };

const kTokens = (n) => (n >= 1000 ? `${Math.round(n / 1000)}k` : `${n}`);

const STATUS = {
  approval: { label: "等你审批", rank: 0 },
  input: { label: "等你回答", rank: 0 },
  running: { label: "运行中", rank: 1 },
  error: { label: "出错", rank: 2 },
  idle: { label: "空闲", rank: 3 },
  offline: { label: "未载入", rank: 3 },
};

function initials(t) {
  const name = title(t).trim();
  const latin = name.match(/[A-Za-z0-9]+/g);
  if (/^[A-Za-z0-9]/.test(name) && latin) return (latin.length > 1 ? latin[0][0] + latin[1][0] : latin[0].slice(0, 2));
  return [...name][0] || "?";
}

function hue(id) {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}

function avatar(t, big = false) {
  return `<div class="avatar${big ? " big" : ""}" style="--h:${hue(t.id)}">${escapeHtml(initials(t))}<span class="badge ${statusKey(t)}"></span></div>`;
}

const FILTERS = {
  waiting: { label: "只看等你处理的", test: (t) => t.status === "approval" || t.status === "input" },
  running: { label: "只看运行中的", test: (t) => t.status === "running" },
  unread: { label: "只看有新回复的", test: (t) => t.unread },
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
  const filter = FILTERS[state.filter];
  const rows = state.threads.filter((t) => (!filter || filter.test(t)) && (!q
    || title(t).toLowerCase().includes(q) || (t.cwd || "").toLowerCase().includes(q)));
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

// Quiet threads whose cwd matches a configured prefix collapse into one row at the bottom.
// A fold with include_active also keeps running / unread threads inside (its row shows their counts);
// threads waiting for you or pinned always stay in the main list.
function foldOf(t) {
  if (t.status === "approval" || t.status === "input" || t.pinned) return null;
  const fold = (state.side.folds || []).find((f) => isWithin(t.cwd, f.cwd_prefix)) || null;
  if (fold && !fold.include_active && (t.status === "running" || t.unread)) return null;
  return fold;
}

function foldBadges(members) {
  const running = members.filter((t) => t.status === "running").length;
  const unread = members.filter((t) => t.unread && t.status !== "running").length;
  return (running ? `<span class="fold-badge running">${running} 运行中</span>` : "")
    + (unread ? `<span class="fold-badge unread">${unread} 新回复</span>` : "");
}

function saveFolds() {
  try { localStorage.setItem("ma4-open-folds", JSON.stringify([...state.openFolds])); } catch { /* not persisted */ }
}

function threadRow(t) {
  const key = statusKey(t);
  const label = key === "unread" ? "新回复" : STATUS[t.status]?.label || t.status;
  // The list only names states worth acting on; idle / not loaded stay quiet.
  const shown = ["running", "approval", "input", "unread", "error"].includes(key) ? label : "";
  const since = t.run && t.run.startedAt ? ` data-since="${t.run.startedAt}"` : "";
  const classes = ["thread", t.id === state.current ? "selected" : "", state.flash.has(t.id) ? "flash" : ""].join(" ");
  return `<li class="${classes}" data-id="${t.id}" title="${label}" role="button" tabindex="0" aria-label="${escapeHtml(title(t))}，${label}">
    ${avatar(t)}
    <div class="thread-main">
      <div class="thread-title">${t.pinned ? "★ " : ""}${escapeHtml(title(t))}</div>
      <div class="thread-sub">${escapeHtml(shortPath(t.cwd))}</div>
    </div>
    <div class="thread-side">
      <span class="thread-state ${key}"${since} data-label="${shown}">${shown}${since ? " " + elapsed(t.run) : ""}</span>
      <span class="thread-time" title="${activityTimestamp(t.updatedAt) ? '最近活动：' + new Date(t.updatedAt * 1000).toLocaleString('zh-CN', { hour12: false }) : '没有可信的会话活动时间'}">${ago(t.updatedAt)}</span>
    </div>
  </li>`;
}

function renderThreads() {
  const q = $("search").value.trim().toLowerCase();
  const focused = document.activeElement;
  const focusKey = $("thread-list").contains(focused) && ["data-id", "data-project", "data-task", "data-task-expand"].find((a) => focused.hasAttribute(a));
  const focusValue = focusKey && focused.getAttribute(focusKey);
  $("thread-list").innerHTML = controllers.tree(sortedThreads(), state.filter, q, threadRow, state.side.folds || [], state.sidebarView);
  const counts = controllers.counts(state.threads);
  for (const tab of document.querySelectorAll("[data-sidebar-view]")) {
    const mode = tab.dataset.sidebarView, selected = mode === state.sidebarView;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    tab.querySelector("span").textContent = counts[mode];
  }
  $("session-panel").setAttribute("aria-labelledby", "tab-" + state.sidebarView);
  $("search").placeholder = state.sidebarView === "tasks" ? "搜索中控任务 / 项目" : "搜索普通会话 / 目录";
  if (focusKey) $("thread-list").querySelector(`[${focusKey}="${CSS.escape(focusValue)}"]`)?.focus({ preventScroll: true });
  state.flash.clear();
  $("filter-bar").hidden = !state.filter;
  $("filter-label").textContent = FILTERS[state.filter]?.label || "";
  renderCounters();
  renderHeader();
  controllers.renderPanel();
  if (!state.current) renderWelcome();
}

function renderCounters() {
  const waiting = state.threads.filter((t) => t.status === "approval" || t.status === "input").length
    + state.approvals.filter((a) => !state.threads.some((t) => t.id === a.threadId && t.status === "approval")).length
    + controllers.attentionCount(state.threads);
  const running = state.threads.filter((t) => t.status === "running").length;
  const unread = state.threads.filter((t) => t.unread).length;
  for (const [key, value] of Object.entries({ waiting, running, unread })) {
    const button = document.querySelector(`.stat[data-filter="${key}"]`);
    if (state.counts[key] !== undefined && value > state.counts[key]) {
      button.classList.remove("bump");
      void button.offsetWidth; // restart the animation
      button.classList.add("bump");
    }
    state.counts[key] = value;
    $(`count-${key}`).textContent = value;
    button.classList.toggle("zero", value === 0);
    button.setAttribute("aria-pressed", String(state.filter === key));
  }
  const attention = waiting + unread;
  document.title = attention ? `(${attention}) MA4` : "MA4";
  const cwds = [...new Set(state.threads.map((t) => t.cwd).filter(Boolean))];
  $("cwd-options").innerHTML = cwds.map((c) => `<option value="${escapeHtml(c)}">`).join("");
}

// ---------- welcome overview ----------
function greeting(hour) {
  if (hour < 5) return "夜深了";
  if (hour < 11) return "早上好";
  if (hour < 13) return "中午好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

function miniCard(t, sub, i) {
  return `<button class="mini" type="button" data-open="${t.id}" style="animation-delay:${i * 40}ms">
    ${avatar(t)}<div class="mini-text"><div class="mini-title">${escapeHtml(title(t))}</div><div class="mini-sub">${escapeHtml(sub)}</div></div>
  </button>`;
}

function renderWelcome() {
  const now = new Date();
  $("welcome-date").textContent = now.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });
  $("welcome-greeting").textContent = greeting(now.getHours());
  const waiting = state.threads.filter((t) => t.status === "approval" || t.status === "input");
  const running = state.threads.filter((t) => t.status === "running");
  const unread = state.threads.filter((t) => t.unread);
  const parts = [];
  if (waiting.length) parts.push(`${waiting.length} 个会话在等你`);
  if (running.length) parts.push(`${running.length} 个正在运行`);
  if (unread.length) parts.push(`${unread.length} 个有新回复`);
  $("welcome-summary").textContent = parts.length ? parts.join("，") + "。" : "一切安静，没有需要你处理的事。";
  const attention = [...waiting, ...running, ...unread].slice(0, 9);
  $("welcome-attention").innerHTML = attention.length ? `<h4>需要留意</h4><div class="cards">${attention.map((t, i) =>
    miniCard(t, t.status === "running" ? `运行中 ${elapsed(t.run)}`.trim() : statusKey(t) === "unread" ? "新回复 · " + ago(t.updatedAt) : STATUS[t.status]?.label, i)).join("")}</div>` : "";
  const shown = new Set(attention.map((t) => t.id));
  const recent = [...state.threads].filter((t) => !shown.has(t.id) && !foldOf(t))
    .sort((a, b) => (b.pinned - a.pinned) || b.updatedAt - a.updatedAt).slice(0, 6);
  $("welcome-recent").innerHTML = recent.length ? `<h4>最近</h4><div class="cards">${recent.map((t, i) =>
    miniCard(t, (t.pinned ? "★ " : "") + ago(t.updatedAt), i + attention.length)).join("")}</div>` : "";
}

function goHome() {
  if (state.current) state.drafts[state.current] = $("input").value;
  state.current = null;
  window.history.replaceState(null, "", location.pathname);
  $("conversation").hidden = true;
  $("empty").hidden = false;
  renderThreads();
}

// ---------- conversation ----------
const currentThread = () => state.threads.find((t) => t.id === state.current)
  || (state.openedThread?.id === state.current ? state.openedThread : null);

function renderHeader() {
  const t = currentThread();
  $("rename").disabled = $("pin").disabled = !t;
  if (!t) {
    $("rename").textContent = "读取会话中…";
    $("chat-meta").textContent = "";
    $("interrupt").hidden = $("live-status").hidden = true;
    $("send").textContent = "发送";
    $("composer-hint").textContent = "会话信息正在读取";
    return;
  }
  $("rename").textContent = title(t);
  $("chat-avatar").outerHTML = avatar(t, true).replace('class="avatar big"', 'id="chat-avatar" class="avatar big"');
  const chips = [];
  if (t.model) chips.push(`<span class="chip model">${escapeHtml(t.model)}</span>`);
  if (t.effort) chips.push(`<span class="chip">思考 ${escapeHtml(t.effort)}</span>`);
  const next = state.override;
  if (next && (next.model !== t.model || (next.effort && next.effort !== t.effort))) {
    chips.push(`<span class="chip pending" title="用 /model 选的，从下一轮开始生效">下一轮 → ${escapeHtml(next.model)}${next.effort ? " · " + escapeHtml(next.effort) : ""}</span>`);
  }
  if (t.branch) chips.push(`<span class="chip">⎇ ${escapeHtml(t.branch)}</span>`);
  if (t.sandbox) {
    const perm = [SANDBOX[t.sandbox] || t.sandbox, APPROVAL[t.approval] || t.approval].filter(Boolean).join(" · ");
    chips.push(`<span class="chip ${t.sandbox === "dangerFullAccess" ? "warn" : ""}" title="权限模式（沙箱 · 审批）">${escapeHtml(perm)}</span>`);
  }
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
  live.textContent = liveText(t);
}

function liveText(t) {
  if (t.status === "approval") return "等你审批（见右侧）";
  if (t.status === "input") return "Agent 在等你回答";
  const parts = ["运行中"];
  if (t.run && t.run.startedAt) parts.push(elapsed(t.run));
  if (t.run && t.run.activity) parts.push(t.run.activity);
  return parts.join(" · ");
}

// Once a second: refresh running timers without re-rendering the list.
function tick() {
  for (const el of document.querySelectorAll("[data-since]")) {
    el.textContent = `${el.dataset.label} ${duration(Date.now() / 1000 - Number(el.dataset.since))}`;
  }
  const t = currentThread();
  if (t && !$("live-status").hidden) $("live-status").textContent = liveText(t);
}

function itemHtml(item) {
  const id = escapeHtml(item.id || "");
  switch (item.type) {
    case "userMessage":
      return userMessageHtml(item);
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
    case "dynamicToolCall":
      return dynamicToolHtml(item);
    case "mcpToolCall":
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

function turnFooter(turn) {
  const bits = [];
  if (turn.startedAt) bits.push(clock(turn.startedAt));
  if (turn.durationMs) bits.push(`用时 ${duration(turn.durationMs / 1000)}`);
  if (turn.status === "interrupted") bits.push("已中断");
  let html = bits.length ? `<div class="turn-meta">${bits.join(" · ")}</div>` : "";
  if (turn.status === "failed") html += `<div class="turn-note failed">出错：${escapeHtml(turn.error || "")}</div>`;
  return html;
}

function turnHtml(turn) {
  const items = turn.items.map(itemHtml).join("");
  const footer = turn.status === "inProgress" ? "" : turnFooter(turn);
  return `<div class="turn" data-turn="${escapeHtml(turn.id)}">${items}${footer}</div>`;
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
  palette.open = false; palette.request++;
  renderPalette();
  renderSkillSelection();
  state.openedThread = state.threads.find((t) => t.id === id) || null;
  state.sidebarView = controllers.taskFor(id) ? "tasks" : "sessions";
  try { localStorage.setItem("ma4-sidebar-view", state.sidebarView); } catch { /* optional preference */ }
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
    state.openedThread = opened.thread || state.openedThread;
    state.turn = opened.turn;
    state.tokens = opened.tokens;
    state.override = opened.override;
    state.older = history.older;
    $("turns").innerHTML = history.turns.map(turnHtml).join("") || `<div class="loading">还没有对话</div>`;
    $("older").hidden = !history.older;
    renderHeader();
    scrollBottom();
  } catch (error) {
    if (state.current !== id) return;
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
    turnElement(turnId).lastElementChild?.classList.add("fresh");
  }
  if (follow) scrollBottom();
}

function appendDelta(itemId, delta) {
  const follow = nearBottom();
  let el = document.querySelector(`[data-item="${CSS.escape(itemId)}"]`);
  if (!el) {
    turnElement(state.turn || "live").insertAdjacentHTML("beforeend",
      `<div class="msg agent fresh" data-item="${escapeHtml(itemId)}"><div class="md"></div></div>`);
    el = document.querySelector(`[data-item="${CSS.escape(itemId)}"]`);
  }
  el.classList.add("streaming");
  el.dataset.raw = (el.dataset.raw || "") + delta;
  el.querySelector(".md").innerHTML = renderMarkdown(el.dataset.raw);
  if (follow) scrollBottom();
}

async function send(event) {
  event.preventDefault();
  if ($("send").disabled || $("input").disabled) return;
  palette.open = false; palette.request++; renderPalette();
  const originalText = $("input").value;
  let text = $("input").value;
  if (!text.trim() || !state.current) return;
  if (text.startsWith("//")) {
    text = text.slice(1); // "//x" sends the literal text "/x"
  } else if (/^\/\S/.test(text)) {
    await runCommand(text.trim());
    return;
  }
  const id = state.current;
  const selectedSkills = state.skillDrafts[id] || [];
  const requestId = crypto.randomUUID();
  const pendingId = "pending-" + requestId;
  $("send").disabled = true;
  $("send").dataset.pending = "true";
  $("turns").insertAdjacentHTML("beforeend", userMessageHtml({ id: pendingId, text,
    attachments: selectedSkills.map((s) => ({ type: "skill", ...s })) }));
  const pending = document.querySelector(`[data-item="${pendingId}"]`);
  pending.classList.add("pending", "fresh");
  pending.querySelector(".message-source").textContent = "你的消息 · 发送中";
  scrollBottom();
  try {
    const result = await api("/api/send", { id, text, skills: selectedSkills, request_id: requestId });
    if (state.current === id && result.turnId) state.turn = result.turnId;
    if (state.current === id && $("input").value === originalText) {
      $("input").value = ""; state.drafts[id] = "";
    } else if (state.current !== id && state.drafts[id] === originalText) state.drafts[id] = "";
    if (state.skillDrafts[id] === selectedSkills) state.skillDrafts[id] = [];
    renderSkillSelection();
  } catch (error) {
    document.querySelector(`[data-item="${pendingId}"]`)?.remove();
    toast("发送失败：" + error.message, true);
  } finally {
    $("send").dataset.pending = "false";
    $("send").disabled = false;
    controllers.renderPanel();
  }
}

function renderSkillSelection() {
  const skills = state.skillDrafts[state.current] || [];
  const box = $("composer-skills");
  box.hidden = !skills.length;
  box.innerHTML = '<span>本条附加：</span>' + skills.map((s) => `<button type="button" class="ghost small" data-remove-skill="${escapeHtml(s.path)}" aria-label="移除 Skill ${escapeHtml(s.name)}">${escapeHtml(s.name)} ×</button>`).join("");
}

// ---------- slash commands & $skills ----------
const COMMANDS = [
  { name: "rename", args: "名称", text: "改会话名称" },
  { name: "compact", args: "", text: "压缩上下文" },
  { name: "model", args: "[模型] [思考深度]", text: "查看或切换模型与思考深度（下一轮起）" },
  { name: "review", args: "[分支]", text: "审查未提交的改动，或与某分支的差异" },
  { name: "stop", args: "", text: "中断当前回合" },
  { name: "new", args: "[目录]", text: "新建会话（默认 ~/codex）" },
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
  if (!t) {
    toast("会话信息尚未载入，请稍后重试；若读取失败，请重新打开该会话。", true);
    return;
  }
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
    } else if (name === "rename" && !arg.trim()) {
      if (!await renameCurrentThread()) return;
    } else if (name === "status") {
      const tokens = state.tokens?.used ? `${kTokens(state.tokens.used)} / ${kTokens(state.tokens.window || 0)}` : "本页还没收到用量";
      note([`会话：${escapeHtml(title(t))}（<code>${t.id}</code>）`, `目录：${escapeHtml(t.cwd)}`,
        `模型：${escapeHtml(t.model || "默认")} · 思考 ${escapeHtml(t.effort || "默认")}`
          + (state.override ? `（下一轮 → ${escapeHtml(state.override.model)}${state.override.effort ? " · " + escapeHtml(state.override.effort) : ""}）` : ""),
        `状态：${STATUS[t.status]?.label || t.status}`, t.branch ? `Git 分支：${escapeHtml(t.branch)}` : "",
        `上下文：${tokens}`].filter(Boolean).join("<br>"));
    } else if (name === "skills") {
      const skills = await listSkills();
      note(`这个目录可用的 Skill。点「＋ Skill 附件」或在 <code>$</code> 菜单中主动选择才会附加；只输入或粘贴名称不会自动附加：<br>`
        + skills.map((k) => `<code>$${escapeHtml(k.name)}</code> ${escapeHtml(k.description.slice(0, 60))}`).join("<br>"));
    } else if (name === "new") {
      $("new-error").textContent = "";
      $("new-cwd").value = arg.trim() || defaultCwd();
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

async function renameCurrentThread() {
  const t = currentThread();
  if (!t) return false;
  const name = prompt("会话名称", title(t));
  if (!name?.trim()) return false;
  await api("/api/rename", { id: t.id, name });
  return true;
}

// Popup above the composer: "/" at the start lists commands, "$word" lists skills.
const palette = { open: false, items: [], index: 0, start: 0, request: 0, origin: null };

async function updatePalette(forceSkills = false) {
  const input = $("input");
  if (!state.current || input.disabled) return;
  const request = ++palette.request;
  palette.open = false; renderPalette();
  const origin = { id: state.current, value: input.value, caret: input.selectionStart };
  const before = input.value.slice(0, input.selectionStart);
  let items = [], start = input.selectionStart;
  const command = before.match(/^\/(\S*)$/);
  const skill = before.match(/(?:^|\s)\$([\w:-]*)$/);
  if (command && !forceSkills) {
    start = 0;
    items = COMMANDS.filter((c) => c.name.startsWith(command[1]))
      .map((c) => ({ insert: `/${c.name}${c.args ? " " : ""}`, label: `/${c.name}`, hint: `${c.args} ${c.text}`.trim() }));
  } else if (skill || forceSkills) {
    start = skill && !forceSkills ? before.length - skill[1].length - 1 : input.selectionStart;
    const q = skill && !forceSkills ? skill[1].toLowerCase() : "";
    items = (await listSkills().catch(() => []))
      .filter((k) => k.name.toLowerCase().includes(q))
      .map((k) => ({ insert: "", skill: { name: k.name, path: k.path }, label: k.name, hint: k.description.slice(0, 50) }));
  }
  if (request !== palette.request || state.current !== origin.id || input.value !== origin.value || input.selectionStart !== origin.caret) return;
  palette.start = start; palette.origin = origin;
  palette.items = forceSkills ? items : items.slice(0, 12);
  // Typing/pasting a name is not a selection. Enter sends unless the user
  // deliberately highlights a skill with an arrow key (or clicks / tabs).
  palette.index = items[0]?.skill ? -1 : 0;
  palette.open = palette.items.length > 0;
  renderPalette();
}

function renderPalette() {
  const box = $("palette");
  box.hidden = !palette.open;
  $("choose-skill").setAttribute("aria-expanded", String(palette.open && Boolean(palette.items[0]?.skill)));
  $("input").setAttribute("aria-expanded", String(palette.open));
  if (palette.open && palette.index >= 0) $("input").setAttribute("aria-activedescendant", `palette-option-${palette.index}`);
  else $("input").removeAttribute("aria-activedescendant");
  box.innerHTML = (palette.items[0]?.skill ? '<li class="palette-help" role="presentation">点击或 ↓ 后 Enter 选择 · 未选择时 Enter 发送原文</li>' : "") + palette.items.map((item, i) =>
    `<li id="palette-option-${i}" role="option" aria-selected="${i === palette.index}" class="${i === palette.index ? "active" : ""}" data-index="${i}"><b>${escapeHtml(item.label)}</b><span>${escapeHtml(item.hint)}</span></li>`).join("");
  box.querySelector(".active")?.scrollIntoView({ block: "nearest" });
}

function choosePalette(i) {
  const item = palette.items[i];
  const input = $("input");
  if (!item || palette.origin?.id !== state.current || palette.origin?.value !== input.value || palette.origin?.caret !== input.selectionStart) return;
  if (item.skill) {
    const selected = state.skillDrafts[state.current] || [];
    if (!selected.some((s) => s.path === item.skill.path)) {
      if (selected.length >= 20) return toast("每条消息最多附加 20 个 Skill", true);
      state.skillDrafts[state.current] = [...selected, item.skill];
    }
    renderSkillSelection();
  }
  const after = input.value.slice(input.selectionStart);
  input.value = input.value.slice(0, palette.start) + item.insert + after;
  const caret = palette.start + item.insert.length;
  input.setSelectionRange(caret, caret);
  palette.open = false; palette.request++;
  renderPalette();
  input.focus();
}

function paletteKeys(e) {
  if (e.isComposing || (["Enter", "Tab"].includes(e.key) && e.shiftKey)) return false;
  if (e.key === "Escape") {
    palette.open = false; palette.request++; renderPalette();
    return false;
  }
  if (!palette.open) return false;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    const step = e.key === "ArrowDown" ? 1 : -1;
    palette.index = palette.index < 0 ? (step > 0 ? 0 : palette.items.length - 1)
      : (palette.index + step + palette.items.length) % palette.items.length;
    renderPalette();
  } else if (e.key === "Enter" && palette.index < 0) {
    return false;
  } else if (e.key === "Enter" && !e.isComposing && !palette.items[palette.index]?.skill
      && palette.items[palette.index].insert.trim() === $("input").value.trim()) {
    // Already fully typed (e.g. "/compact"): run it instead of re-inserting.
    palette.open = false;
    renderPalette();
    $("composer").requestSubmit();
  } else if (e.key === "Tab" || (e.key === "Enter" && !e.isComposing)) {
    choosePalette(Math.max(0, palette.index));
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

function resetText(at) {
  if (!at) return "";
  const left = at - Date.now() / 1000;
  if (left <= 0) return "已到重置时间";
  if (left < 86400) return `${Math.floor(left / 3600)} 小时 ${Math.floor((left % 3600) / 60)} 分后重置`;
  return `${Math.floor(left / 86400)} 天 ${Math.floor((left % 86400) / 3600)} 小时后重置`;
}

function renderSide() {
  const q = state.side.quota || {};
  const families = q.families || [];
  const signature = JSON.stringify([families.map((f) => f.windows.map((w) => w.used)), q.error, q.stale]);
  if (signature === state.quotaSignature) {
    // Same figures: only the countdowns move; do not replay the bar animation.
    for (const el of $("quota").querySelectorAll("[data-reset]")) el.textContent = resetText(Number(el.dataset.reset));
  } else {
    state.quotaSignature = signature;
    renderQuota(q, families);
  }
  renderSites();
  renderActivity();
}

let activitySignature = null;
function activityTime(seconds) {
  return seconds ? new Date(seconds * 1000).toLocaleTimeString("zh-CN", { hour12: false }) : "";
}

function renderActivity() {
  const rows = state.side.activity || [];
  $("activity-card").hidden = !rows.length;
  const signature = JSON.stringify(rows);
  if (signature !== activitySignature) {
    activitySignature = signature;
    const focused = document.activeElement?.dataset.activity === "chat";
    $("service-activity").innerHTML = rows.map((row) => {
      const collecting = !row.stale && row.status === "collecting";
      const ready = !row.stale && !collecting && Number.isSafeInteger(row.count) && row.count >= 0;
      const number = collecting ? "积累中" : ready ? row.count : "未知";
      const detail = row.error || (row.fetched_at ? row.stale ? "数据已过期" : collecting
        ? `统计启动不足 5 分钟 · ${activityTime(row.fetched_at)} 更新` : `${activityTime(row.fetched_at)} 更新` : "查询中…");
      const content = `<span><span class="activity-name">${escapeHtml(row.label)}</span><span class="activity-metric">${escapeHtml(row.metric)}</span></span>
        <span class="activity-value${ready ? '' : ' activity-state'}">${number}${row.key === "chat" ? '<span class="activity-arrow" aria-hidden="true">›</span>' : ""}</span>`;
      const summary = row.key === "chat"
        ? `<button class="activity-summary" data-activity="chat" aria-haspopup="dialog" ${ready ? "" : "disabled"} aria-label="Chat / 代理，近 5 分钟活跃 IP ${ready ? number + ' 个，查看详情' : '未知'}">${content}</button>`
        : `<div class="activity-summary">${content}</div>`;
      const note = row.key === "xiangqi-assist" ? '<p class="activity-updated">按浏览器标识统计，非精准人数；每 60 秒查询。</p>' : "";
      return `<div class="activity-service${ready ? "" : " unavailable"}" data-service="${escapeHtml(row.key)}">${summary}<p class="activity-updated">${escapeHtml(detail)}</p>${note}</div>`;
    }).join("");
    if (focused) $("service-activity").querySelector("[data-activity='chat']")?.focus({ preventScroll: true });
    if ($("activity-dialog").open) renderActivityDetails();
  }
}

function renderActivityDetails() {
  const row = (state.side.activity || []).find((r) => r.key === "chat");
  const ready = row && !row.stale && Number.isInteger(row.count);
  $("activity-detail-status").textContent = ready
    ? `${row.count} 个活跃 IP · ${activityTime(row.fetched_at)} 更新${row.truncated ? ' · 仅列出最近 200 个' : ''}`
    : "查询失败或数据已过期，暂无法确认。";
  const container = $("activity-visitors"), scroll = container.scrollTop;
  container.innerHTML = !ready ? "" : (row.visitors || []).map((v) => {
    const parts = [...new Set([v.country, v.region, v.city].filter((s) => s && s !== "XX"))];
    if (!v.city) parts.push("城市未记录");
    return `<article class="activity-visitor"><strong>${escapeHtml(v.ip)}</strong><span>${escapeHtml(parts.join(" · "))}</span>
      <small>最后调用 ${activityTime(v.last_seen)} · ${v.requests} 次调用</small></article>`;
  }).join("") || '<p class="hint">最近 5 分钟没有调用记录。</p>';
  container.scrollTop = scroll;
}

function renderQuota(q, families) {
  let html = families.map((f) => `<div class="quota-family">
      <div class="quota-name">${escapeHtml(f.label)}</div>
      ${f.windows.map((w) => {
        const level = w.used >= 85 ? "bad" : w.used >= 60 ? "warn" : "";
        return `<div class="quota-row ${level}">
          <div class="quota-line"><span>${escapeHtml(w.label)}</span><b>${w.used}%</b></div>
          <div class="quota-bar"><span style="width:${w.used}%"></span></div>
          <div class="quota-reset" data-reset="${w.reset_at || 0}">${resetText(w.reset_at)}</div>
        </div>`;
      }).join("")}
    </div>`).join("") || `<div class="hint">暂无额度数据</div>`;
  if (q.error || q.stale) html += `<div class="hint">${escapeHtml(q.error || "数据可能过期")}</div>`;
  $("quota").innerHTML = html;
}

function renderSites() {
  $("health").innerHTML = (state.side.health || []).map((h) => {
    const cls = h.at === undefined || h.stale ? "unknown" : h.ok ? "ok" : "bad";
    if (h.type === "tcp") {
      const status = h.at === undefined ? "检查中" : h.stale ? "未知 · 数据已过期" : h.ok ? "可达" : "不可达";
      const timing = h.at === undefined ? "TCP 连接耗时：待检查" : h.stale || !h.ok ? "TCP 连接耗时：未知" : `TCP 连接耗时：${h.ms} ms`;
      const checked = h.at === undefined ? "最近检查：尚无记录" : `最近检查：${new Date(h.at * 1000).toLocaleString("zh-CN", { hour12: false })}`;
      return `<li class="health-tcp"><div class="health-summary"><span class="dot ${cls}" aria-hidden="true"></span><span>${escapeHtml(h.name)}</span><span class="hint">${status}</span></div>
        <p class="health-detail">${escapeHtml(timing)}<br>${escapeHtml(checked)}</p>
        <p class="health-detail">TCP 网络可达性 · ${escapeHtml(h.host)}:${escapeHtml(String(h.port))}<br>每 5 分钟检查；不代表 SSH 登录或主机健康。</p></li>`;
    }
    const detail = h.at === undefined ? "检查中" : h.ok ? `${h.ms} ms` : (h.code ? `HTTP ${h.code}` : h.error || "不可达");
    const name = (h.type === undefined || h.type === "http") && /^https?:\/\//i.test(h.url || "")
      ? `<a href="${escapeHtml(h.url)}" target="_blank" rel="noopener">${escapeHtml(h.name)}</a>` : `<span>${escapeHtml(h.name)}</span>`;
    return `<li><span class="dot ${cls}"></span>${name}<span class="hint">${escapeHtml(h.stale ? "未知 · 数据已过期" : detail)}</span></li>`;
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
  state.threads = mergeThreadTimes(threads, state.threads);
  state.openedThread = threads.find((t) => t.id === state.current) || state.openedThread;
  for (const t of threads) {
    const old = before.get(t.id);
    if (!old) continue;
    if (statusKey(old) !== statusKey(t)) state.flash.add(t.id);
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
    case "controllers":
      controllers.setData(event.controllers);
      renderThreads();
      break;
    case "threads":
      applyThreads(event.threads);
      break;
    case "history":
      if (event.threadId === state.current) openThread(event.threadId);
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
      else if (event.turnId) {
        const el = turnElement(event.turnId);
        el.querySelector(".turn-meta")?.remove();
        el.insertAdjacentHTML("beforeend", turnFooter({ ...event, status: event.state }));
      }
      if (event.state === "failed" && event.error) toast("这一轮出错：" + event.error, true);
      renderHeader();
      break;
    case "run": {
      const t = state.threads.find((x) => x.id === event.threadId);
      if (t) {
        t.run = event.run;
        renderThreads();
      }
      break;
    }
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
  controllers.setData(data.controllers);
  state.seq = data.seq;
  state.approvals = data.approvals;
  state.daemon = data.daemon;
  state.side = data.side;
  state.threads = mergeThreadTimes(data.threads, state.threads);
  state.openedThread = data.threads.find((t) => t.id === state.current) || state.openedThread;
  renderThreads();
  renderApprovals();
  renderDaemon();
  renderSide();
}

function connectEvents() {
  const source = new EventSource(`/api/events?since=${state.seq}`);
  let interrupted = false;
  source.onopen = () => {
    if (!interrupted) return;
    interrupted = false;
    loadState().catch(() => {});
  };
  source.onmessage = (message) => {
    state.seq = Number(message.lastEventId) || state.seq;
    handle(JSON.parse(message.data));
  };
  source.addEventListener("resync", () => loadState().catch(() => {}));
  source.onerror = () => {
    interrupted = true;
    // EventSource reconnects by itself and resends Last-Event-ID.
    state.daemon = { connected: false, error: "与 MA4 后台的连接中断，正在重连" };
    renderDaemon();
  };
}

// ---------- clock & theme ----------
function renderClock() {
  const now = new Date();
  $("clock-time").textContent = now.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  const weekday = now.toLocaleDateString("zh-CN", { weekday: "short" });
  $("clock-date").textContent = `${now.getMonth() + 1}月${now.getDate()}日 ${weekday}`;
}

const THEMES = [["auto", "◐", "外观：跟随系统"], ["light", "☀", "外观：浅色"], ["dark", "☾", "外观：深色"]];

function applyTheme(name) {
  const [key, icon, label] = THEMES.find((t) => t[0] === name) || THEMES[0];
  if (key === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = key;
  $("theme-toggle").textContent = icon;
  $("theme-toggle").title = label + "（点击切换）";
  try { localStorage.setItem("ma4-theme", key); } catch { /* private mode: theme just won't persist */ }
}

function savedTheme() {
  try { return localStorage.getItem("ma4-theme") || "auto"; } catch { return "auto"; }
}

// ---------- wiring ----------
function wire() {
  controllers.wire();
  try { if (localStorage.getItem("ma4-sidebar-view") === "sessions") state.sidebarView = "sessions"; } catch { /* first visit */ }
  $("session-tabs").addEventListener("click", (e) => {
    const tab = e.target.closest("[data-sidebar-view]");
    if (!tab) return;
    state.sidebarView = tab.dataset.sidebarView;
    try { localStorage.setItem("ma4-sidebar-view", state.sidebarView); } catch { /* optional preference */ }
    renderThreads();
  });
  $("session-tabs").addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const mode = e.key === "Home" ? "tasks" : e.key === "End" ? "sessions" : state.sidebarView === "tasks" ? "sessions" : "tasks";
    $("tab-" + mode).click(); $("tab-" + mode).focus();
  });
  applyTheme(savedTheme());
  $("theme-toggle").addEventListener("click", () => {
    const current = document.documentElement.dataset.theme || "auto";
    applyTheme(THEMES[(THEMES.findIndex((t) => t[0] === current) + 1) % THEMES.length][0]);
  });
  renderClock();
  setInterval(renderClock, 15000);
  $("home").addEventListener("click", goHome);
  document.querySelector(".stats").addEventListener("click", (e) => {
    const button = e.target.closest(".stat");
    if (!button) return;
    state.filter = state.filter === button.dataset.filter ? null : button.dataset.filter;
    renderThreads();
  });
  $("filter-clear").addEventListener("click", () => { state.filter = null; renderThreads(); });
  $("empty").addEventListener("click", (e) => {
    const card = e.target.closest("[data-open]");
    if (card) openThread(card.dataset.open);
  });
  $("welcome-new").addEventListener("click", () => $("new-thread").click());
  $("search").addEventListener("input", renderThreads);
  try { state.openFolds = new Set(JSON.parse(localStorage.getItem("ma4-open-folds") || "[]")); } catch { /* default: all folded */ }
  $("thread-list").addEventListener("click", (e) => {
    const fold = e.target.closest(".fold");
    if (fold) {
      const name = fold.dataset.fold;
      if (!state.openFolds.delete(name)) state.openFolds.add(name);
      saveFolds();
      renderThreads();
      return;
    }
    const row = e.target.closest(".thread");
    if (row) openThread(row.dataset.id);
  });
  $("thread-list").addEventListener("keydown", (e) => {
    const row = e.target.closest(".thread");
    if (row && ["Enter", " "].includes(e.key)) { e.preventDefault(); openThread(row.dataset.id); }
  });
  $("composer").addEventListener("submit", send);
  $("input").addEventListener("input", () => updatePalette());
  $("choose-skill").addEventListener("click", () => {
    if ($("input").disabled) return;
    $("input").focus();
    if (palette.open && palette.items[0]?.skill) {
      palette.open = false; palette.request++; renderPalette();
    } else updatePalette(true);
  });
  $("composer-skills").addEventListener("click", (e) => {
    const button = e.target.closest("[data-remove-skill]");
    if (!button) return;
    state.skillDrafts[state.current] = (state.skillDrafts[state.current] || []).filter((s) => s.path !== button.dataset.removeSkill);
    renderSkillSelection();
    $("input").focus();
  });
  $("composer").addEventListener("focusout", () => setTimeout(() => {
    if (document.activeElement === $("input") || document.activeElement === $("choose-skill")) return;
    palette.open = false; palette.request++; renderPalette();
  }, 150));
  $("palette").addEventListener("mousedown", (e) => {
    if (e.target.closest("[data-index]")) e.preventDefault();
  });
  $("palette").addEventListener("click", (e) => {
    const row = e.target.closest("[data-index]");
    if (row) choosePalette(Number(row.dataset.index));
  });
  $("input").addEventListener("keydown", (e) => {
    if (paletteKeys(e)) return;
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      $("composer").requestSubmit();
    }
  });
  $("older").addEventListener("click", () => loadOlder().catch((e) => toast(e.message, true)));
  $("rename").addEventListener("click", () => renameCurrentThread().catch((e) => toast(e.message, true)));
  $("pin").addEventListener("click", () => {
    const t = currentThread();
    if (!t) return;
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
    const file = e.target.closest(".file-ref[data-file-path]");
    if (file) {
      file.disabled = true;
      api("/api/file/open", { id: state.current, path: file.dataset.filePath })
        .then(() => toast("已交给系统默认应用打开"))
        .catch((err) => toast("打开失败：" + err.message, true))
        .finally(() => { file.disabled = false; });
      return;
    }
    const copy = e.target.closest(".copy");
    if (!copy) return;
    navigator.clipboard.writeText(copy.nextElementSibling.textContent)
      .then(() => { copy.textContent = "已复制"; setTimeout(() => { copy.textContent = "复制"; }, 1200); })
      .catch(() => toast("复制失败，请手动选择", true));
  });
  $("new-thread").addEventListener("click", () => {
    $("new-error").textContent = "";
    $("new-cwd").value = defaultCwd();
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
  $("service-activity").addEventListener("click", (event) => {
    if (!event.target.closest("[data-activity='chat']")) return;
    renderActivityDetails();
    $("activity-dialog").showModal();
  });
  setInterval(() => api("/api/side").then((side) => { state.side = side; renderSide(); }).catch(() => {
    for (const row of state.side.activity || []) { row.stale = true; row.error = "MA4 连接中断，暂无法确认"; }
    for (const row of state.side.health || []) row.stale = true;
    renderSites();
    renderActivity();
  }), 15000);
  setInterval(renderThreads, 60000); // keep "n 分钟前" fresh
  setInterval(tick, 1000);
}

setupNotifyToggle();
wire();
loadState()
  .then(() => {
    connectEvents();
    const wanted = location.hash.slice(1);
    if (wanted) openThread(wanted); // may be newer than the list; the header fills in on refresh
  })
  .catch((e) => toast("读取失败：" + e.message, true));
