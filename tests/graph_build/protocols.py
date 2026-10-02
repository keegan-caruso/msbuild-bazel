"""Qualify real MTP and VSTest packages through generated graph rules."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/fixtures'))
from protocol import setup as mtp_setup
from vstest import setup as vstest_setup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph-worker', action='store_true')
    options = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='graph-protocols-') as temporary:
        for protocol, setup in [('mtp', mtp_setup), ('vstest', vstest_setup)]:
            folder = Path(temporary).resolve() / protocol
            folder.mkdir()
            workspace = setup(folder)
            shutil.copy(ROOT / 'global.json', workspace / 'global.json')
            module = (ROOT / 'examples/quickstart/MODULE.bazel').read_text().replace('"../msbuild-bazel"', json.dumps(str(ROOT)))
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
            if protocol == 'vstest':
                project_file = workspace / 'Vstest/Xunit/Xunit.csproj'
                # The old per-project rule forces library compilation; the graph
                # preserves the SDK's executable test project and generated entry.
                project_file.write_text(project_file.read_text().replace('<GenerateProgramFile>false</GenerateProgramFile>', ''))
            dependency = workspace / 'Dependency'
            dependency.mkdir()
            (dependency / 'Dependency.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
            dependency_source = dependency / 'Code.cs'
            original_dependency = 'public static class Dependency { public static int Value => 1; }'
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
            command = [str(ROOT / 'scripts/bazel-launcher.sh'), f'--output_base={folder / "base"}']

            def bazel(*args, success=True):
                if options.graph_worker and args[0] in ('run', 'build', 'test'):
                    args = args[:1] + ('--strategy=MSBuildGraph=worker', '--worker_sandboxing') + args[1:]
                result = subprocess.run(command + list(args), cwd=workspace, env=os.environ, text=True, capture_output=True)
                assert (result.returncode == 0) == success, result.stdout + result.stderr
                return result.stdout + result.stderr

            try:
                bazel('run', '//:sync')
                bazel('run', '//:sync', '--', '--check')
                graph_options = ',linux_stable_paths=True,linux_worker=True' if options.graph_worker else ''
                (workspace / 'BUILD.bazel').write_text(authored + 'load(":graph.generated.bzl","app_graph")\napp_graph(name="graph"' + graph_options + ')\n' + tests)
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
                reference = workspace / 'bazel-bin/graph.graph/workspace/Dependency/obj/Release/net10.0/ref/Dependency.dll'
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
