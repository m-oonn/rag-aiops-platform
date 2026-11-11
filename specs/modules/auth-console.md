# spec · auth-console（鉴权与前端控制台）

- 模块：`auth-console`，规则前缀 `RULE-AUTH-`，断言前缀 `ASRT-AUTH-`
- 基线提交：`bf789d9e4fff51b7a2c0b661046f9e5c72b6e483`
- 需求依据：`requirements/modules/auth-console.md`（REQ-AUTH-001 ~ REQ-AUTH-008）
- 流程：`FLOW-AUTH`（注册登录与每次请求鉴权）。
- 断言被 `cases/auth-console.json` 的 `assertion_id` 引用。**断言只描述可判定的观察点**，不描述"应该更好"。
- 所有 `source` 均为 `完整相对路径:行号`。本模块规则全部为本轮读源码/测试所得，`basis` 以 `observed` 为主；`confirmed` 只用于有注释或已确认决定写明理由的条目。
- 功能单元：`FEAT-AUTH-001` ~ `FEAT-AUTH-010`，定义见 `### 1.3 功能单元`（ID → 用户视角的一句话 → 入口 → requirement_refs → source）。其中 008/009/010 是同一需求（REQ-AUTH-008 控制台骨架）的三个可分别判定的用户面。
- 待登记 ID（供汇总方补齐）：`FEAT-AUTH-001` ~ `FEAT-AUTH-010` 需写入 `specs/feature-index.json`；`REQ-AUTH-001` ~ `REQ-AUTH-008` 需写入 `requirements/index.json`。两者当前尚不存在。

---

## 1. 交互与接口状态

### 1.1 入口清单（用户动作 → 接口）

| 用户动作 | 页面/元素 | 接口 | 方法 | source |
|---|---|---|---|---|
| 注册 | `/login` 页切换按钮切到注册表单 | `/api/v1/auth/register` | POST | `frontend/src/views/Login.vue:21,44-47`、`src/api/routers/auth.py:40-41` |
| 登录 | `/login` 页提交 | `/api/v1/auth/login/access-token` | POST（表单） | `frontend/src/views/Login.vue:49-55`、`src/api/routers/auth.py:61-63` |
| 退出登录 | 左侧栏底部按钮 | **无后端调用** | — | `frontend/src/App.vue:126-130` |
| 进入内部页面 | 任意 `meta.requiresAuth` 路由 | 前端守卫只判 `localStorage.token` | — | `frontend/src/router/index.js:24-31` |
| 任意受保护请求 | axios 实例 | 自动加 `Authorization: Bearer` | 各业务方法 | `frontend/src/api/index.js:7-13` |
| SSE 流式请求 | `/api/v1/aiops` 等 | `getAuthHeaders()` 手加头 | POST | `frontend/src/utils/sse.js:15` |
| el-upload 上传 | 知识库详情 | 显式计算 Authorization 头 | POST | `frontend/src/views/KnowledgeBaseDetail.vue:268-270` |
| 文件下载 | 监控页 | `/api/v1/storage/download/{name}`（**未带令牌**） | GET | `frontend/src/views/Monitor.vue:306-310` |
| 文件预览 | 监控页 iframe | `/api/v1/storage/preview/{name}`（**未带令牌**） | GET | `frontend/src/views/Monitor.vue:321-329` |
| 删除队列任务 | 监控页 | `/api/v1/monitor/tasks/{task_id}` | DELETE | `frontend/src/views/Monitor.vue:213`、`src/api/routers/monitor.py:108-130` |

### 1.2 关键状态迁移

| 起点 | 触发 | 终点 | source |
|---|---|---|---|
| 无账号 | `POST /register` 成功 | users 新增一行，**前端仍停在注册表单**（不自动登录） | `src/api/routers/auth.py:51-59`、`frontend/src/views/Login.vue:44-47` |
| 已注册 | 登录成功 | `localStorage` 有 `token`+`username`，路由跳 `/dashboard` | `frontend/src/views/Login.vue:52-55` |
| 无 token | 访问 `requiresAuth` 路由 | 重定向 `/login` | `frontend/src/router/index.js:26-27` |
| 有 token（任意非空串） | 访问 `requiresAuth` 路由 | **放行**（不校验内容） | `frontend/src/router/index.js:25-29` |
| 有 token | 任一请求返回 401 | 删 `token`，`window.location.href='/login'` | `frontend/src/api/index.js:15-24`、`frontend/src/utils/auth.js:13-24` |
| token 过期 | 请求受保护端点 | 401 `"Token expired"` | `src/api/dependencies.py:24-28` |
| 账号被停用 | 携旧 token 请求 | 401 `"Could not validate credentials"` | `src/api/dependencies.py:33-36` |
| 点退出登录 | 无请求 | 本地两键删除，界面回登录页；**服务端 token 仍有效** | `frontend/src/App.vue:126-130` |

### 1.3 功能单元（FEAT-AUTH-*，供 `specs/feature-index.json` 与 cases 的 feature_id 解析）

