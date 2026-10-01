# MA4 · 多会话 Codex 工作台

在一个网页窗口里管理本机所有 Codex 会话：看清每个会话在干什么、哪个在等你，直接和干活的 Agent 对话。它是 MA3 的精简重写。

入口 `http://127.0.0.1:8764`，只监听本机。用户服务是 `ma4.service`，随图形会话自动启动。

## 现状与接续

更新于 2026-10-01。

**能用的**

- 会话列表：本机全部 Codex 交互会话按「等你处理 / 运行中 / 新回复 / 置顶 / 其他」分组，显示目录和最后活动时间，支持搜索。
- 对话：历史记录，以及实时的逐字回复、命令和改文件记录。空闲时发送会开始新一轮，运行中发送会插进当前回合，也可以中断。
- 新建会话、改名、置顶，以及「在终端打开」（用 `codex resume` 接入同一会话）。
- 斜杠命令（2026-09-30 加入）：输入 `/` 弹出命令菜单，命令由 MA4 调用对应接口执行，不会当文字发给模型。
  - 已支持：`/rename`、`/compact`、`/model`、`/review`、`/stop`、`/new`、`/status`、`/skills`、`/help`。
  - 不认识的命令会被拦下；以 `//` 开头则把 `/` 当普通文字发送。
- 标题栏显示模型、思考深度、Git 分支、权限模式（会话载入后才有）和上下文用量。
- 运行中的会话在列表和对话里显示已用时间和当前动作（如「执行 npm test」）；在终端里运行的会话也会被自动跟随。每一轮结尾显示开始时间和用时。`/model 模型名 [思考深度]` 从下一轮开始切换。
- 输入 `$` 可以选 Skill。消息里的 `$名称` 会像终端一样作为 Skill 调用，而不只是一段文字。
- 审批请求显示在右侧，可以允许、本会话都允许或拒绝。
- 侧栏：Codex 与 Claude 的额度（5 小时、7 天、Fable 周窗口的已用比例和重置倒计时，每 5 分钟查询一次）、muQ 和 21 点服务的在线检测，以及 muQ、个人主页的链接。
- 标签页标题显示需要你处理的数量，可开启桌面提醒。
- 界面（2026-09-30 美化）：磨砂玻璃风格，浅色、深色可切换，也可以跟随系统（右上角按钮）。
  - 没选会话时显示总览：问候语、需要留意的会话、最近会话。点左上角 MA4 回到总览。
  - 顶部计数可以点，点了就只看「等你 / 运行中 / 新回复」这一类。
  - 会话有彩色头像和状态角标；状态变化时那一行会闪一下；新消息淡入，流式回复带闪烁光标。
  - 系统开了「减少动态效果」时，所有动画关闭。
- 折叠：`config.json` 的 `folds` 按工作目录前缀，把不需要关注的会话收进列表底部的折叠栏（默认收起，展开状态记在浏览器里）。现在配置的是 `MA3/runs/` 下的执行任务。这类会话运行起来、在等你或有新回复时，照常出现在上面的分组里；搜索时不折叠。

**已验证（2026-09-30）**

- 真实模型的新建、发送、流式回复、完成、上下文用量、状态切换，API 和网页各走了一遍。
- 另一个客户端（模拟终端）发起的回合，MA4 能实时看到。
- 三种宽度、深色模式无报错，无横向溢出。
- 34 项 Python 测试、6 项 Node 测试通过。

**没验证或没做**

- 审批按钮只用单元测试验证过。你的 Codex 默认「从不请求审批 + 完全访问」，实测中没有触发过真实审批。终端发起的回合，审批请求会不会也发给网页，还不确定。
- 「在终端打开」会弹出 gnome-terminal 运行 `codex resume`，还没在服务环境里实际点过。
- 斜杠命令只在浏览器里实测了菜单、`/help`、`/status`、`/model` 列表、`/skills` 和拦截未知命令。`/compact`、`/review`、`/model 切换` 以及 `$Skill` 调用只有单元测试，因为实测要在真实会话里消耗模型额度。
- `/model` 的切换只存在后台内存里，服务重启后要重新切。
- 重新登录后服务是否自动启动，还没有实际验证。
- 不做：任务协议、手机访问、网页终端（第二版再议）。中控派发见「中控派发」一节。

