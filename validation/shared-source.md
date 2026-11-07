# 共享源码迁移 · 当前验证记录

2026-10-28。Linux 实施、Windows 核心实测及返回 Linux 的针对性回归已完成；保留明确未测项。此文件维护当前结果，不新增每轮历史副本。

<a id="第三轮有限工具优化2026-11-07"></a>
## 第三轮有限工具优化（2026-11-07）

**派发方最终验收：已完成。** [真实调度记录](round3/control-live.json)绑定任务 `1dda5fb483a146eb`、实际状态和最终工具摘要。一个真实中控、一个真实执行者；三轮执行报告逐个按会话/回合 ID 核对，恰好各回传一次。空闲检查点实际 paused，恢复后目标/修订/预算/目录授权/中控/执行者保持；没有再派工，最终 completed，pending 为 0。原四任务和 12 项业务/配置文件摘要保持。任务的 30 分钟时限未延长，到期后只结束既有验收回合；页面记录历时 30 分 34 秒。任务确认/resume 使用现有 HTTP 接口，实际页面仅检查本任务的状态与统计，不声称覆盖页面讨论确认、在途暂停、断线恢复或交接。

派发方独立运行三次 CLI：重复文本失败（2 次模拟请求）、双会话第 11 步 open 失败（3 次）、同一 16 步计划修后通过（3 次），运行前后源码摘要一致；最后两次 HTTP400、两个会话、三次显式 send，alpha 2 回合/beta 1 回合，全部资源回收。实际参数和成功报告见 [计划](round3/control/plan.json)、[调用](round3/control/invocation.json)、[步骤](round3/control/report.json)、[回收](round3/control/session.json)、[刷新实图](round3/control/two-turns-refreshed.png)；初次两项失败报告分别见 [重复文本](round3/control/initial-repeat-report.json)与[跨会话](round3/control/initial-cross-open-report.json)。派发方已查看实图。中控及执行者为真实模型开发任务；上述 CLI 模型为本机模拟，不能互相代替。尚未量化提速或成本收益。

**最终文件清点：** 已按指定起点运行 session_inventory。必要的 19 份派发方记录/图片逐字节复制到 `round3/control`（536,877 字节），控制摘要在 control-live.json；重复的 61 个临时文件/8,419,305 字节已用不带 `-Force` 的精确范围命令清理，运行进程无残留。执行者和中控的临时输出也已清理；本任务目录仅留 29 字节 `.ma4-owner.json`，作为任务归属元数据随任务移除时复查。扫描器把 before-send 图片按名称提示为备份，实际是正式验收截图，没有新增备份/压缩包/定时机制。原始 JSON 中临时路径和截图名只描述当时运行；精选保存的文件以本节链接与 control-live.json 清单为准，不依赖已清理路径。


**最终 direct open 定点修正：** 从 beta 打开 alpha 时，即使 input 仍可见也可能是 beta 内容，之前“隐藏才 reload”的判断不足。现在 direct open 在 goto 目标 hash 后始终重新加载该文档，并核对目标历史；列表 reopen 保持点击路径。按根提供完整 16 步 JSON 用 `session_cli --plan` 执行一次，输出 worker/cross-open，退出 **0**，两次受控失败、alpha 两轮同文、beta 一轮以及双向 direct open 全通过，共 **3 次本机模拟请求**；全部资源回收。新增“另一会话 composer 仍可见也必须 reload”边界检查，`node --test test_session_actions.mjs` **11/11 通过**。实际参数/完整步骤/ID/历史见 [cross-open](round3/implementation/cross-open/session.json) 与 [invocation](round3/implementation/cross-open/invocation.json)，只保留一张已查看的 [alpha 刷新图](round3/implementation/cross-open/ui/14-refreshed.png)，其他截图不再留存；原报告中的截图名仅记录当时取证，不是全部仍保留的文件。根的失败证据由根保全。此次仅改变 direct open，Python 和默认兼容结果按其未变覆盖复用，不记为本次重跑。本执行者全过程自有模拟请求累计 14 次，独立审查请求另计；不含真实执行会话模型消耗。清理数量见 evidence.crossOpen.cleanup。

**当前结果：** 三点独立验收反馈已修正。正式源码为 session_actions/session_cli/ui_check、smoke/verify 和有限测试；没有业务源码变更。先读 [实现摘要](round3/implementation/evidence.json)，需要定位时再读步骤、历史和截图。中控最终验收及本任务空闲时的真实暂停/恢复已完成，见上方派发方记录。

1. **重复文本：** 原 readHistory 使用全页 exact getByText，合法重复消息造成 strict mode violation。改为按 `[data-turn]`＋`[data-item]` 定位每条用户/助手消息，要求唯一节点和准确文本；保留完整历史 ID、数量、状态和内容比较。实际 CLI `--message '中控独立重复文本验证' --actions create,send,wait,send,wait,reopen,refresh,history`，输出目录 `.agent-tmp/ma4-1dda5fb483a146eb/worker/rework-repeat`，退出 **0**；2 次发送/2 次模拟请求/2 回合/4 条消息，重开刷新一致。[调用参数](round3/implementation/cli-repeated/invocation.json)、[步骤与回收](round3/implementation/cli-repeated/session.json)、[实际刷新图](round3/implementation/cli-repeated/ui/07-refreshed.png)。最后仅修 open 在首页相同 hash 时的隐藏聊天刷新分支；该重复组合使用列表 reopen，未触及该分支，故不重复跑已通过的两轮。
2. **兼容覆盖：** 默认 live-ui 的主路径仍是不存在 cwd 的真实 HTTP400/UI错误→正确创建→一次发送→回复→重开→刷新/历史。额外自有兼容会话恢复 Escape 后断言弹窗关闭、创建带首条消息、完成回复、composer aria-label、pin 页面及后端状态、/help 可见、首页 recent cards；额外仅一轮模型请求，和主路径分开记录在 compatibility。默认总计 **2 会话/各 1 轮/2 次模拟请求**。指定计划 CLI 不执行该额外段。只读有 id 模式的 `.turn` 等待、composer 标签及 HTTP 错误监听均恢复并核对源码；未另跑该独立只读模式。默认命令 `tools/verify.py run live-ui --output .agent-tmp/ma4-1dda5fb483a146eb/worker/rework-default-fixed` 退出 **0**，1440/1024/390 宽度通过。[默认结果](round3/implementation/live-ui.json)、[浏览器报告](round3/implementation/ui/report.json)、[pin/help 实图](round3/implementation/ui/08-compatibility-help.png)。已查看重复文本刷新及兼容 pin/help 两张整体图。
3. **不完整计划：** validatePlan 在遍历完后拒绝任何仍未配对 wait 的 send，不自动补动作。实际 CLI `--actions create,send --output .agent-tmp/ma4-1dda5fb483a146eb/worker/rework-unpaired-should-not-exist` 退出 **1**，明确 matching wait 错误，输出目录不存在、fixture 未启动，见 [实际参数与错误](round3/implementation/unpaired.json)。help/README 同步说明。

**最小检查：** Python 均用 `D:/python/anaconda/envs/th123/python.exe -B -X utf8`。最后 `tools/verify.py run tooling --output .agent-tmp/ma4-1dda5fb483a146eb/worker/rework-tooling`：**17 Python＋10 Node，27/27，通过、0 跳过、退出 0**，见 [结果](round3/implementation/tooling/result.json)、[Python](round3/implementation/tooling/python.log)、[Node](round3/implementation/tooling/node.log)。Node 新增未配对 wait 预检、重复文本的回合/消息 ID 定位检查。未运行无关全库。旧 17/8 数字不再当作当前最终数量；第二轮任务/报告证据可读且摘要匹配，相关业务和方法未变，仅保留原覆盖。

**保留失败：** 首次 SSE 刷新取消误报见 [initial-failure](round3/implementation/initial-failure/ui/report.json)。此次中控独立验收在两轮合法消息后第 6 步重开失败，授权的 5 份原始文件逐字节复制到 [repeated-initial](round3/implementation/repeated-initial/ui/report.json)，复制时 audit 原件未修改；中控核对正式副本一致后已精确清理原件。恢复旧功能时另发现首页保留 hash、same-document goto 不打开聊天，首次兼容检查因此超时，见 [compatibility-initial](round3/implementation/compatibility-initial/ui/report.json)；修为聊天仍隐藏时 reload，随后默认 live-ui 定点通过。没有将任何失败退出计为成功。

**隔离和用量：** 每个修改操作前核对完整随机实例和自有会话归属；不操作 8764/原生 daemon。此次返工自有流程运行 3 次，各 2 次本机模拟请求，共 6 次；连同首阶段自有 5 次共 **11 次本机模拟请求**。从 audit 复制的中控失败证据另外记录 2 次，不混入执行者用量；该阶段未读取根 Agent 证据；最终中控已核对派发方同源码的 16 步通过结果。模拟模型与当前真实执行会话模型消耗分开。所有自有 fixture 的四项 cleanup 均 true。此处隔离工具检查未测 Linux、真实供应商、其他浏览器或审批/Skill/插话；本任务真实模型派工、报告与空闲时暂停/恢复由上方派发方记录单独证明。

**文件与登记：** 当前正式证据在 `validation/round3/implementation`，原失败保留，旧通过只按相应方法/版本复用。源码、实际参数、结果/图片/引用核对后更新 feature-map-review.json；current 不代表语义已通过。首阶段已清理 6 目录/66 文件/9,516,055 字节；返工自身临时目录清理及只读清点见 evidence.json 的 reworkCleanup/inventory。旧任务、全局配置、看板及原生日志不动；audit 原件按上述核对后清理，没有新增备份/常驻机制或提交部署。

<a id="第二轮优化2026-11-06"></a>
## 第二轮优化（2026-11-06）

**范围与结果：** 按用户已确认的方案维护现有 MA4-win；不重构架构、不推进 MA4-refra。新增真实普通会话验证入口、操作地图和变化检测，局部修复材料重复计数。此次未派 Agent、安装依赖、取凭据、调用真实供应商、推送或部署。

**真实操作验证：** `tools/verify.py run live-ui` 复用 smoke 独立 CODEX_HOME、随机本机端口、实际 Codex app-server 和本机模拟模型，启动真实 MA4 HTTP/Hub 页面；不模拟 `/api/**`。Python 与浏览器在操作前后检查相同的随机实例 ID、归属 PID、数据目录、后台连接和版本，拒绝 8764/身份不匹配。浏览器实际创建、发送、等待回复、回首页后从列表重开并刷新；核对原生历史的用户消息/回复及回合 ID 不增加。版本自报 0.167.0，1440×900 浅色、1024×800 深色、390×844 浅色检查通过。已查看发送前、重开后、手机整页实图；页面文本、回复和布局与报告一致。