本表把"用户视角的一件事"映射到已写好的需求条目，只做索引，不引入新事实。

| ID | 功能单元（用户视角） | 入口 | requirement_refs | source |
|---|---|---|---|---|
| FEAT-AUTH-001 | 填用户名、邮箱、密码就能建号，密码弱一点当场被挡回来 | `/login` 页切到注册表单 | REQ-AUTH-001 | `frontend/src/views/Login.vue:21,44-47`、`src/api/routers/auth.py:15-59` |
| FEAT-AUTH-002 | 用用户名密码换到一个令牌，拿它能进系统 | `/login` 页提交登录 | REQ-AUTH-002 | `frontend/src/views/Login.vue:49-55`、`src/api/routers/auth.py:61-76` |
| FEAT-AUTH-003 | 令牌被浏览器记住，之后每次请求自动带上，不用反复登录 | 任意页面发请求 | REQ-AUTH-003 | `frontend/src/api/index.js:7-13`、`frontend/src/utils/sse.js:15` |
| FEAT-AUTH-004 | 令牌过期或被停用后，下一次请求就被请回登录页 | 任意受保护接口 | REQ-AUTH-004 | `src/api/dependencies.py:12-37`、`frontend/src/api/index.js:15-24` |
| FEAT-AUTH-005 | 没登录时点内部页面会被弹回登录页 | 任意 `requiresAuth` 路由 | REQ-AUTH-005 | `frontend/src/router/index.js:24-31` |
| FEAT-AUTH-006 | 只能看到自己的知识库、文档、评测任务和诊断记录 | 知识库/文档/评测/存储/AIOps 各页面 | REQ-AUTH-006 | `src/api/routers/evaluation.py:27-41`、`src/api/routers/aiops.py:123-129`、`src/api/routers/storage.py:23-40` |
| FEAT-AUTH-007 | 点退出登录就回到登录页；但系统不提供续期、改密、找回 | 左侧栏底部按钮 | REQ-AUTH-007 | `frontend/src/App.vue:126-130`、`src/api/routers/auth.py:61-76` |
| FEAT-AUTH-008 | 登录页是干净的一屏，进内部页才出现侧栏与顶栏 | `/login` 与任意内部页 | REQ-AUTH-008 | `frontend/src/App.vue:3,56,105` |
| FEAT-AUTH-009 | 侧栏 9 个入口能直接点到各功能页 | 左侧菜单 | REQ-AUTH-008 | `frontend/src/App.vue:11-43` |
| FEAT-AUTH-010 | 首页一进来就看到汇总数字与依赖健康，某项取不到只显示占位符而不是白屏 | `/dashboard` 首屏 | REQ-AUTH-008 | `frontend/src/views/Dashboard.vue:120-173` |

---

## 2. 规则

### RULE-AUTH-001 注册无鉴权，返回体不含任何密码字段
- **要求**：`POST /api/v1/auth/register` 不得声明身份依赖；`response_model=UserOut` 必须只含 `id`、`username`、`email`、`is_active` 四个字段，成功码 201。
- **适用条件**：所有调用方，含未登录访客。
- **可观察**：不携带任何 `Authorization` 头调用成功返回 201；响应 JSON 的键集合恰为上述四项；响应文本中不出现 `password` 与 `password_hash` 字样。
- **source**：`src/api/routers/auth.py:34-41`、`tests/test_auth_functional.py:14-29`
- **requirement_refs**：REQ-AUTH-001　**basis**：observed

### RULE-AUTH-002 注册冲突统一 409 且文案不区分用户名/邮箱
- **要求**：查重必须用 `username == ? OR email == ?` 单次判定；命中时状态码 409、`detail` 恒为"用户名或邮箱已被注册"，两条冲突路径文案逐字相同。
- **适用条件**：username 或 email 任一已存在。
- **可观察**：用"已存在用户名 + 新邮箱"和"新用户名 + 已存在邮箱"各注册一次，两次响应体逐字相同（都是 409 + 同一 detail），无法据此判断是哪一项冲突。
- **source**：`src/api/routers/auth.py:42-50`、`tests/test_auth_functional.py:31-56`
- **requirement_refs**：REQ-AUTH-001　**basis**：observed

### RULE-AUTH-003 密码三项校验：长度 ≥6、含字母、含数字
- **要求**：`password` 必须 `min_length=6`；另有校验器分别拒绝"无字母"与"无数字"，两条错误消息分别为"密码必须包含至少一个字母"与"密码必须包含至少一个数字"。
- **适用条件**：注册请求体。
- **可观察**：提交 5 位密码 → 422；提交纯数字 6 位 → 422 且 detail 含"至少一个字母"；提交纯字母 6 位 → 422 且 detail 含"至少一个数字"；提交"abc123" → 201。前端不做这层校验，故错误只可能来自后端。
- **source**：`src/api/routers/auth.py:18-28`、`tests/test_security.py:102-140`
- **requirement_refs**：REQ-AUTH-001　**basis**：observed

