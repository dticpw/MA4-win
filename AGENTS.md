# MA4 · 双系统共享项目约定

- 开始先读 README.md 的「现状与接续」，结束前更新；交接只看 README。
- 唯一源码 E:/PG/MA4-win（Linux /mnt/e/PG/MA4-win）。公共功能同文件，系统接口放 os_adapters/，配置按 config.linux.json / config.windows.json。修改公共功能须考虑两系统，未实测部分明确写看板。
- Linux 运行数据仍在 /home/dticpw/PG_linux/MA4/.ma4；Windows 为项目 .ma4/。不复制 Codex 会话或运行状态，不并发写同一工作区。
- Linux 改 Python 后重启现有 ma4.service，不另起监听 8764 的进程。Windows 保留手动入口，不新增自启。关闭网页/代理不得停止已有原生 daemon 或无关进程。
- Linux Python：/home/dticpw/conda/envs/py310/bin/python；Windows：D:/python/anaconda/envs/th123/python.exe。测试入口与证据边界见 README。
- 只监听本机，不改全局 Codex/MCP 配置。保留界面、业务逻辑和已有会话权限；中控的既定权限不外推到普通会话。
- 临时材料放 .agent-tmp/，仅清理本任务已无依赖的材料。运行数据和临时区不进 Git；LF，core.fileMode=false。保留旧任务未获准清理材料。
