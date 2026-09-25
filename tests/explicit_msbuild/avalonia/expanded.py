"""Qualify larger pinned Avalonia build/test slices, with raw outcome parity."""
import argparse
import ast
import base64
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from remote_support import RemoteFixture
from native_inputs import prepare as prepare_native
from native_repository import register as register_native
from suite_support import assembly_parity, configured_nodes, outcomes, runner_package, selections, serialize, test_outcomes

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('prepared', type=Path)
p.add_argument('output', type=Path)
p.add_argument('--executor', required=True)
p.add_argument('--test', action='append', default=[], help='Entry project assembly name; other entries are build-only')
p.add_argument('--recover', action='store_true')
p.add_argument('--reuse-compilation-from', help='Existing producer instance; requires all compilation/generation to be cached and executes tests afresh')
a = p.parse_args()
a.prepared = a.prepared.resolve()
workspace = a.prepared if a.recover else a.prepared / 'bazel'
manifest = workspace / 'expanded-qualification.json'
if a.recover:
    saved = json.loads(manifest.read_text())
    f = RemoteFixture(a.output, a.executor, workspace, instance=saved['instance'])
    f.sdk()
    register_native(workspace)
    try:
        actions = f.run('independent-recovery', saved['targets'], [], tests=[], downloads='toplevel', command='test' if saved['outcomes'] else 'build')
        assert actions and all(x['cacheHit'] for x in actions)
        for suite, expected in saved['outcomes'].items():
            assert serialize(test_outcomes(workspace, suite)) == expected, suite
    finally:
        f.shutdown()
    raise SystemExit()

rows = json.loads((a.prepared / 'inventory.json').read_text())
labels = json.loads((a.prepared / 'labels.json').read_text())
config = json.loads((a.prepared / 'config.json').read_text())
roots = [r for r in rows if r['entry']]
by_suite = {labels[r['id']]: r for r in roots}
assert set(a.test) <= set(by_suite), (a.test, list(by_suite))
targets = ['//upstream:' + labels[r['id']] for r in roots]
instance = a.reuse_compilation_from or 'avalonia-expanded/' + a.output.name
f = RemoteFixture(a.output, a.executor, workspace, instance=instance)
f.sdk()
expected = {}
def uses_native(name):
    return name.startswith(('Avalonia.Skia.', 'Avalonia.Headless.', 'Qualification.Headless.'))

