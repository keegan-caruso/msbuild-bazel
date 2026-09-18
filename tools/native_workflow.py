"""Opt-in Release/net10 native-cache Build/Test workflow for restored inputs."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile

from native_graph import prepare_native
from portable_cache import tool_identity, validate_bundle, seed
import remote_snapshot
import remote_preparation
import nuget_cache
from native_staging import Staging
from invocation_identity import InvocationIdentity
from preparation_identity import digest
from preparation_reuse import atomic_json, prepared_view
from prepare_graph import ROOT, DOTNET_ROOT
from probe_graph_execution import BAZEL
from probe_bazel import json_stream
from starlark import call

IMPORTS = [Path('/nix/store/dfhdbgnvv0jm1ld0hrzfaklgigvl7bzp-extra.targets'),
           Path('/nix/store/hm53cqanyh9f8dl3bij21iyhvk1mlb30-sign-apphost.proj')]
TOOLS = ('GraphExport', 'EvaluationProbe', 'ReplayPlugin', 'ActionRunner', 'NativeProjectCache', 'TestRunner')


def writable_directories(path):
    if not path.exists(): return
    for item in path.rglob('*'):
        if item.is_dir() and not item.is_symlink(): item.chmod(0o700)
    path.chmod(0o700)


def remove_tree(path):
    if path.exists():
        writable_directories(path); shutil.rmtree(path)


def files(path):
    return sorted((p for p in path.rglob('*') if p.is_file()), key=lambda p: p.as_posix())


def tool_files(name):
    return [ROOT / f'tools/{name}/bin/Release/net10.0/{name}{suffix}'
            for suffix in ('.dll', '.deps.json', '.runtimeconfig.json')]


def bootstrap():
    for name in TOOLS:
        subprocess.run([str(DOTNET_ROOT / 'dotnet'), 'build', str(ROOT / 'tools' / name), '-c', 'Release', '--nologo'], check=True)


@contextmanager
def fresh_plan(source, entry, output, identity):
    env = dict(os.environ, MSBuildEnableWorkloadResolver='false')
    graph, request = output.parent / 'graph.json', output.parent / 'export.json'
    request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(source), dotnetRoot=str(DOTNET_ROOT),
        sdkVersion='10.0.400', packageRoot=str(source / '.nuget/packages'),
        entryPoints=[dict(project=entry, globalProperties={'Configuration': 'Release', 'TargetFramework': 'net10.0'})], output=str(graph))))
    subprocess.run([str(DOTNET_ROOT / 'dotnet'), str(tool_files('GraphExport')[0]), '--request', str(request)], cwd=source, env=env, check=True)
    prepare_native(source, graph, output, toolchain=identity, environment=env, _prebuilt_tools={name: tool_files(name)[0] for name in ('GraphExport', 'ReplayPlugin')})
    yield dict(reused=False, discoveryExecuted=True, materializationExecuted=True)


def generate(plan, source, generated, tests, seeds):
    manifest = json.loads((plan / 'manifest.json').read_text())
    entry = json.loads((plan / 'entry.json').read_text())['entry']
    module = 'module(name = "native_msbuild_workflow")\n\nbazel_dep(name = "platforms", version = "0.0.11")\n\nlocal_dotnet_sdk = use_repo_rule("//:msbuild.bzl", "local_dotnet_sdk")\n' + call('local_dotnet_sdk', name='dotnet', path=str(DOTNET_ROOT), external_imports=list(map(str, IMPORTS)))
    stage = Staging(generated)
    previous = generated / 'MODULE.bazel'
    if previous.is_file() and previous.read_text() != module:
        (generated / 'MODULE.bazel.lock').unlink(missing_ok=True)
    stage.write('MODULE.bazel', module.encode())
    stage.tree(plan / 'src', 'src')
    for name in ('restore.json', 'manifest.json'): stage.copy(plan / name, name)
    for name in ('msbuild.bzl', 'native_cache.bzl', 'native_test.bzl'): stage.copy(ROOT / 'bazel' / name, name)
    for name in ('NativeProjectCache', 'TestRunner'):
        for path in tool_files(name):
            stage.copy(path, 'runner/' + path.name)
    rejected = []
    if seeds is not None and seeds.exists():
        for bundle in seeds.iterdir():
            if not bundle.is_dir(): continue
            try:
                if bundle.is_symlink() or any(p.is_symlink() for p in bundle.rglob('*')): raise ValueError('linked cache payload')
                values = {p.relative_to(bundle).as_posix(): p.read_bytes() for p in files(bundle)}
                result = validate_bundle(values)
                if result['toolchain'] != manifest['toolchain'] or manifest['projects'].get(result['project'], {}).get('identity') != result['inputs']: continue
                if result['key'] != bundle.name: raise ValueError('seed directory/key mismatch')
                for relative, data in values.items(): stage.write('seeds/' + bundle.name + '/' + relative, data)
            except (OSError, ValueError, KeyError, TypeError) as error: rejected.append(str(error))
    build = 'load(":native_cache.bzl", "msbuild_native_cache")\n'
    if tests is not None: build += 'load(":native_test.bzl", "native_test")\n'
    build += call('msbuild_native_cache', name='build', project=entry,
        srcs=sorted(p for p in stage.desired if p.startswith('src/')),
        seeds=sorted(p for p in stage.desired if p.startswith('seeds/')),
        manifest='manifest.json', restore='restore.json', runner='runner/NativeProjectCache.dll',
        runner_support=['runner/NativeProjectCache.deps.json', 'runner/NativeProjectCache.runtimeconfig.json'],
        sdk='@dotnet//:files', dotnet='@dotnet//:sdk/dotnet')
    if tests is not None:
        data, data_hashes = [], {}
        for relative in tests['data']:
            path = Path(relative)
            if not relative or path.is_absolute() or relative != path.as_posix() or any(p in ('.', '..', '') for p in relative.split('/')) or '\\' in relative:
                raise ValueError('unsafe test data path')
            origin = source / relative
            if not origin.resolve().is_relative_to(source) or not origin.is_file() or relative in data_hashes: raise ValueError('missing, escaping or duplicate test data')
            data_hashes[relative] = hashlib.sha256(origin.read_bytes()).hexdigest()
            target = generated / 'test-data' / relative
            stage.copy(origin, 'test-data/' + relative)
            if hashlib.sha256(target.read_bytes()).hexdigest() != data_hashes[relative]: raise ValueError('test data changed during staging')
            data.append('test-data/' + relative)
        build += call('native_test', name='test', subject=':build', project=entry,
            global_properties={'configuration': 'Release', 'targetframework': 'net10.0'},
            native_inputs=manifest['projects'][entry]['identity'], native_toolchain=manifest['toolchain'],
            runtime_directory=str(Path(entry).parent / 'bin/Release/net10.0'), assembly=Path(entry).stem + '.dll',
            data=data, data_hashes=data_hashes, expected_tests=tests['expectedTests'],
            runner='runner/TestRunner.dll', runner_support=['runner/TestRunner.deps.json', 'runner/TestRunner.runtimeconfig.json'],
            host_identity='manifest.json', sdk='@dotnet//:files', dotnet='@dotnet//:sdk/dotnet', size='small', timeout='moderate')
    stage.write('BUILD.bazel', build.encode())
    stage.finish()
    return rejected


class Workflow:
    def __init__(self, source, state, entry, *, tests=None, reuse=False, protected_store=None, incremental_sources=False, remote_endpoint=None, remote_snapshot_digest=None, nuget_packages=None):
        self.source, self.state = Path(source).resolve(), Path(state).resolve()
        self.entry, self.tests = entry, tests
        self.nuget_packages = Path(nuget_packages).expanduser().resolve() if nuget_packages else nuget_cache.default_cache()
        self.remote_endpoint = remote_endpoint.rstrip('/') if remote_endpoint else None
        self.remote_snapshot_digest = remote_snapshot_digest
        if remote_snapshot_digest is not None and (self.remote_endpoint is None or not remote_snapshot.valid_digest(remote_snapshot_digest)):
            raise ValueError('remote snapshot requires an endpoint and SHA-256 digest')
        self.reuse, self.protected_store, self.incremental_sources = reuse or bool(remote_endpoint), protected_store, incremental_sources or bool(remote_endpoint)
        if self.source == self.state or self.source.is_relative_to(self.state) or self.state.is_relative_to(self.source) or self.state.is_relative_to(ROOT) or ROOT.is_relative_to(self.state):
            raise ValueError('source, state and controller must be disjoint')
        if not entry or entry != Path(entry).as_posix() or Path(entry).is_absolute() or any(p in ('', '.', '..') for p in entry.split('/')): raise ValueError('invalid entry')
        for name in TOOLS:
            if not tool_files(name)[0].exists(): raise ValueError('missing prebuilt tools; run with --bootstrap first')

    def run(self, output, *, operation='build', force_tests=False):
        tick = time.perf_counter()
        output = Path(output).resolve()
        for other in (self.source, self.state, ROOT):
            if output == other or output.is_relative_to(other) or other.is_relative_to(output): raise ValueError('report output must be disjoint')
        output.mkdir(parents=True, exist_ok=False)
        if operation not in ('build', 'test') or operation == 'test' and self.tests is None: raise ValueError('test operation requires explicit --tests')
        self.state.mkdir(parents=True, exist_ok=True)
        report = dict(accepted=False, operation=operation, phases={})
        with (self.state / 'lease').open('a') as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            owner = self.state / 'owner.json'
            if not owner.exists():
                if any(p.name != 'lease' for p in self.state.iterdir()): raise ValueError('state is not owned by native workflow')
                atomic_json(owner, {'policy': 'native-workflow-v1'})
            if json.loads(owner.read_text()) != {'policy': 'native-workflow-v1'}: raise ValueError('state policy mismatch')
            try:
                start = time.perf_counter()
                controller_roots = [ROOT / 'bazel', *[ROOT / 'tools' / name for name in TOOLS]]
                identities = InvocationIdentity(controller_roots, self.protected_store)
                for root in controller_roots: identities.snapshot(root, [root])
                sdk = digest(identities.snapshot(DOTNET_ROOT.parents[1], [Path('/nix/store')]))
                identity = tool_identity(sdk, tool_files('NativeProjectCache'), sorted((ROOT / 'tools').glob('*.py')), IMPORTS)
                report['phases']['identity'] = time.perf_counter() - start
                snapshot = None
                receipts = {'verifiedBlobs': []}
                if self.remote_endpoint:
                    report['remote'] = {}
                    start = time.perf_counter()
                    if self.remote_snapshot_digest:
                        try: snapshot = remote_snapshot.download(self.remote_endpoint, self.remote_snapshot_digest)
                        except (OSError, ValueError, KeyError, TypeError) as error: report['remote']['snapshotMiss'] = str(error)
                    report['phases']['remoteSnapshot'] = time.perf_counter() - start
                with tempfile.TemporaryDirectory(prefix='p-', dir=self.state) as temporary:
                    start = time.perf_counter()
                    source, report['nuget'] = nuget_cache.stage(self.source, self.state / 'nuget/workspace', self.nuget_packages)
                    report['phases']['nuget'] = time.perf_counter() - start
                    plan = Path(temporary) / 'plan'; start = time.perf_counter()
                    context = (prepared_view(source, self.state / 'preparation', plan,
                        [dict(project=self.entry, globalProperties={'Configuration': 'Release', 'TargetFramework': 'net10.0'})],
                        native_toolchain=identity, protected_store=identities, incremental_sources=self.incremental_sources, borrow_native=True,
                        remote_preparation=(self.remote_endpoint, snapshot['preparation']) if snapshot and snapshot['preparation'] else None, nuget_cache=self.nuget_packages)
                        if self.reuse else fresh_plan(source, self.entry, plan, identity))
                    with context as preparation:
                        report['preparation'] = preparation
                        report['phases']['prepare'] = time.perf_counter() - start
                        start = time.perf_counter(); generated = self.state / 'g'
                        pointer = self.state / 'cache.json'; cache = None
                        if pointer.exists():
                            try:
                                name = json.loads(pointer.read_text())['generation']
                                if not isinstance(name, str) or len(name) != 32 or any(c not in '0123456789abcdef' for c in name): raise ValueError('invalid local cache generation')
                                cache = self.state / 'cache' / name
                                if cache.is_symlink(): raise ValueError('linked local cache generation')
                            except (OSError, ValueError, KeyError, TypeError) as error:
                                cache = None; report['cacheRejection'] = str(error)
                        local_cache = cache
                        if snapshot is not None:
                            download_start = time.perf_counter()
                            remote_seeds = Path(temporary) / 'seeds'
                            receipts = seed(self.remote_endpoint, snapshot['projects'], json.loads((Path(preparation.get('workspace', plan)) / 'manifest.json').read_text()), remote_seeds)
                            # Local bundles have the same validation at staging. Prefer
                            # successfully verified remote bytes when keys overlap.
                            if cache is not None and cache.exists():
                                for bundle in cache.iterdir():
                                    if bundle.is_dir() and not bundle.is_symlink() and not (remote_seeds / bundle.name).exists():
                                        shutil.copytree(bundle, remote_seeds / bundle.name, symlinks=True)
                            cache = remote_seeds
                            report['remote']['seeds'] = receipts
                            report['phases']['remoteSeeds'] = time.perf_counter() - download_start
                        report['seedRejections'] = generate(Path(preparation.get('workspace', plan)), Path(preparation.get('sourceView', source)), generated, self.tests, cache)
                        report['phases']['stage'] = time.perf_counter() - start
                        execution = output / 'execution.json'
                        command = [str(BAZEL), '--nohome_rc', '--noworkspace_rc', '--output_base=' + str(self.state / 'b'),
                            '--output_user_root=' + str(self.state / 'u'), operation, '//:' + operation,
                            '--incompatible_autoload_externally=', '--jobs=2', '--spawn_strategy=darwin-sandbox',
                            '--strategy=MsbuildNativeCache=darwin-sandbox', '--execution_log_json_file=' + str(execution),
                            '--noshow_progress', '--color=no', '--curses=no']
                        if operation == 'test': command += ['--test_output=errors', '--cache_test_results=' + ('no' if force_tests else 'yes')]
                        start = time.perf_counter()
                        result = subprocess.run(command, cwd=generated, capture_output=True, text=True, timeout=900)
                        (output / 'bazel.log').write_text(result.stdout + result.stderr)
                        report['phases']['bazel'] = time.perf_counter() - start
                        report['exitCode'] = result.returncode
                        actions = list(json_stream(execution)) if execution.exists() else []
                        builds = [a for a in actions if a.get('mnemonic') == 'MsbuildNativeCache' and not a.get('cacheHit')]
                        report['buildActions'] = len(builds)
                        report['testActions'] = sum(a.get('mnemonic') == 'TestRunner' and not a.get('cacheHit') for a in actions)
                        if any(a.get('runner') != 'darwin-sandbox' for a in builds): raise ValueError('native sandbox required')
                        report['compiles'] = json.loads((generated / 'bazel-bin/build.diagnostics/action.json').read_text())['compiles'] if builds else 0
                        if operation == 'test' and (report['testActions'] or result.returncode == 0):
                            archive = generated / 'bazel-testlogs/test/test.outputs/outputs.zip'
                            if archive.exists():
                                with zipfile.ZipFile(archive) as z: test_report = json.loads(z.read('report.json'))
                            else: test_report = json.loads((generated / 'bazel-testlogs/test/test.outputs/report.json').read_text())
                            report['test'] = test_report
                            shutil.copytree(generated / 'bazel-testlogs/test', output / 'test')
                        if result.returncode: raise RuntimeError('Bazel failed; see ' + str(output / 'bazel.log'))
                        if operation == 'test' and (not report['test']['passed'] or report['test']['buildOrRestoreInvoked']): raise ValueError('test acceptance failed')
                        start = time.perf_counter()
                        name = uuid.uuid4().hex; destination = self.state / 'cache' / name
                        shutil.copytree(generated / 'bazel-bin/build.bundle/cache', destination)
                        report['phases']['publish'] = time.perf_counter() - start
                        report['runtimeHashes'] = {p.relative_to(generated / 'bazel-bin/build.bundle/app').as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files(generated / 'bazel-bin/build.bundle/app')}
                        lease_exit = time.perf_counter()
                    identities.verify()
                    report['identitySnapshotHits'] = identities.hits
                    report['phases']['leaseExit'] = time.perf_counter() - lease_exit
                    # Commit build artifacts only after discovery's lease exit checks.
                    atomic_json(pointer, {'generation': name})
                    if local_cache is not None: remove_tree(local_cache)
                    if self.remote_endpoint:
                        start = time.perf_counter()
                        try:
                            prepared = None
                            # Only the generation consumed by this successful run is
                            # eligible; unsupported fresh fallback must not export stale state.
                            if preparation.get('sourceView'):
                                receipt = json.loads((self.state / 'preparation/current.json').read_text())
                                prepared = remote_preparation.upload(self.remote_endpoint, self.state / 'preparation/generations' / receipt['generation'])
                            report['remote']['publishedSnapshot'] = remote_snapshot.upload(self.remote_endpoint, destination, prepared, verified_blobs=receipts['verifiedBlobs'])
                        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
                            report['remote']['publicationError'] = str(error)
                        report['phases']['remotePublish'] = time.perf_counter() - start
                report['accepted'] = True
            finally:
                report['seconds'] = time.perf_counter() - tick
                (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('workspace', 'state', 'entry', 'output'): p.add_argument('--' + name, required=True)
    p.add_argument('--operation', choices=('build', 'test'), default='build')
    p.add_argument('--reuse', action='store_true')
    p.add_argument('--nuget-packages', help='restored global package cache; defaults to NUGET_PACKAGES or ~/.nuget/packages')
    p.add_argument('--remote-endpoint', help='trusted native HTTP CAS endpoint; enables leased preparation reuse')
    p.add_argument('--remote-snapshot', help='explicit immutable snapshot SHA-256 to consume')
    p.add_argument('--trust-system-nix-store', action='store_true')
    p.add_argument('--incremental-sources', action='store_true')
    p.add_argument('--tests', type=Path); p.add_argument('--force-tests', action='store_true'); p.add_argument('--bootstrap', action='store_true')
    a = p.parse_args()
    if a.bootstrap: bootstrap()
    from protected_store import ProtectedStore
    result = Workflow(a.workspace, a.state, a.entry, tests=json.loads(a.tests.read_text()) if a.tests else None,
        reuse=a.reuse, protected_store=ProtectedStore() if a.trust_system_nix_store else None, incremental_sources=a.incremental_sources, remote_endpoint=a.remote_endpoint, remote_snapshot_digest=a.remote_snapshot, nuget_packages=a.nuget_packages).run(a.output, operation=a.operation, force_tests=a.force_tests)
    print(json.dumps(result, indent=2))