正式证据：[汇总](round2/result.json)、[真实流程与资源回收](round2/live-ui.json)、[浏览器报告](round2/ui/report.json)、[历史](round2/ui/history.json)、[发送前](round2/ui/before-send.png)、[回复](round2/ui/reply.png)、[重开后](round2/ui/reopened.png)、[手机](round2/ui/w390.png)。summary 的 ui_report 相对自身目录，journeys 中 evidence 相对 ui/；argv/identity 中临时绝对路径是当时执行信息，已回收，不能作为后续依赖。

**实际回归：** `run tasks platform transport live-ui --ui`：Python 114 项中 110 通过、4 项 Windows symlink 权限跳过，结果为 passed_with_skips；Node 16/16、讨论确认与报告详情两组模拟页面、原生协议 9 场景及真实普通会话流程通过。详见 [Python 日志](round2/python.log)、[Node 日志](round2/node.log)、[讨论确认](round2/controller_discussion_check.log)、[报告详情](round2/controller_details_check.log)、[协议结果](round2/transport.json)。真实 Junction、硬链接和其他任务保护有独立通过项；跳过的符号链接案例没有冒充通过。未重跑与本轮无关的全套业务检查。

**缺陷复现和修复：** 同一目录的反斜杠、正斜杠、大小写写法各遍历一次，1 个 5 字节文件被报成 3 个/15 字节；新增测试先出现 [预期失败](round2/materials-before.log)，再改 `scratch_cwds` 和登记逻辑使用既有 `path_key`。优先保留主目录路径写法；旧 retained 绝对路径别名的理由仍显示，精确 keep/clean 时更新/清除对应旧键。不同目录不合并，POSIX 大小写分开，不改持久化格式；任务归属、链接/硬链接拒绝和精确路径清理边界保留。测试只创建并清理自身材料，用户旧材料未动。

**地图可信度：** FEATURE-MAP 补三条用户流程的入口、前提、步骤、成功观察、相关检查与未测范围；`tools/feature_map.py` 只读核对本地链接/锚点、操作段和人工记录中登记的源码/检查方法/证据摘要。current 只说明登记输入未变，不证明文字语义、未登记依赖或运行环境。tasks/reports 明确仅逻辑与模拟页面覆盖。维护时先核对源码和必要操作，再人工更新 `validation/feature-map-review.json`；没有自动刷新为通过的命令。[工具检查](round2/tooling/result.json) 15 项通过，实际地图 [变化检测](round2/map.json) 为 current；含故意改变源文件、操作说明、证据、失效引用/锚点及恢复后结果检查；无周期扫描或自动派工。

**失败及诊断记录：** 首次真实 UI 检查的新增“重开”步骤仅修改 URL hash，应用没有对应 hashchange 打开处理，停在首页而超时。截图和实例健康检查说明这是测试操作错误；改成实际点击首页→会话列表后通过，未为测试修改产品页面。最初用 PowerShell stderr 管道收集红测试时发生 NativeCommandError，随后使用 Python unittest runner 收集到完整预期失败；无业务副作用。

**在线加载接续（2026-11-07，UTC+8）：** 初始 [只读在线检查](round2/online.json) 因发现普通会话 active 而暂缓。进一步将该 ID 与当前会话身份精确比较，确认它就是当前对话且不属于任何 MA4 中控任务；其推理运行在独立原生 daemon，网页进程停止不等于停止该回合。因此修正先前“任何 active 都不能重载网页”的过宽判断；没有放宽终止 daemon/其他任务或共享写入的限制。

本次 [加载证据](round2/online-loaded.json) 使用独立只读 AppServer 连接，逐一检查已载入的原生会话，只有当前对话 active；四个中控任务均 hostBusy=false、执行者均 idle、审批 0、无恢复中的任务。核对监听 8764 的 PID/创建时间与启动记录、全部已登记源码摘要后，调用既有 desktop.stop(include_backend=False) / start(browser=False)，只将 web PID 5972 替换为 2700。两项 native daemon 进程身份保持，观察连接未断，21 个原生载入会话集合不变；四任务目标、预算、目录授权、执行者归属/权限和状态的前后摘要一致。没有新建模型回合、改配置、复制原生会话或操作用户文件。

真实材料端点 `/api/tasks/artifacts` 的 list 原报 **485 文件 / 35,999,560 字节**，加载后为 **466 文件 / 34,158,073 字节**。按实际文件系统遍历各唯一根目录（只读、不跟随链接、排除所属根的归属标记）的结果为 466 / 34,158,073，重载前后实际清单及大小摘要一致，修复已在线生效。首次预检查认为 API 返回行足够核对完整清单，但实际超过 200 项展示上限，检查在任何 stop/start 前退出；随后改为完整磁盘只读统计并核对展示行、全量 count/bytes，通过后才执行重载。200 项截断仍是原有展示边界，此次不扩大界面范围。

**仍未测：** Linux 实机、真实模型/供应商、目标确认→派工→报告→恢复的真实全链路、其他浏览器/手机真机；沿用之前 4 项 symlink 权限跳过说明。本次只完成必要在线加载与材料计数定点验收，未重复未变的整套回归，也未新增全项目覆盖审计。Linux 接续仍见 M-20261106-02。

**文件与代价：** 复用现有工具和路径规则，源码/测试/地图是正式成果；validation/round2 只保存本轮代表证据，不建立逐次完整副本。初次交付代表证据 20 文件/925,190 字节，逐字节复制核对后保留。已清理本轮 `.agent-tmp/round2-20261106/` 的 71 个临时文件，共 9,650,105 字节，并移除空目录；隔离运行目录由 fixture 自动回收，无本轮残留测试进程。旧任务留存材料及所有真实运行数据未清理；没有备份、打包文件或新增定时任务。清点工具按文件名把 before-send.png 提示为备份，实际是发送前页面截图；.ma4 的三个近期变化文件属于既有运行数据，未手工编辑或清理。

**本次接续文件：** 仅追加在线加载 JSON、更新 README/本记录/功能地图核对记录及既有 Linux 留言；业务源码未再改。全局协作原则的授权与独立审查材料另归 D:/Linux_share/persona-history/20261107-independent-judgment，不作为 MA4 运行依赖。接续临时脚本与重复输出 2 文件/13,133 字节已清理，空目录移除；追加正式在线证据 1 文件/3,759 字节。旧网页的临时 proxy PID 35084 已退出，原生 daemon 保持；未留下本次一次性检查进程。原有运行目录仅由现有程序正常更新，未手工改写。

<a id="第一轮优化2026-11-06"></a>
## 第一轮优化（2026-11-06）

用户授权按 Agent 工作流方向优化，第一轮落实功能地图和现有验证入口；复用原脚本，无新数据库、服务、自动派工或周期检查。正式新增 `FEATURE-MAP.md`、`tools/verify.py`、`test_verify.py`，修改 `tools/smoke_test.py` 的测试时序、README 与本节，并向共享看板补 Linux 待实测留言。所有原有未提交业务改动保持；没有因此重构产品或修改其他任务。

**本轮新测（Windows / Python 3.10.19）：** 下表命令前缀均为 `D:/python/anaconda/envs/th123/python.exe -B -X utf8 tools/verify.py`。实际运行分别以 `--output` 指定本轮临时区新子目录；五个页面脚本读取入口的临时静态服务，全部 API 使用模拟数据，未请求真实 8764 API。

| 命令 / 对象 | 实际结果 | 能说明什么 |
|---|---|---|
| `run tooling` | 8/8，2.708 秒 | 选择去重、图片预览/真实会话工具不被默认选择、plan 不执行、失败非零退出并停止后项、缺可执行文件报错、输出范围/不覆盖/自动回收、隔离环境、静态白名单和端口关闭 |
| `run sessions tasks side platform --ui` 的 Python 部分 | 204 项，200 通过、4 跳过，23.753 秒 | 包括现有健康检查、真实 Junction、Windows 启动器隔离进程；4 个符号链接检查缺 Windows 权限，未计为通过 |
| 同一命令的 Node 部分 | 25/25，0.168 秒 | Markdown、路径及中控前端纯逻辑 |
| 同一命令的模拟页面部分 | 5 个脚本均通过 | session_creation、skill_selection、controller_discussion、controller_details 各 1440/1024/390；service_activity 为三宽度×浅深主题。共 18 个布局组合；包括脚本既有的交互、失败及资源断言。本轮未改 UI、未另做逐图人工视觉评审 |
| `run transport` 首次 | 失败，退出码 1 | 插话断言期望 steer，实际为 start；入口如实报告失败 |
| 修正测试后 `run transport` | 9/9 场景，退出码 0 | 空会话、HTTP 发送/历史、去重、第二客户端事件、插话、中断、改名/置顶、重连保留后台、实际 SSE |
| `list` / `plan core --ui`、文档与差异检查 | 正常 | 显示分组及完整 argv，无执行/目录创建；本轮文档本地引用及 UTF-8/LF 检查另在收尾完成 |

**测试修正的范围：** 原 smoke_test 只把每个模拟事件延迟到 0.25 秒，不能保证发出插话时回合仍在进行。现在以事件明确等待模拟请求开始、暂缓后续回复，确认是同一活动回合后插话和中断，并在 finally 释放等待。只改测试服务和操作顺序，没有延长业务超时或修改 Hub 发送行为；只定点重跑 transport，未重复已通过的全套回归。

**版本与未测项：** 隔离后台自报 `ma4_smoke_terminal/0.166.0`；真实工作台只读检查仍连接 `codex-tui/0.167.0`，四个任务状态与开始读取一致（stopped / attention / completed / completed，均 hostBusy=false）。本轮没有真实模型/供应商请求、真实任务写入或服务重启。该协议测试不代表在线 0.167.0 已完整测试；Linux 实机、真实权限/桌面应用、其他浏览器/手机真机及图片预览专用测试未覆盖。Linux 接续见共享看板 `M-20261106-01`，无需因工具/文档修改重启 ma4.service。

验证过的三个工具文件 SHA256：`tools/verify.py` = `71fa93c958b79088f6a8f75867ea83c6a10aa9218a7d097298d10875b7319c24`；`test_verify.py` = `527d8a5ce8b8b29d87a520536418c9432f01c6ebd8c31d29df7e816c461d375d`；`tools/smoke_test.py` = `e1cab7f1a32e274881577b2a04adc53911bd753c4fda6750ec0549a4df93581f`。这绑定本轮验证入口和测试修正，不替代整个既有脏工作树的版本描述。结论集中在本节；临时日志和模拟截图无需成为运行依赖，按本轮收尾处理，不建立每轮历史副本。

