"""Bind planned Probe queries to their actual scope and existing observations."""
import fnmatch
import json
import ntpath
from datetime import datetime

from src.probe.evidence import PROBE_TOOL_OPERATIONS


def _log_repeat_has_new_evidence(row, ids, records):
    """Require a changed observation of the same service after the previous log."""
    from src.agent.aiops.strategies.investigation import probe_query_key, _probe_summary_status
    from src.probe.evidence import diagnostic_fingerprint
    logs = [json.loads(records[ident]['payload']) for ident in row['evidence_ids']]
    boundary = max(datetime.fromisoformat(raw['collected_at'].replace('Z', '+00:00')) for raw in logs)
    service = row['arguments']['service']
    for ident in ids - set(row['evidence_ids']):
        raw = json.loads(records[ident]['payload'])
        body = raw.get('payload') or {}
        operation = raw.get('operation')
        tool = next((name for name, op in PROBE_TOOL_OPERATIONS.items() if op == operation), None)
        if (raw.get('data_source') != 'probe_target' or raw.get('truncated') or body.get('error')
                or body.get('not_applicable') or _probe_summary_status(raw, body) == 'not_applicable' or not tool
                or not (body.get('service') == service or
                        (operation == 'dependency_probe' and body.get('dependency') == service))
                or datetime.fromisoformat(raw['collected_at'].replace('Z', '+00:00')) <= boundary):
            continue
        key = probe_query_key(tool, body, observation=True)
        same_before = any(
            old.get('operation') == operation
            and datetime.fromisoformat(old['collected_at'].replace('Z', '+00:00')) <= boundary
            and probe_query_key(tool, old.get('payload') or {}, observation=True) == key
            and diagnostic_fingerprint(old) == diagnostic_fingerprint(raw)
            for old in (json.loads(record['payload']) for record in records.values()))
        if not same_before:
            return True
    return False


def arguments_error(tool, arguments, state, records):
    from src.agent.aiops.strategies.investigation import probe_query_key
    if tool == 'read_run_evidence':
        from src.agent.aiops.evidence_reader import read_query_key
        try:
            read_query_key(arguments)
        except (TypeError, ValueError):
            return '证据读取参数无效：只允许 evidence_id、query、offset、limit，且须符合已有读取范围。'
        record = records.get(arguments['evidence_id'])
        from src.agent.aiops.observations import in_business_scope
        if not record or not record.get('readable') or not in_business_scope(
                json.loads(record['payload']), state.get('target_resolution'), records):
            return '证据读取必须引用本轮范围内已通过校验的可读取证据ID。'
        return ''
    if any(str(key).endswith(('_2', '_3', '_copy')) for key in (arguments or {})):
        return '同一 Probe 工具不能通过伪造名称执行多个对象；每步只填写一个真实工具名，多个对象拆成后续步骤。'
    if tool not in PROBE_TOOL_OPERATIONS or not isinstance(arguments, dict):
        return '检查参数不是可用的 Probe 查询对象。'
    defaults = json.loads(probe_query_key(tool, {}, observation=True))[1]
    required = {'services': ['service'], 'configuration': ['service'], 'event_logs': ['service'], 'text_logs': ['service', 'path'],
                'dependency_probe': ['dependency']}.get(PROBE_TOOL_OPERATIONS[tool], [])
    if set(arguments) - set(defaults) or any(not isinstance(arguments.get(k), str) or not arguments[k].strip() for k in required):
        return '检查参数缺失、类型错误或包含工具未开放的字段。'
    for key, value in arguments.items():
        if value is None and key not in {'service', 'local_port'}:
            return '检查参数不能用空值替代工具默认值。'
        if key in {'service', 'dependency', 'path', 'sort_by'} and value is not None and not isinstance(value, str):
            return '检查参数字符串类型错误。'
        if key in {'lines', 'limit', 'since_minutes', 'local_port'} and value is not None and type(value) is not int:
            return '检查参数整数类型错误。'
        if key == 'listening_only' and type(value) is not bool:
            return '检查参数 listening_only 必须为布尔值。'
    operation = PROBE_TOOL_OPERATIONS[tool]
    limits = {'lines': 1000, 'since_minutes': 1440, 'local_port': 65535,
              'limit': 200 if operation == 'event_logs' else 256}
    if any(value is not None and not 1 <= value <= limits[key]
           for key, value in arguments.items() if key in limits):
        return '检查参数超出工具允许范围。'
    if arguments.get('sort_by', 'memory') not in {'memory', 'cpu'}:
        return '检查参数 sort_by 不受支持。'
    scope = state.get('target_resolution') or {}
    if scope.get('status') == 'resolved':
        if operation == 'dependency_probe' and arguments.get('dependency') not in scope.get('allowed_dependencies', []):
            return '检查参数指定的依赖不在本次允许对象中。'
        if 'service' in defaults and arguments.get('service') not in scope.get('allowed_services', []):
            return '检查参数指定的服务不在本次允许对象中。'
    inventories = [json.loads(row['payload']) for row in records.values()
                   if row.get('provenance', {}).get('operation') == 'inventory']
    inventories = [row for row in inventories if not row.get('truncated') and not row['payload'].get('error')]
    if not inventories:
        return ''  # Collector remains the authority when no fresh inventory is available.
    inventory = max(inventories, key=lambda row: datetime.fromisoformat(row['collected_at'].replace('Z', '+00:00')))['payload']
    if operation == 'dependency_probe' and 'configured_dependencies' in inventory:
        if arguments.get('dependency') not in inventory['configured_dependencies']:
            return '检查参数指定的依赖未配置。'
    service = arguments.get('service')
    if service is not None and 'configured_services' in inventory:
        if service not in inventory['configured_services']:
            return '检查参数指定的服务未配置。'
        config = inventory['configured_services'][service]
        if operation == 'services' and config.get('kind') == 'process':
            return 'Windows 服务检查不适用于该进程应用；应使用进程、入口或监听观测。'
        if operation == 'event_logs' and config.get('event_logs_available') is False:
            return '该服务的事件通道未配置。'
        if operation == 'configuration' and config.get('configuration_available') is not True:
            return '该服务的配置快照路径与字段未配置。'
        if operation == 'text_logs':
            if config.get('text_logs_available') is False:
                return '该服务的文本日志未配置。'
            path = ntpath.normcase(ntpath.normpath(arguments['path']))
            if 'text_logs' in config and not any(fnmatch.fnmatchcase(path, ntpath.normcase(ntpath.normpath(p)))
                                                 for p in config['text_logs']):
                return '检查参数中的日志路径不在配置允许范围内。'
    return ''


