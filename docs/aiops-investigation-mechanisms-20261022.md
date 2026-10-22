# 自主调查机制首轮接入记录（2026-10-22）

本次完成：在现有 InvestigationStrategy 的实际决策路径中接入有限假设保护和矛盾触发调度，以及四组独立开关。保持 LangGraph、工具权限和原有证据/结论校验。这里记录工程行为，不宣称真实模型诊断效果已提升。

## 1. 实际流程与修改入口

页面 → API → AIOpsService.execute 初始化状态 → planner → executor 收集结果 → replanner 委托 InvestigationStrategy.decide → decide_from_evidence 校验现场与候选 → 执行机制调度 → 原有结论与后续检查校验 → 下一次 executor 或结束。

核心文件是 `src/agent/aiops/strategies/investigation.py`：

- `CandidateCheck`：候选的下一项鉴别检查、可用工具、要区分的问题和预期观察。
- `InvestigationDecision.hypothesis_condition`：当前主要假设的可核查预期。
- `Alternative.check`：替代解释的检查方案，可选，兼容旧结构化决策和历史检查点。
- `_apply_investigation_mechanisms`：记录候选及观测关系，按独立开关选择下一检查。
- `decide_from_evidence`：线上与历史规则重放共用的入口；继续执行原有证据引用、替代解释、业务范围和结论等级校验。

`src/agent/aiops/graph.py` 在创建调查状态时快照配置；`state.py` 增加可选 investigation_config；`src/settings.py` 声明新开关。没有替换为 DefaultReplanStrategy，也没有删除自主调查委托。

## 2. 首轮实现的精确定义

### 假设保护

模型曾提出、有可执行检查的候选，在后续决策中被遗漏时，可在有限期限内保留并优先核查。期限以创建后已完成的 executor 步骤数计算，默认 2；年龄严格小于 2 才保护，不是两次模型请求或两条矛盾证据。

无可靠反证且检查未执行、工具仍可用时，状态设为 protected，实际下一计划可替换为该候选检查。达到期限、已被可靠条件反驳、已经排除、数据不可得或没有可执行检查时不保护。没有工具目录的旧运行不强行生成新检查。

这是首轮可验证的“防遗漏并核查”，尚未覆盖模型显式提出但依据不足的所有淘汰情形。不把它描述为完整解决过早淘汰问题。旧 HypothesisManager 的 log-odds、保护证据计数和领域词表保留，本轮没有搬到 Windows 自主调查里，避免将分数当结论或引入其他消融差异。

### 矛盾触发

先保存上一轮的主要假设及必要预期。对新出现的、已通过目标/时效/完整性/业务范围校验的观测，用现有有限字段检查预期；不靠文本包含某个关键词判定因果矛盾。

例如旧预期是 `dependency_probe / db / tcp / failed`，新结果却是同对象 `tcp=ok`，则形成条件反证；TCP 成功仅反驳该条件，不证明所有业务正常。模型本轮改写或删除预期不能抹掉上一轮原始预期。

开关开启时，优先选择另一个没有被条件反驳、且有合法鉴别检查的候选。记录旧领先 ID、旧条件、新证据 ID、原计划、实际下一检查与原因。没有替代检查时停止或报告已独立确认的故障层，不能继续宣称已确认深层原因。

关闭时取消显式强制改向，仍保留普通模型重新规划、相同证据更新和结论门槛。G00 本来就可以由模型主动改查，不人为阻止它。

## 3. 配置与四组复现

新环境变量/Settings 字段：

| 字段 | 默认 | 含义 |
| --- | --- | --- |
| INVESTIGATION_HYPOTHESIS_PROTECTION | True | 候选防遗漏保护与优先核查 |
| INVESTIGATION_CONTRADICTION_TRIGGER | True | 可靠条件反证后的显式改向 |
| INVESTIGATION_PROTECTION_STEPS | 2，范围 0—8 | 创建后的已完成步骤保护期限 |

