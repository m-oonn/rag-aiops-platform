"""Read-only: dump the 037 report text and its section headings for Gate-B review."""
import json
import re
import sqlite3
from pathlib import Path
from rounddir import round_dir

D = round_dir()
con = sqlite3.connect(f'file:{(D / "product/runs.sqlite").as_posix()}?mode=ro', uri=True)
report = con.execute('select report from aiops_runs').fetchone()[0] or ''
con.close()

lines = [ln.rstrip() for ln in report.splitlines()]
headings = [ln for ln in lines if ln and (ln.startswith('#') or re.match(r'^\*\*?.{0,20}\*\*?[:：]?$', ln)
                                          or re.match(r'^[一二三四五六七八九十]+[、.]', ln))]
evidence_ids = sorted(set(re.findall(r'ev-[0-9a-f]{32}', report)))
(D / 'report.txt').write_text(report, encoding='utf-8')
record = {
    'chars': len(report),
    'headings': headings,
    'evidence_ids_cited': len(evidence_ids),
    'evidence_ids': evidence_ids,
    'mentions_root_cause_line': '已确认直接原因' in report,
    'mentions_impact': any(k in report for k in ('影响范围', '影响')),
    'mentions_remediation': any(k in report for k in ('处理建议', '处理')),
    'mentions_retest': any(k in report for k in ('复测', '验证')),
    'mentions_unknowns': any(k in report for k in ('剩余未知', '未知')),
    'mentions_validation_notes': '校验提示' in report,
}
(D / 'report-headings.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(record, ensure_ascii=False, indent=1))
print('--- first 60 lines ---')
print('\n'.join(lines[:60]))
