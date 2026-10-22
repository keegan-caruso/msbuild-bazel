"""Prepare the pinned Orchard CMS CI demo through the public SDK/NuGet/sync APIs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parents[3]
COMMIT = '04467a3438d4255627c1a478598a1585b3ff2947'
SOURCE_SHA256 = '258912f7afca4069d5e6c3d4d3849ce9951fa4d603ff7ec5e374858af77a8e2d'
ENTRY = 'src/OrchardCore.Cms.Web/OrchardCore.Cms.Web.csproj'


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def write_ci_script(workspace):
    script = workspace / 'ci.sh'
    script.write_text('''#!/usr/bin/env bash
set -euo pipefail
base=${1:?Usage: ci.sh FRESH_OUTPUT_BASE CACHE_URL [BAZEL_OPTIONS...]}
cache=${2:?Supply the HTTP AC/CAS URL}
shift 2
[[ $base = /* ]] || { echo 'Use an absolute output-base path.' >&2; exit 1; }
[[ ! -e $base ]] || { echo 'Choose a fresh output base.' >&2; exit 1; }
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
options=(--jobs=4 --strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1
    --spawn_strategy=linux-sandbox --disk_cache= --remote_cache="$cache" --remote_cache_async=false
    --remote_download_outputs=toplevel --action_env="RULES_MSBUILD_PROJECT_CACHE_URL=$cache"
    --lockfile_mode=error --nocache_test_results --test_output=all)
if [[ -n ${RULES_MSBUILD_TEST_REPOSITORY_CACHE:-} ]]; then options+=(--repository_cache="$RULES_MSBUILD_TEST_REPOSITORY_CACHE"); fi
if [[ -n ${RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN:-} ]]; then options+=(--action_env=RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN); fi
exec ''' + shlex.quote(str(ROOT / 'scripts/bazel-launcher.sh')) + ''' --batch --nosystem_rc --nohome_rc --noworkspace_rc --output_base="$base" test //:smoke "${options[@]}" "$@"
''')
    script.chmod(0o755)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_archive', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--resume', action='store_true', help='resume an owned source preparation without repeating completed steps')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert digest(args.source_archive) == SOURCE_SHA256
    base = args.output.resolve()
    source = base / 'source'
    if args.resume:
        assert source.is_dir() and not (base / 'workspace').exists()
    else:
        base.mkdir(parents=True, exist_ok=False)
        with tarfile.open(args.source_archive) as archive:
            archive.extractall(base, filter='data')
        (base / ('OrchardCore-' + COMMIT)).rename(source)
    for path in source.rglob('*'):
        if path.is_symlink():
            assert args.resume and path.parent == source and path.name.startswith('bazel-') and path.resolve().is_relative_to(base / 'sync-bazel'), path
    mapping = json.loads(Path(__file__).with_name('orchard.json').read_text())
    mapping['projectDefaults']['preparedRestore'] = True
    (source / 'mappings.json').write_text(json.dumps(mapping, indent=2) + '\n')
    # Select the same verified SDK for native resolution, sync and graph builds.
    (source / 'global.json').write_text(json.dumps({'sdk': {'version': '10.0.400', 'rollForward': 'disable'}}) + '\n')
    module = ('module(name="orchard_ci_demo")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nbazel_dep(name="rules_shell",version="0.6.1")\n'
              'local_path_override(module_name="rules_msbuild",path=' + json.dumps(str(ROOT)) + ')\n'
              'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
              'dotnet.sdk(name="dotnet",global_json="//:global.json")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
    inventory = ('nuget=use_extension("@rules_msbuild//msbuild:nuget.bzl","nuget")\n'
                 'nuget.lock(name="nuget",lockfile="//:nuget.lock.json")\nuse_repo(nuget,"nuget")\n')
    update = ('load("@rules_msbuild//msbuild:sync.bzl","msbuild_nuget_update","msbuild_sync")\n'
              'msbuild_nuget_update(name="update_packages",projects=[' + json.dumps(ENTRY) + '],framework="net10.0",mappings="mappings.json")\n')
    sync = ('msbuild_sync(name="sync",projects=[' + json.dumps(ENTRY) + '],framework="net10.0",mappings="mappings.json",'
            'package_lock="@nuget//:packages",package_build=True,resolve_references=True)\n')
    command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--max_idle_secs=120', '--output_base=' + str(base / 'sync-bazel')]
    options = ['--repository_cache=' + os.environ['RULES_MSBUILD_TEST_REPOSITORY_CACHE']] if os.environ.get('RULES_MSBUILD_TEST_REPOSITORY_CACHE') else []
    rows = []

    def run(label, arguments):
        start = time.monotonic()
        with (base / (label + '.log')).open('w') as log:
            subprocess.run(command + arguments, cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True)
        row = dict(case=label, seconds=time.monotonic() - start)
        rows.append(row)
        print(json.dumps(row), flush=True)

    (source / 'MODULE.bazel').write_text(module)
    (source / 'BUILD.bazel').write_text(update)
    if not (source / 'nuget.lock.json').exists():
        run('update', ['run', '//:update_packages', *options])
    (source / 'MODULE.bazel').write_text(module + inventory)
    (source / 'BUILD.bazel').write_text(update + sync)
    if not (source / 'graph.generated.json').exists():
        run('sync', ['run', '//:sync', *options])
    contract = json.loads((source / 'graph.generated.json').read_text())
    variants = [v for p in contract['Projects'].values() for v in p.get('Configurations') or [p]]
    compilations = sum(bool(v['OutputDirectories'] or v.get('OutputFiles')) for v in variants)
    assert len(contract['Projects']) == compilations == 202
    paths = set(contract['SharedInputs']) | set(contract['DefinitionDigests']) | {p for v in variants for p in v['Inputs']}
    paths |= set(contract['Restore']['Inputs'])
    workspace = base / 'workspace'
    workspace.mkdir()
    for path in sorted(paths):
        original = source / path
        assert original.resolve().is_relative_to(source) and original.is_file(), path
        destination = workspace / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, destination)
    for name in ['graph.generated.json', 'graph.generated.bzl', 'nuget.lock.json', 'mappings.json', 'NuGet.config']:
        shutil.copyfile(source / name, workspace / name)
    (workspace / 'MODULE.bazel').write_text(module + inventory)
    (workspace / 'BUILD.bazel').write_text(
        'load(":graph.generated.bzl","app_graph")\n'
        'load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph_binary")\n'
        'load("@rules_shell//shell:sh_test.bzl","sh_test")\n'
        'app_graph(name="graph",linux_stable_paths=True,linux_worker=True)\n'
        'msbuild_graph_binary(name="app",graph=":graph",project=' + json.dumps(ENTRY) + ')\n'
        'sh_test(name="smoke",srcs=["smoke.sh"],data=[":app","orchard_http_smoke.py"],size="small",timeout="short")\n')
    (workspace / 'smoke.sh').write_text('#!/usr/bin/env bash\nset -euo pipefail\nexec python3 "$TEST_SRCDIR/$TEST_WORKSPACE/orchard_http_smoke.py" "$TEST_SRCDIR/$TEST_WORKSPACE/app"\n')
    (workspace / 'smoke.sh').chmod(0o755)
    shutil.copyfile(Path(__file__).with_name('orchard_http_smoke.py'), workspace / 'orchard_http_smoke.py')
    write_ci_script(workspace)
    run('archives', ['build', '@nuget//:archives', *options])
    execution_root = Path(subprocess.check_output(command + ['info', 'execution_root'], cwd=source, text=True).strip())
    archives = subprocess.check_output(command + ['cquery', '@nuget//:archives', '--output=files'], cwd=source, text=True).splitlines()
    feed = workspace / '.package-source'
    feed.mkdir()
    manifest = json.loads((source / 'nuget.lock.json').read_text())
    expected = {p['id'].lower() + '.' + p['version'].lower() + '.nupkg': p['sha256'] for p in manifest['packages']}
    assert {Path(path).name for path in archives} == expected.keys()
    for path in archives:
        archive = execution_root / path
        assert digest(archive) == expected[archive.name]
        shutil.copyfile(archive, feed / archive.name)
    shutil.copyfile(source / 'MODULE.bazel.lock', workspace / 'MODULE.bazel.lock')
    summary = dict(commit=COMMIT, sourceSha256=SOURCE_SHA256, sdk='10.0.400', configurations=len(variants), compilations=compilations,
                   archives=len(manifest['packages']), inputs=len(paths), commands=rows)
    (base / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
