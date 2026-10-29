import hashlib
import json

import pytest
from scripts.verify_free_demo import verify_bundle


@pytest.mark.parametrize('mutation', [None, 'artifact', 'source', 'missing', 'escape', 'changed', 'failed'])
def test_demo_bundle_rejects_changes_missing_artifacts_and_unsafe_paths(tmp_path, mutation):
    def write(name, data):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding='utf-8')
        return hashlib.sha256(path.read_bytes()).hexdigest()
    sources = {'scripts/demo.py': hashlib.sha256(b'print(1)').hexdigest()}
    artifacts = {}
    for phase in ('before', 'after'):
        write(phase + '/source-snapshot/scripts/demo.py', 'print(1)')
        artifacts[phase + '/source.json'] = write(phase + '/source.json', json.dumps({'sources': sources}))
    for name in ('controller/summary.json', 'controller/observation-boundary/report.json',
            'failure/summary.json', 'failure/observation-boundary/report.json', 'historical-api.xml'):
        artifacts[name] = write(name, '{}')
    record = {'status': 'completed', 'source_unchanged': True, 'artifacts_sha256': artifacts}
    if mutation == 'artifact': write('controller/summary.json', 'changed')
    if mutation == 'source': write('before/source-snapshot/scripts/demo.py', 'print(2)')
    if mutation == 'missing': del artifacts['historical-api.xml']
    if mutation == 'escape': artifacts['../outside.json'] = 'bad'
    if mutation == 'changed': record['source_unchanged'] = False
    if mutation == 'failed': record['status'] = 'failed'
    write('manifest.json', json.dumps(record))
    before = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    if mutation:
        with pytest.raises(ValueError):
            verify_bundle(tmp_path)
    else:
        assert verify_bundle(tmp_path)['source_files'] == 1
    assert before == {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
