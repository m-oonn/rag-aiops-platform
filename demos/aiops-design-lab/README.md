# AIOps 诊断工作台设计预览

隔离的前端设计原型，读取工作区中一场已保存的诊断运行及其证据。它不连接正式前端或诊断 API，也不触发模型调用。

## 预览

访问 http://127.0.0.1:5274/。本地启动命令：

```powershell
cd D:\ragPdfSystem++agent\demos\aiops-design-lab
npm install
npm run dev
```

## 交互

- **报告总览**：请求结果、服务关系、现场观测、退出事件和建议核实步骤。
- **候选原因**：逐项查看七种解释与其关联证据。实线表达直接支持或反驳，虚线只表示关联，不代表因果。
- **现场证据**：十条保存记录、结构化字段、生命周期日志和可展开的已保存字段节选。
- **排查过程**：按采集顺序播放、暂停、拖动、前后浏览并跳转到证据详情。

桌面使用分栏与细分隔线；手机端将候选、证据列表改为原生选择控件，关系图改为纵向阅读。界面按系统设置支持减少动态效果。

## 设计与实现来源

- Impeccable 提供设计评审指南；其 CLI 上下文生成器未能下载引擎，因此本预览直接采用了本地指南，不将 CLI 记为已运行。
- UI/UX Pro Max 检索了 SaaS 运维场景与减少动态效果的设计指引。
- Vue Flow 绘制候选原因与证据关联图：`references/vue-flow/`，Git commit `17953c329db2d5dc5f5097370cbf5e1173bab520`。
- Anime.js 用于排查回放时的轻量过渡：`references/anime/`，Git commit `01b81be1df6843ccfe0a71c0699a746bf740dd77`。
- npm 依赖版本锁定在 `package-lock.json`；主依赖为 Vue 3.5.30、Vue Flow 1.48.2 和 Anime.js 4.5.0。

## 数据边界

随原型提交的 `src/data/scene.json` 是从 `runtime/aiops-visualization-run-read.json` 和 `runtime/aiops-visualization-evidence-read.json` 投影的脱敏展示快照；不包含原始运行文件。页面不访问服务端，也不提升原文读取权限。此运行的诊断终态是 `localized_fault`：downstream 的进程与监听缺失、localapp 返回 HTTP 503；候选原因仍有未决项，停止请求的发起者未知。页面据此展示现场定位，不将其描述为已确认根因。工作区持有原运行材料时，可用 `npm run data` 重新生成快照。

## 验证

```powershell
npm test
npm run build
playwright-cli run-code --filename=scripts/verify-browser.js
```

浏览器脚本检查 1440、768、390 和 360 像素视口、全部四个视图、七个候选、十项证据、节选展开、回放控制、减少动态效果、页面异常、水平溢出和乱码。截图输出到被忽略的 `artifacts/` 目录。
