"""Planner 节点:制定诊断计划。

流程:
  1. 用 VectorRetriever 查一次知识库,捞相关排查经验(best-effort,查不到不报错);
  2. 加载 MCP 工具(指标/日志)列表,供 LLM 制定计划时参考用哪个工具;
  3. with_structured_output(Plan) 强制 LLM 输出步骤列表。

参考 OnCall app/agent/aiops/planner.py,改用 ChatOpenAI(compatible-mode) + 现有
VectorRetriever(不引 OnCall 的 vector_store_manager)。
"""

import json
import re
from collections import defaultdict
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, List

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.agent.aiops.state import PlanExecuteState
from src.agent.aiops.tools import load_agent_tools
from src.agent.aiops.structured import ainvoke_structured
from src.agent.aiops_llm import create_agent_llm
from src.retrieval.vector_retriever import VectorRetriever
from src.settings import settings
from src.utils.logger import logger

_EXPERIENCE_TOP_K = 3
_RUNBOOKS_DIR = settings.BASE_DIR / "data" / "runbooks"
_KAGGLE_DIR = _RUNBOOKS_DIR / "kaggle"
_HF_DIR = _RUNBOOKS_DIR / "huggingface"
_SKIP_NAMES = {"README.md", "SECURITY.md", "LICENSE", "SUPPORT.md", "CODE_OF_CONDUCT.md"}

# SRE-Navigator 场景: service_type -> service_name 映射,用于把故障类别转可检索文本
_SRE_NAVIGATOR_SCENARIOS: dict[str, str] = {
    "mysql": "Database",
    "database": "Database",
    "postgres": "Database",
    "redis": "Cache",
    "cache": "Cache",
    "memcached": "Cache",
    "frontend": "WebServer",
    "web": "WebServer",
    "nginx": "WebServer",
    "api": "APIGateway",
    "gateway": "APIGateway",
    "auth": "AuthService",
    "login": "AuthService",
    "queue": "QueueWorker",
    "worker": "QueueWorker",
    "payment": "PaymentService",
    "billing": "PaymentService",
    "notification": "NotificationService",
    "email": "NotificationService",
    "s3": "StorageService",
    "storage": "StorageService",
    "cdn": "CDN",
}
_SKIP_DIRS = {".git", "__pycache__", "rca", "main", "camel", "chatdev", "faiss_index_postmortem"}

# Kaggle 数据集配置: label → (路径, 列名映射, 格式)
_KAGGLE_SOURCES: list[dict[str, Any]] = [
    {
        "label": "synthetic-itsm",
        "path": _KAGGLE_DIR / "synthetic-itsm" / "tickets_clean.csv",
        "fmt": "csv",
        "text_cols": ["category", "sub_category", "subject", "description", "resolution"],
    },
    {
        "label": "synthetic-tickets",
        "path": _KAGGLE_DIR / "synthetic-tickets" / "itsm_ticket_corpus.parquet",
        "fmt": "parquet",
        "text_cols": ["root_cause", "resolution", "diagnostics"],
    },
    {
        "label": "root-cause-analysis",
        "path": _KAGGLE_DIR / "root-cause-analysis" / "root_cause_analysis.csv",
        "fmt": "csv",
        "text_cols": ["ROOT_CAUSE"],
    },
]

# 模板占位符: 全文只有骨架没有实操内容,直接跳过
_TEMPLATE_SIGNS = (
    b"<Type of Incident>",
    b"TODO: Expand investigation steps",
)

_BILINGUAL_CATS: dict[str, str] = {
    "configuration": "configuration error",
    "memory": "resource exhaustion",
    "cpu": "performance degradation",
    "disk": "resource exhaustion",
    "network": "network outage",
    "performance": "performance degradation",
    "resource": "resource exhaustion",
    "deployment": "deployment error",
    "security": "security",
    "database": "configuration error",
    "kubernetes": "infrastructure failure",
    "outage": "service outage",
    "software": "software bug",
    "hardware": "hardware failure",
    "cloud": "infrastructure failure",
    "logging": "monitoring",
    "monitoring": "monitoring",
}


