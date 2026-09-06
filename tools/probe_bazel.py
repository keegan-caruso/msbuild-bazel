"""Prepare and measure two explicit Bazel/MSBuild actions with sandboxing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import package_inputs
import binary_inputs
import runtime_inputs
import loader_inputs

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


def bundle_snapshot(directory):
    return {path.relative_to(directory).as_posix(): dict(
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        executable=bool(path.stat().st_mode & 0o111))
        for path in sorted(directory.rglob('*')) if path.is_file()}


def probe(output, identity=False, package_mode=False, staging=False, native_runtime=False, binary_packages=False):
    staging = staging or binary_packages
    has_packages = package_mode or binary_packages
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / 'workspace'
    workspace.mkdir()
    report = dict(binaryPackageProbe=binary_packages, schemaVersion=1, platform=platform.platform(), identityProbe=identity, packageProbe=package_mode, stagingProbe=staging, nativeRuntimeProbe=native_runtime, cases={})
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
    package_provider = (binary_inputs.Packages(output / 'binary-preparation', DOTNET, run)
                        if binary_packages else package_inputs)
    prepare = output / 'prepare'
    shutil.copytree(ROOT / 'tests/fixtures/two-projects', prepare)
    if has_packages:
        pins = package_provider.feed(prepare / 'package-feed')
        package_provider.configure(prepare, '1.0.0', prepare / 'package-feed')
        report['packagePins'] = pins
        report['packagePreparationDeleted'] = []
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
    shutil.copytree(prepare, workspace / 'src', ignore=shutil.ignore_patterns('package-feed'))
    run('restore', [DOTNET, 'msbuild', 'dirs.proj', '-t:Restore', '-p:Configuration=Release', '-nologo'], prepare)
    run('pluginBuild', [DOTNET, 'build', ROOT / 'tools/ReplayPlugin', '-c', 'Release', '--nologo'], ROOT)
    def capture_restore(preparation):
        (workspace / 'restore').mkdir(exist_ok=True)
        for project in ('Shared', 'App'):
            state = {}
            for source in sorted((preparation / project / 'obj').rglob('*')):
                if source.is_file():
                    contents = source.read_text().replace(str(preparation), '${WORKSPACE}').replace(str(DOTNET.parent.resolve()), '${SDK}')
                    state[source.relative_to(preparation).as_posix()] = contents
            (workspace / 'restore' / (project + '.json')).write_text(json.dumps(state, indent=2))
        if has_packages:
            package_provider.stage(preparation, workspace, pins)
    capture_restore(prepare)
    run('baseline', [DOTNET, 'msbuild', 'dirs.proj', '-t:Build', '-p:Configuration=Release',
                     '-graphBuild', '-isolateProjects', '-nologo'], prepare)
    report['baselineOutput'] = run('baseline-app', [DOTNET, prepare / 'App/bin/Release/net10.0/App.dll']).stdout.strip()
    shutil.copyfile(ROOT / 'tools/ReplayPlugin/bin/Release/net10.0/ReplayPlugin.dll', workspace / 'ReplayPlugin.dll')
    run('runnerBuild', [DOTNET, 'build', ROOT / 'tools/ActionRunner', '-c', 'Release', '--nologo'], ROOT)
    (workspace / 'runner').mkdir()
    for suffix in ('.dll', '.deps.json', '.runtimeconfig.json'):
        name = 'ActionRunner' + suffix
        shutil.copyfile(ROOT / 'tools/ActionRunner/bin/Release/net10.0' / name, workspace / 'runner' / name)
    for name in ('Action.props', 'Action.targets'):
        shutil.copyfile(ROOT / 'tools/ActionRunner/Build' / name, workspace / 'runner' / name)
    shutil.copyfile(ROOT / 'bazel/msbuild.bzl', workspace / 'msbuild.bzl')
    (workspace / 'MODULE.bazel').write_text('module(name="msbuild_fixture")\n'
        'local_dotnet_sdk = use_repo_rule("//:msbuild.bzl", "local_dotnet_sdk")\n'
        f'local_dotnet_sdk(name="dotnet", path={json.dumps(str(DOTNET.parent.resolve()))})\n')
    runtime = dict(dotnet=str(DOTNET.resolve()))
    if native_runtime:
        closure = runtime_inputs.prepare(workspace, [DOTNET])
        report['nativeRuntime'] = dict(storePaths=closure['storePaths'], fileCount=len(closure['files']), boundary=closure['boundary'])
        with (workspace / 'MODULE.bazel').open('a') as module:
            module.write('local_native_runtime = use_repo_rule("//:msbuild.bzl", "local_native_runtime")\n')
            module.write('local_native_runtime(name="native", manifest="//:runtime-closure.json")\n')
    host_identity = dict(schemaVersion=1, platform=platform.platform(), machine=platform.machine(),
                         runtime=runtime, policyRevision=1)
    (workspace / 'host-identity.json').write_text(json.dumps(host_identity, indent=2))
    common = ['src/Directory.Build.props', 'src/Directory.Build.targets', 'src/global.json', 'src/NuGet.Config']
    # NuGet.Config fixture casing follows the existing source tree.
    common = [p for p in common if (workspace / p).exists()]
    settings = dict(plugin='ReplayPlugin.dll', build_props='runner/Action.props', build_targets='runner/Action.targets', runner='runner/ActionRunner.dll',
                    runner_support=['runner/ActionRunner.deps.json', 'runner/ActionRunner.runtimeconfig.json'], sdk='@dotnet//:files',
                    dotnet='@dotnet//:sdk/dotnet',
                    host_identity='host-identity.json', build_environment={'SPIKE_INPUT_FLAVOR': 'env-v1'} if identity else {})
    if native_runtime:
        settings.update(native_runtime='@native//:files', native_manifest='runtime-closure.json')
    def rule(name, project, sources, restore, dependency=None, undeclared_probe=''):
        attrs = dict(settings, name=name, project=project, srcs=sources, restore=restore,
                     undeclared_probe=undeclared_probe)
        if has_packages:
            closure = json.loads((workspace / 'package-manifests' / (project + '.json')).read_text())
            attrs['packages'] = sorted('packages/' + package['path'] + '/' + entry['path']
                                       for package in closure['packages'] for entry in package['files'])
            attrs['package_manifest'] = f'package-manifests/{project}.json'
        if dependency:
            attrs['dependency'] = dependency
        return 'msbuild_project(\n' + ''.join(f'    {k} = {json.dumps(v)},\n' for k, v in attrs.items()) + ')\n'
    shared_sources = common + ['src/Shared/' + p.name for p in (workspace / 'src/Shared').iterdir() if p.is_file()]
    app_sources = common + ['src/Shared/Shared.csproj'] + ['src/App/' + p.name for p in (workspace / 'src/App').iterdir() if p.is_file()]
    if identity:
        app_sources.append('src/Shared/BuildInputs.targets')
    def write_build():
        build = 'load(":msbuild.bzl", "msbuild_project")\n' + rule('shared', 'Shared', shared_sources, ['restore/Shared.json'])
        build += rule('app', 'App', app_sources, ['restore/Shared.json', 'restore/App.json'], ':shared')
        build += rule('undeclared', 'Shared', shared_sources, ['restore/Shared.json'], undeclared_probe='undeclared.txt')
        (workspace / 'BUILD.bazel').write_text(build)
    (workspace / 'undeclared.txt').write_text('must not be visible inside an action')
    write_build()
    shutil.rmtree(prepare)
    report['preparationWorkspaceAbsent'] = not prepare.exists()
    if has_packages:
        report['packagePreparationDeleted'].append(not prepare.exists())
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
        if has_packages:
            observed['packageTargets'] = {project: json.loads((workspace / f'bazel-bin/{project.lower()}.diagnostics/action.json').read_text())['packageTargets']
                                          for project in executed}
        if binary_packages:
            observed['binaryAssets'] = binary_inputs.evidence(workspace, binary)
            observed['compiledProjects'] = {project: json.loads((workspace / f'bazel-bin/{project.lower()}.diagnostics/action.json').read_text())['compiledProjects']
                                            for project in executed}
        report['cases'][name] = observed
        (output / 'report.json').write_text(json.dumps(report, indent=2))
        return result

    build_case('cold')
    shared = json.loads((workspace / 'bazel-bin/shared.diagnostics/action.json').read_text())
    app = json.loads((workspace / 'bazel-bin/app.diagnostics/action.json').read_text())
    report.update(sharedWorkspace=shared['workspace'], appWorkspace=app['workspace'],
                  appHasSharedSources=bool(app['sharedSources']),
                  sharedCompiledProjects=shared['compiledProjects'], appCompiledProjects=app['compiledProjects'])
    if has_packages:
        report['packageTargets'] = dict(Shared=shared['packageTargets'], App=app['packageTargets'])
    build_case('unchanged')
    if staging:
        before = {p: bundle_snapshot(workspace / f'bazel-bin/{p}.bundle') for p in ('shared', 'app')}
        # A new output base AND an empty disk cache force real compilation at
        # different action paths, unlike the existing cache-recovery controls.
        startup = [f'--output_base={output / "staging-bazel-base"}' if str(arg).startswith('--output_base=') else arg for arg in startup]
        flags = [f'--disk_cache={output / "staging-disk-cache"}' if str(arg).startswith('--disk_cache=') else arg for arg in flags]
        build_case('freshExecution')
        after = {p: bundle_snapshot(workspace / f'bazel-bin/{p}.bundle') for p in ('shared', 'app')}
        report['staging'] = dict(before=before, after=after, differences={
            p: [name for name in sorted(before[p].keys() | after[p].keys()) if before[p].get(name) != after[p].get(name)]
            for p in before})
        fresh = {p: json.loads((workspace / f'bazel-bin/{p}.diagnostics/action.json').read_text())
                 for p in ('shared', 'app')}
        report['staging']['workspacePathsDiffer'] = (
            fresh['shared']['workspace'] != shared['workspace'] and fresh['app']['workspace'] != app['workspace'])
        (output / 'report.json').write_text(json.dumps(report, indent=2))
        if (report['cases']['freshExecution']['executedProjects'] != ['App', 'Shared']
                or not report['staging']['workspacePathsDiffer']
                or any(report['staging']['differences'].values())):
            raise RuntimeError('fresh execution staging differs; see report.json')
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
        policy = workspace / 'runner/Action.props'
        policy.write_text(policy.read_text().replace('<Deterministic>true',
            '<Deterministic Condition="\'$(Configuration)\' == \'Release\'">true'))
        build_case('policyEdit')
    if has_packages:
        upgrades = (('binaryDirectVersion', '1.0.1'), ('binaryTransitiveVersion', '1.0.2')) if binary_packages else (('packageDataVersion', '1.0.1'), ('packageTargetVersion', '1.0.2'))
        for name, version in upgrades:
            preparation = output / ('prepare-' + version)
            shutil.copytree(workspace / 'src', preparation)
            package_provider.feed(preparation / 'package-feed')
            package_provider.configure(preparation, version, preparation / 'package-feed')
            env['NUGET_PACKAGES'] = str(preparation / '.nuget/packages')
            run(name + '-restore', [DOTNET, 'msbuild', 'dirs.proj', '-t:Restore', '-p:Configuration=Release', '-nologo'], preparation)
            capture_restore(preparation)
            for relative in ('Shared/Shared.csproj', 'NuGet.Config'):
                shutil.copyfile(preparation / relative, workspace / 'src' / relative)
            shutil.rmtree(preparation)
            report['packagePreparationDeleted'].append(not preparation.exists())
            write_build()
            build_case(name)
        def package_failure(name):
            failure = run(name, startup + ['build', '//:app', *flags], require=False)
            if failure.returncode == 0 or 'SPIKE_COMPILE:' in failure.stdout or 'package' not in failure.stdout.lower():
                raise RuntimeError('package rejection was not observed: ' + name)
        build_file = workspace / 'BUILD.bazel'
        original_build = build_file.read_text()
        build_file.write_text('\n'.join('    packages = [],' if line.strip().startswith('packages =') else line
                                        for line in original_build.splitlines()))
        package_failure('missingPackage')
        build_file.write_text(original_build)
        payload = workspace / ('packages/spike.leaf/1.0.1/lib/net10.0/Spike.Leaf.dll' if binary_packages else 'packages/spike.buildinputs/1.0.2/data/value.txt')
        original_payload = payload.read_bytes()
        payload.write_bytes(original_payload + b'corrupt')
        package_failure('corruptPackage')
        payload.write_bytes(original_payload)
        project = workspace / 'src/Shared/Shared.csproj'
        original_project = project.read_text()
        project.write_text(original_project.replace('[1.0.2]', '[1.0.0]'))
        package_failure('stalePackageRestore')
        project.write_text(original_project)
        if binary_packages:
            manifest = workspace / 'package-manifests/Shared.json'
            original_manifest = manifest.read_text()
            value = json.loads(original_manifest)
            value['packages'] = [p for p in value['packages'] if p['id'] != 'Spike.Leaf']
            manifest.write_text(json.dumps(value))
            package_failure('missingTransitivePackage')
            manifest.write_text(original_manifest)
            isolated = output / 'missing-runtime'
            shutil.copytree(workspace / 'bazel-bin/app.bundle/artifacts/App/bin/Release/net10.0', isolated)
            (isolated / 'Spike.Leaf.dll').unlink()
            failure = run('missingRuntimeAsset', [DOTNET, isolated / 'App.dll'], cwd=isolated, require=False)
            if failure.returncode == 0 or 'Spike.Leaf' not in failure.stdout:
                raise RuntimeError('missing transitive runtime asset did not fail execution')
    if native_runtime:
        for execution in report['cases']['cold']['executions']:
            declared = {'/'.join(path.split('/')[2:]) for path in execution['inputs'] if path.startswith('external/')}
            missing = sorted({entry['path'] for entry in closure['files']} - declared)
            if missing:
                raise RuntimeError('native runtime inputs absent from execution log: ' + str(missing[:3]))
        build_file = workspace / 'BUILD.bazel'
        original = build_file.read_text()
        build_file.write_text(original.replace('"@native//:files"', '"empty-runtime"') + '\nfilegroup(name="empty-runtime")\n')
        failure = run('missingNativeRuntime', startup + ['build', '//:app', *flags], require=False)
        build_file.write_text(original)
        if failure.returncode == 0 or 'native runtime closure declaration mismatch' not in failure.stdout or 'SPIKE_COMPILE:' in failure.stdout:
            raise RuntimeError('native runtime rejection not observed')
        # Substitute a workspace copy of an external native library. Absolute
        # Nix loader paths still use the installed library: this tests declared
        # payload identity/integrity, not a loaded-library upgrade.
        entry = next(item for item in closure['files']
                     if '/lib/lib' in item['path'] and
                     (item['path'].endswith('.dylib') or '.so' in item['path']) and
                     not any(item['path'].startswith(Path(root).name + '/') for root in closure['roots']))
        payload = workspace / 'native-probe-library'
        shutil.copyfile(Path('/nix/store') / entry['path'], payload)
        module = workspace / 'MODULE.bazel'
        module.write_text(module.read_text().replace(
            'manifest="//:runtime-closure.json")',
            'manifest="//:runtime-closure.json", overrides={"//:native-probe-library": ' + json.dumps(entry['path']) + '})'))
        build_case('nativeLibraryCopy')
        # Same length, different bytes: exercise the digest, not just size checks.
        with payload.open('r+b') as stream:
            first = stream.read(1)
            stream.seek(0)
            stream.write(bytes([first[0] ^ 1]))
        failure = run('corruptNativeRuntime', startup + ['build', '//:app', *flags], require=False)
        if failure.returncode == 0 or 'native runtime closure payload mismatch' not in failure.stdout or 'SPIKE_COMPILE:' in failure.stdout:
            raise RuntimeError('native runtime payload rejection not observed')
        original_hash = entry['sha256']
        entry['sha256'] = hashlib.sha256(payload.read_bytes()).hexdigest()
        (workspace / 'runtime-closure.json').write_text(json.dumps(closure, indent=2) + '\n')
        build_case('nativeLibraryIdentityChange')
        build_case('nativeLibraryUnchanged')
        report['nativeLibraryControl'] = dict(path=entry['path'], originalSha256=original_hash,
            changedSha256=entry['sha256'], size=entry['size'],
            installedPayloadUnchanged=hashlib.sha256((Path('/nix/store') / entry['path']).read_bytes()).hexdigest() == original_hash,
            boundary='Declared copy only; absolute Nix loader paths still use the installed library')
        if (report['cases']['nativeLibraryIdentityChange']['executedProjects'] != ['App', 'Shared'] or
                report['cases']['nativeLibraryUnchanged']['executedProjects'] or
                not report['nativeLibraryControl']['installedPayloadUnchanged']):
            raise RuntimeError('native library identity control failed')
        build_file.write_text(original.replace('msbuild_project(\n', 'msbuild_project(\n    trace_runtime = True,\n'))
        build_case('nativeLoaderTrace')
        traces = {}
        declared_paths = {'/nix/store/' + item['path'] for item in closure['files']}
        for project in ('shared', 'app'):
            trace = '\n'.join(path.read_text() for path in sorted(
                (workspace / f'bazel-bin/{project}.diagnostics').glob('loader.log*')))
            trace_log = output / f'native-loader-{project}.log'
            trace_log.write_text(trace)
            # dyld reports loaded images; glibc reports initialization calls.
            # Do not classify LD_DEBUG search candidates as loaded libraries.
            loaded = sorted(set(re.findall(r'^dyld\[\d+\]:.*? (/[^\n]+)$', trace, re.MULTILINE)
                                if platform.system() == 'Darwin' else
                                re.findall(r'calling init:\s*(/[^\n]+)', trace)))
            if not loaded:
                raise RuntimeError('native loader trace contained no loaded library records: ' + project)
            traces[project] = dict(loaded=loaded,
                outsideDeclaredClosure=[path for path in loaded if path not in declared_paths],
                log=str(trace_log))
        report['nativeLoaderTraceEvidence'] = dict(projects=traces,
            boundary='Loader diagnostics from MSBuild and inherited child processes, not a complete filesystem read trace')
        build_file.write_text(original)
        jit = loader_inputs.prepare(workspace, DOTNET.parent.resolve(), closure)
        report['loaderRuntime'] = dict(payloads=jit, cases={})
        def select_jit(version):
            loader_inputs.select(workspace, version, jit['library'])
            build_file.write_text(original.replace('msbuild_project(\n',
                'msbuild_project(\n    trace_runtime = True,\n'
                f'    loader_jit = "loader/jit-{version}",\n    loader_manifest = "loader/manifest.json",\n'))
        def jit_case(name, expected_hash):
            build_case(name)
            report['loaderRuntime']['cases'][name] = loader_inputs.evidence(workspace, output, name, expected_hash)
        select_jit('v1')
        jit_case('jitCopied', jit['first']['sha256'])
        select_jit('v2')
        jit_case('jitChanged', jit['second']['sha256'])
        build_case('jitUnchanged')
        run('jitClean', startup + ['clean'])
        build_case('jitDiskCache')
        startup = [f'--output_base={output / "jit-fresh-base"}' if str(arg).startswith('--output_base=') else arg for arg in startup]
        flags = [f'--disk_cache={output / "jit-fresh-cache"}' if str(arg).startswith('--disk_cache=') else arg for arg in flags]
        jit_case('jitFresh', jit['second']['sha256'])
        jit_build = build_file.read_text()
        def jit_failure(name, expected):
            failure = run(name, startup + ['build', '//:app', *flags], require=False)
            if failure.returncode == 0 or 'SPIKE_COMPILE:' in failure.stdout or expected not in failure.stdout:
                raise RuntimeError('JIT rejection not observed: ' + name)
        build_file.write_text('\n'.join(line for line in jit_build.splitlines() if 'loader_jit =' not in line))
        jit_failure('jitMissing', 'loader JIT requires payload')
        build_file.write_text(jit_build)
        payload = workspace / 'loader/jit-v2'
        valid_bytes = payload.read_bytes()
        payload.write_bytes(b'invalid native JIT image\n')
        jit_failure('jitCorrupt', 'loader JIT payload mismatch')
        loader_inputs.select(workspace, 'v2', jit['library'])
        jit_failure('jitLoaderReject', 'JIT')
        payload.write_bytes(valid_bytes)
        select_jit('v2')
        report['loaderRuntime']['originalUnchanged'] = (
            hashlib.sha256(Path(jit['original']).read_bytes()).hexdigest() == jit['first']['sha256'])
        if not report['loaderRuntime']['originalUnchanged']:
            raise RuntimeError('installed JIT changed')
        build_file.write_text(original)
    negative_log = output / 'undeclared.execution.json'
    negative = run('undeclaredInput', startup + ['build', '//:undeclared', *flags,
                   f'--execution_log_json_file={negative_log}'], require=False)
    report['undeclaredInput']['executionLog'] = str(negative_log)
    if 'FileNotFoundException' not in negative.stdout or 'undeclared.txt' not in negative.stdout:
        raise RuntimeError('undeclared-input probe failed for an unexpected reason')
    if negative.returncode == 0:
        raise RuntimeError('sandbox exposed undeclared relative input')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(output / 'report.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--identity-probe', action='store_true')
    mode.add_argument('--package-probe', action='store_true')
    mode.add_argument('--binary-package-probe', action='store_true')
    mode.add_argument('--staging-probe', action='store_true')
    mode.add_argument('--native-runtime-probe', action='store_true')
    args = parser.parse_args()
    try:
        probe(args.output.resolve(), args.identity_probe, args.package_probe, args.staging_probe, args.native_runtime_probe, args.binary_package_probe)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
