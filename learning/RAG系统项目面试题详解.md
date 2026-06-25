# RAG 系统项目面试题详解 (100 题)

本文档整理了围绕 RAG (检索增强生成) 系统项目的 100 道面试题，涵盖基础原理、系统架构、数据库、算法、工程实践、性能优化及运维部署等多个维度。

---

## 第一部分：RAG 基础原理 (20题)

1.  **什么是 RAG？它解决了 LLM 的哪些核心痛点？**
    *   **解答**: RAG (Retrieval-Augmented Generation) 结合了检索系统和生成式模型。它解决了 LLM 的三大痛点：
        1.  **知识滞后性**: LLM 的训练数据截止于训练结束时，无法回答最新问题。
        2.  **幻觉问题 (Hallucination)**: LLM 在不知道答案时倾向于一本正经地胡说八道。
        3.  **私有数据缺失**: LLM 无法访问企业内部文档或个人隐私数据。

2.  **RAG 的基本工作流程是怎样的？**
    *   **解答**: 索引 (Indexing) -> 检索 (Retrieval) -> 生成 (Generation)。
        1.  **索引**: 文档解析 -> 切分 (Chunking) -> 向量化 (Embedding) -> 存入向量数据库。
        2.  **检索**: 用户 Query -> 向量化 -> 在向量库中查找 Top-K 相似片段。
        3.  **生成**: 将 Query + Top-K 片段组装成 Prompt -> 输入 LLM -> 生成回答。

3.  **为什么需要对文档进行切分 (Chunking)？切分粒度如何选择？**
    *   **解答**:
        *   **原因**: LLM 有上下文长度限制 (Context Window)；向量模型对长文本的语义表征能力有限；检索时需要精确匹配相关片段而非整本书。
        *   **粒度**: 
            *   **太小**: 语义不完整，丢失上下文。
            *   **太大**: 包含过多噪声，干扰检索和 LLM 推理。
            *   **策略**: 固定字符数 (如 500-1000)、按段落/句子切分、递归切分 (Recursive)。通常配合 Overlap (重叠) 使用。

4.  **什么是 Embedding？它在 RAG 中起什么作用？**
    *   **解答**: Embedding 是将文本转换为低维稠密向量 (Dense Vector) 的过程。它将语义相似的文本映射到向量空间中距离相近的点。在 RAG 中，它用于计算用户 Query 与文档片段之间的语义相似度。

5.  **RAG 与 Fine-tuning (微调) 有什么区别？如何选择？**
    *   **解答**:
        *   **RAG**: 外挂知识库，适合知识频繁更新、需要精准溯源、数据量巨大的场景。成本低，见效快。
        *   **Fine-tuning**: 内化知识，适合改变模型行为风格、特定任务格式输出、知识相对稳定的场景。成本高，训练慢。
        *   **选择**: 优先 RAG，如果 RAG 效果不佳且需要特定领域行话/风格，再考虑 Fine-tuning。

6.  **什么是幻觉 (Hallucination)？RAG 如何减少幻觉？**
    *   **解答**: 幻觉是模型生成了看似合理但事实错误的内容。RAG 通过在 Prompt 中提供明确的“参考上下文”，并强制模型“仅根据上下文回答”，从而限制了模型的发散，显著减少幻觉。

7.  **如何衡量 RAG 系统的检索质量？**
    *   **解答**:
        *   **Recall@K (召回率)**: 前 K 个结果中包含正确答案的比例。
        *   **MRR (Mean Reciprocal Rank)**: 正确答案在结果列表中的排名倒数均值。
        *   **NDCG**: 归一化折损累计增益，考虑了相关性的排序质量。

8.  **如何衡量 RAG 系统的生成质量？**
    *   **解答**:
        *   **人工评估**: 准确性、流畅性、有用性。
        *   **自动评估 (RAGAS)**:
            *   **Faithfulness (忠实度)**: 回答是否由上下文推导得出。
            *   **Answer Relevance (相关性)**: 回答是否针对问题。
            *   **Context Precision/Recall**: 检索到的上下文是否精准/全面。

