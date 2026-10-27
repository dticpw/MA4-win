# MA4 Windows

## 现状与接续

更新：2026-10-27。项目位于 `E:/PG/MA4-win`，Linux 可读路径为 `/mnt/e/PG/MA4-win`。

2026-10-27 实施清单待确认：按用户要求整理 [Windows MA4 功能追平清单](WINDOWS-PARITY-PLAN.md)，列出源码交付、原生后台接入、功能补齐、Windows 差异、分层验收和收尾；单列后台方式、启动/退出、登录自启、代码维护与真实模型验收额度的推荐选择。当前仅准备文档，尚未批准这些选择或开始移植；用户确认后按清单推进，进度仍在本节维护。本轮只新增清单并更新两边 README，没有代码、配置或服务变更。

2026-10-27 Windows 运行条件调查已完成（跨系统看板 `B-20261027-01` 已记录关键命令结果与限制）：**原生共享 daemon 0.164.0 可以通过 Codex 自带 proxy 从 th123 接入；Windows MA4 尚未接入此路径，功能移植尚未开始。**

- **本次实测：** PATH CLI、MA4 发现器选用的 npm exe 均为 0.164.0；原生 daemon PID 13064（18:29:53 启动）的 version 与实际 initialize 均返回 0.164.0。控制端点为 `C:/Users/DTICPW/.codex/app-server-control/app-server-control.sock`。th123 3.10.19 虽然 `AF_UNIX=False`，但通过 `codex app-server proxy --sock <控制端点>` 的 stdin/stdout 承载 WebSocket，完成 101 握手、initialize/initialized、thread/loaded/list 与当前会话只读 metadata 查询；当前会话在此后台载入。短时代理已正常退出，用户既有后台保持运行。
- **当前未运行项与连接限制：** 8764/8765 无监听，MA4 的 `/api/state` 未测；现有配置仍指向 TCP 8765。桌面 App 私有默认 stdio 子后台 PID 29672 的磁盘 exe 为 0.164.0-alpha.11.1，未接管其 stdio 查询运行版本。已有普通终端 PID 31320 的具体后台连接未确认；其 7563 HTTP 端点返回 401，未取用凭据或绕过认证。不能宣称普通终端、App、MA4 已全部共享同一后台。
- **协议与下一步：** 0.164.0 实验协议定义具备 dynamicTools、item/tool/call、thread/settings/update、tokenUsage 通知及历史分页。本轮只验证定义与只读连接，未发模型任务或调用设置更新。建议后续保留 Windows 适配，集中修改传输/启动层以接入原生 daemon，再逐项合入 Linux 功能；当前 `runtime.load_config` 只接受 Windows TCP，`appserver.WebSocket` 直接 Unix 分支受 AF_UNIX 限制，启动器准备独立 8765 后台，不能只改配置地址。后台未运行时的启动策略、是否保留 TCP 为可选连接方式与统一代码维护结构尚未决定。本轮不改实现、不安装自启。
- **实施前缺口：** Linux 当前源码及未提交修复仍在 ext4，尚未交付；应由 Linux 侧核对本次调查后安排准确代码交付。真实模型派工、三端共享、Windows 路径/文件占用及完整功能验收仍留待实施。10 月 10 日 TCP + --remote 的模拟回复证据只作为历史依据。
- **本轮文件：** 正式修改仅本 README 与看板；临时查询脚本经 stdin 运行，未保存对话。协议生成目录 `.agent-tmp/B-20261027-01/schema-0.164.0/` 共 458 个 JSON、4,530,741 字节，已核验 Git 忽略，无正式依赖。清理被自动审批以 `blocked by policy` 拒绝，未给具体原因，未重试删除；保留该批临时定义，待允许清理或用户手动处理时复核后删除。未新增备份、打包、定时或同步机制，未动其他任务材料。

2026-10-27 Windows 旧待办检查：用户先要求处理全局指令加载与 Playwright 扩展验收，详见跨系统看板 `B-20260927-01` / `B-20260908-03` 的同日记录。persona-sync 报告 22/22，但 Linux 两份来自 10 月 10 日的过期快照；Codex 的 Chrome 标签页授权与哔哩哔哩登录态读取已实测通过，Claude Code 新会话因服务端 403 未完成两项实机验证。两条按看板规则移入已完成，不表示两端验收全部通过。该次旧待办检查结束时，MA4 运行条件调查及功能移植均未开始；之后的调查结果见上方记录。仅更新本节、看板及对应机器状态记录，检查器刷新既有 persona 快照；未改项目源码或客户端配置，未创建持久会话或定时机制。浏览器工具自动生成的 6 个页面快照/日志共 94,238 字节，精确删除被自动审批以 `blocked by policy` 拒绝，未给具体原因；已移入被 Git 忽略的 `.agent-tmp/board-older-checks-20261027/` 暂存，待允许清理或用户手动处理时复核后删除，无正式依赖。原 `.playwright-mcp/` 生成目录现为空；没有重复尝试删除，旧任务材料未动。

