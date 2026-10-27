# 共享源码迁移 · 当前验证记录

2026-10-28。Linux 实施、Windows 核心实测及返回 Linux 的针对性回归已完成；保留明确未测项。此文件维护当前结果，不新增每轮历史副本。

## 新实现与证据

- 公共业务来自旧 Linux 回退点 `510fc47`，共享仓库保留原 Windows 回退点 `1fec307` 中的启动器、TCP、路径与 UTF-8 修复。正式源码只在 `E:/PG/MA4-win` / `/mnt/e/PG/MA4-win` 维护。
- 默认传输：Linux `unix://`，Windows `proxy://`（Codex proxy 的 WebSocket 字节流）。`ws://` 为显式本机 TCP 选项；没有自动换后台或全局 Codex 配置改动。
- 178 项 Python 检查中 174 通过、4 项跳过：3 个 Windows 进程启动器集成测试和 1 个真实 Junction 测试。本侧通过的模拟检查涵盖 native 启动器不接管 daemon、停止边界、代理 bytes/超时/回收、TCP 不自动启原生后台、Windows 路径冲突/reparse point、执行文件拒绝和原有中控完整检查。Windows 若无 symlink 权限，相关 symlink 测试会明确跳过；不得称为实测通过。
- 22 项 Node 检查通过：Markdown/本地引用、任务/普通会话分组、来源/附件/统计、跨系统路径边界。
- 五个模拟 API 页面脚本通过：`session_creation`（含 Windows 默认目录）、`controller_discussion`、`controller_details`、`skill_selection`、`service_activity`。覆盖 1440/1024/390、浅深主题、键盘、发送/失败、授权确认/到期/报告状态。未创建真实任务或调用模型。
- 页面检查期间发现并修复共享图标路由遗漏；两个旧模拟脚本补上新 runtime 元信息后通过，未用硬编码 Linux 默认目录掩盖 Windows 逻辑。
- Linux 实际 CLI/daemon 均为 0.164.0。新 Unix 与 proxy 客户端分别完成 initialize、loaded/list 和 thread/list；关闭 proxy 后子进程已回收，daemon 仍连接正常。该结果不替代 Windows 管道/Win32 实测。
- Linux `ma4.service` 已 active/running，ExecStart `/home/dticpw/conda/envs/py310/bin/python /mnt/e/PG/MA4-win/server.py`，WorkingDirectory 为共享目录，KillMode=process。现有 service 和桌面 `.desktop` 链接均指共享 deploy；没有新服务、自启机制或依赖安装。
- 原数据 `/home/dticpw/PG_linux/MA4/.ma4` 原位使用。两次重启核对 12 项任务的 id/host/formerHosts/cwd/target/budget/workspaces/draft/goalConfirmed/status/workers 摘要一致，原 9 个 loaded 会话全部保留；暂停任务未自动恢复。
- 实际 8764 网页三宽度浅深主题无脚本/资源错误、无横向溢出；8 个静态资源 HTTP 200。没有用用户在途任务做发送/停止试验。
- 四份全局指令只有 MA4 条目改变。`/root/global_rules_review` 审前和写入后均 PASS；实际字节/SHA256 等于通过版本，共享正文一致、LF。persona-sync status 修改前后均 22/22；facts 均通过。Linux 全局 Codex 30,311 字节。备份/完整审查证据见 `D:/Linux_share/persona-history/20261027-ma4-shared-source/`。

## Windows 本轮实测（2026-10-27/28）

详细数量、任务/会话 ID、文件摘要、关键进程与回合证据见 [windows-parity.json](windows-parity.json)。测试对象为共享仓库 `505fe34` 加本轮修正；该 JSON 记录被测源码 SHA256。Windows 11 build 26200、th123 Python 3.10、Node 24.11.1；MA4 所选 CLI 与实际原生 daemon 均为 0.164.0。桌面 App 独立 app-server 进程所用二进制磁盘版本为 0.164.0-alpha.11.1，不能当作它的运行握手版本。

