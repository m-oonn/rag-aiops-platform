# 普通问答与Agent统一GLM（2026-10-27）

用户要求“普通问答等等能用glm的就用glm”。本轮在main工作树将生成/推理统一到RightAPI的 `glm-5.3-flash`，独立核验材料位于 `runtime/glm-default-switch-20261027-a/`。

## 实际改动与范围

- 本机 `.env` 的 `LLM_API_BASE/KEY`、`LLM_MODEL`、主/简单/证据裁判Agent模型同步已提供的RightAPI私有配置；白名单仅保留GLM，显示名GLM-5.3-Flash，`AGENT_DISABLE_THINKING=false`。只替换指定字段，其他私有配置逐项核对未改，不生成含凭据的备份、hash或报告。
- 源码默认值与 `.env.example` 同步。普通问答、RAG回答、QA生成等LLMClient路径使用GLM默认；AIOps规划、执行、再规划、报告仍沿原工厂。没有修改LangGraph状态或策略。
- 模型列表API按全局配置返回GLM；Chat、Assistant、Agent三个页面的模型列表失败回退同步，防止接口异常后提交旧模型。
- 旧助手保存的非白名单模型在LLMClient运行时回退当前默认；旧普通Agent在工具服务入口同样回退。原数据库记录和版本不迁移。ORM新助手默认跟随全局模型；显式聊天模型仍须通过白名单。
- 实验profile仍独立，当前常规与实验均指向GLM。证据裁判开关保持关闭，不增加调用。
- 向量继续使用硅基流动 `BAAI/bge-m3`，重排继续使用百炼 `qwen3.7-text-rerank`；BM25、Milvus和语料未改。聊天模型不替代专用向量或重排模型。

## 验证与限制

使用合成凭据mock工厂验证RAG和Agent选择同一模型/端点、旧模型回退、ORM默认、模型列表及聊天白名单；没有网络请求。前端增加模型列表接口失败后选择GLM的回归。配置解析显示四角色GLM，不发送旧供应商thinking扩展。前端全量109项与独立目录构建通过，后端默认离线全量1154项通过、99项integration排除，相关定向42项包含在全量内不累加；保留既有PyMilvus弃用与Element Plus测试警告。

没有请求RightAPI，没有验证真实鉴权、流式回答、工具或结构化输出，也未核实账户价格。低成本偏好用于选模型，不写成已验证单价或无限调用授权。现有预算器仍因模型费率/域名未适配拒绝GLM，不绕过或套旧价格。服务未启动/重启，不能仅凭文件修改宣称现有进程已加载。

旧审计runtime保留切换前状态，新配置清单与文档导航已同步。期间一次文档写入命令误在frontend目录调用根目录Python路径，未执行写入；已从项目根目录纠正，构建本身通过。

2026-10-27后续用户明确要求测试连通，已按当前私有配置发起2条最小真实请求（无自动重试、每条max_tokens=32）：普通与流式HTTP均200，均返回OK和模型glm-5.3-flash，流式收到DONE。每条usage为输入45/输出3/合计48 Token，共96 Token；耗时约8.88秒和6.07秒，仅为本次样本。供应商未返回金额，实际人民币费用未知，不套用DeepSeek费率、不改旧预算账本。记录为 `runtime/glm-connectivity-20261027-111239/result.json`。此结果确认基础鉴权、模型名和两种传输可用，不代表已验项目完整问答、工具/结构化输出或四组实验；未启动服务或Agent调查。上述“尚未发送请求/未验基础鉴权流式”更新至此，历史验收原记录保留。

2026-10-28用户确认进行一次受限真实冒烟，使用 `glm-5.3-flash`、单场 `downstream_unreachable`、每请求最多256输出Token、最多12次请求。首次运行目录为 `runtime/windows-local-faults-79d30e0d36034514b8f579c8961ea39a/`：控制器正常预检和现场进程清理通过；7次请求中前4次HTTP 200并返回usage，合计可见输入6983 Token、输出562 Token，后3次未取得HTTP响应并在60秒超时，未形成最终报告，控制器判定场景失败；现场工具已取得 inventory、依赖探测、服务状态、进程快照和文本日志，其中日志记录入口503/upstream connection failed。账本保留7条请求，`pricing_verified=false`、`estimated_cny_peak=null`，RightAPI未返回账单金额；不改旧DeepSeek账本，不把本次作为自主效果或论文正确率。完整失败原因和清理状态见该目录下 `summary.json`、模型子目录 `cost.json`、`evaluation-record.json` 与 `model-downstream_unreachable.stderr`。
