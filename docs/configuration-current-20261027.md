# 当前配置盘点与使用边界（2026-10-27）

本文件已按同日后续授权更新：普通问答、RAG生成、Agent统一RightAPI GLM，见[切换记录](glm-default-switch-20261027.md)。首次审计材料保留切换前状态。

本次按当前 main 工作树核对配置，不升级到上游最新模型或依赖，不把配置解析等同于服务可用。覆盖 Settings 全部132字段、独立环境变量、前端、启动器、Compose、Probe TOML、SQL知识库和依赖声明。字段值与消费者详见[132字段全表](configuration-fields-20261027.md)，机器记录位于 `runtime/configuration-audit-20261027-a/`，凭据不进入材料。

## 1. 配置从哪里生效

- `src/settings.py`：显式构造参数 > 进程环境 > 当前工作目录的 `.env` > 源码默认值。模块首次导入创建 `settings` 单例，修改文件不会自动更新已运行进程。
- `.env`：本机常规运行，50字段，其余走默认值；未发现未知字段或重复键。132字段全部已补入 `.env.example`，原先缺65字段。示例不是本机配置备份，不能覆盖现有 `.env`。
- `.env.agent-test`：6字段的本机私有实验配置，Git已忽略且未跟踪。不会自动加载；仅由专用启动器传给实验子进程。用户后续授权后，常规 `.env` 的模型端点/密钥/角色和选择器已与GLM配置统一，其余字段保留。
- `.env.example`：可解析的完整参考。示例访问令牌时长改为480分钟、集合名改为源码默认 `rag_documents_v2`，移除“当前免费/可用”的旧保证。复制到新环境前必须替换凭据。
- 从项目根目录运行。数据库、checkpoint、证据路径中存在相对路径，改变工作目录会改变其含义；`BASE_DIR`覆写也不会自动重新计算各目录字段的默认值。
- 源码静态检出5个派生属性（如 `RESOLVED_LLM_API_BASE/KEY`），未检出不存在的Settings字段引用。直接读环境的进程未必读取 `.env`。

## 2. 常规运行与后续实验

| 项目 | 常规 `.env` 解析 | 专用实验覆盖 |
| --- | --- | --- |
| 兼容API地址 | `https://www.rightapi.ai/v1` | `https://www.rightapi.ai/v1` |
| 主/简单/证据裁判Agent模型 | `glm-5.3-flash` | 三者均为 `glm-5.3-flash` |
| RAG默认与页面模型列表 | 默认与白名单均为GLM-5.3-Flash | 与常规模型一致，仍经专用实验入口加载 |
| thinking供应商扩展 | 开关false，不发送该禁用扩展 | false，不发送该供应商专有参数；不表示模型没有推理过程 |
| 凭据 | 仅保存在本机私有文件 | 仅保存在本机私有文件，不输出内容 |
| 真实请求 | 本轮没有发起 | 仅解析检查，未验鉴权、工具、结构化输出与计费 |

安全检查命令（项目根目录、不会调用模型）：

```powershell
& ./.venv/Scripts/python.exe scripts/with_agent_test_env.py --check
& ./.venv/Scripts/python.exe scripts/audit_configuration.py
```

审计可用 `--output runtime/<新的文件名>.json` 保存脱敏记录；文件必须不存在，以免覆盖旧材料。报告保留采样时间，不能当成持续监控。

`with_agent_test_env.py`仅接受三个现有评测入口：`evaluate_windows_probe.py`、`verify_windows_local_faults.py`、`evaluate_autonomous_investigation.py`，用当前Python和项目根目录启动子进程；不改父进程环境。它仅传递6个获准模型字段，不改数据库、知识库或机制条件。各入口原有付费开关和预算拦截仍然保留。

**真实实验尚有两个配置阻塞**：`PaidRequestBudget`只认可旧DeepSeek模型/费率；`evaluate_windows_probe.py`的预算HTTP transport只接受 `api.deepseek.com`。未知模型继续拒绝，不能套用旧费率。RightAPI计价、小额授权、准确usage/费用记录与transport适配完成前，不启动真实四组实验。本轮未发送用户凭据。

共享模型工厂也供非Qwen RAG使用；本次全局切换同时更新LLM_MODEL和所有Agent角色。旧助手与普通Agent已不在白名单的模型在运行时回退到当前默认，不改数据库原记录。Qwen前缀走ChatTongyi原生接口，不能用共享兼容端点解释所有模型路径。

## 3. 两机制、知识与可能收费的路径