**文件收尾：** 已运行共享 session_inventory（起点 2026-11-06 12:18:07 UTC），正式保留上述 6 项项目文件及 1 项共享看板修改；清点出现的 `.ma4/controllers.json` / `quota-cache.json` 属于既有服务运行数据，不清理、不复制。验证用临时进程已退出，没有残留 verify/smoke/oneclick 临时目录；本轮显式保留目录内 61 个日志/模拟截图/结果文件，共 8,818,602 字节，在结论与首次失败已记录后清理，目录已不存在，无备份、压缩包或新增定时任务。使用不带 `-Force` 的删除命令；其中链接属性检查因 PowerShell 嵌套数组未展开报错，且为非终止错误，不能算该项检查通过。删除前的绝对目标等值、文件数量与总字节核对通过，实际删除完成；本次只处理已知由本轮工具生成的目录，不再次重试删除或触碰旧材料。收尾 UTF-8/LF、Python 语法、地图全部本地引用和 Git 差异空白检查通过。

<a id="本地缓解中控复核与配置阻断2026-11-06"></a>
## 修订 4 最终独立技术验收（2026-10-29 23:14，UTC+8）

**本机已生效，公网仍未发布。** 本节覆盖最终实际运行状态；后面的制作、暂停和首次独立抽查记录保留原时点，不外推为当前阻碍。本轮未修改业务源码、调用新模型实验、SSH、push 或发布主页，也没有终止其他任务。

- **本次新测与复用：** 恢复时所有其他会话/worker/pending/approval 均空闲；MA4 11 项源码/测试摘要、辅助 activity.mjs 与 tests/activity.mjs 摘要、后端 8 项实现/测试/文档/原输出摘要匹配（`2d3e2f`、`4a4d1c`）。制作方 170 项 Python（166 过、4 旧 symlink 跳过）、末轮 6 项定点、Node 13 项、辅助 26 项及后端旧检查按原边界复用，不计为新测。ChineseChessGuide 后续 UI 已更新，因此针对当前页面重新走真实三方 7 场景；不再把早期 186 项未变结论外推到后续合法 UI 改动。
- **受控重载与状态保留：** 使用既有 `launch.py stop` / `start --no-browser`，两次都紧邻核对无其他在途任务，只停止网页。第一次启动成功，但审查脚本在列表初始化尚未结束时索引 host 引发 StopIteration，未计为完整通过（`b3a6df`）；随后只读确认 62 会话/4 任务、辅助未知及新日期已就绪（`281498`）。为补齐被中断的前后比对，第二次先在内存保存受保护字段，等列表就绪后比较：网页 PID 26832→48236，原生 daemon PID 3448/21844 及创建时间不变；19 个载入 ID 全保留；4 项任务的目标、预算、目录授权、归属、状态和模型摘要前后同为 `bfb61ff1d075452234c5211d8b5b654c7b70b65be3d8def6d1a5b954df726048`，差异 0（`0670a2`）。原生版本 0.165.0、CLI 0.164.0，连接正常；没有共享/复制原生历史。
- **日期三方核对：** 四个 host 的自身明确回合统计、API.updatedAt 与 DOM title 逐个相同（`69e5b1`）：本任务 1793286323／2026-10-29 23:05:23；任务 06d898324d4744be 为 1793194182／10-28 21:29:42；54e0ee423c2d4b79 为 1793285113／10-29 22:45:13；4724144705094629 为 1793282127／10-29 21:55:27。原本任务旧值 1793182002 已被真实活动替代。六组页面刷新前后所有 62 个会话时间不变，没有以刷新时钟制造活动；归属、缺失时间、估算值、前任/worker 隔离与旧通知/重连沿用已核对的针对性测试。
- **正式 MA4 页面：** Chrome 实际访问 8764，1440/1024/390 × 浅深主题六组通过；辅助行清楚显示“近 5 分钟活跃浏览器”“非精准人数”“每 60 秒查询”与未知，默认无 VPS/中象大厅新增行，原 texas/ace21/chat 为正常 0，两个原健康项可达、额度卡保留。比对日期 title、刷新稳定、键盘任务展开/折叠、焦点入口、无横向溢出/资源错误/脚本错误；测试浏览器无非 GET 请求。首轮对异步 refresh 返回前立即断言折叠状态而失败，改为等待实际属性变化后六组通过（`f674b8`→`90adaf`），未改产品。实际查看六组整体图，并补看桌面辅助面板、1024 深色整页、390 深色辅助区；宽屏侧栏需滚动才能完整看到统计，沿原布局，未误判为缺项。
- **辅助当前页面三方通路：** 活动模块仍为 `726998951a83fc77b5f7f0d603d335fafa378fdbc1080d3a6e9076654f3d946e`，测试方法仍为 `22794e3472bac399f69672a165e45c1aa61a5d3d435c117d0f509e4be6e6cc22`。在现有 4185 当前页面显式启用本机 endpoint，真实内存游戏后端→真实 ActivityPoller（仅测试传输/时钟注入）→实际 Server→未修改 MA4 页面，再验证积累中、完整 0、完整 1、真实 503 清除旧数、恢复、过期未知、重新获取恢复共 7 场景（`456b27`）；2 次本机 POST、0 公网请求、GET 不增加/续期、错误 0。正式源页默认仍关闭上报，公网 1.0.6 未发布。原生多标签共享、隐藏/关闭节流、容量/重启等边界复用未变模块及方法，不重复全量测试。完整当前绑定和三方结果已补入 ChineseChessGuide 既有 activity-evidence.json。
- **文件链接真实验收：** 当前 8764 的 `/api/file/open` 对同一 98 字节安全文本的正常盘符、`/E:/`、`/mnt/e/` 三种写法均 HTTP 200 / opened=true；不可映射 `/home`、远程 HTTPS、真实 cmd.exe、带 query 的 file URI 四例 HTTP 400，错误符合原限制（`8f3c72`）。未使用桌面控制；只确认真实 API/Windows 打开调用成功，默认应用画面未观察。四盘、中文空格、大小写/反斜杠/行号、URI/相对路径、真实本机文件优先和本系统消息提示保留原有效证据；Linux 实机不外推通过。

最终代表图已从本任务临时区保全到既有 validation：

- [桌面实际辅助面板与左栏日期](assist-live-desktop.png)，319883 字节，SHA256 `1403a1fb073fa8e6f0d6de05407c822b91ef63b4a9302fb2c6feb7e41d63b3ca`。
- [1024 深色实际页面](assist-live-intermediate.png)，240581 字节，SHA256 `5bde733d02ece9397c880349bbce2db082553bb44dee3ef5775e8065fcf0ced9`。
- [390 深色实际辅助区](assist-live-narrow.png)，67384 字节，SHA256 `d83f519b9a03cf8fb5b3e5b1408678ef608dcee69aabd8a9f16c0d551ee4538a`。

**验收边界：** 本阶段本地接入/运行加载、日期和文件链接通过；真实公网人数、生产 Node 兼容、空桌发布及公网资源验收不在本阶段完成项。Linux 实机和默认应用画面未验证，已更新共享看板；没有新增数据库/常驻服务/计划任务/备份，也没有改材料重复计数问题。文件清点与最终清理结果附于本节后续补记。

**最终文件清点与收尾：** 已执行 th123 `session_inventory.py --since 2026-10-29T23:05:00+08:00`，限定三个项目（`5bdf9c`）；本轮正式更新 7 份既有记录（MA4 README/本文、ChineseChessGuide README/activity-evidence.json、ace-21 README/activity-current.json、共享看板），新增上述 3 张正式代表图共 627848 字节。业务源码和后端测试输出未改；原有全部未提交成果保留。当前原生 daemon 身份与监听复核仍正常：MA4 仅 127.0.0.1:8764/PID48236，原辅助预览仍 127.0.0.1:4185/PID35208（`b49fef`）；自建 Node/Python/Chrome 检查进程均退出，未新增常驻或计划任务。没有备份/打包。

必要结果保全后，经 `ma4_artifacts clean` 精确删除 **36 项、5420479 字节**：MA4 controller 20 项临时方法/结果/截图、panel/revision4 15 项制作图/报告，以及 ChineseChessGuide 的 1 个 frontend-backend.json。前后端原始结果内容已嵌入既有 activity-evidence.json，七场景结果也嵌入该文件及后端当前证据；MA4在线结果、失败与比对方法完整记在本节，代表图摘要匹配。所有删除对象均为本任务生成、进程已退出、无正式运行依赖，且不属于此前被拒绝清理的旧材料。下方旧暂存文件名/尺寸仅为当时清单，恢复或复用应以本节正式记录及现有测试入口为准，不再依赖已清理临时脚本和图片。

物理剩余清点（排除归属标记）为 **377 文件、25802148 字节**：MA4 19/1841487（旧 panel 18 项此前清理被拒，另保留本轮已由默认应用打开的 98 字节样例，应用关闭后再复查）；ChineseChessGuide 347/23932476（旧截图及 Chrome 缓存，精确清单沿既有 cleanup.temporary_items）；ace-21 11/28185（此前拒绝的 8 项及 3 项单次主机公钥/诊断）。自动审批此前只返回 `blocked by policy`，本轮未换方式删除，保留理由与允许清理后的复查条件已记录。旧原生会话日志、归属标记及用户资料不动，空目录骨架不等于新增数据。工具路径重复/截断计数未修，本节采用实际文件数。7 份记录 UTF-8/LF、JSON 解析、正式图片摘要与 Git 空白检查通过。

## 辅助统计单独启用与会话日期（2026-10-29，目标修订 4；以下为制作及加载前记录）

**当前阶段与本次新测：** MA4 本地制作、自测和说明完成；默认仅保留中象辅助这个新增统计，停用默认 VPS TCP / 中象大厅，原实现与证据保留。Python **170 项：166 通过、4 跳过**；Node **13/13**，三项语法检查通过；系统 Chrome **六组布局**及定点复测通过。**复用：** 修订 3 的 HTTP/TCP 混合探测实现和 `test_health.py` 未变，其摘要和原记录可读，保留其 5 项通过及真实 TCP 结果的原时间边界，本轮不再探测 TCP。路径修复七文件中 hub.py/controllers.py/test_hub.py/test_controllers.py 已改变，相关回归本次重跑；paths.py/test_platform.py/test_markdown.mjs 摘要仍匹配，保留原解析、平台映射和 Markdown 证据，不宣称重跑旧 161/23 项。旧 18 文件及上述 6 个保留源码/测试共 24 项摘要前后完全一致（包含 health.py/test_health.py/test_server.py），旧图未覆盖或删除。**未验证：** 8764 未重载、远端辅助后端未发布、Linux 未实测；在线日期修复及辅助真实恢复不算完成。未向公网发送访客心跳、操作真实用户任务、SSH、部署、push 或重启共享进程；未改 paths.py、材料重复计数或 ChineseChessGuide。

