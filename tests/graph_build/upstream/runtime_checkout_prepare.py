"""Prepare the connected runtime/JIT qualification from pinned source and tools.

No existing qualified runtime workspace, products archive or generated headers are
inputs. Native tools remain an explicitly hashed Linux ARM64 filesystem bundle;
this does not bootstrap the compiler distribution or the entire runtime repository.
"""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess

from runtime_prepare import COMMIT, SOURCE_SHA256

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_archive', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--toolchain', type=Path, required=True)
    parser.add_argument('--toolchain-sha256', required=True)
    parser.add_argument('--sandbox', type=Path, required=True)
    parser.add_argument('--sandbox-sha256', required=True)
    parser.add_argument('--host-space-path', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert digest(args.source_archive) == SOURCE_SHA256
    assert digest(args.toolchain) == args.toolchain_sha256 and digest(args.sandbox) == args.sandbox_sha256
    base = args.output.resolve()
    base.mkdir(parents=True, exist_ok=args.resume)
    identity = dict(commit=COMMIT, sourceSha256=SOURCE_SHA256, toolchainSha256=args.toolchain_sha256,
        sandboxSha256=args.sandbox_sha256, platform='linux-arm64', sdk='10.0.400', jobs=4, generator='Ninja')
    progress = base / 'preparation.json'
    if progress.exists():
        state = json.loads(progress.read_text())
        assert state['inputs'] == identity, 'Preparation inputs changed; use a fresh output'
    else:
        state = dict(inputs=identity, completed=[])
        progress.write_text(json.dumps(state, indent=2) + '\n')
    managed, native, jit = base / 'managed', base / 'native', base / 'jit'

    def run(name, command, owned=None):
        if name in state['completed']:
            return
        if owned and owned.exists():
            assert args.resume and owned in [managed, native / 'native', *[native / name for name in ['native_support', 'host', 'crypto', 'compression']]], 'Use --resume for interrupted preparation'
            shutil.rmtree(owned)
        stat = os.statvfs(args.host_space_path)
        assert stat.f_bavail * stat.f_frsize >= 12 * 1024**3, 'Insufficient physical host disk headroom'
        with (base / (name + '.log')).open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        state['completed'].append(name)
        progress.write_text(json.dumps(state, indent=2) + '\n')
        subprocess.run(['fstrim', '/'], capture_output=True, check=True)
        print('PASS: ' + name, flush=True)

    run('managed-sync', ['python3', str(HERE / 'runtime_downloaded_prepare.py'), str(args.source_archive), str(managed),
        '--slice=runtime-suites', '--evaluation-reuse', '--evaluation-cache-mb=1024'] +
        (['--resume'] if (managed / 'source/graph.generated.json').exists() and not (managed / 'workspace').exists() else []),
        owned=managed if managed.exists() and (not (managed / 'source/graph.generated.json').exists() or (managed / 'workspace').exists()) else None)
    native.mkdir(exist_ok=True)
    run('native-inputs', ['python3', str(ROOT / 'tests/runtime/native_prepare.py'), str(args.source_archive), str(native),
        '--jobs=4', '--ninja', '--toolchain-archive=' + str(args.toolchain.resolve()), '--toolchain-sha256=' + args.toolchain_sha256,
        '--sandbox=' + str(args.sandbox.resolve()), '--sandbox-sha256=' + args.sandbox_sha256], owned=native / 'native')
    for component, directory in [('support', 'native_support'), ('host', 'host'), ('crypto', 'crypto'), ('compression', 'compression')]:
        run('native-' + component, ['python3', str(ROOT / 'tests/runtime/native_component_prepare.py'),
            str(native / 'native'), str(native / directory), component, '--jobs=4', '--ninja'], owned=native / directory)
    run('runtime-declarations', ['python3', str(HERE / 'runtime_application.py'), str(managed / 'workspace'), str(native)])
    run('jit-sync', ['python3', str(HERE / 'runtime_jit_public_prepare.py'), str(args.source_archive), str(jit),
        '--source-producer=' + str(managed / 'workspace'), '--compiler-references',
        '--cases=' + str(HERE / 'runtime_jit_cases.json'), '--host-space-path=' + str(args.host_space_path)] + (['--resume'] if jit.exists() else []))
    print(str(jit / 'workspace'), flush=True)


if __name__ == '__main__':
    main()
