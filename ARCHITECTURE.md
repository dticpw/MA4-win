# MA4 的任务控制边界

从具体功能在 [FEATURE-MAP.md](FEATURE-MAP.md) 找入口，再用本页决定改动放在哪里。这里记录已经存在的分工，不代表全库重构已经完成。

| 要改的行为 | 编辑位置 | 边界 |
|---|---|---|
| 用量/预算判断、能否确认或交接、报告等待原因、任务诊断 | `task_policy.py` | 输入任务快照及 `RuntimeState`，返回结果；不修改输入，不读时钟/磁盘，不访问会话 |
| 收到命令或事件后如何变更任务、持久化、派工、暂停、恢复 | `controllers.py` 的 `Controllers` | 串行处理事件，保留发送前持久化、发送结果核对及去重顺序；它拥有状态写入和副作用 |
| 会话操作及原生通知转换 | `hub.py`、`appserver.py` | Hub 协调会话；AppServer 处理 RPC/连接。不要让纯规则反向导入这两层 |
| Windows/Linux 差异 | `os_adapters/`、系统配置 | 共享规则不根据系统分叉，不复制两套任务逻辑 |
| 页面呈现与交互 | `web/controllers.js`、`web/index.html`、`web/style.css` | 展示后端诊断和操作限制；后端仍是执行检查的权威，前端不能替代授权和预算检查 |

`Controllers → task_policy` 是这次新增并检查的单向依赖。Controllers 从 Hub 当前状态组装 `RuntimeState(now, connected, recovering, error)`；纯规则不能自己获取这些信息。时间通过参数传入，测试可以直接覆盖预算到期前后，不用等待真实时间。

现有 `Controllers.usage/cost/exhausted/diagnosis/report_delivery` 等方法仍可调用，但只委托给规则模块；外部导入的状态常量与时间辅助函数也保留兼容。不要在兼容方法里重新复制一套规则。任务 JSON 格式、HTTP 接口、状态名称及原生会话归属未迁移。

## 修改一项任务规则的做法

1. 明确触发条件和优先级。例如“连接状态尚待核对”应先于“预算已到”展示；“目标达标”不能被旧的预算或前任错误覆盖。
2. 在 `task_policy.py` 修改判断，直接用任务字典和明确的 `RuntimeState` 测试；参考 `test_task_policy.py` 的到期前后及不可变输入场景。
3. 涉及用户动作时，在 `test_controllers.py` 检查真实编排效果：是否有多发消息、意外修改目标/预算/授权，是否保持执行者和已有成果。纯函数测试不能代替这些检查。
4. 如需新的外部信息，在 Controllers/Hub 取得后明确传入；修改页面接口时同步调整渲染与相关页面检查。
5. 运行相关分组及提交前 CI，审阅地图变化，记录新测、复用依据和未测项。

Windows 示例（仅本机逻辑检查，不连接正在运行的 MA4）：

```powershell
& 'D:/python/anaconda/envs/th123/python.exe' -B -X utf8 tools/verify.py run tasks architecture
& 'D:/python/anaconda/envs/th123/python.exe' -B -X utf8 tools/verify.py run ci
```

Linux 使用 README 指定的 py310 解释器；公共模块不需要第三方包。页面有变化时再使用 `tasks --ui`，涉及真实协议或模型时按对应入口及授权执行。

### 执行者未知状态的维护样例

执行者已知状态为 `running/sending/queued/idle`。其他值只表示需要核对：`confirm_blocker` 阻止确认（包括仅确认保存）和直接恢复；`do_update` 仍按原规则保存草案，不修改正式目标或执行者状态。不能据此认定故障原因，也不扩展交接或调度限制。

诊断保留控制异常、断线/核对、发送未确认、中控缺失、到期收尾、交接、终态、已知在途停止、预算及金额不确定的既有优先级，同时在 `facts` 显示未知执行者。其他情况下，未知状态先于草案、待接续、暂停或空闲解释。终态名称与停止按钮规则不变，但有未知执行者时不能声称没有在途回合。纯规则回归覆盖这些组合；Controllers 回归检查拒绝操作时内存、文件与模拟会话均不变，以及保存草案和核对后继续。此次独立维护记录见 [验证说明](validation/cold-start.json)，不以一次维护结果推算效率收益。

## 自动约束及其限度

`tools/check_architecture.py` 检查规则模块的全部静态导入（包括函数内部及别名）：目前只允许 `math`、`dataclasses`。反向导入 Controllers/Hub、文件/网络/进程依赖，以及 `open`、动态执行等入口会给出文件、行号和修改建议。`run architecture` 检查实际源码，也用故意加入的违规示例验证检查能够失败；该组已加入 `run ci`。

这是防止日常代码偏离分工的静态检查，不是安全沙箱，也不证明任意 Python 程序没有副作用。输入不被修改、预算/状态优先级和编排效果仍由行为测试与审查负责。新增依赖需先说明是否仍属于纯判断，再修改规则及相应检查，不能为了让 CI 通过直接放宽限制。

这一步没有拆完 Controllers 的材料管理、全部状态转换或所有调度代码。接下来的拆分应由实际修改困难推动。一名新建、无此前对话的执行者已在给定问题和文件范围内完成未知状态修复，并通过派发者独立验收；不是无约束的仓库发现试验，也不能证明长期提速。后续真实观察见 [迭代试验](validation/iteration-pilot.json)。

`tools/task_actions.py` / `task_scenarios.py` 是隔离验证的操作层：经现有 HTTP 和原生动态工具操作，不另实现任务调度，不直接改状态字典；保护实例与会话归属。`tools/maintenance.py` 是显式事件入口：保存检查证据与发送意图，经现有任务接口派工；不直接写 Controllers 数据。其次数/文件范围仍是任务约束，实际任务权限和预算由原后端检查。规则层依赖检查不等于这两个 I/O 工具的安全证明，它们另有行为测试和真实演练。

拆分时的固定样本比较方法保留在 `validation/task-policy-compare.py`：从 Git 的 `5b79fe6` 读取原实现，与当前实现比较 2,000 组状态，只输出结果，不访问运行数据或模型。它依赖本地已有该提交，不加入浅检出的 CI；日常检查使用当前行为测试，不把历史实现永久当作新功能的判定标准。结果和在线加载边界见 `validation/task-policy.json`。