2026-10-27 Linux → Windows 接续：用户希望本项目追平当前 Linux MA4，并要求通过跨系统看板传达下一步。当时安排 `D:/Linux_share/agent-board.md` 的 **B-20261027-01** 调查；本次 Windows 已完成运行条件核实，结果见上方同日记录，下一步由 Linux 核对并交付当前代码。本轮只安排运行条件调查，尚未开始功能移植；下方 10 月 10—11 日记录为历史验证。Linux 已看到 Windows npm 包为 0.163.0 及后台端点文件，不能沿用旧版不可用结论，也不能凭文件存在宣称可用。当前 Windows 已有首版及大量未提交成果，须原位保留；缺少当前 Linux 的中控与服务活动模块。Linux 当前源码在 Windows 不可见的 ext4，并有未提交修复，本次未导出或打包，实施前另安排精确交付。该次 Linux 接续仅补充两边 README 与看板，未改程序/配置、启动服务、安装依赖或创建临时产物；后续 Windows 调查与临时文件情况见上方记录。

**Windows 首版已实现。** 保留 MA4 原有界面、会话逻辑和测试，用本机 TCP WebSocket 连接一个独立运行的 Codex app-server；网页和显式使用 `--remote` 的终端共享同一会话及运行事件。当前完成隔离环境验收，尚未验证真实模型和实际命令执行全流程。

本次没有安装依赖、自启、系统服务或计划任务，没有升级 Codex、修改 Codex 全局配置或推送远程。测试服务已停止；现已提供无地址栏的独立应用窗口，启动方式见下文。

