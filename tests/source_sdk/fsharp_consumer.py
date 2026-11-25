"""Exercise an ordered F# graph with the full, pinned Linux ARM64 VMR 11 SDK."""

import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

from source_action_recovery import actions

SDK_SHA256 = '993765849ca1f97d64ca1a157b34158b37dc75facff43d41707365dc8724ec85'
PACKAGE = 'FSharp.Core.11.0.101.nupkg'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sdk_archive', type=Path)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    archive = args.sdk_archive.resolve(strict=True)
    root = args.directory.resolve()
    root.mkdir(parents=True, exist_ok=False)
    rules = Path(__file__).resolve().parents[2]
    workspace = root / 'workspace'
    shutil.copytree(Path(__file__).with_name('fsharp'), workspace)
    build = workspace / 'BUILD.bazel'
    (workspace / 'BUILD.bazel.in').rename(build)
    with tarfile.open(archive, 'r|gz') as tar:
        for member in tar:
            if member.name.removeprefix('./') == 'sdk/11.0.100/FSharp/library-packs/' + PACKAGE:
                with tar.extractfile(member) as stream, (workspace / PACKAGE).open('wb') as output:
                    shutil.copyfileobj(stream, output)
                break
        else:
            raise ValueError('VMR SDK lacks ' + PACKAGE)
    integrity = 'sha256-' + base64.b64encode(bytes.fromhex(SDK_SHA256)).decode()
    (workspace / 'MODULE.bazel').write_text(
        'module(name="vmr_fsharp")\n'
        'bazel_dep(name="rules_msbuild",version="0.0.0")\n'
        f'local_path_override(module_name="rules_msbuild",path={json.dumps(str(rules))})\n'
        'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
        'dotnet.sdk_archive(name="vmr",version="11.0.100",runtime_version="11.0.0",platform="linux-arm64",'
        f'urls=[{json.dumps(archive.as_uri())}],integrity="{integrity}")\n'
        'use_repo(dotnet,"vmr")\nregister_toolchains("@vmr//:all")\n')

    def bazel(label, command, target, *options, base='base', success=True):
        binary = os.environ.get('RULES_MSBUILD_BAZEL', str(rules / 'scripts/bazel-launcher.sh'))
        flags = [
            '--batch', '--host_jvm_args=-Xmx1024m',
            '--output_base=' + str(root / base),
            '--output_user_root=' + str(root / 'user'),
            '--ignore_all_rc_files', command, target, '--jobs=1', '--remote_cache=',
            '--disk_cache=' + str(root / 'disk-cache'),
        ]
        log_path = root / (label + '.log')
        with log_path.open('w') as log:
            result = subprocess.run([binary, *flags, *options], cwd=workspace, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=600)
        text = log_path.read_text()
        if success is not None and (result.returncode == 0) != success:
            raise RuntimeError(label + '\n' + text[-5000:])
        return result.returncode, text

    bazel('sync', 'run', '//:sync')
    with build.open('a') as output:
        output.write('load(":graph.generated.bzl", "app_graph")\n'
                     'load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_test")\n'
                     'app_graph(name="graph")\n'
                     'msbuild_graph_test(name="smoke",graph=":graph",project="App/App.fsproj")\n')

    def smoke(label, value, base='base'):
        log = root / (label + '.execution.json')
        _, output = bazel(label, 'test', '//:smoke', '--test_output=all', '--nocache_test_results',
                       '--execution_log_json_file=' + str(log), base=base)
        assert 'FSHARP_RESULT=' + str(value) in output.splitlines(), label
        rows = actions(log)
        assert any(r['mnemonic'] == 'TestRunner' and not r['cacheHit'] for r in rows)
        return [r for r in rows if r['mnemonic'] == 'MSBuildGraph']

    smoke('seed', 42)
    library = workspace / 'Library/Arithmetic.fs'
    library.write_text(library.read_text().replace('n + 1', 'n + 2'))
    smoke('inline-edit', 43)
    recovered = smoke('fresh-base', 43, base='fresh')
    assert len(recovered) == 1 and recovered[0]['cacheHit'], recovered
    bazel('sync-check', 'run', '//:sync', '--', '--check')

    project = workspace / 'Library/Library.fsproj'
    signature = '    <Compile Include="Arithmetic.fsi" />'
    implementation = '    <Compile Include="Arithmetic.fs" />'
    ordered = signature + '\n' + implementation
    assert ordered in project.read_text()
    project.write_text(project.read_text().replace(ordered, implementation + '\n' + signature))
    status, failure = bazel('reordered-sync', 'run', '//:sync', success=None)
    if status == 0:
        _, failure = bazel('reordered-build', 'build', '//:graph', success=False)
    assert 'error FS0238' in failure, failure[-3000:]
    print('PASS: VMR F# build, inline edit, forced fresh-base recovery, and signature order check')


if __name__ == '__main__':
    main()
