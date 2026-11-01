"""Read-only mechanical checks of mechanism opportunities and scheduled execution."""
from copy import deepcopy
from datetime import datetime
import json

from src.agent.aiops.strategies import investigation as inv
from src.settings import settings


def behavior_snapshot(state, validated_at):
    records = inv.evidence_index(state, now=datetime.fromisoformat(validated_at.replace('Z', '+00:00')))
    records = {key: value for key, value in inv.current_probe_records(records).items()
               if inv.in_business_scope(json.loads(value['payload']), state.get('target_resolution'), records)}
    memory = state.get('investigation_memory') or {}
    return {'step': len(state.get('past_steps', [])), 'plan': deepcopy(state.get('plan', [])),
        'tracking': deepcopy(memory.get('hypothesis_tracking') or {}),
        'next_tools': memory.get('next_tools', []),
        'next_arguments': deepcopy(memory.get('next_arguments')),
        'behavior_context': {'validated_at': validated_at, 'records': records,
            'model_suggestion': deepcopy(memory.get('model_suggestion')),
            'investigation_tools': deepcopy(state.get('investigation_tools', [])),
            'target_resolution': deepcopy(state.get('target_resolution')),
            'tool_execution_checks': inv.execution_checks(state),
            'past_steps': deepcopy(state.get('past_steps', []))}}


def audit_behavior(snapshots, executed_steps, execution_records=None):
    missing = [i for i, row in enumerate(snapshots) if not row.get('behavior_context')
               or row['behavior_context'].get('model_suggestion') is None]
    if not snapshots or missing or executed_steps is None:
        return {'status': 'not_assessed', 'reason': '缺少当轮证据/模型提议或最终执行步骤',
                'missing_context_rows': missing, 'mechanism_effectiveness_verified': False}
    try:
        return _audit_behavior(snapshots, executed_steps, execution_records or [])
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return {'status': 'failed', 'issues': ['行为轨迹格式无效：' + type(exc).__name__],
                'mechanism_effectiveness_verified': False}