def _is_real_playbook(filepath: Path) -> bool:
    """Incident-Playbook 中区分真实 playbook 和空模板。"""
    path_s = str(filepath).replace("\\", "/")
    if "Incident-Playbook" not in path_s:
        return True
    parent = Path(path_s).parent.name.lower()
    gparent = Path(path_s).parent.parent.name.lower()
    if gparent != "mitre-attack" and parent != "mitre-attack":
        return False
    if filepath.name in _SKIP_NAMES:
        return False
    try:
        head = filepath.read_bytes()[:256]
        if any(sig in head for sig in _TEMPLATE_SIGNS):
            return False
    except Exception:
        return False
    return True


def _search_kaggle_csv(path: Path, text_cols: list[str], terms: set[str], limit: int) -> list[str]:
    """逐行搜 CSV,优先取长文本字段(description/resolution 比 title 信息量大)。"""
    import pandas as pd

    results: list[str] = []
    try:
        df = pd.read_csv(path, nrows=5000)
    except Exception:
        return results
    # 长文本列优先
    priority_cols = [c for c in text_cols if c in df.columns if c not in ("subject", "category", "ROOT_CAUSE")]
    for col in priority_cols + [c for c in text_cols if c in df.columns and c not in priority_cols]:
        if col not in df.columns:
            continue
        for _, row in df.head(5000).iterrows():
            cell = str(row[col])
            if any(t in cell.lower() for t in terms):
                snippet = cell.strip()[:250]
                if snippet:
                    label = path.parent.name
                    results.append(f"【Kaggle/{label}】{col}: {snippet}")
                if len(results) >= limit:
                    return results
    return results


def _search_kaggle_parquet(path: Path, text_cols: list[str], terms: set[str], limit: int) -> list[str]:
    """搜 Parquet,优先命中 root_cause/resolution/diagnostics。"""
    import pandas as pd

    results: list[str] = []
    try:
        df = pd.read_parquet(path)
    except Exception:
        return results
    for _, row in df.iterrows():
        for col in text_cols:
            if col not in row.index:
                continue
            cell = str(row[col])
            if any(t in cell.lower() for t in terms):
                rid = row.get("record_id", "?")
                snippet = cell.strip()[:250]
                if snippet:
                    results.append(f"【Kaggle/synthetic-tickets】{col}({rid}): {snippet}")
                if len(results) >= limit:
                    return results
    return results


def _retrieve_hf(query: str, limit: int = 3) -> list[str]:
    """搜索 HuggingFace 数据集(sre-navigator)。按故障类别匹配场景。"""
    results: list[str] = []
    sre_file = _HF_DIR / "sre-navigator" / "train.jsonl"
    if not sre_file.exists():
        return results
    terms = _split_search_terms(query.lower())
    if not terms:
        return results
    # 从 query 推断 service_type
    target_service = ""
    for t in terms:
        if t in _SRE_NAVIGATOR_SCENARIOS:
            target_service = _SRE_NAVIGATOR_SCENARIOS[t]
            break
    try:
        with open(sre_file, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line.strip())
                msgs = rec.get("messages", [])
                content = msgs[0].get("content", "") if msgs else ""
                # 含 target_service 即命中
                if target_service and target_service.lower() not in content.lower():
                    continue
                # 取 assistant 回复中的最终答案
                for m in reversed(msgs):
                    if m.get("role") == "assistant":
                        ans = m.get("content", "").strip()[:200]
                        if ans:
                            results.append(
                                f"【HF/sre-navigator】(难度:{rec.get('difficulty','?')}) {ans}"
                            )
                        break
                if len(results) >= limit:
                    break
    except Exception:
        return results
    return results[:limit]


def _retrieve_kaggle(query: str, limit: int = 3) -> list[str]:
    """搜索 Kaggle 数据集,关键词匹配后返回摘要。"""
    terms = _split_search_terms(query.lower())
    if not terms:
        return []
    results: list[str] = []
    for src in _KAGGLE_SOURCES:
        if not src["path"].exists():
            continue
        if src["fmt"] == "csv":
            hits = _search_kaggle_csv(src["path"], src["text_cols"], terms, limit)
        else:
            hits = _search_kaggle_parquet(src["path"], src["text_cols"], terms, limit)
        results.extend(hits)
        if len(results) >= limit:
            break
    return results[:limit]