### 最小复现与修复依据

- **只读实证：** 本轮查询已有 `/api/state` 后，仅输出本 MA4 中控 `01a181f9-eab5-7040-913d-0188b7e0d91d` 的状态、日期及必要回合时间字段，不输出消息/任务正文。读取时已 idle，`threads.updatedAt=1793182002`，即北京时间 **2026-10-28 18:06:42**；自己的近期完成回合已明确记录 `completedAt=1793269789`，即 **2026-10-29 18:29:49**，无 timeEstimated 标志。与中控此前 `acf44e` 的 running 实证属于不同观察时刻，旧日期异常仍存在。
- **修前确定性复现：** 用已有 `FakeClient` + 临时 Hub，旧列表时间 100；收到 `turn/started.startedAt=200` 后仍为 **100**；在可控时钟 300 下收到一般 status 通知变成 **300**；再刷新旧列表退回 **100**。源码对应 turn 通知未更新摘要、`update_status` 用当前时间、`summarize` 仅取 daemon 列表字段。不是时区显示问题。
- **修复：** `hub.py` 仅在明确 turn 时间到达、既有单回合元数据读取或已有同会话统计可用时推进时间；将其与原元数据及已有内存值取最大，旧刷新、乱序和重连不能回退。status 通知不再制造当前活动时间。回合时间缺失时运行时长也不补造开始时刻。`controllers.py` 只从已有 metrics 的明确 startedAt/completedAt 推导每个 session 的 updatedAt；旧 timeEstimated 可能包含恢复时间，保守排除。推导值只进入现有公开视图，不新增持久索引、数据格式或全量历史扫描。第一眼保持安静、后续未读/排序和已读处理沿用原规则。
- **UI：** `web/controllers.js` 的缺行回退不再用 task.updatedAt，当前中控、worker、formerHost 各取自己的统计；普通会话按自身元数据。浏览器仅在内存保留已经看到的新时间，旧 threads 通知和重新读取 state 不回退。空值、非数值、非正数显示“时间未知”；相对时间保留，title 提供本地完整日期时间。归属、权限、展开/选择及键盘入口不变。
- **真实数据隔离验证：** 把上述真实日期字段送入临时 Hub/FakeClient，新结果 `updatedAt=1793269789`，重复旧列表仍为该值；实际会话写入 **0**，历史读取 **0**。运行中 8764 此时仍返回旧时间，不把隔离结果当在线成功。

### 默认统计与测试

- `config.json` 仅移除默认 TCP 项，HTTP 健康保留；`activity.py` 仅从 SERVICES 移除 xiangqi，保留其 GET/去重实现和测试。默认快照是 texas、ace21、xiangqi-assist、chat 四项，禁用项不显示成“未知”。未增加启用开关体系；未来启用需要明确改变默认配置/列表。辅助沿既定公开 GET 契约、60 秒调度及现有 `/api/side`，不收集或发送访客标识。对应 `test_activity` 验证默认无 TCP、无 xiangqi 调度和快照行、原两大厅/Chat 节奏不变。远端仍未发布，本轮沿用前阶段真实失败事实及当前任务说明，未额外发公网探测或心跳。
- **最小新增检查：** 5 个 Hub 日期测试 + 1 个 Controllers 日期测试 + 13 个 Activity 测试，共 **19/19，0.090 秒**。覆盖明确活动时刻、无可信时间、任意状态通知、刷新中到达事件、旧元数据、重连、不同会话隔离、已有统计恢复及普通会话兼容。
- **受影响回归：** th123 Python **3.10.19**，`test_hub` 59、`test_controllers` 87、`test_activity` 13、`test_server` 11，共 **170 项，166 通过、0 失败、0 错误、4 跳过，14.345 秒**。四项仍为原 Windows 符号链接权限缺口；本轮没有新跳过。覆盖被改 Hub/中控共享核心、文件打开/拒绝、每轮路径消息、权限、归属、普通会话、预算/恢复/报告及 HTTP 本机边界；临时文件均定向 revision4。没有跑不受影响的 appserver、桌面启动器、平台全套或新的模型实验。
- **Node：** `node --test test_controllers.mjs` **13/13**，含新会话时间推导、跨会话隔离和旧列表合并检查；原归属、普通分组、报告、权限范围展示检查保留。`node --check` 对 app.js、controllers.js、service_activity_check.mjs 三项通过。依赖仍为已有 Node v24.11.1 / 系统 Chrome / 现有 Playwright 缓存，无安装。
- **Chrome：** 现有 `tools/service_activity_check.mjs` 默认自建独立 localhost 临时端口，API 全部模拟。1440/1024/390 × 浅深主题共六组：辅助查询中、非 0、合法 0、积累、失败、非法、超时、过期、恢复 **9 状态/组**；默认无 VPS / 中象大厅；相邻额度、HTTP 健康、Chat 详情与转义、焦点/回车选择/权限显示、前任中控未知、普通会话日期、状态不跨会话污染、完整日期 title、旧列表及断线重连不回退。六组均无横向溢出、脚本/控制台/资源错误、远端请求；未向真实会话发消息。正常截图在日期/键盘场景后采集。已实际查看首张 1440 浅色、整体预览、1024 深色、390 深色相邻卡片和状态预览。
- **失败与定点处理：** 新页面模拟数据先缺 `statistics.roles`，继而缺 session.usage，触发两个明确 TypeError；不是产品改动错误。补齐与真实响应一致的模拟字段，仅复测 1440 浅色通过，再跑六组正式覆盖。最初 PowerShell 包装结束码被后续 Remove-Item Env 命令覆盖为 0，但脚本报告/错误已明确失败，未记作通过；随后显式保留 Node 退出码。最终报告 `problems=[]`。没有因此重跑无关产品检查。

按需复核（截图只放新子目录，不覆盖旧证据）：

```powershell
& D:/python/anaconda/envs/th123/python.exe -B -X utf8 -c "import tempfile,unittest; from pathlib import Path; tempfile.tempdir=str(Path('.agent-tmp/ma4-e65cd30e77cb455d/panel/revision4').resolve()); unittest.main(module=None,argv=['unittest','-q','test_hub','test_controllers','test_activity','test_server'])"
node --test test_controllers.mjs
node tools/service_activity_check.mjs .agent-tmp/ma4-e65cd30e77cb455d/panel/revision4
```

页面入口支持 `MA4_PANEL_LAYOUT=1440-light` 等定点筛选；仅显式 `MA4_PANEL_DEFERRED=1` 才载入未默认启用两项的模拟场景，不改变产品配置。正式六组结果为 `revision4/report.json`。源码/测试摘要如下，需复用时只核对相应项与运行条件：

| 文件 | SHA256 |
|---|---|
| activity.py | `8cd685ffb0277a594b9c81a88d26c6fcbe3e6c8d245e3afd9d40d63b960f1684` |
| config.json | `b8e6a90b8677ebad9f58745496cf84e111d8f1ca711edac9726a03e2a7a0d0ca` |
| hub.py | `4fa0e26b44937e0f741a38dce6da2a336a8da1ad67c59401ee26cb4d2a2dfe71` |
| controllers.py | `6776bd9f1fdfdb273c61c1adb4ed4af4c463d85aa9e6d65b8666b3e0a759975e` |
| web/app.js | `23037c4af9666ca3f56677a6643460153a83ee2ff4c898e596aab784b83bab1e` |
| web/controllers.js | `2a4d86623646b0d852431c6a02de3f288c325ed6644910c1a393d27c48465f80` |
| test_activity.py | `f782aa984f85cedbfcaed6fcc298d68df615f4ad3c8413a03a20fdc2624666ca` |
| test_hub.py | `67d30ef8f9aca9495891bc0eb4b6ef45f44bb4d6a0e9fa9a469e8ac2c6dcdfa0` |
| test_controllers.py | `fc8d22676d8a1bc809801564892bdfff7d72c0cc344f5e68269681e1a7821afc` |
| test_controllers.mjs | `9ad31ecd075c6ff858d14d52eba0f4decdf8a1b43914e7d17dfd7bbc989d4a1a` |
| tools/service_activity_check.mjs | `4e679aa02fe16d8718ec786b32733c5a40acae1757781781292b10907b8a3a48` |

- **最终计时边界补查：** 收尾在原日期测试内加入“先恢复估算完成时间，后收到真实开始时间”的断言，修前实测失败：前任会话误得 1000，预期未知。原因是 record_turn 见到 startedAt 就清除了整轮估算标记。现仅在已存的时间边界都得到明确替换时清标记，避免将恢复时钟当活动。随后只跑该失败项、轮次用量/迟到重复/重启、结束计时、旧数据恢复、恢复用量间隔、Hub 同会话恢复共 **6/6，0.536 秒**；包含在上面 170 个测试方法内，不累加为 176 项。其余回归结果依未改行为复用，未重跑全套或页面。最终两项更新摘要已列入上表对应位置；先前 170 项全套是在此小修之前完成。

### 中控独立核验与在线阻碍（2026-10-29 18:55，UTC+8）

