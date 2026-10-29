# Termcp + AIOps 真实闭环验收（2026-10-16）

## 结论

本机隔离环境已跑通完整闭环：AIOps 通过真实 Termcp MCP 网关创建 SSH 会话并提交受控命令；命令停在 Termcp UI 待审批；UI 点击“接受”后命令只执行一次；AIOps 从 LangGraph SQLite checkpoint 恢复，向 Termcp 核验审批关联并读取 shell 输出；最终产生 complete 事件。

## 实际链路

- Termcp 修复镜像：`aiops-termcp:0.2.7-expiry.1`，UI `127.0.0.1:18765`。
- 本地 gateway：`127.0.0.1:18766`，MCP 工具通过真实 HTTP/Streamable HTTP 发现。
- 隔离目标：`live-diag-target`，profile `test-target`，会话由 AIOps 新建。
- AIOps 会话：`d1b9e9cb-604`，shell：`daecefcc-84d`。
- 审批请求：`7287f100-4405-4f8c-a459-a2e681946362`。
- 命令：`echo aiops_ui_resume > /tmp/aiops-ui-resume.txt`。

## 观察结果

1. `shell_input` 暂存命令，`shell_key(enter)` 返回 `review_pending=true`，目标文件尚不存在。
2. Termcp UI 显示待审命令；点击“接受”后 UI 显示 `Approval granted`，待审列表清空。
3. AIOps 轮询到审批状态 `approved`，调用 `resume`；服务端核对 request、session、shell、命令、keys、source 和 expires_at 后继续。
4. 恢复节点读取 `shell_output`，生成 `data_source=termcp_approved_target` 的原始证据并发出 `complete` 事件。
5. 目标容器现场校验：

   ```text
   /tmp/aiops-ui-resume.txt -> aiops_ui_resume
   ```

6. 另一次旧待审命令超过 30 分钟后点击“接受”返回 `Approval expired`，目标文件未生成，证明过期 fail-closed。

## 仍需区分的部署限制

这次闭环最初使用本机 Python gateway；随后已补做 Compose 容器级联调。Compose 中的 Termcp UI、gateway、诊断目标和 app 均已启动，app 通过 gateway 的 `session_list` 返回空会话，诊断 MCP 通过受限 SSH 目标返回 catalog/进程/端口/日志证据，健康接口返回 200。

Compose 运行时 token 保存在本机未跟踪文件中，未写入报告或镜像；单一测试目标的 SSH key/known_hosts 只读挂载到诊断容器。生产部署仍应把测试目标替换为正式授权 profile，并将业务 MCP 地址从 `host.docker.internal` 改为内网服务名。
