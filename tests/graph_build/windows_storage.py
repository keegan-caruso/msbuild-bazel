"""Native Windows storage, alias rejection and killed-owner recovery controls."""

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from xml.sax.saxutils import quoteattr

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='Fresh disposable evidence directory')
    parser.add_argument('--build-only', action='store_true')
    args = parser.parse_args()
    if os.name != 'nt' and not args.build_only:
        raise RuntimeError('Native Windows is required; --build-only verifies compilation only')
    root = args.directory.resolve()
    root.mkdir()
    sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
    assert (sdk / 'sdk/11.0.100/.version').is_file(), 'Expected pinned SDK 11.0.100'
    dotnet = sdk / ('dotnet.exe' if os.name == 'nt' else 'dotnet')
    sources = [ROOT / 'tools/GraphBuild' / (name + '.cs') for name in
               ['WindowsProcess', 'WindowsDrive', 'WindowsStorage', 'WindowsSandboxLease', 'WorkerProcess', 'WorkerOutput']]
    sources += [ROOT / 'tools/NoLinkTree.cs', ROOT / 'tools/RelativePathComponents.cs']
    (root / 'Program.cs').write_bytes((ROOT / 'tests/graph_build/WindowsStorage.cs.txt').read_bytes())
    items = '<Compile Include="Program.cs" />' + ''.join('<Compile Include=' + quoteattr(str(path)) + ' />' for path in sources)
    (root / 'Harness.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
        '<TargetFramework>net11.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
        '<EnableDefaultCompileItems>false</EnableDefaultCompileItems><UseSharedCompilation>false</UseSharedCompilation>'
        '<NuGetAudit>false</NuGetAudit></PropertyGroup><ItemGroup>' + items + '</ItemGroup></Project>', encoding='utf-8')
    config = root / 'NuGet.Config'
    config.write_text('<configuration><packageSources><clear /></packageSources></configuration>', encoding='utf-8')
    environment = dict(os.environ, DOTNET_ROOT=str(sdk), DOTNET_CLI_USE_MSBUILD_SERVER='false',
                       MSBUILDUSESERVER='0', MSBUILDDISABLENODEREUSE='1', DOTNET_CLI_TELEMETRY_OPTOUT='1',
                       DOTNET_ADD_GLOBAL_TOOLS_TO_PATH='false', DOTNET_GENERATE_ASPNET_CERTIFICATE='false',
                       DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE='true')
    home = root / 'profile'
    for path in [home, home / 'appdata', home / 'localappdata']:
        path.mkdir(parents=True, exist_ok=True)
    environment.update(HOME=str(home), DOTNET_CLI_HOME=str(home))
    if os.name == 'nt':
        environment.update(USERPROFILE=str(home), APPDATA=str(home / 'appdata'), LOCALAPPDATA=str(home / 'localappdata'))

    def run(arguments, name, timeout):
        with (root / (name + '.log')).open('wb') as output, (root / (name + '.err')).open('wb') as error:
            result = subprocess.run([str(value) for value in arguments], env=environment,
                                    stdout=output, stderr=error, timeout=timeout)
        assert result.returncode == 0, (root / (name + '.log')).read_text() + (root / (name + '.err')).read_text()

    run([dotnet, 'build', root / 'Harness.csproj', '-c', 'Release', '--disable-build-servers',
         '-warnaserror', '-p:RestoreConfigFile=' + str(config)], 'build', 120)
    recorded = sources + [ROOT / 'tests/graph_build/WindowsStorage.cs.txt', Path(__file__).resolve()]
    receipt = {'buildOnly': args.build_only, 'sources': {path.relative_to(ROOT).as_posix():
               hashlib.sha256(path.read_bytes()).hexdigest() for path in recorded}}
    if args.build_only:
        (root / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print('PASS: linked storage controls compile; native execution not run')
        return
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.QueryDosDeviceW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    kernel.QueryDosDeviceW.restype = ctypes.c_uint

    def query(drive):
        buffer = ctypes.create_unicode_buffer(32768)
        count = kernel.QueryDosDeviceW(drive, buffer, len(buffer))
        if not count:
            if ctypes.get_last_error() == 2:
                return []
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer[:count].rstrip('\0').split('\0')

    outside = root / 'outside'
    outside.mkdir()
    (outside / 'sentinel.txt').write_text('outside')
    harness = [dotnet, 'exec', root / 'bin/Release/net11.0/Harness.dll']
    run(harness + [outside], 'normal', 30)
    record = root / 'held.json'
    with (root / 'hold.log').open('wb') as output, (root / 'hold.err').open('wb') as error:
        child = subprocess.Popen([str(value) for value in harness + ['hold', record]], env=environment, stdout=output, stderr=error)
        try:
            deadline = time.monotonic() + 10
            while not record.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            held = json.loads(record.read_text())
            assert query(held['drive']) == ['\\??\\' + held['action']]
            child.kill()
            child.wait(timeout=5)
            assert Path(held['action']).exists(), 'Hard termination unexpectedly ran managed cleanup'
            assert query(held['drive']) == ['\\??\\' + held['action']]
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
    run(harness + [outside], 'recovery', 30)
    assert not Path(held['action']).exists(), 'Orphan action directory remains'
    assert query(held['drive']) == [], 'Orphan drive definition remains'
    receipt.update(normal=True, killedOwnerRecovered=True, ownedDriveRemoved=True)
    (root / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('PASS: native storage/alias controls and killed-owner recovery')


if __name__ == '__main__':
    main()