9.  **什么是 Dense Retrieval (稠密检索) 和 Sparse Retrieval (稀疏检索)？**
    *   **解答**:
        *   **Dense**: 基于 Embedding 向量，捕捉语义匹配 (如“苹果”与“iPhone”)。
        *   **Sparse**: 基于关键词 (如 TF-IDF, BM25)，捕捉精确匹配 (如人名、型号)。

10. **什么是 Hybrid Search (混合检索)？为什么要用它？**
    *   **解答**: 结合 Dense 和 Sparse 检索。因为 Dense 擅长语义理解但可能忽略精确关键词（如专有名词），Sparse 擅长关键词匹配但不懂语义。混合检索取长补短，通常使用加权求和 (Weighted Sum) 或 RRF (Reciprocal Rank Fusion) 合并结果。

11. **什么是 Rerank (重排序)？它在 RAG 中的位置和作用？**
    *   **解答**: 位于检索之后、生成之前。由于向量检索 (Bi-Encoder) 速度快但精度略低，Rerank 使用 Cross-Encoder 模型对初筛的 Top-K 文档进行精细打分，筛选出最相关的 Top-N 给 LLM，显著提高上下文质量。

12. **Context Window (上下文窗口) 是什么？它对 RAG 有什么限制？**
    *   **解答**: LLM 一次能处理的最大 Token 数。限制了 RAG 能喂给模型的参考文档数量和长度。如果召回文档过多，会超出窗口导致截断或报错。

13. **如何处理长文档 (Long Context)？**
    *   **解答**:
        *   切分 (Chunking)。
        *   摘要 (Summarization): 对长文档生成摘要存入索引。
        *   滑动窗口 (Sliding Window): 检索时包含前后文。
        *   使用支持长上下文的模型 (如 Claude 3 200k, Qwen-Long)。

14. **什么是“迷失中间”现象 (Lost in the Middle)？**
    *   **解答**: LLM 往往更容易关注 Prompt 开头和结尾的信息，而忽略中间的信息。RAG 中如果将最相关的文档放在中间，模型可能忽略。**对策**: 重排序后，将最相关的文档放在 Prompt 的开头或结尾。

15. **Query Rewrite (查询改写) 是什么？有什么用？**
    *   **解答**: 将用户原始 Query (可能模糊、指代不清) 改写为更适合检索的形式。例如补全省略的主语、扩展同义词、将多轮对话中的指代 ("它多少钱?") 还原为完整问题 ("iPhone 15 多少钱?")。

16. **RAG 系统中数据如何更新？**
    *   **解答**:
        *   **增量更新**: 新增文档 -> 切分 -> 向量化 -> 插入向量库。
        *   **删除/修改**: 根据 ID 在向量库中删除/更新对应向量。需要维护文档 ID 到向量 ID 的映射。

17. **如何处理表格数据？**
    *   **解答**: 表格直接切分会破坏结构。
        *   **方法 1**: 将每一行转换为 Key: Value 文本。
        *   **方法 2**: 提取表格摘要用于检索，原始表格存储用于生成。
        *   **方法 3**: Markdown 格式保留。

18. **什么是 Multi-hop QA (多跳问答)？RAG 如何解决？**
    *   **解答**: 问题需要结合多个文档的信息才能回答。
        *   **解决**: 
            *   **CoT (Chain of Thought)**: 让 LLM 分解问题。
            *   **递归检索**: 根据第一次检索结果生成新 Query 继续检索。
            *   **知识图谱 (Graph RAG)**: 利用实体关系跳转。

19. **Prompt Engineering 在 RAG 中的重要性？**
    *   **解答**: 极高。Prompt 决定了 LLM 如何利用检索到的上下文。好的 Prompt 需要包含：角色设定、任务描述、上下文约束 ("仅根据...")、输出格式要求。

