# 前端重建记录 · 2026-11-13

已替换活动前端源码，覆盖登录、工作台及 13 个业务页面。旧源码及原有未提交改动保存在 `runtime/frontend-redesign-20261113/frontend-before-rebuild.zip`，没有修改本次任务之外的后端代码。

设计依据是本机 `8200/docs` 的 OpenAPI 文档与用户提供的 `design.md`。接口快照和设计参考副本保存在同一归档目录。用户明确禁止卡片布局，因此采用浅色连续页面、侧边导航、分栏工作区、工具栏和表格；使用 Fluent 蓝、Segoe UI、小圆角与键盘焦点环。页面不常驻展示业务规则或接口约束，限制通过控件、字段校验、确认与错误反馈表达。

## 页面与流程

| 路由 | 页面 | 主要操作 |
| --- | --- | --- |
| `/login` | 登录 | 登录、注册、返回原访问页面 |
| `/dashboard` | 工作台 | 最近诊断、处理任务、知识与服务状态入口 |
| `/aiops` | 故障诊断 | 发起诊断、读取事件流、报告与引用、候选原因、证据、审批状态核对与恢复 |
| `/aiops/history` | 最近诊断 | 搜索、重载、恢复诊断、移除本机记录 |
| `/chat` | 知识问答 | 会话管理、选择助手与知识库、提问、查看参考资料 |
| `/knowledge-bases` | 知识库 | 创建、编辑、搜索、删除 |
| `/knowledge-bases/:id` | 文档与检索 | 上传、预览、分块、重试、重新处理、问答对管理、检索 |
| `/assistants` | 助手 | 配置、关联知识库与智能体、对话、历史版本保存与恢复 |
| `/agents` | 智能体 | 配置工具、模型、记忆和执行参数、试运行 |
| `/evaluation` | 效果评测 | 数据集生成与上传、条目编辑、执行评测、报告 |
| `/monitor` | 文档任务 | 状态筛选、进度、错误反馈、单项与批量删除 |
| `/storage` | 文件管理 | 上传、搜索、预览、下载、批量删除 |
| `/platform` | 运行状态 | 服务、队列、处理节点、模型、失败重试 |
| `/users` | 用户管理 | 创建用户、角色调整；入口与路由限定管理员 |

诊断历史延续本机存储模式，后端没有提供诊断列表接口。终端命令在外部审批页面审批，前端只核对审批并请求继续。后台处于人工复核状态时展示状态并限制重复提交，没有虚构复核接口。

## 验证结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| `npm run test` | 5 个文件、11 项通过 | `runtime/frontend-redesign-20261113/unit-test.log` |
| `npm run build` | 通过 | `runtime/frontend-redesign-20261113/build.log` |
| 浏览器页面检查 | 13 个页面在 1440px 下通过；在 320px 和 390px 下共 26 次检查，无页面横向溢出 | `runtime/frontend-redesign-20261113/browser-test.json` |
| 浏览器主要流程 | 知识库创建和编辑入口、诊断报告/步骤/候选/证据原文、问答、任务单删与批删、助手和智能体配置保留、版本列表、现有评测任务数据集上传通过 | `frontend/e2e/redesign.cjs` |
| 浏览器边界 | 不完整事件流保持断开、审批 409 保持待审批、刷新恢复暂停状态、队列失败重试、会话创建失败保留消息与草稿、普通成员访问限制、预览 HTML 清理通过 | 同上 |
| 浏览器错误与请求 | `errors=[]`、`unexpected=[]` | 浏览器结果 JSON |
| 视觉检查 | 已人工查看桌面工作台、诊断、知识库和手机会话截图 | 同归档目录中的 PNG |
| 本地可访问性 | 前端登录页和后端文档均返回 HTTP 200 | 2026-11-13 本机只读检查 |
| `git diff --check -- frontend` | 通过；仅有本机 LF/CRLF 转换提示 | 本机命令输出 |

浏览器回归在生产构建预览端口 5275 上拦截并模拟全部业务 API，截图中的数据为模拟数据。没有实际写入业务数据、执行评测或调用真实模型，不构成真实业务端到端验收。本轮没有运行后端测试，也没有提交、推送或发布。

初次普通构建遇到系统临时目录中的 esbuild 文件删除权限错误。最终成功构建仅对该命令设置了项目内临时目录：

```powershell
$env:TEMP = 'D:\ragPdfSystem++agent\runtime\frontend-redesign-20261113\tmp'
$env:TMP = $env:TEMP
npm run build
```

## 运行与复查

前端开发服务位于 `http://127.0.0.1:5273`，通过既有代理连接 `http://127.0.0.1:8200`。在 `frontend` 目录运行 `npm run dev` 可启动，接口与数据是否可用取决于本机后端服务。

浏览器回归需要在 5275 启动生产预览，再从仓库根目录执行：

```powershell
playwright-cli -s=redesign --raw run-code --filename=frontend/e2e/redesign.cjs
```

检查输出中的 `status`、`errors` 和 `unexpected`；该 CLI 的脚本错误可能仍返回退出码 0，不能只看进程退出码。当前脚本末尾不加分号，以适配 CLI 的函数解析方式。

主要源码为 `frontend/src/App.vue`、`frontend/src/router.js`、`frontend/src/styles/app.css`、`frontend/src/views/`、`frontend/src/components/` 和 `frontend/src/lib/`。沿用 Vue 3、Vue Router、Element Plus 及现有依赖，没有新增项目依赖。