def _is_real_playbook(filepath: Path) -> bool:
    """Incident-Playbook 中区分真实 playbook 和空模板。"""
    path_s = str(filepath).replace("\\", "/")
    if "Incident-Playbook" not in path_s:
        return True
    parent = Path(path_s).parent.name.lower()
    gparent = Path(path_s).parent.parent.name.lower()
    if gparent != "mitre-attack" and parent != "mitre-attack":
        return False
    # 跳过 README 和非 playbook 文件
    if filepath.name in ("README.md", "SECURITY.md", "LICENSE", "SUPPORT.md"):
        return False
    # 文件头含模板标记也过滤
    try:
        head = filepath.read_bytes()[:256]
        if any(sig in head for sig in _TEMPLATE_SIGNS):
            return False
    except Exception:
        return False
    return True

# 双向关键词映射: 英文 ↔ 中文别名
# 格式: key -> [别名列表],自动双向扩充
_BILINGUAL: dict[str, list[str]] = {
    "configuration": ["配置", "config", "config错误", "misconfig"],
    "memory": ["内存", "oom", "heap", "leak", "泄漏", "gc"],
    "cpu": ["cpu", "处理器", "processor"],
    "disk": ["磁盘", "空间", "容量", "storage"],
    "network": ["网络", "连接", "networking", "connectivity", "端口", "port", "延迟", "latency", "dns"],
    "performance": ["性能", "慢", "slow", "bottleneck", "timeout", "超时", "latency"],
    "resource": ["资源", "耗尽", "exhaustion", "池", "pool"],
    "deployment": ["部署", "发布", "上线", "deploy", "rollback", "回滚"],
    "security": ["安全", "入侵", "malware", "ddos", "攻击", "漏洞", "breach", "ransomware"],
    "database": ["数据库", "mysql", "postgres", "sql", "连接池", "db", "mongo", "redis"],
    "kubernetes": ["k8s", "pod", "container", "容器", "node", "cluster"],
    "outage": ["中断", "宕机", "不可用", "unavailable", "down"],
    "service": ["服务", "service", "api", "microservice"],
    "software": ["软件", "bug", "defect", "regression", "code"],
    "hardware": ["硬件", "机器", "server", "failure", "disk"],
    "cloud": ["云", "cloud", "aws", "azure", "aliyun", "gcp"],
    "logging": ["日志", "log", "error", "warn", "trace"],
    "monitoring": ["监控", "monitor", "alert", "告警", "metric", "指标"],
}

# 启动时构建 JSONL 倒排索引: {keyword: [filepath, ...]}
_jsonl_index: dict[str, list[Path]] | None = None


def _build_jsonl_index() -> dict[str, list[Path]]:
    """构建 JSONL 文件级关键词倒排索引(只跑一次)。"""
    global _jsonl_index
    if _jsonl_index is not None:
        return _jsonl_index
    idx: dict[str, list[Path]] = defaultdict(list)
    if not _RUNBOOKS_DIR.is_dir():
        _jsonl_index = {}
        return _jsonl_index
    for p in _RUNBOOKS_DIR.rglob("*.jsonl"):
        if p.name.lower() in _SKIP_NAMES:
            continue
        if any(part.name in _SKIP_DIRS for part in p.parents):
            continue
        kw = _extract_cat_keywords(p.name.lower(), str(p.parent).lower())
        for k in kw:
            idx[k].append(p)
        # 也加中文映射
        for k in kw:
            for cn in _BILINGUAL.get(k, []):
                idx[cn].append(p)
    _jsonl_index = dict(idx)
    logger.debug(f"[planner] JSONL 索引构建完成, {len(_jsonl_index)} 关键词")
    return _jsonl_index