- **复用有效性：** 亲读日期、默认统计、前后端实现及测试方法；复算上表 11 项源码/测试摘要全部匹配，六组浏览器报告 `problems=[]`，已实际查看整体和状态图。辅助模块、入口及受保护文件、后端绑定的独立核对和四项真实 Chrome/后端检查已记在 ChineseChessGuide `research/activity-evidence.json.controller_review`；不重跑其 26 项或后端全套。
- **新增日期抽查：** 真实错误时间 1793182002 与可信完成时间 1793269789 输入隔离 Hub/FakeClient。先新完成、后旧开始，再任意状态通知和旧列表刷新，host 保持 1793269789；ordinary 保持 1793181000，missing 为 null。断线重连后完全一致，带 timeEstimated 的恢复时间不参与活动，模型调用 0。源码摘要和断言均通过（`f31457`），不冒充在线成功。
- **新增真实三方通路：** Chrome 加载既有 4185 辅助预览，显式启用本地 endpoint；真实 ace-21 createServer 使用 `RoomStore(null)` / `TableStore(null)` / ActivityStore 注入时钟；真实 ActivityPoller 仅注入本机 HTTP 传输和测试时钟，不改默认 HTTPS 限制；真实 MA4 Server、原前端文件以及 FakeClient 隔离原生会话。7 场景比对聚合、Poller、`/api/side`、DOM：心跳 count=1/collecting/积累中；300000ms 到期 count=0/ok/0；另一浏览器上下文心跳 count=1/ok/1；后端真实 503 后 unknown/null/未知；恢复 1；缓存 generated_at 过期后未知；新 GET 后恢复 1。监控 GET 未增加心跳或延长活跃，共 2 POST、远端请求 0、脚本错误 0。输出 `29faa5`；截图时序修正后复核 `733165`，不重复累计 7 场景。自建浏览器、服务器及 Python 子进程已退出，原 4185/8764 未停止。
- **方法失败：** 首次只推进后端时钟却用同一浏览器预期立即第二次心跳，实际被正确的 60 秒节流阻止；测试包装另漏 prune，出现 TypeError。补齐包装、第二访客改为新上下文后通过，未修改产品。首批截图采集过早，入场动画使画面半透明；按现有 reducedMotion 方法等 300ms 后重新采集，实际查看 1440 页面，辅助值、口径和相邻区域可辨，无横向溢出。初次失败不计通过。
- **安全检查与未完成：** 只读 `/api/state` 和当前 controllers 状态发现另一 host `01a1828e-5d70-7e60-82e8-edc855a77cd4` 为 running，所属任务 `54e0ee423c2d4b79` 虽 paused 但 hostBusy=true，授权工作范围仅 ChineseChessGuide。因此没有执行网页 stop/start，也不写该项目 README/证据，新三方结论暂记此处（`29f038` / `d23cf7`）。本 host 在线仍返回 1793182002。按修订 4 安全约束暂停；在线日期/辅助未知、文件链接真实成功及重载状态保留仍未验收，不能 finish。未 SSH、推送、部署或发公网心跳，Linux/默认应用画面未实测。
- **材料：** 新 `controller/three-way.mjs`、`three-way.json`、四张 `local-*.png` 均为本任务临时检查材料；只需一张正常图支持通路，其他状态已有本文结果及制作方状态证据。修订 4 的 15 份制作材料留至在线验收，旧清理拒绝材料不换方式处理；本轮精确清理及物理清点见后续补记。

**本轮清点补记：** 已运行 th123 `session_inventory.py --since 2026-10-29T18:52:00+08:00`，限定 MA4/ChineseChessGuide/ace-21 三项目（`35ee86`）。本轮正式修改只有 MA4 README、本文和共享看板 M-20261028-01；业务源码未改，两个外部项目无新写入。`ma4_artifacts clean` 成功清理本轮 `controller/local-partial.png`、`local-zero.png`、`local-unknown.png` 三张无依赖截图，共 717805 字节。保留 `local-one.png`、`three-way.json`、`three-way.mjs` 三项共 247343 字节，SHA256 分别为 `758acdf1cfbb58a3c0d2d10b1d2ce10a216a0ad86b9c459edec0f481208988cf`、`a90a03dc649d122a8427f43cc8ec61114735ceb2ea84dea7cedb52812bed2b5b`、`878d40d6d64145ad2b0412449779f3e52a2e6ca569671681d5d6bfef7972c911`；和 revision4 的 15 份材料共 18 项登记保留至在线验收。物理清点（不含归属标记）MA4 37 文件/4113357 字节、ChineseChessGuide 348/23934197、ace-21 11/28185。工具路径重复计数与 200 条截断问题未修，不采用其汇总数。此前自动审批拒绝的旧材料原样保留，未换方式删除；无新增备份、打包、计划任务或常驻服务。本轮两个子服务器、Python 和测试 Chrome 均由 finally 关闭，MA4 与原辅助预览保持。文档 UTF-8/LF、`git diff --check` 通过；运行中 `.ma4` 三项自动更新不是手写成果，不清理。

### 本阶段文件去向

已运行只读 `session_inventory.py --since 2026-10-29T18:20:00+08:00 --root E:/PG/MA4-win`。逐项核对本阶段 13 个正式文件及 15 个新材料；运行中 .ma4 三个状态文件为服务自动更新，未手工修改或清理。11 项源码/测试摘要匹配，13 文件 UTF-8 无 BOM/LF，报告六组均 deferred=false、九状态，Git diff 空白检查通过。

本轮正式变动为上表 11 文件及 README/本记录，共 13 文件；config.json 恢复为不含 TCP 的默认配置，因此可能不再出现在相对 HEAD 的 Git 差异中。旧未提交修改全部保留。新材料仅在 `.agent-tmp/ma4-e65cd30e77cb455d/panel/revision4/`，无正式运行依赖；先看两个整体图，再按需读原图，审查后复查清理：

- `overview.png`（1536×1280）、`states-overview.png`（1500×540）。
- 六张正常原图：`1440-light-normal.png`、`1440-dark-normal.png`、`1024-light-normal.png`、`1024-dark-normal.png`、`390-light-normal.png`、`390-dark-normal.png`。
- 六张状态原图：`390-light-collecting.png`、`390-light-expired.png`、`390-dark-pending.png`、`390-dark-collecting.png`、`390-dark-failure.png`、`390-dark-expired.png`。
- 六组检查报告 `report.json`。共 **15 文件、2,024,527 字节**，均为明确模拟素材或检查结果。

本轮 `TemporaryDirectory` 自动回收；结束后验证新 browser-cache 仅剩一个空目录，按精确路径删除空子目录、空缓存根及多余的 `report-1440-light.json`，成功。预览端口已关闭。旧 panel 18 文件（1,841,389 字节）与原空缓存的 keep 登记继续保留，未尝试清理、未覆盖旧截图、未改原生会话日志。不新增备份、打包、常驻/定时服务。Linux 看板不在本轮写入范围，本阶段未实测事项由中控在授权范围交接；在线重载与远端发布另阶段处理。

## 面板制作与本地自测（2026-10-29，目标修订 3）

**本次新测：** 仅本地实现、自测及下述 TCP/公开聚合 GET 检查。Python 28/28、Node 语法 2/2、Chrome 六组布局通过，无测试失败或跳过。**复用结果：** 下方「文件链接修复」节的 7 个源码/测试文件 SHA256 本轮重新计算全部一致，相关打开路径逻辑、测试方法及本机 Python 条件未改变，因此保留该结果及在线未生效限制；不将原 161/23 项并入本次新测。面板自身受影响检查全部新测，不复用旧“三项服务”截图来证明新增行。**未验证：** 8764 未重载、辅助统计后端未发布、Linux 未实测、未访问真实 Chat 访客或额度凭据、未操作用户任务；未声称线上完成。原材料重复计数缺陷仍未修复。

### 实现与覆盖范围

- `health.py` 复用约 300 秒轮询，配置用明确 `type: tcp` / `host` / `port`，原 HTTP 项省略 type 仍兼容。TCP 使用 Python 标准库、3 秒超时，连接后关闭，不发送应用字节、不登录、不改网络配置；失败不阻塞随后 HTTP 项。快照超过 615 秒标过期。页面将 TCP 地址呈现为文本，保留 HTTP 网页链接，显示最近检查日期时间及网络可达性口径。
- `activity.py` 中象大厅复用 `games_url/tables/xiangqi` 和不入座的观察者 GET；与德州、王牌一致，仅计 online 座位并跨桌按 id 去重。辅助读取 `games_url/activity/xiangqi-assist`，无 Authorization 和新增凭据，仅保留聚合字段；5 项仍在同一轮询线程中调度，三种大厅 15 秒、辅助和 Chat 60 秒。UI 沿原 15 秒 `/api/side` 读取内存结果，不直连远端、不新增轮询。
- 辅助契约校验 service、300 秒窗口、非负安全整数 count、有限时间值、布尔 complete_window，检查 observed_since 不晚于 generated_at 且完整标志与已观察时长一致。generated_at 与本机时间差超过 120 秒或缓存超过原轮询容差即未知；不足 300 秒显示积累中，暂不把部分窗口数当成完整五分钟值。坏数据、缺字段、超时与失败均隐藏旧数。测试额外放入明确模拟的 visitorId，确认 API 响应不含该字段。
- 保留原玻璃样式及相邻卡片布局，仅增加新行、统计口径和状态字样；健康、额度、德州/王牌/Chat、任务界面继续使用原入口。没有修改 `server.py`、系统适配器、系统配置文件或任何路径修复源码/测试；公共实现无平台专用调用。

### 实际检查与证据

- **Python**：th123 **3.10.19**，`-B -X utf8`，`test_activity` 12 项、`test_health` 5 项、`test_server` 11 项，共 **28/28 通过，0 失败、0 错误、0 跳过，0.796 秒**（本会话原生工具输出为 `Ran 28 tests ... OK`，未复制会话日志）。覆盖合法 0/非 0、跨桌去重、观察者不计数、独立时序、缺失/非法/过期数据、重启积累、超时隐藏旧数、无凭据公开 GET、HTTP 混合健康项。标准库本机 TCP listener 收到 EOF/零应用字节；真实 `Server` 临时端口验证 `/api/state` 和 `/api/side` 传递类型与聚合结果，反复读取不触发新探测。原本地 Origin 保护检查保留。测试临时文件均定向 panel，TemporaryDirectory 自动回收。Windows `runtime.load_config()` 读取当前配置通过，包含新 TCP 项和原 games_url。
- **Node / Chrome**：Node **v24.11.1**，系统 Chrome **156.0.8078.48** 与已有 Playwright 缓存；`node --check web/app.js`、`node --check tools/service_activity_check.mjs` 均通过。复用并扩充 `tools/service_activity_check.mjs`，默认自建 `127.0.0.1:0` 静态预览，全部 API 明确模拟，禁止 8764 作为预览目标；可用 `MA4_PANEL_LAYOUT=390-dark` 筛选。首张 1440 浅色整体先查看，随后 **1440/1024/390 × light/dark 六组**，每组 8 种统计状态（查询中、正常非 0、0、积累、失败、坏数据、超时、过期），并测 TCP 查询中/可达/不可达/过期、HTTP 链接、额度相邻区、Chat 键盘详情/转义/实时更新/失败禁用、重连状态。六组最终状态无横向溢出，脚本与控制台错误 0、资源 HTTP 错误 0、远端请求 0；新行未产生额外 UI 请求。新增逐状态溢出断言后仅追加 390 深色筛选检查，同样通过。六组结果在 `panel/report.json`，追加结果在 `panel/report-390-dark.json`；独立端口随脚本 finally 关闭，无后台预览常驻。没有下载浏览器或使用 Windows 桌面控制。
- **实图查看**：1440 浅色整体；1536×1200 `overview.png`（1440 深色整体、1024 浅色相邻区域、390 浅色右栏）；1024 深色完整页面；390 深色正常右栏局部；1500×820 `states-overview.png`（查询中、积累、失败、过期及 TCP 状态）。确认新增行、统计口径、相邻健康/额度可辨，没有文字遮挡；原先 1024 下卡片等高布局保留。
- **真实公共检查**：2026-10-29 17:34（UTC+8）单次 `probe_tcp('51.79.241.161', 22)` 返回 `ok=true, ms=16`；只连接关闭。单次辅助 GET 经实际 `ActivityPoller.collect('xiangqi-assist')` 得 `status=unknown, count=null, error=查询失败，暂无法确认`；线上未发布时正确显示未知，未将其说成 0 或后端已完成。未读取/输出真实访客列表或凭据。其他 HTTP 健康项在隔离测试中验证，不把模拟 200 写作本轮在线实测。
- **失败与边界**：无产品自测失败；一次编辑工具拒绝同一补丁对同一文件做删除/新增，改为正常替换既有入口后成功，未留下中间脚本。收尾清理命令被自动审批拒绝（`blocked by policy`，未给具体原因），命令未执行，未尝试换方式删除。Linux 配置沿现有合并规则、不覆盖 health，代码使用跨平台标准库；这只是源码检查，不能等同 Linux 实机通过。Linux 看板不在本轮写入范围，需中控在其授权范围登记。

