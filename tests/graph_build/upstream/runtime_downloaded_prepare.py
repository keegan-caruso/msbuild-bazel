"""Qualify downloaded SDK + native NuGet update + offline sync on runtime sources.

Keep the full source for update checks and a closed, relocatable consumer workspace.
Use runtime_qualify, runtime_benchmark and runtime_complete_remote for execution.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time

from runtime_prepare import COMMIT, SOURCE_SHA256
from runtime_feed_config import pin_runtime_feeds
from runtime_sync_inputs import SYNC_SRCS, assert_preparation_reused

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_archive', type=Path)
    parser.add_argument('output', type=Path, help='fresh owned preparation directory')
    parser.add_argument('--slice', choices=['loaded-common', 'runtime-suites'], default='loaded-common', help='reviewed four-root or 39-root/eight-suite graph')
    parser.add_argument('--evaluation-reuse', action='store_true', help='opt into the reviewed Pipelines body/API evaluation contract')
    parser.add_argument('--evaluation-cache-mb', type=int, default=512, help='explicit retained-evaluation memory budget; 1024 for the large reviewed graph')
    parser.add_argument('--resume', action='store_true', help='recheck a retained preparation after a completed sync; consumer workspace must still be absent')
    args = parser.parse_args()
    if args.evaluation_cache_mb <= 0:
        parser.error('--evaluation-cache-mb must be positive')
    descriptor = 'runtime_source_host_edit.json' if args.slice == 'runtime-suites' else 'runtime_loaded_common_edit.json'
    edit = json.loads(Path(__file__).with_name(descriptor).read_text())
    entries = edit['entries']
    selection = json.loads((ROOT / 'tests/runtime/subset_slices.json').read_text())
    assert selection['commit'] == COMMIT
    frameworks = {}
    for row in selection['slices']:
        for value in row['entries']:
            project = value if isinstance(value, str) else value['project']
            framework = row['framework'] if isinstance(value, str) else value['framework']
            if project in entries:
                assert project not in frameworks or frameworks[project] == framework, project
                frameworks[project] = framework
    assert set(frameworks) == set(entries)
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert hashlib.sha256(args.source_archive.read_bytes()).hexdigest() == SOURCE_SHA256
    base = args.output.resolve()
    source = base / 'source'
    if args.resume:
        assert source.is_dir() and not (base / 'workspace').exists()
        assert (source / 'graph.generated.json').is_file() and (source / 'nuget.lock.json').is_file()
    else:
        base.mkdir(parents=True, exist_ok=False)
        with tarfile.open(args.source_archive) as archive:
            archive.extractall(base, filter='data')
        (base / ('runtime-' + COMMIT)).rename(source)
        # The upstream README link is irrelevant to compilation. Materialize safe
        # authored links in this owned copy so the updater can reject all symlinks.
        for path in source.rglob('*'):
            if path.is_symlink():
                target = path.resolve()
                assert target.is_relative_to(source) and target.is_file()
                data = target.read_bytes()
                path.unlink()
                path.write_bytes(data)
    # Avoid differently signed copies of the same package racing across feeds.
    pin_runtime_feeds(source / 'NuGet.config', packages=('Microsoft.TestPlatform.ObjectModel',))
    subprocess.run(['python3', str(Path(__file__).with_name('runtime_contract.py')), str(source / 'mappings.json'),
                    '--platform', 'linux-arm64', '--prepared-restore', '--resolve-references'] + (['--evaluation-reuse'] if args.evaluation_reuse else []), check=True)
    mapping_path = source / 'mappings.json'
    mapping = json.loads(mapping_path.read_text())
    overrides = {project: {'TargetFramework': framework} for project, framework in frameworks.items() if framework != 'net10.0'}
    if overrides:
        mapping['entryProperties'] = overrides
        mapping_path.write_text(json.dumps(mapping, indent=2) + '\n')
    module = ('module(name="runtime_downloaded_workflow")\nbazel_dep(name="rules_msbuild",version="0.0.0")\n'
              'local_path_override(module_name="rules_msbuild",path=' + json.dumps(str(ROOT)) + ')\n'
              'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
              'dotnet.sdk(name="dotnet",version="10.0.400")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
    inventory = ('nuget=use_extension("@rules_msbuild//msbuild:nuget.bzl","nuget")\n'
                 'nuget.lock(name="nuget",lockfile="//:nuget.lock.json")\nuse_repo(nuget,"nuget")\n')
    update = ('load("@rules_msbuild//msbuild:sync.bzl","msbuild_nuget_update","msbuild_sync")\n'
              'entries=' + json.dumps(entries) + '\n'
              'msbuild_nuget_update(name="update_packages",projects=entries,framework="net10.0",mappings="mappings.json")\n')
    sync = 'msbuild_sync(name="sync",projects=entries,framework="net10.0",mappings="mappings.json",package_lock="@nuget//:packages",package_build=True,resolve_references=True,' + SYNC_SRCS + ')\n'
    if args.resume:
        assert (source / 'MODULE.bazel').read_text() == module + inventory
        assert (source / 'BUILD.bazel').read_text() in [update + sync, update + sync.replace(',' + SYNC_SRCS, '')]
    (source / 'MODULE.bazel').write_text(module)
    (source / 'BUILD.bazel').write_text(update)
    command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(base / 'sync-bazel'), 'run']
    options = ['--repository_cache=' + os.environ['RULES_MSBUILD_TEST_REPOSITORY_CACHE']] if os.environ.get('RULES_MSBUILD_TEST_REPOSITORY_CACHE') else []
    rows = []

    def run(label, target, check=False):
        start = time.monotonic()
        trace = base / (label + '.actions.json')
        with (base / (label + '.log')).open('w') as log:
            subprocess.run(command + [target, *options, '--execution_log_json_file=' + str(trace)] + (['--', '--check'] if check else []), cwd=source,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        elapsed = time.monotonic() - start
        if label == 'sync-check':
            assert_preparation_reused(trace)
        rows.append(dict(command=target + (' -- --check' if check else ''), seconds=elapsed))
        print(json.dumps(rows[-1]), flush=True)

    try:
        run('update', '//:update_packages')
        run('update-check', '//:update_packages', True)
        (source / 'MODULE.bazel').write_text(module + inventory)
        (source / 'BUILD.bazel').write_text(update + sync)
        run('sync', '//:sync')
        run('sync-check', '//:sync', True)
        contract = json.loads((source / 'graph.generated.json').read_text())
        variants = [v for p in contract['Projects'].values() for v in p.get('Configurations') or [p]]
        assert contract['Entries'] == entries
        compilations = sum(bool(v['OutputDirectories'] or v.get('OutputFiles')) for v in variants)
        assert compilations == edit['compiled'], 'Unexpected reviewed compilation scope'
        assert contract.get('EntryProperties', {}) == overrides
        paths = set(contract['SharedInputs']) | set(contract['DefinitionDigests']) | {p for v in variants for p in v['Inputs']}
        paths |= set(contract['Restore']['Inputs'])
        workspace = base / 'workspace'
        workspace.mkdir()
        for path in sorted(paths):
            original = source / path
            assert original.resolve().is_relative_to(source) and original.is_file(), path
            destination = workspace / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, destination)
        for name in ['graph.generated.json', 'graph.generated.bzl', 'nuget.lock.json', 'mappings.json', 'NuGet.config']:
            shutil.copyfile(source / name, workspace / name)
        (workspace / 'MODULE.bazel').write_text(module + inventory)
        # Update belongs in the retained full source, not this pruned consumer.
        budget = ',evaluation_cache_mb=' + str(args.evaluation_cache_mb) if args.evaluation_cache_mb != 512 else ''
        (workspace / 'BUILD.bazel').write_text('alias(name="packages",actual="@nuget//:packages")\nload(":graph.generated.bzl","app_graph")\napp_graph(name="graph",linux_stable_paths=True,linux_worker=True' + budget + ')\n'
            'load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph_output")\n'
            'msbuild_graph_output(name="pipelines_assembly",graph=":graph",path="artifacts/bin/System.IO.Pipelines/Release/net10.0/System.IO.Pipelines.dll",visibility=["//visibility:public"])\n')
        manifest = json.loads((source / 'nuget.lock.json').read_text())
        query = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(base / 'sync-bazel')]
        execution_root = Path(subprocess.check_output(query + ['info', 'execution_root'], cwd=source, text=True).strip())
        archives = subprocess.check_output(query + ['cquery', '@nuget//:archives', '--output=files'], cwd=source, text=True).splitlines()
        feed = workspace / '.package-source'
        feed.mkdir()
        expected = {p['id'].lower() + '.' + p['version'].lower() + '.nupkg': p['sha256'] for p in manifest['packages']}
        assert {Path(path).name for path in archives} == expected.keys()
        for path in archives:
            archive = execution_root / path
            assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected[archive.name]
            shutil.copyfile(archive, feed / archive.name)
        shutil.copyfile(source / 'MODULE.bazel.lock', workspace / 'MODULE.bazel.lock')
        summary = dict(resumed=args.resume, evaluationReuseInputs=contract.get('EvaluationReuseInputs'), evaluationCacheMiB=args.evaluation_cache_mb, commit=COMMIT, sourceSha256=SOURCE_SHA256, sdk='10.0.400', slice=args.slice, entries=entries,
                       configurations=len(variants), compilations=compilations,
                       archives=len(manifest['packages']), nativeLocks=len(manifest['lockFiles']), inputs=len(paths), commands=rows)
        (base / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps(summary), flush=True)
    finally:
        subprocess.run([str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(base / 'sync-bazel'), 'shutdown'],
                       cwd=source, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
