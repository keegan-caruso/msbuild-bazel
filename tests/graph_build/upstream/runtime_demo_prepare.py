"""Prepare or transfer the runtime CI demo inside an owned Linux ARM64 container."""
import argparse
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import uuid
import urllib.request

from runtime_prepare import COMMIT, SOURCE_SHA256

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BASE = Path('/demo')
AUXILIARY = ['app', 'runtime', 'suite-probe', 'suite-host', 'suite-settings-tool', 'suite-runner',
    'native', 'native_support', 'host', 'crypto', 'compression', '.package-source']


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def workspace_inputs(root):
    contract = json.loads((root / 'graph.generated.json').read_text())
    nodes = [node for project in contract['Projects'].values() for node in project['Configurations']]
    assert len(nodes) == 543 and sum(bool(n['OutputDirectories'] or n.get('OutputFiles')) for n in nodes) == 481
    assert len(json.loads((root / 'suite.json').read_text())['tests']) == 8
    wanted = set(contract['SharedInputs']) | set(contract['DefinitionDigests']) | set(contract['Restore']['Inputs'])
    wanted.update(path for node in nodes for path in node['Inputs'])
    wanted.update(['BUILD.bazel', 'MODULE.bazel', 'MODULE.bazel.lock', 'graph.generated.bzl', 'graph.generated.json',
        'nuget.lock.json', 'mappings.json', 'application.json', 'suite.json', 'runtime_test_settings.bzl'])
    for directory in AUXILIARY:
        wanted.update(str(path.relative_to(root)) for path in (root / directory).rglob('*') if path.is_file())
    for name in wanted:
        path = Path(name)
        assert not path.is_absolute() and '..' not in path.parts, name
        if path.parts[0] in AUXILIARY:
            assert not set(path.parts[1:]) & {'bin', 'obj', '.cache', '.tools'}, 'Generated auxiliary output: ' + name
        assert not (root / path).is_symlink() and (root / path).resolve().is_relative_to(root), name
        assert (root / path).is_file(), name
    # These are inputs, not a transfer of the producer's graph/Restore outputs.
    assert not any(name.startswith(('bazel-', '.nuget/', '.graph-tools/', '.tools/', '.cache/')) for name in wanted)
    return sorted(wanted)


def pack(root, archive):
    root = root.resolve()
    names = workspace_inputs(root)
    files = {name: dict(sha256=digest(root / name), mode=(root / name).stat().st_mode & 0o777) for name in names}
    manifest = json.dumps(dict(version=1, commit=COMMIT, files=files), indent=2).encode()
    with tarfile.open(archive, 'w:gz') as output:
        def normalize(member):
            member.uid = member.gid = member.mtime = 0
            member.uname = member.gname = ''
            return member
        for name in names:
            output.add(root / name, arcname='workspace/' + name, recursive=False, filter=normalize)
        member = tarfile.TarInfo('manifest.json')
        member.size, member.mode = len(manifest), 0o644
        output.addfile(member, io.BytesIO(manifest))
    return digest(archive)


