#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""装配论文交付物：由 4 个分册 + 参考文献 + 附录 A/B 合成一份全文。

交付形态（毕业设计/02_论文草稿/）：
    01-引言.md          第 1 章（分册）
    02-原理.md          第 2 章（分册）
    03-改进方法.md       第 3 章（分册）
    04-实验分析.md       第 4 章（分册）
    全文.md             总论文 = 标题 + 目录 + 第 1~4 章 + 参考文献 + 附录 A/B
    figures/            图 1~11（SVG 矢量源 + 2 倍分辨率 PNG）

注意：分册里的插图引用写成相对路径 `figures/图X.png`，故 figures/ 必须与这些 md 同级。

参考文献与附录不在分册中重复维护，而是从源稿抽取：
    参考文献、附录 A  <- docs/thesis/引言-第三版.md
    附录 B（原"附录 A2"）<- docs/thesis/论文正文-第二至四章.md

用法：python scripts/_assemble_thesis.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "thesis"
OUT = ROOT / "毕业设计" / "02_论文草稿"      # 分册、全文.md、figures/ 都在此同级

TITLE = "基于矛盾触发与假设保护的 AIOps 根因诊断 Agent 设计与实现"
SUBTITLE = "全文合并稿"

# 分册顺序（大点顺序即用户所述"第一大点引言、第二大点原理…"）
PARTS = ["01-引言.md", "02-原理.md", "03-改进方法.md", "04-实验分析.md"]

# 源稿中的参考文献与附录
SRC_INTRO = DOCS / "引言-第三版.md"
SRC_MAIN = DOCS / "论文正文-第二至四章.md"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def between(text: str, start: str, end: str | None) -> str:
    """取 [start, end) 区间的文本；end 为 None 时取到文末。"""
    i = text.index(start)
    if end is None:
        return text[i:].rstrip() + "\n"
    j = text.index(end, i)
    return text[i:j].rstrip() + "\n"


def promote(text: str, names: list[str], level: int = 1) -> str:
    """把指定二级标题提升为一级标题，使其与"章"同级。"""
    for name in names:
        text = re.sub(rf"^## ({re.escape(name)})", "# " + r"\1", text, flags=re.M)
    return text


def norm(text: str) -> str:
    """统一图路径与附录编号，并去掉块首尾残留的分隔线。"""
    text = text.replace("](../figures/", "](figures/")   # 分册与全文同在 毕业设计/，插图在同级 figures/
    text = text.replace("](docs/figures/", "](figures/")
    text = text.replace("附录 A2", "附录 B")
    text = re.sub(r"^(?:\s*---\s*\n)+", "", text)   # 去块首分隔线
    text = re.sub(r"\n(?:---\s*\n)+\s*$", "\n", text)  # 去块尾分隔线
    return text


def build_toc(body: str) -> str:
    """由正文标题生成目录（仅取一、二级标题）。"""
    lines = ["## 目录", ""]
    for line in body.split("\n"):
        m = re.match(r"^(#{1,2})\s+(.*?)\s*$", line)
        if not m:
            continue
        level, title = len(m.group(1)), m.group(2)
        title = title.replace("**", "").strip()
        if title in {"目录"}:
            continue
        indent = "" if level == 1 else "  "
        lines.append(f"{indent}- {title}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    missing = [p for p in PARTS if not (OUT / p).exists()]
    if missing:
        raise SystemExit(f"缺少分册文件：{missing}")

    parts = []
    for name in PARTS:
        parts.append(norm(read(OUT / name).rstrip()) + "\n")

    intro = read(SRC_INTRO)
    refs = promote(between(intro, "## 参考文献", "## 附录 A"), ["参考文献"])
    # 去掉源稿中"编号沿用全文统一文献总表…"这类分册专属提示
    refs = re.sub(r"^> 编号沿用.*$", "> 编号按主题分组排列，便于查核；正式定稿时可重排为首次引用顺序。", refs, flags=re.M)
    refs = norm(refs)

    app_a = promote(between(intro, "## 附录 A", None), ["附录 A"])
    app_b = promote(between(read(SRC_MAIN), "## 附录 A2", "## 本稿（第二至四章）写作状态说明"), ["附录 A2"])
    app_b = norm(app_b)
    app_b = app_b.replace("# 附录 B　第二至四章机制参数与代码出处对照表",
                          "# 附录 B　全文机制参数与代码出处对照表")
    app_b = re.sub(r"^> 本表的作用.*$", "> 本附录使正文中每一条机制描述与参数取值均可回溯到具体实现位置。行号为写作时的代码快照，可能随代码演进发生位移；参数**取值**以符号名为准。第 1 章的参数出处见附录 A。", app_b, flags=re.M)

    body = ("\n\n---\n\n".join(s.rstrip() for s in parts + [refs, app_a, app_b])) + "\n"
    body = re.sub(r"\n{3,}", "\n\n", body)

    doc = f"# {TITLE}\n\n**{SUBTITLE}**\n\n---\n\n" + build_toc(body) + "\n---\n\n" + body
    (OUT / "全文.md").write_text(doc, encoding="utf-8", newline="\n")

    # 自检
    checks = {
        "一级标题数": len(re.findall(r"^# ", doc, flags=re.M)),
        "二级标题数": len(re.findall(r"^## ", doc, flags=re.M)),
        "图片引用数（应为 11）": len(re.findall(r"!\[[^\]]*\]\(figures/", doc)),
        "残留旧路径 ../figures/": doc.count("](../figures/"),
        "残留 附录 A2": doc.count("附录 A2"),
        "残留 待补表格占位": doc.count("| [表"),
    }
    print(f"已生成 {OUT / '全文.md'}  （{len(doc)} 字符，{doc.count(chr(10)) + 1} 行）")
    for k, v in checks.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
