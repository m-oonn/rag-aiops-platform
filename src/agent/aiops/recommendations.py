"""Conditional manual advice from verified fault observations, never causal claims."""
import json


def _configured_object(scope, resolution, records, target_id):
    if (resolution or {}).get('status') != 'resolved':
        return json.dumps(scope, sort_keys=True)
    allowed = set(resolution.get('allowed_services', []))
    mapping = resolution.get('dependency_services', {})
    local_dependencies = {}
    for record in records.values():
        raw = json.loads(record['payload'])
        body = raw.get('payload') or {}
        name = body.get('dependency')
        if (raw.get('operation') == 'dependency_probe'
                and (target_id is None or raw.get('target_id') == target_id)
                and body.get('host') in {'localhost', '127.0.0.1', '::1'}
                and name in resolution.get('allowed_dependencies', [])
                and mapping.get(name) in allowed and type(body.get('port')) is int):
            local_dependencies[name] = (mapping[name], body['port'])
    if set(scope) == {'service'} and scope['service'] in allowed:
        return ('service', scope['service'])
    if set(scope) == {'dependency'} and scope['dependency'] in local_dependencies:
        return ('service', local_dependencies[scope['dependency']][0])
    if set(scope) == {'local_port'}:
        services = {name for name, port in local_dependencies.values() if port == scope['local_port']}
        if len(services) == 1:
            return ('service', services.pop())
    return json.dumps(scope, sort_keys=True)


def manual_recommendations(findings, *, resolution=None, records=None):
    from src.agent.aiops.observations import current_probe_records
    records = current_probe_records(records or {})
    recommendations = []
    grouped = {}
    for finding in findings:
        code = finding['code']
        if code == 'dependency_http_failed':
            action = '核查该接口对应应用的错误日志及近期变更；确认相关配置或代码异常后，由人修正或回退已确认的变更。'
            prerequisite = '先确认日志与本次失败请求、应用对象和时间窗口对应；不能仅凭HTTP失败认定配置错误或下游故障。'
            verification = '处理后重新请求同一接口，核对HTTP状态、响应内容及应用日志；涉及依赖时同时独立探测依赖。'
        elif code in {'dependency_tcp_failed', 'service_not_running', 'configured_process_not_observed',
                      'port_not_listening', 'expected_port_not_listening'}:
            action = '核实该对象对应的进程、监听地址、端口和服务配置；确认预期服务未运行或配置有误后，由人恢复服务或修正已确认的配置。'
            prerequisite = '先确认业务对象与预期进程、监听及配置的映射，并保存错误日志；连接失败或未发现进程不能说明退出原因。'
            verification = '处理后重新检查同一对象的进程与监听，复测连接及健康接口，再检查入口业务是否恢复。'
        elif code == 'port_owner_mismatch':
            action = '核对监听PID与预期服务进程及端口配置；确认占用冲突后，由人调整端口或处理已确认的占用进程。'
            prerequisite = '先核实PID对应程序及业务影响，排除进程重启或配置映射过期；不能直接终止未知进程。'
            verification = '处理后重新核对端口监听PID与服务PID，再请求对应健康接口及入口业务。'
        else:
            continue
        refs = [{'evidence_id': finding['evidence_id'], 'quote': finding['quote']},
                *finding.get('related_evidence', [])]
        key = (finding.get('target_id'), _configured_object(finding['scope'], resolution, records, finding.get('target_id')), action)
        if key in grouped:
            existing = grouped[key]
            scopes = existing.setdefault('related_scopes', [])
            if finding['scope'] != existing['scope'] and finding['scope'] not in scopes:
                scopes.append(finding['scope'])
            codes = existing.setdefault('finding_codes', [existing['finding_code']])
            if code not in codes:
                codes.append(code)
            existing['evidence'].extend(ref for ref in refs if ref not in existing['evidence'])
            continue
        item = {
            'origin': 'verified_observation_template', 'status': 'manual_review_required',
            'finding_code': code, 'scope': finding['scope'],
            'evidence': refs,
            'action': action, 'preconditions': [prerequisite,
                '执行前重新采集当前状态，确认故障仍存在且具备对应业务的操作权限。'],
            'risks': ['变更或重启可能中断请求；先备份相关配置，确定业务影响、操作窗口和回退方法。'],
            'verification_steps': [verification],
        }
        grouped[key] = item
        recommendations.append(item)
    return recommendations


def format_manual_recommendations(recommendations):
    if not recommendations:
        return '\n\n人工处理建议：本次没有形成可用的已核验故障层，暂不给出具体修复操作；请补齐现场证据后再判断。'
    lines = ['', '', '人工处理建议（待人工核对，尚未执行；不作为根因证明）：']
    for item in recommendations:
        lines.append('处理对象：' + json.dumps(item['scope'], ensure_ascii=False))
        if item.get('related_scopes'):
            lines.append('同一配置对象的关联检查：' + json.dumps(item['related_scopes'], ensure_ascii=False))
        lines.append('建议：' + item['action'])
        lines.extend('操作前提：' + text for text in item['preconditions'])
        lines.extend('风险：' + text for text in item['risks'])
        lines.extend('处理后验证：' + text for text in item['verification_steps'])
        lines.extend(f"建议依据：[{ref['evidence_id']}] {ref['quote']}" for ref in item['evidence'])
    return '\n'.join(lines)
