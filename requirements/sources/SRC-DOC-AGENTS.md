# SRC-DOC-AGENTS

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-DOC-AGENTS` |
| 类型 | `doc`（项目文档） |
| 位置 | `AGENTS.md` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:22:00+08:00` |
| 依据等级 | `confirmed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `a8496235bb5322bfd96feccf3707a195ab4d2e95f61292ea84fff400447c607d` |
| 字节数 | 151497 |

## 3. 摘要

项目约定主文档（151KB）。结构：本科毕设目标与执行路线→目标与范围→实施顺序与验收→实验纪律→协作方式→范围与代码入口→Windows 命令→完整实现与验证→工作树与数据保护。正文前 94 行是倒序逐日进展流水，属历史时点，不得当当前验收结论。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/project-card.md §4/§11`

## 5. 反向引用（3 份资料、9 处提及）

- `requirements/overview.md`：L32
- `requirements/project-card.md`：L33, L76, L101, L139, L201, L257
- `specs/questions.md`：L152, L153

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 6. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