def unpack(archive, expected, destination):
    assert digest(archive) == expected, 'Prepared input archive digest differs'
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive) as source:
        members, seen = source.getmembers(), set()
        for member in members:
            path = Path(member.name)
            assert not path.is_absolute() and '..' not in path.parts and member.name not in seen
            assert member.name == 'manifest.json' or member.name.startswith('workspace/')
            assert member.isfile() or member.isdir() or member.islnk(), 'Only regular inputs/internal hardlinks are allowed'
            if member.islnk():
                assert member.linkname.startswith('workspace/') and '..' not in Path(member.linkname).parts
            seen.add(member.name)
        assert hasattr(tarfile, 'data_filter'), 'Secure extraction requires the qualified Linux Python runtime'
        source.extractall(destination, members=members, filter='data')
    manifest = json.loads((destination / 'manifest.json').read_text())
    assert manifest['version'] == 1 and manifest['commit'] == COMMIT
    root = destination / 'workspace'
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
    assert actual == manifest['files'].keys(), 'Prepared input membership differs'
    for name, record in manifest['files'].items():
        path = root / name
        assert not path.is_symlink() and digest(path) == record['sha256']
        assert path.stat().st_mode & 0o777 == record['mode'], name
    assert set(workspace_inputs(root)) == actual, 'Unexpected files in the input checkpoint'
    module = root / 'MODULE.bazel'
    text, count = re.subn(r'local_path_override\(module_name="rules_msbuild",path="[^"]+"\)',
        'local_path_override(module_name="rules_msbuild",path=' + json.dumps(str(ROOT)) + ')', module.read_text())
    assert count == 1
    module.write_text(text)
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['producer', 'consumer', 'pack'])
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    if args.mode == 'pack':
        assert args.workspace and args.archive and not args.archive.exists()
        print(pack(args.workspace, args.archive), flush=True)
        return
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    setup_lock = (BASE / (args.mode + '.lock')).open('a+')
    fcntl.flock(setup_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    config = json.loads((BASE / 'config.json').read_text())
    release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    assert release['ID'].strip('"') == 'ubuntu' and release['VERSION_ID'].strip('"') == '22.04', 'Use the qualified Ubuntu 22.04 boundary'
    if args.mode == 'producer' and not config.get('preparedSha256'):
        assert all(shutil.which(name) for name in ['clang-14', 'cmake', 'ninja', 'pkg-config', 'bwrap']), 'Native tools missing from supplied image'
    os.environ.update(RULES_MSBUILD_DOTNET_ROOT=str(ROOT / '.tools/dotnet'),
        RULES_MSBUILD_BAZELISK=str(ROOT / '.tools/bin/bazelisk'), RULES_MSBUILD_BAZEL=str(ROOT / 'scripts/bazel-launcher.sh'),
        RULES_MSBUILD_TEST_REPOSITORY_CACHE=str(BASE / 'repository-cache'), USE_BAZEL_VERSION='9.3.0')
    progress = BASE / (args.mode + '-progress.json')
    state = json.loads(progress.read_text()) if progress.exists() else dict(identity=config, completed=[])
    assert state['identity'] == config, 'Setup inputs changed; use a fresh setup directory'
    (BASE / 'evidence').mkdir(exist_ok=True)

    def step(name, command, owned=None):
        if name in state['completed']:
            return
        free = os.statvfs('/host')
        assert free.f_bavail * free.f_frsize >= 12 * 1024**3, 'At least 12 GiB physical host headroom required'
        if owned and owned.exists():
            assert owned.is_relative_to(BASE / 'preparation') or owned in [BASE / 'seed-bazel', BASE / 'consumer-bootstrap']
            old_base = owned if owned in [BASE / 'seed-bazel', BASE / 'consumer-bootstrap'] else owned / 'sync-bazel'
            if old_base.exists():
                subprocess.run([str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(old_base), 'shutdown'],
                    cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            shutil.rmtree(owned)
        with (BASE / 'evidence' / (name + '-' + uuid.uuid4().hex[:8] + '.log')).open('w') as log:
            if callable(command):
                command(log)
            else:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        state['completed'].append(name)
        progress.write_text(json.dumps(state, indent=2) + '\n')
        subprocess.run(['fstrim', '/'], check=True, capture_output=True)
        print('PASS: ' + name, flush=True)

    step('tools', ['bash', str(ROOT / 'scripts/setup.sh'), '--toolchain-only'])
    probe = b'rules-msbuild-runtime-demo-cache-probe'
    url = config['cacheUrl'].rstrip('/') + '/cas/' + hashlib.sha256(probe).hexdigest()
    with urllib.request.urlopen(urllib.request.Request(url, data=probe, method='PUT'), timeout=15) as response:
        assert response.status in [200, 201, 204]
    with urllib.request.urlopen(url, timeout=15) as response:
        assert response.read() == probe, 'Cache read/write preflight failed'
    subprocess.run(['bwrap', '--unshare-all', '--ro-bind', '/', '/', '--proc', '/proc', '--dev', '/dev', '/bin/true'], check=True)
    if args.mode == 'consumer':
        if 'unpack' not in state['completed']:
            if (BASE / 'consumer').exists():
                shutil.rmtree(BASE / 'consumer')
            unpack(Path('/host/inputs.tar.gz'), config['inputsSha256'], BASE / 'consumer')
            shutil.copyfile('/host/seed.json', BASE / 'seed.json')
            state['completed'].append('unpack')
            progress.write_text(json.dumps(state, indent=2) + '\n')
        bootstrap = BASE / 'consumer-bootstrap'
        command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--nosystem_rc', '--nohome_rc', '--noworkspace_rc', '--output_base=' + str(bootstrap)]
        def acquire(log):
            execution = BASE / 'evidence/acquisition.execution.json'
            try:
                subprocess.run(command + ['build', '//:packages', '//:graph_runner', '--jobs=1', '--disk_cache=',
                    '--remote_cache=' + config['cacheUrl'], '--remote_cache_async=false', '--remote_download_outputs=all',
                    '--repository_cache=' + str(BASE / 'repository-cache'), '--lockfile_mode=error', '--execution_log_json_file=' + str(execution)],
                    cwd=BASE / 'consumer/workspace', stdout=log, stderr=subprocess.STDOUT, check=True)
                from runtime_recovered_tests import graph_actions
                assert not graph_actions(execution, mnemonics=('MSBuildGraph', 'MSBuildGraphRestore', 'RuntimeNative')), 'Acquisition must not build the managed/native graph'
            finally:
                subprocess.run(command + ['shutdown'], cwd=BASE / 'consumer/workspace',
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        step('acquisition', acquire, owned=bootstrap)
        if bootstrap.exists():
            shutil.rmtree(bootstrap)
            subprocess.run(['fstrim', '/'], check=True, capture_output=True)
        return

    preparation = BASE / 'preparation'
    preparation.mkdir(exist_ok=True)
    if config.get('preparedSha256'):
        imported = preparation / 'imported'
        if 'import' not in state['completed']:
            if imported.exists():
                shutil.rmtree(imported)
            unpack(Path('/host/prepared.tar.gz'), config['preparedSha256'], imported)
            state['completed'].append('import')
            progress.write_text(json.dumps(state, indent=2) + '\n')
        workspace = imported / 'workspace'
    else:
        source = BASE / 'runtime.tar.gz'
        if not source.exists():
            subprocess.run(['curl', '--fail', '--location', '--retry', '3', '--output', str(source) + '.partial',
                'https://codeload.github.com/dotnet/runtime/tar.gz/' + COMMIT], check=True)
            assert digest(Path(str(source) + '.partial')) == SOURCE_SHA256
            Path(str(source) + '.partial').rename(source)
        assert digest(source) == SOURCE_SHA256
        managed, native = preparation / 'managed', preparation / 'native'
        step('managed', [sys.executable, str(HERE / 'runtime_downloaded_prepare.py'), str(source), str(managed),
            '--slice=runtime-suites', '--evaluation-reuse', '--evaluation-cache-mb=1024'], owned=managed)
        native.mkdir(exist_ok=True)
        step('native', [sys.executable, str(ROOT / 'tests/runtime/native_prepare.py'), str(source), str(native), '--ninja', '--jobs=4'], owned=native / 'native')
        for component, name in [('support', 'native_support'), ('host', 'host'), ('crypto', 'crypto'), ('compression', 'compression')]:
            step('native-' + component, [sys.executable, str(ROOT / 'tests/runtime/native_component_prepare.py'),
                str(native / 'native'), str(native / name), component, '--ninja', '--jobs=4'], owned=native / name)
        workspace = preparation / 'workspace'
        runner = BASE / 'vstest.nupkg'
        if not runner.exists():
            subprocess.run(['curl', '--fail', '--location', '--retry', '3', '--output', str(runner) + '.partial',
                'https://api.nuget.org/v3-flatcontainer/microsoft.testplatform.cli/17.14.1/microsoft.testplatform.cli.17.14.1.nupkg'], check=True)
            assert digest(Path(str(runner) + '.partial')) == '3aabba2641a165f8274fbad94ed1c4e2a004877d37b2ddfab89962487f3dceab'
            Path(str(runner) + '.partial').rename(runner)
        def assemble(log):
            shutil.copytree(managed / 'workspace', workspace)
            for command in [
                [sys.executable, str(HERE / 'runtime_application.py'), str(workspace), str(native), '--include-private-frameworks'],
                [sys.executable, str(HERE / 'runtime_suite.py'), str(workspace), str(runner),
                    '--slice=pipelines', '--slice=collections', '--slice=threading', '--slice=filesystem', '--slice=sockets']]:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        step('workspace', assemble, owned=workspace)
    if 'seed' not in state['completed']:
        seed_results = BASE / 'evidence' / ('seed-' + uuid.uuid4().hex[:8])
        def seed(log):
            subprocess.run([sys.executable, str(HERE / 'runtime_recovered_tests.py'), str(workspace), str(seed_results),
                '--phase=producer', '--output-base=' + str(BASE / 'seed-bazel'), '--cache-url=' + config['cacheUrl'],
                '--host-space-path=/host'], stdout=log, stderr=subprocess.STDOUT, check=True)
            shutil.copyfile(seed_results / 'seed.json', BASE / 'seed.json')
        step('seed', seed, owned=BASE / 'seed-bazel')
    if not (BASE / 'inputs.tar.gz').exists():
        pack(workspace, BASE / 'inputs.tar.gz.partial')
        (BASE / 'inputs.tar.gz.partial').rename(BASE / 'inputs.tar.gz')
    if (BASE / 'transfer.json').exists():
        assert json.loads((BASE / 'transfer.json').read_text())['inputsSha256'] == digest(BASE / 'inputs.tar.gz')
    (BASE / 'transfer.json').write_text(json.dumps(dict(inputsSha256=digest(BASE / 'inputs.tar.gz')))+ '\n')
    # Keep the verified input checkpoint and evidence, not another expanded copy
    # of the full source, qualification outputs and native tool filesystem.
    managed_reports = preparation / 'managed'
    if managed_reports.exists():
        for path in [*managed_reports.glob('*.log'), managed_reports / 'summary.json']:
            if path.is_file():
                shutil.copyfile(path, BASE / 'evidence' / ('preparation-' + path.name))
    if preparation.exists():
        shutil.rmtree(preparation)
    if (BASE / 'seed-bazel').exists():
        shutil.rmtree(BASE / 'seed-bazel')
        subprocess.run(['fstrim', '/'], check=True, capture_output=True)
    for directory in [ROOT / '.tools', ROOT / '.cache', BASE / 'repository-cache', Path('/root/.cache/bazel')]:
        if directory.exists():
            shutil.rmtree(directory)
    subprocess.run(['fstrim', '/'], check=True, capture_output=True)


if __name__ == '__main__':
    main()
