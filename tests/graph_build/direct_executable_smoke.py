"""Exercise the opt-in public smoke launcher with a disposable real managed probe."""

import json
import os
from pathlib import Path
import shutil
import subprocess

from qualify import ROOT, fixture
from fixture_host import temporary_directory, WINDOWS, bazel_environment, bazel_startup, sdk_declaration


PROBE = r'''
using System;
using System.Linq;
using System.Text.Json;
Console.WriteLine("SMOKE_PROBE=" + JsonSerializer.Serialize(new {
    version = Environment.Version.ToString(),
    corelib = typeof(object).Assembly.Location,
    root = Environment.GetEnvironmentVariable("DOTNET_ROOT"),
    host = Environment.GetEnvironmentVariable("DOTNET_HOST_PATH"),
    roots = new[] { "X64", "X86", "ARM", "ARM64" }.Select(arch => Environment.GetEnvironmentVariable("DOTNET_ROOT_" + arch)).ToArray(),
    multilevel = Environment.GetEnvironmentVariable("DOTNET_MULTILEVEL_LOOKUP"),
    coreRoot = Environment.GetEnvironmentVariable("CORE_ROOT"),
    args,
}));
return args.Length > 0 && args[0] == "exit-seven" ? 7 : 0;
'''


def main():
    with temporary_directory(prefix='direct-smoke-') as temporary:
        root = Path(temporary).resolve()
        workspace = root / 'workspace'
        workspace.mkdir()
        contract = fixture(workspace, count=1)
        (workspace / 'P0/Code.cs').write_text(PROBE)
        contract['Projects']['P0/P0.csproj']['Inputs'] = ['P0/P0.csproj', 'P0/Code.cs']
        shutil.copy(ROOT / 'global.json', workspace / 'global.json')
        contract['SharedInputs'].append('global.json')
        (workspace / 'contract.json').write_text(json.dumps(contract))
        (workspace / 'MODULE.bazel').write_text(
            'module(name="direct_smoke_probe")\n'
            'bazel_dep(name="rules_msbuild",version="0.0.0")\n'
            f'local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})\n'
            'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
            + sdk_declaration(global_json='//:global.json')
            + 'use_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
        (workspace / 'BUILD.bazel').write_text(
            'load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph","msbuild_graph_runner","msbuild_graph_test")\n'
            'msbuild_graph_runner(name="runner")\n'
            'msbuild_graph(name="graph",runner=":runner",contract="contract.json",'
            'srcs=["P0/P0.csproj","P0/Code.cs","Directory.Build.props","global.json"])\n'
            'msbuild_graph_test(name="smoke",graph=":graph",assembly="P0/bin/Release/net11.0/P0.dll",direct_executable_smoke=True)\n'
            'msbuild_graph_test(name="writable",graph=":graph",assembly="P0/bin/Release/net11.0/P0.dll",expected_exit_code=7,args=["exit-seven"],test_working_directory="work",test_output_dirs=["results"])\n')
        startup = bazel_startup(f'--output_base={root / "bazel"}')

        def bazel(*args, success=True):
            result = subprocess.run(startup + list(args), cwd=workspace, env=bazel_environment(), text=True, capture_output=True)
            assert (result.returncode == 0) == success, result.stdout + result.stderr
            return result.stdout + result.stderr

        try:
            bazel('test', '//:smoke', '//:writable', '--nocache_test_results', '--test_output=errors')
            launcher = workspace / ('bazel-bin/smoke.exe' if WINDOWS else 'bazel-bin/smoke')
            runfiles = Path(str(launcher) + '.runfiles')
            hostile = root / 'ambient SDK'
            hostile.mkdir()
            marker = root / 'ambient-invoked'
            ambient = hostile / 'dotnet'
            ambient.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\nexit 89\n')
            ambient.chmod(0o755)
            env = dict(os.environ, RUNFILES_DIR=str(runfiles),
                       PATH=str(hostile) + os.pathsep + os.environ['PATH'],
                       DOTNET_ROOT=str(hostile), DOTNET_HOST_PATH=str(ambient),
                       DOTNET_ROOT_X64=str(hostile), DOTNET_ROOT_ARM64=str(hostile),
                       DOTNET_MULTILEVEL_LOOKUP='1', CORE_ROOT=str(hostile))
            if WINDOWS:
                env.pop('RUNFILES_DIR', None)
                env['RUNFILES_MANIFEST_FILE'] = str(launcher) + '.runfiles_manifest'
                env['RUNFILES_MANIFEST_ONLY'] = '1'
            for key in ('TESTBRIDGE_TEST_ONLY', 'TEST_TOTAL_SHARDS', 'TEST_SHARD_INDEX'):
                env.pop(key, None)

            def invoke(arguments=(), extra=None, code=0, error=None):
                result = subprocess.run([str(launcher), *arguments], cwd=root,
                                        env=dict(env, **(extra or {})), text=True, capture_output=True)
                assert result.returncode == code, result.stdout + result.stderr
                assert not marker.exists(), 'Launcher invoked ambient dotnet'
                if error:
                    assert error in result.stderr, result.stdout + result.stderr
                    assert 'SMOKE_PROBE=' not in result.stdout
                    return None
                lines = [line for line in result.stdout.splitlines() if line.startswith('SMOKE_PROBE=')]
                assert len(lines) == 1, result.stdout + result.stderr
                return json.loads(lines[0].split('=', 1)[1])

            arguments = ['space argument', '', "quote'and\"double", '*', '$HOME', '--option=value']
            observed = invoke(arguments)
            selected = Path(observed['root'])
            if WINDOWS:
                # Manifest-mode trees resolve to the declared physical runtime.
                entries = Path(env['RUNFILES_MANIFEST_FILE']).read_text().splitlines()
                targets = []
                for line in entries:
                    escaped = line.startswith(' ')
                    _, target = line.lstrip(' ').split(' ', 1)
                    if escaped:
                        target = target.replace('\\s', ' ').replace('\\n', '\n').replace('\\b', '\\')
                    targets.append(Path(target).resolve())
                assert selected.resolve() in targets, observed
            else:
                assert selected.is_relative_to(runfiles), observed
            assert observed['version'] == '11.0.0', observed
            # CoreLib reports a canonical execroot path, while DOTNET_ROOT
            # retains the runfiles symlink path supplied to the selected host.
            assert Path(observed['corelib']).resolve().is_relative_to(selected.resolve()), observed
            assert Path(observed['corelib']).parent.name == observed['version'], observed
            assert Path(observed['host']).resolve() == (selected / ('dotnet.exe' if WINDOWS else 'dotnet')).resolve(), observed
            assert len(observed['roots']) == 4 and all(Path(value).resolve() == selected.resolve() for value in observed['roots']), observed
            assert observed['multilevel'] == '0' and observed['coreRoot'] is None, observed
            assert observed['args'] == arguments, observed
            assert invoke(['exit-seven'], code=7)['args'] == ['exit-seven']
            invoke(extra={'TESTBRIDGE_TEST_ONLY': 'Some.Test'}, code=1, error='filtering')
            invoke(extra={'TEST_TOTAL_SHARDS': '2', 'TEST_SHARD_INDEX': '0'}, code=1, error='sharding')
            invoke(extra={'TEST_TOTAL_SHARDS': '1', 'TEST_SHARD_INDEX': '1'}, code=1, error='sharding')
            invoke(extra={'TEST_TOTAL_SHARDS': '1', 'TEST_SHARD_INDEX': '0'})
            empty = root / 'missing declared runtime'
            empty.mkdir()
            if WINDOWS:
                missing_manifest = root / 'missing-runtime.manifest'
                remaining = [line for line, target in zip(entries, targets) if target != selected.resolve()]
                assert len(remaining) < len(entries), entries
                # Keep the PE launcher's script and library, remove only its host.
                missing_manifest.write_text('\n'.join(remaining) + '\n')
                missing = {'RUNFILES_DIR': '', 'RUNFILES_MANIFEST_FILE': str(missing_manifest), 'RUNFILES_MANIFEST_ONLY': '1'}
            else:
                missing = {'RUNFILES_DIR': str(empty), 'RUNFILES_MANIFEST_FILE': '', 'RUNFILES_MANIFEST_ONLY': '0'}
            invoke(extra=missing, code=1, error='declared runtime host')
            failed = bazel('test', '//:smoke', '--nocache_test_results', '--test_output=errors',
                           '--test_arg=exit-seven', success=False)
            assert 'FAILED' in failed and 'SMOKE_PROBE=' in failed, failed
            filtered = bazel('test', '//:smoke', '--nocache_test_results', '--test_output=errors',
                             '--test_filter=Some.Test', success=False)
            assert 'filtering' in filtered, filtered
        finally:
            subprocess.run(startup + ['shutdown'], cwd=workspace, check=True, capture_output=True)
        print('PASS: public direct smoke, selected .NET 11/CoreLib, stdout, args, exit, hostile environment, missing host, filtering/sharding')


if __name__ == '__main__':
    main()