复核命令（不调用模型，不接触 8764；先确认仍获准使用本任务临时目录）：

```powershell
& D:/python/anaconda/envs/th123/python.exe -B -X utf8 -c "import tempfile,unittest; from pathlib import Path; tempfile.tempdir=str(Path('.agent-tmp/ma4-e65cd30e77cb455d/panel').resolve()); unittest.main(module=None, argv=['unittest','-q','test_activity','test_health','test_server'])"
node --check web/app.js
node --check tools/service_activity_check.mjs
node tools/service_activity_check.mjs .agent-tmp/ma4-e65cd30e77cb455d/panel
```

源码与测试 SHA256（便于按需核对是否仍可复用本节结果，不要求无关变更重跑）：

| 文件 | SHA256 |
|---|---|
| activity.py | `4fc7543f284f2f0751446f1c198eb1f75bcd69b7be38de8a36e9fb59ddbaeb1a` |
| health.py | `f8d58fa469de3c2a4505805c4d6399461d2411e2f2cdceae1733b2e1f482cbcb` |
| config.json | `a23d7e5f2507941983cd9f35ec30f55359a9965dfc2365ec7702d2af3e895b12` |
| web/app.js | `f5977f5d4b1938656888d546fe9308d495f90748dd2b7327ca353e59b8057961` |
| web/index.html | `0307c52ff886b91a5b3e29a6eb0faa1de73a77db5914e9645a897e0dccdc483a` |
| web/style.css | `fbf19f26fceade51d9f98e946977e7a2306840379d3576e6af8cd977ed6a4847` |
| test_activity.py | `17f5b0484ce6d4e35c32f14b6bc341ea56c144d477d8b724a6dfeda4d3c9b124` |
| test_health.py | `ed5592334a8a952999383e463199ce1f120ed206a2ac434ca5a125eabedbd105` |
| test_server.py | `bd58dc91f7f64ef9b1ff48aefbc36a11181825ae51c55541be0411d19e5287d0` |
| tools/service_activity_check.mjs | `7678475b4d7642d7ee201643bc54ceb5589784d34f49651dabdf7bb830b53f93` |

### 文件清点与交接

**发布阻碍复核（2026-10-29）：** 后端执行会话 `01a186fb-d874-73d3-851d-a31f9464f495` 的后续回合 `01a18710-2326-7770-b10e-4c2549fb134c` 使用本任务临时公钥信任文件、StrictHostKeyChecking=yes、BatchMode=yes 和现有 Windows id_rsa，仅进行一次认证；记录为主机身份匹配、公钥已提供但服务器未接受、退出 255/Permission denied (publickey)，无远端 shell。中控亲读检查实现及 `E:/PG/game_dev/ace-21/tests/xiangqi-evidence/activity-current.json`，独立用 ssh-keygen 重算公钥指纹、与 OVH README 比对一致，核对正式记录与临时证据一致；前轮测试输出和 34 项未改摘要仍匹配（输出 `268dbb`），没有重试认证或重跑无关测试。生产目录、服务身份、牌局占用、sudo、Node 22 兼容及部署均未验证；辅助页接入仍受其他任务写入范围阻挡。按正式目标暂停，等待已有可用连接入口及写入范围释放；未改全局 SSH 配置、未发布或重载任何服务。后端 11 份临时材料共 28,185 字节保留，其中 3 份本轮新增公钥/检查脚本/结果共 8,001 字节用于诊断；前 8 份的自动审批清理拒绝继续保留，不绕过。

**中控独立核对（2026-10-29 17:49，UTC+8）：** 亲读 `activity.py`、`health.py`、前端差异、现有测试及两份浏览器报告；上述 10 项源码/测试 SHA256 全部匹配。实际查看整体预览、状态预览及 1024 深色完整页面，确认三项口径、正常/未知/积累/过期状态与相邻区域可辨。另以可控时间独立验证辅助缓存新鲜→过期→重启积累→非法计数→合法 0 恢复，以及 TCP 过期与失败清除旧耗时，均通过。单次真实 `/tables/xiangqi` 只读响应含 4 张桌，中控直接遍历在线座位按 id 去重得 0，`game_activity` 同得 0；没有入座或发送用户操作。独立 TCP 仅连接关闭，返回可达 31 ms。原始输出 `2e53c3`；检查脚本首次误匹配到旧节表格的用途列，在文件摘要阶段退出（`dfb371`），限于本节 10 项后通过，没有修改产品代码。沿用仍有效的制作方六组布局结果，不重跑全套；当前运行中 8764、新后端与辅助页发布仍未验收。18 个 panel 材料及空缓存继续保留，清理拒绝未被绕过。

已运行 `project-file-lifecycle/scripts/session_inventory.py --since 2026-10-29T17:24:00+08:00 --root E:/PG/MA4-win`。正式修改为上述 10 个代码/配置/测试文件及 README、本记录，共 12 个；前阶段另 7 个代码/测试文件字节未变，原 README/验证内容仅增补。清点还列出既有服务自动更新的 `.ma4/controllers.json`、`quota-cache.json`、`prefs.json`，不是本执行者手动写入，未读取其敏感正文或清理。没有新增常驻服务、计划任务、备份、打包或全量浏览器副本；未提交、push、部署或重载服务。

本轮材料均在 `.agent-tmp/ma4-e65cd30e77cb455d/panel/`，默认 Git 忽略。先看两个整体预览，按需读取原图/报告；必要结果和方法已经写在本记录，不以暂存文件作为正式运行依赖。因清理被自动审批拒绝，以下 **18 文件，共 1,841,389 字节，及 browser-cache 空目录结构（0 文件）**暂留供中控审查；审查结束且允许清理后复查，旧任务材料和原生会话日志不动。最终复核 10 项源码摘要、12 文件 UTF-8 无 BOM/LF、两份报告及全部所列截图均完整；两份报告记录的独立预览端口均已关闭，`git diff --check` 通过：

- 整体预览：`overview.png`、`states-overview.png`。
- 六张正常原图：`1440-light-normal.png`、`1440-dark-normal.png`、`1024-light-normal.png`、`1024-dark-normal.png`、`390-light-normal.png`、`390-dark-normal.png`。
- 状态原图：`390-light-collecting.png`、`390-light-expired.png`、`390-dark-collecting.png`、`390-dark-expired.png`、`390-dark-pending.png`、`390-dark-failure.png`、`390-dark-tcp-pending.png`、`390-dark-tcp-expired.png`。深色六张已在状态预览中原尺寸合成；冗余单图未能清理。
- 报告：`report.json`、`report-390-dark.json`；缓存：`browser-cache/`（Chrome 已由 finally 关闭，残留目录仍保留）。未另建过程报告或历史副本。

## 文件链接修复（2026-10-28，目标修订 2）

**本轮新测：** Windows 文件链接源码、自测和隔离 HTTP 检查完成；在线 `127.0.0.1:8764` 尚未重载，因此新解析与消息规则尚未在线生效。开始 HEAD 为 `682e708b9afde0cbfc42222395bcfebba69a89ec`，原有未提交 README SHA256 `a2d095fe35f2d356590bfa2114f78e0b5981ff2c42dde7e3df7f3ed8570ecc84`、本文件 `15d880ab38ca6b5782b7f6b77c2cce6c188bce67352351d6b1f8f620db326c67` 均先核对一致，再追加本节；此前账单与 artifact 重复计数的记录保留。未改 `scratch_cwds`、目录去重或运行数据。

**中控独立核验与当前阻碍：** 已先审查实际三处业务改动与四个测试文件，再核对上表 7 文件 SHA256 全部匹配及样例摘要一致（`966822`），现有自测证据与当前源码对应。新增 27 种实际 E 盘样例引用（9 种写法×3 种行号形式）、C/D/E/F 两方向共 8 项独立映射断言、6 项拒绝输入及当前系统每轮消息说明均通过，样例仍为 98 字节（`c35f0f`）。当前 8764 的真实 POST `/api/file/open` 对 `/E:/…`、`/mnt/e/…` 仍各返回 HTTP 400，错误路径与修前一致（`cd72c0`），证明在线尚未加载修复。首次观察无其他活跃会话；受控重载脚本再次检查时出现另一运行会话，安全断言在任何 stop/start 命令之前退出（`51e354`）；只读复查确认其他会话状态 running（`b27e19`）。因此未重启网页或后台，在线成功打开及重载前后状态保留尚未验收，按目标约束暂停，待其他会话空闲后恢复。Linux 实机待核验已写共享看板 M-20261028-01。

**复用与未验证：** 复用项目既有 Hub、消息/恢复、HTTP 与 Node 测试入口；迁移阶段的旧通过数未计入本轮。旧记录已读取，保留其原对象与证据边界。Linux 本轮只在 Windows 做纯映射及模拟 POSIX 文件系统检查，未实测 Linux 挂载、文件权限、默认应用或服务；C/D/F 和其他 Windows 盘符的映射不代表这些盘上真实文件已逐盘打开。未重开真实模型实验、操作桌面或验收默认应用画面。