| 配置 | 当前常规值/含义 |
| --- | --- |
| `INVESTIGATION_HYPOTHESIS_PROTECTION` | true；当前调查保护机制 |
| `INVESTIGATION_CONTRADICTION_TRIGGER` | true；可靠矛盾证据触发改查 |
| `INVESTIGATION_PROTECTION_STEPS` | 2；保护步龄 |
| `ENABLE_DYNAMIC_CLASSIFICATION` | true；旧兼容策略开关，不是两机制总开关 |
| 历史 `ABLATION_DISABLE_*` | 保留旧策略兼容；旧保护开关同时影响弱信号与复活，不用于主四组替代 |
| `ENABLE_LLM_EVIDENCE_JUDGE` | false；裁判模型字段存在不表示裁判已启用 |
| `ENABLE_STEP_SNAPSHOTS` | false；不据此承诺每轮均有完整额外快照 |
| `EXPERIENCE_KB_IDS` | 空，常规经验检索未限定只查15，仍受实际权限/调用路径影响 |
| embedding | `BAAI/bge-m3`，独立SiliconFlow兼容端点；Milvus维度1024 |
| rerank | 启用，`qwen3.7-text-rerank`；在线额度与价格未核实 |

SQL仅用SQLite `mode=ro`只读核对：本机13个知识库，库15存在，3份已完成文档、8片段，`retrieval_mode=bm25`。这是数据库记录核对，不是本轮重新入库或检索验收。BM25路线可以本地检索；未限定的经验检索可能继续处理其他hybrid库，普通问答也可能调用模型。不能把当前整个系统说成“免费模式”。

本次不自动将经验库限定为15，不替换embedding或重建索引，以免改变已有知识与实验条件。文档数量、维度配置不证明向量服务或远端索引当前可用。

## 4. 服务、Probe与独立环境

| 入口 | 配置/地址 | 本轮状态 |
| --- | --- | --- |
| Vue/Vite | `127.0.0.1:5273`，`/api`代理到 `127.0.0.1:8200` | 未发现监听；修正原localhost代理以对齐IPv4 |
| FastAPI | `127.0.0.1:8200`，`/api/v1` | 未发现监听，未启动/重载 |
| 默认MCP | cls8103、monitor8104、rag8105、change8106 | 未发现监听，未启动 |
| 可选工具 | diagnostic8107、TermCP18765/18766、Probe18767 | 主应用三个开关均关闭；未发现对应监听 |
| 数据/观测 | Milvus19530、Redis6379、RabbitMQ5672、MinIO9000、ES9200、Prometheus19090 | 本轮关注端口未发现监听，不代表已卸载或历史数据丢失 |

以上是本机TCP采样，不是健康检查，也不证明其他网络接口/端口或容器内部状态。`launch_demo.py`默认6个应用服务，不自动包含Probe、diagnostic、TermCP；`up/down`与 `start/stop`作用范围不同，不能因文档存在而自动执行。

Windows Probe实际TOML位于 `%ProgramData%/RagAIOpsProbe/config.toml`，可由 `RAG_AIOPS_PROBE_CONFIG`覆写。本机文件可解析，配置1个service、0个顶层dependency，gateway/target已设置、令牌文件存在；只检查文件存在，没有读取令牌内容，也未核对Windows服务身份/运行权限。主应用 `PROBE_ENABLED=false` 仍成立，两层不能混为一谈。

`mcp_servers/probe_gateway.py`直接从进程环境取 `PROBE_TOKEN`、`PROBE_TARGET_ID`、`PROBE_STALE_SECONDS`，不自动加载主 `.env`。TermCP网关同样直接读取内部URL、token、SSH profile；diagnostic另有对象/命令白名单和执行开关。全部直接环境名与源码位置见全表附录，不能把它们都放入主 `.env`就认为生效。

监控和日志常规配置为Prometheus/Elasticsearch，不可达不应回退为伪造数据。Prometheus抓取由 `docker/prometheus/prometheus.yml`控制，当前示例重复抓取同一node-exporter并重写两个服务标签，这不能证明两个业务各自有独立资源指标。指标中间件还可能受第三方库 `ENABLE_METRICS`环境约束；这类依赖内部环境不在本仓AST清单内。

## 5. Docker、前端和测试边界

三个Compose文件已静态解析，服务名、环境字段名、profiles与端口保存在 `external-config-final.json`。主Compose为app/worker覆写容器内数据库、Milvus、Redis、RabbitMQ、MinIO地址；SQLite使用Docker卷。宿主本机数据库与容器数据库不能视为同一份。容器环境与Compose插值可能覆盖挂载项目里的 `.env`，Compose的插值来源还与调用目录/参数有关；不要直接打印插值后的完整配置，以免泄露凭据。

