"""Measure production package hashing, path resolution and mutable restore-key work."""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
import shutil
import subprocess

from qualify import DOTNET, ROOT, RUNNER, run


def immutable_control(base):
    if sys.platform != 'linux':
        return {'scope': 'kernel byte-immutability probe only', 'supported': False, 'reason': 'Linux required'}
    # This probes only an owned disposable file; it does not change filesystem features.
    import errno
    import fcntl
    import struct
    payload = base / 'immutable-control'
    payload.write_bytes(b'original')
    descriptor = os.open(payload, os.O_RDONLY)
    try:
        try:
            # FS_IOC_ENABLE_VERITY: fsverity_enable_arg v1, SHA256, no salt/signature.
            fcntl.ioctl(descriptor, 0x40806685, struct.pack('IIIIQIIQ11Q', 1, 1, 0, 0, 0, 0, 0, 0, *([0] * 11)))
        except OSError as error:
            if error.errno not in [errno.ENOTSUP, errno.ENOTTY, errno.ENOSYS, errno.EPERM]:
                raise
            return {'scope': 'kernel byte-immutability probe only', 'supported': False,
                'reason': errno.errorcode[error.errno]}
        try:
            payload.write_bytes(b'modified')
        except OSError as error:
            assert error.errno == errno.EPERM, error
        else:
            raise AssertionError('Kernel-verified payload remained writable')
        return {'scope': 'kernel byte-immutability probe only; no worker/path reuse qualification',
            'supported': True, 'writesRejected': True}
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='new disposable results directory')
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--contract', required=True, type=Path)
    parser.add_argument('--sdk', required=True, type=Path)
    parser.add_argument('--prepared', required=True, type=Path, help='prepared directory containing manifest.json')
    parser.add_argument('--runner', type=Path, default=RUNNER)
    parser.add_argument('--compare-runner', type=Path, action='append', default=[], help='additional --apply candidates; rotate their order each sample')
    parser.add_argument('--samples', type=int, default=5, help='fresh probe process per sample')
    parser.add_argument('--materialize', action='store_true', help='measure private copy/reuse and child integrity controls')
    parser.add_argument('--apply', action='store_true', help='measure full Apply in a read-only Linux child; excludes setup/evaluation')
    parser.add_argument('--profile', action='store_true', help='opt-in operation counters for --apply; do not score these rows')
    parser.add_argument('--cold', action='store_true', help='drop guest page caches before each --apply sample; requires disposable Linux VM/root')
    args = parser.parse_args()
    assert args.samples > 0
    assert args.apply or not (args.profile or args.cold or args.compare_runner)
    base = args.directory.resolve()
    for source in [args.workspace, args.sdk, args.prepared]:
        assert not base.is_relative_to(source.resolve()) and not source.resolve().is_relative_to(base)
    base.mkdir(mode=0o700, parents=True, exist_ok=False)
    driver = base / 'driver'
    driver.mkdir()
    (driver / 'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        '<TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType>'
        '<ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup></Project>')
    shutil.copyfile(ROOT / 'tests/graph_build/PackageVerification.cs.txt', driver / 'Program.cs')
    build = run(DOTNET, 'build', driver / 'Probe.csproj', '-c', 'Release',
        '-p:UseSharedCompilation=false', '-p:NuGetAudit=false', '-warnaserror')
    (base / 'build.log').write_text(build.stdout + build.stderr)
    if args.apply:
        assert sys.platform == 'linux' and not args.materialize
        contract = json.loads(args.contract.read_text())
        workspace, prepared = base / 'workspace', base / 'artifact/prepared'
        workspace.mkdir()
        # Stage the authored Restore inputs only; no earlier build outputs.
        inputs = set(contract['Restore']['Inputs'])
        inputs.update(str(path.relative_to(args.workspace)) for path in (args.workspace / '.package-source').glob('*.nupkg'))
        inputs.update(str(path.relative_to(args.workspace)) for path in (args.workspace / '.graph-tools').rglob('*') if path.is_file())
        for relative in inputs:
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(args.workspace / relative, target)
            shutil.copymode(args.workspace / relative, target)
        shutil.copytree(args.prepared, prepared)
        records = json.loads((prepared / 'manifest.json').read_text())['Files']
        for relative, record in records.items():
            (prepared / relative).chmod(record['Mode'])
        (prepared / 'manifest.json').chmod(0o644)
        (workspace / '.nuget').mkdir()
        runners = [args.runner.resolve(), *(path.resolve() for path in args.compare_runner)]
        rows = []
        for sample in range(args.samples):
            for index in range(len(runners)):
                candidate = (sample + index) % len(runners)
                runner = runners[candidate]
                probe = [str(DOTNET), str(driver / 'bin/Release/net10.0/Probe.dll'), str(runner),
                         str(workspace), str(args.contract.resolve()), str(args.sdk.resolve()), str(prepared)]
                report = base / f'sample-{sample}-runner-{candidate}.json'
                subprocess.run(['bwrap', '--die-with-parent', '--bind', '/', '/',
                    '--ro-bind', str(prepared / '.nuget'), str(prepared / '.nuget'),
                    '--ro-bind', str(prepared / '.nuget'), str(workspace / '.nuget'), '--',
                    *probe, str(report), '--rekey'], check=True)
                if args.cold:
                    os.sync()
                    Path('/proc/sys/vm/drop_caches').write_text('3\n')
                subprocess.run(['bwrap', '--die-with-parent', '--bind', '/', '/', '--ro-bind', str(prepared), str(prepared),
                    '--ro-bind', str(prepared / '.nuget'), str(workspace / '.nuget'), '--',
                    *probe, str(report), '--apply', *(['profile'] if args.profile else [])], check=True)
                rows.append(dict(json.loads(report.read_text()), sample=sample, candidate=candidate,
                    runnerSha256=hashlib.sha256(runner.read_bytes()).hexdigest()))
                for relative in records:
                    if not relative.startswith('.nuget/'):
                        (workspace / relative).unlink()
        (base / 'report.json').write_text(json.dumps(dict(rows=rows, profiled=args.profile, cold=args.cold,
            freshProcessPerSample=True, runnerSha256=hashlib.sha256(args.runner.read_bytes()).hexdigest()), indent=2) + '\n')
        shutil.rmtree(prepared.parent)
        shutil.rmtree(workspace)
        print((base / 'report.json').read_text())
        return
    rows = []
    materialization = []
    for sample in range(args.samples):
        report = base / f'sample-{sample}.json'
        run(DOTNET, driver / 'bin/Release/net10.0/Probe.dll', args.runner.resolve(), args.workspace.resolve(),
            args.contract.resolve(), args.sdk.resolve(), args.prepared.resolve(), report,
            *([base / f'broker-copy-{sample}'] if args.materialize else []))
        data = json.loads(report.read_text())
        rows.extend(dict(row, sample=sample) for row in data['rows'])
        if data['materialization']:
            materialization.append(dict(data['materialization'], sample=sample))
            shutil.rmtree(base / f'broker-copy-{sample}')
    data.update(rows=rows, materialization=materialization, freshProcessPerSample=True,
        immutableControl=immutable_control(base),
        runnerSha256=hashlib.sha256(args.runner.read_bytes()).hexdigest(),
        contractSha256=hashlib.sha256(args.contract.read_bytes()).hexdigest())
    (base / 'report.json').write_text(json.dumps(data, indent=2) + '\n')
    print((base / 'report.json').read_text())
    print('PASS: all package and restore-output digests match the manifest')


if __name__ == '__main__':
    main()
