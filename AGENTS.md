# MA4 Windows 项目约定

- 先读 README.md 的「现状与接续」；任务结束前更新同一入口。
- 保留上游界面和会话逻辑，Windows 差异集中于传输、启动与路径处理。
- 只监听本机；手动启动，不安装自启或修改 Codex 全局配置。
- 关闭网页/MA4 不得停止终端使用的共享后台；不终止非本次启动的进程。
- 默认 Python：D:/python/anaconda/envs/th123/python.exe。测试见 README。
- 临时材料放 .agent-tmp/，运行数据放 .ma4/，均不入 Git；不保存完整对话副本。