- **原 bug 前后：** 修前用真实项目 README 和捕获打开参数的 `Hub.open_file` 最小复现：`E:/PG/MA4-win/README.md` 成功；`/E:/PG/MA4-win/README.md` 报不存在，误得 `E:\PG\MA4-win\PG\MA4-win\README.md`；`/mnt/e/PG/MA4-win/README.md` 误得 `E:\mnt\e\PG\MA4-win\README.md`。修后通过隔离 `/api/file/open` 对三者均返回 HTTP 200 / `opened=true`，捕获目标均为 `E:\PG\MA4-win\README.md`。工具输出 `287c42`（修前）、`061564`（修后）。
- **实现边界：** `paths.py` 新增文件链接专用平台映射和解析，未改变授权路径 identity/overlap/link 检查。Windows 将 C/D/E/F 的 `/mnt` 写法转盘符，保留其他本机盘；Linux 保留原盘符转 `/mnt/<小写盘符>` 行为，并修正前置 `/` 与 URI 分支。先找真实本机文件，再尝试映射、移除末尾行号和一次解码；URI 的 `%23L12` 是真实文件名，不能再次剥离成行号。保留根目录 `/mnt/e` → `E:/`，拒绝 `E:`/盘符相对路径、远程/UNC、含控制字符及不支持的 URI。Windows `/home` 等无法对应时明确报错，不拼到 cwd；普通相对引用仍按会话 cwd。
- **消息覆盖：** `controllers.file_link_guidance` 按运行系统生成示例；中控/执行者新建说明与 `message_envelope` 每轮附带该规则，包含复用执行者、已有中控、恢复后的后续发送。现有恢复测试证明不重复发送旧消息、不改已有历史；本机示例与双平台规则模拟均通过。未修改用户全局指令或客户端配置。
- **Python 新测：** th123 Python **3.10.19**，`-B -X utf8`；先跑 12 项最小相关检查，10 通过、2 错误。两项均为新增测试写法错误（移除 cwd 后留下空会话对象、误用不存在的 `start_worker`），修正为保留 id 与使用现有 `launch`，两项复测通过（`4d7253`）。随后新增 Linux 文件系统模拟单项通过（`369793`）。最终运行 `test_hub test_controllers test_platform test_server`：**161 项，157 通过、0 失败、0 错误、4 跳过**，耗时 15.213 秒（`f62c15` / `7e6843`）。跳过的仍是此前四项 symlink 权限检查；真实 Junction 测试通过。文件拒绝用惰性文本样例和捕获 `os.startfile`，没有运行可执行文件。临时目录由进程内 `tempfile.tempdir` 限定在本任务 `file-links`。
- **覆盖重点：** 四盘×大小写×正反斜杠×带/不带前置 `/`，两平台方向；盘根、中文空格、`:行:列`、`#L` 范围、localhost URI、相对路径/缺 cwd；真实 `%20`/`%FF`/`#L12` 文件名、一次解码及编码的行号后缀；Linux 的真实冒号/反斜杠文件名与 `/mnt/E` 优先按原路径定位由模拟文件系统覆盖。Windows 程序/脚本/快捷方式及 Linux `.desktop` 拒绝、默认应用错误、网络引用和控制字符边界均沿现有适配器检查。
- **Node 新测：** Node **v24.11.1**，`node --test test_markdown.mjs test_controllers.mjs test_paths.mjs`：**23/23 通过，无跳过或失败**（`178aaf`）。新增矩阵确认四盘、前置 `/`、URI、中文空格、行号及百分号字面内容原样进入 `data-file-path`；`web/markdown.js`、`web/app.js`、`server.py` 未改，点击仍 POST `/api/file/open`。
- **隔离 HTTP 新测：** 使用现有 `Server` + 真实 `Hub`，绑定 `127.0.0.1:0` 得到 **5643**；默认应用接口替换为参数捕获。E 盘真实安全文本 15 种路径写法与 README 三种写法全部 HTTP 200 且目标逐项相等；8 种网络/非共享 Linux/缺失/URI query 输入 HTTP 400 且无打开调用。**18 成功 + 8 拒绝，0 失败，真实应用启动 0**（`061564`）；线程、端口和测试 Hub 已关闭，不触碰 8764 或用户会话。现有 HTTP 单元测试另覆盖请求头、外部 Origin 和只允许 POST。

相关 Python 检查可在项目根复核（沿用既有模块，不调用模型；先确认该任务临时目录仍保留且允许使用）：

```powershell
& D:/python/anaconda/envs/th123/python.exe -B -X utf8 -c "import tempfile,unittest; from pathlib import Path; tempfile.tempdir=str(Path('.agent-tmp/ma4-e65cd30e77cb455d/file-links').resolve()); unittest.main(module=None, argv=['unittest','-q','test_hub','test_controllers','test_platform','test_server'])"
node --test test_markdown.mjs test_controllers.mjs test_paths.mjs
```

本轮代码/测试最终 SHA256（文档仅追加说明，不把这些值外推到后续改版）：

| 文件 | 改动 | SHA256 |
|---|---|---|
| `paths.py` | 文件链接映射、字面文件优先、引用解析 | `f3abf6e7b9ea1d4900264a2dac552c237b7bc1f132fe3841a1d47834e9b0e6a9` |
| `hub.py` | 沿打开入口调用公共解析，保留适配器 | `3750ea0ea4655547a495c3c962855558e53925671c9e84bfec98fbd61ddea160` |
| `controllers.py` | 本机路径示例，新建与每轮消息覆盖 | `8d53693b3df4ca090b98a0cab4097eeea724c77a8eed6d1b342a3db8bfac2d37` |
| `test_hub.py` | 真实文件、URI/行号/编码、拒绝边界 | `6f79f9527cf2bf3a4de1837a77ce3c5372db27887b00e0ca9146d0e7b36ea428` |
| `test_controllers.py` | 双平台规则、复用与恢复后发送 | `1462261433c5ed5d914f0fa447a3ce7b35989bf595825230f7c6a5678dbd29c8` |
| `test_platform.py` | 四盘双向映射、Linux 文件系统模拟 | `a086ffce1f9800a5fc18fa654c16e905f31e6d11c210c022643718c5ac43fb51` |
| `test_markdown.mjs` | 文件引用原样透传矩阵 | `5d4ac0c944720379b541a074e140467bf848d0daac9f5818e4aba91ca33fbd76` |

**交接与文件去向：** 正式成果为上表七文件、README 与本记录；无提交、推送、线上重载、安装依赖、全局配置或看板写入。只保留 `E:/PG/MA4-win/.agent-tmp/ma4-e65cd30e77cb455d/file-links/中文 空格样例.txt`，98 字节、UTF-8/LF，SHA256 `b8f7e8e8bfed0a558ccd237e0498b190ad6326051b96a877574c838b91bf3e0b`，用于中控后续真实 API 抽查；中控核验后再决定清理。自测状态/文本/模拟数据均由 `TemporaryDirectory` 回收，`file-links` 仅剩该样例；未写新报告、备份、截图或原生会话日志。任务根归属标记和旧材料未动。中控需独立核对 `%`/行号与真实同名文件优先关系、四盘映射边界及新旧会话消息规则，再判断安全重载和真实默认应用检查；Linux 实机与系统看板由中控收尾。

已用 th123 `-B -X utf8` 运行 `project-file-lifecycle/scripts/session_inventory.py --since 2026-10-28T20:43:00+08:00 --root E:/PG/MA4-win --top 15 --json`（输出 `cfaca7`），并结合 Git 范围与样例 SHA256 检查（`73d11d`）：本轮正式修改 9 文件，指定临时子目录仅上述样例，未发现本轮备份/打包/大文件，`git diff --check` 通过。清点同时列出的三项 `.ma4` 当前运行文件及任务根 `.ma4-owner.json` 非本执行者写入或清理对象，未读取其正文；其时间变化不算本轮源码成果。没有新增定时任务；Windows 计划任务未额外普查。

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

## Windows 迁移阶段实测（2026-10-27/28）

详细数量、任务/会话 ID、文件摘要、关键进程与回合证据见 [windows-parity.json](windows-parity.json)。测试对象为共享仓库 `505fe34` 加本轮修正；该 JSON 记录被测源码 SHA256。Windows 11 build 26200、th123 Python 3.10、Node 24.11.1；MA4 所选 CLI 与实际原生 daemon 均为 0.164.0。桌面 App 独立 app-server 进程所用二进制磁盘版本为 0.164.0-alpha.11.1，不能当作它的运行握手版本。

- **自动检查通过：** 最终 Python 179 项中 175 通过、0 失败、0 错误、4 跳过。跳过的是 `test_artifact_cleanup_requires_exact_safe_owned_files`、`test_invalid_owner_markers_are_never_replaced`、`test_shared_artifact_links_and_busy_workers_are_not_cleaned`、`test_symlinks_checked_again_at_launch_and_grant_confirmation`，原因均为本机无符号链接权限；未修改系统权限。真实 Windows Junction 和 3 项 TCP 启动器集成测试通过。Node 22 项全部通过。
- **页面通过：** 五组模拟 API 检查覆盖 1440/1024/390、浅深主题、键盘、讨论确认、报告、附件、服务活动及失败状态；实际页面三宽度无脚本/资源错误或横向溢出，查看了桌面/窄屏图。未使用真实用户会话发送测试消息。
- **实际修正：** `activity.py` 的父进程采用 UTF-8，但原凭据 CLI 子进程会输出 Windows 本地编码，导致解码失败。现在子进程显式 `-B -X utf8`、父进程显式 `encoding=utf-8`；新增真实子进程的非 UTF-8 默认环境回归检查，`test_activity` 7 项通过，真实 Chat 统计恢复。`web/app.js` 原先只在 SSE 错误时显示“未连接”，重连且无新 daemon 事件时不复原；现在重连后读取当前状态。模拟三宽度和实际网页重启连接均确认提示恢复。
- **测试修正：** `test_controllers.py` 对 JSON 解码后比较 Windows 路径，并用实际盘根代替字面 `/`；讨论页面测试等提交后的状态刷新结束再注入下一事件；实际网页脚本允许空中控列表这种合法已载入状态。未削弱原功能断言。
- **原生与启动通过：** 选中 `proxy://C:\Users\DTICPW\.codex\app-server-control\app-server-control.sock`，真实 initialize/loaded/list 成功。三次连接中含一次主动终止本次代理模拟断线，代理均回收，随后可重新连接；用户原生 daemon 保留。独立原生网页重复启动复用进程，`include_backend=True` 只停止该测试网页及其 proxy。现有快捷方式实际双击打开新窗口但复用网页 PID；关闭重复窗口后网页和 daemon 仍正常。没有启动新服务或自启。
- **终端通过与边界：** 对专属测试会话调用 `/api/terminal`，实际 remote TUI 连接相同原生端点；另一受控 TUI 在模型开始前接入并捕获报告、读取结果与完成事件，网页同时收到两轮 started/completed、流式 item/delta 和 token 事件。普通 CLI 的 resume 进程未带显式 `--remote`，其子进程为当前原生 daemon；桌面 App 另有独立 app-server。未对用户会话注入消息，因此不宣称这两类客户端的实时共享已经通过。另起并清理的隔离 TCP 后台可恢复本次**已空闲**的测试会话，HTTP 200；没有启动模型，不能以此证明运行中 409。
- **路径与侧栏：** 中文/空格文本文件由 `/api/file/open` 打开，在 Notepad3 中确认准确两行；小写盘符与编码后的 file URI 成功。实际 `.py`、`.cmd`、`.lnk` 均 HTTP 400 拒绝执行。HTML 由默认 Chrome 打开，窗口标题可见，但浏览器策略拒绝观察 `file://` 内容，故渲染未验收。通知为未授权状态，未操作授权弹窗或测试真实通知。凭据通过 credential-vault 读取，仅写本侧私有 `.ma4/quota-source.json`；使用同服务文档已支持的多家额度接口，当前 Codex/Claude/Grok/Gemini 均有效，muQ 与 21 点健康 HTTP 200，德州/21 点/Chat 统计均不陈旧（本次均 0）。不输出密钥 URL 或访客详情。
- **此前迁移阶段一次真实模型实验通过：** 任务 `dd779cf589e74a48`，中控 `01a17e40-f24f-74e1-ab04-7d1ac5f0d7bc`（2 轮），执行者 `01a17e43-1a92-73b3-b32e-f0ef7aef46cc`（1 轮）。116.96 秒，288,401 tokens，其中缓存输入 233,984、输出 3,121；没有提高 15 分钟/300,000 上限，该迁移阶段没有第二次模型实验。只产生 `验证 结果.txt`，66 字节，SHA256 `f3be67d616443ecf41d94abf87641a2443e05b6cd17bea50b7f9d5345ec71128`。中控真实命令读取后核对路径、UTF-8 无 BOM、无 CR、两处 LF、准确两行和全文内容，外层再次逐字节核对。中控同一回合中一次 PowerShell 引号错误及一次缺少 finish 结论参数均得到明确错误并修正，未增加回合。最终 completed/met，两个会话已通过现有移除接口归档，中控任务数回到 0；原始 Codex 历史仍由 Codex 管理，未复制。

