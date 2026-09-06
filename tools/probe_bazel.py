"""Prepare and measure two explicit Bazel/MSBuild actions with sandboxing."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DOTNET = Path(os.environ.get('SPIKE_DOTNET_ROOT', ROOT / '.tools/dotnet')) / 'dotnet'
BAZEL = Path(os.environ.get('SPIKE_BAZEL', ROOT / '.tools/bin/bazel'))


def json_stream(path):
    text = path.read_text()
    decoder = json.JSONDecoder()
    while text.strip():
        value, end = decoder.raw_decode(text.lstrip())
        yield value
        text = text.lstrip()[end:]


def probe(output, identity=False):
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / 'workspace'
    workspace.mkdir()
    report = dict(schemaVersion=1, platform=platform.platform(), identityProbe=identity, cases={})
    env = dict(os.environ, DOTNET_ROOT=str(DOTNET.parent),
               DOTNET_CLI_HOME=str(output / 'dotnet-home'),
               NUGET_PACKAGES=str(output / 'prepare/.nuget/packages'),
               DOTNET_NOLOGO='1', DOTNET_CLI_TELEMETRY_OPTOUT='1')

    if identity:
        env['SPIKE_INPUT_FLAVOR'] = 'env-v1'

    def run(name, command, cwd=workspace, require=True):
        process = subprocess.run([str(arg) for arg in command], cwd=cwd, env=env, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        log = output / (name + '.log')
        log.write_text(process.stdout)
        observed = dict(command=[str(arg) for arg in command], returncode=process.returncode, log=str(log))
        report[name] = observed
        (output / 'report.json').write_text(json.dumps(report, indent=2))
        if require and process.returncode:
            raise RuntimeError(f'{name} failed; see {log}')
        return process

    report['sdkVersion'] = run('sdkVersion', [DOTNET, '--version'], ROOT).stdout.strip()
    report['engineVersion'] = run('engineVersion', [DOTNET, 'msbuild', '-version', '-nologo'], ROOT).stdout.strip()
    if report['sdkVersion'] != '10.0.100':
        raise ValueError('expected pinned SDK 10.0.100')
    report['python'] = dict(executable=sys.executable, version=sys.version)
    prepare = output / 'prepare'
    shutil.copytree(ROOT / 'tests/fixtures/two-projects', prepare)
    if identity:
        project = prepare / 'Shared/Shared.csproj'
        tree = ET.parse(project)
        ET.SubElement(tree.getroot(), 'Import', Project='BuildInputs.targets')
        tree.write(project)
        # Locate the fixture source without depending on its filename.
        source = next((prepare / 'Shared').glob('*.cs'))
        source.write_text(source.read_text().replace('"shared-v1"', '"shared-v1" + "/" + Inputs.Value'))
        (prepare / 'Shared/value.txt').write_text('data-v1\n')
        (prepare / 'Shared/BuildInputs.targets').write_text('''<Project>
  <PropertyGroup><SpikeImportVersion>import-v1</SpikeImportVersion></PropertyGroup>
  <Target Name="GenerateSharedInput" BeforeTargets="CoreCompile">
    <ReadLinesFromFile File="$(MSBuildProjectDirectory)/value.txt">
      <Output TaskParameter="Lines" PropertyName="_SpikeInput" />
    </ReadLinesFromFile>
    <WriteLinesToFile File="$(IntermediateOutputPath)SpikeInputs.g.cs"
      Lines="namespace Shared { public static class Inputs { public const string Value = &quot;$(_SpikeInput)/$(SpikeImportVersion)/$(SPIKE_INPUT_FLAVOR)&quot;%3B } }"
      Overwrite="true" />
    <ItemGroup><Compile Include="$(IntermediateOutputPath)SpikeInputs.g.cs" /></ItemGroup>
  </Target>
</Project>
''')
    shutil.copytree(prepare, workspace / 'src')
    run('restore', [DOTNET, 'msbuild', 'dirs.proj', '-t:Restore', '-p:Configuration=Release', '-nologo'], prepare)
    run('pluginBuild', [DOTNET, 'build', ROOT / 'tools/ReplayPlugin', '-c', 'Release', '--nologo'], ROOT)
    # Compile actions only consume normalized restore files; the fixture has no
    # application PackageReferences. Traversal itself is preparation-only.
    (workspace / 'restore').mkdir()
    for project in ('Shared', 'App'):
        state = {}
        for source in sorted((prepare / project / 'obj').rglob('*')):
            if source.is_file():
                contents = source.read_text().replace(str(prepare), '${WORKSPACE}').replace(str(DOTNET.parent.resolve()), '${SDK}')
                state[source.relative_to(prepare).as_posix()] = contents
        (workspace / 'restore' / (project + '.json')).write_text(json.dumps(state, indent=2))
    run('baseline', [DOTNET, 'msbuild', 'dirs.proj', '-t:Build', '-p:Configuration=Release',
                     '-graphBuild', '-isolateProjects', '-nologo'], prepare)
    report['baselineOutput'] = run('baseline-app', [DOTNET, prepare / 'App/bin/Release/net10.0/App.dll']).stdout.strip()
    shutil.copyfile(ROOT / 'tools/ReplayPlugin/bin/Release/net10.0/ReplayPlugin.dll', workspace / 'ReplayPlugin.dll')
    shutil.copyfile(ROOT / 'tools/bazel_action.py', workspace / 'bazel_action.py')
    shutil.copyfile(ROOT / 'bazel/msbuild.bzl', workspace / 'msbuild.bzl')
    (workspace / 'MODULE.bazel').write_text('module(name="msbuild_fixture")\n'
        'local_dotnet_sdk = use_repo_rule("//:msbuild.bzl", "local_dotnet_sdk")\n'
        f'local_dotnet_sdk(name="dotnet", path={json.dumps(str(DOTNET.parent.resolve()))})\n')
    library = Path(sysconfig.get_config_var('LIBDIR')) / sysconfig.get_config_var('LDLIBRARY')
    if sysconfig.get_config_var('PYTHONFRAMEWORK'):
        library = Path(sys.prefix) / sysconfig.get_config_var('PYTHONFRAMEWORK')
    runtime = dict(python=str(Path(sys.executable).resolve()), stdlib=str(Path(sysconfig.get_path('stdlib')).resolve()),
                   library=str(library.resolve()) if library.is_file() else '')
    with (workspace / 'MODULE.bazel').open('a') as module:
        module.write('local_python_runtime = use_repo_rule("//:msbuild.bzl", "local_python_runtime")\n')
        module.write('local_python_runtime(name="python", ' + ', '.join(f'{key}={json.dumps(value)}' for key, value in runtime.items()) + ')\n')
    host_identity = dict(schemaVersion=1, platform=platform.platform(), machine=platform.machine(),
                         pythonVersion=sys.version, runtime=runtime, policyRevision=1)
    (workspace / 'host-identity.json').write_text(json.dumps(host_identity, indent=2))
    common = ['src/Directory.Build.props', 'src/Directory.Build.targets', 'src/global.json', 'src/NuGet.Config']
    # NuGet.Config fixture casing follows the existing source tree.
    common = [p for p in common if (workspace / p).exists()]
    settings = dict(plugin='ReplayPlugin.dll', runner='bazel_action.py', sdk='@dotnet//:files',
                    dotnet='@dotnet//:sdk/dotnet', python='@python//:python', runtime='@python//:files',
                    host_identity='host-identity.json', build_environment={'SPIKE_INPUT_FLAVOR': 'env-v1'} if identity else {})
    def rule(name, project, sources, restore, dependency=None, undeclared_probe=''):
        attrs = dict(settings, name=name, project=project, srcs=sources, restore=restore,
                     undeclared_probe=undeclared_probe)
        if dependency:
            attrs['dependency'] = dependency
        return 'msbuild_project(\n' + ''.join(f'    {k} = {json.dumps(v)},\n' for k, v in attrs.items()) + ')\n'
    shared_sources = common + ['src/Shared/' + p.name for p in (workspace / 'src/Shared').iterdir() if p.is_file()]
    app_sources = common + ['src/Shared/Shared.csproj'] + ['src/App/' + p.name for p in (workspace / 'src/App').iterdir() if p.is_file()]
    if identity:
        app_sources.append('src/Shared/BuildInputs.targets')
    build = 'load(":msbuild.bzl", "msbuild_project")\n' + rule('shared', 'Shared', shared_sources, ['restore/Shared.json'])
    build += rule('app', 'App', app_sources, ['restore/Shared.json', 'restore/App.json'], ':shared')
    (workspace / 'undeclared.txt').write_text('must not be visible inside an action')
    build += rule('undeclared', 'Shared', shared_sources, ['restore/Shared.json'], undeclared_probe='undeclared.txt')
    (workspace / 'BUILD.bazel').write_text(build)
    shutil.rmtree(prepare)
    report['preparationWorkspaceAbsent'] = not prepare.exists()
    base = output / 'bazel-base'
    cache = output / 'disk-cache'
    startup = [BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc', f'--output_base={base}', f'--output_user_root={output / "bazel-user"}']
    strategy = 'darwin-sandbox' if platform.system() == 'Darwin' else 'linux-sandbox'
    report['sandboxStrategy'] = strategy
    version = run('bazelVersion', startup + ['version', '--gnu_format']).stdout.strip()
    if not version.endswith(('bazel 8.4.2', 'bazel 8.4.2- (@non-git)')):
        raise ValueError('expected pinned Bazel 8.4.2: ' + version)
    report['bazelVersion'] = version.splitlines()[-1]
    flags = [f'--disk_cache={cache}', f'--spawn_strategy={strategy}', f'--strategy=MsbuildProject={strategy}',
             '--noshow_progress', '--color=no', '--curses=no', '--jobs=2']

    def build_case(name):
        log = output / (name + '.execution.json')
        result = run(name, startup + ['build', '//:app', *flags, f'--execution_log_json_file={log}'])
        records = [entry for entry in json_stream(log) if entry.get('mnemonic') == 'MsbuildProject']
        def project(record):
            label = record.get('targetLabel', '')
            return 'Shared' if label.endswith(':shared') else 'App'
        executions = [dict(project=project(r), runner=r.get('runner', ''), cacheHit=r.get('cacheHit', False),
                           inputs=[item['path'] for item in r.get('inputs', [])],
                           status=r.get('status'), exitCode=r.get('exitCode'), commandArgs=r.get('commandArgs'),
                           remotable=r.get('remotable'), remoteCacheable=r.get('remoteCacheable')) for r in records]
        executed = sorted(r['project'] for r in executions if not r['cacheHit'])
        cached = sorted(r['project'] for r in executions if r['cacheHit'])
        binary = workspace / 'bazel-bin/app.bundle/artifacts/App/bin/Release/net10.0/App.dll'
        app = run(name + '-app', [DOTNET, binary])
        native = run(name + '-apphost', [binary.with_name('App')])
        observed = dict(executedProjects=executed, cacheHitProjects=cached, executions=executions,
                        applicationOutput=app.stdout.strip(), applicationReturncode=app.returncode,
                        apphostOutput=native.stdout.strip(), apphostReturncode=native.returncode,
                        executionLog=str(log))
        report['cases'][name] = observed
        (output / 'report.json').write_text(json.dumps(report, indent=2))
        return result

    build_case('cold')
    shared = json.loads((workspace / 'bazel-bin/shared.bundle/action.json').read_text())
    app = json.loads((workspace / 'bazel-bin/app.bundle/action.json').read_text())
    report.update(sharedWorkspace=shared['workspace'], appWorkspace=app['workspace'],
                  appHasSharedSources=bool(app['sharedSources']),
                  sharedCompiledProjects=shared['compiledProjects'], appCompiledProjects=app['compiledProjects'])
    build_case('unchanged')
    program = workspace / 'src/App/Program.cs'
    program.write_text(program.read_text().replace('app-v1', 'app-v2'))
    build_case('appEdit')
    for source in (workspace / 'src/Shared').glob('*.cs'):
        source.write_text(source.read_text().replace('shared-v1', 'shared-v2'))
    build_case('sharedEdit')
    run('clean', startup + ['clean'])
    build_case('diskCache')
    startup = [f'--output_base={output / "second-bazel-base"}' if str(arg).startswith('--output_base=') else arg for arg in startup]
    build_case('newOutputBase')
    if identity:
        target = workspace / 'src/Shared/BuildInputs.targets'
        target.write_text(target.read_text().replace('import-v1', 'import-v2'))
        build_case('importEdit')
        (workspace / 'src/Shared/value.txt').write_text('data-v2\n')
        build_case('dataEdit')
        build_file = workspace / 'BUILD.bazel'
        build_file.write_text(build_file.read_text().replace('env-v1', 'env-v2'))
        build_case('environmentEdit')
        env['SPIKE_INPUT_FLAVOR'] = 'ambient-must-not-leak'
        env['PYTHONPATH'] = '/does-not-exist'
        build_case('ambientEnvironment')
        restore = workspace / 'restore/App.json'
        state = json.loads(restore.read_text())
        key = 'App/obj/project.assets.json'
        assets = json.loads(state[key])
        assets['spikeIdentityProbe'] = 1
        state[key] = json.dumps(assets)
        restore.write_text(json.dumps(state, indent=2))
        build_case('restoreEdit')
        host_identity['policyRevision'] = 2
        (workspace / 'host-identity.json').write_text(json.dumps(host_identity, indent=2))
        build_case('hostIdentityEdit')
    negative_log = output / 'undeclared.execution.json'
    negative = run('undeclaredInput', startup + ['build', '//:undeclared', *flags,
                   f'--execution_log_json_file={negative_log}'], require=False)
    report['undeclaredInput']['executionLog'] = str(negative_log)
    if 'FileNotFoundError' not in negative.stdout or 'undeclared.txt' not in negative.stdout:
        raise RuntimeError('undeclared-input probe failed for an unexpected reason')
    if negative.returncode == 0:
        raise RuntimeError('sandbox exposed undeclared relative input')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(output / 'report.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--identity-probe', action='store_true')
    args = parser.parse_args()
    try:
        probe(args.output.resolve(), args.identity_probe)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
