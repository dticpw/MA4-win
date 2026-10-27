import { isWithin, shortPath } from "./paths.js";
import { escapeHtml as esc } from "./markdown.js";

export const taskLabels = { draft: "讨论中", running: "推进中", waiting: "执行中", review: "处理回报",
  closing: "到期收尾中", paused: "已暂停", budget: "预算已到", attention: "需要处理", completed: "已达标", stopped: "未达标结束" };

const taskMembers = (t) => [t.host, ...(t.formerHosts || []), ...Object.keys(t.workers || {})].filter(Boolean);
const taskWorkspaces = (t) => t.workspaces || [{ cwd: t.cwd, write_scope: [] }];
export const workspaceText = (rows) => rows.map((g) => `${g.cwd}\n可写：${g.write_scope.length ? g.write_scope.join("、") : "整个目录"}`).join("\n\n");
export function workspaceHtml(t) {
  const workers = Object.values(t.workers).map((w) => `<li><strong>${esc(w.name)}</strong><small>${esc(w.cwd || t.cwd)} · ${w.access === "read" ? "只读" : "可写：" + esc(w.scope?.join("、") || "整个目录")}</small></li>`).join("");
  return `<pre class="goal-compare">${esc(workspaceText(taskWorkspaces(t)))}</pre>${workers ? `<ul class="worker-locations">${workers}</ul>` : ""}`;
}

export function reportDeliveryHtml(delivery) {
  if (!delivery?.count) return "";
  const reports = delivery.reports || [];
  return `<strong>${number(delivery.count)} 份执行报告待回传</strong><p>${esc(delivery.reason)}</p><ul>${reports.slice(0, 8).map((r) => `<li>${r.threadId ? `<button type="button" class="ghost small" data-report-thread="${esc(r.threadId)}" title="查看执行会话">${esc(r.name)}</button>` : esc(r.name)}</li>`).join("")}</ul>${delivery.count > 8 ? `<p>另有 ${number(delivery.count - 8)} 份，后续分批回传。</p>` : ""}`;
}

export function messagePresentation(raw = "") {
  const match = raw.match(/^\[MA4 message:[^\]\n]+\]\n\[MA4 source:(user|automatic|worker_report)\]\n([\s\S]*?)\n\[MA4 content\]\n([\s\S]*)$/);
  if (match) return { source: match[1], context: match[2], text: match[3] };
  // Older messages did not record their source. Only classify known program templates.
  const legacy = /^(MA4 任务：|\[MA4 message:)/.test(raw) && raw.match(/\[MA4 message:[^\]\n]+\]\n([\s\S]*)$/);
  const body = legacy?.[1] || raw;
  if (legacy && /^(以下是执行者的未独立验证报告|\[MA4 到期收尾汇总\])/.test(body))
    return { source: "worker_report", text: body, context: legacy ? raw.slice(0, legacy.index) : "" };
  if (legacy && /^(用户启动\/恢复本任务。|你是接任中控，请核对|本次执行任务：)/.test(body) || raw.startsWith("[MA4 到期收尾提醒]"))
    return { source: "automatic", text: body, context: legacy ? raw.slice(0, legacy.index) : "" };
  return { source: legacy || raw.startsWith("MA4 任务：") ? "legacy" : "user", text: raw, context: "" };
}