### RULE-AUTH-004 密码以 bcrypt 哈希落库，明文不出现
- **要求**：写入 users 的 `password_hash` 必须来自 `bcrypt.gensalt()` + `bcrypt.hashpw()`；**不得**使用项目依赖里存在但未被引用的 `passlib`。
- **适用条件**：注册写入与登录校验。
- **可观察**：库中 `password_hash` 不等于用户提交的明文；`bcrypt.checkpw(明文, 库值)` 为真；源码中 `src/utils/security.py` 只 import `bcrypt`。
- **source**：`src/utils/security.py:4,14-18`、`tests/test_auth_functional.py:100-103`
- **requirement_refs**：REQ-AUTH-001　**basis**：observed

### RULE-AUTH-005 登录用表单而非 JSON，字段名是 username
- **要求**：登录端点必须接收 `OAuth2PasswordRequestForm`（`application/x-www-form-urlencoded`），按 `username` 查询；不得按 email 查询。
- **适用条件**：`POST /api/v1/auth/login/access-token`。
- **可观察**：以 JSON body 提交返回 422；以表单提交 `username`+`password` 可登录成功；只提供 email 字段的表单不构成有效登录（该字段被忽略，username 缺失 → 422）。
- **注意**：失败文案写的是 email（"Incorrect email or password"），与实现字段不一致，属文案问题，不影响判定。
- **source**：`src/api/routers/auth.py:63-69`、`frontend/src/views/Login.vue:49-52`
- **requirement_refs**：REQ-AUTH-002　**basis**：observed

### RULE-AUTH-006 登录成功返回 bearer token，payload 恰为 exp/sub/iat
- **要求**：成功响应必须为 `{"access_token": ..., "token_type": "bearer"}`；JWT 必须用 `HS256` 与 `settings.SECRET_KEY` 签发，payload 键恰为 `exp`、`sub`（`str(user.id)`）、`iat`，`exp = now + ACCESS_TOKEN_EXPIRE_MINUTES`。
- **适用条件**：凭证校验通过且 `is_active` 为真。
- **可观察**：解码 token 得到三个键；`sub` 等于用户 id 的字符串形式；`exp - iat` 等于 `ACCESS_TOKEN_EXPIRE_MINUTES × 60` 秒（默认 480×60）。
- **source**：`src/api/routers/auth.py:61-76`、`src/utils/security.py:7,20-31`、`src/settings.py:20`、`tests/test_auth_functional.py:58-70`
- **requirement_refs**：REQ-AUTH-002　**basis**：observed

### RULE-AUTH-007 登录失败两种 401，文案不同；停用与密码错可区分
- **要求**：用户不存在或密码错 → 401 "Incorrect email or password"；`is_active` 为假 → 401 "Inactive user"。两者不得合并成同一文案。
- **适用条件**：登录端点。
- **可观察**：错密码 401 且 detail 为前者；把测试用户 `is_active` 置假后正确密码登录 401 且 detail 为后者。
- **风险**：这意味着攻击者可区分"密码对但账号停用"与"密码错"——比"统一文案"多泄露一位信息，但属现状。
- **source**：`src/api/routers/auth.py:69-71`、`tests/test_auth_functional.py:72-98`
- **requirement_refs**：REQ-AUTH-002　**basis**：observed

### RULE-AUTH-008 全仓唯一限流：登录 5/minute，其它端点不限
- **要求**：`@limiter.limit("5/minute")` 只允许出现在登录端点；其它端点不得添加限流装饰器；限流键为 `get_remote_address`。
- **适用条件**：所有端点。
- **可观察**：全仓 grep `@limiter.limit` 只有一处；同 IP 一分钟内第 6 次登录请求返回 429；任意其它端点高频请求不返回 429。
- **source**：`src/api/routers/auth.py:62`、`src/utils/rate_limit.py:8-9`、`src/main.py:200-202`
- **requirement_refs**：REQ-AUTH-002　**basis**：observed

### RULE-AUTH-009 前端凭据只存 localStorage 的两个键，不落 cookie
- **要求**：登录成功只允许写 `localStorage` 的 `token` 与 `username`；后端不得下发 `Set-Cookie`。
- **适用条件**：登录成功路径与任意响应。
- **可观察**：登录后 `localStorage` 恰有这两个键，`token` 值等于响应里的 `access_token`；登录响应头无 `Set-Cookie`；应用没有创建任何 cookie。
- **风险**：同源脚本可读 token，安全模型依赖"不出现 XSS"；后端未下发 CSP。
- **source**：`frontend/src/views/Login.vue:53-54`、`frontend/src/App.vue:103`、`src/api/routers/auth.py:61-76`
- **requirement_refs**：REQ-AUTH-003　**basis**：observed

