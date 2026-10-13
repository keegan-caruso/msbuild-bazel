"""Build unchanged Add1_ro after its authored offline test bootstrap.

Supply the pinned runtime archive, the reviewed package feed (including
runtime_jit_packages.json), and refs produced by the qualified runtime graph.
The owned workspace retains SDK behavior; only NuGet sources and the supported
live-reference path are configured. Source-built corerun execution is separate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

from runtime_benchmark import expand_raw_packages
from runtime_jit_prepare import DEPENDENCIES, ENTRY, EXTERNAL, PINNED, REFS, TEST_OUTPUT
from runtime_prepare import COMMIT, SOURCE_SHA256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_archive', type=Path)
    parser.add_argument('package_feed', type=Path)
    parser.add_argument('references', type=Path, help='source-built artifacts/bin/ref/net10.0')
    parser.add_argument('directory', type=Path, help='new disposable result directory')
    parser.add_argument('--cases', type=Path, help='reviewed unchanged JIT case declarations')
    parser.add_argument('--native-inventory', type=Path, help='public native inventory; let NuGet extract and verify signed packages')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert hashlib.sha256(args.source_archive.read_bytes()).hexdigest() == SOURCE_SHA256
    cases = json.loads(args.cases.read_text()) if args.cases else [dict(project=ENTRY, sourceDigests=PINNED)]
    pins = {path: digest for case in cases for path, digest in case['sourceDigests'].items()}
    base = args.directory.resolve()
    base.mkdir(parents=True, exist_ok=False)
    with tarfile.open(args.source_archive) as archive:
        archive.extractall(base, filter='data')
    root = base / 'workspace'
    (base / ('runtime-' + COMMIT)).rename(root)
    expected = json.loads(Path(__file__).with_name('runtime_jit_packages.json').read_text())
    feed = root / '.package-source'
    feed.mkdir()
    for key, record in expected.items():
        identity, version = key.split('/')
        path = args.package_feed / (identity + '.' + version + '.nupkg')
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256'], key
    for path in args.package_feed.glob('*.nupkg'):
        shutil.copyfile(path, feed / path.name)
    if args.native_inventory:
        inventory = json.loads(args.native_inventory.read_text())
        assert inventory['generatedBy'] == 'RulesMSBuild.NuGetUpdate'
        shutil.copyfile(args.native_inventory, root / 'nuget.lock.json')
    expand_raw_packages(root)
    shutil.copytree(args.references, root / REFS, copy_function=shutil.copyfile)
    refs = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (root / REFS).rglob('*') if p.is_file()}
    assert refs and any(p.endswith('/System.Runtime.dll') for p in refs)
    for path, digest in pins.items():
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == digest
    # Keep the authored root config unchanged; raw Restore uses this explicit
    # private offline config, matching the graph runner's declared-package feed.
    config = root / '.qualification/NuGet.Config'
    config.parent.mkdir()
    config.write_text('<configuration><packageSources><clear/><add key="declared" value="../.package-source"/></packageSources><fallbackPackageFolders><clear/></fallbackPackageFolders></configuration>')
    scratch = base / 'scratch'
    scratch.mkdir()
    stable = '/__rules_msbuild_graph/output/workspace'
    properties = dict(Configuration='Release', TargetOS='linux', TargetArchitecture='arm64',
                      BuildAllTestsAsStandalone='true', CLRTestPriorityToBuild='1', UseSharedCompilation='false',
                      NuGetAudit='false', LibrariesSharedFrameworkRefArtifactsPath=stable + '/' + REFS + '/',
                      RestoreSources=stable + '/.package-source', RestoreConfigFile=stable + '/' + str(config.relative_to(root)),
                      RestorePackagesPath=stable + '/.nuget',
                      PathMap=stable + '=/_/workspace%2C/__rules_msbuild_graph/sdk=/_/sdk')
    prefix = ['bash', str(Path(__file__).with_name('runtime_raw.sh')), os.environ['RULES_MSBUILD_DOTNET_ROOT'], str(root), str(scratch)]
    for project in [EXTERNAL, DEPENDENCIES] + [case['project'] for case in cases]:
        with (base / (Path(project).stem + '.log')).open('w') as log:
            subprocess.run(prefix + ['msbuild', stable + '/' + project, '-restore', '-t:Build', '-m:4', '-v:minimal'] +
                           ['-p:' + key + '=' + value for key, value in properties.items()], stdout=log, stderr=subprocess.STDOUT, check=True)
    for path, digest in pins.items():
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == digest
    assembly = root / TEST_OUTPUT / 'Add1_ro.dll'
    assert assembly.is_file()
    (base / 'summary.json').write_text(json.dumps(dict(commit=COMMIT, platform='linux-arm64', properties=properties,
        sourceDigests=pins, referenceDigests=refs, outputSha256=hashlib.sha256(assembly.read_bytes()).hexdigest(),
        scope='unchanged authored bootstrap and compilation; source-runtime execution is separate'), indent=2) + '\n')
    print(root, flush=True)


if __name__ == '__main__':
    main()