上游：[dticpw/MA4](https://github.com/dticpw/MA4)，导入提交 `3ce173f5b0b5bdb8be71dfa639c2a2e000241f1f`。本地 Git 的 `upstream` 使用 HTTPS，改动尚未提交。原 Linux 启动文件保留于 `deploy/`，Windows 不使用它们。

2026-10-11 会话占用排查：用户已实测，独立 CLI/App 占用会话时 MA4 发送返回 `already has an active writer`，退出原客户端后可以继续。此错误是会话写入冲突，不表示 MA4 的沙箱或审批权限更低。已将该错误改为 HTTP 409 与中文处理说明，并修正“未载入”提示，避免暗示所有历史都可立即接入。会话与 HTTP 回归 **30/30** 通过，`node --check web/app.js` 通过。测试确认占用时不发起模型回合，失败不缓存为成功，释放后可在同一个 Hub 中直接重试，无需重新打开会话；这是模拟后台验证，用户观察到的退出后等待时间/切换现象尚未实机定位。占用提示已随下方图标更新重启网页服务而生效；Codex 后台保持运行，既有页面文案需刷新窗口。此次修改仅涉及正式源码、既有测试与本说明，没有新增临时材料、备份或定时机制。

2026-10-11 图标已复用 Linux 仓库原图 `deploy/ma4-icon.svg`：替换了网页原来的纯蓝色 favicon，并生成含 16–256 像素九种尺寸的 `deploy/ma4-icon.ico`。本机项目根目录的 `MA4.lnk` 使用此图标，仍指向原有 `启动MA4.cmd`。已核对快捷方式目标与图标路径、ICO 各尺寸、浅/深背景表现、实际网页图标响应及 Chrome 解码；HTTP 回归 **6/6** 通过。已重启本入口创建的网页服务，确认共享 Codex 后台进程身份不变；旧窗口需刷新或重新打开。原生任务栏的最终图标/缓存刷新尚未截图确认。见 [图标验证](validation/icon.json) 与 [预览](validation/icon.png)。

2026-10-11 23:07 历史显示兼容问题已修复：会话协作产生 `functionCallOutput` 后，MA4 原有 0.149.1 后台进程无法通过 `thread/turns/list(itemsView=full)` 读取两个会话，返回 `failed to deserialize stored thread item`。同一历史在 Codex 0.162.1 后台读取成功；磁盘上的 MA4 启动程序也已是 0.162.1，且与正常后台的程序摘要一致，问题是旧进程尚未退出，并非历史丢失。经用户明确同意，核对启动器记录、进程创建时间、后台无载入会话及无远程终端后，仅重启 MA4 专用后台（PID 824 → 28328）。网页 PID 26760、Codex 自有后台 PID 5908 保持运行；未安装、升级或修改配置。实际网页接口 `/api/state` 返回已连接 0.162.1，`/api/history` 对 daily1011 返回 6 个回合，对“评估 MA4 的 Windows 移植”分两页返回 8 + 7 个回合，三次均 HTTP 200、无错误，原报错项 `fco_01a12b54-e25a-73f0-a0cd-989cc1f8a2fc` 已读出。未取得原窗口截图；若页面仍保留旧错误，刷新窗口或重新选择会话。此次正式文档改动仅 README，启动器进程记录及运行缓存由正常重启/重连更新，无源码变更、内部历史编辑、新增临时文件或备份。此前迁移验收漏查 MA4 的完整历史读取，本次已补验；以后涉及跨版本会话接续，应同时核对运行中版本及消费历史的实际接口，不能只核对磁盘版本。

## 会话归属与工作目录迁移交接

编写时间：2026-10-11 21:24；协作验收：2026-10-11 22:21（Asia/Shanghai）。**状态：会话迁移已完成——原 ID 和历史保留，项目关联及实际 cwd 均已对齐 MA4-win。仅本次临时文件清理被自动审查阻止，保留范围见下文。** 后续仍使用本节接续，不另建第二份交接文件。

### 目标与用户决定

用户希望解决“在 MA5 文件夹下聊天，但实际项目在 MA4-win”的错位，已接受保留项目原位、把会话工作环境对齐过去的建议。用户先决定交由另一个 session 执行，之后明确授权双方直接沟通、合作完成迁移。分工为执行会话操作接口及独占更新 README，原会话只读核查和验收，不并发修改项目文件。

这里的“迁移”指 **Codex 会话的项目归属和实际工作目录对齐**，不是把 MA4-win 源码搬到 MA5，也不是手动搬 Codex 日志、记忆或数据库。优先保留原会话 ID 和历史；不要为目录名称一致而移动整个项目。

| 对象 | 已知位置 / 标识 | 处理原则 |
| --- | --- | --- |
| 需要调整的原会话 | `01a125ac-b184-7b13-ab09-09a2ffe3931a` | 核实身份后调整；不要把执行者自己的会话当成迁移对象 |
| 原会话的工作目录 | 迁移前 `E:/PG/MA5`；验收后 `E:/PG/MA4-win` | 实际默认目录已验证，不是仅修改显示名称 |
| 唯一正式项目 | `E:/PG/MA4-win` | 原位保留源码、Git、运行数据、快捷方式及测试 |
| MA5 目录 | `E:/PG/MA5` | 本次只读清点含隐藏文件，共 0 项；执行时复查，默认保留空目录，不删除 |
| 项目说明 / 长期约定 | 本 README、`E:/PG/MA4-win/AGENTS.md` | 已在正确项目内，无需另搬“记忆文件” |
| Codex 内部历史 / 记忆 / 状态 | 由 Codex 管理，通常在用户级 `CODEX_HOME` 下 | 不因 cwd 为 MA5 就假定它们存在 MA5；不移动、复制或直接修改内部状态文件 |

官方依据：[Codex 本地状态与配置位置](https://developers.openai.com/codex/config-advanced#config-and-state-locations)。项目关联、工作目录和内部历史存储位置是不同概念，不能互相代替。

### 必须保留的当前成果

- `MA4-win` 是 Git 工作区，上游 HTTPS remote 名为 `upstream`，导入提交为 `3ce173f5b0b5bdb8be71dfa639c2a2e000241f1f`。存在大量尚未提交的移植改动和未跟踪的正式文件，均需保留；不能 reset、clean、重新 clone 覆盖或当作临时文件清理。
- 当前架构：MA4 网页 `http://127.0.0.1:8764` 连接独立共享后台 `ws://127.0.0.1:8765`；通过 MA4 打开的远程 CLI 与该后台共享会话。独立 CLI/Codex App 可能持有其他写入权。已见 `already has an active writer`，这是写入冲突，尚无证据表明存在真正的进程死锁。
- 一键入口为 `MA4.lnk` / `启动MA4.cmd`；Chrome 应用窗口无浏览器地址栏。图标已复用 Linux SVG，Windows ICO 和快捷方式已接入。会话占用的中文提示已随网页重启生效。
- `.ma4/` 是当前运行数据，不是可删除的临时目录；其中有启动器进程身份、偏好和额度缓存。`MA4.lnk` 含本机绝对路径，已忽略 Git。由于项目路径不变，这些内容不需要改写。
- 关闭 MA4 窗口只关闭界面；后台可以继续运行。此次调整会话归属原则上无需重启、停止或迁移 MA4 服务。
- 既有测试证据见上文及 `validation/`。最近相关检查为会话/HTTP 30 项通过、图标更新后的 HTTP 6 项通过；它们是不同范围的检查，不能相加称为新的完整测试结果。原生任务栏图标、独立会话释放后的实际等待时机、真实编程任务全流程仍有未验证项，不能在迁移交接时写成已通过。

### 执行步骤

1. **确认本会话已结束当前回复，再操作它。** 用户不应同时让原会话与执行会话修改同一批文件。原会话仍运行或有未处理权限问题时，先完成其他只读核对；不要通过恢复原会话、发送消息、强制解锁或杀进程来取得控制权。
2. **只读核对目标和现场。** 读取本项目 AGENTS 和 README；使用当前客户端提供的会话/项目查询工具核对上述 thread ID、原项目归属、工作目录与运行状态，记录原项目 ID 和 cwd，供必要时恢复。`list_threads` / `read_thread` / `list_projects` 等能力以执行会话实际可用工具为准；不得猜测项目 ID。
3. **保护现有文件。** 复查 MA5 是否仍为空；查看 MA4-win 的 `git status --short`，记录原有未提交改动。无需全量复制或打包。若 MA5 新出现确属本项目的普通笔记，可核对内容和依赖后纳入现有项目文档；未知文件、其他项目资料和 Codex 内部文件保留，不按文件夹名称判断归属。
4. **优先使用受支持的项目管理入口。** 找到根目录确为 `E:/PG/MA4-win` 的项目，再将原会话关联过去。可参考客户端的 `move_thread_to_project` 能力或正常界面入口；先阅读该能力说明。若没有该项目，使用客户端正常的“添加现有文件夹”流程；若该步骤需用户通过侧边栏授予目录访问，只解释这一必要操作，不绕过客户端要求改配置或数据库。
5. **单独核实 cwd。** 项目归属工具可能只改变侧边栏归类，不能据此宣布完成。应从客户端返回的目标会话元数据或该会话下一次正常运行时的环境上下文确认实际 cwd 为 `E:/PG/MA4-win`。执行者自己的 `Get-Location`、给命令传入 `workdir`、改聊天标题，都不能证明原会话 cwd 已迁移。不要为验证而擅自向原会话发送任务。
6. **若当前版本无法修改既有会话 cwd，不进行内部文件手术。** 保留原会话与历史，明确报告已完成与未完成部分。推荐用户以后从 MA4-win 项目打开后续会话，读取本 README 接续；未经用户明确要求，不额外创建或 fork 会话。不能把这一替代方案说成原会话已原地迁移。若正确归类已完成、cwd 尚未改变，应如实标注，而不是继续试改 JSONL/SQLite。
7. **验收并更新本节。** 填写实际采用的客户端操作、目标项目根路径、原会话 ID 是否保持、项目归属和 cwd 各自的证据、历史是否仍可读，以及留下的限制。仅调整客户端元数据不需要重跑模型、真实编程任务或整个测试套件。按文件生命周期技能运行本次文件清点，区分代码/文档改动与 `.ma4` 正常运行产生的变化。

### 操作边界与恢复

- 不移动 MA4-win，不清空 MA5，不更改项目名称，不移动整个 `.codex` / `CODEX_HOME`，不把全局历史或凭据复制入项目。
- 不直接编辑会话 JSONL、SQLite、应用私有状态或手动改会话路径来伪造迁移；不通过另一 app-server 对目标会话调用 `thread/resume` 以尝试抢占写入权。
- 不安装自启/计划任务，不修改 Codex 全局配置、MCP、Skill 或全局指令，不升级 Codex，不 push；不顺手处理其他项目、Linux 服务或 muQ 发布。
- 不停止整个 Codex App 或共享后台来迁移会话。这会中断执行会话或其他工作；若客户端确有额外必要操作，先把具体影响说明白，再由用户决定。
- 如正常项目关联操作失败，先只读核对最终状态，不反复重试未知动作。若确需恢复原关联，通过同一受支持入口恢复到步骤 2 记录的原项目；不通过覆盖内部数据库恢复。不新建持续备份或重复同步机制。

### 完成判定与执行结果

完整完成需要：原会话身份与历史保留、所属项目正确、实际 cwd 已确认是 MA4-win、项目文件及未提交成果未被搬走或覆盖。若只能正确归类或改用后续会话，按实际结果标为部分完成/替代接续，并列出尚未确认的 cwd；不要把“工具调用成功”代替这些证据。

- **执行者 / 时间：** Windows Codex，执行会话 `01a12b3f-6bad-7943-9468-ca162eff0d8f`；21:56–22:00 初次核查，22:09–22:21 经用户授权与原会话直接协作。迁移对象为 `01a125ac-b184-7b13-ab09-09a2ffe3931a`（“评估 MA4 的 Windows 移植”）；执行者自己的目录未变。
- **迁移前状态及早先结论更正：** 缩小 `list_threads` 查询范围后，实际返回 `projectId=null`、`cwd=E:\PG\MA5`。早先查询 40 条时输出被截短，执行者将字段未显示误判为接口不返回，已更正。MA5 已有项目记录 ID 为 `01a125a2-d1c3-73f2-8cde-6467a81feb8e`，但目标会话迁移前没有显式 projectId，不能把这两个 ID 混为一谈。
- **通信与后台：** `send_message_to_thread` 成功双向通信，原会话三轮只读检查分别确认迁移前目录、项目关联后的旧目录、最终新目录。22:09 核查时，8764 网页端口未监听，但 8765 共享后台正常；其 `thread/read` 所见 `notLoaded` 仅表示未在该后台载入，不表示原会话在其他后台未运行。原生界面工具的 `native pipe unavailable` 问题未修复，此次无需界面控制。
- **项目关联操作及证据：** 通过既有 `ws://127.0.0.1:8765` 的公开 `project/list` 核对全部项目，无 MA4-win 后，用 `project/create` 登记现有文件夹 `E:\PG\MA4-win`，得到项目 ID `01a12b50-0451-7c71-9123-c5c540ce1c27`；再用 `thread/metadata/update` 将原会话关联到该 ID。`thread/read` 和原会话独立回读均确认关联生效。项目创建只登记现有目录，没有另建或移动源码目录，MA5 项目记录保留。
- **实际 cwd 操作：** 本机 `codex-cli 0.162.1` 生成的接口定义明确包含 `thread/settings/update.cwd`，含义是覆盖后续回合工作目录。先在 MA4 后台调用时返回 `-32600 thread not found`，回读确认未改目录。随后通过 Codex 自带 `app-server proxy --sock C:\Users\DTICPW\.codex\app-server-control\app-server-control.sock` 连接已经运行的宿主后台；该转发入口承载的是 WebSocket 字节流，须先完成 WebSocket 握手，再发送 initialize/initialized 与 JSON-RPC。`thread/loaded/list` 确认原会话已在此后台载入，`thread/read` 确认其为 idle 后，仅调用 `thread/settings/update`，参数为原 thread ID 与 `cwd=E:\PG\MA4-win`，返回 `{}`。没有调用 `thread/resume`，没有启动、停止或重启 Codex 后台；只创建并关闭了本任务的短时连接代理进程。
- **最终验收：** 设置接口返回后、下一轮开始前 `thread/read.cwd` 仍显示旧值，因此又经获准的直接通信让原会话正常执行一次只读验收。最终回合 `01a12b54-e253-7331-8736-cec02585b86b` 的环境上下文 cwd 为 MA4-win，并加载项目 AGENTS；未指定 workdir 的 `Get-Location`、Python `os.getcwd()` 均返回 `E:\PG\MA4-win`。执行方 `list_threads` 及原会话对公开 `thread/read` 的回读均返回新 cwd 与目标 projectId。最终回合已 completed，原会话为 idle。客户端侧边栏的视觉刷新未截图验证，不影响已完成的元数据及实际运行目录核验。
- **原 ID / 历史保留：** 原 ID 不变，没有创建、fork、归档或改名会话。原会话分页抽查仍可读到迁移前的讨论、图标更新及交接回复；未进行全历史逐字校验。全部修改通过 Codex 公开接口完成，未手动移动、复制或编辑内部 JSONL、数据库或私有状态文件。
- **迁移后 MA4 历史显示补验（23:07）：** 最初只验证了原会话宿主后台和 MA4 的元数据读取，遗漏 MA4 完整历史接口。用户报告旧后台无法识别新增通信记录后，已按上方「现状与接续」完成获准的专用后台重启，并验证两个会话的网页历史接口恢复。项目关联和 cwd 无需回退，未删改通信记录。
- **项目与文件保护：** MA5 含隐藏文件复查仍为 0 项，空目录保留。MA4-win 原位保留，HEAD 为 `3ce173f5b0b5bdb8be71dfa639c2a2e000241f1f`；既有 22 条已跟踪修改和 17 条未跟踪条目保留。Git 已跟踪及未忽略的 50 个文件中，仅 README 交接节由本次修改，其余 49 个摘要不变。原会话只读，双方没有并发写项目文件。
- **文件清点 / 尚待清理：** 正式成果为本 README 同节记录和 Codex 管理的项目关联、会话设置。`.agent-tmp/migration-protocol-20261011-2213/` 内为本次生成的 447 个接口 JSON 加 1 个临时连接脚本，共 448 个文件、4,367,400 字节（约 4.4 MB）；已确认无目录链接、无正式运行依赖。递归清理及缩小为逐文件清理均被自动审查拒绝，工具仅返回 `blocked by policy`，未提供具体理由，因此保留整批，不再尝试绕过。后续自动审查允许清理或用户手动清理时，复核仍仅含这批任务产物后删除；不是长期成果或备份。未新增备份、打包、自启或定时机制，也未修改全局配置、Skill、MCP、其他项目或跨系统旧待办。
- **清点补充：** 已用默认 Python 运行 `session_inventory.py --since 2026-10-11T14:09:20Z --root E:/PG/MA4-win --root E:/PG/MA5`。除 README 和上述临时材料外，还列出 `.ma4/quota-cache.json`、`prefs.json`、`launcher-8986b985940b4105.json` 三个运行数据文件；执行方与原会话均未主动编辑这些文件，保留，不按本任务临时产物清理，启动器文件变化来源未另行追查。工具按名称把 `FeedbackUploadParams.json` / `FeedbackUploadResponse.json` 误标为 backup，实际均为生成的接口定义，不是备份。
- **后续使用 / 恢复：** 可继续使用原会话处理 MA4-win，无需新建或 fork。没有待完成的迁移步骤，只有上述临时材料清理待处理。若用户以后明确要求撤销，用同一公开接口清除显式项目关联（`projectId=""`）并在原会话实际宿主后台将 cwd 改回 `E:\PG\MA5`，随后独立验证；本轮未执行撤销，不通过恢复数据库回退。

## 双击启动（推荐）

双击项目根目录的 **MA4.lnk**（带 Linux 同款图标），或 **[启动MA4.cmd](启动MA4.cmd)** 即可：自动准备共享后台与网页，等待连接成功，再用已安装的 Chrome（缺失时选 Edge）打开独立应用窗口，没有地址栏、标签栏或书签栏。正常启动后命令窗口自动关闭，不需要留两个 PowerShell 窗口。

- 重复点击会复用已运行的实例；并发点击也不会重复创建后台。
- 关闭 MA4 应用窗口后，网页服务和共享后台继续运行；需要重新进入时再次双击。
- 双击 **[停止网页.cmd](停止网页.cmd)** 仅停止本入口创建的网页服务，共享后台与终端不受影响。
- 确认终端会话无需继续后，在项目 PowerShell 中执行以下命令，停止本入口创建的网页及共享后台：

```powershell
./run.ps1 stop -IncludeBackend
```

此停止操作会断开连接后台的终端，请先结束正在执行的任务。通过其他方式启动的后台不会被此入口停止。

一键入口只保存 `.ma4/launcher-*.json` 中的当前进程号和创建时间，停止时核对身份，避免进程号重用后误停其他程序。后台与网页无窗口运行，不安装服务、计划任务或开机自启，也不保存历史进程快照。端口被其他程序占用，或该端口的 MA4 使用其他配置时，会报错而不替换现有进程。

命令行等价入口为 `./run.ps1` 或 `./run.ps1 start`。可加 `-Config <项目配置>`；只启动服务而不打开窗口时加 `-NoBrowser`。双击脚本使用本机既定 th123 Python，不受 PowerShell 脚本执行策略影响。

### 关掉窗口之后

日常不用时，直接点 MA4 窗口的 × 即可。它关闭的是界面，不会停止网页服务或共享 Codex 后台，因此正在运行的任务与终端会话可以继续；再次双击入口即可回来。空闲常驻不会自动发起模型任务，已有会话状态、额度和站点检查仍会按原频率轮询。

Windows 当前为**按需启动、窗口关闭后继续运行**；未安装登录自启、系统服务或故障自动重启。注销或关机后，下一次使用需再双击启动；睡眠期间也不能保证任务继续执行。需要完全退出时，先结束任务，再使用上方 stop -IncludeBackend 命令。

独立窗口复用已安装浏览器的应用模式（与 Linux 的 --app 一致），不安装 Electron、不下载浏览器，也不另建长期浏览器 profile。它隐藏浏览器导航区，但沿用该浏览器现有用户数据；不是一套与浏览器完全独立的渲染程序。

### Linux 服务核查（2026-10-11）

已只读核对远程 HEAD，仍为导入的 3ce173f5b0b5bdb8be71dfa639c2a2e000241f1f。当前可验证的是仓库配置：

- deploy/ma4.desktop 使用 google-chrome --app=http://127.0.0.1:8764；桌面图标只负责打开窗口。
- deploy/ma4.service 是 systemd **用户服务**，WantedBy 与 PartOf 均指向 graphical-session.target；配置意图是随桌面会话运行，与应用窗口开关无关。
- Restart=on-failure 表示服务故障时重启；KillMode=process 表示停止 MA4 网页服务时不连带停止它启动的 Codex 后台。
- WantedBy 配置不能独自证明服务已经 enable；原 README 也写明重新登录后的自动启动尚未实测。不能据此声称它已经验证为全年全天运行。

本机为 Windows/Ubuntu 双启动；当前 Windows 无法读取 ext4 上实际安装的用户服务及其运行状态。本轮没有重启进入 Linux，也不把 WSL 当成该 Ubuntu 系统。尚待实机确认 enable/active、桌面会话目标状态及 Linger。

已提供只读核查脚本，切回 Ubuntu 后运行下面一条命令即可；不需要 sudo，也不会启动、停止或修改服务：

```bash
bash /mnt/e/PG/MA4-win/tools/check-linux-service.sh
```

返回 enabled + active 才能确认当时已启用且正在运行；Linger 表示退出登录后用户服务管理器是否保留，仍需结合 graphical-session.target 的状态判断 MA4 本身。关机时任何本机服务都不会继续运行。

## 分组件手动启动（排查问题时使用）

运行依赖仅 Python 标准库及现有 Codex CLI。本机已验证 Python 3.10.19（th123）和 npm Codex 0.149.1；Node 与现有 Chrome 仅供前端测试使用。

在第一个 PowerShell 窗口中启动共享后台，保持窗口运行：

```powershell
Set-Location E:/PG/MA4-win
./run.ps1 backend
```

在第二个 PowerShell 窗口中启动网页服务：

```powershell
Set-Location E:/PG/MA4-win
./run.ps1 web
```

然后打开 [MA4 本机页面](http://127.0.0.1:8764)。右上角应显示“共享后台已连接”。新建会话时选择实际存在的 Windows 项目目录。

若本机策略不允许运行 PowerShell 脚本，可直接运行相同入口，无需更改执行策略：

```powershell
& 'D:/python/anaconda/envs/th123/python.exe' -B -X utf8 E:/PG/MA4-win/launch.py backend
# 另开窗口运行网页：
& 'D:/python/anaconda/envs/th123/python.exe' -B -X utf8 E:/PG/MA4-win/launch.py web
```

停止网页：在网页服务窗口按 Ctrl+C；共享后台和它承载的终端会话继续运行。
停止后台：确认相关会话无需继续后，在后台窗口按 Ctrl+C；连接它的网页与终端会断开。
启动器只管理自己创建的子进程；发现端口占用会报错，不会终止其他进程。不要直接强制关闭后台宿主窗口来代替正常停止。

### 终端接入

从网页发送过至少一条消息后，可以点击“在终端打开”。它优先使用 Windows Terminal，缺失时打开新的 PowerShell 控制台，始终传入相同共享端点与 thread ID。刚新建、尚无持久历史的空会话不能由另一客户端 resume，网页会提示先发送消息。

也可以手动启动一个连接此后台的新终端：

```powershell
./run.ps1 terminal -WorkingDirectory E:/PG/MA4-win
```

继续指定会话时加 `-ThreadId <会话ID>`。新终端窗口保持打开，退出 Codex 不会停止共享后台。

已经独立启动的 Codex TUI 或桌面 App 不会自动迁入这个后台。同一个 thread ID、相同 CODEX_HOME 或读到历史记录，都不意味着正在共享运行状态。继续旧历史前应先结束原进程对该会话的写入；本项目不接管正在独立运行的会话。

## 连接与配置

```text
浏览器 → MA4 HTTP/SSE（127.0.0.1:8764） ─┐
                                       ├→ Codex app-server（127.0.0.1:8765）
终端 Codex --remote ────────────────────┘          ↓
                                           Codex 自己管理会话
```

`config.json` 只影响本项目。可通过 `./run.ps1 <组件> -Config <文件>` 指定另一份项目配置；后台、网页和终端必须使用同一配置。

| 字段 | 当前默认值与作用 |
| --- | --- |
| app_server | `ws://127.0.0.1:8765`；只接受显式端口的本机回环地址，拒绝公网监听 |
| port | `8764`；网页只绑定 127.0.0.1 |
| codex_bin | `null`；从 PATH 发现 Codex，并将 npm 的 CMD/PS1 包装器解析为同包实际 exe |
| browser_bin | 可选；指定已安装 Chrome/Edge exe 的绝对路径，默认优先 Chrome |
| codex_home | `null`；沿用启动环境的 CODEX_HOME / Codex 默认目录，不修改全局配置 |
| data_dir | 可选；默认项目的 `.ma4/`，保存当前偏好及额度缓存 |
| quota_source | 可选；默认 `.ma4/quota-source.json`，没有来源时显示暂无数据 |
| folds / links / health | 沿用原目录分组、站点链接和五分钟站点检查 |

`codex_home`、`data_dir`、`quota_source` 的相对路径按配置文件所在目录解析。JSON 中路径建议用正斜线；反斜线必须写双份。若指定 `codex_bin`，建议使用实际 exe 的绝对路径。

2026-10-27 发现器实际选用 npm CLI 0.164.0；现有实现与上表配置仍连接独立 TCP 后台，调查时 8764/8765 均未运行。初始化声明 `experimentalApi: true`。原生共享 daemon 已另经 proxy 完成只读连接验证，但该传输尚未接入本项目，不能仅改 app_server 值；详见顶部「现状与接续」。0.164.0 协议定义包含历史分页及中控所需接口，当前版本的完整运行验收仍待后续实施。

模型、鉴权、项目沙箱与审批策略由选定 Codex 后台的有效配置决定，MA4 不强制完全访问或免审批。页面展示的是后台实际返回的权限。新终端可能出现目录信任提示，应按实际项目决定。

额度来源尚未配置。若后续需要接入含凭据的来源，按 credential-vault 流程维护，不能把 URL 或令牌写进 Git、截图或输出日志。现有 chmod 操作不能作为 Windows 文件 ACL 已受保护的证明。

## 复用与适配范围

| 部分 | 实现 |
| --- | --- |
| 原界面 | 保留三栏布局、深浅模式、总览、搜索分组、未读、置顶和动画；适配 Windows 目录显示，补输入标签 |
| 原会话逻辑 | 保留分页、事件订阅、流式内容、start/steer/interrupt、发送去重、模型/Skill、审批和计时 |
| appserver.py | 增加本机 TCP，保留 Unix 连接路径；校验 WebSocket 握手，声明实验能力 |
| runtime.py / desktop.py / launch.py / run.ps1 | 项目配置、npm exe 发现、一键及分组件启动；PowerShell 参数编码处理中文、空格、引号等 |
| hub.py | 移除自动启动 daemon；只连接配置端点；新空会话暂存于内存，短暂空历史有限重试 |
| server.py / quota.py | 保留本机 HTTP 防护和 SSE；处理 Windows 连接中止，文件使用 UTF-8 |
| web/paths.js / markdown.js | 盘符、斜线、Windows 大小写及目录边界；本地文件链接保持不可执行的文字提示 |
| tests / tools | 复用原测试；假 WebSocket 改 TCP，补 Windows 差异测试和真实后台集成检查 |

浏览器验收中还修复了原有的一处交互：命令菜单展开时，直接点击“发送”现在会提交输入。未重写视觉样式。

## 验证结果

2026-10-11 应用窗口改动：**44/44 Python 测试通过**，实际 Chrome 启动后窗口列表显示独立的“MA4”窗口。Computer Use 因无法可靠识别该窗口的当前 URL 而停止；完整窗口截图与点击关闭行为未完成实机验收，不能据此标为已通过。现有关闭窗口不停止后台的实现保持不变。见 [窗口与 Linux 核查记录](validation/app-window.json)。

2026-10-10 首版验收；2026-10-11 增加一键启动检查：

- 原有 Python **40/40**，Node **10/10**，未跳过原有测试。
- 真正的 Codex app-server + 本机模拟 Responses 服务 + MA4 Hub/HTTP/SSE：新建空会话、发送、历史、去重、双客户端流式事件、插话、中断、改名/置顶、断线重连全部通过。
- 真正的 Codex TUI 在 Windows ConPTY 中 `--remote resume` 同一会话：旧历史可见，终端发出的消息及模拟回复能通过 MA4 HTTP 读取。
- `run.ps1 backend/web` 实际启动成功；Ctrl+C 停止网页后后台仍接受 RPC；停止后台后其端口释放。
- 系统 Chrome 检查 1440×900 浅色、1024×800 深色、390×844 浅色；无页面错误、资源错误或横向溢出。实际操作新建、Escape、发送、置顶、帮助命令和总览通过；已人工查看三张截图。

上述集成与界面测试使用独立临时 CODEX_HOME 和**明确标注的本机模拟回复**，没有使用用户凭据或调用真实模型。截图中的额度为空、对话为测试内容。

2026-10-11 的一键入口使用真实 Windows 子进程和隔离配置验证：CMD 入口及中文空格路径、并发重复启动、窗口打开调用、端口冲突、停止网页后后台保留、重启复用、过期进程号保护，以及复用外部后台后不误停。合并原有测试共 **43/43** 通过。见 [一键启动报告](validation/one-click.json)。

当前证据保存在 [validation/](validation/)：
[单元测试](validation/tests.json)、[共享后台](validation/smoke.json)、[终端](validation/terminal.json)、[启动器](validation/launcher.json)、[网页检查](validation/ui/report.json)、[桌面截图](validation/ui/w1440.png)、[深色截图](validation/ui/w1024.png)、[窄屏截图](validation/ui/w390.png)。

### 未验证与边界

- 尚未用真实模型执行实际编程任务；真实命令执行、文件改动与模型调用过程中的审批尚未端到端验证。审批状态机与重复处理防护的原单元测试通过。
- Windows Terminal 图形窗口的点击启动尚未实机验收；已验证命令参数编码及真实 ConPTY TUI 远程接入。
- 未验证独立现有终端/桌面 App 的热接入，不提供此能力承诺。
- 未接真实额度来源；未做长时间稳定性测试；保留的 Unix 代码没有在本轮 Windows 环境做 Linux 回归。

下一次优先从一个专用真实项目会话验证模型、命令审批及“在终端打开”，无需先安装自启或改变全局配置。

## 复现测试

```powershell
Set-Location E:/PG/MA4-win
& 'D:/python/anaconda/envs/th123/python.exe' -B -X utf8 -m unittest -v test_appserver test_hub test_server test_quota test_runtime test_desktop
node --test test_markdown.mjs test_paths.mjs
& 'D:/python/anaconda/envs/th123/python.exe' -B -X utf8 tools/smoke_test.py --output validation/smoke.json
```

集成测试会启动短时本机模拟服务和实际 Codex，结束时停止自己的进程并删除临时数据；不会读取用户会话。测试默认关闭临时 Codex 的 plugins/apps/code_mode_host，避免空配置触发默认插件下载。

需要检查网页时，在一个窗口运行：

```powershell
& 'D:/python/anaconda/envs/th123/python.exe' -B -X utf8 tools/smoke_test.py --serve --port 18764 --output validation/smoke.json
```

另一个窗口读取测试描述并执行 UI 检查：

```powershell
$f = Get-Content -Raw .agent-tmp/ui-fixture.json | ConvertFrom-Json
node tools/ui_check.mjs $f.threadId validation/ui $f.url --exercise
```

`--exercise` 只允许项目临时 smoke 目录，会在其中创建测试会话。脚本使用现有 npm 缓存的 playwright-core 和系统 Chrome，不下载浏览器；可用 MA4_CHROME 指定已有 Chrome 路径。

检查结束，先退出测试 TUI，再在项目内创建 `.agent-tmp/ui-fixture.stop`，测试服务会停止并清理；最多保留二十分钟。不要把临时 CODEX_HOME 用作正式会话目录。

## 文件与维护代价

- 根目录 Python、一键 CMD 入口、`web/`、`tools/`、`test_*`、`run.ps1`：正式源码、启动入口及验证工具。
- `README.md`：唯一当前说明与接续入口；[WINDOWS-CHECK.md](WINDOWS-CHECK.md) 保留最初 B-20261010-01 的日期和原始检查结果，不把后续通过的项目倒写成当时已验证。
- `validation/`：本阶段少量当前测试报告及截图，约 0.7 MB；后续同名覆盖，不建立历史快照。
- `.ma4/`：运行时当前偏好、额度缓存和一键入口进程身份；`.agent-tmp/`：短期试验。两者与 Python 缓存均不入 Git。
- `.gitattributes` 保持文本 LF；`deploy/` 保留上游 Linux 资料及从其 SVG 派生的 Windows ICO，不自动安装。
- `tools/build_icon.mjs` 是手动图标构建工具：运行 `node tools/build_icon.mjs`，使用已有系统 Chrome 和已缓存的 playwright-core 从 SVG 重建 ICO，不安装依赖。SVG 是图标源文件。
- `MA4.lnk` 是本机启动快捷方式，含绝对路径，已忽略 Git；图标源码、ICO、构建工具和少量验证文件作为正式成果保留。本次图标临时渲染与检查脚本已清理。
- 测试产生的隔离会话、失败试验残留和模型服务均由本任务收尾；正式运行不依赖它们。未新增备份、打包或定时机制，未修改 MA5。

主要长期代价是 Codex 实验协议随版本变化，以及终端必须统一连接后台。继续由 Codex 保存会话，MA4 只保存偏好和少量缓存，避免维护第二份完整对话。Windows 差异集中于传输、启动和路径，后续按上游提交审查合并，不定期全量复制仓库。

## 参考

- [muQ MA4 主题](https://muq.koa-ol.com/e/ma4/)、[技术机制](https://muq.koa-ol.com/e/ma4/architecture.html)、[设计取舍](https://muq.koa-ol.com/e/ma4/decisions.html)
- [OpenAI App Server 文档](https://developers.openai.com/codex/app-server)
- 跨系统检查：`D:/Linux_share/agent-board.md` 中 B-20261010-01（已完成）
