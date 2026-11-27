"""Native Windows AppContainer process, stream, job and private-SDK controls."""
import argparse
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def drive_alias(directory, ledger):
    """Lease an unused drive and remove only our exact definition."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.QueryDosDeviceW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    kernel.QueryDosDeviceW.restype = ctypes.c_uint
    kernel.DefineDosDeviceW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p]
    kernel.DefineDosDeviceW.restype = ctypes.c_int

    def query(name):
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel.QueryDosDeviceW(name, buffer, len(buffer))
        if not length:
            error = ctypes.get_last_error()
            if error == 2:
                return []
            raise ctypes.WinError(error)
        return buffer[:length].rstrip('\0').split('\0')

    drive = next((letter + ':' for letter in 'ZYXWVUTSRQPONMLKJIHGFED' if not query(letter + ':')), None)
    if drive is None:
        raise RuntimeError('No unused drive for the native isolation control')
    target = '\\??\\' + str(directory)
    record = {'drive': drive, 'target': target, 'directory': str(directory), 'ownerPid': os.getpid()}
    ledger.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    if not kernel.DefineDosDeviceW(9, drive, target):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        assert query(drive) == [target], 'Drive mapping collided with another definition'
        yield drive + '\\'
    finally:
        removed = bool(kernel.DefineDosDeviceW(15, drive, target))
        after = query(drive)
        record.update(exactTargetRemoved=removed, after=after)
        ledger.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
        assert removed and not after, 'Owned drive cleanup did not complete; see lease receipt'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='Fresh disposable evidence directory')
    parser.add_argument('--build-only', action='store_true', help='Compile the linked controls without claiming native execution')
    args = parser.parse_args()
    if os.name != 'nt' and not args.build_only:
        raise RuntimeError('These controls require native Windows; --build-only verifies source compilation only')
    base = args.directory.resolve()
    base.mkdir()
    harness = base / 'harness'
    control = base / 'control'
    action = base / 'action'
    for directory in [harness, control, action]:
        directory.mkdir()
    sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
    dotnet = sdk / ('dotnet.exe' if os.name == 'nt' else 'dotnet')
    assert (sdk / 'sdk/11.0.100/.version').is_file(), 'Expected the pinned SDK 11.0.100 input'
    if not args.build_only:
        sdk_bytes = sum(path.stat().st_size for path in sdk.rglob('*') if path.is_file())
        assert shutil.disk_usage(base).free > sdk_bytes + 512 * 1024 * 1024, 'Insufficient free space for the private SDK control'
    (control / 'secret.txt').write_text('existing undeclared host sentinel', encoding='utf-8')
    sources = [ROOT / 'tools/GraphBuild' / name for name in ['WindowsProcess.cs', 'WorkerProcess.cs', 'WorkerOutput.cs']]
    sources.append(ROOT / 'tools/NoLinkTree.cs')
    (harness / 'Program.cs').write_text((ROOT / 'tests/graph_build/WindowsProcess.cs.txt').read_text(encoding='utf-8'), encoding='utf-8')
    items = '<Compile Include="Program.cs" />' + ''.join(f'<Compile Include="{escape(str(source))}" />' for source in sources)
    (harness / 'Harness.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net11.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable><EnableDefaultCompileItems>false</EnableDefaultCompileItems><UseSharedCompilation>false</UseSharedCompilation><NuGetAudit>false</NuGetAudit></PropertyGroup><ItemGroup>' + items + '</ItemGroup></Project>', encoding='utf-8')
    config = harness / 'NuGet.Config'
    config.write_text('<configuration><packageSources><clear /></packageSources></configuration>', encoding='utf-8')
    environment = dict(os.environ, DOTNET_ROOT=str(sdk), DOTNET_CLI_USE_MSBUILD_SERVER='false',
                       MSBUILDUSESERVER='0', MSBUILDDISABLENODEREUSE='1', DOTNET_CLI_TELEMETRY_OPTOUT='1',
                       DOTNET_ADD_GLOBAL_TOOLS_TO_PATH='false', DOTNET_GENERATE_ASPNET_CERTIFICATE='false')
    if os.name == 'nt':
        home = control / 'parent-profile'
        for directory in [home, home / 'AppData/Roaming', home / 'AppData/Local']:
            directory.mkdir(parents=True, exist_ok=True)
        environment.update(USERPROFILE=str(home), APPDATA=str(home / 'AppData/Roaming'), LOCALAPPDATA=str(home / 'AppData/Local'))
    with (control / 'build.log').open('w', encoding='utf-8') as output, (control / 'build.err').open('w', encoding='utf-8') as error:
        result = subprocess.run([str(dotnet), 'build', str(harness / 'Harness.csproj'), '-c', 'Release',
                                 '--disable-build-servers', '-warnaserror', '-p:RestoreConfigFile=' + str(config)],
                                env=environment, stdout=output, stderr=error, timeout=120)
    assert result.returncode == 0, (control / 'build.log').read_text(encoding='utf-8') + (control / 'build.err').read_text(encoding='utf-8')
    receipt = {'buildOnly': args.build_only, 'sources': {str(source.relative_to(ROOT)): hashlib.sha256(source.read_bytes()).hexdigest() for source in sources}}
    (control / 'source.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    if args.build_only:
        print('PASS: linked Windows process controls compile; native execution not run')
        return
    with drive_alias(action, control / 'drive-lease.json') as virtual:
        with (control / 'run.log').open('w', encoding='utf-8') as output, (control / 'run.err').open('w', encoding='utf-8') as error:
            result = subprocess.run([str(dotnet), 'exec', str(harness / 'bin/Release/net11.0/Harness.dll'),
                                     str(sdk), str(base), virtual, str(ROOT / 'tests/graph_build/WindowsSdkExec.cs.txt')],
                                    env=environment, stdout=output, stderr=error, timeout=600)
        assert result.returncode == 0, (control / 'run.log').read_text(encoding='utf-8') + (control / 'run.err').read_text(encoding='utf-8')
    result = json.loads((control / 'result.json').read_text(encoding='utf-8'))
    assert result['privateSdkBuildExec'] and result['rootAclUnchanged'], result
    print('PASS: unique AppContainers, private SDK, argument/stream roundtrip, concurrent separation, cancellation and SDK Exec')


if __name__ == '__main__':
    main()
