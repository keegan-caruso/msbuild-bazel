"""Lease-bound local preparation reuse for the qualified RUL-5 discovery slice.

Use prepared_view through the end of consumption. Persisted JSON is never a lease.
The cache is owned local state, not an authenticated or remote artifact store.
"""
import argparse
from contextlib import contextmanager, ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import subprocess
import uuid
import tempfile
import zipfile

import discovery_contract as discovery
import prepare_graph
from preparation_identity import IdentityError, digest, tree_snapshot

ROOT = prepare_graph.ROOT
POLICY = 'leased-preparation-v1'


def controller():
    paths = [*sorted((ROOT / 'tools').glob('*.py')),
             *sorted((ROOT / 'tools').glob('*.json')),
             *sorted((ROOT / 'tools').glob('*.props'))]
    return digest({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})


CONTROLLER = controller()


def tool_identity(protected_store=None):
    if controller() != CONTROLLER:
        raise IdentityError('preparation controller changed; start a fresh process')
    roots = [ROOT / 'bazel', *[ROOT / 'tools' / name for name in
             ('GraphExport', 'EvaluationProbe', 'ReplayPlugin', 'ActionRunner', 'NativeProjectCache', 'TestRunner')]]
    snapshot = tree_snapshot if protected_store is None else protected_store.snapshot
    return dict(controller=CONTROLLER, trees={str(p): snapshot(p, [p])['sha256'] for p in roots},
                sdk=str(prepare_graph.DOTNET_ROOT), python=dict(version=sys.version, executable=sys.executable,
                    executableSha256=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()))


def atomic_json(path, value):
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    try:
        with temporary.open('x') as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def payload_identity(path):
    snapshot = tree_snapshot(path)
    if any(item['kind'] == 'symlink' for item in snapshot['entries']):
        raise IdentityError('prepared payload contains symlinks')
    return snapshot['sha256']


def read_candidate(state, request):
    """A missing, malformed or corrupt generation is a miss, never usable input."""
    try:
        pointer = json.loads((state / 'current.json').read_text())
        name = pointer['generation']
        if not isinstance(name, str) or len(name) != 32 or any(c not in '0123456789abcdef' for c in name):
            raise IdentityError('invalid preparation generation')
        generation = state / 'generations' / name
        if generation.is_symlink(): raise IdentityError('linked preparation generation')
        manifest = json.loads((generation / 'manifest.json').read_text())
        if pointer['sha256'] != digest(manifest): raise IdentityError('corrupt preparation manifest')
        if manifest['policy'] != POLICY or manifest['request'] != request:
            return None, 'request-changed'
        discovery.validate_certificate(manifest['certificate'])
        if digest(json.loads((generation / 'payload/graph.json').read_text())) != manifest['certificate']['graphSha256']:
            raise IdentityError('prepared graph differs from discovery certificate')
        if payload_identity(generation / 'payload') != manifest['payloadSha256']:
            raise IdentityError('corrupt prepared payload')
        return (generation, manifest), None
    except (OSError, ValueError, KeyError, TypeError) as error:
        return None, 'missing-or-corrupt-state: ' + str(error)


def verify_view(certificate, *, protected_store=None):
    """Recheck the leased inputs before committing or exposing prepared bytes."""
    roots = certificate['identity']['roots']
    allowed = [root['location'] for root in roots.values()]
    snapshot = tree_snapshot if protected_store is None else protected_store.snapshot
    for root in roots.values():
        if snapshot(root['location'], allowed)['sha256'] != root['sha256']:
            raise IdentityError('leased discovery inputs changed before publication')
    if any(Path(path).exists() for path in certificate['externalAbsent']):
        raise IdentityError('external namespace changed before publication')


