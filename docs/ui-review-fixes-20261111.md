# UI 复核遗留问题修复（2026-11-11 下午）

来源：`runtime/ui-tour/点击验证报告-20261111.md` 第四节列出的七个问题。问题 1、2、4 已在
`d3aa908` 修复，本轮处理剩下的四个：服务状态慢、AIOps 缺前置条件就花钱、前后端分块
默认值不一致、模型下拉只有一个。每一条都给出真实浏览器或真实接口的结果，不只依赖单测。

## 一、AIOps 缺前置条件时仍可点「开始诊断」（已修）

现象：`PROBE_ENABLED` 默认关闭，诊断链路拿不到主机侧的进程、端口、日志、配置快照，
结论只能停在「已定位」或「待核实」，但要先付出一次付费模型调用。用户点按钮时看不到
任何提示。

改法：
- 后端 `GET /api/v1/health/dependencies` 只在 `PROBE_ENABLED` 为真时返回 `probe` 一项。
  不启用 Probe 的部署不应报告一个假的「正常」。
- 前端进入诊断页时先读这份依赖清单：Probe 可用则什么都不说；取证工具全部不可用则给
  更强的一档说明；其余情况说明「Windows Probe 未启用或不可达，诊断拿不到主机侧现场
  证据」。这段判断失败时保持沉默——网络抖动不该变成一个红色告警。
- 有告警时「开始诊断」保持禁用，必须先勾选「我已知晓：本次仍会调用付费模型，但结论
  可能只到「已定位」或「待核实」」。

真实浏览器结果（`runtime/ui-tour/fix5-aiops-blocked.png`、`fix5-aiops-acknowledged.png`）：
填入问题后按钮仍为 `disabled`，勾选后变为可点。`PROBE_ENABLED=true` 起一个独立实例
（端口 8201）验证：`services` 里出现 `probe`，且错误信息指向 `127.0.0.1:18767`，说明探
的是 Probe 的 `/health` 而不是 MCP 端点。

## 二、服务状态要等约 12 秒（无法复现，改为缩短等待）

复核结论：原报告写的「各依赖串行探活」不成立——`check_dependencies` 一直是
`asyncio.gather` 并发，单项 3 秒超时。逐项实测（`runtime/docs-tools/time_dependency_checks.py`）：
`mcp_monitor`、`mcp_cls` 不可用，其余五项正常，并发总耗时 **2.10 秒**；HTTP 实测
`/api/v1/health/dependencies` 稳定在 2.04–2.07 秒。冷导入 pymilvus 1.03 秒、minio
0.10 秒、pika 0.02 秒、redis 0.10 秒，也解释不了 12 秒。因此 12 秒是当时
Milvus/MinIO/RabbitMQ 全不可用叠加首次冷启动的结果，本机已无法复现。

即便如此，页面上不应该每次都重新建一遍连接，所以加了两件事：
- 依赖探活结果缓存 5 秒（`_DEPS_CACHE`）。5 秒内重复进入仪表盘直接复用，超过则重探，
  恢复中的服务最多晚 5 秒被看见。
- 大模型可达性探测的超时从 5 秒收到 3 秒。依赖面板受最慢一项支配，其余各项本来就是 3 秒。

真实浏览器结果（Vite 代理到 8200，页面内 `fetch` 计时）：第一次 **2046 ms**、5 秒内第二次
**8 ms**、再过 6 秒 **2056 ms**。仪表盘首次进入的 `/health/dependencies` 资源耗时 2067 ms。

## 三、前后端分块默认值不一致（已修）

前端新建知识库表单默认 `chunk_size=500`、`chunk_overlap=50`，后端
`settings.CHUNK_SIZE=1000`、`CHUNK_OVERLAP=200`，详情页本来也用 1000/200。于是
「什么都不改直接建库」建出来的库与后端默认值不同，同一份文档切出来的片段数也不一样，
而这种差异只会表现为检索效果变差，很难被发现。

已把三处默认值（新建表单、编辑表单、编辑回填兜底）统一到 1000/200，并加测试断言提交
给 `/knowledge-bases/` 的 `chunking_config` 就是 1000/200。

## 四、模型下拉只有一个（并非缺陷，补充说明）

选项来自后端 `settings.AVAILABLE_MODELS`，当前 `.env` 与 `.env.example` 都只配了
`deepseek-v4.1-flash-1017`。这不是下拉框坏了，而是确实只配置了一个。在 Agents 与助手
两个页面的模型选择下方加了一行说明：当前只配置了 1 个模型，可选项来自后端
`AVAILABLE_MODELS`，不表示供应商额度或可用性。真正的修法是配置里加模型，不属于代码缺陷。

## 五、回归

- 后端：`pytest -q --no-header` → 2126 passed / 106 deselected / 0 failed。
- 前端：`npx vitest run` → 20 个文件 / 116 个用例全通过。
- 新增测试：`tests/test_health_dependencies.py`（6 例，覆盖 probe 条目契约与 5 秒缓存）、
  `frontend/src/views/AIOps.evidencePrecondition.test.js`（4 例）、
  `frontend/src/views/KnowledgeBase.chunkDefaults.test.js`（1 例）。