## 返回 Linux 核对（2026-10-28）

核对对象为共享提交 `1614e51`，工作区起始干净。逐个重算 Windows JSON 记录的 7 个文件 SHA256，全部一致；复核 Windows 模型实验成果 66 字节、SHA256、严格 UTF-8 内容和 LF，全部与记录吻合。Windows 当前任务列表为 0、私有额度源文件存在（未读取或输出凭据），两批临时文件数量/大小符合其记录。Windows 进程/Junction/终端/GUI 的实测结论仍归属 Windows 当日证据，不伪称在 Linux 重跑了 Windows。

- `test_activity`（7 项）+ `test_controllers`（85 项）：共 92 项通过，无跳过或失败；涵盖本次 UTF-8 子进程修正及变动过的路径/报告断言。未扩大为无关全量复跑。
- `tools/service_activity_check.mjs` 和 `tools/controller_discussion_check.mjs`：1440/1024/390、浅深主题、重连提示/统计失败状态、讨论/权限/预算确认通过。API 模拟，不调用模型。
- 实际浏览器先连接既有 8764 服务，按约定重启现有 `ma4.service`，观察 SSE 的 `open → error → open`，页面恢复“守护进程已连接”，无脚本错误。原生 daemon 未停止。
- 重启前后 12 项任务的 id/host/formerHosts/cwd/target/budget/workspaces/draft/goalConfirmed/status/workers 摘要一致；本次开机已载入的 8 个会话全部保留，恢复状态结束。此前开机的 9 个是上一阶段数据，不能要求跨系统重启后的载入集合恒等。
- 真实德州/21点/Chat 三项统计 `stale=false`、无错误，额度不陈旧，两站健康 `ok=true`；未输出访客详情或密钥。
- **真实登录启动已验证：** 本次 boot 为 2026-10-28 01:29:34 CST；在本轮任何服务操作前，systemd 本次启动日志已记录 01:30:11 启动 MA4，01:30:12 图形会话目标激活。服务 enabled/active/running、WorkingDirectory=/mnt/e/PG/MA4-win、ExecStart 指共享 server.py、WantedBy=graphical-session.target、KillMode=process；Linger=no。因此证明本次图形登录自动启动，不证明退出登录后持续执行。
- 未修改业务代码、全局指令或客户端配置，未追加模型实验。只更新现有 README/清单/本验证记录、系统看板与 machine-state。

## Windows 日常小任务（2026-10-28）

- **范围与身份：** 本次另行授权的两轮任务 `e65cd30e77cb455d`，`targetRevision=1`，开始版本 `682e708b9afde0cbfc42222395bcfebba69a89ec`。执行会话 `01a18205-0ad3-7d93-93d7-294dfb2c2977`；第一轮 `turnId=01a18205-2591-7501-ad35-e1e4d07c6021`，第二轮续接同一会话，未新开执行者。仅测试中文空格路径下的 CSV 读取、Markdown 生成及派工回传，不改业务代码或配置、不安装依赖、不重启服务、不使用桌面控制、不部署或提交 Git。
- **第一轮中控证据及复核：** 依据中控第二轮派工消息，MA4 已自动回传关联上述任务/会话/回合的第一轮报告；中控亲读 3 文件，以整数分独立重算 4040，从项目根连续运行两次，文件字节稳定且 UTF-8 无 BOM、LF，独立检查输出为 `0ac331`。本执行者追加前重新读取三文件并逐一重算 SHA256，均与中控提供值一致（本轮输出 `ba0d56`、`c50c3e`）；脚本及 th123 Python 3.10.19、`-B -X utf8`、标准库读取方法保持一致，故该证据仍适用于追加前的三笔数据，不代替第二轮验收。
- **第二轮新增自测：** CSV 列为 `项目,金额`，有序数据为早餐 `12.50`、通勤 `8.00`、文具 `19.90`、咖啡 `6.60`。保持 `汇总.py` 与前三笔字节不变，仅在 CSV 末尾追加 `咖啡,6.60` 及 LF；脚本仍由自身目录读取输入，以 `csv`/`Decimal` 动态生成明细、笔数及两位小数合计。使用 `D:/python/anaconda/envs/th123/python.exe -B -X utf8`，依次从 `C:/Windows`、项目根、`C:/Windows` 运行三次。内存自测按整数分重算并逐字节比较完整 Markdown：恰好 4 笔、咖啡仅一次、4700 分即 47.00 元；各次输入不变、输出一致，脚本字节不变，三文件均严格 UTF-8 无 BOM、LF，目录仍恰好 3 文件，无本轮失败。结果输出 `c50c3e`；当前脚本 SHA256 `fbe1fffc59fb58cb0da5aaad6245ebc68d4651f0e6bb0109aef3cf2731a1840c`，CSV `e90f279b0f8bbf60463bddedc4861b0e78860bb7e96a558ea47834e71a024dbd`，Markdown `bb83fa68182f770e9b9aae14f916c5d6ec4c5ed7336924968b5e31b69978908e`。
- **中控新增独立验收：** 第二轮自动报告的 `turnId=01a18208-b8ee-7f41-a88d-acb9dd7bba70` 与第一轮属于同一执行会话、同一任务和目标修订。亲读 CSV/Markdown 后，以整数分独立求和为 4700，逐字节确认 CSV 仅在原三笔后追加一次咖啡；脚本 SHA256 与第一轮一致。从项目根和 `validation` 目录各运行一次，全部 3 文件字节均不变，严格 UTF-8 无 BOM/LF、4 笔/47.00 元、物理总量 1220 字节及三项 SHA256 与上文一致；输出 `89d36f`。只读检查当前任务运行数据，恰有一名执行者、metrics 中恰有上述两轮，`lastCompleted` 等于第二轮；中控与执行者的累计 totalTokens 均等于 inputTokens+outputTokens，缓存输入属于输入子集（输出 `39bde9`），最终数字留给程序更新。首次状态检查误用空闲时已清空的 `turnId` 而失败，改按实际 `lastCompleted`/metrics 核对后通过，这是检查脚本假设错误，不计为 MA4 故障。
- **本次发现、未修复：** `ma4_artifacts(list)` 对同一目录返回重复 roots，并分别以相对路径和绝对路径列出同一组文件，count=6、bytes=2440；实际目录仅 3 文件/1220 字节。只读状态显示 `scratchCwds` 同时有 `E:\PG\MA4-win` 与 `E:/PG/MA4-win`，经 Windows realpath/normcase 后相同（输出 `6c307c`）。`controllers.py` 的 `scratch_cwds` 用原始字符串 `dict.fromkeys` 去重，`do_artifacts` 按这些字符串逐个遍历相同物理根，因此发生重复计数。随后仅选择列表中的三条唯一相对路径执行 `ma4_artifacts(clean)`，返回 `count=3`；未将两个写法重复提交同一文件，精确清理成功。本次只记录问题，业务修复另行讨论。
- **证据边界：** 两轮派工、续接、自动回传、文件正确性及独立核验通过；材料清单的去重/计数失败，不能称为全部功能通过。精确清理通过，材料列表重复计数仍为未修复项。175/179 项 Python、22 项 Node 等此前迁移结果本任务未重跑，也不作为本轮复用通过；本任务未覆盖通知、HTML 渲染、普通 CLI/App 实时共享、暂停恢复、预算触发拦截及 Linux 本轮实测。用量只取 MA4 程序字段，含缓存且最终仍会更新，不预填最终数字或为补数字另开回合。
- **文件去向：** 正式修改仅 README 与本记录，以上输入、方法和结果摘要不依赖临时文件链接。任务目录 `.agent-tmp/ma4-e65cd30e77cb455d/中文 路径/` 的 `汇总.py`（991 字节）、`账单.csv`（64 字节）、`汇总.md`（165 字节）已完成中控最终检查并经材料工具精确清理，共 3 文件/1220 字节；任务根归属标记及旧临时材料未动。未另存测试脚本、过程报告、快照或备份；原生会话日志由 MA4/Codex 保留，不复制。

## 尚待验证

Windows：4 项 symlink 检查受权限限制；真实通知弹出未测；HTML 的 `file://` 内容观察被浏览器安全策略拒绝；普通 CLI/App 的完整实时共享和运行中跨后台 409 未测（相关错误映射单元测试已通过）。这些缺项不以模拟结果替代，也不为补测另开整套模型实验。

Linux 必需回归和真实登录启动已完成。核心迁移可以日常使用，剩余 Windows 明确缺项按实际需求在正常使用时补测，不为补齐报告重新安排整套模型实验或无必要的系统往返。

此前迁移阶段模型验收上限保持不变，且该阶段已用完授权的一次实验；与上述新授权日常任务分别记录。Linux 迁移实施阶段模型调用为 0。详见清单与看板 B-20261027-02。

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