运行开始将配置写到 `investigation_config`，恢复时使用保存的配置；已有旧检查点在首次产生跟踪记录时固化默认配置。修改全局 settings 不应改变已经开始的组别。

| 组别 | hypothesis_protection | contradiction_trigger |
| --- | --- | --- |
| G00 | False | False |
| G10 | True | False |
| G01 | False | True |
| G11 | True | True |

内部离线图测试直接给 investigation_config，实际 API 新调查从 settings 快照。尚未新增前端或公开 API 的实验组选择入口；不需要为了本次接入改变请求契约。

旧 ABLATION_DISABLE_HYPOTHESIS_PROTECTION 同时影响旧链路弱信号与复活，不能用作这四组的新开关。四组共用候选生成、结构化 schema 和提示词；检查顺序可因机制变化。

## 4. 状态、结果与兼容边界

候选保存在 `investigation_memory.hypothesis_tracking`，字段包括 id、创建步骤、条件、检查、状态、support/contradict/neutral、证据 ID、去重指纹与事件。候选条件支持只涉及 dependency_probe/services/ports/processes 中现有可确定字段，尚不对自由文本日志做因果裁判。

同范围同诊断内容的重复采样或原文回读不反复累加观测，也不重复触发改向。空进程查询只有满足现有“配置了进程名且查询完整”的要求，才能作为进程不存在的观测。

最终 diagnosis 包含 mechanism_config；正常决策还带 mechanisms 跟踪记录，经既有 report/complete SSE 和诊断读取接口传递。结构化输出失败仍记录组别配置与未定位状态。既有前端可以继续读取 diagnosis，但本轮未增加机制时间线展示。

候选 ID 根据规范化解释文本生成，空白或大小写变化稳定；语义改写可能产生新 ID，属于当前限制。多个候选同时可查时按已有候选顺序选择，未引入信息增益评分或额外模型请求。没有新增或校准信念概率。

## 5. 验证与后续工作

改动前相关基线：95 项通过。新增回归曾在实现前因缺少 hypothesis_tracking 失败，随后用于验证调度与边界。测试使用内存业务数据库、临时 SQLite 检查点和模型/工具替身，不调用真实模型。

直接相关验证覆盖：四组防遗漏与改向、保护到期、可靠反证、重复采样、错误目标、过期/截断/篡改/越界证据、缺失工具、已完成检查、进程空查询边界、先保存旧预期再处理新建议、模型输出失败配置记录。真实 LangGraph 接线有 8 组用例，断言机制选择的检查实际进入 executor；另有 SQLite 关闭重开后候选与组别配置保持不变的用例。

本次最终默认离线回归：667 项通过，99 项 integration 按 pytest.ini 默认配置排除；有 1 条既有 PyMilvus ORM API 弃用警告。新增测试文件覆盖 37 个用例；最后一轮相关测试为 132 项通过，随后补充停止分支清空未证实根因的处理，并由上述最终全量回归覆盖。没有遗留测试失败。文档链接与 git diff --check 通过，Git 对两份 Markdown 提示未来换为 CRLF，不是检查失败。

命令：根目录 `.venv/Scripts/python.exe -m pytest -q`；测试子进程将 DATABASE_URL 显式设为 `sqlite:///:memory:`，不修改项目 .env。离线结果不能代表被排除的集成测试或真实模型可用性。

未验证：真实模型能否稳定生成所需条件/检查字段、真实故障中的改向质量、准确率与成本变化。没有启动服务、故障注入、付费调用或正式四组效果实验；历史规则重放不能代替这些实验。前端未修改，本轮不以浏览器操作作为验证。

下一步：完善候选稳定标识及“显式错误淘汰”处理，复用测试业务形成两个可恢复场景；免费检查控制器、输入与证据边界后，再按已有约定单独确认小额模型预实验。先测生成质量和费用，再决定正式实验规模。
