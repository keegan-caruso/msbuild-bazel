"""Qualify a VMR SDK's runtime as an SDK-free, explicitly selected product.

Run on Linux ARM64. The input is the extracted declared producer archive, not
an installed host SDK. Evidence is written to a fresh directory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--vmr-revision', required=True)
    parser.add_argument('--sdk-version', default='11.0.100')
    parser.add_argument('--runtime-version', default='11.0.0')
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'aarch64':
        parser.error('Run on native Linux ARM64')
    sdk = args.sdk.resolve()
    folder = args.directory.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'global.json').write_text(json.dumps(dict(sdk=dict(
        version=args.sdk_version, rollForward='disable', allowPrerelease=False))) + '\n')
    report = dict(vmrRevision=args.vmr_revision, sdk=str(sdk),
                  sdkVersion=args.sdk_version, runtimeVersion=args.runtime_version,
                  stamps={}, nativeFiles={}, commands=[])
    env = dict(os.environ, DOTNET_ROOT=str(sdk), DOTNET_MULTILEVEL_LOOKUP='0',
               DOTNET_ROLL_FORWARD='Disable', DOTNET_CLI_HOME=str(folder / 'home'),
               DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1', DOTNET_NOLOGO='1',
               NUGET_PACKAGES=str(folder / 'packages'),
               NUGET_HTTP_CACHE_PATH=str(folder / 'http-cache'))
    def save():
        (folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    save()

    def run(command):
        result = subprocess.run([str(x) for x in command], env=env, cwd=folder, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        report['commands'].append(dict(command=[str(x) for x in command],
                                       exitCode=result.returncode, output=result.stdout))
        save()
        if result.returncode:
            raise RuntimeError(result.stdout)
        return result.stdout
    for relative, version in [('sdk/' + args.sdk_version, args.sdk_version),
                              ('shared/Microsoft.NETCore.App/' + args.runtime_version, args.runtime_version),
                              ('shared/Microsoft.AspNetCore.App/' + args.runtime_version, args.runtime_version)]:
        stamp = (sdk / relative / '.version').read_text().splitlines()
        if stamp[:2] != [args.vmr_revision, version]:
            raise ValueError('Unexpected provenance: ' + relative + ': ' + repr(stamp))
        report['stamps'][relative] = stamp
        save()
    runtime = folder / 'runtime'
    runtime.mkdir()
    shutil.copy2(sdk / 'dotnet', runtime / 'dotnet')
    for name in ['host', 'shared']:
        shutil.copytree(sdk / name, runtime / name, symlinks=True)
    for relative in ['dotnet', 'host/fxr/' + args.runtime_version + '/libhostfxr.so',
                     'shared/Microsoft.NETCore.App/' + args.runtime_version + '/libcoreclr.so',
                     'shared/Microsoft.NETCore.App/' + args.runtime_version + '/libhostpolicy.so']:
        data = (runtime / relative).read_bytes()
        if data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', data, 18)[0] != 183:
            raise ValueError('Expected ELF64 little-endian AArch64: ' + relative)
        report['nativeFiles'][relative] = hashlib.sha256(data).hexdigest()
    if run([sdk / 'dotnet', '--version']).strip() != args.sdk_version:
        raise ValueError('Produced SDK selected an unexpected version')
    archive = folder / 'runtime.tar.gz'
    run(['tar', '--sort=name', '--mtime=@0', '--owner=0', '--group=0', '--numeric-owner',
         '-czf', archive, '-C', runtime, '.'])
    report['runtimeArchive'] = dict(path=str(archive), sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                                   bytes=archive.stat().st_size)
    save()
    runtime = folder / 'execution-runtime'
    runtime.mkdir()
    run(['tar', '-xzf', archive, '-C', runtime])
    for relative, digest in report['nativeFiles'].items():
        if hashlib.sha256((runtime / relative).read_bytes()).hexdigest() != digest:
            raise ValueError('Runtime archive changed native payload: ' + relative)
    app = folder / 'app'
    app.mkdir()
    tfm = 'net' + '.'.join(args.runtime_version.split('.')[:2])
    (app / 'NuGet.Config').write_text('<configuration><packageSources><clear /></packageSources></configuration>')
    (app / 'app.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>' + tfm + '</TargetFramework><OutputType>Exe</OutputType><UseAppHost>false</UseAppHost></PropertyGroup></Project>')
    (app / 'Program.cs').write_text('''using System;
using System.Runtime.InteropServices;
Console.WriteLine("VERSION=" + Environment.Version);
Console.WriteLine("FRAMEWORK=" + RuntimeInformation.FrameworkDescription);
Console.WriteLine("ARCH=" + RuntimeInformation.ProcessArchitecture);
Console.WriteLine("PROCESS=" + Environment.ProcessPath);
Console.WriteLine("CORELIB=" + typeof(object).Assembly.Location);
Console.WriteLine("RUNTIME=" + RuntimeEnvironment.GetRuntimeDirectory());
''')
    run([sdk / 'dotnet', 'build', app / 'app.csproj', '-c', 'Release', '-o', app / 'out', '--nologo', '--configfile', app / 'NuGet.Config'])
    env['DOTNET_ROOT'] = str(runtime)
    if run([runtime / 'dotnet', '--list-sdks']).strip():
        raise ValueError('Runtime-only layout contains SDKs')
    output = run([runtime / 'dotnet', '--fx-version', args.runtime_version, app / 'out/app.dll'])
    expected = runtime / 'shared/Microsoft.NETCore.App' / args.runtime_version
    for line in ['VERSION=' + args.runtime_version, 'ARCH=Arm64',
                 'PROCESS=' + str(runtime / 'dotnet'),
                 'CORELIB=' + str(expected / 'System.Private.CoreLib.dll'),
                 'RUNTIME=' + str(expected) + '/']:
        if line not in output.splitlines():
            raise ValueError('Missing runtime identity: ' + line)
    report['result'] = 'PASS'
    save()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
