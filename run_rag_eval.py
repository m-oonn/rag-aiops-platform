"""快速跑 RAG 4 维评测，输出准确率数字用于简历。

策略:直接调用 RAGEvaluator.evaluate() 跑 8 个手工构造的样本。
"""
import sys
import json
from pathlib import Path

# 把 AIOps 项目根加入 path
AIOPS_ROOT = Path(r"D:\ragPdfSystem++agent")
sys.path.insert(0, str(AIOPS_ROOT))

from src.llm.llm_client import LLMClient
from src.services.evaluator import RAGEvaluator

# 8 个仿真样本:模拟 RAG 检索后的事实性问答(运维/企业知识库场景)
samples = [
    {
        "query": "AIOps 平台的 Agent 核心架构是什么?",
        "answer": "AIOps 平台基于 LangGraph StateGraph 实现诊断 Agent,采用 plan-execute-replan 三阶段工作流,通过 MCP 协议调用 monitor 和 cls 两个自研工具,工具不可用时降级到 LLM 知识分析。",
        "context": [
            {"text": "AIOps 平台使用 LangGraph StateGraph 实现诊断图(planner -> executor -> replanner),通过 fastmcp 自研 monitor(8004) 和 cls(8003) 两个 MCP 工具服务。"},
            {"text": "工具不可用时,系统会自动降级到 LLM 知识分析模式,保证服务的可用性。"},
        ],
        "ground_truth": "基于 LangGraph 的多 Agent 编排,通过 MCP 调用自研工具,带降级机制。",
    },
    {
        "query": "如何处理 FastAPI 中的 CORS 跨域问题?",
        "answer": "使用 fastapi.middleware.cors.CORSMiddleware 配置允许的 origins、methods 和 headers,生产环境应该显式列出 allowed origins,不要用通配符 '*' 配合 credentials。",
        "context": [
            {"text": "FastAPI 通过 CORSMiddleware 处理跨域请求,常用配置: allow_origins、allow_credentials、allow_methods、allow_headers。"},
            {"text": "安全最佳实践:生产环境必须显式配置 ALLOWED_ORIGINS,禁止使用通配符与凭据同时启用。"},
        ],
        "ground_truth": "用 CORSMiddleware 配置,生产环境要显式 origins 不能用通配配 credentials。",
    },
    {
        "query": "RAG 系统的忠实度(faithfulness)如何计算?",
        "answer": "忠实度衡量回答是否完全基于检索到的上下文,通过 LLM-as-judge 方法对回答中的每个声明做'是否能从上下文找到证据'的判断,所有声明的比例即为忠实度分数。",
        "context": [
            {"text": "Faithfulness(忠实度) = 回答中有上下文支持的声明数 / 回答中的总声明数。"},
            {"text": "使用 LLM 作为评判器对每个声明做二分类判断,防止幻觉是核心目标。"},
        ],
        "ground_truth": "通过 LLM 评估回答中每个声明是否有上下文支持,取支持声明数/总声明数。",
    },
    {
        "query": "Python 异步编程中 asyncio.gather 的作用?",
        "answer": "asyncio.gather 用于并发运行多个协程,所有任务完成后返回结果列表,可以提升 I/O 密集型任务的吞吐量。",
        "context": [
            {"text": "asyncio.gather(*aws) 并发运行多个 awaitable 对象,聚合结果。"},
            {"text": "I/O 密集型场景使用 gather 性能提升显著,CPU 密集型不适合。"},
        ],
        "ground_truth": "并发执行多个协程,聚合结果,适合 I/O 密集型。",
    },
    {
        "query": "Milvus 向量数据库和 Chroma 的区别?",
        "answer": "Milvus 是分布式向量数据库,适合大规模生产环境(亿级向量),支持标量过滤、混合检索、多种索引类型;Chroma 是轻量级本地向量库,适合原型开发和小型项目。",
        "context": [
            {"text": "Milvus 分布式架构支持水平扩展,亿级向量毫秒级检索。"},
            {"text": "Chroma 适合本地开发和测试,生产环境推荐 Milvus 或 Qdrant。"},
        ],
        "ground_truth": "Milvus 适合大规模生产,Chroma 适合原型。",
    },
    {
        "query": "LangGraph 的 StateGraph 如何保证 Agent 收敛?",
        "answer": "通过设置 max_iterations 硬限制最大步数、设置 replan 阈值(连续 N 次重规划无进展则停止),以及在节点内做循环检测。",
        "context": [
            {"text": "StateGraph 通过 execution_config 配置 max_iterations 防止无限循环。"},
            {"text": "replan 阈值控制:连续 N 次重规划没有信息增益则强制结束。"},
        ],
        "ground_truth": "硬限制最大步数 + replan 阈值 + 循环检测。",
    },
    {
        "query": "Redis 在 AIOps 中的应用场景?",
        "answer": "Redis 在 AIOps 中主要用于:1) 缓存 LLM 响应(降低 API 调用成本);2) 限流(slowapi 底层用 Redis 存储计数器);3) 会话状态管理;4) 分布式锁。",
        "context": [
            {"text": "Redis 用于缓存 LLM 响应,显著降低 token 成本。"},
            {"text": "slowapi 默认使用 Redis 作为限流后端存储。"},
            {"text": "AIOps 服务用 Redis 管理 MCP 客户端单例缓存。"},
        ],
        "ground_truth": "缓存 LLM 响应、限流、会话管理、分布式锁。",
    },
    {
        "query": "pytest 异步测试如何写?",
        "answer": "使用 pytest-asyncio 插件,测试函数加 @pytest.mark.asyncio 装饰器,conftest 中设置 asyncio_mode = auto 可省略装饰器。",
        "context": [
            {"text": "pytest-asyncio 0.21+ 支持 asyncio_mode = strict / auto。"},
            {"text": "异步 fixture 用 @pytest_asyncio.fixture 装饰。"},
        ],
        "ground_truth": "pytest-asyncio 插件 + @pytest.mark.asyncio 或 auto 模式。",
    },
]


