"""Read Python AST only: never import the app, open a database or call a model."""
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
VERBS = {'get', 'post', 'put', 'patch', 'delete', 'options', 'head', 'api_route', 'websocket', 'route'}
PURPOSE = {
    'health_check': '应用存活检查', 'health_check_legacy': '旧健康路径兼容别名',
    'get_queue_stats': '队列统计（按所在模块区分 Worker 与文档任务）',
    'check_dependencies': '平台依赖可用性；不是被诊断业务健康结论', 'list_models': '可用模型及默认模型',
    'register': '注册账号', 'login_access_token': '登录并签发 JWT', 'read_current_user': '读取当前身份与角色',
    'list_users': '管理员列出用户', 'update_user_role': '管理员修改他人角色',
    'create_knowledge_base': '创建知识库', 'list_knowledge_bases': '列出自己的知识库',
    'delete_knowledge_base': '删除知识库及关联数据', 'get_knowledge_base': '读取知识库',
    'update_knowledge_base': '更新知识库', 'upload_document': '上传文档并安排入库',
    'batch_retry_documents': '批量重试文档入库', 'batch_delete_documents': '批量删除文档',
    'retry_document': '重试单份文档', 'list_documents': '列出库内文档',
    'search_local_knowledge': '本地 BM25 知识检索（仅 bm25 库）',
    'generate_qa_for_document': '调用模型生成问答对', 'create_qa_pair': '手工创建问答对',
    'update_qa_pair': '修改问答对', 'delete_qa_pair': '删除问答对', 'download_qa_pairs': '下载问答对',
    'get_document_chunks': '读取文档分块', 'reprocess_document': '修改切分设置并重新入库',
    'preview_document': '预览原始文档', 'get_document_qa_pairs': '读取文档问答对',
    'create_assistant': '创建通用会话助手', 'list_assistants': '列出通用助手',
    'get_assistant': '读取助手', 'update_assistant': '更新助手', 'delete_assistant': '删除助手',
    'create_assistant_version': '保存助手版本', 'list_assistant_versions': '列出助手版本',
    'create_agent': '创建通用 Agent', 'list_agents': '列出通用 Agent', 'get_agent': '读取通用 Agent',
    'update_agent': '更新通用 Agent', 'delete_agent': '删除通用 Agent', 'execute_agent': '执行通用工具调用 Agent',
    'get_queue_status': '自己的文档入库任务列表', 'delete_task': '删除文档任务对应数据库记录（task_id 实为 doc_id）',
    'batch_delete_tasks': '批量删除任务（所在模块分别为文档/评测）',
    'list_files': '列出自己命名空间的对象文件', 'download_file': '下载对象文件',
    'preview_file': '预览对象文件', 'upload_file': '上传文件（知识入库与对象存储按模块区分）',
    'batch_delete_files': '批量删除对象文件', 'get_file_url': '获取文件预签名地址',
    'chat': '同步知识问答', 'chat_stream': '纯聊天流（不支持带知识库/助手的 RAG）',
    'create_session': '预建通用会话', 'list_sessions': '列出聊天会话（不是诊断记录）',
    'get_session_messages': '读取聊天记录', 'delete_session': '删除聊天会话', 'batch_delete_sessions': '批量删除聊天会话',
    'diagnose_stream': '启动 AIOps 诊断；POST 返回 SSE', 'get_run_status': '按 thread_id 恢复诊断与结构化结果',
    'continue_run': '核验 Termcp 审批后续跑；不是任意诊断重试', 'get_run_steps': '可选步快照；关闭时允许为空',
    'get_run_evidence': '当前诊断证据台账（脱敏）', 'get_run_evidence_item': '证据详情（原始字段按角色控制）',
    'get_probe_target_status': '读取唯一配置目标的 Probe 登记状态',
    'generate_evaluation_dataset': '创建知识问答评测任务并按配置生成题集',
    'upload_evaluation_dataset': '上传 JSON/CSV/XLSX 问答题集', 'run_evaluation': '运行 RAG 问答评测',
    'get_dataset_items': '读取评测题集', 'update_dataset_item': '更新评测题目', 'delete_dataset_item': '删除评测题目',
    'list_evaluation_tasks': '列出知识问答评测任务', 'get_evaluation_status': '读取问答评测任务状态',
    'get_evaluation_report': '读取问答评测报告（不是 AIOps 实验结果）', 'get_task_status': '读取 Celery 任务状态',
}

def expr(node):
    return ast.unparse(node) if node is not None else None

def parse(path):
    raw = path.read_bytes()
    return ast.parse(raw.decode('utf-8-sig')), hashlib.sha256(raw).hexdigest()

def signature(node):
    args = node.args.posonlyargs + node.args.args
    defaults = [None] * (len(args) - len(node.args.defaults)) + list(node.args.defaults)
    pairs = list(zip(args, defaults)) + list(zip(node.args.kwonlyargs, node.args.kw_defaults))
    return [{'name': a.arg, 'type': expr(a.annotation), 'default': expr(d)} for a, d in pairs if a.arg != 'self']

