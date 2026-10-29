"""Prepare locally; explicitly execute one historical HTTP request, without tools."""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_windows_probe import read_cost_ledger
from scripts.model_request_diagnostics import record_model_response

ENDPOINT = 'https://www.rightapi.ai/v1'
MODEL = 'glm-5.3-flash'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def profile():
    if (os.environ.get('LLM_API_BASE', '').rstrip('/') != ENDPOINT
            or os.environ.get('AGENT_MODEL') != MODEL
            or not os.environ.get('LLM_API_KEY')):
        raise ValueError('Expected the dedicated RightAPI GLM test profile')


def historical_input(ledger_path, number):
    ledger = read_cost_ledger(ledger_path)
    if type(number) is not int or not 1 <= number <= len(ledger['requests']):
        raise ValueError('Historical request number is invalid')
    row = ledger['requests'][number - 1]
    input_path = (ledger_path.parent / row['input_file']).resolve()
    if not input_path.is_relative_to(ledger_path.parent.resolve()):
        raise ValueError('Historical input must stay within the prior run')
    if row.get('status') != 'ReadTimeout' or sha(input_path) != row.get('input_sha256'):
        raise ValueError('Expected an unchanged historical timeout input')
    body = json.loads(input_path.read_text(encoding='utf-8'))
    if (body.get('model') != MODEL or type(body.get('max_tokens')) is not int
            or body['max_tokens'] != 256 or body.get('stream') is not False
            or not isinstance(body.get('messages'), list) or not body['messages']
            or not isinstance(body.get('tools'), list) or not body['tools']
            or set(body) - {'model', 'max_tokens', 'messages', 'tools', 'tool_choice',
                            'parallel_tool_calls', 'stream', 'temperature'}):
        raise ValueError('Historical model request does not match the bounded replay')
    return input_path, body


def replay_body(body, schema_variant):
    if schema_variant not in ('original', 'hypothesis_only'):
        raise ValueError('Unsupported replay schema variant')
    result = deepcopy(body)
    if schema_variant == 'hypothesis_only':
        if (len(result['tools']) != 1
                or result['tools'][0].get('function', {}).get('name') != 'InvestigationDecision'
                or result.get('tool_choice') != {'type': 'function', 'function': {'name': 'InvestigationDecision'}}):
            raise ValueError('Minimal schema control requires the historical decision tool')
        result['tools'][0]['function']['parameters'] = {
            'type': 'object', 'properties': {'hypothesis': {'type': 'string'}},
            'required': ['hypothesis']}
    return result


def prepare(ledger_path, number, supplement_path, output, *, timeout_seconds=60, schema_variant='original',
            user_agent_variant='httpx'):
    profile()
    if user_agent_variant not in ('httpx', 'agent'):
        raise ValueError('Unsupported replay User-Agent variant')
    if type(timeout_seconds) is not int or timeout_seconds not in (60, 120):
        raise ValueError('Replay timeout must be 60 or 120 seconds')
    ledger_path, supplement_path = Path(ledger_path).resolve(), Path(supplement_path).resolve()
    input_path, original_body = historical_input(ledger_path, number)
    body = replay_body(original_body, schema_variant)
    supplement = json.loads(supplement_path.read_text(encoding='utf-8'))
    attribution = supplement.get('user_authorized_cost_attribution', {})
    if (attribution.get('amount_display_currency') != '0.104769'
            or attribution.get('currency_symbol') != '$'
            or attribution.get('method') != 'entire_account_cumulative_amount_as_user_accepted_estimate'
            or attribution.get('exact_scenario_bill_verified') is not False):
        raise ValueError('Expected the separately recorded user-accepted historical estimate')
    refs = [ledger_path, input_path, supplement_path, Path(__file__).resolve(),
            ROOT / 'scripts/model_request_diagnostics.py', ROOT / 'scripts/with_agent_test_env.py',
            ROOT / 'scripts/evaluate_windows_probe.py', ROOT / 'src/agent/aiops_llm.py']
    plan = {'version': 1, 'purpose': 'historical_request_transport_diagnostic',
        'endpoint': ENDPOINT, 'model': MODEL, 'max_attempts': 1, 'timeout_seconds': timeout_seconds,
        'max_output_tokens': 256, 'previous_cost': str(ledger_path), 'request_number': number,
        'input_file': str(input_path), 'cost_supplement': str(supplement_path),
        'source_sha256': {str(p): sha(p) for p in refs},
        'historical_estimate': attribution, 'diagnosis_evaluated': False,
        'tools_executed': False, 'new_supplier_bill_cny': None}
    plan['schema_variant'] = schema_variant
    plan['user_agent_variant'] = user_agent_variant
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    if schema_variant != 'original':
        # Derived from the already redacted historical input; never a new live prompt.
        write(output / 'request.json', body)
        plan['derived_input_sha256'] = sha(output / 'request.json')
    path = output / 'plan.json'
    write(path, plan)
    # Bind the reviewed local plan too; changed parameters require new preparation.
    (output / 'plan.sha256').write_text(sha(path), encoding='ascii')
    return path