### RULE-AUTH-010 axios 侧统一加 Authorization 头
- **要求**：axios 实例 `baseURL` 必须为 `/api/v1`；请求拦截器必须在存在 `localStorage.token` 时给每个请求加 `Authorization: Bearer <token>`；未登录时不得加该头（也不得报错）。
- **适用条件**：所有经该实例的请求。
- **可观察**：有 token 时拦截器产出的 config 头含该字段且值前缀为 `Bearer `；无 token 时该字段不存在。
- **source**：`frontend/src/api/index.js:3-13`
- **requirement_refs**：REQ-AUTH-003　**basis**：observed

### RULE-AUTH-011 非 axios 路径必须自己带令牌，401 处理与 axios 一致
- **要求**：`getAuthHeaders()` 必须在存在 token 时返回含 `Authorization` 的对象；`handleAuthError(status)` 在 401 时必须删 `localStorage.token`、跳 `/login` 并返回 `true`，非 401 必须返回 `false` 且不动 token、不跳转。
- **适用条件**：SSE 流式请求、上传、下载、预览等 native fetch 场景。
- **可观察**：`frontend/src/utils/auth.test.js` 的九条断言；401 调用后 `removeItem('token')` 被调用且 `window.location.href === '/login'`；500 调用后两者都不发生。
- **注意**：**下载与预览两处违反了本规则的前半段**——见 RULE-AUTH-017。
- **source**：`frontend/src/utils/auth.js:4-36`、`frontend/src/utils/sse.js:15`、`frontend/src/utils/auth.test.js:22-107`
- **requirement_refs**：REQ-AUTH-003　**basis**：observed

### RULE-AUTH-012 401 一律清 token 并回登录页（两条链路同行为）
- **要求**：axios 响应拦截器在 `status === 401` 时必须 `localStorage.removeItem('token')` 并 `window.location.href = '/login'`；native fetch 链路必须由 `handleAuthError` 完成同样动作。
- **适用条件**：任何 401 响应。
- **可观察**：手工置一个无效 token 后访问任一受保护页面，首先触发一次 401，随后被重定向到 `/login`，且 `localStorage.token` 已被删除。
- **source**：`frontend/src/api/index.js:15-24`、`frontend/src/utils/auth.js:13-24`
- **requirement_refs**：REQ-AUTH-003、REQ-AUTH-005　**basis**：observed

### RULE-AUTH-013 后端每次请求重验：HS256 验签 + 查库 + is_active
- **要求**：`get_current_user` 必须 `jwt.decode(token, SECRET_KEY, algorithms=["HS256"])`，用 `sub` 转 int 查 users，用户不存在或 `is_active` 为假都返回 401。
- **适用条件**：所有 `Depends(get_current_user)` 的端点。
- **可观察**：篡改 token 一个字符 → 401 "Could not validate credentials"；用别的密钥签的 token → 同；过期 token → 401 "Token expired"；把用户 `is_active` 置假后携原 token → 401 "Could not validate credentials"。
- **注意**：停用与伪造在响应上不可区分（同文案），这是有意收敛。
- **source**：`src/api/dependencies.py:10-36`、`tests/test_security.py:13-58`
- **requirement_refs**：REQ-AUTH-004　**basis**：observed

### RULE-AUTH-014 无 token 访问受保护端点直接 401，不进业务代码
- **要求**：受保护端点在不带 `Authorization` 时必须由 `OAuth2PasswordBearer` 直接拒绝，不得进入端点函数体。
- **适用条件**：所有受保护端点。
- **可观察**：无 token 请求 `GET /api/v1/health/queues` 返回 401（`tests/test_health.py:16-19`）；无 token 请求 AIOps 诊断端点返回 401（`tests/test_aiops_auth.py:12`）。
- **source**：`src/api/dependencies.py:10-15`、`tests/test_health.py:16-19`、`tests/test_aiops_auth.py:12`
- **requirement_refs**：REQ-AUTH-004　**basis**：observed

### RULE-AUTH-015 前端守卫只判 token 存在，不验有效性
- **要求**：`router.beforeEach` 只允许读 `localStorage.getItem('token')` 做存在性判断；不得解析 JWT、不得检查 `exp`、不得发校验请求。
- **适用条件**：每次路由切换。
- **可观察**：手工把 `localStorage.token` 设为任意非空字符串（如 `"x"`），访问 `/dashboard` **不被重定向**；清空 token 后访问同一路径被重定向到 `/login`；`/login` 自身无论有无 token 都可访问。
- **source**：`frontend/src/router/index.js:24-31`
- **requirement_refs**：REQ-AUTH-005　**basis**：observed

### RULE-AUTH-016 12 条路由中 10 条页面标记 requiresAuth
- **要求**：路由表必须恰为"1 条重定向 + `/login` + 10 条 `requiresAuth` 页面"，全部用 `() => import(...)` 懒加载；**不得**存在 `/register` 路由。
- **适用条件**：应用启动。
- **可观察**：`router.getRoutes()` 计数 12（含 `/` 重定向）；10 条带 `meta.requiresAuth === true`；`/login` 无该 meta；`router.resolve('/register')` 匹配不到已定义路由（落到未匹配状态，而 `frontend/src/App.vue:105` 仍判定该路径）。
- **source**：`frontend/src/router/index.js:4-17`、`frontend/src/App.vue:105`
- **requirement_refs**：REQ-AUTH-005、REQ-AUTH-008　**basis**：observed