def route_info(node, dec, path, mounted, prefix):
    kwargs = {kw.arg: expr(kw.value) for kw in dec.keywords if kw.arg}
    method = dec.func.attr
    methods = ast.literal_eval(next(kw.value for kw in dec.keywords if kw.arg == 'methods')) if 'methods' in kwargs else [method.upper()]
    local = ast.literal_eval(dec.args[0]) if dec.args else ''
    source = ROOT.joinpath(path).read_text(encoding='utf-8-sig')
    body = ast.get_source_segment(source, node) or ''
    auth = '管理员' if 'Depends(require_admin)' in body else ('登录用户' if 'Depends(get_current_user)' in body else '无路由级用户鉴权')
    return {'module': Path(path).stem, 'methods': methods, 'path': prefix + local if mounted else local,
            'local_path': local, 'mounted': mounted, 'function': node.name, 'purpose': PURPOSE.get(node.name, ast.get_docstring(node) or node.name).splitlines()[0],
            'auth': auth, 'parameters': signature(node), 'response_model': kwargs.get('response_model'),
            'return_annotation': expr(node.returns), 'responses': sorted(set(expr(n.value) for n in ast.walk(node) if isinstance(n, ast.Return) and n.value is not None)),
            'http_errors': sorted(set(expr(n) for n in ast.walk(node) if isinstance(n, ast.Call) and expr(n.func) == 'HTTPException')),
            'stream': 'EventSourceResponse' in body or 'StreamingResponse' in body,
            'ownership_check': '_owned_run' in body or '_check_task_ownership' in body or 'owner_id' in body or 'user_id' in body or '_safe_object_name' in body or '_user_prefix' in body,
            'line': node.lineno, 'source': path, 'decorator_options': kwargs}

