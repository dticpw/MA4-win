# 有限维护入口（阶段 4）

`tools/maintenance.py` 只把本地可靠失败转换为可审查的维护任务；默认不派工。
标准库，无后台服务/定时任务，无远程 webhook、CI 日志下载或运行异常自动修复。

本轮只在 Windows 验证并启用此入口，使用 `D:/python/anaconda/envs/th123/python.exe -B -X utf8`。以下命令省略解释器前缀：

```text
tools/maintenance.py capture tasks architecture
tools/maintenance.py plan --scope task_policy.py --minutes 10
tools/maintenance.py start --scope task_policy.py --minutes 10
tools/maintenance.py status
tools/maintenance.py reconcile
tools/maintenance.py ack --review "派发者独立核对了……差异和……检查，实际结果……；未完成项……。"
```

`capture` 只接受 tasks/architecture/tooling/ci/map，可合并去重；禁止任意命令、UI/native/model 选项。记录退出码、结构化结果、最多约 10 KB 的输出尾部、HEAD、源码指纹与前后稳定性。成功/跳过不派工；缺失可执行文件、无结构化报告、零项或全部跳过等检查不完整情况不能变成修复任务。退出码：成功 0、可靠失败 1、无效证据/安全拒绝/无法核实 2。`plan` 不访问 API；无范围/时限时只展示当前证据，有参数时展示自包含任务单。仅 `start` 允许发送 create/confirm；`status/reconcile` 只读，`ack` 只写本地当前记录，不修改远程任务。

`--repo` 放在子命令前，必须是明确的绝对 Git 工作区根路径，有 AGENTS.md 和 tools/verify.py；支持正常 `.git` 文件形式的 worktree。拒绝路径跳转、符号链接/Junction/reparse point；不连接其他端口。这里的验证入口及仓库代码须可信：固定命令白名单不是 Python 执行沙箱。

`--scope` 可重复，限 1–20 个现有普通源码文件，不接受目录、通配符、新文件或硬链接。保护所有识别出的测试/验证框架、配置、AGENTS/Skills/凭据及运行目录；检查框架故障留人工处理。`--minutes` 必须是正数且不超过 60，首次 start 固定绝对截止时间，无 token 限制；重复 start 不续期。范围和“一个执行者、一个修复回合”写入任务约束，**不是 OS 沙箱或新增服务端派工次数限制**。禁止自动提交/push/合并/部署；修复必须由派发者独立审查。

当前记录固定在所选仓库 `.ma4/maintenance/current.json`，最大 64 KiB。只保留当前状态、一个最近已审查事件 ID 和有界摘要，不建历史表、不复制仓库。源码指纹覆盖全部非运行区被跟踪文件（含索引状态/删除）和非运行区未跟踪文件（含被 Git 忽略的文件）；排除 `.git/.ma4/.agent-tmp/__pycache__`，未跟踪 node_modules/.venv/venv 也排除。子模块/冲突索引拒绝自动处理。它不证明未登记的外部依赖、环境或语义正确，也不能检测修改后又在两次观察前完全恢复的变化。源码/HEAD/dirty 内容变化将阻止尚未确认的事件启动。

Linux 维护入口未启用/实测：此工具当前按目标工作区保存事件，尚未按 MA4 两系统的运行数据目录分开。记录绑定 Windows 绝对路径，Linux 不应复制、覆盖或复用它；以后接入 Linux 时先调整系统独立存储与实例对应关系，再验证。此次不改 Linux 服务或运行数据。共享规则和隔离任务工具的 Python 可移植性也不代表 Linux 实机已通过。

capture 每次在项目 `.agent-tmp` 建独占 TemporaryDirectory，验证日志、结构化报告及空 CODEX_HOME 用后回收，不读取真实 CODEX_HOME 或凭据。**执行超时沿用现有 verify.py：它没有整个检查过程的统一硬超时，本入口也不新增进程树管理；卡住时由操作者处理。** MA4 的 60 分钟上限只约束维护任务，不约束 capture。异常终止时临时目录/写锁可能残留，先核对归属及进程，再人工处理；不自动抢锁、杀进程或清理旧材料。

请求前先保存意图。create 超时只 GET 查询 createRequest；找到未修改的草案后，另一次显式 start 可在原预算内继续确认；找不到或创建不完整就停止，不能推断请求没到。confirm 意图一旦保存，后续永不 POST 重发，只核对相同任务 ID/request_id、目标、修订、范围、预算及状态。已确认但无法证明启动、回读失败或不一致均停止；不自动恢复模型回合。对其他任务检查授权和在途写入，包含暂停/终态里未结束的执行者及发送不确定状态；外部终端和未被 MA4 管理的写入仍靠工作区协调，检查与远端操作之间也不是跨进程事务。

启动后不能覆盖证据。只有派发者显式 `ack --review` 才允许之后 capture 替换：必须查到同一任务、completed/stopped 终态、host/worker 均空闲、全部对应会话明确 idle、pending 为空且无 outbox/handoff。API 省略 outbox，所以同时要求其服务端生成的 `diagnosis.code` 为相同终态、`confirmBlocker` 明确为 null；字段缺失/变化拒绝关闭。该判定已对实际 Controllers 的快照逻辑作无模型测试。`ack` 不把 completed 自报当作修复验收，也允许注明未修好的 stopped 任务；审查说明的真实性由调用方负责。同一未变化失败仍不得重派，即使期间 capture 曾成功。历史事件 ID 仍由服务端 createRequest 辅助去重；若人工删除本地记录及远端任务，就不再拥有这些去重证据。

本轮方法与实际结果见 [evidence.json](evidence.json)。维护自测：

```powershell
& 'D:/python/anaconda/envs/th123/python.exe' -B -X utf8 -W error::ResourceWarning -m unittest -v test_maintenance
& 'D:/python/anaconda/envs/th123/python.exe' -B -X utf8 tools/verify.py run tooling architecture
```

派发方已整合 README、功能地图和统一验证入口；[真实修复演练](../iteration-pilot.json)记录独立工作区中复现已确认缺陷、一次执行者修复、重复 start 无 POST、独立审查与真实 ack 的结果。该演练使用真实开发模型，与隔离场景的本机模拟模型分开记录；它不是生产事故，也不能证明长期迭代提速。
