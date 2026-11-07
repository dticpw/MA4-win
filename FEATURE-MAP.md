# MA4 功能地图

用途：接到改动时，先找到用户流程、负责代码及相关检查。这里只记录当前实现；运行状态、实测结论与接续仍以 [README](README.md#现状与接续) 为入口。检查分组由 [tools/verify.py](tools/verify.py) 维护，不另建测试框架。

先运行 `run map` 核对登记输入是否变化，再选择下面相关流程。最新人工核对范围保存在 [核对记录](validation/feature-map-review.json)，实际结果见 [第三轮验证](validation/shared-source.md#第三轮有限工具优化2026-11-07)。地图提供操作依据，不授予创建真实会话、派工或消耗模型额度的权限。

## 从改动选择检查

以下 `run …` 均指 `tools/verify.py` 的参数；完整命令见后文。多个分组可一起传入，重复模块只执行一次。

| 用户行为 / 改动 | 首先查看 | 检查入口 | 覆盖边界 |
|---|---|---|---|
| 新建会话、消息、历史、审批、Skill | [web/app.js](web/app.js)、[hub.py](hub.py)、[server.py](server.py) | `run sessions --ui` | Python/Node + 模拟页面；原生传输另选 transport |
| 讨论目标、确认目录和预算、派工 | [web/controllers.js](web/controllers.js)、[controllers.py](controllers.py) | `run tasks --ui` | 状态转换、写入协调、预算、目标版本及三种宽度 |
| 报告回传、暂停、重连、交接、统计 | 同上，另看 Hub 的通知处理 | `run tasks sessions --ui` | 包括发送未确认、重复通知、等待原因；不等于真实供应商实测 |
| 文件链接、跨系统路径、启动/停止 | [paths.py](paths.py)、[os_adapters](os_adapters)、[runtime.py](runtime.py)、[desktop.py](desktop.py) | `run sessions platform` | 实际本机与模拟另一系统分开；部分链接测试可能因权限跳过 |
| 服务活动、健康、额度 | [activity.py](activity.py)、[health.py](health.py)、[quota.py](quota.py)、app.js | `run side --ui` | 模拟来源、未知/0/过期语义；不探测真实远端 |
| HTTP/SSE 与原生协议兼容 | [appserver.py](appserver.py)、server.py、hub.py | `run transport` | 启动独立 TCP Codex 后台和本机模拟模型；不连接现有 daemon |
| 浏览器创建、发送、回复和重开历史 | [tools/session_actions.mjs](tools/session_actions.mjs)、[tools/session_cli.mjs](tools/session_cli.mjs)、[tools/ui_check.mjs](tools/ui_check.mjs)、[tools/smoke_test.py](tools/smoke_test.py) | `run live-ui` 或 session_cli | 真实页面/后端/独立原生 CLI，本机模拟模型；不代表真实供应商 |
| 验证命令及地图检测自身 | [tools/verify.py](tools/verify.py)、[test_verify.py](test_verify.py)、[tools/feature_map.py](tools/feature_map.py)、[test_feature_map.py](test_feature_map.py) | `run tooling` | 去重、跳过/失败传播、实例身份、输出范围及地图变化检测 |
| PR 轻量自动检查 | [workflow](.github/workflows/verify.yml)、[开发约定](AGENTS.md)、[PR 模板](.github/pull_request_template.md) | `run ci` | 逻辑/工具测试＋地图检查；无 Codex/浏览器/凭据；详见 [README](README.md#pr-自动检查与同步维护) |
| 地图引用、已核对源码/方法/证据是否变化 | [核对记录](validation/feature-map-review.json) | `run map` | 只读比较；未变化不等于语义正确或全部功能通过 |

<a id="sessions"></a>
## 流程一：创建会话 → 发送 → 回复

**入口及前提：** 普通会话页的“新会话”；工作目录必须真实存在，后台连接正常。空会话不要求立刻发起模型回合。

**用户操作与成功观察：**

1. 点击左栏“＋会话”（`#new-thread`），在“工作目录”填写已存在且获准使用的项目目录；第一条消息可留空。需要发消息时先确认模型调用已获授权。
2. 点击“创建”。会话应在普通会话列表出现并打开；填写了第一条消息时，聊天区显示用户消息，然后出现回复。
3. 等回复完成后回到首页，再点击左栏该会话。检查用户消息和完整回复仍在；刷新后再次检查，不应多出一次发送或重复回合。
4. 失败时先看“守护进程已连接”状态、工作目录、页面错误和真实历史；不要因等待超时直接再点发送。

**自动复验：** `run live-ui` 通过统一动作层先对不存在 cwd 发起一次真实创建请求，确认 HTTP 400 和页面错误、没有新增会话；再创建空会话、发送一次、等待本机模拟回复、列表重开、刷新并读取历史。回合及消息 ID、条数、文本必须一致。独立 `session_cli` 支持不同消息、顺序和本地会话别名；参数见 [README](README.md#普通会话组合动作工具第三轮)。每个 send 必须在计划结束前配对 wait；缺失时 CLI 在启动 fixture 前失败，不自动补动作。direct open 始终重新加载目标 hash 文档，列表 reopen 点击列表；不能以 input 可见推定已切到目标会话。根提供的双会话 16 步组合已通过，见 [跨会话证据](validation/round3/implementation/cross-open/session.json)。重复文本以回合 ID＋消息 ID 对应页面，历史 ID/条数/内容比较不放宽。两者都不接受外部 threadId，修改前复核完整实例身份和本次创建归属，拒绝 8764。意外错误停止且不重发。

| 普通会话现象 | 下一步操作 | 可定位证据 |
|---|---|---|
| 创建报“工作目录不存在” | 保留错误，核对目录后创建；不要把失败算成会话 | [步骤 1 / HTTP 400 与 console](validation/round3/implementation/ui/report.json)、[实图](validation/round3/implementation/ui/01-controlled-failure.png) |
| 消息发出但不确定是否完成 | 先等待和查历史，不重复发送 | report 的 send/wait 步骤、requestId/turnId；[原生历史摘要](validation/round3/implementation/ui/history-main.json) |
| 返回首页或刷新后担心历史丢失/重复 | 列表重开、refresh、history；核对 ID 与条数 | [步骤 5–7](validation/round3/implementation/ui/report.json)、[重开实图](validation/round3/implementation/ui/05-reopened.png) |
| 要验证不同输入或操作顺序 | 用 session_cli 的 --message/--actions，先 create/open/history 再 send | [实际参数](validation/round3/implementation/cli/invocation.json)、[8 步与回收](validation/round3/implementation/cli/session.json) |
| 两轮发送了相同文字 | 按两个回合及各自消息 ID 核对重开/刷新，不以全页文本唯一为前提 | [重复文本实测](validation/round3/implementation/cli-repeated/session.json)、[原始独立验收失败](validation/round3/implementation/repeated-initial/ui/report.json) |
| 检查本身失败 | 看 failed step、pageerror、console、failed request、HTTP error；先定位再重跑相关项 | [首次 SSE 误报](validation/round3/implementation/initial-failure/ui/report.json)、[最终报告](validation/round3/implementation/ui/report.json) |

**本轮证据范围：** Windows / 系统 Chrome headless / Codex 0.167.0；真实页面→MA4 后端→独立 Codex→本机模拟模型，没有模拟 `/api/**` 或错误注入。默认 7 步和独立 8 步各只有一次有效发送，历史 1 回合/2 条消息；1440/1024/390 宽度检查通过，代表错误/重开/窄屏图已查看。回收见 [live-ui.json](validation/round3/implementation/live-ui.json)。Linux、真实供应商、其他浏览器和审批/Skill/插话的真实页面路径未测；默认 live-ui 另用自有会话恢复 Escape 关闭、创建带首条消息、pin、/help、首页和 composer 标签检查，兼容会话另 1 轮，总计 2 次模拟请求；指定计划 CLI 不添加发送。真实任务暂停/恢复由派发方另行验证。

**负责代码与接口：**

1. `POST /api/new` → `Hub.new_thread`：建立会话；UI 保存返回的元数据，列表/SSE 延迟到达时仍能打开、改名和发送。
2. `POST /api/open` + `GET /api/history` → `Hub.open/history`：打开记录；空会话尚无持久化历史时按既有规则延迟订阅。
3. `POST /api/send` → `Hub.send/send_raw`：空闲时开始新回合，运行中向当前回合补充消息；同一 `request_id` 不重复发送。Skill 必须由用户显式选择，正文出现名称不算附件。
4. `GET /api/events` → `Hub.on_notification/events_after` → app.js：流式展示回复、状态、审批和工具结果。断线后重新读取状态；旧列表不能覆盖更近的真实会话时间。

**重要区别：** `idle` 只表示这轮结束；不能由此推断任务目标完成。实际发送会调用模型并写入该系统的原生会话，普通会话权限不继承中控的额外设置。

**可重复检查：** `run sessions --ui` 包含 `test_hub` 的空会话、发送去重、权限、Skill、活动时间与重连用例，`test_server` 的 HTTP 边界，`test_markdown.mjs` / `test_paths.mjs` 和两组模拟页面。需要验证实际 RPC/SSE、插话/中断/重连时，另跑 `run transport`。它们与 `run live-ui` 的覆盖互补。

<a id="tasks"></a>
## 流程二：讨论目标 → 用户确认 → 派工

**入口及前提：** 中控任务页创建项目任务，先讨论目标；有完整目标并经用户确认后才允许自主推进。

**代码分工：** [任务控制边界](ARCHITECTURE.md)说明 `task_policy.py` 的纯判断、Controllers 的状态变更/发送，以及 Hub 的会话访问。新规则直接用任务快照和明确时间测试；不要把 RPC 或文件读写放入规则层。`run tasks architecture` 覆盖行为与依赖方向，`run ci` 自动包含两组。

**用户操作与成功观察：**

1. 点击“＋中控”，填写任务名、真实项目目录和初始想法，点“创建并进入讨论”。应进入目标讨论，不能因为创建就开始自主派工；讨论本身仍可能调用模型。
2. 与中控讨论后，点击“确认目标并启动”或“查看并确认后继续”，逐项检查目标、工作目录、可写范围、预算和期限。
   任务诊断会说明尚在进行的工作和下一步责任人；打开确认表单不会自动续期或发送消息。发送未确认、回合未结束、交接中、连接未恢复或执行者状态未知时，确认操作会显示阻碍原因。未知状态须先核对对应会话与任务记录，不能确认保存、确认启动或直接恢复；“只存草案”仍按原规则可用。
3. 需要继续编辑时选“只存草案”；只确认而暂不执行选“确认保存，暂不启动”；已明确授权执行才选“确认并启动”。若出现草案已更新提示，关闭表单再打开，核对新内容。
4. 允许启动后观察任务状态、执行会话、实际工作目录和排队原因。目标仍是已确认版本；重叠写入不得同时启动。执行者出现不等于任务已完成。

**自动复验：** `run tasks --ui` 检查目标确认、预算和排队逻辑，并用模拟数据操作真实页面组件。预期三种宽度的讨论/确认流程通过；未经确认、过期草案和超范围写入被拒绝。

**证据范围：** Windows 逻辑与模拟页面覆盖沿用原记录。2026-11-07 第三轮另经明确授权，在真实 8764 用 HTTP create/confirm 启动一个中控和一个真实模型执行者，完成三轮实现/定点返工；目标、预算和目录授权保持，原四任务不变，见[真实调度证据](validation/round3/control-live.json)。这不代替页面“讨论→确认”整条路径实测。地图不授予真实派工权限，仍按 [README 中控派发](README.md#中控派发兼容直接-http-调用) 取得相应授权。

**负责代码与接口：**

1. `POST /api/tasks/create` → `Controllers.do_create`：建立任务及中控，初始想法进入讨论，不直接等同目标确认或自动派工。
2. `/api/tasks/update` / 中控目标建议 → `stage_draft`：暂存目标、预算、工作目录与可写范围；保留版本号。
3. `/api/tasks/confirm` → `Controllers.do_confirm` → `task_policy.confirm_blocker`：页面与后端共用确认阻碍说明；后端仍按提交字段校验草案版本、完整目标、授权与预算。过期版本不能覆盖新草案，也不能暗中扩大授权范围。普通聊天不替代确认或恢复。
4. `ma4_dispatch` → `dispatch/can_launch/launch`：检查预算和已授权目录、相对写入范围；重叠写入排队，不重叠才可并行。正式发送前再检查期限和路径。执行会话使用所属项目临时目录。

**重要区别：** MA4 的写入排队只协调它管理的任务，不约束外部终端，也不是操作系统沙箱。默认两小时从首次启动计时；暂停、重连和交接不能自动重置预算。时间到期收尾与 token/金额硬上限的处理不同。

**可重复检查：** `test_controllers` 的创建不能启动、明确确认、过期版本、跨目录授权、冲突排队、临界时间派工与恢复用例；`test_controllers.mjs`；`controller_discussion_check.mjs` 的目标、权限、预算确认和三种宽度。

<a id="reports"></a>
## 流程三：执行结束 → 报告回传 → 恢复 / 验收

**入口及前提：** 执行者回合完成事件；用户从任务卡的报告等待提示、执行会话及中控聊天查看进度。

**用户操作与成功观察：**

1. 在“中控任务”中选中任务，查看执行会话状态和报告等待提示；打开执行会话读取实际输出和工具失败详情。
   先看任务诊断的状态、工作数量与下一步，再展开“判断依据”。“中控空闲、执行者仍在工作”不等于任务停住；“已暂停”仍可能有未结束回合，可使用“停止在途回合”，并等待实际结束确认。
2. 报告尚未回传时，先按页面给出的原因处理：连接异常、中控忙、任务暂停、预算到期或交接中。不要手工重复转发来“催一次”。
3. 暂停或需要确认的任务，使用“查看并确认后继续”核对目标和预算后再继续；普通聊天不会自动恢复。预算已到期时必须由用户明确调整。
4. 中控收到报告后仍需检查实际产物和验证证据。只有明确记录目标达标才算通过；执行者空闲、收到报告或中控停止输出都不能代替验收。

**自动复验：** `run tasks --ui` 验证报告仅回传一次、忙时等待、暂停保留、发送结果不确定时先核对，以及模拟页面上的等待原因、失败详情和统计；Hub/通知相关改动再加 `sessions`。

**证据范围：** Windows 逻辑与模拟页面覆盖沿用原记录。2026-11-07 第三轮真实任务的三份执行报告按会话/回合 ID 核对，均自动回传且恰好一次；实际暂停后恢复同一目标、期限和执行者，成果保持，未重复派工，最终 completed。状态与请求证据见[真实调度记录](validation/round3/control-live.json)。暂停发生在执行者空闲、报告均已回传后；在途暂停、断线恢复和中控交接仍未实测。

**任务诊断（分阶段优化·阶段 1）：** [本轮验证记录](validation/task-diagnosis/evidence.json)覆盖过期交接、在途暂停、发送未确认、断线/恢复、终态、草案及当前中控失败辨别；确认续期保留目标、目录、执行者与任务身份，只发送一次接续消息。页面在 1440/1024/390 宽度、浅深主题验证，并保持实时更新时的键盘焦点和表单输入。RPG 实际状态只读抽查已从此前的过期交接变成“一名执行者在运行”，不能沿用旧判断；没有为实验恢复或续期它。2026-11-07 已通过既有入口仅重载 Windows web，五任务保护字段和 10 个载入会话保留；真实 RPG 已达标页面的三种宽度、键盘及只打开确认表单通过，见[在线验证](validation/task-diagnosis/online.json)。没有恢复任务、续期或调用模型，其他实机边界见 README 最新状态。

**负责代码与接口：**

1. `Controllers.event/complete_worker`：按执行会话和回合 ID 去重，把最终摘要、错误和来源放入已有 `pending` 队列；不是新增一份历史数据库。
2. `report_delivery`：根据连接、任务状态、预算、中控是否忙、交接及待确认发送，给出报告尚未回传的原因。暂停时保留报告，普通聊天不会恢复任务；其他任务写入不阻挡报告接收，但会影响相关文件能否验收。
   规则实现位于 `task_policy.py`，Controllers 保留委托方法以兼容已有调用；连接状态与当前时间经 `RuntimeState` 传入。与拆分前实现的固定样本对照、不可变输入测试及编排回归见[规则拆分验证](validation/task-policy.json)。
   `diagnosis` 从同一状态推导任务说明，随 `publish` 的快照/SSE 以及 `ma4_control(action=status)` 提供；复用既有核对周期刷新时间相关状态，不另存诊断历史、不增加轮询或自动修复。`confirm_blocker/handoff_blocker` 同时用于页面提示与后端操作检查；直接 `/api/tasks/resume` 也检查连接恢复、在途、交接、未知执行者和推进状态，不能绕过确认路径的这些限制。预算仍须用户明确调整。
3. `tick/send_host`：条件满足时回传；`outbox` 保存正在确认的发送。`reconcile` 在重连后检查已发标记，避免“结果不确定就重发”导致重复执行。
4. 中控检查实际产物，再通过 `ma4_control` 明确记录达标或未达标；`do_handoff/perform_handoff` 保留同一任务、执行者与预算，把摘要交给新中控。

**重要区别：** 执行者自报完成、中控回合结束、报告已送达和目标通过验收是不同状态。长报告可能截断，完整内容仍须回到执行会话和实际产物核对；新中控不是跨系统复制原生会话。

诊断只解释已有状态。断线时工作数量是最后记录；只对时间顺序可靠的当前中控记录说明最近失败，不把前任错误、旧失败或无输出时间当成当前根因。缺少证据时提示人工核对，供应商故障和语义上的“没有进展”仍需查会话及产物。

执行者状态不属于 `running/sending/queued/idle` 时，始终列出待核对事实并阻止确认/恢复；不把未知值改成空闲或故障。控制异常、断线/核对、发送未确认、收尾/交接、终态、已知在途停止和预算等较高优先级说明保留；终态有未知执行者时不声称没有在途回合。其他情况优先显示“有执行者状态待核对”，保存草案仍沿用原规则，交接与调度策略不变。`test_task_policy` 与 `test_controllers` 的回归、旧实现失败及 Windows 本地检查见 [独立维护验证](validation/cold-start.json)；没有加载服务或访问真实任务。

**可重复检查：** `test_controllers` 的一次回传、忙时等待、暂停保留、发送回复丢失、重启恢复、交接和明确验收用例；`test_hub` 的相关通知与权限；`controller_details_check.mjs` 的等待原因、工具失败详情、统计、收尾状态及实时更新。

## 验证入口怎么用

在项目目录运行；也可用绝对脚本路径从其他目录调用，入口会固定子进程的工作目录为源码根目录。

```powershell
# Windows：列出检查；预览任务检查会执行哪些命令（不运行）
& 'D:/python/anaconda/envs/th123/python.exe' -B -X utf8 tools/verify.py list
& 'D:/python/anaconda/envs/th123/python.exe' -B -X utf8 tools/verify.py plan tasks --ui
# 执行所选功能的逻辑和模拟页面检查；临时输出退出时自动清理
& 'D:/python/anaconda/envs/th123/python.exe' -B -X utf8 tools/verify.py run tasks --ui
# 真实页面链路，保留本次证据；checks 必须尚不存在
& 'D:/python/anaconda/envs/th123/python.exe' -B -X utf8 tools/verify.py run live-ui --output .agent-tmp/<本任务>/checks
# 只读检查地图是否需要复核，不启动浏览器或后台
& 'D:/python/anaconda/envs/th123/python.exe' -B -X utf8 tools/verify.py run map
```

```bash
# Linux：使用同一入口和参数
/home/dticpw/conda/envs/py310/bin/python -B -X utf8 tools/verify.py run tasks --ui
/home/dticpw/conda/envs/py310/bin/python -B -X utf8 tools/verify.py run live-ui --output .agent-tmp/<本任务>/checks
/home/dticpw/conda/envs/py310/bin/python -B -X utf8 tools/verify.py run map
```

将 `<本任务>` 换成自己的任务目录名。Linux 命令是对应入口，第二轮尚未在 Linux 实机运行。

`core` 合并 sessions/tasks/side/platform/tooling，`--ui` 才加跑五个模拟页面脚本；不包含 transport、live-ui、map 或图片预览。适合入口首次验收或确实跨模块的改动；小改先选择相关分组，必要时直接用原测试命令定位到具体用例。不为每个小改重复全量运行。

`transport` 单独选择，运行现有 `tools/smoke_test.py`，会启动独立 CODEX_HOME、随机本机 TCP 后台和模拟模型，结束后关闭自己创建的进程。不调用真实供应商、不读取用户会话凭据、不使用 `--serve`；它不包含在 core 中。

页面检查复用现有 Node、系统 Chrome 和 Playwright 缓存。`--ui` 使用仅开放生产静态资源白名单的临时服务；`live-ui` 则启动完整隔离 MA4 后端并调用 `tools/ui_check.mjs --exercise`。二者都覆盖外部实例设置，不连接 8764。缺少依赖即失败，不自动安装。不要用会创建真实空会话的 `controller_ui_check.mjs` 代替这些入口。

需要审查截图或定位失败时，增加 `--output .agent-tmp/<本任务>/checks`，保留 `result.json`、各检查日志及截图。目录必须全新且属于本项目临时区，拒绝覆盖已有材料；默认临时输出自动回收，不生成长期历史目录。显式保留的材料由本任务验收后清理或转正。结果区分 passed / passed_with_skips / failed / not_run；Python 的数量和跳过数写入结果；Node 固定使用 TAP 输出，记录总数、通过、失败、取消、跳过与待实现（todo）数量。部分跳过或待实现标记 passed_with_skips；零项测试、Node 缺统计或全部跳过/待实现判失败，具体原因见日志。Node 把空文件视为一个文件级测试，入口沿用其统计语义，不把文件内断言数当作完备性证明。首个检查进程失败后不再执行后续项，先定位失败，再跑所需分组。

图片预览的 `test_model_image_preview` 需单独获准的任务目录及真实归属标记；沿用 专项工具自身说明和授权要求，不自动 discovery、不伪造标记。Linux 实机、真实模型/线上任务、外部事件和远端发布均不能由这里的模拟测试推断通过。

## 改动时怎样保持有效

开发 Agent 在同一改动/PR 中同步维护受影响的地图、测试和验证方法；无需修改时说明依据。PR 更新后 CI 执行 `run ci`，发现测试失败、失效引用或登记内容变化就失败，不自动改写材料。完整触发条件和检查边界见 [README](README.md#pr-自动检查与同步维护)。

- `run map` 检查本地图本地链接/锚点、三个流程的操作说明，以及核对记录中登记的源码、验证方法与证据的 SHA256。`current` 只表示这些输入未变化；`needs_review` 表示相关内容变了或核对记录不全；`invalid` 表示引用/记录有问题。后两者使统一入口失败，详细原因在 map.json 和日志中。
- 它不检查外部网页是否可达，不自动理解文档语义，也不能发现未登记的间接依赖或运行环境变化；CLI/浏览器/系统升级后即使 current，也要按影响复验。引用存在不证明描述正确，人工仍需核对操作和代码。
- 更新流程：先读变化源码及用户入口 → 修正本地图 → 运行受影响检查 → 核对实际结果并将必要证据转入 validation → 人工更新 `validation/feature-map-review.json` 中对应流程的说明摘要、输入摘要、源码核对时间、证据摘要、覆盖与未测项 → 再运行 `run map`。不得仅刷新摘要消除提示；工具没有自动“更新为通过”的开关。
- 只有逻辑/模拟页面覆盖的流程也可登记“描述已核对”，但 coverage 和 unverified 必须保留真实范围；不能将 tasks/reports 写成真实全链路通过。`run tooling` 用临时小项目检查引用失效、源码/说明/证据变动能被发现，并验证恢复内容后状态正确、核对记录不被改写。
- 用户行为或接口变了：同步本地图相关流程和负责代码；测试分组变了：只改 verify.py 中的选择表，再运行 `run tooling`。
- 重复故障先补复现检查，再修代码。现有目标确认、发送去重、预算和写入范围由程序执行；临时材料要求保留在既有管理工具中，不另叠提示词文件。
- 跨系统差异继续放在 os_adapters/ 与系统配置，不拆公共业务副本。运行改动选 platform；另一系统没实测就明确留待检查。
- 相关审查顺带看重复逻辑、错误状态、输出增长和失效说明；只整理本次触及且有实际收益的部分。第一轮不新增固定“代码园丁”、定时扫描或外部事件自动派工。

维护代价是这张地图、少量已登记摘要和薄的命令入口；只在功能或验证条件变化时按需复核，不定时全量扫描、不为每次运行保存完整副本。是否继续扩展自动约束，应以真实重复错误和手工耗时为依据。