def _audit_behavior(snapshots, executed_steps, execution_records):
    rows, issues, seen_events = [], [], []
    opportunities = {'protection': 0, 'contradiction': 0}
    executed_changes = {'protection': 0, 'contradiction': 0}
    executed_checks = {'protection': 0, 'contradiction': 0}
    for index, row in enumerate(snapshots):
        context, tracking = row['behavior_context'], row['tracking']
        step, records = row['step'], context['records']
        now = datetime.fromisoformat(context['validated_at'].replace('Z', '+00:00'))
        for record in records.values():
            raw = json.loads(record['payload'])
            inv.validate_evidence(raw, target_id=settings.PROBE_TARGET_ID, now=now)
            if not inv.in_business_scope(raw, context.get('target_resolution'), records):
                raise ValueError('out of business scope')
        config = tracking['config']
        state = {**context, 'investigation_config': config}
        current = {c['id']: c for c in tracking.get('candidates', [])}
        previous = snapshots[index - 1]['tracking'] if index else {}
        saved = {c['id']: c for c in previous.get('candidates', [])}
        proposal = inv.InvestigationDecision.model_validate(context['model_suggestion'])
        if tracking.get('version', 1) >= 2:
            inv._resolve_citations(proposal, records)
            for candidate in current.values():
                condition = candidate.get('condition')
                binding = ('bound' if inv._condition_bound(candidate['explanation'], condition)
                           else 'unverified' if condition else 'not_applicable')
                if candidate.get('condition_binding') != binding:
                    issues.append('候选条件绑定与原始表达不一致：' + candidate['id'])
        emitted, rejected = set(), set()
        primary = inv.Alternative(explanation=proposal.hypothesis, status='unresolved', hypothesis_id=proposal.hypothesis_id,
                                  condition=proposal.hypothesis_condition)
        resolved = []
        projected_sources = {}
        projected_candidates = {}
        identity_errors = []
        for source in [primary, *proposal.alternatives]:
            item = inv.mechanism_candidate(source) if tracking.get('version', 1) >= 3 else source
            ident, error = inv._resolve_candidate_identity(item, saved)
            if error:
                identity_errors.append(error)
            if not error:
                emitted.add(ident)
                source.condition = item.condition
                resolved.append((ident, source))
                sources = projected_sources.setdefault(ident, [])
                if source.explanation not in sources:
                    sources.append(source.explanation)
                # Runtime keeps the first proposal as representative and all prose separately.
                projected_candidates.setdefault(ident, inv.mechanism_candidate(source))
        if identity_errors != tracking.get('identity_issues', []):
            issues.append('候选身份拒绝记录与原始提议不一致')
        if identity_errors:
            # Runtime rejects the entire proposal before replacing any saved candidate.
            fields = ('explanation', 'source_explanation', 'source_explanations', 'condition',
                      'check', 'proposal', 'birth_step')
            if set(current) != set(saved) or any(
                    current.get(ident, {}).get(key) != candidate.get(key)
                    for ident, candidate in saved.items() for key in fields):
                issues.append('身份拒绝后仍更新了候选提议')
            recovery = tracking.get('identity_recovery')
            if recovery:
                # Reconstruct prior failures only. Historical observations were already
                # validated above at their recorded time, not at today's TTL boundary.
                policy_state = {**state, 'raw_evidence': [
                    (item.get('step', ''), json.dumps({**item, 'data_source': 'tool_execution'}))
                    for item in context.get('tool_execution_checks', [])]}
                policy_state['investigation_memory'] = {'hypothesis_tracking': previous}
                expected_policy = (inv.dependency_followup_policy(policy_state, records)
                                   or inv.saved_candidate_followup(policy_state, records))
                check = recovery.get('check') or {}
                fixed_selection = (recovery.get('selection') if
                    recovery.get('selection', {}).get('kind') != 'saved_candidate_check' else None)
                if (recovery != expected_policy or tracking.get('policy_selected_check') != fixed_selection
                        or row['plan'] != [check.get('next_check')]
                        or row.get('next_tools') != check.get('next_tools')
                        or row.get('next_arguments') != check.get('next_arguments')
                        or len(executed_steps) <= step or executed_steps[step] != check.get('next_check')
                        or not _executed_candidate({}, check, execution_records)):
                    issues.append('身份拒绝后的独立补查与现场依据/计划/执行不一致')
            elif row['plan'] or len(executed_steps) > step:
                # Historical stops may expose proposed tool metadata without scheduling it.
                issues.append('身份拒绝后仍选择或执行了新计划')
            if tracking.get('leading_id') != previous.get('leading_id', ''):
                issues.append('身份拒绝后仍替换了主候选')
        elif tracking.get('identity_recovery'):
            issues.append('没有身份拒绝却声明独立补查恢复')
        blocked_recovery = tracking.get('blocked_check_recovery')
        blocked_review = tracking.get('blocked_check_review')
        if blocked_recovery:
            policy_state = {**state, 'raw_evidence': [
                (item.get('step', ''), json.dumps({**item, 'data_source': 'tool_execution'}))
                for item in context.get('tool_execution_checks', [])]}
            policy_state['investigation_memory'] = {'hypothesis_tracking': previous}
            blocked = inv.followup_check_error(proposal.model_dump(), state)
            if not blocked:
                from src.agent.aiops.probe_checks import progress_error
                blocked = progress_error(proposal.model_dump(), state, records)
            expected = inv._blocked_check_candidate_followup(policy_state, records) if blocked else None
            check = (expected or {}).get('check') or {}
            candidate = next((item for item in saved.values()
                              if item.get('id') == blocked_recovery.get('candidate_id')), {})
            if (identity_errors or not blocked or not expected
                    or blocked_recovery != expected.get('selection')
                    or row['plan'] != [check.get('next_check')]
                    or row.get('next_tools') != check.get('next_tools')
                    or row.get('next_arguments') != check.get('next_arguments')
                    or len(executed_steps) <= step or executed_steps[step] != check.get('next_check')
                    or not inv._candidate_check(candidate, state, records)
                    or not _executed_candidate(candidate, check, execution_records)):
                issues.append('不可执行检查后的候选回退与前轮状态/现场/计划/执行不一致')
        elif blocked_review:
            policy_state = {**state, 'raw_evidence': [
                (item.get('step', ''), json.dumps({**item, 'data_source': 'tool_execution'}))
                for item in context.get('tool_execution_checks', [])]}
            policy_state['investigation_memory'] = {'hypothesis_tracking': previous}
            blocked = inv.followup_check_error(proposal.model_dump(), state)
            if not blocked:
                from src.agent.aiops.probe_checks import progress_error
                blocked = progress_error(proposal.model_dump(), state, records)
            expected = inv._blocked_check_candidate_followup(policy_state, records) if blocked else None
            if (identity_errors or not blocked or not expected or expected.get('check')
                    or blocked_review != expected.get('selection') or row['plan']
                    or len(executed_steps) > step):
                issues.append('受阻检查后的候选排查记录与前轮状态/现场/停止结果不一致')
        if tracking.get('version', 1) >= 3 and not identity_errors:
            for ident, sources in projected_sources.items():
                if ident in current:
                    item, candidate = projected_candidates[ident], current[ident]
                    if (candidate.get('explanation') != item.explanation
                            or candidate.get('condition') != (item.condition.model_dump() if item.condition else None)
                            or candidate.get('source_explanation') != sources[0]):
                        issues.append('有限预期与原始模型提议或保存的条件不一致：' + ident)
                if ident in current and current[ident].get('source_explanations') != sources:
                    issues.append('有限预期对应的原始解释列表不一致：' + ident)
        inv._validate_alternatives(proposal, records,
            require_condition_binding=tracking.get('version', 1) >= 2)
        updated = deepcopy(saved)
        for ident, item in resolved:
            if ident in saved:
                if item.original_status == 'excluded' and item.status == 'unresolved':
                    rejected.add(ident)
                    updated[ident].update(condition=item.condition.model_dump() if item.condition else None,
                        check=item.check.model_dump() if item.check else saved[ident].get('check'),
                        status='active')
        protected = []
        for ident, candidate in updated.items():
            observations = inv._candidate_observations(candidate, records)
            expected = (candidate.get('condition') or {}).get('expected')
            contradicted = bool(observations) and (type(observations[0][1]) is not type(expected)
                                                   or observations[0][1] != expected)
            if ((ident not in emitted or ident in rejected)
                    and step - candidate['birth_step'] < config['protection_steps']
                    and candidate['status'] not in {'excluded', 'unavailable', 'dropped'}
                    and not contradicted and inv._candidate_check(candidate, state, records)):
                protected.append(ident)
        leader = saved.get(previous.get('leading_id'))
        observations = inv._candidate_observations(leader, records) if leader else []
        fresh = {token for _, _, token in observations} - set((leader or {}).get('seen_observations', []))
        expected = (leader.get('condition') or {}).get('expected') if leader else None
        contradiction = bool(fresh and observations and (type(observations[0][1]) is not type(expected)
                                                         or observations[0][1] != expected))
        if tracking.get('identity_issues'):
            protected, contradiction = [], False
        opportunities['protection'] += len(protected)
        opportunities['contradiction'] += int(contradiction)
        events = [event for event in tracking.get('events', []) if event not in seen_events]
        seen_events.extend(deepcopy(events))
        entry = {'step': step, 'protected_opportunities': protected,
            'contradiction_opportunity': contradiction, 'identity_rejected': bool(identity_errors),
            'independent_followup': bool(identity_errors and tracking.get('identity_recovery')),
            'saved_check_continued': bool(identity_errors and
                (tracking.get('identity_recovery') or {}).get('selection', {}).get('kind') == 'saved_candidate_check'),
            'events': [], 'issues': []}
        for event in events:
            kind, ident = event['kind'], event['hypothesis_id']
            candidate = current.get(ident, {})
            valid = event.get('step') == step
            if kind in {'hypothesis_protected', 'protection_check_selected'}:
                valid = (valid and config['hypothesis_protection'] and ident in protected
                         and candidate.get('status') == 'protected'
                         and step - candidate.get('birth_step', step) < config['protection_steps'])
            if kind in {'contradiction_triggered', 'contradiction_blocked'}:
                valid = (valid and config['contradiction_trigger'] and contradiction
                         and bool(event.get('evidence_ids'))
                         and set(event['evidence_ids']) == {key for key, _, _ in observations}
                         and event.get('condition') == leader.get('condition'))
                if kind == 'contradiction_triggered':
                    valid = (valid and event.get('previous_leader_id') == leader['id'] and ident != leader['id']
                             and candidate.get('status') in {'active', 'protected'} and not _contradicted(candidate, records))
                else:
                    alternatives = [c for c in current.values() if c['id'] != leader['id']
                        and c['status'] in {'active', 'protected'}
                        and not _contradicted(c, records) and inv._candidate_check(c, state, records)]
                    valid = valid and ident == leader['id'] and not row['plan'] and not alternatives
            selected = kind in {'protection_check_selected', 'contradiction_triggered'}
            executed = False
            if selected:
                check = candidate.get('check') or {}
                valid = (valid and event.get('next_check') == check.get('next_check')
                    and row['plan'] == [event.get('next_check')]
                    and row.get('next_tools') == check.get('next_tools')
                    and (check.get('next_arguments') is None or row.get('next_arguments') == check['next_arguments'])
                    and tracking.get('leading_id') == ident
                    and event.get('from_check') == proposal.next_check
                    and bool(inv._candidate_check(candidate, state, records)))
                executed = (len(executed_steps) > step and executed_steps[step] == event.get('next_check')
                    and _executed_candidate(candidate, check, execution_records))
                valid = valid and executed
                if valid:
                    mechanism = 'protection' if kind == 'protection_check_selected' else 'contradiction'
                    executed_checks[mechanism] += 1
                    executed_changes[mechanism] += int(event['from_check'] != event['next_check'])
            if kind == 'protection_expired':
                valid = (valid and config['hypothesis_protection']
                         and step - candidate.get('birth_step', step) >= config['protection_steps'])
            if not valid:
                entry['issues'].append('事件与候选/证据/计划/执行不一致：' + kind)
            entry['events'].append({'kind': kind, 'valid': bool(valid), 'executed': executed,
                'changed': selected and event.get('from_check') != event.get('next_check')})
        if config['hypothesis_protection'] and any(current.get(ident, {}).get('status') != 'protected' for ident in protected):
            entry['issues'].append('符合保护条件的候选未保留')
        if (config['hypothesis_protection'] and protected and not (config['contradiction_trigger'] and contradiction)
                and not any(e['kind'] == 'protection_check_selected' for e in events)):
            entry['issues'].append('符合保护条件的候选未产生核查选择记录')
        if config['contradiction_trigger'] and contradiction and not any(
                event['kind'] in {'contradiction_triggered', 'contradiction_blocked'} for event in events):
            entry['issues'].append('可靠新反证未产生改向或阻塞记录')
        issues.extend(entry['issues'])
        rows.append(entry)
    return {'status': 'failed' if issues else 'passed', 'issues': issues, 'decisions': rows,
        'opportunities': opportunities, 'executed_changes': executed_changes, 'executed_checks': executed_checks,
        'completed_executor_steps': len(executed_steps),
        'blocked_events': sum(e['kind'] == 'contradiction_blocked' for row in rows for e in row['events']),
        'no_opportunity': not any(opportunities.values()),
        'candidate_correctness': 'pending_manual_review', 'extra_cost_vs_baseline': 'not_estimated',
        'mechanism_effectiveness_verified': False}


def _contradicted(candidate, records):
    observations = inv._candidate_observations(candidate, records)
    expected = (candidate.get('condition') or {}).get('expected')
    return bool(observations) and (type(observations[0][1]) is not type(expected) or observations[0][1] != expected)


def _executed_candidate(candidate, check, executions):
    calls = [e for e in executions if e.get('step') == check.get('next_check')
             and e.get('status') == 'success' and e.get('tool') in check.get('next_tools', [])]
    planned = check.get('next_arguments')
    if planned is not None:
        calls = [e for e in calls if e['tool'] in planned and (
            e['tool'] not in inv.PROBE_TOOL_OPERATIONS or
            inv.probe_query_key(e['tool'], e.get('arguments') or {}) == inv.probe_query_key(e['tool'], planned[e['tool']]))]
    condition = candidate.get('condition')
    if not condition:
        return bool(calls)
    argument = {'dependency_probe': 'dependency', 'services': 'service',
                'processes': 'service', 'ports': 'local_port'}[condition['operation']]
    return any(inv.PROBE_TOOL_OPERATIONS.get(e['tool']) == condition['operation']
        and str((e.get('arguments') or {}).get(argument)) == condition['object_name'] for e in calls)