async def execute(plan_path, *, transport=None):
    import httpx
    profile()
    plan_path = Path(plan_path).resolve()
    if sha(plan_path) != (plan_path.parent / 'plan.sha256').read_text(encoding='ascii'):
        raise ValueError('Prepared plan has changed')
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    if (plan['endpoint'] != ENDPOINT or plan['model'] != MODEL or plan['max_attempts'] != 1
            or type(plan['timeout_seconds']) is not int
            or plan['timeout_seconds'] not in (60, 120) or plan['max_output_tokens'] != 256):
        raise ValueError('Prepared replay limits have changed')
    if any(sha(path) != value for path, value in plan['source_sha256'].items()):
        raise ValueError('Historical sources or replay implementation changed; prepare again')
    input_path, body = historical_input(Path(plan['previous_cost']), plan['request_number'])
    if str(input_path) != plan['input_file']:
        raise ValueError('Historical input reference changed')
    schema_variant = plan.get('schema_variant', 'original')
    user_agent_variant = plan.get('user_agent_variant', 'httpx')
    if user_agent_variant not in ('httpx', 'agent'):
        raise ValueError('Unsupported replay User-Agent variant')
    body = replay_body(body, schema_variant)
    if schema_variant != 'original':
        derived = plan_path.parent / 'request.json'
        if (sha(derived) != plan['derived_input_sha256']
                or json.loads(derived.read_text(encoding='utf-8')) != body):
            raise ValueError('Derived replay input changed; prepare again')
    result_path = plan_path.parent / 'attempt.json'
    row = {'number': 1, 'purpose': plan['purpose'], 'status': 'reserved',
        'previous_cost': plan['previous_cost'], 'historical_request_number': plan['request_number'],
        'input_sha256': sha(input_path), 'model': MODEL, 'pricing_verified': False,
        'timeout_seconds': plan['timeout_seconds'],
        'schema_variant': schema_variant,
        'user_agent_variant': user_agent_variant,
        'supplier_bill_cny': None, 'diagnosis_evaluated': False, 'tools_executed': False}
    row['replay_input_sha256'] = (plan.get('derived_input_sha256') or sha(input_path))
    # Match the original evaluation transport's JSON serialization.
    wire_body = json.dumps(body).encode()
    row['wire_body_sha256'] = hashlib.sha256(wire_body).hexdigest()
    headers = {'Authorization': 'Bearer ' + os.environ['LLM_API_KEY'],
               'Content-Type': 'application/json'}
    if user_agent_variant == 'agent':
        headers['User-Agent'] = 'Python-urllib/3.13'
    # Exclusive creation consumes this plan even on a crash; never silently resend.
    with result_path.open('x', encoding='utf-8') as f:
        json.dump(row, f, ensure_ascii=False, indent=2)
    def save():
        write(result_path, row)
    class DiagnosticTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = transport if transport is not None else httpx.AsyncHTTPTransport(retries=0)
            self.sent = False
        async def handle_async_request(self, request):
            if self.sent or str(request.url) != ENDPOINT + '/chat/completions':
                raise RuntimeError('Only one request to the prepared endpoint is allowed')
            self.sent = True
            row['user_agent'] = request.headers.get('user-agent')
            return await record_model_response(self.inner, request, row, save)
        async def aclose(self):
            await self.inner.aclose()
    try:
        async with httpx.AsyncClient(transport=DiagnosticTransport(), timeout=plan['timeout_seconds'], follow_redirects=False) as client:
            response = await client.post(ENDPOINT + '/chat/completions', content=wire_body,
                headers=headers)
            # HTTP200 is transport success only; do not parse/execute returned tool calls.
            return 0 if response.status_code == 200 else 1
    except Exception as exc:
        row['error_type'] = type(exc).__name__
        save()
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Paid: consume a prepared plan once')
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--previous-cost', type=Path)
    parser.add_argument('--request-number', type=int)
    parser.add_argument('--cost-supplement', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--timeout-seconds', type=int, choices=(60, 120),
                        help='Preparation only; defaults to 60 seconds')
    parser.add_argument('--schema-variant', choices=('original', 'hypothesis_only'),
                        help='Preparation only; defaults to unchanged historical schema')
    parser.add_argument('--user-agent-variant', choices=('httpx', 'agent'),
                        help='Preparation only; change only User-Agent to match the Agent factory')
    args = parser.parse_args(argv)
    if args.execute:
        if not args.plan or any((args.previous_cost, args.request_number, args.cost_supplement, args.output_dir, args.timeout_seconds, args.schema_variant, args.user_agent_variant)):
            parser.error('--execute requires only --plan')
        result = asyncio.run(execute(args.plan))
        print(json.dumps({'attempt_record': str(args.plan.parent / 'attempt.json'), 'exit_code': result}))
        return result
    if args.plan or not all((args.previous_cost, args.request_number, args.cost_supplement, args.output_dir)):
        parser.error('preparation requires previous cost, request number, cost supplement and output directory')
    path = prepare(args.previous_cost, args.request_number, args.cost_supplement, args.output_dir,
                   timeout_seconds=args.timeout_seconds if args.timeout_seconds is not None else 60,
                   schema_variant=args.schema_variant or 'original',
                   user_agent_variant=args.user_agent_variant or 'httpx')
    print(json.dumps({'prepared_plan': str(path), 'model_calls': 0, 'max_attempts': 1}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