export function userMessageHtml(item) {
  const m = messagePresentation(item.text);
  const label = { user: "你的消息", automatic: "MA4 自动通知", worker_report: "执行者回报", legacy: "旧消息 · 来源未记录" }[m.source];
  const attachments = (item.attachments || []).filter((a) => ["skill", "mention"].includes(a.type));
  const attached = attachments.length ? `<div class="message-attachments" aria-label="消息附件">${attachments.map((a) => `<span>${a.type === "skill" ? "Skill 附件" : "引用附件"}：<b>${esc(a.name)}</b></span>`).join("")}</div>` : "";
  return `<div class="msg user source-${m.source}" data-item="${esc(item.id || "")}"><div class="bubble"><div class="message-source">${label}</div><div class="message-body">${esc(m.text).replace(/\n/g, "<br>")}</div>${attached}${m.context ? `<details class="message-context"><summary>MA4 附带的任务信息</summary><pre>${esc(m.context)}</pre></details>` : ""}</div></div>`;
}
export function ordinarySessionGroups(tasks, rows, folds = [], query = "") {
  const managed = new Set(tasks.flatMap(taskMembers));
  const groups = new Map();
  for (const row of rows) {
    if (managed.has(row.id)) continue;
    const fold = !query && !row.pinned && !["approval", "input"].includes(row.status) && folds.find((f) => {
      const prefix = f.cwd_prefix.replace(/\/$/, ""), cwd = row.cwd || "";
      return isWithin(cwd, prefix) && (f.include_active || row.status !== "running" && !row.unread);
    });
    const key = fold ? `sessions:${fold.cwd_prefix}` : "sessions:main";
    if (!groups.has(key)) groups.set(key, { key, name: fold ? fold.name : "日常会话", path: fold?.cwd_prefix || "", rows: [], folded: Boolean(fold) });
    groups.get(key).rows.push(row);
  }
  return [...groups.values()].sort((a, b) => Number(a.folded) - Number(b.folded));
}