try:
    native_data, native_env = prepare_native(a.prepared, f) if any(uses_native(name) for name in a.test) else ({}, {})
    if a.test:
        archive, digest, runner = runner_package(a.prepared)
        for suite in a.test:
            row = by_suite[suite]
            raw = a.prepared / 'source' / Path(row['project']).parent / 'bin/Release' / row['framework'] / (row['properties']['AssemblyName'] + '.dll')
            results = f.folder / ('raw-' + suite)
            with (f.folder / ('raw-' + suite + '.log')).open('w') as log:
                result = subprocess.run([Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']) / 'dotnet', runner, raw,
                    '/Logger:trx;LogFileName=results.trx', '/ResultsDirectory:' + str(results)],
                    cwd=a.prepared / 'source/tests', env=dict(os.environ, DOTNET_ROLL_FORWARD='Major', **(native_env if uses_native(suite) else {})), stdout=log, stderr=subprocess.STDOUT)
            expected[suite] = outcomes(results / 'results.trx')
            summary = dict(Counter(outcome for (_, outcome), count in expected[suite].items() for _ in range(count)))
            print('raw', suite, summary, flush=True)
            assert result.returncode == 0 and 'Failed' not in summary, (suite, summary)
        shutil.copyfile(archive, workspace / 'upstream/locked-packages' / archive.name)
    build = workspace / 'upstream/BUILD.bazel'
    snapshot = a.prepared / 'expanded-build.original'
    if not snapshot.exists():
        assert 'expanded_runner_package' not in build.read_text()
        snapshot.write_text(build.read_text())
    lines = snapshot.read_text().splitlines()
    lines = [line for line in lines if not line.startswith(('load("@rules_msbuild//msbuild:toolchain', 'msbuild_toolchain(', 'toolchain('))]
    lines = [line.replace(',allow_remote_execution=True', '').replace('linux_worker=True', 'linux_worker=True,allow_remote_execution=True') for line in lines]
    lines.insert(0, 'load("@rules_msbuild//msbuild:defs.bzl","msbuild_test","msbuild_test_tool")')
    by_name = {labels[r['id']]: r for r in rows}
    for i, line in enumerate(lines):
        if not line.startswith(('msbuild_library(', 'msbuild_binary(')):
            continue
        call = ast.parse(line).body[0].value
        attrs = {k.arg: ast.literal_eval(k.value) for k in call.keywords}
        name = attrs['name']
        row = by_name[name]
        choices = selections(rows, row['id'], labels)
        if choices:
            attrs['assembly_selections'] = choices
        rule = call.func.id
        if name in a.test:
            rule = 'msbuild_test'
            attrs.update(use_apphost=False, test_protocol='vstest',
                         test_output_type='exe' if row['properties']['OutputType'] == 'Exe' else 'library',
                         test_runner=':expanded_runner', test_adapters=[':expanded_nunit_adapter' if '.NUnit' in name else ':expanded_adapter'],
                         env={'DOTNET_ROLL_FORWARD':'Major'}, size='large')
            if uses_native(name):
                attrs['test_working_directory'] = 'tests'
                attrs['data_paths'] = dict(native_data)
                attrs['env'].update(LD_LIBRARY_PATH='native-tests', FONTCONFIG_PATH='native-tests', FONTCONFIG_FILE='fonts.conf')
            if name == 'Avalonia.Skia.RenderTests':
                attrs['data_paths'].update({p.relative_to(workspace / 'upstream').as_posix():p.relative_to(workspace / 'upstream').as_posix()
                    for p in sorted((workspace / 'upstream/tests/TestFiles').rglob('*'))
                    if p.is_file() and not p.name.endswith('.out.png')})
        lines[i] = rule + '(' + ','.join(k + '=' + repr(v) for k,v in attrs.items()) + ')'
    if a.test:
        lines += [
            'msbuild_nuget_package(name="expanded_runner_package",package_id="Microsoft.TestPlatform.CLI",version="17.14.1",archive="locked-packages/' + archive.name + '",archive_sha256="' + digest + '",content_hash="' + base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode() + '")',
            'msbuild_test_tool(name="expanded_runner",package=":expanded_runner_package",path="contentFiles/any/net9.0/vstest.console.dll")',
            *(['msbuild_test_tool(name="expanded_adapter",package=":archive_xunit.runner.visualstudio_2.8.2",path="build/net6.0")'] if any('.NUnit' not in name for name in a.test) else []),
        ]
    if any('.NUnit' in name for name in a.test):
        lines.append('msbuild_test_tool(name="expanded_nunit_adapter",package=":archive_nunit3testadapter_4.4.2",path="build/netcoreapp3.1")')
    build.write_text('\n'.join(lines) + '\n')
    configured = configured_nodes(rows, config, [r['id'] for r in roots])
    compiled = [('MSBuildAssembly', '//upstream:' + labels[node]) for node, _ in configured]
    generated = json.loads((a.prepared / 'expanded-generators.json').read_text()) if (a.prepared / 'expanded-generators.json').exists() else []
    compiled += [('MSBuildGenerate', '//upstream:' + row['label']) for row in generated]
    command = 'test' if a.test else 'build'
    if a.reuse_compilation_from:
        # Populate the local compilation cache first. Disabling remote cache
        # reads on the following test invocation then reruns tests without
        # suppressing publication of their successful results.
        f.run('compilation-recovery', targets, [], tests=[], command='build')
    f.run('remote-slice', targets, [] if a.reuse_compilation_from else compiled, cold=True, tests=sorted('//upstream:' + name for name in a.test), command=command)
    for suite, raw in expected.items():
        actual = test_outcomes(workspace, suite)
        assert actual == raw, (suite, serialize(raw - actual), serialize(actual - raw))
    for row in generated:
        actual = workspace / 'bazel-bin/upstream' / (row['label'] + '.generated') / row['filename']
        assert actual.read_bytes() == (a.prepared / 'source' / row['output']).read_bytes(), row
    assemblies = assembly_parity(a.prepared, f.base, Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])) if not a.test else []
    f.run('noop', targets, [], tests=[], command=command, downloads='toplevel')
    manifest.write_text(json.dumps(dict(instance=instance,targets=targets,outcomes={suite:serialize(raw) for suite,raw in expected.items()}),indent=2)+'\n')
    summary = dict(configuredProjects=len(rows),compilationActions=len(configured),generationActions=len(generated),suites={suite:dict(Counter(outcome for (_,outcome),count in raw.items() for _ in range(count))) for suite,raw in expected.items()},rawAndRemoteNamesAndOutcomesEqual=True if expected else None,assemblies=assemblies)
    (f.folder / 'parity.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True)
finally:
    f.shutdown()