def check_progress(check, state, records):
    from src.agent.aiops.strategies.investigation import probe_query_key, _probe_summary_status, execution_checks
    rows = []
    for tool, args in (check.get('next_arguments') or {}).items():
        error = arguments_error(tool, args, state, records)
        if tool == 'read_run_evidence':
            from src.agent.aiops.evidence_reader import read_query_key
            attempts = []
            if not error:
                for item in execution_checks(state):
                    if item.get('tool') != tool:
                        continue
                    try:
                        if read_query_key(item.get('arguments') or {}) == read_query_key(args):
                            attempts.append(item)
                    except (TypeError, ValueError):
                        continue
            latest = attempts[-1] if attempts else None
            status = 'unavailable' if error or (latest and latest.get('status') != 'success') else 'observed' if latest else 'unexecuted'
            rows.append({'next_check': check.get('next_check', ''), 'question': check.get('discriminating_question', ''),
                'expected_observation': check.get('expected_observation', ''),
                'tool': tool, 'arguments': args, 'status': status,
                'evidence_ids': [args['evidence_id']] if latest and status == 'observed' else [],
                'observation': {'new_observation': False} if status == 'observed' else None,
                'remaining_unknown': '重读只返回该版本的保存内容，不能读取采集之后产生的日志或确认因果。',
                'limitation': error or ('该证据读取上次失败，不原样自动重试。' if status == 'unavailable' else
                    '已读取该证据版本的相同查询与分页，不重复读取。' if latest else '尚未读取该证据查询与分页。')})
            continue
        matches = []
        if not error:
            key = probe_query_key(tool, args)
            for ident, record in records.items():
                value = json.loads(record['payload'])
                if (value.get('data_source') == 'probe_target' and value.get('operation') == PROBE_TOOL_OPERATIONS[tool]
                        and probe_query_key(tool, value.get('payload') or {}, observation=True) == key):
                    matches.append((ident, value))
        matches.sort(key=lambda item: datetime.fromisoformat(item[1]['collected_at'].replace('Z', '+00:00')))
        latest = matches[-1][1] if matches else None
        attempts = [item for item in execution_checks(state) if not error and item.get('tool') == tool
                    and probe_query_key(tool, item.get('arguments') or {}) == probe_query_key(tool, args)]
        failure = attempts[-1] if attempts and attempts[-1].get('status') in {'failed', 'unavailable', 'cancelled'} else None
        if failure:
            error = '该具体查询上次未取得有效结果：' + str(failure.get('reason') or failure['status']) + '；不原样自动重试。'
        status = 'unavailable' if error else _probe_summary_status(latest, latest['payload']) if latest else 'unexecuted'
        body = latest['payload'] if latest else {}
        operation = PROBE_TOOL_OPERATIONS.get(tool)
        observation = None
        unknown = '尚无有效结果，不能裁决该解释。'
        if latest and status not in {'unavailable', 'not_applicable'}:
            observation = {key: body[key] for key in
                ('tcp', 'http', 'state', 'matched_count', 'inspected_count', 'skipped_count', 'selection') if key in body}
            unknown = '这些是采样时的有限事实，不能单独确认因果解释。'
            if operation == 'text_logs':
                observation = {'line_count': len(body.get('lines') or []), 'truncated': bool(latest.get('truncated'))}
                unknown = '日志只说明本次返回内容；空日志不能证明进程不存在，也不能区分未启动、退出或未写日志。'
            elif operation == 'processes':
                observation['returned_count'] = len(body.get('processes') or [])
                unknown = '只限配置身份、可枚举范围及采样时间；不能扩大为所有相关进程不存在，也不能证明退出历史。'
            elif operation == 'ports':
                observation['listening_count'] = sum(row.get('status') == 'LISTEN' for row in body.get('ports') or [])
                unknown = '只说明查询端口在采样时的监听状态，不能单独确认绑定或退出原因。'
        rows.append({'next_check': check.get('next_check', ''), 'question': check.get('discriminating_question', ''),
            'expected_observation': check.get('expected_observation', ''),
            'tool': tool, 'arguments': args, 'status': status,
            'evidence_ids': [ident for ident, _ in matches[-2:]],
            'observation': observation, 'remaining_unknown': unknown,
            'limitation': error or ('该具体查询返回不适用。' if status == 'not_applicable' else
                '已有该查询的现场结果；只证明返回内容，不证明因果。' if matches else '该具体查询尚未取得有效观测。')})
    return rows


