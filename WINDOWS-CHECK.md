# Windows 接入检查证据

日期：2026-10-10（Asia/Shanghai）。任务：B-20261010-01。

本文件的命令在实际用户 DTICPW 下运行。首次沙箱账户的目录与网络检查不作为结论依据。中断前原始结果未成功保存，本次补录七项命令；版本和能力结果与此前一致；桌面进程 PID 在中断后发生变化，见末尾重新核对。

## 看板要求的七项检查

### 1. 命令

```powershell
codex --version
```

退出码：0

标准输出：
```text
codex-cli 0.149.1

```

标准错误：
```text
（无输出）
```

### 2. 命令

```powershell
codex app-server --help
```

退出码：0

标准输出：
```text
[experimental] Run the app server or related tooling

Usage: codex app-server [OPTIONS] [COMMAND]

Commands:
  daemon                Manage the local app-server daemon
  proxy                 Proxy stdio bytes to the running app-server control socket
  generate-ts           [experimental] Generate TypeScript bindings for the app server protocol
  generate-json-schema  [experimental] Generate JSON Schema for the app server protocol
  help                  Print this message or the help of the given subcommand(s)

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

      --code-mode-host <URL>
          Connect to a remote code-mode host instead of starting a local host

      --strict-config
          Error out when config.toml contains fields that are not recognized by this version of
          Codex

      --listen <URL>
          Transport endpoint URL. Supported values: `stdio://` (default), `unix://`, `unix://PATH`,
          `ws://IP:PORT`, `off`
          
          [default: stdio://]

      --stdio
          Use stdio as the transport (equivalent to `--listen stdio://`)

      --analytics-default-enabled
          Controls whether analytics are enabled by default.
          
          Analytics are disabled by default for app-server. Users have to explicitly opt in via the
          `analytics` section in the config.toml file.
          
          However, for first-party use cases like the VSCode IDE extension, we default analytics to
          be enabled by default by setting this flag. Users can still opt out by setting this in
          their config.toml:
          
          ```toml [analytics] enabled = false ```
          
          See https://developers.openai.com/codex/config-advanced/#metrics for more details.

      --ws-auth <MODE>
          Websocket auth mode for non-loopback listeners
          
          [possible values: capability-token, signed-bearer-token]

      --ws-token-file <PATH>
          Absolute path to the capability-token file

      --ws-token-sha256 <HEX>
          Hex-encoded SHA-256 digest of the capability token

      --ws-shared-secret-file <PATH>
          Absolute path to the shared secret file for signed JWT bearer tokens

      --ws-issuer <ISSUER>
          Expected issuer for signed JWT bearer tokens

      --ws-audience <AUDIENCE>
          Expected audience for signed JWT bearer tokens

      --ws-max-clock-skew-seconds <SECONDS>
          Maximum clock skew when validating signed JWT bearer tokens

  -h, --help
          Print help (see a summary with '-h')

```

标准错误：
```text
（无输出）
```

### 3. 命令

```powershell
codex app-server daemon --help
```

退出码：0

标准输出：
```text
Manage the local app-server daemon

Usage: codex app-server daemon [OPTIONS] <COMMAND>

Commands:
  bootstrap               Install durable local app-server management for SSH-driven use
  start                   Start the local app server daemon if it is not already running
  restart                 Restart the local app server daemon
  enable-remote-control   Enable remote control for future starts and a currently running managed
                          daemon
  disable-remote-control  Disable remote control for future starts and a currently running managed
                          daemon
  stop                    Stop the local app server daemon
  version                 Print local CLI and running app-server versions as JSON
  help                    Print this message or the help of the given subcommand(s)

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.
          
          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

  -h, --help
          Print help (see a summary with '-h')

```

标准错误：
```text
（无输出）
```

### 4. 命令

```powershell
codex app-server daemon version
```

退出码：1

标准输出：
```text
（无输出）
```

标准错误：
```text
Error: codex app-server daemon lifecycle is only supported on Unix platforms

```

### 5. 命令

```powershell
Get-ChildItem "$env:USERPROFILE\.codex\app-server-control" -Force -ErrorAction SilentlyContinue
```

退出码：1

标准输出：
```text
（无输出）
```

标准错误：
```text
（无输出）
```

### 6. 命令

```powershell
Get-Process codex -ErrorAction SilentlyContinue | Select-Object Id, Path
```

退出码：0

标准输出：
```text

   Id Path                                                                     
   -- ----                                                                     
29252 C:\Users\DTICPW\AppData\Local\OpenAI\Codex\bin\2e5e00daee91c61d\codex.exe



```

标准错误：
```text
（无输出）
```

### 7. 命令

```powershell
& D:\python\anaconda\envs\th123\python.exe -c "import socket, sys; print(sys.version); print('AF_UNIX', hasattr(socket, 'AF_UNIX'))"
```

退出码：0

标准输出：
```text
3.10.19 | packaged by conda-forge | (main, Oct 22 2025, 22:23:22) [MSC v.1944 64 bit (AMD64)]
AF_UNIX False

```

标准错误：
```text
（无输出）
```

## 桌面版与端点补充检查

```powershell
Get-CimInstance Win32_Process -Filter "Name = 'codex.exe'" | Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine | Format-List
```

退出码：0

```text


ProcessId       : 29252
ParentProcessId : 28280
ExecutablePath  : C:\Users\DTICPW\AppData\Local\OpenAI\Codex\bin\2e5e00daee91c61d\codex.exe
CommandLine     : C:\Users\DTICPW\AppData\Local\OpenAI\Codex\bin\2e5e00daee91c61d\codex.exe -c features.code_mode_host=
                  true app-server --analytics-default-enabled -c plugins.codex-app-tools@openai-bundled.mcp_servers.cod
                  ex_app.enabled=true -c plugins.code-review@openai-bundled.mcp_servers.code-review.enabled=true




```

```powershell
& 'C:/Users/DTICPW/AppData/Local/OpenAI/Codex/bin/2e5e00daee91c61d/codex.exe' --version
```

退出码：0

```text
codex-cli 0.162.0-alpha.17.2

```

```powershell
& 'C:/Users/DTICPW/AppData/Local/OpenAI/Codex/bin/2e5e00daee91c61d/codex.exe' app-server daemon version
```

退出码：1

```text
Error: failed to connect to C:\Users\DTICPW\.codex\app-server-control\app-server-control.sock

Caused by:
    套接字操作遇到了一个已死的网络。 (os error 10050)

```

```powershell
Test-Path -LiteralPath 'C:/Users/DTICPW/.codex/app-server-control'
```

退出码：0

```text
False

```

```powershell
Get-NetTCPConnection -OwningProcess 11708 -State Listen -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,OwningProcess
```

退出码：1

```text
（无输出）
```

首次补录时只观察到桌面 app-server 进程，没有独立 Codex TUI 进程；后续进程变化见末节。启动参数没有 --listen，帮助说明默认 stdio；控制目录不存在，该 PID 没有枚举到 TCP Listen 记录。没有对系统内全部命名管道进行排查，不能断言任何 Windows 版本都没有其他端点。

因为 Codex App 会话正在运行，按看板要求跳过 daemon start/stop。没有试接、恢复、发消息或中断已有会话。

## 本机协议定义核对

分别使用 PATH CLI 和桌面二进制运行 app-server generate-json-schema --out <本次临时目录>，均成功。下面结果来自默认导出文件的 JSON 结构，不是在线接口测试；默认导出会隐藏实验项，必须结合下方更正后的 --experimental 核对结论。

```json
{
  "version": "0.149.1",
  "methods": {
    "thread/list": true,
    "thread/read": true,
    "thread/turns/list": false,
    "thread/resume": true,
    "thread/start": true,
    "thread/name/set": true,
    "turn/start": true,
    "turn/steer": true,
    "turn/interrupt": true,
    "thread/compact/start": true,
    "review/start": true,
    "model/list": true,
    "skills/list": true
  },
  "thread_resume_excludeTurns": false,
  "thread_turns_schema_exists": false
}
```

```json
{
  "version": "0.162.0-alpha.17.2",
  "methods": {
    "thread/list": true,
    "thread/read": true,
    "thread/turns/list": true,
    "thread/resume": true,
    "thread/start": true,
    "thread/name/set": true,
    "turn/start": true,
    "turn/steer": true,
    "turn/interrupt": true,
    "thread/compact/start": true,
    "review/start": true,
    "model/list": true,
    "skills/list": true
  },
  "thread_resume_excludeTurns": true,
  "thread_turns_schema_exists": true
}
```

更正：上方 false 仅表示 0.149.1 的默认导出未包含实验项，不能据此认定接口缺失。最终使用 --experimental 导出后，两项均存在，详见下方补充。字段存在仍需实际 RPC 验证。

## 原仓库测试（中断前已执行）

源码未修改，提交：3ce173f5b0b5bdb8be71dfa639c2a2e000241f1f。

```powershell
& 'D:/python/anaconda/envs/th123/python.exe' -B -m unittest -v test_appserver test_hub test_server test_quota
node --test test_markdown.mjs
```

Python 实际结果：34 项中 29 项通过，5 项 ERROR。21 项 test_hub、4 项 test_server、4 项 test_quota 通过；5 项 test_appserver 都在 FakeDaemon 创建 AF_UNIX socket 时失败。

```text
File "test_appserver.py", line 51, in __init__
    self.listener = socket.socket(socket.AF_UNIX)
AttributeError: module 'socket' has no attribute 'AF_UNIX'

Ran 34 tests in 0.835s
FAILED (errors=5)
```

Node 实际结果：raw HTML 转义、仅 http(s) 链接、代码块、行内代码、表格/列表/标题、本地文件引用，共 6 项通过。

```text
ℹ tests 6
ℹ pass 6
ℹ fail 0
ℹ skipped 0
```

两条测试命令顺序执行，外层 shell 的退出码 0 来自最后的 Node 测试，不能据此称 Python 全部通过。测试仅用假后台与临时本机 HTTP 端口，不调用模型。原测试 TemporaryDirectory 已按原逻辑退出清理；未改测试来隐藏错误。此处保留足以说明结果的实际输出摘录，七项看板命令保留完整输出。

## 来源与边界

- 仓库 README 已先于第一次七项命令读取：https://github.com/dticpw/MA4/blob/3ce173f5b0b5bdb8be71dfa639c2a2e000241f1f/README.md
- muQ 主题、architecture.html、decisions.html 均实际读取且返回 HTTP 200：https://muq.koa-ol.com/e/ma4/
- 官方文档通过文档搜索工具检索并读取正文：https://developers.openai.com/codex/app-server
- 官方文档列出 ws://、stdio、Unix socket 和 codex --remote。帮助与文档不代替 Windows 实测。
- Python which('codex') 实测返回 C:/Users/DTICPW/AppData/Roaming/npm/codex.CMD；发现 wt.exe，未启动终端窗口。
- 没有运行 daemon start/stop/restart/bootstrap/update/enable-remote-control；未启动 MA4 或 TCP app-server；未改变现有会话、Codex 全局配置、自启或依赖；未调用模型。
- Windows TCP 多客户端实时接入、真实审批和网页视觉效果尚未验证。

## 中断后进程重新核对

中断前桌面后台 PID 为 11708；继续后的首轮为 29252。随后动态检查发现主后台 29252、另一个显式 stdio app-server 13188，以及两个 sandbox 辅助进程；没有独立 TUI。所有这些 Codex 进程的 TCP Listen 记录为空。

上方对旧 PID 11708 的补录查询不作为当前端点依据。重新检查使用 Get-CimInstance 取得现场 codex.exe 的 PID，再从 Get-NetTCPConnection -State Listen -ErrorAction Stop 按 OwningProcess 筛选，命令退出码 0。

以下为重新检查的输出摘录；无关 sandbox 进程仅保留分类和 PID，未保留其他任务的详细命令或路径。

```json
{
  "app_servers": [
    {
      "ProcessId": 29252,
      "ParentProcessId": 28280,
      "ExecutablePath": "C:\\Users\\DTICPW\\AppData\\Local\\OpenAI\\Codex\\bin\\2e5e00daee91c61d\\codex.exe",
      "CommandLine": "C:\\Users\\DTICPW\\AppData\\Local\\OpenAI\\Codex\\bin\\2e5e00daee91c61d\\codex.exe -c features.code_mode_host=true app-server --analytics-default-enabled -c plugins.codex-app-tools@openai-bundled.mcp_servers.codex_app.enabled=true -c plugins.code-review@openai-bundled.mcp_servers.code-review.enabled=true"
    },
    {
      "ProcessId": 13188,
      "ParentProcessId": 28428,
      "ExecutablePath": "C:\\Users\\DTICPW\\AppData\\Local\\OpenAI\\Codex\\bin\\2e5e00daee91c61d\\codex.exe",
      "CommandLine": "\"C:\\Users\\DTICPW\\AppData\\Local\\OpenAI\\Codex\\bin\\2e5e00daee91c61d\\codex.exe\" app-server --listen stdio://"
    }
  ],
  "other_codex_processes": [
    {
      "ProcessId": 29112,
      "kind": "Codex sandbox helper（与会话接入无关，省略命令正文）"
    },
    {
      "ProcessId": 9828,
      "kind": "Codex sandbox helper（与会话接入无关，省略命令正文）"
    }
  ],
  "tcp_listeners": []
}
```

没有创建或终止上述现有进程。这只证明检查时未见 TCP 监听，不扩大为命名管道或未来版本的能力结论。

## 文件收尾

已核对临时目录位于 E:/PG/MA4-win 内、没有目录链接、浅克隆源码无改动，随后清理本次临时源码与两版协议定义：659 个文件，6,885,699 字节。临时父目录为空后已删除。保留 README.md、WINDOWS-CHECK.md、.gitignore，无备份/打包文件、运行数据或新增周期任务。

## 实验接口核对与结论更正

复核 generate-json-schema --help 发现选项：

```text
--experimental
    Include experimental methods and fields in the generated output
```

随后实际执行，退出码 0：

```powershell
codex app-server generate-json-schema --experimental --out 'E:/PG/MA4-win/.agent-tmp/protocol-final-check'
```

解析 JSON 结构的实际结果：

```json
{"version":"0.149.1","include_experimental":true,"thread/turns/list":true,"thread_resume_excludeTurns":true,"thread_turns_schema_exists":true}
```

最终结论：此前“旧版缺少分页接口”的推断错误，已修正计划与看板。MA4 当前 initialize 仅发 clientInfo，Windows 候选接入需声明 experimentalApi 并验证真实 RPC；无需以默认导出缺字段为理由先升级或另写历史兼容层。daemon lifecycle 的 Unix 限制、th123 AF_UNIX=False 与当前未发现共享监听端点仍有独立实测支持。

本次额外协议临时目录已清理：401 个文件、3,778,968 字节。项目最终仍只保留三个正式文件，无临时目录。