- **自动检查通过：** 最终 Python 179 项中 175 通过、0 失败、0 错误、4 跳过。跳过的是 `test_artifact_cleanup_requires_exact_safe_owned_files`、`test_invalid_owner_markers_are_never_replaced`、`test_shared_artifact_links_and_busy_workers_are_not_cleaned`、`test_symlinks_checked_again_at_launch_and_grant_confirmation`，原因均为本机无符号链接权限；未修改系统权限。真实 Windows Junction 和 3 项 TCP 启动器集成测试通过。Node 22 项全部通过。
- **页面通过：** 五组模拟 API 检查覆盖 1440/1024/390、浅深主题、键盘、讨论确认、报告、附件、服务活动及失败状态；实际页面三宽度无脚本/资源错误或横向溢出，查看了桌面/窄屏图。未使用真实用户会话发送测试消息。
- **实际修正：** `activity.py` 的父进程采用 UTF-8，但原凭据 CLI 子进程会输出 Windows 本地编码，导致解码失败。现在子进程显式 `-B -X utf8`、父进程显式 `encoding=utf-8`；新增真实子进程的非 UTF-8 默认环境回归检查，`test_activity` 7 项通过，真实 Chat 统计恢复。`web/app.js` 原先只在 SSE 错误时显示“未连接”，重连且无新 daemon 事件时不复原；现在重连后读取当前状态。模拟三宽度和实际网页重启连接均确认提示恢复。
- **测试修正：** `test_controllers.py` 对 JSON 解码后比较 Windows 路径，并用实际盘根代替字面 `/`；讨论页面测试等提交后的状态刷新结束再注入下一事件；实际网页脚本允许空中控列表这种合法已载入状态。未削弱原功能断言。
- **原生与启动通过：** 选中 `proxy://C:\Users\DTICPW\.codex\app-server-control\app-server-control.sock`，真实 initialize/loaded/list 成功。三次连接中含一次主动终止本次代理模拟断线，代理均回收，随后可重新连接；用户原生 daemon 保留。独立原生网页重复启动复用进程，`include_backend=True` 只停止该测试网页及其 proxy。现有快捷方式实际双击打开新窗口但复用网页 PID；关闭重复窗口后网页和 daemon 仍正常。没有启动新服务或自启。
- **终端通过与边界：** 对专属测试会话调用 `/api/terminal`，实际 remote TUI 连接相同原生端点；另一受控 TUI 在模型开始前接入并捕获报告、读取结果与完成事件，网页同时收到两轮 started/completed、流式 item/delta 和 token 事件。普通 CLI 的 resume 进程未带显式 `--remote`，其子进程为当前原生 daemon；桌面 App 另有独立 app-server。未对用户会话注入消息，因此不宣称这两类客户端的实时共享已经通过。另起并清理的隔离 TCP 后台可恢复本次**已空闲**的测试会话，HTTP 200；没有启动模型，不能以此证明运行中 409。
- **路径与侧栏：** 中文/空格文本文件由 `/api/file/open` 打开，在 Notepad3 中确认准确两行；小写盘符与编码后的 file URI 成功。实际 `.py`、`.cmd`、`.lnk` 均 HTTP 400 拒绝执行。HTML 由默认 Chrome 打开，窗口标题可见，但浏览器策略拒绝观察 `file://` 内容，故渲染未验收。通知为未授权状态，未操作授权弹窗或测试真实通知。凭据通过 credential-vault 读取，仅写本侧私有 `.ma4/quota-source.json`；使用同服务文档已支持的多家额度接口，当前 Codex/Claude/Grok/Gemini 均有效，muQ 与 21 点健康 HTTP 200，德州/21 点/Chat 统计均不陈旧（本次均 0）。不输出密钥 URL 或访客详情。
- **一次真实模型实验通过：** 任务 `dd779cf589e74a48`，中控 `01a17e40-f24f-74e1-ab04-7d1ac5f0d7bc`（2 轮），执行者 `01a17e43-1a92-73b3-b32e-f0ef7aef46cc`（1 轮）。116.96 秒，288,401 tokens，其中缓存输入 233,984、输出 3,121；没有提高 15 分钟/300,000 上限，没有第二次模型实验。只产生 `验证 结果.txt`，66 字节，SHA256 `f3be67d616443ecf41d94abf87641a2443e05b6cd17bea50b7f9d5345ec71128`。中控真实命令读取后核对路径、UTF-8 无 BOM、无 CR、两处 LF、准确两行和全文内容，外层再次逐字节核对。中控同一回合中一次 PowerShell 引号错误及一次缺少 finish 结论参数均得到明确错误并修正，未增加回合。最终 completed/met，两个会话已通过现有移除接口归档，中控任务数回到 0；原始 Codex 历史仍由 Codex 管理，未复制。

