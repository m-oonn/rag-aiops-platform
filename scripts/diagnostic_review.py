"""Prepare/check local human review packets; never invoke models or award correctness."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import verify_windows_local_faults as controller
from src.probe.protocol import redact

VERDICTS = {
    'diagnosis': ['correct_localization', 'correct_healthy_within_scope', 'honest_unlocated',
                  'wrong_cause_or_false_positive', 'incomplete'],
    'citation_support': ['supported', 'unsupported', 'insufficient'],
    'recommendation': ['appropriate', 'inappropriate', 'insufficient', 'not_applicable'],
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(source, output, case=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    audit_path = source / 'output-audit.json'
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding='utf-8'))
        summary = {'diagnosis': audit['refreshed']['diagnosis'],
                   'has_final_report': bool(audit['refreshed']['report'])}
        events, trace = audit['events'], []
        case, mode = audit['case'], audit['mode']
        report = audit['refreshed']['report']
        files = [audit_path]
    else:
        if not case:
            raise ValueError('controller case is required for a model run')
        files = [source / name for name in ('summary.json', 'events.json', 'tool_trace.json', 'report.txt')]
        summary, events, trace = [json.loads(path.read_text(encoding='utf-8')) for path in files[:3]]
        report, mode = files[3].read_text(encoding='utf-8'), 'model_run_requires_human_review'
    diagnosis = summary.get('diagnosis') or {}
    refs = diagnosis.get('evidence', []) + [ref for item in diagnosis.get('recommendations', [])
                                           for ref in item.get('evidence', [])]
    evidence = controller._load_review_evidence_text(source, refs)
    files += [source / 'runs.sqlite'] if (source / 'runs.sqlite').exists() else []
    files += [source / 'evidence' / (key + '.json') for key in evidence]
    hashes = {str(path): digest(path) for path in files}
    checks = controller.review_model_artifacts(source, case, summary, events=events, trace=trace)
    packet = {'report': report,
              'diagnosis': {key: value for key, value in diagnosis.items()
                            if key not in {'mechanism_config', 'mechanisms'}},
              'evidence': {key: redact(json.loads(text)) for key, text in evidence.items()}}
    # Keep scenario/group and mechanical hints apart from the first-pass semantic review.
    output.mkdir(parents=True, exist_ok=False)
    def save(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    save('review-packet.json', packet)
    record = {'reviewer': '', 'reviewed_at': '',
        'packet_sha256': digest(output / 'review-packet.json'),
        'dimensions': {key: {'verdict': 'pending', 'reason': '', 'evidence_ids': [], 'allowed': allowed}
                       for key, allowed in VERDICTS.items()}}
    save('manual-review.json', record)
    save('source-audit.json', {'case': case, 'mode': mode, 'source_hashes': hashes,
        'packet_sha256': record['packet_sha256'], 'mechanical_review': checks,
        'tool_trace_available': bool(trace), 'human_review_completed': False})
    return checks


def check(directory):
    directory = Path(directory)
    audit = json.loads((directory / 'source-audit.json').read_text(encoding='utf-8'))
    packet = json.loads((directory / 'review-packet.json').read_text(encoding='utf-8'))
    record = json.loads((directory / 'manual-review.json').read_text(encoding='utf-8'))
    if (record.get('packet_sha256') != audit['packet_sha256']
            or digest(directory / 'review-packet.json') != audit['packet_sha256']
            or any(not Path(path).is_file() or digest(Path(path)) != expected
                   for path, expected in audit['source_hashes'].items())):
        raise ValueError('review source or packet changed; prepare a new review')
    dimensions = record.get('dimensions', {})
    for key, allowed in VERDICTS.items():
        item = dimensions.get(key, {})
        if item.get('verdict') not in ['pending', *allowed]:
            raise ValueError('invalid verdict: ' + key)
        if item['verdict'] == 'pending':
            continue
        ids = item.get('evidence_ids')
        if (not record.get('reviewer', '').strip() or not record.get('reviewed_at', '').strip()
                or not item.get('reason', '').strip() or not isinstance(ids, list)
                or any(eid not in packet['evidence'] for eid in ids)):
            raise ValueError('reviewer, date, reason and valid evidence ids are required: ' + key)
        if item['verdict'] in {'correct_localization', 'correct_healthy_within_scope', 'supported', 'appropriate'} and not ids:
            raise ValueError('positive verdict requires evidence: ' + key)
        if key == 'recommendation' and item['verdict'] == 'not_applicable' and packet['diagnosis'].get('recommendations'):
            raise ValueError('existing recommendations require an applicability review')
    pending = [key for key in VERDICTS if dimensions[key]['verdict'] == 'pending']
    return {'review_status': 'pending' if pending else 'recorded', 'pending_dimensions': pending,
            'verdicts': {key: dimensions[key]['verdict'] for key in VERDICTS},
            'review_is_human_assertion': True, 'automatically_verified_correctness': False,
            'mode': audit['mode'], 'mechanical_review': audit['mechanical_review']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare_parser = sub.add_parser('prepare')
    prepare_parser.add_argument('source', type=Path)
    prepare_parser.add_argument('--output', type=Path, required=True)
    prepare_parser.add_argument('--case')
    sub.add_parser('check').add_argument('directory', type=Path)
    args = parser.parse_args()
    result = prepare(args.source, args.output, args.case) if args.command == 'prepare' else check(args.directory)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