def main():
    main_tree, _ = parse(ROOT / 'src/main.py')
    settings_tree, _ = parse(ROOT / 'src/settings.py')
    api_prefix = next(ast.literal_eval(n.value) for n in ast.walk(settings_tree) if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == 'API_PREFIX')
    mounts = {}
    for n in ast.walk(main_tree):
        if isinstance(n, ast.Call) and expr(n.func) == 'app.include_router':
            module = n.args[0].value.id
            prefix = next(k.value for k in n.keywords if k.arg == 'prefix')
            assert isinstance(prefix, ast.BinOp) and expr(prefix.left) == 'settings.API_PREFIX'
            mounts[module] = api_prefix + ast.literal_eval(prefix.right)
    routes, unmounted, models, fingerprints, service_routes, tools = [], [], [], {}, [], []
    for path in sorted((ROOT / 'src/api/routers').glob('*.py')):
        rel = path.relative_to(ROOT).as_posix()
        tree, digest = parse(path)
        fingerprints[rel] = digest
        for n in tree.body:
            if isinstance(n, ast.ClassDef):
                fields = [{'name': f.target.id, 'type': expr(f.annotation), 'default': expr(f.value)} for f in n.body if isinstance(f, ast.AnnAssign) and isinstance(f.target, ast.Name)]
                models.append({'module': path.stem, 'name': n.name, 'bases': [expr(b) for b in n.bases], 'fields': fields, 'source': rel, 'line': n.lineno})
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in n.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and expr(d.func.value) == 'router' and d.func.attr in VERBS:
                    item = route_info(n, d, rel, path.stem in mounts, mounts.get(path.stem, ''))
                    (routes if item['mounted'] else unmounted).append(item)
    for path in sorted((ROOT / 'mcp_servers').glob('*.py')):
        tree, digest = parse(path)
        rel = path.relative_to(ROOT).as_posix()
        for n in tree.body:
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in n.decorator_list:
                if not isinstance(d, ast.Call) or not isinstance(d.func, ast.Attribute):
                    continue
                if d.func.attr == 'tool' and expr(d.func.value) == 'mcp':
                    tools.append({'server': path.stem, 'name': n.name, 'parameters': signature(n), 'description': ast.get_docstring(n), 'source': rel, 'line': n.lineno})
                    fingerprints[rel] = digest
                elif d.func.attr in VERBS and expr(d.func.value) == 'app':
                    service_routes.append(route_info(n, d, rel, True, ''))
                    fingerprints[rel] = digest
    for p in ['src/main.py', 'src/settings.py', 'src/api/dependencies.py', 'src/agent/aiops/events.py']:
        fingerprints[p] = parse(ROOT / p)[1]
    assert len({(m, r['path']) for r in routes for m in r['methods']}) == sum(len(r['methods']) for r in routes)
    counts = dict(Counter(r['module'] for r in routes))
    data = {'date': '2026-11-13', 'method': 'static AST + manual semantic review; no app import, requests, database or models',
            'api_prefix_default': api_prefix, 'mounted_modules': mounts, 'counts': counts, 'route_count': len(routes),
            'routes': routes, 'unmounted_routes': unmounted, 'models': models, 'service_routes': service_routes, 'mcp_tools': tools, 'source_sha256': fingerprints}
    (OUT / 'api-inventory.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (OUT / 'api-inventory.js').write_text('window.API_INVENTORY = ' + json.dumps(data, ensure_ascii=False).replace('</', r'<\/') + ';\n', encoding='utf-8')
    lines = ['# 后端接口全量清单', '', '核对日期：2026-11-13。默认 API_PREFIX=/api/v1；部署可覆盖。', '',
             f'从 src/main.py 实际挂载关系解析出 **{len(mounts)} 组、{len(routes)} 个业务路由**（含隐藏健康兼容别名）；另有 {len(unmounted)} 个未注册路由、{len(service_routes)} 个独立网关路由声明、{len(tools)} 个显式 MCP 工具。', '',
             '只读 AST 与手工语义复核，没有导入应用、启动产品后端、改动数据库、请求模型。此清单反映源码合同，不证明线上部署可用。JSON 提供参数、模型字段、返回表达式、错误分支与源码 SHA256；不是运行时 OpenAPI。', '',
             '| 模块 | 路由数 | 界面归属 |', '|---|---:|---|']
    placement = {'aiops': '诊断主界面/按 ID 恢复/证据抽屉', 'knowledge_base': '运维知识库；QA 功能收起', 'health': '诊断前能力检查/平台维护', 'auth': '登录与账号权限', 'monitor': '平台维护的文档入库任务', 'storage': '平台维护的文件管理', 'chat': '降级辅助入口', 'assistant': '退出毕设主导航，暂保留兼容', 'agent': '退出毕设主导航，暂保留兼容', 'evaluation': '仅知识问答评测，退出主导航', 'loadfile': '历史上传兼容，不新增主入口'}
    for module, count in counts.items():
        lines.append(f'| {module} | {count} | {placement[module]} |')
    for module in counts:
        lines += ['', f'## {module}', '', '| 方法 | 完整路径 | 作用 | 鉴权 | 源码 |', '|---|---|---|---|---|']
        for r in routes:
            if r['module'] == module:
                lines.append(f"| {' / '.join(r['methods'])} | `{r['path']}` | {r['purpose']} | {r['auth']} | [{r['function']}](../../../{r['source']}#L{r['line']}) |")
        for r in routes:
            if r['module'] != module:
                continue
            lines += ['', f"### {' / '.join(r['methods'])} {r['path']}", '', f"函数：`{r['function']}`。响应模型：`{r['response_model'] or r['return_annotation'] or '无显式 response_model，见 JSON 返回表达式'}`。", '']
            for p in r['parameters']:
                lines.append(f"- `{p['name']}: {p['type'] or '未标注'}`；默认/注入：`{p['default'] if p['default'] is not None else '必填'}`")
    lines += ['', '## 未注册路由', '', '存在源码不代表已经对外提供；不得为这些模块臆造 URL 前缀。', '']
    for r in unmounted:
        lines.append(f"- `{r['source']}:{r['line']}`：{' / '.join(r['methods'])} `{r['path']}`，{r['purpose']}。未在 src/main.py include_router。")
    lines += ['', '## 框架与条件端点', '', '- 非 production：`GET /docs`、`GET /docs/oauth2-redirect`、`GET /redoc`、`GET /openapi.json`，由 FastAPI 默认文档生成。生产关闭。', '- Prometheus 可选依赖存在时挂载 `/metrics` ASGI 子应用；属于平台抓取接口，不是页面业务接口。', '- 当前主应用没有挂载 `/mcp/rag`，相关示例代码处于注释中。', '', '## 独立网关 HTTP 与 WebSocket', '', '这些服务不在 /api/v1 下，使用各自监听地址；不是浏览器应直接取得 Probe 凭据的理由。', '']
    for r in service_routes:
        lines.append(f"- `{r['source']}:{r['line']}`：{' / '.join(r['methods'])} `{r['path']}` → `{r['function']}`；认证需看该服务中间件/握手。")
    lines += ['', '## MCP 工具', '', 'MCP 服务由 Agent 后端调用。HTTP /mcp 传输路由由 SDK 构造，不能把工具名当 REST URL；以下为显式 @mcp.tool 全量定义，不等于当前运行时全部已启用。', '', '| 服务 | 工具 | 参数 | 源码 |', '|---|---|---|---|']
    for t in tools:
        sig = ', '.join(p['name'] + (': ' + p['type'] if p['type'] else '') for p in t['parameters'])
        lines.append(f"| {t['server']} | `{t['name']}` | `{sig}` | {t['source']}:{t['line']} |")
    lines += ['', '## 数据结构', '', '继承字段需要同时查看 bases 指定的父类；Field/validator 的全部校验以源码为准。', '']
    for m in models:
        lines += [f"### {m['module']}.{m['name']}", '', f"父类：`{', '.join(m['bases'])}`。源码：`{m['source']}:{m['line']}`。", '', '| 字段 | 类型 | 默认/约束表达式 |', '|---|---|---|']
        for f in m['fields']:
            lines.append(f"| {f['name']} | `{f['type']}` | `{str(f['default'] if f['default'] is not None else '必填').replace('|', '/')}` |")
        lines.append('')
    (OUT / '接口全量清单.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'registered': len(routes), 'modules': counts, 'unmounted': len(unmounted), 'gateway_routes': len(service_routes), 'mcp_tools': len(tools)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