### RULE-AUTH-017 监控页下载与预览不带 Authorization（现状缺口）
- **要求（现状描述）**：`downloadFile` 用 `window.open` 直连 `/api/v1/storage/download/{name}`，`viewFile` 把 iframe `src` 设为 `/api/v1/storage/preview/{name}`，**两处都不带 `Authorization` 头**；而后端这两个端点都要求 `Depends(get_current_user)`。
- **适用条件**：登录用户在监控页点"下载"或"预览"。
- **可观察**：这两个请求在浏览器网络面板中无 `Authorization` 请求头，后端返回 **401**；用户看到新窗口/iframe 里是 401 的 JSON，或空白。
- **反例（正确做法，代码里已有）**：`frontend/src/views/KnowledgeBaseDetail.vue:268-270` 的 el-upload 显式计算了 `Bearer` 头。
- **source**：`frontend/src/views/Monitor.vue:306-310,321-329`、`src/api/routers/storage.py:62-63,98-99`、`frontend/src/views/KnowledgeBaseDetail.vue:268-270`
- **requirement_refs**：REQ-AUTH-008　**basis**：observed

### RULE-AUTH-018 监控页删除任务传 task_id，后端强制 int
- **要求（现状描述）**：前端 `DELETE /api/v1/monitor/tasks/{row.task_id}` 与批量删除都传 `task_id` 字符串；后端把该值 `int(task_id)`，失败即 400 "Invalid ID format"。
- **适用条件**：监控页删除/批量删除队列条目。
- **可观察**：若 `task_id` 为非数字串（如 UUID），删除请求返回 400 且 detail 为 "Invalid ID format"；若为数字串则进入后续 owner 校验（404 "Task/Document not found" 或 403 "Not authorized"）。
- **注意**：后端注释自称"把 task_id 宽松映射作 doc_id"，字段语义未与前端对齐。
- **source**：`frontend/src/views/Monitor.vue:213,225-226`、`src/api/routers/monitor.py:108-127`
- **requirement_refs**：REQ-AUTH-008　**basis**：observed

### RULE-AUTH-019 知识库/文档删除按 kb.owner_id 判定，非所有者 403
- **要求**：删除文档必须先查 `KnowledgeDocument`，再查所属 kb 并比较 `kb.owner_id != current_user.id` → 403 "Not authorized"。
- **适用条件**：`DELETE /api/v1/monitor/tasks/{task_id}`。
- **可观察**：用户 A 删除用户 B 知识库下的文档返回 403 且 detail 为 "Not authorized"；所有者删除返回成功。
- **source**：`src/api/routers/monitor.py:121-130`
- **requirement_refs**：REQ-AUTH-006　**basis**：observed

### RULE-AUTH-020 评测任务双重所有权：有 kb 看 kb.owner_id，无 kb 看 created_by
- **要求**：`_check_task_ownership` 必须按 `task.kb_id` 是否为空分两支：非空则查 kb 比较 `owner_id`，为空则比较 `task.created_by`；列表查询必须同口径过滤。
- **适用条件**：评测任务的读/写/删操作（8 个调用点）与列表查询。
- **可观察**：用户 A 访问用户 B 的评测任务返回 403（detail 按调用点不同，含"无权操作该知识库"）；用户 A 的 `GET /api/v1/evaluations/tasks` 结果中不出现 `created_by` 为 B 的任务。
- **source**：`src/api/routers/evaluation.py:27-41,294,347,397,414,429,449,471,495-496,511,524`
- **requirement_refs**：REQ-AUTH-006　**basis**：observed

### RULE-AUTH-021 对象存储按 user_{id}/ 前缀隔离，越权前缀被剥离
- **要求**：`_safe_object_name` 必须先删除所有 `..`、剥掉前导 `/`，若已带自己的 `user_{id}/` 前缀则原样使用，若带他人 `user_` 前缀则剥掉后重新拼自己的前缀；`GET /files` 必须忽略前端传入的 prefix。
- **适用条件**：`storage` 的全部对象名入口（列表/下载/预览/上传/批删/预签名）。
- **可观察**：传 `user_99/secret.pdf` 得到的实际名称以 `user_{自己id}/` 开头且不含 `user_99`；传 `../../etc/passwd` 得到的名称不含 `..`；`GET /files?prefix=user_99/` 返回的仍是自己命名空间的内容。
- **source**：`src/api/routers/storage.py:18-55`、`tests/test_storage_security.py:32-100`
- **requirement_refs**：REQ-AUTH-006　**basis**：observed

