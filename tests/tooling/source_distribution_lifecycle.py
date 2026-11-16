#!/usr/bin/env python3
"""Exercise pinned Git source selection and rollback in a disposable consumer.

The two commits and their marker exist only in the fixture. No release, .NET
compilation, or project-cache compatibility is implied by this control.
"""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def run(command, cwd, log=None):
    result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=300)
    if log is not None:
        log.write_text(result.stdout)
    if result.returncode:
        raise RuntimeError(f'{command[0]} failed ({result.returncode}); see {log}:\n{result.stdout[-4000:]}')
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='New disposable evidence directory')
    parser.add_argument('--bazel', required=True, type=Path, help='Absolute path to Bazel or the repository wrapper')
    parser.add_argument('--disk-cache', required=True, type=Path, help='New empty cache directory owned by this control')
    args = parser.parse_args()
    folder, cache, bazel = args.directory.resolve(), args.disk_cache.resolve(), args.bazel.resolve()
    if not bazel.is_file():
        parser.error('--bazel must name an existing executable')
    folder.mkdir(parents=True, exist_ok=False)
    cache.mkdir(parents=True, exist_ok=False)
    repo, consumer = folder / 'source', folder / 'consumer'
    repo.mkdir()
    archive = folder / 'tracked-source.tar'
    with archive.open('wb') as out:
        subprocess.run(['git', 'archive', 'HEAD'], cwd=ROOT, stdout=out, check=True)
    # The archive is generated from the current tracked Git tree above.
    run(['tar', '-xf', str(archive), '-C', str(repo)], folder)
    run(['git', 'init', '-q'], repo)
    commits = []
    for marker in ('revision-a', 'revision-b'):
        # Synthetic test hook in the disposable snapshot, not the production API.
        defs = repo / 'msbuild/defs.bzl'
        original = defs.read_text().split('\nLIFECYCLE_TEST_REVISION =', 1)[0]
        defs.write_text(original + '\nLIFECYCLE_TEST_REVISION = "' + marker + '"\n')
        run(['git', 'add', '.'], repo)
        run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
             'commit', '-qm', marker], repo)
        commits.append(run(['git', 'rev-parse', 'HEAD'], repo).strip())
    consumer.mkdir()
    (consumer / 'BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:defs.bzl", "LIFECYCLE_TEST_REVISION", "msbuild_graph")
load("@rules_msbuild//msbuild:toolchain.bzl", "msbuild_toolchain")
msbuild_toolchain(name="fake_sdk",dotnet="sdk/dotnet",runner="Runner.dll",sdk=":sdk_files")
filegroup(name="sdk_files",srcs=["sdk/dotnet"])
toolchain(name="fake_registered",toolchain=":fake_sdk",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
filegroup(name="runner",srcs=["Runner.dll"])
msbuild_graph(name="graph",runner=":runner",contract="contract.json",srcs=["App.csproj"],linux_stable_paths=False)
genrule(name="identity",outs=["identity.txt"],cmd="printf '%s' " + LIFECYCLE_TEST_REVISION + " > $@")
''')
    (consumer / 'sdk').mkdir()
    for name, content in [('sdk/dotnet', '#!/bin/sh\nexit 1\n'), ('Runner.dll', ''), ('contract.json', '{}'), ('App.csproj', '<Project />')]:
        (consumer / name).write_text(content)
    (consumer / 'sdk/dotnet').chmod(0o755)
    phases = [('install', commits[0], 'revision-a', False), ('upgrade', commits[1], 'revision-b', False), ('rollback', commits[0], 'revision-a', True)]
    report = []
    for phase, commit, expected, hit in phases:
        module = ('module(name="lifecycle_consumer")\n'
                  'bazel_dep(name="rules_msbuild", version="0.0.0")\n'
                  'git_override(module_name="rules_msbuild", remote=' + json.dumps(repo.as_uri()) + ', commit=' + json.dumps(commit) + ')\n'
                  'register_toolchains("//:fake_registered")\n')
        (consumer / 'MODULE.bazel').write_text(module)
        (folder / (phase + '.MODULE.bazel')).write_text(module)
        base = [str(bazel), '--ignore_all_rc_files', '--host_jvm_args=-Xmx768m',
                '--output_base=' + str(folder / (phase + '-base'))]
        try:
            query = run(base + ['aquery', 'mnemonic("MSBuildGraph", //:graph)', '--output=text', '--jobs=1'], consumer, folder / (phase + '.aquery.log'))
            if 'Mnemonic: MSBuildGraph' not in query:
                raise AssertionError('public graph rule did not analyze')
            execution = folder / (phase + '.execution.json')
            run(base + ['build', '//:identity', '--jobs=1', '--disk_cache=' + str(cache),
                        '--remote_cache=', '--execution_log_json_file=' + str(execution)], consumer, folder / (phase + '.build.log'))
            actual = (consumer / 'bazel-bin/identity.txt').read_text()
            rows, text, decoder = [], execution.read_text(), json.JSONDecoder()
            while text.strip():
                value, size = decoder.raw_decode(text.lstrip())
                text = text.lstrip()[size:]
                rows.append(value)
            actions = [row for row in rows if row.get('mnemonic') == 'Genrule']
            if actual != expected or len(actions) != 1 or bool(actions[0].get('cacheHit')) != hit:
                raise AssertionError(f'{phase}: output={actual!r}, genrule={actions!r}')
            report.append({'phase': phase, 'commit': commit, 'output': actual, 'actionCacheHit': hit})
            (folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            print(phase, actual, 'cacheHit=' + str(hit), flush=True)
        finally:
            run(base + ['shutdown'], consumer, folder / (phase + '.shutdown.log'))


if __name__ == '__main__':
    main()