const number = (n) => Number(n || 0).toLocaleString("zh-CN");
function duration(ms) {
  if (ms == null) return "—";
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}分${s % 60}秒`;
}
const roleLabel = (role) => role === "host" ? "中控" : "执行者";
function usageCells(u) {
  if (!u) return '<td colspan="4">未取得轮次用量</td>';
  return [u.totalTokens, Math.max(0, (u.inputTokens || 0) - (u.cachedInputTokens || 0)), u.cachedInputTokens, u.outputTokens]
    .map((n) => `<td>${number(n)}</td>`).join("");
}
function statsTable(body, label) {
  return `<div class="stats-scroll" tabindex="0" role="region" aria-label="${esc(label)}"><table class="stats-table"><caption>${esc(label)}</caption><thead><tr><th scope="col">角色 / 轮次</th><th scope="col">用时</th><th scope="col">总 tokens</th><th scope="col">非缓存输入</th><th scope="col">缓存输入</th><th scope="col">输出</th></tr></thead><tbody>${body}</tbody></table></div>`;
}
export function statisticsHtml(t) {
  const stats = t.statistics;
  if (!stats) return '<p class="hint">轮次统计尚未记录。</p>';
  const summary = statsTable(stats.roles.map((r) => `<tr><th scope="row">${roleLabel(r.role)} · ${r.turnCount} 轮已记录</th><td>${duration(r.durationMs)}</td>${usageCells(r.usage)}</tr>`).join(""), "按角色统计");
  const sessions = stats.sessions.map((s) => `<details data-session-stats="${esc(s.threadId)}"><summary>${esc(s.name)} · ${number(s.usage.totalTokens)} tokens · ${duration(s.durationMs)}</summary><p class="hint stats-session-id">${esc(s.threadId)}</p>${s.unattributedTokens ? `<p class="hint">${number(s.unattributedTokens)} tokens 尚未归属到轮次（历史数据或通知缺失）。</p>` : ""}${s.turns.length ? statsTable(s.turns.map((r, i) => `<tr><th scope="row" title="${esc(r.id)}">${i + 1} · ${esc(({ inProgress: "进行中", completed: "已结束", failed: "失败", interrupted: "中断" })[r.status] || "状态待核对")}${r.timeEstimated ? "（计时约值）" : ""}</th><td>${duration(r.durationMs)}</td>${usageCells(r.usage)}</tr>`).join(""), `${s.name}的已记录轮次`) : '<p class="hint">旧会话未补扫历史，暂无轮次统计。</p>'}</details>`).join("");
  const done = t.completion;
  const ending = done ? `<p class="hint">结束记录：${done.outcome === "met" ? "已达标" : "未达标"} · ${number(done.usageTotal?.totalTokens)} tokens · 已记录回合用时 ${duration(done.turnDurationMs)}${done.elapsedMs != null ? ` · 任务历时 ${duration(done.elapsedMs)}（含暂停）` : ""}${done.settling ? " · 中控正在收尾，数字继续更新" : " · 已含收到的收尾用量"}</p>` : "";
  return ending + '<p class="hint">用时为已记录回合之和；并行会重叠，不等于任务历时。缓存输入单列且已包含在总量中；缺失数据不估算。</p>' + summary + sessions;
}

export function dynamicToolHtml(item) {
  const failed = item.success === false || item.status === "failed";
  const label = failed ? "失败" : item.status === "inProgress" ? "运行中" : item.success === true ? "成功" : item.status === "completed" ? "已结束" : "待确认";
  return `<details class="tool ${failed ? "failed" : ""}" data-item="${esc(item.id || "")}"><summary><span class="tool-kind">工具</span><code>${esc(item.tool || "")}</code><span class="tool-state">${label}</span></summary><div class="tool-detail-label">${item.tool === "ma4_dispatch" ? "派工内容与参数" : "参数"}</div><pre>${esc(item.arguments ?? "（无参数记录）")}</pre><div class="tool-detail-label">${failed ? "返回值 / 失败原因" : "返回值"}</div><pre>${esc(item.output ?? (item.status === "inProgress" ? "等待返回…" : "（无返回值记录）"))}</pre></details>`;
}

export function createControllers({ api, openThread, toast, refresh, current, home = () => "" }) {
  let data = { tasks: [], error: null }, editing = null, inspecting = null, selected = null, createRequest = null;
  let formRevision = 0, formTarget = "", formWorkspaces = [];
  let formRelativeDeadline = false, formDeadline = null;
  const $ = (id) => document.getElementById(id);
  const projectOpen = new Map(), taskOpen = new Set();
  try {
    const saved = JSON.parse(localStorage.getItem("ma4-project-tree") || "{}");
    for (const [path, open] of Object.entries(saved.projects || {})) projectOpen.set(path, open);
    for (const id of saved.tasks || []) taskOpen.add(id);
  } catch { /* first visit */ }
  const save = () => localStorage.setItem("ma4-project-tree", JSON.stringify({ projects: Object.fromEntries(projectOpen), tasks: [...taskOpen] }));
  const members = taskMembers;
  const taskFor = (tid) => data.tasks.find((t) => members(t).includes(tid));
  const short = (path) => shortPath(path, home());
  function budgetText(t) {
    const b = t.budget, used = t.usageTotal?.totalTokens || 0;
    const parts = [`${number(used)}${b.tokenLimit ? " / " + number(b.tokenLimit) : ""} tokens（含缓存输入）`];
    if (b.deadline) parts.push(`截止 ${new Date(b.deadline * 1000).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}`);
    else if (b.durationMinutes) parts.push(`启动后 ${number(b.durationMinutes)} 分钟到期`);
    if (t.estimatedCost != null) parts.push(`估算 ${t.estimatedCost.toFixed(3)}${b.moneyLimit ? " / " + b.moneyLimit : ""} ${b.currency}`);
    return parts.join(" · ");
  }
  function fallback(t, id, role) {
    return { id, name: role === "host" ? t.name : t.workers[id]?.name || "前任中控", cwd: t.workers[id]?.cwd || t.cwd,
      status: role === "host" && t.hostBusy || t.workers[id]?.state === "running" ? "running" : "offline", updatedAt: t.updatedAt };
  }
  function tree(rows, filter, query, rowHtml, folds = [], view = "tasks") {
    if (view === "sessions") {
      return ordinarySessionGroups(data.tasks, rows, folds, query).map((g) => {
        const opened = Boolean(query || (projectOpen.get(g.key) ?? (!g.folded || g.rows.some((r) => r.id === current()))));
        const running = g.rows.filter((r) => r.status === "running").length;
        return `<li class="project-group"><button class="project-toggle" type="button" data-project="${esc(g.key)}" aria-expanded="${opened}"><span aria-hidden="true">${opened ? "▾" : "▸"}</span><span>${esc(g.name)}</span><small>${g.rows.length} 个${running ? ` · ${running} 运行` : ""}</small></button>${g.path ? `<div class="project-path">${esc(short(g.path))}</div>` : ""}${opened ? `<ul class="project-children">${g.rows.map(rowHtml).join("")}</ul>` : ""}</li>`;
      }).join("") || '<li class="group">没有匹配的普通会话</li>';
    }
    const byId = new Map(rows.map((r) => [r.id, r]));
    const projects = new Map();
    const project = (cwd) => {
      if (!projects.has(cwd)) projects.set(cwd, { tasks: [] });
      return projects.get(cwd);
    };
    for (const t of data.tasks) {
      const matchText = `${t.name} ${t.cwd} ${t.target} ${taskWorkspaces(t).map((g) => g.cwd).join(" ")}`.toLowerCase().includes(query);
      const matchMember = members(t).some((id) => byId.has(id));
      if (query && !matchText && !matchMember) continue;
      const taskWaiting = filter === "waiting" && ["attention", "budget"].includes(t.status);
      if (filter && !matchMember && !taskWaiting) continue;
      project(t.cwd).tasks.push(t);
    }
    const html = [];
    for (const [cwd, p] of [...projects].sort(([a], [b]) => a.localeCompare(b))) {
      const key = `tasks:${cwd}`;
      const opened = query || (projectOpen.get(key) ?? true);
      const basename = cwd.replaceAll("\\", "/").split("/").filter(Boolean).pop() || cwd;
      html.push(`<li class="project-group"><button class="project-toggle" type="button" data-project="${esc(key)}" aria-expanded="${Boolean(opened)}" title="${esc(cwd)}"><span aria-hidden="true">${opened ? "▾" : "▸"}</span><span>${esc(basename)}</span><small>${p.tasks.length} 项任务</small></button><div class="project-path">${esc(short(cwd))}</div>`);
      if (opened) {
        html.push('<ul class="project-children">');
        for (const t of p.tasks) {
          if (members(t).includes(current()) && selected !== t.id) taskOpen.add(t.id);
          const expanded = query || taskOpen.has(t.id);
          html.push(`<li class="task-node${members(t).includes(current()) ? " current-task" : ""}"><div class="task-row"><button class="task-expand" type="button" data-task-expand="${t.id}" aria-expanded="${Boolean(expanded)}" aria-label="展开或收起 ${esc(t.name)}">${expanded ? "▾" : "▸"}</button><button class="task-select" type="button" data-task="${t.id}"><span>${esc(t.name)}</span><small class="task-state ${t.status}">${taskLabels[t.status] || esc(t.status)}</small></button></div>`);
          if (expanded) {
            html.push('<ul class="task-members">');
            for (const id of [t.host, ...Object.keys(t.workers)]) {
              if (!id) continue;
              const role = id === t.host ? "中控" : t.workers[id].access === "read" ? "只读执行" : "执行";
              const row = byId.get(id) || fallback(t, id, id === t.host ? "host" : "worker");
              html.push(rowHtml({ ...row, name: `${role} · ${id === t.host ? t.name : t.workers[id].name}` }));
            }
            if (t.formerHosts.length) html.push(`<li class="former-hosts"><details><summary>前任中控 · ${t.formerHosts.length}</summary><ul>${t.formerHosts.map((id) => rowHtml(byId.get(id) || fallback(t, id, "former"))).join("")}</ul></details></li>`);
            html.push("</ul>");
          }
          html.push("</li>");
        }
        html.push("</ul>");
      }
      html.push("</li>");
    }
    return html.join("") || '<li class="group">没有匹配的中控任务</li>';
  }
  function renderPanel() {
    const t = taskFor(current());
    selected = t?.id || null;
    $("task-context").hidden = !t;
    $("controller-error").hidden = !data.error && !data.warning && !data.recovering;
    $("controller-error").textContent = data.error || data.warning || (data.recovering ? "正在核对中控运行状态…" : "");
    if (!t) { $("choose-skill").disabled = $("input").disabled = false; $("send").disabled = $("send").dataset.pending === "true"; return; }
    $("task-name").textContent = t.name;
    $("task-state").textContent = taskLabels[t.status] || t.status;
    $("task-target").textContent = t.target || "尚未确认正式目标。先与中控讨论，再查看草案。";
    $("task-workspace-summary").innerHTML = workspaceHtml(t);
    const running = ["running", "waiting", "review", "closing"].includes(t.status);
    $("task-phase").textContent = running ? "当前正在执行；消息会交给中控协调。目标变更需另行确认。"
      : "当前仅讨论：聊天不会恢复执行。请让中控整理目标、范围和验收草案，再确认预算并启动。";
    $("task-draft-notice").hidden = !t.draft?.target;
    $("task-draft-notice").textContent = t.target ? "有待确认的新草案，正式目标尚未改变。" : "草案已准备好，等待你查看并确认。";
    $("task-budget").textContent = budgetText(t);
    $("task-note").textContent = t.note || "";
    $("task-note").hidden = !t.note;
    const reports = $("task-reports"), reportHtml = reportDeliveryHtml(t.reportDelivery);
    reports.hidden = !reportHtml;
    // Keep keyboard focus when unrelated usage updates arrive.
    if (reports._html !== reportHtml) { reports.innerHTML = reportHtml; reports._html = reportHtml; }
    $("task-summary").textContent = [t.summary, t.evidence].filter(Boolean).join("\n");
    $("task-summary").hidden = !t.summary && !t.evidence;
    const stats = $("task-statistics");
    const opened = new Set([...stats.querySelectorAll("details[open]")].map((el) => el.dataset.sessionStats));
    const html = statisticsHtml(t);
    if (stats.dataset.task !== t.id || stats._html !== html) {
      const same = stats.dataset.task === t.id;
      stats.innerHTML = html; stats._html = html; stats.dataset.task = t.id;
      if (same) for (const el of stats.querySelectorAll("details")) el.open = opened.has(el.dataset.sessionStats);
    }
    $("task-resume").hidden = ["running", "waiting", "review", "closing"].includes(t.status);
    $("task-resume").textContent = t.target ? "查看并确认后继续" : "确认目标并启动";
    $("task-pause").hidden = !["running", "waiting", "review", "closing"].includes(t.status);
    $("task-pause").textContent = t.status === "closing" ? "立即停止" : "暂停任务";
    $("task-remove").hidden = ["running", "waiting", "review", "closing"].includes(t.status) || t.hostBusy;
    $("task-handoff").disabled = ["completed", "stopped", "closing"].includes(t.status) || !t.host;
    const isHost = current() === t.host;
    $("choose-skill").disabled = $("input").disabled = !isHost;
    $("send").disabled = !isHost || $("send").dataset.pending === "true";
    $("task-back-host").hidden = isHost || !t.host;
    if ($("task-dialog").open && editing === t.id) updateFormAvailability(t);
  }
  function dateInput(seconds) {
    if (!seconds) return "";
    const d = new Date(seconds * 1000);
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  }
  function showForm(t = null) {
    editing = t?.id || null;
    createRequest = crypto.randomUUID();
    formRevision = t?.draftRevision || 0;
    formTarget = t?.target || "";
    formWorkspaces = t ? taskWorkspaces(t) : [];
    $("task-dialog-title").textContent = t ? "确认目标与预算" : "新建任务中控";
    $("task-create-fields").hidden = Boolean(t);
    $("task-review-fields").hidden = !t;
    $("task-confirm-hint").hidden = !t;
    $("task-form-idea").value = "";
    $("task-cwd").value = t?.cwd || "";
    $("task-cwd").disabled = Boolean(t);
    $("task-form-name").value = t?.name || "";
    $("task-form-target").value = t?.draft?.target || t?.target || "";
    $("task-form-target").required = Boolean(t);
    $("task-current-details").hidden = !t?.target;
    $("task-current-details").open = Boolean(t?.draft?.target && t.draft.target !== t.target);
    $("task-current-target").textContent = t?.target || "";
    $("task-current-workspace-text").textContent = workspaceText(formWorkspaces);
    $("task-current-workspaces").hidden = !t?.target;
    $("task-current-workspaces").open = Boolean(t?.draft?.workspaces && JSON.stringify(t.draft.workspaces) !== JSON.stringify(formWorkspaces));
    $("task-workspace-rows").replaceChildren();
    for (const g of t?.draft?.workspaces || formWorkspaces) addWorkspace(g, g.cwd === t?.cwd);
    const budget = t?.draft?.budget || t?.budget || {};
    formRelativeDeadline = Boolean(t && (budget.deadline || !budget.durationMinutes));
    formDeadline = budget.deadline || null;
    $("task-tokens").value = budget.tokenLimit || "";
    $("task-deadline").value = dateInput(budget.deadline);
    $("task-deadline-label").textContent = formRelativeDeadline ? "指定截止时间" : "指定截止时间（优先）";
    $("task-duration-label").textContent = formRelativeDeadline ? "从现在起的时限（min）" : "启动后时限（min）";
    $("task-duration").value = formRelativeDeadline ? "" : budget.durationMinutes || "";
    $("task-duration").placeholder = formRelativeDeadline ? "留空保留截止时间，例如填 30" : "填写分钟数，例如 480";
    $("task-duration-hint").hidden = !formRelativeDeadline;
    if (formRelativeDeadline) $("task-duration").setAttribute("aria-describedby", "task-duration-hint");
    else $("task-duration").removeAttribute("aria-describedby");
    $("task-duration").required = !t;
    updateTimeInputs();
    $("task-advanced-budget").open = Boolean(budget.deadline || budget.tokenLimit || budget.moneyLimit);
    $("task-money").value = budget.moneyLimit || "";
    $("task-currency").value = budget.currency || "CNY";
    for (const k of ["input", "cached", "output"]) $("task-rate-" + k).value = budget.rates?.[k] ?? "";
    $("task-form-error").textContent = "";
    $("task-save").textContent = t ? "确认并启动" : "创建并进入讨论";
    $("task-save-draft").hidden = $("task-confirm-only").hidden = !t;
    updateFormAvailability(t);
    updateChangeNote();
    $("task-dialog").showModal();
  }
  function updateTimeInputs() {
    const relative = formRelativeDeadline && $("task-duration").value !== "";
    $("task-duration").disabled = !formRelativeDeadline && Boolean($("task-deadline").value);
    $("task-deadline").disabled = relative;
    const deadline = Date.now() + Number($("task-duration").value) * 60000;
    $("task-duration").setCustomValidity(relative && !Number.isFinite(new Date(deadline).getTime()) ? "分钟数过大，请填写有效的时限。" : "");
  }
  function readWorkspaces() {
    return [...$("task-workspace-rows").children].map((row) => ({
      cwd: row.querySelector("input").value.trim(),
      write_scope: row.querySelector("textarea").value.split("\n").map((s) => s.trim()).filter(Boolean),
    }));
  }
  function addWorkspace(g = { cwd: "", write_scope: [] }, main = false) {
    const row = document.createElement("div"); row.className = "workspace-row";
    row.innerHTML = `<label>${main ? "主项目" : "工作目录"}<input value="${esc(g.cwd)}" required ${main ? "readonly" : ""} placeholder="已存在的工作目录绝对路径"></label><label>允许写入的相对路径<textarea rows="2" placeholder="例如 skills/godot-tech；留空为整个目录">${esc(g.write_scope.join("\n"))}</textarea></label>${main ? "" : '<button type="button" class="ghost" data-remove-workspace>移除此目录</button>'}`;
    row.querySelector("[data-remove-workspace]")?.addEventListener("click", () => { row.remove(); updateChangeNote(); });
    row.addEventListener("input", updateChangeNote);
    $("task-workspace-rows").append(row);
    updateChangeNote();
    return row;
  }
  function updateChangeNote() {
    $("task-change-note").textContent = !formTarget ? "这是首次目标确认；草案可以继续修改。"
      : $("task-form-target").value.trim() === formTarget.trim() ? "正式目标未改变；请核对预算。"
      : "目标将发生变更：上方是当前正式目标，下方是本次草案，确认后才会替换。";
    $("task-workspace-note").textContent = JSON.stringify(readWorkspaces()) === JSON.stringify(formWorkspaces)
      ? "目录授权未改变；已确认的范围可直接复用。"
      : "目录或写入范围将发生变更：只有确认后才生效，旧的排队工作将取消。请同时核对目标中的分工约定。";
  }
  function updateFormAvailability(t) {
    const stale = t && (t.draftRevision || 0) !== formRevision;
    const busy = t && (t.hostBusy || Object.values(t.workers).some((w) => ["running", "sending"].includes(w.state)));
    const active = t && ["running", "waiting", "review", "closing"].includes(t.status);
    $("task-save").disabled = $("task-confirm-only").disabled = Boolean(stale || busy || active);
    $("task-save-draft").disabled = Boolean(stale || t?.status === "closing");
    $("task-confirm-hint").textContent = stale ? "草案刚刚更新了，请关闭并重新打开，查看最新内容后确认。"
      : busy ? "还有回合未结束，可以先保存草案；等它们返回后再确认。"
      : active ? "任务正在执行；请先保存草案或暂停，再确认变更。"
      : "确认将保存这里显示的完整目标、目录授权和预算。只存草案不会启动，也不会替换正式目标。";
  }
  async function operate(action, args = {}) {
    if (!selected) return;
    const result = await api("/api/tasks/" + action, { task_id: selected, ...args });
    await refresh();
    renderPanel();
    return result;
  }
  async function artifacts() {
    inspecting = selected;
    const value = await api("/api/tasks/artifacts", { task_id: inspecting, action: "list" });
    $("artifacts-info").textContent = `${value.count || 0} 个文件 · ${number(value.bytes)} 字节${value.truncated ? "（仅显示前 200 项）" : ""}`;
    $("artifacts-list").innerHTML = value.files.map((f) => `<label class="artifact-row"><input type="checkbox" value="${esc(f.path)}"${f.symlink ? " disabled" : ""}><span>${esc(f.path)}<small>${number(f.bytes)} 字节${f.symlink ? " · 符号链接，禁止清理" : ""}${f.retained ? " · 保留：" + esc(f.retained) : ""}</small></span></label>`).join("") || '<p class="hint">没有待处理的临时文件。</p>';
    $("artifacts-reason").value = "";
    $("artifacts-error").textContent = "";
    if (!$("artifacts-dialog").open) $("artifacts-dialog").showModal();
  }
  function wire() {
    $("new-controller").onclick = () => showForm();
    $("task-reports").onclick = (e) => {
      const button = e.target.closest("[data-report-thread]");
      if (button) openThread(button.dataset.reportThread);
    };
    $("task-form-target").oninput = updateChangeNote;
    $("task-add-workspace").onclick = () => {
      if ($("task-workspace-rows").children.length >= 12) return toast("最多 12 个工作目录", true);
      addWorkspace().querySelector("input").focus();
    };
    $("task-deadline").oninput = $("task-duration").oninput = updateTimeInputs;
    $("thread-list").addEventListener("click", (e) => {
      const project = e.target.closest("[data-project]");
      if (project) {
        projectOpen.set(project.dataset.project, project.getAttribute("aria-expanded") !== "true"); save(); refresh(); return;
      }
      const expand = e.target.closest("[data-task-expand]");
      if (expand) { const id = expand.dataset.taskExpand; if (!taskOpen.delete(id)) taskOpen.add(id); save(); refresh(); return; }
      const task = e.target.closest("[data-task]");
      if (task) {
        const t = data.tasks.find((t) => t.id === task.dataset.task);
        taskOpen.add(t.id); projectOpen.set(`tasks:${t.cwd}`, true); save();
        if (t.host) openThread(t.host); else toast(t.note || "中控尚未创建成功", true);
      }
    });
    $("task-resume").onclick = () => showForm(data.tasks.find((t) => t.id === selected));
    $("task-pause").onclick = async (e) => {
      e.target.disabled = true;
      try { await operate("pause"); } catch (error) { toast(error.message, true); } finally { e.target.disabled = false; }
    };
    $("task-remove").onclick = async () => {
      if (!confirm("移除这项任务并归档关联会话？对话和正式项目文件会保留；临时材料未收尾时不会移除。")) return;
      try { const r = await operate("remove"); toast(r.message); } catch (error) { toast(error.message, true); }
    };
    $("task-edit").onclick = () => showForm(data.tasks.find((t) => t.id === selected));
    $("task-back-host").onclick = () => openThread(data.tasks.find((t) => t.id === selected).host);
    $("task-handoff").onclick = () => {
      $("handoff-summary").value = ""; $("handoff-error").textContent = ""; $("handoff-dialog").showModal();
    };
    $("handoff-submit").onclick = async (e) => {
      if (!$("handoff-form").reportValidity()) return;
      e.target.disabled = true;
      try { await operate("handoff", { summary: $("handoff-summary").value }); $("handoff-dialog").close(); }
      catch (error) { $("handoff-error").textContent = error.message; } finally { e.target.disabled = false; }
    };
    for (const button of ["task-save", "task-save-draft", "task-confirm-only"]) $(button).onclick = async (e) => {
      if (!$("task-form").reportValidity()) return;
      e.target.disabled = true;
      try {
        const budget = {};
        if ($("task-tokens").value) budget.tokenLimit = Number($("task-tokens").value);
        if (formRelativeDeadline && $("task-duration").value) budget.deadline = Date.now() / 1000 + Number($("task-duration").value) * 60;
        else if ($("task-deadline").value) budget.deadline = $("task-deadline").value === dateInput(formDeadline)
          ? formDeadline : new Date($("task-deadline").value).getTime() / 1000;
        else if ($("task-duration").value) budget.durationMinutes = Number($("task-duration").value);
        if ($("task-money").value) {
          budget.moneyLimit = Number($("task-money").value); budget.currency = $("task-currency").value;
          budget.rates = Object.fromEntries(["input", "cached", "output"].map((k) => [k, $("task-rate-" + k).value === "" ? null : Number($("task-rate-" + k).value)]));
        }
        const payload = { name: $("task-form-name").value, target: $("task-form-target").value, budget };
        const result = editing ? await api(button === "task-save-draft" ? "/api/tasks/update" : "/api/tasks/confirm",
          { ...payload, task_id: editing, draft_revision: formRevision, workspaces: readWorkspaces(),
            ...(button === "task-save-draft" ? {} : { start: button === "task-save" }) })
          : await api("/api/tasks/create", { name: payload.name, cwd: $("task-cwd").value,
            idea: $("task-form-idea").value, budget, request_id: createRequest });
        $("task-dialog").close();
        await refresh();
        if (result.threadId) openThread(result.threadId); else renderPanel();
      } catch (error) { $("task-form-error").textContent = error.message; }
      finally { if ($("task-dialog").open) updateFormAvailability(data.tasks.find((t) => t.id === editing)); else e.target.disabled = false; }
    };
    $("task-artifacts").onclick = () => artifacts().catch((e) => toast(e.message, true));
    for (const action of ["clean", "keep"]) $("artifacts-" + action).onclick = async (e) => {
      const paths = [...$("artifacts-list").querySelectorAll("input:checked")].map((el) => el.value);
      e.target.disabled = true;
      try {
        await api("/api/tasks/artifacts", { task_id: inspecting, action, paths, reason: $("artifacts-reason").value });
        await artifacts(); await refresh();
      } catch (error) { $("artifacts-error").textContent = error.message; }
      finally { e.target.disabled = false; }
    };
    for (const el of document.querySelectorAll("[data-close-dialog]")) el.onclick = () => $(el.dataset.closeDialog).close();
  }
  return { tree, renderPanel, wire, taskFor, counts(rows) { return { tasks: data.tasks.length, sessions: rows.filter((r) => !taskFor(r.id)).length }; }, attentionCount(rows) { return data.tasks.filter((t) => ["attention", "budget"].includes(t.status) && !rows.some((r) => r.id === t.host && ["approval", "input"].includes(r.status))).length; }, setData(value) { data = value || { tasks: [] }; const t = taskFor(current()); if (t && selected !== t.id) taskOpen.add(t.id); renderPanel(); } };
}