20. **RAG 的常见架构模式有哪些？**
    *   **解答**: 
        *   **Naive RAG**: 检索-生成。
        *   **Advanced RAG**: 增加预处理 (改写)、后处理 (重排序)、混合检索。
        *   **Modular RAG**: 模块化设计，动态路由。

---

## 第二部分：向量数据库与 Embedding (15题)

21. **本项目使用的向量数据库是什么？为什么选择它？**
    *   **解答**: Milvus。
        *   **原因**: 开源、云原生、支持百亿级数据、高性能 (HNSW 索引)、社区活跃、支持标量过滤 (Scalar Filtering)。相比 FAISS (库) 更像一个完整的数据库系统。

22. **Milvus 中的 Collection、Partition、Segment 是什么关系？**
    *   **解答**: 
        *   **Collection**: 类似 SQL 的 Table，包含 Schema。
        *   **Partition**: 逻辑分区，可用于加速查询 (如按年份/用户 ID 分区)。
        *   **Segment**: 数据存储的物理单元，Milvus 自动合并小 Segment。

23. **常见的向量索引类型有哪些？(IVF_FLAT, HNSW, DiskANN)**
    *   **解答**:
        *   **FLAT**: 暴力搜索，100% 召回，慢。
        *   **IVF_FLAT**: 倒排文件，聚类加速，召回率略降。
        *   **HNSW**: 基于图的索引，速度极快，召回率高，内存占用大。
        *   **DiskANN**: 基于磁盘的索引，适合超大规模数据。

24. **什么是余弦相似度 (Cosine Similarity)？与欧氏距离 (L2) 有何区别？**
    *   **解答**:
        *   **Cosine**: 衡量向量方向的差异，对向量长度不敏感。常用于文本语义相似度。
        *   **L2**: 衡量向量空间距离，对长度敏感。
        *   **注意**: 如果向量已归一化 (Normalized)，Cosine 与 L2 等价。

25. **Embedding 维度 (Dimension) 是什么？越高越好吗？**
    *   **解答**: 向量的长度 (如 768, 1536)。维度越高，表达能力越强，但存储和计算成本越高。需要在性能和成本间平衡。

26. **如何处理多语言检索？**
    *   **解答**: 使用多语言 Embedding 模型 (如 `m3e`, `text-embedding-ada-002`)，它们将不同语言的相同语义映射到相近向量空间。

27. **什么是标量过滤 (Scalar Filtering)？**
    *   **解答**: 在向量检索的同时，根据元数据 (Metadata) 进行过滤。例如：`search(vector, filter="user_id=123 AND date>2023")`。
    *   **Pre-filtering vs Post-filtering**: Milvus 支持高效的混合过滤。

28. **向量数据库如何保证数据一致性？**
    *   **解答**: Milvus 支持不同的一致性等级 (Strong, Bounded, Session, Eventually)。RAG 通常使用 Bounded (有界) 或 Session (会话) 一致性即可。

29. **如果检索结果不相关怎么办？**
    *   **解答**: 
        *   检查 Embedding 模型是否适配领域数据。
        *   检查切分策略是否合理。
        *   尝试混合检索 (加入关键词)。
        *   引入 Rerank。

30. **Embedding 模型如何微调 (Fine-tuning)？**
    *   **解答**: 使用对比学习 (Contrastive Learning)。构造 (Query, Positive Document, Negative Document) 三元组，训练模型拉近 Query-Pos 距离，推远 Query-Neg 距离。

31. **Milvus 的部署模式有哪些？**
    *   **解答**: Standalone (单机 Docker)、Cluster (分布式 K8s)。本项目使用 Standalone。

32. **如何备份和恢复向量数据？**
    *   **解答**: Milvus 提供了 `Milvus-Backup` 工具。或者直接备份底层存储 (MinIO/S3) 和元数据存储 (Etcd)。

