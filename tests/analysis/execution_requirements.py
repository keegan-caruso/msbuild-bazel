"""Check execution requirements, which Bazel's Starlark Action API omits."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
version = subprocess.check_output(['bash', 'scripts/bazel.sh', '--version'], cwd=ROOT, text=True).strip()
expected = 'bazel ' + os.environ.get('USE_BAZEL_VERSION', (ROOT/'.bazelversion').read_text().strip())
assert version in (expected, expected + '- (@non-git)'), (version, expected)
print('Checking execution requirements with ' + version)
result = subprocess.check_output([
    'bash', 'scripts/bazel.sh', 'aquery',
    'mnemonic("MSBuild(Assembly|NugetExtract)", set(//tests/analysis:root //tests/analysis:worker //tests/analysis:package))',
    '--output=jsonproto', '--lockfile_mode=off',
], cwd=ROOT, text=True)
graph = json.loads(result)
labels = {row['id']: row['label'] for row in graph['targets']}
expected = {
    '//tests/analysis:root': {'no-sandbox': '1', 'no-remote-exec': '1'},
    '//tests/analysis:worker': {'no-sandbox': '1', 'supports-workers': '1', 'requires-worker-protocol': 'json'},
    '//tests/analysis:package': {'block-network': '1', 'no-remote-exec': '1'},
}
seen = set()
for action in graph['actions']:
    label = labels[action['targetId']]
    if label in expected:
        actual = {row['key']: row['value'] for row in action.get('executionInfo', [])}
        assert actual == expected[label], (label, actual)
        seen.add(label)
assert seen == expected.keys(), seen
print('Execution requirements passed')
