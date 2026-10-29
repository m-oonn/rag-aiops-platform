# 项目目录约定

根目录只放工程入口、依赖与规则文件，以及当前不能随意迁移的本机运行状态。临时脚本、截图和个人资料不再直接写入根目录。

| 位置 | 用途 | 处理原则 |
| --- | --- | --- |
| src/、frontend/src/、mcp_servers/ | 后端、前端和证据工具源码 | 保留并纳入版本控制 |
| tests/、前端测试、docs/fixtures/ | 回归测试与夹具 | 保留，不作为缓存清理 |
| scripts/、scripts/tools/ | 启动、验证、评测和辅助工具 | 按 scripts/README.md 查找 |
| scripts/probes/ | 模型和后端探索探针 | 不自动运行；核对网络与费用 |
| docker/、.github/、docs/site/ | 部署、CI 与现有文档站 | 保留既有入口 |
| docs/ | 当前路线、机制、接口与运行说明 | 从 docs/README.md 进入 |
| docs/thesis/、research/、history/ | 论文草稿、相关工作、历史验证 | 不将历史结果当作当前验收 |
| docs/local/、docs/superpowers/ | 本机参考与历史方案 | Git 忽略，保留资料 |
| data/ | 上传、索引、诊断证据与受控手册 | 有效数据和实验依据不得按缓存删除 |
| runtime/ | 运行记录、实验输出、费用账本与整理清单 | 每次检查用独立子目录；保留失败 |
| runtime/demo/pids.json | 启动器进程状态 | 启动器自动创建父目录，原根目录状态已迁入 |
| logs/ | 服务与工具日志 | 旧根日志位于 logs/legacy/ |
| .env、rag_system.db 及其 WAL/SHM | 现用配置和数据库 | 原位保留，不提交、不打印凭据 |
| .git、.venv、frontend/node_modules/ | Git 历史和已安装依赖 | 不作为目录清理目标 |
| .vscode、.codebuddy、.workbuddy、.local | 本机开发与工具状态 | 原位保留；不等同于可删除缓存 |

## 当前工具命令

从项目根目录执行：

```powershell
& .\.venv\Scripts\python.exe scripts/launch_demo.py status --all
# 以下会操作数据库，仅在需要初始化时执行
& .\.venv\Scripts\python.exe scripts/create_tables.py
```

根目录原有 run_full_pipeline.py、run_rag_eval.py 已移入 scripts/；探针由 scripts/probe_*.py 移入 scripts/probes/。新路径的工具功能保持原用途，不因整理而授权启动服务、入库或付费调用。

辅助工具位于 scripts/tools/，静态展示站位于 docs/site/（Pages 工作流同步更新），贡献说明位于 docs/CONTRIBUTING.md。

## 临时产物与个人资料

临时检查优先使用系统临时目录；需要留存时放入 runtime/ 下的独立目录。Python/pytest 缓存可重新生成，不需要为保持外观在运行后反复清除。

2026-10-23 归档在本机 D:/ragPdfSystem++agent-archive/2026-10-23/。个人材料未删除；论文草稿仍有依赖个人图片和分册的历史引用，整理目录不等于论文流水线验收通过。

不通过编辑器隐藏规则掩盖文件，也不为减小目录项数迁移数据库或实验原始记录。目录整理尚未提交时，Git 显示旧路径删除和新路径未跟踪是文件移动的工作树状态；提交前必须同时纳入新路径。