33. **什么是 Cross-Encoder 和 Bi-Encoder？**
    *   **解答**:
        *   **Bi-Encoder**: 分别计算 Query 和 Doc 的向量，计算 Cosine。速度快，适合大规模检索 (Embedding)。
        *   **Cross-Encoder**: 将 Query 和 Doc 拼接输入模型，直接输出分数。精度高，速度慢，适合重排序 (Rerank)。

34. **如何优化向量检索的延迟？**
    *   **解答**: 使用更快的索引 (HNSW)；减少 Top-K；降低维度 (量化)；增加硬件资源；使用 Partition 缩小搜索范围。

35. **Text Embedding 模型有哪些推荐？**
    *   **解答**: OpenAI `text-embedding-3`；HuggingFace `BGE`, `M3E`；Qwen `text-embedding`。

---

## 第三部分：LLM 与 Prompt (15题)

36. **本项目使用了哪个 LLM？为什么？**
    *   **解答**: Qwen-Max (通义千问)。中文能力强，API 成本合理，支持长上下文。

37. **什么是 System Prompt？它在 RAG 中的典型写法？**
    *   **解答**: 设定模型行为的指令。
    *   **典型写法**: "你是一个智能助手。请仅根据提供的上下文回答问题。如果上下文中没有答案，请回答不知道，不要编造。"

38. **Temperature 参数如何设置？**
    *   **解答**: 
        *   **RAG (知识问答)**: 设置低 (0.0 - 0.3)，追求准确、确定性。
        *   **创意写作**: 设置高 (0.7 - 1.0)，追求多样性。

39. **如何处理 Token Limit 超出问题？**
    *   **解答**: 截断上下文；使用支持更大 Context 的模型；优化切分策略；精简 Prompt。

40. **什么是 In-Context Learning (上下文学习)？**
    *   **解答**: LLM 不需要更新参数，仅通过 Prompt 中的示例 (Few-shot) 或上下文信息就能学习并完成任务的能力。RAG 本质上就是一种 In-Context Learning。

41. **如何防止 Prompt Injection (提示注入) 攻击？**
    *   **解答**: 严格分隔 System Prompt 和 User Input (使用特殊分隔符)；检测输入中的恶意指令；使用最新的安全对齐模型。

42. **LLM 的输出流式传输 (Streaming) 是如何实现的？**
    *   **解答**: 基于 Server-Sent Events (SSE)。后端逐步生成 Token 并推送给前端，前端实时渲染，提升用户体验 (TTFT - Time To First Token)。

43. **什么是 Chain of Thought (CoT)？**
    *   **解答**: 引导模型 "Let's think step by step"。对于复杂推理问题，CoT 能显著提高正确率。

44. **Function Calling (工具调用) 是什么？RAG 中怎么用？**
    *   **解答**: LLM 输出特定的 JSON 格式请求调用外部函数。RAG 中可用它来决定 "是否需要检索"、"调用搜索引擎" 或 "查询数据库"。

45. **如何评估 LLM 的生成效果？**
    *   **解答**: 
        *   **Reference-based**: BLEU, ROUGE (不适合生成式)。
        *   **Model-based**: 使用 GPT-4 作为裁判 (LLM-as-a-Judge)。

46. **Qwen 模型支持的上下文长度是多少？**
    *   **解答**: Qwen-Max 支持 8k/32k 等版本，Qwen-Long 支持 10M (理论值)。具体视 API 版本而定。

47. **如何降低 LLM API 的成本？**
    *   **解答**: 缓存常见问题的回答 (Semantic Cache)；使用更便宜的模型 (Qwen-Turbo) 处理简单任务；精简 Prompt；批量处理。

48. **什么是 P-tuning / LoRA？**
    *   **解答**: 参数高效微调方法。LoRA (Low-Rank Adaptation) 冻结预训练参数，只训练低秩矩阵，大幅降低显存需求。

49. **如何让 LLM 输出 JSON 格式？**
    *   **解答**: 在 Prompt 中明确要求 JSON 格式及 Schema；使用模型的 JSON Mode (如果支持)；使用 Pydantic Parser 校验修复。