## 返回 Linux 核对（2026-10-28）

核对对象为共享提交 `1614e51`，工作区起始干净。逐个重算 Windows JSON 记录的 7 个文件 SHA256，全部一致；复核 Windows 模型实验成果 66 字节、SHA256、严格 UTF-8 内容和 LF，全部与记录吻合。Windows 当前任务列表为 0、私有额度源文件存在（未读取或输出凭据），两批临时文件数量/大小符合其记录。Windows 进程/Junction/终端/GUI 的实测结论仍归属 Windows 当日证据，不伪称在 Linux 重跑了 Windows。

- `test_activity`（7 项）+ `test_controllers`（85 项）：共 92 项通过，无跳过或失败；涵盖本次 UTF-8 子进程修正及变动过的路径/报告断言。未扩大为无关全量复跑。
- `tools/service_activity_check.mjs` 和 `tools/controller_discussion_check.mjs`：1440/1024/390、浅深主题、重连提示/统计失败状态、讨论/权限/预算确认通过。API 模拟，不调用模型。
- 实际浏览器先连接既有 8764 服务，按约定重启现有 `ma4.service`，观察 SSE 的 `open → error → open`，页面恢复“守护进程已连接”，无脚本错误。原生 daemon 未停止。
- 重启前后 12 项任务的 id/host/formerHosts/cwd/target/budget/workspaces/draft/goalConfirmed/status/workers 摘要一致；本次开机已载入的 8 个会话全部保留，恢复状态结束。此前开机的 9 个是上一阶段数据，不能要求跨系统重启后的载入集合恒等。
- 真实德州/21点/Chat 三项统计 `stale=false`、无错误，额度不陈旧，两站健康 `ok=true`；未输出访客详情或密钥。
- **真实登录启动已验证：** 本次 boot 为 2026-10-28 01:29:34 CST；在本轮任何服务操作前，systemd 本次启动日志已记录 01:30:11 启动 MA4，01:30:12 图形会话目标激活。服务 enabled/active/running、WorkingDirectory=/mnt/e/PG/MA4-win、ExecStart 指共享 server.py、WantedBy=graphical-session.target、KillMode=process；Linger=no。因此证明本次图形登录自动启动，不证明退出登录后持续执行。
- 未修改业务代码、全局指令或客户端配置，未追加模型实验。只更新现有 README/清单/本验证记录、系统看板与 machine-state。

## 尚待验证

Windows：4 项 symlink 检查受权限限制；真实通知弹出未测；HTML 的 `file://` 内容观察被浏览器安全策略拒绝；普通 CLI/App 的完整实时共享和运行中跨后台 409 未测（相关错误映射单元测试已通过）。这些缺项不以模拟结果替代，也不为补测另开整套模型实验。

Linux 必需回归和真实登录启动已完成。核心迁移可以日常使用，剩余 Windows 明确缺项按实际需求在正常使用时补测，不为补齐报告重新安排整套模型实验或无必要的系统往返。

模型验收上限保持不变且本次已用完授权的一次实验。Linux 实施阶段模型调用为 0。详见清单与看板 B-20261027-02。

## 回退与保留

