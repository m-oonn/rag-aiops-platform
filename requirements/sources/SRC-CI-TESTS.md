# SRC-CI-TESTS

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-CI-TESTS` |
| 类型 | `ci_config`（CI 配置） |
| 位置 | `.github/workflows/tests.yml` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:24:00+08:00` |
| 依据等级 | `confirmed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `d4d86f4c353a33518ed18568a5007437ac5301b2fb8a361be6da3118cfbc67ad` |
| 字节数 | 2561 |

## 3. 摘要

offline-tests workflow：ubuntu+py3.12；用 sk-ci-placeholder 假凭据跑离线；grep 排除 paddle/datasets/ragas 等重量级依赖；两步门禁——先跑零成本回放门禁 tests/test_recorded_round_replay.py，再跑 pytest -m 'not integration'。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/platform.md`

## 5. 反向引用（10 份资料、39 处提及）

- `cases/aiops-diagnosis.json`：L695, L701, L707, L714
- `cases/platform.json`：L556, L558, L574, L575, L576, L583
- `requirements/index.json`：L434, L435, L436, L437, L438, L439, L443, L1682, L1939
- `requirements/modules/aiops-diagnosis.md`：L375, L379, L646
- `requirements/modules/platform.md`：L244, L247, L248, L249, L262, L319
- `requirements/overview.md`：L54
- `requirements/project-card.md`：L97, L104
- `specs/feature-index.json`：L227
- `specs/modules/aiops-diagnosis.md`：L197, L198, L236
- `specs/modules/platform.md`：L67, L215, L216, L259

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 6. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