50. **OpenAI 兼容接口的好处是什么？**
    *   **解答**: 生态兼容。可以无缝切换模型 (如从 GPT-4 切到 Qwen)，复用 LangChain 等框架代码。

---

## 第四部分：后端与架构 (15题)

51. **为什么选择 FastAPI 而不是 Flask/Django？**
    *   **解答**: 
        *   **异步支持 (AsyncIO)**: 原生支持 `async/await`，适合 IO 密集型 (API 调用, DB 查询) 的 RAG 任务。
        *   **性能**: 基于 Starlette 和 Pydantic，速度极快。
        *   **类型检查**: 利用 Python Type Hints，减少 Bug。
        *   **自动文档**: 自动生成 Swagger UI。

52. **Celery 在项目中的作用是什么？**
    *   **解答**: 异步任务队列。用于处理耗时的文档解析、Embedding 和 批量评测。避免阻塞 API 主线程，防止 HTTP 超时。

53. **RabbitMQ 与 Redis 作为 Broker 的区别？**
    *   **解答**:
        *   **RabbitMQ**: 专业消息队列，支持持久化、复杂路由 (Exchange)、可靠性高。
        *   **Redis**: 内存数据库，速度快，轻量，但在消息堆积和可靠性上不如 RabbitMQ。
        *   **本项目**: 使用 RabbitMQ 做 Broker，Redis 做 Result Backend。

54. **MinIO 是什么？为什么不用本地文件系统？**
    *   **解答**: 对象存储服务器 (S3 兼容)。
        *   **优势**: 分布式、高可用、支持预签名 URL (Presigned URL) 安全分享、与 Docker 容器环境解耦 (避免容器销毁数据丢失或路径问题)。

55. **SQLAlchemy 的作用？什么是 ORM？**
    *   **解答**: Python 的 SQL 工具包和 ORM (对象关系映射)。将 Python 类映射到数据库表，操作对象即操作数据库，屏蔽 SQL 差异，防注入。

56. **如何处理并发请求？**
    *   **解答**: FastAPI + Uvicorn (ASGI 服务器) 利用 Event Loop 处理并发。Celery Worker 扩展处理后台任务。

57. **Pydantic 在项目中的用途？**
    *   **解答**: 数据验证和序列化。定义 API 的 Request/Response Schema，确保数据格式正确。

58. **如何实现用户认证 (Auth)？**
    *   **解答**: OAuth2 Password Flow + JWT (JSON Web Token)。登录颁发 Token，API 依赖 `get_current_user` 校验 Token。

59. **Docker Compose 的网络隔离 (Networks) 是怎么工作的？**
    *   **解答**: `rag_net` 创建了一个虚拟网络，容器间可以通过 Service Name (如 `milvus-standalone`) 互相访问，无需关心 IP。

60. **如何优化 Docker 镜像大小？**
    *   **解答**: 使用 Slim/Alpine 基础镜像；多阶段构建 (Multi-stage Build)；合并 RUN 指令；清理缓存 (`pip cache purge`).

61. **项目中的 `settings.py` 是如何管理配置的？**
    *   **解答**: 使用 `pydantic-settings` 读取 `.env` 环境变量。优先级：环境变量 > .env 文件 > 默认值。

62. **如何处理 Python 的依赖冲突？**
    *   **解答**: 使用虚拟环境 (`venv`, `conda`)；锁定版本 (`requirements.txt` 或 `poetry.lock`)。

63. **Redis 在项目中的用途有哪些？**
    *   **解答**: Celery Result Backend；缓存 Session；API 限流 (Rate Limiting)；简易的键值存储。

64. **如何实现 SSE (Server-Sent Events)？**
    *   **解答**: FastAPI `StreamingResponse`，返回 `yield` 生成器，MIME 类型 `text/event-stream`。

65. **项目结构设计遵循什么原则？**
    *   **解答**: 分层架构 (Layered Architecture)。API 层 (Routers) -> 业务逻辑层 (Services) -> 数据访问层 (CRUD/DB) -> 基础设施层 (Utils/Config)。

