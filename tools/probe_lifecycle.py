#!/usr/bin/env python3
"""Characterize existing output ownership; do not expose graph Clean/Rebuild APIs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

from prepare_graph import ROOT, DOTNET_ROOT, prepare
from probe_graph_cache import cache_environment, restore_source, run_logged
from probe_graph_execution import BAZEL, write_fixture
from probe_bazel import json_stream


def fingerprint(directory):
    return {p.relative_to(directory).as_posix(): dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
        executable=bool(p.stat().st_mode & 0o111)) for p in sorted(directory.rglob('*')) if p.is_file()}


def remove_tree(path):
    for directory, _, _ in os.walk(path, followlinks=False):
        folder = Path(directory)
        if not folder.is_symlink(): folder.chmod(folder.stat().st_mode | 0o700)
    shutil.rmtree(path)


def probe(output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    dotnet = DOTNET_ROOT / 'dotnet'
    names = ('Shared', 'Left', 'Right', 'App')
    projects = {n: f'src/{n}/{n}.csproj' for n in names}
    def run(name, args, cwd):
        return run_logged(output, name, args, cwd)
    def fixture(path):
        write_fixture(path)
        (path / '.nuget/packages').mkdir(parents=True)
        target = path / 'Directory.Build.targets'
        target.write_text(target.read_text().replace('</Project>',
            '<Target Name="LifecycleCompileEvidence" BeforeTargets="CoreCompile" Condition="\'$(RULES_MSBUILD_GRAPH_PROJECT)\' == \'\'"><Message Importance="high" Text="LIFECYCLE_COMPILE:$(MSBuildProjectName)" /></Target></Project>'))

    ordinary = output / 'ordinary'
    fixture(ordinary)
    restore_source(output, ordinary, 'ordinary-restore')
    def msbuild(name, target, configuration='Release', *, isolated=True, expected_failure=None):
        command = [dotnet, 'msbuild', 'build.proj', '-t:' + target,
            '-p:Configuration=' + configuration, '-nodeReuse:false', '-nologo']
        if isolated: command += ['-graphBuild', '-isolateProjects']
        result = subprocess.run(list(map(str, command)), cwd=ordinary, env=cache_environment(output, ordinary),
            text=True, capture_output=True, timeout=300)
        log = result.stdout + result.stderr
        (output / (name + '.log')).write_text(log)
        if expected_failure:
            if result.returncode == 0 or expected_failure not in log:
                raise RuntimeError(name + ' did not reproduce expected ' + expected_failure + ': ' + log)
        elif result.returncode:
            raise RuntimeError(name + ' failed: ' + log)
        return dict(returncode=result.returncode, compiledProjects=sorted(line.split('LIFECYCLE_COMPILE:', 1)[1].strip()
            for line in log.splitlines() if 'LIFECYCLE_COMPILE:' in line), log=name + '.log',
            command=list(map(str, command)), diagnostic=expected_failure if expected_failure and expected_failure in log else None)
    msbuild('ordinary-debug-build', 'Build', 'Debug')
    cold = msbuild('ordinary-release-build', 'Build')
    release_binary = ordinary / 'src/App/bin/Release/net10.0/App.dll'
    expected = run('ordinary-app', [dotnet, release_binary], ordinary)
    debug_before = {name: fingerprint(ordinary / f'src/{name}/bin/Debug') for name in names}
    unmanaged = ordinary / 'src/App/bin/Release/net10.0/user-owned.txt'
    unmanaged.write_text('ordinary unmanaged file\n')
    clean = msbuild('ordinary-clean-release', 'Clean')
    clean.update(releaseAssembliesAbsent=all(not (ordinary / f'src/{name}/bin/Release/net10.0/{name}.dll').exists() for name in names),
        debugOutputsPreserved=debug_before == {name: fingerprint(ordinary / f'src/{name}/bin/Debug') for name in names},
        restoreAssetsPreserved=all((ordinary / f'src/{name}/obj/project.assets.json').is_file() for name in names),
        userFilePreserved=unmanaged.read_text() == 'ordinary unmanaged file\n')
    after_clean = msbuild('ordinary-build-after-clean', 'Build')
    after_clean['applicationOutput'] = run('ordinary-after-clean-app', [dotnet, release_binary], ordinary)
    isolated_rebuild = msbuild('isolated-rebuild-release', 'Rebuild', expected_failure='MSB4252')
    isolated_rebuild['appAssemblyAbsentAfterFailure'] = not release_binary.exists()
    rebuild = msbuild('ordinary-rebuild-release', 'Rebuild', isolated=False)
    rebuild.update(applicationOutput=run('ordinary-after-rebuild-app', [dotnet, release_binary], ordinary),
        debugOutputsPreserved=debug_before == {name: fingerprint(ordinary / f'src/{name}/bin/Debug') for name in names},
        userFilePreserved=unmanaged.read_text() == 'ordinary unmanaged file\n')

    source = output / 'preparation'
    fixture(source)
    restore_source(output, source, 'graph-restore')
    run('exporter-build', [dotnet, 'build', ROOT / 'tools/GraphExport', '-c', 'Release', '--nologo'], ROOT)
    manifest = output / 'graph-manifest.json'
    request = output / 'graph-request.json'
    request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(source), dotnetRoot=str(DOTNET_ROOT),
        sdkVersion='10.0.100', packageRoot=str(source / '.nuget/packages'),
        entryPoints=[dict(project='build.proj', globalProperties={'Configuration':'Release'})], output=str(manifest))))
    run('export', [dotnet, ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], source)
    generated = output / 'workspace'
    graph = prepare(source, manifest, generated, environment=cache_environment(output, source))
    shutil.rmtree(source)
    nodes = {n['id']: n['project'].removeprefix('workspace/') for n in graph['nodes']}
    ids = {Path(project).stem: identity for identity, project in nodes.items()}
    sentinel = generated / 'user-owned.txt'
    sentinel.write_text('outside declared output trees\n')
    plan_before = {p: fingerprint(generated / p) for p in ('src', 'restore', 'runner')}
    build_before = (generated / 'BUILD.bazel').read_bytes()
    strategy = 'darwin-sandbox' if platform.system() == 'Darwin' else 'linux-sandbox'
    base, cache = output / 'bazel-base', output / 'disk-cache'
    def bazel(name, command, selected_base=None, selected_cache=None):
        return run(name, [BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc',
            '--output_base=' + str(selected_base or base), '--output_user_root=' + str(output / 'bazel-user'), *command], generated)
    def build(name, selected_base=None, selected_cache=None):
        log = output / (name + '-execution.json')
        bazel(name, ['build', '//:all', '--disk_cache=' + str(selected_cache or cache),
            '--jobs=2', '--spawn_strategy=' + strategy, '--strategy=MsbuildProject=' + strategy,
            '--remote_download_outputs=all', '--execution_log_json_file=' + str(log), '--noshow_progress'], selected_base)
        binary_root = (generated / 'bazel-bin').resolve()
        evidence = output / 'evidence' / name
        evidence.mkdir(parents=True)
        files, actions = {}, []
        for identity, project in nodes.items():
            bundle = binary_root / ('node_' + identity + '.bundle')
            if not bundle.is_dir(): raise RuntimeError('bundle not materialized: ' + project)
            for logical, metadata in fingerprint(bundle).items():
                name_in_bundle = 'node_' + identity + '/' + logical
                retained = evidence / 'bundles' / name_in_bundle
                retained.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(bundle / logical, retained)
                files[name_in_bundle] = dict(metadata, file=retained.relative_to(output).as_posix())
        for record in json_stream(log):
            if record.get('mnemonic') != 'MsbuildProject': continue
            identity = record['targetLabel'].split(':node_')[-1]
            action = dict(project=nodes[identity], cacheHit=record.get('cacheHit', False), runner=record.get('runner'),
                remotable=record.get('remotable'), remoteCacheable=record.get('remoteCacheable'))
            if not action['cacheHit']:
                diagnostic = binary_root / ('node_' + identity + '.diagnostics')
                action['command'] = json.loads((diagnostic / 'action.json').read_text())['command']
                retained = evidence / (identity + '.log')
                shutil.copyfile(diagnostic / 'build.log', retained)
                action['log'] = retained.relative_to(output).as_posix()
            actions.append(action)
        canonical = {p: {k: m[k] for k in ('sha256', 'executable')} for p, m in files.items()}
        actual = run(name + '-app', [dotnet, binary_root / ('node_' + ids['App'] + '.bundle/artifacts/src/App/bin/Release/net10.0/App.dll')], generated)
        return dict(returncode=0, applicationOutput=actual, actions=actions,
            executedProjects=sorted(a['project'] for a in actions if not a['cacheHit']),
            cacheHitProjects=sorted(a['project'] for a in actions if a['cacheHit']), executionLog=log.name,
            bundleFiles=files, bundleDigest=hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            binaryRoot=str(binary_root))

    cases = {'cold': build('cold')}
    other_base = output / 'other-bazel-base'
    other = build('other-output-base', selected_base=other_base)
    other_root = Path(other['binaryRoot'])
    other_before = {i: fingerprint(other_root / ('node_' + i + '.bundle')) for i in nodes}
    build('main-output-base-warm')
    main_root = Path(cases['cold']['binaryRoot'])
    intruder = main_root / ('node_' + ids['App'] + '.bundle/unowned-inside-tree.txt')
    intruder.parent.chmod(intruder.parent.stat().st_mode | 0o700)
    intruder.write_text('inside a declared Bazel tree\n')
    bazel('bazel-clean', ['clean'])
    clean_state = dict(declaredBundlesAbsent=all(not (main_root / ('node_' + i + '.bundle')).exists() for i in nodes),
        injectedTreeFileRemoved=not intruder.exists(), sourceInputsPreserved=plan_before == {p: fingerprint(generated / p) for p in plan_before},
        buildPlanPreserved=build_before == (generated / 'BUILD.bazel').read_bytes(),
        userFilePreserved=sentinel.read_text() == 'outside declared output trees\n', diskCachePreserved=cache.is_dir(),
        otherOutputBasePreserved=other_before == {i: fingerprint(other_root / ('node_' + i + '.bundle')) for i in nodes}, log='bazel-clean.log')
    cases['afterClean'] = build('afterClean')
    bazel('bazel-expunge', ['clean', '--expunge'])
    expunge_state = dict(outputBaseAbsent=not base.exists(), diskCachePreserved=cache.is_dir(),
        sourceInputsPreserved=plan_before == {p: fingerprint(generated / p) for p in plan_before},
        userFilePreserved=sentinel.read_text() == 'outside declared output trees\n',
        otherOutputBasePreserved=other_before == {i: fingerprint(other_root / ('node_' + i + '.bundle')) for i in nodes}, log='bazel-expunge.log')
    cases['afterExpunge'] = build('afterExpunge')
    for name, project in (('producerDeleted', 'Shared'), ('consumerDeleted', 'App')):
        binary_root = Path(cases['afterExpunge']['binaryRoot'])
        bundle = binary_root / ('node_' + ids[project] + '.bundle')
        remove_tree(bundle)
        absent = not bundle.exists()
        cases[name] = build(name)
        cases[name].update(deletedProject=projects[project], deletedBundleAbsentBeforeBuild=absent)
    bazel('before-forced-fresh-expunge', ['clean', '--expunge'])
    fresh_cache = output / 'fresh-empty-cache'
    absent = not base.exists() and not fresh_cache.exists()
    cases['forcedFreshBuild'] = build('forcedFreshBuild', selected_cache=fresh_cache)
    cases['forcedFreshBuild']['outputBaseAndCacheAbsentBeforeBuild'] = absent
    report = dict(schemaVersion=1, scope='R06-lifecycle-characterization', baselineOutput=expected,
        ordinary=dict(cold=cold, clean=clean, afterClean=after_clean, isolatedRebuild=isolated_rebuild, rebuild=rebuild),
        bazelClean=clean_state, bazelExpunge=expunge_state, cases=cases, preparationWorkspaceAbsent=not source.exists(),
        graphLifecycleApi='not implemented; graph action commands remain fixed Build plus replay targets')
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    result = probe(parser.parse_args().output)
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}, indent=2))
