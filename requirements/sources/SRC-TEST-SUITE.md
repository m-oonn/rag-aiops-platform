# SRC-TEST-SUITE

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-TEST-SUITE` |
| 类型 | `test`（测试资产） |
| 位置 | `tests/` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:22:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `未计算` |

## 3. 摘要

118 个 test_*.py（含 conftest.py）；pytest.ini 设 testpaths=tests、注册 integration marker、addopts='-ra -m not integration'；另有前端 vitest（frontend/vitest.config.js，多页面配套 .test.js 与 329KB 回放 fixture）。

## 4. 当前材料路径（本来源支撑的资料正文）

- `requirements/project-card.md 附缺口 6`

## 5. 反向引用（12 份资料、113 处提及）

- `cases/aiops-diagnosis.json`：L689, L693, L708, L714
- `cases/auth-console.json`：L38, L44, L81, L87, L125, L131, L169, L175, L258, L264, L301, L307 …共 15 处
- `cases/platform.json`：L533, L539, L566
- `requirements/index.json`：L301, L359, L428, L442, L444, L466, L467, L481, L495, L497, L500, L526 …共 31 处
- `requirements/modules/aiops-diagnosis.md`：L205, L375, L646
- `requirements/modules/auth-console.md`：L99, L101, L107, L109, L121, L125, L135, L178, L182, L184, L225, L231 …共 25 处
- `requirements/modules/platform.md`：L122, L134, L173, L183, L249, L258, L260, L262, L319
- `requirements/project-card.md`：L211
- `specs/modules/aiops-diagnosis.md`：L195, L197, L198, L236
- `specs/modules/auth-console.md`：L69, L76, L83, L90, L105, L113, L158, L164, L165, L216
- `specs/modules/platform.md`：L169, L170, L212, L221, L222, L259, L260
- `specs/questions.md`：L38

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 6. 登记备注

本次未运行任何测试（任务边界禁止执行产品用例）。全量口径存在冲突，见 specs/questions.md Q-05。

## 7. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

