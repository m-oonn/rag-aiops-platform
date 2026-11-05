# 运维Agent报告设计复核与最小改造建议

2026-11-04。本轮为公开资料调研和本地调用链核对，没有实施生产修改、运行新模型或采集现场。接续`report-model-acceptance-20261104.md`，不改写上次degraded结果或历史评分。

## 结论

保留现有后端与replanner中的报告收束入口，修reporting模块的数据分工。完整证据和报告内容由程序保证；可选模型只排列一份明确列出的核心事实。默认规则报告继续使用。

这里需要纠正一个容易误导的说法：本次不能简单归结为“提示词不够好”，也没有证据说明增加一个Agent节点就能解决。当前模块已经有证据包、受限schema、完整性校验和规则回退。真正暴露的断点，是把不同作用的材料混进同一排序集合，再要求模型全部重列。另一个投入问题是：优先对象、解释和行动边界已由程序确定，模型只是重排ID；当前没有证据证明这次额外模型请求必要。

## 市面公开实现能确认什么

仅引用厂商官方文档、工程文章和项目维护者文档。商业产品的内部节点、服务划分和守卫实现未公开，不能由产品界面反推出内部架构。开源master文档是本次查阅时的内容，不当成固定版本承诺。

| 参考 | 可核实做法 | 对当前项目的启发与限制 |
|---|---|---|
| Datadog Bits Investigation [S1,S2] | 假设→针对性查询→证据更新；数据不足时可给inconclusive。工程文章记录过：把所有工具结果一次交给总结，曾被上游可疑信号带偏，虽然已有工具找到关键原因 | 报告接收已经收束的调查状态；不要靠最后一轮总结重新决定根因。文章不是公开的固定渲染器实现 |
| Microsoft Azure SRE Agent [S3]及Azure Copilot Observability Agent [S4] | 前者公开假设验证和引用链；后者报告列出时间与影响范围、异常组件、被排除的解释、缓解措施、支持数据，并保存完整调查上下文 | 可借鉴主报告与可追溯详情的职责；“排除”只能来自本项目实际反证，不能为了填章节编造。两者是不同产品，不能混称同一实现 |
| HolmesGPT [S5,S6] | 可按sections生成解释、可能原因、日志等；维护者明确说明模型可能输出null、增加或忽略章节。HTTP接口另支持response_format schema，返回中保留tool_calls | 章节提示和schema解决结构表达，仍需本项目的集合完整性、引用和边界检查。不把strict支持推广到当前供应商或型号 |
| Dynatrace SRE Agent [S7] | 官方页面描述固定模板：root cause、key findings、conclusion、recommendations，并把调查接入既有工作流和问题记录 | 复用既有流程、标准结构；没有独立证据时，本项目“根因”字段仍应表示未知。固定模板不是因果证明 |

Datadog评测工程文章[S8]还强调，不只检查最后结论，也看调查轨迹是否找到有价值信号、是否查得足够深。这支持本项目继续分开衡量“调查得到什么”和“报告表达怎样”，不能用报告整齐代替调查有效。

这些资料支持职责分离、证据可追溯、允许未定论和轨迹评测；**它们并未共同证明所有运维Agent都用确定性报告渲染器**。下面的具体方案是结合本项目约束作出的工程选择。

## 本项目实际断点

1. `reporting.py::build_bundle`将5条主要finding写成fact-0至4，再把2条日志、3条采集说明写成note-4至8，全部放入facts。
2. `ReportLayout.fact_order`要求对这个混合集合排序；`_model_layout`把完整bundle作为JSON送给模型。完整bundle还包括原建议、检查及限制，许多字段并不需要模型重写。
3. 真实请求669只返回5个fact-*，没有返回note-*；对象、解释和行动集合完整，finish_reason为tool_calls，输出161 Token。能确认的是业务契约未满足，不能证明是输出上限不足。
4. `validate_layout`正确拒绝不完整集合，随后规则回退。因此数据最终没有丢失，但模型编排没有交付成功。

这些事实见`runtime/report-model-acceptance-20261104-a/live/{rejection-analysis,report-generation,result}.json`。命名与输入组织可能影响模型行为，单次轨迹不足以认定唯一提示原因。

## 建议怎样改

仍走既有链路：

```text
调查策略给出经过守卫的结果
        ↓
reporting构造完整、带版本的报告包
        ├─ 规则顺序：默认可直接出稿
        └─ 可选模型：只对明确的核心事实ID排序
        ↓
程序校验核心排序，固定保留日志/采样限制/未知/停止理由
        ↓
统一渲染response、diagnosis建议、报告详情并持久化
```

**一、把完整报告包与模型输入投影分开。** 原始已验证证据包继续保存，不删审计材料。新报告包区分核心事实、日志来源说明、采集覆盖说明、未决与停止信息；分类来自现有finding来源和已知说明类别，不让模型猜。模型输入仅包含本次允许排序的核心事实ID、对象、简短观察和必要上下文，另给明确的allowed_core_fact_ids。没有分类依据的材料固定保留，不能因为不理解就丢弃。

