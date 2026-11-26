"""Fresh SDK design-time graph state for an external C# editor consumer."""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
import tempfile

from qualify import DOTNET, ROOT, RUNNER, SDK, fixture, run
from fixture_host import assert_no_host_paths


def bazel_control(base, root):
    # Build through the public rule, with a declared downloaded SDK and staged
    # generated files, then resolve the portable metadata as an editor would.
    shutil.copy(ROOT / 'global.json', root / 'global.json')
    (root / 'MODULE.bazel').write_text(
        'module(name="design_time_probe")\n'
        'bazel_dep(name="rules_msbuild",version="0.0.0")\n'
        f'local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})\n'
        'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
        'dotnet.sdk(name="dotnet",global_json="//:global.json")\n'
        'use_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
    build_file = root / 'BUILD.bazel'
    declarations = ('load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\n'
                    'msbuild_sync(name="sync",projects=["P2/P2.csproj"])\n')
    build_file.write_text(declarations)
    startup = [str(ROOT / 'scripts/bazel-launcher.sh'), f'--output_base={base / "bazel"}']
    env = dict(os.environ, RULES_MSBUILD_BAZELISK=os.environ.get(
        'RULES_MSBUILD_BAZELISK', str(SDK.parent / 'bin/bazelisk')))

    def bazel(*arguments):
        result = subprocess.run(startup + list(arguments), cwd=root, env=env, text=True, capture_output=True)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout.strip()

    try:
        bazel('run', '//:sync')
        build_file.write_text(declarations + 'load(":graph.generated.bzl","app_graph")\n'
                              'app_graph(name="editor",target="DesignTimeBuild")\n')
        bazel('build', '//:editor', '--jobs=2')
        output = root / 'bazel-bin/editor.graph'
        result = json.loads((output / 'report.json').read_text())
        project_outputs = {p[key] for p in result['projects'] for key in ('targetPath', 'targetRefPath')}
        # SDK references can be remapped to a separately retained matching SDK;
        # project references bind source projects, whose DLLs need not exist.
        for project in result['projects']:
            for source in project['compile']:
                assert (output / 'workspace' / Path(project['project']).parent / source).is_file(), source
            for reference in project['references']:
                resolved = reference.replace('{workspace}', str(output / 'workspace')).replace('{sdk}', str(SDK))
                assert Path(resolved).is_file() or reference in project_outputs, reference
        assert not list((output / 'workspace').rglob('bin/**/*.dll'))
        assert 'EDITED_SYMBOL' in result['projects'][2]['defineConstants'].split(';')
        assert str(base / '.editorconfig') not in (output / 'report.json').read_text()
        print('PASS: public Bazel DesignTimeBuild output and external-consumer source/reference path resolution')
    finally:
        bazel('shutdown')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bazel', action='store_true')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='graph-design-time-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        ancestor = base / '.editorconfig'
        ancestor.write_text('[*.cs]\ndotnet_diagnostic.IDE0055.severity = error\n')
        contract = fixture(root)
        props = root / 'Directory.Build.props'
        props.write_text('<Project><PropertyGroup><DefineConstants>$(DefineConstants);EDITOR_SYMBOL</DefineConstants>'
                         '</PropertyGroup></Project>')
        # Invalid C# still produces design-time state without invoking a compiler.
        (root / 'P2/Code.cs').write_text('this is incomplete editor source !!!')
        manifest = base / 'contract.json'
        manifest.write_text(json.dumps(contract))
        report = base / 'editor.json'
        run(DOTNET, RUNNER, 'build', root, manifest, report, base / 'cache', 'DesignTimeBuild')
        result = json.loads(report.read_text())
        assert result['designTimeBuild'] and result['version'] == 1, result
        assert len(result['projects']) == 3, result
        for project in result['projects']:
            assert project['properties']['DesignTimeBuild'] == 'true', project
            assert 'Code.cs' in project['compile'], project
            assert 'EDITOR_SYMBOL' in project['defineConstants'].split(';'), project
            assert project['compilerArguments'], project
            assert all(str(ancestor) not in item for item in project['compilerArguments']), project['compilerArguments']
            assert any('System.Runtime.dll' in item for item in project['references']), project
        assert result['projects'][2]['projectReferences'] == ['P0/P0.csproj', 'P1/P1.csproj'], result['projects'][2]['projectReferences']
        assert_no_host_paths(result, root, SDK)
        project_outputs = {p[key] for p in result['projects'] for key in ('targetPath', 'targetRefPath')}
        for project in result['projects']:
            for source in project['compile']:
                assert (root / Path(project['project']).parent / source).is_file(), source
            for reference in project['references']:
                resolved = reference.replace('{workspace}', str(root)).replace('{sdk}', str(SDK))
                assert Path(resolved).is_file() or reference in project_outputs, reference
        assert not list(root.rglob('*.dll')), 'design-time request compiled an assembly'
        assert not (base / 'cache').exists(), 'design-time request published project snapshots'
        # Re-evaluation sees source and property changes; no project snapshot hit.
        (root / 'P2/Added.cs').write_text('class Added {}')
        contract['Projects']['P2/P2.csproj']['Inputs'].append('P2/Added.cs')
        props.write_text(props.read_text().replace('EDITOR_SYMBOL', 'EDITED_SYMBOL'))
        manifest.write_text(json.dumps(contract))
        run(DOTNET, RUNNER, 'build', root, manifest, report, base / 'cache', 'DesignTimeBuild')
        edited = json.loads(report.read_text())['projects'][2]
        assert 'Added.cs' in edited['compile'], edited
        assert 'EDITED_SYMBOL' in edited['defineConstants'].split(';'), edited
        # Per-entry global properties cannot turn compilation back on.
        contract['Version'] = 6
        contract['EntryProperties'] = {contract['Entry']: {'SkipCompilerExecution': 'false'}}
        manifest.write_text(json.dumps(contract))
        failure = run(DOTNET, RUNNER, 'build', root, manifest, report, base / 'cache',
                      'DesignTimeBuild', success=False)
        assert 'cannot be overridden' in failure.stdout + failure.stderr
        contract.pop('EntryProperties')
        contract['Version'] = 1
        if args.bazel:
            bazel_control(base, root)
        print('PASS: fresh C# design-time Compile, project/framework references, symbols, compiler arguments and edits without compilation')


if __name__ == '__main__':
    main()
