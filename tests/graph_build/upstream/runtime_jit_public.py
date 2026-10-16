"""Qualify generated JIT graphs; reports and disposable inputs stay outside Git."""
import argparse
from collections import Counter
import json
import os
import re
import socket
from pathlib import Path
import subprocess
import time
import uuid

from runtime_jit import digest, inventory
from runtime_jit_prepare import CODE, TEST_OUTPUT

ROOT = Path(__file__).resolve().parents[3]


def records_from(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output-base', type=Path, required=True)
    parser.add_argument('--raw', type=Path)
    parser.add_argument('--seed-report', type=Path)
    parser.add_argument('--host-space-path', type=Path, required=True)
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    root, results = args.workspace.resolve(), args.results.resolve()
    results.mkdir(parents=True, exist_ok=False)
    if args.seed_report:
        expected = json.loads(args.seed_report.read_text())
        assert expected['machine'] != socket.gethostname() and expected['workspace'] != str(root), 'Require an independent relocated consumer'
        assert not args.output_base.exists(), 'Recovery requires a fresh output base'
    metadata = json.loads((root / 'jit-public.json').read_text())
    assert not metadata.get('sourceProducer'), 'Use runtime_jit_live.py for live source-runtime qualification'
    cases = metadata['cases']
    contract = json.loads((root / "graph.generated.json").read_text())
    node_count = sum(len(project.get("Configurations", [{}])) for project in contract["Projects"].values())
    for path, value in metadata['sourceDigests'].items():
        assert digest(root / path) == value, path
    endpoint = os.environ['RULES_MSBUILD_PROJECT_CACHE_URL']
    command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(args.output_base.resolve()), 'test', '//:jit_tests',
        '--jobs=1', '--strategy=MSBuildGraph=worker', '--worker_sandboxing', '--worker_max_instances=MSBuildGraph=1',
        '--disk_cache=', '--remote_cache=', '--nocache_test_results', '--test_output=all', '--lockfile_mode=off',
        '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + endpoint]
    rows = []

    def invoke(label, success=True):
        subprocess.run(['fstrim', '/'], check=True, capture_output=True)
        disk = os.statvfs(args.host_space_path)
        assert disk.f_bavail * disk.f_frsize >= 8 * 1024**3, 'Insufficient physical host disk headroom'
        events = results / (label + '.bep')
        start = time.monotonic()
        with (results / (label + '.log')).open('w') as log:
            outcome = subprocess.run(command + ['--build_event_json_file=' + str(events)], cwd=root, stdout=log, stderr=subprocess.STDOUT)
        assert (outcome.returncode == 0) == success, str(results / (label + '.log'))
        records = [json.loads(line) for line in events.read_text().splitlines()]
        tests = [event['testResult'] for event in records if 'testResult' in event]
        if success or label == 'failure':
            assert len(tests) == len(cases), tests
            labels = {event['id']['testResult']['label'] for event in records if 'testResult' in event}
            assert labels == {'//:' + case['name'] for case in cases}, labels
            expected = Counter(PASSED=len(cases)) if success else Counter(PASSED=len(cases)-1, FAILED=1)
            assert Counter(test['status'] for test in tests) == expected, tests
            assert all(not test.get('cachedLocally') and not test.get('executionInfo', {}).get('cachedRemotely') for test in tests), tests
        row = dict(case=label, seconds=time.monotonic() - start, success=success, executed=len(tests))
        if success:
            graph = root / 'bazel-bin/graph.graph'
            report = json.loads((graph / 'report.json').read_text())
            row.update(hits=report['hits'], misses=report['misses'], outputs=inventory(graph / 'workspace'),
                sourceHost=inventory(root / 'bazel-bin/core_root.layout'))
        rows.append(row)
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps({k: v for k, v in row.items() if k not in ['outputs', 'sourceHost']}), flush=True)
        return row

    seed = invoke('recovery' if args.seed_report else 'seed')
    if args.seed_report:
        expected = json.loads(args.seed_report.read_text())
        assert (seed['hits'], seed['misses']) == (node_count, 0)
        for key in ['outputs', 'sourceHost']:
            assert seed[key] == expected[key], key
        bootstrap_report = json.loads(next((root / 'bazel-bin/external').glob('*/bootstrap.graph/report.json')).read_text())
        # Artifact-only ordinary SDK deployment is not a plugin compilation node.
        # With Bazel's action cache disabled it runs again, without Csc.
        assert (bootstrap_report['hits'], bootstrap_report['misses']) == (0, 0), bootstrap_report
        targeting = next((root / 'bazel-bin/external').glob('*/targeting/TargetingPack'))
        assert inventory(targeting) == expected['bootstrapOutputs'], 'Recovered bootstrap differs'
        metrics = next(event['buildMetrics']['actionSummary'] for event in records_from(results / 'recovery.bep') if 'buildMetrics' in event)
        assert sum(int(row.get('actionsExecuted', 0)) for row in metrics['actionData'] if row['mnemonic'] == 'MSBuildGraph') >= 2
        print('PASS: independent public JIT recovery and actual source-runtime execution', flush=True)
        return
    assert args.raw
    compiled = [path for path in seed['outputs'] if path.endswith(('.dll', '.pdb'))]
    assert len(compiled) == 8 + sum(case['compiledFiles'] for case in cases), compiled
    for path in compiled:
        assert digest(args.raw / path) == seed['outputs'][path]['sha256'], path
    targeting = next((root / 'bazel-bin/external').glob('*/targeting/TargetingPack'))
    deployed = inventory(targeting)
    raw_deployed = inventory(args.raw / 'artifacts/TargetingPack')
    assert deployed.keys() == raw_deployed.keys(), 'Bootstrap product inventory differs'
    for path in deployed:
        assert deployed[path]['sha256'] == raw_deployed[path]['sha256'], path
    seed.update(comparedCompiledFiles=len(compiled), bootstrapOutputs=deployed, nodeCount=node_count, sourceDigests=metadata['sourceDigests'], sourceProductsSha256=digest(root / 'source-products.tar.gz'), machine=socket.gethostname(), workspace=str(root))
    # Execute each raw binary with only the declared source runtime and OS visible.
    host = (root / 'bazel-bin/core_root.layout').resolve()
    for case in cases:
        product = 'artifacts/tests/coreclr/linux.arm64.Release/' + str(Path(case['project']).parent.relative_to('src/tests')) + '/' + Path(case['project']).stem
        raw_output = (args.raw / product).resolve()
        raw_command = ['bwrap', '--die-with-parent', '--unshare-user', '--unshare-pid', '--clearenv', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp']
        for path in ['/usr', '/bin', '/lib', '/lib64', '/etc/ld.so.cache']:
            if Path(path).exists():
                raw_command += ['--ro-bind', path, path]
        raw_command += ['--ro-bind', str(host), '/runtime', '--ro-bind', str(raw_output), '/test',
            '--setenv', 'CORE_ROOT', '/runtime', '--chdir', '/test', '/runtime/corerun', '/test/' + Path(case['project']).stem + '.dll']
        with (results / (case['name'] + '-raw.log')).open('w') as log:
            outcome = subprocess.run(raw_command, stdout=log, stderr=subprocess.STDOUT)
        assert outcome.returncode == 100, (case['name'], outcome.returncode)
    seed['rawExecuted'] = len(cases)
    (results / 'seed.json').write_text(json.dumps(seed, indent=2) + '\n')
    source = root / CODE
    original = source.read_bytes()
    generator = root / 'src/tests/Common/XUnitWrapperGenerator/XUnitWrapperGenerator.cs'
    original_generator = generator.read_bytes()
    generated = root / 'graph.generated.bzl'
    original_generated = generated.read_text()
    try:
        source.write_bytes(original.replace(b'return x+1;', b'return unchecked(x+1);') + ('\n// Body token: ' + uuid.uuid4().hex + '\n').encode())
        body = invoke('body')
        assert (body['hits'], body['misses']) == (node_count-1, 1)
        assert body['outputs'][TEST_OUTPUT + '/Add1_ro.dll'] != seed['outputs'][TEST_OUTPUT + '/Add1_ro.dll']
        source.write_bytes(original.replace(b'return x+1;', b'return x+2;'))
        invoke('failure', False)
        assert 'Expected exit code 100, received 101' in (results / 'failure.log').read_text()
        source.write_bytes(original)
        assert invoke('restored')['outputs'] == seed['outputs']
        generator.write_bytes(original_generator + ('\ninternal static class QualificationGeneratorInput_' + uuid.uuid4().hex + ' {}\n').encode())
        changed = invoke('generator')
        wrapper = 'src/tests/Common/XUnitWrapperGenerator/XUnitWrapperGenerator.csproj'
        generator_dependents = sum(wrapper in config.get('ImplementationDependencies', [])
            for project in contract['Projects'].values() for config in project.get('Configurations', []))
        assert (changed['hits'], changed['misses']) == (node_count-generator_dependents-1, generator_dependents+1)
        generator.write_bytes(original_generator)
        assert invoke('generator-restored')['outputs'] == seed['outputs']
        for case in cases:
            if 'dependency' not in case:
                continue
            dependency = case['dependency']
            helper = root / dependency['source']
            helper_original = helper.read_bytes()
            assert dependency['project'] in contract['Projects']
            assert '<ProjectReference Include="helper.csproj"' in (root / case['project']).read_text()
            configuration = contract['Projects'][case['project']]['Configurations'][0]
            assert configuration['ReferenceBoundary'] == bool(metadata.get('compilerReferences'))
            if metadata.get('compilerReferences'):
                assert configuration['CompilerReferencesComplete']
                assert configuration['CompilerReferences'][dependency['project']].endswith('/helper/helper.dll')
                producer = contract['Projects'][dependency['project']]['Configurations'][0]
                assert producer['CompilerReference'] is None  # SDK default implementation output, not an invented ref DLL
            helper_output = 'artifacts/tests/coreclr/linux.arm64.Release/' + str(Path(dependency['project']).parent.relative_to('src/tests')) + '/' + Path(dependency['project']).stem
            test_output = 'artifacts/tests/coreclr/linux.arm64.Release/' + str(Path(case['project']).parent.relative_to('src/tests')) + '/' + Path(case['project']).stem
            try:
                before = b'return x.m + y.m;'
                assert before in helper_original
                helper.write_bytes(helper_original.replace(before, b'return unchecked(x.m + y.m);') + ('\n// Body token: ' + uuid.uuid4().hex + '\n').encode())
                dependency_body = invoke(case['name'] + '-dependency-body')
                assert (dependency_body['hits'], dependency_body['misses']) == (node_count-2, 2)
                assert dependency_body['outputs'][helper_output + '/helper.dll'] != seed['outputs'][helper_output + '/helper.dll']
                assert dependency_body['outputs'][test_output + '/helper.dll'] == dependency_body['outputs'][helper_output + '/helper.dll']
                helper.write_bytes(helper_original + ('\npublic static class QualificationApi_' + uuid.uuid4().hex + ' {}\n').encode())
                dependency_api = invoke(case['name'] + '-dependency-api')
                assert (dependency_api['hits'], dependency_api['misses']) == (node_count-2, 2)
            finally:
                helper.write_bytes(helper_original)
            assert invoke(case['name'] + '-dependency-restored')['outputs'] == seed['outputs']
        if any('dependency' in case for case in cases):
            contract_path = root / 'graph.generated.json'
            contract_original = contract_path.read_bytes()
            try:
                missing = json.loads(contract_original)
                for case in cases:
                    if 'dependency' in case:
                        del missing['Projects'][case['dependency']['project']]
                contract_path.write_text(json.dumps(missing) + '\n')
                invoke('missing-helper', False)
                diagnostic = (results / 'missing-helper.log').read_text()
                for case in cases:
                    if 'dependency' in case:
                        assert 'Missing project contract: ' + case['dependency']['project'] in diagnostic
            finally:
                contract_path.write_bytes(contract_original)
        bindings = re.findall(r'"[^"]+":"artifacts/bin/ref/net10.0"', original_generated)
        assert bindings and len(set(bindings)) == 1
        binding = bindings[0]
        generated.write_text(original_generated.replace(',' + binding, '').replace(binding + ',', '').replace(binding, ''))
        invoke('missing-references', False)
    finally:
        source.write_bytes(original)
        generator.write_bytes(original_generator)
        generated.write_text(original_generated)
    print('PASS: public update/sync, raw parity, edits, generator invalidation and exit semantics', flush=True)


if __name__ == '__main__':
    main()