### RULE-AUTH-022 AIOps 诊断按 run.user_id 隔离，越权返回 404 而非 403
- **要求**：`_owned_run` 必须先正则校验 `thread_id`（`[A-Za-z0-9_.-]{1,64}`，不符 400 "thread_id 非法"），再对"run 不存在"与"run 不属于自己"统一返回 404 "诊断不存在"。
- **适用条件**：所有 `/api/v1/aiops/runs/{thread_id}` 系列端点。
- **可观察**：用户 A 请求用户 B 的 thread_id 得到 404 且 detail 为 "诊断不存在"（与不存在的 thread_id 完全一致，无法探测存在性）；含非法字符的 thread_id 得到 400。
- **source**：`src/api/routers/aiops.py:123-129,132,146,169,184,193`
- **requirement_refs**：REQ-AUTH-006　**basis**：observed

### RULE-AUTH-023 原始证据读取按 role 分档，非审计员看不到 raw_ref
- **要求**：`can_read_raw` 必须由 `role in {"admin","auditor"}` 计算；单条证据对非审计员必须 `pop("raw_ref")`。
- **适用条件**：`GET /runs/{thread_id}/evidence` 与 `/evidence/{evidence_id}`。
- **可观察**：`role` 为默认 `"user"` 的用户，前者的 `can_read_raw` 为 `false`，后者响应体不含 `raw_ref` 键；把库里 role 改为 `auditor` 后两者行为反转。
- **注意**：系统内**没有任何接口或代码路径把 role 设为 admin/auditor**，所以该能力实际只对直接改库者可达。
- **source**：`src/api/routers/aiops.py:184-190,193-205`、`src/database/models.py:7-22`
- **requirement_refs**：REQ-AUTH-006　**basis**：observed

### RULE-AUTH-024 后端不存在登出/续期/改密/找回端点
- **要求**：`src/api/routers/auth.py` 只允许存在 `/register` 与 `/login/access-token` 两个路由；不得出现 `/logout`、`/refresh`、`/me`、`/change-password`、`/reset-password`。
- **适用条件**：任何调用方。
- **可观察**：对 `/api/v1/auth/logout`、`/api/v1/auth/refresh`、`/api/v1/auth/me` 的任意方法请求均 404 或 405（因无路由）；`src/utils/security.py` 只有一个签发函数，无 refresh 逻辑。
- **source**：`src/api/routers/auth.py:40,61`、`src/utils/security.py:20-31`、`src/api/dependencies.py:10-36`
- **requirement_refs**：REQ-AUTH-007　**basis**：observed

### RULE-AUTH-025 前端退出登录只清本地两键，不发请求
- **要求**：`logout()` 必须只做三件事：删 `token`、删 `username`、`router.push('/login')`；不得调用任何后端接口。
- **适用条件**：点"退出登录"。
- **可观察**：点击后浏览器网络面板**无任何请求**；`localStorage` 两键消失；地址变为 `/login`；用退出前的 token 手工发请求**仍然有效**（直到 `exp`）。
- **source**：`frontend/src/App.vue:126-130`
- **requirement_refs**：REQ-AUTH-007　**basis**：observed

### RULE-AUTH-026 控制台外壳：登录页隐藏侧栏与顶栏，导航恰 9 项
- **要求**：侧栏与顶栏必须由 `v-if="!isLoginPage"` 控制；导航必须恰好 9 项（仪表盘、会话、知识库、助手、AIOps 诊断、监控、队列监控、评测，加"退出登录"按钮不计入菜单项）；`isLoginPage` 判定 `/login` 与 `/register` 两条路径。
- **适用条件**：任意路由。
- **可观察**：`/dashboard` 下左侧有 9 个中文导航文案且无英文原词；`/login` 下侧栏与顶栏都不渲染；`App.vue` 中 `/register` 分支存在但路由表无该路径。
- **source**：`frontend/src/App.vue:3,11-43,56,105`、`frontend/src/router/index.js:4-17`、`frontend/src/App.test.js:1-29`
- **requirement_refs**：REQ-AUTH-008　**basis**：observed

### RULE-AUTH-027 控制台首屏四个数据源失败即降级为占位符，不阻断渲染
- **要求**：`loadStats()` 必须分别请求知识库列表、前 10 个知识库的文档、`/monitor/stats`、`/evaluations/tasks`，任一失败把对应指标置为 `'—'` 而不是抛出；`loadDeps()` 失败置"检测失败"。
- **适用条件**：进入 `/dashboard`。
- **可观察**：断掉后端后打开仪表盘，页面仍渲染，四个指标显示 `—`，依赖面板显示"检测失败"；后端恢复后刷新各指标恢复真实值。
- **source**：`frontend/src/views/Dashboard.vue:105-113,120-173`
- **requirement_refs**：REQ-AUTH-008　**basis**：observed

---

## 3. 断言