def progress_error(check, state, records):
    """A repeated query needs a stated purpose tied to the returned evidence."""
    if check.get('next_arguments') is None:
        return ''  # Legacy checkpoint continuation keeps its previous validation path.
    from src.agent.aiops.strategies.investigation import repeated_probe_arguments, evidence_index, in_business_scope
    # The latest-per-query view is right for conclusions, but cannot count repeats.
    history = evidence_index(state) if 'raw_evidence' in state else records
    history = {key: record for key, record in history.items()
               if in_business_scope(json.loads(record['payload']), state.get('target_resolution'), records)}
    for row in check_progress(check, state, records):
        if row['status'] in {'unavailable', 'not_applicable'}:
            return row['limitation'] + ' 请改用适用检查或说明实际限制。'
        if row['tool'] == 'read_run_evidence':
            if row['evidence_ids']:
                return row['limitation']
            continue
        if row['evidence_ids']:
            if repeated_probe_arguments(row['tool'], row['arguments'], state, records=history):
                return '下一项检查只会重复已有查询，raw_hash 未变化；请改查有效鉴别对象或说明停止原因。'
            ids = set(check.get('repeat_evidence_ids') or [])
            if (not str(check.get('repeat_reason') or '').strip()
                    or not ids & set(row['evidence_ids']) or not ids <= set(records)):
                return '已有该对象和参数的检查结果；再次采样须说明复核目的并关联原证据，不能换句话重复检查。'
            version = state.get('_probe_check_contract_version',
                ((state.get('investigation_memory') or {}).get('hypothesis_tracking') or {}).get('check_contract_version', 2))
            if version >= 2 and row['tool'] == 'probe_text_log':
                # Include older observations to distinguish a new ID from new information.
                relevant = {**history, **records}
                relevant = {key: record for key, record in relevant.items()
                    if in_business_scope(json.loads(record['payload']), state.get('target_resolution'), records)}
                if not _log_repeat_has_new_evidence(row, ids & set(relevant), relevant):
                    return ('相同日志检查已完成；复查须关联旧日志之后同服务有变化的新证据，'
                            '不能仅凭可能遗漏启动记录重复读取；请改查未执行的鉴别检查或保留未知后结束。')
    return ''
