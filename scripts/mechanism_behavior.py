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
        'behavior_context': {'validated_at': validated_at, 'records': records,
            'model_suggestion': deepcopy(memory.get('model_suggestion')),
            'investigation_tools': deepcopy(state.get('investigation_tools', [])),
            'target_resolution': deepcopy(state.get('target_resolution')),
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
        emitted, rejected = set(), set()
        primary = inv.Alternative(explanation=proposal.hypothesis, status='unresolved', hypothesis_id=proposal.hypothesis_id,
                                  condition=proposal.hypothesis_condition)
        resolved = []
        for item in [primary, *proposal.alternatives]:
            ident, error = inv._resolve_candidate_identity(item, saved)
            if not error:
                emitted.add(ident)
                resolved.append((ident, item))
        inv._validate_alternatives(proposal, records)
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
            'contradiction_opportunity': contradiction, 'events': [], 'issues': []}
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
    condition = candidate.get('condition')
    if not condition:
        return bool(calls)
    argument = {'dependency_probe': 'dependency', 'services': 'service',
                'processes': 'service', 'ports': 'local_port'}[condition['operation']]
    return any(inv.PROBE_TOOL_OPERATIONS.get(e['tool']) == condition['operation']
        and str((e.get('arguments') or {}).get(argument)) == condition['object_name'] for e in calls)
