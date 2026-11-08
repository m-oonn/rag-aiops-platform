"""Verify the 034 -> ... -> current-round budget ledger inheritance chain.

Read-only. The plan requires each real round to inherit the newest ledger with identical
hash, row count and historical unknown items, and to get its own fresh 5 CNY cap rather
than sharing the historical reservation.

The round comes from the command line (``--round-dir``) or from ``$AIOPS_ROUND_DIR``,
falling back to the newest round that actually ran, so this one file keeps working for
every later round: it walks runtime/aiops-goal-034 ... runtime/aiops-goal-<that round>.
"""
import hashlib
import json
from pathlib import Path

from rounddir import ROOT, round_dir

CUR = round_dir().name                              # e.g. aiops-goal-050
NAMES = []
_candidates = sorted(p.name for p in (ROOT / 'runtime').glob('aiops-goal-0*')
                     if p.is_dir() and (p / 'product-model/cost.json').exists())
for name in _candidates:
    number = name.split('-')[-1]
    if not number.isdigit() or len(number) != 3:
        continue
    if int(number) < 34:
        continue
    NAMES.append(number)
    if name == CUR:
        break
if not NAMES or f'aiops-goal-{NAMES[-1]}' != CUR:
    raise SystemExit(f'cannot walk the ledger chain up to {CUR}')

LEDGERS = {name: ROOT / f'runtime/aiops-goal-{name}/product-model/cost.json' for name in NAMES}
MANIFEST = ROOT / f'runtime/{CUR}/product-model/run-budget.json'
PREVIOUS = NAMES[-2]

# historical reservations, kept as an independent expectation set (the value a round
# published must never be rewritten by later rounds)
EXPECTED_RESERVED = {
    '034': 46.82155, '035': 46.82155, '036': 47.655306, '037': 48.575392,
    '038': 49.370096, '039': 49.983634, '040': 50.759848, '041': 51.429662,
    '042': 52.077212, '043': 52.436218, '044': 53.027216,
}
EXPECTED_ADDED = {'035': 0, '036': 17, '037': 17, '038': 15, '039': 14,
                  '040': 15, '041': 13, '042': 14, '043': 9, '044': 12}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n'


def load(path):
    data = path.read_bytes()
    return {'path': str(path), 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest(),
            'content': json.loads(data.decode('utf-8'))}


ledgers = {name: load(path) for name, path in LEDGERS.items()}
manifest = load(MANIFEST)

previous = ledgers[PREVIOUS]['content']
inherited = len(previous['requests'])
current = ledgers[NAMES[-1]]['content']

rows = {name: ledgers[name]['content']['requests'][:inherited] for name in (PREVIOUS, NAMES[-1])}
equivalent = canonical(rows[PREVIOUS]) == canonical(rows[NAMES[-1]])

base = len(ledgers['034']['content']['requests'])
history = {name: ledgers[name]['content']['requests'][:base] for name in NAMES}
history_equivalent = len({canonical(history[name]) for name in NAMES}) == 1

unknown = {name: [r['number'] for r in ledgers[name]['content']['requests']
                  if (r.get('usage') or {}).get('total_tokens') is None]
           for name in NAMES}
reserved = {name: ledgers[name]['content']['reserved_cny'] for name in NAMES}
row710 = {name: [r for r in ledgers[name]['content']['requests'] if r['number'] == 710][0]
          for name in NAMES}

own_baseline = {'034': 0}
for previous_name, name in zip(NAMES, NAMES[1:]):
    own_baseline[name] = len(ledgers[previous_name]['content']['requests'])
added = {name: len(ledgers[name]['content']['requests']) - own_baseline[name] for name in NAMES}
round_spent = round(current['reserved_cny'] - reserved[PREVIOUS], 6)

reserved_ok = all(reserved[name] == value for name, value in EXPECTED_RESERVED.items())
added_ok = all(added[name] == value for name, value in EXPECTED_ADDED.items())

checks = {
    'round': NAMES[-1],
    'chain': NAMES,
    'inherited_rows': inherited,
    'history_rows_checked': base,
    'ledger_sha256': {name: ledgers[name]['sha256'] for name in NAMES},
    'ledger_bytes': {name: ledgers[name]['bytes'] for name in NAMES},
    'ledger_rows': {name: len(ledgers[name]['content']['requests']) for name in NAMES},
    'reserved_cny': reserved,
    'unknown_usage_rows': unknown,
    'row710_reserved_cny': {name: row710[name]['reserved_cny'] for name in NAMES},
    f'rows_1_to_inherited_byte_identical_{PREVIOUS}_{NAMES[-1]}': equivalent,
    f'rows_1_to_history_byte_identical_all_{len(NAMES)}': history_equivalent,
    'rows_added_per_round': added,
    'expected_reserved_cny_match': reserved_ok,
    'expected_rows_added_match': added_ok,
    'round_spent_cny': round_spent,
    'manifest': {'bytes': manifest['bytes'], 'sha256': manifest['sha256'],
                 'content': manifest['content']},
    'chain_equivalent': bool(
        equivalent
        and history_equivalent
        and len({tuple(unknown[name]) for name in NAMES}) == 1
        and unknown[NAMES[-1]] == [710]
        and reserved_ok
        and added_ok
        and reserved['035'] == reserved['034']
        and row710[NAMES[-1]]['reserved_cny'] == row710['034']['reserved_cny'] == 0.092916
        and added[NAMES[-1]] >= 1
        and 0 <= round_spent <= 5
        and manifest['content']['inherited_requests'] == inherited
        and manifest['content']['inherited_reserved_cny'] == reserved[PREVIOUS]
        and manifest['content']['run_limit_cny'] == 5
        and manifest['content']['previous_sha256'] == ledgers[PREVIOUS]['sha256']
    ),
    'purpose': (f'prove {NAMES[-1]} inherited the same {inherited} historical rows, unknown item '
                f'and reservation as the {PREVIOUS} ledger, with its own fresh 5 CNY run cap'),
}

out = ROOT / f'runtime/{CUR}/chain-equivalence.json'
out.write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: checks[k] for k in ('round', 'chain_equivalent', 'inherited_rows',
                                         'rows_added_per_round', 'round_spent_cny',
                                         f'rows_1_to_history_byte_identical_all_{len(NAMES)}')},
                 ensure_ascii=False, indent=1))
print('written:', out)
if not checks['chain_equivalent']:
    raise SystemExit('ledger inheritance chain is not equivalent; gate B evidence is incomplete')
