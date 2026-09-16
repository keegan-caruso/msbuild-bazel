"""Lease-bound local preparation reuse for the qualified RUL-5 discovery slice.

Use prepared_view through the end of consumption. Persisted JSON is never a lease.
The cache is owned local state, not an authenticated or remote artifact store.
"""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
import sys
import subprocess
import uuid

import discovery_contract as discovery
import prepare_graph
from preparation_identity import IdentityError, digest, tree_snapshot

ROOT = prepare_graph.ROOT
POLICY = 'leased-preparation-v1'


def controller():
    paths = [*sorted((ROOT / 'tools').glob('*.py')),
             *sorted((ROOT / 'tools').glob('*.json')),
             *sorted((ROOT / 'tools').glob('*.props'))]
    return digest({str(p.relative_to(ROOT)): p.read_bytes().hex() for p in paths})


CONTROLLER = controller()


def tool_identity():
    if controller() != CONTROLLER:
        raise IdentityError('preparation controller changed; start a fresh process')
    roots = [ROOT / 'bazel', *[ROOT / 'tools' / name for name in
             ('GraphExport', 'EvaluationProbe', 'ReplayPlugin', 'ActionRunner')]]
    return dict(controller=CONTROLLER, trees={str(p): tree_snapshot(p)['sha256'] for p in roots},
                sdk=str(prepare_graph.DOTNET_ROOT), python=dict(version=sys.version, executable=sys.executable,
                    executableSha256=digest(Path(sys.executable).read_bytes().hex())))


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


def publish(state, workspace, graph_path, certificate, request, *, protected_store=None):
    """Flush a complete generation before atomically switching the commit pointer."""
    generations = state / 'generations'
    generations.mkdir(exist_ok=True)
    name = uuid.uuid4().hex
    pending = generations / ('.pending-' + name)
    pending.mkdir()
    try:
        prepare_graph._prepare(workspace, graph_path, pending / 'payload', _leased=True)
        if tool_identity() != request['tools']:
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
def fresh_view(source, output, entries, *, environment=None, tests=None):
    """Existing uncached behavior for operations outside the qualified slice."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix='fresh-export-', dir=output.parent) as directory:
        temporary = Path(directory)
        dotnet = prepare_graph.DOTNET_ROOT / 'dotnet'
        subprocess.run([str(dotnet), 'build', str(ROOT / 'tools/GraphExport'), '-c', 'Release', '--nologo'],
                       cwd=ROOT, env=environment, check=True)
        graph = temporary / 'graph.json'
        request = temporary / 'request.json'
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(source),
            dotnetRoot=str(prepare_graph.DOTNET_ROOT), sdkVersion='10.0.400',
            packageRoot=str(source / '.nuget/packages'), entryPoints=entries, output=str(graph))))
        subprocess.run([str(dotnet), str(ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll'),
                        '--request', str(request)], cwd=source, env=environment, check=True)
        prepare_graph.prepare(source, graph, output, environment=environment, tests=tests)
        yield dict(reused=False, discoveryExecuted=True, materializationExecuted=True,
                   toolBuildsExecuted=True, reason='unsupported-request', workspace=str(output))


@contextmanager
def prepared_view(source, state, output, entries, *, environment=None, tests=None, protected_store=None, incremental_sources=False):
    """Materialize a private consumer copy and retain both leases until it finishes.

    Tools must be prebuilt for reuse. Tests and custom environments take the fresh
    path. A cache hit skips evaluation, export, tool builds and materialization;
    input sealing/hashing, artifact verification and consumer copying still run.
    """
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
        with fresh_view(source, output, entries, environment=environment, tests=tests) as result:
            yield result
        return
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'lease').open('a') as lease:
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
                       operation='prepare_graph', tools=tool_identity())
        if protected_store is not None: request['storePolicy'] = 'trusted-system-nix-session-v1'
        if incremental_sources: request['sourcePolicy'] = 'compile-content-only-v1'
        candidate, reason = read_candidate(state, request)
        discovery_state = state / 'discovery'

        def consume(generation, manifest, reused, reason, discovery_executed=None):
            # Atomic publication of the caller's copy; builds never mutate cached bytes.
            import tempfile
            with tempfile.TemporaryDirectory(prefix='.consumer-', dir=output.parent) as directory:
                staged = Path(directory) / 'workspace'
                shutil.copytree(generation / 'payload', staged)
                if payload_identity(staged) != manifest['payloadSha256']:
                    raise IdentityError('prepared payload changed during copy')
                if output.exists(): raise FileExistsError(output)
                staged.rename(output)
            return dict(reused=reused, discoveryExecuted=not reused if discovery_executed is None else discovery_executed,
                        materializationExecuted=not reused, toolBuildsExecuted=False,
                        reason=reason, workspace=str(output))

        if candidate:
            generation, manifest = candidate
            options = {'protected_store': protected_store} if protected_store is not None else {}
            if incremental_sources: options['candidate_graph'] = json.loads((generation / 'payload/graph.json').read_text())
            with discovery.qualified_view(source, discovery_state, entries, candidate=manifest['certificate'], **options) as validation:
                if validation['unchanged']:
                    yield consume(generation, manifest, True, 'unchanged')
                    if tool_identity() != request['tools']: raise IdentityError('tools changed during consumption')
                    return
                if validation.get('sourceContentUpdate'):
                    generation = publish(state, discovery_state / 'workspace', discovery_state / 'output/graph.json', validation['certificate'], request, protected_store=protected_store)
                    manifest = json.loads((generation / 'manifest.json').read_text())
                    yield consume(generation, manifest, False, 'source-content-changed', discovery_executed=False)
                    if tool_identity() != request['tools']: raise IdentityError('tools changed during consumption')
                    return
            reason = 'discovery-inputs-changed'
        # Only qualification failures before the yield can choose fresh preparation.
        # Consumer exceptions must propagate; never retry a user's command.
        from contextlib import ExitStack
        with ExitStack() as stack:
            try:
                certificate = stack.enter_context(discovery.qualified_view(source, discovery_state, entries, **({"protected_store": protected_store} if protected_store is not None else {})))
            except IdentityError:
                with fresh_view(source, output, entries, environment=environment, tests=tests) as result:
                    yield result
                return
            generation = publish(state, discovery_state / 'workspace', discovery_state / 'output/graph.json', certificate, request, protected_store=protected_store)
            manifest = json.loads((generation / 'manifest.json').read_text())
            yield consume(generation, manifest, False, reason)
            if tool_identity() != request['tools']: raise IdentityError('tools changed during consumption')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('workspace', 'state', 'output', 'entries'):
        parser.add_argument('--' + name, required=True, type=Path)
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
                       incremental_sources=args.incremental_sources) as result:
        print(json.dumps(result), flush=True)
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        if command: subprocess.run(command, cwd=args.output, check=True)