`docker-compose.probe-local.yml`只为Probe网关额外提供宿主绑定端口；可选TermCP相关服务仍有profile。`.dockerignore`和`.gitignore`都排除私有env和运行数据。未启动Docker、拉取镜像或验证镜像可重建性。

前端开发地址由Vite决定，业务常量前缀固定 `/api/v1`，仅Monitor个别路径读取 `VITE_API_BASE_URL`；Dockerfile传的 `VITE_API_BASE`目前无对应业务消费者，不能当全局API切换开关。Docker nginx配置未配置 `/api`反向代理，此路径需单独部署验收，本轮不扩大为Docker部署改造。当前本科路线继续使用Windows本机Vite/API。

前端存在 `package-lock.json`，使用npm现有安装验证，未重装。`pytest.ini`默认排除integration；`.github/workflows/tests.yml`与主Dockerfile原声明Python3.10，但现有Probe直接使用Python3.11+的tomllib；本轮统一声明为Python3.12，并保留CI过滤重型依赖，不代表CI安装与本机环境完全相同。Pages工作流只发布 `docs/site`；本轮未推送或触发部署。

Python依赖逐项对照已安装版本，发现唯一精确版本差异为 `prometheus-fastapi-instrumentator`：声明6.1.0、实际7.0.0。本轮将声明同步到已安装7.0.0，没有执行升级或安装；其余可解析的 `==`条目相符，`pip check`通过。本机Python为3.13.11，未用Python3.12重新安装或复验全仓。记录安装版本不等于完成全依赖漏洞审计，也不保证全新环境解算成功。

## 6. 本轮变更、验证和剩余事项

- 增加只读脱敏配置盘点、实验子进程profile加载与回归；实验源码快照包含这两个脚本，继续排除env、凭据及数据。
- 补齐示例132字段，修正旧模型免费措辞/策略开关说明，修正Vite代理地址，同步一项依赖声明以及Python运行版本声明。原有业务数据与历史实验材料未覆盖；全局 `.env` 仅按后续授权修改指定模型字段。
- 后端相关8文件180项通过（含先前定向48项，不累加），结果见本轮 `regression.xml`，前端108项通过，独立输出目录构建通过。保留既有PyMilvus弃用和Element Plus测试警告；静态扫描原脚本文档字符串有2条既有escape警告。
- profile离线解析通过，三个Agent角色为GLM，端点为RightAPI；`model_calls=0`，鉴权、工具/结构化输出和价格均未验证。

下一步按原路线继续免费文献/论文核对和真实人工审核。配置方面真实模型前须完成费率与预算transport适配，再取得约定小额调用授权；不反复用配置盘点代替实验。未来增加Settings字段时运行本轮覆盖测试和审计，避免示例再次遗漏。外部账号后台、第三方库隐含环境、嵌入脚本和运行进程内存未穷尽，不能承诺理论上零遗漏或已全系统端到端通过。

2026-10-27后续用户明确要求测试连通，已按当前私有配置发起2条最小真实请求（无自动重试、每条max_tokens=32）：普通与流式HTTP均200，均返回OK和模型glm-5.3-flash，流式收到DONE。每条usage为输入45/输出3/合计48 Token，共96 Token；耗时约8.88秒和6.07秒，仅为本次样本。供应商未返回金额，实际人民币费用未知，不套用DeepSeek费率、不改旧预算账本。记录为 `runtime/glm-connectivity-20261027-111239/result.json`。此结果确认基础鉴权、模型名和两种传输可用，不代表已验项目完整问答、工具/结构化输出或四组实验；未启动服务或Agent调查。上述“尚未发送请求/未验基础鉴权流式”更新至此，历史验收原记录保留。

2026-10-28受限真实冒烟已尝试：`glm-5.3-flash` 在单场 `downstream_unreachable` 中发起7次请求，其中4次HTTP 200并有usage，后3次各在60秒未取得HTTP响应而超时；工具现场证据采集和临时进程/端口清理通过，但无最终报告，不能宣称Agent调查完成。产物位于 `runtime/windows-local-faults-79d30e0d36034514b8f579c8961ea39a/`；7条请求均标记 `pricing_verified=false`，供应商未返回金额，`estimated_cny_peak=null`。这次只证明RightAPI在项目结构化调用链中可以返回部分结果，暴露了重规划阶段超时和最终报告缺失问题；未启动四组实验，不修改既有费用账本。
