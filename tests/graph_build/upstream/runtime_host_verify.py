"""Verify graph/native host products and execute a probe with the SDK absent."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    assert os.uname().sysname == "Linux" and os.uname().machine == "aarch64", "Qualification requires Linux ARM64"
    root = args.workspace.resolve()
    host = (root / 'bazel-bin/runtime_source.layout').resolve()
    graph = root / 'bazel-bin/graph.graph/workspace'
    app = (root / 'bazel-bin/runtime_probe_test.runtime').resolve()
    products = {
        'libcoreclr.so': root / 'bazel-bin/native/runtime.generated/libcoreclr.so',
        'libclrjit.so': root / 'bazel-bin/native/runtime.generated/libclrjit.so',
        'corerun': root / 'bazel-bin/native/runtime.generated/corerun',
        'libSystem.Native.so': root / 'bazel-bin/native_support/runtime.generated/libSystem.Native.so',
        'System.Private.CoreLib.dll': graph / 'artifacts/bin/coreclr/linux.arm64.Release/IL/System.Private.CoreLib.dll',
        'System.Runtime.dll': graph / 'artifacts/bin/System.Runtime/Release/net10.0/System.Runtime.dll',
    }
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    expected = {name: digest(path) for name, path in products.items()}
    assert expected == {name: digest(host / name) for name in expected}
    binaries = {p.name for p in host.iterdir() if p.is_file() and (p.suffix in ['.dll', '.so'] or p.name == 'corerun')}
    assert binaries == set(products), binaries
    assert all(not path.is_symlink() for path in host.rglob('*'))
    sandbox = root / 'native/bwrap'
    def command(layout):
        return [str(sandbox), '--die-with-parent', '--unshare-all', '--new-session', '--cap-drop', 'ALL',
                '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib', '--ro-bind', '/etc', '/etc',
                '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--dir', '/opt',
                '--ro-bind', str(layout), '/runtime_source.layout', '--ro-bind', str(app), '/app',
                '--clearenv', '--setenv', 'DOTNET_ROOT', '/missing-sdk', '--setenv', 'RUNTIME_PROVIDER', 'source',
                '--', '/runtime_source.layout/corerun', '/app/App.dll']
    passed = subprocess.run(command(host), text=True, capture_output=True, timeout=60)
    assert passed.returncode == 0, passed.stdout + passed.stderr
    # Mount a private copy missing CoreCLR; no installed payload may rescue it.
    with tempfile.TemporaryDirectory(prefix='runtime-host-missing-coreclr-') as temporary:
        copy = Path(temporary) / 'host'
        shutil.copytree(host, copy)
        copy.chmod(0o755)
        (copy / 'libcoreclr.so').unlink()
        rejected = subprocess.run(command(copy), text=True, capture_output=True, timeout=60)
        assert rejected.returncode != 0
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(dict(platform='linux-arm64', products=expected,
                                         graphManagedLibraries=2, sourceNativeProducts=4, loadedNativePathChecks=3,
                                         sdkAbsentProbeExit=passed.returncode, missingCoreclrExit=rejected.returncode,
                                         scope='bounded corerun probe, not the full upstream test host or ordinary app'), indent=2) + '\n')
    print('PASS: graph/native producer byte identity, SDK-absent probe and missing-CoreCLR failure', flush=True)


if __name__ == '__main__':
    main()