**下一步**

先日常用一段时间，收集反馈。和 MA3 的关系见文末。

## 怎么工作

Codex 自带一个共享的 app-server 守护进程（`codex app-server daemon`）：
- 控制套接字：`~/.codex/app-server-control/app-server-control.sock`
- 通信方式：WebSocket 上的 JSON-RPC

终端里的 `codex` 会话也连在它上面，所以 MA4 看到的就是同一条时间线。

| 文件 | 作用 |
|---|---|
| `appserver.py` | 用标准库实现的 WebSocket 与 JSON-RPC 客户端 |
| `hub.py` | 维护连接（守护进程不在时会自动 `daemon start`）、会话列表轮询（3 秒）、订阅、审批、偏好，以及发给网页的事件 |
| `server.py` | HTTP 接口、SSE 事件流、静态页面；只接受本机请求，写操作必须带 `X-MA4-Request` 头 |
| `quota.py` | 额度轮询：解析 quota-detail 格式（Codex + Claude），兼容 MA3 的旧格式 |
| `health.py` | 站点在线检测，每 5 分钟一次 |
| `web/` | 页面：`app.js`、`markdown.js`（先转义再渲染的安全 Markdown）、`style.css` |
| `config.json` | 端口、链接、检测地址、折叠规则（不含密钥） |
| `deploy/ma4.service` | 用户服务，以符号链接装在 `~/.config/systemd/user/` |
| `tools/ui_check.mjs` | 用系统 Chrome 截图检查页面 |
| `deploy/ma4.desktop`、`deploy/ma4-icon.svg` | 桌面启动器：以 Chrome 应用模式打开页面。以符号链接装在 `~/.local/share/applications/`；换 Logo 时要一起更新图标 |

几条设计取舍：
- **背景不用模糊滤镜：** 背景光斑是静态的径向渐变，不用 `filter: blur`。玻璃面板要实时模糊背后的内容，背景再加模糊或做动画，每一帧的渲染开销都会很大。
- **未读判定：** 会话的 `updatedAt` 晚于你上次打开它的时间，且当前不在运行，就算有新回复。第一次出现的会话不算未读。
- **子会话不显示：** 子 Agent 会话和临时会话不进列表。
- **会话的保存：** 会话本身由 Codex 保存，MA4 只存 `.ma4/prefs.json`（置顶、已读时间）和额度缓存。
- **停服务不影响终端：** 服务用 `KillMode=process`。MA4 可能是拉起 Codex 守护进程的那个进程，停掉 MA4 时不能连带杀掉守护进程，否则终端里的会话都会断。

## 运行与维护

```bash
# 服务状态与日志
systemctl --user status ma4.service
journalctl --user -u ma4.service -n 50
# 改了 Python 代码后重启（只改 web/ 下的文件时刷新网页即可）
systemctl --user restart ma4.service
# 测试（不调用模型）
/home/dticpw/conda/envs/py310/bin/python -m unittest -q test_appserver test_hub test_server test_quota
~/.nvm/versions/node/*/bin/node --test test_markdown.mjs
# 页面截图检查（服务需在运行），截图写到 .agent-tmp/ui-check/
~/.nvm/versions/node/*/bin/node tools/ui_check.mjs [会话ID]
```

- **额度来源：** 来源地址存在私有文件 `.ma4/quota-source.json` 里（`{"url": ...}`，权限 600，不进 Git），格式是 HTTH 的 `/api/public/quota-detail?k=…`。地址里带访问口令，不要写进代码、配置或文档。2026-10-01 起不再依赖 MA3 的配置。
- **Codex 升级：** app-server 协议标着 experimental。升级后如果页面顶部显示守护进程异常，或者列表、对话读不出来，先跑测试，再用 `codex app-server generate-json-schema --out <临时目录>` 导出新协议，对照 `hub.py` 里用到的方法。用到的方法有：
  - `thread/list`、`thread/read`、`thread/turns/list`、`thread/resume`、`thread/start`、`thread/name/set`
  - `turn/start`、`turn/steer`、`turn/interrupt`
  - 通知 `thread/status/changed`、`turn/*`、`item/*`、`thread/tokenUsage/updated`、`serverRequest/resolved`
