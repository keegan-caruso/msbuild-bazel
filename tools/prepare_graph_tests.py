"""Explicit test-data publication; no implicit approval-file discovery."""
import hashlib
import json
from pathlib import Path
import shutil


def add_tests(workspace, output, nodes, tests, root):
    if not tests: return ''
    shutil.copyfile(root / 'bazel/graph_test.bzl', output / 'graph_test.bzl')
    (output / 'test-runner').mkdir()
    for suffix in ('.dll', '.deps.json', '.runtimeconfig.json'):
        shutil.copyfile(root / ('tools/TestRunner/bin/Release/net10.0/TestRunner' + suffix), output / ('test-runner/TestRunner' + suffix))
    declarations = []
    seen = set()
    build = ''
    for test in tests:
        identity = test['node']
        if identity not in nodes or identity in seen: raise ValueError('missing or duplicate test node')
        seen.add(identity)
        node = nodes[identity]
        expected = test['expectedTests']
        if not expected or len(set(expected)) != len(expected) or any(not isinstance(name, str) or not name for name in expected):
            raise ValueError('expectedTests must contain unique test names')
        data, hashes = [], {}
        for logical in test['data']:
            path = Path(logical)
            if path.is_absolute() or '..' in path.parts or '\\' in logical or logical != path.as_posix() or not logical:
                raise ValueError('unsafe declared test data path')
            source = workspace / path
            if not source.is_file() or not source.resolve().is_relative_to(workspace):
                raise ValueError('missing or escaping test data: ' + logical)
            if logical in hashes: raise ValueError('duplicate declared test data')
            target = output / 'test-data' / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            data.append('test-data/' + logical)
            hashes[logical] = hashlib.sha256(source.read_bytes()).hexdigest()
        directory = node['execution']['outputDirectory'].removeprefix('workspace/')
        assemblies = [item['path'] for item in node['outputs'] if item['kind'] == 'assembly']
        if len(assemblies) != 1 or str(Path(assemblies[0]).parent) != 'workspace/' + directory:
            raise ValueError('test node requires exactly one assembly in its runtime output directory')
        assembly = Path(assemblies[0]).name
        attrs = dict(name='test_' + identity, subject=':node_' + identity,
            project=node['project'].removeprefix('workspace/'), global_properties=node['globalProperties'],
            runtime_directory=directory, assembly=assembly, data=data, data_hashes=hashes, expected_tests=expected,
            runner='test-runner/TestRunner.dll', runner_support=['test-runner/TestRunner.deps.json','test-runner/TestRunner.runtimeconfig.json'],
            host_identity='host-identity.json', sdk='@dotnet//:files', dotnet='@dotnet//:sdk/dotnet',
            size='small', timeout='moderate')
        build += 'graph_test(\n' + ''.join(f'    {key} = {json.dumps(value)},\n' for key, value in attrs.items()) + ')\n'
        declarations.append(dict(node=identity, target='//:test_' + identity, dataHashes=hashes, expectedTests=expected))
    (output / 'tests.json').write_text(json.dumps(dict(schemaVersion=1, tests=declarations), indent=2))
    return build