def main():
    llm = LLMClient()
    evaluator = RAGEvaluator(llm)
    results = []
    print(f"开始评测 {len(samples)} 个样本...")
    print("=" * 80)
    for i, s in enumerate(samples, 1):
        print(f"\n[{i}/{len(samples)}] Q: {s['query']}")
        r = evaluator.evaluate(s["query"], s["answer"], s["context"], s.get("ground_truth"))
        if "error" in r:
            print(f"  ❌ 评测失败: {r['error']}")
            continue
        scores = r.get("scores", {})
        print(f"  忠实度: {scores.get('faithfulness')}/10")
        print(f"  相关性: {scores.get('relevancy')}/10")
        print(f"  上下文精度: {scores.get('context_precision')}/10")
        print(f"  准确性: {scores.get('accuracy')}/10")
        print(f"  综合: {r.get('overall_score')}/10")
        results.append(r)
    print("\n" + "=" * 80)
    if not results:
        print("所有样本都失败了,请检查 LLM 客户端配置。")
        return
    n = len(results)
    faith = sum(r["scores"]["faithfulness"] for r in results) / n
    rel = sum(r["scores"]["relevancy"] for r in results) / n
    prec = sum(r["scores"]["context_precision"] for r in results) / n
    acc = sum(r["scores"].get("accuracy", 0) for r in results) / n
    overall = sum(r.get("overall_score", 0) for r in results) / n
    print(f"\n📊 评测汇总({n} 个样本):")
    print(f"  忠实度(Faithfulness):          {faith:.2f} / 10  ({faith*10:.0f}%)")
    print(f"  相关性(Relevancy):             {rel:.2f} / 10  ({rel*10:.0f}%)")
    print(f"  上下文精度(Context Precision): {prec:.2f} / 10  ({prec*10:.0f}%)")
    print(f"  准确性(Accuracy):              {acc:.2f} / 10  ({acc*10:.0f}%)")
    print(f"  综合得分:                      {overall:.2f} / 10  ({overall*10:.0f}%)")
    out_path = Path(r"c:\Users\Administrator\.trae-cn\work\6a46334572ba4a138e850f39\rag_eval_results.json")
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n💾 详细结果已保存到: {out_path}")


if __name__ == "__main__":
    main()
