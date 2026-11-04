"""Verify exact source producers and SDK-absent ordinary app execution."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    root = args.workspace.resolve()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root / 'application.json').read_text())
    product = (root/'runtime-product.json').exists()
    flags = ['--describe-runtime'] + (['--verify-product'] if product else [])
    host = (root / 'bazel-bin/app_source_runtime.layout').resolve(strict=True)
    app = (root / 'bazel-bin/app.runtime').resolve(strict=True)
    shared = 'shared/Microsoft.NETCore.App/' + manifest['framework']
    graph = root / 'bazel-bin/graph.graph/workspace'
    expected = {shared + '/' + name: graph / producer['path'] for name, producer in manifest['managed'].items()}
    expected.update({producer['path']: root / 'bazel-bin' / producer['producer'] / 'runtime.generated' / name
                     for name, producer in manifest['native'].items()})
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    actual = {str(path.relative_to(host)): digest(path) for path in host.rglob('*') if path.is_file()
              and (path.suffix in ['.dll', '.so'] or path.name in manifest['native'])}
    assert actual == {name: digest(path) for name, path in expected.items()}, 'Framework differs from declared source producers'
    assert all(not path.is_symlink() for path in host.rglob('*'))
    for name, source in expected.items():
        assert (host/name).stat().st_mode & 0o111 == source.stat().st_mode & 0o111, name
    if product:
        membership = json.loads((root/'runtime-product.json').read_text())
        assert sorted(manifest['managed']) == membership['assemblies']
        assert len(manifest['managed']) == 172 and len(manifest['native']) == 16

    required = {'System.Private.CoreLib.dll', 'System.Text.Json.dll', 'System.IO.Compression.dll',
                'System.Security.Cryptography.dll', 'libcoreclr.so', 'libclrjit.so', 'libSystem.Native.so',
                'libSystem.IO.Compression.Native.so', 'libSystem.Security.Cryptography.Native.OpenSsl.so',
                'dotnet', 'libhostfxr.so', 'libhostpolicy.so'}
    def observe(result, host_prefix, app_prefix):
        assert result.returncode == 0, result.stdout
        assert 'Hello from source-built .NET' in result.stdout
        observed = json.loads(next(line.removeprefix('RUNTIME=') for line in result.stdout.splitlines() if line.startswith('RUNTIME=')))
        assert Path(observed['corelib']).resolve() == host_prefix / shared / 'System.Private.CoreLib.dll'
        loaded = set()
        for row in observed['files']:
            path = Path(row['path']).resolve()
            if path.is_relative_to(host_prefix):
                relative = str(path.relative_to(host_prefix))
                assert row['sha256'].lower() == actual[relative], relative
                loaded.add(path.name)
            elif path.suffix == '.dll':
                assert path.name == 'App.dll' and row['sha256'].lower() == digest(app / 'App.dll'), path
                if app_prefix is not None:
                    assert path == app_prefix / 'App.dll', path
            else:
                assert path.name not in manifest['native'], path
        assert required <= loaded, sorted(required - loaded)
        if product:
            assert {'Microsoft.VisualBasic.Core.dll', 'System.Text.Encoding.CodePages.dll', 'System.Formats.Tar.dll'} <= loaded
            assert 'PRODUCT_MEMBERS=172' in result.stdout
        return sorted(loaded)
    result = subprocess.run([str(root / 'bazel-bin/app'), *flags], cwd=root,
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    args.report.with_suffix('.launcher.log').write_text(result.stdout)
    loaded = observe(result, host, None)
    command = [str(root / 'native/bwrap'), '--die-with-parent', '--unshare-all', '--new-session', '--cap-drop', 'ALL',
               '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib', '--ro-bind', '/etc', '/etc',
               '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--dir', '/opt',
               '--ro-bind', str(host), '/runtime', '--ro-bind', str(app), '/app', '--clearenv',
               '--setenv', 'DOTNET_ROOT', '/missing-sdk', '--setenv', 'DOTNET_MULTILEVEL_LOOKUP', '1',
               '--', '/runtime/dotnet', '/app/App.dll', *flags]
    isolated = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    args.report.with_suffix('.sdk-absent.log').write_text(isolated.stdout)
    isolated_loaded = observe(isolated, Path('/runtime'), Path('/app'))
    package_verified = False
    if product:
        package = root/'bazel-bin/runtime_package.tar.gz'
        with tempfile.TemporaryDirectory(prefix='runtime-product-package-') as temporary:
            extracted = Path(temporary)
            with tarfile.open(package) as archive:
                members = archive.getmembers()
                assert all(member.isfile() or member.isdir() for member in members), 'Runtime package contains links or special files'
                actual_members = {member.name.removeprefix('./'): member for member in members if member.isfile()}
                assert len(actual_members) == sum(member.isfile() for member in members), 'Duplicate runtime package members'
                files = {str(path.relative_to(host)): path for path in host.rglob('*') if path.is_file()}
                assert actual_members.keys() == files.keys(), 'Archive differs from the declared runtime layout'
                for name, file in files.items():
                    assert hashlib.sha256(archive.extractfile(actual_members[name]).read()).hexdigest() == digest(file), name
                    assert actual_members[name].mode & 0o111 == file.stat().st_mode & 0o111, name
                archive.extractall(extracted, filter='data')
            packaged = list(command)
            packaged[packaged.index(str(host))] = str(extracted)
            result = subprocess.run(packaged, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
            args.report.with_suffix('.package-sdk-absent.log').write_text(result.stdout)
            observe(result, Path('/runtime'), Path('/app'))
            package_verified = True
    with tempfile.TemporaryDirectory(prefix='runtime-app-missing-coreclr-') as temporary:
        broken = Path(temporary) / 'host'
        shutil.copytree(host, broken)
        for directory in [broken, broken / shared]:
            directory.chmod(0o755)
        (broken / shared / 'libcoreclr.so').unlink()
        rejected = subprocess.run([str(broken / 'dotnet'), str(app / 'App.dll')], text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60,
            env=dict(os.environ, DOTNET_ROOT=os.environ['RULES_MSBUILD_DOTNET_ROOT'], DOTNET_MULTILEVEL_LOOKUP='1'))
        args.report.with_suffix('.missing-coreclr.log').write_text(rejected.stdout)
        assert rejected.returncode != 0 and 'Could not resolve CoreCLR path' in rejected.stdout, rejected.stdout
    args.report.write_text(json.dumps(dict(platform='linux-arm64', binaryHashes=actual, managed=len(manifest['managed']),
        native=len(manifest['native']), loadedSourceComponents=loaded, sdkAbsentLoadedSourceComponents=isolated_loaded,
        missingCoreclrExit=rejected.returncode, sdkAbsentExecution=True,
        packageVerified=package_verified,
        scope='complete unsigned IL developer product; selected APIs, not full upstream suites' if product else 'ordinary app on selected source framework; not full upstream test suites or redistributable runtime'), indent=2) + '\n')
    print('PASS: ordinary app producer identity, loaded source hashes, SDK-absent execution and missing-CoreCLR failure', flush=True)


if __name__ == '__main__':
    main()
