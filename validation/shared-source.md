# 共享源码迁移 · 当前验证记录

2026-10-27。Linux 阶段已完成；Windows 实机验收待做。此文件维护当前结果，不新增每轮历史副本。

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

## 尚待验证

Windows 双击入口/原生 proxy/同端点终端事件共享、桌面 App 与普通 CLI 的实际宿主、Junction/路径/文件关联/通知、额度来源与服务活动、获准小模型任务。返回 Linux 后按 Windows 实际修改做必要回归，并核实真实登录启动。Windows 本轮尚无新的运行结果；旧 `validation/*.json` 是其各自日期的原版本证据。

模型验收上限：1 中控 + 1 执行者，各最多 2 轮，15 分钟、300,000 累计 tokens（含缓存）。在途消耗可能越界。本轮 Linux 模型验收调用为 0。详见清单与看板 B-20261027-02。

## 回退与保留

Linux 若共享源无法启动，可将 `~/.config/systemd/user/ma4.service` 与 `~/.local/share/applications/ma4.desktop` 两个链接重新指向 `/home/dticpw/PG_linux/MA4/deploy/` 的原文件，再 `systemctl --user daemon-reload`、`systemctl --user restart ma4.service`。这只回退启动源码，不动原 `.ma4`、Codex daemon、会话历史或其他项目。旧源码在验收完成前保留，不在两处继续开发；恢复正常后仍以共享源码为唯一入口。

Windows 原版可从本仓库 `1fec307` 查阅差异并定点恢复；禁止直接 reset/clean 覆盖后来工作或运行数据。全局指令回退须遵循独立审查，不直接覆盖四份已更新文件。

## 文件收尾

正式成果为共享源码/测试/配置/文档与当前验证记录。两张保留的 [桌面确认窗口](shared-source-desktop.png) / [窄屏确认窗口](shared-source-mobile.png) 来自模拟数据，已人工查看；没有保存用户聊天截图作为正式证据。其余本次 `.agent-tmp/shared-source/` 的45个截图/摘要文件（9,738,015字节）已清理，该任务临时目录无残留；隔离预览和测试进程已停止。

一次性回退材料：两个本地 Git 提交、原位旧 Linux 源码、上述全局指令原文备份/审查目录；保留到 Windows 验收与 Linux 回归完成时复查。旧任务 `.agent-tmp/B-20261027-01/` 等原样保留，不属于本次清理。没有压缩包、持续备份、计划任务或新自启；未 push。

已运行 session_inventory.py，范围含两项目、共享看板/状态/审查目录及四份全局指令。清点中的 Linux `.ma4/controllers.json` 与 `quota-cache.json` 为服务自行维护，未手工编辑或提交。`persona-snapshot.json` 是 persona-sync 既有当前快照，更新一次，不是新备份机制；before-status/facts 是本次独立审查证据。清点列出的 ma4/sunshine/ma3-workbench 均为既有服务，本轮仅修改 ma4 的源码入口。
