# SRC-CODE-DEPS

> 单来源登记（由 `runtime/docs-tools/build_sources.py` 从 `requirements/sources/index.json` 生成，生成时间 2026-11-11T10:04:18+08:00）。
> 本文件只登记来源与引用关系，**不复制来源正文**；源码类来源仅登记提交、路径与符号。

## 1. 身份与可用性

| 字段 | 值 |
|---|---|
| `source_id` | `SRC-CODE-DEPS` |
| 类型 | `code`（源码） |
| 位置 | `src/api/dependencies.py` |
| 可用状态 | `available` |
| 采集时间 | `2026-11-11T09:26:00+08:00` |
| 依据等级 | `observed` |

## 2. 版本锚点

| 字段 | 值 |
|---|---|
| 基线提交 | `bf789d9e4fff51b7a2c0b661046f9e5c72b6e483` |
| 正文 SHA-256 | `0cd65c89998a3b65a91059ff1f851b01ddbea3afde49e8b7552aeda98730ed2f` |
| 字节数 | 1497 |

## 3. 摘要

OAuth2PasswordBearer + JWT(HS256) 验签 + is_active 校验；tokenUrl=/api/v1/auth/login/access-token。

## 4. 登记的符号

```
get_current_user
get_current_active_user
```

## 5. 当前材料路径（本来源支撑的资料正文）

- `requirements/modules/platform.md`

## 6. 反向引用（7 份资料、32 处提及）

- `cases/auth-console.json`：L552, L553, L554, L561
- `requirements/index.json`：L585, L586, L587, L588, L589, L590, L594, L672, L728, L2234
- `requirements/modules/aiops-audit.md`：L347
- `requirements/modules/auth-console.md`：L167, L169, L174, L175, L176, L184, L244, L256, L338
- `requirements/overview.md`：L51
- `specs/feature-index.json`：L330
- `specs/modules/auth-console.md`：L40, L41, L53, L158, L165, L238

> 说明：以上是**路径字符串在资料区被提及**的位置，用于反查影响面；提及不等于该处结论一定依赖本来源。

## 7. 维护方式

本文件是**生成物**，不要手工编辑；要改内容请改 `requirements/sources/index.json` 后重跑：

```bat
python runtime\docs-tools\build_sources.py
```

