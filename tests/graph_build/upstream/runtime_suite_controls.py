"""Qualify larger source-host replay, body/API boundaries and real-test failure.

Use a retained successful 474-compilation worker and a completed full-source raw
Build. Runs include diagnostics and are correctness controls, not scored timing.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid
import xml.etree.ElementTree as ET

from runtime_full_source import capture_compiled_products, validate_raw_contract

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('raw_results', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output-base', type=Path, required=True)
    parser.add_argument('--version', choices=['8.8.0', '9.2.0'], default='9.2.0')
    parser.add_argument('--test-failure-only', action='store_true', help='extend a completed edit control with assertion failure and restoration')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    root, raw_results, results = args.workspace.resolve(), args.raw_results.resolve(), args.results.resolve()
    assert not results.is_relative_to(root) and not results.is_relative_to(raw_results)
    results.mkdir(parents=True, exist_ok=False)
    raw = raw_results / 'raw-workspace'
    contract = json.loads((root / 'graph.generated.json').read_text())
    validate_raw_contract(contract, raw_results)
    nodes = [(path, v) for path, p in contract['Projects'].items() for v in p.get('Configurations') or [p]]
    count = sum(bool(v['OutputDirectories'] or v.get('OutputFiles')) for _, v in nodes)
    assert count == 474, 'Use the reviewed expanded source-host/Pipelines graph'
    directories = {d for _, v in nodes for d in v['OutputDirectories']}
    files = {f for _, v in nodes for f in v.get('OutputFiles', [])}
    states = {d + '/' + Path(p).name + '.GenerateResource.cache' for p, v in nodes
              for d in v['OutputDirectories'] if d.startswith('artifacts/obj/')}
    mutation = json.loads(Path(__file__).with_name('runtime_loaded_common_edit.json').read_text())
    test_source = 'src/libraries/System.IO.Pipelines/tests/PipeOptionsTests.cs'
    originals = {p: (root / p).read_bytes() for p in [mutation['implementation'], mutation['reference'], test_source]}
    assert all((raw / p).read_bytes() == content for p, content in originals.items())
    generated = root / 'graph.generated.bzl'
    original_generated = generated.read_bytes()
    nonce = root / 'suite-controls-request.txt'
    assert not nonce.exists()
    prefix, action = original_generated.decode().split('    msbuild_graph(\n')
    assert action.count('        srcs = [') == 1
    environment = dict(os.environ, USE_BAZEL_VERSION=args.version)
    for name in ['RULES_MSBUILD_PROJECT_CACHE_URL', 'RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN', 'RULES_MSBUILD_GRAPH_PROFILE']:
        environment.pop(name, None)
    bazel = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(args.output_base.resolve()),
             'test', '//:pipelines_suite', '--jobs=1', '--strategy=MSBuildGraph=worker', '--worker_sandboxing',
             '--worker_max_instances=MSBuildGraph=1', '--disk_cache=', '--remote_cache=', '--test_output=errors', '--noshow_progress']
    sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
    scratch = results / 'scratch'
    scratch.mkdir()
    stable = '/__rules_msbuild_graph/output/workspace'
    raw_command = ['bash', str(Path(__file__).with_name('runtime_raw.sh')), str(sdk), str(raw), str(scratch),
                   stable + '/.qualification/Raw.dll', stable, stable + '/graph.generated.json', 'build']
    reader = results / 'reader'
    reader.mkdir()
    fixtures = ROOT / 'tests/explicit_msbuild/runtime'
    shutil.copyfile(fixtures / 'Inventory.csproj.txt', reader / 'Reader.csproj')
    shutil.copyfile(fixtures / 'RawTimingLog.cs.txt', reader / 'Program.cs')
    rows = []
    def invoke(command, label, cwd):
        with (results / (label + '.log')).open('w') as log:
            return subprocess.run(command, cwd=cwd, env=environment, stdout=log, stderr=subprocess.STDOUT)
    def capture():
        workspace = root / 'bazel-bin/graph.graph/workspace'
        assert all((workspace / path).is_file() for path in files), 'Missing declared shared output'
        paths = {workspace / path for path in files} | {p for d in directories for p in (workspace / d).rglob('*')}
        return {str(p.relative_to(workspace)): dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(), mode=p.stat().st_mode & 0o777)
                for p in paths if p.is_file() and not p.name.endswith('.AssemblyReference.cache')
                and (str(p.relative_to(workspace)) not in states or str(p.relative_to(workspace)) in files)}
    def compare():
        graph_products = capture_compiled_products(root / 'bazel-bin/graph.graph/workspace', contract)
        raw_products = capture_compiled_products(raw, contract)
        differences = {p: dict(graph=graph_products.get(p), raw=raw_products.get(p))
                       for p in graph_products.keys() | raw_products.keys()
                       if graph_products.get(p, {}).get('sha256') != raw_products.get(p, {}).get('sha256')}
        (results / 'differences.json').write_text(json.dumps(differences, indent=2) + '\n')
        assert graph_products and not differences, 'Full-source compiled-product parity failed'
        return len(graph_products)
    def record(row):
        rows.append(row)
        (results / 'summary.json').write_text(json.dumps(dict(platform='linux-arm64', version=args.version,
            compiled=count, scope='unscored correctness; raw diagnostics enable binary logging', rows=rows), indent=2) + '\n')
        print(json.dumps(row), flush=True)
    def test(label, misses=None, failure=None):
        events = results / (label + '.bep')
        extra = ['--test_env=QUALIFICATION_CORELIB_SHA256=' + '0' * 64] if failure == 'observer' else []
        process = invoke(bazel + ['--build_event_json_file=' + str(events)] + extra, label, root)
        assert (process.returncode == 0) == (not failure), label
        records = [json.loads(line) for line in events.read_text().splitlines()]
        metrics = next(e['buildMetrics']['actionSummary'] for e in records if 'buildMetrics' in e)
        actions = {r['mnemonic']: int(r.get('actionsExecuted', 0)) for r in metrics.get('actionData', [])}
        assert actions.get('RuntimeNative', 0) == actions.get('MSBuildGraphRestore', 0) == 0, actions
        assert actions.get('MSBuildGraph', 0) == int(misses is not None), actions
        outcomes = [e['testResult'] for e in records if 'testResult' in e]
        assert len(outcomes) == 1 and outcomes[0]['status'] == ('FAILED' if failure else 'PASSED'), outcomes
        if failure:
            assert not outcomes[0].get('cachedLocally')
        if failure == 'observer':
            assert 'Qualification loaded wrong binary' in (results / (label + '.log')).read_text()
        else:
            cases = Counter((r.get('name'), r.find('skipped') is not None, r.find('failure') is not None or r.find('error') is not None)
                for r in ET.parse(root / 'bazel-testlogs/pipelines_suite/test.xml').getroot().findall('.//testcase'))
            assert sum(cases.values()) == 577 and not any(skip for _, skip, _ in cases), cases
            assert sum(n for (_, _, failed), n in cases.items() if failed) == int(failure == 'assertion'), cases
        row = dict(case=label, passed=not failure, testCached=bool(outcomes[0].get('cachedLocally')), graphActions=actions.get('MSBuildGraph', 0))
        if misses is not None:
            report = json.loads((root / 'bazel-bin/graph.graph/report.json').read_text())
            assert (report['hits'], report['misses']) == (count - misses, misses), report
            assert report['preparedRestore'] and report['readOnlyPreparedPackages']
            row.update(hits=report['hits'], misses=report['misses'])
        return row
    def restore():
        for p, content in originals.items():
            for workspace in [root, raw]:
                source = workspace / p
                if source.read_bytes() != content:
                    source.write_bytes(content)
    initial_cases = ET.parse(root / 'bazel-testlogs/pipelines_suite/test.xml').getroot().findall('.//testcase')
    assert len(initial_cases) == 577 and all(case.find('failure') is None and case.find('error') is None and case.find('skipped') is None for case in initial_cases), 'Restore a successful original suite before starting controls'
    baseline = capture()
    try:
        record(dict(case='baseline', files=len(baseline), compiledProducts=compare()))
        generated.write_text(prefix + '    msbuild_graph(\n' + action.replace('        srcs = [', '        srcs = ["suite-controls-request.txt",', 1))
        nonce.write_text(str(uuid.uuid4()))
        row = test('forced-local-replay', 0)
        assert capture() == baseline, 'Full replay files/bytes/modes differ'
        record(row)
        assert invoke([str(sdk / 'dotnet'), 'build', str(reader / 'Reader.csproj'), '-c', 'Release',
                       '-p:UseSharedCompilation=false', '-p:NuGetAudit=false'], 'reader-build', ROOT).returncode == 0
        for case in ([] if args.test_failure_only else ['body', 'api']):
            restore()
            changes = {}
            if case == 'body':
                path, anchor = mutation['implementation'], mutation['bodyAnchor'].encode()
                assert originals[path].count(anchor) == 1
                changes[path] = originals[path].replace(anchor, anchor + b'\n            GC.KeepAlive("' + str(uuid.uuid4()).encode() + b'");')
            else:
                declaration = b'\n        /// <summary>Qualification edit control.</summary>\n        public const int SuiteProbe = 421;'
                for path, anchor in [(mutation['implementation'], mutation['implementationAnchor'].encode()),
                                     (mutation['reference'], mutation['referenceAnchor'].encode())]:
                    assert originals[path].count(anchor) == 1
                    changes[path] = originals[path].replace(anchor, anchor + declaration)
            for p, content in changes.items():
                (root / p).write_bytes(content)
                (raw / p).write_bytes(content)
            binlog = raw / '.qualification' / (case + '-suite.binlog')
            assert invoke(raw_command + [stable + '/.qualification/' + binlog.name], case + '-raw', raw).returncode == 0
            details = json.loads(subprocess.check_output([str(sdk / 'dotnet'), str(reader / 'bin/Release/net10.0/Reader.dll'), str(binlog)], env=environment, text=True))
            compiled = details['compiled']
            assert compiled and len({(c['project'], c['framework']) for c in compiled}) == len(compiled), compiled
            row = test(case, len(compiled))
            assert not row['testCached'], 'Runtime edit must rerun dependency tests'
            row.update(rawCompilerCalls=compiled, comparedCompiledProducts=compare())
            edited = capture()
            assert edited[mutation['implDll']] != baseline[mutation['implDll']]
            assert (edited[mutation['refDll']] == baseline[mutation['refDll']]) == (case == 'body')
            record(row)
            restore()
            assert invoke(raw_command, case + '-raw-restored', raw).returncode == 0
            row = test(case + '-restored', 0)
            assert capture() == baseline
            row['comparedCompiledProducts'] = compare()
            record(row)
        marker = 'qual-fail-' + uuid.uuid4().hex[:12]
        anchor = b'("pauseWriterThreshold", () => new PipeOptions(pauseWriterThreshold: -2))'
        assert originals[test_source].count(anchor) == 1
        changed = originals[test_source].replace(anchor, anchor.replace(b'pauseWriterThreshold",', marker.encode() + b'",', 1))
        for workspace in [root, raw]:
            (workspace / test_source).write_bytes(changed)
        assert invoke(raw_command + [stable + '/.qualification/assertion-suite.binlog'], 'assertion-raw', raw).returncode == 0
        compiled = json.loads(subprocess.check_output([str(sdk / 'dotnet'), str(reader / 'bin/Release/net10.0/Reader.dll'),
            str(raw / '.qualification/assertion-suite.binlog')], env=environment, text=True))['compiled']
        assert len(compiled) == 1 and compiled[0]['project'].endswith('/System.IO.Pipelines.Tests.csproj'), compiled
        row = test('assertion-failure', 1, failure='assertion')
        assert marker in (results / 'assertion-failure.log').read_text()
        row.update(comparedCompiledProducts=compare(), rawCompilerCalls=compiled, passingCases=576, failingCases=1)
        record(row)
        restore()
        assert invoke(raw_command, 'assertion-raw-restored', raw).returncode == 0
        row = test('assertion-restored', 0)
        assert capture() == baseline
        row['comparedCompiledProducts'] = compare()
        record(row)
        record(test('deliberate-observer-failure', failure='observer'))
        record(test('restored-test'))
        row = test('unchanged-cached')
        assert row['testCached'], 'Unchanged successful suite should be cached'
        record(row)
        print('PASS: replay, raw compiler boundaries, test invalidation and deliberate failure', flush=True)
    finally:
        restore()
        generated.write_bytes(original_generated)
        nonce.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