def _iter_runbook_files() -> list[Path]:
    """遍历 runbooks 目录下所有可搜索 .md 文件(过滤模板和 boilerplate)。"""
    result: list[Path] = []
    if not _RUNBOOKS_DIR.is_dir():
        return result
    for p in _RUNBOOKS_DIR.rglob("*.md"):
        if p.name in _SKIP_NAMES:
            continue
        if any(part.name in _SKIP_DIRS for part in p.parents):
            continue
        if _is_real_playbook(p):
            result.append(p)
    return result


def _split_search_terms(query_lower: str) -> set[str]:
    """把中英混合 query 拆成独立搜索词 + n-gram + 双向映射词。"""
    terms: set[str] = set()
    # 英文: 按空格和非字母数字切
    eng = re.split(r"[^a-z0-9]+", query_lower)
    terms.update(t for t in eng if len(t) > 2)
    # 中文: 2-4 字滑动窗口
    cn = "".join(c for c in query_lower if "一" <= c <= "鿿")
    for n in (2, 3, 4):
        for i in range(len(cn) - n + 1):
            terms.add(cn[i : i + n])
    # 双向映射扩充
    ext: set[str] = set()
    for t in terms:
        ext.update(_BILINGUAL.get(t, []))
    # 反向: 如果 t 是某个 value 的中文别名,把 key 也加进来
    for key, vals in _BILINGUAL.items():
        if any(v in terms for v in vals):
            ext.add(key)
    terms.update(ext)
    return terms


def _score_file(filepath: Path, query_lower: str) -> float:
    """对单个 .md 文件算关键词命中分(中英文混合匹配)。

    手写 runbook(直接放在 data/runbooks/ 下,非子目录)加权 ×3,优先于外部导入的 playbook。
    """
    stem = filepath.stem.lower().replace("-", " ").replace("_", " ")
    path_s = str(filepath).replace("\\", "/")
    search_pool = f"{stem} {filepath.parent.name.lower()}"
    terms = _split_search_terms(query_lower)
    score = sum(0.5 for t in terms if t in search_pool)
    # 手写文件(不在子目录模板里)加权
    is_handwritten = "/Incident-Playbook/" not in path_s and "/TRAC-RCA/" not in path_s
    if is_handwritten:
        score *= 3.0
    return score


def _extract_cat_keywords(name_lower: str, path_lower: str) -> set[str]:
    """从 JSONL 文件名/路径提取类别关键词(中英双向)。"""
    kw: set[str] = set()
    for token in re.split(r"[_\-\s\.]", name_lower):
        if len(token) > 2 and token not in ("jsonl", "data", "en", "6mtd"):
            kw.add(token)
    for token in re.split(r"[\\/\-]", path_lower):
        if len(token) > 2 and token not in ("jsonl", "data", "runbooks"):
            kw.add(token)
    # 双向扩充: 英文 key → 中文别名,中文 key → 英文别名
    ext: set[str] = set()
    for k in kw:
        ext.update(_BILINGUAL.get(k, []))
    kw.update(ext)
    return kw


