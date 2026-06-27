"""本地 Runbook 经验检索——从 data/runbooks/ 搜索排查经验。

优先级: 手写 .md (×3 权重) > MITRE-ATTACK .md > TRAC-RCA JSONL > Kaggle > HF
所有函数对调用方友好:失败返回空、不抛异常。
"""

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.settings import settings
from src.utils.logger import logger

_EXPERIENCE_TOP_K = 3
_RUNBOOKS_DIR = settings.BASE_DIR / "data" / "runbooks"
_KAGGLE_DIR = _RUNBOOKS_DIR / "kaggle"
_HF_DIR = _RUNBOOKS_DIR / "huggingface"
_SKIP_NAMES = {"README.md", "SECURITY.md", "LICENSE", "SUPPORT.md", "CODE_OF_CONDUCT.md"}
_SKIP_DIRS = {".git", "__pycache__", "rca", "main", "camel", "chatdev", "faiss_index_postmortem"}

_SRE_NAVIGATOR_SCENARIOS: dict[str, str] = {
    "mysql": "Database", "database": "Database", "postgres": "Database",
    "redis": "Cache", "cache": "Cache", "memcached": "Cache",
    "frontend": "WebServer", "web": "WebServer", "nginx": "WebServer",
    "api": "APIGateway", "gateway": "APIGateway",
    "auth": "AuthService", "login": "AuthService",
    "queue": "QueueWorker", "worker": "QueueWorker",
    "payment": "PaymentService", "billing": "PaymentService",
    "notification": "NotificationService", "email": "NotificationService",
    "s3": "StorageService", "storage": "StorageService", "cdn": "CDN",
}

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

_jsonl_index: dict[str, list[Path]] | None = None


# ── 搜索词处理 ──────────────────────────────────────────

def split_search_terms(query_lower: str) -> set[str]:
    """把中英混合 query 拆成独立搜索词 + n-gram + 双向映射词。"""
    terms: set[str] = set()
    eng = re.split(r"[^a-z0-9]+", query_lower)
    terms.update(t for t in eng if len(t) > 2)
    cn = "".join(c for c in query_lower if "一" <= c <= "鿿")
    for n in (2, 3, 4):
        for i in range(len(cn) - n + 1):
            terms.add(cn[i : i + n])
    ext: set[str] = set()
    for t in terms:
        ext.update(_BILINGUAL.get(t, []))
    for key, vals in _BILINGUAL.items():
        if any(v in terms for v in vals):
            ext.add(key)
    terms.update(ext)
    return terms


# ── 文件级过滤 ──────────────────────────────────────────

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


def _score_file(filepath: Path, query_lower: str) -> float:
    """关键词命中分,手写 runbook 加权 ×3。"""
    stem = filepath.stem.lower().replace("-", " ").replace("_", " ")
    path_s = str(filepath).replace("\\", "/")
    search_pool = f"{stem} {filepath.parent.name.lower()}"
    terms = split_search_terms(query_lower)
    score = sum(0.5 for t in terms if t in search_pool)
    is_handwritten = "/Incident-Playbook/" not in path_s and "/TRAC-RCA/" not in path_s
    if is_handwritten:
        score *= 3.0
    return score


def _content_preview(filepath: Path, max_chars: int = 400) -> str | None:
    """读 .md 文件前 max_chars 作为摘要。"""
    try:
        text = filepath.read_text(encoding="utf-8").strip()
        return text[:max_chars] + ("..." if len(text) > max_chars else "")
    except Exception:
        return None


# ── JSONL 索引与搜索 ────────────────────────────────────

def _extract_cat_keywords(name_lower: str, path_lower: str) -> set[str]:
    """从 JSONL 文件名/路径提取类别关键词(中英双向)。"""
    kw: set[str] = set()
    for token in re.split(r"[_\-\s\.]", name_lower):
        if len(token) > 2 and token not in ("jsonl", "data", "en", "6mtd"):
            kw.add(token)
    for token in re.split(r"[\\/\-]", path_lower):
        if len(token) > 2 and token not in ("jsonl", "data", "runbooks"):
            kw.add(token)
    ext: set[str] = set()
    for k in kw:
        ext.update(_BILINGUAL.get(k, []))
    kw.update(ext)
    return kw


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
        for k in kw:
            for cn in _BILINGUAL.get(k, []):
                idx[cn].append(p)
    _jsonl_index = dict(idx)
    logger.debug(f"[planner] JSONL 索引构建完成, {len(_jsonl_index)} 关键词")
    return _jsonl_index


def _search_jsonl(filepath: Path, query_lower: str, limit: int) -> list[str]:
    """在单个 JSONL 文件里逐行搜,返回匹配记录的摘要。"""
    results: list[str] = []
    terms = split_search_terms(query_lower)
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


# ── Kaggle 数据集搜索 ────────────────────────────────────