def publish(state, workspace, graph_path, certificate, request, *, protected_store=None, compile_boundary=False, native_toolchain=None, previous_native=None, imported_payload=None, imported_sha256=None):
    """Flush a complete generation before atomically switching the commit pointer."""
    generations = state / 'generations'
    generations.mkdir(exist_ok=True)
    name = uuid.uuid4().hex
    pending = generations / ('.pending-' + name)
    pending.mkdir()
    try:
        if imported_payload is not None:
            shutil.copytree(imported_payload, pending / 'payload')
            if payload_identity(pending / 'payload') != imported_sha256:
                raise IdentityError('remote payload changed during installation')
        elif native_toolchain is None:
            prepare_graph._prepare(workspace, graph_path, pending / 'payload', _leased=True, compile_boundary=compile_boundary)
        elif previous_native is not None:
            from native_graph import refresh_sources
            generation, previous_manifest = previous_native
            refresh_sources(generation / 'payload', workspace, json.loads(graph_path.read_text()),
                pending / 'payload', native_toolchain, certificate=certificate,
                previous_certificate=previous_manifest['certificate'], payload_sha256=previous_manifest['payloadSha256'])
        else:
            from native_graph import materialize
            prepared = pending / 'evaluated'
            graph = prepare_graph._prepare(workspace, graph_path, prepared, _leased=True)
            materialize(prepared, graph, pending / 'payload', native_toolchain)
            shutil.rmtree(prepared)
        if tool_identity(protected_store) != request['tools']:
            raise IdentityError('preparation tools changed during materialization')
        manifest = dict(policy=POLICY, request=request, certificate=certificate,
                        payloadSha256=payload_identity(pending / 'payload'))
        atomic_json(pending / 'manifest.json', manifest)
        for path in pending.rglob('*'):
            if path.is_file():
                with path.open('rb') as stream: os.fsync(stream.fileno())
        for path in sorted((p for p in pending.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            sync_directory(path)
        sync_directory(pending)
        committed = generations / name
        pending.rename(committed)
        sync_directory(generations)
        verify_view(certificate, protected_store=protected_store)
        atomic_json(state / 'current.json', dict(generation=name, sha256=digest(manifest)))
        return committed
    finally:
        if pending.exists(): shutil.rmtree(pending)


@contextmanager
def fresh_view(source, output, entries, *, environment=None, tests=None, compile_boundary=False, native_toolchain=None):
    """Existing uncached behavior for operations outside the qualified slice."""
    import tempfile
    if native_toolchain is not None: environment = dict(os.environ, MSBuildEnableWorkloadResolver='false')
    with tempfile.TemporaryDirectory(prefix='fresh-export-', dir=output.parent) as directory:
        temporary = Path(directory)
        dotnet = prepare_graph.DOTNET_ROOT / 'dotnet'
        # Native callers bind prebuilt tools before entering preparation.
        # Rebuilding here would mutate the controller within that invocation.
        if native_toolchain is None:
            subprocess.run([str(dotnet), 'build', str(ROOT / 'tools/GraphExport'), '-c', 'Release', '--nologo'],
                           cwd=ROOT, env=environment, check=True)
        graph = temporary / 'graph.json'
        request = temporary / 'request.json'
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(source),
            dotnetRoot=str(prepare_graph.DOTNET_ROOT), sdkVersion='10.0.400',
            packageRoot=str(source / '.nuget/packages'), entryPoints=entries, output=str(graph))))
        subprocess.run([str(dotnet), str(ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll'),
                        '--request', str(request)], cwd=source, env=environment, check=True)
        if native_toolchain is None:
            prepare_graph.prepare(source, graph, output, environment=environment, tests=tests, compile_boundary=compile_boundary)
        else:
            from native_graph import prepare_native
            prepare_native(source, graph, output, toolchain=native_toolchain, environment=environment, _prebuilt_tools={name: ROOT / 'tools' / name / 'bin/Release/net10.0' / (name + '.dll') for name in ('GraphExport', 'ReplayPlugin')})
        yield dict(reused=False, discoveryExecuted=True, materializationExecuted=True,
                   toolBuildsExecuted=native_toolchain is None, reason='unsupported-request', workspace=str(output))


@contextmanager
def prepared_view(source, state, output, entries, *, environment=None, tests=None, protected_store=None, incremental_sources=False, compile_boundary=False, native_toolchain=None, borrow_native=False, remote_preparation=None, nuget_cache=None):
    """Materialize a private consumer copy and retain both leases until it finishes.

    Tools must be prebuilt for reuse. Tests and custom environments take the fresh
    path. A cache hit skips evaluation, export, tool builds and materialization;
    input sealing/hashing, artifact verification and consumer copying still run.
    """
    if borrow_native and native_toolchain is None:
        raise IdentityError('borrowing requires native read-only consumption')
    if native_toolchain is not None and (compile_boundary or tests is not None or environment is not None or
            len(native_toolchain) != 64 or any(c not in '0123456789abcdef' for c in native_toolchain)):
        raise IdentityError('native preparation requires an explicit digest and build-only default context')
    source, state, output = (Path(p).resolve() for p in (source, state, output))
    if output.exists(): raise FileExistsError(output)
    for left, right in ((source, state), (source, output), (state, output), (ROOT, state)):
        if left == right or left.is_relative_to(right) or right.is_relative_to(left):
            raise IdentityError('source, state, controller and consumer paths must be disjoint')
    output.parent.mkdir(parents=True, exist_ok=True)
    supported = (environment is None and tests is None and prepare_graph.DOTNET_ROOT == discovery.SDK and
        all(set(e) == {'project', 'globalProperties'} and e['globalProperties'] ==
            {'Configuration': 'Release', 'TargetFramework': 'net10.0'} for e in entries))
    if not supported:
        with fresh_view(source, output, entries, environment=environment, tests=tests, compile_boundary=compile_boundary, native_toolchain=native_toolchain) as result:
            yield result
        return
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'lease').open('a') as lease, ExitStack() as remote_stack:
        fcntl.flock(lease, fcntl.LOCK_EX)
        marker = state / 'owner.json'
        if not marker.exists():
            if any(p.name != 'lease' for p in state.iterdir()):
                raise IdentityError('state directory is not owned by preparation reuse')
            atomic_json(marker, dict(policy=POLICY))
        if json.loads(marker.read_text()) != dict(policy=POLICY):
            raise IdentityError('preparation owner policy mismatch')
        # Stale pending generations are never selected, even after a killed writer.
        for pending in (state / 'generations').glob('.pending-*'):
            if pending.is_symlink(): pending.unlink()
            else: shutil.rmtree(pending)
        request = dict(entries=entries, environment=environment, tests=tests,
                       operation='prepare_graph', tools=tool_identity(protected_store), compileBoundary=compile_boundary)
        if native_toolchain is not None: request['nativeToolchain'] = native_toolchain
        if protected_store is not None: request['storePolicy'] = getattr(protected_store, 'policy', 'trusted-system-nix-session-v1')
        if incremental_sources: request['sourcePolicy'] = 'compile-content-only-v1'
        candidate, reason = read_candidate(state, request)
        remote_metadata = None
        if candidate is None and remote_preparation is not None:
            import remote_preparation as portable
            try:
                directory = Path(remote_stack.enter_context(tempfile.TemporaryDirectory(prefix='.remote-', dir=state))) / 'generation'
                remote_metadata = portable.download(*remote_preparation, directory, request, cache_roots=([nuget_cache] if nuget_cache is not None else []) + [source / '.nuget/packages'])
                candidate = (directory, dict(policy=POLICY, request=request,
                    certificate=remote_metadata['certificate'], payloadSha256=remote_metadata['payloadSha256']))
            except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
                remote_metadata = None
                reason = 'remote-preparation-miss: ' + str(error)
        discovery_state = state / 'discovery'

        @contextmanager
        def consume(generation, manifest, reused, reason, discovery_executed=None):
            payload = generation / 'payload'
            if borrow_native:
                # Native staging only reads this view. The preparation lease is
                # held until after its bytes are checked again at consumption exit.
                workspace = payload
            else:
                import tempfile
                with tempfile.TemporaryDirectory(prefix='.consumer-', dir=output.parent) as directory:
                    staged = Path(directory) / 'workspace'
                    shutil.copytree(payload, staged)
                    if payload_identity(staged) != manifest['payloadSha256']:
                        raise IdentityError('prepared payload changed during copy')
                    if output.exists(): raise FileExistsError(output)
                    staged.rename(output)
                workspace = output
            result = dict(reused=reused, discoveryExecuted=not reused if discovery_executed is None else discovery_executed,
                       materializationExecuted=not reused, toolBuildsExecuted=False,
                       reason=reason, workspace=str(workspace), sourceView=str(discovery_state / 'workspace'),
                       borrowedPayload=borrow_native)
            if remote_metadata is not None: result['remotePackages'] = remote_metadata['packageReuse']
            yield result
            if borrow_native and payload_identity(payload) != manifest['payloadSha256']:
                raise IdentityError('prepared payload changed during consumption')

        if candidate:
            generation, manifest = candidate
            options = {'protected_store': protected_store} if protected_store is not None else {}
            if incremental_sources: options['candidate_graph'] = json.loads((generation / 'payload/graph.json').read_text())
            if remote_metadata is not None:
                options['candidate_adapter'] = lambda previous, current, host: portable.rebase(remote_metadata, current, host)
            with ExitStack() as candidate_stack:
                try:
                    validation = candidate_stack.enter_context(discovery.qualified_view(source, discovery_state, entries, candidate=manifest['certificate'], **options))
                except (OSError, ValueError, KeyError, TypeError) as error:
                    if remote_metadata is None: raise
                    validation = {'unchanged': False}
                    reason = 'remote-preparation-miss: ' + str(error)
                if remote_metadata is not None and 'candidateCertificate' in validation:
                    manifest = dict(manifest, certificate=validation['candidateCertificate'])
                if validation['unchanged']:
                    if remote_metadata is not None:
                        generation = publish(state, discovery_state / 'workspace', generation / 'payload/graph.json', manifest['certificate'], request,
                            protected_store=protected_store, native_toolchain=native_toolchain, imported_payload=generation / 'payload', imported_sha256=manifest['payloadSha256'])
                        manifest = json.loads((generation / 'manifest.json').read_text())
                    with consume(generation, manifest, True, 'remote-unchanged' if remote_metadata is not None else 'unchanged') as result: yield result
                    if tool_identity(protected_store) != request['tools']: raise IdentityError('tools changed during consumption')
                    return
                if validation.get('sourceContentUpdate'):
                    generation = publish(state, discovery_state / 'workspace', discovery_state / 'output/graph.json', validation['certificate'], request, protected_store=protected_store, compile_boundary=compile_boundary, native_toolchain=native_toolchain, previous_native=(generation, manifest) if native_toolchain is not None else None)
                    manifest = json.loads((generation / 'manifest.json').read_text())
                    with consume(generation, manifest, False, 'remote-source-content-changed' if remote_metadata is not None else 'source-content-changed', discovery_executed=False) as result:
                        result['packagePayloadReused'] = native_toolchain is not None
                        yield result
                    if tool_identity(protected_store) != request['tools']: raise IdentityError('tools changed during consumption')
                    return
            if not str(reason).startswith('remote-preparation-miss:'): reason = 'discovery-inputs-changed'
        # Only qualification failures before the yield can choose fresh preparation.
        # Consumer exceptions must propagate; never retry a user's command.
        with ExitStack() as stack:
            try:
                certificate = stack.enter_context(discovery.qualified_view(source, discovery_state, entries, **({"protected_store": protected_store} if protected_store is not None else {})))
            except IdentityError as error:
                fallback_reason = str(error)
                with fresh_view(source, output, entries, environment=environment, tests=tests, compile_boundary=compile_boundary, native_toolchain=native_toolchain) as result:
                    result['reason'] = 'qualification-fallback: ' + fallback_reason
                    yield result
                return
            generation = publish(state, discovery_state / 'workspace', discovery_state / 'output/graph.json', certificate, request, protected_store=protected_store, compile_boundary=compile_boundary, native_toolchain=native_toolchain)
            manifest = json.loads((generation / 'manifest.json').read_text())
            with consume(generation, manifest, False, reason) as result: yield result
            if tool_identity(protected_store) != request['tools']: raise IdentityError('tools changed during consumption')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('workspace', 'state', 'output', 'entries'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--compile-boundary', action='store_true')
    parser.add_argument('--tests', type=Path)
    parser.add_argument('--trust-system-nix-store', action='store_true',
                        help='reuse verified system-owned Nix trees within this process; trust privileged store administration and storage integrity')
    parser.add_argument('--incremental-sources', action='store_true',
                        help='refresh qualified C# content hashes without reevaluating unchanged graph structure')
    parser.add_argument('command', nargs=argparse.REMAINDER, help='command consumed under lease, after --')
    args = parser.parse_args()
    from protected_store import ProtectedStore
    with prepared_view(args.workspace, args.state, args.output, json.loads(args.entries.read_text()),
                       tests=json.loads(args.tests.read_text()) if args.tests else None,
                       protected_store=ProtectedStore() if args.trust_system_nix_store else None,
                       incremental_sources=args.incremental_sources, compile_boundary=args.compile_boundary) as result:
        print(json.dumps(result), flush=True)
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        if command: subprocess.run(command, cwd=args.output, check=True)
