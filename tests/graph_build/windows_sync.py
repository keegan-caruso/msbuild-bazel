"""Qualify declared-source ProjectSync on a native Windows x64 host."""

import json
from pathlib import Path
import platform
import subprocess
import tempfile
from xml.sax.saxutils import escape

from fixture_host import ROOT, WINDOWS, bazel_environment, bazel_startup, sdk_declaration


def main():
    if not WINDOWS or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise SystemExit('Requires native Windows x64')
    with tempfile.TemporaryDirectory(prefix='wsync-') as temporary:
        base = Path(temporary)
        workspace = base / 'workspace'
        workspace.mkdir()
        (workspace / 'global.json').write_bytes((ROOT / 'global.json').read_bytes())
        (workspace / 'MODULE.bazel').write_text(
            'module(name="windows_sync_fixture")\nbazel_dep(name="rules_msbuild",version="0.0.0")\n'
            f'local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})\n'
            'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
            + sdk_declaration(global_json='//:global.json') + 'use_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
        (workspace / 'BUILD.bazel').write_text(
            'load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\n'
            'msbuild_sync(name="sync", projects=["App.csproj"], srcs=["App.csproj","App.cs","Lib/Lib.csproj","Lib/Lib.cs","global.json"], windows_isolation=True)\n')
        library = workspace / 'Lib'
        library.mkdir()
        (library / 'Lib.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net11.0</TargetFramework></PropertyGroup></Project>')
        (library / 'Lib.cs').write_text('public class Library {}')
        project = workspace / 'App.csproj'
        template = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net11.0</TargetFramework><DefaultItemExcludes>$(DefaultItemExcludes);Lib/**</DefaultItemExcludes>{}</PropertyGroup><ItemGroup><ProjectReference Include="Lib/Lib.csproj" /></ItemGroup></Project>'
        project.write_text(template.format(''))
        (workspace / 'App.cs').write_text('public class App {}')
        prefix = bazel_startup('--output_base=' + str(base / 'bazel'))

        def bazel(*args, success=True):
            result = subprocess.run([*prefix, *args], cwd=workspace, env=bazel_environment(),
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            assert (result.returncode == 0) == success, result.stdout
            return result.stdout

        try:
            bazel('run', '//:sync')
            outputs = [workspace / name for name in ['graph.generated.json', 'graph.generated.bzl']]
            generated = [path.read_bytes() for path in outputs]
            assert set(json.loads(generated[0])['Projects']) == {'App.csproj', 'Lib/Lib.csproj'}
            bazel('run', '//:sync', '--', '--check')
            sentinel = base / 'parent-private.txt'
            sentinel.write_text('outside declared sync inputs')
            project.write_text(template.format(
                "<Marker>$([System.IO.File]::ReadAllText('" + escape(str(sentinel)) + "'))</Marker>"))
            diagnostic = bazel('run', '//:sync', success=False)
            assert sentinel.name in diagnostic and 'denied' in diagnostic.lower(), diagnostic
            assert [path.read_bytes() for path in outputs] == generated
        finally:
            bazel('clean', '--expunge')
    print('PASS: native Windows x64 isolated sync, generated graph check and undeclared read denial')


if __name__ == '__main__':
    main()