---

## 第五部分：前端与 Vue 3 (10题)

66. **Vue 3 相比 Vue 2 的最大改进是什么？**
    *   **解答**: Composition API (组合式 API)。更好的逻辑复用 (Hooks)，更好的 TypeScript 支持，Tree-shaking 优化，更快的 Virtual DOM。

67. **Composition API (`setup`) 的优势？**
    *   **解答**: 将相关联的业务逻辑 (State, Method, Watch) 组织在一起，而不是分散在 data, methods, mounted 中。

68. **Element Plus 是什么？**
    *   **解答**: 基于 Vue 3 的 UI 组件库。提供现成的 Table, Form, Dialog 等组件，加速开发。

69. **如何实现前端的即时聊天打字机效果？**
    *   **解答**: 接收后端 SSE 流，将收到的字符逐步追加到 `message.content`，并触发视图更新。

70. **前端如何与后端交互？**
    *   **解答**: 使用 Axios 库。封装 `request.js`，统一处理 Base URL、Header (Token)、响应拦截 (401 跳转登录)。

71. **Vue Router 的作用？**
    *   **解答**: SPA (单页应用) 的路由管理。实现页面无刷新跳转，路由守卫 (Guards) 控制权限。

72. **什么是响应式原理 (Reactivity)？Ref vs Reactive？**
    *   **解答**: Vue 3 使用 Proxy 代理对象。
        *   **Ref**: 处理基本类型 (通过 `.value` 访问)。
        *   **Reactive**: 处理对象/数组 (深层响应)。

73. **如何解决跨域 (CORS) 问题？**
    *   **解答**: 
        *   **开发环境**: Vite `server.proxy` 转发。
        *   **生产环境**: Nginx 反向代理 或 后端 FastAPI 配置 `CORSMiddleware`。

74. **前端如何预览 MinIO 中的文件？**
    *   **解答**: 后端生成 Presigned URL (临时访问链接) 或通过后端 Proxy 接口流式转发文件内容 (解决内网 IP 问题)。

75. **Vue 组件通信方式有哪些？**
    *   **解答**: Props/Emit (父子), Provide/Inject (祖孙), Pinia/Vuex (全局状态), EventBus.

---

## 第六部分：工程实践与优化 (15题)

76. **如何提高 PDF 解析的准确率？**
    *   **解答**: 使用 OCR (如 PaddleOCR) 处理扫描件；针对多栏排版进行版面分析 (Layout Analysis)；提取表格单独处理。

77. **RAGAS 评测框架的原理？**
    *   **解答**: 利用强 LLM (如 GPT-4) 作为裁判，根据预定义的 Prompt 模板，对 (Question, Answer, Context, Ground Truth) 进行评分。

78. **如何处理多轮对话的上下文？**
    *   **解答**: 
        *   **拼接**: 将历史对话拼接在 System Prompt 后。
        *   **改写**: 将 "它" 改写为具体的指代对象。
        *   **摘要**: 对长历史进行摘要。

79. **如何优化系统的响应速度 (Latency)？**
    *   **解答**: 
        *   **流式输出**: 提升感知速度。
        *   **异步处理**: 文档上传不阻塞。
        *   **缓存**: 语义缓存 (Semantic Cache) 命中相似问题直接返回。
        *   **硬件**: GPU 加速 LLM 和 Embedding。

80. **如何保证数据安全 (Security)？**
    *   **解答**: HTTPS 加密；API 鉴权；敏感数据脱敏；私有化部署 (LLM 本地化)；MinIO 访问控制。

81. **如何处理 RAG 中的 "不知道" 问题？**
    *   **解答**: 设置阈值 (Threshold)，如果检索到的文档相似度都低于阈值，则直接回答 "知识库中未找到相关信息"，防止强行回答导致幻觉。

