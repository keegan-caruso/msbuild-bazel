"""Measure SDK verification and show why a borrowed read-only mount is insufficient alone."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from qualify import DOTNET, ROOT, RUNNER, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='new disposable results directory')
    parser.add_argument('--sdk', required=True, type=Path, help='qualified declared SDK payload')
    parser.add_argument('--copy', action='store_true', help='measure an owned copy, including executable modes')
    args = parser.parse_args()
    base, sdk = args.directory.resolve(), args.sdk.resolve()
    assert not base.is_relative_to(sdk) and not sdk.is_relative_to(base)
    base.mkdir(parents=True, exist_ok=False)
    driver = base / 'driver'
    driver.mkdir()
    (driver / 'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        '<TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType>'
        '<ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup></Project>')
    shutil.copyfile(ROOT / 'tests/graph_build/SdkVerification.cs.txt', driver / 'Program.cs')
    build = run(DOTNET, 'build', driver / 'Probe.csproj', '-c', 'Release', '-p:UseSharedCompilation=false', '-p:NuGetAudit=false', '-warnaserror')
    (base / 'build.log').write_text(build.stdout + build.stderr)
    run(DOTNET, driver / 'bin/Release/net10.0/Probe.dll', RUNNER, sdk, base / 'hash.json',
        *([base / 'owned-sdk'] if args.copy else []))
    if os.uname().sysname == 'Linux':
        source = base / 'borrowed'
        source.mkdir()
        payload = source / 'payload'
        payload.write_bytes(b'original')
        code = '''import errno, os, sys
root = sys.argv[1]
assert os.statvfs(root).f_flag & os.ST_RDONLY
try:
    open(root + '/payload', 'wb')
except OSError as error:
    assert error.errno == errno.EROFS
else:
    raise AssertionError('Child changed the read-only payload')
print('ready', flush=True)
sys.stdin.readline()
assert open(root + '/payload', 'rb').read() == b'changed'
print('external change visible', flush=True)
'''
        child = subprocess.Popen(['/usr/bin/bwrap', '--die-with-parent', '--unshare-user', '--unshare-pid',
            '--unshare-ipc', '--unshare-uts', '--cap-drop', 'ALL', '--ro-bind', '/', '/',
            '--ro-bind', str(source), str(source), '/usr/bin/python3', '-c', code, str(source)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            ready = child.stdout.readline().strip()
            if ready != 'ready':
                out, err = child.communicate(timeout=30)
                raise AssertionError(f'Borrowed-mount control did not start: {ready} {out} {err}')
            payload.write_bytes(b'changed')
            out, err = child.communicate('\n', timeout=30)
            assert child.returncode == 0 and out.strip() == 'external change visible', (out, err)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
        (base / 'ownership.json').write_text(json.dumps({'childWritesRejected': True, 'externalMutationVisible': True,
            'scope': 'borrowed bind-mount control; deliberately bypasses Bazel input tracking; not a Bazel cache fault'}) + '\n')
    print((base / 'hash.json').read_text())
    print('PASS: stable SDK content/mode digest and selected copy/borrowed-mount controls')


if __name__ == '__main__':
    main()