| ID | 断言（可判定） | 关联规则 | requirement_refs | basis |
|---|---|---|---|---|
| ASRT-AUTH-001 | 不携带任何 `Authorization` 头调用 `POST /api/v1/auth/register`（合法 username/email/password）返回 **201**，响应键集合恰为 `id`、`username`、`email`、`is_active`，文本中不含 `password` 与 `password_hash` | RULE-AUTH-001 | REQ-AUTH-001 | observed |
| ASRT-AUTH-002 | 用已存在用户名 + 新邮箱注册，与用新用户名 + 已存在邮箱注册，两次都为 **409** 且响应体逐字相同（含同一 detail 文案），无法区分冲突项 | RULE-AUTH-002 | REQ-AUTH-001 | observed |
| ASRT-AUTH-003 | 提交 5 位密码返回 **422**；提交 6 位纯数字返回 422 且 detail 含"至少一个字母"；提交 6 位纯字母返回 422 且 detail 含"至少一个数字"；提交同时含字母与数字的 6 位密码返回 201 | RULE-AUTH-003 | REQ-AUTH-001 | observed |
| ASRT-AUTH-004 | 注册后从 `users` 表读 `password_hash`，其值不等于提交的明文，且 `bcrypt.checkpw(明文, 该值)` 为真 | RULE-AUTH-004 | REQ-AUTH-001 | observed |
| ASRT-AUTH-005 | 以 JSON body 调用登录端点返回 **422**；以表单传 `username`+`password` 返回 **200** | RULE-AUTH-005 | REQ-AUTH-002 | observed |
| ASRT-AUTH-006 | 登录响应为 `token_type` 等于 `bearer`，`access_token` 解码后键集合恰为 `exp`/`sub`/`iat`，`sub` 等于 `str(用户id)`，`exp - iat` 等于 480×60 秒 | RULE-AUTH-006 | REQ-AUTH-002 | observed |
| ASRT-AUTH-007 | 错误密码登录返回 **401** 且 detail 为 `Incorrect email or password`；把该用户 `is_active` 置假后用正确密码登录返回 **401** 且 detail 为 `Inactive user` | RULE-AUTH-007 | REQ-AUTH-002 | observed |
| ASRT-AUTH-008 | 同一客户端 IP 连续 6 次登录失败，前 5 次 **401**、第 6 次 **429**；同时段对 `GET /api/v1/health/health` 连续 10 次均为 **200** | RULE-AUTH-008 | REQ-AUTH-002 | observed |
| ASRT-AUTH-009 | 登录成功后 `localStorage` 恰有 `token` 与 `username` 两键，`token` 等于响应里的 `access_token`；登录响应头不含 `Set-Cookie` | RULE-AUTH-009 | REQ-AUTH-003 | observed |
| ASRT-AUTH-010 | 存在 `localStorage.token` 时，axios 请求拦截器产出的 config 头含 `Authorization` 且值以 `Bearer ` 开头；无 token 时该头不存在 | RULE-AUTH-010 | REQ-AUTH-003 | observed |
| ASRT-AUTH-011 | `handleAuthError(401)` 返回 `true`，`localStorage.removeItem('token')` 被调用一次，`window.location.href` 变为 `/login`；`handleAuthError(500)` 返回 `false`，token 未被删除且 `location.href` 未变 | RULE-AUTH-011、RULE-AUTH-012 | REQ-AUTH-003 | observed |
| ASRT-AUTH-012 | 往 `localStorage` 写入一个无效字符串作为 token 后访问受保护页面：前端守卫放行，随后接口返回 **401**，最终地址变为 `/login` 且 `localStorage.token` 已被删除 | RULE-AUTH-012、RULE-AUTH-015 | REQ-AUTH-003、REQ-AUTH-005 | observed |
| ASRT-AUTH-013 | 篡改 token 任一位 → 401 且 detail 为 `Could not validate credentials`；用别于 `SECRET_KEY` 的密钥签发的 token → 同；过期 token → 401 且 detail 为 `Token expired`；把用户 `is_active` 置假后携原 token → 401 且 detail 为 `Could not validate credentials` | RULE-AUTH-013 | REQ-AUTH-004 | observed |
| ASRT-AUTH-014 | 不带 `Authorization` 请求 `GET /api/v1/health/queues` 与任一 `/api/v1/aiops/runs/{thread_id}` 端点，均返回 **401** | RULE-AUTH-014 | REQ-AUTH-004 | observed |
| ASRT-AUTH-015 | 把 `localStorage.token` 设为任意非空串（如单字符）后访问 `/dashboard` **不发生重定向**；清空该键后访问同一路径被重定向到 `/login` | RULE-AUTH-015 | REQ-AUTH-005 | observed |
| ASRT-AUTH-016 | 路由表共 12 条（含 `/` 重定向与 `/login`），其中 10 条 `meta.requiresAuth === true`，`/login` 无该 meta；`/register` 不是已定义路由 | RULE-AUTH-016 | REQ-AUTH-005、REQ-AUTH-008 | observed |
| ASRT-AUTH-017 | 在监控页触发下载与预览，浏览器网络面板中这两个请求**无** `Authorization` 请求头，后端分别返回 **401** | RULE-AUTH-017 | REQ-AUTH-008 | observed |
| ASRT-AUTH-018 | 用非数字 `task_id` 调 `DELETE /api/v1/monitor/tasks/{task_id}` 返回 **400** 且 detail 为 `Invalid ID format` | RULE-AUTH-018 | REQ-AUTH-008 | observed |
| ASRT-AUTH-019 | 用户 A 删除用户 B 知识库下的文档返回 **403** 且 detail 为 `Not authorized`；所有者删除同一文档成功 | RULE-AUTH-019 | REQ-AUTH-006 | observed |
| ASRT-AUTH-020 | 用户 A 访问用户 B 的评测任务返回 **403**；`GET /api/v1/evaluations/tasks` 的结果中不出现 `created_by` 为 B 的任务 | RULE-AUTH-020 | REQ-AUTH-006 | observed |
| ASRT-AUTH-021 | 传 `user_99/secret.pdf` 经 `_safe_object_name` 处理后以自己 `user_{id}/` 开头且不含 `user_99`；传含 `..` 的名称处理后不含 `..`；`GET /api/v1/storage/files?prefix=user_99/` 返回的条目仍属自己命名空间 | RULE-AUTH-021 | REQ-AUTH-006 | observed |
| ASRT-AUTH-022 | 用户 A 请求用户 B 的 thread_id 返回 **404** 且 detail 为 `诊断不存在`（与不存在的 thread_id 响应完全一致）；含非法字符的 thread_id 返回 **400** 且 detail 为 `thread_id 非法` | RULE-AUTH-022 | REQ-AUTH-006 | observed |
| ASRT-AUTH-023 | 默认 `role="user"` 的用户请求 `/runs/{thread_id}/evidence` 得到 `can_read_raw` 为 `false`；请求 `/evidence/{evidence_id}` 的响应体**不含** `raw_ref` 键 | RULE-AUTH-023 | REQ-AUTH-006 | observed |
| ASRT-AUTH-024 | 对 `/api/v1/auth/logout`、`/api/v1/auth/refresh`、`/api/v1/auth/me` 请求均得到 **404** 或 **405**；`src/api/routers/auth.py` 中 `@router.post` 装饰器恰有 2 处 | RULE-AUTH-024 | REQ-AUTH-007 | observed |
| ASRT-AUTH-025 | 点"退出登录"时浏览器网络面板**无任何请求**；`localStorage` 的 `token` 与 `username` 均消失，地址变为 `/login`；用退出前取得的 token 手工请求受保护端点仍返回 **200** | RULE-AUTH-025 | REQ-AUTH-007 | observed |
| ASRT-AUTH-026 | `/dashboard` 下左侧导航渲染 9 个中文文案且不含 `Dashboard`/`Chat`/`Knowledge Bases`/`Assistants`/`Monitor`/`Evaluation`/`Logout` 任一英文词；`/login` 下侧栏与顶栏均不渲染 | RULE-AUTH-026 | REQ-AUTH-008 | observed |
| ASRT-AUTH-027 | 后端不可达时打开 `/dashboard`，页面仍渲染，四个统计指标显示 `—`，依赖面板显示"检测失败"，控制台无未捕获异常 | RULE-AUTH-027 | REQ-AUTH-008 | observed |

