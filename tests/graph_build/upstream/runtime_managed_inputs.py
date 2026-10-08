"""Independent runtime managed-input edits, raw bytes and source-host observations.

Use a successful retained eight-suite worker. Imports must reject stale generated
contracts before the normal reviewed sync workflow updates their definitions.
This is an unscored correctness control, including diagnostic raw binary logs.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from runtime_full_source import capture_compiled_products, validate_raw_contract

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tests/runtime'))
from case_names import normalize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'raw_results', 'results', 'mappings']:
        parser.add_argument(name, type=Path)
    parser.add_argument('--output-base', required=True, type=Path)
    parser.add_argument('--case', choices=['shared-source', 'resource', 'generated-metadata', 'imported-property'], help='run one independent control')
    parser.add_argument('--inputs', required=True, type=Path)
    parser.add_argument('--runfiles', required=True, type=Path)
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    root, raw_results, results = [p.resolve() for p in [args.workspace, args.raw_results, args.results]]
    results.mkdir(parents=True, exist_ok=False)
    raw = raw_results / 'raw-workspace'
    manifest = root / 'graph.generated.json'
    original_contract = manifest.read_bytes()
    contract = json.loads(original_contract)
    validate_raw_contract(contract, raw_results)
    nodes = [(p, v) for p, declaration in contract['Projects'].items() for v in declaration.get('Configurations') or [declaration]]
    count = sum(bool(v['OutputDirectories'] or v.get('OutputFiles')) for _, v in nodes)
    assert count == 481 and len(nodes) == 543
    suite = json.loads((root / 'suite.json').read_text())
    application = json.loads((root / 'application.json').read_text())
    assert len(suite['tests']) == 8
    def cases():
        return {test['target']: normalize(Counter((c.get('name'), 'Failed' if c.find('failure') is not None or c.find('error') is not None
            else 'NotExecuted' if c.find('skipped') is not None else 'Passed') for c in
            ET.parse(root / 'bazel-testlogs' / test['target'].removeprefix('//:') / 'test.xml').getroot().findall('.//testcase')))
            for test in suite['tests']}
    baseline_cases = cases()
    assert sum(sum(c.values()) for c in baseline_cases.values()) == 119016
    sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
    environment = dict(os.environ, USE_BAZEL_VERSION='9.3.0')
    for name in ['RULES_MSBUILD_PROJECT_CACHE_URL', 'RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN', 'RULES_MSBUILD_GRAPH_PROFILE']:
        environment.pop(name, None)
    bazel = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(args.output_base.resolve())]
    options = ['--jobs=1', '--local_test_jobs=1', '--strategy=MSBuildGraph=worker', '--worker_sandboxing',
               '--worker_max_instances=MSBuildGraph=1', '--disk_cache=', '--remote_cache=', '--test_output=errors', '--noshow_progress']
    scratch = results / 'scratch'
    scratch.mkdir()
    stable = '/__rules_msbuild_graph/output/workspace'
    raw_command = ['bash', str(Path(__file__).with_name('runtime_raw.sh')), str(sdk), str(raw), str(scratch),
                   stable + '/.qualification/Raw.dll', stable, stable + '/graph.generated.json', 'build']
    def invoke(command, label, cwd=root, success=True, extra_env=None):
        with (results / (label + '.log')).open('w') as log:
            result = subprocess.run(command, cwd=cwd, env=dict(environment, **(extra_env or {})), stdout=log, stderr=subprocess.STDOUT)
        assert (result.returncode == 0) == success, label
        return result
    reader, probe = results / 'reader', results / 'probe'
    for folder, source, project in [(reader, ROOT / 'tests/runtime/RawTimingLog.cs.txt', ROOT / 'tests/runtime/Inventory.csproj.txt'),
                                    (probe, Path(__file__).with_name('ManagedInputProbe.cs.txt'), None)]:
        folder.mkdir()
        shutil.copyfile(source, folder / 'Program.cs')
        if project:
            shutil.copyfile(project, folder / 'Tool.csproj')
        else:
            (folder / 'Tool.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup></Project>')
        invoke([str(sdk / 'dotnet'), 'build', str(folder / 'Tool.csproj'), '-c', 'Release', '-p:UseSharedCompilation=false'], folder.name + '-build')
    baseline = capture_compiled_products(root / 'bazel-bin/graph.graph/workspace', contract)
    raw_baseline = capture_compiled_products(raw, contract)
    assert len(baseline) == len(raw_baseline) == 3622
    assert baseline.keys() == raw_baseline.keys()
    assert all(baseline[p]['sha256'] == raw_baseline[p]['sha256'] for p in baseline), 'Start from matching original bytes'
    rows = []
    token = "managed-edited-" + uuid.uuid4().hex
    generated = root / 'graph.generated.bzl'
    original_generated = generated.read_bytes()
    paths = ['src/libraries/Common/src/Internal/Padding.cs', 'src/libraries/Microsoft.CSharp/src/Resources/Strings.resx',
             'src/libraries/System.Diagnostics.DiagnosticSource/src/ThisAssembly.cs.in', 'src/libraries/System.Private.Uri/Directory.Build.props']
    originals = {p: (root / p).read_bytes() for p in paths}
    assert all((raw / p).read_bytes() == value for p, value in originals.items())
    assert all(any(p in v['Inputs'] for _, v in nodes) for p in paths)
    def raw_build(label):
        name = 'managed-' + label + '.binlog'
        invoke(raw_command + [stable + '/.qualification/' + name], label + '-raw', raw)
        return json.loads(subprocess.check_output([str(sdk / 'dotnet'), str(reader / 'bin/Release/net10.0/Tool.dll'),
            str(raw / '.qualification' / name)], env=environment, text=True))['compiled']
    def graph(label, restored=False, resynced=False):
        events = results / (label + '.bep')
        invoke(bazel + ['test', '//:runtime_suites', *options, '--build_event_json_file=' + str(events)], label)
        report = json.loads((root / 'bazel-bin/graph.graph/report.json').read_text())
        assert report['hits'] + report['misses'] == count and report['readOnlyPreparedPackages']
        if restored and not resynced:
            assert report['misses'] == 0, report
        else:
            assert (0 if restored else 1) <= report['misses'] < count, report
        assert cases() == baseline_cases, 'Changed test outcomes: ' + label
        graph_products = capture_compiled_products(root / 'bazel-bin/graph.graph/workspace', contract)
        raw_products = capture_compiled_products(raw, contract)
        assert graph_products.keys() == raw_products.keys() == baseline.keys()
        assert all(graph_products[p]['sha256'] == raw_products[p]['sha256'] for p in graph_products), label + ' raw byte parity'
        if restored:
            assert graph_products == baseline, label + ' original output restoration'
        unchanged = sum(graph_products[p] == baseline[p] for p in graph_products)
        assert unchanged > 0
        records = [json.loads(line) for line in events.read_text().splitlines()]
        tests = [e['testResult'] for e in records if 'testResult' in e]
        assert len(tests) == 8 and all(t['status'] == 'PASSED' for t in tests)
        return dict(case=label, hits=report['hits'], misses=report['misses'], compiledProducts=len(graph_products),
                    unchangedProducts=unchanged, testOutcomes=119016, testsCached=sum(bool(t.get('cachedLocally')) for t in tests))
    def observe(label, mode, assembly, key, value):
        producer = application['managed'][assembly + '.dll']['path']
        product = root / 'bazel-bin/graph.graph/workspace' / producer
        digest = hashlib.sha256(product.read_bytes()).hexdigest().upper()
        host = (root / 'bazel-bin' / suite['host']).resolve()
        invoke([str(host / 'host.sh'), str(probe / 'bin/Release/net10.0/Tool.dll'), mode, assembly, key, value, digest], label + '-probe', extra_env={'TEST_UNDECLARED_OUTPUTS_DIR': str(results / (label + '-proof'))})
        return json.loads((results / (label + '-probe.log')).read_text())
    # The expanded fixture adds reviewed per-entry frameworks after the initial
    # preparation. Resync must use that current contract, not its older mapping.
    mappings = json.loads(args.mappings.read_text())
    mappings['entryProperties'] = contract.get('EntryProperties', {})
    reviewed_mappings = results / 'reviewed-mappings.json'
    reviewed_mappings.write_text(json.dumps(mappings, indent=2) + '\n')
    def sync(label):
        invoke([str(sdk / 'dotnet'), str(ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll'), str(root),
            str(sdk / 'sdk/10.0.400'), *contract['Entries'], '--framework', contract['Properties']['TargetFramework'], '--package-build',
            '--inputs', str(args.inputs.resolve()), '--runfiles', str(args.runfiles.resolve()),
            '--mappings', str(reviewed_mappings)], label + '-sync')
        updated = json.loads(manifest.read_text())
        (results / (label + '-contract.json')).write_text(json.dumps(updated, indent=2) + '\n')
        assert updated['Entries'] == contract['Entries'] and updated['Projects'].keys() == contract['Projects'].keys()
        # The reviewed native/tool/output binding sections must survive sync.
        for key in ['Properties', 'OutputDirectories', 'OutputFiles', 'CompilerReference', 'CompilerReferences', 'ImplementationDependencies', 'ReferenceBoundary', 'InputDirectories', 'TemporaryDirectories']:
            for path, declaration in contract['Projects'].items():
                variants = declaration.get('Configurations') or [declaration]
                replacements = updated['Projects'][path].get('Configurations') or [updated['Projects'][path]]
                assert len(variants) == len(replacements)
                identity = lambda v: tuple(sorted((v.get('Properties') or {}).items()))
                before = {identity(v): v for v in variants}
                after = {identity(v): v for v in replacements}
                assert before.keys() == after.keys(), (path, 'configured identities')
                assert all(before[k].get(key) == after[k].get(key) for k in before), (path, key)
    try:
        for index, path in enumerate(paths):
            label = ['shared-source', 'resource', 'generated-metadata', 'imported-property'][index]
            if args.case and args.case != label:
                continue
            original = originals[path]
            observers = []
            if index == 0:
                anchor = b'internal static class PaddingHelpers\n    {'
                assert original.count(anchor) == 1 and original.count(b'CACHE_LINE_SIZE = 128') == 1
                # A private method is stripped from the .NET 10 products. The
                # retained Channels structure exposes the changed padding size.
                changed = original.replace(b'CACHE_LINE_SIZE = 128', b'CACHE_LINE_SIZE = 256')
                changed = changed.replace(anchor, anchor + b'\n        private static string QualificationManagedInputProbe() => "' + token.encode() + b'";\n')
                observers = [('layout', 'System.Threading.Channels', 'Internal.PaddingFor32', '252')]
            elif index == 2:
                generated_source = root / 'bazel-bin/graph.graph/workspace/artifacts/obj/System.Diagnostics.DiagnosticSource/Release/net10.0/ThisAssembly.cs'
                version = re.search(r'BuildAssemblyFileVersion = "([^"]+)"', generated_source.read_text()).group(1)
                parts = version.split('.')
                assert len(parts) == 4
                parts[3] = str((int(parts[3]) + int(uuid.uuid4().hex[:4], 16) % 65535 + 1) % 65536)
                value = '.'.join(parts)
                assert original.count(b'${AssemblyFileVersion}') == 1 and value != version
                changed = original.replace(b'${AssemblyFileVersion}', value.encode())
                observers = [('property', 'System.Diagnostics.DiagnosticSource', 'System.Diagnostics.ThisAssembly|AssemblyFileVersion', value)]
            elif index == 1:
                anchor = b'An unexpected exception occurred while binding a dynamic operation'
                assert original.count(anchor) == 1
                changed = original.replace(anchor, anchor + b' ' + token.encode())
                observers = [('resource', 'Microsoft.CSharp', 'InternalCompilerError', (anchor + b' ' + token.encode()).decode())]
            else:
                assert original.count(b'</Project>') == 1
                changed = original.replace(b'</Project>', b'<ItemGroup><AssemblyAttribute Include="System.Reflection.AssemblyMetadataAttribute"><_Parameter1>QualificationManagedInput</_Parameter1><_Parameter2>' + token.encode() + b'</_Parameter2></AssemblyAttribute></ItemGroup></Project>')
                observers = [('metadata', 'System.Private.Uri', 'QualificationManagedInput', token)]
            for workspace in [root, raw]:
                (workspace / path).write_bytes(changed)
            if index == 3:
                invoke(bazel + ['build', '//:graph', *[o for o in options if not o.startswith('--local_test_jobs') and not o.startswith('--test_output')]], label + '-stale-definition', success=False)
                assert 'Graph definition changed; rerun sync: ' + path in (results / (label + '-stale-definition.log')).read_text()
                sync(label)
            compiled = raw_build(label)
            assert compiled, label + ' must invoke raw compilation'
            row = graph(label)
            row['rawCompilerCalls'] = compiled
            row['observations'] = [observe(label + '-' + str(n), *observation) for n, observation in enumerate(observers)]
            rows.append(row)
            (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
            print(json.dumps({k: v for k, v in row.items() if k != 'rawCompilerCalls'}), flush=True)
            for workspace in [root, raw]:
                (workspace / path).write_bytes(original)
            if index == 3:
                sync(label + '-restored')
            compiled = raw_build(label + '-restored')
            row = graph(label + '-restored', restored=True, resynced=index == 3)
            row['rawCompilerCalls'] = compiled
            rows.append(row)
            (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
            print(json.dumps({k: v for k, v in row.items() if k != 'rawCompilerCalls'}), flush=True)
        print('PASS: selected independent runtime input controls, current host producers, raw bytes, suites and restoration', flush=True)
    finally:
        for path, content in originals.items():
            for workspace in [root, raw]:
                if (workspace / path).read_bytes() != content:
                    (workspace / path).write_bytes(content)
        manifest.write_bytes(original_contract)
        generated.write_bytes(original_generated)


if __name__ == '__main__':
    main()