- **本机版本：** 2026-09-30 为 CLI 0.158.0，守护进程 0.159.0。

## 中控派发

另一个 Agent（如 Claude Code）当中控时，可以经 MA4 新建 Codex 会话派活：中控写任务单、审查结果，Codex 实现。会话是普通的 Codex 交互会话，用户在 MA4 里能实时看到过程，也能插话或中断。2026-10-01 首次实际使用（RPGO3dPixel 任务 001）。

**前提**

- 用户已明确同意这次派发，以及执行权限。Codex 按 `~/.codex/config.toml` 的默认设置运行（当前为完全访问、从不请求审批）；需要更严的权限时先和用户商量。显式 `workspace-write` 沙箱里 Godot 等图形程序打不开窗口，无法截图（2026-10-01 实测）。
- 任务单已写进目标项目，执行者没有对话上下文也能读懂：目标、范围、硬约束、交付物、验收方法、不做的事、报告写在哪里。

**步骤**（写操作必须带 `X-MA4-Request` 头）

```bash
# 1. 新建会话并发出第一条消息；返回 {"threadId": ...}
curl -s --noproxy 127.0.0.1 -X POST -H 'Content-Type: application/json' -H 'X-MA4-Request: 1' \
  --data '{"cwd":"<项目目录>","text":"请执行任务单 <路径>……"}' http://127.0.0.1:8764/api/new
# 2. 起一个好认的名字
curl -s --noproxy 127.0.0.1 -X POST -H 'Content-Type: application/json' -H 'X-MA4-Request: 1' \
  --data '{"id":"<threadId>","name":"<项目> · <任务>"}' http://127.0.0.1:8764/api/rename
```

3. 等待：轮询 `GET /api/state`，找到该 `id` 的 `status`（running、approval、input、idle、error、offline 之一）。会话列表每 3 秒刷新，新建后先等它出现在列表里，再判断状态；`approval`、`input` 表示要人处理，`idle` 是这一轮结束，`error`、`offline` 要查原因。间隔 60 秒即可；Claude Code 用后台 Bash 的 until 循环，状态离开 running 时只通知一次。
4. 审查：读任务单里的执行报告、`git status`/diff、截图，必要时亲自运行；把结论写回任务单。
5. 返工或补充要求：`POST /api/send`，内容 `{"id":"<threadId>","text":"……","request_id":"<唯一字符串>"}`。会话运行中发送会插进当前回合。

**边界**

- 派发方负责审查和收尾，Codex 自报「完成」不能代替审查。
- 不对同一工作区并发派多个会话，除非已经划分好文件范围或用了独立 worktree。
- Codex 运行期间，派发方不写它可能改动的同一批文件；补充要求走 `/api/send`。

## 与 MA3 的关系

MA3（`/home/dticpw/PG_linux/MA3`，8763 端口）仍在运行，没有改动。

2026-10-01 用户决定：中控默认经 MA4 派发（见「中控派发」）；只有用户明确说「MA3 的中控」时才用 MA3。停掉 `ma3-workbench.service`、`ma3-control` Skill 的去留、`runs/` 的清理仍待和用户商量，尚未执行。

MA4 取代的是它的日常用途（会话浏览、聊天、额度），不包括它的任务协议。等 MA4 日常够用，再和用户商量：
- 停掉 `ma3-workbench.service`；
- `ma3-control` Skill 怎么处理；
- MA3 的 `runs/`（227M）去留。

重写原因见 2026-09-29/30 的会话。

## 归档

muQ 公开主题 `ma4`：https://muq.koa-ol.com/e/ma4/ （总览、使用手册、技术机制与维护、从 MA3 到 MA4、过程记录）。以后归档续更同一主题 ID，不另建。

## 仓库

私有仓库 `https://github.com/dticpw/MA4`，2026-09-30 首次推送。远程保持 HTTPS 写法（连接时由全局 `insteadOf` 改走 SSH）。`.ma4/` 和 `.agent-tmp/` 不进仓库。

## 文件约定

- 临时输出放 `.agent-tmp/<任务>/`，运行数据放 `.ma4/`，两者都不进 Git。
- 交接只看本 README。任务结束前更新「现状与接续」。
