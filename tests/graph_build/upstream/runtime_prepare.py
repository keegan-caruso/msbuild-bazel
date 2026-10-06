"""Stage selected pinned Linux ARM64 managed graphs from source/package archives.

Preparation invokes offline project sync in an owned workspace. The build itself
uses only generated declarations and the public Bazel graph rules.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[3]
COMMIT = '60629d14374c56f1cb51819049ad1fa529307f8d'
SOURCE_SHA256 = '4fae24371e108a046d7bfd30785e9a2f4400552b165b70300a72f855370da3de'
ENTRY = 'src/libraries/System.IO.Pipelines/src/System.IO.Pipelines.csproj'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_archive', type=Path)
    parser.add_argument('package_feed', type=Path, help='directory containing the declared .nupkg archives')
    parser.add_argument('output', type=Path, help='new disposable directory')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--entry', action='append', help='entry project; repeat for a combined graph')
    selection.add_argument('--slice', help='reviewed selection in runtime/subset_slices.json')
    parser.add_argument('--also-slice', action='append', default=[], help='combine reviewed selections, retaining frameworks and declared root replacements')
    parser.add_argument('--framework', help='entry framework; default net10.0 or the selected slice framework')
    parser.add_argument('--prepared-restore', action='store_true', help='generate a separate declared Restore action')
    parser.add_argument('--reference-bindings', type=Path, help='reviewed full raw Build compiler/copy selections')
    parser.add_argument('--worker-cache-mb', type=int, default=4096, help='explicit logical snapshot/preparation cache budget in MiB')
    args = parser.parse_args()
    if args.reference_bindings and args.slice != 'runtime-suites':
        parser.error('--reference-bindings requires --slice runtime-suites')
    if args.worker_cache_mb < 0:
        parser.error('--worker-cache-mb must be nonnegative')
    if args.also_slice and not args.slice:
        parser.error('--also-slice requires --slice')
    entry_properties = {}
    entries, framework = args.entry or [ENTRY], args.framework or 'net10.0'
    if args.slice:
        inventory = json.loads((ROOT / 'tests/runtime/subset_slices.json').read_text())
        assert inventory['commit'] == COMMIT
        selections = [args.slice] + args.also_slice
        reviewed = {item['name']: item for item in inventory['slices']}
        if len(set(selections)) != len(selections) or any(name not in reviewed or not reviewed[name]['entries'] for name in selections):
            parser.error('Choose distinct nonempty reviewed managed slices')
        framework = args.framework or reviewed[args.slice]['framework']
        configured_roots = {}
        for name in selections:
            selected = reviewed[name]
            for path in selected.get('removeRoots', []):
                configured_roots.pop(path, None)
            for entry in selected['entries']:
                path = entry if isinstance(entry, str) else entry['project']
                configured = selected['framework'] if isinstance(entry, str) else entry['framework']
                if args.framework and configured != framework:
                    parser.error('A framework override must match every reviewed slice entry; do not flatten them')
                if path in configured_roots and configured_roots[path] != configured:
                    parser.error('The same entry cannot select conflicting frameworks: ' + path)
                configured_roots[path] = configured
        entries = list(configured_roots)
        entry_properties = {path: {'TargetFramework': configured} for path, configured in configured_roots.items() if configured != framework}
    assert os.uname().sysname == 'Linux', 'Qualification requires Linux'
    assert os.uname().machine == 'aarch64', 'This output mapping qualifies ARM64 only'
    assert hashlib.sha256(args.source_archive.read_bytes()).hexdigest() == SOURCE_SHA256, 'Pinned source archive changed'
    base = args.output.resolve()
    base.mkdir(parents=True, exist_ok=False)
    sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
    dotnet = sdk / 'dotnet'
    env = dict(os.environ, DOTNET_ROOT=str(sdk), DOTNET_HOST_PATH=str(dotnet),
               MSBUILDDISABLENODEREUSE='1')
    source = base / 'source'
    with tarfile.open(args.source_archive) as archive:
        archive.extractall(base, filter='data')
    extracted = base / ('runtime-' + COMMIT)
    extracted.rename(source)
    packages = base / 'packages'
    rows = []
    supplemental = json.loads(Path(__file__).with_name('runtime_supplemental_packages.json').read_text())
    identities = set()
    archives = sorted(args.package_feed.glob('*.nupkg'))
    assert archives, 'Explicit offline package archives are required'
    for archive in archives:
        if archive.name.startswith('._'):
            continue
        with zipfile.ZipFile(archive) as package:
            metadata = ET.fromstring(package.read(next(name for name in package.namelist() if name.endswith('.nuspec'))))
            def field(name):
                return next(item.text for item in metadata.iter() if item.tag.split('}')[-1] == name).lower()
            identity, version = field('id'), field('version')
            assert all(value and not any(part in value for part in ['/', '\\', '..']) for value in [identity, version])
            key = identity + '/' + version
            if key in supplemental:
                assert hashlib.sha256(archive.read_bytes()).hexdigest() == supplemental[key]['sha256'], 'Supplemental archive changed: ' + key
            assert key not in identities, 'Duplicate package identity: ' + key
            identities.add(key)
            directory = packages / key
            directory.mkdir(parents=True)
            package.extractall(directory)
        shutil.copyfile(archive, directory / (identity + '.' + version + '.nupkg'))
        rows.append({'Id': identity, 'Version': version, 'Runfile': key})
    inputs = base / 'inputs.json'
    inputs.write_text(json.dumps({'Inputs': [], 'Packages': rows, 'PackageLock': '//:packages'}, indent=2) + '\n')
    mapping = base / 'mapping.json'
    subprocess.run(['python3', str(Path(__file__).with_name('runtime_contract.py')), str(mapping),
                    '--platform', 'linux-arm64'] + (['--prepared-restore'] if args.prepared_restore else []) +
                    (['--reference-bindings', str(args.reference_bindings.resolve())] if args.reference_bindings else []), check=True)
    if entry_properties:
        reviewed = json.loads(mapping.read_text())
        reviewed['entryProperties'] = entry_properties
        mapping.write_text(json.dumps(reviewed, indent=2) + '\n')
    with (base / 'sync.log').open('w') as log:
        subprocess.run([str(dotnet), str(ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll'),
                        str(source), str(sdk / 'sdk/10.0.400'), *entries, '--framework', framework,
                        '--package-build', '--inputs', str(inputs), '--runfiles', str(packages),
                        '--mappings', str(mapping)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    contract = json.loads((source / 'graph.generated.json').read_text())
    paths = set(contract['SharedInputs'])
    for project in contract['Projects'].values():
        for variant in [project] + project.get('Configurations', []):
            paths.update(variant['Inputs'])
    workspace = base / 'workspace'
    workspace.mkdir()
    for path in sorted(paths):
        original = source / path
        assert original.resolve().is_relative_to(source), 'Input outside owned source: ' + path
        destination = workspace / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, destination)
    for name in ['graph.generated.json', 'graph.generated.bzl']:
        shutil.copyfile(source / name, workspace / name)
    (workspace / 'MODULE.bazel').write_text('module(name="runtime_graph")\nbazel_dep(name="rules_msbuild",version="0.0.0")\n'
        'local_path_override(module_name="rules_msbuild",path=' + json.dumps(str(ROOT)) + ')\n'
        'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
        'dotnet.sdk(name="dotnet",global_json="@rules_msbuild//:global.json")\n'
        'use_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
    build = ['load("@rules_msbuild//msbuild:defs.bzl","msbuild_nuget_package","msbuild_package_lock")',
             'load(":graph.generated.bzl","app_graph")']
    labels = []
    feed = workspace / '.package-source'
    feed.mkdir()
    for index, row in enumerate(rows):
        name = row['Id'] + '.' + row['Version'] + '.nupkg'
        archive = packages / row['Runfile'] / name
        data = archive.read_bytes()
        shutil.copyfile(archive, feed / name)
        label = 'package_' + str(index)
        labels.append(':' + label)
        attributes = dict(name=label, package_id=row['Id'], version=row['Version'], archive='.package-source/' + name,
                          archive_sha256=hashlib.sha256(data).hexdigest(),
                          content_hash=base64.b64encode(hashlib.sha512(data).digest()).decode())
        build.append('msbuild_nuget_package(' + ','.join(key + '=' + json.dumps(value) for key, value in attributes.items()) + ')')
    build += ['msbuild_package_lock(name="packages",packages=' + json.dumps(labels) + ',allow_multiple_versions=True)',
              'app_graph(name="graph",linux_stable_paths=True,linux_worker=True,worker_cache_mb=' + str(args.worker_cache_mb) + ')']
    (workspace / 'BUILD.bazel').write_text('\n'.join(build) + '\n')
    (base / 'preparation.json').write_text(json.dumps(dict(commit=COMMIT, sourceSha256=SOURCE_SHA256, platform='linux-arm64',
        entry=entries[0], entries=entries, framework=framework, entryProperties=entry_properties, slice=args.slice, additionalSlices=args.also_slice, preparedRestore=args.prepared_restore, workerCacheMiB=args.worker_cache_mb,
        inputs=len(paths), archives=len(rows), workspace=str(workspace)), indent=2) + '\n')
    print(workspace, flush=True)


if __name__ == '__main__':
    main()
