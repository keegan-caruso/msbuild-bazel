"""Qualify real MTP and VSTest packages through generated graph rules."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
from fixture_host import temporary_directory, bazel_environment, bazel_startup, sdk_declaration

sys.path.insert(0, str(ROOT / 'tests/fixtures'))
from protocol import setup as mtp_setup
from vstest import setup as vstest_setup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph-worker', action='store_true')
    parser.add_argument('--sharding', action='store_true')
    parser.add_argument('--coverage', action='store_true')
    parser.add_argument('--evidence-directory', type=Path)
    options = parser.parse_args()
    if options.evidence_directory:
        options.evidence_directory.mkdir(parents=True, exist_ok=False)
    with temporary_directory(prefix='graph-protocols-') as temporary:
        for protocol, setup in [('mtp', mtp_setup), ('vstest', vstest_setup)]:
            folder = Path(temporary).resolve() / protocol
            folder.mkdir()
            workspace = setup(folder, coverage=options.coverage)
            shutil.copy(ROOT / 'global.json', workspace / 'global.json')
            module = (ROOT / 'examples/quickstart/MODULE.bazel').read_text().replace('"../msbuild-bazel"', json.dumps(str(ROOT)))
            declaration = 'dotnet.sdk(\n    name = "dotnet",\n    global_json = "//:global.json",\n)'
            assert module.count(declaration) == 1, 'Update the fixture SDK declaration for the current quickstart'
            module = module.replace(declaration, sdk_declaration(global_json='//:global.json').strip())
            (workspace / 'MODULE.bazel').write_text(module)
            if protocol == 'mtp':
                projects = ['Mtp/Mtp.csproj']
                roots = ['//packages:xunit.v3.mtp-v2', '//packages:microsoft.testing.extensions.trxreport']
                tests = 'msbuild_graph_test(name="tests",graph=":graph",project="Mtp/Mtp.csproj",test_protocol="mtp",test_output_dirs=["logs"],test_filter_argument="--filter-query")\n'
            else:
                projects = ['Vstest/Xunit/Xunit.csproj']
                roots = ['//Vstest/packages:' + name for name in ['microsoft.net.test.sdk', 'xunit', 'xunit.runner.visualstudio', 'microsoft.testplatform.cli']]
                tests = ('msbuild_test_tool(name="runner",package="//Vstest/packages:microsoft.testplatform.cli",path="contentFiles/any/net9.0/vstest.console.dll")\n'
                         'msbuild_test_tool(name="adapter",package="//Vstest/packages:xunit.runner.visualstudio",path="build/net8.0")\n'
                         'msbuild_graph_test(name="tests",graph=":graph",project="Vstest/Xunit/Xunit.csproj",test_protocol="vstest",test_runner=":runner",test_adapters=[":adapter"],'
                         'test_settings="Vstest/Xunit/settings.runsettings",test_working_directory="tests",data_paths={"Vstest/Xunit/input.txt":"tests/input.txt"},test_output_dirs=["tests/logs"])\n')
            if options.coverage:
                tests = tests.replace('name="tests",', 'name="tests",test_coverage="coverlet",')
                if protocol == 'mtp':
                    roots.append('//packages:coverlet.mtp')
                else:
                    roots.append('//Vstest/packages:coverlet.collector')
                    tests = ('msbuild_test_tool(name="collector",package="//Vstest/packages:coverlet.collector",path="build/netstandard2.0")\n' +
                             tests.replace('test_adapters=[":adapter"]', 'test_adapters=[":adapter"],test_coverage_collector=":collector"'))
            if protocol == 'vstest':
                project_file = workspace / 'Vstest/Xunit/Xunit.csproj'
                # The old per-project rule forces library compilation; the graph
                # preserves the SDK's executable test project and generated entry.
                project_file.write_text(project_file.read_text().replace('<GenerateProgramFile>false</GenerateProgramFile>', ''))
            dependency = workspace / 'Dependency'
            dependency.mkdir()
            (dependency / 'Dependency.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net11.0</TargetFramework></PropertyGroup></Project>')
            dependency_source = dependency / 'Code.cs'
            original_dependency = 'public static class Dependency {\n public static int Value => 1;\n public static int NeverCalled() => 7;\n}\n'
            dependency_source.write_text(original_dependency)
            test_project = workspace / projects[0]
            relative = os.path.relpath(dependency / 'Dependency.csproj', test_project.parent)
            test_project.write_text(test_project.read_text().replace('</Project>', '<ItemGroup><ProjectReference Include="' + relative + '" /></ItemGroup></Project>'))
            test_source = test_project.parent / 'Tests.cs'
            test_source.write_text(test_source.read_text().replace('void Passes() {', 'void Passes() { Assert.Equal(1, Dependency.Value);'))
            # These fixed fixtures consume dependency API through compilation;
            # runtime tests must still observe the current implementation.
            (workspace / 'mapping.json').write_text(json.dumps({'projectDefaults': {'referenceBoundary': True}}))
            for path in workspace.rglob('BUILD.bazel'):
                if path.parent.name != 'packages':
                    path.unlink()
            authored = ('load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\n'
                        'load("@rules_msbuild//msbuild:defs.bzl","msbuild_package_lock","msbuild_graph_test","msbuild_test_tool")\n'
                        'msbuild_package_lock(name="packages",packages=' + json.dumps(roots) + ')\n'
                        'msbuild_sync(name="sync",package_build=True,mappings="mapping.json",package_lock=":packages",projects=' + json.dumps(projects) + ')\n')
            (workspace / 'BUILD.bazel').write_text(authored)
            command = bazel_startup(f'--output_base={folder / "base"}')

            def bazel(*args, success=True):
                if options.graph_worker and args[0] in ('run', 'build', 'test'):
                    args = args[:1] + ('--strategy=MSBuildGraph=worker', '--worker_sandboxing') + args[1:]
                result = subprocess.run(command + list(args), cwd=workspace, env=bazel_environment(), text=True, capture_output=True)
                assert (result.returncode == 0) == success, result.stdout + result.stderr
                return result.stdout + result.stderr

            try:
                bazel('run', '//:sync')
                bazel('run', '//:sync', '--', '--check')
                graph_options = ',linux_stable_paths=True,linux_worker=True' if options.graph_worker else ''
                (workspace / 'BUILD.bazel').write_text(authored + 'load(":graph.generated.bzl","app_graph")\napp_graph(name="graph"' + graph_options + ')\n' + tests)
                if options.coverage:
                    bazel('build', '//:tests')
                    assembly_path = 'Mtp.dll' if protocol == 'mtp' else 'Xunit.Tests.dll'
                    runtime_directory = workspace / 'bazel-bin/tests.runtime'
                    original = runtime_directory / assembly_path
                    original_digest = hashlib.sha256(original.read_bytes()).hexdigest()
                    runtime_hashes = lambda: {str(path.relative_to(runtime_directory)): hashlib.sha256(path.read_bytes()).hexdigest() for path in runtime_directory.rglob('*') if path.is_file()}
                    original_files = runtime_hashes()
                    command_flags = ['--combined_report=lcov', '--test_output=errors']
                    coverage_log = bazel('coverage', '//:tests', *command_flags, '--nocache_test_results')
                    report = workspace / 'bazel-out/_coverage/_coverage_report.dat'
                    def check_coverage(expect_hits=True):
                        text = report.read_text()
                        records = [record for record in text.split('end_of_record') if 'SF:Dependency/Code.cs' in record]
                        assert len(records) == 1, text
                        lines = {int(value.split(',')[0]): int(value.split(',')[1]) for line in records[0].splitlines() if line.startswith('DA:') for value in [line[3:]]}
                        assert (lines.get(2, 0) > 0 if expect_hits else lines.get(2) == 0) and lines.get(3) == 0, lines
                        assert '/private/' not in text and '/_/workspace/' not in text, text
                        assert runtime_hashes() == original_files, 'Declared runtime inputs changed during instrumentation'
                        return text
                    ordinary = check_coverage()
                    cached = bazel('coverage', '//:tests', *command_flags)
                    assert '(cached)' in cached, cached
                    assert check_coverage() == ordinary
                    sharded = tests.replace('name="tests",', 'name="tests",shard_count=3,')
                    (workspace / 'BUILD.bazel').write_text(authored + 'load(":graph.generated.bzl","app_graph")\napp_graph(name="graph"' + graph_options + ')\n' + sharded)
                    shard_log = bazel('coverage', '//:tests', *command_flags, '--nocache_test_results')
                    sharded_report = check_coverage()
                    shard_reports = sorted((workspace / 'bazel-testlogs/tests').glob('shard_*_of_3/test.xml'))
                    assert len(shard_reports) == 3
                    cases = [test.get('name') for path in shard_reports for test in ET.parse(path).getroot().findall('.//testcase')]
                    assert len(cases) == 4 and len(set(cases)) == 4, cases
                    filter_value = '/*/*/Tests/Passes' if protocol == 'mtp' else 'FullyQualifiedName~Passes'
                    filtered_log = bazel('coverage', '//:tests', *command_flags, '--test_filter=' + filter_value, '--nocache_test_results')
                    filtered_report = check_coverage()
                    filtered_cases = [test.get('name') for path in shard_reports for test in ET.parse(path).getroot().findall('.//testcase')]
                    assert len(filtered_cases) == 1 and 'Passes' in filtered_cases[0], filtered_cases
                    skipped_filter = '/*/*/Tests/Skipped' if protocol == 'mtp' else 'FullyQualifiedName~Skipped'
                    skipped_log = bazel('coverage', '//:tests', *command_flags, '--test_filter=' + skipped_filter, '--nocache_test_results')
                    skipped_report = check_coverage(expect_hits=False)
                    skipped_cases = [test for path in shard_reports for test in ET.parse(path).getroot().findall('.//testcase')]
                    assert len(skipped_cases) == 1 and skipped_cases[0].find('skipped') is not None
                    if options.evidence_directory:
                        evidence = options.evidence_directory
                        (evidence / (protocol + '.lcov')).write_text(ordinary)
                        (evidence / (protocol + '-sharded.lcov')).write_text(sharded_report)
                        (evidence / (protocol + '-filtered.lcov')).write_text(filtered_report)
                        (evidence / (protocol + '-skipped.lcov')).write_text(skipped_report)
                        (evidence / (protocol + '.log')).write_text(coverage_log + cached + shard_log + filtered_log + skipped_log)
                        archives = sorted(folder.rglob('*.nupkg'))
                        (evidence / (protocol + '-inputs.json')).write_text(json.dumps({
                            'runtimeAssemblySha256': original_digest,
                            'runtimeFiles': original_files,
                            'packages': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in archives},
                        }, indent=2))
                    print('PASS:', protocol, 'instrumented bazel coverage hit/unhit lines, cache reuse, three-shard merge and immutable inputs', flush=True)
                    continue
                if options.sharding:
                    bazel('test', '//:tests', '--test_output=errors', '--nocache_test_results')
                    baseline = ET.parse(workspace / 'bazel-testlogs/tests/test.xml').getroot()
                    identities = lambda tree: sorted((test.get('classname'), test.get('name')) for test in tree.findall('.//testcase'))
                    expected_cases = identities(baseline)
                    assert len(expected_cases) == 4, expected_cases
                    sharded = tests.replace('name="tests",', 'name="tests",shard_count=3,')
                    (workspace / 'BUILD.bazel').write_text(authored + 'load(":graph.generated.bzl","app_graph")\napp_graph(name="graph"' + graph_options + ')\n' + sharded)
                    bazel('test', '//:tests', '--test_output=errors', '--nocache_test_results')
                    shard_reports = sorted((workspace / 'bazel-testlogs/tests').glob('shard_*_of_3/test.xml'))
                    assert len(shard_reports) == 3, shard_reports
                    observed = sorted(case for path in shard_reports for case in identities(ET.parse(path).getroot()))
                    assert observed == expected_cases, (observed, expected_cases)
                    cached = bazel('test', '//:tests', '--test_output=errors')
                    assert '(cached)' in cached, cached
                    filter_value = '/*/*/Tests/Passes' if protocol == 'mtp' else 'FullyQualifiedName~Passes'
                    bazel('test', '//:tests', '--test_output=errors', '--test_filter=' + filter_value, '--nocache_test_results')
                    filtered = [case for path in shard_reports for case in identities(ET.parse(path).getroot())]
                    assert len(filtered) == 1 and 'Passes' in filtered[0][1], filtered
                    if protocol == 'vstest':
                        bazel('test', '//:tests', '--test_output=errors', '--test_filter=DisplayName~1', '--nocache_test_results')
                        rows = [case for path in shard_reports for case in identities(ET.parse(path).getroot())]
                        assert len(rows) == 1 and 'n: 1' in rows[0][1], rows
                        bazel('test', '//:tests', '--test_output=errors', '--test_filter=DisplayName~Absent', '--nocache_test_results', success=False)
                    bazel('test', '//:tests', '--test_output=errors', '--test_env=CASE=fail', '--nocache_test_results', success=False)
                    print('PASS:', protocol, 'three shards execute every case once; filter, empty shards, failures and cache reuse', flush=True)
                    continue
                for case, flags, success, count in [
                    ('pass', [], True, 4), ('fail', ['--test_env=CASE=fail'], False, 4),
                    ('filter', ['--test_filter=' + ('/*/*/Tests/Passes' if protocol == 'mtp' else 'FullyQualifiedName~Passes')], True, 1),
                    ('empty', ['--test_filter=' + ('/*/*/Tests/Absent' if protocol == 'mtp' else 'FullyQualifiedName~Absent')], False, None),
                    ('restored', [], True, 4),
                ]:
                    bazel('test', '//:tests', '--test_output=errors', *flags, success=success)
                    xml = ET.parse(workspace / 'bazel-testlogs/tests/test.xml').getroot()
                    if count is not None:
                        assert len(xml.findall('.//testcase')) == count, ET.tostring(xml)
                    if case == 'pass':
                        assert len(xml.findall('.//skipped')) == 1
                        output = workspace / 'bazel-testlogs/tests/test.outputs/files' / ('logs/output.txt' if protocol == 'mtp' else 'tests/logs/result.txt')
                        assert output.is_file(), output
                    if case == 'fail':
                        assert len(xml.findall('.//failure')) == 1
                    print('PASS:', protocol, case, flush=True)
                reference = workspace / 'bazel-bin/graph.graph/workspace/Dependency/obj/Release/net11.0/ref/Dependency.dll'
                reference_bytes = reference.read_bytes()
                dependency_source.write_text(original_dependency.replace('=> 1;', '=> 2;'))
                bazel('test', '//:tests', '--test_output=errors', success=False)
                xml = ET.parse(workspace / 'bazel-testlogs/tests/test.xml').getroot()
                assert len(xml.findall('.//failure')) == 1, ET.tostring(xml)
                report = json.loads((workspace / 'bazel-bin/graph.graph/report.json').read_text())
                expected = (1, 1) if options.graph_worker else (0, 2)
                assert (report['hits'], report['misses']) == expected, report
                assert reference.read_bytes() == reference_bytes
                dependency_source.write_text(original_dependency)
                bazel('test', '//:tests', '--test_output=errors')
                print('PASS:', protocol, 'dependency body invalidates tests', 'with compilation reused' if options.graph_worker else 'with a fresh local snapshot cache', flush=True)
            finally:
                bazel('shutdown')


if __name__ == '__main__':
    main()