**二、缩减模型输出职责。** 本阶段如保留模型路径，使用清楚的`core_fact_order`，只重排全部核心事实。优先对象、合法解释及处理前提已经由程序确定，继续由程序掌握；不让模型重复返回没有实际选择空间的对象/解释/行动列表。提示词给出实际可排序清单、完整输出示例、一次且只一次规则；日志与限制可作阅读上下文，但不要求模型重新抄回。程序验证集合完全一致、无重复和陌生ID。schema约束只是辅助，不能移除业务守卫。

**三、固定内容由程序按关联呈现。** 两条日志留在对应对象的证据说明，采样限制贴近相关进程观察；未知、冲突、停止理由和引用由程序输出。完整记录在详情，主报告使用简短原义说明及可定位引用，不把JSON或全部审计历史堆给用户。分组依据必须显式；没有映射时按原范围保留。已知信息不能通过“模型没返回”被删除，也不能将历史日志陈述写成独立因果确认。

**四、保留失败含义与兼容读取。** 核心排序缺项仍回退，不自动补模型答案后称成功，不新增纠正调用。记录本次采用的契约版本、投影hash、解析提议、错误及最终来源；新旧报告包按版本读取，旧checkpoint只读不迁移。API、事件和前端页面不变。`finalize_report`仍一次保存同源结果，刷新不触发生成。

本次最小修改应集中在`reporting.py`和已有报告/评测消费测试。若内部报告版本改变，机械读取方需最小兼容调整；这是内部记录兼容工作，不扩大为公开API或调查策略改造。4项既有停止审计失败和inventory/resources空投影继续单列，不并入本次报告改造。

## 验收与费用边界

先用请求669的原提议及同一bundle免费复现原完整性错误，再构造新契约输出验证：5条核心事实可以合法排序，2条日志和3条采样说明无论模型排列如何都保留。原布局可显式投影为新契约的离线样例，但必须记录转换步骤，不能冒充模型真实按新提示返回或改判原场成功。

再验证核心缺项/重复/陌生ID被拒绝、独立异常和未知不被删、非法处理顺序不出现、规则和模型两路径的主报告/建议/详情/关闭重开读取一致、旧记录兼容及刷新零请求。优先运行已有报告、预算、评测读取及持久化测试，不新增故障场或重复铺全仓测试。

完成免费改造后仍默认规则。只有出现明确而且规则无法满足的表达目标，才有理由另行审议一次同输入模型对照；不能为了获得model/ready而持续付费调提示。本轮不新增真实调用，也不将累计预算余量当作重试许可。

## 部署判断

当前报告只依附现有诊断结果，没有独立负载、权限或发布需求；在既有后端模块中分开职责即可，不增加LangGraph节点或进程。若以后多个系统共享报告能力，或真实负载需要独立扩缩容，再评估拆服务。

拆服务将增加部署进程/镜像、服务鉴权、证据传输与版本、网络故障与幂等、跨服务预算账本、监控告警及运维发布；这些成本不能直接解决本次遗漏，当前没有承担理由。

## 查阅来源

以下官方资料于2026-11-04查阅；仅核对公开行为，不代表安装或付费实测。

- [S1] Datadog，Introducing Bits Investigation, your AI on-call teammate：`https://www.datadoghq.com/blog/bits-ai-sre/`（调查文档地址本次抓取受限，未将其作为已读取正文）
- [S2] Datadog，How we built an AI SRE agent that investigates like a team of engineers：`https://www.datadoghq.com/blog/building-bits-ai-sre/`
- [S3] Microsoft，Root cause analysis in Azure SRE Agent：`https://learn.microsoft.com/en-us/azure/sre-agent/root-cause-analysis`
- [S4] Microsoft，Deep investigations in the Azure Copilot Observability Agent：`https://learn.microsoft.com/azure/azure-monitor/aiops/observability-agent-deep-investigations`
- [S5] HolmesGPT，FEATURES.md / Sectioned output：`https://github.com/HolmesGPT/holmesgpt/blob/master/FEATURES.md`
- [S6] HolmesGPT，HTTP API / response_format：`https://github.com/HolmesGPT/holmesgpt/blob/master/docs/reference/http-api.md`
- [S7] Dynatrace官方Hub，SRE Agent：`https://website.dm.dynatrace.com/hub/detail/sre-agent/`
- [S8] Datadog，How we built a real-world evaluation platform for autonomous SRE agents at scale：`https://www.datadoghq.com/blog/engineering/bits-ai-eval-platform/`

本地核对`reporting.py`、`replanner.py`、评测report_model接线及请求669保存结果。本轮未运行代码测试、未修改生产代码、未进行真实模型或现场验收。