def _search_kaggle_csv(path: Path, text_cols: list[str], terms: set[str], limit: int) -> list[str]:
    """逐行搜 CSV,长文本字段优先。"""
    import pandas as pd

    results: list[str] = []
    try:
        df = pd.read_csv(path, nrows=5000)
    except Exception:
        return results
    priority_cols = [c for c in text_cols if c in df.columns if c not in ("subject", "category", "ROOT_CAUSE")]
    for col in priority_cols + [c for c in text_cols if c in df.columns and c not in priority_cols]:
        if col not in df.columns:
            continue
        for _, row in df.head(5000).iterrows():
            cell = str(row[col])
            if any(t in cell.lower() for t in terms):
                snippet = cell.strip()[:250]
                if snippet:
                    results.append(f"【Kaggle/{path.parent.name}】{col}: {snippet}")
                if len(results) >= limit:
                    return results
    return results


def _search_kaggle_parquet(path: Path, text_cols: list[str], terms: set[str], limit: int) -> list[str]:
    """搜 Parquet,命中 root_cause/resolution/diagnostics。"""
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


def _retrieve_kaggle(query: str, limit: int = 3) -> list[str]:
    """搜索 Kaggle 数据集。"""
    terms = split_search_terms(query.lower())
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


# ── HuggingFace 数据集搜索 ──────────────────────────────

def _retrieve_hf(query: str, limit: int = 3) -> list[str]:
    """搜索 HuggingFace sre-navigator,按故障类别匹配场景。"""
    results: list[str] = []
    sre_file = _HF_DIR / "sre-navigator" / "train.jsonl"
    if not sre_file.exists():
        return results
    terms = split_search_terms(query.lower())
    if not terms:
        return results
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
                if target_service and target_service.lower() not in content.lower():
                    continue
                for m in reversed(msgs):
                    if m.get("role") == "assistant":
                        ans = m.get("content", "").strip()[:200]
                        if ans:
                            results.append(f"【HF/sre-navigator】(难度:{rec.get('difficulty','?')}) {ans}")
                        break
                if len(results) >= limit:
                    break
    except Exception:
        return results
    return results[:limit]


# ── 公开入口 ─────────────────────────────────────────────

def retrieve_local(query: str) -> str:
    """搜索 data/runbooks/ 中所有数据源,关键词匹配后返回 top K 经验。

    优先级: 手写 .md > Incident-Playbook .md > TRAC-RCA JSONL > Kaggle > HF
    """
    try:
        lower_q = query.lower()
        parts: list[str] = []
        seen: set[str] = set()

        # 第一轮: .md 文件名/目录名匹配,手写文件加权优先
        md_scored: list[tuple[float, Path]] = []
        for fp in _iter_runbook_files():
            s = _score_file(fp, lower_q)
            if s > 0:
                md_scored.append((s, fp))
        md_scored.sort(key=lambda x: x[0], reverse=True)

        handwritten = [(s, fp) for s, fp in md_scored if "/Incident-Playbook/" not in str(fp)]
        imported = [(s, fp) for s, fp in md_scored if "/Incident-Playbook/" in str(fp)]
        for _, fp in (handwritten + imported)[:_EXPERIENCE_TOP_K]:
            content = _content_preview(fp, max_chars=500)
            if content and content not in seen:
                seen.add(content)
                parts.append(f"【{fp.parent.name}/{fp.stem}】\n{content}")
            if len(parts) >= _EXPERIENCE_TOP_K:
                return _format_experience_block(parts)

        # 第二轮: JSONL 倒排索引 → 定向搜
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

        # 第三轮: Kaggle
        if len(parts) < _EXPERIENCE_TOP_K:
            kaggle_hits = _retrieve_kaggle(query, limit=_EXPERIENCE_TOP_K - len(parts))
            for h in kaggle_hits:
                if h not in seen:
                    seen.add(h)
                    parts.append(h)
            if kaggle_hits:
                logger.info(f"[planner] Kaggle 命中 {len(kaggle_hits)} 条")

        # 第四轮: HuggingFace
        if len(parts) < _EXPERIENCE_TOP_K:
            hf_hits = _retrieve_hf(query, limit=_EXPERIENCE_TOP_K - len(parts))
            for h in hf_hits:
                if h not in seen:
                    seen.add(h)
                    parts.append(h)
            if hf_hits:
                logger.info(f"[planner] HF 命中 {len(hf_hits)} 条")

        # 兜底: _BILINGUAL_CATS 推断类别 → 搜 JSONL
        if not parts:
            search_words = [w.strip(",.;:!?\"'") for w in lower_q.split() if len(w.strip(",.;:!?\"'")) > 2]
            for jsonl_file in sorted(
                _RUNBOOKS_DIR.rglob("*.jsonl"), key=lambda f: f.stat().st_size, reverse=True,
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
            if not parts:
                for jsonl_file in sorted(
                    _RUNBOOKS_DIR.rglob("*.jsonl"), key=lambda f: f.stat().st_size, reverse=True,
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
    from textwrap import dedent
    return dedent(
        f"""
        ## 相关排查经验
        以下是从知识库检索到的经验,请参考:
        {block}
        ---
        """
    ).strip()
