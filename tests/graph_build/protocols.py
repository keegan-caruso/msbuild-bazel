"""Qualify real MTP and VSTest packages through generated graph rules."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/explicit_msbuild'))
from protocol import setup as mtp_setup
from vstest import setup as vstest_setup


def main():
    with tempfile.TemporaryDirectory(prefix='graph-protocols-') as temporary:
        for protocol, setup in [('mtp', mtp_setup), ('vstest', vstest_setup)]:
            folder = Path(temporary).resolve() / protocol
            folder.mkdir()
            workspace = setup(folder)
            shutil.copy(ROOT / 'global.json', workspace / 'global.json')
            module = (ROOT / 'examples/graph-quickstart/MODULE.bazel').read_text().replace('"../msbuild-bazel"', json.dumps(str(ROOT)))
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
            for path in workspace.rglob('BUILD.bazel'):
                if path.parent.name != 'packages':
                    path.unlink()
            authored = ('load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\n'
                        'load("@rules_msbuild//msbuild:defs.bzl","msbuild_package_lock","msbuild_graph_test","msbuild_test_tool")\n'
                        'msbuild_package_lock(name="packages",packages=' + json.dumps(roots) + ')\n'
                        'msbuild_sync(name="sync",mode="graph",package_build=True,package_lock=":packages",projects=' + json.dumps(projects) + ')\n')
            (workspace / 'BUILD.bazel').write_text(authored)
            command = [str(ROOT / 'scripts/bazel-launcher.sh'), f'--output_base={folder / "base"}']

            def bazel(*args, success=True):
                result = subprocess.run(command + list(args), cwd=workspace, env=os.environ, text=True, capture_output=True)
                assert (result.returncode == 0) == success, result.stdout + result.stderr
                return result.stdout + result.stderr

            try:
                bazel('run', '//:sync')
                bazel('run', '//:sync', '--', '--check')
                (workspace / 'BUILD.bazel').write_text(authored + 'load(":graph.generated.bzl","app_graph")\napp_graph(name="graph")\n' + tests)
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
            finally:
                bazel('shutdown')


if __name__ == '__main__':
    main()
