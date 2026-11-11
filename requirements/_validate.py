#!/usr/bin/env python3
"""项目理解资料校验器（纯文档校验，不触碰业务代码、不发网络请求、不跑产品用例）。

用法：
    python requirements/_validate.py            # 校验并打印报告
    python requirements/_validate.py --strict   # 有 error 时退出码 1

校验内容：
 1. 每个 JSON 文件可解析。
 2. 目录结构齐全（requirements/specs/cases 三件套 + index + catalog）。
 3. cases/<module>.json 的字段完整性与类型（按模板要求的 24 个字段）。
 4. 跨文件 ID 引用闭合：case.assertion_id / feature_id / requirement_refs / rule_refs /
    flow_refs 必须能在 specs 或 requirements 里解析到。
 5. 唯一性：case_id / assertion_id / feature_id / requirement_id 全局不重复。
 6. 空用例检测：steps 或 expected 为空即 error。
 7. basis / role / readiness / execution_kind / evaluation_mode 取值合法。
 8. 源码锚点格式：形如 `path:123`，path 必须真实存在于工作树。
 9. 禁止出现疑似凭据明文（简单前缀扫描）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQ = ROOT / "requirements"
SPEC = ROOT / "specs"
CASES = ROOT / "cases"

MODULES = [
    "platform", "auth-console", "kb-ingest", "rag-qa",
    "aiops-diagnosis", "aiops-audit", "evaluation",
    "assistant-agent", "storage-queue",
]

BASIS = {"confirmed", "observed", "unresolved", "proposed"}
ROLES = {"functional", "core-flow", "performance", "experience", "product-details"}
READINESS = {"ready", "draft", "retired"}
EXEC_KIND = {"live_ui", "live_api", "live_cli", "static_review", "controlled_fixture"}
EVAL_MODE = {"binary", "graded", "measurement"}

CASE_FIELDS = [
    "case_id", "assertion_id", "feature_id", "role", "basis", "readiness",
    "requirement_refs", "rule_refs", "flow_refs", "applicability",
    "preconditions", "steps", "expected", "evaluation_mode",
    "comparison_dimensions", "evidence", "execution_kind",
    "required_actions", "required_capabilities", "resource_requirements",
    "resource_refs", "dependencies", "timeout_seconds", "readonly_retry_max",
    "cleanup",
]

LIST_FIELDS = {
    "requirement_refs", "rule_refs", "flow_refs", "preconditions", "steps",
    "expected", "comparison_dimensions", "evidence", "required_actions",
    "required_capabilities", "resource_requirements", "resource_refs",
    "dependencies",
}

CRED_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{16,}"), "疑似 API key"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "疑似 GitHub token"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"), "疑似 JWT"),
    (re.compile(r"(?i)(password|passwd|secret_key|api_key)\s*[=:]\s*['\"]?[A-Za-z0-9/+=_\-]{12,}"), "疑似凭据赋值"),
]

ANCHOR = re.compile(r"((?:[\w\-.]+/)+[\w\-.]+\.(?:py|js|vue|json|md|ya?ml|ini|txt|toml|bat|sh|cfg)):(\d+(?:-\d+)?)")

errors: list[str] = []
warns: list[str] = []


def err(m: str) -> None:
    errors.append(m)


def warn(m: str) -> None:
    warns.append(m)


def load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        err(f"[缺失] {p.relative_to(ROOT)}")
    except json.JSONDecodeError as e:
        err(f"[JSON 解析失败] {p.relative_to(ROOT)}: {e}")
    return None


def main() -> int:
    strict = "--strict" in sys.argv

    # 0. 目录与必需文件
    for d in (REQ, SPEC, CASES):
        if not d.is_dir():
            err(f"[缺失目录] {d.relative_to(ROOT)}")
    for f in [
        REQ / "project-card.md", REQ / "overview.md", REQ / "index.json",
        REQ / "sources" / "index.json",
        SPEC / "feature-index.json", SPEC / "questions.md", SPEC / "catalog.json",
    ]:
        if not f.is_file():
            err(f"[缺失文件] {f.relative_to(ROOT)}")

    # 1. 收集所有 JSON
    json_files = sorted(list(REQ.rglob("*.json")) + list(SPEC.rglob("*.json")) + list(CASES.rglob("*.json")))
    parsed = {}
    for p in json_files:
        d = load_json(p)
        if d is not None:
            parsed[p.relative_to(ROOT).as_posix()] = d

    # 2. ID 收集与唯一性
    req_ids, feat_ids, rule_ids, asrt_ids, case_ids, flow_ids = (set() for _ in range(6))

    def add(container: set, value, where: str, kind: str) -> None:
        if not isinstance(value, str) or not value:
            err(f"[{kind} 非字符串] {where}: {value!r}")
            return
        if value in container:
            err(f"[{kind} 重复] {value} @ {where}")
        container.add(value)

    # requirements/index.json
    ri = parsed.get("requirements/index.json")
    if isinstance(ri, dict):
        for item in ri.get("requirements", []):
            add(req_ids, item.get("requirement_id"), "requirements/index.json", "requirement_id")

    # specs/feature-index.json
    fi = parsed.get("specs/feature-index.json")
    if isinstance(fi, dict):
        for item in fi.get("features", []):
            add(feat_ids, item.get("feature_id"), "specs/feature-index.json", "feature_id")
            for r in item.get("requirement_refs") or []:
                if r not in req_ids:
                    err(f"[悬空引用] {item.get('feature_id')} -> requirement {r}")

    # specs/modules/*.md 里的 RULE-*/ASRT-*/FLOW-*
    # RULE 的"定义"是 `### RULE-XXX-NNN 标题`；ASRT 的定义是断言表格里的 `| ASRT-XXX-NNN |` 行。
    # 只统计定义位置：正文里提到编号（例如"ASRT-DIAG-015 刻意留空"）不算定义，
    # 否则会让"悬空断言"检查漏掉真正缺失的断言。
    for p in sorted((SPEC / "modules").glob("*.md")) if (SPEC / "modules").is_dir() else []:
        txt = p.read_text(encoding="utf-8", errors="replace")
        for line in txt.splitlines():
            s = line.strip()
            m = re.match(r"^#{2,4}\s+(RULE-[A-Z]+-\d{3})\b", s)
            if m:
                rule_ids.add(m.group(1))
            m = re.match(r"^\|\s*(ASRT-[A-Z]+-\d{3})\s*\|", s)
            if m:
                asrt_ids.add(m.group(1))
        for m in re.finditer(r"\bFLOW-[A-Z][A-Z-]*[A-Z]\b", txt):
            flow_ids.add(m.group(0))

    # 3. cases 校验
    total_cases = 0
    per_module: dict[str, int] = {}
    for mod in MODULES:
        p = CASES / f"{mod}.json"
        if not p.is_file():
            err(f"[缺失用例] cases/{mod}.json")
            continue
        doc = parsed.get(f"cases/{mod}.json")
        if not isinstance(doc, dict):
            continue
        if doc.get("module_id") != mod:
            err(f"[module_id 不符] cases/{mod}.json: {doc.get('module_id')!r}")
        if not isinstance(doc.get("baseline_commit"), str) or len(doc["baseline_commit"]) != 40:
            err(f"[baseline_commit 缺失/非40位] cases/{mod}.json")
        cases = doc.get("cases")
        if not isinstance(cases, list) or not cases:
            err(f"[无用例] cases/{mod}.json")
            continue
        per_module[mod] = len(cases)
        for c in cases:
            total_cases += 1
            cid = c.get("case_id", "<no-id>")
            where = f"cases/{mod}.json#{cid}"
            missing = [f for f in CASE_FIELDS if f not in c]
            if missing:
                err(f"[字段缺失] {where}: {', '.join(missing)}")
            extra = [f for f in c if f not in CASE_FIELDS]
            if extra:
                warn(f"[多余字段] {where}: {', '.join(extra)}")
            add(case_ids, c.get("case_id"), where, "case_id")
            aid = c.get("assertion_id")
            if aid and aid not in asrt_ids:
                err(f"[悬空断言] {where} -> {aid}（specs/modules/*.md 里未定义）")
            fid = c.get("feature_id")
            if fid and fid not in feat_ids:
                err(f"[悬空功能] {where} -> {fid}（specs/feature-index.json 里未定义）")
            for r in c.get("requirement_refs") or []:
                if r not in req_ids:
                    err(f"[悬空需求] {where} -> {r}")
            for r in c.get("rule_refs") or []:
                if r not in rule_ids:
                    err(f"[悬空规则] {where} -> {r}")
            for r in c.get("flow_refs") or []:
                if r not in flow_ids:
                    err(f"[悬空流程] {where} -> {r}")
            if c.get("basis") not in BASIS:
                err(f"[basis 非法] {where}: {c.get('basis')!r}")
            if c.get("role") not in ROLES:
                err(f"[role 非法] {where}: {c.get('role')!r}")
            if c.get("readiness") not in READINESS:
                err(f"[readiness 非法] {where}: {c.get('readiness')!r}")
            if c.get("execution_kind") not in EXEC_KIND:
                err(f"[execution_kind 非法] {where}: {c.get('execution_kind')!r}")
            if c.get("evaluation_mode") not in EVAL_MODE:
                err(f"[evaluation_mode 非法] {where}: {c.get('evaluation_mode')!r}")
            for lf in LIST_FIELDS:
                v = c.get(lf)
                if v is not None and not isinstance(v, list):
                    err(f"[类型错误] {where}.{lf} 应为数组")
            if not c.get("steps"):
                err(f"[空用例] {where}: steps 为空")
            if not c.get("expected"):
                err(f"[空用例] {where}: expected 为空")
            if c.get("basis") == "unresolved" and c.get("readiness") != "draft":
                err(f"[依据/完整度矛盾] {where}: unresolved 必须 readiness=draft")
            if not isinstance(c.get("timeout_seconds"), int):
                err(f"[timeout_seconds 非整数] {where}")
            if not isinstance(c.get("readonly_retry_max"), int):
                err(f"[readonly_retry_max 非整数] {where}")
            if not c.get("cleanup"):
                err(f"[缺 cleanup] {where}（无副作用请写 'none'）")

    # 4. 源码锚点存在性
    all_text_files = list(REQ.rglob("*.md")) + list(SPEC.rglob("*.md")) + [p for p in CASES.rglob("*.json")]
    bad_anchor = 0
    for p in all_text_files:
        txt = p.read_text(encoding="utf-8", errors="replace")
        for m in ANCHOR.finditer(txt):
            rel = m.group(1)
            if not (ROOT / rel).exists():
                bad_anchor += 1
                if bad_anchor <= 25:
                    err(f"[锚点路径不存在] {p.relative_to(ROOT)}: {m.group(0)}")
    if bad_anchor > 25:
        err(f"[锚点路径不存在] 另有 {bad_anchor - 25} 处未逐条列出")

    # 5. 凭据明文扫描
    for p in all_text_files:
        txt = p.read_text(encoding="utf-8", errors="replace")
        for pat, label in CRED_PATTERNS:
            for m in pat.finditer(txt):
                err(f"[疑似凭据] {p.relative_to(ROOT)}: {label} -> {m.group(0)[:40]}...")

    # 6. catalog 一致性
    cat = parsed.get("specs/catalog.json")
    if isinstance(cat, dict):
        listed = {m.get("module_id") for m in cat.get("modules", [])}
        for mod in MODULES:
            if mod not in listed:
                err(f"[catalog 缺模块] {mod}")
        for m in cat.get("modules", []):
            mid = m.get("module_id")
            n = per_module.get(mid, 0)
            stated = (m.get("case_stats") or {}).get("total")
            if stated is not None and stated != n:
                err(f"[catalog 用例数不符] {mid}: 声明 {stated}，实际 {n}")

    # 报告
    print("=" * 72)
    print("项目理解资料校验报告")
    print("=" * 72)
    print(f"JSON 文件: {len(parsed)}  用例总数: {total_cases}")
    print(f"需求: {len(req_ids)}  功能: {len(feat_ids)}  规则: {len(rule_ids)}  断言: {len(asrt_ids)}")
    print("按模块用例数: " + ", ".join(f"{k}={v}" for k, v in sorted(per_module.items())))
    print("-" * 72)
    if warns:
        print(f"WARN {len(warns)}")
        for w in warns[:40]:
            print("  !", w)
    if errors:
        print(f"ERROR {len(errors)}")
        for e in errors[:80]:
            print("  x", e)
        if len(errors) > 80:
            print(f"  ... 另有 {len(errors) - 80} 条")
    else:
        print("ERROR 0 —— 全部校验通过")
    print("=" * 72)
    return 1 if (strict and errors) else (0 if not errors else 0)


if __name__ == "__main__":
    sys.exit(main())
