"""Check actual spawn cache hits, recovered bytes/modes and fresh test execution."""
import hashlib
import json
import os
from pathlib import Path
import sys

phase, case, token, seed, logs, results = sys.argv[1:]
logs, results = Path(logs), Path(results)
text = (logs / (case + '.execution.json')).read_text()
decoder, actions = json.JSONDecoder(), []
while text.strip():
    row, end = decoder.raw_decode(text.lstrip())
    text = text.lstrip()[end:]
    actions.append(row)

def selected(mnemonic):
    return [row for row in actions if row.get('mnemonic') == mnemonic]

restore, graph = selected('MSBuildGraphRestore'), selected('MSBuildGraph')
report = json.loads(Path('bazel-bin/graph.graph/report.json').read_text())
artifact = Path('bazel-bin/graph.graph/workspace')
files = {str(p.relative_to(artifact)): {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'mode': p.stat().st_mode & 0o777}
         for p in sorted(artifact.rglob('*')) if p.is_file() and not p.name.endswith('.AssemblyReference.cache')}
contract = json.loads(Path('graph.generated.json').read_text())
omitted = sorted({path for project in contract['Projects'].values()
                  for variant in project.get('Configurations') or [project]
                  for path in variant.get('ReplayOmissions', [])})
if os.environ.get('COMPLETE_REPLAY_OMISSIONS') == '1':
    assert len(omitted) == 6, 'Expected both SDK intermediates for all three compilations'
assert not set(omitted) & files.keys(), 'Optional intermediates were published'
assert report['preparedRestore'] and files
for project in ['src/Library', 'src/App', 'tests/Tests']:
    assert (artifact / project / 'obj/Release/net10.0/import-state.txt').read_text().strip() == 'True', 'Authored import-list entry was lost'
assert any(not row.get('cacheHit') for row in selected('TestRunner')), 'Tests must execute afresh'
if phase == 'producer':
    assert len(restore) == len(graph) == 1 and not restore[0].get('cacheHit') and not graph[0].get('cacheHit'), [(r.get('mnemonic'), r.get('cacheHit'), r.get('runner')) for r in restore + graph]
    assert (report['hits'], report['misses']) == (0, 3), report
else:
    expected = json.loads(Path(seed).read_text())
    assert omitted == expected.get('omittedIntermediates', []), 'Different replay contract'
    if case in ['consumer', 'project-recovery']:
        assert files == expected['files'], 'Recovered bytes/modes differ'
        assert len(restore) == 1 and restore[0].get('cacheHit') and restore[0]['runner'] == 'remote cache hit', restore
        assert len(graph) == 1, graph
    if case == 'consumer':
        assert graph[0].get('cacheHit') and graph[0]['runner'] == 'remote cache hit', graph
        # The report came from the producer's whole-action result, not a fresh plugin run.
        assert (report['hits'], report['misses']) == (0, 3), report
    elif case == 'project-recovery':
        assert not graph[0].get('cacheHit') and (report['hits'], report['misses']) == (3, 0), report
    elif case == 'body':
        assert not any(not row.get('cacheHit') for row in restore), restore
        assert len(graph) == 1 and not graph[0].get('cacheHit') and (report['hits'], report['misses']) == (2, 1), report
        assert files['src/Library/bin/Release/net10.0/Library.dll'] != expected['files']['src/Library/bin/Release/net10.0/Library.dll']
        assert files['src/Library/obj/Release/net10.0/ref/Library.dll'] == expected['files']['src/Library/obj/Release/net10.0/ref/Library.dll']
    elif case == 'api':
        assert not any(not row.get('cacheHit') for row in restore), restore
        assert len(graph) == 1 and not graph[0].get('cacheHit') and (report['hits'], report['misses']) == (0, 3), report
        assert files['src/Library/obj/Release/net10.0/ref/Library.dll'] != expected['files']['src/Library/obj/Release/net10.0/ref/Library.dll']
record = {'omittedIntermediates': omitted, 'token': token, 'case': case, 'files': files, 'hits': report['hits'], 'misses': report['misses'],
          'restore': [{'cacheHit': r.get('cacheHit', False), 'runner': r['runner']} for r in restore],
          'graph': [{'cacheHit': r.get('cacheHit', False), 'runner': r['runner']} for r in graph]}
results.mkdir(parents=True, exist_ok=True)
(results / (case + '.json')).write_text(json.dumps(record, indent=2) + '\n')
print('PASS:', case, record['restore'], record['graph'], 'plugin', report['hits'], report['misses'], 'files', len(files))