82. **Git 工作流规范？**
    *   **解答**: Feature Branch Workflow。Master/Main (稳定), Develop (开发), Feature/xxx (功能)。Commit Message 规范 (feat, fix, docs)。

83. **如何进行单元测试 (Unit Test)？**
    *   **解答**: Python 使用 `pytest`。Mock 外部依赖 (DB, LLM API) 进行隔离测试。

84. **什么是 CI/CD？**
    *   **解答**: 持续集成/持续部署。Git Push -> 自动运行 Test -> Build Docker Image -> Deploy。

85. **如何排查 RAG 效果不好的原因？**
    *   **解答**: 
        *   **检索差**: 检查 Embedding 质量、切分策略、关键词匹配。
        *   **生成差**: 检查 Prompt、Context 是否包含答案、模型能力。
        *   **工具**: 使用 RAGAS 评分定位是 Retrieval 问题还是 Generation 问题。

86. **如何设计 RAG 的缓存策略？**
    *   **解答**: 
        *   **Exact Match**: 完全相同的 Query 走 Redis。
        *   **Semantic Match**: 向量相似度极高 (如 >0.95) 的 Query 走缓存。

87. **如何处理知识库中的冲突信息？**
    *   **解答**: 在 Prompt 中提示 LLM "如果上下文存在冲突，请指出"；或者根据文档的时间戳/权威性加权。

88. **Chunk Size 对性能的影响？**
    *   **解答**: 
        *   **大 Chunk**: 检索次数少，但包含噪声多，容易超出 Context Window。
        *   **小 Chunk**: 精准，但可能切断语义，需要检索更多数量。

89. **如何实现文档的增量更新？**
    *   **解答**: 记录文档的 Hash 值。上传时比对 Hash，若变化则删除旧向量，重新切分插入新向量。

90. **Elasticsearch vs Milvus？**
    *   **解答**: 
        *   **ES**: 擅长倒排索引 (全文检索)，向量检索是插件 (KNN)，内存消耗大。
        *   **Milvus**: 纯向量数据库，向量性能更优，但缺乏全文检索 (需要配合)。

---

## 第七部分：运维与故障排查 (10题)

91. **Docker 容器无法连接宿主机服务怎么办？**
    *   **解答**: 使用 `host.docker.internal` (Windows/Mac) 或 `--network host` (Linux)。

92. **Milvus 启动失败常见原因？**
    *   **解答**: CPU 不支持 AVX 指令集；内存不足；Etcd/MinIO 依赖未就绪。

93. **如何监控系统状态？**
    *   **解答**: Prometheus + Grafana。监控 API QPS、延迟、GPU 利用率、Milvus 内存等。

94. **RabbitMQ 消息堆积怎么处理？**
    *   **解答**: 增加 Consumer (Worker) 数量；优化任务处理逻辑；设置消息 TTL。

95. **API 出现 500 Error 如何定位？**
    *   **解答**: 查看 `logs/app.log`；检查 Sentry (如果集成)；复现请求。

96. **MinIO 预签名 URL 访问不通 (SignatureDoesNotMatch)？**
    *   **解答**: 检查生成 URL 的 Endpoint 和客户端访问的 Endpoint 是否一致 (Docker 内外网 IP 问题)。

97. **如何处理数据库迁移 (Migration)？**
    *   **解答**: 使用 Alembic (SQLAlchemy) 管理 Schema 变更。`alembic revision --autogenerate`, `alembic upgrade head`.

98. **Python 内存泄漏如何排查？**
    *   **解答**: 使用 `tracemalloc`, `objgraph`。检查全局变量、循环引用、未关闭的文件句柄。

99. **前端白屏如何排查？**
    *   **解答**: 检查浏览器 Console 报错；检查 Network 请求是否失败；检查路由配置。

100. **系统如何支持高并发 (C10K)？**
    *   **解答**: 负载均衡 (Nginx)；水平扩展 API 实例；数据库读写分离；Redis 缓存热点；CDN 加速前端资源。

---
**祝您面试顺利！**
