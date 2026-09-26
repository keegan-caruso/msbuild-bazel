"""Body, API and declared-resource edits after independent generated-graph recovery."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

p = argparse.ArgumentParser(description=__doc__)
for name in ['workspace', 'base', 'seed', 'out']:
    p.add_argument(name, type=Path)
p.add_argument('--family', choices=['http', 'immutable'], required=True)
p.add_argument('--cache', required=True)
a = p.parse_args()
w, base, out = a.workspace.resolve(), a.base.resolve(), a.out.resolve()
out.mkdir(parents=True, exist_ok=False)
seed = json.loads(a.seed.read_text())
target = '//:' + ('src_Http_Http.Abstractions_test_Microsoft.AspNetCore.Http.Abstractions.Tests_net10_0' if a.family == 'http' else 'src_libraries_System.Collections.Immutable_tests_System.Collections.Immutable.Tests_net10_0')
if a.family == 'http':
    directory = 'src/Http/Http.Abstractions/src/'
    source = w / (directory + 'QueryString.cs')
    contract = w / (directory + 'PublicAPI.Unshipped.txt')
    resource = w / (directory + 'Resources.resx')
    assembly = 'Microsoft.AspNetCore.Http.Abstractions'
    producer = '//:src_Http_Http.Abstractions_src_' + assembly + '_net10_0'
    reference_producer = producer
    body = source
    needle, replacement = 'return ToUriComponent();', 'GC.KeepAlive("remote-body-control"); return ToUriComponent();'
else:
    directory = 'src/libraries/System.Collections.Immutable/'
    source = w / (directory + 'src/System/Collections/Immutable/ImmutableArray_1.cs')
    contract = w / (directory + 'ref/System.Collections.Immutable.cs')
    resource = w / (directory + 'src/Resources/Strings.resx')
    assembly = 'System.Collections.Immutable'
    producer = '//:src_libraries_System.Collections.Immutable_src_System.Collections.Immutable_net10_0'
    reference_producer = '//:src_libraries_System.Collections.Immutable_ref_System.Collections.Immutable_net10_0'
    body = w / (directory + 'src/Validation/Requires.cs')
    needle, replacement = 'throw new ArgumentNullException(parameterName);', 'GC.KeepAlive("remote-body-control"); throw new ArgumentNullException(parameterName);'
original = {path: path.read_bytes() for path in {source, contract, resource, body}}
start = [os.environ['RULES_MSBUILD_BAZEL'], '--host_jvm_args=-Xmx1536m', '--output_base=' + str(base), '--ignore_all_rc_files']
flags = ['--jobs=2', '--disk_cache=', '--remote_cache=' + a.cache, '--remote_upload_local_results=false', '--remote_download_outputs=all']
reference = w / 'bazel-bin' / (reference_producer.split(':')[1] + '.reference') / (assembly + '.dll')
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
baseline = digest(reference)
ns = {'t': 'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
def outcomes():
    result = Counter((r.get('testName'), r.get('outcome')) for r in ET.parse(w / 'bazel-testlogs' / target.split(':')[1] / 'test.outputs/results.trx').findall('.//t:UnitTestResult', ns))
    if a.family == 'immutable':
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'explicit_msbuild/runtime'))
        from case_names import normalized
        return normalized(result)
    return result
expected = outcomes()
original_targets = {r['targetLabel'] for r in seed['actions'] if r['mnemonic'] == 'MSBuildAssembly'}
rows = []
def test(name, changed, changed_reference=False):
    execution = out / (name + '.execution.json'); bep = out / (name + '.bep')
    with (out / (name + '.log')).open('w') as log:
        result = subprocess.run(start + ['test', target, *flags, '--execution_log_json_file=' + str(execution), '--build_event_json_file=' + str(bep)], cwd=w, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
    assert result.returncode == 0, name
    text = execution.read_text(); decoder = json.JSONDecoder(); offset = 0; actions = []
    while offset < len(text):
        if text[offset].isspace(): offset += 1; continue
        row, offset = decoder.raw_decode(text, offset); actions.append(row)
    rebuilt = {r['targetLabel'] for r in actions if r.get('mnemonic') == 'MSBuildAssembly' and not r.get('cacheHit')}
    if changed:
        assert producer in rebuilt, (name, rebuilt)
        assert original_targets - rebuilt, 'No unrelated assemblies remained cached'
    else:
        assert not rebuilt, rebuilt
    events = [json.loads(line) for line in bep.read_text().splitlines()]
    tests = [e['testResult'] for e in events if 'testResult' in e]
    assert len(tests) == 1
    if name in ['body', 'api']:
        assert not tests[0].get('cachedLocally') and not tests[0].get('executionInfo', {}).get('cachedRemotely')
    assert (digest(reference) != baseline) == changed_reference
    assert outcomes() == expected
    if a.family == 'immutable':
        binary = w / 'bazel-bin' / (producer.split(':')[1] + '.runtime') / (assembly + '.dll')
        probes = list((w / 'bazel-testlogs' / target.split(':')[1] / 'test.outputs').glob('loaded-source-*.json'))
        assert probes and all(json.loads(p.read_text())['sha256'] == digest(binary).upper() for p in probes)
    rows.append(dict(case=name, rebuilt=sorted(rebuilt), otherAssembliesReused=sorted(original_targets - rebuilt), referenceChanged=changed_reference))
    (out / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(name, 'rebuilt', len(rebuilt), 'other assemblies reused', len(original_targets - rebuilt), flush=True)

def restore():
    for path, data in original.items(): path.write_bytes(data)

try:
    text = body.read_text(); assert needle in text
    body.write_text(text.replace(needle, replacement, 1))
    test('body', True)
    restore(); test('body-restored', False)
    if a.family == 'http':
        needle_api = 'public readonly struct QueryString : IEquatable<QueryString>\n{'
        text = source.read_text(); assert needle_api in text
        source.write_text(text.replace(needle_api, needle_api + '\n    /// <summary>Remote cache API probe.</summary>\n    public bool RemoteCacheProbe => HasValue;\n', 1))
        contract.write_text(contract.read_text() + '\nMicrosoft.AspNetCore.Http.QueryString.RemoteCacheProbe.get -> bool\n')
    else:
        pattern = r'(public readonly partial struct ImmutableArray<T>[^\n]*\n\s*\{)'
        for path, member in [(source, '/// <summary>Remote cache API probe.</summary>\n        public bool RemoteCacheProbe => IsEmpty;'), (contract, 'public bool RemoteCacheProbe { get { throw null; } }')]:
            text, count = re.subn(pattern, lambda m: m[1] + '\n        ' + member, path.read_text(), count=1)
            assert count == 1; path.write_text(text)
    test('api', True, True)
    restore(); test('api-restored', False)
    text = resource.read_text(); assert '</root>' in text
    resource.write_text(text.replace('</root>', '<!-- declared input cache probe -->\n</root>'))
    test('resource', True)
    restore(); test('resource-restored', False)
finally:
    restore()
    subprocess.run(start + ['shutdown'], cwd=w, check=True)
