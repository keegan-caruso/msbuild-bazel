"""Prepare unchanged CoreCLR tests through public SDK, NuGet update and sync.

Runtime products are declared, digest-locked producer artifacts. No handwritten
graph contract or preexisting project cache is consumed by this preparation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

from runtime_jit_prepare import DEPENDENCIES, ENTRY, EXTERNAL, PINNED
from runtime_prepare import COMMIT, SOURCE_SHA256

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_archive', type=Path)
    parser.add_argument('source_products', type=Path)
    parser.add_argument('seed_report', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--resume', action='store_true', help='resume an interrupted disposable preparation')
    parser.add_argument('--host-space-path', type=Path, required=True)
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert hashlib.sha256(args.source_archive.read_bytes()).hexdigest() == SOURCE_SHA256
    seed = json.loads(args.seed_report.read_text())
    assert hashlib.sha256(args.source_products.read_bytes()).hexdigest() == seed['sourceProductsSha256']
    base = args.output.resolve()
    base.mkdir(parents=True, exist_ok=args.resume)
    source = base / 'workspace'
    source.mkdir(exist_ok=args.resume)
    directories = ['eng/', 'src/tests/Common/', 'src/tests/JIT/CodeGenBringUpTests/']
    files = {'global.json', 'NuGet.config', 'Directory.Build.props', 'Directory.Build.targets',
        'src/tests/Directory.Build.props', 'src/tests/Directory.Build.targets', 'src/tests/Directory.Merged.props',
        'src/tests/JIT/Directory.Build.props', 'src/coreclr/Directory.Build.props', 'src/coreclr/Directory.Build.targets',
        'src/coreclr/clr.featuredefines.props', 'src/libraries/Microsoft.NETCore.Platforms/src/runtime.json',
        'src/libraries/Microsoft.NETCore.Platforms/src/PortableRuntimeIdentifierGraph.json'}
    prefix = 'runtime-' + COMMIT + '/'
    with tarfile.open(args.source_archive) as archive:
        for member in archive.getmembers():
            if not member.name.startswith(prefix):
                continue
            relative = member.name[len(prefix):]
            if relative in files or any(relative.startswith(path) for path in directories):
                assert not member.issym() and not member.islnk()
                member.name = relative
                archive.extract(member, source, filter='data')
    for path, digest in PINNED.items():
        assert hashlib.sha256((source / path).read_bytes()).hexdigest() == digest
    shutil.copyfile(Path(__file__).with_name('runtime_jit_public_mappings.json'), source / 'mappings.json')
    shutil.copyfile(Path(__file__).with_name('runtime_jit_artifacts.bzl'), source / 'products.bzl')
    shutil.copyfile(args.source_products, source / 'source-products.tar.gz')
    module = ('module(name="jit_public")\nbazel_dep(name="rules_msbuild",version="0.0.0")\n'
        'local_path_override(module_name="rules_msbuild",path=' + json.dumps(str(ROOT)) + ')\n'
        'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
        'dotnet.sdk(name="dotnet",version="10.0.400")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
    (source / 'MODULE.bazel').write_text(module)
    update = ('load("@rules_msbuild//msbuild:sync.bzl","msbuild_nuget_update","msbuild_sync")\n'
        'projects=' + repr([DEPENDENCIES, ENTRY]) + '\n'
        'msbuild_nuget_update(name="update_packages",projects=projects,mappings="mappings.json")\n')
    (source / 'BUILD.bazel').write_text(update)
    command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(base / 'bazel')]

    def run(label, arguments, cwd=source, output_base=None):
        disk = os.statvfs(args.host_space_path)
        assert disk.f_bavail * disk.f_frsize >= 8 * 1024**3, 'Insufficient physical host disk headroom'
        with (base / (label + '.log')).open('w') as log:
            subprocess.run((command if output_base is None else [command[0], '--output_base=' + str(output_base)]) + arguments, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(['fstrim', '/'], check=True, capture_output=True)

    # Bootstrap is its own public generated graph and an explicit producer module.
    bootstrap = base / 'bootstrap'
    if not bootstrap.exists():
        shutil.copytree(source, bootstrap, ignore=shutil.ignore_patterns('bazel-*', '*.lock.json'))
    bootstrap_module = module.replace('jit_public', 'jit_bootstrap').replace('dotnet.sdk(name="dotnet"', 'dotnet.sdk(name="jit_bootstrap_sdk"').replace('use_repo(dotnet,"dotnet")', 'use_repo(dotnet,dotnet="jit_bootstrap_sdk")')
    (bootstrap / 'MODULE.bazel').write_text(bootstrap_module)
    bootstrap_mapping = json.loads((source / 'mappings.json').read_text())
    bootstrap_mapping['projectDefaults']['inputDirectories'] = []
    external = bootstrap / EXTERNAL
    bootstrap_mapping['projectDefaults']['documents'][EXTERNAL] = dict(
        sha256=hashlib.sha256(external.read_bytes()).hexdigest(),
        targets=['FilterNugetPackages', 'AddXunitConsoleRunner', 'CoreCompile'], tasks=[], inputs=[])
    (bootstrap / 'mappings.json').write_text(json.dumps(bootstrap_mapping, indent=2) + '\n')
    bootstrap_build = update.replace(repr([DEPENDENCIES, ENTRY]), repr([EXTERNAL]))
    (bootstrap / 'BUILD.bazel').write_text(bootstrap_build)
    run('bootstrap-update', ['run', '//:update_packages'], bootstrap, base / 'bootstrap-bazel')
    run('bootstrap-update-check', ['run', '//:update_packages', '--', '--check'], bootstrap, base / 'bootstrap-bazel')
    nuget = 'nuget=use_extension("@rules_msbuild//msbuild:nuget.bzl","nuget")\nnuget.lock(name="nuget",lockfile="//:nuget.lock.json")\nuse_repo(nuget,"nuget")\n'
    (bootstrap / 'MODULE.bazel').write_text(bootstrap_module + nuget.replace('lock(name="nuget"', 'lock(name="jit_bootstrap_nuget"').replace('use_repo(nuget,"nuget")', 'use_repo(nuget,nuget="jit_bootstrap_nuget")'))
    bootstrap_build += 'msbuild_sync(name="sync",projects=projects,mappings="mappings.json",package_lock="@nuget//:packages",package_build=True)\n'
    (bootstrap / 'BUILD.bazel').write_text(bootstrap_build)
    run('bootstrap-sync', ['run', '//:sync'], bootstrap, base / 'bootstrap-bazel')
    run('bootstrap-sync-check', ['run', '//:sync', '--', '--check'], bootstrap, base / 'bootstrap-bazel')
    bootstrap_build += ('load(":graph.generated.bzl","app_graph")\n'
        'load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph_output")\n'
        'app_graph(name="bootstrap",linux_stable_paths=True,linux_worker=True)\n'
        'msbuild_graph_output(name="targeting",graph=":bootstrap",path="artifacts/TargetingPack",directory=True,visibility=["//visibility:public"])\n')
    (bootstrap / 'BUILD.bazel').write_text(bootstrap_build)
    test_mapping = json.loads((source / 'mappings.json').read_text())
    test_mapping.pop('entryProperties')
    test_mapping.pop('projects')
    (source / 'mappings.json').write_text(json.dumps(test_mapping, indent=2) + '\n')
    module += 'bazel_dep(name="jit_bootstrap",version="0.0.0")\nlocal_path_override(module_name="jit_bootstrap",path=' + json.dumps(str(bootstrap)) + ')\n'
    (source / 'MODULE.bazel').write_text(module)
    run('update', ['run', '//:update_packages'])
    run('update-check', ['run', '//:update_packages', '--', '--check'])
    (source / 'MODULE.bazel').write_text(module + nuget)
    declarations = [update, 'load(":products.bzl","runtime_jit_products")']
    for name, prefix in [('refs', 'references'), ('host_products', 'core-root')]:
        declarations.append('runtime_jit_products(name=' + repr(name) + ',archive="source-products.tar.gz",sha256=' + repr(seed['sourceProductsSha256']) + ',prefix=' + repr(prefix) + ')')
    declarations.append('msbuild_sync(name="sync",projects=projects,mappings="mappings.json",package_lock="@nuget//:packages",package_build=True,inputs={":refs":"artifacts/bin/ref/net10.0","@jit_bootstrap//:targeting":"artifacts/TargetingPack"})')
    (source / 'BUILD.bazel').write_text('\n'.join(declarations) + '\n')
    run('sync', ['run', '//:sync'])
    run('sync-check', ['run', '//:sync', '--', '--check'])
    declarations += ['load(":graph.generated.bzl","app_graph")',
        'load("@rules_msbuild//msbuild:defs.bzl","msbuild_layout","msbuild_runtime","msbuild_graph_test")',
        'app_graph(name="graph",linux_stable_paths=True,linux_worker=True)',
        'msbuild_layout(name="core_root",paths={":host_products":"."})',
        'msbuild_runtime(name="jit_host",layout=":core_root",entry_point="corerun",launch_mode="corerun",runtime_identifier="linux-arm64",version="10.0.0")',
        'msbuild_graph_test(name="add1",graph=":graph",project=' + repr(ENTRY) + ',runtime_host=":jit_host",expected_exit_code=100)']
    (source / 'BUILD.bazel').write_text('\n'.join(declarations) + '\n')
    contract = json.loads((source / 'graph.generated.json').read_text())
    wrapper = 'src/tests/Common/XUnitWrapperGenerator/XUnitWrapperGenerator.csproj'
    assert contract['Projects'][ENTRY]['Configurations'][0]['ImplementationDependencies'] == [wrapper]
    manifest = json.loads((source / 'nuget.lock.json').read_text())
    (base / 'summary.json').write_text(json.dumps(dict(commit=COMMIT, sdk='10.0.400',
        sourceDigests=PINNED, projects=list(contract['Projects']), archives=len(manifest['packages']),
        nativeLocks=len(manifest['lockFiles']), sourceProductsSha256=seed['sourceProductsSha256']), indent=2) + '\n')
    print(source, flush=True)


if __name__ == '__main__':
    main()
