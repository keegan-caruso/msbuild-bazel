#!/usr/bin/env python3
"""R01 package-free generated graph cache evidence; R02 packages remain separate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from probe_graph_execution import BAZEL, DOTNET_ROOT, ROOT, write_fixture
from prepare_graph import prepare
from probe_bazel import json_stream


def cache_environment(output, workspace):
    """Keep NuGet configuration stable and never inherit an old MSBuild worker."""
    return dict(os.environ, NUGET_PACKAGES=str(workspace / '.nuget/packages'),
                DOTNET_CLI_HOME=str(output / 'home'), DOTNET_NOLOGO='1',
                DOTNET_CLI_TELEMETRY_OPTOUT='1', MSBUILDDISABLENODEREUSE='1')


def run_logged(output, name, args, cwd):
    result = subprocess.run(list(map(str, args)), cwd=cwd, env=cache_environment(output, cwd),
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    (output / (name + '.log')).write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(name + ' failed: ' + result.stdout + result.stderr)
    return result.stdout.strip()


def restore_source(output, source, name):
    return run_logged(output, name, [DOTNET_ROOT / 'dotnet', 'msbuild', 'build.proj',
        '-t:Restore', '-p:Configuration=Release', '-nodeReuse:false', '-nologo'], source)


def probe(output, packages=True):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    dotnet = DOTNET_ROOT / 'dotnet'
    serial = 0
    def run(name, args, cwd):
        return run_logged(output, name, args, cwd)

    def fixture(path):
        write_fixture(path)
        (path / 'src/App/Program.cs').write_text('''var suffix = "";
#if CACHE_CONFIG_V2
suffix = "|config-v2";
#endif
Console.WriteLine(Left.Value.Text + "|" + Right.Value.Text + suffix);
''')
        (path / '.nuget/packages').mkdir(parents=True, exist_ok=True)

    def export(source, name):
        nonlocal serial
        restore_source(output, source, name + '-restore')
        manifest = output / (name + '-manifest.json')
        request = output / (name + '-request.json')
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(source), dotnetRoot=str(DOTNET_ROOT),
            sdkVersion='10.0.100', packageRoot=str(source / '.nuget/packages'),
            entryPoints=[dict(project='build.proj', globalProperties={'Configuration':'Release'})], output=str(manifest))))
        run(name + '-export', [dotnet, ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], source)
        return manifest

    def generate(source, generated, name):
        nonlocal serial
        manifest = export(source, name)
        if generated.exists(): shutil.rmtree(generated)
        graph = prepare(source, manifest, generated, environment=cache_environment(output, source))
        serial += 1
        return graph, manifest

    strategy = 'darwin-sandbox' if platform.system() == 'Darwin' else 'linux-sandbox'
    def remove_output_base():
        # Bazel protects output directories; never follow toolchain symlinks.
        for directory, _, _ in os.walk(base, followlinks=False):
            path = Path(directory)
            if not path.is_symlink(): path.chmod(path.stat().st_mode | 0o700)
        shutil.rmtree(base)

    cache = output / 'disk-cache'
    base = output / 'bazel-base'
    bazel_invocations = []
    def bazel(generated, name, command):
        bazel_invocations.append(name)
        return run(name, [BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc',
            f'--output_base={base}', f'--output_user_root={output / "bazel-user"}', *command], generated)

    def build(generated, graph, name, **extra):
        execution = output / (name + '-execution.json')
        bazel(generated, name, ['build', '//:all', f'--disk_cache={cache}',
            f'--spawn_strategy={strategy}', f'--strategy=MsbuildProject={strategy}', '--jobs=2',
            '--noshow_progress', '--color=no', '--curses=no', '--remote_download_outputs=all', f'--execution_log_json_file={execution}'])
        nodes = {n['id']: n['project'].removeprefix('workspace/') for n in graph['nodes']}
        retained = output / 'evidence' / name
        retained.mkdir(parents=True)
        shutil.copytree(generated / 'restore', retained / 'restore')
        for directory in ('package-manifests', 'packages'):
            if (generated / directory).is_dir():
                shutil.copytree(generated / directory, retained / directory)
        executions = []
        for record in json_stream(execution):
            if record.get('mnemonic') != 'MsbuildProject': continue
            identity = record['targetLabel'].split(':node_')[-1]
            action = dict(nodeId=identity, project=nodes[identity], cacheHit=record.get('cacheHit', False),
                runner=record.get('runner'), remotable=record.get('remotable'), remoteCacheable=record.get('remoteCacheable'))
            if not action['cacheHit']:
                log = retained / (identity + '.log')
                shutil.copyfile(generated / f'bazel-bin/node_{identity}.diagnostics/build.log', log)
                action['log'] = log.relative_to(output).as_posix()
            executions.append(action)
        bundle_files = {}
        for identity in nodes:
            bundle = generated / f'bazel-bin/node_{identity}.bundle'
            if not bundle.is_dir():
                raise RuntimeError('configured bundle was not materialized: ' + identity)
            for source in sorted(bundle.rglob('*')):
                if not source.is_file(): continue
                logical = f'node_{identity}/' + source.relative_to(bundle).as_posix()
                target = retained / 'bundles' / logical
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                bundle_files[logical] = dict(file=target.relative_to(output).as_posix(),
                    sha256=hashlib.sha256(target.read_bytes()).hexdigest(), executable=bool(target.stat().st_mode & 0o111))
        canonical = {p: {k: m[k] for k in ('sha256', 'executable')} for p, m in bundle_files.items()}
        app = next(i for i, p in nodes.items() if p == 'src/App/App.csproj')
        actual = run(name + '-app', [dotnet, generated / f'bazel-bin/node_{app}.bundle/artifacts/src/App/bin/Release/net10.0/App.dll'], generated)
        return dict(returncode=0, applicationReturncode=0, applicationOutput=actual,
            executedProjects=sorted(a['project'] for a in executions if not a['cacheHit']),
            cacheHitProjects=sorted(a['project'] for a in executions if a['cacheHit']), executions=executions,
            executionLog=execution.relative_to(output).as_posix(), bundleFiles=bundle_files,
            bundleDigest=hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode()).hexdigest(), **extra)

    run('exporter-build', [dotnet, 'build', ROOT / 'tools/GraphExport', '-c', 'Release', '--nologo'], ROOT)
    ordinary = output / 'ordinary'
    fixture(ordinary)
    export(ordinary, 'ordinary')
    run('ordinary-build', [dotnet, 'msbuild', 'build.proj', '-t:Build', '-p:Configuration=Release', '-graphBuild', '-isolateProjects', '-nologo'], ordinary)
    baseline = run('ordinary-app', [dotnet, ordinary / 'src/App/bin/Release/net10.0/App.dll'], ordinary)
    shutil.rmtree(ordinary)
    source, generated = output / 'preparation', output / 'workspace'
    fixture(source)
    graph, before_manifest = generate(source, generated, 'cold')
    cases = {'cold': build(generated, graph, 'cold')}
    cases['unchanged'] = build(generated, graph, 'unchanged')
    mutations = {
        'appEdit': ('src/App/Program.cs', ' + suffix)', ' + suffix + "|app-v2")'),
        'leftEdit': ('src/Left/Value.cs', ':left"', ':left-v2"'),
        'sharedEdit': ('src/Shared/Message.cs', 'shared-v1', 'shared-v2'),
        'importEdit': ('Directory.Build.props', '</PropertyGroup>', '<DefineConstants>$(DefineConstants);CACHE_CONFIG_V2</DefineConstants></PropertyGroup>'),
        'graphEdgeAdded': ('src/Right/Right.csproj', '</ItemGroup>', '<ProjectReference Include="../Left/Left.csproj"/></ItemGroup>'),
    }
    edge = None
    for name, (path, old, new) in mutations.items():
        # Reset and warm the exact baseline before each independent perturbation.
        shutil.rmtree(source)
        fixture(source)
        graph, before = generate(source, generated, name + '-baseline')
        build(generated, graph, name + '-baseline')
        target = source / path
        target.write_text(target.read_text().replace(old, new))
        if name == 'graphEdgeAdded':
            target = source / 'src/Right/Value.cs'
            target.write_text(target.read_text().replace(' + ":right"', ' + ":right+" + Left.Value.Text'))
        graph, after = generate(source, generated, name)
        if name == 'graphEdgeAdded':
            generation = serial
            analysis = bazel(generated, 'edge-analysis', ['query', 'kind(graph_project, //:*)', '--output=xml', '--noshow_progress'])
            import xml.etree.ElementTree as ET
            analyzed = {}
            for rule in ET.fromstring(analysis).findall('rule'):
                dependencies = rule.find("list[@name='dependencies']")
                analyzed[rule.attrib['name'].split(':node_')[-1]] = sorted(v.attrib['value'].split(':node_')[-1] for v in ([] if dependencies is None else dependencies))
            serial += 1
            edge = dict(beforeManifest=before.name, afterManifest=after.name, analysisLog='edge-analysis.log',
                analyzedDependencies=analyzed, planGenerationSequence=generation, analysisSequence=serial)
        cases[name] = build(generated, graph, name)
        if name == 'sharedEdit':
            control = output / 'ordinary-shared-edit'
            fixture(control)
            target = control / path
            target.write_text(target.read_text().replace(old, new))
            export(control, 'ordinary-shared-edit')
            run('ordinary-shared-edit-build', [dotnet, 'msbuild', 'build.proj', '-t:Build',
                '-p:Configuration=Release', '-graphBuild', '-isolateProjects', '-nologo'], control)
            cases[name]['ordinaryOutput'] = run('ordinary-shared-edit-app',
                [dotnet, control / 'src/App/bin/Release/net10.0/App.dll'], control)
            shutil.rmtree(control)
    shutil.rmtree(source)
    fixture(source)
    graph, _ = generate(source, generated, 'recovery-baseline')
    build(generated, graph, 'recovery-baseline')
    remove_output_base()
    # Regenerate from restored source, dropping every prior output symlink/product.
    graph, _ = generate(source, generated, 'recovery')
    absent = not list(generated.glob('bazel-*')) and not list(source.glob('src/*/bin'))
    cases['diskCache'] = build(generated, graph, 'diskCache', outputsAbsentBeforeBuild=absent, outputBaseAbsentBeforeBuild=not base.exists())
    remove_output_base()
    shutil.rmtree(generated)
    shutil.rmtree(source)
    relocated_source, relocated = output / 'relocated-preparation', output / 'relocated-workspace'
    fixture(relocated_source)
    graph, _ = generate(relocated_source, relocated, 'relocated')
    shutil.rmtree(relocated_source)
    cases['relocated'] = build(relocated, graph, 'relocated', outputsAbsentBeforeBuild=not list(relocated.glob('bazel-*')),
        outputBaseAbsentBeforeBuild=not base.exists(), producerWorkspaceAbsent=not source.exists() and not generated.exists(),
        producerWorkspace=str(generated), consumerWorkspace=str(relocated))
    report = dict(schemaVersion=1, scope='R01-package-free-cache', baselineOutput=baseline, cases=cases, graphEdgeAdded=edge,
        pendingTracks=['R01-handoff-controls', 'R02-managed-packages'])
    if packages:
        from binary_inputs import Packages
        from graph_private_assets import configure
        import re

        package_builder = Packages(output / 'package-builder', dotnet, run)
        archive_directory = output / 'pinned-package-archives'
        pins = package_builder.feed(archive_directory)
        (output / 'package-pins.json').write_text(json.dumps(pins, indent=2, sort_keys=True))
        cache = output / 'package-disk-cache'
        base = output / 'package-bazel-base'
        package_source = output / 'package-preparation'
        package_generated = output / 'package-workspace'

        def package_fixture(source, version='1.0.0'):
            fixture(source)
            package_builder.feed(source / '.feed')
            configure(source, source / '.feed', version)

        def package_details(generated, graph, name):
            left = next(n for n in graph['nodes'] if n['project'] == 'workspace/src/Left/Left.csproj')
            manifest_file = generated / 'package-manifests' / (left['id'] + '.json')
            manifest = json.loads(manifest_file.read_text())
            binary = next(p for p in manifest['packages'] if p['id'] == 'Spike.Binary')
            if binary['archiveSha256'] != pins['Spike.Binary/' + binary['version']]:
                raise RuntimeError('staged Binary archive differs from pinned fixture archive')
            payload = generated / 'packages' / binary['path'] / 'lib/net10.0/Spike.Binary.dll'
            retained = output / (name + '-payload.dll')
            shutil.copy2(payload, retained)
            return dict(version=binary['version'], payloadSha256=hashlib.sha256(payload.read_bytes()).hexdigest(),
                archiveSha256=binary['archiveSha256'], payloadFile=retained.name)

        package_oracles = {}
        for version in ('1.0.0', '1.0.1'):
            control = output / ('ordinary-package-' + version)
            package_fixture(control, version)
            restore_source(output, control, 'ordinary-package-' + version + '-restore')
            run('ordinary-package-' + version + '-build', [dotnet, 'msbuild', 'build.proj',
                '-t:Build', '-p:Configuration=Release', '-graphBuild', '-isolateProjects', '-nodeReuse:false', '-nologo'], control)
            package_oracles[version] = run('ordinary-package-' + version + '-app',
                [dotnet, control / 'src/App/bin/Release/net10.0/App.dll'], control)
            shutil.rmtree(control)

        package_fixture(package_source)
        graph, before = generate(package_source, package_generated, 'packageCold')
        before_package = package_details(package_generated, graph, 'packageCold')
        shutil.rmtree(package_source)
        cases['packageCold'] = build(package_generated, graph, 'packageCold',
            preparationWorkspaceAbsent=not package_source.exists(), ordinaryOutput=package_oracles['1.0.0'])
        package_fixture(package_source, '1.0.1')
        graph, after = generate(package_source, package_generated, 'packageUpgrade')
        after_package = package_details(package_generated, graph, 'packageUpgrade')
        shutil.rmtree(package_source)
        absent = not package_source.exists()
        cases['packageUpgrade'] = build(package_generated, graph, 'packageUpgrade', preparationWorkspaceAbsent=absent, ordinaryOutput=package_oracles['1.0.1'])
        report['packageUpgrade'] = dict(beforeVersion=before_package['version'], afterVersion=after_package['version'],
            beforePayloadSha256=before_package['payloadSha256'], afterPayloadSha256=after_package['payloadSha256'],
            beforePayloadFile=before_package['payloadFile'], afterPayloadFile=after_package['payloadFile'],
            beforeArchiveSha256=before_package['archiveSha256'], afterArchiveSha256=after_package['archiveSha256'],
            beforeManifest=before.name, afterManifest=after.name, pins='package-pins.json', preparationWorkspaceAbsent=absent)

        # Every negative starts from a valid independently warmed package baseline.
        failures = {}
        for name in ('missingSource', 'missingPackage', 'corruptPackage', 'staleManifest', 'staleRestore'):
            package_fixture(package_source)
            graph, manifest = generate(package_source, package_generated, name + '-baseline')
            build(package_generated, graph, name + '-baseline')
            digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
            if name == 'missingSource':
                (package_source / 'src/Left/Value.cs').unlink()
            elif name in ('missingPackage', 'corruptPackage'):
                payload = package_source / '.nuget/packages/spike.binary/1.0.0/ref/net10.0/Spike.Binary.dll'
                if name == 'missingPackage': payload.unlink()
                else:
                    payload.chmod(payload.stat().st_mode | 0o200)
                    payload.write_bytes(payload.read_bytes() + b'corrupt')
            elif name == 'staleManifest':
                target = package_source / 'src/Right/Right.csproj'
                target.write_text(target.read_text().replace('</ItemGroup>', '<ProjectReference Include="../Left/Left.csproj"/></ItemGroup>'))
            else:
                target = package_source / 'src/Left/Left.csproj'
                target.write_text(target.read_text().replace('[1.0.0]', '[1.0.1]'))
            failed_output = output / (name + '-replacement')
            result = subprocess.run([sys.executable, str(ROOT / 'tools/prepare_graph.py'),
                '--workspace', str(package_source), '--manifest', str(manifest), '--output', str(failed_output)],
                cwd=ROOT, env=cache_environment(output, package_source), text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
            log = result.stdout + result.stderr
            log_path = output / (name + '.log')
            log_path.write_text(log)
            if result.returncode == 0:
                raise RuntimeError(name + ' unexpectedly published a valid preparation')
            codes = re.findall(r'(?<![\w-])(missing-input|hash-mismatch|stale-manifest|stale-restore)(?![\w-])', log)
            failures[name] = dict(returncode=result.returncode, diagnostic=codes[-1] if codes else None,
                executedProjects=[], publishedPlan=failed_output.exists(), log=log_path.name,
                manifest=manifest.name, manifestSha256=digest,
                preservedManifest=hashlib.sha256(manifest.read_bytes()).hexdigest() == digest)
            shutil.rmtree(package_source)
        # Re-export is intentionally attempted without restore: recording current
        # source hashes must not bless stale PackageReference semantics.
        import xml.etree.ElementTree as ET
        namespace = 'http://schemas.microsoft.com/developer/msbuild/2003'
        for name in ('stalePrivateAssets', 'namespacedStaleRestore', 'namespacedUnpinnedVersion'):
            package_fixture(package_source)
            graph, baseline_manifest = generate(package_source, package_generated, name + '-baseline')
            build(package_generated, graph, name + '-baseline')
            guard_evidence = output / 'guards' / name
            guard_evidence.mkdir(parents=True)

            def snapshot_plan(retain=False):
                snapshot = {}
                for directory, children, files in os.walk(package_generated, followlinks=False):
                    children[:] = [child for child in children if not (Path(directory) / child).is_symlink()]
                    for filename in files:
                        path = Path(directory) / filename
                        if path.is_symlink(): continue
                        logical = path.relative_to(package_generated).as_posix()
                        snapshot[logical] = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            executable=bool(path.stat().st_mode & 0o111))
                        if retain:
                            retained = guard_evidence / 'published-plan' / logical
                            retained.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(path, retained)
                return snapshot

            before_snapshot = snapshot_plan(retain=True)
            before_snapshot_file = guard_evidence / 'before-plan.json'
            before_snapshot_file.write_text(json.dumps(before_snapshot, indent=2, sort_keys=True))
            invocations_before = list(bazel_invocations)
            original_digest = hashlib.sha256(baseline_manifest.read_bytes()).hexdigest()
            target = package_source / 'src/Left/Left.csproj'
            tree = ET.parse(target)
            reference = tree.getroot().find('.//PackageReference')
            if name == 'stalePrivateAssets':
                reference.set('PrivateAssets', 'all')
            else:
                reference.set('Version', '[1.0.1]' if name == 'namespacedStaleRestore' else '1.0.0')
                for element in tree.iter(): element.tag = '{' + namespace + '}' + element.tag
                ET.register_namespace('', namespace)
            tree.write(target)
            shutil.copy2(target, guard_evidence / 'mutated-Left.csproj')
            refreshed = output / (name + '-fresh-manifest.json')
            request = output / (name + '-reexport-request.json')
            request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(package_source),
                dotnetRoot=str(DOTNET_ROOT), sdkVersion='10.0.100',
                packageRoot=str(package_source / '.nuget/packages'),
                entryPoints=[dict(project='build.proj', globalProperties={'Configuration':'Release'})],
                output=str(refreshed))))
            environment = cache_environment(output, package_source)
            result = subprocess.run([str(dotnet), str(ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll'),
                '--request', str(request)], cwd=package_source, env=environment,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
            export_returncode = result.returncode
            export_log = result.stdout + result.stderr
            (guard_evidence / 'reexport.log').write_text(export_log)
            failed_output = output / (name + '-replacement')
            # Also check the preparation boundary directly against the original
            # graph; neither entry point may publish or silently reuse a plan.
            result = subprocess.run([sys.executable, str(ROOT / 'tools/prepare_graph.py'),
                '--workspace', str(package_source), '--manifest', str(baseline_manifest), '--output', str(failed_output)],
                cwd=ROOT, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
            log = result.stdout + result.stderr
            (guard_evidence / 'failure.log').write_text(log)
            if result.returncode == 0 or export_returncode == 0:
                raise RuntimeError(name + ' blessed stale package semantics during re-export/preparation')
            after_snapshot = snapshot_plan()
            after_snapshot_file = guard_evidence / 'after-plan.json'
            after_snapshot_file.write_text(json.dumps(after_snapshot, indent=2, sort_keys=True))
            codes = re.findall(r'(?<![\w-])(stale-restore|unsupported-package)(?![\w-])', log)
            export_codes = re.findall(r'(?<![\w-])(stale-restore|unsupported-package)(?![\w-])', export_log)
            failures[name] = dict(returncode=result.returncode, exportReturncode=export_returncode,
                diagnostic=codes[-1] if codes else None, exportDiagnostic=export_codes[-1] if export_codes else None,
                exportLog=(guard_evidence / 'reexport.log').relative_to(output).as_posix(),
                executedProjects=[], publishedPlan=failed_output.exists(), freshManifestPublished=refreshed.exists(),
                log=(guard_evidence / 'failure.log').relative_to(output).as_posix(),
                manifest=baseline_manifest.name, manifestSha256=original_digest,
                preservedManifest=hashlib.sha256(baseline_manifest.read_bytes()).hexdigest() == original_digest,
                existingPlanIntact=before_snapshot == after_snapshot and (package_generated / 'BUILD.bazel').is_file(),
                beforePlan=before_snapshot_file.relative_to(output).as_posix(),
                afterPlan=after_snapshot_file.relative_to(output).as_posix(),
                retainedPlan=(guard_evidence / 'published-plan').relative_to(output).as_posix(),
                mutatedProject=(guard_evidence / 'mutated-Left.csproj').relative_to(output).as_posix(),
                bazelInvocationsBefore=invocations_before, bazelInvocationsAfter=list(bazel_invocations))
            shutil.rmtree(package_source)
        report['failures'] = failures

        package_fixture(package_source)
        graph, _ = generate(package_source, package_generated, 'packageRecovery-baseline')
        build(package_generated, graph, 'packageRecovery-baseline')
        remove_output_base()
        graph, _ = generate(package_source, package_generated, 'packageRecovery')
        shutil.rmtree(package_source)
        cases['packageDiskCache'] = build(package_generated, graph, 'packageDiskCache',
            outputsAbsentBeforeBuild=not list(package_generated.glob('bazel-*')),
            outputBaseAbsentBeforeBuild=not base.exists(), preparationWorkspaceAbsent=not package_source.exists())
        remove_output_base()
        shutil.rmtree(package_generated)
        relocated_source, relocated = output / 'package-relocated-preparation', output / 'package-relocated-workspace'
        package_fixture(relocated_source)
        graph, _ = generate(relocated_source, relocated, 'packageRelocated')
        shutil.rmtree(relocated_source)
        cases['packageRelocated'] = build(relocated, graph, 'packageRelocated',
            outputsAbsentBeforeBuild=not list(relocated.glob('bazel-*')),
            outputBaseAbsentBeforeBuild=not base.exists(), preparationWorkspaceAbsent=not relocated_source.exists(),
            producerWorkspaceAbsent=not package_source.exists() and not package_generated.exists(),
            producerWorkspace=str(package_generated), consumerWorkspace=str(relocated))
        report.update(scope='R02-managed-package-cache', pendingTracks=[])
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--package-free', action='store_true', help='Run only the R01 package-free scope')
    args = parser.parse_args()
    result = probe(args.output, packages=not args.package_free)
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}, indent=2))