Linux 若共享源无法启动，可将 `~/.config/systemd/user/ma4.service` 与 `~/.local/share/applications/ma4.desktop` 两个链接重新指向 `/home/dticpw/PG_linux/MA4/deploy/` 的原文件，再 `systemctl --user daemon-reload`、`systemctl --user restart ma4.service`。这只回退启动源码，不动原 `.ma4`、Codex daemon、会话历史或其他项目。旧源码在验收完成前保留，不在两处继续开发；恢复正常后仍以共享源码为唯一入口。

Windows 原版可从本仓库 `1fec307` 查阅差异并定点恢复；禁止直接 reset/clean 覆盖后来工作或运行数据。全局指令回退须遵循独立审查，不直接覆盖四份已更新文件。

## 文件收尾

Windows 正式改动为两处共享业务修正、相关测试、README/清单和本验证记录；必要证据汇总在 `validation/windows-parity.json`。`.ma4/quota-source.json` 是本侧私有运行配置，Git 忽略；服务自行更新 controllers、额度缓存及启动器状态。两个测试会话已归档，受控终端与隔离原生/TCP 测试进程已退出，主 MA4 与用户 daemon 保留。没有压缩包、备份、自启、定时任务、全局配置变更或 push。

**Windows 临时清理未执行：** 清理仅限本轮 `.agent-tmp/windows-parity/`（原计划保留仍在浏览器中的 HTML）和 `.agent-tmp/windows-parity-smoke/`，已核对绝对路径与非链接边界，但命令在运行前被自动审批策略拒绝，仅返回“blocked by policy”，未提供更具体原因。没有改用其他方式绕过，故两目录全部保留；含截图、测试脚本/摘要、已停止实例的私有临时状态及 66 字节文本成果。HTML 测试标签的内容读取/自动关闭也受 file URL 策略限制，样例保留。复查条件：用户关闭该 HTML 标签，且清理可在批准策略允许的方式下执行；不得把本记录当作绕过拒绝的授权。旧 `.agent-tmp/B-20261027-01/` 等完全未动。实际数量见 Windows 摘要的 cleanup 字段。已按会话起点运行只读文件清点。

Linux 实施阶段正式成果为共享源码/测试/配置/文档与当前验证记录。两张保留的 [桌面确认窗口](shared-source-desktop.png) / [窄屏确认窗口](shared-source-mobile.png) 来自模拟数据，已人工查看；没有保存用户聊天截图作为正式证据。其余本次 `.agent-tmp/shared-source/` 的45个截图/摘要文件（9,738,015字节）已清理，该任务临时目录无残留；隔离预览和测试进程已停止。

一次性回退材料：两个本地 Git 提交、原位旧 Linux 源码、上述全局指令原文备份/审查目录；保留到 Windows 验收与 Linux 回归完成时复查。旧任务 `.agent-tmp/B-20261027-01/` 等原样保留，不属于本次清理。没有压缩包、持续备份、计划任务或新自启；未 push。

已运行 session_inventory.py，范围含两项目、共享看板/状态/审查目录及四份全局指令。清点中的 Linux `.ma4/controllers.json` 与 `quota-cache.json` 为服务自行维护，未手工编辑或提交。`persona-snapshot.json` 是 persona-sync 既有当前快照，更新一次，不是新备份机制；before-status/facts 是本次独立审查证据。清点列出的 ma4/sunshine/ma3-workbench 均为既有服务，本轮仅修改 ma4 的源码入口。

返回 Linux 本轮的 `.agent-tmp/linux-return/` 18 个模拟检查截图（3,764,117 字节）已在核对后清理；浏览器测试进程已退出，无本轮临时残留。Windows 被策略拒绝删除的两目录和旧协议文件保持原状，没有在 Linux 换命令重试清理。回退源码与既有全局指令审查备份继续登记保留，未新建备份或定时机制。

返回 Linux 收尾已运行 session_inventory.py（从本次01:30起，限定两项目和共享文档目录）：正式修改为共享README/实施清单/本记录、旧Linux README接续指针及看板/machine-state；Linux `.ma4/controllers.json` / `quota-cache.json` 是服务自行更新，未手工改写或提交。未新增备份、打包或定时服务。