---

## 4. 未决（供 `specs/questions.md` 汇总）

1. **登出是否可以只清本地**：RULE-AUTH-025 是现状；若要"真登出"需 token 黑名单或短有效期，属设计决定。
2. **无 refresh 是否可接受**：480 分钟单窗口、无法续期、过期即重登。
3. **无改密/找回**：用户自助恢复路径为零，是否列入产品范围未定。
4. **token 在 localStorage 的 XSS 面**：无 HttpOnly 方案，且安全头里**没有 CSP**（对照 `src/main.py:223-230` 只有 4 项）。是否需要 CSP 未定。
5. **越权失败码三种口径**（403 / 404 / 静默改写）是否统一。
6. **`role` 无授予路径**：`admin`/`auditor` 只能改库获得，证据原文读取能力实际不可达。
7. **登录 401 文案写 email、字段是 username**（`src/api/routers/auth.py:69`）：改文案还是改字段口径。
8. **停用与伪造共用同一 401 文案**：与"密码错/用户不存在"共用文案的口径相反，是否统一未定。
9. **`App.vue:105` 的 `/register` 死判定**：删判定还是补路由。
10. **监控页下载/预览必然 401**（RULE-AUTH-017）：改前端用 fetch+blob，还是后端加短期票据，未定。
11. **监控页删除语义错配**（RULE-AUTH-018）：`task_id` 与 `doc_id` 该对齐到哪个。
12. **前端守卫无单测**：`frontend/src/router/index.js:24-31` 三条分支无测试覆盖。
13. **`frontend/src/main.js` 无全局错误处理**（`frontend/src/main.js:14-19`），未捕获的前端异常不会统一上报。