def _search_jsonl(filepath: Path, query_lower: str, limit: int) -> list[str]:
    """在单个 JSONL 文件里逐行搜,返回匹配记录的摘要。中英文双检。"""
    results: list[str] = []
    terms = _split_search_terms(query_lower)
    if not terms:
        return results
    try:
        with open(filepath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cat = (rec.get("root_cause_category") or "").lower()
                symptoms = " ".join(rec.get("symptoms") or []).lower()
                pattern = (rec.get("failure_pattern") or "").lower()
                component = (rec.get("component") or "").lower()
                search_text = f"{cat} {symptoms} {pattern} {component}"
                if any(t in search_text for t in terms):
                    results.append(
                        f"根因: {rec.get('root_cause_category')} | "
                        f"症状: {', '.join(rec.get('symptoms', [])[:3])} | "
                        f"修复: {(rec.get('mitigation_principle') or '')[:150]}"
                    )
                    if len(results) >= limit:
                        break
    except Exception:
        pass
    return results


def _content_preview(filepath: Path, max_chars: int = 400) -> str | None:
    """读 .md 文件前 max_chars 作为摘要。"""
    try:
        text = filepath.read_text(encoding="utf-8").strip()
        return text[:max_chars] + ("..." if len(text) > max_chars else "")
    except Exception:
        return None


def _retrieve_local(query: str) -> str:
    """搜索 data/runbooks/ 中所有 .md + .jsonl,关键词匹配后返回 top K 经验。

    优先级: 手写 .md > Incident-Playbook .md > TRAC-RCA JSONL。
    """
    try:
        lower_q = query.lower()
        parts: list[str] = []
        seen: set[str] = set()

        # ── 第一轮: .md 文件名/目录名匹配,手写文件加权优先 ──
        md_scored: list[tuple[float, Path]] = []
        for fp in _iter_runbook_files():
            s = _score_file(fp, lower_q)
            if s > 0:
                md_scored.append((s, fp))
        md_scored.sort(key=lambda x: x[0], reverse=True)

        # 取前 3: 先取手写(不在子目录里),再取其余
        handwritten = [(s, fp) for s, fp in md_scored if "/Incident-Playbook/" not in str(fp)]
        imported = [(s, fp) for s, fp in md_scored if "/Incident-Playbook/" in str(fp)]
        for _, fp in (handwritten + imported)[:_EXPERIENCE_TOP_K]:
            content = _content_preview(fp, max_chars=500)
            if content and content not in seen:
                seen.add(content)
                parts.append(f"【{fp.parent.name}/{fp.stem}】\n{content}")
            if len(parts) >= _EXPERIENCE_TOP_K:
                return _format_experience_block(parts)

        # ── 第二轮: JSONL 倒排索引 → 定向搜 ──
        idx = _build_jsonl_index()
        search_words = [w.strip(",.;:!?\"'") for w in lower_q.split() if len(w.strip(",.;:!?\"'")) > 2]
        for word in search_words:
            for fp in idx.get(word, []):
                hits = _search_jsonl(fp, lower_q, limit=2)
                for h in hits:
                    if h not in seen:
                        seen.add(h)
                        parts.append(f"【TRAC-RCA】{h}")
                if len(parts) >= _EXPERIENCE_TOP_K:
                    return _format_experience_block(parts)

        # ── 第三轮: Kaggle 数据集关键词搜(仅在不足时补充) ──
        if len(parts) < _EXPERIENCE_TOP_K:
            kaggle_hits = _retrieve_kaggle(query, limit=_EXPERIENCE_TOP_K - len(parts))
            for h in kaggle_hits:
                if h not in seen:
                    seen.add(h)
                    parts.append(h)
            if kaggle_hits:
                logger.info(f"[planner] Kaggle 命中 {len(kaggle_hits)} 条")

        # ── 第四轮: HuggingFace 数据集(sre-navigator) ──
        if len(parts) < _EXPERIENCE_TOP_K:
            hf_hits = _retrieve_hf(query, limit=_EXPERIENCE_TOP_K - len(parts))
            for h in hf_hits:
                if h not in seen:
                    seen.add(h)
                    parts.append(h)
            if hf_hits:
                logger.info(f"[planner] HF 命中 {len(hf_hits)} 条")

        # ── 兜底: _BILINGUAL_CATS 推断类别 → 搜 TRAC-RCA JSONL ──
        if not parts:
            search_words = [w.strip(",.;:!?\"'") for w in lower_q.split() if len(w.strip(",.;:!?\"'")) > 2]
            # 第一层: 按类别定向搜
            for jsonl_file in sorted(
                _RUNBOOKS_DIR.rglob("*.jsonl"),
                key=lambda f: f.stat().st_size,
                reverse=True,
            )[:5]:
                found = False
                for kw in search_words:
                    guess_cat = _BILINGUAL_CATS.get(kw)
                    if not guess_cat:
                        continue
                    h = _search_jsonl(jsonl_file, guess_cat, limit=1)
                    if h:
                        for line in h:
                            parts.append(f"【TRAC-RCA/{guess_cat}】{line}")
                        found = True
                        break
                if found:
                    break
            # 第二层: 搜 outage
            if not parts:
                for jsonl_file in sorted(
                    _RUNBOOKS_DIR.rglob("*.jsonl"),
                    key=lambda f: f.stat().st_size,
                    reverse=True,
                )[:2]:
                    h = _search_jsonl(jsonl_file, "outage", limit=1)
                    if h:
                        parts.append(f"【TRAC-RCA (通用)】{h[0]}")
                        break

        return _format_experience_block(parts)
    except Exception:
        logger.debug("[planner] 本地 runbook 搜索跳过,返回空")
        return ""


def _format_experience_block(parts: list[str]) -> str:
    """把多个 experience 片段格式化为 prompt block。"""
    if not parts:
        return ""
    block = "\n\n---\n\n".join(parts)
    logger.info(f"[planner] 本地 runbook 命中 {len(parts)} 条")
    return dedent(
        f"""
        ## 相关排查经验
        以下是从知识库检索到的经验,请参考:
        {block}
        ---
        """
    ).strip()


def _format_tools(tools: list) -> str:
    """把工具列表格式化成 名称: 描述 的多行文本。"""
    if not tools:
        return "(当前无可用工具)"
    return "\n".join(f"- {t.name}: {t.description}" for t in tools)


def _retrieve_experience(query: str) -> str:
    """查知识库捞排查经验。优先 Milvus,不可用时降级本地 runbooks。best-effort。"""
    try:
        retriever = VectorRetriever()
        results = retriever.retrieve(query, top_k=_EXPERIENCE_TOP_K)
        if results:
            parts = [f"【经验 {i}】{r.text}" for i, r in enumerate(results, 1)]
            block = "\n".join(parts)
            return dedent(
                f"""
                ## 相关排查经验
                以下是从知识库检索到的经验,请参考:
                {block}
                ---
                """
            ).strip()
        # Milvus 不可用或无结果 → 降级本地 runbook
        local = _retrieve_local(query)
        if local:
            logger.info("[planner] 降级到本地 runbook 经验")
            return local
        return ""
    except Exception as e:
        logger.warning(f"[planner] 经验检索失败,尝试本地: {e}")
        return _retrieve_local(query)


class Plan(BaseModel):
    """计划输出格式。"""

    steps: List[str] = Field(
        description="完成诊断所需的步骤,按顺序执行,每步说明用哪个工具(若需要)及参数。"
    )


planner_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            dedent(
                """
                你是一个专家级运维诊断规划者,负责把故障诊断任务拆成可执行的步骤。

                可用工具列表(制定计划时参考,实际调用由执行器负责):
                {tools_description}

                {experience_context}

                请为给定任务创建简单、逐步的计划。要求:
                - 每步逻辑独立,明确用哪个工具(如需)及参数;
                - 步骤之间有清晰依赖;
                - 若有相关经验文档,参考其中的排查方法;
                - 步骤要具体可操作,不要空泛。
                """
            ).strip(),
        ),
        ("placeholder", "{messages}"),
    ]
)


async def planner(state: PlanExecuteState) -> Dict[str, Any]:
    """规划节点:据输入生成诊断步骤列表。"""
    logger.info("=== Planner:制定诊断计划 ===")
    input_text = state.get("input", "")

    try:
        experience_context = _retrieve_experience(input_text)
        tools, err = await load_agent_tools()
        if err:
            logger.warning(f"[planner] MCP 工具加载失败: {err}")
        tools_description = _format_tools(tools)

        llm = create_agent_llm(temperature=0)
        result = await ainvoke_structured(llm, Plan, planner_prompt, {
            "messages": [("user", input_text)],
            "tools_description": tools_description,
            "experience_context": experience_context,
        })
        steps = result.steps
        logger.info(f"[planner] 计划已生成,共 {len(steps)} 步")
        return {"plan": steps}

    except Exception:
        logger.exception("[planner] 生成计划失败,用默认计划")
        return {"plan": ["收集相关指标和日志", "分析数据定位问题", "生成诊断报告"]}
